"""Stable error domain and provider error mapping."""

from __future__ import annotations

import json
from collections.abc import Mapping
from enum import StrEnum
from typing import Any


class RuntimeErrorCode(StrEnum):
    RUNTIME_NOT_READY = "RUNTIME_NOT_READY"
    RUNTIME_BUSY = "RUNTIME_BUSY"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_NOT_READY = "PROVIDER_NOT_READY"
    PROVIDER_PROTOCOL_ERROR = "PROVIDER_PROTOCOL_ERROR"
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    MODEL_NOT_READY = "MODEL_NOT_READY"
    MODEL_LOAD_FAILED = "MODEL_LOAD_FAILED"
    CONTEXT_LIMIT_EXCEEDED = "CONTEXT_LIMIT_EXCEEDED"
    OUT_OF_MEMORY = "OUT_OF_MEMORY"
    REQUEST_TIMEOUT = "REQUEST_TIMEOUT"
    PROVIDER_TIMEOUT = "REQUEST_TIMEOUT"
    STREAM_INTERRUPTED = "STREAM_INTERRUPTED"
    INVALID_STRUCTURED_OUTPUT = "INVALID_STRUCTURED_OUTPUT"
    STRUCTURED_OUTPUT_INVALID = "INVALID_STRUCTURED_OUTPUT"
    UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
    CANCELLED = "CANCELLED"
    GENERATION_CANCELLED = "CANCELLED"
    GENERATION_FAILED = "GENERATION_FAILED"
    FALLBACK_EXHAUSTED = "FALLBACK_EXHAUSTED"
    PROCESS_START_FAILED = "PROCESS_START_FAILED"
    PROCESS_EXITED = "PROCESS_EXITED"
    PROCESS_STOP_FAILED = "PROCESS_STOP_FAILED"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    RUNTIME_ERROR = "RUNTIME_ERROR"


class LLMRuntimeError(Exception):
    """An error safe to expose to the runtime boundary.

    Provider response bodies are retained only in ``details`` after truncation;
    prompts, model context and credentials are intentionally not included.
    """

    def __init__(
        self,
        code: RuntimeErrorCode,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
        provider: str | None = None,
        partial_output: bool = False,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.status_code = status_code
        self.provider = provider
        self.partial_output = partial_output
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "retryable": self.retryable,
            "status_code": self.status_code,
            "provider": self.provider,
            "partial_output": self.partial_output,
            "details": dict(self.details),
        }


def map_http_error(
    status_code: int,
    body: str | bytes | Mapping[str, Any] | None,
    *,
    provider: str,
) -> LLMRuntimeError:
    message = _safe_error_message(body) or f"{provider} returned HTTP {status_code}."
    lowered = message.lower()
    if "out of memory" in lowered or "oom" in lowered or "not enough memory" in lowered:
        code = RuntimeErrorCode.OUT_OF_MEMORY
    elif status_code == 404 and "model" in lowered:
        code = RuntimeErrorCode.MODEL_NOT_FOUND
    elif status_code in {408, 504}:
        code = RuntimeErrorCode.REQUEST_TIMEOUT
    elif status_code in {502, 503}:
        code = RuntimeErrorCode.PROVIDER_NOT_READY
    elif status_code >= 500:
        code = RuntimeErrorCode.PROVIDER_UNAVAILABLE
    elif status_code == 429:
        code = RuntimeErrorCode.PROVIDER_NOT_READY
    else:
        code = RuntimeErrorCode.RUNTIME_ERROR
    return LLMRuntimeError(
        code,
        message,
        retryable=status_code in {408, 429, 500, 502, 503, 504},
        status_code=status_code,
        provider=provider,
    )


def map_provider_error(
    message: str,
    *,
    provider: str,
    status_code: int | None = None,
) -> LLMRuntimeError:
    lowered = message.lower()
    if "out of memory" in lowered or "oom" in lowered or "not enough memory" in lowered:
        code = RuntimeErrorCode.OUT_OF_MEMORY
    elif "context" in lowered and (
        "limit" in lowered or "exceed" in lowered or "length" in lowered
    ):
        code = RuntimeErrorCode.CONTEXT_LIMIT_EXCEEDED
    elif "not found" in lowered or "model does not exist" in lowered:
        code = RuntimeErrorCode.MODEL_NOT_FOUND
    elif "timeout" in lowered or "timed out" in lowered:
        code = RuntimeErrorCode.REQUEST_TIMEOUT
    elif "loading model" in lowered or "not ready" in lowered:
        code = RuntimeErrorCode.PROVIDER_NOT_READY
    elif "connection" in lowered or "refused" in lowered or "unreachable" in lowered:
        code = RuntimeErrorCode.PROVIDER_UNAVAILABLE
    elif "protocol" in lowered or "invalid json" in lowered or "malformed" in lowered:
        code = RuntimeErrorCode.PROVIDER_PROTOCOL_ERROR
    else:
        code = RuntimeErrorCode.RUNTIME_ERROR
    return LLMRuntimeError(
        code,
        message[:500],
        retryable=code in {
            RuntimeErrorCode.PROVIDER_UNAVAILABLE,
            RuntimeErrorCode.PROVIDER_NOT_READY,
            RuntimeErrorCode.REQUEST_TIMEOUT,
        },
        status_code=status_code,
        provider=provider,
    )


def _safe_error_message(body: str | bytes | Mapping[str, Any] | None) -> str | None:
    if body is None:
        return None
    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="replace")
    if isinstance(body, Mapping):
        value = body.get("error") or body.get("message")
        if isinstance(value, Mapping):
            value = value.get("message") or value.get("detail")
        return str(value)[:500] if value else None
    text = str(body).strip()
    if not text:
        return None
    try:
        return _safe_error_message(json.loads(text))
    except (json.JSONDecodeError, TypeError):
        return text[:500]

