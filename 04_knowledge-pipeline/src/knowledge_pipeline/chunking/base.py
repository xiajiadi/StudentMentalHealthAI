"""Common chunk construction; strategies decide semantic boundaries."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from typing import Any

from ..config import ChunkConfig
from ..domain.block import Block
from ..domain.chunk import KnowledgeChunk, document_source_context
from ..domain.document import CanonicalDocument
from ..utils import content_hash, estimate_tokens, normalize_text, stable_id


class ChunkingError(RuntimeError):
    """Invalid structure or configuration for a document."""


class ChunkStrategy(ABC):
    name = "base"
    version = "1.0.0"

    def __init__(self, config: ChunkConfig) -> None:
        self.config = config

    @abstractmethod
    def chunk(self, document: CanonicalDocument) -> list[KnowledgeChunk]:
        """Chunk a canonical document without accessing parser-specific objects."""

    def _manual_units(self, document: CanonicalDocument) -> list[list[Block]]:
        """Preserve curator-declared chunk groups before any secondary splitting."""

        if not any(block.metadata.get("manual_chunk_id") for block in document.blocks):
            return []
        groups: list[list[Block]] = []
        current: list[Block] = []
        current_id: str | None = None
        for block in document.blocks:
            marker = block.metadata.get("manual_chunk_id")
            if marker and current and marker != current_id:
                groups.append(current)
                current = []
            if marker:
                current_id = str(marker)
            elif current and current_id is not None and block.kind == "heading":
                # A heading after a manual marker remains part of that manual unit.
                pass
            current.append(block)
        if current:
            groups.append(current)
        return groups

    @staticmethod
    def _block_text(block: Block) -> str:
        return block.text.strip()

    def _unit_text(self, blocks: Sequence[Block]) -> str:
        return normalize_text("\n\n".join(self._block_text(block) for block in blocks if self._block_text(block)))

    def _split_long_text(self, text: str) -> list[str]:
        """Secondary boundary splitter, reached only after semantic grouping."""

        if estimate_tokens(text) <= self.config.max_tokens:
            return [text]
        paragraphs = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
        sentences: list[str] = []
        for paragraph in paragraphs:
            parts = [part.strip() for part in re.split(r"(?<=[。！？!?；;])\s*", paragraph) if part.strip()]
            sentences.extend(parts or [paragraph])
        pieces: list[str] = []
        current: list[str] = []
        current_tokens = 0
        for sentence in sentences:
            sentence_tokens = estimate_tokens(sentence)
            if current and current_tokens + sentence_tokens > self.config.max_tokens:
                pieces.append("\n".join(current))
                current = []
                current_tokens = 0
            if sentence_tokens > self.config.max_tokens:
                pieces.extend(self._hard_split(sentence))
                continue
            current.append(sentence)
            current_tokens += sentence_tokens
        if current:
            pieces.append("\n".join(current))
        return pieces or [text]

    def _hard_split(self, text: str) -> list[str]:
        """Last-resort boundary for one overlong sentence; never the primary algorithm."""

        pieces: list[str] = []
        start = 0
        while start < len(text):
            end = min(len(text), start + max(16, self.config.max_tokens * 2))
            candidate = text[start:end].strip()
            while len(candidate) > 1 and estimate_tokens(candidate) > self.config.max_tokens:
                end -= max(1, len(candidate) // 8)
                candidate = text[start:end].strip()
            if not candidate:
                break
            pieces.append(candidate)
            start = end
        return pieces or [text]

    def _make_chunks(
        self,
        document: CanonicalDocument,
        units: Iterable[tuple[list[Block], str]],
    ) -> list[KnowledgeChunk]:
        chunks: list[KnowledgeChunk] = []
        for unit_index, (blocks, semantic_context) in enumerate(units):
            if not blocks:
                continue
            original_text = self._unit_text(blocks)
            if not original_text:
                continue
            split_texts = self._split_long_text(original_text)
            first = blocks[0]
            last = blocks[-1]
            heading_path = tuple(first.heading_path or last.heading_path)
            section = heading_path[-1] if heading_path else "document"
            page_values = [
                page
                for block in blocks
                for page in (block.page_start, block.page_end)
                if isinstance(page, int) and page > 0
            ]
            page_start = min(page_values) if page_values else None
            page_end = max(page_values) if page_values else None
            for split_index, text in enumerate(split_texts):
                token_count = estimate_tokens(text)
                location_key = f"{section}|{page_start}|{page_end}|{unit_index}|{split_index}"
                chunk_id = stable_id(
                    "CHUNK",
                    document.document_id,
                    self.name,
                    self.version,
                    location_key,
                    text,
                )
                metadata = self._metadata(document, chunk_id, heading_path, section, page_start, page_end, token_count)
                metadata["content_hash"] = content_hash(text)
                metadata["semantic_context"] = semantic_context or None
                metadata["semantic_unit_index"] = unit_index
                metadata["split_index"] = split_index
                manual_ids = {str(block.metadata["manual_chunk_id"]) for block in blocks if block.metadata.get("manual_chunk_id")}
                if len(manual_ids) == 1:
                    metadata["manual_chunk_id"] = next(iter(manual_ids))
                context = document_source_context(document, heading_path, semantic_context)
                chunks.append(
                    KnowledgeChunk(
                        chunk_id=chunk_id,
                        document_id=document.document_id,
                        text=text,
                        context_text=f"{context}\n\n{text}",
                        blocks=list(blocks),
                        section=section,
                        heading_path=heading_path,
                        page_start=page_start,
                        page_end=page_end,
                        strategy=self.name,
                        chunker_version=self.version,
                        metadata=metadata,
                    )
                )
        return chunks

    def _metadata(
        self,
        document: CanonicalDocument,
        chunk_id: str,
        heading_path: tuple[str, ...],
        section: str,
        page_start: int | None,
        page_end: int | None,
        token_count: int,
    ) -> dict[str, Any]:
        doc_meta = document.metadata
        authority = doc_meta.authority_level
        if authority is None:
            authority = {
                "policy": "high",
                "theory": "high",
                "practice_guidance": "medium",
                "referral": "high",
            }.get(doc_meta.category, "unknown")
        metadata = {
            "document_id": document.document_id,
            "chunk_id": chunk_id,
            "layer": "knowledge",
            "title": document.title,
            "author": doc_meta.author,
            "organization": doc_meta.organization,
            "year": doc_meta.published_year,
            "language": document.language,
            "target_population": list(doc_meta.population_scope),
            "topic": doc_meta.topic,
            "role_scope": list(doc_meta.role_scope),
            "authority_level": authority,
            "source_url": doc_meta.source_url,
            "source_filename": document.source.filename,
            "source_hash": document.source.source_hash,
            "page_start": page_start,
            "page_end": page_end,
            "section": section,
            "heading_path": list(heading_path),
            "parser": document.parser,
            "parser_version": document.parser_version,
            "chunker": self.name,
            "chunker_version": self.version,
            "pipeline_version": document.pipeline_version,
            "human_curated": doc_meta.human_curated,
            "review_status": doc_meta.review_status,
            "rights_status": doc_meta.rights_status,
            "risk_scope": list(doc_meta.risk_scope),
            "content_hash": None,
            "token_count": token_count,
            "embedding_status": "not_indexed",
        }
        review_semantics = doc_meta.extra.get("review_semantics")
        if review_semantics is not None:
            metadata["review_semantics"] = str(review_semantics)
        return metadata
