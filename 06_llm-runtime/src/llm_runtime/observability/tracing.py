"""Runtime trace measurement and logging without prompt capture."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping
from typing import Any

from ..domain.models import (
    GenerationConfig,
    GenerationRequest,
    ModelEntry,
    ProviderResponse,
    RuntimeStreamEvent,
    RuntimeTrace,
    Usage,
)


class RuntimeTraceBuilder:
    def __init__(
        self,
        request: GenerationRequest,
        model: ModelEntry,
        *,
        runtime_version: str,
        hardware: Mapping[str, Any],
    ) -> None:
        self._started = time.perf_counter()
        self._first_delta: float | None = None
        self.trace = RuntimeTrace(
            trace_id=request.trace_id,
            request_id=request.request_id,
            logical_model=model.logical_model_id,
            provider=model.provider,
            provider_model=model.provider_model_id,
            model_revision=model.revision,
            digest=model.digest,
            quantization=model.quantization,
            runtime_version=runtime_version,
            hardware=dict(hardware),
            generation_config=_config_dict(request.config),
            requested_model=model.logical_model_id,
            actual_model=model.logical_model_id,
            requested_provider_model=model.provider_model_id,
        )

    def mark_delta(self) -> None:
        if self._first_delta is None:
            self._first_delta = time.perf_counter()
            self.trace.ttft_ms = (self._first_delta - self._started) * 1000

    def set_selection(
        self,
        *,
        actual_model: ModelEntry,
        retry_count: int = 0,
        fallback_reason: str | None = None,
    ) -> None:
        self.trace.provider = actual_model.provider
        self.trace.provider_model = actual_model.provider_model_id
        self.trace.model_revision = actual_model.revision
        self.trace.digest = actual_model.digest
        self.trace.quantization = actual_model.quantization
        self.trace.actual_model = actual_model.logical_model_id
        self.trace.retry_count = retry_count
        self.trace.fallback_reason = fallback_reason
        if (
            self.trace.fallback_attempted
            and self.trace.fallback_model == actual_model.logical_model_id
        ):
            self.trace.fallback_generation_success = True

    def record_fallback(
        self,
        *,
        primary_error: Mapping[str, Any],
        fallback_model: ModelEntry,
        fallback_reason: str,
    ) -> None:
        """Record a model-level fallback before the fallback request starts."""

        error = dict(primary_error)
        if self.trace.primary_error is None:
            self.trace.primary_error = error
            code = error.get("code")
            self.trace.primary_error_normalized_code = str(code) if code else None
        self.trace.fallback_attempted = True
        self.trace.fallback_model = fallback_model.logical_model_id
        self.trace.fallback_provider_model = fallback_model.provider_model_id
        self.trace.fallback_generation_success = False
        self.trace.fallback_count += 1
        self.trace.fallback_reason = fallback_reason

    def set_attempts(
        self,
        attempts: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    ) -> None:
        """Attach redacted attempt metadata without prompts or generated text."""

        self.trace.attempts = tuple(dict(attempt) for attempt in attempts)

    def complete(self, response: ProviderResponse, *, retry_count: int = 0) -> RuntimeTrace:
        finished = time.perf_counter()
        total_ms = (finished - self._started) * 1000
        self.trace.total_latency_ms = total_ms
        self.trace.generation_latency_ms = total_ms
        self.trace.retry_count = retry_count
        self._set_usage(response.usage)
        self.trace.finish_reason = response.finish_reason
        self._set_throughput()
        return self.trace

    def complete_stream(
        self,
        event: RuntimeStreamEvent,
        *,
        usage: Usage | None = None,
        error: Mapping[str, Any] | None = None,
    ) -> RuntimeTrace:
        finished = time.perf_counter()
        total_ms = (finished - self._started) * 1000
        self.trace.total_latency_ms = total_ms
        self.trace.generation_latency_ms = total_ms
        if usage is not None:
            self._set_usage(usage)
        self.trace.finish_reason = event.finish_reason
        self.trace.error = dict(error) if error else None
        self._set_throughput()
        return self.trace

    def fail(self, error: Mapping[str, Any], *, retry_count: int = 0) -> RuntimeTrace:
        self.trace.total_latency_ms = (time.perf_counter() - self._started) * 1000
        self.trace.generation_latency_ms = self.trace.total_latency_ms
        self.trace.retry_count = retry_count
        self.trace.error = dict(error)
        return self.trace

    def _set_usage(self, usage: Usage) -> None:
        self.trace.prompt_tokens = usage.prompt_tokens
        self.trace.completion_tokens = usage.completion_tokens

    def _set_throughput(self) -> None:
        if self.trace.completion_tokens is not None and self.trace.generation_latency_ms:
            self.trace.tokens_per_second = self.trace.completion_tokens / (
                self.trace.generation_latency_ms / 1000
            )


class StructuredRuntimeLogger:
    """Emit logging.v1-shaped records and never serialize prompt text."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger("llm_runtime")

    def emit(
        self,
        *,
        event: str,
        request_id: str,
        trace_id: str,
        outcome: str,
        level: str = "INFO",
        duration_ms: int | None = None,
        error_code: str | None = None,
        entity_refs: Mapping[str, str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = {
            "schema_version": "logging.v1",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "level": level,
            "event": event,
            "component": "06_llm-runtime",
            "request_id": request_id,
            "trace_id": trace_id,
            "outcome": outcome,
            "duration_ms": duration_ms,
            "error_code": error_code,
            "entity_refs": dict(entity_refs or {}),
            "metadata": {
                key: value
                for key, value in (metadata or {}).items()
                if key
                in {"operation", "route", "dependency", "reason_code", "attempt", "retryable"}
            },
        }
        self.logger.log(
            getattr(logging, level, logging.INFO),
            json.dumps(record, ensure_ascii=False),
        )
        return record


def _config_dict(config: GenerationConfig) -> dict[str, Any]:
    return {
        "max_output_tokens": config.max_output_tokens,
        "max_tokens": config.max_tokens,
        "temperature": config.temperature,
        "top_p": config.top_p,
        "top_k": config.top_k,
        "context_length": config.context_length,
        "timeout_seconds": config.timeout_seconds,
        "keep_alive": config.keep_alive,
        "seed": config.seed,
        "stop": list(config.stop),
        "think": config.think,
    }
