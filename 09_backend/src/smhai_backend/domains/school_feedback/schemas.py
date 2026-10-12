"""Strict request and privacy-limited DTOs for synthetic school feedback."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator


class FeedbackModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class FeedbackDraftRequest(FeedbackModel):
    expected_case_version: StrictInt = Field(ge=1, le=2147483647)
    title: StrictStr = Field(min_length=1, max_length=120)
    body: StrictStr = Field(min_length=1, max_length=2000)

    @field_validator("title", "body")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value


class FeedbackTransitionRequest(FeedbackModel):
    expected_case_version: StrictInt = Field(ge=1, le=2147483647)
    expected_state_version: StrictInt = Field(ge=1, le=2147483647)


class FeedbackProjection(FeedbackModel):
    """An explicit allowlist; never serialize persistence or ORM objects."""

    @field_validator("synthetic_only", check_fields=False)
    @classmethod
    def require_synthetic_only(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("feedback projection must be synthetic")
        return value

    @field_validator("*")
    @classmethod
    def normalize_datetime(cls, value):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=UTC)
            return value.astimezone(UTC)
        return value


class FeedbackDto(FeedbackProjection):
    feedback_ref: StrictStr = Field(
        min_length=6,
        max_length=128,
        pattern=r"^FEED_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}$",
    )
    case_ref: StrictStr = Field(min_length=1, max_length=128)
    assessment_ref: StrictStr = Field(min_length=1, max_length=128)
    level: Literal["L3"]
    synthetic_only: StrictBool
    content_revision: StrictInt = Field(ge=1, le=2147483647)
    state_version: StrictInt = Field(ge=1, le=2147483647)
    case_version: StrictInt = Field(ge=1, le=2147483647)
    status: Literal["DRAFT", "PUBLISHED", "REVOKED"]
    title: StrictStr = Field(min_length=1, max_length=120)
    body: StrictStr = Field(min_length=1, max_length=2000)
    created_at: datetime
    published_at: datetime | None = None
    revoked_at: datetime | None = None


class StudentFeedbackDto(FeedbackProjection):
    """Published student view omits case identifiers and case version."""

    feedback_ref: StrictStr = Field(
        min_length=6,
        max_length=128,
        pattern=r"^FEED_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}$",
    )
    assessment_ref: StrictStr = Field(min_length=1, max_length=128)
    level: Literal["L3"]
    synthetic_only: StrictBool
    content_revision: StrictInt = Field(ge=1, le=2147483647)
    state_version: StrictInt = Field(ge=1, le=2147483647)
    status: Literal["PUBLISHED"]
    title: StrictStr = Field(min_length=1, max_length=120)
    body: StrictStr = Field(min_length=1, max_length=2000)
    created_at: datetime
    published_at: datetime


class FeedbackListDto(FeedbackModel):
    items: list[FeedbackDto]
    total: StrictInt = Field(ge=0)


class StudentFeedbackListDto(FeedbackModel):
    items: list[StudentFeedbackDto]
    total: StrictInt = Field(ge=0)
