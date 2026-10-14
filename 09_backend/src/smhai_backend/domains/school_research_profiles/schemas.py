"""Strict request and candidate-only response DTOs for research profiles."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator


class ResearchProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ResearchProfileImportRequest(ResearchProfileRequest):
    profile_ref: StrictStr = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    )
    version_number: StrictInt = Field(ge=1, le=2_147_483_647)


class ResearchProfileOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, strict=True)

    @field_validator("*", mode="after")
    @classmethod
    def normalize_datetime_to_utc(cls, value):
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                return value.replace(tzinfo=UTC)
            return value.astimezone(UTC)
        return value


class ResearchProfileCandidateDto(ResearchProfileOutput):
    profile_ref: StrictStr = Field(min_length=1, max_length=128)
    version_number: StrictInt | None = Field(ge=1, le=2_147_483_647)
    source_population_scope: StrictStr | None = Field(default=None, max_length=64)
    instrument_id: StrictStr = Field(min_length=1, max_length=128)
    research_only: Literal[True]
    publication_status: Literal["not_approved_for_publication_or_operational_use"]
    rights_status: StrictStr = Field(min_length=1, max_length=32)
    execution_status: StrictStr = Field(min_length=1, max_length=32)
    created_at: datetime | None = None
    catalog_state: Literal[
        "REGISTRY_CANDIDATE",
        "IMPORTED_CANDIDATE",
        "EXISTING_CANDIDATE",
        "IDEMPOTENT_REPLAY",
    ]
