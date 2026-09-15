"""Validation against the repository's frozen v1 JSON Schemas."""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any, cast

import jsonschema

from .errors import PromptRefusal

_JSONSCHEMA: Any = cast(Any, jsonschema)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@cache
def _validator(schema_name: str) -> Any:
    path = _repo_root() / "00_architecture" / "schemas" / f"{schema_name}.schema.json"
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PromptRefusal("CONTRACT_SCHEMA_UNAVAILABLE") from exc
    validator_cls = _JSONSCHEMA.validators.validator_for(schema)
    try:
        validator_cls.check_schema(schema)
    except _JSONSCHEMA.exceptions.SchemaError as exc:
        raise PromptRefusal("CONTRACT_SCHEMA_INVALID") from exc
    return validator_cls(schema)


def _validate(value: object, schema_name: str, reason_code: str) -> None:
    if not isinstance(value, Mapping):
        raise PromptRefusal(reason_code)
    try:
        errors = list(_validator(schema_name).iter_errors(dict(value)))
    except (TypeError, ValueError) as exc:
        raise PromptRefusal(reason_code) from exc
    if errors:
        raise PromptRefusal(reason_code)


def validate_assessment(value: object) -> None:
    _validate(value, "assessment.v1", "ASSESSMENT_SCHEMA_INVALID")
    if not isinstance(value, Mapping) or value.get("schema_version") != "assessment.v1":
        raise PromptRefusal("ASSESSMENT_SCHEMA_INVALID")


def validate_generation_request(value: object) -> None:
    _validate(value, "generation.v1", "GENERATION_REQUEST_SCHEMA_INVALID")
    if not isinstance(value, Mapping):
        raise PromptRefusal("GENERATION_REQUEST_SCHEMA_INVALID")
    required = {
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
    if not required.issubset(value):
        raise PromptRefusal("GENERATION_REQUEST_SCHEMA_INVALID")
    if value.get("schema_version") != "generation.v1":
        raise PromptRefusal("GENERATION_REQUEST_SCHEMA_INVALID")


def validate_knowledge_chunk(value: object) -> None:
    _validate(value, "knowledge.v1", "KNOWLEDGE_CHUNK_SCHEMA_INVALID")
    if not isinstance(value, Mapping) or value.get("schema_version") != "knowledge.v1":
        raise PromptRefusal("KNOWLEDGE_CHUNK_SCHEMA_INVALID")
    if "chunk_id" not in value or "text" not in value:
        raise PromptRefusal("KNOWLEDGE_CHUNK_SCHEMA_INVALID")
