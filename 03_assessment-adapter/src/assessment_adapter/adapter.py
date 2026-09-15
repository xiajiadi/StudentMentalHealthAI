"""Deterministic D3-2 assessment interpretation adapter."""

from __future__ import annotations

import re
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any

from .models import (
    _TRUSTED_CONTEXT_CAPABILITY,
    Claim,
    ExecutionMode,
    InterpretationPolicyPack,
    InterpretationRequest,
    InterpretationResult,
    InterpretationStatus,
    PolicyReference,
    ReasonCode,
    SafetyAction,
    TrustedInterpretationContext,
)
from .policy import PolicyRegistry, is_forbidden_claim_code, load_policy_registry
from .schema import AssessmentValidationError, validate_assessment_v1

DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parents[2] / "assets" / "interpretation_policy_registry.v1.json"
)
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_BYPASS_ACTIONS = {
    SafetyAction.CRISIS_ROUTE,
    SafetyAction.REVIEW_REQUIRED,
    SafetyAction.BLOCK,
}
_REQUIRED_MEASUREMENT_LIMITATIONS = (
    "SYNTHETIC_ONLY",
    "NOT_DIAGNOSTIC",
    "NO_VALIDATED_CUTOFF",
    "NO_CLINICAL_INFERENCE",
    "NO_CRISIS_INFERENCE",
)
_ASSESSMENT_ID = re.compile(r"^ASSESS_[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SUBJECT_ID = re.compile(r"^SUBJ_[A-Za-z0-9][A-Za-z0-9_.-]*$")
_VALID_POLICY_KINDS = frozenset({"SHIPPED_CONSERVATIVE", "SYNTHETIC_TEST_ONLY"})


def _safe_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _safe_anonymous_id(value: object, pattern: re.Pattern[str]) -> str | None:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        return None
    return value


def _assessment_identity(assessment: object) -> dict[str, str | None]:
    if not isinstance(assessment, Mapping):
        return {
            "assessment_id": None,
            "subject_id": None,
            "instrument_id": None,
            "instrument_version": None,
            "population_scope": None,
        }
    instrument = assessment.get("instrument")
    if not isinstance(instrument, Mapping):
        instrument = {}
    return {
        "assessment_id": _safe_anonymous_id(assessment.get("assessment_id"), _ASSESSMENT_ID),
        "subject_id": _safe_anonymous_id(assessment.get("subject_id"), _SUBJECT_ID),
        "instrument_id": _safe_text(instrument.get("instrument_id")),
        "instrument_version": _safe_text(instrument.get("version")),
        "population_scope": _safe_text(assessment.get("population_scope")),
    }


def _policy_identity(policy: InterpretationPolicyPack | None) -> dict[str, str | None]:
    if policy is None:
        return {
            "policy_id": None,
            "policy_version": None,
            "effective_version": None,
            "policy_hash": None,
            "policy_kind": None,
            "psychology_review_status": None,
            "review_decision_id": None,
        }
    return {
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "effective_version": policy.effective_version,
        "policy_hash": policy.policy_hash,
        "policy_kind": policy.policy_kind,
        "psychology_review_status": policy.psychology_review_status,
        "review_decision_id": policy.review_decision_id,
    }


def _audit(
    context: TrustedInterpretationContext | None,
    request: InterpretationRequest,
) -> dict[str, str | None]:
    if context is None:
        return {
            "request_id": request.request_id,
            "trace_id": request.trace_id,
            "context_id": None,
            "context_version": None,
            "execution_mode": None,
            "safety_action": None,
        }
    return {
        "request_id": context.request_id,
        "trace_id": context.trace_id,
        "context_id": context.context_id,
        "context_version": context.context_version,
        "execution_mode": context.execution_mode.value,
        "safety_action": context.safety_action.value,
    }


def _result(
    *,
    status: InterpretationStatus,
    reason_codes: tuple[str, ...],
    request: InterpretationRequest,
    context: TrustedInterpretationContext | None,
    policy: InterpretationPolicyPack | None = None,
    limitations: tuple[str, ...] = (),
    claims: tuple[Claim, ...] = (),
) -> InterpretationResult:
    identity = _assessment_identity(request.assessment)
    return InterpretationResult(
        schema_version="interpretation_result.v1",
        status=status,
        reason_codes=reason_codes,
        assessment_id=identity["assessment_id"],
        subject_id=identity["subject_id"],
        instrument_id=identity["instrument_id"],
        instrument_version=identity["instrument_version"],
        population_scope=identity["population_scope"],
        policy=_policy_identity(policy),
        claims=claims,
        limitations=limitations,
        audit=_audit(context, request),
    )


def _coerce_context_value(
    value: object,
    enum_type: type[ExecutionMode] | type[SafetyAction],
    name: str,
) -> Any:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"{name} is invalid") from exc


def _build_trusted_interpretation_context(
    value: Mapping[str, Any],
) -> TrustedInterpretationContext:
    """Build an internal trusted context for controlled ports and tests.

    This private seam mirrors D3-1.  It is process-local and does not prove a
    human approval, consent decision or cryptographic authority.
    """

    required = {
        "execution_mode",
        "assessment_population",
        "context_id",
        "context_version",
        "safety_action",
        "request_id",
        "trace_id",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise ValueError("trusted context shape is invalid")
    text_fields = {
        "assessment_population",
        "context_id",
        "context_version",
        "request_id",
        "trace_id",
    }
    for key in text_fields:
        item = value.get(key)
        if not isinstance(item, str) or not item.strip() or not _IDENTIFIER.fullmatch(item):
            raise ValueError(f"trusted context field {key} is invalid")
    execution_mode = _coerce_context_value(value["execution_mode"], ExecutionMode, "execution_mode")
    safety_action = _coerce_context_value(value["safety_action"], SafetyAction, "safety_action")
    return TrustedInterpretationContext(
        execution_mode=execution_mode,
        assessment_population=value["assessment_population"],
        context_id=value["context_id"],
        context_version=value["context_version"],
        safety_action=safety_action,
        request_id=value["request_id"],
        trace_id=value["trace_id"],
        _capability=_TRUSTED_CONTEXT_CAPABILITY,
    )


# Explicit alias for integration/test code that used the shorter D3-1 naming style.
_build_trusted_context = _build_trusted_interpretation_context


def _request_from_input(value: object) -> InterpretationRequest:
    if isinstance(value, InterpretationRequest):
        return value
    if isinstance(value, Mapping):
        return InterpretationRequest.from_mapping(value)
    raise TypeError("interpretation request must be a typed request or mapping")


def _error_request(value: object) -> InterpretationRequest:
    assessment: Mapping[str, Any] = {}
    if isinstance(value, Mapping) and isinstance(value.get("assessment"), Mapping):
        assessment = value["assessment"]
    return InterpretationRequest(
        assessment=assessment,
        policy_ref=PolicyReference("INVALID", "INVALID", "INVALID"),
    )


def _invalid_request_result(
    value: object,
    *,
    reason: str = ReasonCode.POLICY_REFERENCE_INVALID.value,
    status: InterpretationStatus = InterpretationStatus.ABSTAIN_INPUT_INVALID,
) -> InterpretationResult:
    # A malformed request cannot safely supply policy identity or audit values.
    request = _error_request(value)
    return _result(
        status=status,
        reason_codes=(reason,),
        request=request,
        context=None,
    )


class InterpretationAdapter:
    """Deterministic policy gate over a completed CAT assessment object."""

    def __init__(self, registry: PolicyRegistry) -> None:
        self._registry = registry

    def interpret(
        self,
        request: InterpretationRequest,
        trusted_context: object,
    ) -> InterpretationResult:
        if not isinstance(request, InterpretationRequest):
            return _invalid_request_result(request)
        if not isinstance(trusted_context, TrustedInterpretationContext):
            return _result(
                status=InterpretationStatus.ABSTAIN_INPUT_INVALID,
                reason_codes=(ReasonCode.TRUSTED_CONTEXT_REQUIRED.value,),
                request=request,
                context=None,
            )
        context = trusted_context
        if not isinstance(context.execution_mode, ExecutionMode) or not isinstance(
            context.safety_action, SafetyAction
        ):
            return _result(
                status=InterpretationStatus.ABSTAIN_INPUT_INVALID,
                reason_codes=(ReasonCode.TRUSTED_CONTEXT_REQUIRED.value,),
                request=request,
                context=None,
            )
        if context.execution_mode is ExecutionMode.REAL_USER:
            return _result(
                status=InterpretationStatus.ABSTAIN_REAL_USER_BLOCKED,
                reason_codes=(InterpretationStatus.ABSTAIN_REAL_USER_BLOCKED.value,),
                request=request,
                context=context,
            )
        if context.safety_action in _BYPASS_ACTIONS:
            return _result(
                status=InterpretationStatus.ABSTAIN_SAFETY_BYPASS,
                reason_codes=(ReasonCode.SAFETY_BYPASS.value,),
                request=request,
                context=context,
            )

        try:
            validate_assessment_v1(request.assessment)
        except AssessmentValidationError as exc:
            reason = (
                ReasonCode.ASSESSMENT_NOT_COMPLETED.value
                if "completed" in str(exc)
                else ReasonCode.ASSESSMENT_SCHEMA_INVALID.value
            )
            return _result(
                status=InterpretationStatus.ABSTAIN_INPUT_INVALID,
                reason_codes=(reason,),
                request=request,
                context=context,
            )
        assessment = request.assessment
        if assessment.get("status") != "completed":
            return _result(
                status=InterpretationStatus.ABSTAIN_INPUT_INVALID,
                reason_codes=(ReasonCode.ASSESSMENT_NOT_COMPLETED.value,),
                request=request,
                context=context,
            )
        population = assessment.get("population_scope")
        if population != context.assessment_population:
            return _result(
                status=InterpretationStatus.ABSTAIN_POPULATION_MISMATCH,
                reason_codes=(ReasonCode.POPULATION_CONTEXT_MISMATCH.value,),
                request=request,
                context=context,
            )

        if request.policy_ref is None:  # guarded by InterpretationRequest.__post_init__
            return _result(
                status=InterpretationStatus.ABSTAIN_POLICY_MISSING,
                reason_codes=(ReasonCode.POLICY_REFERENCE_MISSING.value,),
                request=request,
                context=context,
            )
        lookup = self._registry.lookup(request.policy_ref)
        if lookup.policy is None:
            status_by_reason = {
                "POLICY_NOT_FOUND": InterpretationStatus.ABSTAIN_POLICY_MISSING,
                "POLICY_DUPLICATE": InterpretationStatus.ABSTAIN_POLICY_MISMATCH,
                "POLICY_INVALID": InterpretationStatus.ABSTAIN_POLICY_MISMATCH,
                "POLICY_HASH_MISMATCH": InterpretationStatus.ABSTAIN_POLICY_HASH_MISMATCH,
            }
            reason_by_reason = {
                "POLICY_NOT_FOUND": ReasonCode.POLICY_NOT_FOUND.value,
                "POLICY_DUPLICATE": ReasonCode.POLICY_DUPLICATE.value,
                "POLICY_INVALID": ReasonCode.POLICY_INVALID.value,
                "POLICY_HASH_MISMATCH": ReasonCode.POLICY_HASH_MISMATCH.value,
            }
            key = lookup.reason
            return _result(
                status=status_by_reason.get(key, InterpretationStatus.ABSTAIN_POLICY_MISSING),
                reason_codes=(
                    reason_by_reason.get(key, ReasonCode.POLICY_REFERENCE_INVALID.value),
                ),
                request=request,
                context=context,
            )
        policy = lookup.policy
        instrument = assessment.get("instrument")
        instrument_id = instrument.get("instrument_id") if isinstance(instrument, Mapping) else None
        instrument_version = instrument.get("version") if isinstance(instrument, Mapping) else None
        if instrument_id != policy.instrument_id:
            return _result(
                status=InterpretationStatus.ABSTAIN_INSTRUMENT_MISMATCH,
                reason_codes=(ReasonCode.POLICY_INSTRUMENT_MISMATCH.value,),
                request=request,
                context=context,
                policy=policy,
            )
        if instrument_version != policy.instrument_version:
            return _result(
                status=InterpretationStatus.ABSTAIN_VERSION_MISMATCH,
                reason_codes=(ReasonCode.POLICY_VERSION_MISMATCH.value,),
                request=request,
                context=context,
                policy=policy,
            )
        if population != policy.population_scope:
            return _result(
                status=InterpretationStatus.ABSTAIN_POPULATION_MISMATCH,
                reason_codes=(ReasonCode.POLICY_POPULATION_MISMATCH.value,),
                request=request,
                context=context,
                policy=policy,
            )
        if context.execution_mode not in policy.allowed_modes:
            return _result(
                status=InterpretationStatus.ABSTAIN_MODE_NOT_ALLOWED,
                reason_codes=(ReasonCode.POLICY_MODE_NOT_ALLOWED.value,),
                request=request,
                context=context,
                policy=policy,
            )
        # D3I-39: every interpretation policy must carry an explicit,
        # well-formed synthetic-only marker while real data is prohibited.
        # Keep this runtime check even though JSON parsing validates the
        # shipped registry: a typed registry can be assembled by same-process
        # callers and must fail closed before any test-only claims are built.
        if policy.synthetic_only is not True or policy.policy_kind not in _VALID_POLICY_KINDS:
            return _result(
                status=InterpretationStatus.ABSTAIN_POLICY_MISMATCH,
                reason_codes=(ReasonCode.POLICY_INVALID.value,),
                request=request,
                context=context,
                policy=policy,
            )
        constructs = assessment.get("dimensions")
        if not isinstance(constructs, Mapping):  # guarded by schema validation, kept explicit
            return _result(
                status=InterpretationStatus.ABSTAIN_INPUT_INVALID,
                reason_codes=(ReasonCode.ASSESSMENT_SCHEMA_INVALID.value,),
                request=request,
                context=context,
                policy=policy,
            )
        if any(is_forbidden_claim_code(code) for code in policy.allowed_claims) or any(
            is_forbidden_claim_code(code)
            for construct_policy in policy.construct_policies.values()
            for code in construct_policy.allowed_claim_codes
        ):
            return _result(
                status=InterpretationStatus.ABSTAIN_POLICY_MISMATCH,
                reason_codes=(ReasonCode.POLICY_INVALID.value,),
                request=request,
                context=context,
                policy=policy,
            )
        selected_constructs = []
        for dimension_id in constructs:
            construct = policy.construct_policies.get(dimension_id)
            if construct is None or construct.status not in {"MEASUREMENT_ONLY", "TEST_ONLY"}:
                return _result(
                    status=InterpretationStatus.ABSTAIN_CONSTRUCT_UNAPPROVED,
                    reason_codes=(ReasonCode.CONSTRUCT_UNAPPROVED.value,),
                    request=request,
                    context=context,
                    policy=policy,
                    limitations=policy.limitations,
                )
            if any(code not in policy.allowed_claims for code in construct.allowed_claim_codes):
                return _result(
                    status=InterpretationStatus.ABSTAIN_POLICY_MISMATCH,
                    reason_codes=(ReasonCode.POLICY_INVALID.value,),
                    request=request,
                    context=context,
                    policy=policy,
                )
            selected_constructs.append(construct)

        if policy.policy_kind == "SYNTHETIC_TEST_ONLY":
            claims = tuple(
                Claim(code, construct.construct_id, True)
                for construct in selected_constructs
                for code in construct.allowed_claim_codes
            )
            return _result(
                status=InterpretationStatus.READY_FOR_RENDERING,
                reason_codes=(ReasonCode.SYNTHETIC_TEST_ONLY_POLICY.value,),
                request=request,
                context=context,
                policy=policy,
                limitations=policy.limitations,
                claims=claims,
            )
        # Every shipped production-facing interpretation is intentionally
        # measurement-only until a separate review creates a validated pack.
        return _result(
            status=InterpretationStatus.MEASUREMENT_ONLY,
            reason_codes=(ReasonCode.POLICY_CONSERVATIVE_MEASUREMENT_ONLY.value,),
            request=request,
            context=context,
            policy=policy,
            limitations=policy.limitations,
        )


@cache
def load_shipped_registry() -> PolicyRegistry:
    """Load the one committed conservative policy asset by its exact path."""

    return load_policy_registry(DEFAULT_POLICY_PATH)


def interpret(
    request: InterpretationRequest | Mapping[str, Any],
    trusted_context: object,
    registry: PolicyRegistry | None = None,
) -> InterpretationResult:
    """Interpret one request with typed trusted context and exact policy lookup."""

    try:
        request_value = _request_from_input(request)
    except (TypeError, ValueError) as exc:
        if "policy" in str(exc).lower():
            return _invalid_request_result(
                request,
                reason=ReasonCode.POLICY_REFERENCE_MISSING.value,
                status=InterpretationStatus.ABSTAIN_POLICY_MISSING,
            )
        return _invalid_request_result(request)
    selected_registry = registry if registry is not None else load_shipped_registry()
    return InterpretationAdapter(selected_registry).interpret(request_value, trusted_context)


def interpret_assessment(
    assessment: Mapping[str, Any],
    policy_ref: PolicyReference | Mapping[str, Any],
    trusted_context: object,
    registry: PolicyRegistry | None = None,
    *,
    request_id: str = "REQ_assessment_adapter",
    trace_id: str = "TRACE_assessment_adapter",
) -> InterpretationResult:
    """Convenience wrapper that still requires the typed trusted context."""

    try:
        reference = (
            policy_ref
            if isinstance(policy_ref, PolicyReference)
            else PolicyReference.from_mapping(policy_ref)
        )
        request = InterpretationRequest(
            assessment=assessment,
            policy_ref=reference,
            request_id=request_id,
            trace_id=trace_id,
        )
    except (TypeError, ValueError):
        return _invalid_request_result(
            {"assessment": assessment},
            reason=ReasonCode.POLICY_REFERENCE_MISSING.value,
            status=InterpretationStatus.ABSTAIN_POLICY_MISSING,
        )
    return interpret(request, trusted_context, registry)


__all__ = [
    "DEFAULT_POLICY_PATH",
    "InterpretationAdapter",
    "interpret",
    "interpret_assessment",
    "load_shipped_registry",
    "validate_assessment_v1",
]
