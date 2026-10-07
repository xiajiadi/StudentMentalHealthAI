from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import rag_engine.api.app as rag_app
from rag_engine.api.app import RagRuntime, create_app


def test_explicit_bm25_profile_serves_real_sparse_retrieval_without_embeddings(
    tmp_path: Path, monkeypatch, rag_config, sample_records
) -> None:
    corpus_path = tmp_path / "m0_demo" / "embedding_ready.jsonl"
    documents_path = tmp_path / "m0_demo" / "knowledge_documents.jsonl"
    review_path = tmp_path / "m0_demo" / "review_queue.jsonl"
    corpus_path.parent.mkdir(parents=True)
    corpus_path.write_text(
        "".join(
            json.dumps(
                {
                    "chunk_id": record.chunk_id,
                    "document_id": record.document_id,
                    "text": record.text,
                    "context_text": record.context_text,
                    "metadata": record.metadata,
                },
                ensure_ascii=False,
            )
            + "\n"
            for record in sample_records
        ),
        encoding="utf-8",
    )
    documents_path.write_text("", encoding="utf-8")
    review_path.write_text("", encoding="utf-8")

    config_value = rag_config.to_dict()
    config_value["environment"] = "demo"
    config_value["retrieval_mode"] = "bm25"
    config_path = tmp_path / "config" / "rag.m0-demo-bm25.v1.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(config_value), encoding="utf-8")
    monkeypatch.setenv("SMHAI_RAG_CONFIG", str(config_path))
    monkeypatch.setattr(
        rag_app,
        "_default_input_paths",
        lambda: {
            "config": config_path,
            "corpus": corpus_path,
            "documents": documents_path,
            "review_queue": review_path,
        },
    )

    runtime = RagRuntime()
    runtime.load()
    assert runtime.ready
    assert runtime.health()["retrieval_mode"] == "bm25"
    assert runtime.health()["provider"]["bm25s"]["provider"] == "bm25s"

    application = create_app(runtime=runtime)
    with TestClient(application) as client:
        ready = client.get("/health/ready")
        assert ready.status_code == 200
        capabilities = client.get("/capabilities")
        assert capabilities.json()["retrieval_mode"] == "bm25"
        assert capabilities.json()["publication_boundary"] == (
            "configured Knowledge embedding-ready export"
        )
        response = client.post(
            "/internal/rag/retrievals",
            headers={"X-Request-ID": "REQ_m0_bm25", "X-Trace-ID": "TRACE_m0_bm25"},
            json={
                "assessment": {
                    "schema_version": "assessment.v1",
                    "assessment_id": "ASSESS_m0_bm25",
                    "subject_id": "SUBJ_m0_bm25",
                    "population_scope": "K12学生",
                    "status": "completed",
                    "dimensions": {"stress": {"band": "unknown"}},
                    "risk": {"level": "normal", "need_human_review": False},
                },
                "target_role": "student",
                "query": "压力对要求与资源的主观体验",
                "top_k": 3,
                "target_population": "K12学生",
            },
        )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["trace"]["sparse_enabled"] is True
    assert data["trace"]["sparse_hits"]
    assert data["chunks"]
    assert data["chunks"][0]["chunk_id"] == "CHUNK_test_theory_001"
    citation = data["citations"]["citations"][0]
    assert citation["chunk_id"] == "CHUNK_test_theory_001"
    assert citation["source_file"] == "theory.md"
    assert citation["section"] == "压力"
