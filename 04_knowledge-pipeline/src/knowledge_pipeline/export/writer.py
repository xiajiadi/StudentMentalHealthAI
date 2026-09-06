"""Write contract projections, audit records, and no-vector embedding input."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import PipelineConfig
from ..dedup.detector import DuplicateReport
from ..domain.chunk import KnowledgeChunk
from ..domain.document import CanonicalDocument
from ..domain.source import SourceRecord
from ..quality.gate import QualityReport
from ..review.gate import ReviewGate
from ..utils import canonical_json
from ..validation.mapping import to_contract_chunk, to_contract_document


@dataclass(frozen=True)
class ExportResult:
    output_dir: Path
    document_count: int
    chunk_count: int
    embedding_ready_count: int
    manifest: dict[str, Any]


def _write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    path.write_text("".join(canonical_json(value) + "\n" for value in values), encoding="utf-8")


def write_run_exports(
    *,
    output_dir: Path,
    run_id: str,
    timestamp: str,
    config: PipelineConfig,
    sources: list[SourceRecord],
    documents: list[CanonicalDocument],
    chunks: list[KnowledgeChunk],
    quality_by_document: dict[str, QualityReport],
    duplicates: DuplicateReport,
    review_gate: ReviewGate,
    document_runs: list[dict[str, Any]],
    logs: list[dict[str, Any]],
) -> ExportResult:
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    contract_documents = [to_contract_document(document) for document in documents]
    contract_chunks = [to_contract_chunk(chunk) for chunk in chunks]
    embedding_ready = [
        chunk.to_embedding_record()
        for chunk in chunks
        if review_gate.is_publishable(
            chunk,
            quality_status=quality_by_document.get(chunk.document_id, QualityReport("FAIL")).status,
        )
    ]
    review_records = [
        review_gate.to_record(
            chunk,
            quality_status=quality_by_document.get(chunk.document_id, QualityReport("FAIL")).status,
        )
        for chunk in chunks
    ]
    issues = [
        issue.to_dict()
        for report in quality_by_document.values()
        for issue in report.issues
    ]
    _write_jsonl(output_dir / "knowledge_documents.jsonl", contract_documents)
    _write_jsonl(output_dir / "knowledge_chunks.jsonl", contract_chunks)
    _write_jsonl(output_dir / "embedding_ready.jsonl", embedding_ready)
    _write_jsonl(output_dir / "review_queue.jsonl", review_records)
    _write_jsonl(output_dir / "quality_issues.jsonl", issues)
    _write_jsonl(output_dir / "pipeline_logs.jsonl", logs)
    source_values: list[dict[str, Any]] = []
    for source in sources:
        primary = duplicates.source_primary.get(source.source_hash)
        source_values.append(source.to_manifest_dict(primary if primary and primary != source.source_id else None))
    quality_counts = {
        "pass": sum(1 for report in quality_by_document.values() if report.status == "PASS"),
        "warn": sum(1 for report in quality_by_document.values() if report.status == "WARN"),
        "fail": sum(1 for report in quality_by_document.values() if report.status == "FAIL")
        + sum(1 for item in document_runs if item.get("status") == "PARSE_FAILED"),
    }
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "pipeline_version": config.pipeline_version,
        "timestamp": timestamp,
        "contract_release": config.contract_release,
        "config_hash": config.config_hash,
        "config": config.as_dict(),
        "sources": source_values,
        "documents": document_runs,
        "chunks": {
            "total": len(chunks),
            "embedding_ready": len(embedding_ready),
            "contract_file": "knowledge_chunks.jsonl",
            "embedding_file": "embedding_ready.jsonl",
        },
        "pass": quality_counts["pass"],
        "warn": quality_counts["warn"],
        "fail": quality_counts["fail"],
        "duplicates": duplicates.to_dict(),
        "parser_versions": sorted({document.parser: document.parser_version for document in documents}.items()),
        "chunker_versions": sorted({chunk.strategy: chunk.chunker_version for chunk in chunks}.items()),
        "quality_issue_count": len(issues),
        "parse_failed_count": sum(1 for item in document_runs if item.get("status") == "PARSE_FAILED"),
        "no_embeddings_generated": True,
        "document_stage_events": document_runs,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return ExportResult(output_dir, len(documents), len(chunks), len(embedding_ready), manifest)
