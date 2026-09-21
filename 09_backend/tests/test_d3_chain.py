from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

import pytest

from smhai_backend.core.orchestration import OrchestrationStage, StageLedger
from smhai_backend.core.trusted_context import derive_trusted_request_context
from smhai_backend.domains.assessment.binding import (
    D3_IDENTITY,
    D3_POLICY_HASH,
    D3_POLICY_ID,
    D3_POLICY_VERSION,
    LEGACY_BACKEND_COMPATIBILITY_FIXTURE,
    AssessmentBindingError,
    bind_assessment,
)
from smhai_backend.domains.models import Actor, AssessmentRecord, BackendRole
from smhai_backend.integrations import d3_chain as d3_chain_module
from smhai_backend.integrations.d3 import default_fixture_config
from smhai_backend.integrations.d3_chain import (
    D3ChainError,
    compose_d3_chain,
    interpret_d3_chain,
)
from smhai_backend.integrations.evidence import (
    EligibilityPolicy,
    build_retrieval_evidence_bundle,
)
from smhai_backend.integrations.rag import Citation, KnowledgeChunk, RetrievalResult

_ASSESSMENT_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "03_assessment-adapter"
    / "fixtures"
    / "synthetic_assessment.v1.json"
)


def _assessment() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(_ASSESSMENT_FIXTURE.read_text(encoding="utf-8")))


def _actor(role: BackendRole, subject_id: str) -> Actor:
    if role is BackendRole.STUDENT:
        return Actor(
            user_id="USER_d3_student",
            username="d3_student",
            role=role,
            subject_id=subject_id,
        )
    return Actor(
        user_id=f"USER_d3_{role.value.lower()}",
        username=f"d3_{role.value.lower()}",
        role=role,
        subject_id=None,
        accessible_subject_ids=frozenset({subject_id}),
    )


def _prepared(role: BackendRole) -> tuple[Any, Any, StageLedger, Any]:
    assessment = _assessment()
    actor = _actor(role, assessment["subject_id"])
    record = AssessmentRecord(
        assessment_id=assessment["assessment_id"],
        subject_id=assessment["subject_id"],
        assessment=assessment,
    )
    context = derive_trusted_request_context(
        actor,
        assessment,
        transaction_id=f"TX_d3_{role.value.lower()}",
        request_id=f"REQ_d3_{role.value.lower()}",
        trace_id=f"TRACE_d3_{role.value.lower()}",
    )
    binding = bind_assessment(
        actor,
        record,
        assessment_id=assessment["assessment_id"],
        trusted_context=context,
    )
    ledger = StageLedger(context)
    ledger.advance(OrchestrationStage.REQUEST_AUTHENTICATED)
    ledger.advance(OrchestrationStage.REQUEST_AUTHORIZED)
    ledger.advance(OrchestrationStage.INPUT_SAFETY_EVALUATED, safety_action="PROCEED")
    ledger.advance(OrchestrationStage.ASSESSMENT_BOUND)
    target_role = {
        BackendRole.STUDENT: "student",
        BackendRole.TEACHER: "teacher",
        BackendRole.PARENT: "parent",
        BackendRole.ADMIN: "admin",
    }[role]
    chunk = KnowledgeChunk(
        schema_version="knowledge.v1",
        chunk_id=f"CHUNK_d3_{target_role}",
        document_id="KB_d3_chain",
        text="Synthetic support material.",
        content_type="approved_summary",
        location={"section": "demo", "page_start": None, "page_end": None},
        citation=Citation(
            title="D3 synthetic guidance",
            organization="StudentMentalHealthAI synthetic fixture",
            locator="fixture://d3-chain",
        ),
        population_scope=["UNIVERSITY_FRESHMEN_SYNTHETIC_DEMO"],
        role_scope=[target_role],
        risk_scope=["normal", "attention"],
        review_status="approved",
        rights_status="verified",
        content_hash="sha256:" + "a" * 64,
    )
    retrieval = RetrievalResult(
        retrieval_id=f"RETR_d3_{target_role}",
        chunks=(chunk,),
        label="D3_TEST",
    )
    bundle = build_retrieval_evidence_bundle(
        retrieval,
        transaction_id=context.transaction_id,
        request_id=context.request_id,
        trace_id=context.trace_id,
        policy=EligibilityPolicy(
            target_population="UNIVERSITY_FRESHMEN_SYNTHETIC_DEMO",
            target_role=target_role,
            risk_level="normal",
        ),
    )
    return context, binding, ledger, bundle


def test_student_composes_real_d3_chain_and_excludes_measurements() -> None:
    context, binding, ledger, bundle = _prepared(BackendRole.STUDENT)

    result = compose_d3_chain(
        context,
        binding,
        ledger,
        bundle,
        generation_id="GEN_d3_student",
    )

    assert result.interpretation.status.value == "MEASUREMENT_ONLY"
    assert result.role_projection.status.value == "READY_FOR_PROMPT"
    assert result.assessment_policy == result.assessment_policy.__class__(
        D3_POLICY_ID,
        D3_POLICY_VERSION,
        D3_POLICY_HASH,
    )
    assert result.template.prompt_id == "PROMPT_student_synthetic_v1"
    assert result.template.prompt_version == "1.0.0"
    assert result.template.content_hash.startswith("sha256:")
    assert re.search(r"(?i)\b(?:theta|se)\b", result.rendered_prompt.rendered_text) is None
    assert "theta" not in json.dumps(result.prompt_input, ensure_ascii=False).lower()
    assert ledger.current is OrchestrationStage.PROMPT_ASSEMBLED


def test_formal_path_uses_typed_projection_seam_and_preserves_prompt_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, binding, ledger, bundle = _prepared(BackendRole.STUDENT)
    _models, _adapter, _role_models, _role_projection, engine, _registry = (
        d3_chain_module._accepted_modules()
    )
    observed: list[Any] = []
    original_render_projected = engine.render_projected

    def fail_legacy_render(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("formal D3 chain must not call legacy engine.render")

    def capture_projected(*args: Any, **kwargs: Any) -> Any:
        projection = kwargs.get("projection")
        if projection is None and len(args) >= 6:
            projection = args[5]
        observed.append(projection)
        return original_render_projected(*args, **kwargs)

    monkeypatch.setattr(engine, "render", fail_legacy_render)
    monkeypatch.setattr(engine, "render_projected", capture_projected)

    result = compose_d3_chain(
        context,
        binding,
        ledger,
        bundle,
        generation_id="GEN_d3_typed_projection",
    )

    assert len(observed) == 1
    projection = observed[0]
    assert isinstance(projection, _role_models.PromptFacingProjection)
    assert projection is result.role_projection.prompt
    assert set(result.prompt_input) == {"status", "claims", "limitations", "citations"}
    assert result.prompt_input == projection.to_public_dict()


def test_d3int_43_projection_content_changes_prompt_with_same_bundle_and_template() -> None:
    context, binding, ledger, bundle = _prepared(BackendRole.STUDENT)
    result = compose_d3_chain(
        context,
        binding,
        ledger,
        bundle,
        generation_id="GEN_d3_projection_causality",
    )
    _models, _adapter, role_models, _role_projection, engine, registry = (
        d3_chain_module._accepted_modules()
    )
    original_projection = result.role_projection.prompt
    changed_projection = role_models._build_prompt_facing_projection(
        status=role_models.ProjectionStatus.READY_FOR_PROMPT,
        claims=original_projection.claims,
        limitations=("NOT_DIAGNOSTIC",),
        citations=original_projection.citations,
    )
    assert tuple(item.source_chunk_id for item in original_projection.citations) == bundle.chunk_ids
    assert tuple(item.source_chunk_id for item in changed_projection.citations) == bundle.chunk_ids

    assessment = d3_chain_module._assessment_projection(binding)
    changed_rendered, changed_template, _mapping = d3_chain_module._render(
        context=context,
        role="student",
        assessment=assessment,
        bundle=bundle,
        prompt_projection=changed_projection,
        generation_id="GEN_d3_projection_causality",
        input_safety_action="PROCEED",
        retrieval_safety_action="PROCEED",
        engine=engine,
        registry=registry,
    )

    assert changed_template == result.template
    assert changed_rendered.rendered_text != result.rendered_prompt.rendered_text
    assert changed_rendered.prompt_hash != result.rendered_prompt.prompt_hash


def test_d3_2_interpretation_is_one_use_and_reused_after_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, binding, ledger, bundle = _prepared(BackendRole.STUDENT)
    calls = 0
    original_interpret = d3_chain_module._interpret

    def counted_interpret(*args: Any, **kwargs: Any) -> tuple[Any, Any]:
        nonlocal calls
        calls += 1
        return original_interpret(*args, **kwargs)

    monkeypatch.setattr(d3_chain_module, "_interpret", counted_interpret)

    prepared = interpret_d3_chain(context, binding, ledger)
    assert ledger.current is OrchestrationStage.INTERPRETATION_READY

    result = compose_d3_chain(
        context,
        binding,
        ledger,
        bundle,
        generation_id="GEN_d3_two_phase",
        interpretation=prepared,
    )

    assert calls == 1
    assert result.interpretation is prepared.interpretation
    assert ledger.current is OrchestrationStage.PROMPT_ASSEMBLED
    assert [record.stage for record in ledger.records] == [
        OrchestrationStage.REQUEST_AUTHENTICATED,
        OrchestrationStage.REQUEST_AUTHORIZED,
        OrchestrationStage.INPUT_SAFETY_EVALUATED,
        OrchestrationStage.ASSESSMENT_BOUND,
        OrchestrationStage.INTERPRETATION_READY,
        OrchestrationStage.RETRIEVAL_BOUND,
        OrchestrationStage.ROLE_PROJECTED,
        OrchestrationStage.PROMPT_ASSEMBLED,
    ]

    with pytest.raises(D3ChainError) as caught:
        interpret_d3_chain(context, binding, ledger)
    assert caught.value.code == "STAGE_PRECONDITION"
    assert calls == 1


@pytest.mark.parametrize(
    ("role", "audience", "policy_id", "template_id"),
    [
        (
            BackendRole.TEACHER,
            "TEACHER_SUPPORT",
            "ROLE_PROJECTION_TEACHER_SUPPORT_V09",
            "PROMPT_teacher_synthetic_v1",
        ),
        (
            BackendRole.PARENT,
            "PARENT_DEMO",
            "ROLE_PROJECTION_PARENT_DEMO_V09",
            "PROMPT_parent_synthetic_demo_v1",
        ),
    ],
)
def test_teacher_and_parent_use_coarse_role_policies(
    role: BackendRole, audience: str, policy_id: str, template_id: str
) -> None:
    context, binding, ledger, bundle = _prepared(role)

    assert context.audience_role.value == audience
    with pytest.raises(D3ChainError) as caught:
        compose_d3_chain(
            context,
            binding,
            ledger,
            bundle,
            generation_id=f"GEN_d3_{role.value.lower()}",
        )
    # The accepted D3-3 policy deliberately emits the coarse denial envelope
    # for teacher/parent, so D3-1 is never reached.
    assert caught.value.code == "D3_3_NOT_READY"
    assert policy_id.startswith("ROLE_PROJECTION_")
    assert template_id.startswith("PROMPT_")
    assert ledger.current is OrchestrationStage.RETRIEVAL_BOUND


def test_admin_has_no_d3_psychology_prompt() -> None:
    context, binding, ledger, bundle = _prepared(BackendRole.ADMIN)

    with pytest.raises(D3ChainError) as caught:
        compose_d3_chain(
            context,
            binding,
            ledger,
            bundle,
            generation_id="GEN_d3_admin",
        )
    assert caught.value.code == "ROLE_NOT_ELIGIBLE"
    assert ledger.current is OrchestrationStage.ASSESSMENT_BOUND


def test_forged_plain_context_is_rejected_before_any_d3_call() -> None:
    context, binding, ledger, bundle = _prepared(BackendRole.STUDENT)

    with pytest.raises(D3ChainError) as caught:
        compose_d3_chain(
            cast(Any, context.to_dict()),
            binding,
            ledger,
            bundle,
            generation_id="GEN_d3_forged",
        )
    assert caught.value.code == "TRUSTED_CONTEXT_REQUIRED"


def test_legacy_identity_requires_explicit_versioned_fixture() -> None:
    assessment = _assessment()
    assessment["instrument"] = {
        "instrument_id": LEGACY_BACKEND_COMPATIBILITY_FIXTURE.source.instrument_id,
        "version": LEGACY_BACKEND_COMPATIBILITY_FIXTURE.source.instrument_version,
    }
    assessment["population_scope"] = LEGACY_BACKEND_COMPATIBILITY_FIXTURE.source.population_scope
    actor = _actor(BackendRole.STUDENT, assessment["subject_id"])
    record = AssessmentRecord(
        assessment_id=assessment["assessment_id"],
        subject_id=assessment["subject_id"],
        assessment=assessment,
    )
    with pytest.raises(AssessmentBindingError) as caught:
        bind_assessment(actor, record, assessment_id=assessment["assessment_id"])
    assert caught.value.code == "ASSESSMENT_COMPATIBILITY_REQUIRED"

    fixture = default_fixture_config().assessment_fixtures[0]
    binding = bind_assessment(
        actor,
        record,
        assessment_id=assessment["assessment_id"],
        compatibility_fixtures=(fixture,),
    )
    assert fixture.approved is True
    assert fixture.fixture_version
    assert binding.d3_identity == D3_IDENTITY
