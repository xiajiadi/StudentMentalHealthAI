"""Metrics for synthetic CAT simulation results."""

from __future__ import annotations

from collections import Counter
import math
from statistics import mean, median
from typing import Iterable, Sequence

from ..domain.errors import SimulationError


def _validated_errors(true_values: Sequence[float], estimated_values: Sequence[float]) -> list[float]:
    if not true_values or len(true_values) != len(estimated_values):
        raise SimulationError("true and estimated theta values must be non-empty and equally sized")
    errors = [float(estimated - true) for true, estimated in zip(true_values, estimated_values)]
    if any(not math.isfinite(error) for error in errors):
        raise SimulationError("simulation contains a non-finite estimation error")
    return errors


def bias(true_values: Sequence[float], estimated_values: Sequence[float]) -> float:
    """Mean signed estimation error."""

    return float(mean(_validated_errors(true_values, estimated_values)))


def rmse(true_values: Sequence[float], estimated_values: Sequence[float]) -> float:
    """Root mean squared estimation error."""

    errors = _validated_errors(true_values, estimated_values)
    return float(math.sqrt(mean(error * error for error in errors)))


def mae(true_values: Sequence[float], estimated_values: Sequence[float]) -> float:
    """Mean absolute estimation error."""

    return float(mean(abs(error) for error in _validated_errors(true_values, estimated_values)))


def length_metrics(lengths: Iterable[int]) -> tuple[float, float]:
    """Return mean and median test length."""

    values = [int(value) for value in lengths]
    if not values:
        raise SimulationError("simulation has no test lengths")
    return float(mean(values)), float(median(values))


def stopping_distribution(reasons: Iterable[str]) -> dict[str, int]:
    """Count stop reasons in stable lexical order."""

    counts = Counter(reasons)
    return dict(sorted(counts.items()))

