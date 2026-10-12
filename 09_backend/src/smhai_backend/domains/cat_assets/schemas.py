"""Strict request and metadata-only response DTOs for CAT asset management."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator


class StrictDto(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


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


class BankDto(StrictDto):
    bank_ref: str = Field(pattern=r"^CBANK_[A-Za-z0-9-]{36}$")
    display_name: str = Field(min_length=1, max_length=120)
    status: Literal["ACTIVE", "ARCHIVED"]
    revision: StrictInt = Field(ge=1)
    created_at: str
    updated_at: str


class BankDetailDto(BankDto):
    versions: list[BankVersionMetadataDto]


class BankListDto(StrictDto):
    engineering_only: Literal[True]
    psychological_interpretation_allowed: Literal[False]
    items: list[BankDto]
    has_more: bool


class BankDetailResponseDto(StrictDto):
    engineering_only: Literal[True]
    psychological_interpretation_allowed: Literal[False]
    bank: BankDetailDto


class BankWriteResponseDto(BankDetailResponseDto):
    version_ref: str = Field(pattern=r"^CBVER_[A-Za-z0-9-]{36}$")


class BankVersionResponseDto(StrictDto):
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


class PlanListDto(StrictDto):
    engineering_only: Literal[True]
    psychological_interpretation_allowed: Literal[False]
    items: list[PlanDto]
    has_more: bool


class PlanDetailResponseDto(StrictDto):
    engineering_only: Literal[True]
    psychological_interpretation_allowed: Literal[False]
    plan: PlanDetailDto


class PlanWriteResponseDto(PlanDetailResponseDto):
    version_ref: str = Field(pattern=r"^CPVER_[A-Za-z0-9-]{36}$")


class PlanVersionResponseDto(StrictDto):
    engineering_only: Literal[True]
    psychological_interpretation_allowed: Literal[False]
    version: AssetVersionDto
    bank_version_ref: str = Field(pattern=r"^CBVER_[A-Za-z0-9-]{36}$")
    config_document: dict[str, Any]


class TemplateResponseDto(StrictDto):
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


class ValidatedAssetsResponseDto(StrictDto):
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
    "TemplateResponseDto",
    "ValidatedAssetsRequest",
    "ValidatedAssetsResponseDto",
]
