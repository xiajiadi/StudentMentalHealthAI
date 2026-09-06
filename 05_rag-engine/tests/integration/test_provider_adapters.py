from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, RefResolver

from rag_engine.config import RAGConfig
from rag_engine.domain import LayerBudget, MetadataFilter, RetrievalPlan
from rag_engine.embedding import MockEmbeddingProvider
from rag_engine.evaluation import load_golden_queries
from rag_engine.indexing import KnowledgeCorpusLoader
from rag_engine.retrieval import RetrievalService
from rag_engine.sparse import BM25SRetriever
from rag_engine.stores import ChromaVectorStore, MemoryVectorStore, QdrantVectorStore


pytestmark = pytest.mark.integration


@pytest.fixture()
def round1_corpus():
    root = Path(__file__).parents[3]
    return KnowledgeCorpusLoader().load(
        root / "04_knowledge-pipeline/data/published/round1/embedding_ready.jsonl",
        documents_path=root / "04_knowledge-pipeline/data/published/round1/knowledge_documents.jsonl",
        review_queue_path=root / "04_knowledge-pipeline/data/published/round1/review_queue.jsonl",
    )


def test_bm25s_real_index_save_load_and_chinese_retrieval(round1_corpus, tmp_path: Path):
    retriever = BM25SRetriever(round1_corpus.records)
    retriever.build()
    query_filter = MetadataFilter(layers=("intervention",), role_scope=("student",), target_population=("K12学生",), risk_scope=("normal",))
    first = retriever.search("考试压力支持建议", limit=5, filters=query_filter)
    assert first and first[0].chunk_id == "CHUNK_67b56abe21fe9860a26d"

    path = tmp_path / "bm25"
    retriever.save(path)
    loaded = BM25SRetriever.load(path, records=round1_corpus.records)
    second = loaded.search("考试压力支持建议", limit=5, filters=query_filter)
    assert [hit.chunk_id for hit in second] == [hit.chunk_id for hit in first]
    assert loaded.health_check()["version"] == "0.3.11"


def test_chroma_real_persistent_storage_and_metadata_filter(round1_corpus, tmp_path: Path):
    embedding = MockEmbeddingProvider(dimension=24)
    store = ChromaVectorStore(tmp_path / "chroma", "round1_integration")
    try:
        store.create_index(dimension=embedding.dimension, distance="cosine")
        output = embedding.embed_documents([record.context_text for record in round1_corpus.records])
        store.upsert(round1_corpus.records, output.dense_vectors)
        query = embedding.embed_queries(["学生压力支持"])
        hits = store.search_dense(
            query.dense_vectors[0],
            limit=10,
            filters=MetadataFilter(layers=("theory",), role_scope=("teacher",), target_population=("K12学生",), risk_scope=("normal",)),
        )
        assert store.index_info()["count"] == 14
        assert hits and all(hit.record.layer == "theory" for hit in hits)
        assert all(hit.record.review_status == "approved" and hit.record.rights_status == "verified" for hit in hits)
    finally:
        store.close()


def test_qdrant_local_named_vectors_and_native_rrf(round1_corpus, tmp_path: Path):
    embedding = MockEmbeddingProvider(dimension=16)
    store = QdrantVectorStore(tmp_path / "qdrant", "round1_hybrid_integration")
    try:
        store.create_index(dimension=embedding.dimension, distance="cosine")
        output = embedding.embed_documents([record.context_text for record in round1_corpus.records])
        sparse = [{index + 1: 1.0} for index, _ in enumerate(round1_corpus.records)]
        store.upsert(round1_corpus.records, output.dense_vectors, sparse)
        query = embedding.embed_queries(["学生压力支持"])
        query_filter = MetadataFilter(review_status=("approved",), rights_status=("verified",))
        dense = store.search_dense(query.dense_vectors[0], limit=3, filters=query_filter)
        sparse_hits = store.search_sparse({1: 1.0}, limit=3, filters=query_filter)
        hybrid = store.search_hybrid(query.dense_vectors[0], {1: 1.0}, limit=3, filters=query_filter, candidate_limit=5)
        assert dense and sparse_hits and hybrid
        assert hybrid[0].record.review_status == "approved"
        assert hybrid[0].fusion_score is not None
    finally:
        store.close()


def test_retrieval_api_envelope_validates_against_frozen_openapi(sample_records, tmp_path: Path):
    root = Path(__file__).parents[3]
    config_value = json.loads((root / "05_rag-engine/config/rag.v1.json").read_text(encoding="utf-8"))
    config_value["environment"] = "test"
    config_value["retrieval_mode"] = "dense"
    config_value["reranker"]["provider"] = "noop"
    config_value["stores"]["chroma_path"] = str(tmp_path / "chroma")
    config_value["stores"]["qdrant_path"] = str(tmp_path / "qdrant")
    config_value["stores"]["bm25_path"] = str(tmp_path / "bm25")
    config = RAGConfig.from_mapping(config_value, base_dir=tmp_path)
    embedding = MockEmbeddingProvider(dimension=16)
    store = MemoryVectorStore()
    store.create_index(dimension=16)
    output = embedding.embed_documents([record.context_text for record in sample_records[:3]])
    store.upsert(sample_records[:3], output.dense_vectors)
    service = RetrievalService(embedding_provider=embedding, dense_store=store)
    plan = RetrievalPlan(
        queries=("支持性沟通",),
        filters=MetadataFilter(role_scope=("teacher",), target_population=("K12学生",), risk_scope=("normal",)),
        layers=(LayerBudget("policy", 2),),
        retrieval_mode="dense",
        final_k=2,
        role="teacher",
        target_population="K12学生",
        risk_level="normal",
    )
    result = service.retrieve(plan, request_id="REQ_contract_001", trace_id="TRACE_contract_001", retrieval_id="RETR_contract_001")
    envelope = result.to_api_envelope(request_id="REQ_contract_001", trace_id="TRACE_contract_001")
    openapi = json.loads((root / "00_architecture/openapi.v1.json").read_text(encoding="utf-8"))
    schema = openapi["components"]["schemas"]["RetrievalEnvelope"]
    errors = list(Draft202012Validator(schema, resolver=RefResolver.from_schema(openapi)).iter_errors(envelope))
    assert not errors, [error.message for error in errors]
