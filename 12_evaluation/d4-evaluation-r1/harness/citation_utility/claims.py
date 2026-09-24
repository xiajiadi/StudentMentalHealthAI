"""Evaluation-only claim records for D4 citation-support review.

This module deliberately stays outside the product path.  It models the
annotation boundary described by D4SUP-01..06: citation identity, textual
entailment, and population/role/purpose applicability are separate pieces of
evidence.  A valid citation therefore never becomes ``SUPPORTS`` by itself.

The records are plain, deterministic data objects.  They retain the complete
answer and Python half-open character offsets so a reviewer can always locate
the annotated text in the original answer.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Final, Literal

try:  # Normal import when the evaluation root is on sys.path.
    from harness.foundation.hashing import canonical_sha256_tag
except ModuleNotFoundError:  # pragma: no cover - package-relative fallback
    from ..foundation.hashing import canonical_sha256_tag


SUPPORT_LABELS: Final[tuple[str, ...]] = (
    "SUPPORTS",
    "PARTIALLY_SUPPORTS",
    "UNSUPPORTED",
    "CONTRADICTS",
    "OUT_OF_SCOPE",
)
TEXTUAL_ENTAILMENT_LABELS: Final[tuple[str, ...]] = (
    "SUPPORTS",
    "PARTIALLY_SUPPORTS",
    "UNSUPPORTED",
    "CONTRADICTS",
)
CLAIM_TYPES: Final[tuple[str, ...]] = (
    "FACTUAL_VERIFIABLE",
    "EVIDENCE_GROUNDED_ACTION",
    "SCOPE_LIMITATION",
    "CONVERSATIONAL_GLUE",
)
APPLICABILITY_STATUSES: Final[tuple[str, ...]] = (
    "APPLICABLE",
    "MISMATCH",
    "UNKNOWN",
)
REVIEW_STATES: Final[tuple[str, ...]] = (
    "DRAFT",
    "HUMAN_REVIEW_REQUIRED",
    "HUMAN_APPROVED",
    "HUMAN_REJECTED",
    "DISPUTED",
)
REVIEW_SOURCES: Final[tuple[str, ...]] = (
    "NONE",
    "HUMAN_REVIEWER",
    "TEST_SIMULATION",
)
TEST_FIXTURE_SIMULATED_APPROVAL: Final[str] = "TEST_FIXTURE_SIMULATED_APPROVAL"
TEST_FIXTURE_SIMULATED_REJECTION: Final[str] = "TEST_FIXTURE_SIMULATED_REJECTION"
TRANSFORMATION_OPERATIONS: Final[tuple[str, ...]] = (
    "ORIGIN",
    "MERGE",
    "SPLIT",
    "EDIT",
    "EXCLUDE",
)
CITATION_IDENTITY_STATUSES: Final[tuple[str, ...]] = (
    "VALID",
    "UNKNOWN",
    "NONE",
)
DATA_CLASSIFICATION: Final[tuple[str, ...]] = (
    "SYNTHETIC_EVALUATION_ONLY",
    "NOT_D2_PUBLICATION",
    "NOT_PRODUCTION_KNOWLEDGE",
    "NOT_REAL_STUDENT_DATA",
    "NOT_PSYCHOLOGY_VALIDATION",
)

SupportLabel = Literal[
    "SUPPORTS",
    "PARTIALLY_SUPPORTS",
    "UNSUPPORTED",
    "CONTRADICTS",
    "OUT_OF_SCOPE",
]
TextualEntailment = Literal[
    "SUPPORTS",
    "PARTIALLY_SUPPORTS",
    "UNSUPPORTED",
    "CONTRADICTS",
]
ClaimType = Literal[
    "FACTUAL_VERIFIABLE",
    "EVIDENCE_GROUNDED_ACTION",
    "SCOPE_LIMITATION",
    "CONVERSATIONAL_GLUE",
]


def _require_non_empty_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _unique_strings(values: Iterable[str], field_name: str) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        _require_non_empty_text(value, field_name)
        if value in seen:
            raise ValueError(f"{field_name} must not contain duplicates: {value!r}")
        seen.add(value)
        result.append(value)
    return tuple(result)


def _span_dict(start: int, end: int) -> dict[str, Any]:
    return {
        "start": start,
        "end": end,
        "end_inclusive": False,
        "unit": "python_codepoint",
    }


def _validate_span(start: int, end: int, answer: str) -> None:
    if isinstance(start, bool) or not isinstance(start, int):
        raise TypeError("span start must be an integer")
    if isinstance(end, bool) or not isinstance(end, int):
        raise TypeError("span end must be an integer")
    if start < 0 or end <= start or end > len(answer):
        raise ValueError(
            f"span must be a non-empty half-open range within the answer: {start}:{end}"
        )


def citation_requirement_for(
    claim_type: str,
    *,
    required: bool | None = None,
    policy_id: str | None = None,
    reason: str | None = None,
    citation_required: bool | None = None,
    policy_override: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an explicit citation policy for a claim type.

    The default for ``SCOPE_LIMITATION`` is an optional source because an
    ordinary boundary statement can be a local evaluation guard.  A
    source-dependent scope claim must pass an explicit override containing all
    three fields: ``required``, ``policy_id``, and ``reason``.  This keeps the
    choice visible in both machine records and manual-review packets.
    """

    rules: dict[str, tuple[bool, str, str]] = {
        "FACTUAL_VERIFIABLE": (
            True,
            "Externally checkable factual, causal, risk, or population content requires a source.",
            "FACTUAL_CLAIM_REQUIRES_SOURCE",
        ),
        "EVIDENCE_GROUNDED_ACTION": (
            True,
            "The action is presented as grounded in educational evidence and must be traceable to a source.",
            "EVIDENCE_GROUNDED_ACTION_REQUIRES_SOURCE",
        ),
        "SCOPE_LIMITATION": (
            False,
            "A scope or uncertainty boundary is recorded as an evaluation guard, not as a source-backed fact.",
            "SCOPE_BOUNDARY_DOES_NOT_REQUIRE_SOURCE",
        ),
        "CONVERSATIONAL_GLUE": (
            False,
            "Conversational glue does not assert externally checkable content.",
            "CONVERSATIONAL_GLUE_DOES_NOT_REQUIRE_SOURCE",
        ),
    }
    try:
        default_required, default_reason, default_policy_id = rules[claim_type]
    except KeyError as exc:
        raise ValueError(f"unsupported claim type: {claim_type!r}") from exc

    if policy_override is not None:
        if any(
            item is not None
            for item in (required, policy_id, reason, citation_required)
        ):
            raise ValueError(
                "policy_override cannot be combined with individual overrides"
            )
        required = policy_override.get(
            "required", policy_override.get("citation_required")
        )
        policy_id = policy_override.get("policy_id")
        reason = policy_override.get("reason")

    if citation_required is not None:
        if required is not None and required != citation_required:
            raise ValueError("required and citation_required disagree")
        required = citation_required

    has_override = any(item is not None for item in (required, policy_id, reason))
    if not has_override:
        return {
            "required": default_required,
            "reason": default_reason,
            "policy_id": default_policy_id,
        }
    if not isinstance(required, bool):
        raise TypeError("an explicit citation policy requires boolean required")
    if not isinstance(policy_id, str) or not policy_id.strip():
        raise ValueError("an explicit citation policy requires non-empty policy_id")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("an explicit citation policy requires non-empty reason")
    return {"required": required, "reason": reason, "policy_id": policy_id}


def _coerce_applicability(value: Any, field_name: str) -> Applicability:
    if isinstance(value, Applicability):
        return value
    if isinstance(value, str):
        return Applicability(
            value, reason=f"{field_name} status supplied by annotation"
        )
    if isinstance(value, Mapping):
        return Applicability(
            status=value.get("status"),
            reason=value.get("reason"),
            expected_scope=value.get("expected_scope"),
            evidence_scope=value.get("evidence_scope", ()),
        )
    raise ValueError(f"{field_name} must be an Applicability or mapping")


@dataclass(frozen=True)
class Applicability:
    """One independent population, role, or purpose applicability judgement."""

    status: str
    reason: str
    expected_scope: str | None = None
    evidence_scope: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in APPLICABILITY_STATUSES:
            raise ValueError(f"unsupported applicability status: {self.status!r}")
        _require_non_empty_text(self.reason, "applicability reason")
        if self.expected_scope is not None:
            _require_non_empty_text(self.expected_scope, "expected_scope")
        object.__setattr__(
            self,
            "evidence_scope",
            _unique_strings(self.evidence_scope, "evidence_scope"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "expected_scope": self.expected_scope,
            "evidence_scope": list(self.evidence_scope),
        }


@dataclass(frozen=True)
class TransformationTrace:
    """Trace one claim transformation back to earlier text or claims."""

    operation: str
    source_claim_ids: tuple[str, ...]
    reason: str
    source_spans: tuple[dict[str, Any], ...] = ()
    result_span: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.operation not in TRANSFORMATION_OPERATIONS:
            raise ValueError(
                f"unsupported transformation operation: {self.operation!r}"
            )
        _require_non_empty_text(self.reason, "transformation reason")
        object.__setattr__(
            self,
            "source_claim_ids",
            _unique_strings(self.source_claim_ids, "source_claim_ids"),
        )
        if self.operation != "ORIGIN" and not self.source_claim_ids:
            raise ValueError(
                f"{self.operation} transformations require source_claim_ids"
            )
        normalised_sources = tuple(dict(span) for span in self.source_spans)
        for span in normalised_sources:
            _validate_span_mapping(span, "source_spans")
        object.__setattr__(self, "source_spans", normalised_sources)
        if self.result_span is not None:
            result = dict(self.result_span)
            _validate_span_mapping(result, "result_span")
            object.__setattr__(self, "result_span", result)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "source_claim_ids": list(self.source_claim_ids),
            "source_spans": [dict(span) for span in self.source_spans],
            "result_span": dict(self.result_span)
            if self.result_span is not None
            else None,
            "reason": self.reason,
        }


def _validate_span_mapping(value: Mapping[str, Any], field_name: str) -> None:
    if set(value) - {"start", "end", "end_inclusive", "unit"}:
        raise ValueError(f"{field_name} contains unknown span fields")
    start = value.get("start")
    end = value.get("end")
    if isinstance(start, bool) or not isinstance(start, int):
        raise TypeError(f"{field_name}.start must be an integer")
    if isinstance(end, bool) or not isinstance(end, int) or end < start:
        raise ValueError(f"{field_name}.end must be an integer >= start")
    if (
        value.get("end_inclusive") is not False
        or value.get("unit") != "python_codepoint"
    ):
        raise ValueError(f"{field_name} must use Python half-open codepoint offsets")


def _coerce_trace(value: Any) -> TransformationTrace:
    if isinstance(value, TransformationTrace):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("traceability entries must be mappings")
    return TransformationTrace(
        operation=value.get("operation"),
        source_claim_ids=value.get("source_claim_ids", ()),
        source_spans=value.get("source_spans", ()),
        result_span=value.get("result_span"),
        reason=value.get("reason"),
    )


@dataclass(frozen=True)
class ReviewMetadata:
    """Human-review state with an explicit boundary for test simulations."""

    state: str = "HUMAN_REVIEW_REQUIRED"
    decision_source: str = "NONE"
    reviewer_id: str | None = None
    reviewed_at: str | None = None
    evidence_ref: str | None = None
    simulated_outcome: str | None = None

    def __post_init__(self) -> None:
        if self.state not in REVIEW_STATES:
            raise ValueError(f"unsupported review state: {self.state!r}")
        if self.decision_source not in REVIEW_SOURCES:
            raise ValueError(f"unsupported review source: {self.decision_source!r}")
        for field_name, value in (
            ("reviewer_id", self.reviewer_id),
            ("reviewed_at", self.reviewed_at),
            ("evidence_ref", self.evidence_ref),
        ):
            if value is not None:
                _require_non_empty_text(value, field_name)

        if self.state in {"HUMAN_APPROVED", "HUMAN_REJECTED"}:
            if self.decision_source == "TEST_SIMULATION":
                expected = (
                    TEST_FIXTURE_SIMULATED_APPROVAL
                    if self.state == "HUMAN_APPROVED"
                    else TEST_FIXTURE_SIMULATED_REJECTION
                )
                if self.simulated_outcome != expected:
                    raise ValueError(
                        f"test-only {self.state} requires simulated_outcome={expected}"
                    )
            elif self.decision_source != "HUMAN_REVIEWER":
                raise ValueError(
                    f"{self.state} requires decision_source=HUMAN_REVIEWER"
                )
            elif not self.reviewer_id or not self.reviewed_at or not self.evidence_ref:
                raise ValueError(
                    f"{self.state} requires reviewer_id, reviewed_at, and evidence_ref"
                )
        if self.decision_source == "TEST_SIMULATION":
            if self.state not in {"HUMAN_APPROVED", "HUMAN_REJECTED"}:
                raise ValueError(
                    "TEST_SIMULATION must use a separate simulated approval/rejection state"
                )
            if self.simulated_outcome not in {
                TEST_FIXTURE_SIMULATED_APPROVAL,
                TEST_FIXTURE_SIMULATED_REJECTION,
            }:
                raise ValueError(
                    "TEST_SIMULATION requires an explicit TEST_FIXTURE_SIMULATED_* outcome"
                )
        elif self.simulated_outcome is not None:
            raise ValueError(
                "simulated_outcome requires decision_source=TEST_SIMULATION"
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ReviewMetadata:
        review = cls(
            state=value.get(
                "state", value.get("review_state", "HUMAN_REVIEW_REQUIRED")
            ),
            decision_source=value.get("decision_source", "NONE"),
            reviewer_id=value.get("reviewer_id"),
            reviewed_at=value.get("reviewed_at"),
            evidence_ref=value.get("evidence_ref"),
            simulated_outcome=value.get("simulated_outcome"),
        )
        if "human_gold" in value and value["human_gold"] != review.is_human_gold:
            raise ValueError("review.human_gold does not match reviewer provenance")
        if "test_only" in value and value["test_only"] != review.is_test_only:
            raise ValueError("review.test_only does not match decision_source")
        return review

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "decision_source": self.decision_source,
            "reviewer_id": self.reviewer_id,
            "reviewed_at": self.reviewed_at,
            "evidence_ref": self.evidence_ref,
            "simulated_outcome": self.simulated_outcome,
            "human_gold": self.is_human_gold,
            "test_only": self.is_test_only,
        }

    @property
    def is_test_only(self) -> bool:
        """Whether the decision is a fixture simulation rather than human gold."""

        return self.decision_source == "TEST_SIMULATION"

    @property
    def is_human_gold(self) -> bool:
        """Whether default human-gold metrics may include this decision."""

        return (
            self.decision_source == "HUMAN_REVIEWER"
            and self.state in {"HUMAN_APPROVED", "HUMAN_REJECTED"}
            and bool(self.reviewer_id and self.reviewed_at and self.evidence_ref)
        )


def _coerce_review(value: Any) -> ReviewMetadata:
    if isinstance(value, ReviewMetadata):
        return value
    if value is None:
        return ReviewMetadata()
    if isinstance(value, Mapping):
        return ReviewMetadata.from_mapping(value)
    raise ValueError("review must be ReviewMetadata or a mapping")


def _coerce_classification(value: Iterable[str] | None) -> tuple[str, ...]:
    result = tuple(value) if value is not None else DATA_CLASSIFICATION
    if result != DATA_CLASSIFICATION:
        raise ValueError(
            "evaluation records must carry the exact synthetic-only classification markers"
        )
    return result


@dataclass(frozen=True)
class ClaimRecord:
    """One annotated answer claim, suitable for deterministic review export."""

    claim_id: str
    case_id: str
    original_answer: str
    span_start: int
    span_end: int
    text: str
    claim_type: str
    citation_required: bool | None = None
    citation_reason: str = ""
    citation_policy_id: str | None = None
    cited_chunk_ids: tuple[str, ...] = ()
    textual_entailment: str = "UNSUPPORTED"
    population_applicability: Applicability | Mapping[str, Any] | str = field(
        default_factory=lambda: Applicability(
            "UNKNOWN", "Population applicability has not yet been reviewed."
        )
    )
    role_applicability: Applicability | Mapping[str, Any] | str = field(
        default_factory=lambda: Applicability(
            "UNKNOWN", "Role applicability has not yet been reviewed."
        )
    )
    purpose_applicability: Applicability | Mapping[str, Any] | str = field(
        default_factory=lambda: Applicability(
            "UNKNOWN", "Purpose applicability has not yet been reviewed."
        )
    )
    support_label: str | None = None
    contradiction_flag: bool = False
    contradiction_reason: str | None = None
    review: ReviewMetadata | Mapping[str, Any] | None = None
    traceability: tuple[TransformationTrace | Mapping[str, Any], ...] = ()
    excluded: bool = False
    data_classification: tuple[str, ...] = DATA_CLASSIFICATION
    content_hash: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty_text(self.claim_id, "claim_id")
        _require_non_empty_text(self.case_id, "case_id")
        if not isinstance(self.original_answer, str):
            raise TypeError("original_answer must be a string")
        _validate_span(self.span_start, self.span_end, self.original_answer)
        if self.text != self.original_answer[self.span_start : self.span_end]:
            raise ValueError("text must equal original_answer[span_start:span_end]")
        if not self.text.strip():
            raise ValueError("claim text cannot be whitespace only")
        if self.claim_type not in CLAIM_TYPES:
            raise ValueError(f"unsupported claim type: {self.claim_type!r}")

        policy = citation_requirement_for(
            self.claim_type,
            required=self.citation_required,
            policy_id=self.citation_policy_id,
            reason=self.citation_reason or None,
        )
        object.__setattr__(self, "citation_required", policy["required"])
        object.__setattr__(self, "citation_reason", policy["reason"])
        object.__setattr__(self, "citation_policy_id", policy["policy_id"])

        if self.citation_required and not isinstance(self.cited_chunk_ids, Iterable):
            raise ValueError("cited_chunk_ids must be iterable")
        object.__setattr__(
            self,
            "cited_chunk_ids",
            _unique_strings(self.cited_chunk_ids, "cited_chunk_ids"),
        )
        if self.textual_entailment not in TEXTUAL_ENTAILMENT_LABELS:
            raise ValueError(
                f"unsupported textual entailment: {self.textual_entailment!r}"
            )

        population = _coerce_applicability(
            self.population_applicability, "population_applicability"
        )
        role = _coerce_applicability(self.role_applicability, "role_applicability")
        purpose = _coerce_applicability(
            self.purpose_applicability, "purpose_applicability"
        )
        object.__setattr__(self, "population_applicability", population)
        object.__setattr__(self, "role_applicability", role)
        object.__setattr__(self, "purpose_applicability", purpose)

        derived_label = derive_support_label(
            self.textual_entailment,
            population=population,
            role=role,
            purpose=purpose,
        )
        if self.support_label is not None and self.support_label != derived_label:
            raise ValueError(
                f"support_label must preserve textual/applicability separation: expected {derived_label}, got {self.support_label}"
            )
        object.__setattr__(self, "support_label", derived_label)

        contradiction = self.textual_entailment == "CONTRADICTS"
        if self.contradiction_flag and not contradiction:
            raise ValueError(
                "contradiction_flag can only be true when textual_entailment=CONTRADICTS"
            )
        object.__setattr__(self, "contradiction_flag", contradiction)
        if contradiction:
            reason_value = (
                self.contradiction_reason or "Cited evidence conflicts with the claim."
            )
            _require_non_empty_text(reason_value, "contradiction_reason")
            object.__setattr__(self, "contradiction_reason", reason_value)
        elif self.contradiction_reason is not None:
            raise ValueError("contradiction_reason requires textual contradiction")

        review = _coerce_review(self.review)
        object.__setattr__(self, "review", review)
        classification = _coerce_classification(self.data_classification)
        object.__setattr__(self, "data_classification", classification)

        traces = tuple(_coerce_trace(item) for item in self.traceability)
        if not traces:
            traces = (
                TransformationTrace(
                    operation="ORIGIN",
                    source_claim_ids=(),
                    source_spans=(_span_dict(self.span_start, self.span_end),),
                    result_span=_span_dict(self.span_start, self.span_end),
                    reason="Claim originates from the preserved answer span.",
                ),
            )
        object.__setattr__(self, "traceability", traces)

        if not isinstance(self.excluded, bool):
            raise TypeError("excluded must be boolean")
        payload = self._payload_dict()
        expected_hash = canonical_sha256_tag(payload, self_field="content_hash")
        if self.content_hash is not None and self.content_hash != expected_hash:
            raise ValueError(
                f"content_hash mismatch: expected {expected_hash}, got {self.content_hash}"
            )
        object.__setattr__(self, "content_hash", expected_hash)

    def _payload_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "citation-support.v1",
            "record_type": "claim",
            "claim_id": self.claim_id,
            "case_id": self.case_id,
            "original_answer": self.original_answer,
            "answer_span": _span_dict(self.span_start, self.span_end),
            "text": self.text,
            "claim_type": self.claim_type,
            "citation_required": self.citation_required,
            "citation_reason": self.citation_reason,
            "citation_policy_id": self.citation_policy_id,
            "citation_requirement": {
                "required": self.citation_required,
                "reason": self.citation_reason,
                "policy_id": self.citation_policy_id,
            },
            "cited_chunk_ids": list(self.cited_chunk_ids),
            "textual_entailment": self.textual_entailment,
            "population_applicability": self.population_applicability.to_dict(),
            "role_applicability": self.role_applicability.to_dict(),
            "purpose_applicability": self.purpose_applicability.to_dict(),
            "applicability": {
                "population": self.population_applicability.to_dict(),
                "role": self.role_applicability.to_dict(),
                "purpose": self.purpose_applicability.to_dict(),
            },
            "support_label": self.support_label,
            "contradiction": {
                "flag": self.contradiction_flag,
                "reason": self.contradiction_reason,
            },
            "review": self.review.to_dict(),
            "traceability": [trace.to_dict() for trace in self.traceability],
            "excluded": self.excluded,
            "data_classification": list(self.data_classification),
        }

    def to_dict(self) -> dict[str, Any]:
        value = self._payload_dict()
        value["content_hash"] = self.content_hash
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ClaimRecord:
        span = value.get("answer_span")
        if not isinstance(span, Mapping):
            raise TypeError("claim answer_span must be an object")
        requirement = value.get("citation_requirement", {})
        if not isinstance(requirement, Mapping):
            requirement = {}
        if (
            "citation_required" in value
            and "required" in requirement
            and value["citation_required"] != requirement["required"]
        ):
            raise ValueError(
                "citation_required disagrees with citation_requirement.required"
            )
        if (
            "citation_reason" in value
            and "reason" in requirement
            and value["citation_reason"] != requirement["reason"]
        ):
            raise ValueError(
                "citation_reason disagrees with citation_requirement.reason"
            )
        if (
            "citation_policy_id" in value
            and "policy_id" in requirement
            and value["citation_policy_id"] != requirement["policy_id"]
        ):
            raise ValueError(
                "citation_policy_id disagrees with citation_requirement.policy_id"
            )
        applicability = value.get("applicability", {})
        if not isinstance(applicability, Mapping):
            applicability = {}
        for direct_name, nested_name in (
            ("population_applicability", "population"),
            ("role_applicability", "role"),
            ("purpose_applicability", "purpose"),
        ):
            if (
                direct_name in value
                and nested_name in applicability
                and value[direct_name] != applicability[nested_name]
            ):
                raise ValueError(
                    f"{direct_name} disagrees with applicability.{nested_name}"
                )
        review = value.get("review")
        return cls(
            claim_id=value.get("claim_id"),
            case_id=value.get("case_id"),
            original_answer=value.get("original_answer"),
            span_start=span.get("start"),
            span_end=span.get("end"),
            text=value.get("text"),
            claim_type=value.get("claim_type"),
            citation_required=value.get(
                "citation_required", requirement.get("required")
            ),
            citation_reason=value.get("citation_reason", requirement.get("reason", "")),
            citation_policy_id=value.get(
                "citation_policy_id", requirement.get("policy_id")
            ),
            cited_chunk_ids=value.get("cited_chunk_ids", ()),
            textual_entailment=value.get("textual_entailment"),
            population_applicability=value.get(
                "population_applicability", applicability.get("population")
            ),
            role_applicability=value.get(
                "role_applicability", applicability.get("role")
            ),
            purpose_applicability=value.get(
                "purpose_applicability", applicability.get("purpose")
            ),
            support_label=value.get("support_label"),
            contradiction_flag=(value.get("contradiction") or {}).get("flag", False),
            contradiction_reason=(value.get("contradiction") or {}).get("reason"),
            review=review,
            traceability=value.get("traceability", ()),
            excluded=value.get("excluded", False),
            data_classification=value.get("data_classification"),
            content_hash=value.get("content_hash"),
        )


def derive_support_label(
    textual_entailment: str,
    *,
    population: Applicability | Mapping[str, Any] | str,
    role: Applicability | Mapping[str, Any] | str,
    purpose: Applicability | Mapping[str, Any] | str,
) -> SupportLabel:
    """Combine independent judgements without losing textual entailment.

    An applicability mismatch produces ``OUT_OF_SCOPE`` as the case-level
    support label, while ``textual_entailment`` remains the original direct,
    partial, unsupported, or contradictory judgement on the cited text.
    """

    if textual_entailment not in TEXTUAL_ENTAILMENT_LABELS:
        raise ValueError(f"unsupported textual entailment: {textual_entailment!r}")
    applicability_values = (
        _coerce_applicability(population, "population"),
        _coerce_applicability(role, "role"),
        _coerce_applicability(purpose, "purpose"),
    )
    if any(item.status == "MISMATCH" for item in applicability_values):
        return "OUT_OF_SCOPE"
    return textual_entailment  # type: ignore[return-value]


def build_claim_record(
    *,
    claim_id: str,
    case_id: str,
    original_answer: str,
    span_start: int,
    span_end: int,
    text: str | None = None,
    claim_type: str,
    citation_required: bool | None = None,
    citation_reason: str = "",
    citation_policy_id: str | None = None,
    cited_chunk_ids: Iterable[str] = (),
    textual_entailment: str = "UNSUPPORTED",
    population_applicability: Applicability | Mapping[str, Any] | str = "UNKNOWN",
    role_applicability: Applicability | Mapping[str, Any] | str = "UNKNOWN",
    purpose_applicability: Applicability | Mapping[str, Any] | str = "UNKNOWN",
    support_label: str | None = None,
    contradiction_reason: str | None = None,
    review: ReviewMetadata | Mapping[str, Any] | None = None,
    review_state: str | None = None,
    traceability: Iterable[TransformationTrace | Mapping[str, Any]] = (),
    excluded: bool = False,
) -> ClaimRecord:
    """Construct a claim record with policy, label, trace, and hash checks."""

    if text is None:
        text = original_answer[span_start:span_end]
    if review is None and review_state is not None:
        review = ReviewMetadata(state=review_state)
    return ClaimRecord(
        claim_id=claim_id,
        case_id=case_id,
        original_answer=original_answer,
        span_start=span_start,
        span_end=span_end,
        text=text,
        claim_type=claim_type,
        citation_required=citation_required,
        citation_reason=citation_reason,
        citation_policy_id=citation_policy_id,
        cited_chunk_ids=tuple(cited_chunk_ids),
        textual_entailment=textual_entailment,
        population_applicability=population_applicability,
        role_applicability=role_applicability,
        purpose_applicability=purpose_applicability,
        support_label=support_label,
        contradiction_flag=textual_entailment == "CONTRADICTS",
        contradiction_reason=contradiction_reason,
        review=review,
        traceability=tuple(traceability),
        excluded=excluded,
    )


def _claim_id_for_answer(case_id: str, ordinal: int) -> str:
    safe = "".join(char if char.isalnum() else "_" for char in case_id).strip("_")
    return f"CLM_{safe or 'CASE'}_{ordinal:03d}"


@dataclass(frozen=True)
class CitationSupportCase:
    """A synthetic answer plus its claim-level review annotations."""

    case_id: str
    original_answer: str
    target_population: str
    target_role: str
    target_purpose: str
    claims: tuple[ClaimRecord, ...]
    evidence: tuple[Mapping[str, Any], ...] = ()
    split: str = "DEV"
    review: ReviewMetadata | Mapping[str, Any] | None = None
    data_classification: tuple[str, ...] = DATA_CLASSIFICATION
    content_hash: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty_text(self.case_id, "case_id")
        if not isinstance(self.original_answer, str) or not self.original_answer:
            raise ValueError("original_answer must be a non-empty string")
        for name, value in (
            ("target_population", self.target_population),
            ("target_role", self.target_role),
            ("target_purpose", self.target_purpose),
        ):
            _require_non_empty_text(value, name)
        if self.split not in {"DEV", "REGRESSION", "SEALED_EVAL"}:
            raise ValueError(f"unsupported case split: {self.split!r}")
        claims = tuple(self.claims)
        if not claims:
            raise ValueError("a citation-support case requires at least one claim")
        ids: set[str] = set()
        for claim in claims:
            if not isinstance(claim, ClaimRecord):
                raise TypeError("claims must contain ClaimRecord values")
            if claim.case_id != self.case_id:
                raise ValueError("claim case_id does not match case_id")
            if claim.original_answer != self.original_answer:
                raise ValueError("claim original_answer does not match case answer")
            if claim.claim_id in ids:
                raise ValueError(f"duplicate claim_id: {claim.claim_id}")
            ids.add(claim.claim_id)
        object.__setattr__(self, "claims", claims)
        review = _coerce_review(self.review)
        object.__setattr__(self, "review", review)
        classification = _coerce_classification(self.data_classification)
        object.__setattr__(self, "data_classification", classification)
        evidence = tuple(_normalise_evidence_card(item) for item in self.evidence)
        evidence_ids = [item["chunk_id"] for item in evidence]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("evidence chunk_id values must be unique")
        object.__setattr__(self, "evidence", evidence)
        expected_hash = canonical_sha256_tag(
            self._payload_dict(), self_field="content_hash"
        )
        if self.content_hash is not None and self.content_hash != expected_hash:
            raise ValueError(
                f"case content_hash mismatch: expected {expected_hash}, got {self.content_hash}"
            )
        object.__setattr__(self, "content_hash", expected_hash)

    def _payload_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "citation-support.v1",
            "record_type": "case",
            "case_id": self.case_id,
            "original_answer": self.original_answer,
            "target_scope": {
                "population": self.target_population,
                "role": self.target_role,
                "purpose": self.target_purpose,
            },
            "split": self.split,
            "evidence": [dict(item) for item in self.evidence],
            "claims": [claim.to_dict() for claim in self.claims],
            "citation_identity": [
                check_citation_identity(claim, self.evidence).to_dict()
                for claim in self.claims
            ],
            "review": self.review.to_dict(),
            "data_classification": list(self.data_classification),
        }

    def to_dict(self) -> dict[str, Any]:
        value = self._payload_dict()
        value["content_hash"] = self.content_hash
        return value


def _normalise_evidence_card(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("evidence cards must be mappings")
    chunk_id = _require_non_empty_text(value.get("chunk_id"), "chunk_id")
    document_id = _require_non_empty_text(value.get("document_id"), "document_id")
    citation_id = _require_non_empty_text(value.get("citation_id"), "citation_id")
    source_title = _require_non_empty_text(value.get("source_title"), "source_title")
    source_organization = _require_non_empty_text(
        value.get("source_organization"), "source_organization"
    )
    locator = _require_non_empty_text(value.get("locator"), "locator")
    text = _require_non_empty_text(value.get("text"), "evidence text")
    population_scope = tuple(value.get("population_scope", ()))
    role_scope = tuple(value.get("role_scope", ()))
    purpose_scope = tuple(value.get("purpose_scope", ()))
    supplied_classification = tuple(
        value.get("data_classification", DATA_CLASSIFICATION)
    )
    if supplied_classification != DATA_CLASSIFICATION:
        raise ValueError(
            "evidence classification markers are fixed synthetic-only values"
        )
    review_state = value.get("review_state", "HUMAN_REVIEW_REQUIRED")
    if review_state not in {"DRAFT", "HUMAN_REVIEW_REQUIRED", "DISPUTED"}:
        raise ValueError(
            "evidence cards require draft/review/disputed state until reviewer provenance is stored"
        )
    for name, values in (
        ("population_scope", population_scope),
        ("role_scope", role_scope),
        ("purpose_scope", purpose_scope),
    ):
        _unique_strings(values, name)
    payload = {
        "schema_version": "citation-support.v1",
        "record_type": "synthetic_evidence_card",
        "chunk_id": chunk_id,
        "document_id": document_id,
        "citation_id": citation_id,
        "source_title": source_title,
        "source_organization": source_organization,
        "locator": locator,
        "text": text,
        "population_scope": list(population_scope),
        "role_scope": list(role_scope),
        "purpose_scope": list(purpose_scope),
        "data_classification": list(DATA_CLASSIFICATION),
        "review_state": review_state,
    }
    reported_hash = value.get("content_hash")
    expected_hash = canonical_sha256_tag(payload, self_field="content_hash")
    if reported_hash is not None and reported_hash != expected_hash:
        raise ValueError(f"evidence content_hash mismatch for {chunk_id}")
    payload["content_hash"] = expected_hash
    return payload


@dataclass(frozen=True)
class CitationIdentityCheck:
    """Evaluation-only identity/provenance result for one claim.

    ``VALID`` means every cited chunk belongs to the supplied evidence cards
    and each matching card carries the required synthetic provenance fields.
    It deliberately says nothing about textual entailment.  A valid identity
    can therefore accompany an ``UNSUPPORTED`` claim.
    """

    claim_id: str
    status: str
    cited_chunk_ids: tuple[str, ...]
    valid_chunk_ids: tuple[str, ...]
    unknown_chunk_ids: tuple[str, ...]
    provenance_complete: bool

    def __post_init__(self) -> None:
        if self.status not in CITATION_IDENTITY_STATUSES:
            raise ValueError(f"unsupported citation identity status: {self.status!r}")
        _require_non_empty_text(self.claim_id, "claim_id")
        for field_name, values in (
            ("cited_chunk_ids", self.cited_chunk_ids),
            ("valid_chunk_ids", self.valid_chunk_ids),
            ("unknown_chunk_ids", self.unknown_chunk_ids),
        ):
            object.__setattr__(self, field_name, _unique_strings(values, field_name))
        if not isinstance(self.provenance_complete, bool):
            raise TypeError("provenance_complete must be boolean")
        expected_status = (
            "NONE"
            if not self.cited_chunk_ids
            else "UNKNOWN"
            if self.unknown_chunk_ids
            else "VALID"
        )
        if self.status != expected_status:
            raise ValueError(
                f"citation identity status does not match IDs: expected {expected_status}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "status": self.status,
            "cited_chunk_ids": list(self.cited_chunk_ids),
            "valid_chunk_ids": list(self.valid_chunk_ids),
            "unknown_chunk_ids": list(self.unknown_chunk_ids),
            "provenance_complete": self.provenance_complete,
        }


def check_citation_identity(
    claim: ClaimRecord | Mapping[str, Any],
    evidence_cards: Iterable[Mapping[str, Any]] | Mapping[str, Any],
) -> CitationIdentityCheck:
    """Compare cited chunk IDs with evidence-card identity/provenance.

    Unknown IDs are reported as ``UNKNOWN`` and remain separate from the
    claim's textual entailment/support label.  The function accepts a case
    mapping for convenient review-packet checks, but never treats an ID as
    valid without a matching evidence card with stable synthetic identity.
    """

    record = claim if isinstance(claim, ClaimRecord) else ClaimRecord.from_dict(claim)
    if isinstance(evidence_cards, Mapping):
        cards_value = evidence_cards.get("evidence", ())
    else:
        cards_value = evidence_cards
    if not isinstance(cards_value, Iterable) or isinstance(
        cards_value, (str, bytes, bytearray)
    ):
        raise TypeError("evidence_cards must be an iterable of evidence mappings")
    cards_by_chunk: dict[str, dict[str, Any]] = {}
    for card in cards_value:
        if not isinstance(card, Mapping):
            raise TypeError("evidence cards must be mappings")
        normalised = _normalise_evidence_card(card)
        chunk_id = normalised["chunk_id"]
        if chunk_id in cards_by_chunk:
            raise ValueError(f"duplicate evidence chunk_id: {chunk_id}")
        cards_by_chunk[chunk_id] = normalised

    cited = tuple(record.cited_chunk_ids)
    valid = tuple(chunk_id for chunk_id in cited if chunk_id in cards_by_chunk)
    unknown = tuple(chunk_id for chunk_id in cited if chunk_id not in cards_by_chunk)
    status = "NONE" if not cited else "UNKNOWN" if unknown else "VALID"
    return CitationIdentityCheck(
        claim_id=record.claim_id,
        status=status,
        cited_chunk_ids=cited,
        valid_chunk_ids=valid,
        unknown_chunk_ids=unknown,
        provenance_complete=bool(cited)
        and not unknown
        and all(
            all(
                isinstance(card.get(field_name), str) and bool(card[field_name].strip())
                for field_name in (
                    "document_id",
                    "citation_id",
                    "source_title",
                    "source_organization",
                    "locator",
                    "content_hash",
                )
            )
            for card in cards_by_chunk.values()
            if card["chunk_id"] in valid
        ),
    )


# Verbose alias for review/export callers.
citation_identity_check = check_citation_identity


def build_case_record(
    *,
    case_id: str,
    original_answer: str,
    target_population: str,
    target_role: str,
    target_purpose: str,
    claims: Iterable[ClaimRecord],
    evidence: Iterable[Mapping[str, Any]] = (),
    split: str = "DEV",
    review: ReviewMetadata | Mapping[str, Any] | None = None,
    review_state: str | None = None,
) -> CitationSupportCase:
    if review is None and review_state is not None:
        review = ReviewMetadata(state=review_state)
    return CitationSupportCase(
        case_id=case_id,
        original_answer=original_answer,
        target_population=target_population,
        target_role=target_role,
        target_purpose=target_purpose,
        claims=tuple(claims),
        evidence=tuple(evidence),
        split=split,
        review=review,
    )


def claim_record_from_dict(value: Mapping[str, Any]) -> ClaimRecord:
    return ClaimRecord.from_dict(value)


def validate_claim_record(value: ClaimRecord | Mapping[str, Any]) -> ClaimRecord:
    """Validate one record and its self hash without changing it."""

    record = value if isinstance(value, ClaimRecord) else ClaimRecord.from_dict(value)
    if record.to_dict()["content_hash"] != record.content_hash:
        raise ValueError("claim content hash is not stable")
    return record


def validate_traceability(
    traces: Iterable[TransformationTrace | Mapping[str, Any]],
) -> tuple[TransformationTrace, ...]:
    """Validate transformation operations used by a manual-review export."""

    return tuple(_coerce_trace(trace) for trace in traces)


def is_human_gold_review(value: ReviewMetadata | Mapping[str, Any]) -> bool:
    """Return the default-metric eligibility flag.

    A test fixture may use the review-state spelling ``HUMAN_APPROVED`` to
    exercise state transitions, but ``decision_source=TEST_SIMULATION`` keeps
    it out of human-gold metrics by construction.
    """

    review = (
        value
        if isinstance(value, ReviewMetadata)
        else ReviewMetadata.from_mapping(value)
    )
    return review.is_human_gold


def append_transformation(
    record: ClaimRecord,
    *,
    operation: str,
    source_claim_ids: Iterable[str],
    reason: str,
    source_spans: Iterable[Mapping[str, Any]] = (),
    result_span: Mapping[str, Any] | None = None,
) -> ClaimRecord:
    """Return a re-hashed record with one explicit transformation trace."""

    trace = TransformationTrace(
        operation=operation,
        source_claim_ids=tuple(source_claim_ids),
        source_spans=tuple(dict(item) for item in source_spans),
        result_span=dict(result_span) if result_span is not None else None,
        reason=reason,
    )
    return replace(
        record,
        traceability=(*record.traceability, trace),
        content_hash=None,
    )


def mark_claim_excluded(record: ClaimRecord, *, reason: str) -> ClaimRecord:
    """Keep an excluded claim auditable while excluding it from scoring."""

    traced = append_transformation(
        record,
        operation="EXCLUDE",
        source_claim_ids=(record.claim_id,),
        source_spans=(_span_dict(record.span_start, record.span_end),),
        result_span=None,
        reason=reason,
    )
    return replace(
        traced,
        excluded=True,
        content_hash=None,
    )


def validate_case_record(
    value: CitationSupportCase | Mapping[str, Any],
) -> CitationSupportCase:
    """Validate a case; mapping input is intentionally strict and explicit."""

    if isinstance(value, CitationSupportCase):
        case = value
    else:
        target_scope = value.get("target_scope")
        if not isinstance(target_scope, Mapping):
            raise TypeError("case target_scope must be an object")
        claims = tuple(ClaimRecord.from_dict(item) for item in value.get("claims", ()))
        case = CitationSupportCase(
            case_id=value.get("case_id"),
            original_answer=value.get("original_answer"),
            target_population=target_scope.get("population"),
            target_role=target_scope.get("role"),
            target_purpose=target_scope.get("purpose"),
            claims=claims,
            evidence=tuple(value.get("evidence", ())),
            split=value.get("split", "DEV"),
            review=value.get("review"),
            data_classification=value.get("data_classification"),
            content_hash=value.get("content_hash"),
        )
    serialised = case.to_dict()
    if (
        isinstance(value, Mapping)
        and "citation_identity" in value
        and value["citation_identity"] != serialised["citation_identity"]
    ):
        raise ValueError("case citation identity checks are not stable")
    if serialised["content_hash"] != case.content_hash:
        raise ValueError("case content hash is not stable")
    return case


__all__ = [
    "APPLICABILITY_STATUSES",
    "CITATION_IDENTITY_STATUSES",
    "CLAIM_TYPES",
    "DATA_CLASSIFICATION",
    "REVIEW_SOURCES",
    "REVIEW_STATES",
    "SUPPORT_LABELS",
    "TEST_FIXTURE_SIMULATED_APPROVAL",
    "TEST_FIXTURE_SIMULATED_REJECTION",
    "TEXTUAL_ENTAILMENT_LABELS",
    "TRANSFORMATION_OPERATIONS",
    "Applicability",
    "CitationIdentityCheck",
    "CitationSupportCase",
    "ClaimRecord",
    "ReviewMetadata",
    "TransformationTrace",
    "append_transformation",
    "build_case_record",
    "build_claim_record",
    "check_citation_identity",
    "citation_identity_check",
    "citation_requirement_for",
    "claim_record_from_dict",
    "derive_support_label",
    "is_human_gold_review",
    "mark_claim_excluded",
    "validate_case_record",
    "validate_claim_record",
    "validate_traceability",
]
