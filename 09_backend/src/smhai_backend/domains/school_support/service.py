"""Role, request, and workflow validation for school support v1."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import ValidationError

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.models import Actor, BackendRole

from .schemas import (
    SupportActionCreateRequest,
    SupportActionDto,
    SupportActionFeedbackRequest,
    SupportActionPageDto,
    SupportAssigneeDto,
    SupportAssigneeListDto,
    SupportCaseCreateRequest,
    SupportCaseDetailDto,
    SupportCasePageDto,
    SupportCaseReceiptDto,
    SupportCaseSummaryDto,
    SupportStudentDto,
    SupportStudentListDto,
    SupportTransitionRequest,
)

_CASE_TRANSITIONS = {
    "SUBMITTED": frozenset({"TRIAGED"}),
    "TRIAGED": frozenset({"PLANNED"}),
    "PLANNED": frozenset(),
    "FOLLOWING": frozenset({"REVIEW"}),
    "REVIEW": frozenset({"CLOSED"}),
    "CLOSED": frozenset(),
}


def validate_case_transition(current_status: str, target_status: str) -> None:
    """Reject skipped, repeated, or out-of-order case states."""

    allowed = _CASE_TRANSITIONS.get(current_status)
    if allowed is None or target_status not in allowed:
        raise error(ErrorCode.WORKFLOW_CONFLICT, detail="support case state changed")


def validate_action_outcome(role: BackendRole, current_status: str, outcome: str) -> None:
    """Keep teacher submissions and specialist review on separate outcomes."""

    if role is BackendRole.STUDENT:
        if outcome != "SUBMITTED" or current_status not in {"PENDING", "RETURNED"}:
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="support action state changed")
        return
    if role is BackendRole.TEACHER:
        if outcome != "SUBMITTED" or current_status not in {"PENDING", "RETURNED"}:
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="support action state changed")
        return
    if role is not BackendRole.PSYCHOLOGICAL_SPECIALIST:
        raise error(ErrorCode.FORBIDDEN, detail="access denied")
    allowed = {
        "SUBMITTED": {"ACCEPTED", "RETURNED", "CANCELLED"},
        "PENDING": {"CANCELLED"},
        "RETURNED": {"CANCELLED"},
    }.get(current_status, set())
    if outcome not in allowed:
        raise error(ErrorCode.WORKFLOW_CONFLICT, detail="support action state changed")


class SchoolSupportService:
    def __init__(self, *, persistence) -> None:
        self.persistence = persistence

    def _port(self):
        if self.persistence is None:
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="school support is unavailable",
                retryable=True,
            )
        return self.persistence

    @staticmethod
    def _require_school_actor(actor: Actor, *roles: BackendRole) -> None:
        if (
            not isinstance(actor, Actor)
            or actor.scope_profile != "school_tenant"
            or actor.role not in roles
            or type(actor.school_id) is not int
            or actor.school_id <= 0
            or not isinstance(actor.school_ref, str)
            or not actor.school_ref
        ):
            raise error(ErrorCode.FORBIDDEN, detail="access denied")

    @staticmethod
    def _pagination(offset: int, limit: int) -> None:
        if (
            type(offset) is not int
            or not 0 <= offset <= 100_000
            or type(limit) is not int
            or not 1 <= limit <= 50
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="pagination is invalid")

    @staticmethod
    def _request(dto_type, values):
        try:
            return dto_type.model_validate(values, strict=True)
        except ValidationError as exc:
            raise error(
                ErrorCode.VALIDATION_FAILED,
                detail="school support request is invalid",
            ) from exc

    @staticmethod
    def _project(dto_type, row):
        if not isinstance(row, Mapping):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="school support data is unavailable",
            )
        try:
            return dto_type.model_validate(dict(row), strict=True).model_dump(mode="python")
        except ValidationError as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="school support data is unavailable",
            ) from exc

    @classmethod
    def _project_page(cls, dto_type, item_type, result, *, limit: int):
        if (
            not isinstance(result, Mapping)
            or set(result) != {"items", "total"}
            or type(result["total"]) is not int
            or result["total"] < 0
            or not isinstance(result["items"], list)
            or len(result["items"]) > result["total"]
            or len(result["items"]) > limit
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="school support data is unavailable",
            )
        items = [cls._project(item_type, row) for row in result["items"]]
        try:
            return dto_type(items=items, total=result["total"]).model_dump(mode="python")
        except ValidationError as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="school support data is unavailable",
            ) from exc

    async def list_students(self, actor: Actor):
        self._require_school_actor(actor, BackendRole.TEACHER)
        result = await self._port().support_list_students(actor)
        if (
            not isinstance(result, Mapping)
            or set(result) != {"items", "total"}
            or type(result["total"]) is not int
            or result["total"] < 0
            or not isinstance(result["items"], list)
            or len(result["items"]) != result["total"]
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="school support data is unavailable",
            )
        items = [self._project(SupportStudentDto, row) for row in result["items"]]
        return SupportStudentListDto(items=items, total=result["total"]).model_dump(mode="python")

    async def list_assignees(self, actor: Actor, case_ref: str):
        self._require_school_actor(actor, BackendRole.PSYCHOLOGICAL_SPECIALIST)
        result = await self._port().support_list_assignees(actor, case_ref)
        if (
            not isinstance(result, Mapping)
            or set(result) != {"items", "total"}
            or type(result["total"]) is not int
            or result["total"] < 0
            or not isinstance(result["items"], list)
            or len(result["items"]) != result["total"]
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="school support data is unavailable",
            )
        items = [self._project(SupportAssigneeDto, row) for row in result["items"]]
        return SupportAssigneeListDto(items=items, total=result["total"]).model_dump(mode="python")

    async def create_case(
        self, actor: Actor, *, payload: dict, idempotency, trace_id: str
    ):
        self._require_school_actor(actor, BackendRole.TEACHER, BackendRole.STUDENT)
        request = self._request(SupportCaseCreateRequest, payload)
        if actor.role is BackendRole.TEACHER:
            if request.student_ref is None or request.class_ref is None:
                raise error(
                    ErrorCode.VALIDATION_FAILED,
                    detail="teacher referrals require a student and class",
                )
        elif request.student_ref is not None or request.class_ref is not None:
            raise error(
                ErrorCode.VALIDATION_FAILED,
                detail="student requests use the current student and class",
            )
        row = await self._port().support_create_case(
            actor,
            student_ref=request.student_ref,
            class_ref=request.class_ref,
            category_code=request.category_code,
            content=request.content,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        return self._project(SupportCaseReceiptDto, row)

    async def list_cases(self, actor: Actor, *, offset: int = 0, limit: int = 20):
        self._require_school_actor(
            actor,
            BackendRole.STUDENT,
            BackendRole.TEACHER,
            BackendRole.PSYCHOLOGICAL_SPECIALIST,
        )
        self._pagination(offset, limit)
        result = await self._port().support_list_cases(actor, offset=offset, limit=limit)
        return self._project_page(
            SupportCasePageDto, SupportCaseSummaryDto, result, limit=limit
        )

    async def list_actions(self, actor: Actor, *, offset: int = 0, limit: int = 20):
        self._require_school_actor(actor, BackendRole.STUDENT, BackendRole.TEACHER)
        self._pagination(offset, limit)
        result = await self._port().support_list_actions(
            actor, offset=offset, limit=limit
        )
        return self._project_page(
            SupportActionPageDto, SupportActionDto, result, limit=limit
        )

    async def get_case(self, actor: Actor, case_ref: str):
        self._require_school_actor(
            actor,
            BackendRole.STUDENT,
            BackendRole.TEACHER,
            BackendRole.PSYCHOLOGICAL_SPECIALIST,
        )
        row = await self._port().support_get_case(actor, case_ref)
        return self._project(SupportCaseDetailDto, row)

    async def transition_case(
        self,
        actor: Actor,
        case_ref: str,
        *,
        payload: dict,
        idempotency,
        trace_id: str,
    ):
        self._require_school_actor(actor, BackendRole.PSYCHOLOGICAL_SPECIALIST)
        request = self._request(SupportTransitionRequest, payload)
        row = await self._port().support_transition_case(
            actor,
            case_ref,
            expected_version=request.expected_version,
            target_status=request.target_status,
            plan=request.plan,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        return self._project(SupportCaseDetailDto, row)

    async def create_action(
        self,
        actor: Actor,
        case_ref: str,
        *,
        payload: dict,
        idempotency,
        trace_id: str,
    ):
        self._require_school_actor(actor, BackendRole.PSYCHOLOGICAL_SPECIALIST)
        request = self._request(SupportActionCreateRequest, payload)
        row = await self._port().support_create_action(
            actor,
            case_ref,
            expected_version=request.expected_version,
            target=request.target,
            teacher_user_id=request.teacher_user_id,
            instructions=request.instructions,
            due_at=request.due_at,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        return self._project(SupportCaseDetailDto, row)

    async def action_feedback(
        self,
        actor: Actor,
        action_ref: str,
        *,
        payload: dict,
        idempotency,
        trace_id: str,
    ):
        self._require_school_actor(
            actor,
            BackendRole.STUDENT,
            BackendRole.TEACHER,
            BackendRole.PSYCHOLOGICAL_SPECIALIST,
        )
        request = self._request(SupportActionFeedbackRequest, payload)
        if actor.role is BackendRole.STUDENT and request.outcome != "SUBMITTED":
            raise error(
                ErrorCode.VALIDATION_FAILED,
                detail="students may only submit action feedback",
            )
        if actor.role is BackendRole.TEACHER and request.outcome != "SUBMITTED":
            raise error(
                ErrorCode.VALIDATION_FAILED,
                detail="teachers may only submit action feedback",
            )
        if actor.role is BackendRole.PSYCHOLOGICAL_SPECIALIST and request.outcome == "SUBMITTED":
            raise error(
                ErrorCode.VALIDATION_FAILED,
                detail="specialists may only review action feedback",
            )
        row = await self._port().support_action_feedback(
            actor,
            action_ref,
            expected_version=request.expected_version,
            outcome=request.outcome,
            feedback=request.feedback,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        return self._project(SupportActionDto, row)
