"""Deterministic Mock Provider for unit and contract tests only."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from typing import Any

from ..domain.models import (
    Capabilities,
    GenerationRequest,
    ModelHealth,
    ProviderHealth,
    ProviderResponse,
    RuntimeStreamEvent,
    StreamEventType,
    Usage,
)
from ..errors import LLMRuntimeError, RuntimeErrorCode
from ..validation import example_for_schema, parse_and_validate
from .base import LLMProvider


class MockProvider(LLMProvider):
    """A test double that is never used as real model evidence."""

    name = "mock"

    def __init__(
        self,
        models: tuple[str, ...] = ("mock-model",),
        *,
        unavailable_models: tuple[str, ...] = (),
        timeout_models: tuple[str, ...] = (),
    ) -> None:
        self.models = set(models)
        self.unavailable_models = set(unavailable_models)
        self.timeout_models = set(timeout_models)
        self.loaded: set[str] = set()
        self._cancelled: set[str] = set()
        self._lock = threading.Lock()
        self.generate_calls = 0

    def discover_models(self) -> list[dict[str, Any]]:
        return [
            {
                "provider_model_id": model,
                "revision": "mock-0.1.0",
                "digest": "mock-digest",
                "format": "synthetic",
                "quantization": None,
                "size_bytes": 0,
                "provider_version": "mock-0.1.0",
            }
            for model in sorted(self.models)
        ]

    def get_model_info(self, provider_model_id: str) -> dict[str, Any]:
        self._check_model(provider_model_id)
        return {"provider_model_id": provider_model_id, "revision": "mock-0.1.0"}

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(self.name, "pass", "pass", "mock-0.1.0", "in-process")

    def model_health_check(self, provider_model_id: str) -> ModelHealth:
        if provider_model_id not in self.models:
            return ModelHealth(
                provider_model_id,
                provider_model_id,
                "unavailable",
                "unavailable",
                False,
                RuntimeErrorCode.MODEL_NOT_FOUND.value,
                "Mock model is not configured.",
            )
        return ModelHealth(
            provider_model_id,
            provider_model_id,
            "available",
            "loaded" if provider_model_id in self.loaded else "ready",
            provider_model_id in self.loaded,
        )

    def load_model(self, provider_model_id: str, request: GenerationRequest | None = None) -> dict[str, Any]:
        self._check_model(provider_model_id)
        self.loaded.add(provider_model_id)
        return {"model": provider_model_id, "loaded": True, "synthetic": True}

    def unload_model(self, provider_model_id: str) -> dict[str, Any]:
        self._check_model(provider_model_id)
        self.loaded.discard(provider_model_id)
        return {"model": provider_model_id, "loaded": False, "synthetic": True}

    def generate(self, request: GenerationRequest) -> ProviderResponse:
        self._check_model(request.effective_provider_model_id)
        self.generate_calls += 1
        if "__timeout__" in request.prompt and request.effective_provider_model_id in self.timeout_models:
            raise LLMRuntimeError(RuntimeErrorCode.REQUEST_TIMEOUT, "synthetic timeout", retryable=True)
        if "__unavailable__" in request.prompt and request.effective_provider_model_id in self.unavailable_models:
            raise LLMRuntimeError(
                RuntimeErrorCode.PROVIDER_UNAVAILABLE,
                "synthetic provider outage",
                retryable=True,
            )
        text = self._response_text(request)
        structured = None
        if request.structured_schema is not None:
            structured = parse_and_validate(text, request.structured_schema)
        return ProviderResponse(
            text=text,
            provider=self.name,
            provider_model=request.effective_provider_model_id,
            runtime_version="mock-0.1.0",
            usage=Usage(prompt_tokens=3, completion_tokens=max(1, len(text.split())), total_tokens=None),
            finish_reason="stop",
            structured=structured,
            metadata={"synthetic": True},
        )

    def stream_generate(self, request: GenerationRequest) -> Iterator[RuntimeStreamEvent]:
        self._check_model(request.effective_provider_model_id)
        yield RuntimeStreamEvent(StreamEventType.START, request.request_id, request.trace_id)
        if "__stream_error__" in request.prompt:
            yield RuntimeStreamEvent(
                StreamEventType.ERROR,
                request.request_id,
                request.trace_id,
                error_code=RuntimeErrorCode.STREAM_INTERRUPTED.value,
                error_message="synthetic stream interruption",
                metadata={"partial_output": True},
            )
            return
        text = self._response_text(request)
        for delta in (text[: max(1, len(text) // 2)], text[max(1, len(text) // 2) :]):
            with self._lock:
                cancelled = request.request_id in self._cancelled
                if cancelled:
                    self._cancelled.discard(request.request_id)
            if cancelled:
                yield RuntimeStreamEvent(
                    StreamEventType.CANCELLED,
                    request.request_id,
                    request.trace_id,
                    error_code=RuntimeErrorCode.CANCELLED.value,
                    error_message="Generation was cancelled.",
                )
                return
            if delta:
                yield RuntimeStreamEvent(
                    StreamEventType.DELTA,
                    request.request_id,
                    request.trace_id,
                    delta=delta,
                )
        yield RuntimeStreamEvent(
            StreamEventType.USAGE,
            request.request_id,
            request.trace_id,
            usage=Usage(prompt_tokens=3, completion_tokens=2, total_tokens=5),
        )
        yield RuntimeStreamEvent(
            StreamEventType.DONE,
            request.request_id,
            request.trace_id,
            finish_reason="stop",
        )

    def cancel(self, request_id: str) -> bool:
        with self._lock:
            self._cancelled.add(request_id)
        return True

    def capabilities(self) -> Capabilities:
        return Capabilities(chat=True, stream=True, structured_output=True, json_schema=True)

    def runtime_info(self) -> dict[str, Any]:
        return {"provider": self.name, "version": "mock-0.1.0", "synthetic": True}

    def _check_model(self, provider_model_id: str) -> None:
        if provider_model_id not in self.models:
            raise LLMRuntimeError(
                RuntimeErrorCode.MODEL_NOT_FOUND,
                f"Mock model {provider_model_id!r} is not configured.",
            )

    @staticmethod
    def _response_text(request: GenerationRequest) -> str:
        if request.structured_schema is not None:
            return json.dumps(example_for_schema(request.structured_schema), ensure_ascii=False)
        return "synthetic local response"
