"""Simulation reproducibility and metric tests."""

from __future__ import annotations

import math

from cat_engine.simulation.runner import SimulationRunner


def test_simulation_uses_real_provider_and_is_reproducible(service, item_bank, cat_config) -> None:
    runner = SimulationRunner(service.provider, item_bank, cat_config)
    first = runner.run(n_examinees=20, seed=12345)
    second = runner.run(n_examinees=20, seed=12345)
    assert first.to_dict() == second.to_dict()
    assert first.n_examinees == 20
    assert first.stopping_reason_distribution
    for value in first.metrics.values():
        assert math.isfinite(value)
    assert all(result.items_administered <= cat_config.max_items for result in first.results)


def test_simulation_metrics_have_expected_fields(service, item_bank, cat_config) -> None:
    summary = SimulationRunner(service.provider, item_bank, cat_config).run(n_examinees=10, seed=7)
    assert {"bias", "rmse", "mae", "mean_test_length", "median_test_length", "mean_se"}.issubset(
        summary.metrics
    )
    assert summary.metadata["provider_version"] == "adaptivetesting-1.2.1"

