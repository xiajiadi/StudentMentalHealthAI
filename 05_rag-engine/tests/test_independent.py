from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from rag_engine.domain import KnowledgeRecord
from rag_engine.embedding import MockEmbeddingProvider
from rag_engine.exceptions import InvalidConfigurationError, UnsafeQueryError
from rag_engine.independent import (
    IndependentRetrieveRequest,
    attach_independent_routes,
    build_independent_plan,
)
from rag_engine.retrieval import RetrievalService
from rag_engine.stores import MemoryVectorStore


def _record(chunk_id: str, population: str, text: str) -> KnowledgeRecord:
    row = {
        "chunk_id": chunk_id,
        "document_id": f"KB_{chunk_id.removeprefix('CHUNK_')}",
        "text": text,
        "context_text": text,
        "metadata": {
            "layer": "intervention",
            "title": f"Synthetic {population} guidance",
            "organization": "Synthetic test corpus",
            "source_filename": "synthetic-guidance.md",
            "section": "Study planning",
            "citation_locator": "synthetic://rag/independent-test",
            "role_scope": ["student"],
            "target_population": [population],
            "risk_scope": ["normal"],
            "review_status": "approved",
            "rights_status": "verified",
            "content_hash": f"sha256:{chunk_id.lower()}",
        },
    }
    return KnowledgeRecord.from_embedding_record(row)


def _app_with_dense_runtime(config, records: list[KnowledgeRecord]):
    provider = MockEmbeddingProvider(dimension=16)
    store = MemoryVectorStore()
    store.create_index(dimension=16)
    embeddings = provider.embed_documents([record.context_text for record in records])
    store.upsert(records, embeddings.dense_vectors)
    retrieval = RetrievalService(
        embedding_provider=provider,
        dense_store=store,
        index_manifest={"index_version": "test-1", "corpus_version": "sha256:test"},
    )
    runtime = SimpleNamespace(
        config=config,
        ready=True,
        stack={"dense_service": retrieval},
    )
    app = FastAPI()
    attach_independent_routes(app, runtime)
    return app


def test_independent_plan_has_no_measurement_or_risk_and_uses_fixed_student_scope(
    rag_config,
) -> None:
    query = "How can I break study planning into manageable steps?"

    plan = build_independent_plan(rag_config, query, "university_freshman")

    assert plan.queries == (query,)
    assert plan.assessment_id is None
    assert plan.risk_level is None
    assert plan.filters.risk_scope == ()
    assert plan.filters.role_scope == ("student",)
    assert plan.filters.target_population == ("university_freshman",)
    assert plan.role == "student"
    assert plan.dimension is None
    assert plan.topic is None
    assert plan.intent is None
    projection = plan.to_dict()
    assert projection["assessment_id"] is None
    assert projection["risk_level"] is None
    assert projection["filters"]["risk_scope"] == []
    assert "subject_id" not in projection
    assert "theta" not in projection


def test_independent_endpoint_uses_real_retrieval_and_returns_scoped_citations(
    rag_config,
) -> None:
    matching = _record(
        "CHUNK_university_001",
        "university_freshman",
        "Study planning: divide assignments into manageable short steps.",
    )
    k12 = _record(
        "CHUNK_k12_001",
        "K12学生",
        "Study planning: divide assignments into manageable short steps.",
    )
    app = _app_with_dense_runtime(rag_config, [matching, k12])

    with TestClient(app) as client:
        response = client.post(
            "/internal/rag/independent-retrievals",
            headers={
                "X-Request-ID": "REQ_independent_001",
                "X-Trace-ID": "TRACE_independent_001",
            },
            json={
                "query": "Study planning manageable steps",
                "target_population": "university_freshman",
                "top_k": 3,
                "retrieval_id": "RETR_independent_001",
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["request_id"] == "REQ_independent_001"
    assert payload["trace_id"] == "TRACE_independent_001"
    data = payload["data"]
    assert data["retrieval_id"] == "RETR_independent_001"
    assert [chunk["chunk_id"] for chunk in data["chunks"]] == ["CHUNK_university_001"]
    citation = data["citations"]["citations"][0]
    assert citation["chunk_id"] == "CHUNK_university_001"
    assert citation["source_title"] == "Synthetic university_freshman guidance"
    assert data["trace"]["raw_query"] == "Study planning manageable steps"
    assert data["trace"]["outcome"] == "success"
    assert data["plan"]["assessment_id"] is None
    assert data["plan"]["risk_level"] is None
    assert data["plan"]["filters"]["target_population"] == ["university_freshman"]
    assert data["plan"]["filters"]["risk_scope"] == []


def test_independent_endpoint_returns_real_empty_evidence_without_k12_fallback(
    rag_config,
) -> None:
    k12 = _record(
        "CHUNK_k12_only_001",
        "K12学生",
        "Study planning: divide assignments into manageable short steps.",
    )
    app = _app_with_dense_runtime(rag_config, [k12])

    with TestClient(app) as client:
        response = client.post(
            "/internal/rag/independent-retrievals",
            json={
                "query": "Study planning manageable steps",
                "target_population": "university_freshman",
            },
        )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["chunks"] == []
    assert data["citations"]["citations"] == []
    assert data["trace"]["outcome"] == "no_results"
    assert data["trace"]["final"] == []


def test_university_student_scope_does_not_alias_freshman_corpus(rag_config) -> None:
    freshman = _record(
        "CHUNK_freshman_001",
        "university_freshman",
        "Study planning: divide assignments into manageable short steps.",
    )
    app = _app_with_dense_runtime(rag_config, [freshman])
    plan = build_independent_plan(
        rag_config,
        "Study planning manageable steps",
        "university_student",
    )
    assert plan.target_population == "university_student"
    assert plan.filters.target_population == ("university_student",)
    assert plan.risk_level is None
    assert plan.filters.risk_scope == ()

    with TestClient(app) as client:
        response = client.post(
            "/internal/rag/independent-retrievals",
            json={
                "query": "Study planning manageable steps",
                "target_population": "university_student",
            },
        )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["plan"]["target_population"] == "university_student"
    assert data["chunks"] == []
    assert data["citations"]["citations"] == []
    assert data["trace"]["outcome"] == "no_results"


def test_independent_request_rejects_assessment_role_risk_and_unapproved_population(
    rag_config,
) -> None:
    allowed = {
        "query": "Study planning steps",
        "target_population": "university_freshman",
    }
    assert (
        IndependentRetrieveRequest.model_validate(allowed).target_population
        == "university_freshman"
    )
    student_scope = IndependentRetrieveRequest.model_validate(
        {**allowed, "target_population": "university_student"}
    )
    assert student_scope.target_population == "university_student"
    for forbidden in (
        "assessment",
        "assessment_id",
        "subject_id",
        "risk",
        "risk_level",
        "dimensions",
        "target_role",
    ):
        with pytest.raises(ValueError):
            IndependentRetrieveRequest.model_validate({**allowed, forbidden: {}})

    with pytest.raises(ValueError):
        IndependentRetrieveRequest.model_validate(
            {**allowed, "target_population": "K12学生"}
        )
    with pytest.raises(
        InvalidConfigurationError, match="unsupported independent student population"
    ):
        build_independent_plan(rag_config, "Study planning steps", "K12学生")
    with pytest.raises(
        InvalidConfigurationError, match="unsupported configured retrieval mode"
    ):
        build_independent_plan(
            replace(rag_config, retrieval_mode="unsupported"),
            "Study planning steps",
            "university_freshman",
        )
    with pytest.raises(UnsafeQueryError):
        build_independent_plan(
            rag_config, "Contact student 123456789", "university_freshman"
        )
    for invalid_top_k in (True, "3"):
        with pytest.raises(ValueError):
            IndependentRetrieveRequest.model_validate(
                {**allowed, "top_k": invalid_top_k}
            )
        with pytest.raises(InvalidConfigurationError, match="top_k must be an integer"):
            build_independent_plan(
                rag_config,
                "Study planning steps",
                "university_freshman",
                top_k=invalid_top_k,
            )

    with pytest.raises(ValueError):
        IndependentRetrieveRequest.model_validate({**allowed, "query": "   "})
    with pytest.raises(ValueError):
        IndependentRetrieveRequest.model_validate(
            {**allowed, "query": "Contact student 123456789"}
        )


def test_independent_endpoint_does_not_hide_missing_configured_provider(
    rag_config,
) -> None:
    runtime = SimpleNamespace(config=rag_config, ready=True, stack={})
    app = FastAPI()
    attach_independent_routes(app, runtime)

    with TestClient(app) as client:
        response = client.post(
            "/internal/rag/independent-retrievals",
            json={
                "query": "Study planning steps",
                "target_population": "university_freshman",
            },
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "configured RAG provider is not ready"
