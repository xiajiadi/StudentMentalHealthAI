"""Acceptance-only HTTP host for the accepted RuntimeService.

This file is intentionally outside product source.  It supplies the exact
GPU model registry needed by the closure without changing the frozen runtime
configuration.  Generation still goes through the accepted RuntimeService
and its OllamaProvider; the Backend never calls Ollama from this process.
"""

from __future__ import annotations

import json
import os
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool

from llm_runtime.api.app import GenerateRequest, _result_payload, _status_for_error
from llm_runtime.domain.models import Capabilities, Compatibility, HardwareProfile, ModelEntry, ModelStatus
from llm_runtime.domain.registry import ModelRegistry
from llm_runtime.errors import LLMRuntimeError
from llm_runtime.hardware.detector import HardwareDetector
from llm_runtime.providers.ollama import OllamaProvider
from llm_runtime.runtime.service import RuntimeService


GPU_MODEL = "qwen2.5:7b-instruct-q4_K_M"
GPU_DIGEST = "845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e"
FALLBACK_MODEL = "qwen2.5:1.5b"
FALLBACK_DIGEST = "65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b"
PRIMARY_LOGICAL_ID = "qwen2.5-0.5b-engineering"
FALLBACK_LOGICAL_ID = "qwen2.5-1.5b-engineering-fallback"


class NamedOllamaProvider(OllamaProvider):
    """Keep two local Ollama endpoints distinct in RuntimeService traces."""

    def __init__(self, provider_id: str, base_url: str, *, timeout_seconds: float = 180.0) -> None:
        super().__init__(base_url, timeout_seconds=timeout_seconds)
        self.name = provider_id
        self.http.provider = provider_id


def _entry(value: dict[str, Any]) -> ModelEntry:
    return ModelEntry.from_dict(value)


def _capabilities() -> dict[str, bool]:
    return Capabilities(
        chat=True,
        stream=True,
        structured_output=True,
        json_schema=True,
        tools=False,
        vision=False,
        reasoning=True,
        embeddings=False,
    ).to_dict()


def _base_entry(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "logical_model_id": PRIMARY_LOGICAL_ID,
        "contract_model_id": "MODEL_local_gpu_acceptance",
        "display_name": "Qwen2.5 7B Instruct Q4_K_M GPU closure model",
        "family": "Qwen2.5",
        "parameters": "7.6B",
        "provider": "ollama_gpu",
        "provider_model_id": GPU_MODEL,
        "source": "Ollama local model manifest",
        "source_repository": "https://ollama.com/library/qwen2.5",
        "revision": GPU_MODEL,
        "digest": GPU_DIGEST,
        "expected_digest": GPU_DIGEST,
        "format": "gguf",
        "quantization": "Q4_K_M",
        "license": "Apache-2.0",
        "capabilities": _capabilities(),
        "hardware_profile": HardwareProfile.CONSUMER_GPU.value,
        "compatibility": Compatibility.SUPPORTED.value,
        "status": ModelStatus.READY.value,
        "validation_status": "GPU_PRODUCT_INTEGRATION_CLOSURE_R1",
        "provider_version": "0.33.3",
        "priority": 0,
        "enabled": True,
        "fallback_eligible": False,
        "context_limit": 8192,
        "structured_output_supported": True,
        "local_only": True,
        "fallback_model_id": None,
    }
    value.update(overrides)
    return value


def _fallback_entry() -> dict[str, Any]:
    return {
        "logical_model_id": FALLBACK_LOGICAL_ID,
        "contract_model_id": "MODEL_local_cpu_fallback",
        "display_name": "Qwen2.5 1.5B local CPU fallback",
        "family": "Qwen2.5",
        "parameters": "1.5B",
        "provider": "ollama_cpu",
        "provider_model_id": FALLBACK_MODEL,
        "source": "Ollama local model manifest",
        "source_repository": "https://ollama.com/library/qwen2.5",
        "revision": FALLBACK_MODEL,
        "digest": FALLBACK_DIGEST,
        "expected_digest": FALLBACK_DIGEST,
        "format": "gguf",
        "quantization": "Q4_K_M",
        "license": "Apache-2.0",
        "capabilities": _capabilities(),
        "hardware_profile": HardwareProfile.CPU_ONLY.value,
        "compatibility": Compatibility.SUPPORTED.value,
        "status": ModelStatus.READY.value,
        "validation_status": "ACCEPTED_LOCAL_ENGINEERING_FALLBACK",
        "provider_version": "0.21.1",
        "priority": 1,
        "enabled": True,
        "fallback_eligible": True,
        "context_limit": 8192,
        "structured_output_supported": True,
        "local_only": True,
        "fallback_model_id": None,
    }


def build_service(mode: str) -> RuntimeService:
    gpu_url = os.environ.get("SMHAI_GPI_GPU_OLLAMA_URL", "http://127.0.0.1:11435")
    cpu_url = os.environ.get("SMHAI_GPI_CPU_OLLAMA_URL", "http://127.0.0.1:11434")
    gpu = NamedOllamaProvider("ollama_gpu", gpu_url)
    providers: dict[str, OllamaProvider] = {"ollama_gpu": gpu}
    primary = _base_entry()
    entries = [primary]
    if mode == "fallback":
        primary = _base_entry(
            provider_model_id="qwen2.5:7b-instruct-q4_K_M__acceptance_unavailable",
            digest=GPU_DIGEST,
            expected_digest=GPU_DIGEST,
            fallback_model_id=FALLBACK_LOGICAL_ID,
            validation_status="ACCEPTANCE_FAILURE_INJECTION_ONLY",
        )
        cpu = NamedOllamaProvider("ollama_cpu", cpu_url, timeout_seconds=120.0)
        providers["ollama_cpu"] = cpu
        entries = [primary, _fallback_entry()]
    registry = ModelRegistry([_entry(value) for value in entries], registry_version="gpi-r1")
    return RuntimeService(
        registry,
        providers,
        hardware=HardwareDetector().detect(),
        runtime_version="0.1.0-gpi-r1",
        max_attempts=1,
        backoff_seconds=(),
        default_model_id=PRIMARY_LOGICAL_ID,
        max_generation_concurrency=1,
        acquire_timeout_seconds=10.0,
        preload_primary=False,
    )


def _safe_trace(result: Any) -> dict[str, Any]:
    trace = result.trace.to_dict()
    attempts = []
    for attempt in result.attempts:
        value = attempt.to_dict()
        attempts.append(
            {
                "attempt_index": value.get("attempt_index"),
                "provider_id": value.get("provider_id"),
                "logical_model_id": value.get("logical_model_id"),
                "provider_model_id": value.get("provider_model_id"),
                "outcome": value.get("outcome"),
                "error_code": value.get("error_code"),
                "fallback_reason": value.get("fallback_reason"),
            }
        )
    return {
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "request_id": result.request_id,
        "trace_id": result.trace_id,
        "status": result.status,
        "provider_id": result.provider_id,
        "logical_model_id": result.logical_model_id,
        "actual_model_id": result.actual_model_id,
        "provider_model": result.response.provider_model,
        "runtime_version": result.response.runtime_version,
        "fallback_used": result.fallback_used,
        "buffered": True,
        "model_revision": trace.get("model_revision"),
        "digest": trace.get("digest"),
        "quantization": trace.get("quantization"),
        "hardware": trace.get("hardware"),
        "attempts": attempts,
    }


def create_app(service: RuntimeService) -> FastAPI:
    log_path = Path(os.environ.get("SMHAI_GPI_RUNTIME_LOG", "runtime_service.log"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_lock = threading.Lock()

    def write_event(value: dict[str, Any]) -> None:
        with log_lock:
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.llm_runtime = service
        service.startup()
        try:
            yield
        finally:
            service.shutdown()

    app = FastAPI(
        title="StudentMentalHealthAI GPI RuntimeService Acceptance Host",
        version="0.1.0-gpi-r1",
        lifespan=lifespan,
    )

    @app.get("/health/live")
    async def health_live() -> dict[str, Any]:
        return {"status": "LIVE", "service": "llm_runtime"}

    @app.get("/health/ready")
    async def health_ready() -> dict[str, Any]:
        health = service.health()
        if not service.ready():
            raise HTTPException(status_code=503, detail=health)
        return {"status": "READY", "service": "llm_runtime", "health": health}

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return service.health()

    @app.get("/capabilities")
    async def capabilities() -> dict[str, Any]:
        return {
            "service": "llm_runtime",
            "transport": "http",
            "buffered_generation": True,
            "streaming": False,
            "cloud_fallback": False,
            "default_model": service.default_model_id,
            "synthetic_fixture_only": False,
        }

    @app.get("/internal/llm/models")
    async def models() -> dict[str, Any]:
        return {"models": service.list_models(), "cloud_fallback": service.registry.cloud_fallback}

    @app.post("/internal/llm/generate")
    @app.post("/internal/llm/generations")
    async def generate(payload: GenerateRequest) -> dict[str, Any]:
        if payload.stream:
            raise HTTPException(status_code=422, detail="buffered generation only")
        try:
            config_values = {
                key: value
                for key, value in payload.config.items()
                if key in {"max_output_tokens", "temperature", "top_p", "top_k", "context_length", "timeout_seconds", "keep_alive", "seed", "stop", "think", "max_tokens"}
            }
            # Reuse the accepted API's request construction by calling the
            # official RuntimeService with its frozen request model.
            from llm_runtime.domain.models import GenerationConfig, GenerationRequest

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
                config=GenerationConfig(**config_values),
                metadata=payload.metadata,
            )
            result = await run_in_threadpool(service.generate, request)
        except LLMRuntimeError as exc:
            write_event(
                {
                    "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    "status": "error",
                    "request_id": payload.request_id,
                    "trace_id": payload.trace_id,
                    "generation_id": payload.generation_id,
                    "error_code": exc.code.value,
                    "retryable": exc.retryable,
                    "details": exc.details,
                }
            )
            raise HTTPException(status_code=_status_for_error(exc), detail=exc.to_dict()) from exc
        write_event(_safe_trace(result))
        return _result_payload(result)

    return app


def main() -> None:
    mode = os.environ.get("SMHAI_GPI_RUNTIME_MODE", "primary").strip().lower()
    if mode not in {"primary", "fallback"}:
        raise SystemExit("SMHAI_GPI_RUNTIME_MODE must be primary or fallback")
    service = build_service(mode)
    app = create_app(service)
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("SMHAI_LLM_PORT", "8160")), log_level="info")


if __name__ == "__main__":
    main()
