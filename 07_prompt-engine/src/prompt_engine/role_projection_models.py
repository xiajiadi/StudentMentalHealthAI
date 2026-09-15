"""Typed contracts and exact policy registry for D3-3 role projection.

This module owns the D3-3 boundary without changing the frozen assessment or
prompt contracts.  The registry is deliberately conservative: every shipped
policy is synthetic-only, selects the D3-2 ``MEASUREMENT_ONLY`` source status,
and has an empty claim allow-list.  A future policy must be introduced as a
new reviewed, hashed record rather than inferred from a role or from a
``latest``/default fallback.

The trusted audience context is a process-local capability, mirroring the
boundary used by the D3-2 adapter.  It is useful for controlled integration
ports and deterministic tests; it is not a cryptographic authority or a
consent workflow.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar, Self

_HASH_PREFIX = "sha256:"
_POLICY_SCHEMA_VERSION = "role-projection-policy.v1"
_REGISTRY_SCHEMA_VERSION = "role-projection-policy-registry.v1"
_RESULT_SCHEMA_VERSION = "role_projection_result.v1"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_CODE = re.compile(r"^[A-Z][A-Z0-9_.-]+$")
_SAFE_TRACE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_POLICY_REFERENCE_FORBIDDEN = {"latest", "LATEST", "default", "DEFAULT", "*"}
_FORBIDDEN_CLAIM_TOKENS = (
    "DIAGNOS",
    "DIAGNOST",
    "DISORDER",
    "CLINICAL",
    "SUICIDE",
    "SELF_HARM",
    "SELFHARM",
    "CRISIS",
    "TREATMENT",
    "THERAPY",
    "MEDICATION",
    "THETA",
    "SCORE",
    "BAND",
    "CUTOFF",
    "THRESHOLD",
    "RISK",
    "SEVERITY",
    "PRECISION",
    "STANDARD_ERROR",
    "LATENT",
    "LEVEL",
    "INTERVAL",
    "RESPONSE",
    "PROMPT",
    "PII",
    "PERSONAL_DATA",
    "EMAIL",
    "PHONE",
    "NAME",
)
_SAFE_LIMITATION_CODES = frozenset(
    {
        "SYNTHETIC_ONLY",
        "NOT_DIAGNOSTIC",
        "NO_VALIDATED_CUTOFF",
        "NO_CLINICAL_INFERENCE",
        "NO_CRISIS_INFERENCE",
        "NO_PERSONALIZED_DISCLOSURE",
    }
)


class _TextEnum(StrEnum):
    """String enum that serializes naturally in JSON-like projections."""

    def __str__(self) -> str:
        return self.value


class AudienceRole(_TextEnum):
    """The only D3-3 audience roles.

    ``SYSTEM_ADMIN`` and ``UNKNOWN`` remain representable in trusted input so
    that the engine can record an explicit denial.  They are never valid
    policy audience roles.
    """

    STUDENT_SELF = "STUDENT_SELF"
    TEACHER_SUPPORT = "TEACHER_SUPPORT"
    PARENT_DEMO = "PARENT_DEMO"
    SYSTEM_ADMIN = "SYSTEM_ADMIN"
    UNKNOWN = "UNKNOWN"


class PurposeOfUse(_TextEnum):
    SELF_UNDERSTANDING = "SELF_UNDERSTANDING"
    EDUCATIONAL_SUPPORT = "EDUCATIONAL_SUPPORT"
    SYNTHETIC_PARENT_DEMO = "SYNTHETIC_PARENT_DEMO"


class TrustedRelation(_TextEnum):
    SELF = "SELF"
    ASSIGNED_SUPPORT = "ASSIGNED_SUPPORT"
    SYNTHETIC_DEMO = "SYNTHETIC_DEMO"


class ProjectionMode(_TextEnum):
    SYNTHETIC_DEMO = "SYNTHETIC_DEMO"
    REAL_USER = "REAL_USER"


class DisclosureAuthorization(_TextEnum):
    """Minimal projection authorization state, never a legal-consent model."""

    NOT_AUTHORIZED = "NOT_AUTHORIZED"
    SYNTHETIC_SELF = "SYNTHETIC_SELF"
    SYNTHETIC_SUPPORT = "SYNTHETIC_SUPPORT"
    SYNTHETIC_PARENT_DEMO = "SYNTHETIC_PARENT_DEMO"

    # Readable aliases for integration callers; aliases do not add states.
    DENIED = "NOT_AUTHORIZED"
    SELF_SYNTHETIC = "SYNTHETIC_SELF"
    ASSIGNED_SUPPORT_SYNTHETIC = "SYNTHETIC_SUPPORT"


class SourceStatus(_TextEnum):
    """D3-2 source statuses that D3-3 may inspect, without reinterpreting."""

    READY_FOR_RENDERING = "READY_FOR_RENDERING"
    MEASUREMENT_ONLY = "MEASUREMENT_ONLY"
    ABSTAIN_POLICY_MISSING = "ABSTAIN_POLICY_MISSING"
    ABSTAIN_POLICY_NOT_APPROVED = "ABSTAIN_POLICY_NOT_APPROVED"
    ABSTAIN_INSTRUMENT_MISMATCH = "ABSTAIN_INSTRUMENT_MISMATCH"
    ABSTAIN_POPULATION_MISMATCH = "ABSTAIN_POPULATION_MISMATCH"
    ABSTAIN_PRECISION_INSUFFICIENT = "ABSTAIN_PRECISION_INSUFFICIENT"
    ABSTAIN_CONSTRUCT_UNAPPROVED = "ABSTAIN_CONSTRUCT_UNAPPROVED"
    ABSTAIN_POLICY_MISMATCH = "ABSTAIN_POLICY_MISMATCH"
    ABSTAIN_POLICY_HASH_MISMATCH = "ABSTAIN_POLICY_HASH_MISMATCH"
    ABSTAIN_VERSION_MISMATCH = "ABSTAIN_VERSION_MISMATCH"
    ABSTAIN_REAL_USER_BLOCKED = "ABSTAIN_REAL_USER_BLOCKED"
    ABSTAIN_MODE_NOT_ALLOWED = "ABSTAIN_MODE_NOT_ALLOWED"
    ABSTAIN_INPUT_INVALID = "ABSTAIN_INPUT_INVALID"
    BYPASS_SAFETY = "BYPASS_SAFETY"


class SafetyAction(_TextEnum):
    PROCEED = "PROCEED"
    PROCEED_WITH_BOUNDARY = "PROCEED_WITH_BOUNDARY"
    CRISIS_ROUTE = "CRISIS_ROUTE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCK = "BLOCK"


class DisclosureRequirement(_TextEnum):
    """Typed disclosure boundary; this is not a consent model."""

    SELF_ONLY = "SELF_ONLY"
    NO_PERSONALIZED_DISCLOSURE = "NO_PERSONALIZED_DISCLOSURE"
    SYNTHETIC_DEMO_ONLY = "SYNTHETIC_DEMO_ONLY"


class ProjectionStatus(_TextEnum):
    """Canonical D3-3 status vocabulary.

    Do not add diagnostics here.  Detailed diagnostics belong in the audit
    projection's reason codes, while the public projection stays stable.
    """

    READY_FOR_PROMPT = "READY_FOR_PROMPT"
    NO_PERSONALIZED_DISCLOSURE = "NO_PERSONALIZED_DISCLOSURE"
    ABSTAIN_POLICY_MISSING = "ABSTAIN_POLICY_MISSING"
    ABSTAIN_POLICY_MISMATCH = "ABSTAIN_POLICY_MISMATCH"
    ABSTAIN_ROLE_NOT_ALLOWED = "ABSTAIN_ROLE_NOT_ALLOWED"
    ABSTAIN_PURPOSE_NOT_ALLOWED = "ABSTAIN_PURPOSE_NOT_ALLOWED"
    ABSTAIN_RELATIONSHIP_MISMATCH = "ABSTAIN_RELATIONSHIP_MISMATCH"
    ABSTAIN_DISCLOSURE_NOT_AUTHORIZED = "ABSTAIN_DISCLOSURE_NOT_AUTHORIZED"
    ABSTAIN_MODE_NOT_ALLOWED = "ABSTAIN_MODE_NOT_ALLOWED"
    ABSTAIN_SOURCE_STATUS = "ABSTAIN_SOURCE_STATUS"
    BYPASS_SAFETY = "BYPASS_SAFETY"


CANONICAL_PROJECTION_STATUSES: tuple[str, ...] = tuple(
    status.value for status in ProjectionStatus
)


class ProjectionReasonCode(_TextEnum):
    """Typed audit reasons; none of these are exposed by the public envelope."""

    READY_FOR_PROMPT = "READY_FOR_PROMPT"
    NO_PERSONALIZED_DISCLOSURE = "NO_PERSONALIZED_DISCLOSURE"
    POLICY_MISSING = "POLICY_MISSING"
    POLICY_MISMATCH = "POLICY_MISMATCH"
    POLICY_HASH_MISMATCH = "POLICY_HASH_MISMATCH"
    POLICY_REFERENCE_INVALID = "POLICY_REFERENCE_INVALID"
    ROLE_NOT_ALLOWED = "ROLE_NOT_ALLOWED"
    PURPOSE_NOT_ALLOWED = "PURPOSE_NOT_ALLOWED"
    RELATIONSHIP_MISMATCH = "RELATIONSHIP_MISMATCH"
    DISCLOSURE_NOT_AUTHORIZED = "DISCLOSURE_NOT_AUTHORIZED"
    DISCLOSURE_AUTHORIZATION_MISSING = "DISCLOSURE_AUTHORIZATION_MISSING"
    CONSENT_MISSING = "CONSENT_MISSING"
    CLAIM_NOT_VISIBLE = "CLAIM_NOT_VISIBLE"
    RELATION_FAILED = "RELATION_FAILED"
    SENSITIVE_SOURCE_PRESENT = "SENSITIVE_SOURCE_PRESENT"
    MODE_NOT_ALLOWED = "MODE_NOT_ALLOWED"
    REAL_USER_DISCLOSURE_BLOCKED = "REAL_USER_DISCLOSURE_BLOCKED"
    SOURCE_STATUS_NOT_ALLOWED = "SOURCE_STATUS_NOT_ALLOWED"
    SOURCE_CLAIMS_NOT_SUBSET = "SOURCE_CLAIMS_NOT_SUBSET"
    TRUSTED_CONTEXT_REQUIRED = "TRUSTED_CONTEXT_REQUIRED"
    SAFETY_BYPASS = "SAFETY_BYPASS"
    REGISTRY_INVALID = "REGISTRY_INVALID"
    POLICY_TAMPERED = "POLICY_TAMPERED"


ReasonCode = ProjectionReasonCode


class RoleProjectionError(ValueError):
    """Base class for deterministic, redacted D3-3 contract failures."""

    def __init__(self, reason_code: str, message: str | None = None) -> None:
        self.reason_code = reason_code
        super().__init__(message or reason_code)


class PolicyIntegrityError(RoleProjectionError):
    """A policy's stored hash no longer matches its canonical content."""


class PolicySelectionError(RoleProjectionError):
    """An exact policy reference cannot be resolved."""


def _as_enum[EnumT: _TextEnum](
    value: object, enum_type: type[EnumT], field_name: str
) -> EnumT:
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise RoleProjectionError("REGISTRY_INVALID", f"{field_name} must be a string enum")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise RoleProjectionError("REGISTRY_INVALID", f"{field_name} is not allowed") from exc


def _require_text(value: object, field_name: str, *, identifier: bool = True) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RoleProjectionError("REGISTRY_INVALID", f"{field_name} must be non-empty text")
    if value in _POLICY_REFERENCE_FORBIDDEN or "*" in value:
        raise RoleProjectionError("POLICY_REFERENCE_INVALID", f"{field_name} cannot use fallback")
    if identifier and not _IDENTIFIER.fullmatch(value):
        raise RoleProjectionError("REGISTRY_INVALID", f"{field_name} is not a safe identifier")
    return value


def _require_safe_trace(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_TRACE_ID.fullmatch(value):
        raise RoleProjectionError("TRUSTED_CONTEXT_REQUIRED", f"{field_name} is invalid")
    return value


def _string_tuple(
    value: object,
    field_name: str,
    *,
    code: bool = False,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
        raise RoleProjectionError("REGISTRY_INVALID", f"{field_name} must be a string list")
    items = tuple(value)
    if not allow_empty and not items:
        raise RoleProjectionError("REGISTRY_INVALID", f"{field_name} cannot be empty")
    if len(set(items)) != len(items):
        raise RoleProjectionError("REGISTRY_INVALID", f"{field_name} must be unique")
    for item in items:
        if item in _POLICY_REFERENCE_FORBIDDEN or "*" in item or not item.strip():
            raise RoleProjectionError("POLICY_REFERENCE_INVALID", f"{field_name} contains fallback")
        if code and not _CODE.fullmatch(item):
            raise RoleProjectionError("REGISTRY_INVALID", f"{field_name} contains invalid code")
    return items


def _is_forbidden_projection_code(value: str) -> bool:
    """Return whether a claim/limitation code carries forbidden semantics."""

    normalized = re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_")
    if any(token in normalized for token in _FORBIDDEN_CLAIM_TOKENS):
        return True
    if "SELF_INJURY" in normalized:
        return True
    if normalized.startswith(("TREATMENT", "THERAPY", "MEDICATION")):
        return True
    if normalized.startswith("LEVEL_") or (
        normalized.startswith("LEVEL") and normalized[-1:].isdigit()
    ):
        return True
    if normalized == "SE" or normalized.startswith("SE_") or normalized.endswith("_SE"):
        return True
    if "INTERVAL" in normalized or ("PRECISION" in normalized and "RISK" in normalized):
        return True
    return False


def _validated_limitation_codes(
    value: object,
    field_name: str,
    *,
    allow_empty: bool = False,
    reason_code: str = "REGISTRY_INVALID",
) -> tuple[str, ...]:
    """Validate limitation identifiers while retaining safe negative meanings."""

    items = _string_tuple(value, field_name, code=True, allow_empty=allow_empty)
    if any(
        item not in _SAFE_LIMITATION_CODES and _is_forbidden_projection_code(item)
        for item in items
    ):
        raise RoleProjectionError(reason_code, f"{field_name} contains forbidden code")
    return items


def _canonical_payload(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        {key: item for key, item in value.items() if key != "policy_hash"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_policy_hash(value: Mapping[str, Any] | RoleProjectionPolicy) -> str:
    """Compute the registry hash over every policy field except ``policy_hash``."""

    if isinstance(value, RoleProjectionPolicy):
        payload = value.to_mapping(include_hash=False)
    elif isinstance(value, Mapping):
        payload = value
    else:
        raise TypeError("policy must be a mapping or RoleProjectionPolicy")
    return _HASH_PREFIX + hashlib.sha256(_canonical_payload(payload)).hexdigest()


@dataclass(frozen=True, slots=True)
class PolicyReference:
    """Exact policy identity supplied to a projection boundary."""

    policy_id: str
    policy_version: str
    policy_hash: str

    def __post_init__(self) -> None:
        _require_text(self.policy_id, "policy_id")
        _require_text(self.policy_version, "policy_version")
        if not isinstance(self.policy_hash, str) or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", self.policy_hash
        ):
            raise RoleProjectionError("POLICY_REFERENCE_INVALID", "policy_hash is invalid")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> Self:
        if not isinstance(value, Mapping) or set(value) != {
            "policy_id",
            "policy_version",
            "policy_hash",
        }:
            raise PolicySelectionError("POLICY_REFERENCE_INVALID")
        try:
            return cls(
                policy_id=value["policy_id"],
                policy_version=value["policy_version"],
                policy_hash=value["policy_hash"],
            )
        except (RoleProjectionError, TypeError) as exc:
            raise PolicySelectionError("POLICY_REFERENCE_INVALID") from exc

    def to_dict(self) -> dict[str, str]:
        return {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_hash": self.policy_hash,
        }


@dataclass(frozen=True, slots=True)
class PolicyReviewMetadata:
    """Minimal review provenance attached to one exact policy pack."""

    review_status: str
    review_decision_id: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_text(self.review_status, "review_status", identifier=False)
        _require_text(self.review_decision_id, "review_decision_id")
        _string_tuple(self.evidence_refs, "evidence_refs")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> Self:
        if not isinstance(value, Mapping) or set(value) != {
            "review_status",
            "review_decision_id",
            "evidence_refs",
        }:
            raise RoleProjectionError("REGISTRY_INVALID", "review_metadata shape is invalid")
        return cls(
            review_status=_require_text(value["review_status"], "review_status", identifier=False),
            review_decision_id=_require_text(value["review_decision_id"], "review_decision_id"),
            evidence_refs=_string_tuple(value["evidence_refs"], "evidence_refs"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "review_status": self.review_status,
            "review_decision_id": self.review_decision_id,
            "evidence_refs": list(self.evidence_refs),
        }


_ROLE_PURPOSE: dict[AudienceRole, PurposeOfUse] = {
    AudienceRole.STUDENT_SELF: PurposeOfUse.SELF_UNDERSTANDING,
    AudienceRole.TEACHER_SUPPORT: PurposeOfUse.EDUCATIONAL_SUPPORT,
    AudienceRole.PARENT_DEMO: PurposeOfUse.SYNTHETIC_PARENT_DEMO,
}
_ROLE_RELATION: dict[AudienceRole, TrustedRelation] = {
    AudienceRole.STUDENT_SELF: TrustedRelation.SELF,
    AudienceRole.TEACHER_SUPPORT: TrustedRelation.ASSIGNED_SUPPORT,
    AudienceRole.PARENT_DEMO: TrustedRelation.SYNTHETIC_DEMO,
}
ALLOWED_AUDIENCE_ROLES: frozenset[AudienceRole] = frozenset(_ROLE_PURPOSE)


def expected_purpose_for_role(role: AudienceRole) -> PurposeOfUse | None:
    return _ROLE_PURPOSE.get(role)


def expected_relation_for_role(role: AudienceRole) -> TrustedRelation | None:
    return _ROLE_RELATION.get(role)


@dataclass(frozen=True, slots=True)
class RoleProjectionPolicy:
    """One immutable, exact, hashed D3-3 role/purpose disclosure policy."""

    policy_id: str
    policy_version: str
    policy_hash: str
    audience_role: AudienceRole
    purpose_of_use: PurposeOfUse
    allowed_modes: tuple[ProjectionMode, ...]
    allowed_source_statuses: tuple[SourceStatus, ...]
    allowed_claim_codes: tuple[str, ...]
    allowed_limitation_codes: tuple[str, ...]
    public_field_allowlist: tuple[str, ...]
    required_relation: TrustedRelation
    disclosure_requirement: DisclosureRequirement
    synthetic_only: bool
    review_metadata: PolicyReviewMetadata
    effective_version: str
    status: str = "active"
    schema_version: str = _POLICY_SCHEMA_VERSION

    _PUBLIC_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"status", "claims", "limitations", "citations"}
    )

    def __post_init__(self) -> None:
        _require_text(self.policy_id, "policy_id")
        _require_text(self.policy_version, "policy_version")
        _require_text(self.effective_version, "effective_version")
        _require_text(self.status, "status")
        if self.schema_version != _POLICY_SCHEMA_VERSION:
            raise RoleProjectionError("REGISTRY_INVALID", "policy schema_version is invalid")
        if self.status != "active":
            raise RoleProjectionError("POLICY_MISMATCH", "policy is not active")
        if not isinstance(self.audience_role, AudienceRole):
            raise RoleProjectionError("REGISTRY_INVALID", "audience_role is invalid")
        if self.audience_role not in ALLOWED_AUDIENCE_ROLES:
            raise RoleProjectionError("ABSTAIN_ROLE_NOT_ALLOWED", "role is not policy eligible")
        if not isinstance(self.purpose_of_use, PurposeOfUse):
            raise RoleProjectionError("REGISTRY_INVALID", "purpose_of_use is invalid")
        if _ROLE_PURPOSE[self.audience_role] is not self.purpose_of_use:
            raise RoleProjectionError(
                "ABSTAIN_PURPOSE_NOT_ALLOWED", "role and purpose do not match"
            )
        if not isinstance(self.required_relation, TrustedRelation):
            raise RoleProjectionError("REGISTRY_INVALID", "required_relation is invalid")
        if _ROLE_RELATION[self.audience_role] is not self.required_relation:
            raise RoleProjectionError(
                "ABSTAIN_RELATIONSHIP_MISMATCH", "role and relation do not match"
            )
        if not isinstance(self.synthetic_only, bool) or not self.synthetic_only:
            raise RoleProjectionError(
                "ABSTAIN_MODE_NOT_ALLOWED", "D3-3 policy must be synthetic-only"
            )
        if not self.allowed_modes or any(
            not isinstance(item, ProjectionMode) for item in self.allowed_modes
        ):
            raise RoleProjectionError("REGISTRY_INVALID", "allowed_modes is invalid")
        if len(set(self.allowed_modes)) != len(self.allowed_modes):
            raise RoleProjectionError("REGISTRY_INVALID", "allowed_modes is not unique")
        if any(item is ProjectionMode.REAL_USER for item in self.allowed_modes):
            raise RoleProjectionError("ABSTAIN_MODE_NOT_ALLOWED", "REAL_USER is not allowed")
        if self.allowed_modes != (ProjectionMode.SYNTHETIC_DEMO,):
            raise RoleProjectionError(
                "ABSTAIN_MODE_NOT_ALLOWED", "synthetic policy mode is not exact"
            )
        if not self.allowed_source_statuses or any(
            not isinstance(item, SourceStatus) for item in self.allowed_source_statuses
        ):
            raise RoleProjectionError("REGISTRY_INVALID", "allowed_source_statuses is invalid")
        if len(set(self.allowed_source_statuses)) != len(self.allowed_source_statuses):
            raise RoleProjectionError("REGISTRY_INVALID", "allowed_source_statuses is not unique")
        _string_tuple(self.allowed_claim_codes, "allowed_claim_codes", code=True, allow_empty=True)
        if any(
            _is_forbidden_projection_code(claim_code) for claim_code in self.allowed_claim_codes
        ):
            raise RoleProjectionError(
                "ABSTAIN_POLICY_MISMATCH", "psychological claim code is forbidden"
            )
        _validated_limitation_codes(
            self.allowed_limitation_codes,
            "allowed_limitation_codes",
        )
        _string_tuple(self.public_field_allowlist, "public_field_allowlist", allow_empty=False)
        if not set(self.public_field_allowlist).issubset(self._PUBLIC_FIELDS):
            raise RoleProjectionError(
                "REGISTRY_INVALID", "public_field_allowlist contains hidden fields"
            )
        if len(set(self.public_field_allowlist)) != len(self.public_field_allowlist):
            raise RoleProjectionError("REGISTRY_INVALID", "public_field_allowlist is not unique")
        if not isinstance(self.disclosure_requirement, DisclosureRequirement):
            raise RoleProjectionError("REGISTRY_INVALID", "disclosure_requirement is invalid")
        if self.audience_role is AudienceRole.TEACHER_SUPPORT:
            if self.allowed_claim_codes:
                raise RoleProjectionError(
                    "ABSTAIN_DISCLOSURE_NOT_AUTHORIZED", "teacher policy cannot emit claims"
                )
            if self.disclosure_requirement is not DisclosureRequirement.NO_PERSONALIZED_DISCLOSURE:
                raise RoleProjectionError(
                    "ABSTAIN_DISCLOSURE_NOT_AUTHORIZED", "teacher policy must suppress disclosure"
                )
        if self.audience_role is AudienceRole.PARENT_DEMO:
            if self.required_relation is not TrustedRelation.SYNTHETIC_DEMO:
                raise RoleProjectionError("ABSTAIN_RELATIONSHIP_MISMATCH")
            if self.disclosure_requirement is not DisclosureRequirement.SYNTHETIC_DEMO_ONLY:
                raise RoleProjectionError("ABSTAIN_DISCLOSURE_NOT_AUTHORIZED")
        if not isinstance(self.review_metadata, PolicyReviewMetadata):
            raise RoleProjectionError("REGISTRY_INVALID", "review_metadata is invalid")
        if not isinstance(self.policy_hash, str) or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", self.policy_hash
        ):
            raise PolicyIntegrityError("POLICY_HASH_MISMATCH")
        if canonical_policy_hash(self) != self.policy_hash:
            raise PolicyIntegrityError("POLICY_HASH_MISMATCH")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> Self:
        required = {
            "schema_version",
            "policy_id",
            "policy_version",
            "policy_hash",
            "audience_role",
            "purpose_of_use",
            "allowed_modes",
            "allowed_source_statuses",
            "allowed_claim_codes",
            "allowed_limitation_codes",
            "public_field_allowlist",
            "required_relation",
            "disclosure_requirement",
            "synthetic_only",
            "review_metadata",
            "effective_version",
            "status",
        }
        if not isinstance(value, Mapping) or set(value) != required:
            raise RoleProjectionError("REGISTRY_INVALID", "policy shape is invalid")
        try:
            role = _as_enum(value["audience_role"], AudienceRole, "audience_role")
            purpose = _as_enum(value["purpose_of_use"], PurposeOfUse, "purpose_of_use")
            modes = tuple(
                _as_enum(item, ProjectionMode, "allowed_modes")
                for item in _string_tuple(value["allowed_modes"], "allowed_modes")
            )
            source_statuses = tuple(
                _as_enum(item, SourceStatus, "allowed_source_statuses")
                for item in _string_tuple(
                    value["allowed_source_statuses"], "allowed_source_statuses"
                )
            )
            relation = _as_enum(value["required_relation"], TrustedRelation, "required_relation")
            disclosure = _as_enum(
                value["disclosure_requirement"], DisclosureRequirement, "disclosure_requirement"
            )
            policy = cls(
                schema_version=_require_text(value["schema_version"], "schema_version"),
                policy_id=_require_text(value["policy_id"], "policy_id"),
                policy_version=_require_text(value["policy_version"], "policy_version"),
                policy_hash=value["policy_hash"],
                audience_role=role,
                purpose_of_use=purpose,
                allowed_modes=modes,
                allowed_source_statuses=source_statuses,
                allowed_claim_codes=_string_tuple(
                    value["allowed_claim_codes"], "allowed_claim_codes", code=True, allow_empty=True
                ),
                allowed_limitation_codes=_string_tuple(
                    value["allowed_limitation_codes"], "allowed_limitation_codes", code=True
                ),
                public_field_allowlist=_string_tuple(
                    value["public_field_allowlist"], "public_field_allowlist"
                ),
                required_relation=relation,
                disclosure_requirement=disclosure,
                synthetic_only=value["synthetic_only"],
                review_metadata=PolicyReviewMetadata.from_mapping(value["review_metadata"]),
                effective_version=_require_text(value["effective_version"], "effective_version"),
                status=_require_text(value["status"], "status"),
            )
            return policy
        except KeyError as exc:
            raise RoleProjectionError("REGISTRY_INVALID", "policy field is missing") from exc
        except TypeError as exc:
            raise RoleProjectionError("REGISTRY_INVALID", "policy field has invalid type") from exc

    def to_mapping(self, *, include_hash: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "audience_role": self.audience_role.value,
            "purpose_of_use": self.purpose_of_use.value,
            "allowed_modes": [item.value for item in self.allowed_modes],
            "allowed_source_statuses": [item.value for item in self.allowed_source_statuses],
            "allowed_claim_codes": list(self.allowed_claim_codes),
            "allowed_limitation_codes": list(self.allowed_limitation_codes),
            "public_field_allowlist": list(self.public_field_allowlist),
            "required_relation": self.required_relation.value,
            "disclosure_requirement": self.disclosure_requirement.value,
            "synthetic_only": self.synthetic_only,
            "review_metadata": self.review_metadata.to_mapping(),
            "effective_version": self.effective_version,
            "status": self.status,
        }
        if include_hash:
            result["policy_hash"] = self.policy_hash
        return result

    def to_dict(self) -> dict[str, Any]:
        return self.to_mapping()

    def assert_integrity(self) -> None:
        """Recompute the hash after possible same-process typed tampering."""

        try:
            expected = canonical_policy_hash(self)
        except (TypeError, ValueError, AttributeError) as exc:
            raise PolicyIntegrityError("POLICY_TAMPERED") from exc
        if expected != self.policy_hash:
            raise PolicyIntegrityError("POLICY_TAMPERED")


PolicyRecord = RoleProjectionPolicy
RoleProjectionPolicyRecord = RoleProjectionPolicy


_TRUSTED_AUDIENCE_CAPABILITY = object()
_PROMPT_FACING_CAPABILITY = object()


@dataclass(frozen=True, slots=True)
class TrustedAudienceContext:
    """Trusted role/purpose/relation state for a controlled projection port.

    The constructor guard protects the public boundary; hostile code already
    running in the same process can inspect or bypass private state, which is
    explicitly out of scope for this process-local capability.
    """

    audience_role: AudienceRole
    purpose_of_use: PurposeOfUse
    subject_relation: TrustedRelation
    execution_mode: ProjectionMode
    disclosure_authorization: DisclosureAuthorization
    source_status: SourceStatus
    source_claim_codes: tuple[str, ...]
    safety_action: SafetyAction
    request_id: str
    trace_id: str
    context_id: str
    context_version: str
    _capability: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._capability is not _TRUSTED_AUDIENCE_CAPABILITY:
            raise TypeError("TrustedAudienceContext is internal-only")
        for name, enum_type in (
            ("audience_role", AudienceRole),
            ("purpose_of_use", PurposeOfUse),
            ("subject_relation", TrustedRelation),
            ("execution_mode", ProjectionMode),
            ("disclosure_authorization", DisclosureAuthorization),
            ("source_status", SourceStatus),
            ("safety_action", SafetyAction),
        ):
            if not isinstance(getattr(self, name), enum_type):
                raise RoleProjectionError("TRUSTED_CONTEXT_REQUIRED", f"{name} is not typed")
        _string_tuple(self.source_claim_codes, "source_claim_codes", code=True, allow_empty=True)
        for name, value in (
            ("request_id", self.request_id),
            ("trace_id", self.trace_id),
            ("context_id", self.context_id),
            ("context_version", self.context_version),
        ):
            _require_safe_trace(value, name)

    @property
    def role(self) -> AudienceRole:
        return self.audience_role

    @property
    def purpose(self) -> PurposeOfUse:
        return self.purpose_of_use

    @property
    def relationship(self) -> TrustedRelation:
        return self.subject_relation

    @property
    def relation(self) -> TrustedRelation:
        return self.subject_relation

    @property
    def mode(self) -> ProjectionMode:
        return self.execution_mode

def _build_trusted_audience_context(value: Mapping[str, Any]) -> TrustedAudienceContext:
    """Controlled internal/test seam for constructing trusted context.

    The public request surface must not accept a mapping in place of this
    capability.  A caller may only pass the resulting typed object to an
    engine boundary that explicitly requires it.
    """

    required = {
        "audience_role",
        "purpose_of_use",
        "subject_relation",
        "execution_mode",
        "disclosure_authorization",
        "source_status",
        "source_claim_codes",
        "safety_action",
        "request_id",
        "trace_id",
        "context_id",
        "context_version",
    }
    legacy_required = {
        "audience_role",
        "purpose_of_use",
        "relation",
        "mode",
        "source_status",
        "source_claim_codes",
        "safety_action",
        "request_id",
        "trace_id",
        "context_id",
        "context_version",
    }
    if not isinstance(value, Mapping):
        raise RoleProjectionError("TRUSTED_CONTEXT_REQUIRED", "trusted context shape is invalid")
    if set(value) == legacy_required:
        value = {
            **value,
            "subject_relation": value["relation"],
            "execution_mode": value["mode"],
            "disclosure_authorization": DisclosureAuthorization.NOT_AUTHORIZED.value,
        }
    elif set(value) != required:
        raise RoleProjectionError("TRUSTED_CONTEXT_REQUIRED", "trusted context shape is invalid")
    try:
        return TrustedAudienceContext(
            audience_role=_as_enum(value["audience_role"], AudienceRole, "audience_role"),
            purpose_of_use=_as_enum(value["purpose_of_use"], PurposeOfUse, "purpose_of_use"),
            subject_relation=_as_enum(
                value["subject_relation"], TrustedRelation, "subject_relation"
            ),
            execution_mode=_as_enum(
                value["execution_mode"], ProjectionMode, "execution_mode"
            ),
            disclosure_authorization=_as_enum(
                value["disclosure_authorization"],
                DisclosureAuthorization,
                "disclosure_authorization",
            ),
            source_status=_as_enum(value["source_status"], SourceStatus, "source_status"),
            source_claim_codes=_string_tuple(
                value["source_claim_codes"], "source_claim_codes", code=True, allow_empty=True
            ),
            safety_action=_as_enum(value["safety_action"], SafetyAction, "safety_action"),
            request_id=_require_safe_trace(value["request_id"], "request_id"),
            trace_id=_require_safe_trace(value["trace_id"], "trace_id"),
            context_id=_require_safe_trace(value["context_id"], "context_id"),
            context_version=_require_safe_trace(value["context_version"], "context_version"),
            _capability=_TRUSTED_AUDIENCE_CAPABILITY,
        )
    except KeyError as exc:
        raise RoleProjectionError("TRUSTED_CONTEXT_REQUIRED") from exc


# Short private seam name retained for integration code following D3-2 style.
_build_trusted_context = _build_trusted_audience_context
TrustedContext = TrustedAudienceContext


@dataclass(frozen=True, slots=True)
class PromptClaim:
    """A non-provenance claim safe for a prompt-facing surface."""

    claim_code: str
    value: str | bool | int | float

    def __post_init__(self) -> None:
        if not isinstance(self.claim_code, str) or not _CODE.fullmatch(self.claim_code):
            raise RoleProjectionError("ABSTAIN_POLICY_MISMATCH", "claim code is invalid")
        if _is_forbidden_projection_code(self.claim_code):
            raise RoleProjectionError(
                "ABSTAIN_POLICY_MISMATCH", "claim code carries forbidden semantics"
            )
        if not isinstance(self.value, (str, bool, int, float)):
            raise RoleProjectionError("ABSTAIN_POLICY_MISMATCH", "claim value is invalid")
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise RoleProjectionError("ABSTAIN_POLICY_MISMATCH", "claim value must be finite")

    def to_dict(self) -> dict[str, Any]:
        return {"claim_code": self.claim_code, "value": self.value}


@dataclass(frozen=True, slots=True)
class PromptCitation:
    """Opaque approved citation reference; it never contains source text."""

    source_chunk_id: str
    locator: str | None = None

    def __post_init__(self) -> None:
        _require_safe_trace(self.source_chunk_id, "source_chunk_id")
        if self.locator is not None and (
            not isinstance(self.locator, str) or not self.locator.strip() or len(self.locator) > 256
        ):
            raise RoleProjectionError("ABSTAIN_POLICY_MISMATCH", "citation locator is invalid")

    def to_dict(self) -> dict[str, Any]:
        return {"source_chunk_id": self.source_chunk_id, "locator": self.locator}


Claim = PromptClaim
Citation = PromptCitation


def validate_claim_monotonicity(
    emitted_claim_codes: Sequence[str],
    source_approved_claim_codes: Sequence[str],
    policy: RoleProjectionPolicy,
) -> tuple[str, ...]:
    """Return validated emitted codes or fail closed on invention/upgrading.

    D3-3 may only project codes already approved by D3-2 *and* explicitly
    allowed by the selected role policy.  The helper returns a stable tuple so
    callers can use it directly when building the audit projection.
    """

    emitted = _string_tuple(emitted_claim_codes, "emitted_claim_codes", code=True, allow_empty=True)
    source = _string_tuple(
        source_approved_claim_codes,
        "source_approved_claim_codes",
        code=True,
        allow_empty=True,
    )
    if not set(emitted).issubset(source) or not set(emitted).issubset(policy.allowed_claim_codes):
        raise RoleProjectionError("SOURCE_CLAIMS_NOT_SUBSET")
    return emitted


assert_claim_monotonicity = validate_claim_monotonicity


@dataclass(frozen=True, slots=True)
class StatusExtension:
    """A non-canonical audit diagnostic that must carry a justification."""

    code: str
    justification: str

    def __post_init__(self) -> None:
        _require_text(self.code, "status_extension.code")
        if self.code in CANONICAL_PROJECTION_STATUSES:
            raise RoleProjectionError(
                "REGISTRY_INVALID", "status extension duplicates canonical status"
            )
        if not isinstance(self.justification, str) or not self.justification.strip():
            raise RoleProjectionError("REGISTRY_INVALID", "status extension requires justification")

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "justification": self.justification}


@dataclass(frozen=True, slots=True)
class PromptFacingProjection:
    """Public projection created only through the internal construction seam.

    The capability is process-local.  Code already running in this process can
    inspect or bypass private state; that hostile same-process threat is out of
    scope.  The guard prevents ordinary callers from manufacturing a prompt
    payload outside the policy-controlled projection path.
    """

    status: ProjectionStatus
    claims: tuple[PromptClaim, ...] = ()
    limitations: tuple[str, ...] = ()
    citations: tuple[PromptCitation, ...] = ()
    _capability: object = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._assert_internal_capability()
        if not isinstance(self.status, ProjectionStatus):
            raise RoleProjectionError("ABSTAIN_POLICY_MISMATCH", "projection status is invalid")
        if any(not isinstance(item, PromptClaim) for item in self.claims):
            raise RoleProjectionError("ABSTAIN_POLICY_MISMATCH", "claims are not typed")
        _validated_limitation_codes(
            self.limitations,
            "limitations",
            allow_empty=True,
            reason_code="ABSTAIN_POLICY_MISMATCH",
        )
        if any(not isinstance(item, PromptCitation) for item in self.citations):
            raise RoleProjectionError("ABSTAIN_POLICY_MISMATCH", "citations are not typed")
        if self.status is not ProjectionStatus.READY_FOR_PROMPT and (
            self.claims or self.limitations or self.citations
        ):
            raise RoleProjectionError(
                "ABSTAIN_DISCLOSURE_NOT_AUTHORIZED",
                "public denial envelope must be empty",
            )

    def _assert_internal_capability(self) -> None:
        if self._capability is not _PROMPT_FACING_CAPABILITY:
            raise TypeError("PromptFacingProjection is internal-only")

    def to_dict(self) -> dict[str, Any]:
        """Serialize only the public envelope; no IDs or diagnostic reason."""

        self._assert_internal_capability()
        return {
            "status": self.status.value,
            "claims": [item.to_dict() for item in self.claims],
            "limitations": list(self.limitations),
            "citations": [item.to_dict() for item in self.citations],
        }

    def to_public_dict(self) -> dict[str, Any]:
        return self.to_dict()

    @property
    def content_claim_codes(self) -> tuple[str, ...]:
        """Claim-code view used by the monotonicity boundary."""

        self._assert_internal_capability()
        return tuple(item.claim_code for item in self.claims)


def _build_prompt_facing_projection(
    *,
    status: ProjectionStatus,
    claims: Sequence[PromptClaim] = (),
    limitations: Sequence[str] = (),
    citations: Sequence[PromptCitation] = (),
) -> PromptFacingProjection:
    """Build a prompt projection for the policy-controlled engine seam.

    This is intentionally private and process-local.  It is not a hostile
    same-process security boundary or a substitute for policy authorization.
    """

    instance = object.__new__(PromptFacingProjection)
    object.__setattr__(instance, "status", status)
    object.__setattr__(instance, "claims", tuple(claims))
    object.__setattr__(instance, "limitations", tuple(limitations))
    object.__setattr__(instance, "citations", tuple(citations))
    object.__setattr__(instance, "_capability", _PROMPT_FACING_CAPABILITY)
    instance.__post_init__()
    return instance


@dataclass(frozen=True, slots=True)
class AuditProjection:
    """Internal audit projection with minimum provenance and exact reasons."""

    status: ProjectionStatus
    reason_codes: tuple[ProjectionReasonCode, ...]
    request_id: str | None = None
    trace_id: str | None = None
    context_id: str | None = None
    context_version: str | None = None
    audience_role: AudienceRole | None = None
    purpose_of_use: PurposeOfUse | None = None
    relation: TrustedRelation | None = None
    disclosure_authorization: DisclosureAuthorization | None = None
    mode: ProjectionMode | None = None
    source_status: SourceStatus | None = None
    safety_action: SafetyAction | None = None
    policy_id: str | None = None
    policy_version: str | None = None
    policy_hash: str | None = None
    effective_version: str | None = None
    review_status: str | None = None
    review_decision_id: str | None = None
    source_approved_claim_codes: tuple[str, ...] = ()
    emitted_claim_codes: tuple[str, ...] = ()
    suppressed_claim_codes: tuple[str, ...] = ()
    source_chunk_ids: tuple[str, ...] = ()
    status_extension: StatusExtension | None = None

    _FORBIDDEN_FIELD_NAMES: ClassVar[frozenset[str]] = frozenset(
        {
            "raw_response",
            "response",
            "theta",
            "se",
            "standard_error",
            "full_prompt",
            "prompt_text",
            "pii",
            "name",
            "email",
            "phone",
        }
    )

    @property
    def subject_relation(self) -> TrustedRelation | None:
        return self.relation

    @property
    def execution_mode(self) -> ProjectionMode | None:
        return self.mode

    def __post_init__(self) -> None:
        if not isinstance(self.status, ProjectionStatus):
            raise RoleProjectionError("REGISTRY_INVALID", "audit status is invalid")
        if not self.reason_codes or any(
            not isinstance(item, ProjectionReasonCode) for item in self.reason_codes
        ):
            raise RoleProjectionError("REGISTRY_INVALID", "audit reason_codes are invalid")
        for name, value in (
            ("request_id", self.request_id),
            ("trace_id", self.trace_id),
            ("context_id", self.context_id),
            ("context_version", self.context_version),
            ("policy_id", self.policy_id),
            ("policy_version", self.policy_version),
            ("effective_version", self.effective_version),
        ):
            if value is not None:
                _require_safe_trace(value, name)
        if self.policy_hash is not None and not re.fullmatch(
            r"sha256:[0-9a-f]{64}", self.policy_hash
        ):
            raise RoleProjectionError("POLICY_HASH_MISMATCH", "audit policy_hash is invalid")
        _string_tuple(
            self.source_approved_claim_codes,
            "source_approved_claim_codes",
            code=True,
            allow_empty=True,
        )
        _string_tuple(self.emitted_claim_codes, "emitted_claim_codes", code=True, allow_empty=True)
        _string_tuple(
            self.suppressed_claim_codes,
            "suppressed_claim_codes",
            code=True,
            allow_empty=True,
        )
        for chunk_id in self.source_chunk_ids:
            _require_safe_trace(chunk_id, "source_chunk_ids")
        if self.status_extension is not None and not isinstance(
            self.status_extension, StatusExtension
        ):
            raise RoleProjectionError("REGISTRY_INVALID", "status_extension is not typed")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reason_codes": [item.value for item in self.reason_codes],
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "context_id": self.context_id,
            "context_version": self.context_version,
            "audience_role": self.audience_role.value if self.audience_role else None,
            "purpose_of_use": self.purpose_of_use.value if self.purpose_of_use else None,
            "relation": self.relation.value if self.relation else None,
            "disclosure_authorization": self.disclosure_authorization.value
            if self.disclosure_authorization
            else None,
            "mode": self.mode.value if self.mode else None,
            "source_status": self.source_status.value if self.source_status else None,
            "safety_action": self.safety_action.value if self.safety_action else None,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_hash": self.policy_hash,
            "effective_version": self.effective_version,
            "review_status": self.review_status,
            "review_decision_id": self.review_decision_id,
            "source_approved_claim_codes": list(self.source_approved_claim_codes),
            "emitted_claim_codes": list(self.emitted_claim_codes),
            "suppressed_claim_codes": list(self.suppressed_claim_codes),
            "source_chunk_ids": list(self.source_chunk_ids),
            "status_extension": self.status_extension.to_dict()
            if self.status_extension is not None
            else None,
        }


@dataclass(frozen=True, slots=True)
class RoleProjectionResult:
    """Combined internal result; public callers should use ``prompt`` only."""

    status: ProjectionStatus
    prompt: PromptFacingProjection
    audit: AuditProjection
    schema_version: str = _RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != _RESULT_SCHEMA_VERSION:
            raise RoleProjectionError("REGISTRY_INVALID", "result schema_version is invalid")
        if not isinstance(self.status, ProjectionStatus):
            raise RoleProjectionError("REGISTRY_INVALID", "result status is invalid")
        if not isinstance(self.prompt, PromptFacingProjection) or not isinstance(
            self.audit, AuditProjection
        ):
            raise RoleProjectionError("REGISTRY_INVALID", "result surfaces are not typed")
        if self.status is not self.prompt.status or self.status is not self.audit.status:
            raise RoleProjectionError("REGISTRY_INVALID", "result status surfaces disagree")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "prompt": self.prompt.to_dict(),
            "audit": self.audit.to_dict(),
        }

    def to_public_dict(self) -> dict[str, Any]:
        return self.prompt.to_public_dict()


ProjectionResult = RoleProjectionResult
RoleProjectionPolicyPack = RoleProjectionPolicy
PolicyPack = RoleProjectionPolicy
RolePolicyRecord = RoleProjectionPolicy
RoleProjectionStatus = ProjectionStatus
RoleProjectionReason = ProjectionReasonCode
SubjectRelation = TrustedRelation
ExecutionMode = ProjectionMode


@dataclass(frozen=True, slots=True)
class RoleProjectionPolicyRegistry:
    """Read-only registry requiring exact ID/version/hash lookup."""

    registry_version: str
    policies: tuple[RoleProjectionPolicy, ...]
    source: str | None = None
    schema_version: str = _REGISTRY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_text(self.registry_version, "registry_version")
        if self.schema_version != _REGISTRY_SCHEMA_VERSION:
            raise RoleProjectionError("REGISTRY_INVALID", "registry schema_version is invalid")
        if not self.policies:
            raise RoleProjectionError("REGISTRY_INVALID", "registry must contain policies")
        identities = [(item.policy_id, item.policy_version) for item in self.policies]
        if len(set(identities)) != len(identities):
            raise PolicySelectionError("POLICY_MISMATCH", "duplicate policy id/version")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, source: str | None = None) -> Self:
        required = {"schema_version", "registry_version", "policies"}
        if not isinstance(value, Mapping) or set(value) != required:
            raise RoleProjectionError("REGISTRY_INVALID", "registry shape is invalid")
        if value["schema_version"] != _REGISTRY_SCHEMA_VERSION:
            raise RoleProjectionError("REGISTRY_INVALID", "registry schema_version is invalid")
        raw = value["policies"]
        if not isinstance(raw, list) or not raw:
            raise RoleProjectionError("REGISTRY_INVALID", "registry policies are empty")
        policies = tuple(RoleProjectionPolicy.from_mapping(item) for item in raw)
        return cls(
            registry_version=_require_text(value["registry_version"], "registry_version"),
            policies=policies,
            source=source,
        )

    @classmethod
    def from_json(cls, path: str | Path) -> Self:
        selected = Path(path)
        try:
            payload = json.loads(
                selected.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise RoleProjectionError("REGISTRY_INVALID") from exc
        return cls.from_mapping(payload, source=str(selected))

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "registry_version": self.registry_version,
            "policies": [item.to_mapping() for item in self.policies],
        }

    def resolve(
        self,
        reference: PolicyReference | Mapping[str, Any] | str,
        policy_version: str | None = None,
        policy_hash: str | None = None,
    ) -> RoleProjectionPolicy:
        """Resolve only an exact identity; no wildcard/default/first-match path."""

        if isinstance(reference, PolicyReference):
            selected = reference
        elif isinstance(reference, Mapping):
            selected = PolicyReference.from_mapping(reference)
        elif isinstance(reference, str):
            if policy_version is None or policy_hash is None:
                raise PolicySelectionError("POLICY_REFERENCE_INVALID")
            try:
                selected = PolicyReference(reference, policy_version, policy_hash)
            except (RoleProjectionError, TypeError) as exc:
                raise PolicySelectionError("POLICY_REFERENCE_INVALID") from exc
        else:
            raise PolicySelectionError("POLICY_REFERENCE_INVALID")

        for policy in self.policies:
            try:
                policy.assert_integrity()
            except PolicyIntegrityError as exc:
                raise PolicyIntegrityError("POLICY_TAMPERED") from exc
        matches = [
            policy
            for policy in self.policies
            if policy.policy_id == selected.policy_id
            and policy.policy_version == selected.policy_version
        ]
        if not matches:
            raise PolicySelectionError("POLICY_MISSING")
        if len(matches) != 1:
            raise PolicySelectionError("POLICY_MISMATCH")
        policy = matches[0]
        if policy.policy_hash != selected.policy_hash:
            raise PolicySelectionError("POLICY_HASH_MISMATCH")
        return policy

    def resolve_exact(
        self,
        reference: PolicyReference | Mapping[str, Any] | str,
        policy_version: str | None = None,
        policy_hash: str | None = None,
        *,
        audience_role: AudienceRole | None = None,
        purpose_of_use: PurposeOfUse | None = None,
        required_relation: TrustedRelation | None = None,
        mode: ProjectionMode | None = None,
        source_status: SourceStatus | None = None,
    ) -> RoleProjectionPolicy:
        """Resolve identity and bind every supplied trusted selector exactly."""

        policy = self.resolve(reference, policy_version, policy_hash)
        checks = (
            (audience_role, policy.audience_role),
            (purpose_of_use, policy.purpose_of_use),
            (required_relation, policy.required_relation),
        )
        if any(expected is not None and expected is not actual for expected, actual in checks):
            raise PolicySelectionError("POLICY_MISMATCH")
        if mode is not None and mode not in policy.allowed_modes:
            raise PolicySelectionError("POLICY_MISMATCH")
        if source_status is not None and source_status not in policy.allowed_source_statuses:
            raise PolicySelectionError("POLICY_MISMATCH")
        return policy


PolicyRegistry = RoleProjectionPolicyRegistry


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


DEFAULT_POLICY_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2] / "assets" / "role_projection_policy_registry.v1.json"
)
DEFAULT_POLICY_PATH = DEFAULT_POLICY_REGISTRY_PATH


def load_role_projection_policy_registry(
    path: str | Path = DEFAULT_POLICY_REGISTRY_PATH,
) -> RoleProjectionPolicyRegistry:
    """Load one explicit registry path; policy selection remains exact."""

    return RoleProjectionPolicyRegistry.from_json(path)


load_policy_registry = load_role_projection_policy_registry


def resolve_role_projection_policy(
    reference: PolicyReference | Mapping[str, Any] | str,
    policy_version: str | None = None,
    policy_hash: str | None = None,
    *,
    registry: RoleProjectionPolicyRegistry | None = None,
) -> RoleProjectionPolicy:
    selected_registry = (
        registry if registry is not None else load_role_projection_policy_registry()
    )
    return selected_registry.resolve(reference, policy_version, policy_hash)


__all__ = [
    "ALLOWED_AUDIENCE_ROLES",
    "AudienceRole",
    "AuditProjection",
    "CANONICAL_PROJECTION_STATUSES",
    "Claim",
    "Citation",
    "DEFAULT_POLICY_REGISTRY_PATH",
    "DEFAULT_POLICY_PATH",
    "DisclosureRequirement",
    "DisclosureAuthorization",
    "ExecutionMode",
    "PolicyIntegrityError",
    "PolicyRecord",
    "PolicyReference",
    "PolicyRegistry",
    "PolicyPack",
    "PolicyReviewMetadata",
    "PolicySelectionError",
    "ProjectionMode",
    "RoleProjectionReason",
    "ProjectionReasonCode",
    "ProjectionResult",
    "ProjectionStatus",
    "PromptCitation",
    "PromptClaim",
    "PromptFacingProjection",
    "PurposeOfUse",
    "ReasonCode",
    "RoleProjectionError",
    "RoleProjectionPolicy",
    "RoleProjectionPolicyPack",
    "RoleProjectionPolicyRecord",
    "RolePolicyRecord",
    "RoleProjectionPolicyRegistry",
    "RoleProjectionResult",
    "RoleProjectionStatus",
    "SafetyAction",
    "SourceStatus",
    "StatusExtension",
    "TrustedAudienceContext",
    "TrustedContext",
    "TrustedRelation",
    "SubjectRelation",
    "_build_prompt_facing_projection",
    "_build_trusted_audience_context",
    "_build_trusted_context",
    "assert_claim_monotonicity",
    "canonical_policy_hash",
    "expected_purpose_for_role",
    "expected_relation_for_role",
    "load_policy_registry",
    "load_role_projection_policy_registry",
    "resolve_role_projection_policy",
    "validate_claim_monotonicity",
]
