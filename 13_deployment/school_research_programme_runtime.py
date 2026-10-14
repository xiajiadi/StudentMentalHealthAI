"""Internal hold-only runtime route for qualified school programme research."""

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
from school_llm_runtime import (
    EXPECTED_CONTRACT_MODEL_ID,
    EXPECTED_MODEL_DIGEST,
    EXPECTED_MODEL_ID,
    EXPECTED_PROVIDER_MODEL_ID,
)

ROUTE_PATH = "/internal/llm/research-programme-generations"
SCHEMA_VERSION = "research_programme_generation.v1"
PURPOSE = "staff_school_programme_research"
TARGET_ROLE = "psychological_specialist"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class StrictDto(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ResearchPromptRefDto(StrictDto):
    prompt_id: StrictStr = Field(
        pattern=r"^PROMPT_[A-Za-z0-9][A-Za-z0-9_.-]*$", max_length=160
    )
    prompt_version: StrictStr = Field(min_length=1, max_length=64)


class ResearchMessageDto(StrictDto):
    role: Literal["system", "user", "assistant"]
    content: StrictStr = Field(min_length=1, max_length=16_000)


class ResearchGenerationConfigDto(StrictDto):
    max_output_tokens: StrictInt = Field(default=256, ge=1, le=8192)
    temperature: StrictFloat = Field(default=0.2, ge=0)
    top_p: StrictFloat = Field(default=0.9, gt=0, le=1)
    top_k: StrictInt | None = Field(default=None, ge=1)
    context_length: StrictInt | None = Field(default=None, ge=1, le=8192)
    timeout_seconds: StrictFloat = Field(default=60.0, gt=0, le=300)
    keep_alive: StrictStr | StrictInt | StrictFloat = "5m"
    seed: StrictInt | None = None
    stop: list[StrictStr] = Field(default_factory=list, max_length=8)
    think: bool | StrictStr | None = None

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


class ResearchProgrammeGenerationDto(StrictDto):
    schema_version: Literal[SCHEMA_VERSION]
    request_id: StrictStr = Field(
        pattern=r"^REQ_[A-Za-z0-9][A-Za-z0-9_.-]*$", max_length=160
    )
    trace_id: StrictStr = Field(
        pattern=r"^TRACE_[A-Za-z0-9][A-Za-z0-9_.-]*$", max_length=160
    )
    generation_id: StrictStr = Field(
        pattern=r"^GEN_[A-Za-z0-9][A-Za-z0-9_.-]*$", max_length=160
    )
    retrieval_id: StrictStr = Field(
        pattern=r"^RETR_[A-Za-z0-9][A-Za-z0-9_.-]*$", max_length=160
    )
    programme_ref: StrictStr = Field(
        pattern=r"^PROGRAMME_[A-Za-z0-9][A-Za-z0-9_.-]*$", max_length=160
    )
    source_manifest_sha256: StrictStr = Field(pattern=_SHA256.pattern)
    prompt_ref: ResearchPromptRefDto
    chunk_ids: list[StrictStr] = Field(min_length=1, max_length=100)
    messages: list[ResearchMessageDto] = Field(min_length=1, max_length=32)
    structured_schema: dict[str, Any] = Field(min_length=1)
    config: ResearchGenerationConfigDto

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

    @field_validator("source_manifest_sha256")
    @classmethod
    def validate_manifest_digest(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("source manifest digest must be lowercase SHA-256")
        return value

    @field_validator("messages")
    @classmethod
    def require_user_message(cls, values: list[ResearchMessageDto]) -> list[ResearchMessageDto]:
        if not any(message.role == "user" for message in values):
            raise ValueError("at least one user message is required")
        return values


class ResearchProgrammeGenerationDataDto(StrictDto):
    text: StrictStr
    model_id: Literal[EXPECTED_CONTRACT_MODEL_ID]
    logical_model_id: Literal[EXPECTED_MODEL_ID]
    model_version: StrictStr
    runtime_version: StrictStr
    trace: dict[str, Any]
    buffered: Literal[True]


class ResearchProgrammeGenerationResponseDto(StrictDto):
    schema_version: Literal[SCHEMA_VERSION]
    request_id: StrictStr
    trace_id: StrictStr
    generation_id: StrictStr
    retrieval_id: StrictStr
    programme_ref: StrictStr
    source_manifest_sha256: StrictStr
    prompt_ref: ResearchPromptRefDto
    chunk_ids: list[StrictStr]
    purpose: Literal[PURPOSE]
    target_role: Literal[TARGET_ROLE]
    production_use: Literal[False]
    publication_eligible: Literal[False]
    status: Literal["HOLD_FOR_REVIEW"]
    data: ResearchProgrammeGenerationDataDto


@dataclass(frozen=True, slots=True)
class ResearchProgrammeRuntimeRequest:
    """Runtime-compatible request without student, subject, or assessment IDs."""

    request_id: str
    trace_id: str
    generation_id: str
    retrieval_id: str
    programme_ref: str
    source_manifest_sha256: str
    chunk_ids: tuple[str, ...]
    prompt_id: str
    prompt_version: str
    contract_model_id: str
    logical_model_id: str
    messages: tuple[Mapping[str, str], ...]
    structured_schema: dict[str, Any]
    config: Any
    system_prompt: str | None = None
    provider_model_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    target_role: str = TARGET_ROLE
    purpose: str = PURPOSE
    production_use: bool = False
    publication_eligible: bool = False
    stream: bool = False

    @property
    def prompt(self) -> str:
        return "\n".join(
            message["content"] for message in self.messages if message["role"] == "user"
        )

    @property
    def effective_messages(self) -> list[dict[str, str]]:
        return [dict(message) for message in self.messages]

    @property
    def effective_provider_model_id(self) -> str:
        return self.provider_model_id or EXPECTED_PROVIDER_MODEL_ID


def _resolve_research_programme_model(runtime: Any) -> Any:
    service = runtime.service
    try:
        model = service.registry.resolve_primary(service.default_model_id)
        valid = (
            service.default_model_id == EXPECTED_MODEL_ID
            and model.logical_model_id == EXPECTED_MODEL_ID
            and model.contract_model_id == EXPECTED_CONTRACT_MODEL_ID
            and model.provider == "ollama"
            and model.provider_model_id == EXPECTED_PROVIDER_MODEL_ID
            and model.digest == EXPECTED_MODEL_DIGEST
            and model.expected_digest == EXPECTED_MODEL_DIGEST
            and model.local_only is True
            and service.registry.cloud_fallback is False
            and type(service.max_attempts) is int
            and service.max_attempts == 1
            and not service.registry.fallback_chain(model.logical_model_id)
        )
    except (AttributeError, KeyError, TypeError):
        raise HTTPException(
            status_code=503,
            detail={"code": "SCHOOL_RUNTIME_CONFIGURATION_INVALID"},
        ) from None
    if not valid:
        raise HTTPException(
            status_code=503,
            detail={"code": "SCHOOL_RUNTIME_CONFIGURATION_INVALID"},
        )
    return model


def _to_runtime_request(
    payload: ResearchProgrammeGenerationDto, model: Any
) -> ResearchProgrammeRuntimeRequest:
    return ResearchProgrammeRuntimeRequest(
        request_id=payload.request_id,
        trace_id=payload.trace_id,
        generation_id=payload.generation_id,
        retrieval_id=payload.retrieval_id,
        programme_ref=payload.programme_ref,
        source_manifest_sha256=payload.source_manifest_sha256,
        chunk_ids=tuple(payload.chunk_ids),
        prompt_id=payload.prompt_ref.prompt_id,
        prompt_version=payload.prompt_ref.prompt_version,
        contract_model_id=model.contract_model_id,
        logical_model_id=model.logical_model_id,
        messages=tuple(message.model_dump() for message in payload.messages),
        structured_schema=payload.structured_schema,
        config=payload.config.to_runtime_config(),
    )


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


def _result_payload(
    result: Any, payload: ResearchProgrammeGenerationDto, model: Any
) -> dict[str, Any]:
    try:
        trace = result.trace.to_dict()
        executed = result.executed_model
        attempts = result.attempts
        text = result.text
    except (AttributeError, TypeError):
        raise HTTPException(
            status_code=502,
            detail={"code": "RESEARCH_PROGRAMME_RESULT_SCOPE_MISMATCH"},
        ) from None
    if (
        not isinstance(trace, dict)
        or result.status != "success"
        or result.request_id != payload.request_id
        or result.trace_id != payload.trace_id
        or trace.get("request_id") != payload.request_id
        or trace.get("trace_id") != payload.trace_id
        or trace.get("logical_model") != model.logical_model_id
        or trace.get("provider") != "ollama"
        or trace.get("provider_model") != model.provider_model_id
        or trace.get("digest") != EXPECTED_MODEL_DIGEST
        or trace.get("fallback_attempted") is not False
        or result.actual_model_id != model.logical_model_id
        or executed.logical_model_id != model.logical_model_id
        or executed.contract_model_id != model.contract_model_id
        or executed.provider_model_id != model.provider_model_id
        or executed.digest != EXPECTED_MODEL_DIGEST
        or executed.expected_digest != EXPECTED_MODEL_DIGEST
        or executed.local_only is not True
        or result.fallback_used is not False
        or len(attempts) != 1
        or not isinstance(text, str)
        or not text
        or len(text) > 100_000
    ):
        raise HTTPException(
            status_code=502,
            detail={"code": "RESEARCH_PROGRAMME_RESULT_SCOPE_MISMATCH"},
        )
    response = {
        "schema_version": SCHEMA_VERSION,
        "request_id": payload.request_id,
        "trace_id": payload.trace_id,
        "generation_id": payload.generation_id,
        "retrieval_id": payload.retrieval_id,
        "programme_ref": payload.programme_ref,
        "source_manifest_sha256": payload.source_manifest_sha256,
        "prompt_ref": payload.prompt_ref.model_dump(),
        "chunk_ids": list(payload.chunk_ids),
        "purpose": PURPOSE,
        "target_role": TARGET_ROLE,
        "production_use": False,
        "publication_eligible": False,
        "status": "HOLD_FOR_REVIEW",
        "data": {
            "text": text,
            "model_id": model.contract_model_id,
            "logical_model_id": model.logical_model_id,
            "model_version": trace.get("model_revision") or model.provider_model_id,
            "runtime_version": trace.get("runtime_version", "unknown"),
            "trace": trace,
            "buffered": True,
        },
    }
    return ResearchProgrammeGenerationResponseDto.model_validate(
        response, strict=True
    ).model_dump(mode="json")


def attach_research_programme_routes(app: FastAPI, runtime: Any) -> None:
    """Attach a hold-only, staff programme-generation route to the Runtime host."""

    @app.post(ROUTE_PATH, operation_id="researchProgrammeGenerations")
    async def research_programme_generation(
        payload: ResearchProgrammeGenerationDto,
    ) -> dict[str, Any]:
        from llm_runtime.errors import LLMRuntimeError

        model = _resolve_research_programme_model(runtime)
        request = _to_runtime_request(payload, model)
        try:
            result = await run_in_threadpool(runtime.service.generate, request)
        except LLMRuntimeError as exc:
            raise HTTPException(
                status_code=_status_for_error(exc),
                detail=exc.to_dict(),
            ) from exc
        return _result_payload(result, payload, model)
