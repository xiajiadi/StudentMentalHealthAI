"""Closed request and safe response schemas for research task publication."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)


class ResearchTaskRequest(BaseModel):
    # Datetimes arrive as ISO-8601 strings in JSON; identifiers and version
    # numbers remain explicitly strict through StrictStr/StrictInt fields.
    model_config = ConfigDict(extra="forbid")


class ResearchTaskPublishRequest(ResearchTaskRequest):
    class_ref: StrictStr = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    )
    task_ref: StrictStr = Field(
        min_length=6,
        max_length=128,
        pattern=r"^TASK_[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    )
    binding_ref: StrictStr = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    )
    profile_version_number: StrictInt = Field(ge=1, le=2_147_483_647)
    opens_at: datetime
    due_at: datetime

    @field_validator("opens_at", "due_at", mode="before")
    @classmethod
    def parse_zoned_iso_datetime(cls, value: object) -> datetime:
        if type(value) is not str or not 1 <= len(value) <= 64:
            raise ValueError("timestamp must be an ISO-8601 string")
        candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            raise ValueError("timestamp must be an ISO-8601 string") from None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return parsed.astimezone(UTC)

    @model_validator(mode="after")
    def require_ordered_window(self):
        if self.due_at <= self.opens_at:
            raise ValueError("task window must have a positive duration")
        return self


class ResearchTaskBindingOptionDto(BaseModel):
    """Safe admin selector; excludes profile hashes and CAT configuration."""

    model_config = ConfigDict(extra="forbid", from_attributes=True, strict=True)

    binding_ref: StrictStr = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    )
    profile_ref: StrictStr = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    )
    profile_version_number: StrictInt = Field(ge=1, le=2_147_483_647)
    source_population_scope: StrictStr = Field(min_length=1, max_length=64)
    instrument_id: StrictStr = Field(min_length=1, max_length=128)
    instrument_version: StrictStr = Field(min_length=1, max_length=64)
    research_only: Literal[True]
    publication_status: Literal["not_approved_for_publication_or_operational_use"]


class ResearchTaskOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, strict=True)

    @field_validator("opens_at", "due_at", "published_at", mode="after", check_fields=False)
    @classmethod
    def normalize_datetime_to_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class ResearchTaskPublicationDto(ResearchTaskOutput):
    task_ref: StrictStr = Field(min_length=1, max_length=128)
    class_ref: StrictStr = Field(min_length=1, max_length=128)
    binding_ref: StrictStr = Field(min_length=1, max_length=128)
    profile_ref: StrictStr = Field(min_length=1, max_length=128)
    profile_version_number: StrictInt = Field(ge=1, le=2_147_483_647)
    source_population_scope: StrictStr = Field(min_length=1, max_length=64)
    instrument_id: StrictStr = Field(min_length=1, max_length=128)
    instrument_version: StrictStr = Field(min_length=1, max_length=64)
    status: Literal["PUBLISHED"]
    opens_at: datetime
    due_at: datetime
    published_at: datetime
    published_enrollment_count: StrictInt = Field(ge=0)
    response_origin: Literal["PUBLIC_OBSERVED"]
    research_only: Literal[True]
    publication_status: Literal["not_approved_for_publication_or_operational_use"]
