"""Detect file and content duplicates while preserving every provenance record."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.chunk import KnowledgeChunk
from ..domain.source import SourceRecord


@dataclass
class DuplicateReport:
    duplicate_sources: dict[str, list[str]] = field(default_factory=dict)
    duplicate_chunks: dict[str, list[str]] = field(default_factory=dict)
    source_primary: dict[str, str] = field(default_factory=dict)
    chunk_primary: dict[str, str] = field(default_factory=dict)

    @property
    def source_duplicate_count(self) -> int:
        return sum(max(0, len(items) - 1) for items in self.duplicate_sources.values())

    @property
    def chunk_duplicate_count(self) -> int:
        return sum(max(0, len(items) - 1) for items in self.duplicate_chunks.values())

    def to_dict(self) -> dict[str, object]:
        return {
            "source_duplicates": self.duplicate_sources,
            "chunk_duplicates": self.duplicate_chunks,
            "source_duplicate_count": self.source_duplicate_count,
            "chunk_duplicate_count": self.chunk_duplicate_count,
        }


def detect_duplicates(sources: list[SourceRecord], chunks: list[KnowledgeChunk]) -> DuplicateReport:
    report = DuplicateReport()
    by_source_hash: dict[str, list[SourceRecord]] = {}
    for source in sources:
        by_source_hash.setdefault(source.source_hash, []).append(source)
    for source_hash, records in by_source_hash.items():
        ids = [record.source_id for record in records]
        report.source_primary[source_hash] = ids[0]
        if len(ids) > 1:
            report.duplicate_sources[source_hash] = ids

    by_content_hash: dict[str, list[KnowledgeChunk]] = {}
    for chunk in chunks:
        by_content_hash.setdefault(chunk.content_hash, []).append(chunk)
    for hash_value, records in by_content_hash.items():
        ids = [chunk.chunk_id for chunk in records]
        report.chunk_primary[hash_value] = ids[0]
        if len(ids) > 1:
            report.duplicate_chunks[hash_value] = ids
    return report

