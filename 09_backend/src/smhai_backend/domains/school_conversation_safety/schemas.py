"""Closed DTOs for durable school conversation safety review."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

DecisionCode = Literal["UNRESOLVED_NEEDS_CONTEXT"]
CaseStatus = Literal[
    "UNASSIGNED_PENDING",
    "ASSIGNED",
    "IN_REVIEW",
    "REVIEWED",
    "ESCALATION_NEEDED",
    "CLOSED",
    "REVOKED",
]
SpecialistCaseStatus = Literal["ASSIGNED", "IN_REVIEW", "REVIEWED", "ESCALATION_NEEDED", "CLOSED"]


class SafetyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SafetyAssignmentRequest(SafetyModel):
    expected_version: StrictInt = Field(ge=1, le=2_147_483_647)
    class_ref: StrictStr = Field(min_length=1, max_length=128)
    specialist_user_id: StrictStr = Field(min_length=1, max_length=128)


class SafetyVersionRequest(SafetyModel):
    expected_version: StrictInt = Field(ge=1, le=2_147_483_647)


class SafetyNoteRequest(SafetyModel):
    expected_version: StrictInt = Field(ge=1, le=2_147_483_647)
    note: StrictStr = Field(min_length=1, max_length=4000)

    @field_validator("note")
    @classmethod
    def note_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("review note must not be blank")
        return value


class SafetyTransitionRequest(SafetyModel):
    expected_version: StrictInt = Field(ge=1, le=2_147_483_647)
    status: Literal["IN_REVIEW", "REVIEWED", "ESCALATION_NEEDED", "CLOSED"]
    decision_code: DecisionCode | None = None


class _SafetyOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, strict=True)

    @field_validator(
        "created_at",
        "updated_at",
        "assigned_at",
        "reviewed_at",
        "closed_at",
        mode="after",
        check_fields=False,
    )
    @classmethod
    def normalize_datetime(cls, value):
        if not isinstance(value, datetime):
            return value
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class AdminCaseDto(_SafetyOutput):
    case_ref: StrictStr = Field(min_length=1, max_length=128)
    status: CaseStatus
    state_version: StrictInt = Field(ge=1, le=2_147_483_647)
    class_ref: StrictStr | None = Field(default=None, max_length=128)
    created_at: datetime
    updated_at: datetime
    assigned_at: datetime | None = None


class UnassignedCaseDto(_SafetyOutput):
    case_ref: StrictStr = Field(min_length=1, max_length=128)
    status: Literal["UNASSIGNED_PENDING"]
    state_version: StrictInt = Field(ge=1, le=2_147_483_647)
    class_ref: StrictStr | None = Field(default=None, max_length=128)
    created_at: datetime
    updated_at: datetime


class AssignmentReceiptDto(_SafetyOutput):
    case_ref: StrictStr = Field(min_length=1, max_length=128)
    status: Literal["ASSIGNED"]
    state_version: StrictInt = Field(ge=1, le=2_147_483_647)
    class_ref: StrictStr = Field(min_length=1, max_length=128)
    assigned_at: datetime
    updated_at: datetime


class SpecialistCaseDto(_SafetyOutput):
    case_ref: StrictStr = Field(min_length=1, max_length=128)
    class_ref: StrictStr = Field(min_length=1, max_length=128)
    action: Literal["REVIEW_REQUIRED", "CRISIS_ROUTE"]
    reason_codes: list[StrictStr] = Field(min_length=1, max_length=16)
    status: SpecialistCaseStatus
    state_version: StrictInt = Field(ge=1, le=2_147_483_647)
    decision_code: DecisionCode | None
    created_at: datetime
    updated_at: datetime
    assigned_at: datetime
    reviewed_at: datetime | None
    closed_at: datetime | None


class SpecialistCaseDetailDto(SpecialistCaseDto):
    review_note: StrictStr | None = Field(default=None, max_length=4000)


class StudentSafetyStatusDto(_SafetyOutput):
    case_ref: StrictStr = Field(min_length=1, max_length=128)
    action: Literal["REVIEW_REQUIRED", "CRISIS_ROUTE"]
    status: CaseStatus
    created_at: datetime
    updated_at: datetime


class SafetyPage(SafetyModel):
    items: list[AdminCaseDto | UnassignedCaseDto | SpecialistCaseDto]
    total: StrictInt = Field(ge=0)


class UnassignedSafetyPage(SafetyModel):
    items: list[UnassignedCaseDto]
    total: StrictInt = Field(ge=0)


class SpecialistSafetyPage(SafetyModel):
    items: list[SpecialistCaseDto]
    total: StrictInt = Field(ge=0)
