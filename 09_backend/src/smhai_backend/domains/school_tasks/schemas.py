"""Additive DTOs for the school task workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SchoolAssessmentStatus = Literal[
    "created", "in_progress", "completed", "abandoned", "invalid"
]


def normalize_school_assessment_status(value):
    if isinstance(value, str):
        return value.lower()
    return value


class ClassCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    class_ref: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class StudentAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_user_id: str = Field(pattern=r"^USER_[A-Za-z0-9][A-Za-z0-9_.-]*$", max_length=128)


class TeacherAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    teacher_user_id: str = Field(pattern=r"^USER_[A-Za-z0-9][A-Za-z0-9_.-]*$", max_length=128)


class TaskPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    opens_at: datetime
    due_at: datetime | None = None
    activation_ref: str | None = Field(
        default=None, pattern=r"^CACT_[A-Za-z0-9-]{36}$"
    )


class SchoolOutputDto(BaseModel):
    """Base for school responses whose naive database datetimes are stored as UTC."""

    @field_validator("*", mode="after")
    @classmethod
    def utc_datetime_output(cls, value):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=UTC)
            return value.astimezone(UTC)
        return value


class ClassDto(SchoolOutputDto):
    class_ref: str
    display_name: str | None = None
    status: str
    active_student_count: int
    active_teacher_count: int


class TaskDto(SchoolOutputDto):
    task_ref: str
    class_ref: str
    status: str
    opens_at: datetime
    due_at: datetime | None
    published_at: datetime
    published_enrollment_count: int
    active_enrollment_count: int
    revoked_enrollment_count: int
    instrument_id: str
    instrument_version: str
    activation_ref: str | None = None
    plan_name: str | None = None
    plan_version_number: int | None = None


class StudentTaskDto(SchoolOutputDto):
    task_ref: str
    class_ref: str
    status: str
    opens_at: datetime
    due_at: datetime | None
    assessment_id: str | None = None
    assessment_status: SchoolAssessmentStatus | None = None

    @field_validator("assessment_status", mode="before")
    @classmethod
    def normalize_assessment_status(cls, value):
        return normalize_school_assessment_status(value)


class StudentTaskHistoryDto(SchoolOutputDto):
    task_ref: str
    class_ref: str
    task_status: str
    enrollment_status: str
    assessment_status: SchoolAssessmentStatus | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @field_validator("assessment_status", mode="before")
    @classmethod
    def normalize_assessment_status(cls, value):
        return normalize_school_assessment_status(value)


class StudentAssessmentMetadataDto(SchoolOutputDto):
    model_config = ConfigDict(extra="forbid")

    assessment_id: str
    status: Literal["created", "in_progress", "completed", "abandoned", "invalid"]
    items_answered: int = Field(ge=0)
    started_at: datetime | None
    completed_at: datetime | None


class TaskStartDto(SchoolOutputDto):
    task_ref: str
    assessment_id: str
    subject_id: str
    status: str
    selected_item_id: str | None = None
    current_item: dict[str, object] | None = None
    answered_count: int
    administered_count: int
    can_complete: bool
    max_items: int | None = None


class TeacherTaskProgressDto(SchoolOutputDto):
    class_ref: str
    task_ref: str
    task_status: str
    opens_at: datetime
    due_at: datetime | None
    published_enrollment_count: int
    active_enrollment_count: int
    revoked_enrollment_count: int
    not_started_count: int
    created_count: int
    in_progress_count: int
    completed_count: int
    abandoned_count: int
    invalid_count: int


class RevocationDto(SchoolOutputDto):
    enrollment_ref: str
    status: str


class EnrollmentDto(SchoolOutputDto):
    enrollment_ref: str
    status: str


class SchoolMemberDto(SchoolOutputDto):
    user_id: str
    role: str
    subject_id: str | None = None
    display_name: str | None = None


class StudentAssignmentDto(SchoolOutputDto):
    class_ref: str
    student_user_id: str
    status: str


class TeacherAssignmentDto(SchoolOutputDto):
    class_ref: str
    teacher_user_id: str
    status: str
