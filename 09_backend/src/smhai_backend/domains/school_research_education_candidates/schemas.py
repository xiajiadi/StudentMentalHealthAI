"""Closed API DTOs for task-bound research education candidates."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator

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
