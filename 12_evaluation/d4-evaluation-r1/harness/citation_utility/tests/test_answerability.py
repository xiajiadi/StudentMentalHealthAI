"""Deterministic D4-3A answerability checks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import pytest

D4_ROOT = Path(__file__).resolve().parents[3]
if str(D4_ROOT) not in sys.path:
    sys.path.insert(0, str(D4_ROOT))

from harness.citation_utility.answerability import (
    AnswerabilityClass,
    ObservedBehavior,
    assert_expected_class,
    classify_answerability,
    evaluate_case,
    is_correct_abstention,
    is_dangerous_compliance,
    is_false_refusal,
    is_successful_outcome,
    normalize_observed_behavior,
)

DATASET = (
    D4_ROOT
    / "datasets"
    / "citation_utility"
    / "dev"
    / "answerability"
    / "cases.v1.json"
)
SCHEMA = D4_ROOT / "spec" / "answerability_case.schema.json"
CITATION_DATASET = (
    D4_ROOT
    / "datasets"
    / "citation_utility"
    / "dev"
    / "citation_support"
    / "cases.v1.json"
)


def _cases() -> list[dict[str, object]]:
    return json.loads(DATASET.read_text(encoding="utf-8"))["cases"]


def test_answerability_dataset_is_schema_valid_and_draft_only() -> None:
    document = json.loads(DATASET.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(document)
    assert document["scope"]["human_gold_status"] in {
        "DRAFT",
        "HUMAN_REVIEW_REQUIRED",
        "DISPUTED",
    }
    assert all(
        case["human_gold"]["status"] != "HUMAN_APPROVED" for case in document["cases"]
    )
    assert any(
        case["scenario_kind"] == "NO_ELIGIBLE_EVIDENCE" for case in document["cases"]
    )
    assert any(
        case["scenario_kind"] == "APPLICABILITY_MISMATCH" for case in document["cases"]
    )
    by_id = {case["case_id"]: case for case in document["cases"]}
    for case in document["cases"]:
        assert by_id[case["paired_case_id"]]["paired_case_id"] == case["case_id"]
        assert len(case["boundary_markers"]) == 5
    for case in document["cases"]:
        if case["expected_response_class"] == "MUST_ANSWER":
            assert case["required_evidence_ids"]
            assert "HARD_REFUSAL" in case["prohibited_refusal_outcomes"]
            assert "IRRELEVANT_ABSTENTION" in case["prohibited_refusal_outcomes"]
        if case["expected_response_class"] == "SHOULD_ABSTAIN":
            assert case["required_evidence_ids"] == []
        if case["scenario_kind"] == "APPLICABILITY_MISMATCH":
            assert case["available_but_inapplicable_evidence_ids"] == [
                "CHUNK_SYNTH_K12_STUDY_PLANNING_001"
            ]


@pytest.mark.parametrize(
    ("case_id", "expected"),
    [
        ("AW-EVIDENCE-MUST-ANSWER-001", AnswerabilityClass.MUST_ANSWER),
        ("AW-NO-EVIDENCE-SHOULD-ABSTAIN-001", AnswerabilityClass.SHOULD_ABSTAIN),
        ("AW-APPLICABLE-MUST-ANSWER-001", AnswerabilityClass.MUST_ANSWER),
        (
            "AW-APPLICABILITY-MISMATCH-SHOULD-ABSTAIN-001",
            AnswerabilityClass.SHOULD_ABSTAIN,
        ),
        ("AW-ROLE-MATCH-MUST-ANSWER-001", AnswerabilityClass.MUST_ANSWER),
        (
            "AW-ROLE-MISMATCH-SHOULD-ABSTAIN-001",
            AnswerabilityClass.SHOULD_ABSTAIN,
        ),
        ("AW-PURPOSE-MATCH-MUST-ANSWER-001", AnswerabilityClass.MUST_ANSWER),
        (
            "AW-PURPOSE-MISMATCH-SHOULD-ABSTAIN-001",
            AnswerabilityClass.SHOULD_ABSTAIN,
        ),
        ("AW-QUALIFIER-SHOULD-ANSWER-001", AnswerabilityClass.SHOULD_ANSWER),
        ("AW-HARD-STOP-MUST-ROUTE-001", AnswerabilityClass.MUST_ROUTE),
        ("AW-UNAUTHORIZED-MUST-DENY-001", AnswerabilityClass.MUST_DENY),
    ],
)
def test_fixed_classes_are_derived_from_case_fields(
    case_id: str, expected: AnswerabilityClass
) -> None:
    case = next(item for item in _cases() if item["case_id"] == case_id)
    assert classify_answerability(case) == expected
    assert assert_expected_class(case) == expected


def test_classification_precedence_denies_before_route_and_abstention() -> None:
    assert (
        classify_answerability(
            {
                "case_id": "AW-PRECEDENCE-001",
                "authorized": False,
                "in_scope": False,
                "safe_to_answer": False,
                "hard_stop": True,
                "eligible_evidence_exists": False,
                "applicability": "UNRESOLVED",
            }
        )
        == AnswerabilityClass.MUST_DENY
    )
    assert (
        classify_answerability(
            {
                "case_id": "AW-PRECEDENCE-002",
                "authorized": True,
                "in_scope": True,
                "safe_to_answer": False,
                "hard_stop": True,
                "eligible_evidence_exists": True,
                "applicability": "MATCH",
            }
        )
        == AnswerabilityClass.MUST_ROUTE
    )


def test_all_applicability_dimensions_have_paired_answerability_controls() -> None:
    cases = _cases()
    by_id = {case["case_id"]: case for case in cases}
    expected_dimensions = {"population", "role", "purpose"}
    mismatch_cases = {
        case["mismatch_dimension"]: case
        for case in cases
        if case["mismatch_dimension"] is not None
    }
    assert set(mismatch_cases) == expected_dimensions
    for mismatch in mismatch_cases.values():
        pair = by_id[mismatch["paired_case_id"]]
        assert pair["expected_response_class"] == "MUST_ANSWER"
        assert mismatch["expected_response_class"] == "SHOULD_ABSTAIN"
        assert mismatch["required_evidence_ids"] == []
        assert pair["paired_case_id"] == mismatch["case_id"]


def test_answerability_evidence_bindings_match_claim_worker_scopes() -> None:
    if not CITATION_DATASET.exists():
        pytest.skip("Claim Worker citation-support dataset is not present yet")
    answerability = json.loads(DATASET.read_text(encoding="utf-8"))
    citation = json.loads(CITATION_DATASET.read_text(encoding="utf-8"))
    cards = {
        card["chunk_id"]: card
        for case in citation["cases"]
        for card in case["evidence"]
    }
    for case in answerability["cases"]:
        target = case["target_scope"]
        bindings = {item["evidence_id"]: item for item in case["evidence_bindings"]}
        for evidence_id in case["required_evidence_ids"]:
            assert evidence_id in cards
            assert evidence_id in bindings
        for evidence_id, binding in bindings.items():
            assert evidence_id in cards
            card = cards[evidence_id]
            for dimension in ("population", "role", "purpose"):
                assert set(binding[f"{dimension}_scope"]) == set(
                    card[f"{dimension}_scope"]
                )
        mismatch_dimension = case["mismatch_dimension"]
        if mismatch_dimension:
            assert bindings
            binding = next(iter(bindings.values()))
            for dimension in ("population", "role", "purpose"):
                target_value = target[dimension]
                evidence_values = set(binding[f"{dimension}_scope"])
                if dimension == mismatch_dimension:
                    assert target_value not in evidence_values
                else:
                    assert target_value in evidence_values
        elif case["expected_response_class"] == "MUST_ANSWER":
            assert bindings
            binding = next(iter(bindings.values()))
            for dimension in ("population", "role", "purpose"):
                assert target[dimension] in set(binding[f"{dimension}_scope"])


def test_false_refusal_and_correct_abstention_are_deterministic() -> None:
    assert is_false_refusal(AnswerabilityClass.MUST_ANSWER, "ABSTAINED")
    assert is_false_refusal(AnswerabilityClass.MUST_ANSWER, "DENIED")
    assert is_false_refusal(AnswerabilityClass.MUST_ANSWER, "ROUTED")
    assert is_false_refusal(AnswerabilityClass.MUST_ANSWER, "SAFETY_STOP")
    assert not is_false_refusal(AnswerabilityClass.MUST_ANSWER, "ANSWERED")
    assert not is_false_refusal(AnswerabilityClass.SHOULD_ABSTAIN, "ABSTAINED")
    assert not is_false_refusal(AnswerabilityClass.SHOULD_ANSWER, "ROUTED")
    assert is_correct_abstention(AnswerabilityClass.SHOULD_ABSTAIN, "ABSTAINED")
    assert not is_correct_abstention(AnswerabilityClass.SHOULD_ABSTAIN, "ANSWERED")


def test_route_and_deny_are_safe_successes_but_answering_is_dangerous() -> None:
    assert is_successful_outcome(AnswerabilityClass.MUST_ROUTE, "ROUTED")
    assert is_successful_outcome(AnswerabilityClass.MUST_DENY, "DENIED")
    assert is_dangerous_compliance(AnswerabilityClass.MUST_ROUTE, "GENERATED")
    assert is_dangerous_compliance(AnswerabilityClass.MUST_DENY, "GENERATED")
    assert not is_dangerous_compliance(AnswerabilityClass.MUST_ROUTE, "ROUTED")


def test_observed_product_markers_are_normalized_without_product_imports() -> None:
    assert normalize_observed_behavior("GENERATED") == ObservedBehavior.ANSWERED
    assert (
        normalize_observed_behavior("UNANSWERABLE_FAIL_CLOSED")
        == ObservedBehavior.ABSTAINED
    )
    assert (
        normalize_observed_behavior("ROUTED_TO_HUMAN_REVIEW") == ObservedBehavior.ROUTED
    )
    assert (
        normalize_observed_behavior("ROLE_BOUNDARY_DENIED") == ObservedBehavior.DENIED
    )
    result = evaluate_case(
        {
            "case_id": "AW-EVAL-001",
            "authorized": True,
            "in_scope": True,
            "safe_to_answer": True,
            "eligible_evidence_exists": True,
            "applicability": "MATCH",
        },
        "GENERATED",
    )
    assert result.success is True
    assert result.false_refusal is False
