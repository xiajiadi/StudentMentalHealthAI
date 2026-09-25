"""Isolated RAG fixture and fresh-index provisioning for D4-3B.

Only evidence cards embedded in the approved D4-3A packet enter this temporary
index. Source annotation fields are retained verbatim in ``source_annotation``;
the RAG eligibility projection is marked as temporary evaluation use and is
never written back to the packet, D2 publication, or the product corpus.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from .approved_packet import load_approved_packet
from .manifest import ManifestError, build_approved_corpus_manifest, verify_corpus_manifest, write_json_once


class IsolatedRagError(RuntimeError):
    """The approved synthetic corpus cannot be safely indexed in isolation."""


def _write_lines_once(path: Path, records: list[Mapping[str, Any]]) -> str:
    payload = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for record in records).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise IsolatedRagError(f"temporary corpus file already differs: {path.name}")
    else:
        with path.open("xb") as handle:
            handle.write(payload)
    import hashlib

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def materialize_rag_inputs(
    corpus_manifest: Mapping[str, Any],
    *,
    work_dir: str | Path,
    repo_root: str | Path,
) -> dict[str, Any]:
    """Write a temporary embedding-ready fixture and bind its exact hashes."""

    verify_corpus_manifest(corpus_manifest)
    root = Path(repo_root).resolve()
    destination = Path(work_dir).resolve()
    try:
        destination.relative_to(root)
    except ValueError:
        pass
    else:
        raise IsolatedRagError("temporary corpus/index must be outside the project checkout")

    records = corpus_manifest.get("rag_embedding_records")
    if not isinstance(records, list) or len(records) != corpus_manifest.get("evidence_count"):
        raise IsolatedRagError("approved corpus has no complete RAG evaluation projection")
    record_ids = [record.get("chunk_id") for record in records if isinstance(record, Mapping)]
    if record_ids != corpus_manifest.get("evidence_ids"):
        raise IsolatedRagError("RAG projection IDs differ from the approved evidence allowlist")
    if any(not isinstance(record, Mapping) or record.get("metadata", {}).get("evaluation_only") is not True for record in records):
        raise IsolatedRagError("RAG projection contains a record without the evaluation-only marker")

    source_annotations = [record["metadata"].get("source_annotation", {}) for record in records]
    if any(not isinstance(item, Mapping) for item in source_annotations):
        raise IsolatedRagError("source annotation provenance is missing from a temporary RAG record")
    if any(item.get("source_review_state") != "HUMAN_REVIEW_REQUIRED" or item.get("source_human_gold") is not False for item in source_annotations):
        raise IsolatedRagError("temporary RAG projection no longer preserves the original pending source annotations")

    corpus_dir = destination / "corpus"
    docs_by_id = {
        record["document_id"]: {
            "document_id": record["document_id"],
            "category": "practice_guidance",
            "fixture_identity": "D4_3A_HUMAN_GOLD_SYNTHETIC_EVIDENCE",
            "evaluation_only": True,
        }
        for record in records
    }
    review_records = [
        {
            "chunk_id": record["chunk_id"],
            "publishable": True,
            "decision_scope": "D4_3B_TEMPORARY_EVALUATION_INDEX_ONLY",
            "source_packet_id": corpus_manifest["source_packet_id"],
            "source_packet_hash": corpus_manifest["source_packet_hash"],
        }
        for record in records
    ]
    hashes = {
        "embedding_ready_sha256": _write_lines_once(corpus_dir / "embedding_ready.jsonl", records),
        "documents_sha256": _write_lines_once(corpus_dir / "knowledge_documents.jsonl", list(docs_by_id.values())),
        "review_queue_sha256": _write_lines_once(corpus_dir / "review_queue.jsonl", review_records),
    }
    input_manifest: dict[str, Any] = {
        "schema_version": "d4-slice3b-rag-inputs.v1",
        "corpus_id": corpus_manifest["corpus_id"],
        "corpus_hash": corpus_manifest["corpus_hash"],
        "source_packet_id": corpus_manifest["source_packet_id"],
        "source_packet_hash": corpus_manifest["source_packet_hash"],
        "evidence_ids": record_ids,
        "evidence_count": len(records),
        "input_file_hashes": hashes,
        "source_annotations_preserved": True,
        "temporary_eligibility_scope": "D4_3B_TEMPORARY_EVALUATION_INDEX_ONLY",
        "d2_publication": False,
        "production_knowledge": False,
        "real_student_data": False,
    }
    import hashlib
    from harness.foundation.hashing import canonical_sha256_tag

    input_manifest["input_manifest_hash"] = canonical_sha256_tag(input_manifest, self_field="input_manifest_hash")
    write_json_once(destination / "rag-input-manifest.json", input_manifest)
    return {
        "root": destination,
        "corpus_dir": corpus_dir,
        "embedding_ready_path": corpus_dir / "embedding_ready.jsonl",
        "documents_path": corpus_dir / "knowledge_documents.jsonl",
        "review_queue_path": corpus_dir / "review_queue.jsonl",
        "input_manifest": input_manifest,
        "input_manifest_hash": input_manifest["input_manifest_hash"],
    }


def create_isolated_rag_app(
    corpus_manifest: Mapping[str, Any],
    *,
    repo_root: str | Path,
    work_dir: str | Path,
    rag_config_path: str | Path | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Create the accepted RAG API with a fresh local-only D4 synthetic index."""

    repo = Path(repo_root).resolve()
    module_root = repo / "05_rag-engine"
    src = module_root / "src"
    for candidate in (src,):
        if str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))

    # Prevent Hugging Face clients from attempting network access. Missing
    # local model files cause preflight failure; there is no download fallback.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    inputs = materialize_rag_inputs(corpus_manifest, work_dir=work_dir, repo_root=repo)
    config_path = Path(rag_config_path).resolve() if rag_config_path else module_root / "config" / "rag.v1.json"
    if not config_path.is_file():
        raise IsolatedRagError("accepted RAG config is unavailable")

    try:
        from rag_engine.api.app import RagRuntime, create_app
        from rag_engine.cli import _prepare_bm25
        from rag_engine.config import RAGConfig
        from rag_engine.embedding import BGEM3EmbeddingProvider
        from rag_engine.indexing import IndexBuilder, KnowledgeCorpusLoader
        from rag_engine.rerank import NoOpReranker
        from rag_engine.retrieval import RetrievalService
        from rag_engine.stores import ChromaVectorStore
        from harness.foundation.hashing import canonical_sha256_tag
    except ImportError as exc:
        raise IsolatedRagError(f"accepted RAG runtime dependencies are unavailable: {type(exc).__name__}") from exc

    corpus = KnowledgeCorpusLoader().load(
        inputs["embedding_ready_path"],
        documents_path=inputs["documents_path"],
        review_queue_path=inputs["review_queue_path"],
    )
    loaded_ids = sorted(record.chunk_id for record in corpus.records)
    if loaded_ids != sorted(corpus_manifest["evidence_ids"]) or corpus.excluded:
        raise IsolatedRagError("KnowledgeCorpusLoader changed or excluded the approved D4 temporary corpus")

    config = RAGConfig.load(config_path)
    work = Path(work_dir).resolve()
    collection_suffix = str(corpus_manifest["corpus_hash"]).split(":", 1)[-1][:16]
    stores = replace(
        config.stores,
        chroma_collection=f"d4_3b_{collection_suffix}",
        chroma_path=work / "fresh-index" / "chroma",
        qdrant_collection=f"d4_3b_{collection_suffix}",
        qdrant_path=work / "fresh-index" / "qdrant-unused",
        bm25_path=work / "fresh-index" / "bm25",
    )
    config = replace(
        config,
        stores=stores,
        raw={**(config.raw or config.to_dict()), "stores": stores.to_dict()},
    )
    embedding = BGEM3EmbeddingProvider(config.embedding, return_sparse=True)
    embedding_health = embedding.health_check(load=True)
    if embedding_health.get("status") != "ok":
        raise IsolatedRagError("accepted local BGE-M3 embedding provider is unavailable offline")

    bm25 = None
    bm25_manifest: Mapping[str, Any] | None = None
    if config.retrieval_mode in {"bm25", "hybrid"}:
        bm25, bm25_manifest, reused = _prepare_bm25(corpus, config, persist=False)
        if reused:
            raise IsolatedRagError("temporary BM25 index unexpectedly reused persisted state")

    vector_store = None
    build = None
    if config.retrieval_mode in {"dense", "hybrid"}:
        vector_store = ChromaVectorStore(config.stores.chroma_path, config.stores.chroma_collection)
        build = IndexBuilder(embedding, vector_store).build(
            corpus.records,
            config=config,
            index_dir=work / "fresh-index" / "index-manifest",
            excluded_count=0,
        )
        if build.reused or sorted(build.manifest.eligible_chunk_ids) != sorted(corpus_manifest["evidence_ids"]):
            raise IsolatedRagError("fresh Chroma index reused or contains an unexpected evidence set")

    manifest = build.manifest.to_dict() if build is not None else dict(bm25_manifest or {})
    if config.retrieval_mode == "hybrid":
        service = RetrievalService(
            embedding_provider=embedding,
            dense_store=vector_store,
            sparse_retriever=bm25,
            reranker=NoOpReranker(),
            index_manifest=manifest,
            rrf_k=config.rrf_k,
        )
    elif config.retrieval_mode == "dense":
        service = RetrievalService(
            embedding_provider=embedding,
            dense_store=vector_store,
            reranker=NoOpReranker(),
            index_manifest=manifest,
            rrf_k=config.rrf_k,
        )
    else:
        service = RetrievalService(
            embedding_provider=None,
            dense_store=None,
            sparse_retriever=bm25,
            reranker=NoOpReranker(),
            index_manifest=manifest,
            rrf_k=config.rrf_k,
        )
    stack_key = "hybrid_service" if config.retrieval_mode == "hybrid" else "dense_service"
    runtime = RagRuntime.__new__(RagRuntime)
    runtime.paths = {"config": config_path, "corpus": inputs["embedding_ready_path"], "documents": inputs["documents_path"], "review_queue": inputs["review_queue_path"]}
    runtime.config = config
    runtime.corpus = corpus
    runtime.stack = {"status": "ready", stack_key: service, "manifest": manifest}
    runtime.provider_report = {"embedding": {key: embedding_health.get(key) for key in ("status", "provider", "model_name", "model_version", "model_revision", "device", "precision")}}
    runtime.load_error = None

    def evaluation_health() -> dict[str, Any]:
        return {
            "status": "READY",
            "service": "rag",
            "retrieval_mode": config.retrieval_mode,
            "rerank_enabled": False,
            "corpus_version": corpus.corpus_version,
            "eligible_chunk_count": len(corpus.records),
            "evaluation_only": True,
            "synthetic_fixture_only": True,
            "index_id": manifest.get("index_id"),
            "index_reused": False,
            "eligible_chunk_ids": sorted(record.chunk_id for record in corpus.records),
            "index_manifest_hash": canonical_sha256_tag(manifest),
            "corpus_manifest_hash": corpus_manifest["corpus_hash"],
            "source_packet_id": corpus_manifest["source_packet_id"],
            "source_packet_hash": corpus_manifest["source_packet_hash"],
            "input_manifest_hash": inputs["input_manifest_hash"],
            "config_hash": config.config_hash,
            "base_config_path": str(config_path),
            "provider": runtime.provider_report,
        }

    runtime.health = evaluation_health
    app = create_app(runtime=runtime)
    service_identity = evaluation_health()
    return app, service_identity


def main() -> None:
    parser = argparse.ArgumentParser(description="Start a loopback-only isolated D4-3B RAG service")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--corpus-manifest")
    parser.add_argument("--packet", default=str(Path(__file__).resolve().parents[2] / "D4_3A_HUMAN_GOLD_REVIEW_PACKET.json"))
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--port", type=int, default=8170)
    parser.add_argument("--rag-config")
    args = parser.parse_args()
    if args.port < 1 or args.port > 65535:
        raise SystemExit("port must be 1..65535")
    if args.corpus_manifest:
        corpus_manifest = json.loads(Path(args.corpus_manifest).read_text(encoding="utf-8"))
    else:
        packet = load_approved_packet(args.packet)
        corpus_manifest = build_approved_corpus_manifest(packet)
        write_json_once(Path(args.work_dir).resolve() / "corpus-manifest.json", corpus_manifest)
    app, identity = create_isolated_rag_app(
        corpus_manifest,
        repo_root=args.repo_root,
        work_dir=args.work_dir,
        rag_config_path=args.rag_config,
    )
    if identity.get("eligible_chunk_ids") != corpus_manifest.get("evidence_ids"):
        raise SystemExit("fresh evaluation index identity check failed")
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit("uvicorn is required in the accepted RAG environment") from exc
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
