"""Serializable simulation result models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class SimulatedExamineeResult:
    """One synthetic examinee's actual CAT outcome."""

    examinee_id: str
    true_theta: float
    estimated_theta: float
    se: float
    items_administered: int
    stopping_reason: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible row."""

        return {
            "examinee_id": self.examinee_id,
            "true_theta": self.true_theta,
            "estimated_theta": self.estimated_theta,
            "se": self.se,
            "items_administered": self.items_administered,
            "stopping_reason": self.stopping_reason,
        }


@dataclass(frozen=True)
class SimulationSummary:
    """Batch metrics plus reproducibility metadata and per-case outcomes."""

    n_examinees: int
    seed: int
    metadata: Mapping[str, str]
    metrics: Mapping[str, float]
    stopping_reason_distribution: Mapping[str, int]
    results: tuple[SimulatedExamineeResult, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return the full batch summary for JSON export and reproducibility checks."""

        return {
            "n_examinees": self.n_examinees,
            "seed": self.seed,
            "metadata": dict(self.metadata),
            "metrics": dict(self.metrics),
            "stopping_reason_distribution": dict(self.stopping_reason_distribution),
            "results": [result.to_dict() for result in self.results],
        }

