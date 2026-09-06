"""Reproducible CAT batch simulation using the real provider path."""

from __future__ import annotations

import csv
import json
from importlib import metadata
from pathlib import Path
import platform
from random import Random
from typing import Any

from ..domain.config import CATConfig
from ..domain.errors import SimulationError
from ..domain.item_bank import ItemBank
from ..domain.session import Session
from ..providers.base import CATProvider
from .metrics import bias, length_metrics, mae, rmse, stopping_distribution
from .models import SimulatedExamineeResult, SimulationSummary


class SimulationRunner:
    """Drive real provider selection, response generation, estimation and stopping."""

    def __init__(
        self,
        provider: CATProvider,
        item_bank: ItemBank,
        config: CATConfig,
        engine_version: str = "0.1.0",
    ) -> None:
        self.provider = provider
        self.item_bank = item_bank
        self.config = config
        self.engine_version = engine_version

    def run(
        self,
        n_examinees: int,
        seed: int | None = None,
        theta_min: float = -2.5,
        theta_max: float = 2.5,
    ) -> SimulationSummary:
        """Run a deterministic synthetic batch with a fixed seed."""

        if not isinstance(n_examinees, int) or isinstance(n_examinees, bool) or n_examinees < 1:
            raise SimulationError("n_examinees must be a positive integer")
        if theta_min >= theta_max:
            raise SimulationError("theta_min must be smaller than theta_max")
        batch_seed = self.config.seed if seed is None else seed
        if batch_seed is None or not isinstance(batch_seed, int) or batch_seed < 0:
            raise SimulationError("a non-negative fixed seed is required for batch simulation")
        rng = Random(batch_seed)
        results: list[SimulatedExamineeResult] = []
        for index in range(n_examinees):
            true_theta = rng.uniform(theta_min, theta_max)
            results.append(self._run_one(index, true_theta, rng))
        true_values = [result.true_theta for result in results]
        estimated_values = [result.estimated_theta for result in results]
        mean_length, median_length = length_metrics(result.items_administered for result in results)
        metrics = {
            "bias": bias(true_values, estimated_values),
            "rmse": rmse(true_values, estimated_values),
            "mae": mae(true_values, estimated_values),
            "mean_test_length": mean_length,
            "median_test_length": median_length,
            "mean_se": sum(result.se for result in results) / len(results),
        }
        metadata = {
            "cat_engine_version": self.engine_version,
            "provider": self.provider.provider_name,
            "provider_version": self.provider.provider_version,
            "item_bank_id": self.item_bank.item_bank_id,
            "item_bank_version": self.item_bank.version,
            "config_version": self.config.config_version,
            "python_version": platform.python_version(),
            "adaptivetesting_version": self._dependency_version("adaptivetesting"),
            "numpy_version": self._dependency_version("numpy"),
            "scipy_version": self._dependency_version("scipy"),
        }
        return SimulationSummary(
            n_examinees=n_examinees,
            seed=batch_seed,
            metadata=metadata,
            metrics=metrics,
            stopping_reason_distribution=stopping_distribution(
                result.stopping_reason for result in results
            ),
            results=tuple(results),
        )

    def write_reports(self, summary: SimulationSummary, reports_dir: str | Path) -> dict[str, Path]:
        """Export JSON, CSV, and a concise Markdown summary."""

        output_dir = Path(reports_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "cat_simulation_summary.json"
        csv_path = output_dir / "cat_simulation_results.csv"
        markdown_path = output_dir / "CAT_SIMULATION_SUMMARY.md"
        json_path.write_text(
            json.dumps(summary.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(summary.results[0].to_dict()))
            writer.writeheader()
            writer.writerows(result.to_dict() for result in summary.results)
        markdown_path.write_text(self._markdown(summary), encoding="utf-8")
        return {"json": json_path, "csv": csv_path, "markdown": markdown_path}

    def _run_one(self, index: int, true_theta: float, rng: Random) -> SimulatedExamineeResult:
        suffix = f"{index + 1:04d}"
        session = Session.create(
            assessment_id=f"ASSESS_sim_{suffix}",
            subject_id=f"SUBJ_sim_{suffix}",
            item_bank=self.item_bank,
            config=self.config,
        )
        session.initialize(self.provider)
        while session.result is None:
            selection = session.select_next_item(self.provider)
            response = self.provider.sample_response(
                session.provider_session,  # type: ignore[arg-type]
                selection.item_id,
                true_theta,
                rng,
            )
            session.submit_response(self.provider, response)
            if session.last_stop_decision and session.last_stop_decision.should_stop:
                session.complete(self.provider)
        assert session.result is not None
        return SimulatedExamineeResult(
            examinee_id=f"SIM_{suffix}",
            true_theta=true_theta,
            estimated_theta=session.result.estimate.theta,
            se=session.result.estimate.se,
            items_administered=session.result.items_administered,
            stopping_reason=session.result.stopping_reason.value,
        )

    @staticmethod
    def _dependency_version(name: str) -> str:
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            return "not_installed"

    @staticmethod
    def _markdown(summary: SimulationSummary) -> str:
        metrics = summary.metrics
        lines = [
            "# CAT Simulation Summary",
            "",
            "`DEMO / ENGINEERING USE ONLY` — `NOT FOR PSYCHOLOGICAL INTERPRETATION`.",
            "",
            f"- N: {summary.n_examinees}",
            f"- Seed: {summary.seed}",
            f"- Bias: {metrics['bias']:.6f}",
            f"- RMSE: {metrics['rmse']:.6f}",
            f"- MAE: {metrics['mae']:.6f}",
            f"- Mean Test Length: {metrics['mean_test_length']:.6f}",
            f"- Median Test Length: {metrics['median_test_length']:.6f}",
            f"- Mean SE: {metrics['mean_se']:.6f}",
            "",
            "## Stopping reason distribution",
            "",
        ]
        lines.extend(
            f"- {reason}: {count}"
            for reason, count in summary.stopping_reason_distribution.items()
        )
        lines.extend(["", "## Reproducibility metadata", ""])
        lines.extend(f"- {key}: {value}" for key, value in summary.metadata.items())
        lines.append("")
        return "\n".join(lines)

