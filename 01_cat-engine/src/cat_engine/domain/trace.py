"""Structured CAT administration trace records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .enums import ResponseStatus
from .item import ResponseValue


@dataclass(frozen=True)
class CATTraceRecord:
    """One auditable item administration and estimate transition."""

    sequence_number: int
    item_id: str
    response_status: ResponseStatus
    response: ResponseValue | None
    theta_before: float
    theta_after: float
    se_before: float
    se_after: float
    selection_criterion: str
    selection_score: float | None
    timestamp: str
    provider_version: str
    item_bank_version: str
    config_version: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible trace record."""

        return {
            "sequence_number": self.sequence_number,
            "item_id": self.item_id,
            "response_status": self.response_status.value,
            "response": self.response,
            "theta_before": self.theta_before,
            "theta_after": self.theta_after,
            "se_before": self.se_before,
            "se_after": self.se_after,
            "selection_criterion": self.selection_criterion,
            "selection_score": self.selection_score,
            "timestamp": self.timestamp,
            "provider_version": self.provider_version,
            "item_bank_version": self.item_bank_version,
            "config_version": self.config_version,
        }

