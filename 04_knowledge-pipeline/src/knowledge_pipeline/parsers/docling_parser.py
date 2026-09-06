"""Docling adapter for PDF, DOCX and other supported office/web formats."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from ..config import PipelineConfig
from ..domain.block import Block
from ..domain.document import CanonicalDocument
from ..domain.source import SourceRecord
from ..utils import content_hash, first_non_empty, normalize_text, stable_id
from .base import DocumentParser, ParserError, ParserUnavailableError, metadata_from_mapping


def _label(item: Any) -> str:
    value = getattr(item, "label", "other")
    value = getattr(value, "value", value)
    return str(value).lower().replace("-", "_")


def _page_bounds(item: Any) -> tuple[int | None, int | None]:
    pages: list[int] = []
    for provenance in getattr(item, "prov", []) or []:
        page = getattr(provenance, "page_no", None)
        if isinstance(page, int) and page > 0:
            pages.append(page)
    if not pages:
        return None, None
    return min(pages), max(pages)


def _item_text(item: Any, document: Any) -> str:
    prefer_export = _label(item) == "table"
    exporter = getattr(item, "export_to_markdown", None)
    if prefer_export and callable(exporter):
        for kwargs in ({"doc": document}, {}):
            try:
                exported = exporter(**kwargs)
            except TypeError:
                continue
            if isinstance(exported, str) and exported.strip():
                return normalize_text(exported)
    value = getattr(item, "text", None)
    if isinstance(value, str) and value.strip():
        return normalize_text(value)
    if callable(exporter):
        for kwargs in ({"doc": document}, {}):
            try:
                exported = exporter(**kwargs)
            except TypeError:
                continue
            if isinstance(exported, str) and exported.strip():
                return normalize_text(exported)
    return ""


class DoclingParser(DocumentParser):
    """Use Docling's maintained converter; downstream sees only canonical blocks."""

    name = "docling"

    def __init__(self, converter: Any | None = None) -> None:
        self._converter = converter
        self._version = self._resolve_version()

    @staticmethod
    def _resolve_version() -> str:
        try:
            module = importlib.import_module("docling")
        except ImportError:
            return "unavailable"
        return str(getattr(module, "__version__", "unknown"))

    @property
    def version(self) -> str:
        return self._version

    def _get_converter(self) -> Any:
        if self._converter is not None:
            return self._converter
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as exc:
            raise ParserUnavailableError("DOCLING_NOT_INSTALLED") from exc
        self._converter = DocumentConverter()
        return self._converter

    def parse(self, source: SourceRecord, config: PipelineConfig) -> CanonicalDocument:
        converter = self._get_converter()
        try:
            result = converter.convert(source.path)
        except Exception as exc:  # document-level boundary; caller records the concrete error
            raise ParserError(f"DOCLING_CONVERSION_FAILED: {type(exc).__name__}: {exc}") from exc
        document = getattr(result, "document", None)
        if document is None:
            raise ParserError("DOCLING_DOCUMENT_EMPTY")
        metadata = metadata_from_mapping(
            source.metadata,
            config=config,
            input_mode=source.input_mode,
        )
        blocks: list[Block] = []
        heading_stack: list[str] = []
        item_count = 0
        table_count = 0
        iterator = getattr(document, "iterate_items", None)
        items = iterator() if callable(iterator) else []
        for item, level in items:
            item_count += 1
            raw_label = _label(item)
            text = _item_text(item, document)
            if not text:
                continue
            page_start, page_end = _page_bounds(item)
            is_heading = raw_label in {"section_header", "title", "heading"}
            try:
                numeric_level = int(level) + 1
            except (TypeError, ValueError):
                numeric_level = 1
            if is_heading:
                numeric_level = max(1, min(numeric_level, 6))
                heading_stack = heading_stack[: numeric_level - 1]
                heading_stack.append(text)
                kind = "heading"
                heading_level: int | None = numeric_level
            elif raw_label in {"text", "paragraph", "formula"}:
                kind = "paragraph"
                heading_level = None
            elif raw_label in {"list_item", "list"}:
                kind = "list"
                heading_level = None
            elif raw_label in {"table"}:
                kind = "table"
                heading_level = None
                table_count += 1
            elif raw_label in {"caption", "figure_caption"}:
                kind = "figure_caption"
                heading_level = None
            else:
                kind = "other"
                heading_level = None
            block_id = stable_id("BLOCK", source.source_hash, len(blocks), kind, text, page_start)
            blocks.append(
                Block(
                    block_id,
                    kind,
                    text,
                    heading_level,
                    tuple(heading_stack),
                    page_start,
                    page_end,
                    {"docling_label": raw_label, "item_index": item_count},
                )
            )
        title = first_non_empty(
            [
                metadata.extra.get("title") if isinstance(metadata.extra, dict) else None,
                next((block.text for block in blocks if block.kind == "heading"), None),
                Path(source.filename).stem,
            ],
            default=Path(source.filename).stem,
        )
        if not blocks:
            markdown_export = ""
            exporter = getattr(document, "export_to_markdown", None)
            if callable(exporter):
                markdown_export = normalize_text(exporter())
            if not markdown_export:
                raise ParserError("DOCLING_NO_TEXT_BLOCKS")
        else:
            markdown_export = ""
            exporter = getattr(document, "export_to_markdown", None)
            if callable(exporter):
                try:
                    markdown_export = normalize_text(exporter())
                except Exception:
                    markdown_export = ""
        json_keys: list[str] = []
        json_exporter = getattr(document, "export_to_dict", None)
        if callable(json_exporter):
            try:
                json_value = json_exporter()
                if isinstance(json_value, dict):
                    json_keys = sorted(str(key) for key in json_value)
            except Exception:
                json_keys = []
        native_chunk_count: int | None = None
        try:
            from docling.chunking import HierarchicalChunker

            native_chunk_count = sum(1 for _ in HierarchicalChunker().chunk(document))
        except (ImportError, TypeError, ValueError):
            # Native chunking is evidence/baseline only; domain strategies do
            # not depend on parser-specific objects.
            native_chunk_count = None
        document_id = stable_id("KB", source.source_hash, source.source_id, config.pipeline_version, config.config_hash, title)
        parser_metadata = {
            "format": source.file_type,
            "conversion_status": str(getattr(getattr(result, "status", None), "value", getattr(result, "status", "unknown"))),
            "item_count": item_count,
            "block_count": len(blocks),
            "table_count": table_count,
            "docling_markdown_hash": content_hash(markdown_export) if markdown_export else None,
            "docling_json_keys": json_keys,
            "docling_hierarchical_chunk_count": native_chunk_count,
            "representation": "DoclingDocument v2",
        }
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
            parser_metadata=parser_metadata,
            native_document=document,
        )
