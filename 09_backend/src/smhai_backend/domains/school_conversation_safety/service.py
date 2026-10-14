"""Role boundary and DTO validation for school conversation safety review."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import ValidationError

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.models import Actor, BackendRole

from .schemas import (
    AdminCaseDto,
    AssignmentReceiptDto,
    SafetyAssignmentRequest,
    SafetyNoteRequest,
    SafetyTransitionRequest,
    SafetyVersionRequest,
    SpecialistCaseDetailDto,
    SpecialistCaseDto,
    SpecialistSafetyPage,
    StudentSafetyStatusDto,
    UnassignedCaseDto,
    UnassignedSafetyPage,
)


class SchoolConversationSafetyService:
    def __init__(self, *, persistence) -> None:
        self.persistence = persistence

    def _port(self):
        if self.persistence is None:
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="conversation safety review is unavailable",
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
                detail="conversation safety request is invalid",
            ) from exc

    @staticmethod
    def _project(dto_type, row):
        if not isinstance(row, Mapping):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="conversation safety data is unavailable",
            )
        try:
            return dto_type.model_validate(dict(row), strict=True).model_dump(mode="python")
        except ValidationError as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="conversation safety data is unavailable",
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
                detail="conversation safety data is unavailable",
            )
        items = [cls._project(item_type, row) for row in result["items"]]
        try:
            return dto_type(items=items, total=result["total"]).model_dump(mode="python")
        except ValidationError as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="conversation safety data is unavailable",
            ) from exc

    async def list_unassigned(self, actor: Actor, *, offset: int = 0, limit: int = 20):
        self._require_role(actor, BackendRole.ADMIN)
        self._pagination(offset, limit)
        result = await self._port().admin_list_unassigned(actor, offset=offset, limit=limit)
        return self._project_page(UnassignedSafetyPage, UnassignedCaseDto, result, limit=limit)

    async def list_assigned(self, actor: Actor, *, offset: int = 0, limit: int = 20):
        self._require_role(actor, BackendRole.PSYCHOLOGICAL_SPECIALIST)
        self._pagination(offset, limit)
        result = await self._port().specialist_list_assigned(actor, offset=offset, limit=limit)
        return self._project_page(SpecialistSafetyPage, SpecialistCaseDto, result, limit=limit)

    async def get_assigned(self, actor: Actor, case_ref: str):
        self._require_role(actor, BackendRole.PSYCHOLOGICAL_SPECIALIST)
        result = await self._port().specialist_get(actor, case_ref, include_note=True)
        return self._project(SpecialistCaseDetailDto, result)

    async def assign(
        self, actor: Actor, case_ref: str, *, payload: dict, idempotency, trace_id: str
    ):
        self._require_role(actor, BackendRole.ADMIN)
        request = self._request(SafetyAssignmentRequest, payload)
        row = await self._port().admin_assign(
            actor,
            case_ref,
            class_ref=request.class_ref,
            specialist_user_id=request.specialist_user_id,
            expected_version=request.expected_version,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        return self._project(AssignmentReceiptDto, row)

    async def transfer(
        self, actor: Actor, case_ref: str, *, payload: dict, idempotency, trace_id: str
    ):
        self._require_role(actor, BackendRole.ADMIN)
        request = self._request(SafetyAssignmentRequest, payload)
        row = await self._port().admin_transfer(
            actor,
            case_ref,
            class_ref=request.class_ref,
            specialist_user_id=request.specialist_user_id,
            expected_version=request.expected_version,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        return self._project(AssignmentReceiptDto, row)

    async def unassign(
        self, actor: Actor, case_ref: str, *, payload: dict, idempotency, trace_id: str
    ):
        self._require_role(actor, BackendRole.ADMIN)
        request = self._request(SafetyVersionRequest, payload)
        row = await self._port().admin_unassign(
            actor,
            case_ref,
            expected_version=request.expected_version,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        return self._project(AdminCaseDto, row)

    async def revoke(
        self, actor: Actor, case_ref: str, *, payload: dict, idempotency, trace_id: str
    ):
        self._require_role(actor, BackendRole.ADMIN)
        request = self._request(SafetyVersionRequest, payload)
        row = await self._port().admin_revoke(
            actor,
            case_ref,
            expected_version=request.expected_version,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        return self._project(AdminCaseDto, row)

    async def save_note(
        self, actor: Actor, case_ref: str, *, payload: dict, idempotency, trace_id: str
    ):
        self._require_role(actor, BackendRole.PSYCHOLOGICAL_SPECIALIST)
        request = self._request(SafetyNoteRequest, payload)
        row = await self._port().specialist_save_note(
            actor,
            case_ref,
            expected_version=request.expected_version,
            note=request.note,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        return self._project(SpecialistCaseDetailDto, row)

    async def transition(
        self, actor: Actor, case_ref: str, *, payload: dict, idempotency, trace_id: str
    ):
        self._require_role(actor, BackendRole.PSYCHOLOGICAL_SPECIALIST)
        request = self._request(SafetyTransitionRequest, payload)
        if request.status == "IN_REVIEW":
            valid_decision = request.decision_code is None
        else:
            valid_decision = request.decision_code == "UNRESOLVED_NEEDS_CONTEXT"
        if not valid_decision:
            raise error(
                ErrorCode.VALIDATION_FAILED,
                detail="decision code does not match this transition",
            )
        row = await self._port().specialist_transition(
            actor,
            case_ref,
            expected_version=request.expected_version,
            status=request.status,
            decision_code=request.decision_code,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        return self._project(SpecialistCaseDetailDto, row)

    async def student_status(self, actor: Actor, conversation_ref: str, *, research: bool):
        self._require_role(actor, BackendRole.STUDENT)
        row = await self._port().student_status(
            actor,
            conversation_ref,
            target_role="student_research" if research else "student",
        )
        return self._project(StudentSafetyStatusDto, row)
