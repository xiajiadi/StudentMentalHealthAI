"""Versioned, exact-match interpretation policy registry."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import (
    ConstructPolicy,
    ExecutionMode,
    InterpretationPolicyPack,
    PolicyReference,
)

_HASH_PREFIX = "sha256:"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_CLAIM_CODE = re.compile(r"^[A-Z][A-Z0-9_.-]{1,127}$")
_SCHEMA_VERSION = "interpretation-policy.v1"

# These codes and aliases must never be emitted as interpretation claims.  The
# list is deliberately broader than the shipped policy so a test or future
# policy cannot turn a renamed alias into a clinical-looking claim.
_FORBIDDEN_CLAIM_ALIASES = frozenset(
    {
        "DIAGNOSIS",
        "DIAGNOSTIC",
        "DISORDER",
        "CLINICAL",
        "CLINICAL_INFERENCE",
        "CLINICAL_RISK",
        "CLINICAL_SEVERITY",
        "SEVERITY",
        "RISK",
        "RISK_LEVEL",
        "RISK_BAND",
        "SUICIDE",
        "SUICIDE_INFERENCE",
        "SUICIDALITY",
        "SELF_HARM",
        "SELF_HARM_INFERENCE",
        "SELF_INJURY",
        "CRISIS",
        "CRISIS_INFERENCE",
        "CRISIS_RISK",
        "CRISIS_ROUTE",
        "TREATMENT",
        "THERAPY",
        "MEDICATION",
        "LEVEL",
        "LEVEL_1_TO_5",
        "LEVEL1TO5",
        "CUTOFF",
        "THRESHOLD",
        "VALIDATED_CUTOFF",
        "SCORE",
        "SCORE_BAND",
        "BAND",
        "THETA",
        "SE",
        "STANDARD_ERROR",
        "INTERVAL",
        "CONFIDENCE_INTERVAL",
        "PRECISION_AS_RISK",
        "PRECISION_RISK",
    }
)


def normalize_claim_code(value: str) -> str:
    """Normalize code spelling before applying the semantic deny-list."""

    return re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_")


def is_forbidden_claim_code(value: str) -> bool:
    """Return whether a claim code or alias is outside the D3-2 boundary."""

    normalized = normalize_claim_code(value)
    if normalized in _FORBIDDEN_CLAIM_ALIASES:
        return True
    if any(
        token in normalized
        for token in ("DIAGNOST", "DISORDER", "CLINICAL", "SUICIDE", "SELF_HARM", "SELFHARM")
    ):
        return True
    if "SELF_INJURY" in normalized or "CRISIS" in normalized:
        return True
    if normalized.startswith(("TREATMENT", "THERAPY", "MEDICATION")):
        return True
    if normalized.startswith("LEVEL_") or (
        normalized.startswith("LEVEL") and normalized[-1:].isdigit()
    ):
        return True
    if "RISK" in normalized or "CUTOFF" in normalized or "THRESHOLD" in normalized:
        return True
    if "SCORE" in normalized:
        return True
    if "BAND" in normalized:
        return True
    if "THETA" in normalized:
        return True
    if normalized == "SE" or normalized.startswith("SE_") or normalized.endswith("_SE"):
        return True
    if "INTERVAL" in normalized or "PRECISION" in normalized and "RISK" in normalized:
        return True
    return False


class PolicyRegistryError(ValueError):
    """The registry file or payload cannot be interpreted safely."""


class _DuplicateJSONKey(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def canonical_policy_hash(policy: Mapping[str, Any]) -> str:
    """Return the canonical ``sha256:`` hash for one parsed policy object."""

    if not isinstance(policy, Mapping):
        raise TypeError("policy must be a mapping")
    without_hash = {key: value for key, value in policy.items() if key != "policy_hash"}
    canonical = json.dumps(
        without_hash,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _HASH_PREFIX + hashlib.sha256(canonical).hexdigest()


def _nonempty_text(
    value: object,
    field_name: str,
    *,
    allow_freeform: bool = False,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PolicyRegistryError(f"{field_name} must be a non-empty string")
    if value in {"latest", "LATEST", "default", "DEFAULT", "*"} or "*" in value:
        raise PolicyRegistryError(f"{field_name} cannot use wildcard/default selection")
    if not allow_freeform and not _IDENTIFIER.fullmatch(value) and field_name not in {
        "instrument_version",
        "engineering_scope",
        "controller_scope",
        "review_status_detail",
    }:
        raise PolicyRegistryError(f"{field_name} has an invalid identifier")
    return value


def _string_list(
    value: object,
    field_name: str,
    *,
    claim_codes: bool = False,
    allow_empty: bool = False,
    deny_forbidden: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PolicyRegistryError(f"{field_name} must be a non-empty string list")
    if not allow_empty and not value:
        raise PolicyRegistryError(f"{field_name} must be a non-empty string list")
    items = tuple(value)
    if len(set(items)) != len(items):
        raise PolicyRegistryError(f"{field_name} must not contain duplicates")
    for item in items:
        if not item.strip() or item in {"latest", "LATEST", "default", "DEFAULT", "*"}:
            raise PolicyRegistryError(f"{field_name} contains an invalid selection")
        if claim_codes and not _CLAIM_CODE.fullmatch(item):
            raise PolicyRegistryError(f"{field_name} contains an invalid claim code")
        if claim_codes and deny_forbidden and is_forbidden_claim_code(item):
            raise PolicyRegistryError(f"{field_name} contains a forbidden claim code")
    return items


def _nullable_text(value: object, field_name: str) -> str | None:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise PolicyRegistryError(f"{field_name} must be null or non-empty text")
    return value


def _parse_construct(key: object, value: object) -> ConstructPolicy:
    if not isinstance(key, str) or not key or not _IDENTIFIER.fullmatch(key):
        raise PolicyRegistryError("construct policy key is invalid")
    if not isinstance(value, Mapping):
        raise PolicyRegistryError(f"construct policy {key} must be an object")
    required = {
        "construct_id",
        "status",
        "direction",
        "high_score_meaning",
        "low_score_meaning",
        "allowed_claim_codes",
        "forbidden_claim_codes",
    }
    if set(value) != required:
        raise PolicyRegistryError(f"construct policy {key} shape is invalid")
    construct_id = _nonempty_text(
        value.get("construct_id"), "construct_id", allow_freeform=True
    )
    status = _nonempty_text(value.get("status"), "construct status")
    direction = _nullable_text(value.get("direction"), "construct direction")
    high_meaning = _nullable_text(value.get("high_score_meaning"), "high_score_meaning")
    low_meaning = _nullable_text(value.get("low_score_meaning"), "low_score_meaning")
    allowed = _string_list(
        value.get("allowed_claim_codes"),
        "allowed_claim_codes",
        claim_codes=True,
        allow_empty=True,
        deny_forbidden=True,
    )
    forbidden = _string_list(
        value.get("forbidden_claim_codes"), "forbidden_claim_codes", claim_codes=True
    )
    if set(allowed) & set(forbidden):
        raise PolicyRegistryError("construct claim code cannot be both allowed and forbidden")
    return ConstructPolicy(
        construct_id=construct_id,
        status=status,
        direction=direction,
        high_score_meaning=high_meaning,
        low_score_meaning=low_meaning,
        allowed_claim_codes=allowed,
        forbidden_claim_codes=forbidden,
    )


def policy_from_mapping(
    value: Mapping[str, Any],
    *,
    allow_test_only: bool = False,
) -> InterpretationPolicyPack:
    """Parse and hash-check one policy object without mutating it."""

    required = {
        "schema_version",
        "policy_id",
        "policy_version",
        "effective_version",
        "policy_hash",
        "instrument_id",
        "instrument_version",
        "population_scope",
        "allowed_modes",
        "synthetic_only",
        "engineering_scope",
        "controller_scope",
        "psychology_review_status",
        "review_status_detail",
        "review_decision_id",
        "evidence_refs",
        "construct_policies",
        "allowed_claims",
        "forbidden_claims",
        "policy_kind",
        "limitations",
    }
    if not isinstance(value, Mapping):
        raise PolicyRegistryError("policy shape is invalid")
    if "policy_hash" not in value:
        raise PolicyRegistryError("POLICY_HASH_MISSING")
    if set(value) != required:
        raise PolicyRegistryError("policy shape is invalid")
    if value.get("schema_version") != _SCHEMA_VERSION:
        raise PolicyRegistryError("policy schema_version is invalid")

    policy_id = _nonempty_text(value.get("policy_id"), "policy_id")
    policy_version = _nonempty_text(value.get("policy_version"), "policy_version")
    effective_version = _nonempty_text(value.get("effective_version"), "effective_version")
    policy_hash = _nonempty_text(value.get("policy_hash"), "policy_hash")
    actual_hash = canonical_policy_hash(value)
    if policy_hash != actual_hash:
        raise PolicyRegistryError("policy_hash does not match canonical policy content")
    instrument_id = _nonempty_text(value.get("instrument_id"), "instrument_id")
    instrument_version = _nonempty_text(value.get("instrument_version"), "instrument_version")
    population_scope = _nonempty_text(value.get("population_scope"), "population_scope")
    allowed_modes_value = value.get("allowed_modes")
    if (
        not isinstance(allowed_modes_value, list)
        or not allowed_modes_value
        or not all(isinstance(item, str) for item in allowed_modes_value)
        or len(set(allowed_modes_value)) != len(allowed_modes_value)
    ):
        raise PolicyRegistryError("allowed_modes must be a unique non-empty list")
    try:
        allowed_modes = tuple(ExecutionMode(item) for item in allowed_modes_value)
    except ValueError as exc:
        raise PolicyRegistryError("allowed_modes contains an unknown mode") from exc
    if ExecutionMode.REAL_USER in allowed_modes:
        raise PolicyRegistryError("REAL_USER cannot be allowed by an interpretation policy")

    synthetic_only = value.get("synthetic_only")
    if not isinstance(synthetic_only, bool):
        raise PolicyRegistryError("synthetic_only must be boolean")
    engineering_scope = _nonempty_text(value.get("engineering_scope"), "engineering_scope")
    controller_scope = _nonempty_text(value.get("controller_scope"), "controller_scope")
    psychology_status = _nonempty_text(
        value.get("psychology_review_status"), "psychology_review_status"
    )
    review_detail = _nonempty_text(value.get("review_status_detail"), "review_status_detail")
    review_decision_id = _nonempty_text(value.get("review_decision_id"), "review_decision_id")
    evidence_refs = _string_list(value.get("evidence_refs"), "evidence_refs")
    allowed_claims = _string_list(
        value.get("allowed_claims"),
        "allowed_claims",
        claim_codes=True,
        allow_empty=True,
        deny_forbidden=True,
    )
    forbidden_claims = _string_list(
        value.get("forbidden_claims"), "forbidden_claims", claim_codes=True
    )
    if set(allowed_claims) & set(forbidden_claims):
        raise PolicyRegistryError("claim code cannot be both allowed and forbidden")
    policy_kind = _nonempty_text(value.get("policy_kind"), "policy_kind")
    if policy_kind == "SYNTHETIC_TEST_ONLY" and not allow_test_only:
        raise PolicyRegistryError("test-only policies are not accepted by the shipped registry")
    if policy_kind not in {"SHIPPED_CONSERVATIVE", "SYNTHETIC_TEST_ONLY"}:
        raise PolicyRegistryError("policy_kind is invalid")
    limitations = _string_list(value.get("limitations"), "limitations", claim_codes=True)

    constructs_value = value.get("construct_policies")
    if not isinstance(constructs_value, Mapping) or not constructs_value:
        raise PolicyRegistryError("construct_policies must be a non-empty object")
    constructs: dict[str, ConstructPolicy] = {}
    for key, construct in constructs_value.items():
        parsed = _parse_construct(key, construct)
        if parsed.construct_id in constructs:
            raise PolicyRegistryError("duplicate construct policy")
        constructs[parsed.construct_id] = parsed

    return InterpretationPolicyPack(
        schema_version=_SCHEMA_VERSION,
        policy_id=policy_id,
        policy_version=policy_version,
        effective_version=effective_version,
        policy_hash=policy_hash,
        instrument_id=instrument_id,
        instrument_version=instrument_version,
        population_scope=population_scope,
        allowed_modes=allowed_modes,
        synthetic_only=synthetic_only,
        engineering_scope=engineering_scope,
        controller_scope=controller_scope,
        psychology_review_status=psychology_status,
        review_status_detail=review_detail,
        review_decision_id=review_decision_id,
        evidence_refs=evidence_refs,
        construct_policies=constructs,
        allowed_claims=allowed_claims,
        forbidden_claims=forbidden_claims,
        policy_kind=policy_kind,
        limitations=limitations,
    )


@dataclass(frozen=True, slots=True)
class InvalidPolicyEntry:
    policy_id: str | None
    policy_version: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class PolicyLookup:
    policy: InterpretationPolicyPack | None
    reason: str


@dataclass(frozen=True, slots=True)
class PolicyRegistry:
    """Read-only registry with duplicate and invalid entries retained as failures."""

    policies: tuple[InterpretationPolicyPack, ...]
    invalid_entries: tuple[InvalidPolicyEntry, ...] = ()
    duplicate_id_versions: frozenset[tuple[str, str]] = frozenset()
    source: str | None = None

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        allow_test_only: bool = False,
        source: str | None = None,
    ) -> PolicyRegistry:
        if not isinstance(payload, Mapping):
            raise PolicyRegistryError("registry must be an object")
        if set(payload) != {"schema_version", "registry_version", "policies"}:
            raise PolicyRegistryError("registry shape is invalid")
        if payload.get("schema_version") != "interpretation-policy-registry.v1":
            raise PolicyRegistryError("registry schema_version is invalid")
        if not isinstance(payload.get("registry_version"), str) or not payload.get(
            "registry_version"
        ):
            raise PolicyRegistryError("registry_version is invalid")
        raw_policies = payload.get("policies")
        if not isinstance(raw_policies, list) or not raw_policies:
            raise PolicyRegistryError("registry policies must be a non-empty list")

        parsed: list[InterpretationPolicyPack] = []
        invalid: list[InvalidPolicyEntry] = []
        for item in raw_policies:
            policy_id = item.get("policy_id") if isinstance(item, Mapping) else None
            policy_version = item.get("policy_version") if isinstance(item, Mapping) else None
            try:
                parsed.append(policy_from_mapping(item, allow_test_only=allow_test_only))
            except (PolicyRegistryError, TypeError) as exc:
                invalid.append(
                    InvalidPolicyEntry(
                        policy_id=policy_id if isinstance(policy_id, str) else None,
                        policy_version=policy_version if isinstance(policy_version, str) else None,
                        reason=str(exc),
                    )
                )

        grouped: dict[tuple[str, str], list[InterpretationPolicyPack]] = defaultdict(list)
        for policy in parsed:
            grouped[(policy.policy_id, policy.policy_version)].append(policy)
        duplicates = frozenset(key for key, values in grouped.items() if len(values) != 1)
        if duplicates:
            for key in duplicates:
                invalid.append(
                    InvalidPolicyEntry(
                        policy_id=key[0],
                        policy_version=key[1],
                        reason="duplicate policy id/version",
                    )
                )
            parsed = [
                policy
                for policy in parsed
                if (policy.policy_id, policy.policy_version) not in duplicates
            ]
        return cls(
            policies=tuple(parsed),
            invalid_entries=tuple(invalid),
            duplicate_id_versions=duplicates,
            source=source,
        )

    @classmethod
    def from_json(
        cls,
        path: str | Path,
        *,
        allow_test_only: bool = False,
    ) -> PolicyRegistry:
        """Named constructor retained for callers that prefer file semantics."""

        return load_policy_registry(path, allow_test_only=allow_test_only)

    def lookup(self, reference: PolicyReference) -> PolicyLookup:
        """Resolve only the exact requested id/version/hash triple."""

        key = (reference.policy_id, reference.policy_version)
        if key in self.duplicate_id_versions:
            return PolicyLookup(None, "POLICY_DUPLICATE")
        if any(
            entry.policy_id == reference.policy_id
            and entry.policy_version == reference.policy_version
            for entry in self.invalid_entries
        ):
            if any(
                entry.policy_id == reference.policy_id
                and entry.policy_version == reference.policy_version
                and "policy_hash" in entry.reason.lower()
                for entry in self.invalid_entries
            ):
                return PolicyLookup(None, "POLICY_HASH_MISMATCH")
            return PolicyLookup(None, "POLICY_INVALID")
        matches = [
            policy
            for policy in self.policies
            if policy.policy_id == reference.policy_id
            and policy.policy_version == reference.policy_version
            and policy.policy_hash == reference.policy_hash
        ]
        if not matches:
            same_id_version = [
                policy
                for policy in self.policies
                if policy.policy_id == reference.policy_id
                and policy.policy_version == reference.policy_version
            ]
            if same_id_version:
                return PolicyLookup(None, "POLICY_HASH_MISMATCH")
            return PolicyLookup(None, "POLICY_NOT_FOUND")
        if len(matches) != 1:
            return PolicyLookup(None, "POLICY_DUPLICATE")
        return PolicyLookup(matches[0], "OK")


def load_policy_registry(path: str | Path, *, allow_test_only: bool = False) -> PolicyRegistry:
    """Load one exact local registry file; no path discovery or fallback occurs."""

    selected = Path(path)
    try:
        payload = json.loads(
            selected.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (OSError, UnicodeError, json.JSONDecodeError, _DuplicateJSONKey) as exc:
        raise PolicyRegistryError(f"cannot load policy registry: {exc}") from exc
    return PolicyRegistry.from_payload(
        payload,
        allow_test_only=allow_test_only,
        source=str(selected),
    )
