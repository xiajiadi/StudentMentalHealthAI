"""Independent conversation route adapter for the school Runtime host."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
)

ROUTE_PATH = "/internal/llm/independent-generations"
SCHOOL_MODEL_ID = "qwen2.5-7b-instruct-school-demo"
SCHOOL_CONTRACT_MODEL_ID = "MODEL_local_primary"
SCHOOL_PROVIDER_MODEL_ID = "qwen2.5:7b-instruct-q4_K_M"


class StrictDto(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PromptRefDto(StrictDto):
    prompt_id: str = Field(pattern=r"^PROMPT_[A-Za-z0-9][A-Za-z0-9_.-]*$", max_length=160)
    prompt_version: str = Field(min_length=1, max_length=64)


class IndependentMessageDto(StrictDto):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=16_000)


class IndependentConfigDto(StrictDto):
    max_output_tokens: int = Field(default=256, ge=1, le=8192)
    temperature: float = Field(default=0.2, ge=0)
    top_p: float = Field(default=0.9, gt=0, le=1)
    top_k: int | None = Field(default=None, ge=1)
    context_length: int | None = Field(default=None, ge=1, le=8192)
    timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    keep_alive: StrictStr | StrictInt | StrictFloat = "5m"
    seed: int | None = None
    stop: list[str] = Field(default_factory=list, max_length=8)
    think: bool | str | None = None

    def to_runtime_config(self) -> Any:
        from llm_runtime.domain.models import GenerationConfig

        return GenerationConfig(
            max_output_tokens=self.max_output_tokens,
            temperature=self.temperature,
            top_p=self.top_p,
            top_k=self.top_k,
            context_length=self.context_length,
            timeout_seconds=self.timeout_seconds,
            keep_alive=self.keep_alive,
            seed=self.seed,
            stop=tuple(self.stop),
            think=self.think,
        )


class IndependentGenerationDto(StrictDto):
    request_id: str = Field(pattern=r"^REQ_[A-Za-z0-9][A-Za-z0-9_.-]*$", max_length=160)
    trace_id: str = Field(pattern=r"^TRACE_[A-Za-z0-9][A-Za-z0-9_.-]*$", max_length=160)
    generation_id: str = Field(pattern=r"^GEN_[A-Za-z0-9][A-Za-z0-9_.-]*$", max_length=160)
    conversation_id: str = Field(pattern=r"^CONV_[A-Za-z0-9][A-Za-z0-9_.-]*$", max_length=160)
    turn_id: str = Field(pattern=r"^TURN_[A-Za-z0-9][A-Za-z0-9_.-]*$", max_length=160)
    retrieval_id: str = Field(pattern=r"^RETR_[A-Za-z0-9][A-Za-z0-9_.-]*$", max_length=160)
    chunk_ids: list[str] = Field(min_length=1, max_length=100)
    prompt_ref: PromptRefDto
    messages: list[IndependentMessageDto] = Field(min_length=1, max_length=32)
    structured_schema: dict[str, Any] = Field(min_length=1)
    config: IndependentConfigDto

    @field_validator("chunk_ids")
    @classmethod
    def validate_chunk_ids(cls, values: list[str]) -> list[str]:
        if any(
            not value
            or len(value) > 160
            or not re.fullmatch(r"CHUNK_[A-Za-z0-9][A-Za-z0-9_.-]*", value)
            for value in values
        ):
            raise ValueError("chunk ids must use the CHUNK_ identifier format")
        if len(set(values)) != len(values):
            raise ValueError("chunk ids must be unique")
        return values

    @field_validator("messages")
    @classmethod
    def require_user_message(cls, values: list[IndependentMessageDto]) -> list[IndependentMessageDto]:
        if not any(message.role == "user" for message in values):
            raise ValueError("at least one user message is required")
        return values


@dataclass(frozen=True)
class IndependentRuntimeRequest:
    """RuntimeService-compatible request without assessment or subject fields."""

    request_id: str
    trace_id: str
    generation_id: str
    conversation_id: str
    turn_id: str
    retrieval_id: str
    chunk_ids: tuple[str, ...]
    prompt_id: str
    prompt_version: str
    contract_model_id: str
    logical_model_id: str
    messages: tuple[Mapping[str, str], ...]
    structured_schema: dict[str, Any]
    config: Any
    provider_model_id: str | None = None
    system_prompt: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    target_role: str = "student"
    purpose: str = "education_support"
    stream: bool = False

    @property
    def prompt(self) -> str:
        return "\n".join(message["content"] for message in self.messages if message["role"] == "user")

    @property
    def effective_messages(self) -> list[dict[str, str]]:
        return [dict(message) for message in self.messages]

    @property
    def effective_provider_model_id(self) -> str:
        return self.provider_model_id or self.logical_model_id


def _to_runtime_request(payload: IndependentGenerationDto, model: Any) -> IndependentRuntimeRequest:
    return IndependentRuntimeRequest(
        request_id=payload.request_id,
        trace_id=payload.trace_id,
        generation_id=payload.generation_id,
        conversation_id=payload.conversation_id,
        turn_id=payload.turn_id,
        retrieval_id=payload.retrieval_id,
        chunk_ids=tuple(payload.chunk_ids),
        prompt_id=payload.prompt_ref.prompt_id,
        prompt_version=payload.prompt_ref.prompt_version,
        contract_model_id=model.contract_model_id,
        logical_model_id=model.logical_model_id,
        messages=tuple(message.model_dump() for message in payload.messages),
        structured_schema=payload.structured_schema,
        config=payload.config.to_runtime_config(),
    )


def _resolve_school_default(runtime: Any) -> Any:
    service = runtime.service
    try:
        model = service.registry.resolve_primary(service.default_model_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "SCHOOL_RUNTIME_CONFIGURATION_INVALID"},
        ) from exc
    if (
        model.logical_model_id != SCHOOL_MODEL_ID
        or model.contract_model_id != SCHOOL_CONTRACT_MODEL_ID
        or model.provider_model_id != SCHOOL_PROVIDER_MODEL_ID
        or service.registry.cloud_fallback
        or service.max_attempts != 1
        or service.registry.fallback_chain(model.logical_model_id)
    ):
        raise HTTPException(status_code=503, detail={"code": "SCHOOL_RUNTIME_CONFIGURATION_INVALID"})
    return model


def _status_for_error(error: Any) -> int:
    from llm_runtime.errors import RuntimeErrorCode

    if error.status_code is not None:
        return error.status_code
    if error.code is RuntimeErrorCode.MODEL_NOT_FOUND:
        return 404
    if error.code is RuntimeErrorCode.RUNTIME_BUSY:
        return 429
    if error.code in {
        RuntimeErrorCode.INVALID_STRUCTURED_OUTPUT,
        RuntimeErrorCode.CONFIGURATION_ERROR,
    }:
        return 422
    if error.code is RuntimeErrorCode.REQUEST_TIMEOUT:
        return 504
    return 503


def _result_payload(result: Any, payload: IndependentGenerationDto) -> dict[str, Any]:
    trace = result.trace.to_dict()
    return {
        "request_id": result.request_id,
        "trace_id": result.trace_id,
        "generation_id": payload.generation_id,
        "conversation_id": payload.conversation_id,
        "turn_id": payload.turn_id,
        "data": {
            "text": result.text,
            "model_id": result.executed_model.contract_model_id,
            "logical_model_id": result.actual_model_id,
            "model_version": trace.get("model_revision") or result.executed_model.provider_model_id,
            "runtime_version": trace.get("runtime_version", "unknown"),
            "trace": trace,
            "buffered": True,
            "synthetic_fixture_only": bool(result.response.metadata.get("synthetic", False)),
        },
    }


def attach_independent_routes(app: FastAPI, runtime: Any) -> None:
    """Attach a student education-support route without creating generation.v1."""

    @app.post(ROUTE_PATH, operation_id="independentStudentGenerations")
    async def independent_generation(payload: IndependentGenerationDto) -> dict[str, Any]:
        from llm_runtime.errors import LLMRuntimeError

        model = _resolve_school_default(runtime)
        independent_request = _to_runtime_request(payload, model)
        try:
            result = await run_in_threadpool(runtime.service.generate, independent_request)
        except LLMRuntimeError as exc:
            raise HTTPException(
                status_code=_status_for_error(exc),
                detail=exc.to_dict(),
            ) from exc
        return _result_payload(result, payload)
