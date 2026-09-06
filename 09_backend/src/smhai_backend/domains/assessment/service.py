"""Assessment lifecycle orchestration without CAT algorithm logic."""

from __future__ import annotations

from uuid import uuid4

from smhai_backend.core.async_utils import maybe_await
from smhai_backend.core.errors import ErrorCode, error
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
        record = await self._get(assessment_id)
        self.authorization.require(
            actor,
            "assessment:write",
            resource={"subject_id": record.subject_id, "owner_user_id": actor.user_id},
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
        record = await self._get(assessment_id)
        self.authorization.require(
            actor,
            "assessment:complete",
            resource={"subject_id": record.subject_id, "owner_user_id": actor.user_id},
        )
        if record.assessment["status"] not in {"created", "in_progress"}:
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="assessment is already complete")
        session = await self._cat_session(record, request_id=request_id, trace_id=trace_id)
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
        self, actor: Actor, assessment_id: str, *, action: str
    ) -> AssessmentRecord:
        record = await self._get(assessment_id)
        self.authorization.require(
            actor,
            action,
            resource={"subject_id": record.subject_id, "owner_user_id": actor.user_id},
        )
        return record

    async def state_for_actor(
        self, actor: Actor, assessment_id: str, *, action: str, request_id: str, trace_id: str
    ) -> AssessmentRecord:
        record = await self.get_for_actor(actor, assessment_id, action=action)
        if record.assessment.get("status") in {"created", "in_progress"}:
            session = await self._cat_session(record, request_id=request_id, trace_id=trace_id)
            self._apply_state(record, session)
        return record

    async def _get(self, assessment_id: str) -> AssessmentRecord:
        record = await maybe_await(self.repository.get(assessment_id))
        if record is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="assessment not found")
        return record

    async def _cat_session(
        self, record: AssessmentRecord, *, request_id: str, trace_id: str
    ) -> CatStart:
        session = self._sessions.get(record.assessment_id)
        if session is not None:
            return session
        session = CatStart(
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
        except AttributeError:
            pass
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
