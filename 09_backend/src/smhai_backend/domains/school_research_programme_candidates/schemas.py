"""Closed DTOs for encrypted, task-level programme candidates."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

_PUBLICATION_STATUS = "not_approved_for_publication_or_operational_use"
_HEX = frozenset("0123456789abcdef")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProgrammeTaskScope(_StrictModel):
    school_id: StrictInt = Field(gt=0)
    task_id: StrictInt = Field(gt=0)
    class_id: StrictInt = Field(gt=0)
    task_binding_id: StrictInt = Field(gt=0)
    profile_version_id: StrictInt = Field(gt=0)
    profile_ref: StrictStr = Field(min_length=1, max_length=128)
    profile_version_number: StrictInt = Field(ge=1)
    profile_sha256: StrictStr = Field(min_length=64, max_length=64)
    response_origin: Literal["PUBLIC_OBSERVED", "MODEL_GENERATED"]

    @field_validator("profile_sha256")
    @classmethod
    def profile_hash_is_lowercase_sha256(cls, value: str) -> str:
        if any(char not in _HEX for char in value):
            raise ValueError("invalid profile pin")
        return value


class ProgrammeCitation(_StrictModel):
    citation_id: StrictStr = Field(pattern=r"^S[1-9][0-9]?$", max_length=3)
    source_title: StrictStr = Field(min_length=1, max_length=300)
    source_organization: StrictStr = Field(min_length=1, max_length=200)
    source_url: StrictStr = Field(min_length=8, max_length=2048)
    source_locator: StrictStr | None = Field(default=None, max_length=500)

    @field_validator("source_url")
    @classmethod
    def require_https_citation(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("citation URL is invalid")
        return value


class ProgrammeCandidateContent(_StrictModel):
    programme_ref: StrictStr = Field(min_length=1, max_length=128)
    content_origin: Literal["VERIFIED_SOURCE_METADATA", "LEGACY_MODEL_TEXT"] = (
        "LEGACY_MODEL_TEXT"
    )
    generation_mode: Literal["MODEL_SOURCE_SELECTION", "LEGACY_MODEL_AUTHORED_PASSAGES"] = (
        "LEGACY_MODEL_AUTHORED_PASSAGES"
    )
    title: StrictStr = Field(min_length=1, max_length=120, repr=False)
    body: StrictStr = Field(min_length=1, max_length=3600, repr=False)
    citations: list[ProgrammeCitation] = Field(min_length=1, max_length=12, repr=False)

    @field_validator("title", "body")
    @classmethod
    def reject_blank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("candidate text must not be blank")
        return value


class ProgrammeCandidateJobLease(_StrictModel):
    job_id: StrictInt = Field(gt=0, repr=False)
    school_id: StrictInt = Field(gt=0, repr=False)
    research_session_id: StrictInt = Field(gt=0, repr=False)
    lease_owner: StrictStr = Field(min_length=1, max_length=128, repr=False)
    lease_token: StrictStr = Field(min_length=1, max_length=128, repr=False)
    policy_version: StrictStr = Field(min_length=1, max_length=128)
    policy_hash: StrictStr = Field(min_length=64, max_length=64, repr=False)


class GeneratedProgrammeCandidate(_StrictModel):
    """Internal processor result; this type is never an HTTP request."""

    job: ProgrammeCandidateJobLease = Field(repr=False)
    trace_id: StrictStr = Field(pattern=r"^TRACE_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}$")
    task_scope: ProgrammeTaskScope
    study_ref: StrictStr = Field(min_length=1, max_length=128)
    source_study_ref: StrictStr = Field(min_length=1, max_length=128)
    study_policy_sha256: StrictStr = Field(min_length=64, max_length=64)
    processor_policy_sha256: StrictStr = Field(min_length=64, max_length=64, repr=False)
    programme_ref: StrictStr = Field(min_length=1, max_length=128)
    source_manifest_sha256: StrictStr = Field(min_length=64, max_length=64)
    source_set_sha256: StrictStr = Field(min_length=64, max_length=64)
    retrieval_id: StrictStr = Field(min_length=1, max_length=128)
    retrieval_bundle_sha256: StrictStr = Field(min_length=64, max_length=64)
    chunk_set_sha256: StrictStr = Field(min_length=64, max_length=64)
    prompt_ref: StrictStr = Field(min_length=1, max_length=128)
    prompt_version: StrictStr = Field(min_length=1, max_length=64)
    prompt_sha256: StrictStr = Field(min_length=64, max_length=64)
    model_ref: StrictStr = Field(min_length=1, max_length=128)
    model_digest_sha256: StrictStr = Field(min_length=64, max_length=64)
    runtime_version: StrictStr = Field(min_length=1, max_length=64)
    safety_policy_version: StrictStr = Field(min_length=1, max_length=64)
    input_safety_action: Literal["PROCEED", "PROCEED_WITH_BOUNDARY"]
    retrieval_safety_action: Literal["PROCEED", "PROCEED_WITH_BOUNDARY"]
    output_safety_action: Literal["PROCEED", "PROCEED_WITH_BOUNDARY"]
    claim_boundary_version: StrictStr = Field(min_length=1, max_length=64)
    claim_boundary_status: Literal["ACCEPTED"]
    output_boundary: Literal["STAFF_REFERENCE_ONLY"]
    content: ProgrammeCandidateContent = Field(repr=False)

    @field_validator(
        "study_policy_sha256",
        "processor_policy_sha256",
        "source_manifest_sha256",
        "source_set_sha256",
        "retrieval_bundle_sha256", "chunk_set_sha256", "prompt_sha256",
        "model_digest_sha256",
    )
    @classmethod
    def hashes_are_lowercase_sha256(cls, value: str) -> str:
        if any(char not in _HEX for char in value):
            raise ValueError("candidate pin is invalid")
        return value

    @field_validator("content")
    @classmethod
    def candidate_programme_matches_pin(cls, value: ProgrammeCandidateContent, info):
        programme_ref = info.data.get("programme_ref")
        if programme_ref is not None and value.programme_ref != programme_ref:
            raise ValueError("candidate programme pin does not match")
        return value

    @model_validator(mode="after")
    def processor_policy_matches_lease(self):
        if self.job.policy_hash != self.processor_policy_sha256:
            raise ValueError("processor policy pin does not match lease")
        if (
            self.content.content_origin != "VERIFIED_SOURCE_METADATA"
            or self.content.generation_mode != "MODEL_SOURCE_SELECTION"
        ):
            raise ValueError("candidate content origin is invalid")
        return self


class CandidateAdoptRequest(_StrictModel):
    expected_state_version: StrictInt = Field(ge=1, le=2_147_483_647)


class CandidateDiscardRequest(_StrictModel):
    expected_state_version: StrictInt = Field(ge=1, le=2_147_483_647)


class QueueProgrammeGenerationRequest(_StrictModel):
    """Empty closed request; the server selects the completed session."""


class QueueProgrammeGenerationBatchRequest(_StrictModel):
    """Bounded page of server-selected completed sessions for staff research."""

    limit: StrictInt = Field(default=25, ge=1, le=100)
    after_job_ref: StrictStr | None = Field(default=None, min_length=68, max_length=68)

    @field_validator("after_job_ref")
    @classmethod
    def cursor_is_a_job_reference(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("REJ_"):
            raise ValueError("batch cursor is invalid")
        if value is not None and any(char not in _HEX for char in value[4:]):
            raise ValueError("batch cursor is invalid")
        return value


class ProgrammeGenerationQueuedDto(_StrictModel):
    job_ref: StrictStr = Field(min_length=1, max_length=128)
    status: Literal[
        "QUEUED", "LEASED", "RETRY", "HELD", "ABSTAINED", "REVIEW_REQUIRED",
        "CRISIS_ROUTED", "FAILED", "CANCELLED",
    ]
    policy_version: Literal["RESEARCH_STAFF_PROGRAMME_POLICY_V1"]
    purpose: Literal["RESEARCH_SIMULATION"]
    research_only: Literal[True]
    publication_status: Literal[_PUBLICATION_STATUS]
    student_feedback_eligible: Literal[False]


class ProgrammeGenerationBatchQueuedDto(_StrictModel):
    """Stable, content-free receipt for one atomic batch of unique jobs."""

    batch_ref: StrictStr = Field(pattern=r"^REJBATCH_[0-9a-f]{64}$", max_length=73)
    job_refs: list[StrictStr] = Field(max_length=100)
    job_count: StrictInt = Field(ge=0, le=100)
    next_cursor: StrictStr | None = Field(default=None, min_length=68, max_length=68)
    policy_version: Literal["RESEARCH_STAFF_PROGRAMME_POLICY_V1"]
    purpose: Literal["RESEARCH_SIMULATION"]
    research_only: Literal[True]
    publication_status: Literal[_PUBLICATION_STATUS]
    student_feedback_eligible: Literal[False]

    @field_validator("job_refs", "next_cursor")
    @classmethod
    def references_are_job_ids(cls, value):
        values = value if isinstance(value, list) else [value]
        for ref in values:
            if ref is None:
                continue
            if len(ref) != 68 or not ref.startswith("REJ_") or any(
                char not in _HEX for char in ref[4:]
            ):
                raise ValueError("batch job reference is invalid")
        return value

    @model_validator(mode="after")
    def count_and_cursor_match_jobs(self):
        if self.job_count != len(self.job_refs):
            raise ValueError("batch job count does not match references")
        if self.next_cursor is not None and (
            not self.job_refs or self.next_cursor != self.job_refs[-1]
        ):
            raise ValueError("batch cursor must refer to its last job")
        return self


class _Output(_StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("created_at", mode="after", check_fields=False)
    @classmethod
    def normalize_created_at(cls, value):
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                return value.replace(tzinfo=UTC)
            return value.astimezone(UTC)
        return value


class ProgrammeCandidateSummaryDto(_Output):
    candidate_ref: StrictStr = Field(min_length=1, max_length=128)
    programme_ref: StrictStr = Field(min_length=1, max_length=128)
    status: Literal["HELD", "ADOPTED", "DISCARDED"]
    state_version: StrictInt = Field(ge=1, le=2)
    student_feedback_eligible: Literal[False]
    output_boundary: Literal["STAFF_REFERENCE_ONLY"]
    created_at: datetime


class ProgrammeCandidateDetailDto(ProgrammeCandidateSummaryDto):
    purpose: Literal["RESEARCH_SIMULATION"]
    research_only: Literal[True]
    psychological_interpretation_allowed: Literal[False]
    publication_status: Literal[_PUBLICATION_STATUS]
    content: ProgrammeCandidateContent


class ProgrammeCandidateListDto(_StrictModel):
    items: list[ProgrammeCandidateSummaryDto]


class ProgrammeCandidateGenerationResultDto(_StrictModel):
    """Non-sensitive internal receipt for a future worker; not routed over HTTP."""

    candidate_ref: StrictStr = Field(min_length=1, max_length=128)
    status: Literal["HELD"]
    state_version: StrictInt = Field(ge=1, le=2)
