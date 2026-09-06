"""Explicit parser routing with no silent optional-provider fallback."""

from __future__ import annotations

from pathlib import Path

from .base import DocumentParser, ParserError


class ParserRouter:
    def __init__(self, parsers: dict[str, DocumentParser] | None = None) -> None:
        self._parsers = parsers or {}

    def register(self, suffix: str, parser: DocumentParser) -> None:
        self._parsers[suffix.lower().lstrip(".")] = parser

    def resolve(self, path: Path) -> DocumentParser:
        suffix = path.suffix.lower().lstrip(".")
        parser = self._parsers.get(suffix)
        if parser is None:
            raise ParserError(f"UNSUPPORTED_FILE_TYPE: .{suffix or 'unknown'}")
        return parser

