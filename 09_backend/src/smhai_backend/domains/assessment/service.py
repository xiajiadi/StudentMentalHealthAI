"""Assessment lifecycle orchestration without CAT algorithm logic."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from smhai_backend.core.async_utils import maybe_await
from smhai_backend.core.errors import BackendError, ErrorCode, error
from smhai_backend.domains.audit import AuditService
from smhai_backend.domains.authorization import NativeAuthorizationProvider
from smhai_backend.domains.models import Actor, AssessmentRecord
from smhai_backend.domains.ports import AssessmentRepository
from smhai_backend.integrations.cat import CatClient, CatStart

from .schemas import AssessmentStartRequest, ResponseEvent


def _same_json_value(left: Any, right: Any) -> bool:
    """Compare JSON values recursively without Python's bool/int coercion."""

    if type(left) is not type(right):
        return False
    if left is None:
        return True
    if type(left) in {str, bool, int}:
        return left == right
    if type(left) is float:
        return math.isfinite(left) and math.isfinite(right) and left == right
    if type(left) is list:
        return len(left) == len(right) and all(
            _same_json_value(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    if type(left) is dict:
        return (
            all(type(key) is str for key in left)
            and all(type(key) is str for key in right)
            and left.keys() == right.keys()
            and all(_same_json_value(left[key], right[key]) for key in left)
        )
    return False


def _same_response_history(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return left.keys() == right.keys() and all(
        _same_json_value(left[item_id], right[item_id]) for item_id in left
    )


def _is_commit_outcome_uncertain(exc: Exception) -> bool:
    """Recognize domain, transport, and SQLAlchemy persistence failures only."""

    if isinstance(exc, (BackendError, OSError)):
        return True
    return any(
        base.__name__ == "SQLAlchemyError" and base.__module__.startswith("sqlalchemy.")
        for base in type(exc).__mro__
    )


class AssessmentService:
    def __init__(
        self,
        *,
        repository: AssessmentRepository,
        cat: CatClient,
        authorization: NativeAuthorizationProvider,
        audit: AuditService,
    ) -> None:
        self.repository = repository
        self.cat = cat
        self.authorization = authorization
        self.audit = audit
        self._sessions: dict[str, CatStart] = {}

    async def create(
        self, actor: Actor, payload: AssessmentStartRequest, *, request_id: str, trace_id: str
    ) -> AssessmentRecord:
        if actor.scope_profile == "school_tenant":
            raise error(ErrorCode.FORBIDDEN, detail="direct school assessment start is unavailable")
        self.authorization.require(
            actor, "assessment:create", resource={"subject_id": payload.subject_id}
        )
        assessment_id = f"ASSESS_{uuid4().hex}"
        session = await self.cat.start(
            assessment_id=assessment_id,
            subject_id=payload.subject_id,
            instrument_id=payload.instrument_id,
            instrument_version=payload.instrument_version,
            request_id=request_id,
            trace_id=trace_id,
        )
        assessment = {
            "schema_version": "assessment.v1",
            "assessment_id": assessment_id,
            "subject_id": payload.subject_id,
            "instrument": {
                "instrument_id": payload.instrument_id,
                "version": payload.instrument_version,
            },
            "population_scope": "synthetic_demo",
            "status": "created",
            "dimensions": {
                "wellbeing": {
                    "theta": None,
                    "se": None,
                    "score": None,
                    "band": "unknown",
                    "interpretation_status": "insufficient_data",
                    "items_answered": 0,
                }
            },
            "risk": {
                "level": "normal",
                "need_human_review": False,
                "reason_codes": ["ASSESSMENT_NOT_COMPLETED"],
                "ruleset_id": "RULESET_backend_contract_fake",
            },
            "response_summary": {"items_answered": 0, "duration_seconds": None},
            "provenance": {
                "source_adapter": (
                    "backend-real-http-cat"
                    if getattr(self.cat, "label", "CONTRACT_FAKE") == "REAL_HTTP"
                    else "backend-contract-fake-cat"
                ),
                "adapter_version": "1.0",
                "cat_engine_version": session.provider_version or "CONTRACT_FAKE",
                "item_bank_version": session.item_bank_version or "ITEMBANK_synthetic_v1",
            },
            "timestamps": {"started_at": session.started_at, "completed_at": None},
        }
        record = AssessmentRecord(
            assessment_id,
            payload.subject_id,
            assessment,
            selected_item_id=session.current_item.get("item_id") if session.current_item else None,
            current_item=session.current_item,
            current_index=session.current_index,
            answered_count=session.answered_count,
            administered_count=session.administered_count,
            can_complete=session.can_complete,
            max_items=session.max_items,
            cat_provider_version=session.provider_version,
            cat_item_bank_version=session.item_bank_version,
            cat_config_version=session.config_version,
        )
        self._sessions[assessment_id] = session
        await self._save_for_actor(actor, record, trace_id=trace_id)
        await maybe_await(
            self.audit.record(
                event="ASSESSMENT_STARTED",
                actor=actor,
                request_id=request_id,
                trace_id=trace_id,
                outcome="accepted",
                metadata={"assessment_id": assessment_id, "synthetic_fixture_only": True},
            )
        )
        return record

    async def submit(
        self,
        actor: Actor,
        assessment_id: str,
        payload: ResponseEvent,
        *,
        request_id: str,
        trace_id: str,
    ) -> AssessmentRecord:
        record = await self._get_for_actor(
            actor,
            assessment_id,
            action="assessment:write",
            request_id=request_id,
            trace_id=trace_id,
        )
        if record.assessment["status"] not in {"created", "in_progress"}:
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="assessment is not accepting responses")
        if payload.item_id in record.responses:
            if not _same_json_value(record.responses[payload.item_id], payload.response):
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT,
                    detail="assessment response does not match persisted history",
                )
            prior_responses = record.responses.copy()
            session = await self._cat_session(record, request_id=request_id, trace_id=trace_id)
            if session.administered_count != len(record.responses):
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT,
                    detail="CAT state does not match persisted response history",
                )
            record = await self._fresh_authorized_record(
                actor, record, action="assessment:write", request_id=request_id, trace_id=trace_id
            )
            if (
                record.assessment["status"] not in {"created", "in_progress"}
                or not _same_response_history(record.responses, prior_responses)
                or payload.item_id not in record.responses
                or not _same_json_value(record.responses[payload.item_id], payload.response)
                or session.administered_count != len(record.responses)
            ):
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT,
                    detail="assessment response history changed",
                )
            self._apply_state(record, session)
            return record
        session = await self._cat_session(record, request_id=request_id, trace_id=trace_id)
        await self.cat.submit_response(
            session,
            item_id=payload.item_id,
            response=payload.response,
            request_id=request_id,
            trace_id=trace_id,
        )
        session = await self.cat.state(session, request_id=request_id, trace_id=trace_id)
        self._sessions[assessment_id] = session
        record = await self._fresh_authorized_record(
            actor, record, action="assessment:write", request_id=request_id, trace_id=trace_id
        )
        record.responses[payload.item_id] = payload.response
        record.assessment["status"] = "in_progress"
        record.assessment["response_summary"]["items_answered"] = len(record.responses)
        dimensions = record.assessment.get("dimensions", {})
        if dimensions:
            first_dimension = next(iter(dimensions.values()))
            if isinstance(first_dimension, dict):
                first_dimension["items_answered"] = len(record.responses)
        self._apply_state(record, session)
        try:
            await self._save_for_actor(actor, record, trace_id=trace_id)
        except Exception as save_error:
            if not _is_commit_outcome_uncertain(save_error):
                raise
            if actor.scope_profile == "school_tenant":
                try:
                    persisted = await self._get_for_actor(
                        actor,
                        assessment_id,
                        "assessment:write",
                        request_id=request_id,
                        trace_id=trace_id,
                    )
                except Exception:
                    raise save_error from None
                if (
                    persisted.assessment["status"] in {"created", "in_progress"}
                    and persisted.subject_id == record.subject_id
                    and persisted.task_enrollment_id == record.task_enrollment_id
                    and persisted.cat_binding_mode == record.cat_binding_mode
                    and persisted.saved_binding == record.saved_binding
                    and persisted.saved_bank_document == record.saved_bank_document
                    and persisted.saved_config_document == record.saved_config_document
                    and payload.item_id in persisted.responses
                    and _same_json_value(
                        persisted.responses[payload.item_id], payload.response
                    )
                    and session.administered_count == len(persisted.responses)
                ):
                    self._apply_state(persisted, session)
                    record = persisted
                else:
                    raise save_error
            else:
                raise
        await maybe_await(
            self.audit.record(
                event="ASSESSMENT_RESPONSE_ACCEPTED",
                actor=actor,
                request_id=request_id,
                trace_id=trace_id,
                outcome="accepted",
                metadata={"assessment_id": assessment_id, "item_id": payload.item_id},
            )
        )
        return record

    async def complete(
        self,
        actor: Actor,
        assessment_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> AssessmentRecord:
        record = await self._get_for_actor(
            actor,
            assessment_id,
            action="assessment:complete",
            request_id=request_id,
            trace_id=trace_id,
        )
        if record.assessment["status"] not in {"created", "in_progress"}:
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="assessment is already complete")
        session = await self._cat_session(record, request_id=request_id, trace_id=trace_id)
        if getattr(self.cat, "label", "") == "REAL_HTTP" and not session.can_complete:
            raise error(
                ErrorCode.WORKFLOW_CONFLICT,
                detail="assessment has not reached its configured stopping condition",
            )
        result = await self.cat.complete(
            session,
            responses=record.responses,
            request_id=request_id,
            trace_id=trace_id,
        )
        record = await self._fresh_authorized_record(
            actor, record, action="assessment:complete", request_id=request_id, trace_id=trace_id
        )
        record.assessment = result
        record.current_item = None
        record.selected_item_id = None
        record.can_complete = False
        await self._save_for_actor(actor, record, trace_id=trace_id)
        await maybe_await(
            self.audit.record(
                event="ASSESSMENT_COMPLETED",
                actor=actor,
                request_id=request_id,
                trace_id=trace_id,
                outcome="accepted",
                metadata={"assessment_id": assessment_id, "items_answered": len(record.responses)},
            )
        )
        return record

    async def get_for_actor(
        self,
        actor: Actor,
        assessment_id: str,
        *,
        action: str,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> AssessmentRecord:
        return await self._get_for_actor(
            actor,
            assessment_id,
            action,
            request_id=request_id,
            trace_id=trace_id,
        )

    async def list_for_actor(
        self,
        actor: Actor,
        *,
        limit: int | None = None,
        skip: int = 0,
        status: str | None = None,
    ) -> list[AssessmentRecord]:
        """List assessments only for subjects the authenticated actor can read."""

        subject_ids = set(actor.accessible_subject_ids)
        if actor.subject_id:
            subject_ids.add(actor.subject_id)
        allowed_subject_ids = {
            subject_id
            for subject_id in subject_ids
            if self.authorization.can(actor, "assessment:read", resource={"subject_id": subject_id})
        }
        school_list = getattr(self.repository, "school_list_assessments_for_actor", None)
        if actor.scope_profile == "school_tenant" and school_list is not None:
            records = school_list(
                actor,
                allowed_subject_ids,
                limit=limit,
                skip=skip,
                status=status,
            )
        elif limit is None and skip == 0 and status is None:
            records = self.repository.list_assessments_for_subjects(allowed_subject_ids)
        else:
            records = self.repository.list_assessments_for_subjects(
                allowed_subject_ids,
                limit=limit,
                skip=skip,
                status=status,
            )
        return await maybe_await(records)

    async def state_for_actor(
        self, actor: Actor, assessment_id: str, *, action: str, request_id: str, trace_id: str
    ) -> AssessmentRecord:
        record = await self.get_for_actor(
            actor,
            assessment_id,
            action=action,
            request_id=request_id,
            trace_id=trace_id,
        )
        if record.assessment.get("status") in {"created", "in_progress"}:
            session = await self._cat_session(record, request_id=request_id, trace_id=trace_id)
            record = await self._fresh_authorized_record(
                actor, record, action=action, request_id=request_id, trace_id=trace_id
            )
            self._apply_state(record, session)
        return record

    async def _fresh_authorized_record(
        self,
        actor: Actor,
        original: AssessmentRecord,
        *,
        action: str,
        request_id: str,
        trace_id: str,
    ) -> AssessmentRecord:
        fresh = await self._get_for_actor(
            actor,
            original.assessment_id,
            action,
            request_id=request_id,
            trace_id=trace_id,
        )
        if (
            fresh.subject_id != original.subject_id
            or fresh.task_enrollment_id != original.task_enrollment_id
            or fresh.cat_binding_mode != original.cat_binding_mode
            or fresh.saved_binding != original.saved_binding
            or fresh.saved_bank_document != original.saved_bank_document
            or fresh.saved_config_document != original.saved_config_document
        ):
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="assessment session binding changed")
        return fresh

    async def _save_for_actor(
        self, actor: Actor, record: AssessmentRecord, *, trace_id: str
    ) -> None:
        if actor.scope_profile == "school_tenant":
            writer = getattr(self.repository, "school_save_assessment_for_actor", None)
            if writer is None:
                raise error(ErrorCode.FORBIDDEN, detail="assessment access is unavailable")
            await maybe_await(
                writer(
                    actor,
                    record,
                    at=datetime.now(UTC).replace(tzinfo=None),
                    trace_id=trace_id,
                )
            )
            return
        await maybe_await(self.repository.save(record))

    async def _get(self, assessment_id: str) -> AssessmentRecord:
        record = await maybe_await(self.repository.get(assessment_id))
        if record is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="assessment not found")
        return record

    async def _get_for_actor(
        self,
        actor: Actor,
        assessment_id: str,
        action: str,
        *,
        request_id: str | None,
        trace_id: str | None,
    ) -> AssessmentRecord:
        """Look up and authorize an assessment behind one public envelope.

        The service keeps the internal reason in the audit stream while both
        unknown and unauthorized identifiers use the same public 404 problem.
        This seam is deliberately assessment-scoped; the global authorization
        provider continues to expose its normal 403 behavior elsewhere.
        """

        school_reader = getattr(self.repository, "school_get_assessment_for_actor", None)
        if actor.scope_profile == "school_tenant" and school_reader is not None:
            record = await maybe_await(
                school_reader(
                    actor,
                    assessment_id,
                    at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
        else:
            record = await maybe_await(self.repository.get(assessment_id))
        if record is None:
            await self._record_lookup_denial(
                actor,
                request_id=request_id,
                trace_id=trace_id,
                reason_code="ASSESSMENT_NOT_FOUND",
            )
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="assessment not found")
        try:
            self.authorization.require(
                actor,
                action,
                resource={"subject_id": record.subject_id, "owner_user_id": actor.user_id},
            )
        except BackendError as exc:
            if exc.code is not ErrorCode.FORBIDDEN:
                raise
            await self._record_lookup_denial(
                actor,
                request_id=request_id,
                trace_id=trace_id,
                reason_code="ASSESSMENT_ACCESS_DENIED",
            )
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="assessment not found") from exc
        return record

    async def _record_lookup_denial(
        self,
        actor: Actor,
        *,
        request_id: str | None,
        trace_id: str | None,
        reason_code: str,
    ) -> None:
        await maybe_await(
            self.audit.record(
                event="ASSESSMENT_LOOKUP",
                actor=actor,
                request_id=request_id or "REQ_internal",
                trace_id=trace_id or "TRACE_internal",
                outcome="denied",
                metadata={"reason_code": reason_code},
            )
        )

    async def _cat_session(
        self, record: AssessmentRecord, *, request_id: str, trace_id: str
    ) -> CatStart:
        instrument = record.assessment.get("instrument", {})
        instrument_id = str(instrument.get("instrument_id", "instrument.synthetic"))
        instrument_version = str(instrument.get("version", "1.0"))
        if record.task_enrollment_id is not None:
            from smhai_backend.domains.assessment.binding import D3_IDENTITY

            if record.cat_binding_mode == "FIXTURE" and (
                instrument_id != D3_IDENTITY.instrument_id
                or instrument_version != D3_IDENTITY.instrument_version
            ):
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT,
                    detail="fixture task CAT identity is unsupported",
                )
        saved_binding = None
        if record.cat_binding_mode == "SAVED_VERSION":
            expected_binding_keys = {
                "binding_ref", "activation_ref", "plan_version_ref", "bank_version_ref"
            }
            bank_document = record.saved_bank_document
            config_document = record.saved_config_document
            metadata = bank_document.get("metadata") if isinstance(bank_document, dict) else None
            if isinstance(metadata, Mapping):
                saved_instrument_version = metadata.get(
                    "instrument_version", bank_document.get("version")
                )
            elif isinstance(bank_document, dict):
                saved_instrument_version = bank_document.get("version")
            else:
                saved_instrument_version = None
            if (
                not isinstance(record.saved_binding, dict)
                or set(record.saved_binding) != expected_binding_keys
                or not isinstance(bank_document, dict)
                or not isinstance(config_document, dict)
                or bank_document.get("instrument_id") != instrument_id
                or saved_instrument_version != instrument_version
                or record.cat_item_bank_version != bank_document.get("version")
                or record.cat_config_version != config_document.get("config_version")
            ):
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT,
                    detail="saved CAT session binding is unavailable",
                )
            saved_binding = dict(record.saved_binding)
        elif record.cat_binding_mode != "FIXTURE":
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="CAT binding mode is invalid")

        expected_session = CatStart(
            assessment_id=record.assessment_id,
            subject_id=record.subject_id,
            instrument_id=instrument_id,
            instrument_version=instrument_version,
            started_at=str(record.assessment.get("timestamps", {}).get("started_at") or ""),
            current_item=record.current_item,
            current_index=record.current_index,
            answered_count=record.answered_count,
            administered_count=record.administered_count,
            can_complete=record.can_complete,
            max_items=record.max_items,
            item_bank_version=record.cat_item_bank_version,
            config_version=record.cat_config_version,
            provider_version=record.cat_provider_version,
            cat_binding_mode=record.cat_binding_mode,
            saved_binding=saved_binding,
        )
        cached = self._sessions.get(record.assessment_id)
        if cached is not None and (
            cached.subject_id != expected_session.subject_id
            or cached.instrument_id != expected_session.instrument_id
            or cached.instrument_version != expected_session.instrument_version
            or cached.cat_binding_mode != expected_session.cat_binding_mode
            or cached.saved_binding != expected_session.saved_binding
        ):
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="CAT session binding changed")
        session = cached or expected_session
        try:
            session = await self.cat.state(session, request_id=request_id, trace_id=trace_id)
        except BackendError as exc:
            if exc.code is not ErrorCode.RESOURCE_NOT_FOUND:
                raise
            # CAT owns process-local provider state. Recreate it from the
            # encrypted response history persisted by the Backend repository.
            if record.cat_binding_mode == "SAVED_VERSION":
                start_saved = getattr(self.cat, "start_saved_session", None)
                if start_saved is None:
                    raise error(
                        ErrorCode.DEPENDENCY_UNAVAILABLE,
                        detail="saved CAT session start is unavailable",
                    ) from exc
                session = await start_saved(
                    assessment_id=record.assessment_id,
                    subject_id=record.subject_id,
                    instrument_id=instrument_id,
                    instrument_version=instrument_version,
                    binding=saved_binding,
                    bank_document=record.saved_bank_document,
                    config_document=record.saved_config_document,
                    request_id=request_id,
                    trace_id=trace_id,
                )
            else:
                session = await self.cat.start(
                    assessment_id=record.assessment_id,
                    subject_id=record.subject_id,
                    instrument_id=instrument_id,
                    instrument_version=instrument_version,
                    request_id=request_id,
                    trace_id=trace_id,
                )
            for item_id, response in record.responses.items():
                if (session.current_item or {}).get("item_id") != item_id:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT,
                        detail=(
                            "persisted CAT response history does not match "
                            "the published item sequence"
                        ),
                    ) from exc
                await self.cat.submit_response(
                    session,
                    item_id=item_id,
                    response=response,
                    request_id=request_id,
                    trace_id=trace_id,
                )
                session = await self.cat.state(session, request_id=request_id, trace_id=trace_id)
        self._sessions[record.assessment_id] = session
        return session

    @staticmethod
    def _apply_state(record: AssessmentRecord, session: CatStart) -> None:
        record.selected_item_id = (
            session.current_item.get("item_id") if session.current_item else None
        )
        record.current_item = session.current_item
        record.current_index = session.current_index
        record.answered_count = session.answered_count
        record.administered_count = session.administered_count
        record.can_complete = session.can_complete
        record.max_items = session.max_items
        record.cat_provider_version = session.provider_version or record.cat_provider_version
        record.cat_item_bank_version = session.item_bank_version or record.cat_item_bank_version
        record.cat_config_version = session.config_version or record.cat_config_version
