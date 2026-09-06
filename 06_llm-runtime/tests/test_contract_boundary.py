from __future__ import annotations

import json

from jsonschema import Draft202012Validator


def test_runtime_request_serializes_to_frozen_generation_v1(request_factory):
    request = request_factory()
    payload = request.to_contract_request()
    schema_path = __import__("pathlib").Path(__file__).resolve().parents[2] / "00_architecture" / "schemas" / "generation.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    errors = list(Draft202012Validator(schema).iter_errors(payload))
    assert errors == []
    assert set(payload) == {
        "schema_version",
        "generation_id",
        "assessment_id",
        "subject_id",
        "target_role",
        "purpose",
        "language",
        "safety_mode",
        "retrieval",
        "prompt_ref",
        "model_policy",
    }

