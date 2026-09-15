"""Read-only validation for the frozen assessment.v1 shape.

The adapter does not import the CAT implementation or modify the root schema.
This small validator mirrors the frozen JSON Schema boundary so the module can
remain independently runnable with the Python standard library.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any, cast

_ASSESSMENT_ID = re.compile(r"^ASSESS_[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SUBJECT_ID = re.compile(r"^SUBJ_[A-Za-z0-9][A-Za-z0-9_.-]*$")
_DIMENSION_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_.-]+$")
_RULESET_ID = re.compile(r"^RULESET_[A-Za-z0-9][A-Za-z0-9_.-]*$")


class AssessmentValidationError(ValueError):
    """Raised when an assessment cannot cross the D3-2 input boundary."""

    reason_code = "ASSESSMENT_SCHEMA_INVALID"


def _fail(message: str) -> None:
    raise AssessmentValidationError(message)


def _object(value: object, name: str, required: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    record = cast(Mapping[str, Any], value)
    if set(record) != required:
        _fail(f"{name} fields are invalid")
    return record


def _text(value: object, name: str, *, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or not value:
        _fail(f"{name} must be non-empty text")
    text = cast(str, value)
    if pattern is not None and not pattern.fullmatch(text):
        _fail(f"{name} has an invalid format")
    return text


def _number_or_none(value: object, name: str, *, minimum: float | None = None) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{name} must be a number or null")
    if isinstance(value, float) and not math.isfinite(value):
        _fail(f"{name} must be finite")
    number = cast(int | float, value)
    if minimum is not None and number < minimum:
        _fail(f"{name} is below its minimum")


def _nonnegative_int(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail(f"{name} must be a non-negative integer")


def _validate_dimensions(value: object) -> None:
    if not isinstance(value, Mapping) or not value:
        _fail("dimensions must be a non-empty object")
    dimensions = cast(Mapping[str, Any], value)
    required = {
        "theta",
        "se",
        "score",
        "band",
        "interpretation_status",
        "items_answered",
    }
    for key, dimension in dimensions.items():
        if not isinstance(key, str) or not _DIMENSION_ID.fullmatch(key):
            _fail("dimension identifier is invalid")
        record = _object(dimension, f"dimension {key}", required)
        _number_or_none(record["theta"], f"dimension {key}.theta")
        _number_or_none(record["se"], f"dimension {key}.se", minimum=0)
        _number_or_none(record["score"], f"dimension {key}.score")
        if record["band"] not in {"normal", "attention", "high", "unknown"}:
            _fail(f"dimension {key}.band is invalid")
        if record["interpretation_status"] not in {
            "estimated",
            "insufficient_data",
            "not_scored",
        }:
            _fail(f"dimension {key}.interpretation_status is invalid")
        _nonnegative_int(record["items_answered"], f"dimension {key}.items_answered")


def _validate_risk(value: object) -> None:
    record = _object(
        value,
        "risk",
        {"level", "need_human_review", "reason_codes", "ruleset_id"},
    )
    if record["level"] not in {"normal", "attention", "high", "crisis"}:
        _fail("risk.level is invalid")
    if not isinstance(record["need_human_review"], bool):
        _fail("risk.need_human_review must be boolean")
    if record["level"] in {"high", "crisis"} and record["need_human_review"] is not True:
        _fail("high or crisis risk requires human review")
    codes = record["reason_codes"]
    if (
        not isinstance(codes, list)
        or not codes
        or not all(isinstance(code, str) and _REASON_CODE.fullmatch(code) for code in codes)
        or len(set(codes)) != len(codes)
    ):
        _fail("risk.reason_codes is invalid")
    _text(record["ruleset_id"], "risk.ruleset_id", pattern=_RULESET_ID)


def validate_assessment_v1(value: object) -> None:
    """Validate an assessment.v1 mapping without modifying or enriching it."""

    required = {
        "schema_version",
        "assessment_id",
        "subject_id",
        "instrument",
        "population_scope",
        "status",
        "dimensions",
        "risk",
        "response_summary",
        "provenance",
        "timestamps",
    }
    assessment = _object(value, "assessment", required)
    if assessment["schema_version"] != "assessment.v1":
        _fail("schema_version must be assessment.v1")
    _text(assessment["assessment_id"], "assessment_id", pattern=_ASSESSMENT_ID)
    _text(assessment["subject_id"], "subject_id", pattern=_SUBJECT_ID)
    instrument = _object(assessment["instrument"], "instrument", {"instrument_id", "version"})
    _text(instrument["instrument_id"], "instrument.instrument_id")
    _text(instrument["version"], "instrument.version")
    _text(assessment["population_scope"], "population_scope")
    status = assessment["status"]
    if status not in {"created", "in_progress", "completed", "abandoned", "invalid"}:
        _fail("status is invalid")
    _validate_dimensions(assessment["dimensions"])
    _validate_risk(assessment["risk"])

    summary = _object(
        assessment["response_summary"],
        "response_summary",
        {"items_answered", "duration_seconds"},
    )
    _nonnegative_int(summary["items_answered"], "response_summary.items_answered")
    duration = summary["duration_seconds"]
    if duration is not None:
        _nonnegative_int(duration, "response_summary.duration_seconds")

    provenance = _object(
        assessment["provenance"],
        "provenance",
        {"source_adapter", "adapter_version", "cat_engine_version", "item_bank_version"},
    )
    for key in provenance:
        _text(provenance[key], f"provenance.{key}")

    timestamps = _object(
        assessment["timestamps"],
        "timestamps",
        {"started_at", "completed_at"},
    )
    _text(timestamps["started_at"], "timestamps.started_at")
    completed_at = timestamps["completed_at"]
    if completed_at is not None:
        _text(completed_at, "timestamps.completed_at")
    if status == "completed" and completed_at is None:
        _fail("completed assessment requires completed_at")
