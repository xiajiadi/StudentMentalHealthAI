"""Provider-neutral local generation service."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from threading import RLock
from typing import Any

from ..domain.models import (
    GenerationRequest,
    ModelEntry,
    ModelHealth,
    ModelStatus,
    ProviderResponse,
    RuntimeStreamEvent,
    RuntimeTrace,
    StreamEventType,
)
from ..domain.registry import ModelRegistry
from ..errors import LLMRuntimeError, RuntimeErrorCode
from ..hardware.detector import HardwareDetector
from ..observability.tracing import RuntimeTraceBuilder
from ..providers.base import LLMProvider
from ..validation import parse_and_validate
from .coordinator import GenerationCoordinator
from .health import RuntimeHealth, RuntimeState, RuntimeStateMachine
from .registry import ExternalProcessBinding, ProviderRegistry

_FALLBACK_ELIGIBLE = frozenset(
    {
        RuntimeErrorCode.PROVIDER_UNAVAILABLE,
        RuntimeErrorCode.PROVIDER_NOT_READY,
        RuntimeErrorCode.MODEL_NOT_FOUND,
        RuntimeErrorCode.MODEL_NOT_READY,
        RuntimeErrorCode.MODEL_LOAD_FAILED,
        RuntimeErrorCode.REQUEST_TIMEOUT,
    }
)


@dataclass
class GenerationAttempt:
    attempt_index: int
    provider_id: str
    logical_model_id: str
    provider_model_id: str
    started_at: str
    ended_at: str | None = None
    outcome: str = "started"
    error_code: str | None = None
    fallback_reason: str | None = None
    retry: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_index": self.attempt_index,
            "provider_id": self.provider_id,
            "logical_model_id": self.logical_model_id,
            "provider_model_id": self.provider_model_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "outcome": self.outcome,
            "error_code": self.error_code,
            "fallback_reason": self.fallback_reason,
            "retry": self.retry,
        }


@dataclass
class GenerationResult:
    request_id: str
    trace_id: str
    status: str
    text: str
    provider_id: str
    logical_model_id: str
    actual_model_id: str
    executed_model: ModelEntry
    response: ProviderResponse
    trace: RuntimeTrace
    fallback_used: bool = False
    attempts: tuple[GenerationAttempt, ...] = ()
    error: LLMRuntimeError | None = None
    started_at: str | None = None
    ended_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "status": self.status,
            "text": self.text,
            "provider_id": self.provider_id,
            "logical_model_id": self.logical_model_id,
            "actual_model_id": self.actual_model_id,
            "executed_model": self.executed_model.to_dict(),
            "response": {
                "provider": self.response.provider,
                "provider_model": self.response.provider_model,
                "runtime_version": self.response.runtime_version,
                "usage": self.response.usage.to_dict(),
                "finish_reason": self.response.finish_reason,
                "structured": self.response.structured,
                "metadata": dict(self.response.metadata),
            },
            "trace": self.trace.to_dict(),
            "fallback_used": self.fallback_used,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "error": self.error.to_dict() if self.error else None,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
        }


class RuntimeService:
    """Own model selection, provider lifecycle, retries and local fallback."""

    def __init__(
        self,
        registry: ModelRegistry,
        providers: Mapping[str, LLMProvider] | ProviderRegistry,
        *,
        hardware: Any | None = None,
        runtime_version: str = "0.1.0",
        max_attempts: int = 2,
        backoff_seconds: tuple[float, ...] = (0.25, 0.5),
        provider_registry: ProviderRegistry | None = None,
        default_model_id: str | None = None,
        max_generation_concurrency: int = 1,
        acquire_timeout_seconds: float = 5.0,
        shutdown_timeout_seconds: float = 10.0,
        preload_primary: bool = False,
        process_bindings: Mapping[str, ExternalProcessBinding] | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if any(value < 0 for value in backoff_seconds):
            raise ValueError("backoff_seconds must be non-negative")
        self.registry = registry
        if provider_registry is not None:
            self.provider_registry = provider_registry
        elif isinstance(providers, ProviderRegistry):
            self.provider_registry = providers
        else:
            self.provider_registry = ProviderRegistry(providers, process_bindings=process_bindings)
        self.providers = {
            definition.provider_id: provider
            for definition, provider in zip(
                self.provider_registry.definitions(),
                self.provider_registry.all(),
                strict=True,
            )
        }
        self.hardware = hardware or HardwareDetector().detect()
        self.runtime_version = runtime_version
        self.max_attempts = max_attempts
        self.backoff_seconds = tuple(backoff_seconds)
        self.shutdown_timeout_seconds = shutdown_timeout_seconds
        self.default_model_id: str = (
            default_model_id or self.registry.resolve_primary().logical_model_id
        )
        self.preload_primary = preload_primary
        self.coordinator = GenerationCoordinator(
            max_concurrency=max_generation_concurrency,
            acquire_timeout_seconds=acquire_timeout_seconds,
        )
        self._state_machine = RuntimeStateMachine()
        self._closed = False
        self._lock = RLock()
        self._last_error: LLMRuntimeError | None = None
        self._last_traces: dict[str, RuntimeTrace] = {}
        self._started_at: str | None = None

    @property
    def state(self) -> RuntimeState:
        return self._state_machine.state

    def startup(self) -> dict[str, Any]:
        with self._lock:
            if self._closed:
                raise LLMRuntimeError(
                    RuntimeErrorCode.RUNTIME_NOT_READY,
                    "Runtime has been shut down.",
                )
            if self.state in {RuntimeState.READY, RuntimeState.DEGRADED}:
                return self.health()
            if self.state is RuntimeState.STARTING:
                return self.health()
            self._state_machine.transition(RuntimeState.STARTING)
            self._started_at = _now()
            self._last_error = None
        try:
            self.provider_registry.start_managed()
            provider_health = self.provider_registry.health()
            healthy = [value for value in provider_health.values() if value.readiness == "pass"]
            target = RuntimeState.READY if healthy else RuntimeState.DEGRADED
            with self._lock:
                self._state_machine.transition(target)
            if self.preload_primary and healthy:
                self.load_model(self.default_model_id)
            return self.health()
        except LLMRuntimeError as exc:
            with self._lock:
                self._last_error = exc
                self._state_machine.transition(RuntimeState.FAILED)
            raise
        except Exception as exc:
            error = LLMRuntimeError(
                RuntimeErrorCode.RUNTIME_ERROR,
                "Runtime startup failed.",
                details={"exception": type(exc).__name__},
            )
            with self._lock:
                self._last_error = error
                self._state_machine.transition(RuntimeState.FAILED)
            raise error from exc

    def shutdown(self) -> None:
        with self._lock:
            if self._closed and self.state is RuntimeState.STOPPED:
                return
            if self.state is not RuntimeState.STOPPED:
                self._state_machine.transition(RuntimeState.STOPPING)
        self.coordinator.cancel_all()
        first_error: LLMRuntimeError | None = None
        try:
            self.provider_registry.close(timeout_seconds=self.shutdown_timeout_seconds)
        except LLMRuntimeError as exc:
            first_error = exc
        with self._lock:
            if first_error is None:
                if self.state is RuntimeState.STOPPING:
                    self._state_machine.transition(RuntimeState.STOPPED)
            else:
                self._last_error = first_error
                if self.state is RuntimeState.STOPPING:
                    self._state_machine.transition(RuntimeState.FAILED)
            self._closed = True
        if first_error is not None:
            raise first_error

    close = shutdown

    def ready(self) -> bool:
        return self.state is RuntimeState.READY and not self._closed

    def health(self) -> dict[str, Any]:
        provider_health = self.provider_registry.health()
        models: dict[str, Any] = {}
        for entry in self.registry.all():
            try:
                provider = self.provider_registry.resolve(entry.provider)
                value = provider.model_health_check(entry.provider_model_id)
                models[entry.logical_model_id] = ModelHealth(
                    logical_model_id=entry.logical_model_id,
                    provider_model_id=entry.provider_model_id,
                    availability=value.availability,
                    inference_readiness=value.inference_readiness,
                    loaded=value.loaded,
                    error_code=value.error_code,
                    message=value.message,
                ).to_dict()
            except (LLMRuntimeError, KeyError) as exc:
                models[entry.logical_model_id] = {
                    "logical_model_id": entry.logical_model_id,
                    "provider_model_id": entry.provider_model_id,
                    "availability": "unknown",
                    "inference_readiness": "unknown",
                    "loaded": False,
                    "error_code": getattr(
                        getattr(exc, "code", None), "value", "CONFIGURATION_ERROR"
                    ),
                    "message": str(exc),
                }
        health = RuntimeHealth(
            state=self.state,
            runtime_version=self.runtime_version,
            cloud_fallback=self.registry.cloud_fallback,
            providers={key: value.to_dict() for key, value in provider_health.items()},
            models=models,
            processes=self.provider_registry.process_health(),
            last_error=self._last_error.to_dict() if self._last_error else None,
        )
        return health.to_dict()

    def list_models(self) -> list[dict[str, Any]]:
        return [entry.to_dict() for entry in self.registry.all()]

    def discover(self) -> dict[str, list[dict[str, Any]]]:
        discovered: dict[str, list[dict[str, Any]]] = {}
        for definition in self.provider_registry.definitions():
            if not definition.enabled:
                discovered[definition.provider_id] = []
                continue
            provider = self.provider_registry.resolve(definition.provider_id)
            values = provider.discover_models()
            discovered[definition.provider_id] = values
            self.registry.reconcile_discovery(definition.provider_id, values)
        return discovered

    def load_model(self, model_id: str, request: GenerationRequest | None = None) -> dict[str, Any]:
        self._ensure_available()
        entry = self.registry.resolve(model_id)
        provider = self.provider_registry.resolve(entry.provider)
        result = provider.load_model(entry.provider_model_id, request)
        entry.status = ModelStatus.LOADED
        self.registry.update(entry)
        return {"model": entry.to_dict(), "result": result}

    def unload_model(self, model_id: str) -> dict[str, Any]:
        self._ensure_available()
        entry = self.registry.resolve(model_id)
        provider = self.provider_registry.resolve(entry.provider)
        result = provider.unload_model(entry.provider_model_id)
        entry.status = ModelStatus.READY
        self.registry.update(entry)
        return {"model": entry.to_dict(), "result": result}

    def generate(self, request: GenerationRequest) -> GenerationResult:
        self._ensure_started()
        primary = self._resolve_request_model(request)
        candidates = (primary, *self.registry.fallback_chain(primary.logical_model_id))
        builder = RuntimeTraceBuilder(
            request,
            primary,
            runtime_version=self.runtime_version,
            hardware=self.hardware.to_dict(),
        )
        attempts: list[GenerationAttempt] = []
        started_at = _now()
        previous_error: LLMRuntimeError | None = None
        for candidate_index, model in enumerate(candidates):
            if candidate_index > 0:
                assert previous_error is not None
                builder.record_fallback(
                    primary_error=previous_error.to_dict(),
                    fallback_model=model,
                    fallback_reason=previous_error.code.value,
                )
            try:
                response, retries = self._generate_one(
                    request,
                    model,
                    attempts,
                    fallback_reason=(
                        previous_error.code.value
                        if candidate_index > 0 and previous_error
                        else None
                    ),
                )
                builder.set_selection(
                    actual_model=model,
                    retry_count=retries,
                    fallback_reason=builder.trace.fallback_reason,
                )
                builder.set_attempts([attempt.to_dict() for attempt in attempts])
                trace = builder.complete(response, retry_count=retries)
                self._remember_trace(request.request_id, trace)
                return GenerationResult(
                    request_id=request.request_id,
                    trace_id=request.trace_id,
                    status="success",
                    text=response.text,
                    provider_id=model.provider,
                    logical_model_id=model.logical_model_id,
                    actual_model_id=model.logical_model_id,
                    executed_model=model,
                    response=response,
                    trace=trace,
                    fallback_used=candidate_index > 0,
                    attempts=tuple(attempts),
                    started_at=started_at,
                    ended_at=_now(),
                )
            except LLMRuntimeError as exc:
                previous_error = exc
                if not self._is_fallback_eligible(exc) or candidate_index >= len(candidates) - 1:
                    final_error = self._final_generation_error(
                        exc,
                        request,
                        attempts,
                        exhausted=(
                            candidate_index > 0
                            and candidate_index >= len(candidates) - 1
                            and self._is_fallback_eligible(exc)
                        ),
                    )
                    builder.set_attempts([attempt.to_dict() for attempt in attempts])
                    builder.fail(final_error.to_dict(), retry_count=_retry_count(attempts))
                    self._remember_trace(request.request_id, builder.trace)
                    raise final_error
        raise AssertionError("generation candidate loop completed without a result")

    async def generate_async(self, request: GenerationRequest) -> GenerationResult:
        try:
            return await asyncio.to_thread(self.generate, request)
        except asyncio.CancelledError:
            self.cancel(request.request_id)
            raise

    agenerate = generate_async

    def stream_generate(self, request: GenerationRequest) -> Any:
        """Yield provider-normalized events; streaming never crosses model fallback."""

        self._ensure_started()
        model = self._resolve_request_model(request)
        provider = self.provider_registry.resolve(model.provider)
        provider_request = self._provider_request(request, model)
        builder = RuntimeTraceBuilder(
            request,
            model,
            runtime_version=self.runtime_version,
            hardware=self.hardware.to_dict(),
        )
        attempts = [
            GenerationAttempt(
                1,
                model.provider,
                model.logical_model_id,
                model.provider_model_id,
                _now(),
            )
        ]
        terminal = False
        with self.coordinator.slot(request.request_id, provider):
            try:
                for event in provider.stream_generate(provider_request):
                    if event.event_type is StreamEventType.DELTA:
                        builder.mark_delta()
                    if event.event_type in {
                        StreamEventType.DONE,
                        StreamEventType.CANCELLED,
                        StreamEventType.ERROR,
                    }:
                        terminal = True
                        attempts[0].ended_at = _now()
                        attempts[0].outcome = event.event_type.value.lower()
                        attempts[0].error_code = event.error_code
                        builder.set_attempts([attempt.to_dict() for attempt in attempts])
                        trace = builder.complete_stream(
                            event,
                            usage=event.usage,
                            error=(
                                {
                                    "code": event.error_code,
                                    "message": event.error_message,
                                    "partial_output": bool(event.metadata.get("partial_output")),
                                }
                                if event.error_code
                                else None
                            ),
                        )
                        self._remember_trace(request.request_id, trace)
                    yield event
            except LLMRuntimeError as exc:
                attempts[0].ended_at = _now()
                attempts[0].outcome = "error"
                attempts[0].error_code = exc.code.value
                builder.set_attempts([attempt.to_dict() for attempt in attempts])
                error_event = RuntimeStreamEvent(
                    StreamEventType.ERROR,
                    request.request_id,
                    request.trace_id,
                    error_code=exc.code.value,
                    error_message=exc.message,
                    metadata={"partial_output": builder.trace.ttft_ms is not None},
                )
                trace = builder.complete_stream(error_event, error=exc.to_dict())
                self._remember_trace(request.request_id, trace)
                yield error_event
            finally:
                if not terminal:
                    attempts[0].ended_at = attempts[0].ended_at or _now()
                    attempts[0].outcome = (
                        attempts[0].outcome
                        if attempts[0].outcome != "started"
                        else "interrupted"
                    )
                    builder.set_attempts([attempt.to_dict() for attempt in attempts])

    def cancel(self, request_id: str) -> bool:
        return self.coordinator.cancel(request_id)

    def last_trace(self, request_id: str) -> RuntimeTrace | None:
        return self._last_traces.get(request_id)

    @staticmethod
    def parse_structured(text: str, schema_or_model: Any) -> Any:
        if isinstance(schema_or_model, Mapping):
            return parse_and_validate(text, schema_or_model)
        validator = getattr(schema_or_model, "model_validate_json", None)
        if callable(validator):
            try:
                return validator(text)
            except Exception as exc:
                raise LLMRuntimeError(
                    RuntimeErrorCode.INVALID_STRUCTURED_OUTPUT,
                    "Provider output failed Pydantic structured-output validation.",
                    details={"validation": "pydantic", "exception": type(exc).__name__},
                ) from exc
        raise LLMRuntimeError(
            RuntimeErrorCode.CONFIGURATION_ERROR,
            "Structured schema must be a JSON Schema mapping or a Pydantic model class.",
        )

    def _generate_one(
        self,
        request: GenerationRequest,
        model: ModelEntry,
        attempts: list[GenerationAttempt],
        *,
        fallback_reason: str | None,
    ) -> tuple[ProviderResponse, int]:
        provider = self.provider_registry.resolve(model.provider)
        retries = 0
        for attempt_number in range(1, self.max_attempts + 1):
            attempt = GenerationAttempt(
                attempt_index=len(attempts) + 1,
                provider_id=model.provider,
                logical_model_id=model.logical_model_id,
                provider_model_id=model.provider_model_id,
                started_at=_now(),
                fallback_reason=fallback_reason,
                retry=attempt_number > 1,
            )
            attempts.append(attempt)
            try:
                with self.coordinator.slot(request.request_id, provider):
                    response = provider.generate(self._provider_request(request, model))
                response = self._validate_response(request, response)
                attempt.ended_at = _now()
                attempt.outcome = "success"
                return response, retries
            except LLMRuntimeError as exc:
                attempt.ended_at = _now()
                attempt.outcome = "error"
                attempt.error_code = exc.code.value
                if not exc.retryable or attempt_number >= self.max_attempts:
                    raise
                retries += 1
                delay = (
                    self.backoff_seconds[
                        min(attempt_number - 1, len(self.backoff_seconds) - 1)
                    ]
                    if self.backoff_seconds
                    else 0
                )
                if delay:
                    time.sleep(delay)
            except Exception as exc:
                attempt.ended_at = _now()
                attempt.outcome = "error"
                attempt.error_code = RuntimeErrorCode.GENERATION_FAILED.value
                raise LLMRuntimeError(
                    RuntimeErrorCode.GENERATION_FAILED,
                    "Provider generation failed.",
                    provider=model.provider,
                    details={"exception": type(exc).__name__},
                ) from exc
        raise AssertionError("attempt loop completed without result or error")

    def _validate_response(
        self, request: GenerationRequest, response: ProviderResponse
    ) -> ProviderResponse:
        schema = request.structured_schema
        if schema is None:
            return response
        structured = self.parse_structured(response.text, schema)
        return replace(
            response,
            structured=structured,
            metadata={**dict(response.metadata), "schema_validated": True},
        )

    @staticmethod
    def _schema_dict(schema: Any) -> dict[str, Any]:
        if isinstance(schema, Mapping):
            return dict(schema)
        builder = getattr(schema, "model_json_schema", None)
        if callable(builder):
            value = builder()
            if isinstance(value, Mapping):
                return dict(value)
        raise LLMRuntimeError(
            RuntimeErrorCode.CONFIGURATION_ERROR,
            "Structured schema must expose a JSON Schema mapping.",
        )

    def _provider_request(self, request: GenerationRequest, model: ModelEntry) -> GenerationRequest:
        schema = request.structured_schema
        normalized = self._schema_dict(schema) if schema is not None else None
        return replace(
            request,
            logical_model_id=model.logical_model_id,
            provider_model_id=model.provider_model_id,
            structured_schema=normalized,
        )

    def _resolve_request_model(self, request: GenerationRequest) -> ModelEntry:
        model_id = request.logical_model_id or self.default_model_id
        try:
            return self.registry.resolve(model_id)
        except KeyError:
            try:
                return self.registry.resolve(request.contract_model_id)
            except KeyError as exc:
                raise LLMRuntimeError(
                    RuntimeErrorCode.MODEL_NOT_FOUND,
                    "Requested model is not in the local registry.",
                    details={"model_id": model_id},
                ) from exc

    def _ensure_started(self) -> None:
        if self._closed:
            raise LLMRuntimeError(RuntimeErrorCode.RUNTIME_NOT_READY, "Runtime has been shut down.")
        if self.state is RuntimeState.STOPPED:
            self.startup()
        if self.state is RuntimeState.FAILED:
            raise LLMRuntimeError(RuntimeErrorCode.RUNTIME_NOT_READY, "Runtime startup failed.")
        if self.state is RuntimeState.STOPPING:
            raise LLMRuntimeError(RuntimeErrorCode.RUNTIME_NOT_READY, "Runtime is stopping.")

    def _ensure_available(self) -> None:
        self._ensure_started()

    def _final_generation_error(
        self,
        error: LLMRuntimeError,
        request: GenerationRequest,
        attempts: list[GenerationAttempt],
        *,
        exhausted: bool,
    ) -> LLMRuntimeError:
        details = dict(error.details)
        details.setdefault("trace_id", request.trace_id)
        details["attempts"] = [attempt.to_dict() for attempt in attempts]
        if exhausted:
            details["last_error"] = error.to_dict()
            return LLMRuntimeError(
                RuntimeErrorCode.FALLBACK_EXHAUSTED,
                "All eligible local model candidates failed.",
                retryable=error.retryable,
                status_code=error.status_code,
                provider=error.provider,
                partial_output=error.partial_output,
                details=details,
            )
        return LLMRuntimeError(
            error.code,
            error.message,
            retryable=error.retryable,
            status_code=error.status_code,
            provider=error.provider,
            partial_output=error.partial_output,
            details=details,
        )

    @staticmethod
    def _is_fallback_eligible(error: LLMRuntimeError) -> bool:
        return error.code in _FALLBACK_ELIGIBLE and not error.partial_output

    def _remember_trace(self, request_id: str, trace: RuntimeTrace) -> None:
        with self._lock:
            self._last_traces[request_id] = trace


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _retry_count(attempts: list[GenerationAttempt]) -> int:
    return sum(1 for attempt in attempts if attempt.retry)


__all__ = ["GenerationAttempt", "GenerationResult", "RuntimeService"]
