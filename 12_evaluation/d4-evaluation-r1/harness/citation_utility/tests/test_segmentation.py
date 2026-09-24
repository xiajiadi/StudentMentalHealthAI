from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

D4_ROOT = Path(__file__).resolve().parents[3]
if str(D4_ROOT) not in sys.path:
    sys.path.insert(0, str(D4_ROOT))

from harness.citation_utility.claims import (
    DATA_CLASSIFICATION,
    Applicability,
    ReviewMetadata,
    validate_case_record,
)
from harness.citation_utility.segmentation import (
    segment_answer,
    validate_segments,
)
from harness.foundation.hashing import canonical_sha256_tag


def test_segmentation_is_deterministic_and_keeps_half_open_offsets():
    answer = "保持规律作息有助于安排学习。\n这不代表可以据此作出诊断。"
    scope_policy = {
        "required": False,
        "policy_id": "TEST_ORDINARY_SCOPE_BOUNDARY_NO_SOURCE",
        "reason": "这是普通边界说明，不依赖外部来源。",
    }
    first = segment_answer(
        answer, case_id="D4SUP-SEGMENT-001", scope_citation_policy=scope_policy
    )
    second = segment_answer(
        answer, case_id="D4SUP-SEGMENT-001", scope_citation_policy=scope_policy
    )
    assert [item.to_dict() for item in first] == [item.to_dict() for item in second]
    assert validate_segments(first) == first
    assert len(first) == 2
    for segment in first:
        assert answer[segment.span_start : segment.span_end] == segment.text
        assert segment.to_dict()["answer_span"]["end_inclusive"] is False
        assert segment.to_dict()["answer_span"]["unit"] == "python_codepoint"
        assert segment.original_answer == answer
    assert first[0].text.endswith("。")
    assert first[1].text.endswith("。")
    assert first[0].traceability[-1].operation == "SPLIT"


def test_segmentation_resolver_freezes_claim_type_and_policy():
    answer = "先说明范围。建议与信任的教师讨论学习安排。"
    segments = segment_answer(
        answer,
        case_id="D4SUP-SEGMENT-002",
        claim_type_resolver=lambda text, index: (
            "SCOPE_LIMITATION" if index == 0 else "EVIDENCE_GROUNDED_ACTION"
        ),
        scope_citation_policy={
            "required": True,
            "policy_id": "TEST_SOURCE_DEPENDENT_SCOPE_REQUIRED",
            "reason": "该范围说明依赖合成证据卡中的适用范围。",
        },
    )
    assert [item.claim_type for item in segments] == [
        "SCOPE_LIMITATION",
        "EVIDENCE_GROUNDED_ACTION",
    ]
    assert segments[0].citation_required is True
    assert segments[1].citation_required is True
    assert all(item.content_hash.startswith("sha256:") for item in segments)


def test_scope_policy_must_be_explicit_and_can_require_a_source():
    with pytest.raises(ValueError, match="scope_citation_policy"):
        segment_answer("这不代表可以据此作出诊断。", case_id="D4SUP-SEGMENT-004")
    required = {
        "required": True,
        "policy_id": "TEST_SOURCE_DEPENDENT_SCOPE_REQUIRED",
        "reason": "范围结论取决于合成证据卡的适用范围。",
    }
    segment = segment_answer(
        "这不代表可以据此作出诊断。",
        case_id="D4SUP-SEGMENT-005",
        scope_citation_policy=required,
    )[0]
    assert segment.citation_required is True
    assert segment.citation_policy_id == required["policy_id"]


def test_segment_can_be_promoted_with_separate_applicability_and_support():
    answer = "规律作息有助于安排学习。"
    segment = segment_answer(answer, case_id="D4SUP-SEGMENT-003")[0]
    mismatch = Applicability(
        "MISMATCH",
        "证据是中小学生范围，当前案例目标是大学新生。",
        expected_scope="university_freshman",
        evidence_scope=("k12",),
    )
    claim = segment.to_claim_record(
        cited_chunk_ids=("CHUNK_SYNTH_K12_001",),
        textual_entailment="SUPPORTS",
        population_applicability=mismatch,
        role_applicability=Applicability("APPLICABLE", "角色范围一致。"),
        purpose_applicability=Applicability("APPLICABLE", "教育支持用途一致。"),
        support_label="OUT_OF_SCOPE",
    )
    assert claim.textual_entailment == "SUPPORTS"
    assert claim.support_label == "OUT_OF_SCOPE"


def test_dev_dataset_schema_hashes_and_synthetic_boundaries():
    dataset_path = (
        D4_ROOT
        / "datasets"
        / "citation_utility"
        / "dev"
        / "citation_support"
        / "cases.v1.json"
    )
    schema_path = D4_ROOT / "spec" / "citation_support.schema.json"
    if not dataset_path.exists():
        pytest.skip("citation-support fixture is created with the Worker A handoff")
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(dataset)
    assert (
        canonical_sha256_tag(dataset, self_field="dataset_hash")
        == dataset["dataset_hash"]
    )
    assert dataset["data_classification"] == list(DATA_CLASSIFICATION)
    assert dataset["review"]["state"] == "HUMAN_REVIEW_REQUIRED"
    assert dataset["review"]["human_gold"] is False
    assert len(dataset["cases"]) >= 7
    labels = {
        claim["support_label"] for case in dataset["cases"] for claim in case["claims"]
    }
    assert {
        "SUPPORTS",
        "PARTIALLY_SUPPORTS",
        "UNSUPPORTED",
        "CONTRADICTS",
        "OUT_OF_SCOPE",
    } <= labels
    for case_data in dataset["cases"]:
        case = validate_case_record(case_data)
        assert case.content_hash == case_data["content_hash"]
        assert case.review.is_human_gold is False
        assert case.review.is_test_only is False
        assert all(
            item["status"] == "VALID" and item["provenance_complete"] is True
            for item in case_data["citation_identity"]
        )
        for claim in case.claims:
            assert claim.data_classification == DATA_CLASSIFICATION
            assert (
                claim.original_answer[claim.span_start : claim.span_end] == claim.text
            )
            assert claim.review.is_human_gold is False
            assert claim.review.is_test_only is False
        for evidence in case_data["evidence"]:
            assert evidence["document_id"]
            assert evidence["citation_id"]
            assert evidence["source_title"]
            assert evidence["source_organization"]
            assert evidence["locator"].startswith("synthetic://")
            matching_claims = [
                claim
                for claim in case_data["claims"]
                if evidence["chunk_id"] in claim["cited_chunk_ids"]
            ]
            if any(
                claim["textual_entailment"] == "UNSUPPORTED"
                for claim in matching_claims
            ):
                assert all(
                    claim["support_label"] != "SUPPORTS"
                    for claim in matching_claims
                    if claim["textual_entailment"] == "UNSUPPORTED"
                )


def test_schema_allows_only_explicit_test_simulated_human_approval():
    dataset_path = (
        D4_ROOT
        / "datasets"
        / "citation_utility"
        / "dev"
        / "citation_support"
        / "cases.v1.json"
    )
    schema_path = D4_ROOT / "spec" / "citation_support.schema.json"
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    simulated = ReviewMetadata(
        state="HUMAN_APPROVED",
        decision_source="TEST_SIMULATION",
        simulated_outcome="TEST_FIXTURE_SIMULATED_APPROVAL",
    ).to_dict()
    candidate = dict(dataset)
    candidate["review"] = simulated
    Draft202012Validator(schema).validate(candidate)

    invalid = dict(candidate)
    invalid["review"] = dict(simulated, human_gold=True)
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(invalid)

    invalid_card = deepcopy(dataset)
    invalid_card["cases"][0]["evidence"][0]["review_state"] = "HUMAN_APPROVED"
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(invalid_card)
