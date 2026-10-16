"""Closed DTOs for non-personal, held general-education research drafts."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
)

from smhai_backend.domains.support.schemas import GenerationContent, SupportCitation
from smhai_backend.integrations.safety import SafetyAction

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CHUNK_ID = re.compile(r"^CHUNK_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
_REF = re.compile(r"^(?:RETR|GEN|PROMPT)_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
_SAFE_REASON = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ResearchGeneralEducationSourceCard(_StrictModel):
    """Exact source-package metadata retained with a cited excerpt."""

    chunk_id: StrictStr = Field(pattern=_CHUNK_ID.pattern)
    record_id: StrictStr = Field(min_length=1, max_length=128)
    source_id: StrictStr = Field(min_length=1, max_length=128)
    title: StrictStr = Field(min_length=1, max_length=512)
    organization: StrictStr = Field(min_length=1, max_length=256)
    canonical_url: StrictStr = Field(min_length=1, max_length=2048)
    record_locator: StrictStr = Field(min_length=1, max_length=1024)
    source_population_scope: StrictStr = Field(min_length=1, max_length=512)
    source_language: StrictStr = Field(min_length=1, max_length=16)
    license: StrictStr = Field(min_length=1, max_length=256)
    license_url: StrictStr = Field(min_length=1, max_length=2048)
    attribution: StrictStr = Field(min_length=1, max_length=2048)
    excerpt_sha256: StrictStr = Field(pattern=_SHA256.pattern)
    excerpt_text: StrictStr = Field(min_length=1, max_length=8000)
    consumer_age_min: StrictInt = Field(ge=14, le=17)
    consumer_age_max: StrictInt = Field(ge=14, le=17)

    @field_validator("canonical_url", "license_url")
    @classmethod
    def require_https_source_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("source URLs must preserve an HTTPS locator")
        return value


class ResearchGeneralEducationProvenance(_StrictModel):
    policy_version: Literal["RESEARCH_GENERAL_EDUCATION_DRAFT_V1"]
    policy_hash: StrictStr = Field(pattern=_SHA256.pattern)
    safety_policy_version: Literal["safety-port-unversioned.v1"]
    source_package_ref: StrictStr = Field(min_length=1)
    source_study_ref: StrictStr = Field(min_length=1)
    source_manifest_sha256: StrictStr = Field(pattern=_SHA256.pattern)
    source_age_scope: Literal["14-17"]
    retrieval_id: StrictStr = Field(pattern=r"^RETR_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
    retrieval_bundle_sha256: StrictStr = Field(pattern=_SHA256.pattern)
    cited_chunk_ids: list[StrictStr] = Field(min_length=1, max_length=8)
    generation_id: StrictStr = Field(pattern=r"^GEN_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
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
    input_safety_action: SafetyAction
    input_safety_reason_codes: list[StrictStr] = Field(min_length=1, max_length=16)
    retrieval_safety_action: SafetyAction
    retrieval_safety_reason_codes: list[StrictStr] = Field(min_length=1, max_length=16)
    output_safety_action: SafetyAction
    output_safety_reason_codes: list[StrictStr] = Field(min_length=1, max_length=16)

    def model_post_init(self, __context: object) -> None:
        if any(
            _SAFE_REASON.fullmatch(code) is None
            for codes in (
                self.input_safety_reason_codes,
                self.retrieval_safety_reason_codes,
                self.output_safety_reason_codes,
            )
            for code in codes
        ):
            raise ValueError("safety reason codes must be closed code tokens")
        if len(set(self.cited_chunk_ids)) != len(self.cited_chunk_ids):
            raise ValueError("cited chunk ids must be unique")
        if any(_CHUNK_ID.fullmatch(value) is None for value in self.cited_chunk_ids):
            raise ValueError("cited chunk id is invalid")


class ResearchGeneralEducationCandidatePayload(_StrictModel):
    schema_version: Literal["school-research-general-education-candidate.v1"]
    content: GenerationContent
    citations: list[SupportCitation] = Field(min_length=1, max_length=8)
    source_cards: list[ResearchGeneralEducationSourceCard] = Field(min_length=1, max_length=8)
    provenance: ResearchGeneralEducationProvenance

    @classmethod
    def from_closed_mapping(cls, value: object) -> ResearchGeneralEducationCandidatePayload:
        """Validate closed nested citations despite SupportCitation's legacy extra=ignore."""
        if not isinstance(value, dict):
            raise ValueError("candidate payload must be an object")
        allowed = set(SupportCitation.model_fields)
        citations = value.get("citations")
        if not isinstance(citations, list) or any(
            not isinstance(item, dict) or set(item) - allowed for item in citations
        ):
            raise ValueError("candidate citations must use the closed SupportCitation fields")
        return cls.model_validate(value, strict=True)

    def model_post_init(self, __context: object) -> None:
        citation_ids = [citation.chunk_id for citation in self.citations]
        card_ids = [card.chunk_id for card in self.source_cards]
        if (
            any(value is None for value in citation_ids)
            or len(set(citation_ids)) != len(citation_ids)
            or len(set(card_ids)) != len(card_ids)
            or set(citation_ids) != set(card_ids)
            or set(self.provenance.cited_chunk_ids) != set(citation_ids)
        ):
            raise ValueError("citations, source cards, and provenance do not bind exactly")
        for citation, card in zip(self.citations, self.source_cards, strict=True):
            if (
                citation.chunk_id != card.chunk_id
                or citation.title != card.title
                or citation.organization != card.organization
            ):
                raise ValueError("citation metadata differs from its source card")
            suffix = (
                f"; source population: {card.source_population_scope}; "
                f"source: {card.canonical_url}; license: {card.license} "
                f"({card.license_url}); attribution: {card.attribution}"
            )
            expected_locators = {
                f"{card.record_locator}{suffix}",
                f"record: {card.record_id}{suffix}",
            }
            if citation.locator not in expected_locators:
                raise ValueError("citation locator differs from its source-card metadata")
            if citation.source_hash != f"sha256:{card.excerpt_sha256}":
                raise ValueError("citation hash differs from source card excerpt hash")
            if (card.consumer_age_min, card.consumer_age_max) != (14, 17):
                raise ValueError("candidate source-card age scope must remain 14-17")


ResearchGeneralEducationStatus = Literal[
    "HELD", "ABSTAINED", "REVIEW_REQUIRED", "CRISIS_ROUTED", "FAILED"
]


class ResearchGeneralEducationInputReviewReceipt(_StrictModel):
    """Actual, content-free Safety evidence for the fixed research input stop."""

    schema_version: Literal["school-research-general-education-input-review.v1"]
    operation: Literal["INPUT"]
    action: Literal["REVIEW_REQUIRED"]
    reason_codes: tuple[Literal["CONTENT_CONTROVERSIAL"], ...] = Field(
        min_length=1, max_length=1
    )
    requires_human: Literal[True]
    decision_id: StrictStr = Field(pattern=r"^DEC_[A-Za-z0-9][A-Za-z0-9_.:-]{0,155}$")
    review_ref: StrictStr = Field(pattern=r"^REVIEW_[A-Za-z0-9][A-Za-z0-9_.:-]{0,152}$")
    trace_id: StrictStr = Field(pattern=r"^TRACE_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
    canonical_input_sha256: StrictStr = Field(pattern=_SHA256.pattern)
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


class ResearchGeneralEducationReviewedInputAuthorization(_StrictModel):
    """Typed, worker-only capability for one review-bound continuation job."""

    input_review_ref: StrictStr = Field(pattern=r"^REIR_[0-9a-f]{32}$")
    authorized_state_version: Literal[2]
    receipt: ResearchGeneralEducationInputReviewReceipt
    continuation_job_ref: StrictStr = Field(pattern=r"^REJ_[A-Za-z0-9][A-Za-z0-9_.:-]{0,155}$")
    continuation_trace_id: StrictStr = Field(pattern=r"^TRACE_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
    continuation_policy_version: StrictStr = Field(min_length=1, max_length=64)
    continuation_policy_hash: StrictStr = Field(pattern=_SHA256.pattern)
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def require_aware_expiry(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("review continuation expiry must include a timezone")
        return value


class ResearchGeneralEducationBoundaryDiagnostic(_StrictModel):
    """Content-free bounded metadata for the existing claim boundary matcher."""

    field_kind: Literal["SUMMARY", "OBSERVATION", "SUGGESTION"]
    field_index: StrictInt = Field(ge=0, le=12_000)
    category: Literal[
        "DIAGNOSIS",
        "CLINICAL",
        "SEVERITY",
        "PSYCHOMETRIC_SCORE",
        "OTHER_ALLOWLISTED",
    ]
    match_count: StrictInt = Field(ge=1, le=12_000)


# Closed projection of `08_safety-engine/policies/output.rego` decisions plus
# the current output-stage signal/failure tokens; unknown tokens omit diagnostics.
OutputSafetyReasonCode = Literal[
    "COMPONENT_UNAVAILABLE",
    "CONTENT_CONTROVERSIAL",
    "CONTENT_SAFE",
    "CONTENT_TRANSFORMED",
    "CONTENT_UNSAFE",
    "CRISIS_TEMPLATE_UNAVAILABLE",
    "DISCLOSURE_RESTRICTED",
    "EXPLICIT_CRISIS_SIGNAL",
    "JAILBREAK",
    "NO_BLOCKING_SIGNAL",
    "PII_DETECTED",
    "POLICY_EVALUATION_FAILED",
    "PROMPT_INJECTION",
    "REVIEW_QUEUE_FAILED",
    "SAFETY_SERVICE_UNAVAILABLE",
    "CLINICAL_OVERREACH",
]


class ResearchGeneralEducationOutputSafetyDiagnostic(_StrictModel):
    """Closed, content-free projection of an actual output Safety stop."""

    action: SafetyAction
    reason_codes: tuple[OutputSafetyReasonCode, ...] = Field(min_length=1, max_length=16)
    requires_human: StrictBool

    @field_validator("reason_codes")
    @classmethod
    def _unique_reason_codes(
        cls, value: tuple[OutputSafetyReasonCode, ...]
    ) -> tuple[OutputSafetyReasonCode, ...]:
        if len(set(value)) != len(value):
            raise ValueError("output Safety reason codes must be unique")
        return value

    @property
    def stopped_status(self) -> str | None:
        if self.action == "CRISIS_ROUTE":
            return "CRISIS_ROUTED"
        if self.action == "REVIEW_REQUIRED" or self.requires_human is True:
            return "REVIEW_REQUIRED"
        if self.action == "BLOCK":
            return "ABSTAINED"
        return None


class ResearchGeneralEducationOutputReviewProvenance(_StrictModel):
    """Safe generation/source pins retained with an eligible output review."""

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
    input_safety_action: SafetyAction
    input_safety_reason_codes: list[StrictStr] = Field(min_length=1, max_length=16)
    retrieval_safety_action: SafetyAction
    retrieval_safety_reason_codes: list[StrictStr] = Field(min_length=1, max_length=16)
    output_safety_action: Literal["REVIEW_REQUIRED"]
    output_safety_reason_codes: tuple[Literal["CONTENT_CONTROVERSIAL"], ...] = Field(
        min_length=1, max_length=1
    )
    output_safety_requires_human: Literal[True]

    def model_post_init(self, __context: object) -> None:
        if any(
            _SAFE_REASON.fullmatch(code) is None
            for codes in (
                self.input_safety_reason_codes,
                self.retrieval_safety_reason_codes,
            )
            for code in codes
        ):
            raise ValueError("Safety reason codes must be closed code tokens")


class ResearchGeneralEducationRetrievalSnapshot(_StrictModel):
    """Private encrypted snapshot needed to re-run original evidence checks."""

    retrieval_id: StrictStr = Field(pattern=r"^RETR_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
    label: Literal["SCHOOL_RESEARCH_STUDENT_SOURCE_PACKAGE"]
    chunks: list[dict[str, object]] = Field(min_length=1, max_length=8)
    trace: dict[str, object]


class ResearchGeneralEducationOutputReviewPayload(_StrictModel):
    """Encrypted original output plus exact retrieval input; never an HTTP DTO."""

    schema_version: Literal["school-research-general-education-output-review.v1"]
    content: GenerationContent
    retrieval_snapshot: ResearchGeneralEducationRetrievalSnapshot
    provenance: ResearchGeneralEducationOutputReviewProvenance
    safety_decision_id: StrictStr = Field(pattern=r"^DEC_[A-Za-z0-9][A-Za-z0-9_.:-]{0,155}$")
    safety_review_ref: StrictStr = Field(
        pattern=r"^REVIEW_[A-Za-z0-9][A-Za-z0-9_.:-]{0,152}$"
    )
    safety_trace_id: StrictStr = Field(pattern=r"^TRACE_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
    request_id: StrictStr = Field(pattern=r"^REQ_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
    canonical_input_sha256: StrictStr | None = Field(default=None, pattern=_SHA256.pattern)


class ResearchGeneralEducationOutcome(_StrictModel):
    status: ResearchGeneralEducationStatus
    reason_code: StrictStr = Field(pattern=r"^[A-Z][A-Z0-9_]{0,95}$")
    candidate: ResearchGeneralEducationCandidatePayload | None = None
    input_review: ResearchGeneralEducationInputReviewReceipt | None = None
    boundary_diagnostic: ResearchGeneralEducationBoundaryDiagnostic | None = None
    output_safety_diagnostic: ResearchGeneralEducationOutputSafetyDiagnostic | None = None
    output_review_payload: ResearchGeneralEducationOutputReviewPayload | None = None
    private_output_safety_failure: Literal[
        "TIMEOUT", "TRANSPORT", "UPSTREAM_HTTP", "INVALID_RESPONSE", "OTHER"
    ] | None = Field(default=None, exclude=True)

    def model_post_init(self, __context: object) -> None:
        if (self.status == "HELD") != (self.candidate is not None):
            raise ValueError("only a held outcome may contain a candidate")
        if self.input_review is not None and (
            self.status != "REVIEW_REQUIRED" or self.reason_code != "INPUT_SAFETY_STOP"
        ):
            raise ValueError("input review evidence is only valid for a stopped input outcome")
        if self.boundary_diagnostic is not None and (
            self.status != "ABSTAINED"
            or self.reason_code != "RESEARCH_CLAIM_BOUNDARY_REJECTED"
        ):
            raise ValueError("boundary diagnostics are only valid for a boundary rejection")
        if self.output_safety_diagnostic is not None and (
            type(self.output_safety_diagnostic)
            is not ResearchGeneralEducationOutputSafetyDiagnostic
            or self.reason_code != "OUTPUT_SAFETY_STOP"
            or self.output_safety_diagnostic.stopped_status != self.status
        ):
            raise ValueError("output Safety diagnostics must match the actual stop outcome")
        if self.private_output_safety_failure is not None and (
            self.status != "FAILED" or self.reason_code != "OUTPUT_SAFETY_UNAVAILABLE"
        ):
            raise ValueError(
                "private output dependency diagnostics require an output Safety failure"
            )
        if self.output_review_payload is not None and (
            self.status != "REVIEW_REQUIRED"
            or self.reason_code != "OUTPUT_SAFETY_STOP"
            or self.output_safety_diagnostic is None
            or self.output_safety_diagnostic.action != "REVIEW_REQUIRED"
            or self.output_safety_diagnostic.reason_codes != ("CONTENT_CONTROVERSIAL",)
            or self.output_safety_diagnostic.requires_human is not True
            or self.output_review_payload.provenance.output_safety_action
            != self.output_safety_diagnostic.action
            or self.output_review_payload.provenance.output_safety_reason_codes
            != self.output_safety_diagnostic.reason_codes
        ):
            raise ValueError("output review payload must match the exact eligible Safety stop")
