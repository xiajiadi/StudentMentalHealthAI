"""The single downstream document abstraction used by all parsers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..utils import content_hash, normalized_for_hash
from .block import Block
from .source import SourceRecord


@dataclass
class DocumentMetadata:
    """Metadata explicitly supplied by a curator or source registry."""

    organization: str | None = None
    author: str | None = None
    published_year: int | None = None
    language: str | None = None
    population_scope: list[str] = field(default_factory=list)
    category: str = "other"
    rights_status: str = "unknown"
    review_status: str = "pending"
    role_scope: list[str] = field(default_factory=lambda: ["student", "teacher", "parent"])
    risk_scope: list[str] = field(default_factory=lambda: ["normal", "attention"])
    topic: str | None = None
    authority_level: str | None = None
    source_url: str | None = None
    human_curated: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "organization": self.organization,
            "author": self.author,
            "published_year": self.published_year,
            "language": self.language,
            "population_scope": list(self.population_scope),
            "category": self.category,
            "rights_status": self.rights_status,
            "review_status": self.review_status,
            "role_scope": list(self.role_scope),
            "risk_scope": list(self.risk_scope),
            "topic": self.topic,
            "authority_level": self.authority_level,
            "source_url": self.source_url,
            "human_curated": self.human_curated,
            "extra": self.extra,
        }


@dataclass
class CanonicalDocument:
    document_id: str
    title: str
    source: SourceRecord
    language: str
    blocks: list[Block]
    metadata: DocumentMetadata
    parser: str
    parser_version: str
    pipeline_version: str
    parser_metadata: dict[str, Any] = field(default_factory=dict)
    native_document: Any = field(default=None, repr=False, compare=False)

    @property
    def content_hash(self) -> str:
        content = "\n".join(block.text for block in self.blocks if block.text.strip())
        return content_hash(content)

    @property
    def normalized_text(self) -> str:
        return normalized_for_hash("\n".join(block.text for block in self.blocks))

    @property
    def heading_paths(self) -> list[list[str]]:
        return [list(block.heading_path) for block in self.blocks if block.heading_path]

    def to_internal_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "title": self.title,
            "source_id": self.source.source_id,
            "source_hash": self.source.source_hash,
            "language": self.language,
            "blocks": [block.to_dict() for block in self.blocks],
            "metadata": self.metadata.to_dict(),
            "parser": self.parser,
            "parser_version": self.parser_version,
            "pipeline_version": self.pipeline_version,
            "content_hash": self.content_hash,
            "parser_metadata": self.parser_metadata,
        }

