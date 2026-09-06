from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_pipeline.chunking import PolicyChunkStrategy
from knowledge_pipeline.config import ChunkConfig, PipelineConfig
from knowledge_pipeline.domain.source import SourceRecord, SourceRequest
from knowledge_pipeline.parsers.markdown_parser import MarkdownCuratedParser
from knowledge_pipeline.validation.contracts import ContractValidator
from knowledge_pipeline.validation.mapping import to_contract_chunk, to_contract_document


MODULE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = MODULE_ROOT.parent


def test_contract_projection_passes_and_extra_field_fails() -> None:
    config = PipelineConfig(chunk=ChunkConfig(min_tokens=4, target_tokens=40, max_tokens=160))
    source = SourceRecord.from_request(SourceRequest(MODULE_ROOT / "fixtures/policy/policy.md", input_mode="curated"))
    document = MarkdownCuratedParser().parse(source, config)
    chunk = PolicyChunkStrategy(config.chunk).chunk(document)[0]
    validator = ContractValidator(PROJECT_ROOT)

    validator.validate(to_contract_document(document))
    validator.validate(to_contract_chunk(chunk))
    invalid = to_contract_chunk(chunk)
    invalid["context_text"] = chunk.context_text
    with pytest.raises(ValueError):
        validator.validate(invalid)


def test_frozen_schema_fixture_still_validates() -> None:
    validator = ContractValidator(PROJECT_ROOT)
    for name in ("valid_knowledge_document.json", "valid_knowledge_chunk.json"):
        value = json.loads((PROJECT_ROOT / "00_architecture" / "fixtures" / name).read_text(encoding="utf-8"))
        validator.validate(value)

