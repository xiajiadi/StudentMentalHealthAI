"""Authorization and safe projection for task-specific professional reviews.

The persistence port is expected to re-resolve school membership, task scope,
assignment, enrollment and assessment inside the same unit of work as each read
or write. Every call therefore receives the complete server-derived Actor.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import ValidationError

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.domains.professional_reviews.schemas import (
    ProfessionalEligibleEnrollmentDto,
    ProfessionalEligibleEnrollmentListDto,
    ProfessionalReviewCaseDto,
    ProfessionalReviewCaseListDto,
    ProfessionalReviewTaskDto,
    ProfessionalSpecialistDto,
    ReviewCaseCreateRequest,
    ReviewCaseDecisionRequest,
    ReviewCaseOpenRequest,
    SpecialistAssignmentDto,
    SpecialistAssignmentRequest,
)


class SchoolProfessionalReviewService:
    """Task review orchestration; approval is workflow state, never publication."""

    def __init__(self, *, persistence) -> None:
        self.persistence = persistence

    @staticmethod
    def _require_school_actor(actor: Actor, role: BackendRole) -> None:
        if (
            actor.scope_profile != "school_tenant"
            or actor.role is not role
            or actor.school_id is None
            or actor.school_id <= 0
            or not actor.school_ref
        ):
            raise error(ErrorCode.FORBIDDEN, detail="access denied")

    @classmethod
    def _require_admin(cls, actor: Actor) -> None:
        cls._require_school_actor(actor, BackendRole.ADMIN)

    @classmethod
    def _require_specialist(cls, actor: Actor) -> None:
        cls._require_school_actor(actor, BackendRole.PSYCHOLOGICAL_SPECIALIST)

    @staticmethod
    def _validate_projection(dto_type, row: Mapping[str, Any]):
        if not isinstance(row, Mapping):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="professional review data is unavailable",
            )
        try:
            # DTOs forbid unknown keys to fail closed if persistence attempts to
            # send report text, raw responses, ciphertext, or unrelated records.
            return dto_type.model_validate(dict(row), strict=True)
        except ValidationError as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="professional review data is unavailable",
            ) from exc

    @classmethod
    def _project(cls, dto_type, row: Mapping[str, Any]):
        return cls._validate_projection(dto_type, row).model_dump(mode="python")

    @classmethod
    def _project_many(cls, dto_type, rows):
        if not isinstance(rows, list):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="professional review data is unavailable",
            )
        return [cls._project(dto_type, row) for row in rows]

    async def list_assignments(self, actor: Actor, *, task_ref: str | None = None):
        self._require_admin(actor)
        rows = await self.persistence.school_professional_review_list_assignments(
            actor, task_ref=task_ref
        )
        return self._project_many(SpecialistAssignmentDto, rows)

    async def list_specialists(self, actor: Actor):
        self._require_admin(actor)
        rows = await self.persistence.school_professional_review_list_specialists(actor)
        return self._project_many(ProfessionalSpecialistDto, rows)

    async def assign(
        self,
        actor: Actor,
        task_ref: str,
        specialist_user_id: str,
        *,
        idempotency,
        trace_id: str,
    ):
        self._require_admin(actor)
        request = SpecialistAssignmentRequest(specialist_user_id=specialist_user_id)
        row = await self.persistence.school_professional_review_assign(
            actor,
            task_ref,
            request.specialist_user_id,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        return self._project(SpecialistAssignmentDto, row)

    async def revoke(
        self,
        actor: Actor,
        task_ref: str,
        assignment_ref: str,
        *,
        idempotency,
        trace_id: str,
    ):
        self._require_admin(actor)
        row = await self.persistence.school_professional_review_revoke(
            actor,
            task_ref,
            assignment_ref,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        return self._project(SpecialistAssignmentDto, row)

    async def list_cases(self, actor: Actor, task_ref: str, *, offset: int = 0, limit: int = 50):
        self._require_specialist(actor)
        if (
            type(offset) is not int
            or not 0 <= offset <= 100000
            or type(limit) is not int
            or not 1 <= limit <= 50
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="pagination is invalid")
        result = await self.persistence.school_professional_review_list_cases(
            actor, task_ref, offset=offset, limit=limit
        )
        if not isinstance(result, Mapping) or set(result) != {"items", "total"}:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="professional review data is unavailable",
            )
        total = result["total"]
        if type(total) is not int or total < 0:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="professional review data is unavailable",
            )
        rows = result["items"]
        if not isinstance(rows, list) or len(rows) > limit or len(rows) > total:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="professional review data is unavailable",
            )
        items = [self._validate_projection(ProfessionalReviewCaseDto, row) for row in rows]
        return ProfessionalReviewCaseListDto(items=items, total=total).model_dump(mode="python")

    async def get_case(self, actor: Actor, task_ref: str, case_ref: str):
        self._require_specialist(actor)
        row = await self.persistence.school_professional_review_get_case(actor, task_ref, case_ref)
        return self._project(ProfessionalReviewCaseDto, row)

    async def list_tasks(self, actor: Actor):
        self._require_specialist(actor)
        rows = await self.persistence.school_professional_review_list_tasks(actor)
        return self._project_many(ProfessionalReviewTaskDto, rows)

    async def list_eligible_enrollments(
        self, actor: Actor, task_ref: str, *, offset: int, limit: int
    ):
        self._require_specialist(actor)
        if (
            type(offset) is not int
            or not 0 <= offset <= 100000
            or type(limit) is not int
            or not 1 <= limit <= 50
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="pagination is invalid")
        result = await self.persistence.school_professional_review_list_eligible_enrollments(
            actor,
            task_ref,
            offset=offset,
            limit=limit,
        )
        if (
            not isinstance(result, Mapping)
            or set(result) != {"items", "total"}
            or type(result["total"]) is not int
            or result["total"] < 0
            or not isinstance(result["items"], list)
            or len(result["items"]) > limit
            or len(result["items"]) > result["total"]
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="professional review data is unavailable",
            )
        items = [
            self._validate_projection(ProfessionalEligibleEnrollmentDto, row)
            for row in result["items"]
        ]
        return ProfessionalEligibleEnrollmentListDto(items=items, total=result["total"]).model_dump(
            mode="python"
        )

    async def ensure_case(
        self,
        actor: Actor,
        task_ref: str,
        enrollment_ref: str,
        *,
        idempotency,
        trace_id: str,
    ):
        """Idempotently create/retrieve the task-bound case for one enrollment."""
        self._require_specialist(actor)
        request = ReviewCaseCreateRequest(enrollment_ref=enrollment_ref)
        row = await self.persistence.school_professional_review_ensure_case(
            actor,
            task_ref,
            request.enrollment_ref,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        return self._project(ProfessionalReviewCaseDto, row)

    async def open_case(
        self,
        actor: Actor,
        task_ref: str,
        case_ref: str,
        *,
        expected_version: int,
        idempotency,
        trace_id: str,
    ):
        self._require_specialist(actor)
        request = ReviewCaseOpenRequest(expected_version=expected_version)
        row = await self.persistence.school_professional_review_open_case(
            actor,
            task_ref,
            case_ref,
            expected_version=request.expected_version,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        return self._project(ProfessionalReviewCaseDto, row)

    async def process_case(
        self,
        actor: Actor,
        task_ref: str,
        case_ref: str,
        *,
        expected_version: int,
        decision: Literal["APPROVED", "REJECTED"],
        note: str,
        idempotency,
        trace_id: str,
    ):
        self._require_specialist(actor)
        request = ReviewCaseDecisionRequest(
            expected_version=expected_version, decision=decision, note=note
        )
        row = await self.persistence.school_professional_review_process_case(
            actor,
            task_ref,
            case_ref,
            expected_version=request.expected_version,
            decision=request.decision,
            note=request.note,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        return self._project(ProfessionalReviewCaseDto, row)
