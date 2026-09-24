"""Focused deterministic checks for the D4-3A human-review packet."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

D4_ROOT = Path(__file__).resolve().parents[3]
if str(D4_ROOT) not in sys.path:
    sys.path.insert(0, str(D4_ROOT))

from harness.citation_utility.review_packet import (
    DATA_CLASSIFICATION,
    SIMULATED_APPROVAL_PROVENANCE,
    SUPPORT_LABELS,
    ReviewPacketError,
    build_review_packet,
    packet_from_json,
    packet_hash,
    packet_to_json,
    packet_to_markdown,
    round_trip_packet,
    verify_packet_hash,
)


def _case(*, review: dict[str, object] | None = None) -> dict[str, object]:
    evidence = [
        {
            "chunk_id": f"CHUNK_PACKET_{index:03d}",
            "document_id": f"DOC_PACKET_{index:03d}",
            "citation_id": f"CIT_PACKET_{index:03d}",
            "source_title": "合成学习支持资料",
            "source_organization": "D4 Synthetic Evaluation Fixture",
            "locator": f"synthetic://d4/review/{index}",
            "text": "用于评估的中性学习支持说明。",
            "population_scope": ["university_freshman"],
            "role_scope": ["student"],
            "purpose_scope": ["education_support"],
            "review_state": "HUMAN_REVIEW_REQUIRED",
            "content_hash": "sha256:" + "0" * 64,
        }
        for index in range(1, 6)
    ]
    claims = []
    for index, label in enumerate(SUPPORT_LABELS, start=1):
        applicability = {
            "population": {
                "status": "MISMATCH" if label == "OUT_OF_SCOPE" else "APPLICABLE",
                "reason": "合成适用范围检查。",
                "expected_scope": "university_freshman",
                "evidence_scope": ["k12"]
                if label == "OUT_OF_SCOPE"
                else ["university_freshman"],
            },
            "role": {"status": "APPLICABLE", "reason": "角色匹配。"},
            "purpose": {"status": "APPLICABLE", "reason": "用途匹配。"},
        }
        claims.append(
            {
                "claim_id": f"CLM_PACKET_{index:03d}",
                "case_id": "D4SUP-PACKET-001",
                "text": f"合成主张 {index}",
                "answer_span": {
                    "start": 0,
                    "end": 6,
                    "end_inclusive": False,
                    "unit": "python_codepoint",
                },
                "content_hash": "sha256:" + "2" * 64,
                "traceability": [
                    {
                        "operation": "ORIGIN",
                        "source_claim_ids": [],
                        "source_spans": [],
                        "result_span": None,
                        "reason": "合成主张来源保留。",
                    }
                ],
                "claim_type": "FACTUAL_VERIFIABLE",
                "citation_required": True,
                "citation_reason": "外部可核验主张需要引用。",
                "cited_chunk_ids": [f"CHUNK_PACKET_{index:03d}"],
                "textual_entailment": "SUPPORTS" if label == "OUT_OF_SCOPE" else label,
                "population_applicability": applicability["population"],
                "role_applicability": applicability["role"],
                "purpose_applicability": applicability["purpose"],
                "applicability": applicability,
                "support_label": label,
                "review": {
                    "state": "HUMAN_REVIEW_REQUIRED",
                    "decision_source": "NONE",
                    "reviewer_id": None,
                    "reviewed_at": None,
                    "evidence_ref": None,
                    "simulated_outcome": None,
                },
            }
        )
    result: dict[str, object] = {
        "schema_version": "citation-support.v1",
        "record_type": "case",
        "case_id": "D4SUP-PACKET-001",
        "original_answer": "这是一段仅用于评估的合成教育支持输出。",
        "target_scope": {
            "population": "university_freshman",
            "role": "student",
            "purpose": "education_support",
        },
        "split": "DEV",
        "evidence": evidence,
        "claims": claims,
        "review": review
        or {
            "state": "HUMAN_REVIEW_REQUIRED",
            "decision_source": "NONE",
            "reviewer_id": None,
            "reviewed_at": None,
            "evidence_ref": None,
            "simulated_outcome": None,
        },
        "data_classification": list(DATA_CLASSIFICATION),
    }
    return result


def _answerability_case() -> dict[str, object]:
    return {
        "case_id": "AW-PACKET-MUST-ANSWER-001",
        "pair_id": "PAIR-PACKET-EVIDENCE",
        "paired_case_id": "AW-PACKET-SHOULD-ABSTAIN-001",
        "request": "请根据已审核资料概括一条学习计划建议。",
        "target_scope": {
            "population": "university_freshman",
            "role": "student",
            "purpose": "education_support",
        },
        "evidence_bindings": [
            {
                "evidence_id": "CHUNK_PACKET_001",
                "population_scope": ["university_freshman"],
                "role_scope": ["student"],
                "purpose_scope": ["education_support"],
            }
        ],
        "expected_response_class": "MUST_ANSWER",
        "required_evidence_ids": ["CHUNK_PACKET_001"],
        "available_but_inapplicable_evidence_ids": [],
        "minimum_useful_behavior": "ANSWER_WITH_BOUNDED_EDUCATIONAL_GUIDANCE",
        "minimum_useful_content_expectation": "给出一条有限范围的教育支持建议并保留来源。",
        "prohibited_refusal_outcomes": ["HARD_REFUSAL", "IRRELEVANT_ABSTENTION"],
        "expected_rationale": "存在适用合成证据，且请求已授权。",
        "mismatch_dimension": None,
        "human_gold": {
            "status": "DRAFT",
            "provenance": "SYNTHETIC_DRAFT_NO_HUMAN_REVIEW",
        },
    }


def test_packet_contains_all_labels_identity_scope_and_blank_review_fields() -> None:
    packet = build_review_packet(_case())
    assert packet["review_status"] == "HUMAN_REVIEW_REQUIRED"
    assert packet["human_gold"] is False
    assert packet["source_dataset_hash"].startswith("sha256:")
    assert (
        packet["source_binding"]["citation_support"]["hash"]
        == packet["source_dataset_hash"]
    )
    assert [item["label"] for item in packet["label_legend"]] == list(SUPPORT_LABELS)
    case = packet["cases"][0]
    assert {item["support_label"] for item in case["claims"]} == set(SUPPORT_LABELS)
    assert case["scope_dimensions"] == {
        "population": "university_freshman",
        "role": "student",
        "purpose": "education_support",
    }
    assert case["citations"][0]["chunk_id"] == "CHUNK_PACKET_001"
    assert case["citations"][0]["document_id"] == "DOC_PACKET_001"
    assert case["citations"][0]["content_hash"] == "sha256:" + "0" * 64
    assert case["claims"][0]["draft_rationale"]
    assert case["claims"][0]["content_hash"] == "sha256:" + "2" * 64
    assert case["claims"][0]["traceability"][0]["operation"] == "ORIGIN"
    assert case["claims"][0]["citation_identity"]["status"] == "VALID"
    assert case["claims"][0]["citation_identity"]["provenance_complete"] is True
    out_of_scope = next(
        claim for claim in case["claims"] if claim["support_label"] == "OUT_OF_SCOPE"
    )
    assert out_of_scope["textual_entailment"] == "SUPPORTS"
    assert out_of_scope["citation_identity"]["status"] == "VALID"
    assert case["review"]["status"] == "HUMAN_REVIEW_REQUIRED"
    assert case["review"]["human_decision"] is None
    assert case["review"]["human_notes"] == ""
    assert verify_packet_hash(packet)


def test_packet_json_markdown_round_trip_and_hash_are_deterministic() -> None:
    source = _case()
    first = build_review_packet(source)
    reordered = _case()
    reordered["claims"] = list(reversed(reordered["claims"]))
    reordered["evidence"] = list(reversed(reordered["evidence"]))
    second = build_review_packet(reordered)
    assert first["packet_hash"] == second["packet_hash"]
    serialized = packet_to_json(first)
    restored = packet_from_json(serialized)
    assert restored == first
    assert round_trip_packet(first) == first
    assert packet_hash(first) == first["packet_hash"]
    markdown = packet_to_markdown(first)
    assert "D4-3A Human Review Packet" in markdown
    for label in SUPPORT_LABELS:
        assert f"`{label}`" in markdown
    assert "合成主张 1" in markdown
    assert "用于评估的中性学习支持说明。" in markdown
    assert first["source_dataset_hash"] in markdown
    assert "Traceability" in markdown
    assert "ORIGIN" in markdown
    assert "HUMAN_APPROVED" not in serialized
    assert "HUMAN_APPROVED" not in markdown


def test_citation_identity_distinguishes_unknown_and_no_citation() -> None:
    source = _case()
    claims = list(source["claims"])
    claims[0] = {**claims[0], "cited_chunk_ids": ["CHUNK_DOES_NOT_EXIST"]}
    claims[1] = {**claims[1], "cited_chunk_ids": []}
    source["claims"] = claims
    packet = build_review_packet(source)
    claim_unknown = next(
        claim
        for claim in packet["cases"][0]["claims"]
        if claim["claim_id"] == "CLM_PACKET_001"
    )
    claim_none = next(
        claim
        for claim in packet["cases"][0]["claims"]
        if claim["claim_id"] == "CLM_PACKET_002"
    )
    assert claim_unknown["citation_identity"]["status"] == "UNKNOWN"
    assert claim_unknown["citation_identity"]["unknown_chunk_ids"] == [
        "CHUNK_DOES_NOT_EXIST"
    ]
    assert claim_none["citation_identity"]["status"] == "NONE"


def test_packet_includes_answerability_controls_with_pending_reviewer_fields() -> None:
    packet = build_review_packet(
        {"citation_cases": [_case()], "answerability_cases": [_answerability_case()]}
    )
    control = packet["answerability_cases"][0]
    assert control["expected_response_class"] == "MUST_ANSWER"
    assert control["target_scope"] == {
        "population": "university_freshman",
        "role": "student",
        "purpose": "education_support",
    }
    assert control["evidence_bindings"][0]["evidence_id"] == "CHUNK_PACKET_001"
    assert control["required_evidence_ids"] == ["CHUNK_PACKET_001"]
    assert control["paired_case_id"] == "AW-PACKET-SHOULD-ABSTAIN-001"
    assert control["human_review"]["status"] == "DRAFT"
    assert control["human_review"]["human_decision"] is None
    assert control["human_review"]["human_notes"] == ""
    markdown = packet_to_markdown(packet)
    assert "Answerability controls" in markdown
    assert "AW-PACKET-SHOULD-ABSTAIN-001" in markdown
    assert packet["source_binding"]["answerability"]["hash"] in markdown
    assert "请根据已审核资料概括一条学习计划建议。" in markdown
    assert "Mismatch dimension: `(none)`" in markdown
    assert "Human decision: `None`" not in markdown
    assert "Target scope: population=`university_freshman`" in markdown
    assert "CHUNK_PACKET_001` population=university_freshman" in markdown


def test_simulated_approval_is_pending_test_fixture_provenance_only() -> None:
    packet = build_review_packet(
        _case(
            review={
                "state": "HUMAN_APPROVED",
                "decision_source": "TEST_SIMULATION",
                "reviewer_id": None,
                "reviewed_at": None,
                "evidence_ref": None,
                "simulated_outcome": SIMULATED_APPROVAL_PROVENANCE,
            }
        )
    )
    review = packet["cases"][0]["review"]
    assert review["status"] == "HUMAN_REVIEW_REQUIRED"
    assert review["human_gold"] is False
    assert review["test_fixture"] == {
        "simulated_approval": True,
        "provenance": SIMULATED_APPROVAL_PROVENANCE,
        "excluded_from_human_gold": True,
    }
    assert "HUMAN_APPROVED" not in packet_to_json(packet)


def test_actual_approval_cannot_be_exported_as_a_review_packet() -> None:
    with pytest.raises(ReviewPacketError, match="cannot be emitted"):
        build_review_packet(
            _case(
                review={
                    "state": "HUMAN_APPROVED",
                    "decision_source": "HUMAN_REVIEWER",
                    "reviewer_id": "synthetic-human-reviewer",
                    "reviewed_at": "2026-09-24T00:00:00Z",
                    "evidence_ref": "fixture://review/approved",
                    "simulated_outcome": None,
                }
            )
        )
