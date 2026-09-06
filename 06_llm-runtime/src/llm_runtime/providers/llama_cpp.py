"""llama-server OpenAI-compatible Provider PoC.

This adapter is intentionally independent from ``llama-cpp-python``. The
server process boundary allows a later managed binary to be swapped in without
coupling business code to Python bindings.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, Mapping

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
from ..errors import LLMRuntimeError, RuntimeErrorCode, map_provider_error
from ..validation import parse_and_validate
from .base import LLMProvider
from .http import ActiveHTTPStream, LocalHTTPClient


class LlamaCppProvider(LLMProvider):
    name = "llama.cpp"

    def __init__(self, base_url: str = "http://127.0.0.1:8080", *, timeout_seconds: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.http = LocalHTTPClient(self.base_url, provider=self.name)

    def discover_models(self) -> list[dict[str, Any]]:
        data = self.http.request_json("GET", "/v1/models", timeout=self.timeout_seconds)
        result: list[dict[str, Any]] = []
        for item in data.get("data", []):
            if isinstance(item, Mapping) and item.get("id"):
                result.append(
                    {
                        "provider_model_id": item["id"],
                        "revision": item.get("created"),
                        "owned_by": item.get("owned_by"),
                        "provider_version": None,
                    }
                )
        return result

    def get_model_info(self, provider_model_id: str) -> dict[str, Any]:
        for item in self.discover_models():
            if item.get("provider_model_id") == provider_model_id:
                return item
        raise LLMRuntimeError(RuntimeErrorCode.MODEL_NOT_FOUND, "llama-server model was not listed.")

    def health_check(self) -> ProviderHealth:
        try:
            self.http.request_json("GET", "/health", timeout=min(self.timeout_seconds, 10.0))
            return ProviderHealth(self.name, "pass", "pass", None, self.base_url)
        except LLMRuntimeError as exc:
            return ProviderHealth(
                self.name,
                "fail",
                "fail",
                None,
                self.base_url,
                exc.code.value,
                exc.message,
            )

    def model_health_check(self, provider_model_id: str) -> ModelHealth:
        try:
            self.get_model_info(provider_model_id)
            health = self.health_check()
            return ModelHealth(
                provider_model_id,
                provider_model_id,
                "available" if health.readiness == "pass" else "unknown",
                "ready" if health.readiness == "pass" else "unavailable",
                health.readiness == "pass",
            )
        except LLMRuntimeError as exc:
            return ModelHealth(
                provider_model_id,
                provider_model_id,
                "unknown",
                "unknown",
                False,
                exc.code.value,
                exc.message,
            )

    def load_model(self, provider_model_id: str, request: GenerationRequest | None = None) -> dict[str, Any]:
        raise LLMRuntimeError(
            RuntimeErrorCode.UNSUPPORTED_CAPABILITY,
            "llama-server PoC does not expose a portable load endpoint.",
            provider=self.name,
        )

    def unload_model(self, provider_model_id: str) -> dict[str, Any]:
        raise LLMRuntimeError(
            RuntimeErrorCode.UNSUPPORTED_CAPABILITY,
            "llama-server PoC does not expose a portable unload endpoint.",
            provider=self.name,
        )

    def generate(self, request: GenerationRequest) -> ProviderResponse:
        payload = self._payload(request, stream=False)
        data = self.http.request_json(
            "POST",
            "/v1/chat/completions",
            payload,
            timeout=request.config.timeout_seconds,
        )
        if data.get("error"):
            raise map_provider_error(str(data["error"]), provider=self.name)
        text = self._content(data)
        if not text:
            raise LLMRuntimeError(RuntimeErrorCode.RUNTIME_ERROR, "llama-server returned an empty response.")
        structured = parse_and_validate(text, request.structured_schema) if request.structured_schema else None
        choices = data.get("choices")
        finish_reason = choices[0].get("finish_reason") if choices and isinstance(choices[0], Mapping) else None
        return ProviderResponse(
            text=text,
            provider=self.name,
            provider_model=request.effective_provider_model_id,
            runtime_version="llama-server-unknown",
            usage=Usage.from_openai(data.get("usage")),
            finish_reason=finish_reason,
            structured=structured,
        )

    def stream_generate(self, request: GenerationRequest) -> Iterator[RuntimeStreamEvent]:
        active = self.http.open_stream(
            "POST",
            "/v1/chat/completions",
            self._payload(request, stream=True),
            timeout=request.config.timeout_seconds,
            request_id=request.request_id,
        )
        saw_delta = False
        done = False
        try:
            yield RuntimeStreamEvent(
                StreamEventType.START,
                request.request_id,
                request.trace_id,
                metadata={"provider": self.name, "provider_model": request.effective_provider_model_id},
            )
            for raw_line in active.response:
                if active.cancel_event.is_set():
                    yield RuntimeStreamEvent(
                        StreamEventType.CANCELLED,
                        request.request_id,
                        request.trace_id,
                        error_code=RuntimeErrorCode.CANCELLED.value,
                        error_message="Generation was cancelled.",
                    )
                    return
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                value = line[5:].strip()
                if value == "[DONE]":
                    yield RuntimeStreamEvent(
                        StreamEventType.DONE,
                        request.request_id,
                        request.trace_id,
                        finish_reason="stop",
                    )
                    done = True
                    return
                try:
                    data = json.loads(value)
                except json.JSONDecodeError:
                    yield self._error_event(request, RuntimeErrorCode.STREAM_INTERRUPTED, "Invalid SSE event.", saw_delta)
                    return
                if data.get("error"):
                    yield self._error_event(request, RuntimeErrorCode.RUNTIME_ERROR, str(data["error"]), saw_delta)
                    return
                choices = data.get("choices")
                delta = ""
                if choices and isinstance(choices[0], Mapping):
                    message = choices[0].get("delta")
                    if isinstance(message, Mapping):
                        delta = str(message.get("content") or "")
                if delta:
                    saw_delta = True
                    yield RuntimeStreamEvent(
                        StreamEventType.DELTA,
                        request.request_id,
                        request.trace_id,
                        delta=delta,
                    )
                usage = Usage.from_openai(data.get("usage"))
                if any(value is not None for value in usage.to_dict().values()):
                    yield RuntimeStreamEvent(
                        StreamEventType.USAGE,
                        request.request_id,
                        request.trace_id,
                        usage=usage,
                    )
            if not done:
                yield self._error_event(
                    request,
                    RuntimeErrorCode.STREAM_INTERRUPTED,
                    "llama-server stream ended before DONE.",
                    saw_delta,
                )
        except LLMRuntimeError as exc:
            yield self._error_event(request, exc.code, exc.message, saw_delta)
        except (OSError, ValueError) as exc:
            if active.cancel_event.is_set():
                yield RuntimeStreamEvent(
                    StreamEventType.CANCELLED,
                    request.request_id,
                    request.trace_id,
                    error_code=RuntimeErrorCode.CANCELLED.value,
                    error_message="Generation was cancelled.",
                )
                return
            yield self._error_event(
                request,
                RuntimeErrorCode.STREAM_INTERRUPTED,
                "llama-server stream was interrupted.",
                saw_delta,
                {"exception": type(exc).__name__},
            )
        finally:
            self.http.close_stream(request.request_id, active)

    def cancel(self, request_id: str) -> bool:
        return self.http.cancel(request_id)

    def capabilities(self) -> Capabilities:
        return Capabilities(chat=True, stream=True, structured_output=True, json_schema=True)

    def runtime_info(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "endpoint": self.base_url,
            "api": "OpenAI-compatible",
            "default_bind": "127.0.0.1",
            "server_version": None,
        }

    def _payload(self, request: GenerationRequest, *, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.effective_provider_model_id,
            "messages": request.effective_messages,
            "stream": stream,
            "max_tokens": request.config.max_output_tokens,
            "temperature": request.config.temperature,
            "top_p": request.config.top_p,
        }
        if request.config.seed is not None:
            payload["seed"] = request.config.seed
        if request.config.top_k is not None:
            payload["top_k"] = request.config.top_k
        if request.config.context_length is not None:
            payload["n_ctx"] = request.config.context_length
        if request.structured_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "runtime_output", "schema": request.structured_schema},
            }
        return payload

    @staticmethod
    def _content(data: Mapping[str, Any]) -> str:
        choices = data.get("choices")
        if not choices or not isinstance(choices[0], Mapping):
            return ""
        message = choices[0].get("message")
        return str(message.get("content") or "") if isinstance(message, Mapping) else ""

    @staticmethod
    def _error_event(
        request: GenerationRequest,
        code: RuntimeErrorCode,
        message: str,
        partial: bool,
        details: Mapping[str, Any] | None = None,
    ) -> RuntimeStreamEvent:
        return RuntimeStreamEvent(
            StreamEventType.ERROR,
            request.request_id,
            request.trace_id,
            error_code=code.value,
            error_message=message,
            metadata={"partial_output": partial, **dict(details or {})},
        )
