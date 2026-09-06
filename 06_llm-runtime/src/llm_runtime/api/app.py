"""Loopback buffered-generation service.

Backend talks to this process instead of reaching Ollama directly.  The
runtime owns model resolution, retries, fallback policy, and provider traces.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from llm_runtime.cli import build_service
from llm_runtime.domain.models import GenerationConfig, GenerationRequest
from llm_runtime.errors import LLMRuntimeError


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(pattern=r"^REQ_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    trace_id: str = Field(pattern=r"^TRACE_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    generation_id: str = Field(pattern=r"^GEN_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    assessment_id: str = Field(pattern=r"^ASSESS_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    subject_id: str = Field(pattern=r"^SUBJ_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    target_role: str = Field(pattern=r"^(student|teacher|parent|admin)$")
    purpose: str = "education_support"
    language: str = Field(min_length=2, max_length=32)
    safety_mode: str = Field(pattern=r"^(standard|restricted)$")
    retrieval_id: str = Field(pattern=r"^RETR_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    chunk_ids: list[str] = Field(min_length=1, max_length=100)
    prompt_id: str = Field(pattern=r"^PROMPT_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    prompt_version: str = Field(min_length=1, max_length=64)
    contract_model_id: str = Field(pattern=r"^MODEL_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    logical_model_id: str = Field(min_length=1, max_length=160)
    prompt: str = Field(default="", max_length=40_000)
    messages: list[dict[str, str]] = Field(default_factory=list, max_length=32)
    stream: bool = False
    structured_schema: dict[str, Any] | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Runtime:
    def __init__(self) -> None:
        self.service = build_service()

    def health(self) -> dict[str, Any]:
        return self.service.health()

    def ready(self) -> bool:
        health = self.health()
        primary = health.get("models", {}).get("qwen2.5-0.5b-engineering", {})
        return primary.get("availability") in {"available", "ready"} and primary.get(
            "inference_readiness"
        ) in {"ready", "loaded"}

    def generate(self, payload: GenerateRequest) -> dict[str, Any]:
        if payload.stream:
            raise HTTPException(status_code=422, detail="Round 1 integration accepts buffered generation only")
        try:
            config_values = {
                key: value
                for key, value in payload.config.items()
                if key in GenerationConfig.__dataclass_fields__
            }
            generation_config = GenerationConfig(**config_values)
            request = GenerationRequest(
                request_id=payload.request_id,
                trace_id=payload.trace_id,
                generation_id=payload.generation_id,
                assessment_id=payload.assessment_id,
                subject_id=payload.subject_id,
                target_role=payload.target_role,
                purpose=payload.purpose,
                language=payload.language,
                safety_mode=payload.safety_mode,
                retrieval_id=payload.retrieval_id,
                chunk_ids=tuple(payload.chunk_ids),
                prompt_id=payload.prompt_id,
                prompt_version=payload.prompt_version,
                contract_model_id=payload.contract_model_id,
                logical_model_id=payload.logical_model_id,
                prompt=payload.prompt,
                messages=tuple(payload.messages),
                stream=False,
                structured_schema=payload.structured_schema,
                config=generation_config,
                metadata=payload.metadata,
            )
            result = self.service.generate(request)
        except KeyError as exc:
            raise HTTPException(status_code=422, detail="requested model is not in the local registry") from exc
        except LLMRuntimeError as exc:
            status = 504 if exc.code.value in {"REQUEST_TIMEOUT", "STREAM_INTERRUPTED"} else 503
            raise HTTPException(status_code=status, detail={"code": exc.code.value, "retryable": exc.retryable}) from exc
        trace = result.trace.to_dict()
        actual_entry = self.service.registry.resolve(result.actual_model_id)
        return {
            "request_id": payload.request_id,
            "trace_id": payload.trace_id,
            "data": {
                "text": result.text,
                "model_id": actual_entry.contract_model_id,
                "logical_model_id": result.actual_model_id,
                "model_version": trace.get("model_revision") or actual_entry.provider_model_id,
                "runtime_version": trace.get("runtime_version", "unknown"),
                "trace": trace,
                "buffered": True,
                "synthetic_fixture_only": True,
            },
        }


def create_app(*, runtime: Runtime | None = None) -> FastAPI:
    runtime = runtime or Runtime()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.llm_runtime = runtime
        yield

    app = FastAPI(
        title="StudentMentalHealthAI LLM Runtime",
        version="0.1.0",
        description="Loopback buffered local-model generation boundary.",
        lifespan=lifespan,
    )
    app.state.llm_runtime = runtime

    @app.get("/health/live", operation_id="llmLiveHealth")
    async def health_live() -> dict[str, Any]:
        return {"status": "LIVE", "service": "llm_runtime"}

    @app.get("/health/ready", operation_id="llmReadyHealth")
    async def health_ready() -> dict[str, Any]:
        health = runtime.health()
        if not runtime.ready():
            raise HTTPException(status_code=503, detail=health)
        return {"status": "READY", "service": "llm_runtime", "health": health}

    @app.get("/health", operation_id="llmHealth")
    async def health() -> dict[str, Any]:
        return runtime.health()

    @app.get("/capabilities", operation_id="llmCapabilities")
    async def capabilities() -> dict[str, Any]:
        return {
            "service": "llm_runtime",
            "transport": "http",
            "buffered_generation": True,
            "streaming": False,
            "cloud_fallback": False,
            "default_model": "MODEL_local_cpu_test",
            "synthetic_fixture_only": True,
        }

    @app.post("/internal/llm/generations", operation_id="llmGenerate")
    async def generate(payload: GenerateRequest, request: Request) -> dict[str, Any]:
        del request
        return runtime.generate(payload)

    return app


app = create_app()


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("SMHAI_LLM_PORT", "8160")))


if __name__ == "__main__":
    main()

