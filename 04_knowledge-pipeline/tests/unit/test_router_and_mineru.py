from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_pipeline.config import PipelineConfig
from knowledge_pipeline.domain.source import SourceRecord, SourceRequest
from knowledge_pipeline.parsers.base import ParserUnavailableError
from knowledge_pipeline.parsers.mineru_parser import MinerUParser
from knowledge_pipeline.parsers.router import ParserRouter


MODULE_ROOT = Path(__file__).resolve().parents[2]


def test_router_rejects_unsupported_format() -> None:
    router = ParserRouter()
    with pytest.raises(Exception, match="UNSUPPORTED_FILE_TYPE"):
        router.resolve(Path("input.bin"))


def test_mineru_is_explicitly_pending_when_not_installed() -> None:
    parser = MinerUParser(executable=None)
    if parser.available:
        pytest.skip("MinerU is available in this environment; integration evidence must be captured separately")
    source = SourceRecord.from_request(SourceRequest(MODULE_ROOT / "fixtures/policy/policy.md"))
    with pytest.raises(ParserUnavailableError, match="MINERU_NOT_INSTALLED"):
        parser.parse(source, PipelineConfig())

