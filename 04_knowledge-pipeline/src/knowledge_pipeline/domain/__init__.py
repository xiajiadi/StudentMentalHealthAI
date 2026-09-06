"""Canonical domain objects for document ingestion."""

from .block import Block, BlockType
from .chunk import KnowledgeChunk
from .document import CanonicalDocument, DocumentMetadata
from .source import SourceRecord, SourceRequest

__all__ = [
    "Block",
    "BlockType",
    "CanonicalDocument",
    "DocumentMetadata",
    "KnowledgeChunk",
    "SourceRecord",
    "SourceRequest",
]

