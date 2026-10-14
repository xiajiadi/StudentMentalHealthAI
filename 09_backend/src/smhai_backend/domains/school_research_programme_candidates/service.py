"""Specialist-only review of encrypted staff programme research candidates."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import ValidationError

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.domains.support.service import _FORBIDDEN_GENERATED_CLAIMS

from .schemas import (
    CandidateAdoptRequest,
    CandidateDiscardRequest,
    GeneratedProgrammeCandidate,
    ProgrammeCandidateDetailDto,
    ProgrammeCandidateListDto,
    ProgrammeCandidateSummaryDto,
)


class SchoolResearchProgrammeCandidateService:
    """Keep staff-only adoption separate from student feedback publication."""

    def __init__(self, *, persistence) -> None:
        self.persistence = persistence

    def _port(self):
        if self.persistence is None:
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="research programme candidates are unavailable",
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
    def _request(model, values):
        try:
            return model.model_validate(values, strict=True)
        except ValidationError as exc:
            raise error(
                ErrorCode.VALIDATION_FAILED,
                detail="research programme candidate request is invalid",
            ) from exc

    @staticmethod
    def _project(model, value):
        if not isinstance(value, Mapping):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research programme candidate is unavailable",
            )
        try:
            return model.model_validate(dict(value), strict=True).model_dump(mode="python")
        except ValidationError as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research programme candidate is unavailable",
            ) from exc

    @classmethod
    def _summary(cls, value):
        projected = cls._project(ProgrammeCandidateSummaryDto, value)
        return projected

    @staticmethod
    def _pagination(offset: int, limit: int) -> None:
        if (
            type(offset) is not int
            or not 0 <= offset <= 100_000
            or type(limit) is not int
            or not 1 <= limit <= 50
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="pagination is invalid")

    async def list_for_task(self, actor: Actor, task_ref: str, *, offset=0, limit=20):
        self._require_specialist(actor)
        self._pagination(offset, limit)
        items = await self._port().school_research_programme_candidate_list(
            actor, task_ref, offset=offset, limit=limit
        )
        if not isinstance(items, list):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research programme candidate data is unavailable",
            )
        summary = [self._summary(item) for item in items]
        return ProgrammeCandidateListDto(items=summary).model_dump(mode="python")

    async def get(self, actor: Actor, task_ref: str, candidate_ref: str):
        self._require_specialist(actor)
        result = await self._port().school_research_programme_candidate_get(
            actor, task_ref, candidate_ref
        )
        return self._project(ProgrammeCandidateDetailDto, result)

    async def adopt(
        self,
        actor: Actor,
        task_ref: str,
        candidate_ref: str,
        *,
        expected_state_version: int,
        idempotency,
        trace_id: str,
    ):
        self._require_specialist(actor)
        request = self._request(
            CandidateAdoptRequest,
            {"expected_state_version": expected_state_version},
        )
        result = await self._port().school_research_programme_candidate_adopt(
            actor,
            task_ref,
            candidate_ref,
            expected_state_version=request.expected_state_version,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        return self._summary(result)

    async def discard(
        self,
        actor: Actor,
        task_ref: str,
        candidate_ref: str,
        *,
        expected_state_version: int,
        idempotency,
        trace_id: str,
    ):
        self._require_specialist(actor)
        request = self._request(
            CandidateDiscardRequest,
            {"expected_state_version": expected_state_version},
        )
        result = await self._port().school_research_programme_candidate_discard(
            actor,
            task_ref,
            candidate_ref,
            expected_state_version=request.expected_state_version,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        return self._summary(result)

    async def store_generated_candidate(self, generated: GeneratedProgrammeCandidate):
        """Internal processor seam; deliberately has no HTTP route."""
        if type(generated) is not GeneratedProgrammeCandidate:
            raise error(ErrorCode.VALIDATION_FAILED, detail="generated candidate is invalid")
        if _FORBIDDEN_GENERATED_CLAIMS.search(
            generated.content.title
        ) or _FORBIDDEN_GENERATED_CLAIMS.search(generated.content.body):
            raise error(ErrorCode.VALIDATION_FAILED, detail="candidate is outside this workflow")
        result = await self._port().store_generated_candidate(generated)
        return self._project(ProgrammeCandidateSummaryDto, result)
