"""Typed browser-facing response models for the candidate API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from smhai_backend.integrations.rag import KnowledgeChunk


class ApiEnvelope[T](BaseModel):
    model_config = ConfigDict(extra="ignore")

    request_id: str
    trace_id: str
    data: T


class HealthLiveDto(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    service: str
    contract_version: str


class HealthReadyDto(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    core: dict[str, str]
    optional_dependencies_not_used_for_core_readiness: bool = True


class DependencyStatusDto(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    integration: str


class ApiHealthDto(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    contract_version: str
    dependencies: dict[str, DependencyStatusDto]


class RetrievalResponseDto(BaseModel):
    model_config = ConfigDict(extra="ignore")

    retrieval_id: str
    chunks: list[KnowledgeChunk]
    label: str | None = None
    trace: dict[str, object] | None = None


class SafetyResponseDto(BaseModel):
    model_config = ConfigDict(extra="ignore")

    decision: str
    reason_codes: list[str]
    human_review_required: bool
    safety_action: str


class ReviewActionResponseDto(BaseModel):
    model_config = ConfigDict(extra="ignore")

    report_id: str
    review_status: str
    review_id: str


class EmptyObjectDto(BaseModel):
    """Explicit schema for an intentionally empty response object."""

    model_config = ConfigDict(extra="ignore")
