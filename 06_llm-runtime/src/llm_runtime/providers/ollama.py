"""Ollama native API adapter.

Generation and lifecycle calls deliberately stay inside this adapter. Upper
layers see normalized domain objects rather than Ollama NDJSON or field names.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator, Mapping
from typing import Any

import httpx

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
from .http import LocalHTTPClient


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        *,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.http = LocalHTTPClient(
            self.base_url,
            provider=self.name,
            timeout_seconds=timeout_seconds,
        )
        self._version: str | None = None

    def close(self) -> None:
        """Close the provider-scoped pooled client."""

        close = getattr(self.http, "close", None)
        if callable(close):
            close()

    def discover_models(self) -> list[dict[str, Any]]:
        data = self.http.request_json("GET", "/api/tags", timeout=self.timeout_seconds)
        result: list[dict[str, Any]] = []
        for model in data.get("models", []):
            if not isinstance(model, Mapping):
                continue
            raw_details = model.get("details")
            details: Mapping[str, Any] = raw_details if isinstance(raw_details, Mapping) else {}
            result.append(
                {
                    "provider_model_id": model.get("name") or model.get("model"),
                    "revision": model.get("model") or model.get("name"),
                    "digest": model.get("digest"),
                    "format": details.get("format"),
                    "family": details.get("family"),
                    "families": details.get("families"),
                    "parameters": details.get("parameter_size"),
                    "quantization": details.get("quantization_level"),
                    "size_bytes": model.get("size"),
                    "modified_at": model.get("modified_at"),
                    "provider_version": self._version,
                }
            )
        return result

    def get_model_info(self, provider_model_id: str) -> dict[str, Any]:
        data = self.http.request_json(
            "POST",
            "/api/show",
            {"model": provider_model_id},
            timeout=self.timeout_seconds,
        )
        raw_details = data.get("details")
        details: Mapping[str, Any] = raw_details if isinstance(raw_details, Mapping) else {}
        raw_model_info = data.get("model_info")
        model_info: Mapping[str, Any] = (
            raw_model_info if isinstance(raw_model_info, Mapping) else {}
        )
        return {
            "provider_model_id": provider_model_id,
            "revision": data.get("modified_at") or provider_model_id,
            "digest": data.get("digest"),
            "format": details.get("format"),
            "family": details.get("family"),
            "families": details.get("families"),
            "parameters": details.get("parameter_size"),
            "quantization": details.get("quantization_level"),
            "license": data.get("license"),
            "template": data.get("template"),
            "model_info": model_info,
            "parameters_text": data.get("parameters"),
        }

    def health_check(self) -> ProviderHealth:
        try:
            data = self.http.request_json(
                "GET",
                "/api/version",
                timeout=min(self.timeout_seconds, 10.0),
            )
            self._version = str(data.get("version")) if data.get("version") else None
            return ProviderHealth(
                provider=self.name,
                liveness="pass",
                readiness="pass",
                version=self._version,
                endpoint=self.base_url,
            )
        except LLMRuntimeError as exc:
            return ProviderHealth(
                provider=self.name,
                liveness="fail",
                readiness="fail",
                version=self._version,
                endpoint=self.base_url,
                error_code=exc.code.value,
                message=exc.message,
            )

    def model_health_check(self, provider_model_id: str) -> ModelHealth:
        try:
            discovered = self.discover_models()
            model = next(
                (item for item in discovered if item.get("provider_model_id") == provider_model_id),
                None,
            )
            if model is None:
                return ModelHealth(
                    logical_model_id=provider_model_id,
                    provider_model_id=provider_model_id,
                    availability="unavailable",
                    inference_readiness="unavailable",
                    loaded=False,
                    error_code=RuntimeErrorCode.MODEL_NOT_FOUND.value,
                    message="Model is not present in the provider model list.",
                )
            running = self.http.request_json("GET", "/api/ps", timeout=self.timeout_seconds)
            loaded_names = {
                str(item.get("name") or item.get("model"))
                for item in running.get("models", [])
                if isinstance(item, Mapping)
            }
            loaded = provider_model_id in loaded_names
            return ModelHealth(
                logical_model_id=provider_model_id,
                provider_model_id=provider_model_id,
                availability="available",
                inference_readiness="loaded" if loaded else "ready",
                loaded=loaded,
            )
        except LLMRuntimeError as exc:
            return ModelHealth(
                logical_model_id=provider_model_id,
                provider_model_id=provider_model_id,
                availability="unknown",
                inference_readiness="unknown",
                loaded=False,
                error_code=exc.code.value,
                message=exc.message,
            )

    def load_model(
        self,
        provider_model_id: str,
        request: GenerationRequest | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": provider_model_id,
            "prompt": "",
            "stream": False,
            "keep_alive": -1,
        }
        if request is not None:
            payload["options"] = request.config.to_ollama_options()
        return self.http.request_json(
            "POST",
            "/api/generate",
            payload,
            timeout=self.timeout_seconds,
        )

    def unload_model(self, provider_model_id: str) -> dict[str, Any]:
        response = self.http.request_json(
            "POST",
            "/api/generate",
            {"model": provider_model_id, "prompt": "", "stream": False, "keep_alive": 0},
            timeout=self.timeout_seconds,
        )
        # Ollama acknowledges the unload request before the runner disappears
        # from /api/ps on some versions. Wait briefly so the lifecycle method
        # has a truthful postcondition for callers and acceptance checks.
        deadline = time.monotonic() + min(self.timeout_seconds, 5.0)
        while time.monotonic() < deadline:
            running = self.http.request_json("GET", "/api/ps", timeout=self.timeout_seconds)
            loaded = {
                str(item.get("name") or item.get("model"))
                for item in running.get("models", [])
                if isinstance(item, Mapping)
            }
            if provider_model_id not in loaded:
                break
            time.sleep(0.1)
        return response

    def generate(self, request: GenerationRequest) -> ProviderResponse:
        provider_model_id = request.effective_provider_model_id
        payload = self._generation_payload(request, stream=False)
        data = self.http.request_json(
            "POST",
            self._generation_path(request),
            payload,
            timeout=request.config.timeout_seconds,
        )
        self._raise_for_embedded_error(data)
        text = self._response_text(data)
        if not text:
            raise LLMRuntimeError(
                RuntimeErrorCode.RUNTIME_ERROR,
                "Ollama returned an empty response.",
                provider=self.name,
            )
        structured = None
        if request.structured_schema is not None:
            structured = parse_and_validate(text, request.structured_schema)
        return ProviderResponse(
            text=text,
            provider=self.name,
            provider_model=provider_model_id,
            runtime_version=self._version or "unknown",
            usage=Usage.from_ollama(data),
            finish_reason=str(data.get("done_reason")) if data.get("done_reason") else None,
            structured=structured,
            metadata={
                "load_duration_ns": data.get("load_duration"),
                "total_duration_ns": data.get("total_duration"),
            },
        )

    def stream_generate(self, request: GenerationRequest) -> Iterator[RuntimeStreamEvent]:
        provider_model_id = request.effective_provider_model_id
        active = self.http.open_stream(
            "POST",
            self._generation_path(request),
            self._generation_payload(request, stream=True),
            timeout=request.config.timeout_seconds,
            request_id=request.request_id,
        )
        saw_delta = False
        completed = False
        try:
            yield RuntimeStreamEvent(
                event_type=StreamEventType.START,
                request_id=request.request_id,
                trace_id=request.trace_id,
                metadata={"provider": self.name, "provider_model": provider_model_id},
            )
            response_lines = (
                active.response.iter_lines()
                if hasattr(active.response, "iter_lines")
                else active.response
            )
            for raw_line in response_lines:
                if active.cancel_event.is_set():
                    yield RuntimeStreamEvent(
                        event_type=StreamEventType.CANCELLED,
                        request_id=request.request_id,
                        trace_id=request.trace_id,
                        error_code=RuntimeErrorCode.CANCELLED.value,
                        error_message="Generation was cancelled.",
                    )
                    return
                line = (
                    raw_line.decode("utf-8", errors="replace")
                    if isinstance(raw_line, bytes)
                    else str(raw_line)
                ).strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    yield self._error_event(
                        request,
                        RuntimeErrorCode.STREAM_INTERRUPTED,
                        "Ollama returned an invalid stream event.",
                        partial=saw_delta,
                    )
                    return
                if data.get("error"):
                    error = map_provider_error(str(data["error"]), provider=self.name)
                    error.partial_output = saw_delta
                    yield self._error_event(request, error.code, error.message, partial=saw_delta)
                    return
                delta = self._response_text(data)
                if delta:
                    saw_delta = True
                    yield RuntimeStreamEvent(
                        event_type=StreamEventType.DELTA,
                        request_id=request.request_id,
                        trace_id=request.trace_id,
                        delta=delta,
                    )
                if data.get("done") is True:
                    usage = Usage.from_ollama(data)
                    if any(value is not None for value in usage.to_dict().values()):
                        yield RuntimeStreamEvent(
                            event_type=StreamEventType.USAGE,
                            request_id=request.request_id,
                            trace_id=request.trace_id,
                            usage=usage,
                        )
                    yield RuntimeStreamEvent(
                        event_type=StreamEventType.DONE,
                        request_id=request.request_id,
                        trace_id=request.trace_id,
                        finish_reason=str(data.get("done_reason") or "stop"),
                    )
                    completed = True
                    return
            if not completed:
                yield self._error_event(
                    request,
                    RuntimeErrorCode.STREAM_INTERRUPTED,
                    "Ollama stream ended before a DONE event.",
                    partial=saw_delta,
                )
        except LLMRuntimeError as exc:
            yield self._error_event(request, exc.code, exc.message, partial=saw_delta)
        except (httpx.TransportError, OSError, RuntimeError, ValueError, AttributeError) as exc:
            if active.cancel_event.is_set():
                yield RuntimeStreamEvent(
                    event_type=StreamEventType.CANCELLED,
                    request_id=request.request_id,
                    trace_id=request.trace_id,
                    error_code=RuntimeErrorCode.CANCELLED.value,
                    error_message="Generation was cancelled.",
                )
                return
            yield self._error_event(
                request,
                RuntimeErrorCode.STREAM_INTERRUPTED,
                "Ollama stream was interrupted.",
                partial=saw_delta,
                details={"exception": type(exc).__name__},
            )
        finally:
            self.http.close_stream(request.request_id, active)

    def cancel(self, request_id: str) -> bool:
        return self.http.cancel(request_id)

    def capabilities(self) -> Capabilities:
        return Capabilities(
            chat=True,
            stream=True,
            structured_output=True,
            json_schema=True,
            tools=False,
            vision=False,
            reasoning=True,
            embeddings=False,
        )

    def runtime_info(self) -> dict[str, Any]:
        health = self.health_check()
        return {
            "provider": self.name,
            "endpoint": self.base_url,
            "version": health.version,
            "api": "native",
            "default_bind": "127.0.0.1",
        }

    def pull_model(self, provider_model_id: str) -> list[dict[str, Any]]:
        """Pull a model through Ollama's native streaming pull endpoint."""

        active = self.http.open_stream(
            "POST",
            "/api/pull",
            {"model": provider_model_id, "stream": True},
            timeout=max(self.timeout_seconds, 300.0),
            request_id=f"pull:{provider_model_id}",
        )
        updates: list[dict[str, Any]] = []
        try:
            response_lines = (
                active.response.iter_lines()
                if hasattr(active.response, "iter_lines")
                else active.response
            )
            for raw_line in response_lines:
                line = (
                    raw_line.decode("utf-8", errors="replace")
                    if isinstance(raw_line, bytes)
                    else str(raw_line)
                ).strip()
                if line:
                    update = json.loads(line)
                    updates.append(update)
                    if update.get("error"):
                        raise map_provider_error(str(update["error"]), provider=self.name)
        finally:
            self.http.close_stream(f"pull:{provider_model_id}", active)
        return updates

    def _generation_payload(self, request: GenerationRequest, *, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.effective_provider_model_id,
            "stream": stream,
            "options": request.config.to_ollama_options(),
            "keep_alive": request.config.keep_alive,
        }
        if request.messages:
            payload["messages"] = request.effective_messages
        else:
            payload["prompt"] = request.prompt
        if request.system_prompt and not request.messages:
            payload["system"] = request.system_prompt
        if request.structured_schema is not None:
            payload["format"] = request.structured_schema
        if request.config.think is not None:
            payload["think"] = request.config.think
        return payload

    @staticmethod
    def _generation_path(request: GenerationRequest) -> str:
        return "/api/chat" if request.messages else "/api/generate"

    @staticmethod
    def _response_text(data: Mapping[str, Any]) -> str:
        if isinstance(data.get("response"), str):
            return data["response"]
        message = data.get("message")
        if isinstance(message, Mapping) and isinstance(message.get("content"), str):
            return str(message["content"])
        return ""

    def _raise_for_embedded_error(self, data: Mapping[str, Any]) -> None:
        if data.get("error"):
            raise map_provider_error(str(data["error"]), provider=self.name)

    @staticmethod
    def _error_event(
        request: GenerationRequest,
        code: RuntimeErrorCode,
        message: str,
        *,
        partial: bool,
        details: Mapping[str, Any] | None = None,
    ) -> RuntimeStreamEvent:
        return RuntimeStreamEvent(
            event_type=StreamEventType.ERROR,
            request_id=request.request_id,
            trace_id=request.trace_id,
            error_code=code.value,
            error_message=message,
            metadata={"partial_output": partial, **dict(details or {})},
        )
