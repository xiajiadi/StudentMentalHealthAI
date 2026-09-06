from __future__ import annotations

import os
from pathlib import Path

import pytest

from rag_engine.config import RAGConfig
from rag_engine.domain import LayerBudget, MetadataFilter, RetrievalHit, RetrievalPlan
from rag_engine.embedding import BGEM3EmbeddingProvider
from rag_engine.indexing import IndexBuilder, KnowledgeCorpusLoader
from rag_engine.rerank import BGERerankerProvider
from rag_engine.retrieval import RetrievalService
from rag_engine.sparse import BM25SRetriever
from rag_engine.stores import ChromaVectorStore


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("SMHAI_RUN_RERANKER_INTEGRATION") != "1",
        reason="set SMHAI_RUN_RERANKER_INTEGRATION=1 to run the real reranker gate",
    ),
]


@pytest.fixture(scope="module")
def real_reranker_stack(tmp_path_factory: pytest.TempPathFactory):
    root = Path(__file__).parents[3]
    config = RAGConfig.load(root / "05_rag-engine/config/rag.v1.json")
    corpus = KnowledgeCorpusLoader().load(
        root / "04_knowledge-pipeline/data/published/round1/embedding_ready.jsonl",
        documents_path=root / "04_knowledge-pipeline/data/published/round1/knowledge_documents.jsonl",
        review_queue_path=root / "04_knowledge-pipeline/data/published/round1/review_queue.jsonl",
    )
    embedding = BGEM3EmbeddingProvider(config.embedding, return_sparse=True)
    store = ChromaVectorStore(tmp_path_factory.mktemp("reranker") / "chroma", "reranker_integration")
    build = IndexBuilder(embedding, store).build(
        corpus.records,
        config=config,
        index_dir=tmp_path_factory.mktemp("reranker-index"),
        excluded_count=len(corpus.excluded),
    )
    reranker = BGERerankerProvider(config.reranker)
    health = reranker.health_check(load=True)
    if health.get("status") != "ok":
        store.close()
        pytest.fail(f"real reranker is not ready: {health}")

    bm25 = BM25SRetriever(corpus.records)
    bm25.build()
    dense_service = RetrievalService(
        embedding_provider=embedding,
        dense_store=store,
        reranker=reranker,
        index_manifest=build.manifest.to_dict(),
        rrf_k=config.rrf_k,
    )
    hybrid_service = RetrievalService(
        embedding_provider=embedding,
        dense_store=store,
        sparse_retriever=bm25,
        reranker=reranker,
        index_manifest=build.manifest.to_dict(),
        rrf_k=config.rrf_k,
    )
    result = {
        "config": config,
        "corpus": corpus,
        "embedding": embedding,
        "store": store,
        "reranker": reranker,
        "health": health,
        "dense": dense_service,
        "hybrid": hybrid_service,
    }
    try:
        yield result
    finally:
        store.close()


def _plan(config: RAGConfig, *, mode: str, query: str = "第十三条 支持性沟通") -> RetrievalPlan:
    return RetrievalPlan(
        queries=(query,),
        filters=MetadataFilter(
            role_scope=("teacher",),
            target_population=("K12学生",),
            risk_scope=("normal",),
        ),
        layers=(LayerBudget("policy", 5),),
        retrieval_mode=mode,
        dense_candidate_k=config.dense_candidate_k,
        sparse_candidate_k=config.sparse_candidate_k,
        fusion_candidate_k=config.fusion_candidate_k,
        rerank_candidate_k=config.rerank_candidate_k,
        final_k=config.final_k,
        rerank_enabled=True,
        context_max_chars=config.context_max_chars,
        role="teacher",
        target_population="K12学生",
        dimension="stress",
        intent="policy",
        risk_level="normal",
        query_type="integration",
    )


def test_real_bge_reranker_load(real_reranker_stack):
    health = real_reranker_stack["health"]
    assert health["status"] == "ok"
    assert health["loaded"] is True
    assert health["model_name"] == "BAAI/bge-reranker-v2-m3"
    assert health["model_revision"] == "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
    assert health["device"] == "cpu"
    assert health["score_probe"]["status"] == "ok"
    assert isinstance(health["score_probe"]["score"], float)


def test_real_bge_reranker_scores(real_reranker_stack):
    records = real_reranker_stack["corpus"].records[:3]
    hits = [RetrievalHit(record=record, retriever="integration", rank=rank) for rank, record in enumerate(records)]
    ranked = real_reranker_stack["reranker"].rerank("如何提供教育支持", hits, limit=3)
    assert len(ranked) == 3
    assert {hit.chunk_id for hit in ranked} == {record.chunk_id for record in records}
    assert all(hit.rerank_score is not None for hit in ranked)
    assert all(hit.retriever == "bge-reranker-v2-m3" for hit in ranked)


def test_dense_rerank_pipeline(real_reranker_stack):
    result = real_reranker_stack["dense"].retrieve(
        _plan(real_reranker_stack["config"], mode="dense"),
        request_id="REQ_real_dense_rerank",
        trace_id="TRACE_real_dense_rerank",
        retrieval_id="RETR_real_dense_rerank",
    )
    trace = result.trace.to_dict()
    assert trace["retrieval_plan"]["rerank_enabled"] is True
    assert trace["rerank_candidates"]
    assert trace["rerank"]
    assert all(item["rerank_score"] is not None for item in trace["rerank"])
    assert all(item["before_rank"] is not None and item["after_rank"] is not None for item in trace["rerank"])
    assert trace["reranker_version"] == "FlagEmbedding:1.4.2"
    assert trace["reranker_revision"] == "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
    assert trace["latency_ms"]["rerank_ms"] is not None and trace["latency_ms"]["rerank_ms"] > 0
    assert list(trace["final_context"]) == list(result.citations.ids)


def test_hybrid_rerank_pipeline(real_reranker_stack):
    result = real_reranker_stack["hybrid"].retrieve(
        _plan(real_reranker_stack["config"], mode="hybrid", query="支持性沟通流程"),
        request_id="REQ_real_hybrid_rerank",
        trace_id="TRACE_real_hybrid_rerank",
        retrieval_id="RETR_real_hybrid_rerank",
    )
    trace = result.trace.to_dict()
    assert trace["dense_hits"]
    assert trace["sparse_hits"]
    assert trace["fusion"]
    assert trace["rerank_candidates"]
    assert trace["rerank"]
    assert trace["retrieval_plan"]["rerank_enabled"] is True
    assert trace["latency_ms"]["rerank_ms"] is not None and trace["latency_ms"]["rerank_ms"] > 0
    assert list(trace["final_context"]) == list(result.citations.ids)
    assert all(citation.chunk_id.startswith("CHUNK_") for citation in result.citations.citations)
