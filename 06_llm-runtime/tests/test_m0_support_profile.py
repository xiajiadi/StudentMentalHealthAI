from __future__ import annotations

import pytest

import llm_runtime.cli as runtime_cli
from llm_runtime.errors import LLMRuntimeError
from llm_runtime.providers.mock import MockProvider


def test_m0_support_profile_is_allowlisted_and_uses_only_authorized_primary(monkeypatch, hardware):
    monkeypatch.setattr(runtime_cli.HardwareDetector, "detect", lambda self: hardware)
    monkeypatch.setenv("SMHAI_LLM_RUNTIME_PROFILE", "m0-p1-support")

    service = runtime_cli.build_service()
    try:
        assert service.max_attempts == 1
        assert service.backoff_seconds == ()
        assert service.default_model_id == "qwen2.5-0.5b-engineering"
        assert service.registry.cloud_fallback is False
        assert service.registry.fallback_chain(service.default_model_id) == ()
    finally:
        service.shutdown()


def test_unknown_runtime_profile_is_rejected(monkeypatch):
    monkeypatch.setenv("SMHAI_LLM_RUNTIME_PROFILE", "C:/arbitrary/runtime.json")

    with pytest.raises(ValueError, match="unknown LLM Runtime profile"):
        runtime_cli.build_service()


def test_m0_support_profile_makes_one_provider_attempt_without_fallback(
    monkeypatch, hardware, request_factory
):
    monkeypatch.setattr(runtime_cli.HardwareDetector, "detect", lambda self: hardware)
    provider = MockProvider(("qwen2.5:0.5b",), timeout_models=("qwen2.5:0.5b",))
    monkeypatch.setattr(runtime_cli, "OllamaProvider", lambda *_args, **_kwargs: provider)
    service = runtime_cli.build_service("m0-p1-support")
    request = request_factory(
        contract_model_id="MODEL_local_cpu_test",
        logical_model_id="qwen2.5-0.5b-engineering",
        prompt="__timeout__ synthetic fixture",
    )
    try:
        with pytest.raises(LLMRuntimeError):
            service.generate(request)
        assert provider.generate_calls == 1
        trace = service.last_trace(request.request_id)
        assert trace is not None
        assert trace.retry_count == 0
        assert trace.fallback_attempted is False
        assert len(trace.attempts) == 1
        assert trace.attempts[0]["logical_model_id"] == "qwen2.5-0.5b-engineering"
    finally:
        service.shutdown()
