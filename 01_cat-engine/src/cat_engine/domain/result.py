"""Provider-neutral CAT result and externally supplied risk snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .enums import StopReason
from .errors import ValidationError
from .trace import CATTraceRecord


@dataclass(frozen=True)
class AbilityEstimate:
    """Current estimate for one CAT dimension."""

    theta: float
    se: float
    items_answered: int


@dataclass(frozen=True)
class RiskSnapshot:
    """A risk routing snapshot owned by another approved project component."""

    level: str
    need_human_review: bool
    reason_codes: tuple[str, ...]
    ruleset_id: str

    def validate(self) -> None:
        """Validate the frozen Contract shape without interpreting risk."""

        if self.level not in {"normal", "attention", "high", "crisis"}:
            raise ValidationError(f"unsupported risk level: {self.level}")
        if not self.reason_codes or len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValidationError("risk reason_codes must be non-empty and unique")
        if not self.ruleset_id.startswith("RULESET_"):
            raise ValidationError("ruleset_id must use the RULESET_ prefix")
        if self.level in {"high", "crisis"} and self.need_human_review is not True:
            raise ValidationError("high and crisis risk must require human review")

    def to_dict(self) -> dict[str, Any]:
        """Return the snapshot in assessment.v1 form."""

        self.validate()
        return {
            "level": self.level,
            "need_human_review": self.need_human_review,
            "reason_codes": list(self.reason_codes),
            "ruleset_id": self.ruleset_id,
        }


@dataclass(frozen=True)
class CATResult:
    """Completed provider-neutral CAT result before assessment mapping."""

    assessment_id: str
    subject_id: str
    instrument_id: str
    instrument_version: str
    population_scope: str
    dimension: str
    estimate: AbilityEstimate
    items_administered: int
    provider_version: str
    item_bank_id: str
    item_bank_version: str
    config_version: str
    status: str
    started_at: str
    completed_at: str
    duration_seconds: int | None
    stopping_reason: StopReason
    traces: tuple[CATTraceRecord, ...]

    def validate(self) -> None:
        """Check result invariants before exposing it to a mapper."""

        if self.status != "completed":
            raise ValidationError("CATResult must be completed before mapping")
        if self.items_administered < self.estimate.items_answered:
            raise ValidationError("items_administered cannot be less than items_answered")
        if self.estimate.items_answered != sum(
            1 for record in self.traces if record.response_status.value == "answered"
        ):
            raise ValidationError("answered item count does not match trace")
        if self.items_administered != len(self.traces):
            raise ValidationError("administered item count does not match trace")

    def dimension_estimates(self) -> Mapping[str, AbilityEstimate]:
        """Expose the one-dimensional demo estimate under its stable dimension key."""

        return {self.dimension: self.estimate}

