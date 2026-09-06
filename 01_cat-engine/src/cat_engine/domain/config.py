"""Validated, versioned CAT runtime configuration."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

from .errors import ConfigValidationError


@dataclass(frozen=True)
class CATConfig:
    """All algorithm and stopping parameters used by one CAT configuration."""

    config_version: str
    model: str
    estimator: str
    selection_method: str
    min_items: int
    max_items: int
    se_threshold: float | None
    initial_theta: float
    prior_mean: float
    prior_sd: float
    optimization_interval: tuple[float, float]
    seed: int | None
    exposure_control: str
    content_balancing: str

    @classmethod
    def from_dict(cls, source: Mapping[str, Any]) -> "CATConfig":
        """Build and validate a configuration from a JSON-like mapping."""

        required = {
            "config_version",
            "model",
            "estimator",
            "selection_method",
            "min_items",
            "max_items",
            "se_threshold",
            "initial_theta",
            "prior_mean",
            "prior_sd",
            "optimization_interval",
            "seed",
            "exposure_control",
            "content_balancing",
        }
        missing = sorted(required.difference(source))
        if missing:
            raise ConfigValidationError(f"CAT config missing fields: {', '.join(missing)}")

        interval = source["optimization_interval"]
        if not isinstance(interval, (list, tuple)) or len(interval) != 2:
            raise ConfigValidationError("optimization_interval must contain two numbers")
        try:
            interval_tuple = (float(interval[0]), float(interval[1]))
        except (TypeError, ValueError) as exc:
            raise ConfigValidationError("optimization_interval must contain numbers") from exc

        values = {
            "config_version": source["config_version"],
            "model": source["model"],
            "estimator": source["estimator"],
            "selection_method": source["selection_method"],
            "min_items": source["min_items"],
            "max_items": source["max_items"],
            "se_threshold": source["se_threshold"],
            "initial_theta": source["initial_theta"],
            "prior_mean": source["prior_mean"],
            "prior_sd": source["prior_sd"],
            "optimization_interval": interval_tuple,
            "seed": source["seed"],
            "exposure_control": source["exposure_control"],
            "content_balancing": source["content_balancing"],
        }
        config = cls(**values)
        config.validate()
        return config

    def validate(self) -> None:
        """Reject unsupported algorithms and unsafe stopping parameters."""

        if not isinstance(self.config_version, str) or not self.config_version:
            raise ConfigValidationError("config_version must be a non-empty string")
        if self.model not in {"GRM", "GPCM"}:
            raise ConfigValidationError("model must be GRM or GPCM")
        if self.estimator not in {"EAP", "BM"}:
            raise ConfigValidationError("estimator must be EAP or BM")
        if self.selection_method not in {"MFI"}:
            raise ConfigValidationError("selection_method must be MFI in CAT V0.1")
        if not isinstance(self.min_items, int) or isinstance(self.min_items, bool):
            raise ConfigValidationError("min_items must be an integer")
        if not isinstance(self.max_items, int) or isinstance(self.max_items, bool):
            raise ConfigValidationError("max_items must be an integer")
        if self.min_items < 1 or self.max_items < self.min_items:
            raise ConfigValidationError("max_items must be at least min_items >= 1")
        if self.se_threshold is not None and (
            not isinstance(self.se_threshold, (int, float))
            or isinstance(self.se_threshold, bool)
            or not math.isfinite(float(self.se_threshold))
            or float(self.se_threshold) <= 0
        ):
            raise ConfigValidationError("se_threshold must be null or a positive finite number")
        numeric_fields = {
            "initial_theta": self.initial_theta,
            "prior_mean": self.prior_mean,
            "prior_sd": self.prior_sd,
        }
        for name, value in numeric_fields.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                raise ConfigValidationError(f"{name} must be a finite number")
        if self.prior_sd <= 0:
            raise ConfigValidationError("prior_sd must be positive")
        low, high = self.optimization_interval
        if not math.isfinite(low) or not math.isfinite(high) or low >= high:
            raise ConfigValidationError("optimization_interval must be finite and increasing")
        if self.seed is not None and (
            not isinstance(self.seed, int) or isinstance(self.seed, bool) or self.seed < 0
        ):
            raise ConfigValidationError("seed must be null or a non-negative integer")
        if self.exposure_control not in {"none"}:
            raise ConfigValidationError("only exposure_control=none is implemented in CAT V0.1")
        if self.content_balancing not in {"none"}:
            raise ConfigValidationError("only content_balancing=none is implemented in CAT V0.1")

    def to_dict(self) -> dict[str, Any]:
        """Return the configuration in its fixture-friendly representation."""

        return {
            "config_version": self.config_version,
            "model": self.model,
            "estimator": self.estimator,
            "selection_method": self.selection_method,
            "min_items": self.min_items,
            "max_items": self.max_items,
            "se_threshold": self.se_threshold,
            "initial_theta": self.initial_theta,
            "prior_mean": self.prior_mean,
            "prior_sd": self.prior_sd,
            "optimization_interval": list(self.optimization_interval),
            "seed": self.seed,
            "exposure_control": self.exposure_control,
            "content_balancing": self.content_balancing,
        }

