"""Closed selectors and content-free receipts for an 800-case cohort.

The server resolves membership, study pins and private case assignments. No
caller-supplied population, response row, hash, seed or approval is accepted.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

Reference = Annotated[
    StrictStr,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"),
]


class ResearchCohortSealRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    binding_ref: Reference
    profile_version_number: StrictInt = Field(ge=1, le=2_147_483_647)
    batch_refs: list[Reference] = Field(min_length=8, max_length=8)

    @field_validator("batch_refs")
    @classmethod
    def require_unique_batches(cls, value: list[str]) -> list[str]:
        if len(set(value)) != 8:
            raise ValueError("eight distinct account import batches are required")
        # Request order has no semantic meaning. Normalize before generating
        # the idempotency fingerprint; never use it to assign private cases.
        return sorted(value)


class ResearchCohortReceiptDto(BaseModel):
    """Operational metadata only; counts do not imply completed observations."""

    model_config = ConfigDict(extra="forbid", from_attributes=True, strict=True)

    cohort_ref: Reference
    study_ref: Reference
    profile_ref: Reference
    profile_version_number: StrictInt = Field(ge=1, le=2_147_483_647)
    source_population_scope: StrictStr = Field(min_length=1, max_length=64)
    instrument_id: Reference
    status: Literal["SEALED"]
    subject_count: StrictInt = Field(ge=800, le=800)
    class_count: StrictInt = Field(ge=8, le=8)
    assigned_distinct_cases: StrictInt = Field(ge=800, le=800)
    sealed_at: datetime
    response_origin: Literal["PUBLIC_OBSERVED"]
    research_only: Literal[True]
    publication_status: Literal["not_approved_for_publication_or_operational_use"]

    @field_validator("sealed_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
