"""Closed request and projection DTOs for school support v1."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

SupportCaseStatus = Literal["SUBMITTED", "TRIAGED", "PLANNED", "FOLLOWING", "REVIEW", "CLOSED"]
SupportCaseSource = Literal["TEACHER_REFERRAL", "STUDENT_REQUEST"]
SupportActionTarget = Literal["STUDENT", "TEACHER"]
SupportCategoryCode = Literal[
    "LEARNING_SUPPORT",
    "ATTENDANCE_SUPPORT",
    "PEER_RELATION",
    "FAMILY_CONTEXT",
    "OTHER",
]
SupportActionStatus = Literal["PENDING", "SUBMITTED", "ACCEPTED", "RETURNED", "CANCELLED"]


class SupportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SupportCaseCreateRequest(SupportModel):
    student_ref: StrictStr | None = Field(default=None, min_length=1, max_length=128)
    class_ref: StrictStr | None = Field(default=None, min_length=1, max_length=128)
    category_code: SupportCategoryCode
    content: StrictStr = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def content_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("support content must not be blank")
        return value


class SupportTransitionRequest(SupportModel):
    expected_version: StrictInt = Field(ge=1, le=2_147_483_647)
    target_status: Literal["TRIAGED", "PLANNED", "REVIEW", "CLOSED"]
    plan: StrictStr | None = Field(default=None, min_length=1, max_length=4000)

    @model_validator(mode="after")
    def validate_plan_shape(self):
        if self.target_status == "PLANNED":
            if self.plan is None or not self.plan.strip():
                raise ValueError("a plan is required")
        elif self.plan is not None:
            raise ValueError("a plan is only accepted when planning")
        return self


class SupportActionCreateRequest(SupportModel):
    expected_version: StrictInt = Field(ge=1, le=2_147_483_647)
    target: SupportActionTarget = "TEACHER"
    teacher_user_id: StrictStr | None = Field(default=None, min_length=1, max_length=128)
    instructions: StrictStr = Field(min_length=1, max_length=4000)
    due_at: datetime = Field(strict=False)

    @model_validator(mode="after")
    def validate_target_shape(self):
        if self.target == "TEACHER":
            if self.teacher_user_id is None:
                raise ValueError("teacher targets require a teacher_user_id")
        elif self.teacher_user_id is not None:
            raise ValueError("student targets do not accept a teacher_user_id")
        return self

    @field_validator("instructions")
    @classmethod
    def instructions_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("instructions must not be blank")
        return value

    @field_validator("due_at")
    @classmethod
    def normalize_due_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class SupportActionFeedbackRequest(SupportModel):
    expected_version: StrictInt = Field(ge=1, le=2_147_483_647)
    outcome: Literal["SUBMITTED", "ACCEPTED", "RETURNED", "CANCELLED"]
    feedback: StrictStr | None = Field(default=None, min_length=1, max_length=4000)

    @model_validator(mode="after")
    def validate_feedback_shape(self):
        if self.outcome == "SUBMITTED":
            if self.feedback is None or not self.feedback.strip():
                raise ValueError("feedback is required")
        elif self.feedback is not None:
            raise ValueError("feedback is not accepted for this outcome")
        return self


class _SupportOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, strict=True)

    @field_validator(
        "created_at",
        "updated_at",
        "assigned_at",
        "closed_at",
        "due_at",
        "published_at",
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


class SupportStudentDto(SupportModel):
    student_ref: StrictStr = Field(min_length=1, max_length=128)
    display_name: StrictStr = Field(min_length=1, max_length=120)
    class_ref: StrictStr = Field(min_length=1, max_length=128)


class SupportStudentListDto(SupportModel):
    items: list[SupportStudentDto]
    total: StrictInt = Field(ge=0)


class SupportAssigneeDto(SupportModel):
    teacher_user_id: StrictStr = Field(min_length=1, max_length=128)
    display_name: StrictStr = Field(min_length=1, max_length=120)


class SupportAssigneeListDto(SupportModel):
    items: list[SupportAssigneeDto]
    total: StrictInt = Field(ge=0)


class SupportCaseSummaryDto(_SupportOutput):
    case_ref: StrictStr = Field(min_length=1, max_length=128)
    source: SupportCaseSource
    category_code: SupportCategoryCode
    status: SupportCaseStatus
    state_version: StrictInt = Field(ge=1, le=2_147_483_647)
    created_at: datetime
    updated_at: datetime


class SupportCasePageDto(SupportModel):
    items: list[SupportCaseSummaryDto]
    total: StrictInt = Field(ge=0)


class SupportActionDto(_SupportOutput):
    action_ref: StrictStr = Field(min_length=1, max_length=128)
    case_ref: StrictStr = Field(min_length=1, max_length=128)
    status: SupportActionStatus
    version: StrictInt = Field(ge=1, le=2_147_483_647)
    teacher_user_id: StrictStr | None = Field(default=None, min_length=1, max_length=128)
    instructions: StrictStr | None = Field(default=None, max_length=4000)
    feedback: StrictStr | None = Field(default=None, max_length=4000)
    due_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SupportActionPageDto(SupportModel):
    items: list[SupportActionDto]
    total: StrictInt = Field(ge=0)


class SupportCaseDetailDto(SupportCaseSummaryDto):
    student_ref: StrictStr | None = Field(default=None, min_length=1, max_length=128)
    class_ref: StrictStr | None = Field(default=None, min_length=1, max_length=128)
    content: StrictStr | None = Field(default=None, max_length=4000)
    plan: StrictStr | None = Field(default=None, max_length=4000)
    actions: list[SupportActionDto] = Field(default_factory=list)
    assigned_at: datetime | None = None
    closed_at: datetime | None = None


class SupportCaseReceiptDto(_SupportOutput):
    case_ref: StrictStr = Field(min_length=1, max_length=128)
    source: SupportCaseSource
    category_code: SupportCategoryCode
    status: SupportCaseStatus
    state_version: StrictInt = Field(ge=1, le=2_147_483_647)
    created_at: datetime
    updated_at: datetime


class SupportPlanFeedbackDto(_SupportOutput):
    title: StrictStr = Field(min_length=1, max_length=120)
    body: StrictStr = Field(min_length=1, max_length=2000)
    published_at: datetime
    content_revision: StrictInt = Field(ge=1, le=2_147_483_647)


class SupportPlanEvidenceDto(SupportModel):
    feedback: SupportPlanFeedbackDto | None
