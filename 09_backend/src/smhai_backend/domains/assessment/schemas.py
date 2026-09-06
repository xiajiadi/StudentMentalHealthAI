"""Assessment DTOs aligned with the frozen assessment.v1 and api.v1 inputs."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr


class AssessmentStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_id: str = Field(pattern=r"^SUBJ_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    instrument_id: str = Field(min_length=1, max_length=160)
    instrument_version: str = Field(min_length=1, max_length=64)


class ResponseEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(pattern=r"^ITEM_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    response: Annotated[StrictStr | StrictInt | StrictFloat | StrictBool, Field()]


class CompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssessmentDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    assessment_id: str
    subject_id: str
    instrument: dict[str, Any]
    population_scope: str
    status: str
    dimensions: dict[str, Any]
    risk: dict[str, Any]
    response_summary: dict[str, Any]
    provenance: dict[str, Any]
    timestamps: dict[str, Any]


class AssessmentStateDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_id: str
    subject_id: str | None = None
    status: str
    selected_item_id: str | None = None
    current_item: dict[str, Any] | None = None
    current_index: int = 0
    answered_count: int = 0
    administered_count: int = 0
    can_complete: bool = False
    max_items: int | None = None
    cat_provider_version: str | None = None
    cat_item_bank_version: str | None = None
    cat_config_version: str | None = None
