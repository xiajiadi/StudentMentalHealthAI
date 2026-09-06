"""Support, retrieval, generation, and report DTOs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TargetRole = Literal["student", "teacher", "parent", "admin"]


class SupportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_id: str = Field(pattern=r"^ASSESS_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    target_role: TargetRole
    message: str = Field(min_length=1, max_length=20_000)
    language: str = Field(default="zh-CN", min_length=2, max_length=32)
    purpose: Literal["education_support"] = "education_support"


class RetrievalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_id: str = Field(pattern=r"^ASSESS_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    target_role: TargetRole
    query: str = Field(min_length=1, max_length=20_000)
    top_k: int = Field(default=5, ge=1, le=100)


class PromptRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_id: str = Field(pattern=r"^PROMPT_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    prompt_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class RetrievalRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retrieval_id: str = Field(pattern=r"^RETR_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    chunk_ids: list[str] = Field(min_length=1)


class ModelPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(pattern=r"^MODEL_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    provider_class: Literal["local", "mock"]


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["generation.v1"]
    generation_id: str = Field(pattern=r"^GEN_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    assessment_id: str = Field(pattern=r"^ASSESS_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    subject_id: str = Field(pattern=r"^SUBJ_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    target_role: TargetRole
    purpose: Literal["education_support"]
    language: str = Field(min_length=2)
    safety_mode: Literal["standard", "restricted"]
    retrieval: RetrievalRef
    prompt_ref: PromptRef
    model_policy: ModelPolicy


class SafetyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_id: str = Field(pattern=r"^ASSESS_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    generation_candidate: dict[str, Any] | None = None


class Suggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    source_chunk_ids: list[str] = Field(min_length=1)


class GenerationContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    observations: list[str]
    suggestions: list[Suggestion]
    disclaimer: str = Field(min_length=1)


class SupportCitation(BaseModel):
    """Citation identity retained from RAG through persistence and reports."""

    model_config = ConfigDict(extra="ignore")

    citation_id: str
    chunk_id: str | None = None
    document_id: str | None = None
    title: str | None = None
    organization: str | None = None
    locator: str | None = None
    rank: int | None = Field(default=None, ge=1)
    source_version: str | None = None
    source_hash: str | None = None


class GenerationSafetyProjection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    precheck: Literal["passed", "warn", "blocked", "needs_review"]
    postcheck: Literal["passed", "warn", "blocked", "needs_review"]
    reason_codes: list[str]
    human_review_required: bool


class GenerationProvenanceProjection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    assessment_id: str
    retrieval_id: str
    prompt_id: str
    prompt_version: str
    model_id: str | None
    model_version: str | None
    runtime_version: str | None
    generation_status: Literal["EXECUTED", "NOT_RUN"] = "EXECUTED"
    candidate_source: Literal[
        "MODEL_EXECUTED", "CONTROLLED_SYNTHETIC", "NOT_RUN"
    ] = "MODEL_EXECUTED"


class GenerationReviewProjection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["pending", "approved", "rejected", "not_required", "closed"]
    reviewer_id: str | None
    reviewed_at: str | None


class GenerationProjection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: Literal["generation.v1"]
    generation_id: str
    status: str
    target_role: TargetRole
    content: GenerationContent | None
    safety: GenerationSafetyProjection
    provenance: GenerationProvenanceProjection
    review: GenerationReviewProjection
    created_at: str


class SupportResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    safety_action: str
    normal_generation: bool
    generation: GenerationProjection
    report_id: str
    content: GenerationContent | None = None
    citations: list[SupportCitation] = Field(default_factory=list)
    review_reference: str | None = None
    crisis_response: str | None = None
    trace_id: str
    synthetic_fixture_only: bool = True
    integration_labels: dict[str, str]


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]
    reviewer_id: str | None = Field(default=None, min_length=1, max_length=160)
    note_code: str | None = Field(default=None, min_length=1, max_length=160)


class ReportDto(BaseModel):
    model_config = ConfigDict(extra="ignore")

    report_id: str
    assessment_id: str
    status: str
    generation_ids: list[str]
    review_status: str
    review_id: str | None = None
    generation: GenerationProjection | None = None
    citations: list[SupportCitation] = Field(default_factory=list)


class ReviewProjectionDto(BaseModel):
    model_config = ConfigDict(extra="ignore")

    review_id: str
    report_id: str
    assessment_id: str
    generation_id: str
    status: str
    reason_codes: list[str]
    safety_action: str
    safety_review_case_id: str | None = None
