"""Strict request and metadata-only response DTOs for CAT asset management."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)


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


class BankCreateRequest(StrictDto):
    display_name: str = Field(min_length=1, max_length=120)
    bank_document: dict[str, Any]


class BankPatchRequest(StrictDto):
    expected_revision: StrictInt = Field(ge=1)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    status: Literal["ACTIVE", "ARCHIVED"] | None = None

    @model_validator(mode="after")
    def require_change(self):
        if self.display_name is None and self.status is None:
            raise ValueError("at least one bank field must change")
        return self


class BankVersionRequest(StrictDto):
    expected_revision: StrictInt = Field(ge=1)
    bank_document: dict[str, Any]


class PlanCreateRequest(StrictDto):
    display_name: str = Field(min_length=1, max_length=120)
    bank_version_ref: str = Field(pattern=r"^CBVER_[A-Za-z0-9-]{36}$")
    config_document: dict[str, Any]


class PlanPatchRequest(StrictDto):
    expected_revision: StrictInt = Field(ge=1)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    status: Literal["ACTIVE", "ARCHIVED"] | None = None

    @model_validator(mode="after")
    def require_change(self):
        if self.display_name is None and self.status is None:
            raise ValueError("at least one plan field must change")
        return self


class PlanVersionRequest(StrictDto):
    expected_revision: StrictInt = Field(ge=1)
    bank_version_ref: str = Field(pattern=r"^CBVER_[A-Za-z0-9-]{36}$")
    config_document: dict[str, Any]


class AssetVersionDto(StrictDto):
    version_ref: str = Field(pattern=r"^(CBVER|CPVER)_[A-Za-z0-9-]{36}$")
    version_number: StrictInt = Field(ge=1)
    created_at: str


class BankVersionMetadataDto(AssetVersionDto):
    version_ref: str = Field(pattern=r"^CBVER_[A-Za-z0-9-]{36}$")
    item_count: StrictInt = Field(ge=1, le=100)
    dimension_count: StrictInt

    @field_validator("dimension_count")
    @classmethod
    def single_dimension(cls, value: int) -> int:
        if value != 1:
            raise ValueError("current synthetic CAT supports one dimension")
        return value


class PlanVersionMetadataDto(AssetVersionDto):
    version_ref: str = Field(pattern=r"^CPVER_[A-Za-z0-9-]{36}$")


class SavedSimulationRequestDto(StrictDto):
    n_examinees: StrictInt = 100

    @field_validator("n_examinees")
    @classmethod
    def valid_batch_size(cls, value: int) -> int:
        if value not in {100, 1000}:
            raise ValueError("n_examinees must be 100 or 1000")
        return value


class SavedSimulationMetricsDto(StrictDto):
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


class SavedSimulationUpstreamResponseDto(EngineeringOnlyDto):
    engineering_only: Literal[True]
    psychological_interpretation_allowed: Literal[False]
    item_bank_id: str = Field(min_length=1, max_length=120)
    item_bank_version: str = Field(min_length=1, max_length=120)
    config_version: str = Field(min_length=1, max_length=120)
    n_examinees: StrictInt
    seed: StrictInt
    metrics: SavedSimulationMetricsDto
    stopping_reason_distribution: dict[
        Literal[
            "SE_THRESHOLD_REACHED",
            "MAX_ITEMS_REACHED",
            "ITEM_BANK_EXHAUSTED",
            "MANUAL_TERMINATION",
            "ERROR",
            "NOT_STOPPED",
        ],
        StrictInt,
    ]

    @field_validator("n_examinees")
    @classmethod
    def valid_batch_size(cls, value: int) -> int:
        if value not in {100, 1000}:
            raise ValueError("n_examinees must be 100 or 1000")
        return value

    @model_validator(mode="after")
    def valid_stopping_counts(self):
        counts = self.stopping_reason_distribution
        if not counts or sum(counts.values()) != self.n_examinees:
            raise ValueError("stopping counts must sum to n_examinees")
        return self


class SavedSimulationResponseDto(SavedSimulationUpstreamResponseDto):
    plan_version_ref: str = Field(pattern=r"^CPVER_[A-Za-z0-9-]{36}$")
    bank_version_ref: str = Field(pattern=r"^CBVER_[A-Za-z0-9-]{36}$")


class BankDto(StrictDto):
    bank_ref: str = Field(pattern=r"^CBANK_[A-Za-z0-9-]{36}$")
    display_name: str = Field(min_length=1, max_length=120)
    status: Literal["ACTIVE", "ARCHIVED"]
    revision: StrictInt = Field(ge=1)
    created_at: str
    updated_at: str


class BankDetailDto(BankDto):
    versions: list[BankVersionMetadataDto]


class BankListDto(EngineeringOnlyDto):
    engineering_only: Literal[True]
    psychological_interpretation_allowed: Literal[False]
    items: list[BankDto]
    has_more: bool


class BankDetailResponseDto(EngineeringOnlyDto):
    engineering_only: Literal[True]
    psychological_interpretation_allowed: Literal[False]
    bank: BankDetailDto


class BankWriteResponseDto(BankDetailResponseDto):
    version_ref: str = Field(pattern=r"^CBVER_[A-Za-z0-9-]{36}$")


class BankVersionResponseDto(EngineeringOnlyDto):
    engineering_only: Literal[True]
    psychological_interpretation_allowed: Literal[False]
    version: BankVersionMetadataDto
    bank_document: dict[str, Any]


class PlanDto(StrictDto):
    plan_ref: str = Field(pattern=r"^CPLAN_[A-Za-z0-9-]{36}$")
    display_name: str = Field(min_length=1, max_length=120)
    status: Literal["ACTIVE", "ARCHIVED"]
    revision: StrictInt = Field(ge=1)
    created_at: str
    updated_at: str


class PlanDetailDto(PlanDto):
    versions: list[PlanVersionMetadataDto]


class PlanListDto(EngineeringOnlyDto):
    engineering_only: Literal[True]
    psychological_interpretation_allowed: Literal[False]
    items: list[PlanDto]
    has_more: bool


class PlanDetailResponseDto(EngineeringOnlyDto):
    engineering_only: Literal[True]
    psychological_interpretation_allowed: Literal[False]
    plan: PlanDetailDto


class PlanWriteResponseDto(PlanDetailResponseDto):
    version_ref: str = Field(pattern=r"^CPVER_[A-Za-z0-9-]{36}$")


class PlanVersionResponseDto(EngineeringOnlyDto):
    engineering_only: Literal[True]
    psychological_interpretation_allowed: Literal[False]
    version: AssetVersionDto
    bank_version_ref: str = Field(pattern=r"^CBVER_[A-Za-z0-9-]{36}$")
    config_document: dict[str, Any]


class TemplateResponseDto(EngineeringOnlyDto):
    engineering_only: Literal[True]
    psychological_interpretation_allowed: Literal[False]
    bank_document: dict[str, Any]
    config_document: dict[str, Any]
    item_count: StrictInt = Field(ge=1, le=100)
    dimension_count: StrictInt

    @field_validator("dimension_count")
    @classmethod
    def single_dimension(cls, value: int) -> int:
        if value != 1:
            raise ValueError("current synthetic CAT supports one dimension")
        return value


class ValidatedAssetsRequest(StrictDto):
    bank_document: dict[str, Any]
    config_document: dict[str, Any] | None = None


class ValidatedAssetsResponseDto(EngineeringOnlyDto):
    engineering_only: Literal[True]
    psychological_interpretation_allowed: Literal[False]
    bank_document: dict[str, Any]
    config_document: dict[str, Any] | None
    item_count: StrictInt = Field(ge=1, le=100)
    dimension_count: StrictInt

    @field_validator("dimension_count")
    @classmethod
    def single_dimension(cls, value: int) -> int:
        if value != 1:
            raise ValueError("current synthetic CAT supports one dimension")
        return value


class PaginationQuery(StrictDto):
    limit: StrictInt = Field(default=30, ge=1, le=100)
    skip: StrictInt = Field(default=0, ge=0, le=100000)


__all__ = [
    "BankCreateRequest",
    "BankDetailDto",
    "BankDetailResponseDto",
    "BankDto",
    "BankListDto",
    "BankPatchRequest",
    "BankVersionMetadataDto",
    "BankVersionRequest",
    "BankVersionResponseDto",
    "BankWriteResponseDto",
    "PaginationQuery",
    "PlanCreateRequest",
    "PlanDetailDto",
    "PlanDetailResponseDto",
    "PlanDto",
    "PlanListDto",
    "PlanPatchRequest",
    "PlanVersionMetadataDto",
    "PlanVersionRequest",
    "PlanVersionResponseDto",
    "PlanWriteResponseDto",
    "SavedSimulationMetricsDto",
    "SavedSimulationRequestDto",
    "SavedSimulationResponseDto",
    "SavedSimulationUpstreamResponseDto",
    "TemplateResponseDto",
    "ValidatedAssetsRequest",
    "ValidatedAssetsResponseDto",
]
