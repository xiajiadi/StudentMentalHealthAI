"""Map an internal CATResult to the frozen assessment.v1 Contract."""

from __future__ import annotations

from typing import Any

from ..domain.result import CATResult, RiskSnapshot


class AssessmentMapper:
    """Boundary adapter that does not calculate psychological risk or bands."""

    schema_version = "assessment.v1"
    adapter_version = "0.1.0"
    cat_engine_version = "0.1.0"

    def map(self, result: CATResult, risk: RiskSnapshot) -> dict[str, Any]:
        """Return a schema-shaped assessment using an externally supplied risk snapshot."""

        result.validate()
        risk_data = risk.to_dict()
        dimensions = {
            dimension: {
                "theta": estimate.theta,
                "se": estimate.se,
                "score": None,
                "band": "unknown",
                "interpretation_status": "estimated" if estimate.items_answered else "insufficient_data",
                "items_answered": estimate.items_answered,
            }
            for dimension, estimate in result.dimension_estimates().items()
        }
        return {
            "schema_version": self.schema_version,
            "assessment_id": result.assessment_id,
            "subject_id": result.subject_id,
            "instrument": {
                "instrument_id": result.instrument_id,
                "version": result.instrument_version,
            },
            "population_scope": result.population_scope,
            "status": result.status,
            "dimensions": dimensions,
            "risk": risk_data,
            "response_summary": {
                "items_answered": result.estimate.items_answered,
                "duration_seconds": result.duration_seconds,
            },
            "provenance": {
                "source_adapter": "cat_engine",
                "adapter_version": self.adapter_version,
                "cat_engine_version": self.cat_engine_version,
                "item_bank_version": result.item_bank_version,
            },
            "timestamps": {
                "started_at": result.started_at,
                "completed_at": result.completed_at,
            },
        }

