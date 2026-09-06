from __future__ import annotations

from rag_engine.domain import MetadataFilter, RetrievalPlan
from rag_engine.embedding import MockEmbeddingProvider
from rag_engine.indexing import IndexBuilder
from rag_engine.retrieval import RetrievalService
from rag_engine.stores import MemoryVectorStore


def _plan(mode: str = "dense") -> RetrievalPlan:
    return RetrievalPlan(
        queries=("支持性沟通",),
        filters=MetadataFilter(role_scope=("teacher",), target_population=("K12学生",), risk_scope=("normal",)),
        layers=(__import__("rag_engine").LayerBudget("policy", 2),),
        retrieval_mode=mode,
        dense_candidate_k=10,
        sparse_candidate_k=10,
        fusion_candidate_k=10,
        rerank_candidate_k=5,
        final_k=2,
        rerank_enabled=False,
        context_max_chars=1000,
        role="teacher",
        target_population="K12学生",
        risk_level="normal",
    )


def test_index_builder_manifest_is_stable(rag_config, sample_records, tmp_path):
    provider = MockEmbeddingProvider(dimension=16)
    store = MemoryVectorStore()
    result = IndexBuilder(provider, store).build(sample_records[:3], config=rag_config, index_dir=tmp_path / "index", timestamp="2026-09-04T00:00:00Z")
    assert result.manifest.index_id.startswith("INDEX_")
    assert result.manifest.chunk_count == 3
    second = IndexBuilder(provider, store).build(sample_records[:3], config=rag_config, index_dir=tmp_path / "index", timestamp="2026-09-05T00:00:00Z")
    assert second.reused
    assert second.manifest.index_id == result.manifest.index_id


def test_index_builder_rebuild_removes_stale_chunks(rag_config, sample_records, tmp_path):
    provider = MockEmbeddingProvider(dimension=16)
    store = MemoryVectorStore()
    builder = IndexBuilder(provider, store)
    first = builder.build(sample_records[:3], config=rag_config, index_dir=tmp_path / "index", timestamp="2026-09-04T00:00:00Z")
    second = builder.build(sample_records[:2], config=rag_config, index_dir=tmp_path / "index", timestamp="2026-09-04T00:00:00Z")
    assert not second.reused
    assert second.manifest.index_id != first.manifest.index_id
    assert store.index_info()["count"] == 2


def test_service_returns_trace_context_and_citations(sample_records):
    provider = MockEmbeddingProvider(dimension=16)
    store = MemoryVectorStore()
    store.create_index(dimension=16)
    store.upsert(sample_records[:3], provider.embed_documents([record.context_text for record in sample_records[:3]]).dense_vectors)
    service = RetrievalService(embedding_provider=provider, dense_store=store, index_manifest={"index_version": "1.0.0", "corpus_version": "sha256:test"})
    result = service.retrieve(_plan(), request_id="REQ_test_001", trace_id="TRACE_test_001", retrieval_id="RETR_test_001")
    assert result.retrieval_id == "RETR_test_001"
    assert result.trace.trace_id == "TRACE_test_001"
    assert result.trace.final_hits
    assert result.trace.final_context == list(result.citations.ids)
    assert result.hits[0].record.review_status == "approved"


def test_memory_store_never_returns_rejected_with_filter(sample_records):
    provider = MockEmbeddingProvider(dimension=16)
    store = MemoryVectorStore()
    store.create_index(dimension=16)
    output = provider.embed_documents([record.context_text for record in sample_records])
    store.upsert(sample_records, output.dense_vectors)
    hits = store.search_dense(output.dense_vectors[-1], limit=10, filters=MetadataFilter(review_status=("approved",)))
    assert all(hit.record.review_status == "approved" for hit in hits)
