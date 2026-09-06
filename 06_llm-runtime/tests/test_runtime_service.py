from __future__ import annotations

from llm_runtime.domain.models import (
    Capabilities,
    Compatibility,
    HardwareProfile,
    ModelEntry,
    ModelStatus,
    StreamEventType,
)
from llm_runtime.domain.registry import ModelRegistry
from llm_runtime.errors import LLMRuntimeError, RuntimeErrorCode
from llm_runtime.providers.base import LLMProvider
from llm_runtime.providers.mock import MockProvider
from llm_runtime.runtime.service import RuntimeService


def _entry(logical, contract, provider_model, *, fallback=None):
    return ModelEntry(
        logical_model_id=logical,
        contract_model_id=contract,
        display_name=logical,
        family="test",
        parameters="small",
        provider="mock",
        provider_model_id=provider_model,
        capabilities=Capabilities(chat=True, stream=True, structured_output=True, json_schema=True),
        hardware_profile=HardwareProfile.CPU_ONLY,
        compatibility=Compatibility.SUPPORTED,
        status=ModelStatus.READY,
        fallback_model_id=fallback,
    )


def test_service_retries_transient_error(hardware, request_factory):
    provider = MockProvider(("primary",), timeout_models=("primary",))
    registry = ModelRegistry([_entry("primary", "MODEL_local_primary", "primary")])
    service = RuntimeService(registry, {"mock": provider}, hardware=hardware, backoff_seconds=(0,))
    request = request_factory(logical_model_id="primary", prompt="__timeout__")

    try:
        service.generate(request)
    except LLMRuntimeError as error:
        assert error.code is RuntimeErrorCode.REQUEST_TIMEOUT
        assert error.details["trace_id"] == "TRACE_test_001"
    else:  # pragma: no cover
        raise AssertionError("expected timeout")
    assert provider.generate_calls == 2
    assert service.last_trace(request.request_id).retry_count == 1


def test_service_uses_local_fallback_and_records_trace(hardware, request_factory):
    provider = MockProvider(("primary", "fallback"), unavailable_models=("primary",))
    registry = ModelRegistry(
        [
            _entry("primary", "MODEL_local_primary", "primary", fallback="fallback"),
            _entry("fallback", "MODEL_local_fallback", "fallback"),
        ]
    )
    service = RuntimeService(registry, {"mock": provider}, hardware=hardware, backoff_seconds=(0,))
    request = request_factory(logical_model_id="primary", prompt="__unavailable__")

    result = service.generate(request)

    assert result.actual_model_id == "fallback"
    assert result.trace.requested_model == "primary"
    assert result.trace.requested_provider_model == "primary"
    assert result.trace.actual_model == "fallback"
    assert result.trace.fallback_reason == RuntimeErrorCode.PROVIDER_UNAVAILABLE.value
    assert result.trace.primary_error_normalized_code == RuntimeErrorCode.PROVIDER_UNAVAILABLE.value
    assert result.trace.primary_error["code"] == RuntimeErrorCode.PROVIDER_UNAVAILABLE.value
    assert result.trace.fallback_attempted is True
    assert result.trace.fallback_model == "fallback"
    assert result.trace.fallback_provider_model == "fallback"
    assert result.trace.fallback_generation_success is True
    assert result.trace.fallback_count == 1


def test_service_cancel_has_no_done_after_cancel(hardware, request_factory):
    provider = MockProvider(("primary",))
    registry = ModelRegistry([_entry("primary", "MODEL_local_primary", "primary")])
    service = RuntimeService(registry, {"mock": provider}, hardware=hardware)
    request = request_factory(logical_model_id="primary")
    events = service.stream_generate(request)

    first = next(events)
    assert first.event_type is StreamEventType.START
    assert service.cancel(request.request_id) is True
    remaining = list(events)

    assert [event.event_type for event in remaining] == [StreamEventType.CANCELLED]
