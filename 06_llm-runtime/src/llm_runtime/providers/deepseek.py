"""Opt-in DeepSeek Chat Completions provider for synthetic-only deployments."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
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
from ..errors import LLMRuntimeError, RuntimeErrorCode
from ..validation import parse_and_validate
from .base import LLMProvider

_API_BASE_URL = "https://api.deepseek.com"
_MODEL_ID = "deepseek-flash"
_KEY_PATTERN = re.compile(r"^sk-[A-Za-z0-9_-]{20,128}$")
_ALLOWED_ROLES = frozenset({"system", "user", "assistant"})


class DeepSeekProvider(LLMProvider):
    """Buffered, one-attempt API adapter with a fixed HTTPS destination."""

    name = "deepseek"

    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not _KEY_PATTERN.fullmatch(api_key):
            raise ValueError("DeepSeek credential is malformed")
        if timeout_seconds <= 0:
            raise ValueError("DeepSeek timeout must be positive")
        self.timeout_seconds = timeout_seconds
        self._client = httpx.Client(
            base_url=_API_BASE_URL,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
            verify=True,
            timeout=httpx.Timeout(timeout_seconds, connect=min(5.0, timeout_seconds)),
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "PsyNova-Synthetic-Demo/1.0",
            },
        )

    @classmethod
    def from_credential_file(
        cls,
        path: str | Path,
        *,
        timeout_seconds: float = 60.0,
    ) -> DeepSeekProvider:
        try:
            raw = bytearray(Path(path).read_bytes())
        except OSError:
            raise ValueError("DeepSeek credential file is unavailable") from None
        try:
            while raw.endswith((b"\n", b"\r")):
                raw.pop()
            api_key = raw.decode("ascii", errors="strict")
        except (UnicodeDecodeError, ValueError):
            raise ValueError("DeepSeek credential is malformed") from None
        finally:
            for index in range(len(raw)):
                raw[index] = 0
        return cls(api_key, timeout_seconds=timeout_seconds)

    def discover_models(self) -> list[dict[str, Any]]:
        payload = self._request_json("GET", "/models", timeout=self.timeout_seconds)
        raw_models = payload.get("data")
        if not isinstance(raw_models, list):
            raise self._protocol_error("DeepSeek returned an invalid model list.")
        models: list[dict[str, Any]] = []
        for model in raw_models:
            if not isinstance(model, Mapping) or not isinstance(model.get("id"), str):
                continue
            models.append(
                {
                    "provider_model_id": model["id"],
                    "revision": model["id"],
                    "provider_version": "deepseek-api",
                }
            )
        return models

    def get_model_info(self, provider_model_id: str) -> dict[str, Any]:
        model = next(
            (
                item
                for item in self.discover_models()
                if item["provider_model_id"] == provider_model_id
            ),
            None,
        )
        if model is None:
            raise LLMRuntimeError(
                RuntimeErrorCode.MODEL_NOT_FOUND,
                "Requested DeepSeek model is not available to this credential.",
                provider=self.name,
            )
        return model

    def health_check(self) -> ProviderHealth:
        try:
            self.discover_models()
        except LLMRuntimeError as exc:
            return ProviderHealth(
                provider=self.name,
                liveness="fail",
                readiness="fail",
                version="deepseek-api",
                endpoint=_API_BASE_URL,
                error_code=exc.code.value,
                message=exc.message,
            )
        return ProviderHealth(
            provider=self.name,
            liveness="pass",
            readiness="pass",
            version="deepseek-api",
            endpoint=_API_BASE_URL,
        )

    def model_health_check(self, provider_model_id: str) -> ModelHealth:
        try:
            available = any(
                item["provider_model_id"] == provider_model_id
                for item in self.discover_models()
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
        if not available:
            return ModelHealth(
                logical_model_id=provider_model_id,
                provider_model_id=provider_model_id,
                availability="unavailable",
                inference_readiness="unavailable",
                loaded=False,
                error_code=RuntimeErrorCode.MODEL_NOT_FOUND.value,
                message="Model is not available to this DeepSeek credential.",
            )
        return ModelHealth(
            logical_model_id=provider_model_id,
            provider_model_id=provider_model_id,
            availability="available",
            inference_readiness="ready",
            loaded=False,
        )

    def load_model(
        self,
        provider_model_id: str,
        request: GenerationRequest | None = None,
    ) -> dict[str, Any]:
        del request
        self._require_model(provider_model_id)
        return {"provider_model_id": provider_model_id, "operation": "not_applicable"}

    def unload_model(self, provider_model_id: str) -> dict[str, Any]:
        self._require_model(provider_model_id)
        return {"provider_model_id": provider_model_id, "operation": "not_applicable"}

    def generate(self, request: GenerationRequest) -> ProviderResponse:
        provider_model_id = request.effective_provider_model_id
        self._require_model(provider_model_id)
        if request.stream:
            raise LLMRuntimeError(
                RuntimeErrorCode.UNSUPPORTED_CAPABILITY,
                "DeepSeek school integration accepts buffered generation only.",
                provider=self.name,
            )

        messages = self._messages_for(request)
        response_format = None
        if request.structured_schema is not None:
            schema_text = json.dumps(request.structured_schema, ensure_ascii=False, sort_keys=True)
            instruction = (
                "Return a JSON object only. Make it conform to this JSON Schema:\n"
                f"{schema_text}"
            )
            if messages[0]["role"] == "system":
                messages[0]["content"] = f"{messages[0]['content']}\n\n{instruction}"
            else:
                messages.insert(0, {"role": "system", "content": instruction})
            response_format = {"type": "json_object"}

        body: dict[str, Any] = {
            "model": provider_model_id,
            "messages": messages,
            "stream": False,
            "thinking": {"type": "disabled"},
            "max_tokens": request.config.max_output_tokens,
            "temperature": request.config.temperature,
        }
        if response_format is not None:
            body["response_format"] = response_format
        payload = self._request_json(
            "POST",
            "/chat/completions",
            body,
            timeout=request.config.timeout_seconds,
        )
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
            raise self._protocol_error("DeepSeek returned no completion choice.")
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, str) or not content.strip():
            raise self._protocol_error("DeepSeek returned an empty completion.")
        actual_model = payload.get("model")
        finish_reason = choices[0].get("finish_reason")
        structured = (
            parse_and_validate(content, request.structured_schema)
            if request.structured_schema is not None
            else None
        )
        return ProviderResponse(
            text=content,
            provider=self.name,
            provider_model=actual_model if isinstance(actual_model, str) else provider_model_id,
            runtime_version="deepseek-api",
            usage=Usage.from_openai(
                payload.get("usage") if isinstance(payload.get("usage"), Mapping) else None
            ),
            finish_reason=finish_reason if isinstance(finish_reason, str) else None,
            structured=structured,
            metadata={"api_request_id": payload.get("id")},
        )

    def stream_generate(self, request: GenerationRequest) -> Iterator[RuntimeStreamEvent]:
        yield RuntimeStreamEvent(
            event_type=StreamEventType.ERROR,
            request_id=request.request_id,
            trace_id=request.trace_id,
            error_code=RuntimeErrorCode.UNSUPPORTED_CAPABILITY.value,
            error_message="DeepSeek school integration does not expose streamed output.",
        )

    def cancel(self, request_id: str) -> bool:
        del request_id
        return False

    def capabilities(self) -> Capabilities:
        return Capabilities(
            chat=True,
            stream=False,
            structured_output=True,
            json_schema=False,
            tools=False,
            vision=False,
            reasoning=False,
            embeddings=False,
        )

    def runtime_info(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "endpoint": _API_BASE_URL,
            "api": "chat-completions",
            "streaming": False,
            "fallback": False,
        }

    def close(self) -> None:
        self._client.close()

    def _request_json(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout: float,
    ) -> dict[str, Any]:
        try:
            response = self._client.request(
                method,
                path,
                json=payload,
                timeout=httpx.Timeout(max(float(timeout), 0.001)),
            )
        except httpx.TimeoutException:
            raise LLMRuntimeError(
                RuntimeErrorCode.REQUEST_TIMEOUT,
                "DeepSeek request timed out; automatic retry is disabled.",
                provider=self.name,
            ) from None
        except httpx.RequestError:
            raise LLMRuntimeError(
                RuntimeErrorCode.PROVIDER_UNAVAILABLE,
                "DeepSeek endpoint is unavailable.",
                provider=self.name,
            ) from None

        if response.status_code >= 400:
            if response.status_code in {401, 403}:
                code = RuntimeErrorCode.CONFIGURATION_ERROR
                message = "DeepSeek rejected the configured API credential."
            elif response.status_code == 404:
                code = RuntimeErrorCode.MODEL_NOT_FOUND
                message = "DeepSeek endpoint or model was not found."
            elif response.status_code == 429:
                code = RuntimeErrorCode.PROVIDER_NOT_READY
                message = "DeepSeek rate limit was reached; automatic retry is disabled."
            elif response.status_code >= 500:
                code = RuntimeErrorCode.PROVIDER_UNAVAILABLE
                message = "DeepSeek endpoint returned a server error."
            else:
                code = RuntimeErrorCode.RUNTIME_ERROR
                message = "DeepSeek rejected the request."
            raise LLMRuntimeError(
                code,
                message,
                status_code=response.status_code,
                provider=self.name,
            )
        try:
            value = response.json()
        except (UnicodeDecodeError, ValueError):
            raise self._protocol_error("DeepSeek returned invalid JSON.") from None
        if not isinstance(value, dict):
            raise self._protocol_error("DeepSeek returned a non-object JSON response.")
        return value

    @staticmethod
    def _messages_for(request: GenerationRequest) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for message in request.effective_messages:
            role = message.get("role")
            content = message.get("content")
            if role not in _ALLOWED_ROLES or not isinstance(content, str):
                raise LLMRuntimeError(
                    RuntimeErrorCode.UNSUPPORTED_CAPABILITY,
                    "DeepSeek request contains an unsupported message shape.",
                    provider=DeepSeekProvider.name,
                )
            messages.append({"role": role, "content": content})
        if not messages:
            raise LLMRuntimeError(
                RuntimeErrorCode.CONFIGURATION_ERROR,
                "DeepSeek request has no messages.",
                provider=DeepSeekProvider.name,
            )
        return messages

    @staticmethod
    def _require_model(provider_model_id: str) -> None:
        if provider_model_id != _MODEL_ID:
            raise LLMRuntimeError(
                RuntimeErrorCode.MODEL_NOT_FOUND,
                "Requested DeepSeek model is not registered for this deployment.",
                provider=DeepSeekProvider.name,
            )

    @classmethod
    def _protocol_error(cls, message: str) -> LLMRuntimeError:
        return LLMRuntimeError(
            RuntimeErrorCode.PROVIDER_PROTOCOL_ERROR,
            message,
            provider=cls.name,
        )
