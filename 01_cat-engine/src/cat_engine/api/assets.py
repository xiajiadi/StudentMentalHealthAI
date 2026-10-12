"""Bounded structure validation for school synthetic version documents."""
from __future__ import annotations

import json
import math
from threading import Lock
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    field_validator,
)

from cat_engine.api.management import (
    CatManagementRuntime,
    _require_synthetic_runtime,
    _run_in_simulation_slot,
)
from cat_engine.domain.config import CATConfig
from cat_engine.domain.errors import ValidationError as CATValidationError
from cat_engine.domain.item_bank import ItemBank
from cat_engine.simulation.models import SimulationSummary

Text = Annotated[str, StringConstraints(min_length=1, max_length=160)]
Finite = Annotated[float, Field(allow_inf_nan=False)]


class StrictDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SyntheticMetadata(StrictDocument):
    synthetic: Literal[True]
    intended_use: Literal["engineering_test_only"]
    psychological_interpretation_allowed: Literal[False]
    instrument_version: Text | None = None
    notice: Annotated[str, StringConstraints(max_length=500)] | None = None
    psychometric_status: Literal["PENDING_PSYCHOMETRIC_CONFIRMATION"] | None = None

    @field_validator("synthetic", "psychological_interpretation_allowed", mode="before")
    @classmethod
    def require_actual_boolean_flags(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("synthetic metadata flags must be JSON booleans")
        return value


class Parameters(StrictDocument):
    a: Annotated[Finite, Field(gt=0, le=10)]
    thresholds: Annotated[list[Finite], Field(min_length=1, max_length=9)]


class ItemDocument(StrictDocument):
    item_id: Annotated[str, StringConstraints(pattern=r"^ITEM_[A-Za-z0-9_.-]{1,122}$")]
    dimension: Text
    stem: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    response_type: Literal["likert"]
    response_options: Annotated[list[Text], Field(min_length=2, max_length=10)]
    scoring: dict[Text, StrictInt]
    model: Literal["GRM"]
    parameters: Parameters
    source: Text
    status: Literal["published", "demo", "synthetic"]


class BankDocument(StrictDocument):
    item_bank_id: Text
    version: Text
    instrument_id: Text
    target_population: Text
    measurement_model: Literal["GRM"]
    dimensions: Annotated[list[Text], Field(min_length=1, max_length=1)]
    items: Annotated[list[ItemDocument], Field(min_length=1, max_length=100)]
    status: Literal["draft", "published"]
    metadata: SyntheticMetadata


class ConfigDocument(StrictDocument):
    config_version: Text
    model: Literal["GRM"]
    estimator: Literal["EAP", "BM"]
    selection_method: Literal["MFI"]
    min_items: Annotated[StrictInt, Field(ge=1, le=100)]
    max_items: Annotated[StrictInt, Field(ge=1, le=100)]
    se_threshold: Annotated[Finite, Field(gt=0, le=10)] | None
    initial_theta: Finite
    prior_mean: Finite
    prior_sd: Annotated[Finite, Field(gt=0, le=10)]
    optimization_interval: Annotated[list[Finite], Field(min_length=2, max_length=2)]
    seed: Annotated[StrictInt, Field(ge=0, le=4294967295)]
    exposure_control: Literal["none"]
    content_balancing: Literal["none"]


class ValidateAssetsRequest(StrictDocument):
    bank_document: BankDocument
    config_document: ConfigDocument | None = None


class SimulateAssetsRequest(StrictDocument):
    bank_document: BankDocument
    config_document: ConfigDocument
    n_examinees: StrictInt

    @field_validator("n_examinees")
    @classmethod
    def require_bounded_sample_size(cls, value: int) -> int:
        if value not in {100, 1000}:
            raise ValueError("n_examinees must be 100 or 1000")
        return value


def validate_documents(payload: ValidateAssetsRequest) -> dict:
    bank_document = payload.bank_document.model_dump(mode="json", exclude_none=True)
    config_document = (
        payload.config_document.model_dump(mode="json") if payload.config_document else None
    )
    encoded = json.dumps(bank_document, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(encoded) > 256 * 1024:
        raise HTTPException(status_code=422, detail="synthetic_cat_asset_invalid")
    try:
        bank = ItemBank.from_dict(bank_document)
        if config_document is not None:
            config = CATConfig.from_dict(config_document)
            if config.model != bank.measurement_model or config.max_items > len(bank.items):
                raise ValueError("incompatible configuration")
    except (CATValidationError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=422, detail="synthetic_cat_asset_invalid") from exc
    return {
        "engineering_only": True,
        "psychological_interpretation_allowed": False,
        "bank_document": bank_document,
        "config_document": config_document,
        "item_count": len(bank.items),
        "dimension_count": len(bank.dimensions),
    }


def _run_assets_simulation(
    bank: ItemBank, config: CATConfig, n_examinees: int
) -> SimulationSummary:
    # Keep the provider used for document simulation separate from live sessions.
    from cat_engine.providers.adaptivetesting_provider import AdaptiveTestingProvider
    from cat_engine.simulation.runner import SimulationRunner

    return SimulationRunner(AdaptiveTestingProvider(), bank, config).run(
        n_examinees=n_examinees
    )


def _run_assets_simulation_captured(
    bank: ItemBank, config: CATConfig, n_examinees: int
) -> tuple[SimulationSummary | None, Exception | None]:
    try:
        return _run_assets_simulation(bank, config, n_examinees), None
    except Exception as exc:  # noqa: BLE001 - worker failure is returned as a value.
        return None, exc


def _assets_simulation_response(
    summary: SimulationSummary, bank: ItemBank, config: CATConfig, n_examinees: int
) -> dict:
    metrics_names = (
        "bias", "rmse", "mae", "mean_test_length", "median_test_length", "mean_se",
    )
    if (
        summary.n_examinees != n_examinees
        or summary.seed != config.seed
        or summary.metadata.get("item_bank_id") != bank.item_bank_id
        or summary.metadata.get("item_bank_version") != bank.version
        or summary.metadata.get("config_version") != config.config_version
    ):
        raise HTTPException(status_code=503, detail="synthetic_cat_simulation_unavailable")

    metrics: dict[str, float] = {}
    for name in metrics_names:
        value = summary.metrics.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise HTTPException(status_code=503, detail="synthetic_cat_simulation_unavailable")
        metrics[name] = float(value)

    stopping = dict(summary.stopping_reason_distribution)
    if (
        any(not isinstance(reason, str) or not reason for reason in stopping)
        or any(
            isinstance(count, bool) or not isinstance(count, int) or count < 0
            for count in stopping.values()
        )
        or sum(stopping.values()) != n_examinees
    ):
        raise HTTPException(status_code=503, detail="synthetic_cat_simulation_unavailable")

    return {
        "engineering_only": True,
        "psychological_interpretation_allowed": False,
        "item_bank_id": bank.item_bank_id,
        "item_bank_version": bank.version,
        "config_version": config.config_version,
        "n_examinees": n_examinees,
        "seed": summary.seed,
        "metrics": metrics,
        "stopping_reason_distribution": stopping,
    }


def create_assets_router(
    runtime: CatManagementRuntime, simulation_lock: Lock | None = None
) -> APIRouter:
    router = APIRouter(prefix="/internal/cat/management", tags=["cat-management"])
    if simulation_lock is None:
        simulation_lock = Lock()

    @router.get("/template", operation_id="catManagementTemplate")
    async def get_template() -> dict:
        _require_synthetic_runtime(runtime)
        return validate_documents(ValidateAssetsRequest.model_validate({
            "bank_document": runtime.item_bank.to_dict(),
            "config_document": runtime.config.to_dict(),
        }))

    @router.post("/validate-assets", operation_id="catManagementValidateAssets")
    async def validate_assets(payload: ValidateAssetsRequest, request: Request) -> dict:
        if len(await request.body()) > 256 * 1024:
            raise HTTPException(status_code=422, detail="synthetic_cat_asset_invalid")
        return validate_documents(payload)

    @router.post("/simulate-assets", operation_id="catManagementSimulateAssets")
    async def simulate_assets(payload: SimulateAssetsRequest, request: Request) -> dict:
        if len(await request.body()) > 256 * 1024:
            raise HTTPException(status_code=422, detail="synthetic_cat_asset_invalid")

        validated = validate_documents(
            ValidateAssetsRequest(
                bank_document=payload.bank_document,
                config_document=payload.config_document,
            )
        )
        bank_document = validated["bank_document"]
        config_document = validated["config_document"]
        try:
            bank = ItemBank.from_dict(bank_document)
            bank.assert_runtime_ready()
            config = CATConfig.from_dict(config_document)
        except (CATValidationError, ValueError, TypeError, KeyError) as exc:
            raise HTTPException(status_code=422, detail="synthetic_cat_asset_invalid") from exc

        summary, simulation_error = await _run_in_simulation_slot(
            simulation_lock,
            _run_assets_simulation_captured,
            bank,
            config,
            payload.n_examinees,
            unavailable_detail="synthetic_cat_simulation_unavailable",
        )
        if simulation_error is not None or summary is None:
            raise HTTPException(status_code=503, detail="synthetic_cat_simulation_unavailable")
        return _assets_simulation_response(summary, bank, config, payload.n_examinees)

    return router
