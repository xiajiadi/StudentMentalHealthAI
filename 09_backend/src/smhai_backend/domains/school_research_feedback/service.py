"""Authorization and safe projections for research-only educational feedback."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import ValidationError

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.domains.support.service import _FORBIDDEN_GENERATED_CLAIMS

from .schemas import (
    ResearchCaseCreateRequest,
    ResearchCaseDecisionRequest,
    ResearchEligibleSessionDto,
    ResearchEligibleSessionListDto,
    ResearchFeedbackDraftRequest,
    ResearchFeedbackDto,
    ResearchFeedbackListDto,
    ResearchFeedbackPublishRequest,
    ResearchFeedbackRevokeRequest,
    ResearchReviewCaseDto,
    ResearchReviewCaseListDto,
    ResearchReviewTaskDto,
    StudentResearchFeedbackDto,
    StudentResearchFeedbackListDto,
)


class SchoolResearchFeedbackService:
    """Keep review state, student release, and global publication authority apart."""

    def __init__(self, *, persistence) -> None:
        self.persistence = persistence

    def _port(self):
        if self.persistence is None:
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="research feedback is unavailable",
                retryable=True,
            )
        return self.persistence

    @staticmethod
    def _require_role(actor: Actor, role: BackendRole) -> None:
        if (
            not isinstance(actor, Actor)
            or actor.scope_profile != "school_tenant"
            or actor.role is not role
            or type(actor.school_id) is not int
            or actor.school_id <= 0
            or type(actor.school_ref) is not str
            or not actor.school_ref
        ):
            raise error(ErrorCode.FORBIDDEN, detail="access denied")

    @classmethod
    def _require_specialist(cls, actor: Actor) -> None:
        cls._require_role(actor, BackendRole.PSYCHOLOGICAL_SPECIALIST)

    @classmethod
    def _require_student(cls, actor: Actor) -> None:
        cls._require_role(actor, BackendRole.STUDENT)

    @staticmethod
    def _request(dto_type, values):
        try:
            return dto_type.model_validate(values, strict=True)
        except ValidationError as exc:
            raise error(
                ErrorCode.VALIDATION_FAILED,
                detail="research feedback request is invalid",
            ) from exc

    @staticmethod
    def _project(dto_type, row):
        if not isinstance(row, Mapping):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research feedback data is unavailable",
            )
        try:
            return dto_type.model_validate(dict(row), strict=True).model_dump(mode="python")
        except ValidationError as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research feedback data is unavailable",
            ) from exc

    @classmethod
    def _project_list(cls, dto_type, item_dto, result, *, limit: int | None = None):
        if (
            not isinstance(result, Mapping)
            or set(result) != {"items", "total"}
            or type(result["total"]) is not int
            or result["total"] < 0
            or not isinstance(result["items"], list)
            or len(result["items"]) > result["total"]
            or (limit is not None and len(result["items"]) > limit)
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research feedback data is unavailable",
            )
        items = [cls._project(item_dto, row) for row in result["items"]]
        try:
            return dto_type(items=items, total=result["total"]).model_dump(mode="python")
        except ValidationError as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research feedback data is unavailable",
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
        rows = await self._port().school_research_feedback_list_tasks(actor)
        if not isinstance(rows, list):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research feedback data is unavailable",
            )
        return [self._project(ResearchReviewTaskDto, row) for row in rows]

    async def list_eligible_sessions(
        self, actor: Actor, task_ref: str, *, offset: int = 0, limit: int = 20
    ):
        self._require_specialist(actor)
        self._pagination(offset, limit)
        result = await self._port().school_research_feedback_list_eligible_sessions(
            actor, task_ref, offset=offset, limit=limit
        )
        return self._project_list(
            ResearchEligibleSessionListDto,
            ResearchEligibleSessionDto,
            result,
            limit=limit,
        )

    async def list_cases(
        self,
        actor: Actor,
        task_ref: str,
        *,
        status: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ):
        self._require_specialist(actor)
        self._pagination(offset, limit)
        if status is not None and status not in {"OPEN", "IN_REVIEW", "APPROVED", "REJECTED"}:
            raise error(ErrorCode.VALIDATION_FAILED, detail="review status is invalid")
        result = await self._port().school_research_feedback_list_cases(
            actor, task_ref, status=status, offset=offset, limit=limit
        )
        return self._project_list(
            ResearchReviewCaseListDto, ResearchReviewCaseDto, result, limit=limit
        )

    async def get_case(self, actor: Actor, task_ref: str, case_ref: str):
        self._require_specialist(actor)
        row = await self._port().school_research_feedback_get_case(actor, task_ref, case_ref)
        return self._project(ResearchReviewCaseDto, row)

    async def create_case(
        self, actor: Actor, task_ref: str, *, session_ref: str, idempotency, trace_id: str
    ):
        self._require_specialist(actor)
        request = self._request(ResearchCaseCreateRequest, {"session_ref": session_ref})
        row = await self._port().school_research_feedback_create_case(
            actor,
            task_ref,
            request.session_ref,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        return self._project(ResearchReviewCaseDto, row)

    async def transition_case(
        self,
        actor: Actor,
        task_ref: str,
        case_ref: str,
        *,
        expected_version: int,
        status: str,
        note: str,
        idempotency,
        trace_id: str,
    ):
        self._require_specialist(actor)
        request = self._request(
            ResearchCaseDecisionRequest,
            {"expected_version": expected_version, "status": status, "note": note},
        )
        if _FORBIDDEN_GENERATED_CLAIMS.search(request.note):
            raise error(ErrorCode.VALIDATION_FAILED, detail="review note is outside this workflow")
        row = await self._port().school_research_feedback_transition_case(
            actor,
            task_ref,
            case_ref,
            expected_version=request.expected_version,
            status=request.status,
            note=request.note,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        return self._project(ResearchReviewCaseDto, row)

    async def create_draft(
        self,
        actor: Actor,
        case_ref: str,
        *,
        expected_case_version: int,
        title: str,
        body: str,
        candidate_ref: str | None = None,
        idempotency,
        trace_id: str,
    ):
        self._require_specialist(actor)
        request = self._request(
            ResearchFeedbackDraftRequest,
            {
                "expected_case_version": expected_case_version,
                "title": title,
                "body": body,
                "candidate_ref": candidate_ref,
            },
        )
        if _FORBIDDEN_GENERATED_CLAIMS.search(request.title) or _FORBIDDEN_GENERATED_CLAIMS.search(
            request.body
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="feedback is outside this workflow")
        row = await self._port().school_research_feedback_create_draft(
            actor,
            case_ref,
            expected_case_version=request.expected_case_version,
            title=request.title,
            body=request.body,
            candidate_ref=request.candidate_ref,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        return self._project(ResearchFeedbackDto, row)

    async def list_feedback(self, actor: Actor, case_ref: str, *, offset: int = 0, limit: int = 20):
        self._require_specialist(actor)
        self._pagination(offset, limit)
        result = await self._port().school_research_feedback_list_for_case(
            actor, case_ref, offset=offset, limit=limit
        )
        return self._project_list(ResearchFeedbackListDto, ResearchFeedbackDto, result, limit=limit)

    async def publish(
        self,
        actor: Actor,
        feedback_ref: str,
        *,
        expected_state_version: int,
        expected_case_version: int,
        idempotency,
        trace_id: str,
    ):
        self._require_specialist(actor)
        request = self._request(
            ResearchFeedbackPublishRequest,
            {
                "expected_state_version": expected_state_version,
                "expected_case_version": expected_case_version,
            },
        )
        row = await self._port().school_research_feedback_publish(
            actor,
            feedback_ref,
            expected_state_version=request.expected_state_version,
            expected_case_version=request.expected_case_version,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        return self._project(ResearchFeedbackDto, row)

    async def revoke(
        self,
        actor: Actor,
        feedback_ref: str,
        *,
        expected_state_version: int,
        idempotency,
        trace_id: str,
    ):
        self._require_specialist(actor)
        request = self._request(
            ResearchFeedbackRevokeRequest,
            {"expected_state_version": expected_state_version},
        )
        row = await self._port().school_research_feedback_revoke(
            actor,
            feedback_ref,
            expected_state_version=request.expected_state_version,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        return self._project(ResearchFeedbackDto, row)

    async def list_student_feedback(self, actor: Actor, *, offset: int = 0, limit: int = 20):
        self._require_student(actor)
        self._pagination(offset, limit)
        result = await self._port().school_research_feedback_list_student(
            actor, offset=offset, limit=limit
        )
        return self._project_list(
            StudentResearchFeedbackListDto,
            StudentResearchFeedbackDto,
            result,
            limit=limit,
        )

    async def get_student_feedback(self, actor: Actor, feedback_ref: str):
        self._require_student(actor)
        row = await self._port().school_research_feedback_read_student(actor, feedback_ref)
        projected = self._project(StudentResearchFeedbackDto, row)
        if projected["feedback_ref"] != feedback_ref:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research feedback data is unavailable",
            )
        return projected
