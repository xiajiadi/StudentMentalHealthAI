"""Synthetic-only tests for the D3-3 projection engine."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import pytest

from prompt_engine.role_projection import (
    SourceResultError,
    project,
    prompt_input,
)
from prompt_engine.role_projection_models import (
    AudienceRole,
    PolicyReference,
    ProjectionStatus,
    PromptFacingProjection,
    RoleProjectionError,
    SourceStatus,
    TrustedAudienceContext,
    _build_trusted_audience_context,
    load_role_projection_policy_registry,
)

REGISTRY_PATH = (
    Path(__file__).resolve().parents[1] / "assets" / "role_projection_policy_registry.v1.json"
)
REGISTRY = load_role_projection_policy_registry(REGISTRY_PATH)
SOURCE_POLICY = {
    "policy_id": "POLICY_assessment_synthetic_measurement_only",
    "policy_version": "1.0.0",
    "effective_version": "1.0.0",
    "policy_hash": "sha256:7c61cf80dc68561c78618c2d6e3859295b0dc53a291a1805c9bb623c5b7714a4",
    "policy_kind": "SHIPPED_CONSERVATIVE",
    "psychology_review_status": "REVISIONS_REQUIRED",
    "review_decision_id": "D1_RECONCILIATION_2026-09-14",
}
LIMITATIONS = [
    "SYNTHETIC_ONLY",
    "NOT_DIAGNOSTIC",
    "NO_VALIDATED_CUTOFF",
    "NO_CLINICAL_INFERENCE",
    "NO_CRISIS_INFERENCE",
]


def policy(role: AudienceRole):
    return next(item for item in REGISTRY.policies if item.audience_role is role)


def context(
    role: AudienceRole = AudienceRole.STUDENT_SELF,
    *,
    purpose: str | None = None,
    relation: str | None = None,
    mode: str = "SYNTHETIC_DEMO",
    authorization: str | None = None,
    source_status: str = "MEASUREMENT_ONLY",
    source_claim_codes: list[str] | None = None,
    safety_action: str = "PROCEED",
) -> TrustedAudienceContext:
    purpose = purpose or {
        "STUDENT_SELF": "SELF_UNDERSTANDING",
        "TEACHER_SUPPORT": "EDUCATIONAL_SUPPORT",
        "PARENT_DEMO": "SYNTHETIC_PARENT_DEMO",
    }.get(role.value, "SELF_UNDERSTANDING")
    relation = relation or {
        "STUDENT_SELF": "SELF",
        "TEACHER_SUPPORT": "ASSIGNED_SUPPORT",
        "PARENT_DEMO": "SYNTHETIC_DEMO",
    }.get(role.value, "SELF")
    authorization = authorization or {
        "STUDENT_SELF": "SYNTHETIC_SELF",
        "TEACHER_SUPPORT": "SYNTHETIC_SUPPORT",
        "PARENT_DEMO": "SYNTHETIC_PARENT_DEMO",
    }.get(role.value, "NOT_AUTHORIZED")
    return _build_trusted_audience_context(
        {
            "audience_role": role.value,
            "purpose_of_use": purpose,
            "subject_relation": relation,
            "execution_mode": mode,
            "disclosure_authorization": authorization,
            "source_status": source_status,
            "source_claim_codes": source_claim_codes or [],
            "safety_action": safety_action,
            "request_id": "REQ_d3r_engine_test",
            "trace_id": "TRACE_d3r_engine_test",
            "context_id": "CTX_d3r_engine_test",
            "context_version": "1.0.0",
        }
    )


def source(
    *,
    status: str = "MEASUREMENT_ONLY",
    reason_codes: list[str] | None = None,
    claims: list[dict[str, Any]] | None = None,
    limitations: list[str] | None = None,
    policy_value: dict[str, Any] | None = None,
    audit_action: str = "PROCEED",
    audit_mode: str = "SYNTHETIC_DEMO",
) -> dict[str, Any]:
    return {
        "schema_version": "interpretation_result.v1",
        "status": status,
        "reason_codes": reason_codes or [
            "POLICY_CONSERVATIVE_MEASUREMENT_ONLY"
            if status == "MEASUREMENT_ONLY"
            else status
        ],
        "assessment_id": "ASSESS_d3r_engine_demo",
        "subject_id": "SUBJ_d3r_engine_demo",
        "instrument": {
            "instrument_id": "CURRENT_SYNTHETIC_GRM",
            "version": "synthetic_item_bank.v1 / demo.v1",
        },
        "population_scope": "SYNTHETIC_STUDENT_DEMO",
        "policy": copy.deepcopy(SOURCE_POLICY if policy_value is None else policy_value),
        "claims": copy.deepcopy(claims or []),
        "limitations": copy.deepcopy(LIMITATIONS if limitations is None else limitations),
        "audit": {
            "request_id": "REQ_d3r_engine_test",
            "trace_id": "TRACE_d3r_engine_test",
            "context_id": "CTX_d3r_engine_test",
            "context_version": "1.0.0",
            "execution_mode": audit_mode,
            "safety_action": audit_action,
        },
    }


def reference(role: AudienceRole) -> PolicyReference:
    selected_role = (
        role
        if role in {item.audience_role for item in REGISTRY.policies}
        else AudienceRole.STUDENT_SELF
    )
    selected = policy(selected_role)
    return PolicyReference(selected.policy_id, selected.policy_version, selected.policy_hash)


def project_for(
    role: AudienceRole = AudienceRole.STUDENT_SELF,
    *,
    source_value: dict[str, Any] | None = None,
    context_value: TrustedAudienceContext | None = None,
    citations: tuple[dict[str, Any], ...] = (),
):
    selected_context = context_value or context(role)
    return project(
        source_value or source(),
        reference(role),
        selected_context,
        citations,
    )


def test_student_synthetic_measurement_only_is_ready_with_safe_allowlist():
    result = project_for(citations=({"source_chunk_id": "CHUNK_d3r_demo", "locator": "p.1"},))

    assert result.status is ProjectionStatus.READY_FOR_PROMPT
    assert result.prompt.content_claim_codes == ()
    assert result.prompt.limitations == tuple(LIMITATIONS)
    assert result.prompt.citations[0].source_chunk_id == "CHUNK_d3r_demo"
    assert result.audit.policy_id == "ROLE_PROJECTION_STUDENT_SELF_V09"


def test_teacher_support_is_coarse_default_deny_with_no_hidden_fields():
    result = project_for(AudienceRole.TEACHER_SUPPORT)

    assert result.status is ProjectionStatus.NO_PERSONALIZED_DISCLOSURE
    assert result.to_public_dict() == {
        "status": "NO_PERSONALIZED_DISCLOSURE",
        "claims": [],
        "limitations": [],
        "citations": [],
    }
    assert result.audit.suppressed_claim_codes == ()
    assert "policy_hash" not in result.to_public_dict()

    hidden_source = source(
        claims=[
            {"claim_code": "SYNTHETIC_HIDDEN_CLAIM", "construct_id": "demo_trait", "value": True}
        ]
    )
    hidden = project_for(
        AudienceRole.TEACHER_SUPPORT,
        source_value=hidden_source,
        context_value=context(
            AudienceRole.TEACHER_SUPPORT,
            source_claim_codes=["SYNTHETIC_HIDDEN_CLAIM"],
        ),
    )
    assert hidden.to_public_dict() == result.to_public_dict()
    assert hidden.audit.suppressed_claim_codes == ("SYNTHETIC_HIDDEN_CLAIM",)


def test_parent_synthetic_demo_is_coarse_and_hidden_claims_are_audit_only():
    result = project_for(AudienceRole.PARENT_DEMO)
    assert result.status is ProjectionStatus.NO_PERSONALIZED_DISCLOSURE
    assert result.to_public_dict() == {
        "status": "NO_PERSONALIZED_DISCLOSURE",
        "claims": [],
        "limitations": [],
        "citations": [],
    }

    hidden = project_for(
        AudienceRole.PARENT_DEMO,
        source_value=source(
            claims=[
                {
                    "claim_code": "SYNTHETIC_HIDDEN_CLAIM",
                    "construct_id": "demo_trait",
                    "value": True,
                }
            ]
        ),
        context_value=context(
            AudienceRole.PARENT_DEMO,
            source_claim_codes=["SYNTHETIC_HIDDEN_CLAIM"],
        ),
    )
    assert hidden.status is ProjectionStatus.NO_PERSONALIZED_DISCLOSURE
    assert hidden.to_public_dict() == result.to_public_dict()
    assert hidden.audit.suppressed_claim_codes == ("SYNTHETIC_HIDDEN_CLAIM",)

    real_context = context(
        AudienceRole.PARENT_DEMO,
        mode="REAL_USER",
        source_status="ABSTAIN_REAL_USER_BLOCKED",
    )
    blocked = project_for(
        AudienceRole.PARENT_DEMO,
        context_value=real_context,
        source_value=source(
            status="ABSTAIN_REAL_USER_BLOCKED",
            reason_codes=["ABSTAIN_REAL_USER_BLOCKED"],
            limitations=[],
            audit_mode="REAL_USER",
        ),
    )
    assert blocked.status is ProjectionStatus.ABSTAIN_MODE_NOT_ALLOWED
    assert blocked.to_public_dict()["claims"] == []


@pytest.mark.parametrize("role", [AudienceRole.SYSTEM_ADMIN, AudienceRole.UNKNOWN])
def test_admin_and_unknown_are_denied_with_same_coarse_public_shape(role: AudienceRole):
    result = project_for(role)
    assert result.status is ProjectionStatus.NO_PERSONALIZED_DISCLOSURE
    assert set(result.to_public_dict()) == {"status", "claims", "limitations", "citations"}
    assert result.to_public_dict()["claims"] == []


@pytest.mark.parametrize(
    ("role", "kwargs", "status"),
    [
        (
            AudienceRole.STUDENT_SELF,
            {"purpose": "EDUCATIONAL_SUPPORT"},
            ProjectionStatus.ABSTAIN_PURPOSE_NOT_ALLOWED,
        ),
        (
            AudienceRole.STUDENT_SELF,
            {"relation": "ASSIGNED_SUPPORT"},
            ProjectionStatus.ABSTAIN_RELATIONSHIP_MISMATCH,
        ),
        (
            AudienceRole.TEACHER_SUPPORT,
            {"authorization": "SYNTHETIC_SELF"},
            ProjectionStatus.ABSTAIN_DISCLOSURE_NOT_AUTHORIZED,
        ),
    ],
)
def test_role_purpose_relation_and_authorization_forgery_denies(role, kwargs, status):
    forged = context(role, **kwargs)
    result = project_for(role, context_value=forged)
    assert result.status is status
    assert result.prompt.claims == ()
    assert result.prompt.limitations == ()


def test_raw_mapping_cannot_replace_trusted_context():
    with pytest.raises(RoleProjectionError) as exc_info:
        project_for(context_value=cast(Any, {"audience_role": "STUDENT_SELF"}))
    assert exc_info.value.reason_code == "TRUSTED_CONTEXT_REQUIRED"


@pytest.mark.parametrize("action", ["CRISIS_ROUTE", "REVIEW_REQUIRED", "BLOCK"])
def test_safety_bypass_stops_projection_and_keeps_action_audit_only(action):
    bypass = source(
        status="BYPASS_SAFETY",
        reason_codes=[action],
        limitations=[],
        policy_value={key: None for key in SOURCE_POLICY},
        audit_action=action,
    )
    result = project_for(
        source_value=bypass,
        context_value=context(
            source_status="BYPASS_SAFETY",
            safety_action=action,
        ),
    )
    assert result.status is ProjectionStatus.BYPASS_SAFETY
    assert result.to_public_dict() == {
        "status": "BYPASS_SAFETY",
        "claims": [],
        "limitations": [],
        "citations": [],
    }
    assert result.audit.safety_action is not None
    assert result.audit.safety_action.value == action
    assert action not in json.dumps(result.to_public_dict())


def test_abstain_source_status_cannot_be_upgraded():
    abstain = source(
        status="ABSTAIN_INSTRUMENT_MISMATCH",
        reason_codes=["POLICY_INSTRUMENT_MISMATCH"],
        limitations=[],
    )
    result = project_for(
        source_value=abstain,
        context_value=context(source_status="ABSTAIN_INSTRUMENT_MISMATCH"),
    )
    assert result.status is ProjectionStatus.ABSTAIN_SOURCE_STATUS
    assert result.prompt.claims == ()
    assert result.audit.source_status is SourceStatus.ABSTAIN_INSTRUMENT_MISMATCH


def test_source_claim_injection_and_trust_status_tamper_fail_atomically():
    injected = source(
        claims=[
            {"claim_code": "INJECTED_CLAIM", "construct_id": "demo_trait", "value": True}
        ]
    )
    with pytest.raises(SourceResultError) as exc_info:
        project_for(source_value=injected)
    assert exc_info.value.reason_code == "SOURCE_CLAIMS_TRUST_MISMATCH"

    with pytest.raises(SourceResultError) as subset_error:
        project_for(
            source_value=injected,
            context_value=context(source_claim_codes=["INJECTED_CLAIM"]),
        )
    assert subset_error.value.reason_code == "SOURCE_CLAIMS_NOT_SUBSET"

    with pytest.raises(SourceResultError) as status_error:
        project_for(
            source_value=source(),
            context_value=context(source_status="ABSTAIN_INPUT_INVALID"),
        )
    assert status_error.value.reason_code == "SOURCE_STATUS_TRUST_MISMATCH"


@pytest.mark.parametrize(
    "forbidden_code",
    [
        "SEVERITY",
        "PRECISION",
        "STANDARD_ERROR",
        "LATENT",
        "LEVEL",
        "LEVEL_1_TO_5",
        "INTERVAL",
        "CONFIDENCE_INTERVAL",
        "SE",
    ],
)
def test_forbidden_source_claim_codes_fail_before_teacher_parent_suppression(
    forbidden_code: str,
):
    with pytest.raises(SourceResultError) as claim_error:
        project_for(
            AudienceRole.PARENT_DEMO,
            source_value=source(
                claims=[
                    {
                        "claim_code": forbidden_code,
                        "construct_id": "demo_trait",
                        "value": True,
                    }
                ]
            ),
            context_value=context(
                AudienceRole.PARENT_DEMO,
                source_claim_codes=[forbidden_code],
            ),
        )
    assert claim_error.value.reason_code == "SOURCE_CLAIM_CODE_INVALID"

    with pytest.raises(SourceResultError) as construct_error:
        project_for(
            AudienceRole.TEACHER_SUPPORT,
            source_value=source(
                claims=[
                    {
                        "claim_code": "SYNTHETIC_HIDDEN_CLAIM",
                        "construct_id": forbidden_code,
                        "value": True,
                    }
                ]
            ),
            context_value=context(
                AudienceRole.TEACHER_SUPPORT,
                source_claim_codes=["SYNTHETIC_HIDDEN_CLAIM"],
            ),
        )
    assert construct_error.value.reason_code == "SOURCE_CLAIM_CONSTRUCT_INVALID"


def test_source_policy_identity_tamper_fails_closed():
    tampered = copy.deepcopy(SOURCE_POLICY)
    tampered["policy_id"] = "POLICY_forged"
    with pytest.raises(SourceResultError) as exc_info:
        project_for(source_value=source(policy_value=tampered))
    assert exc_info.value.reason_code == "SOURCE_POLICY_IDENTITY_MISMATCH"


def test_exact_policy_hash_and_fallback_references_are_denied():
    selected = policy(AudienceRole.STUDENT_SELF)
    wrong_hash = PolicyReference(selected.policy_id, selected.policy_version, "sha256:" + "0" * 64)
    result = project(
        source(),
        wrong_hash,
        context(),
    )
    assert result.status is ProjectionStatus.ABSTAIN_POLICY_MISMATCH
    fallback = project(
        source(),
        {
            "policy_id": selected.policy_id,
            "policy_version": "latest",
            "policy_hash": selected.policy_hash,
        },
        context(),
    )
    assert fallback.status is ProjectionStatus.ABSTAIN_POLICY_MISMATCH


def test_missing_policy_reference_is_a_typed_policy_missing_abstention():
    result = project(source(), None, context())

    assert result.status is ProjectionStatus.ABSTAIN_POLICY_MISSING
    assert result.to_public_dict() == {
        "status": "ABSTAIN_POLICY_MISSING",
        "claims": [],
        "limitations": [],
        "citations": [],
    }


def test_prompt_and_audit_surfaces_are_separate_and_audit_is_rejected_as_prompt_input():
    result = project_for()
    assert set(result.to_public_dict()) == {"status", "claims", "limitations", "citations"}
    assert "request_id" not in result.to_public_dict()
    assert "policy_id" not in result.to_public_dict()
    with pytest.raises(TypeError):
        prompt_input(result.audit)
    with pytest.raises(TypeError):
        prompt_input(result)
    assert prompt_input(result.prompt) == result.to_public_dict()


def test_direct_forged_prompt_surface_is_rejected_before_serialization():
    with pytest.raises(TypeError):
        PromptFacingProjection(status=ProjectionStatus.READY_FOR_PROMPT)

    forged = object.__new__(PromptFacingProjection)
    object.__setattr__(forged, "status", ProjectionStatus.READY_FOR_PROMPT)
    object.__setattr__(forged, "claims", ())
    object.__setattr__(forged, "limitations", ())
    object.__setattr__(forged, "citations", ())
    object.__setattr__(forged, "_capability", None)
    with pytest.raises(TypeError):
        prompt_input(forged)


def test_citations_are_opaque_and_extra_source_text_is_rejected():
    result = project_for(citations=({"source_chunk_id": "CHUNK_d3r_demo", "locator": None},))
    assert result.prompt.citations[0].locator is None
    with pytest.raises(RoleProjectionError):
        project_for(
            citations=(
                {
                    "source_chunk_id": "CHUNK_d3r_demo",
                    "locator": "p.1",
                    "source_text": "forbidden",
                },
            )
        )


def test_deterministic_repeatability_and_input_immutability():
    source_value = source()
    before = copy.deepcopy(source_value)
    first = project_for(source_value=source_value)
    second = project_for(source_value=source_value)
    assert first.to_dict() == second.to_dict()
    assert source_value == before


def test_public_output_has_no_measurement_or_clinical_fields():
    encoded = json.dumps(project_for().to_public_dict()).lower()
    for forbidden in (
        "theta",
        "se",
        "score",
        "band",
        "diagnosis",
        "risk",
        "natural_language",
    ):
        assert forbidden not in encoded
