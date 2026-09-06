"""Internal chunk object; contract projection and embedding record are separate."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..utils import content_hash
from .block import Block
from .document import CanonicalDocument


@dataclass
class KnowledgeChunk:
    chunk_id: str
    document_id: str
    text: str
    context_text: str
    blocks: list[Block]
    section: str
    heading_path: tuple[str, ...]
    page_start: int | None
    page_end: int | None
    strategy: str
    chunker_version: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        return content_hash(self.text)

    @property
    def token_count(self) -> int:
        return int(self.metadata.get("token_count", 0))

    def to_embedding_record(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "text": self.text,
            "context_text": self.context_text,
            "metadata": dict(self.metadata),
        }

    def to_internal_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "text": self.text,
            "context_text": self.context_text,
            "section": self.section,
            "heading_path": list(self.heading_path),
            "page_start": self.page_start,
            "page_end": self.page_end,
            "strategy": self.strategy,
            "chunker_version": self.chunker_version,
            "content_hash": self.content_hash,
            "token_count": self.token_count,
            "metadata": dict(self.metadata),
        }


def document_source_context(document: CanonicalDocument, heading_path: tuple[str, ...], extra: str = "") -> str:
    path = " > ".join(heading_path) if heading_path else "document"
    source = document.metadata.organization or "unknown"
    lines = [
        f"Document: {document.title}",
        f"Source: {source} ({document.source.filename})",
        f"Section: {path}",
    ]
    if extra:
        lines.append(extra)
    return "\n".join(lines)

