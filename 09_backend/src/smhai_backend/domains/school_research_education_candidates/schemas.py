"""Closed API DTOs for task-bound research education candidates."""

from __future__ import annotations

import re
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

from smhai_backend.domains.research_general_education.prompt import (
    FIXED_GENERAL_EDUCATION_REQUEST,
)
from smhai_backend.domains.research_general_education.schemas import (
    ResearchGeneralEducationCandidatePayload,
    ResearchGeneralEducationSourceCard,
)
from smhai_backend.domains.support.schemas import GenerationContent, SupportCitation

_PUBLICATION_STATUS = "not_approved_for_publication_or_operational_use"
_INPUT_REVIEW_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


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
    generation_round: Literal[0, 1]
    input_review_ref: StrictStr | None = Field(max_length=128)
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

    @field_validator("input_review_ref", mode="after")
    @classmethod
    def review_reference_is_bounded(cls, value: str | None) -> str | None:
        if value is not None and _INPUT_REVIEW_TOKEN.fullmatch(value) is None:
            raise ValueError("input review reference is invalid")
        return value

    @model_validator(mode="after")
    def generation_round_matches_review_reference(self):
        if (self.generation_round == 0) != (self.input_review_ref is None):
            raise ValueError("generation round and input review reference are inconsistent")
        return self


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


class ResearchEducationInputReviewSummaryDto(_StrictModel):
    input_review_ref: StrictStr = Field(min_length=1, max_length=128)
    job_ref: StrictStr = Field(pattern=r"^REJ_[0-9a-f]{64}$", max_length=68)
    task_ref: StrictStr = Field(min_length=1, max_length=128)
    session_ref: StrictStr = Field(min_length=1, max_length=128)
    status: Literal[
        "PENDING",
        "CONTINUATION_AUTHORIZED",
        "CONSUMED",
        "REJECTED",
        "REVOKED",
    ]
    state_version: StrictInt = Field(ge=1, le=3)
    expires_at: datetime
    created_at: datetime
    updated_at: datetime
    reason_codes: list[Literal["CONTENT_CONTROVERSIAL"]] = Field(min_length=1, max_length=1)
    purpose: Literal["RESEARCH_SIMULATION"]
    research_only: Literal[True]
    continuation_enabled: StrictBool

    @field_validator("input_review_ref", "task_ref", "session_ref", mode="after")
    @classmethod
    def refs_are_bounded_tokens(cls, value: str) -> str:
        if _INPUT_REVIEW_TOKEN.fullmatch(value) is None:
            raise ValueError("input review reference is invalid")
        return value

    @field_validator("expires_at", "created_at", "updated_at", mode="after")
    @classmethod
    def review_timestamps_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def review_version_matches_status(self):
        valid_versions = {
            "PENDING": {1},
            "CONTINUATION_AUTHORIZED": {2},
            "CONSUMED": {3},
            "REJECTED": {2},
            "REVOKED": {2, 3},
        }
        if self.state_version not in valid_versions[self.status]:
            raise ValueError("input review status and version are inconsistent")
        if self.expires_at <= self.created_at or self.updated_at < self.created_at:
            raise ValueError("input review timestamps are inconsistent")
        return self


class ResearchEducationInputReviewListDto(_StrictModel):
    items: list[ResearchEducationInputReviewSummaryDto]
    offset: StrictInt = Field(ge=0, le=100_000)
    limit: StrictInt = Field(ge=1, le=20)
    has_more: StrictBool

    @model_validator(mode="after")
    def page_is_consistent(self):
        if (
            len(self.items) > self.limit
            or len({item.input_review_ref for item in self.items}) != len(self.items)
        ):
            raise ValueError("input review page is inconsistent")
        return self


class ResearchEducationInputReviewDetailDto(ResearchEducationInputReviewSummaryDto):
    fixed_request: StrictStr = Field(min_length=1, max_length=2_000)
    canonical_input_sha256: StrictStr = Field(pattern=_SHA256.pattern)
    policy_version: Literal["RESEARCH_GENERAL_EDUCATION_DRAFT_V1"]
    policy_hash: StrictStr = Field(pattern=_SHA256.pattern)
    source_package_ref: StrictStr = Field(min_length=1, max_length=128)
    source_study_ref: StrictStr = Field(min_length=1, max_length=128)
    source_manifest_sha256: StrictStr = Field(pattern=_SHA256.pattern)
    prompt_id: StrictStr = Field(pattern=r"^PROMPT_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
    prompt_version: StrictStr = Field(min_length=1, max_length=64)
    prompt_sha256: StrictStr = Field(pattern=_SHA256.pattern)

    @field_validator("fixed_request", mode="after")
    @classmethod
    def request_is_the_fixed_research_request(cls, value: str) -> str:
        if value != FIXED_GENERAL_EDUCATION_REQUEST:
            raise ValueError("input review request is not the fixed request")
        return value

    @field_validator("source_package_ref", "source_study_ref", mode="after")
    @classmethod
    def source_refs_are_bounded_tokens(cls, value: str) -> str:
        if _INPUT_REVIEW_TOKEN.fullmatch(value) is None:
            raise ValueError("input review source reference is invalid")
        return value


class ResearchEducationInputReviewResolutionRequest(_StrictModel):
    expected_state_version: StrictInt = Field(ge=1, le=2)
    target: Literal["CONTINUATION_AUTHORIZED", "REJECTED", "REVOKED"]

    @model_validator(mode="after")
    def target_matches_expected_version(self):
        if (
            self.target in {"CONTINUATION_AUTHORIZED", "REJECTED"}
            and self.expected_state_version != 1
        ):
            raise ValueError("input review target is incompatible with its version")
        return self


class ResearchEducationOutputReviewSummaryDto(_StrictModel):
    output_review_ref: StrictStr = Field(pattern=r"^REOR_[0-9a-f]{32}$", max_length=37)
    job_ref: StrictStr = Field(pattern=r"^REJ_[0-9a-f]{64}$", max_length=68)
    task_ref: StrictStr = Field(min_length=1, max_length=128)
    session_ref: StrictStr = Field(min_length=1, max_length=128)
    generation_round: Literal[0, 1]
    status: Literal["PENDING", "REJECTED", "REVOKED", "CONSUMED"]
    state_version: StrictInt = Field(ge=1, le=2)
    expires_at: datetime
    created_at: datetime
    updated_at: datetime
    safety_action: Literal["REVIEW_REQUIRED"]
    reason_codes: list[Literal["CONTENT_CONTROVERSIAL"]] = Field(min_length=1, max_length=1)
    requires_human: Literal[True]
    purpose: Literal["RESEARCH_SIMULATION"]
    research_only: Literal[True]
    publication_status: Literal[_PUBLICATION_STATUS]
    student_feedback_eligible: Literal[False]

    @field_validator("expires_at", "created_at", "updated_at", mode="after")
    @classmethod
    def output_review_timestamps_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def review_status_matches_version(self):
        expected = 1 if self.status == "PENDING" else 2
        if (
            self.state_version != expected
            or self.expires_at <= self.created_at
            or self.updated_at < self.created_at
        ):
            raise ValueError("output review status, version, or timestamps are inconsistent")
        return self


class ResearchEducationOutputReviewListDto(_StrictModel):
    items: list[ResearchEducationOutputReviewSummaryDto]
    offset: StrictInt = Field(ge=0, le=100_000)
    limit: StrictInt = Field(ge=1, le=20)
    has_more: StrictBool

    @model_validator(mode="after")
    def page_is_consistent(self):
        if (
            len(self.items) > self.limit
            or len({item.output_review_ref for item in self.items}) != len(self.items)
        ):
            raise ValueError("output review page is inconsistent")
        return self


class ResearchEducationOutputReviewProvenanceDto(_StrictModel):
    generation_id: StrictStr = Field(pattern=r"^GEN_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
    retrieval_id: StrictStr = Field(pattern=r"^RETR_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
    retrieval_bundle_sha256: StrictStr = Field(pattern=_SHA256.pattern)
    policy_version: Literal["RESEARCH_GENERAL_EDUCATION_DRAFT_V1"]
    policy_hash: StrictStr = Field(pattern=_SHA256.pattern)
    safety_policy_version: Literal["safety-port-unversioned.v1"]
    source_package_ref: StrictStr = Field(min_length=1, max_length=255)
    source_study_ref: StrictStr = Field(min_length=1, max_length=255)
    source_manifest_sha256: StrictStr = Field(pattern=_SHA256.pattern)
    source_age_scope: Literal["14-17"]
    prompt_id: StrictStr = Field(pattern=r"^PROMPT_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
    prompt_version: StrictStr = Field(min_length=1, max_length=64)
    prompt_sha256: StrictStr = Field(pattern=_SHA256.pattern)
    model_id: StrictStr = Field(min_length=1, max_length=128)
    model_version: StrictStr = Field(min_length=1, max_length=128)
    model_digest_sha256: StrictStr = Field(pattern=_SHA256.pattern)
    runtime_version: StrictStr = Field(min_length=1, max_length=64)
    runtime_attempt_count: Literal[1]
    runtime_retry_count: Literal[0]
    runtime_fallback_count: Literal[0]
    runtime_fallback_attempted: Literal[False]
    runtime_local_only: Literal[True]
    input_safety_action: Literal[
        "PROCEED", "PROCEED_WITH_BOUNDARY", "BLOCK", "REVIEW_REQUIRED", "CRISIS_ROUTE"
    ]
    input_safety_reason_codes: list[StrictStr] = Field(min_length=1, max_length=16)
    retrieval_safety_action: Literal[
        "PROCEED", "PROCEED_WITH_BOUNDARY", "BLOCK", "REVIEW_REQUIRED", "CRISIS_ROUTE"
    ]
    retrieval_safety_reason_codes: list[StrictStr] = Field(min_length=1, max_length=16)
    output_safety_action: Literal["REVIEW_REQUIRED"]
    output_safety_reason_codes: tuple[Literal["CONTENT_CONTROVERSIAL"], ...] = Field(
        min_length=1, max_length=1
    )
    output_safety_requires_human: Literal[True]


class ResearchEducationOutputReviewPayloadDto(_StrictModel):
    schema_version: Literal["school-research-general-education-output-review.v1"]
    content: GenerationContent
    source_cards: list[ResearchGeneralEducationSourceCard] = Field(min_length=1, max_length=8)
    citations: list[SupportCitation] = Field(default_factory=list, max_length=8)
    citation_binding_status: Literal["NOT_EVALUATED_AT_OUTPUT_STOP"]
    provenance: ResearchEducationOutputReviewProvenanceDto


class ResearchEducationOutputReviewDetailDto(ResearchEducationOutputReviewSummaryDto):
    review_payload: ResearchEducationOutputReviewPayloadDto


class ResearchEducationOutputReviewResolutionRequest(_StrictModel):
    expected_state_version: StrictInt = Field(ge=1, le=1)
    target: Literal["REJECTED", "REVOKED", "CREATE_HELD_CANDIDATE"]


class ResearchEducationOutputReviewResolutionDto(_StrictModel):
    output_review: ResearchEducationOutputReviewSummaryDto
    candidate: ResearchEducationCandidateSummaryDto | None = None

    @model_validator(mode="after")
    def candidate_matches_resolution(self):
        if (self.output_review.status == "CONSUMED") != (self.candidate is not None):
            raise ValueError("output review resolution and candidate disagree")
        if self.candidate is not None and self.candidate.status != "HELD":
            raise ValueError("output review candidate must remain held")
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


class ResearchEducationInputReviewLineageDto(_StrictModel):
    input_review_ref: StrictStr = Field(pattern=r"^REIR_[0-9a-f]{32}$", max_length=37)
    status: Literal["CONSUMED"]
    state_version: Literal[3]


class ResearchEducationOutputReviewLineageDto(_StrictModel):
    output_review_ref: StrictStr = Field(pattern=r"^REOR_[0-9a-f]{32}$", max_length=37)
    status: Literal["CONSUMED"]
    state_version: Literal[2]
    reason_code: Literal["CONTENT_CONTROVERSIAL"]


class ResearchEducationCandidateReviewLineageDto(_StrictModel):
    generation_round: Literal[0, 1]
    input_review: ResearchEducationInputReviewLineageDto | None
    output_review: ResearchEducationOutputReviewLineageDto | None

    @model_validator(mode="after")
    def input_review_matches_generation_round(self):
        if (self.generation_round == 1) != (self.input_review is not None):
            raise ValueError("candidate and input review lineage disagree")
        return self


class ResearchEducationCandidateDetailDto(ResearchEducationCandidateSummaryDto):
    candidate_payload: ResearchGeneralEducationCandidatePayload
    review_lineage: ResearchEducationCandidateReviewLineageDto
