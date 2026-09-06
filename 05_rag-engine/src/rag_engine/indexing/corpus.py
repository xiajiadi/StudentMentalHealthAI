"""Load the Knowledge pipeline's embedding-ready boundary without changing it."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..domain import KnowledgeRecord
from ..exceptions import CorpusValidationError


@dataclass(frozen=True)
class CorpusLoadResult:
    records: tuple[KnowledgeRecord, ...]
    excluded: tuple[dict[str, Any], ...]
    source_path: Path
    document_count: int

    @property
    def corpus_version(self) -> str:
        from ..domain import stable_digest

        values = [
            {
                "chunk_id": record.chunk_id,
                "document_id": record.document_id,
                "content_hash": record.content_hash,
                "text": record.text,
                "context_text": record.context_text,
            }
            for record in sorted(self.records, key=lambda item: item.chunk_id)
        ]
        return f"sha256:{stable_digest(values)}"


class KnowledgeCorpusLoader:
    def load(
        self,
        embedding_ready_path: str | Path,
        *,
        documents_path: str | Path | None = None,
        review_queue_path: str | Path | None = None,
    ) -> CorpusLoadResult:
        source_path = Path(embedding_ready_path).resolve()
        if not source_path.exists():
            raise CorpusValidationError(f"Knowledge embedding-ready file does not exist: {source_path}", code="KNOWLEDGE_EXPORT_MISSING")
        category_by_document = self._document_categories(documents_path)
        review_by_chunk = self._review_records(review_queue_path)
        records: list[KnowledgeRecord] = []
        excluded: list[dict[str, Any]] = []
        seen: set[str] = set()
        try:
            lines = source_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise CorpusValidationError(f"Cannot read Knowledge export {source_path}: {exc}", code="KNOWLEDGE_EXPORT_READ_FAILED") from exc
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                if not isinstance(value, Mapping):
                    raise ValueError("record is not an object")
                record = KnowledgeRecord.from_embedding_record(value, category_by_document=category_by_document)
            except (json.JSONDecodeError, ValueError, CorpusValidationError) as exc:
                excluded.append({"line": line_number, "reason": "invalid_record", "detail": str(exc)})
                continue
            if record.chunk_id in seen:
                excluded.append({"chunk_id": record.chunk_id, "reason": "duplicate_chunk_id", "line": line_number})
                continue
            seen.add(record.chunk_id)
            decision = review_by_chunk.get(record.chunk_id)
            if decision is not None and not bool(decision.get("publishable")):
                excluded.append({"chunk_id": record.chunk_id, "reason": "knowledge_review_not_publishable"})
                continue
            if record.review_status != "approved":
                excluded.append({"chunk_id": record.chunk_id, "reason": f"review_status={record.review_status}"})
                continue
            if record.rights_status != "verified":
                excluded.append({"chunk_id": record.chunk_id, "reason": f"rights_status={record.rights_status}"})
                continue
            if not record.role_scope or not record.target_population or not record.risk_scope:
                excluded.append({"chunk_id": record.chunk_id, "reason": "missing_filter_metadata"})
                continue
            records.append(record)
        if not records:
            raise CorpusValidationError("No eligible Knowledge chunks were found", code="KNOWLEDGE_CORPUS_EMPTY")
        return CorpusLoadResult(
            records=tuple(records),
            excluded=tuple(excluded),
            source_path=source_path,
            document_count=len(category_by_document),
        )

    @staticmethod
    def _document_categories(path: str | Path | None) -> dict[str, str]:
        if path is None:
            return {}
        result: dict[str, str] = {}
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, Mapping) and value.get("document_id"):
                result[str(value["document_id"])] = str(value.get("category") or "")
        return result

    @staticmethod
    def _review_records(path: str | Path | None) -> dict[str, dict[str, Any]]:
        if path is None or not Path(path).exists():
            return {}
        result: dict[str, dict[str, Any]] = {}
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, Mapping) and value.get("chunk_id"):
                result[str(value["chunk_id"])] = dict(value)
        return result
