"""Serve one fresh, non-Human-Gold synthetic corpus for D4SMOKE."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="serve a temporary D4SMOKE-only synthetic RAG corpus")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--corpus-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--corpus-id", required=True)
    parser.add_argument("--index-id", required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--port", type=int, default=8170)
    args = parser.parse_args()

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    repo = args.repo_root.resolve(strict=True)
    corpus_dir = args.corpus_dir.resolve(strict=True)
    work_dir = args.work_dir.resolve()
    if corpus_dir.is_relative_to(repo) or work_dir.is_relative_to(repo):
        raise RuntimeError("D4SMOKE corpus and fresh index must stay outside the repository")

    rag_root = repo / "05_rag-engine"
    rag_src = rag_root / "src"
    if str(rag_src) not in sys.path:
        sys.path.insert(0, str(rag_src))

    from rag_engine.api.app import RagRuntime, create_app
    from rag_engine.cli import _prepare_bm25
    from rag_engine.config import RAGConfig
    from rag_engine.embedding import BGEM3EmbeddingProvider
    from rag_engine.indexing import IndexBuilder, KnowledgeCorpusLoader
    from rag_engine.rerank import NoOpReranker
    from rag_engine.retrieval import RetrievalService
    from rag_engine.stores import ChromaVectorStore

    corpus = KnowledgeCorpusLoader().load(
        corpus_dir / "embedding_ready.jsonl",
        documents_path=corpus_dir / "knowledge_documents.jsonl",
        review_queue_path=corpus_dir / "review_queue.jsonl",
    )
    if len(corpus.records) != 1 or corpus.excluded:
        raise RuntimeError("D4SMOKE RAG corpus must contain one synthetic record and no exclusions")

    config_path = rag_root / "config" / "rag.v1.json"
    config = RAGConfig.load(config_path)
    suffix = hashlib.sha256(
        (args.corpus_id + _sha256(corpus_dir / "embedding_ready.jsonl")).encode("utf-8")
    ).hexdigest()[:16]
    stores = replace(
        config.stores,
        chroma_collection=f"d4_smoke_{suffix}",
        chroma_path=work_dir / "fresh-index" / "chroma",
        qdrant_collection=f"d4_smoke_{suffix}",
        qdrant_path=work_dir / "fresh-index" / "qdrant-unused",
        bm25_path=work_dir / "fresh-index" / "bm25",
    )
    config = replace(
        config,
        stores=stores,
        raw={**(config.raw or config.to_dict()), "stores": stores.to_dict()},
    )
    embedding = BGEM3EmbeddingProvider(config.embedding, return_sparse=True)
    embedding_health = embedding.health_check(load=True)
    if embedding_health.get("status") != "ok":
        raise RuntimeError("offline BGE-M3 embedding provider did not become ready")

    sparse = None
    manifest: dict[str, Any] = {}
    if config.retrieval_mode in {"bm25", "hybrid"}:
        sparse, manifest, reused = _prepare_bm25(corpus, config, persist=False)
        if reused:
            raise RuntimeError("D4SMOKE must not reuse a BM25 index")
    dense = None
    build = None
    if config.retrieval_mode in {"dense", "hybrid"}:
        dense = ChromaVectorStore(config.stores.chroma_path, config.stores.chroma_collection)
        build = IndexBuilder(embedding, dense).build(
            corpus.records,
            config=config,
            index_dir=work_dir / "fresh-index" / "index-manifest",
        )
        if build.reused or len(build.manifest.eligible_chunk_ids) != 1:
            raise RuntimeError("D4SMOKE must build a fresh index with exactly one eligible record")
        manifest = build.manifest.to_dict()

    if config.retrieval_mode == "hybrid":
        service = RetrievalService(
            embedding_provider=embedding,
            dense_store=dense,
            sparse_retriever=sparse,
            reranker=NoOpReranker(),
            index_manifest=manifest,
            rrf_k=config.rrf_k,
        )
        service_key = "hybrid_service"
    elif config.retrieval_mode == "dense":
        service = RetrievalService(
            embedding_provider=embedding,
            dense_store=dense,
            reranker=NoOpReranker(),
            index_manifest=manifest,
            rrf_k=config.rrf_k,
        )
        service_key = "dense_service"
    else:
        service = RetrievalService(
            embedding_provider=None,
            dense_store=None,
            sparse_retriever=sparse,
            reranker=NoOpReranker(),
            index_manifest=manifest,
            rrf_k=config.rrf_k,
        )
        service_key = "sparse_service"

    embedding_file = corpus_dir / "embedding_ready.jsonl"
    documents_file = corpus_dir / "knowledge_documents.jsonl"
    review_file = corpus_dir / "review_queue.jsonl"
    input_manifest_hash = hashlib.sha256(
        (_sha256(embedding_file) + _sha256(documents_file) + _sha256(review_file)).encode("ascii")
    ).hexdigest()
    corpus_manifest_hash = hashlib.sha256(
        (args.corpus_id + input_manifest_hash + args.source_id).encode("ascii")
    ).hexdigest()

    runtime = RagRuntime.__new__(RagRuntime)
    runtime.paths = {
        "config": config_path,
        "corpus": embedding_file,
        "documents": documents_file,
        "review_queue": review_file,
    }
    runtime.config = config
    runtime.corpus = corpus
    runtime.stack = {"status": "ready", service_key: service, "manifest": manifest}
    runtime.provider_report = {
        "embedding": {
            key: embedding_health.get(key)
            for key in (
                "status",
                "provider",
                "model_name",
                "model_version",
                "model_revision",
                "device",
                "precision",
            )
        }
    }
    runtime.load_error = None

    def health() -> dict[str, Any]:
        index_hash = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return {
            "status": "READY",
            "service": "rag",
            "retrieval_mode": config.retrieval_mode,
            "rerank_enabled": False,
            "corpus_version": corpus.corpus_version,
            "eligible_chunk_count": 1,
            "evaluation_only": True,
            "synthetic_fixture_only": True,
            "corpus_id": args.corpus_id,
            "index_id": args.index_id,
            "index_reused": False,
            "eligible_chunk_ids": sorted(item.chunk_id for item in corpus.records),
            "index_manifest_hash": "sha256:" + index_hash,
            "corpus_manifest_hash": "sha256:" + corpus_manifest_hash,
            "input_manifest_hash": "sha256:" + input_manifest_hash,
            "source_identity": args.source_id,
            "config_hash": config.config_hash,
            "base_config_path": str(config_path),
            "provider": runtime.provider_report,
        }

    runtime.health = health
    import uvicorn

    uvicorn.run(create_app(runtime=runtime), host="127.0.0.1", port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
