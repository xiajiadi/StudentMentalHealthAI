"""Assessment-free Backend route for the fixed DeepSeek school Runtime identity."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field
from school_independent_runtime import (
    IndependentGenerationDto,
    _result_payload,
    _status_for_error,
    _to_runtime_request,
)

DEEPSEEK_LOGICAL_MODEL_ID = "deepseek-flash-education-support"
DEEPSEEK_CONTRACT_MODEL_ID = "MODEL_deepseek_flash_education_support"
DEEPSEEK_PROVIDER_ID = "deepseek"
DEEPSEEK_PROVIDER_MODEL_ID = "deepseek-flash"
ROUTE_PATH = "/internal/llm/independent-generations"


class WorkspaceStepDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[dict[str, Any]] = Field(min_length=2, max_length=48)
    tools: list[dict[str, Any]] = Field(min_length=1, max_length=24)


def _resolve_deepseek_default(runtime: Any) -> Any:
    service = runtime.service
    try:
        model = service.registry.resolve_primary(DEEPSEEK_LOGICAL_MODEL_ID)
        fallback_chain = service.registry.fallback_chain(DEEPSEEK_LOGICAL_MODEL_ID)
    except (KeyError, ValueError):
        raise HTTPException(
            status_code=503,
            detail={"code": "SCHOOL_RUNTIME_CONFIGURATION_INVALID"},
        ) from None
    if (
        service.default_model_id != DEEPSEEK_LOGICAL_MODEL_ID
        or model.logical_model_id != DEEPSEEK_LOGICAL_MODEL_ID
        or model.contract_model_id != DEEPSEEK_CONTRACT_MODEL_ID
        or model.provider != DEEPSEEK_PROVIDER_ID
        or model.provider_model_id != DEEPSEEK_PROVIDER_MODEL_ID
        or service.registry.cloud_fallback is not False
        or service.max_attempts != 1
        or fallback_chain
    ):
        raise HTTPException(
            status_code=503,
            detail={"code": "SCHOOL_RUNTIME_CONFIGURATION_INVALID"},
        )
    return model


def attach_deepseek_independent_route(app: FastAPI, runtime: Any) -> None:
    """Attach one buffered education-generation route behind Runtime auth middleware."""

    @app.post(ROUTE_PATH, operation_id="deepSeekIndependentStudentGenerations")
    async def independent_generation(
        payload: IndependentGenerationDto,
    ) -> dict[str, Any]:
        from llm_runtime.errors import LLMRuntimeError

        model = _resolve_deepseek_default(runtime)
        request = _to_runtime_request(payload, model)
        try:
            result = await run_in_threadpool(runtime.service.generate, request)
        except LLMRuntimeError as exc:
            raise HTTPException(
                status_code=_status_for_error(exc),
                detail=exc.to_dict(),
            ) from exc
        return _result_payload(result, payload)

    @app.post("/internal/llm/workspace-agent/step", include_in_schema=False)
    async def workspace_step(payload: WorkspaceStepDto) -> dict[str, Any]:
        from llm_runtime.errors import LLMRuntimeError
        from llm_runtime.providers.deepseek import DeepSeekProvider

        if len(payload.model_dump_json()) > 64_000:
            raise HTTPException(
                status_code=413, detail="workspace context is too large"
            )
        model = _resolve_deepseek_default(runtime)
        try:
            provider = runtime.service.provider_registry.resolve(model.provider)
            if not isinstance(provider, DeepSeekProvider):
                raise HTTPException(
                    status_code=503, detail="workspace model unavailable"
                )
            return await run_in_threadpool(
                provider.workspace_agent_step, payload.messages, payload.tools
            )
        except LLMRuntimeError as exc:
            raise HTTPException(
                status_code=_status_for_error(exc), detail=exc.code.value
            ) from exc


__all__ = [
    "DEEPSEEK_CONTRACT_MODEL_ID",
    "DEEPSEEK_LOGICAL_MODEL_ID",
    "DEEPSEEK_PROVIDER_ID",
    "DEEPSEEK_PROVIDER_MODEL_ID",
    "ROUTE_PATH",
    "attach_deepseek_independent_route",
]
