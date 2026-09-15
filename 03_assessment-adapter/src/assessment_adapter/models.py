"""Typed, module-owned D3-2 records.

These records are intentionally independent of the frozen root contracts.  A
future integration may map them to a root contract after a separate decision.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, cast


class _TextEnum(StrEnum):
    """String enum that serializes naturally in JSON-like projections."""

    def __str__(self) -> str:
        return self.value


class ExecutionMode(_TextEnum):
    SYNTHETIC_DEMO = "SYNTHETIC_DEMO"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    REAL_USER = "REAL_USER"


class SafetyAction(_TextEnum):
    PROCEED = "PROCEED"
    PROCEED_WITH_BOUNDARY = "PROCEED_WITH_BOUNDARY"
    CRISIS_ROUTE = "CRISIS_ROUTE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCK = "BLOCK"


class InterpretationStatus(_TextEnum):
    # Canonical D3-2 status vocabulary.  The additional values below retain
    # useful module-local diagnostics without changing the canonical outcomes.
    READY_FOR_RENDERING = "READY_FOR_RENDERING"
    MEASUREMENT_ONLY = "MEASUREMENT_ONLY"
    ABSTAIN_POLICY_MISSING = "ABSTAIN_POLICY_MISSING"
    ABSTAIN_POLICY_NOT_APPROVED = "ABSTAIN_POLICY_NOT_APPROVED"
    ABSTAIN_INSTRUMENT_MISMATCH = "ABSTAIN_INSTRUMENT_MISMATCH"
    ABSTAIN_POPULATION_MISMATCH = "ABSTAIN_POPULATION_MISMATCH"
    ABSTAIN_PRECISION_INSUFFICIENT = "ABSTAIN_PRECISION_INSUFFICIENT"
    ABSTAIN_CONSTRUCT_UNAPPROVED = "ABSTAIN_CONSTRUCT_UNAPPROVED"
    BYPASS_SAFETY = "BYPASS_SAFETY"

    # Useful extensions that preserve more specific module diagnostics.
    ABSTAIN_POLICY_MISMATCH = "ABSTAIN_POLICY_MISMATCH"
    ABSTAIN_POLICY_HASH_MISMATCH = "ABSTAIN_POLICY_HASH_MISMATCH"
    ABSTAIN_VERSION_MISMATCH = "ABSTAIN_VERSION_MISMATCH"
    ABSTAIN_REAL_USER_BLOCKED = "ABSTAIN_REAL_USER_BLOCKED"
    ABSTAIN_MODE_NOT_ALLOWED = "ABSTAIN_MODE_NOT_ALLOWED"
    ABSTAIN_INPUT_INVALID = "ABSTAIN_INPUT_INVALID"


class ReasonCode(_TextEnum):
    TRUSTED_CONTEXT_REQUIRED = "TRUSTED_CONTEXT_REQUIRED"
    POLICY_REFERENCE_INVALID = "POLICY_REFERENCE_INVALID"
    POLICY_REFERENCE_MISSING = "POLICY_REFERENCE_MISSING"
    POLICY_NOT_FOUND = "POLICY_NOT_FOUND"
    POLICY_DUPLICATE = "POLICY_DUPLICATE"
    POLICY_INVALID = "POLICY_INVALID"
    POLICY_HASH_MISSING = "POLICY_HASH_MISSING"
    POLICY_HASH_MISMATCH = "POLICY_HASH_MISMATCH"
    POLICY_INSTRUMENT_MISMATCH = "POLICY_INSTRUMENT_MISMATCH"
    POLICY_VERSION_MISMATCH = "POLICY_VERSION_MISMATCH"
    POLICY_POPULATION_MISMATCH = "POLICY_POPULATION_MISMATCH"
    POLICY_MODE_NOT_ALLOWED = "POLICY_MODE_NOT_ALLOWED"
    POLICY_CONSERVATIVE_MEASUREMENT_ONLY = "POLICY_CONSERVATIVE_MEASUREMENT_ONLY"
    SYNTHETIC_TEST_ONLY_POLICY = "SYNTHETIC_TEST_ONLY_POLICY"
    CONSTRUCT_UNAPPROVED = "CONSTRUCT_UNAPPROVED"
    ASSESSMENT_SCHEMA_INVALID = "ASSESSMENT_SCHEMA_INVALID"
    ASSESSMENT_NOT_COMPLETED = "ASSESSMENT_NOT_COMPLETED"
    POPULATION_CONTEXT_MISMATCH = "POPULATION_CONTEXT_MISMATCH"
    CRISIS_ROUTE = "CRISIS_ROUTE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCK = "BLOCK"


@dataclass(frozen=True, slots=True)
class PolicyReference:
    """Exact caller-supplied identity for a policy pack."""

    policy_id: str
    policy_version: str
    policy_hash: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> PolicyReference:
        required = {"policy_id", "policy_version", "policy_hash"}
        if set(value) != required or not all(
            isinstance(value.get(key), str) and bool(value.get(key)) for key in required
        ):
            raise ValueError("policy reference must contain exactly id, version and hash")
        return cls(
            policy_id=value["policy_id"],
            policy_version=value["policy_version"],
            policy_hash=value["policy_hash"],
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_hash": self.policy_hash,
        }


@dataclass(frozen=True, slots=True)
class InterpretationRequest:
    """A read-only request containing a copied completed assessment."""

    assessment: Mapping[str, Any]
    policy_ref: PolicyReference | None = None
    request_id: str = "REQ_assessment_adapter"
    trace_id: str = "TRACE_assessment_adapter"
    policy_id: str | None = None
    policy_version: str | None = None
    policy_hash: str | None = None

    def __post_init__(self) -> None:
        try:
            copied = copy.deepcopy(self.assessment)
        except Exception as exc:  # pragma: no cover - hostile object defense
            raise TypeError("assessment cannot be copied") from exc
        if not isinstance(copied, Mapping):
            raise TypeError("assessment must be a mapping")
        reference = self.policy_ref
        if reference is None:
            if not all(
                isinstance(item, str) and item
                for item in (self.policy_id, self.policy_version, self.policy_hash)
            ):
                raise TypeError("policy_ref or all policy identity fields are required")
            reference = PolicyReference(
                cast(str, self.policy_id),
                cast(str, self.policy_version),
                cast(str, self.policy_hash),
            )
        if not isinstance(reference, PolicyReference):
            raise TypeError("policy_ref must be a PolicyReference")
        if any(
            item is not None
            and item != expected
            for item, expected in (
                (self.policy_id, reference.policy_id),
                (self.policy_version, reference.policy_version),
                (self.policy_hash, reference.policy_hash),
            )
        ):
            raise ValueError("duplicated policy identity fields disagree")
        object.__setattr__(self, "policy_ref", reference)
        object.__setattr__(self, "policy_id", reference.policy_id)
        object.__setattr__(self, "policy_version", reference.policy_version)
        object.__setattr__(self, "policy_hash", reference.policy_hash)
        if not isinstance(self.request_id, str) or not self.request_id:
            raise ValueError("request_id must be a non-empty string")
        if not isinstance(self.trace_id, str) or not self.trace_id:
            raise ValueError("trace_id must be a non-empty string")
        object.__setattr__(self, "assessment", copied)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> InterpretationRequest:
        if not isinstance(value, Mapping):
            raise TypeError("request must be a mapping")
        assessment = value.get("assessment")
        policy_ref_value = value.get("policy_ref")
        if not isinstance(assessment, Mapping):
            raise ValueError("request requires an assessment mapping")
        if isinstance(policy_ref_value, Mapping):
            reference = PolicyReference.from_mapping(policy_ref_value)
        else:
            reference = PolicyReference.from_mapping(
                {
                    "policy_id": value.get("policy_id"),
                    "policy_version": value.get("policy_version"),
                    "policy_hash": value.get("policy_hash"),
                }
            )
        return cls(
            assessment=assessment,
            policy_ref=reference,
            request_id=value.get("request_id", "REQ_assessment_adapter"),
            trace_id=value.get("trace_id", "TRACE_assessment_adapter"),
        )


_TRUSTED_CONTEXT_CAPABILITY = object()


@dataclass(frozen=True, slots=True)
class TrustedInterpretationContext:
    """Capability-like integration state for interpretation gating.

    The private capability marker prevents ordinary callers from constructing a
    valid context by simply passing a dictionary.  This is a process-local
    trust boundary, not a cryptographic defence against hostile code that can
    import private names or mutate the Python process.
    """

    execution_mode: ExecutionMode
    assessment_population: str
    context_id: str
    context_version: str
    safety_action: SafetyAction
    request_id: str
    trace_id: str
    _capability: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._capability is not _TRUSTED_CONTEXT_CAPABILITY:
            raise TypeError("TrustedInterpretationContext is internal-only")

    @property
    def mode(self) -> ExecutionMode:
        """Compatibility alias for policy-facing callers."""

        return self.execution_mode

    @property
    def context_identity(self) -> str:
        return self.context_id

    @property
    def safety_state(self) -> SafetyAction:
        return self.safety_action


@dataclass(frozen=True, slots=True)
class ConstructPolicy:
    """Typed meaning gate for one assessment dimension."""

    construct_id: str
    status: str
    direction: str | None
    high_score_meaning: str | None
    low_score_meaning: str | None
    allowed_claim_codes: tuple[str, ...]
    forbidden_claim_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "construct_id": self.construct_id,
            "status": self.status,
            "direction": self.direction,
            "high_score_meaning": self.high_score_meaning,
            "low_score_meaning": self.low_score_meaning,
            "allowed_claim_codes": list(self.allowed_claim_codes),
            "forbidden_claim_codes": list(self.forbidden_claim_codes),
        }


@dataclass(frozen=True, slots=True)
class InterpretationPolicyPack:
    """Versioned interpretation policy parsed from one JSON object."""

    schema_version: str
    policy_id: str
    policy_version: str
    effective_version: str
    policy_hash: str
    instrument_id: str
    instrument_version: str
    population_scope: str
    allowed_modes: tuple[ExecutionMode, ...]
    synthetic_only: bool
    engineering_scope: str
    controller_scope: str
    psychology_review_status: str
    review_status_detail: str
    review_decision_id: str
    evidence_refs: tuple[str, ...]
    construct_policies: dict[str, ConstructPolicy]
    allowed_claims: tuple[str, ...]
    forbidden_claims: tuple[str, ...]
    policy_kind: str
    limitations: tuple[str, ...]

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "effective_version": self.effective_version,
            "instrument_id": self.instrument_id,
            "instrument_version": self.instrument_version,
            "population_scope": self.population_scope,
            "allowed_modes": [mode.value for mode in self.allowed_modes],
            "synthetic_only": self.synthetic_only,
            "engineering_scope": self.engineering_scope,
            "controller_scope": self.controller_scope,
            "psychology_review_status": self.psychology_review_status,
            "review_status_detail": self.review_status_detail,
            "review_decision_id": self.review_decision_id,
            "evidence_refs": list(self.evidence_refs),
            "construct_policies": {
                key: value.to_dict() for key, value in self.construct_policies.items()
            },
            "allowed_claims": list(self.allowed_claims),
            "forbidden_claims": list(self.forbidden_claims),
            "policy_kind": self.policy_kind,
            "limitations": list(self.limitations),
        }
        if include_hash:
            result["policy_hash"] = self.policy_hash
        return result


@dataclass(frozen=True, slots=True)
class Claim:
    """Role-neutral structured claim; never natural-language prose."""

    claim_code: str
    construct_id: str
    value: str | bool | int | float

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_code": self.claim_code,
            "construct_id": self.construct_id,
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class InterpretationResult:
    """Canonical role-neutral output for the module-owned result schema."""

    schema_version: str
    status: InterpretationStatus
    reason_codes: tuple[str, ...]
    assessment_id: str | None
    subject_id: str | None
    instrument_id: str | None
    instrument_version: str | None
    population_scope: str | None
    policy: dict[str, str | None]
    claims: tuple[Claim, ...]
    limitations: tuple[str, ...]
    audit: dict[str, str | None]

    _KEYS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "status",
        "reason_codes",
        "assessment_id",
        "subject_id",
        "instrument",
        "population_scope",
        "policy",
        "claims",
        "limitations",
        "audit",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "reason_codes": list(self.reason_codes),
            "assessment_id": self.assessment_id,
            "subject_id": self.subject_id,
            "instrument": {
                "instrument_id": self.instrument_id,
                "version": self.instrument_version,
            },
            "population_scope": self.population_scope,
            "policy": dict(self.policy),
            "claims": [claim.to_dict() for claim in self.claims],
            "limitations": list(self.limitations),
            "audit": dict(self.audit),
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def __contains__(self, key: object) -> bool:
        return key in self._KEYS

    def __iter__(self) -> Iterator[str]:
        return iter(self._KEYS)


# Names used by integration code can remain explicit without adding another
# structural contract.
TypedClaim = Claim
PolicyRef = PolicyReference
