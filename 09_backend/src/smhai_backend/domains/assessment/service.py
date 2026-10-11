"""Assessment lifecycle orchestration without CAT algorithm logic."""

from __future__ import annotations

from uuid import uuid4

from smhai_backend.core.async_utils import maybe_await
from smhai_backend.core.errors import BackendError, ErrorCode, error
from smhai_backend.domains.audit import AuditService
from smhai_backend.domains.authorization import NativeAuthorizationProvider
from smhai_backend.domains.models import Actor, AssessmentRecord
from smhai_backend.domains.ports import AssessmentRepository
from smhai_backend.integrations.cat import CatClient, CatStart

from .schemas import AssessmentStartRequest, ResponseEvent


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
        await maybe_await(self.repository.save(record))
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
        record.responses[payload.item_id] = payload.response
        record.assessment["status"] = "in_progress"
        record.assessment["response_summary"]["items_answered"] = len(record.responses)
        dimensions = record.assessment.get("dimensions", {})
        if dimensions:
            first_dimension = next(iter(dimensions.values()))
            if isinstance(first_dimension, dict):
                first_dimension["items_answered"] = len(record.responses)
        self._apply_state(record, session)
        await maybe_await(self.repository.save(record))
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
        record.assessment = result
        record.current_item = None
        record.selected_item_id = None
        record.can_complete = False
        await maybe_await(self.repository.save(record))
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
            if self.authorization.can(
                actor, "assessment:read", resource={"subject_id": subject_id}
            )
        }
        if limit is None and skip == 0 and status is None:
            records = self.repository.list_assessments_for_subjects(
                allowed_subject_ids
            )
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
            self._apply_state(record, session)
        return record

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
        session = self._sessions.get(record.assessment_id) or CatStart(
            assessment_id=record.assessment_id,
            subject_id=record.subject_id,
            instrument_id=str(
                record.assessment.get("instrument", {}).get("instrument_id", "instrument.synthetic")
            ),
            instrument_version=str(record.assessment.get("instrument", {}).get("version", "1.0")),
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
        )
        try:
            session = await self.cat.state(session, request_id=request_id, trace_id=trace_id)
        except BackendError as exc:
            if exc.code is not ErrorCode.RESOURCE_NOT_FOUND:
                raise
            # CAT owns process-local provider state. Recreate it from the
            # encrypted response history persisted by the Backend repository.
            session = await self.cat.start(
                assessment_id=record.assessment_id,
                subject_id=record.subject_id,
                instrument_id=session.instrument_id,
                instrument_version=session.instrument_version,
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
                session = await self.cat.state(
                    session, request_id=request_id, trace_id=trace_id
                )
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
