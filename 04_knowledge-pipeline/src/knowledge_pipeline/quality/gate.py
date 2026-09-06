"""Quality checks that produce actionable PASS/WARN/FAIL evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from ..config import ChunkConfig
from ..domain.chunk import KnowledgeChunk
from ..domain.document import CanonicalDocument
from ..utils import estimate_tokens

QualityStatus = Literal["PASS", "WARN", "FAIL"]
Severity = Literal["WARN", "FAIL"]


@dataclass(frozen=True)
class QualityIssue:
    code: str
    severity: Severity
    message: str
    document_id: str | None = None
    chunk_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "details": self.details,
        }


@dataclass
class QualityReport:
    status: QualityStatus
    issues: list[QualityIssue] = field(default_factory=list)

    @property
    def pass_count(self) -> int:
        return 1 if self.status == "PASS" else 0

    @property
    def warn_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "WARN")

    @property
    def fail_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "FAIL")

    def add(self, issue: QualityIssue) -> None:
        self.issues.append(issue)
        if issue.severity == "FAIL":
            self.status = "FAIL"
        elif self.status == "PASS":
            self.status = "WARN"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "pass": self.pass_count,
            "warn": self.warn_count,
            "fail": self.fail_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


class QualityGate:
    def __init__(self, config: ChunkConfig) -> None:
        self.config = config

    def evaluate(
        self,
        document: CanonicalDocument,
        chunks: list[KnowledgeChunk],
        *,
        duplicate_source: bool = False,
        duplicate_chunk_ids: set[str] | None = None,
        contract_errors: dict[str, list[str]] | None = None,
    ) -> QualityReport:
        report = QualityReport("PASS")
        doc_id = document.document_id
        if not document.blocks or not document.normalized_text:
            report.add(QualityIssue("EMPTY_DOCUMENT", "FAIL", "document has no usable text", doc_id))
        if not document.source.source_hash or not document.source.source_id:
            report.add(QualityIssue("MISSING_SOURCE_PROVENANCE", "FAIL", "source id/hash is missing", doc_id))
        if not document.source.filename:
            report.add(QualityIssue("MISSING_SOURCE_FILENAME", "FAIL", "source filename is missing", doc_id))
        if not document.metadata.organization:
            report.add(QualityIssue("MISSING_SOURCE_ORGANIZATION", "FAIL", "source organization is not declared", doc_id))
        if not document.metadata.population_scope:
            report.add(QualityIssue("MISSING_POPULATION_SCOPE", "FAIL", "population_scope is not declared", doc_id))
        if document.metadata.rights_status != "verified":
            report.add(
                QualityIssue(
                    "RIGHTS_NOT_VERIFIED",
                    "WARN",
                    "rights status prevents automatic publication",
                    doc_id,
                    details={"rights_status": document.metadata.rights_status},
                )
            )
        if document.metadata.review_status != "approved":
            report.add(
                QualityIssue(
                    "REVIEW_PENDING",
                    "WARN",
                    "document is not approved for production publication",
                    doc_id,
                    details={"review_status": document.metadata.review_status},
                )
            )
        if duplicate_source:
            report.add(QualityIssue("DUPLICATE_SOURCE", "WARN", "same source hash appeared more than once", doc_id))
        if any("\ufffd" in block.text for block in document.blocks):
            report.add(QualityIssue("REPLACEMENT_CHARACTER", "WARN", "replacement character suggests decoding loss", doc_id))
        if any(
            block.kind != "table" and re.search(r"[^\w\s]{6,}", block.text, re.UNICODE)
            for block in document.blocks
        ):
            report.add(QualityIssue("SUSPICIOUS_OCR", "WARN", "long punctuation/symbol run may indicate OCR noise", doc_id))
        self._hierarchy_checks(document, report)
        if not chunks:
            report.add(QualityIssue("EMPTY_CHUNK_SET", "FAIL", "no chunks were produced", doc_id))
        for chunk in chunks:
            if not chunk.text.strip():
                report.add(QualityIssue("EMPTY_CHUNK", "FAIL", "chunk text is empty", doc_id, chunk.chunk_id))
                continue
            token_count = estimate_tokens(chunk.text)
            if token_count < self.config.min_tokens:
                report.add(
                    QualityIssue(
                        "CHUNK_TOO_SHORT",
                        "WARN",
                        "chunk is below the configured minimum token baseline",
                        doc_id,
                        chunk.chunk_id,
                        {"token_count": token_count, "min_tokens": self.config.min_tokens},
                    )
                )
            if token_count > self.config.max_tokens:
                report.add(
                    QualityIssue(
                        "CHUNK_TOO_LONG",
                        "FAIL",
                        "chunk exceeds the configured maximum token limit",
                        doc_id,
                        chunk.chunk_id,
                        {"token_count": token_count, "max_tokens": self.config.max_tokens},
                    )
                )
            if not chunk.metadata.get("layer"):
                report.add(QualityIssue("MISSING_LAYER", "FAIL", "chunk layer is missing", doc_id, chunk.chunk_id))
            if duplicate_chunk_ids and chunk.chunk_id in duplicate_chunk_ids:
                report.add(QualityIssue("DUPLICATE_CONTENT", "WARN", "normalized chunk content is duplicated", doc_id, chunk.chunk_id))
        for object_id, errors in (contract_errors or {}).items():
            for error in errors:
                report.add(QualityIssue("CONTRACT_INVALID", "FAIL", error, doc_id, object_id))
        return report

    @staticmethod
    def _hierarchy_checks(document: CanonicalDocument, report: QualityReport) -> None:
        previous: int | None = None
        for block in document.blocks:
            if block.kind != "heading" or block.heading_level is None:
                continue
            if previous is not None and block.heading_level > previous + 1:
                report.add(
                    QualityIssue(
                        "MALFORMED_HIERARCHY",
                        "WARN",
                        "heading level skips a structural level",
                        document.document_id,
                        details={"previous_level": previous, "current_level": block.heading_level},
                    )
                )
            previous = block.heading_level
