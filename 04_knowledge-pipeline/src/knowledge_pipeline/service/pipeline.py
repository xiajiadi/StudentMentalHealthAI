"""Batch orchestration with document-level failure isolation."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..chunking import InterventionChunkStrategy, PolicyChunkStrategy, TheoryChunkStrategy
from ..config import PipelineConfig
from ..dedup.detector import DuplicateReport, detect_duplicates
from ..domain.chunk import KnowledgeChunk
from ..domain.document import CanonicalDocument
from ..domain.source import SourceRecord, SourceRequest, assert_raw_is_read_only
from ..export.writer import ExportResult, write_run_exports
from ..logging_support import make_log_record
from ..parsers import DoclingParser, MarkdownCuratedParser, MinerUParser, ParserError, ParserRouter
from ..quality.gate import QualityGate, QualityReport
from ..review.gate import ReviewGate
from ..utils import stable_id
from ..validation.contracts import ContractValidator
from ..validation.mapping import to_contract_chunk, to_contract_document


@dataclass
class PipelineRun:
    run_id: str
    timestamp: str
    sources: list[SourceRecord] = field(default_factory=list)
    documents: list[CanonicalDocument] = field(default_factory=list)
    chunks: list[KnowledgeChunk] = field(default_factory=list)
    quality_by_document: dict[str, QualityReport] = field(default_factory=dict)
    duplicates: DuplicateReport = field(default_factory=DuplicateReport)
    document_runs: list[dict[str, Any]] = field(default_factory=list)
    logs: list[dict[str, Any]] = field(default_factory=list)
    export: ExportResult | None = None


class KnowledgePipeline:
    """The public V0.1 service: intake -> parse -> canonical -> curate -> export."""

    def __init__(
        self,
        *,
        schema_root: Path,
        config: PipelineConfig | None = None,
        router: ParserRouter | None = None,
        raw_root: Path | None = None,
    ) -> None:
        self.config = config or PipelineConfig()
        self.schema_root = Path(schema_root).resolve()
        self.raw_root = Path(raw_root).resolve() if raw_root else None
        self.validator = ContractValidator(self.schema_root)
        self.router = router or ParserRouter()
        if router is None:
            docling = DoclingParser()
            self.router.register("pdf", docling)
            self.router.register("docx", docling)
            self.router.register("html", docling)
            self.router.register("htm", docling)
            self.router.register("md", MarkdownCuratedParser())
            self.router.register("markdown", MarkdownCuratedParser())
            self.router.register("mineru", MinerUParser())
        self.strategies = {
            "policy": PolicyChunkStrategy(self.config.chunk),
            "theory": TheoryChunkStrategy(self.config.chunk),
            "practice_guidance": InterventionChunkStrategy(self.config.chunk),
            "referral": InterventionChunkStrategy(self.config.chunk),
            "other": InterventionChunkStrategy(self.config.chunk),
        }
        self.quality_gate = QualityGate(self.config.chunk)
        self.review_gate = ReviewGate(self.config.allow_test_auto_approve)

    def run(
        self,
        requests: list[SourceRequest],
        *,
        output_dir: Path,
        timestamp: str | None = None,
        run_id: str | None = None,
    ) -> PipelineRun:
        timestamp = timestamp or datetime.now(UTC).isoformat().replace("+00:00", "Z")
        output_path = Path(output_dir).resolve()
        if self.raw_root:
            try:
                output_path.relative_to(self.raw_root)
            except ValueError:
                pass
            else:
                raise ValueError("RAW_IMMUTABLE: output directory cannot be inside data/raw")
        records = [SourceRecord.from_request(request) for request in requests]
        run_id = run_id or stable_id("RUN", self.config.pipeline_version, self.config.config_hash, *(record.source_hash for record in records))
        run = PipelineRun(run_id=run_id, timestamp=timestamp, sources=records)
        source_hash_counts: dict[str, int] = {}
        for record in records:
            source_hash_counts[record.source_hash] = source_hash_counts.get(record.source_hash, 0) + 1

        for source in records:
            assert_raw_is_read_only(source.path, self.raw_root)
            self._process_source(run, source, duplicate_source=source_hash_counts[source.source_hash] > 1)
        run.duplicates = detect_duplicates(run.sources, run.chunks)
        duplicate_ids = {chunk_id for ids in run.duplicates.duplicate_chunks.values() for chunk_id in ids}
        for document_id, report in run.quality_by_document.items():
            for chunk in (chunk for chunk in run.chunks if chunk.document_id == document_id):
                if chunk.chunk_id in duplicate_ids and not any(issue.chunk_id == chunk.chunk_id and issue.code == "DUPLICATE_CONTENT" for issue in report.issues):
                    from ..quality.gate import QualityIssue

                    report.add(QualityIssue("DUPLICATE_CONTENT", "WARN", "normalized chunk content is duplicated", document_id, chunk.chunk_id))
        invalid_objects = {
            issue.chunk_id or issue.document_id
            for report in run.quality_by_document.values()
            for issue in report.issues
            if issue.code == "CONTRACT_INVALID"
        }
        export_documents = [document for document in run.documents if document.document_id not in invalid_objects]
        export_chunks = [chunk for chunk in run.chunks if chunk.chunk_id not in invalid_objects and chunk.document_id in {document.document_id for document in export_documents}]
        run.export = write_run_exports(
            output_dir=output_path,
            run_id=run.run_id,
            timestamp=run.timestamp,
            config=self.config,
            sources=run.sources,
            documents=export_documents,
            chunks=export_chunks,
            quality_by_document=run.quality_by_document,
            duplicates=run.duplicates,
            review_gate=self.review_gate,
            document_runs=run.document_runs,
            logs=run.logs,
        )
        return run

    def _process_source(self, run: PipelineRun, source: SourceRecord, *, duplicate_source: bool) -> None:
        started = time.perf_counter()
        parser_name = "unknown"
        stage_events: list[dict[str, Any]] = []
        try:
            parser = self.router.resolve(source.path)
            parser_name = parser.name
            parse_started = time.perf_counter()
            document = parser.parse(source, self.config)
            parse_duration_ms = int((time.perf_counter() - parse_started) * 1000)
            run.logs.append(make_log_record(run_id=run.run_id, document_id=document.document_id, stage="parse", status="success", duration_ms=parse_duration_ms))
            stage_events.append({"stage": "parse", "status": "success", "duration_ms": parse_duration_ms, "parser": parser_name})
            strategy = self.strategies.get(document.metadata.category, self.strategies["other"])
            chunk_started = time.perf_counter()
            chunks = strategy.chunk(document)
            chunk_duration_ms = int((time.perf_counter() - chunk_started) * 1000)
            run.logs.append(make_log_record(run_id=run.run_id, document_id=document.document_id, stage="chunk", status="success", duration_ms=chunk_duration_ms))
            stage_events.append({"stage": "chunk", "status": "success", "duration_ms": chunk_duration_ms, "chunker": strategy.name, "chunk_count": len(chunks)})
            contract_errors: dict[str, list[str]] = {}
            for value, object_id in [(to_contract_document(document), document.document_id), *( (to_contract_chunk(chunk), chunk.chunk_id) for chunk in chunks )]:
                errors = self.validator.errors(value)
                if errors:
                    contract_errors[object_id] = errors
            report = self.quality_gate.evaluate(
                document,
                chunks,
                duplicate_source=duplicate_source,
                contract_errors=contract_errors,
            )
            run.documents.append(document)
            run.chunks.extend(chunks)
            run.quality_by_document[document.document_id] = report
            total_duration_ms = int((time.perf_counter() - started) * 1000)
            stage_events.append({"stage": "quality", "status": report.status, "duration_ms": 0, "issue_count": len(report.issues)})
            run.logs.append(make_log_record(run_id=run.run_id, document_id=document.document_id, stage="quality", status="warning" if report.status == "WARN" else "success" if report.status == "PASS" else "failed", duration_ms=0, error_code="QUALITY_FAILED" if report.status == "FAIL" else None))
            stage_events.append({"stage": "total", "status": report.status, "duration_ms": total_duration_ms})
            run.document_runs.append({
                "document_id": document.document_id,
                "source_id": source.source_id,
                "filename": source.filename,
                "status": "PROCESSED",
                "parser": parser_name,
                "parser_version": document.parser_version,
                "chunk_count": len(chunks),
                "quality": report.to_dict(),
                "stage_events": stage_events,
                "error": None,
            })
        except (ParserError, OSError, ValueError) as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            code = getattr(exc, "code", "DOCUMENT_FAILED")
            run.logs.append(make_log_record(run_id=run.run_id, document_id=None, stage="parse", status="failed", duration_ms=duration_ms, error_code=code))
            run.document_runs.append({
                "document_id": None,
                "source_id": source.source_id,
                "filename": source.filename,
                "status": "PARSE_FAILED",
                "parser": parser_name,
                "parser_version": None,
                "chunk_count": 0,
                "quality": {"status": "FAIL", "pass": 0, "warn": 0, "fail": 1, "issues": [{"code": code, "severity": "FAIL", "message": str(exc)}]},
                "stage_events": [{"stage": "parse", "status": "failed", "duration_ms": duration_ms}],
                "error": {"code": code, "message": str(exc)},
            })
