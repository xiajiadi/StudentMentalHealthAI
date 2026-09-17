from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest

from prompt_engine import PromptRefusal, render, render_projected
from prompt_engine import engine as engine_module
from prompt_engine.contracts import (
    _repo_root,
    validate_assessment,
    validate_generation_request,
    validate_knowledge_chunk,
)
from prompt_engine.registry import TemplateRecord, resolve_policy, resolve_template
from prompt_engine.role_projection_models import (
    AuditProjection,
    ProjectionReasonCode,
    ProjectionStatus,
    PromptCitation,
    PromptFacingProjection,
    RoleProjectionResult,
    _build_prompt_facing_projection,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "00_architecture" / "fixtures"

POLICY_ID = "POLICY_synthetic_engineering_university_freshmen"
POLICY_VERSION = "1.0.0"
MAPPING_ID = "MAP_SYNTHETIC_DEMO_TO_UNIVERSITY_FRESHMEN_CONTENT_V1"
CONTENT_POPULATION = "UNIVERSITY_FRESHMEN_SYNTHETIC_DEMO"
ASSESSMENT_POPULATION = "SYNTHETIC_STUDENT_DEMO"
INSTRUMENT_ID = "CURRENT_SYNTHETIC_GRM"
INSTRUMENT_VERSION = "synthetic_item_bank.v1 / demo.v1"

PROMPT_IDS = {
    "student": "PROMPT_student_synthetic_v1",
    "teacher": "PROMPT_teacher_synthetic_v1",
    "parent": "PROMPT_parent_synthetic_demo_v1",
}

EXPECTED_TEMPLATE_HASHES = {
    "student": "sha256:8f821afbcbe53b4741982ac9cac02961151ab1b2f15b2fdb2786e5707baa237e",
    "teacher": "sha256:51eedb7fb436474eb5ee6b141df66db12cd3230254948b637ffff6639e0dacb0",
    "parent": "sha256:6297d629b7e2f1a124dd5950e111177d2515999a15d755830aae4f20b5d0f528",
}


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def d3_case():
    """Build D3 synthetic inputs from the repository's frozen fixtures."""

    def build(role: str = "student") -> dict:
        if role not in PROMPT_IDS:
            raise ValueError(role)
        assessment = _load_fixture("valid_assessment.json")
        assessment["instrument"] = {
            "instrument_id": INSTRUMENT_ID,
            "version": INSTRUMENT_VERSION,
        }
        assessment["population_scope"] = ASSESSMENT_POPULATION
        assessment["assessment_id"] = "ASSESS_d3_001"
        assessment["subject_id"] = "SUBJ_d3_001"
        assessment["provenance"]["item_bank_version"] = "synthetic_item_bank.v1"

        request = _load_fixture("valid_generation_request.json")
        request["generation_id"] = "GEN_d3_001"
        request["assessment_id"] = assessment["assessment_id"]
        request["subject_id"] = assessment["subject_id"]
        request["target_role"] = role
        request["prompt_ref"] = {
            "prompt_id": PROMPT_IDS[role],
            "prompt_version": "1.0.0",
        }
        request["retrieval"]["chunk_ids"] = ["CHUNK_d3_001"]

        chunk = _load_fixture("valid_knowledge_chunk.json")
        chunk["chunk_id"] = "CHUNK_d3_001"
        chunk["document_id"] = "KB_d3_001"
        chunk["text"] = "approved synthetic education-support excerpt"
        chunk["population_scope"] = [CONTENT_POPULATION]
        chunk["role_scope"] = ["student", "teacher", "parent"]
        chunk["risk_scope"] = ["normal", "attention"]
        chunk["citation"]["locator"] = "section:d3-fixture"

        case = {
            "assessment": assessment,
            "request": request,
            "chunks": [chunk],
            "policy_ref": {
                "policy_id": POLICY_ID,
                "policy_version": POLICY_VERSION,
                "mapping_id": MAPPING_ID,
                "mapping_version": "1.0.0",
            },
            "context": {
                "request_id": "REQ_d3_001",
                "trace_id": "TRACE_d3_001",
                "execution_mode": "synthetic_demo",
                "content_population": CONTENT_POPULATION,
                "input_safety_action": "PROCEED",
                "retrieval_safety_action": "PROCEED",
            },
        }
        case["trusted_context"] = engine_module._build_trusted_prompt_context(
            case["context"], case["assessment"], case["chunks"]
        )
        return case

    return build


def _render(case: dict):
    return render(
        case["assessment"],
        case["request"],
        case["chunks"],
        case["policy_ref"],
        case["trusted_context"],
    )


def _rebuild_trusted_context(case: dict) -> None:
    case["trusted_context"] = engine_module._build_trusted_prompt_context(
        case["context"], case["assessment"], case["chunks"]
    )


def _trusted_variant(
    case: dict,
    *,
    context_updates: dict | None = None,
    assessment_updates: dict | None = None,
    chunk_updates: dict | None = None,
):
    context = copy.deepcopy(case["context"])
    assessment = copy.deepcopy(case["assessment"])
    chunks = copy.deepcopy(case["chunks"])
    if context_updates:
        context.update(context_updates)
    if assessment_updates:
        assessment.update(assessment_updates)
    if chunk_updates:
        chunks[0].update(chunk_updates)
    return engine_module._build_trusted_prompt_context(context, assessment, chunks)


def _assert_refusal(call, reason_code: str) -> None:
    with pytest.raises(PromptRefusal) as caught:
        call()
    assert caught.value.reason_code == reason_code


def _ready_projection(case: dict, *, limitations: tuple[str, ...] = ()):
    return _build_prompt_facing_projection(
        status=ProjectionStatus.READY_FOR_PROMPT,
        limitations=limitations,
        citations=(
            PromptCitation(
                case["chunks"][0]["chunk_id"],
                case["chunks"][0]["citation"]["locator"],
            ),
        ),
    )


def _render_projected(case: dict, projection):
    return render_projected(
        case["assessment"],
        case["request"],
        case["chunks"],
        case["policy_ref"],
        case["trusted_context"],
        projection,
    )


@pytest.mark.parametrize("role", ["student", "teacher", "parent"])
def test_three_roles_render_with_real_frozen_inputs(d3_case, role):
    case = d3_case(role)
    result = _render(case)

    assert result.generation_request == case["request"]
    assert f"the target role is {role}" in result.rendered_text.lower()
    assert "CHUNK_d3_001" in result.rendered_text
    assert result.audit["target_role"] == role
    assert result.audit["workflow_outcome"] == "PROMPT_RENDERED"
    assert result.prompt_hash.startswith("sha256:")
    rendered_lower = result.rendered_text.lower()
    assert '"theta"' not in rendered_lower
    assert '"se"' not in rendered_lower
    assert '"band"' not in rendered_lower
    assert all(term not in result.audit for term in ("theta", "se", "band"))


def test_template_hashes_are_stable_lf_utf8_and_resolve_exactly():
    for role, prompt_id in PROMPT_IDS.items():
        record = resolve_template(prompt_id, "1.0.0", role)
        assert record.content_hash == EXPECTED_TEMPLATE_HASHES[role]
        assert (
            record.content_hash
            == "sha256:" + hashlib.sha256(record.template_text.encode("utf-8")).hexdigest()
        )
        assert "PLACEHOLDER" not in record.content_hash
        assert "\r" not in record.template_text
        assert record.template_text.encode("utf-8")


def test_frozen_contract_schema_validation_and_repo_root(d3_case):
    case = d3_case("teacher")

    assert _repo_root() == ROOT
    validate_assessment(case["assessment"])
    validate_generation_request(case["request"])
    validate_knowledge_chunk(case["chunks"][0])


def test_render_is_deterministic_and_does_not_mutate_inputs(d3_case):
    case = d3_case("student")
    before = copy.deepcopy(case)

    first = _render(case)
    second = _render(case)

    assert first.rendered_text == second.rendered_text
    assert first.prompt_hash == second.prompt_hash
    assert first.audit == second.audit
    assert case == before
    first.generation_request["target_role"] = "parent"
    assert case["request"]["target_role"] == "student"


def test_render_projected_uses_only_public_projection_and_changes_causally(d3_case):
    case = d3_case("student")
    before = copy.deepcopy(case)
    legacy = _render(case)
    projection = _ready_projection(case, limitations=("SYNTHETIC_ONLY",))

    projected = _render_projected(case, projection)

    assert case == before
    assert projected.rendered_text != legacy.rendered_text
    assert projected.prompt_hash != legacy.prompt_hash
    assert '"prompt_projection"' in projected.rendered_text
    assert '"status":"READY_FOR_PROMPT"' in projected.rendered_text
    assert '"limitations":["SYNTHETIC_ONLY"]' in projected.rendered_text
    assert '"source_chunk_id":"CHUNK_d3_001"' in projected.rendered_text
    assert case["policy_ref"]["policy_id"] not in projected.rendered_text
    assert "policy_hash" not in projected.rendered_text
    assert "review_decision_id" not in projected.rendered_text
    assert '"theta"' not in projected.rendered_text.lower()
    assert '"se"' not in projected.rendered_text.lower()


def test_render_projected_causal_envelope_difference_is_observable(d3_case):
    case = d3_case("student")
    first = _render_projected(case, _ready_projection(case, limitations=("SYNTHETIC_ONLY",)))
    second = _render_projected(case, _ready_projection(case, limitations=("NOT_DIAGNOSTIC",)))

    assert first.rendered_text != second.rendered_text
    assert first.prompt_hash != second.prompt_hash


def test_projected_path_preserves_legacy_render_and_template_hashes(d3_case):
    case = d3_case("teacher")
    legacy_before = _render(case)
    template_before = resolve_template("PROMPT_teacher_synthetic_v1", "1.0.0", "teacher")

    _render_projected(case, _ready_projection(case, limitations=("SYNTHETIC_ONLY",)))

    legacy_after = _render(case)
    template_after = resolve_template("PROMPT_teacher_synthetic_v1", "1.0.0", "teacher")
    assert legacy_after.rendered_text == legacy_before.rendered_text
    assert legacy_after.prompt_hash == legacy_before.prompt_hash
    assert template_after.content_hash == template_before.content_hash
    assert template_after.template_text == template_before.template_text


def test_render_projected_rejects_non_projection_and_denial_surfaces(d3_case):
    case = d3_case("student")
    denial = _build_prompt_facing_projection(status=ProjectionStatus.NO_PERSONALIZED_DISCLOSURE)
    audit = AuditProjection(
        status=ProjectionStatus.NO_PERSONALIZED_DISCLOSURE,
        reason_codes=(ProjectionReasonCode.NO_PERSONALIZED_DISCLOSURE,),
    )
    combined = RoleProjectionResult(
        status=ProjectionStatus.NO_PERSONALIZED_DISCLOSURE,
        prompt=denial,
        audit=audit,
    )
    forged = object.__new__(PromptFacingProjection)
    object.__setattr__(forged, "status", ProjectionStatus.READY_FOR_PROMPT)
    object.__setattr__(forged, "claims", ())
    object.__setattr__(forged, "limitations", ())
    object.__setattr__(forged, "citations", ())
    object.__setattr__(forged, "_capability", None)

    for value, reason in (
        ({"status": "READY_FOR_PROMPT"}, "PROMPT_FACING_PROJECTION_REQUIRED"),
        (audit, "PROMPT_FACING_PROJECTION_REQUIRED"),
        (combined, "PROMPT_FACING_PROJECTION_REQUIRED"),
        (forged, "PROMPT_FACING_PROJECTION_REQUIRED"),
        (denial, "PROMPT_PROJECTION_NOT_READY"),
    ):
        _assert_refusal(
            lambda value=value: _render_projected(case, cast(Any, value)),
            reason,
        )


@pytest.mark.parametrize(
    ("citation", "reason"),
    [
        (
            PromptCitation("CHUNK_unknown", "section:d3-fixture"),
            "PROMPT_PROJECTION_CITATIONS_MISMATCH",
        ),
        (PromptCitation("CHUNK_d3_001", "section:foreign"), "TRUSTED_CONTEXT_MISMATCH"),
    ],
)
def test_render_projected_rejects_unknown_or_cross_bundle_citations(d3_case, citation, reason):
    case = d3_case("student")
    projection = _build_prompt_facing_projection(
        status=ProjectionStatus.READY_FOR_PROMPT,
        citations=(citation,),
    )

    _assert_refusal(lambda: _render_projected(case, projection), reason)


def test_render_projected_rejects_duplicate_and_reordered_citations(d3_case):
    case = d3_case("student")
    second = copy.deepcopy(case["chunks"][0])
    second["chunk_id"] = "CHUNK_d3_002"
    second["document_id"] = "KB_d3_002"
    second["citation"]["locator"] = "section:d3-fixture-2"
    case["request"]["retrieval"]["chunk_ids"] = ["CHUNK_d3_001", "CHUNK_d3_002"]
    case["chunks"].append(second)
    _rebuild_trusted_context(case)

    duplicate = _build_prompt_facing_projection(
        status=ProjectionStatus.READY_FOR_PROMPT,
        citations=(
            PromptCitation("CHUNK_d3_001", "section:d3-fixture"),
            PromptCitation("CHUNK_d3_001", "section:d3-fixture"),
        ),
    )
    reordered = _build_prompt_facing_projection(
        status=ProjectionStatus.READY_FOR_PROMPT,
        citations=(
            PromptCitation("CHUNK_d3_002", "section:d3-fixture-2"),
            PromptCitation("CHUNK_d3_001", "section:d3-fixture"),
        ),
    )

    _assert_refusal(
        lambda: _render_projected(case, duplicate),
        "PROMPT_PROJECTION_CITATIONS_INVALID",
    )
    _assert_refusal(
        lambda: _render_projected(case, reordered),
        "PROMPT_PROJECTION_CITATIONS_MISMATCH",
    )


def test_boundary_safety_action_is_allowed(d3_case):
    case = d3_case("teacher")
    case["context"]["input_safety_action"] = "PROCEED_WITH_BOUNDARY"
    case["context"]["retrieval_safety_action"] = "PROCEED_WITH_BOUNDARY"
    _rebuild_trusted_context(case)

    result = _render(case)

    assert result.audit["input_safety_action"] == "PROCEED_WITH_BOUNDARY"
    assert result.audit["retrieval_safety_action"] == "PROCEED_WITH_BOUNDARY"


@pytest.mark.parametrize(
    ("prompt_id", "prompt_version", "role", "reason"),
    [
        ("PROMPT_unknown", "1.0.0", "student", "TEMPLATE_NOT_FOUND"),
        ("PROMPT_student_synthetic_v1", "9.9.9", "student", "TEMPLATE_NOT_FOUND"),
        ("PROMPT_student_synthetic_v1", "1.0.0", "teacher", "TEMPLATE_ROLE_MISMATCH"),
    ],
)
def test_unknown_template_version_or_role_refuses(d3_case, prompt_id, prompt_version, role, reason):
    case = d3_case("student")
    case["request"]["prompt_ref"] = {
        "prompt_id": prompt_id,
        "prompt_version": prompt_version,
    }
    case["request"]["target_role"] = role

    _assert_refusal(lambda: _render(case), reason)


def test_inactive_policy_and_unknown_policy_refuse(d3_case):
    case = d3_case("student")
    case["policy_ref"] = {"policy_id": "FUTURE_DIRECTION_CANDIDATE", "policy_version": "1.0.0"}
    _assert_refusal(lambda: _render(case), "POLICY_NOT_ACTIVE")

    case["policy_ref"] = {"policy_id": "POLICY_unknown", "policy_version": "1.0.0"}
    _assert_refusal(lambda: _render(case), "POLICY_NOT_FOUND")


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("execution_mode", "real", "EXECUTION_MODE_NOT_ALLOWED"),
        ("content_population", "K12_STUDENT", "POLICY_CONTENT_POPULATION_MISMATCH"),
        ("input_safety_action", "BLOCK", "INPUT_SAFETY_ACTION_REJECTED"),
        ("retrieval_safety_action", "CRISIS", "RETRIEVAL_SAFETY_ACTION_REJECTED"),
        ("retrieval_safety_action", "UNKNOWN", "RETRIEVAL_SAFETY_ACTION_REJECTED"),
    ],
)
def test_context_scope_and_non_proceed_safety_are_fail_closed(d3_case, field, value, reason):
    case = d3_case("student")
    case["context"][field] = value
    _rebuild_trusted_context(case)

    _assert_refusal(lambda: _render(case), reason)


def test_raw_mapping_cannot_supply_trusted_context(d3_case):
    case = d3_case("student")
    _assert_refusal(
        lambda: render(
            case["assessment"],
            case["request"],
            case["chunks"],
            case["policy_ref"],
            case["context"],
        ),
        "TRUSTED_CONTEXT_REQUIRED",
    )


def test_caller_forged_review_state_cannot_override_trusted_pending(d3_case):
    case = d3_case("student")
    case["trusted_context"] = _trusted_variant(case, chunk_updates={"review_status": "pending"})
    case["chunks"][0]["review_status"] = "approved"
    _assert_refusal(lambda: _render(case), "TRUSTED_CONTEXT_MISMATCH")


def test_caller_forged_rights_state_cannot_override_trusted_unknown(d3_case):
    case = d3_case("student")
    case["trusted_context"] = _trusted_variant(case, chunk_updates={"rights_status": "unknown"})
    case["chunks"][0]["rights_status"] = "verified"
    _assert_refusal(lambda: _render(case), "TRUSTED_CONTEXT_MISMATCH")


def test_caller_safety_action_cannot_override_trusted_crisis_route(d3_case):
    case = d3_case("student")
    case["trusted_context"] = _trusted_variant(
        case,
        context_updates={
            "input_safety_action": "CRISIS_ROUTE",
            "retrieval_safety_action": "CRISIS_ROUTE",
        },
    )
    case["context"]["input_safety_action"] = "PROCEED"
    case["context"]["retrieval_safety_action"] = "PROCEED"
    _assert_refusal(lambda: _render(case), "INPUT_SAFETY_ACTION_REJECTED")


def test_caller_risk_state_cannot_override_trusted_review_required(d3_case):
    case = d3_case("student")
    trusted_assessment = copy.deepcopy(case["assessment"])
    trusted_assessment["risk"]["level"] = "high"
    trusted_assessment["risk"]["need_human_review"] = True
    case["trusted_context"] = engine_module._build_trusted_prompt_context(
        case["context"], trusted_assessment, case["chunks"]
    )
    case["assessment"]["risk"]["level"] = "normal"
    case["assessment"]["risk"]["need_human_review"] = False
    _assert_refusal(lambda: _render(case), "TRUSTED_CONTEXT_MISMATCH")


def test_caller_synthetic_claim_without_trusted_context_refuses(d3_case):
    case = d3_case("student")
    _assert_refusal(
        lambda: render(
            case["assessment"],
            case["request"],
            case["chunks"],
            case["policy_ref"],
            cast(Any, {**case["context"], "execution_mode": "synthetic_demo"}),
        ),
        "TRUSTED_CONTEXT_REQUIRED",
    )


def test_caller_population_claim_cannot_override_trusted_scope(d3_case):
    case = d3_case("student")
    case["trusted_context"] = _trusted_variant(
        case, context_updates={"content_population": "K12_STUDENT"}
    )
    _assert_refusal(lambda: _render(case), "POLICY_CONTENT_POPULATION_MISMATCH")


def test_caller_scope_mapping_cannot_override_trusted_eligibility(d3_case):
    case = d3_case("student")
    case["trusted_context"] = _trusted_variant(case, chunk_updates={"role_scope": ["teacher"]})
    _assert_refusal(lambda: _render(case), "TRUSTED_CONTEXT_MISMATCH")


def test_policy_instrument_version_is_exact_and_not_any_version(d3_case):
    case = d3_case("student")
    case["assessment"]["instrument"]["version"] = "1.0.0"

    _assert_refusal(lambda: _render(case), "POLICY_INSTRUMENT_MISMATCH")


def test_policy_assessment_population_and_untrusted_policy_fields_refuse(d3_case):
    case = d3_case("student")
    case["assessment"]["population_scope"] = "demo_population"
    _rebuild_trusted_context(case)
    _assert_refusal(lambda: _render(case), "POLICY_ASSESSMENT_POPULATION_MISMATCH")

    case = d3_case("student")
    case["policy_ref"]["approved"] = True
    _assert_refusal(lambda: _render(case), "POLICY_REF_INVALID")


def test_role_language_and_parent_delivery_scope_are_exact(d3_case):
    case = d3_case("student")
    case["request"]["target_role"] = "admin"
    _assert_refusal(lambda: _render(case), "POLICY_MAPPING_MISMATCH")

    case = d3_case("student")
    case["request"]["language"] = "en-US"
    _assert_refusal(lambda: _render(case), "TEMPLATE_REQUEST_SCOPE_MISMATCH")

    case = d3_case("parent")
    case["context"]["execution_mode"] = "real"
    _rebuild_trusted_context(case)
    _assert_refusal(lambda: _render(case), "EXECUTION_MODE_NOT_ALLOWED")


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda case: case["assessment"].update(status="in_progress"), "ASSESSMENT_NOT_COMPLETED"),
        (
            lambda case: case["assessment"].update(assessment_id="ASSESS_other"),
            "ASSESSMENT_ID_MISMATCH",
        ),
        (lambda case: case["assessment"].update(subject_id="SUBJ_other"), "SUBJECT_ID_MISMATCH"),
        (lambda case: case.update(trusted_context=case["context"]), "TRUSTED_CONTEXT_REQUIRED"),
    ],
)
def test_assessment_cross_id_and_context_boundaries(d3_case, mutation, reason):
    case = d3_case("student")
    mutation(case)

    _assert_refusal(lambda: _render(case), reason)


@pytest.mark.parametrize("risk_level", ["high", "crisis"])
def test_high_and_crisis_assessments_never_render(d3_case, risk_level):
    case = d3_case("student")
    case["assessment"]["risk"]["level"] = risk_level
    case["assessment"]["risk"]["need_human_review"] = True
    _rebuild_trusted_context(case)

    _assert_refusal(lambda: _render(case), "ASSESSMENT_REVIEW_REQUIRED")


def test_attention_assessment_marked_for_review_never_renders(d3_case):
    case = d3_case("student")
    case["assessment"]["risk"]["need_human_review"] = True
    _rebuild_trusted_context(case)

    _assert_refusal(lambda: _render(case), "ASSESSMENT_REVIEW_REQUIRED")


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda chunk: chunk.update(review_status="pending"), "RETRIEVAL_CHUNK_NOT_ELIGIBLE"),
        (lambda chunk: chunk.update(rights_status="unknown"), "RETRIEVAL_CHUNK_NOT_ELIGIBLE"),
        (lambda chunk: chunk["citation"].update(locator="   "), "RETRIEVAL_CHUNK_NOT_ELIGIBLE"),
        (lambda chunk: chunk["citation"].pop("locator"), "KNOWLEDGE_CHUNK_SCHEMA_INVALID"),
    ],
)
def test_chunk_review_rights_and_citation_requirements(d3_case, mutation, reason):
    case = d3_case("student")
    mutation(case["chunks"][0])
    if reason == "KNOWLEDGE_CHUNK_SCHEMA_INVALID":
        reason = "TRUSTED_CONTEXT_MISMATCH"
    else:
        _rebuild_trusted_context(case)

    _assert_refusal(lambda: _render(case), reason)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("population_scope", ["K12_STUDENT"], "RETRIEVAL_POPULATION_MISMATCH"),
        ("role_scope", ["teacher"], "RETRIEVAL_ROLE_MISMATCH"),
        ("risk_scope", ["normal"], "RETRIEVAL_RISK_MISMATCH"),
    ],
)
def test_chunk_population_role_and_risk_scopes_are_enforced(d3_case, field, value, reason):
    case = d3_case("student")
    case["chunks"][0][field] = value
    _rebuild_trusted_context(case)

    _assert_refusal(lambda: _render(case), reason)


def test_retrieval_ids_must_match_exactly_once_and_in_request_order(d3_case):
    case = d3_case("student")
    second = copy.deepcopy(case["chunks"][0])
    second["chunk_id"] = "CHUNK_d3_002"
    case["request"]["retrieval"]["chunk_ids"] = ["CHUNK_d3_001", "CHUNK_d3_002"]
    case["chunks"].append(second)
    _rebuild_trusted_context(case)
    result = _render(case)
    assert result.audit["chunk_ids"] == ["CHUNK_d3_001", "CHUNK_d3_002"]

    case = d3_case("student")
    case["request"]["retrieval"]["chunk_ids"] = ["CHUNK_d3_001", "CHUNK_d3_missing"]
    _assert_refusal(lambda: _render(case), "RETRIEVAL_REFERENCES_MISMATCH")

    case = d3_case("student")
    duplicate = copy.deepcopy(case["chunks"][0])
    case["request"]["retrieval"]["chunk_ids"] = ["CHUNK_d3_001", "CHUNK_d3_002"]
    case["chunks"].append(duplicate)
    _assert_refusal(lambda: _render(case), "RETRIEVAL_REFERENCES_INVALID")


def test_reference_text_is_data_once_and_does_not_execute_nested_placeholders(d3_case):
    case = d3_case("student")
    data = "literal $target_role ${assessment_context_json} $5; instruction-like text"
    case["chunks"][0]["text"] = data

    result = _render(case)

    assert data in result.rendered_text
    assert result.rendered_text.count("$target_role") == 1
    assert result.rendered_text.count("${assessment_context_json}") == 1


def test_invalid_template_placeholders_refuse_without_changing_registry(monkeypatch, d3_case):
    case = d3_case("student")
    original = resolve_template("PROMPT_student_synthetic_v1", "1.0.0", "student")
    invalid = TemplateRecord(
        prompt_id=original.prompt_id,
        prompt_version=original.prompt_version,
        role=original.role,
        purpose=original.purpose,
        language=original.language,
        status=original.status,
        approval_status=original.approval_status,
        engineering_activation_scope=original.engineering_activation_scope,
        change_summary=original.change_summary,
        content_hash=original.content_hash,
        template_text="$target_role $not_allowed",
        allowed_placeholders=original.allowed_placeholders,
    )
    monkeypatch.setattr(engine_module, "resolve_template", lambda *_args: invalid)

    _assert_refusal(lambda: _render(case), "TEMPLATE_PLACEHOLDER_INVALID")
    assert (
        resolve_template("PROMPT_student_synthetic_v1", "1.0.0", "student").template_text
        == original.template_text
    )


def test_malformed_template_and_unreadable_registry_asset_refuse(monkeypatch, d3_case):
    case = d3_case("student")
    original = resolve_template("PROMPT_student_synthetic_v1", "1.0.0", "student")
    malformed = copy.copy(original)
    monkeypatch.setattr(
        engine_module,
        "resolve_template",
        lambda *_args: TemplateRecord(
            prompt_id=malformed.prompt_id,
            prompt_version=malformed.prompt_version,
            role=malformed.role,
            purpose=malformed.purpose,
            language=malformed.language,
            status=malformed.status,
            approval_status=malformed.approval_status,
            engineering_activation_scope=malformed.engineering_activation_scope,
            change_summary=malformed.change_summary,
            content_hash=malformed.content_hash,
            template_text="$",
            allowed_placeholders=malformed.allowed_placeholders,
        ),
    )

    _assert_refusal(lambda: _render(case), "TEMPLATE_INVALID")


def test_refusal_does_not_leak_input_body_or_fabricate_result(d3_case):
    case = d3_case("student")
    secret = "PRIVATE_SYNTHETIC_BODY_7f62f"
    case["chunks"][0]["text"] = secret
    case["chunks"][0]["review_status"] = "pending"

    with pytest.raises(PromptRefusal) as caught:
        _render(case)

    assert caught.value.reason_code == "TRUSTED_CONTEXT_MISMATCH"
    assert secret not in str(caught.value)


def test_untrusted_arbitrary_registry_path_is_not_an_api_option():
    with pytest.raises(TypeError):
        cast(Any, resolve_template)(
            "PROMPT_student_synthetic_v1", "1.0.0", "student", "C:\\secret.txt"
        )


def test_policy_registry_is_read_only_and_exact():
    policy = resolve_policy(POLICY_ID, POLICY_VERSION)
    assert policy["intended_use"] == "synthetic_engineering_only"
    assert policy["real_population_allowed"] is False
    assert policy["instrument_allowlist"][0]["versions"] == [INSTRUMENT_VERSION]
    assert policy["roles"] == ["student", "teacher", "parent"]
