"""Assessment DTOs aligned with the frozen assessment.v1 and api.v1 inputs."""

from __future__ import annotations

from typing import Annotated, Literal

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


class AssessmentInstrumentDto(BaseModel):
    model_config = ConfigDict(extra="ignore")

    instrument_id: str
    version: str


class AssessmentDimensionDto(BaseModel):
    model_config = ConfigDict(extra="ignore")

    theta: float | None
    se: float | None
    score: float | None
    band: Literal["normal", "attention", "high", "unknown"]
    interpretation_status: Literal["estimated", "insufficient_data", "not_scored"]
    items_answered: int


class AssessmentRiskDto(BaseModel):
    model_config = ConfigDict(extra="ignore")

    level: Literal["normal", "attention", "high", "crisis"]
    need_human_review: bool
    reason_codes: list[str]
    ruleset_id: str


class AssessmentResponseSummaryDto(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items_answered: int
    duration_seconds: int | None


class AssessmentProvenanceDto(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_adapter: str
    adapter_version: str
    cat_engine_version: str
    item_bank_version: str


class AssessmentTimestampsDto(BaseModel):
    model_config = ConfigDict(extra="ignore")

    started_at: str
    completed_at: str | None


class AssessmentDto(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: Literal["assessment.v1"]
    assessment_id: str
    subject_id: str
    instrument: AssessmentInstrumentDto
    population_scope: str
    status: str
    dimensions: dict[str, AssessmentDimensionDto]
    risk: AssessmentRiskDto
    response_summary: AssessmentResponseSummaryDto
    provenance: AssessmentProvenanceDto
    timestamps: AssessmentTimestampsDto


class CurrentItemOptionDto(BaseModel):
    model_config = ConfigDict(extra="ignore")

    value: str | None = None
    label: str | None = None


class CurrentItemDto(BaseModel):
    model_config = ConfigDict(extra="ignore")

    item_id: str | None = None
    prompt: str | None = None
    options: list[CurrentItemOptionDto] = Field(default_factory=list)


class AssessmentStateDto(BaseModel):
    model_config = ConfigDict(extra="ignore")

    assessment_id: str
    subject_id: str | None = None
    status: str
    selected_item_id: str | None = None
    current_item: CurrentItemDto | None = None
    current_index: int = 0
    answered_count: int = 0
    administered_count: int = 0
    can_complete: bool = False
    max_items: int | None = None
    cat_provider_version: str | None = None
    cat_item_bank_version: str | None = None
    cat_config_version: str | None = None
