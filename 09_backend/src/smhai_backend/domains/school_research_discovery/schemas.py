"""Closed, content-free DTOs for student research task discovery/history."""

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


class _Output(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, strict=True)

    @field_validator("opens_at", "due_at", "completed_at", mode="after", check_fields=False)
    @classmethod
    def normalize_datetime_to_utc(cls, value):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class ResearchDiscoveryTaskDto(_Output):
    task_ref: StrictStr = Field(min_length=1, max_length=128)
    class_ref: StrictStr = Field(min_length=1, max_length=128)
    profile_ref: StrictStr = Field(min_length=1, max_length=128)
    source_population_scope: StrictStr = Field(min_length=1, max_length=64)
    instrument_id: StrictStr = Field(min_length=1, max_length=128)
    instrument_version: StrictStr = Field(min_length=1, max_length=64)
    publication_status: Literal["not_approved_for_publication_or_operational_use"]
    research_only: Literal[True] = True
    opens_at: datetime
    due_at: datetime | None
    status: Literal["PUBLISHED"]
    completion_count: StrictInt = Field(ge=0, le=1)
    session_ref: StrictStr | None = Field(default=None, min_length=1, max_length=128)
    session_status: Literal["IN_PROGRESS", "COMPLETED", "FAILED", "ABANDONED"] | None = None
    items_answered: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def validate_session_projection(self):
        if self.session_ref is None:
            if (
                self.session_status is not None
                or self.items_answered != 0
                or self.completion_count != 0
            ):
                raise ValueError("research task session projection is inconsistent")
        elif self.session_status is None or self.completion_count != int(
            self.session_status == "COMPLETED"
        ):
            raise ValueError("research task session projection is inconsistent")
        return self


class ResearchDiscoverySessionDto(_Output):
    session_ref: StrictStr = Field(min_length=1, max_length=128)
    task_ref: StrictStr = Field(min_length=1, max_length=128)
    status: Literal["IN_PROGRESS", "COMPLETED", "FAILED", "ABANDONED"]
    items_answered: StrictInt = Field(ge=0)
    completed_at: datetime | None
    research_only: Literal[True] = True


class ResearchDiscoveryTaskPage(_Output):
    items: list[ResearchDiscoveryTaskDto] = Field(max_length=30)
    total: StrictInt = Field(ge=0)
    limit: StrictInt = Field(ge=1, le=30)
    offset: StrictInt = Field(ge=0, le=10_000)
    has_more: bool
    next_offset: StrictInt | None = Field(ge=0)


class ResearchDiscoverySessionPage(_Output):
    items: list[ResearchDiscoverySessionDto] = Field(max_length=30)
    total: StrictInt = Field(ge=0)
    limit: StrictInt = Field(ge=1, le=30)
    offset: StrictInt = Field(ge=0, le=10_000)
    has_more: bool
    next_offset: StrictInt | None = Field(ge=0)
