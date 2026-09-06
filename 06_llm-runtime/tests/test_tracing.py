from __future__ import annotations

import json

from jsonschema import Draft202012Validator

from llm_runtime.observability.tracing import StructuredRuntimeLogger


def test_structured_logger_matches_frozen_logging_v1(module_root):
    schema = json.loads(
        (module_root.parent / "00_architecture" / "schemas" / "logging.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    record = StructuredRuntimeLogger().emit(
        event="GENERATION_COMPLETED",
        request_id="REQ_trace_001",
        trace_id="TRACE_trace_001",
        outcome="success",
        entity_refs={"generation_id": "GEN_trace_001"},
        metadata={"operation": "generation", "dependency": "ollama", "unexpected": "dropped"},
    )

    assert list(Draft202012Validator(schema).iter_errors(record)) == []
    assert "unexpected" not in record["metadata"]
