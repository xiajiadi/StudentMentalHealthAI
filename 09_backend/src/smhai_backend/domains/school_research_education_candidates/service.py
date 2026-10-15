"""Task-scoped specialist access to held research education candidates."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import ValidationError

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.domains.research_general_education.schemas import (
    ResearchGeneralEducationCandidatePayload,
)

from .schemas import (
    ResearchEducationCandidateBatchDto,
    ResearchEducationCandidateBatchRequest,
    ResearchEducationCandidateDetailDto,
    ResearchEducationCandidateListDto,
    ResearchEducationCandidateResolutionRequest,
    ResearchEducationCandidateSummaryDto,
    ResearchEducationCandidateTaskListDto,
    ResearchEducationGenerationJobListDto,
)


class SchoolResearchEducationCandidateService:
    """Expose no candidate operation without the configured persistence port."""

    def __init__(self, *, persistence=None) -> None:
        self.persistence = persistence

    def _port(self):
        if self.persistence is None:
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="research education candidates are unavailable",
                retryable=True,
            )
        return self.persistence

    @staticmethod
    def _require_specialist(actor: Actor) -> None:
        if (
            not isinstance(actor, Actor)
            or actor.scope_profile != "school_tenant"
            or actor.role is not BackendRole.PSYCHOLOGICAL_SPECIALIST
            or type(actor.school_id) is not int
            or actor.school_id <= 0
            or type(actor.school_ref) is not str
            or not actor.school_ref
        ):
            raise error(ErrorCode.FORBIDDEN, detail="access denied")

    @staticmethod
    def _validate(model, values):
        try:
            return model.model_validate(values, strict=True)
        except (ValidationError, ValueError) as exc:
            raise error(
                ErrorCode.VALIDATION_FAILED,
                detail="research education candidate request is invalid",
            ) from exc

    @staticmethod
    def _project(model, value):
        if not isinstance(value, Mapping):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research education candidate is unavailable",
            )
        try:
            values = dict(value)
            if model is ResearchEducationCandidateDetailDto:
                payload_value = values.get("candidate_payload")
                if type(payload_value) is ResearchGeneralEducationCandidatePayload:
                    payload = payload_value
                else:
                    payload = ResearchGeneralEducationCandidatePayload.from_closed_mapping(
                        payload_value
                    )
                values["candidate_payload"] = payload
            return model.model_validate(values, strict=True).model_dump(mode="python")
        except (ValidationError, ValueError) as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research education candidate is unavailable",
            ) from exc

    @staticmethod
    def _pagination(offset: int, limit: int) -> None:
        if (
            type(offset) is not int
            or not 0 <= offset <= 100_000
            or type(limit) is not int
            or not 1 <= limit <= 50
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="pagination is invalid")

    async def list_tasks(self, actor: Actor):
        self._require_specialist(actor)
        result = await self._port().school_research_education_candidate_list_tasks(actor)
        return self._project(ResearchEducationCandidateTaskListDto, result)

    async def list_for_task(
        self, actor: Actor, task_ref: str, *, status="HELD", offset=0, limit=20
    ):
        self._require_specialist(actor)
        self._pagination(offset, limit)
        result = await self._port().school_research_education_candidate_list(
            actor, task_ref, status=status, offset=offset, limit=limit
        )
        return self._project(ResearchEducationCandidateListDto, result)

    async def list_jobs(self, actor: Actor, task_ref: str, *, offset=0, limit=20):
        self._require_specialist(actor)
        self._pagination(offset, limit)
        result = await self._port().school_research_education_candidate_generation_job_list(
            actor, task_ref, offset=offset, limit=limit
        )
        return self._project(ResearchEducationGenerationJobListDto, result)

    async def get(self, actor: Actor, task_ref: str, candidate_ref: str):
        self._require_specialist(actor)
        result = await self._port().school_research_education_candidate_get(
            actor, task_ref, candidate_ref
        )
        return self._project(ResearchEducationCandidateDetailDto, result)

    async def queue_batch(
        self,
        actor: Actor,
        task_ref: str,
        *,
        limit: int = 25,
        offset: int = 0,
        idempotency,
        trace_id: str,
    ):
        self._require_specialist(actor)
        request = self._validate(
            ResearchEducationCandidateBatchRequest,
            {"limit": limit, "offset": offset},
        )
        result = await self._port().school_research_education_candidate_queue_batch(
            actor,
            task_ref,
            limit=request.limit,
            offset=request.offset,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        return self._project(ResearchEducationCandidateBatchDto, result)

    async def resolve(
        self,
        actor: Actor,
        task_ref: str,
        candidate_ref: str,
        *,
        expected_state_version: int,
        target: str,
        idempotency,
        trace_id: str,
    ):
        self._require_specialist(actor)
        request = self._validate(
            ResearchEducationCandidateResolutionRequest,
            {"expected_state_version": expected_state_version, "target": target},
        )
        result = await self._port().school_research_education_candidate_resolve(
            actor,
            task_ref,
            candidate_ref,
            expected_state_version=request.expected_state_version,
            target=request.target,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        return self._project(ResearchEducationCandidateSummaryDto, result)
