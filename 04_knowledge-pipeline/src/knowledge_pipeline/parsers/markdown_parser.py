"""Curated Markdown parser with YAML front matter and manual chunk markers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from ..config import PipelineConfig
from ..domain.block import Block
from ..domain.document import CanonicalDocument
from ..domain.source import SourceRecord
from ..utils import normalize_text, stable_id
from .base import DocumentParser, ParserError, metadata_from_mapping


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_CHUNK_MARKER = re.compile(r"^\s*<!--\s*chunk(?::\s*([^>]+?))?\s*-->\s*$", re.IGNORECASE)
_LIST = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+|[一二三四五六七八九十百]+[、.]\s+)")
_TABLE = re.compile(r"^\s*\|.*\|\s*$")


def _front_matter(raw: str) -> tuple[dict[str, Any], str]:
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.startswith("---\n"):
        return {}, normalized
    match = re.search(r"\n---\s*\n", normalized[4:])
    if not match:
        raise ParserError("MARKDOWN_FRONT_MATTER_INVALID: closing delimiter missing")
    end = match.start() + 4
    header = normalized[4:end]
    body = normalized[end + len("\n---\n") :]
    values = yaml.safe_load(header) or {}
    if not isinstance(values, dict):
        raise ParserError("MARKDOWN_FRONT_MATTER_INVALID: YAML must be an object")
    return dict(values), body


def _flush_block(
    blocks: list[Block],
    lines: list[str],
    *,
    kind: str,
    heading_path: tuple[str, ...],
    source: SourceRecord,
    index: int,
    manual_chunk_id: str | None,
) -> int:
    text = normalize_text("\n".join(lines))
    if not text:
        return index
    metadata: dict[str, Any] = {}
    if manual_chunk_id:
        metadata["manual_chunk_id"] = manual_chunk_id
    block_id = stable_id("BLOCK", source.source_hash, index, kind, text)
    blocks.append(Block(block_id, kind, text, None, heading_path, None, None, metadata))
    return index + 1


class MarkdownCuratedParser(DocumentParser):
    name = "markdown-curated"

    @property
    def version(self) -> str:
        return "1.0.0"

    def parse(self, source: SourceRecord, config: PipelineConfig) -> CanonicalDocument:
        try:
            raw = source.path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ParserError(f"MARKDOWN_ENCODING_INVALID: {exc}") from exc
        front, body = _front_matter(raw)
        metadata = metadata_from_mapping(
            front,
            config=config,
            input_mode=source.input_mode,
            fallback_language=front.get("language"),
        )
        title = str(front.get("title") or "")
        blocks: list[Block] = []
        heading_stack: list[str] = []
        pending: list[str] = []
        pending_kind = "paragraph"
        manual_chunk_id: str | None = None
        index = 0

        def flush() -> None:
            nonlocal index, pending
            index = _flush_block(
                blocks,
                pending,
                kind=pending_kind,
                heading_path=tuple(heading_stack),
                source=source,
                index=index,
                manual_chunk_id=manual_chunk_id,
            )
            pending = []

        lines = body.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]
            marker = _CHUNK_MARKER.match(line)
            if marker:
                flush()
                manual_chunk_id = (marker.group(1) or f"manual-{len(blocks) + 1}").strip()
                i += 1
                continue
            heading = _HEADING.match(line)
            if heading:
                flush()
                level = len(heading.group(1))
                heading_text = normalize_text(heading.group(2))
                if not title and level == 1:
                    title = heading_text
                heading_stack = heading_stack[: level - 1]
                heading_stack.append(heading_text)
                block_id = stable_id("BLOCK", source.source_hash, index, "heading", heading_text)
                metadata_value: dict[str, Any] = {}
                if manual_chunk_id:
                    metadata_value["manual_chunk_id"] = manual_chunk_id
                blocks.append(
                    Block(
                        block_id,
                        "heading",
                        heading_text,
                        level,
                        tuple(heading_stack),
                        None,
                        None,
                        metadata_value,
                    )
                )
                index += 1
                i += 1
                continue
            if not line.strip():
                flush()
                i += 1
                continue
            if _TABLE.match(line):
                flush()
                table_lines = [line]
                i += 1
                while i < len(lines) and _TABLE.match(lines[i]) and lines[i].strip():
                    table_lines.append(lines[i])
                    i += 1
                pending_kind = "table"
                index = _flush_block(
                    blocks,
                    table_lines,
                    kind="table",
                    heading_path=tuple(heading_stack),
                    source=source,
                    index=index,
                    manual_chunk_id=manual_chunk_id,
                )
                pending_kind = "paragraph"
                continue
            if _LIST.match(line):
                if pending and pending_kind != "list":
                    flush()
                pending_kind = "list"
                pending.append(line)
                i += 1
                continue
            if pending and pending_kind == "list":
                flush()
            pending_kind = "paragraph"
            pending.append(line)
            i += 1
        flush()
        if not title:
            title = Path(source.filename).stem
        if not title.strip():
            raise ParserError("MARKDOWN_TITLE_MISSING")
        if source.input_mode == "curated" and not metadata.human_curated:
            raise ParserError("CURATED_MARKDOWN_FLAG_MISSING: human_curated=true is required")
        document_id = stable_id("KB", source.source_hash, source.source_id, config.pipeline_version, config.config_hash, title)
        return CanonicalDocument(
            document_id=document_id,
            title=title,
            source=source,
            language=metadata.language or config.default_language,
            blocks=blocks,
            metadata=metadata,
            parser=self.name,
            parser_version=self.version,
            pipeline_version=config.pipeline_version,
            parser_metadata={
                "format": "markdown",
                "front_matter": bool(front),
                "manual_chunk_markers": sum(1 for block in blocks if "manual_chunk_id" in block.metadata),
            },
        )
