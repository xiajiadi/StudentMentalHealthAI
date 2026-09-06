from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from knowledge_pipeline.config import PipelineConfig
from knowledge_pipeline.logging_support import make_log_record


MODULE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = MODULE_ROOT.parent


def test_yaml_config_is_versioned_and_hashable() -> None:
    config = PipelineConfig.from_file(MODULE_ROOT / "config" / "pipeline.v1.yaml")
    assert config.pipeline_version == "0.1.0"
    assert config.chunk.max_tokens == 160
    assert config.config_hash.startswith("sha256:")
    assert config.config_hash == PipelineConfig.from_file(MODULE_ROOT / "config" / "pipeline.v1.yaml").config_hash


def test_stage_log_matches_frozen_logging_schema() -> None:
    schema = json.loads((PROJECT_ROOT / "00_architecture/schemas/logging.v1.schema.json").read_text(encoding="utf-8"))
    record = make_log_record(
        run_id="RUN_test",
        document_id="KB_test",
        stage="parse",
        status="success",
        duration_ms=12,
    )
    jsonschema.validators.validator_for(schema)(schema).validate(record)
    assert record["metadata"]["operation"] == "parse"
    assert "document_id" not in record

