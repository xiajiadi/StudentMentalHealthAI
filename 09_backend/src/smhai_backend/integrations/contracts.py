"""Read-only validation against the frozen root schemas."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from smhai_backend.core.errors import ErrorCode, error


def project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "00_architecture").is_dir():
            return parent
    raise RuntimeError("StudentMentalHealthAI project root not found")


def schema_path(name: str) -> Path:
    return project_root() / "00_architecture" / "schemas" / name


def validate_frozen(schema_name: str, value: dict[str, Any]) -> None:
    try:
        schema = json.loads(schema_path(schema_name).read_text(encoding="utf-8"))
        errors = sorted(
            Draft202012Validator(schema).iter_errors(value),
            key=lambda item: list(item.path),
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise error(
            ErrorCode.DEPENDENCY_INVALID_RESPONSE,
            status_code=502,
            detail="frozen contract validator is unavailable",
        ) from exc
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.path) or "$"
        raise error(
            ErrorCode.DEPENDENCY_INVALID_RESPONSE,
            status_code=502,
            detail=f"upstream contract validation failed at {path}",
        )
