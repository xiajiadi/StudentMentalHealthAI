from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest

from smhai_backend.core.orchestration import (
    OrchestrationStage,
    OrchestrationState,
    StageLedger,
    StageLedgerError,
)
from smhai_backend.core.trusted_context import (
    AudienceRole,
    DisclosureState,
    ExecutionMode,
    TrustedContextError,
    TrustedContextPolicy,
    TrustedPurpose,
    TrustedRelationship,
    TrustedRequestContext,
    derive_trusted_request_context,
)
from smhai_backend.domains.assessment.binding import (
    D3_IDENTITY,
    D3_POLICY_ID,
    LEGACY_BACKEND_COMPATIBILITY_FIXTURE,
    AssessmentBindingError,
    AssessmentCompatibilityFixture,
    AssessmentIdentity,
    bind_assessment,
)
from smhai_backend.domains.models import Actor, AssessmentRecord, BackendRole
from smhai_backend.integrations.contracts import validate_frozen
from smhai_backend.integrations.d3 import interpret_assessment


def _assessment(
    *,
    assessment_id: str = "ASSESS_d3_001",
    subject_id: str = "SUBJ_demo_a",
    exact_d3_identity: bool = True,
) -> dict[str, object]:
    identity = D3_IDENTITY if exact_d3_identity else LEGACY_BACKEND_COMPATIBILITY_FIXTURE.source
    return {
        "schema_version": "assessment.v1",
        "assessment_id": assessment_id,
        "subject_id": subject_id,
        "instrument": {
            "instrument_id": identity.instrument_id,
            "version": identity.instrument_version,
        },
        "population_scope": identity.population_scope,
        "status": "completed",
        "dimensions": {
            "demo_trait" if exact_d3_identity else "wellbeing": {
                "theta": -0.25,
                "se": 0.42,
                "score": None,
                "band": "unknown",
                "interpretation_status": "estimated",
                "items_answered": 9,
            }
        },
        "risk": {
            "level": "normal",
            "need_human_review": False,
            "reason_codes": ["RULESET_SYNTHETIC_DEMO_NORMAL"],
            "ruleset_id": "RULESET_synthetic_demo_v1",
        },
        "response_summary": {"items_answered": 1, "duration_seconds": 1},
        "provenance": {
            "source_adapter": "synthetic",
            "adapter_version": "1.0",
            "cat_engine_version": "synthetic",
            "item_bank_version": "demo.v1",
        },
        "timestamps": {
            "started_at": "2026-09-16T00:00:00Z",
            "completed_at": "2026-09-16T00:01:00Z",
        },
    }


def _record(**kwargs: object) -> AssessmentRecord:
    value = _assessment(
        assessment_id=cast(str, kwargs.get("assessment_id", "ASSESS_d3_001")),
        subject_id=cast(str, kwargs.get("subject_id", "SUBJ_demo_a")),
        exact_d3_identity=cast(bool, kwargs.get("exact_d3_identity", True)),
    )
    return AssessmentRecord(
        assessment_id=str(value["assessment_id"]),
        subject_id=str(value["subject_id"]),
        assessment=value,
    )


def _student(subject_id: str = "SUBJ_demo_a") -> Actor:
    return Actor(
        user_id="USER_student_a",
        username="student_a",
        role=BackendRole.STUDENT,
        subject_id=subject_id,
    )


def test_server_derived_context_ignores_generic_purpose_and_sets_d3_mapping() -> None:
    context = derive_trusted_request_context(
        _student(),
        _assessment(),
        request={"target_role": "student", "purpose": "education_support"},
        transaction_id="TX_d3_001",
        request_id="REQ_d3_001",
        trace_id="TRACE_d3_001",
    )

    assert context.principal_id == "USER_student_a"
    assert context.product_role is BackendRole.STUDENT
    assert context.audience_role is AudienceRole.STUDENT_SELF
    assert context.purpose is TrustedPurpose.SELF_UNDERSTANDING
    assert context.relationship is TrustedRelationship.SELF
    assert context.disclosure_state is DisclosureState.SYNTHETIC_SELF
    assert context.to_dict()["transaction_id"] == "TX_d3_001"


@pytest.mark.parametrize(
    "field,value",
    [
        ("purpose", "SYNTHETIC_PARENT_DEMO"),
        ("relationship", "ASSIGNED_SUPPORT"),
        ("execution_mode", "REAL_USER"),
        ("disclosure_authorized", True),
        ("safety_action", "PROCEED"),
        ("review_status", "approved"),
    ],
)
def test_caller_privilege_forgery_fails_closed(field: str, value: object) -> None:
    request = {"target_role": "student", field: value}
    with pytest.raises(TrustedContextError) as caught:
        derive_trusted_request_context(_student(), _assessment(), request=request)
    assert caught.value.code in {"CALLER_PRIVILEGE_ASSERTION", "TRUSTED_CONTEXT_MISMATCH"}


def test_direct_context_construction_and_plain_mapping_are_rejected() -> None:
    with pytest.raises(TypeError, match="internal-only"):
        TrustedRequestContext(
            transaction_id="TX_d3",
            principal_id="USER_student_a",
            product_role=BackendRole.STUDENT,
            subject_id="SUBJ_demo_a",
            purpose=TrustedPurpose.SELF_UNDERSTANDING,
            relationship=TrustedRelationship.SELF,
            execution_mode="SYNTHETIC_DEMO",  # type: ignore[arg-type]
            disclosure_state=DisclosureState.SYNTHETIC_SELF,
            request_id="REQ_d3",
            trace_id="TRACE_d3",
            context_id="CTX_d3",
            audience_role=AudienceRole.STUDENT_SELF,
        )

    with pytest.raises(StageLedgerError) as caught:
        StageLedger({"product_role": "STUDENT"})  # type: ignore[arg-type]
    assert caught.value.code == "TRUSTED_CONTEXT_REQUIRED"


def test_student_foreign_assessment_is_idor_denied() -> None:
    with pytest.raises(AssessmentBindingError) as caught:
        bind_assessment(
            _student(),
            _record(subject_id="SUBJ_demo_b"),
            assessment_id="ASSESS_d3_001",
        )
    assert caught.value.code == "SUBJECT_SCOPE_DENIED"


def test_parent_real_user_policy_is_explicitly_rejected() -> None:
    parent = Actor(
        user_id="USER_parent_demo",
        username="parent_demo",
        role=BackendRole.PARENT,
        subject_id=None,
        accessible_subject_ids=frozenset({"SUBJ_demo_a"}),
    )
    with pytest.raises(TrustedContextError) as caught:
        derive_trusted_request_context(
            parent,
            _assessment(),
            target_role="parent",
            policy=TrustedContextPolicy(
                execution_mode=ExecutionMode.REAL_USER,
                allow_real_user=True,
            ),
        )
    assert caught.value.code == "EXECUTION_MODE_NOT_ALLOWED"


def test_path_body_and_record_assessment_ids_must_match() -> None:
    with pytest.raises(AssessmentBindingError) as caught:
        bind_assessment(
            _student(),
            _record(),
            assessment_id="ASSESS_d3_002",
            requested_assessment_id="ASSESS_d3_003",
        )
    assert caught.value.code == "ASSESSMENT_ID_MISMATCH"


def test_repository_record_id_must_match_requested_assessment() -> None:
    record = _record()
    record.assessment_id = "ASSESS_d3_other"
    with pytest.raises(AssessmentBindingError) as caught:
        bind_assessment(
            _student(),
            record,
            assessment_id="ASSESS_d3_001",
        )
    assert caught.value.code == "ASSESSMENT_ID_MISMATCH"


def test_legacy_backend_fixture_requires_explicit_approved_compatibility() -> None:
    with pytest.raises(AssessmentBindingError) as caught:
        bind_assessment(
            _student(),
            _record(exact_d3_identity=False),
            assessment_id="ASSESS_d3_001",
        )
    assert caught.value.code == "ASSESSMENT_COMPATIBILITY_REQUIRED"

    approved = replace(
        LEGACY_BACKEND_COMPATIBILITY_FIXTURE,
        approved=True,
        approval_reference="D3-4-controller-fixture-test",
        dimension_map=(("wellbeing", "demo_trait"),),
    )
    binding = bind_assessment(
        _student(),
        _record(exact_d3_identity=False),
        assessment_id="ASSESS_d3_001",
        compatibility_fixtures=(approved,),
    )
    assert binding.is_compatibility_mapped
    assert binding.source_identity == LEGACY_BACKEND_COMPATIBILITY_FIXTURE.source
    assert binding.d3_identity == D3_IDENTITY
    projected = binding.assessment_for_d3()
    assert projected["instrument"] == {
        "instrument_id": D3_IDENTITY.instrument_id,
        "version": D3_IDENTITY.instrument_version,
    }
    assert projected["population_scope"] == D3_IDENTITY.population_scope
    validate_frozen("assessment.v1.schema.json", projected)
    assert "backend_compatibility_fixture" not in projected["provenance"]  # type: ignore[operator]
    audit = binding.audit_projection()
    assert audit["compatibility_fixture_id"] == approved.fixture_id
    assert audit["compatibility_fixture_version"] == approved.fixture_version
    assert audit["compatibility_dimension_map"] == {"wellbeing": "demo_trait"}
    context = derive_trusted_request_context(
        _student(),
        projected,
        transaction_id="TX_d3_projection",
        request_id="REQ_d3_projection",
        trace_id="TRACE_d3_projection",
    )
    result = interpret_assessment(
        context=context,
        assessment=projected,
        safety_action="PROCEED",
    )
    assert result.status.value == "MEASUREMENT_ONLY"


def test_compatibility_fixture_target_and_policy_are_checked() -> None:
    invalid = AssessmentCompatibilityFixture(
        fixture_id="bad",
        fixture_version="1.0.0",
        source=LEGACY_BACKEND_COMPATIBILITY_FIXTURE.source,
        target=AssessmentIdentity("other", "other", "other"),
        policy_id=D3_POLICY_ID,
        approved=True,
    )
    with pytest.raises(AssessmentBindingError) as caught:
        bind_assessment(
            _student(),
            _record(exact_d3_identity=False),
            assessment_id="ASSESS_d3_001",
            compatibility_fixtures=(invalid,),
        )
    assert caught.value.code == "ASSESSMENT_COMPATIBILITY_INVALID"


def test_binding_detects_mutation_and_keeps_source_identity() -> None:
    binding = bind_assessment(_student(), _record(), assessment_id="ASSESS_d3_001")
    binding.assessment["risk"]["level"] = "high"  # type: ignore[index]
    with pytest.raises(AssessmentBindingError) as caught:
        binding.assert_intact()
    assert caught.value.code == "ASSESSMENT_BINDING_TAMPERED"


def test_stage_ledger_enforces_order_duplicate_context_and_safety_stop() -> None:
    context = derive_trusted_request_context(
        _student(),
        _assessment(),
        transaction_id="TX_stage",
        request_id="REQ_stage",
        trace_id="TRACE_stage",
    )
    ledger = StageLedger(context)
    with pytest.raises(StageLedgerError) as caught:
        ledger.advance(OrchestrationStage.REQUEST_AUTHORIZED)
    assert caught.value.code == "STAGE_OUT_OF_ORDER"

    ledger.advance(OrchestrationStage.REQUEST_AUTHENTICATED)
    with pytest.raises(StageLedgerError) as caught:
        ledger.advance(
            OrchestrationStage.REQUEST_AUTHORIZED,
            context=replace(context, context_id="CTX_other"),
        )
    assert caught.value.code == "TRUSTED_CONTEXT_MISMATCH"
    ledger.advance(OrchestrationStage.REQUEST_AUTHORIZED)
    ledger.advance(
        OrchestrationStage.INPUT_SAFETY_EVALUATED,
        safety_action="CRISIS_ROUTE",
    )
    assert ledger.state is OrchestrationState.ABORTED
    assert ledger.terminal_action == "CRISIS_ROUTE"
    with pytest.raises(StageLedgerError) as caught:
        ledger.advance(OrchestrationStage.ASSESSMENT_BOUND)
    assert caught.value.code == "STAGE_TERMINAL"
