from __future__ import annotations

import pytest

from rag_engine.context import ContextBuilder
from rag_engine.domain import CitationBundle, MetadataFilter, RetrievalHit
from rag_engine.exceptions import ContractValidationError, UnsafeQueryError
from rag_engine.query import DeterministicQueryBuilder


def _assessment() -> dict:
    return {
        "schema_version": "assessment.v1",
        "assessment_id": "ASSESS_test_001",
        "subject_id": "SUBJ_test_001",
        "population_scope": "K12学生",
        "status": "completed",
        "dimensions": {"stress": {"theta": -0.7, "band": "unknown"}},
        "risk": {"level": "normal"},
    }


def test_query_builder_is_structured_and_does_not_interpret_theta(rag_config):
    plan = DeterministicQueryBuilder(rag_config).build(
        _assessment(),
        role="teacher",
        user_query="学生最近遇到学习压力时如何支持",
        topic="考试压力",
        intent="intervention",
    )
    assert plan.queries
    assert plan.layers[0].layer == "intervention"
    assert plan.filters.review_status == ("approved",)
    assert plan.filters.rights_status == ("verified",)
    assert "-0.7" not in " ".join(plan.queries)
    assert "SUBJ_test_001" not in " ".join(plan.queries)


def test_query_builder_rejects_identifier_tokens(rag_config):
    with pytest.raises(UnsafeQueryError):
        DeterministicQueryBuilder(rag_config).build(_assessment(), role="teacher", user_query="请看 SUBJ_test_001")


def test_query_builder_rejects_invalid_contract(rag_config):
    value = _assessment()
    value["schema_version"] = "assessment.v2"
    with pytest.raises(ContractValidationError):
        DeterministicQueryBuilder(rag_config).build(value, role="teacher")


def test_metadata_filter_uses_intersection_and_review_gate(sample_records):
    policy = sample_records[0]
    assert MetadataFilter(layers=("policy",), role_scope=("teacher",)).matches(policy)
    assert not MetadataFilter(layers=("theory",)).matches(policy)
    assert not MetadataFilter(review_status=("approved",)).matches(sample_records[-1])


def test_context_and_citations_have_identical_order(sample_records):
    hits = [RetrievalHit(record, "test", index) for index, record in enumerate(sample_records[:2])]
    bundle = ContextBuilder().build(hits, max_chars=4000)
    assert bundle.citation_bundle.ids == tuple(item.citation_id for item in bundle.items)
    assert bundle.citation_bundle.ids == ("S1", "S2")
    assert "CHUNK_test_policy_001" in {citation.chunk_id for citation in bundle.citation_bundle.citations}
    assert "[S1]" in bundle.text and "[S2]" in bundle.text


def test_context_truncation_keeps_source_binding(sample_records):
    hits = [RetrievalHit(record, "test", index) for index, record in enumerate(sample_records[:2])]
    bundle = ContextBuilder().build(hits, max_chars=80)
    assert bundle.truncated
    assert len(bundle.items) == len(bundle.citation_bundle.citations)
