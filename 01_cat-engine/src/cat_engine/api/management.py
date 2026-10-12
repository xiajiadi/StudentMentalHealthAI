"""Engineering-only inspection and simulation for the active synthetic CAT fixture."""

from __future__ import annotations

import asyncio
import math
from threading import Lock
from typing import Any, Protocol

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, StrictInt, field_validator

from cat_engine.domain.config import CATConfig
from cat_engine.domain.item_bank import ItemBank
from cat_engine.providers.adaptivetesting_provider import AdaptiveTestingProvider
from cat_engine.simulation.models import SimulationSummary
from cat_engine.simulation.runner import SimulationRunner


class CatManagementRuntime(Protocol):
    item_bank: ItemBank
    config: CATConfig


class SimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    n_examinees: StrictInt = 100

    @field_validator("n_examinees")
    @classmethod
    def require_bounded_sample_size(cls, value: int) -> int:
        if value not in {100, 1000}:
            raise ValueError("n_examinees must be 100 or 1000")
        return value


def _require_synthetic_runtime(runtime: CatManagementRuntime) -> None:
    metadata = runtime.item_bank.metadata
    try:
        runtime.item_bank.validate()
        runtime.item_bank.assert_runtime_ready()
        runtime.config.validate()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="synthetic_cat_management_unavailable") from exc
    if (
        metadata.get("synthetic") is not True
        or metadata.get("intended_use") != "engineering_test_only"
        or metadata.get("psychological_interpretation_allowed") is not False
        or runtime.config.seed is None
    ):
        raise HTTPException(status_code=503, detail="synthetic_cat_management_unavailable")


def _catalog(runtime: CatManagementRuntime) -> dict[str, Any]:
    _require_synthetic_runtime(runtime)
    bank = runtime.item_bank
    config = runtime.config
    return {
        "schema_version": "synthetic_cat_management.v1",
        "engineering_only": True,
        "psychological_interpretation_allowed": False,
        "item_bank": {
            "item_bank_id": bank.item_bank_id,
            "version": bank.version,
            "instrument_id": bank.instrument_id,
            "item_count": len(bank.items),
            "dimension_count": len(bank.dimensions),
            "status": bank.status.value,
            "validation": "STRUCTURE_VALID",
        },
        "config": {
            "config_version": config.config_version,
            "model": config.model,
            "estimator": config.estimator,
            "selection_method": config.selection_method,
            "min_items": config.min_items,
            "max_items": config.max_items,
            "se_threshold": config.se_threshold,
            "seed": config.seed,
        },
        "simulation": {"available": True, "sample_sizes": [100, 1000], "fixed_seed": config.seed},
    }


def _simulation_response(runtime: CatManagementRuntime, summary: SimulationSummary) -> dict[str, Any]:
    bank = runtime.item_bank
    config = runtime.config
    expected_metrics = (
        "bias", "rmse", "mae", "mean_test_length", "median_test_length", "mean_se",
    )
    if (
        summary.n_examinees not in {100, 1000}
        or summary.seed != config.seed
        or summary.metadata.get("item_bank_id") != bank.item_bank_id
        or summary.metadata.get("item_bank_version") != bank.version
        or summary.metadata.get("config_version") != config.config_version
    ):
        raise HTTPException(status_code=503, detail="synthetic_cat_simulation_unavailable")

    metrics: dict[str, float] = {}
    for name in expected_metrics:
        value = summary.metrics.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise HTTPException(status_code=503, detail="synthetic_cat_simulation_unavailable")
        metrics[name] = float(value)

    stopping = dict(summary.stopping_reason_distribution)
    if (
        any(not isinstance(reason, str) or not reason for reason in stopping)
        or any(isinstance(count, bool) or not isinstance(count, int) or count < 0 for count in stopping.values())
        or sum(stopping.values()) != summary.n_examinees
    ):
        raise HTTPException(status_code=503, detail="synthetic_cat_simulation_unavailable")

    return {
        "schema_version": "synthetic_cat_management.v1",
        "engineering_only": True,
        "psychological_interpretation_allowed": False,
        "item_bank_id": bank.item_bank_id,
        "item_bank_version": bank.version,
        "config_version": config.config_version,
        "n_examinees": summary.n_examinees,
        "seed": summary.seed,
        "metrics": metrics,
        "stopping_reason_distribution": stopping,
    }


def _run_simulation(runtime: CatManagementRuntime, n_examinees: int) -> SimulationSummary:
    # Keep simulation provider state isolated from the live session provider and registry.
    provider = AdaptiveTestingProvider()
    runner = SimulationRunner(provider, runtime.item_bank, runtime.config)
    return runner.run(n_examinees=n_examinees)


def _run_simulation_captured(
    runtime: CatManagementRuntime, n_examinees: int
) -> tuple[SimulationSummary | None, Exception | None]:
    try:
        return _run_simulation(runtime, n_examinees), None
    except Exception as exc:
        # Return failures as values so a cancelled request's shielded future
        # cannot emit an unobserved exception after the client has disconnected.
        return None, exc


def create_management_router(runtime: CatManagementRuntime) -> APIRouter:
    router = APIRouter(prefix="/internal/cat/management", tags=["cat-management"])
    simulation_lock = Lock()

    @router.get("/catalog", operation_id="catManagementCatalog")
    async def get_catalog() -> dict[str, Any]:
        return _catalog(runtime)

    def release_cancelled_simulation(
        task: asyncio.Task[tuple[SimulationSummary | None, Exception | None]],
    ) -> None:
        try:
            # Retrieving the result prevents an abandoned HTTP request from
            # leaving any worker-task outcome unobserved on the event loop.
            task.result()
        except asyncio.CancelledError:
            pass
        finally:
            simulation_lock.release()

    @router.post("/simulations", operation_id="catManagementSimulation")
    async def run_simulation(request: SimulationRequest) -> dict[str, Any]:
        _require_synthetic_runtime(runtime)
        if not simulation_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="synthetic_cat_simulation_busy")

        simulation_task = asyncio.create_task(
            asyncio.to_thread(_run_simulation_captured, runtime, request.n_examinees)
        )
        release_on_completion = False
        try:
            summary, simulation_error = await asyncio.shield(simulation_task)
        except asyncio.CancelledError:
            # A disconnected request does not make the still-running CPU work available twice.
            simulation_task.add_done_callback(release_cancelled_simulation)
            release_on_completion = True
            raise
        except Exception:
            raise HTTPException(status_code=503, detail="synthetic_cat_simulation_unavailable") from None
        finally:
            if not release_on_completion:
                simulation_lock.release()

        if simulation_error is not None or summary is None:
            raise HTTPException(status_code=503, detail="synthetic_cat_simulation_unavailable")
        return _simulation_response(runtime, summary)

    return router
