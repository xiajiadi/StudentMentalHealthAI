"""Deterministic D3-3 contract, registry, hash, and schema checks.

These tests intentionally do not exercise engine behavior.  They prove that
the typed boundary is conservative and that the shipped synthetic-only policy
pack cannot be selected through a fallback or silently tampered with.
"""

from __future__ import annotations

import copy
import json
from dataclasses import fields
from pathlib import Path

import jsonschema
import pytest

from prompt_engine.role_projection import prompt_input
from prompt_engine.role_projection_models import (
    ALLOWED_AUDIENCE_ROLES,
    CANONICAL_PROJECTION_STATUSES,
    AudienceRole,
    AuditProjection,
    DisclosureAuthorization,
    DisclosureRequirement,
    PolicyIntegrityError,
    PolicyReference,
    PolicySelectionError,
    ProjectionMode,
    ProjectionReasonCode,
    ProjectionStatus,
    PromptClaim,
    PromptFacingProjection,
    PurposeOfUse,
    RoleProjectionError,
    RoleProjectionPolicy,
    RoleProjectionPolicyRegistry,
    RoleProjectionResult,
    SafetyAction,
    SourceStatus,
    TrustedRelation,
    _build_prompt_facing_projection,
    _build_trusted_audience_context,
    canonical_policy_hash,
    load_role_projection_policy_registry,
    validate_claim_monotonicity,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "assets" / "role_projection_policy_registry.v1.json"
SCHEMA_PATH = ROOT / "schemas" / "role_projection_result.v1.schema.json"


def _reference(policy) -> PolicyReference:
    return PolicyReference(policy.policy_id, policy.policy_version, policy.policy_hash)


def _audit(*, status: ProjectionStatus, reason: ProjectionReasonCode, policy=None):
    return AuditProjection(
        status=status,
        reason_codes=(reason,),
        request_id="REQ_d3r_001",
        trace_id="TRACE_d3r_001",
        context_id="CTX_d3r_001",
        context_version="1.0.0",
        audience_role=policy.audience_role if policy else None,
        purpose_of_use=policy.purpose_of_use if policy else None,
        relation=policy.required_relation if policy else None,
        disclosure_authorization=(
            DisclosureAuthorization.SYNTHETIC_SELF
            if policy and policy.audience_role is AudienceRole.STUDENT_SELF
            else DisclosureAuthorization.SYNTHETIC_SUPPORT
            if policy and policy.audience_role is AudienceRole.TEACHER_SUPPORT
            else DisclosureAuthorization.SYNTHETIC_PARENT_DEMO
            if policy
            else None
        ),
        mode=ProjectionMode.SYNTHETIC_DEMO if policy else None,
        source_status=SourceStatus.MEASUREMENT_ONLY if policy else None,
        safety_action=SafetyAction.PROCEED,
        policy_id=policy.policy_id if policy else None,
        policy_version=policy.policy_version if policy else None,
        policy_hash=policy.policy_hash if policy else None,
        effective_version=policy.effective_version if policy else None,
        review_status=policy.review_metadata.review_status if policy else None,
        review_decision_id=policy.review_metadata.review_decision_id if policy else None,
        source_approved_claim_codes=(),
        emitted_claim_codes=(),
        suppressed_claim_codes=(),
        source_chunk_ids=(),
    )


def _ready_result_payload() -> dict:
    registry = load_role_projection_policy_registry(REGISTRY_PATH)
    student = next(
        item for item in registry.policies if item.audience_role is AudienceRole.STUDENT_SELF
    )
    return RoleProjectionResult(
        status=ProjectionStatus.READY_FOR_PROMPT,
        prompt=_build_prompt_facing_projection(
            status=ProjectionStatus.READY_FOR_PROMPT,
            claims=(PromptClaim(claim_code="SYNTHETIC_TEST_ONLY", value=True),),
            limitations=("SYNTHETIC_ONLY", "NOT_DIAGNOSTIC"),
        ),
        audit=_audit(
            status=ProjectionStatus.READY_FOR_PROMPT,
            reason=ProjectionReasonCode.READY_FOR_PROMPT,
            policy=student,
        ),
    ).to_dict()


def test_canonical_status_vocabulary_and_schema_enum_align():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert tuple(ProjectionStatus) == tuple(
        ProjectionStatus(value) for value in CANONICAL_PROJECTION_STATUSES
    )
    assert schema["properties"]["status"]["$ref"] == "#/$defs/projectionStatus"
    assert tuple(schema["$defs"]["projectionStatus"]["enum"]) == CANONICAL_PROJECTION_STATUSES
    assert len(CANONICAL_PROJECTION_STATUSES) == 11


def test_role_purpose_relation_and_mode_enums_are_closed():
    assert {item.value for item in AudienceRole} == {
        "STUDENT_SELF",
        "TEACHER_SUPPORT",
        "PARENT_DEMO",
        "SYSTEM_ADMIN",
        "UNKNOWN",
    }
    assert {item.value for item in PurposeOfUse} == {
        "SELF_UNDERSTANDING",
        "EDUCATIONAL_SUPPORT",
        "SYNTHETIC_PARENT_DEMO",
    }
    assert {item.value for item in TrustedRelation} == {
        "SELF",
        "ASSIGNED_SUPPORT",
        "SYNTHETIC_DEMO",
    }
    assert {item.value for item in ProjectionMode} == {"SYNTHETIC_DEMO", "REAL_USER"}
    assert AudienceRole.SYSTEM_ADMIN not in ALLOWED_AUDIENCE_ROLES
    assert AudienceRole.UNKNOWN not in ALLOWED_AUDIENCE_ROLES
    assert "COUNSELOR" not in {item.value for item in AudienceRole}
    assert "CLINICIAN" not in {item.value for item in AudienceRole}


def test_trusted_context_cannot_be_self_asserted():
    with pytest.raises(TypeError):
        from prompt_engine.role_projection_models import TrustedAudienceContext

        TrustedAudienceContext(
            audience_role=AudienceRole.STUDENT_SELF,
            purpose_of_use=PurposeOfUse.SELF_UNDERSTANDING,
            subject_relation=TrustedRelation.SELF,
            execution_mode=ProjectionMode.SYNTHETIC_DEMO,
            disclosure_authorization=DisclosureAuthorization.SYNTHETIC_SELF,
            source_status=SourceStatus.MEASUREMENT_ONLY,
            source_claim_codes=(),
            safety_action=SafetyAction.PROCEED,
            request_id="REQ_d3r_001",
            trace_id="TRACE_d3r_001",
            context_id="CTX_d3r_001",
            context_version="1.0.0",
        )
    context = _build_trusted_audience_context(
        {
            "audience_role": "STUDENT_SELF",
            "purpose_of_use": "SELF_UNDERSTANDING",
            "subject_relation": "SELF",
            "execution_mode": "SYNTHETIC_DEMO",
            "disclosure_authorization": "SYNTHETIC_SELF",
            "source_status": "MEASUREMENT_ONLY",
            "source_claim_codes": [],
            "safety_action": "PROCEED",
            "request_id": "REQ_d3r_001",
            "trace_id": "TRACE_d3r_001",
            "context_id": "CTX_d3r_001",
            "context_version": "1.0.0",
        }
    )
    assert context.relation is TrustedRelation.SELF
    assert context.mode is ProjectionMode.SYNTHETIC_DEMO


def test_registry_has_three_exact_synthetic_policies_and_d3_2_status():
    registry = load_role_projection_policy_registry(REGISTRY_PATH)
    assert len(registry.policies) == 3
    assert all(policy.synthetic_only for policy in registry.policies)
    assert all(
        policy.allowed_modes == (ProjectionMode.SYNTHETIC_DEMO,)
        for policy in registry.policies
    )
    assert all(
        policy.allowed_source_statuses == (SourceStatus.MEASUREMENT_ONLY,)
        for policy in registry.policies
    )
    assert all(policy.allowed_claim_codes == () for policy in registry.policies)
    assert {
        (policy.audience_role, policy.purpose_of_use, policy.required_relation)
        for policy in registry.policies
    } == {
        (AudienceRole.STUDENT_SELF, PurposeOfUse.SELF_UNDERSTANDING, TrustedRelation.SELF),
        (
            AudienceRole.TEACHER_SUPPORT,
            PurposeOfUse.EDUCATIONAL_SUPPORT,
            TrustedRelation.ASSIGNED_SUPPORT,
        ),
        (
            AudienceRole.PARENT_DEMO,
            PurposeOfUse.SYNTHETIC_PARENT_DEMO,
            TrustedRelation.SYNTHETIC_DEMO,
        ),
    }


def test_policy_hashes_are_canonical_and_exactly_selectable():
    registry = load_role_projection_policy_registry(REGISTRY_PATH)
    for policy in registry.policies:
        assert canonical_policy_hash(policy) == policy.policy_hash
        assert registry.resolve(_reference(policy)) is policy
    with pytest.raises(PolicySelectionError):
        registry.resolve("latest", "1.0.0", registry.policies[0].policy_hash)
    with pytest.raises(PolicySelectionError):
        registry.resolve(
            {
                "policy_id": registry.policies[0].policy_id,
                "policy_version": "default",
                "policy_hash": registry.policies[0].policy_hash,
            }
        )
    with pytest.raises(PolicySelectionError):
        registry.resolve(
            {
                "policy_id": registry.policies[0].policy_id,
                "policy_version": registry.policies[0].policy_version,
            }
        )


def test_hash_mismatch_and_direct_typed_tamper_fail_closed():
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    tampered_payload = copy.deepcopy(payload)
    tampered_payload["policies"][0]["allowed_limitation_codes"].append("INVENTED_CODE")
    with pytest.raises(PolicyIntegrityError):
        RoleProjectionPolicyRegistry.from_mapping(tampered_payload)

    registry = load_role_projection_policy_registry(REGISTRY_PATH)
    policy = registry.policies[0]
    object.__setattr__(policy, "allowed_claim_codes", ("SYNTHETIC_TEST_ONLY",))
    with pytest.raises(PolicyIntegrityError):
        policy.assert_integrity()
    with pytest.raises(PolicyIntegrityError):
        registry.resolve(_reference(policy))


def test_teacher_zero_claim_policy_and_parent_synthetic_only_policy():
    registry = load_role_projection_policy_registry(REGISTRY_PATH)
    teacher = next(
        item for item in registry.policies if item.audience_role is AudienceRole.TEACHER_SUPPORT
    )
    parent = next(
        item for item in registry.policies if item.audience_role is AudienceRole.PARENT_DEMO
    )
    assert teacher.allowed_claim_codes == ()
    assert teacher.disclosure_requirement is DisclosureRequirement.NO_PERSONALIZED_DISCLOSURE
    assert parent.synthetic_only is True
    assert parent.required_relation is TrustedRelation.SYNTHETIC_DEMO
    assert parent.disclosure_requirement is DisclosureRequirement.SYNTHETIC_DEMO_ONLY
    assert ProjectionMode.REAL_USER not in parent.allowed_modes


@pytest.mark.parametrize(
    "claim_code",
    (
        "SEVERITY",
        "PRECISION",
        "STANDARD_ERROR",
        "LATENT",
        "LEVEL",
        "LEVEL_1_TO_5",
        "CONFIDENCE_INTERVAL",
    ),
)
def test_policy_allowed_claim_codes_reject_extended_forbidden_vocabulary(claim_code):
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))["policies"][0]
    payload["allowed_claim_codes"] = [claim_code]
    with pytest.raises(RoleProjectionError):
        RoleProjectionPolicy.from_mapping(payload)


def test_monotonic_claim_helper_rejects_invention_and_accepts_empty_d3_2_claims():
    registry = load_role_projection_policy_registry(REGISTRY_PATH)
    policy = registry.policies[0]
    assert validate_claim_monotonicity((), (), policy) == ()
    with pytest.raises(RoleProjectionError):
        validate_claim_monotonicity(("INVENTED_CLAIM",), (), policy)


@pytest.mark.parametrize(
    "claim_code",
    (
        "DIAGNOSIS",
        "THETA",
        "SCORE",
        "CLINICAL_SEVERITY",
        "RAW_RESPONSE",
        "SEVERITY",
        "PRECISION",
        "STANDARD_ERROR",
        "LATENT",
        "LEVEL",
        "LEVEL_1_TO_5",
        "CONFIDENCE_INTERVAL",
    ),
)
def test_prompt_claim_rejects_forbidden_measurement_and_clinical_codes(claim_code):
    with pytest.raises(RoleProjectionError):
        PromptClaim(claim_code=claim_code, value=True)
    with pytest.raises(RoleProjectionError):
        PromptClaim(claim_code="SYNTHETIC_TEST_ONLY", value=float("nan"))
    with pytest.raises(RoleProjectionError):
        PromptClaim(claim_code="SYNTHETIC_TEST_ONLY", value=float("inf"))


@pytest.mark.parametrize(
    "limitation",
    (
        "DIAGNOSIS",
        "THETA",
        "SCORE",
        "CLINICAL_SEVERITY",
        "RAW_RESPONSE",
        "SEVERITY",
        "PRECISION",
        "STANDARD_ERROR",
        "LATENT",
        "LEVEL",
        "LEVEL_1_TO_5",
        "CONFIDENCE_INTERVAL",
    ),
)
def test_prompt_projection_rejects_forbidden_limitations_and_keeps_safe_negative_codes(
    limitation,
):
    with pytest.raises(RoleProjectionError):
        _build_prompt_facing_projection(
            status=ProjectionStatus.READY_FOR_PROMPT,
            limitations=(limitation,),
        )
    prompt = _build_prompt_facing_projection(
        status=ProjectionStatus.READY_FOR_PROMPT,
        limitations=("SYNTHETIC_ONLY", "NOT_DIAGNOSTIC"),
    )
    assert prompt_input(prompt)["limitations"] == ["SYNTHETIC_ONLY", "NOT_DIAGNOSTIC"]


def test_prompt_projection_requires_private_construction_capability():
    claim = PromptClaim(claim_code="SYNTHETIC_TEST_ONLY", value=True)
    with pytest.raises(TypeError):
        PromptFacingProjection(status=ProjectionStatus.READY_FOR_PROMPT)
    with pytest.raises(TypeError):
        PromptFacingProjection(status=ProjectionStatus.READY_FOR_PROMPT, claims=(claim,))

    prompt = _build_prompt_facing_projection(
        status=ProjectionStatus.READY_FOR_PROMPT,
        claims=(claim,),
    )
    assert prompt_input(prompt)["claims"] == [
        {"claim_code": "SYNTHETIC_TEST_ONLY", "value": True}
    ]


def test_prompt_input_rejects_untrusted_projection_before_serialization():
    forged = object.__new__(PromptFacingProjection)
    object.__setattr__(forged, "status", ProjectionStatus.READY_FOR_PROMPT)
    object.__setattr__(
        forged,
        "claims",
        (PromptClaim(claim_code="SYNTHETIC_TEST_ONLY", value=True),),
    )
    object.__setattr__(forged, "limitations", ())
    object.__setattr__(forged, "citations", ())
    object.__setattr__(forged, "_capability", None)
    with pytest.raises(TypeError):
        prompt_input(forged)


def test_prompt_and_audit_surfaces_are_different_and_denial_has_no_side_channel():
    prompt = _build_prompt_facing_projection(
        status=ProjectionStatus.NO_PERSONALIZED_DISCLOSURE
    )
    audit = _audit(
        status=ProjectionStatus.NO_PERSONALIZED_DISCLOSURE,
        reason=ProjectionReasonCode.NO_PERSONALIZED_DISCLOSURE,
    )
    result = RoleProjectionResult(
        status=ProjectionStatus.NO_PERSONALIZED_DISCLOSURE,
        prompt=prompt,
        audit=audit,
    )
    public = result.to_public_dict()
    assert set(public) == {"status", "claims", "limitations", "citations"}
    assert not any(
        forbidden in json.dumps(public)
        for forbidden in (
            "result_exists",
            "request_id",
            "policy_id",
            "policy_hash",
            "reason_codes",
            "suppressed",
        )
    )
    assert "policy_hash" in result.audit.to_dict()
    prompt_field_names = {item.name for item in fields(prompt)}
    assert prompt_field_names.isdisjoint(
        {
            "policy_hash",
            "review_status",
            "safety_action",
            "source_status",
            "raw_response",
            "theta",
            "se",
        }
    )
    assert not {
        "raw_response",
        "theta",
        "se",
        "full_prompt",
        "pii",
    } & set(audit.to_dict())


def test_schema_accepts_typed_denial_result_and_rejects_public_claim_leak():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    registry = load_role_projection_policy_registry(REGISTRY_PATH)
    teacher = next(
        item for item in registry.policies if item.audience_role is AudienceRole.TEACHER_SUPPORT
    )
    result = RoleProjectionResult(
        status=ProjectionStatus.NO_PERSONALIZED_DISCLOSURE,
        prompt=_build_prompt_facing_projection(
            status=ProjectionStatus.NO_PERSONALIZED_DISCLOSURE
        ),
        audit=_audit(
            status=ProjectionStatus.NO_PERSONALIZED_DISCLOSURE,
            reason=ProjectionReasonCode.NO_PERSONALIZED_DISCLOSURE,
            policy=teacher,
        ),
    ).to_dict()
    assert list(validator.iter_errors(result)) == []
    leaked = copy.deepcopy(result)
    leaked["prompt"]["claims"] = [{"claim_code": "HIDDEN_CLAIM", "value": True}]
    assert list(validator.iter_errors(leaked))


@pytest.mark.parametrize(
    "claim_code",
    (
        "DIAGNOSIS",
        "THETA",
        "SCORE",
        "CLINICAL_SEVERITY",
        "RAW_RESPONSE",
        "SEVERITY",
        "PRECISION",
        "STANDARD_ERROR",
        "LATENT",
        "LEVEL",
        "LEVEL_1_TO_5",
        "CONFIDENCE_INTERVAL",
    ),
)
def test_schema_rejects_forbidden_prompt_claim_codes(claim_code):
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    code_rules = schema["$defs"]["forbiddenPromptCode"]["allOf"]
    assert all("not" in rule and "pattern" in rule["not"] for rule in code_rules)

    payload = _ready_result_payload()
    payload["prompt"]["claims"] = [{"claim_code": claim_code, "value": True}]
    assert list(validator.iter_errors(payload))


@pytest.mark.parametrize(
    "limitation",
    (
        "DIAGNOSIS",
        "THETA",
        "SCORE",
        "CLINICAL_SEVERITY",
        "RAW_RESPONSE",
        "SEVERITY",
        "PRECISION",
        "STANDARD_ERROR",
        "LATENT",
        "LEVEL",
        "LEVEL_1_TO_5",
        "CONFIDENCE_INTERVAL",
    ),
)
def test_schema_rejects_forbidden_prompt_limitations_but_keeps_safe_codes(limitation):
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    payload = _ready_result_payload()
    assert list(validator.iter_errors(payload)) == []

    payload["prompt"]["limitations"] = [limitation]
    assert list(validator.iter_errors(payload))

    payload["prompt"]["limitations"] = [
        "SYNTHETIC_ONLY",
        "NOT_DIAGNOSTIC",
        "NO_VALIDATED_CUTOFF",
        "NO_CLINICAL_INFERENCE",
        "NO_CRISIS_INFERENCE",
        "NO_PERSONALIZED_DISCLOSURE",
        "SYNTHETIC_TEST_ONLY",
    ]
    assert list(validator.iter_errors(payload)) == []


def test_status_extensions_require_justification_and_never_replace_canonical_status():
    from prompt_engine.role_projection_models import StatusExtension

    with pytest.raises(RoleProjectionError):
        StatusExtension(code="D3R_EXTENSION", justification="")
    extension = StatusExtension(code="D3R_EXTENSION", justification="synthetic test diagnostic")
    assert extension.code not in CANONICAL_PROJECTION_STATUSES
