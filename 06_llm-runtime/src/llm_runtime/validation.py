"""Strict structured-output validation at the runtime boundary."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .errors import LLMRuntimeError, RuntimeErrorCode


def parse_and_validate(text: str, schema: Mapping[str, Any]) -> Any:
    """Parse JSON and validate its meaning against a JSON Schema.

    A syntactically valid but schema-invalid object is a runtime failure. The
    validator is deliberately kept after provider generation so each provider
    gets the same semantic acceptance rule.
    """

    # Deliberately do not strip Markdown fences or surrounding prose. A
    # provider-native structured response must be valid JSON as returned;
    # repairing arbitrary text would turn an invalid candidate into a false
    # success and would make provenance/audit behavior ambiguous.
    candidate_text = text.strip()
    try:
        value = json.loads(candidate_text)
    except json.JSONDecodeError as exc:
        raise LLMRuntimeError(
            RuntimeErrorCode.INVALID_STRUCTURED_OUTPUT,
            "Provider output is not valid JSON.",
            details={"validation": "json_parse", "line": exc.lineno, "column": exc.colno},
        ) from exc
    try:
        from jsonschema import Draft202012Validator

        validator = Draft202012Validator(dict(schema))
        errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    except ImportError as exc:  # pragma: no cover - dependency is declared in pyproject
        raise LLMRuntimeError(
            RuntimeErrorCode.RUNTIME_ERROR,
            "Structured-output validation dependency is unavailable.",
        ) from exc
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.path) or "$"
        raise LLMRuntimeError(
            RuntimeErrorCode.INVALID_STRUCTURED_OUTPUT,
            "Provider output failed the requested JSON Schema.",
            details={"validation": "json_schema", "path": path, "reason": first.message[:300]},
        )
    return value


def example_for_schema(schema: Mapping[str, Any]) -> Any:
    """Build a small deterministic fixture value for the Mock Provider."""

    if "const" in schema:
        return schema["const"]
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    schema_type = schema.get("type")
    if schema_type == "object" or "properties" in schema:
        properties = schema.get("properties", {})
        required = schema.get("required", list(properties))
        return {
            name: example_for_schema(properties[name])
            for name in required
            if name in properties
        }
    if schema_type == "array":
        return [example_for_schema(schema.get("items", {}))]
    if schema_type == "integer":
        return int(schema.get("minimum", 0))
    if schema_type == "number":
        return float(schema.get("minimum", 0))
    if schema_type == "boolean":
        return False
    return "synthetic"

