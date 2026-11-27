"""Read a narrow projection of a student's own published-feedback measurement."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.assessment.schemas import AssessmentDto
from smhai_backend.domains.models import AssessmentRecord


class MeasurementDimension(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    label: str
    estimate: float | None
    standard_error: float | None


class FeedbackMeasurement(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["engineering", "unscored", "not_displayable"]
    completed_at: str
    answered_count: int
    item_bank_version: str
    dimensions: list[MeasurementDimension]


def _finite(value: float | None) -> float | None:
    return value if value is not None and math.isfinite(value) else None


def feedback_measurement(record: AssessmentRecord, assessment_ref: str) -> FeedbackMeasurement:
    try:
        assessment = AssessmentDto.model_validate(record.assessment)
    except ValidationError:
        raise error(
            ErrorCode.DEPENDENCY_INVALID_RESPONSE, detail="measurement record is unavailable"
        ) from None
    if (
        record.data_origin != "SYNTHETIC"
        or assessment.assessment_id != assessment_ref
        or assessment.status != "completed"
        or assessment.timestamps.completed_at is None
    ):
        raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="measurement record is unavailable")
    dimensions: list[MeasurementDimension] = []
    status: Literal["engineering", "unscored", "not_displayable"] = "not_displayable"
    if (
        assessment.risk.ruleset_id == "RULESET_synthetic_cat_v1"
        and "SYNTHETIC_ENGINEERING_FIXTURE" in assessment.risk.reason_codes
        and assessment.provenance.source_adapter == "cat_engine"
    ):
        status = "engineering"
        for label, dimension in assessment.dimensions.items():
            estimate = (
                _finite(dimension.theta) if dimension.interpretation_status == "estimated" else None
            )
            standard_error = _finite(dimension.se) if estimate is not None else None
            if standard_error is not None and standard_error < 0:
                standard_error = None
            dimensions.append(
                MeasurementDimension(label=label, estimate=estimate, standard_error=standard_error)
            )
    elif assessment.dimensions and all(
        dimension.interpretation_status == "not_scored"
        for dimension in assessment.dimensions.values()
    ):
        status = "unscored"
    return FeedbackMeasurement(
        status=status,
        completed_at=assessment.timestamps.completed_at,
        answered_count=assessment.response_summary.items_answered,
        item_bank_version=assessment.provenance.item_bank_version,
        dimensions=dimensions,
    )
