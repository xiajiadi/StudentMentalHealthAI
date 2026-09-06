from __future__ import annotations

from rag_engine.domain import RetrievalHit
from rag_engine.evaluation.metrics import aggregate_metrics, evaluate_ranking
from rag_engine.retrieval import rrf_fuse


def test_rrf_preserves_stage_scores(sample_records):
    dense = [RetrievalHit(sample_records[1], "dense", 0, dense_score=0.8), RetrievalHit(sample_records[0], "dense", 1, dense_score=0.7)]
    sparse = [RetrievalHit(sample_records[1], "bm25s", 0, sparse_score=4.0), RetrievalHit(sample_records[0], "bm25s", 1, sparse_score=2.0)]
    fused = rrf_fuse([dense, sparse], k=2)
    assert fused[0].chunk_id == "CHUNK_test_theory_001"
    assert fused[0].dense_score == 0.8
    assert fused[0].sparse_score == 4.0
    assert fused[0].fusion_score is not None


def test_metrics_and_latency_percentiles():
    row = evaluate_ranking(["a", "x", "b"], ["a", "b"], latency_ms=10.0)
    assert row["hit_at_1"] == 1.0
    assert row["recall_at_5"] == 1.0
    assert row["mrr"] == 1.0
    aggregate = aggregate_metrics([row, evaluate_ranking([], [], latency_ms=20.0)])
    assert aggregate["query_count"] == 2
    assert aggregate["latency_p50_ms"] == 15.0
    assert aggregate["latency_p95_ms"] is not None


def test_negative_query_metrics_are_explicit_zero():
    row = evaluate_ranking(["a"], [])
    assert row["hit_at_1"] == 0.0
    assert row["recall_at_5"] == 0.0
    assert row["mrr"] == 0.0
