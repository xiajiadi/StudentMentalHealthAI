"""Closed API DTOs for task-bound research education candidates."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from smhai_backend.domains.research_general_education.schemas import (
    ResearchGeneralEducationCandidatePayload,
)

_PUBLICATION_STATUS = "not_approved_for_publication_or_operational_use"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ResearchEducationCandidateTaskDto(_StrictModel):
    task_ref: StrictStr = Field(min_length=1, max_length=128)
    class_ref: StrictStr = Field(min_length=1, max_length=128)
    class_display_name: StrictStr | None = Field(default=None, max_length=160)
    published_at: datetime

    @field_validator("published_at", mode="after")
    @classmethod
    def published_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class ResearchEducationCandidateTaskListDto(_StrictModel):
    items: list[ResearchEducationCandidateTaskDto]


class ResearchEducationCandidateSummaryDto(_StrictModel):
    candidate_ref: StrictStr = Field(min_length=1, max_length=128)
    task_ref: StrictStr = Field(min_length=1, max_length=128)
    session_ref: StrictStr = Field(min_length=1, max_length=128)
    status: Literal["HELD", "ADOPTED", "DISCARDED"]
    state_version: StrictInt = Field(ge=1, le=2)
    purpose: Literal["RESEARCH_SIMULATION"]
    research_only: Literal[True]
    psychological_interpretation_allowed: Literal[False]
    publication_status: Literal[_PUBLICATION_STATUS]
    student_feedback_eligible: Literal[False]
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class ResearchEducationCandidateListDto(_StrictModel):
    items: list[ResearchEducationCandidateSummaryDto]
    offset: StrictInt = Field(ge=0)
    limit: StrictInt = Field(ge=1, le=50)
    has_more: StrictBool


class ResearchEducationGenerationJobSummaryDto(_StrictModel):
    job_ref: StrictStr = Field(pattern=r"^REJ_[0-9a-f]{64}$", max_length=68)
    status: Literal[
        "QUEUED",
        "LEASED",
        "RETRY",
        "HELD",
        "ABSTAINED",
        "REVIEW_REQUIRED",
        "CRISIS_ROUTED",
        "FAILED",
        "CANCELLED",
    ]
    attempt_count: StrictInt = Field(ge=0, le=1)
    last_error_code: Literal[
        "POLICY_UNAVAILABLE",
        "SOURCE_UNQUALIFIED",
        "SAFETY_BLOCKED",
        "UPSTREAM_TRANSIENT",
        "UPSTREAM_RATE_LIMITED",
        "UPSTREAM_TIMEOUT",
        "DEPENDENCY_INVALID_RESPONSE",
        "GENERATION_FAILED",
        "INTERNAL_FAILURE",
        "INTERNAL_FAILURE_AUTHORIZATION",
        "INTERNAL_FAILURE_GENERATION",
        "INTERNAL_FAILURE_OUTCOME_VALIDATION",
        "INTERNAL_FAILURE_CANDIDATE_PROJECTION",
        "INTERNAL_FAILURE_CANDIDATE_STORE",
        "INTERNAL_FAILURE_DISPOSITION",
        "INTERNAL_FAILURE_FINALIZATION",
        "LEASE_EXPIRED_MAX_ATTEMPTS",
        "MAX_ATTEMPTS_EXHAUSTED",
    ] | None
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class ResearchEducationGenerationJobStatusCountsDto(_StrictModel):
    QUEUED: StrictInt = Field(ge=0)
    LEASED: StrictInt = Field(ge=0)
    RETRY: StrictInt = Field(ge=0)
    HELD: StrictInt = Field(ge=0)
    ABSTAINED: StrictInt = Field(ge=0)
    REVIEW_REQUIRED: StrictInt = Field(ge=0)
    CRISIS_ROUTED: StrictInt = Field(ge=0)
    FAILED: StrictInt = Field(ge=0)
    CANCELLED: StrictInt = Field(ge=0)


class ResearchEducationGenerationJobListDto(_StrictModel):
    items: list[ResearchEducationGenerationJobSummaryDto]
    offset: StrictInt = Field(ge=0, le=100_000)
    limit: StrictInt = Field(ge=1, le=50)
    total: StrictInt = Field(ge=0)
    has_more: StrictBool
    status_counts: ResearchEducationGenerationJobStatusCountsDto
    policy_version: Literal["RESEARCH_GENERAL_EDUCATION_DRAFT_V1"]
    purpose: Literal["RESEARCH_SIMULATION"]
    research_only: Literal[True]
    publication_status: Literal[_PUBLICATION_STATUS]
    student_feedback_eligible: Literal[False]

    @model_validator(mode="after")
    def page_is_consistent(self):
        if (
            len(self.items) > self.limit
            or len({item.job_ref for item in self.items}) != len(self.items)
            or self.has_more != (self.offset + len(self.items) < self.total)
            or sum(self.status_counts.model_dump().values()) != self.total
        ):
            raise ValueError("research education generation job page is inconsistent")
        return self


class ResearchEducationCandidateResolutionRequest(_StrictModel):
    expected_state_version: StrictInt = Field(ge=1, le=2)
    target: Literal["ADOPTED", "DISCARDED"]


class ResearchEducationCandidateBatchRequest(_StrictModel):
    limit: StrictInt = Field(default=25, ge=1, le=100)
    offset: StrictInt = Field(default=0, ge=0, le=100_000)


class ResearchEducationCandidateBatchDto(_StrictModel):
    batch_ref: StrictStr = Field(min_length=1, max_length=128)
    job_refs: list[StrictStr] = Field(max_length=100)
    job_count: StrictInt = Field(ge=0, le=100)
    offset: StrictInt = Field(ge=0)
    limit: StrictInt = Field(ge=1, le=100)
    next_offset: StrictInt | None = Field(default=None, ge=0)
    policy_version: Literal["RESEARCH_GENERAL_EDUCATION_DRAFT_V1"]
    purpose: Literal["RESEARCH_SIMULATION"]
    research_only: Literal[True]
    publication_status: Literal[_PUBLICATION_STATUS]
    student_feedback_eligible: Literal[False]


class ResearchEducationCandidateDetailDto(ResearchEducationCandidateSummaryDto):
    candidate_payload: ResearchGeneralEducationCandidatePayload
