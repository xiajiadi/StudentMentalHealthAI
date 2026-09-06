"""Validate mapped CAT output against the repository's frozen assessment schema."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from ..domain.errors import ContractValidationError


def _schema_path() -> Path:
    """Resolve the shared assessment schema without copying or modifying it."""

    return Path(__file__).resolve().parents[4] / "00_architecture" / "schemas" / "assessment.v1.schema.json"


def validate_assessment_v1(
    assessment: Mapping[str, Any],
    schema_path: str | Path | None = None,
) -> None:
    """Raise ContractValidationError unless `assessment` validates."""

    try:
        import jsonschema
    except ImportError as exc:
        raise ContractValidationError("jsonschema is required for assessment.v1 validation") from exc
    selected_path = Path(schema_path) if schema_path else _schema_path()
    try:
        schema = json.loads(selected_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractValidationError(f"cannot load assessment schema: {exc}") from exc
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    errors = sorted(validator_cls(schema).iter_errors(dict(assessment)), key=lambda error: list(error.path))
    if errors:
        messages = "; ".join(error.message for error in errors)
        raise ContractValidationError(f"assessment.v1 validation failed: {messages}")

