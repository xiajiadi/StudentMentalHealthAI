"""Parser adapters that all return :class:`CanonicalDocument`."""

from .base import DocumentParser, ParserError, ParserUnavailableError
from .docling_parser import DoclingParser
from .markdown_parser import MarkdownCuratedParser
from .mineru_parser import MinerUParser
from .router import ParserRouter

__all__ = [
    "DocumentParser",
    "DoclingParser",
    "MarkdownCuratedParser",
    "MinerUParser",
    "ParserError",
    "ParserRouter",
    "ParserUnavailableError",
]

