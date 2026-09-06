"""Optional MinerU adapter boundary; it is never silently used as a fallback."""

from __future__ import annotations

import importlib.util
import shutil
from typing import Any

from ..config import PipelineConfig
from ..domain.document import CanonicalDocument
from ..domain.source import SourceRecord
from .base import DocumentParser, ParserUnavailableError


class MinerUParser(DocumentParser):
    name = "mineru"

    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable or shutil.which("mineru")

    @property
    def version(self) -> str:
        try:
            from mineru.version import __version__
        except (ImportError, AttributeError):
            return "unavailable"
        return str(__version__)

    @property
    def available(self) -> bool:
        return self.executable is not None or importlib.util.find_spec("mineru") is not None

    def parse(self, source: SourceRecord, config: PipelineConfig) -> CanonicalDocument:
        if not self.available:
            raise ParserUnavailableError("MINERU_NOT_INSTALLED: optional provider is not enabled")
        raise ParserUnavailableError(
            "MINERU_ADAPTER_PENDING: provider discovery is explicit; no unverified CLI output is accepted"
        )

