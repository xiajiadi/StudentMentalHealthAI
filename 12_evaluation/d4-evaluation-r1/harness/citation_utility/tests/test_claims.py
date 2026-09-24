from __future__ import annotations

import sys
from pathlib import Path

import pytest

D4_ROOT = Path(__file__).resolve().parents[3]
if str(D4_ROOT) not in sys.path:
    sys.path.insert(0, str(D4_ROOT))

from harness.citation_utility.claims import (
    APPLICABILITY_STATUSES,
    CLAIM_TYPES,
    DATA_CLASSIFICATION,
    REVIEW_STATES,
    SUPPORT_LABELS,
    Applicability,
    ReviewMetadata,
    append_transformation,
    build_case_record,
    build_claim_record,
    check_citation_identity,
    citation_requirement_for,
    derive_support_label,
    is_human_gold_review,
    mark_claim_excluded,
    validate_claim_record,
)

ANSWER = "保持相对规律的作息，有助于大学新生安排日常学习。"


def _applicable(reason: str = "合成教育证据与目标范围一致") -> Applicability:
    return Applicability(
        "APPLICABLE",
        reason,
        expected_scope="university_freshman/student/education_support",
        evidence_scope=("university_freshman", "student", "education_support"),
    )


def _claim(**overrides):
    values = {
        "claim_id": "CLM_TEST_001",
        "case_id": "D4SUP-TEST-DIRECT",
        "original_answer": ANSWER,
        "span_start": 0,
        "span_end": len(ANSWER),
        "text": ANSWER,
        "claim_type": "FACTUAL_VERIFIABLE",
        "cited_chunk_ids": ("CHUNK_SYNTH_001",),
        "textual_entailment": "SUPPORTS",
        "population_applicability": _applicable(),
        "role_applicability": _applicable(),
        "purpose_applicability": _applicable(),
    }
    values.update(overrides)
    return build_claim_record(**values)


def test_fixed_enums_and_explicit_citation_policy_are_stable():
    assert SUPPORT_LABELS == (
        "SUPPORTS",
        "PARTIALLY_SUPPORTS",
        "UNSUPPORTED",
        "CONTRADICTS",
        "OUT_OF_SCOPE",
    )
    assert CLAIM_TYPES == (
        "FACTUAL_VERIFIABLE",
        "EVIDENCE_GROUNDED_ACTION",
        "SCOPE_LIMITATION",
        "CONVERSATIONAL_GLUE",
    )
    assert REVIEW_STATES == (
        "DRAFT",
        "HUMAN_REVIEW_REQUIRED",
        "HUMAN_APPROVED",
        "HUMAN_REJECTED",
        "DISPUTED",
    )
    assert set(APPLICABILITY_STATUSES) == {"APPLICABLE", "MISMATCH", "UNKNOWN"}
    factual_policy = citation_requirement_for("FACTUAL_VERIFIABLE")
    glue_policy = citation_requirement_for("CONVERSATIONAL_GLUE")
    assert factual_policy["required"] is True
    assert factual_policy["reason"]
    assert glue_policy["required"] is False
    assert glue_policy["reason"]


def test_scope_claims_can_explicitly_require_or_skip_citation():
    ordinary_boundary = citation_requirement_for("SCOPE_LIMITATION")
    assert ordinary_boundary["required"] is False
    required_boundary = citation_requirement_for(
        "SCOPE_LIMITATION",
        required=True,
        policy_id="TEST_SOURCE_DEPENDENT_SCOPE_REQUIRED",
        reason="范围结论依赖合成证据卡的适用范围。",
    )
    assert required_boundary == {
        "required": True,
        "policy_id": "TEST_SOURCE_DEPENDENT_SCOPE_REQUIRED",
        "reason": "范围结论依赖合成证据卡的适用范围。",
    }
    with pytest.raises(ValueError, match="policy_id"):
        citation_requirement_for(
            "SCOPE_LIMITATION",
            required=True,
            reason="缺少稳定 policy ID。",
        )


def test_direct_claim_preserves_answer_span_and_hash():
    claim = _claim()
    value = claim.to_dict()
    assert value["original_answer"] == ANSWER
    assert value["text"] == ANSWER
    assert value["answer_span"] == {
        "start": 0,
        "end": len(ANSWER),
        "end_inclusive": False,
        "unit": "python_codepoint",
    }
    assert value["support_label"] == "SUPPORTS"
    assert value["textual_entailment"] == "SUPPORTS"
    assert tuple(value["data_classification"]) == DATA_CLASSIFICATION
    assert claim.content_hash == validate_claim_record(value).content_hash


def test_valid_citation_identity_does_not_auto_support_a_claim():
    claim = _claim(
        textual_entailment="UNSUPPORTED",
        support_label="UNSUPPORTED",
    )
    assert claim.cited_chunk_ids == ("CHUNK_SYNTH_001",)
    assert claim.textual_entailment == "UNSUPPORTED"
    assert claim.support_label == "UNSUPPORTED"


def test_citation_identity_is_separate_from_textual_entailment():
    evidence = {
        "chunk_id": "CHUNK_SYNTH_001",
        "document_id": "DOC_SYNTH_001",
        "citation_id": "CIT_SYNTH_001",
        "source_title": "合成教育支持证据卡",
        "source_organization": "D4 Synthetic Evaluation Fixture",
        "locator": "synthetic://d4/citation-support/CIT_SYNTH_001",
        "text": "规律作息是学习安排中可以讨论的一般因素。",
        "population_scope": ["university_freshman"],
        "role_scope": ["student"],
        "purpose_scope": ["education_support"],
    }
    unsupported = _claim(
        textual_entailment="UNSUPPORTED",
        support_label="UNSUPPORTED",
    )
    valid_identity = check_citation_identity(unsupported, [evidence])
    assert valid_identity.status == "VALID"
    assert valid_identity.provenance_complete is True
    assert valid_identity.valid_chunk_ids == ("CHUNK_SYNTH_001",)
    assert unsupported.support_label == "UNSUPPORTED"

    fabricated = _claim(
        cited_chunk_ids=("CHUNK_UNKNOWN",),
        textual_entailment="UNSUPPORTED",
        support_label="UNSUPPORTED",
    )
    unknown_identity = check_citation_identity(fabricated, [evidence])
    assert unknown_identity.status == "UNKNOWN"
    assert unknown_identity.unknown_chunk_ids == ("CHUNK_UNKNOWN",)
    assert unknown_identity.provenance_complete is False
    assert fabricated.support_label == "UNSUPPORTED"


def test_evidence_cards_cannot_claim_human_approval_without_provenance():
    claim = _claim()
    card = {
        "chunk_id": "CHUNK_SYNTH_001",
        "document_id": "DOC_SYNTH_001",
        "citation_id": "CIT_SYNTH_001",
        "source_title": "合成教育支持证据卡",
        "source_organization": "D4 Synthetic Evaluation Fixture",
        "locator": "synthetic://d4/citation-support/CIT_SYNTH_001",
        "text": "规律作息是学习安排中可以讨论的一般因素。",
        "population_scope": ["university_freshman"],
        "role_scope": ["student"],
        "purpose_scope": ["education_support"],
        "review_state": "HUMAN_APPROVED",
    }
    with pytest.raises(ValueError, match="evidence cards require"):
        build_case_record(
            case_id=claim.case_id,
            original_answer=claim.original_answer,
            target_population="university_freshman",
            target_role="student",
            target_purpose="education_support",
            claims=[claim],
            evidence=[card],
        )


def test_out_of_scope_does_not_erase_textual_entailment():
    population_mismatch = Applicability(
        "MISMATCH",
        "证据覆盖中小学生，目标案例是大学新生。",
        expected_scope="university_freshman",
        evidence_scope=("k12",),
    )
    label = derive_support_label(
        "SUPPORTS",
        population=population_mismatch,
        role=_applicable(),
        purpose=_applicable(),
    )
    assert label == "OUT_OF_SCOPE"
    claim = _claim(
        population_applicability=population_mismatch,
        support_label="OUT_OF_SCOPE",
    )
    assert claim.textual_entailment == "SUPPORTS"
    assert claim.support_label == "OUT_OF_SCOPE"
    assert claim.population_applicability.status == "MISMATCH"


@pytest.mark.parametrize(
    ("field", "mismatch"),
    [
        (
            "role_applicability",
            Applicability("MISMATCH", "证据面向学生自助，当前请求要求教师执行。"),
        ),
        (
            "purpose_applicability",
            Applicability("MISMATCH", "证据用于教育支持，当前请求要求用于评分。"),
        ),
    ],
)
def test_role_and_purpose_mismatch_are_independent(field, mismatch):
    claim = _claim(**{field: mismatch}, support_label="OUT_OF_SCOPE")
    assert claim.textual_entailment == "SUPPORTS"
    assert claim.support_label == "OUT_OF_SCOPE"


def test_partial_unsupported_and_contradiction_labels_are_exact():
    partial = _claim(
        textual_entailment="PARTIALLY_SUPPORTS", support_label="PARTIALLY_SUPPORTS"
    )
    assert partial.support_label == "PARTIALLY_SUPPORTS"
    unsupported = _claim(textual_entailment="UNSUPPORTED", support_label="UNSUPPORTED")
    assert unsupported.support_label == "UNSUPPORTED"
    contradiction = _claim(
        textual_entailment="CONTRADICTS",
        support_label="CONTRADICTS",
        contradiction_reason="证据说明该说法会造成相反方向的学习安排影响。",
    )
    assert contradiction.contradiction_flag is True
    assert contradiction.to_dict()["contradiction"]["flag"] is True


def test_invalid_support_label_is_rejected():
    with pytest.raises(ValueError, match="support_label"):
        _claim(support_label="INVALID_LABEL")


def test_review_boundary_rejects_unverifiable_approval_and_excludes_simulation_from_gold():
    with pytest.raises(ValueError, match="reviewer_id"):
        ReviewMetadata(state="HUMAN_APPROVED", decision_source="HUMAN_REVIEWER")
    simulated = ReviewMetadata(
        state="HUMAN_APPROVED",
        decision_source="TEST_SIMULATION",
        simulated_outcome="TEST_FIXTURE_SIMULATED_APPROVAL",
    )
    assert simulated.is_test_only is True
    assert simulated.is_human_gold is False
    assert is_human_gold_review(simulated) is False
    with pytest.raises(ValueError, match="TEST_FIXTURE_SIMULATED_APPROVAL"):
        ReviewMetadata(state="HUMAN_APPROVED", decision_source="TEST_SIMULATION")
    real = ReviewMetadata(
        state="HUMAN_APPROVED",
        decision_source="HUMAN_REVIEWER",
        reviewer_id="REVIEWER_SYNTHETIC_01",
        reviewed_at="2026-09-24T00:00:00Z",
        evidence_ref="review_packet_case_001",
    )
    assert real.is_human_gold is True
    assert is_human_gold_review(real) is True


def test_transformation_trace_covers_edit_and_exclude_without_losing_hash():
    claim = _claim(review_state="DRAFT")
    edited = append_transformation(
        claim,
        operation="EDIT",
        source_claim_ids=(claim.claim_id,),
        source_spans=(claim.to_dict()["answer_span"],),
        result_span=claim.to_dict()["answer_span"],
        reason="Reviewer-friendly wording boundary edit recorded for later review.",
    )
    assert edited.content_hash != claim.content_hash
    assert edited.traceability[-1].operation == "EDIT"
    excluded = mark_claim_excluded(
        edited, reason="Excluded as duplicated conversational glue."
    )
    assert excluded.excluded is True
    assert excluded.traceability[-1].operation == "EXCLUDE"
    assert excluded.content_hash


@pytest.mark.parametrize("operation", ["MERGE", "SPLIT", "EDIT"])
def test_non_origin_transformations_require_traceable_sources(operation):
    claim = _claim(review_state="DRAFT")
    traced = append_transformation(
        claim,
        operation=operation,
        source_claim_ids=(claim.claim_id,),
        source_spans=(claim.to_dict()["answer_span"],),
        result_span=claim.to_dict()["answer_span"],
        reason=f"Synthetic {operation.lower()} trace for review tooling.",
    )
    assert traced.traceability[-1].operation == operation
    assert traced.traceability[-1].source_claim_ids == (claim.claim_id,)
