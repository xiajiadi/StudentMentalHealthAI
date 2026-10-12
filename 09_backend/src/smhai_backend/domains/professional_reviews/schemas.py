"""Strict request and privacy-limited response DTOs for professional review."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator


class ProfessionalReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SpecialistAssignmentRequest(ProfessionalReviewRequest):
    specialist_user_id: StrictStr = Field(
        min_length=1,
        max_length=128,
        pattern=r"^USER_[A-Za-z0-9][A-Za-z0-9_.-]*$",
    )


class ReviewTransitionRequest(ProfessionalReviewRequest):
    expected_version: StrictInt = Field(ge=1, le=2147483647)


class ReviewCaseCreateRequest(ProfessionalReviewRequest):
    enrollment_ref: StrictStr = Field(min_length=1, max_length=128)


class ReviewCaseOpenRequest(ReviewTransitionRequest):
    pass


class ReviewCaseDecisionRequest(ReviewTransitionRequest):
    decision: Literal["APPROVED", "REJECTED"]
    note: StrictStr = Field(min_length=1, max_length=2000)

    @field_validator("note")
    @classmethod
    def note_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("note must not be blank")
        return value


class ProfessionalReviewOutput(BaseModel):
    """Adapter output is a deliberately whitelisted projection, never ORM data."""

    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("*", mode="after")
    @classmethod
    def normalize_datetime(cls, value):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=UTC)
            return value.astimezone(UTC)
        return value


class SpecialistAssignmentDto(ProfessionalReviewOutput):
    assignment_ref: StrictStr = Field(min_length=1, max_length=128)
    task_ref: StrictStr = Field(min_length=1, max_length=128)
    specialist_user_id: StrictStr = Field(min_length=1, max_length=128)
    status: Literal["ACTIVE", "REVOKED"]
    assigned_at: datetime
    revoked_at: datetime | None = None


class ProfessionalSpecialistDto(ProfessionalReviewOutput):
    user_id: StrictStr = Field(min_length=1, max_length=128)
    display_name: StrictStr | None = None


class ProfessionalReviewCaseDto(ProfessionalReviewOutput):
    case_ref: StrictStr = Field(min_length=1, max_length=128)
    task_ref: StrictStr = Field(min_length=1, max_length=128)
    enrollment_ref: StrictStr = Field(min_length=1, max_length=128)
    assessment_ref: StrictStr = Field(min_length=1, max_length=128)
    status: Literal["OPEN", "IN_REVIEW", "APPROVED", "REJECTED"]
    publication_status: Literal["NOT_PUBLISHED"]
    version: StrictInt = Field(ge=1, le=2147483647)
    created_at: datetime
    updated_at: datetime
    decision: Literal["APPROVED", "REJECTED"] | None = None
    review_note: StrictStr | None = Field(default=None, max_length=2000)


class ProfessionalReviewCaseListDto(ProfessionalReviewOutput):
    items: list[ProfessionalReviewCaseDto]
    total: StrictInt = Field(ge=0)


class ProfessionalReviewTaskDto(ProfessionalReviewOutput):
    task_ref: StrictStr = Field(min_length=1, max_length=128)
    class_ref: StrictStr = Field(min_length=1, max_length=128)
    class_display_name: StrictStr | None = None
    published_at: datetime


class ProfessionalEligibleEnrollmentDto(ProfessionalReviewOutput):
    enrollment_ref: StrictStr = Field(min_length=1, max_length=128)
    assessment_ref: StrictStr = Field(min_length=1, max_length=128)
    completed_at: datetime
    case_ref: StrictStr | None = None


class ProfessionalEligibleEnrollmentListDto(ProfessionalReviewOutput):
    items: list[ProfessionalEligibleEnrollmentDto]
    total: StrictInt = Field(ge=0)
