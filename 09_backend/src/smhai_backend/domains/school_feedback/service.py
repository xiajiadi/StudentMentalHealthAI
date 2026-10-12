"""Authorization gates and safe DTO projection for synthetic feedback."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import ValidationError

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.models import Actor, BackendRole

from .schemas import (
    FeedbackDraftRequest,
    FeedbackDto,
    FeedbackListDto,
    FeedbackTransitionRequest,
    StudentFeedbackDto,
    StudentFeedbackListDto,
)


class SchoolFeedbackService:
    """Orchestrate a strict L3 acknowledgement workflow, without judging content."""

    def __init__(self, *, persistence) -> None:
        self.persistence = persistence

    def _port(self):
        if self.persistence is None:
            raise error(ErrorCode.DEPENDENCY_UNAVAILABLE, detail="feedback is unavailable")
        return self.persistence

    @staticmethod
    def _require_school_role(actor: Actor, role: BackendRole) -> None:
        if (
            actor.scope_profile != "school_tenant"
            or actor.role is not role
            or actor.school_id is None
            or actor.school_id <= 0
            or not actor.school_ref
        ):
            raise error(ErrorCode.FORBIDDEN, detail="access denied")

    @classmethod
    def _require_specialist(cls, actor: Actor) -> None:
        cls._require_school_role(actor, BackendRole.PSYCHOLOGICAL_SPECIALIST)

    @classmethod
    def _require_student(cls, actor: Actor) -> None:
        cls._require_school_role(actor, BackendRole.STUDENT)

    @staticmethod
    def _request(dto_type, values):
        try:
            return dto_type.model_validate(values, strict=True)
        except ValidationError as exc:
            raise error(ErrorCode.VALIDATION_FAILED, detail="feedback request is invalid") from exc

    @staticmethod
    def _project(dto_type, row):
        if not isinstance(row, Mapping):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="feedback data is unavailable",
            )
        try:
            return dto_type.model_validate(dict(row), strict=True).model_dump(mode="python")
        except ValidationError as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="feedback data is unavailable",
            ) from exc

    @classmethod
    def _project_list(cls, dto_type, result, item_type, limit: int):
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
                detail="feedback data is unavailable",
            )
        items = [cls._project(item_type, row) for row in result["items"]]
        try:
            return dto_type(items=items, total=result["total"]).model_dump(mode="python")
        except ValidationError as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="feedback data is unavailable",
            ) from exc

    @staticmethod
    def _pagination(offset: int, limit: int) -> None:
        if (
            type(offset) is not int
            or not 0 <= offset <= 100000
            or type(limit) is not int
            or not 1 <= limit <= 50
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="pagination is invalid")

    @staticmethod
    def _require_status(row: Mapping, expected: str) -> None:
        if row.get("status") != expected:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="feedback data is unavailable",
            )

    @staticmethod
    def _require_case_version(row: Mapping, expected: int) -> None:
        if row.get("case_version") != expected:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="feedback data is unavailable",
            )

    @staticmethod
    def _require_state_version(row: Mapping, expected: int) -> None:
        if row.get("state_version") != expected + 1:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="feedback data is unavailable",
            )

    async def list_case_feedback(
        self, actor: Actor, case_ref: str, *, offset: int = 0, limit: int = 50
    ):
        self._require_specialist(actor)
        self._pagination(offset, limit)
        result = await self._port().school_feedback_list_cases(
            actor, case_ref, offset=offset, limit=limit
        )
        projected = self._project_list(FeedbackListDto, result, FeedbackDto, limit)
        if any(item["case_ref"] != case_ref for item in projected["items"]):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="feedback data is unavailable",
            )
        return projected

    async def create_draft(
        self,
        actor: Actor,
        case_ref: str,
        *,
        expected_case_version: int,
        title: str,
        body: str,
        idempotency,
        trace_id: str,
    ):
        self._require_specialist(actor)
        request = self._request(
            FeedbackDraftRequest,
            {
                "expected_case_version": expected_case_version,
                "title": title,
                "body": body,
            },
        )
        row = await self._port().school_feedback_create(
            actor,
            case_ref,
            expected_case_version=request.expected_case_version,
            title=request.title,
            body=request.body,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        projected = self._project(FeedbackDto, row)
        self._require_status(projected, "DRAFT")
        self._require_case_version(projected, request.expected_case_version)
        return projected

    async def publish(
        self,
        actor: Actor,
        feedback_ref: str,
        *,
        expected_case_version: int,
        expected_state_version: int,
        idempotency,
        trace_id: str,
    ):
        self._require_specialist(actor)
        request = self._request(
            FeedbackTransitionRequest,
            {
                "expected_case_version": expected_case_version,
                "expected_state_version": expected_state_version,
            },
        )
        row = await self._port().school_feedback_publish(
            actor,
            feedback_ref,
            expected_case_version=request.expected_case_version,
            expected_state_version=request.expected_state_version,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        projected = self._project(FeedbackDto, row)
        self._require_status(projected, "PUBLISHED")
        self._require_case_version(projected, request.expected_case_version)
        self._require_state_version(projected, request.expected_state_version)
        return projected

    async def revoke(
        self,
        actor: Actor,
        feedback_ref: str,
        *,
        expected_case_version: int,
        expected_state_version: int,
        idempotency,
        trace_id: str,
    ):
        self._require_specialist(actor)
        request = self._request(
            FeedbackTransitionRequest,
            {
                "expected_case_version": expected_case_version,
                "expected_state_version": expected_state_version,
            },
        )
        row = await self._port().school_feedback_revoke(
            actor,
            feedback_ref,
            expected_case_version=request.expected_case_version,
            expected_state_version=request.expected_state_version,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        projected = self._project(FeedbackDto, row)
        self._require_status(projected, "REVOKED")
        self._require_case_version(projected, request.expected_case_version)
        self._require_state_version(projected, request.expected_state_version)
        return projected

    async def list_student_feedback(self, actor: Actor, *, offset: int = 0, limit: int = 50):
        self._require_student(actor)
        self._pagination(offset, limit)
        result = await self._port().school_feedback_list_student(
            actor, offset=offset, limit=limit
        )
        return self._project_list(StudentFeedbackListDto, result, StudentFeedbackDto, limit)

    async def get_student_feedback(self, actor: Actor, feedback_ref: str):
        self._require_student(actor)
        row = await self._port().school_feedback_read_student(actor, feedback_ref)
        projected = self._project(StudentFeedbackDto, row)
        if projected["feedback_ref"] != feedback_ref:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="feedback data is unavailable",
            )
        return projected
