"""Deterministic D3-3 role projection and minimum-disclosure engine.

The module is deliberately independent of D3-1 and D3-2 implementations.  It
accepts the serializable ``interpretation_result.v1`` shape (or an equivalent
typed value exposing ``to_dict``) and consumes the D3-3 typed policy/context
boundary.  No measurement interpretation, natural-language generation,
network call, RAG lookup, or Safety decision is performed here.
"""

from __future__ import annotations

import copy
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any, NoReturn, cast

from .role_projection_models import (
    AudienceRole,
    AuditProjection,
    DisclosureAuthorization,
    PolicyReference,
    PolicySelectionError,
    ProjectionMode,
    ProjectionReasonCode,
    ProjectionStatus,
    PromptCitation,
    PromptClaim,
    PromptFacingProjection,
    PurposeOfUse,
    RoleProjectionError,
    RoleProjectionPolicy,
    RoleProjectionPolicyRegistry,
    RoleProjectionResult,
    SafetyAction,
    SourceStatus,
    TrustedAudienceContext,
    TrustedRelation,
    _build_prompt_facing_projection,
    _is_forbidden_projection_code,
    canonical_policy_hash,
    load_role_projection_policy_registry,
    validate_claim_monotonicity,
)

_SOURCE_SCHEMA_VERSION = "interpretation_result.v1"
_SOURCE_POLICY_KEYS = frozenset(
    {
        "policy_id",
        "policy_version",
        "effective_version",
        "policy_hash",
        "policy_kind",
        "psychology_review_status",
        "review_decision_id",
    }
)
_SOURCE_AUDIT_KEYS = frozenset(
    {
        "request_id",
        "trace_id",
        "context_id",
        "context_version",
        "execution_mode",
        "safety_action",
    }
)
_SOURCE_KEYS = frozenset(
    {
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
    }
)
_INSTRUMENT_KEYS = frozenset({"instrument_id", "version"})
_CLAIM_KEYS = frozenset({"claim_code", "construct_id", "value"})
_CITATION_KEYS = frozenset({"source_chunk_id", "locator"})
_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_.-]+$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_ASSESSMENT_ID_RE = re.compile(r"^ASSESS_[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SUBJECT_ID_RE = re.compile(r"^SUBJ_[A-Za-z0-9][A-Za-z0-9_.-]*$")
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

# This is the identity of the currently shipped conservative D3-2 source pack.
# Keeping the identity at this boundary prevents a caller from replacing the
# source policy while still presenting a normal ``MEASUREMENT_ONLY`` result.
_SHIPPED_SOURCE_POLICY = {
    "policy_id": "POLICY_assessment_synthetic_measurement_only",
    "policy_version": "1.0.0",
    "effective_version": "1.0.0",
    "policy_hash": "sha256:7c61cf80dc68561c78618c2d6e3859295b0dc53a291a1805c9bb623c5b7714a4",
    "policy_kind": "SHIPPED_CONSERVATIVE",
    "psychology_review_status": "REVISIONS_REQUIRED",
    "review_decision_id": "D1_RECONCILIATION_2026-09-14",
}
_SHIPPED_INSTRUMENT = "CURRENT_SYNTHETIC_GRM"
_SHIPPED_INSTRUMENT_VERSION = "synthetic_item_bank.v1 / demo.v1"
_SHIPPED_POPULATION = "SYNTHETIC_STUDENT_DEMO"
_SHIPPED_LIMITATIONS = (
    "SYNTHETIC_ONLY",
    "NOT_DIAGNOSTIC",
    "NO_VALIDATED_CUTOFF",
    "NO_CLINICAL_INFERENCE",
    "NO_CRISIS_INFERENCE",
)
_NORMAL_SOURCE_REASONS = frozenset({"POLICY_CONSERVATIVE_MEASUREMENT_ONLY"})
_BYPASS_ACTIONS = frozenset(
    {SafetyAction.CRISIS_ROUTE, SafetyAction.REVIEW_REQUIRED, SafetyAction.BLOCK}
)
class SourceResultError(RoleProjectionError):
    """The upstream result is malformed, tampered, or not source-authoritative."""


class PromptProjectionTypeError(TypeError):
    """An audit/combined result was supplied where the prompt surface is required."""


def _fail(reason: str) -> NoReturn:
    raise SourceResultError(reason)


def _is_code(value: object) -> bool:
    return isinstance(value, str) and _CODE_RE.fullmatch(value) is not None


def _is_forbidden_source_code(value: str) -> bool:
    """Share the model-layer semantic deny-list at the source boundary.

    The model validator is the canonical vocabulary check for claim-like
    projection codes.  ``SE`` is also rejected explicitly here because D3-3
    must not allow the exact standard-error abbreviation into the source
    audit, even if a future model validator changes its normalization rules.
    """

    return value.upper() == "SE" or _is_forbidden_projection_code(value)


def _codes(
    value: object,
    name: str,
    *,
    allow_empty: bool = False,
    forbid_content: bool = True,
) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        _fail(f"{name.upper()}_INVALID")
    items = tuple(cast(Sequence[object], value))
    if not allow_empty and not items:
        _fail(f"{name.upper()}_EMPTY")
    if any(not _is_code(item) for item in items):
        _fail(f"{name.upper()}_INVALID")
    string_items = cast(tuple[str, ...], items)
    if len(set(string_items)) != len(string_items):
        _fail(f"{name.upper()}_INVALID")
    if forbid_content and any(_is_forbidden_source_code(item) for item in string_items):
        _fail(f"{name.upper()}_FORBIDDEN")
    return string_items


def _safe_identifier(value: object, name: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        _fail(f"{name.upper()}_INVALID")
    return value


def _enum(value: object, enum_type: type[Any], name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        _fail(f"{name.upper()}_INVALID")
    try:
        return enum_type(value)
    except ValueError:
        _fail(f"{name.upper()}_INVALID")


def _copy_mapping(value: object, reason: str) -> dict[str, Any]:
    """Materialize a mapping or D3-2 typed-equivalent without importing it."""

    candidate: object = value
    if not isinstance(candidate, Mapping):
        to_dict = getattr(candidate, "to_dict", None)
        if callable(to_dict):
            try:
                candidate = to_dict()
            except Exception as exc:  # pragma: no cover - hostile object boundary
                raise SourceResultError(reason) from exc
        elif hasattr(candidate, "__iter__") and hasattr(candidate, "__getitem__"):
            try:
                candidate_any = cast(Any, candidate)
                keys = tuple(iter(candidate_any))
                candidate = {key: candidate_any[key] for key in keys}
            except Exception as exc:  # pragma: no cover - hostile object boundary
                raise SourceResultError(reason) from exc
    if not isinstance(candidate, Mapping):
        raise SourceResultError(reason)
    try:
        copied = copy.deepcopy(dict(candidate))
    except Exception as exc:  # pragma: no cover - hostile object boundary
        raise SourceResultError(reason) from exc
    return copied


def _validate_source_policy(policy: object, status: SourceStatus) -> dict[str, str | None]:
    if not isinstance(policy, Mapping) or set(policy) != _SOURCE_POLICY_KEYS:
        _fail("SOURCE_POLICY_SHAPE_INVALID")
    result: dict[str, str | None] = {}
    for key in _SOURCE_POLICY_KEYS:
        value = policy.get(key)
        if value is not None and not isinstance(value, str):
            _fail("SOURCE_POLICY_IDENTITY_INVALID")
        result[key] = cast(str | None, value)
    non_null = [value for value in result.values() if value is not None]
    if not non_null:
        # D3-2 uses an empty policy identity for its safety/invalid-input
        # results.  Such results can only remain an upstream abstention.
        return result
    if any(value is None for value in result.values()):
        _fail("SOURCE_POLICY_IDENTITY_INVALID")
    if not isinstance(result["policy_hash"], str) or _HASH_RE.fullmatch(
        result["policy_hash"]
    ) is None:
        _fail("SOURCE_POLICY_HASH_INVALID")
    if result != _SHIPPED_SOURCE_POLICY:
        _fail("SOURCE_POLICY_IDENTITY_MISMATCH")
    return result


def _validate_source_audit(
    audit: object,
    context: TrustedAudienceContext,
    status: SourceStatus,
) -> None:
    if not isinstance(audit, Mapping) or set(audit) != _SOURCE_AUDIT_KEYS:
        _fail("SOURCE_AUDIT_SHAPE_INVALID")
    expected = {
        "request_id": context.request_id,
        "trace_id": context.trace_id,
        "context_id": context.context_id,
        "context_version": context.context_version,
        "execution_mode": context.execution_mode.value,
        "safety_action": context.safety_action.value,
    }
    for key, value in audit.items():
        if value is not None and not isinstance(value, str):
            _fail("SOURCE_AUDIT_INVALID")
        if value != expected[key]:
            _fail("SOURCE_AUDIT_IDENTITY_MISMATCH")
    if status is SourceStatus.BYPASS_SAFETY and context.safety_action not in _BYPASS_ACTIONS:
        _fail("SOURCE_SAFETY_STATUS_MISMATCH")
    if status is not SourceStatus.BYPASS_SAFETY and context.safety_action in _BYPASS_ACTIONS:
        _fail("SOURCE_SAFETY_STATUS_MISMATCH")


def _validate_source(
    source_result: object,
    context: TrustedAudienceContext,
) -> tuple[
    dict[str, Any],
    SourceStatus,
    tuple[str, ...],
    tuple[dict[str, Any], ...],
    tuple[str, ...],
]:
    source = _copy_mapping(source_result, "SOURCE_RESULT_INVALID")
    if set(source) != _SOURCE_KEYS or source.get("schema_version") != _SOURCE_SCHEMA_VERSION:
        _fail("SOURCE_SCHEMA_MISMATCH")
    status = _enum(source.get("status"), SourceStatus, "source_status")
    reason_codes = _codes(
        source.get("reason_codes"), "source_reason_codes", forbid_content=False
    )
    if status is SourceStatus.MEASUREMENT_ONLY and not set(reason_codes) == _NORMAL_SOURCE_REASONS:
        _fail("SOURCE_REASON_INVALID")
    if status is SourceStatus.BYPASS_SAFETY:
        if set(reason_codes) != {context.safety_action.value} or (
            context.safety_action not in _BYPASS_ACTIONS
        ):
            _fail("SOURCE_REASON_INVALID")

    assessment_id = _safe_identifier(source.get("assessment_id"), "assessment_id", nullable=True)
    subject_id = _safe_identifier(source.get("subject_id"), "subject_id", nullable=True)
    if status is SourceStatus.MEASUREMENT_ONLY:
        if assessment_id is None or _ASSESSMENT_ID_RE.fullmatch(assessment_id) is None:
            _fail("SOURCE_IDENTITY_INVALID")
        if subject_id is None or _SUBJECT_ID_RE.fullmatch(subject_id) is None:
            _fail("SOURCE_IDENTITY_INVALID")

    instrument = source.get("instrument")
    if not isinstance(instrument, Mapping) or set(instrument) != _INSTRUMENT_KEYS:
        _fail("SOURCE_INSTRUMENT_INVALID")
    for _key, value in instrument.items():
        if value is not None and (not isinstance(value, str) or not value.strip()):
            _fail("SOURCE_INSTRUMENT_INVALID")
    if status is SourceStatus.MEASUREMENT_ONLY and (
        instrument.get("instrument_id") != _SHIPPED_INSTRUMENT
        or instrument.get("version") != _SHIPPED_INSTRUMENT_VERSION
        or source.get("population_scope") != _SHIPPED_POPULATION
    ):
        _fail("SOURCE_IDENTITY_MISMATCH")

    population = source.get("population_scope")
    if population is not None and (not isinstance(population, str) or not population.strip()):
        _fail("SOURCE_POPULATION_INVALID")

    _validate_source_policy(source.get("policy"), status)
    _validate_source_audit(source.get("audit"), context, status)

    claims_value = source.get("claims")
    if not isinstance(claims_value, list):
        _fail("SOURCE_CLAIMS_INVALID")
    claims: list[dict[str, Any]] = []
    claim_codes: list[str] = []
    for claim in claims_value:
        if not isinstance(claim, Mapping) or set(claim) != _CLAIM_KEYS:
            _fail("SOURCE_CLAIM_SHAPE_INVALID")
        claim_code = claim.get("claim_code")
        construct_id = claim.get("construct_id")
        value = claim.get("value")
        if not _is_code(claim_code) or _is_forbidden_source_code(cast(str, claim_code)):
            _fail("SOURCE_CLAIM_CODE_INVALID")
        if (
            not isinstance(construct_id, str)
            or _IDENTIFIER_RE.fullmatch(construct_id) is None
            or _is_forbidden_source_code(construct_id)
        ):
            _fail("SOURCE_CLAIM_CONSTRUCT_INVALID")
        if not isinstance(value, (str, bool, int, float)):
            _fail("SOURCE_CLAIM_VALUE_INVALID")
        if isinstance(value, float) and not math.isfinite(value):
            _fail("SOURCE_CLAIM_VALUE_INVALID")
        if claim_code in claim_codes:
            _fail("SOURCE_CLAIMS_DUPLICATE")
        claim_codes.append(cast(str, claim_code))
        claims.append({"claim_code": claim_code, "construct_id": construct_id, "value": value})
    source_codes = tuple(claim_codes)
    trusted_codes = tuple(context.source_claim_codes)
    if set(source_codes) != set(trusted_codes) or len(source_codes) != len(trusted_codes):
        _fail("SOURCE_CLAIMS_TRUST_MISMATCH")

    limitations = _codes(
        source.get("limitations"),
        "source_limitations",
        allow_empty=True,
        forbid_content=False,
    )
    if status is SourceStatus.MEASUREMENT_ONLY and set(limitations) != set(_SHIPPED_LIMITATIONS):
        _fail("SOURCE_LIMITATIONS_MISMATCH")
    return source, status, source_codes, tuple(claims), limitations


def _validate_context(context: object) -> TrustedAudienceContext:
    if not isinstance(context, TrustedAudienceContext):
        raise RoleProjectionError("TRUSTED_CONTEXT_REQUIRED")
    for name, enum_type in (
        ("audience_role", AudienceRole),
        ("purpose_of_use", PurposeOfUse),
        ("subject_relation", TrustedRelation),
        ("execution_mode", ProjectionMode),
        ("disclosure_authorization", DisclosureAuthorization),
        ("source_status", SourceStatus),
        ("safety_action", SafetyAction),
    ):
        if not isinstance(getattr(context, name), enum_type):
            raise RoleProjectionError("TRUSTED_CONTEXT_REQUIRED")
    # Keep this identity list shape-checked here, then apply the semantic
    # source-code deny-list while validating the actual upstream claims.  This
    # gives malformed/forbidden source claims one atomic failure path before a
    # teacher/parent role can suppress them into an audit-only projection.
    _codes(
        context.source_claim_codes,
        "source_claim_codes",
        allow_empty=True,
        forbid_content=False,
    )
    return context


def _policy_ref(value: object) -> PolicyReference:
    if value is None:
        raise PolicySelectionError("POLICY_MISSING")
    if isinstance(value, PolicyReference):
        return value
    if isinstance(value, Mapping):
        try:
            return PolicyReference.from_mapping(value)
        except (RoleProjectionError, TypeError) as exc:
            raise PolicySelectionError("POLICY_REFERENCE_INVALID") from exc
    raise PolicySelectionError("POLICY_REFERENCE_INVALID")


def _reason(value: str) -> ProjectionReasonCode:
    try:
        return ProjectionReasonCode(value)
    except ValueError:
        return ProjectionReasonCode.POLICY_MISMATCH


def _audit(
    *,
    status: ProjectionStatus,
    reason: ProjectionReasonCode,
    context: TrustedAudienceContext,
    source_status: SourceStatus | None,
    policy: RoleProjectionPolicy | None,
    source_codes: tuple[str, ...] = (),
    emitted_codes: tuple[str, ...] = (),
    suppressed_codes: tuple[str, ...] = (),
    source_chunk_ids: tuple[str, ...] = (),
) -> AuditProjection:
    return AuditProjection(
        status=status,
        reason_codes=(reason,),
        request_id=context.request_id,
        trace_id=context.trace_id,
        context_id=context.context_id,
        context_version=context.context_version,
        audience_role=context.audience_role,
        purpose_of_use=context.purpose_of_use,
        relation=context.subject_relation,
        disclosure_authorization=context.disclosure_authorization,
        mode=context.execution_mode,
        source_status=source_status,
        safety_action=context.safety_action,
        policy_id=policy.policy_id if policy else None,
        policy_version=policy.policy_version if policy else None,
        policy_hash=policy.policy_hash if policy else None,
        effective_version=policy.effective_version if policy else None,
        review_status=policy.review_metadata.review_status if policy else None,
        review_decision_id=policy.review_metadata.review_decision_id if policy else None,
        source_approved_claim_codes=source_codes,
        emitted_claim_codes=emitted_codes,
        suppressed_claim_codes=suppressed_codes,
        source_chunk_ids=source_chunk_ids,
    )


def _result(
    *,
    status: ProjectionStatus,
    reason: ProjectionReasonCode,
    context: TrustedAudienceContext,
    source_status: SourceStatus | None,
    policy: RoleProjectionPolicy | None,
    source_codes: tuple[str, ...] = (),
    emitted_codes: tuple[str, ...] = (),
    suppressed_codes: tuple[str, ...] = (),
    limitations: tuple[str, ...] = (),
    citations: tuple[PromptCitation, ...] = (),
) -> RoleProjectionResult:
    prompt = _build_prompt_facing_projection(
        status=status,
        claims=(),
        limitations=limitations if status is ProjectionStatus.READY_FOR_PROMPT else (),
        citations=citations if status is ProjectionStatus.READY_FOR_PROMPT else (),
    )
    audit = _audit(
        status=status,
        reason=reason,
        context=context,
        source_status=source_status,
        policy=policy,
        source_codes=source_codes,
        emitted_codes=emitted_codes,
        suppressed_codes=suppressed_codes,
        source_chunk_ids=tuple(item.source_chunk_id for item in citations),
    )
    return RoleProjectionResult(status=status, prompt=prompt, audit=audit)


def _validate_citations(value: object) -> tuple[PromptCitation, ...]:
    if value is None or not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise RoleProjectionError("CITATIONS_INVALID")
    result: list[PromptCitation] = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, PromptCitation):
            citation = PromptCitation(item.source_chunk_id, item.locator)
        elif isinstance(item, Mapping):
            if set(item) != _CITATION_KEYS:
                raise RoleProjectionError("CITATION_SHAPE_INVALID")
            source_chunk_id = item.get("source_chunk_id")
            locator = item.get("locator")
            if not isinstance(source_chunk_id, str) or not _IDENTIFIER_RE.fullmatch(
                source_chunk_id
            ):
                raise RoleProjectionError("CITATION_ID_INVALID")
            if locator is not None and (
                not isinstance(locator, str) or not locator.strip() or len(locator) > 256
            ):
                raise RoleProjectionError("CITATION_LOCATOR_INVALID")
            citation = PromptCitation(source_chunk_id, locator)
        else:
            raise RoleProjectionError("CITATION_SHAPE_INVALID")
        if citation.source_chunk_id in seen:
            raise RoleProjectionError("CITATIONS_DUPLICATE")
        seen.add(citation.source_chunk_id)
        result.append(citation)
    return tuple(result)


def _validate_role_matrix(context: TrustedAudienceContext) -> ProjectionStatus | None:
    role = context.audience_role
    if role in {AudienceRole.SYSTEM_ADMIN, AudienceRole.UNKNOWN}:
        return ProjectionStatus.NO_PERSONALIZED_DISCLOSURE
    expected_purpose = {
        AudienceRole.STUDENT_SELF: PurposeOfUse.SELF_UNDERSTANDING,
        AudienceRole.TEACHER_SUPPORT: PurposeOfUse.EDUCATIONAL_SUPPORT,
        AudienceRole.PARENT_DEMO: PurposeOfUse.SYNTHETIC_PARENT_DEMO,
    }.get(role)
    expected_relation = {
        AudienceRole.STUDENT_SELF: TrustedRelation.SELF,
        AudienceRole.TEACHER_SUPPORT: TrustedRelation.ASSIGNED_SUPPORT,
        AudienceRole.PARENT_DEMO: TrustedRelation.SYNTHETIC_DEMO,
    }.get(role)
    if expected_purpose is None or expected_relation is None:
        return ProjectionStatus.ABSTAIN_ROLE_NOT_ALLOWED
    if context.purpose_of_use is not expected_purpose:
        return ProjectionStatus.ABSTAIN_PURPOSE_NOT_ALLOWED
    if context.subject_relation is not expected_relation:
        return ProjectionStatus.ABSTAIN_RELATIONSHIP_MISMATCH
    if context.execution_mode is not ProjectionMode.SYNTHETIC_DEMO:
        return ProjectionStatus.ABSTAIN_MODE_NOT_ALLOWED
    expected_auth = {
        AudienceRole.STUDENT_SELF: DisclosureAuthorization.SYNTHETIC_SELF,
        AudienceRole.TEACHER_SUPPORT: DisclosureAuthorization.SYNTHETIC_SUPPORT,
        AudienceRole.PARENT_DEMO: DisclosureAuthorization.SYNTHETIC_PARENT_DEMO,
    }[role]
    if context.disclosure_authorization is not expected_auth:
        return ProjectionStatus.ABSTAIN_DISCLOSURE_NOT_AUTHORIZED
    return None


def _policy_error_result(
    error: RoleProjectionError,
    context: TrustedAudienceContext,
    source_status: SourceStatus,
    source_codes: tuple[str, ...],
) -> RoleProjectionResult:
    mapping = {
        "POLICY_MISSING": ProjectionStatus.ABSTAIN_POLICY_MISSING,
        "POLICY_REFERENCE_INVALID": ProjectionStatus.ABSTAIN_POLICY_MISMATCH,
        "POLICY_HASH_MISMATCH": ProjectionStatus.ABSTAIN_POLICY_MISMATCH,
        "POLICY_TAMPERED": ProjectionStatus.ABSTAIN_POLICY_MISMATCH,
        "POLICY_MISMATCH": ProjectionStatus.ABSTAIN_POLICY_MISMATCH,
    }
    status = mapping.get(error.reason_code, ProjectionStatus.ABSTAIN_POLICY_MISMATCH)
    reason = (
        ProjectionReasonCode.POLICY_MISSING
        if status is ProjectionStatus.ABSTAIN_POLICY_MISSING
        else _reason(error.reason_code)
    )
    return _result(
        status=status,
        reason=reason,
        context=context,
        source_status=source_status,
        policy=None,
        source_codes=source_codes,
    )


def project(
    source_result: object,
    policy_reference: PolicyReference | Mapping[str, Any] | None,
    trusted_context: TrustedAudienceContext,
    citations: Sequence[PromptCitation | Mapping[str, Any]] = (),
    *,
    registry: RoleProjectionPolicyRegistry | None = None,
) -> RoleProjectionResult:
    """Project one D3-2 result through an exact D3-3 role policy.

    The public surface requires a typed ``TrustedAudienceContext``.  Source
    and citation inputs are copied before validation, and all public denial
    envelopes are intentionally the same four-field shape.  Invalid/tampered
    source and citation data raises a stable ``RoleProjectionError``; policy,
    role, mode, authorization, and upstream-status decisions return a typed
    empty projection with the canonical status.
    """

    context = _validate_context(trusted_context)
    source, source_status, source_codes, _source_claims, source_limitations = _validate_source(
        source_result, context
    )
    if context.source_status is not source_status:
        raise SourceResultError("SOURCE_STATUS_TRUST_MISMATCH")
    parsed_citations = _validate_citations(citations)

    matrix_status = _validate_role_matrix(context)
    if matrix_status is ProjectionStatus.NO_PERSONALIZED_DISCLOSURE:
        return _result(
            status=matrix_status,
            reason=ProjectionReasonCode.ROLE_NOT_ALLOWED,
            context=context,
            source_status=source_status,
            policy=None,
            source_codes=source_codes,
            suppressed_codes=source_codes,
        )
    if matrix_status is not None:
        reason_by_status = {
            ProjectionStatus.ABSTAIN_ROLE_NOT_ALLOWED: ProjectionReasonCode.ROLE_NOT_ALLOWED,
            ProjectionStatus.ABSTAIN_PURPOSE_NOT_ALLOWED: ProjectionReasonCode.PURPOSE_NOT_ALLOWED,
            ProjectionStatus.ABSTAIN_RELATIONSHIP_MISMATCH: (
                ProjectionReasonCode.RELATIONSHIP_MISMATCH
            ),
            ProjectionStatus.ABSTAIN_MODE_NOT_ALLOWED: ProjectionReasonCode.MODE_NOT_ALLOWED,
            ProjectionStatus.ABSTAIN_DISCLOSURE_NOT_AUTHORIZED: (
                ProjectionReasonCode.DISCLOSURE_NOT_AUTHORIZED
            ),
        }
        return _result(
            status=matrix_status,
            reason=reason_by_status[matrix_status],
            context=context,
            source_status=source_status,
            policy=None,
            source_codes=source_codes,
            suppressed_codes=source_codes,
        )

    try:
        reference = _policy_ref(policy_reference)
    except PolicySelectionError as exc:
        return _policy_error_result(exc, context, source_status, source_codes)
    selected_registry = registry if registry is not None else load_role_projection_policy_registry()
    if not isinstance(selected_registry, RoleProjectionPolicyRegistry):
        raise RoleProjectionError("REGISTRY_INVALID")

    try:
        # Identity is always exact.  BYPASS_SAFETY is handled before the
        # normal source-status binding because D3-3 must preserve the stop.
        policy = selected_registry.resolve_exact(
            reference,
            audience_role=context.audience_role,
            purpose_of_use=context.purpose_of_use,
            required_relation=context.subject_relation,
            mode=context.execution_mode,
            source_status=source_status
            if source_status is SourceStatus.MEASUREMENT_ONLY
            else None,
        )
        policy.assert_integrity()
        expected_hash = canonical_policy_hash(policy)
        if expected_hash != policy.policy_hash:
            raise RoleProjectionError("POLICY_TAMPERED")
    except (PolicySelectionError, RoleProjectionError) as exc:
        return _policy_error_result(exc, context, source_status, source_codes)

    if source_status is SourceStatus.BYPASS_SAFETY:
        return _result(
            status=ProjectionStatus.BYPASS_SAFETY,
            reason=ProjectionReasonCode.SAFETY_BYPASS,
            context=context,
            source_status=source_status,
            policy=policy,
            source_codes=source_codes,
            suppressed_codes=source_codes,
        )
    if source_status is not SourceStatus.MEASUREMENT_ONLY:
        return _result(
            status=ProjectionStatus.ABSTAIN_SOURCE_STATUS,
            reason=ProjectionReasonCode.SOURCE_STATUS_NOT_ALLOWED,
            context=context,
            source_status=source_status,
            policy=policy,
            source_codes=source_codes,
            suppressed_codes=source_codes,
        )
    if source.get("policy") != _SHIPPED_SOURCE_POLICY:
        raise SourceResultError("SOURCE_POLICY_IDENTITY_MISMATCH")
    if set(source_limitations) != set(_SHIPPED_LIMITATIONS):
        raise SourceResultError("SOURCE_LIMITATIONS_MISMATCH")

    if context.audience_role is AudienceRole.TEACHER_SUPPORT:
        emitted_codes = validate_claim_monotonicity((), source_codes, policy)
        return _result(
            status=ProjectionStatus.NO_PERSONALIZED_DISCLOSURE,
            reason=ProjectionReasonCode.NO_PERSONALIZED_DISCLOSURE,
            context=context,
            source_status=source_status,
            policy=policy,
            source_codes=source_codes,
            emitted_codes=emitted_codes,
            suppressed_codes=source_codes,
        )

    if context.audience_role is AudienceRole.PARENT_DEMO:
        # Parent synthetic-demo claims are not currently authorized by the
        # shipped policy.  Suppress the complete source claim set and expose
        # the same coarse envelope as the no-claim Parent path; the audit
        # retains only typed codes and provenance.
        emitted_codes = validate_claim_monotonicity((), source_codes, policy)
        return _result(
            status=ProjectionStatus.NO_PERSONALIZED_DISCLOSURE,
            reason=ProjectionReasonCode.NO_PERSONALIZED_DISCLOSURE,
            context=context,
            source_status=source_status,
            policy=policy,
            source_codes=source_codes,
            emitted_codes=emitted_codes,
            suppressed_codes=source_codes,
        )

    # Current D3-2 shipped output is a measurement-only result with no
    # approved claims.  Any non-empty source claim set is therefore an
    # injected or stale source contract and must fail atomically.  This keeps
    # the empty source set from ever becoming a claim through policy metadata.
    if source_codes:
        raise SourceResultError("SOURCE_CLAIMS_NOT_SUBSET")
    emitted_codes = validate_claim_monotonicity((), source_codes, policy)
    public_emitted_claims: tuple[PromptClaim, ...] = ()
    public_emitted_codes = emitted_codes if "claims" in policy.public_field_allowlist else ()
    suppressed_codes = tuple(code for code in source_codes if code not in set(public_emitted_codes))

    # Use Worker D's private construction seam so callers cannot manufacture a
    # prompt-facing surface outside this policy-controlled engine path.
    prompt = _build_prompt_facing_projection(
        status=ProjectionStatus.READY_FOR_PROMPT,
        claims=public_emitted_claims,
        limitations=tuple(
            code
            for code in source_limitations
            if code in policy.allowed_limitation_codes
            and "limitations" in policy.public_field_allowlist
        ),
        citations=(
            parsed_citations
            if "citations" in policy.public_field_allowlist
            else ()
        ),
    )
    audit = _audit(
        status=ProjectionStatus.READY_FOR_PROMPT,
        reason=ProjectionReasonCode.READY_FOR_PROMPT,
        context=context,
        source_status=source_status,
        policy=policy,
        source_codes=source_codes,
        emitted_codes=public_emitted_codes,
        suppressed_codes=suppressed_codes,
        source_chunk_ids=tuple(item.source_chunk_id for item in parsed_citations),
    )
    return RoleProjectionResult(
        status=ProjectionStatus.READY_FOR_PROMPT,
        prompt=prompt,
        audit=audit,
    )


def prompt_input(value: object) -> dict[str, Any]:
    """Return a prompt-facing envelope and reject audit/combined surfaces."""

    if not isinstance(value, PromptFacingProjection):
        raise PromptProjectionTypeError("PROMPT_FACING_PROJECTION_REQUIRED")
    return copy.deepcopy(value.to_public_dict())


as_prompt_input = prompt_input
project_role_projection = project


__all__ = [
    "PromptProjectionTypeError",
    "SourceResultError",
    "as_prompt_input",
    "project",
    "project_role_projection",
    "prompt_input",
]
