"""Strict, privacy-limited projections for synthetic CAT management."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class StrictDto(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EngineeringOnlyDto(StrictDto):
    @field_validator("engineering_only", mode="before", check_fields=False)
    @classmethod
    def exact_engineering_only_flag(cls, value):
        if type(value) is not bool or value is not True:
            raise ValueError("engineering_only must be true")
        return value

    @field_validator("psychological_interpretation_allowed", mode="before", check_fields=False)
    @classmethod
    def exact_interpretation_flag(cls, value):
        if type(value) is not bool or value is not False:
            raise ValueError("psychological_interpretation_allowed must be false")
        return value


class ItemBankDto(StrictDto):
    item_bank_id: Literal["ITEMBANK_demo_cat"]
    version: Literal["demo.v1"]
    instrument_id: Literal["CURRENT_SYNTHETIC_GRM"]
    item_count: Literal[9]
    dimension_count: Literal[1]
    status: Literal["published"]
    validation: Literal["STRUCTURE_VALID"]


class ConfigDto(StrictDto):
    config_version: Literal["demo.cat.v1"]
    model: Literal["GRM"]
    estimator: Literal["EAP"]
    selection_method: Literal["MFI"]
    min_items: Literal[3]
    max_items: Literal[8]
    se_threshold: Literal[0.55]
    seed: Literal[20260904]

    @field_validator("se_threshold")
    @classmethod
    def finite_threshold(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("must be finite")
        return value

    @field_validator("max_items")
    @classmethod
    def max_not_less_than_min(cls, value: int, info):
        minimum = info.data.get("min_items")
        if minimum is not None and value < minimum:
            raise ValueError("max_items must not be less than min_items")
        return value


class SimulationAvailabilityDto(StrictDto):
    available: Literal[True]
    sample_sizes: list[Literal[100, 1000]] = Field(min_length=2, max_length=2)
    fixed_seed: Literal[20260904]

    @field_validator("sample_sizes")
    @classmethod
    def exact_sample_sizes(cls, value: list[int]) -> list[int]:
        if value != [100, 1000]:
            raise ValueError("sample_sizes must be [100, 1000]")
        return value


class CatalogResponseDto(EngineeringOnlyDto):
    schema_version: Literal["synthetic_cat_management.v1"]
    engineering_only: Literal[True]
    psychological_interpretation_allowed: Literal[False]
    item_bank: ItemBankDto
    config: ConfigDto
    simulation: SimulationAvailabilityDto


class SimulationRequestDto(StrictDto):
    n_examinees: StrictInt = 100

    @field_validator("n_examinees")
    @classmethod
    def valid_batch_size(cls, value: int) -> int:
        if value not in {100, 1000}:
            raise ValueError("n_examinees must be 100 or 1000")
        return value


class SimulationMetricsDto(StrictDto):
    bias: float
    rmse: float = Field(ge=0)
    mae: float = Field(ge=0)
    mean_test_length: float = Field(gt=0)
    median_test_length: float = Field(gt=0)
    mean_se: float = Field(ge=0)

    @field_validator("bias", "rmse", "mae", "mean_test_length", "median_test_length", "mean_se")
    @classmethod
    def finite_metric(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("metric must be finite")
        return value


class SimulationResponseDto(EngineeringOnlyDto):
    schema_version: Literal["synthetic_cat_management.v1"]
    engineering_only: Literal[True]
    psychological_interpretation_allowed: Literal[False]
    item_bank_id: Literal["ITEMBANK_demo_cat"]
    item_bank_version: Literal["demo.v1"]
    config_version: Literal["demo.cat.v1"]
    n_examinees: StrictInt
    seed: Literal[20260904]
    metrics: SimulationMetricsDto
    stopping_reason_distribution: dict[
        Literal[
            "SE_THRESHOLD_REACHED",
            "MAX_ITEMS_REACHED",
            "ITEM_BANK_EXHAUSTED",
            "MANUAL_TERMINATION",
            "ERROR",
            "NOT_STOPPED",
        ],
        int,
    ]

    @field_validator("n_examinees")
    @classmethod
    def valid_batch_size(cls, value: int) -> int:
        if value not in {100, 1000}:
            raise ValueError("n_examinees must be 100 or 1000")
        return value

    @field_validator("stopping_reason_distribution")
    @classmethod
    def valid_counts(cls, value: dict[str, int], info) -> dict[str, int]:
        n_examinees = info.data.get("n_examinees")
        if any(type(count) is not int or count < 0 for count in value.values()):
            raise ValueError("stopping counts must be nonnegative integers")
        if n_examinees is None or sum(value.values()) != n_examinees:
            raise ValueError("stopping counts must sum to n_examinees")
        return value


__all__ = [
    "CatalogResponseDto",
    "SimulationRequestDto",
    "SimulationResponseDto",
]
