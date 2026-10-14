"""Closed DTOs for research-only educational feedback and review."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

_PUBLICATION_STATUS = "not_approved_for_publication_or_operational_use"


class ResearchFeedbackModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ResearchCaseCreateRequest(ResearchFeedbackModel):
    session_ref: StrictStr = Field(min_length=1, max_length=128)


class ResearchCaseDecisionRequest(ResearchFeedbackModel):
    expected_version: StrictInt = Field(ge=1, le=2_147_483_647)
    status: Literal["OPEN", "IN_REVIEW", "APPROVED", "REJECTED"]
    note: StrictStr = Field(min_length=1, max_length=4000)

    @field_validator("note")
    @classmethod
    def note_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("review note must not be blank")
        return value


class ResearchFeedbackDraftRequest(ResearchFeedbackModel):
    expected_case_version: StrictInt = Field(ge=1, le=2_147_483_647)
    title: StrictStr = Field(min_length=1, max_length=120)
    body: StrictStr = Field(min_length=1, max_length=4000)

    @field_validator("title", "body")
    @classmethod
    def text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("feedback text must not be blank")
        return value


class ResearchFeedbackPublishRequest(ResearchFeedbackModel):
    expected_state_version: StrictInt = Field(ge=1, le=2_147_483_647)
    expected_case_version: StrictInt = Field(ge=1, le=2_147_483_647)


class ResearchFeedbackRevokeRequest(ResearchFeedbackModel):
    expected_state_version: StrictInt = Field(ge=1, le=2_147_483_647)


class _ResearchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, strict=True)

    @field_validator("*", mode="after")
    @classmethod
    def normalize_datetime(cls, value):
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                return value.replace(tzinfo=UTC)
            return value.astimezone(UTC)
        return value


class ResearchReviewTaskDto(_ResearchOutput):
    task_ref: StrictStr = Field(min_length=1, max_length=128)
    class_ref: StrictStr = Field(min_length=1, max_length=128)
    class_display_name: StrictStr | None = Field(default=None, max_length=160)
    published_at: datetime


class ResearchEligibleSessionDto(_ResearchOutput):
    session_ref: StrictStr = Field(min_length=1, max_length=128)
    task_ref: StrictStr = Field(min_length=1, max_length=128)
    status: Literal["COMPLETED"]
    items_answered: StrictInt = Field(ge=0)
    completed_at: datetime
    case_ref: StrictStr | None = Field(default=None, max_length=128)


class ResearchReviewCaseDto(_ResearchOutput):
    case_ref: StrictStr = Field(min_length=1, max_length=128)
    task_ref: StrictStr = Field(min_length=1, max_length=128)
    session_ref: StrictStr = Field(min_length=1, max_length=128)
    status: Literal["OPEN", "IN_REVIEW", "APPROVED", "REJECTED"]
    version: StrictInt = Field(ge=1, le=2_147_483_647)
    created_at: datetime
    updated_at: datetime
    review_note: StrictStr | None = Field(default=None, max_length=4000)


class ResearchFeedbackDto(_ResearchOutput):
    feedback_ref: StrictStr = Field(min_length=1, max_length=128)
    case_ref: StrictStr = Field(min_length=1, max_length=128)
    session_ref: StrictStr = Field(min_length=1, max_length=128)
    feedback_kind: Literal["GENERAL_EDUCATIONAL_SUPPORT"]
    purpose: Literal["RESEARCH_SIMULATION"]
    research_only: Literal[True]
    psychological_interpretation_allowed: Literal[False]
    publication_status: Literal[_PUBLICATION_STATUS]
    content_revision: StrictInt = Field(ge=1, le=2_147_483_647)
    case_version: StrictInt = Field(ge=1, le=2_147_483_647)
    state_version: StrictInt = Field(ge=1, le=2_147_483_647)
    status: Literal["DRAFT", "PUBLISHED", "REVOKED"]
    title: StrictStr = Field(min_length=1, max_length=120)
    body: StrictStr = Field(min_length=1, max_length=4000)
    created_at: datetime
    published_at: datetime | None = None
    revoked_at: datetime | None = None


class StudentResearchFeedbackDto(_ResearchOutput):
    """Published student projection; deliberately omits case and task refs."""

    feedback_ref: StrictStr = Field(min_length=1, max_length=128)
    session_ref: StrictStr = Field(min_length=1, max_length=128)
    feedback_kind: Literal["GENERAL_EDUCATIONAL_SUPPORT"]
    purpose: Literal["RESEARCH_SIMULATION"]
    research_only: Literal[True]
    psychological_interpretation_allowed: Literal[False]
    publication_status: Literal[_PUBLICATION_STATUS]
    content_revision: StrictInt = Field(ge=1, le=2_147_483_647)
    state_version: StrictInt = Field(ge=1, le=2_147_483_647)
    status: Literal["PUBLISHED"]
    title: StrictStr = Field(min_length=1, max_length=120)
    body: StrictStr = Field(min_length=1, max_length=4000)
    created_at: datetime
    published_at: datetime


class ResearchReviewTaskListDto(ResearchFeedbackModel):
    items: list[ResearchReviewTaskDto]


class ResearchEligibleSessionListDto(ResearchFeedbackModel):
    items: list[ResearchEligibleSessionDto]
    total: StrictInt = Field(ge=0)


class ResearchReviewCaseListDto(ResearchFeedbackModel):
    items: list[ResearchReviewCaseDto]
    total: StrictInt = Field(ge=0)


class ResearchFeedbackListDto(ResearchFeedbackModel):
    items: list[ResearchFeedbackDto]
    total: StrictInt = Field(ge=0)


class StudentResearchFeedbackListDto(ResearchFeedbackModel):
    items: list[StudentResearchFeedbackDto]
    total: StrictInt = Field(ge=0)
