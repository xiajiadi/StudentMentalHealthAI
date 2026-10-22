from __future__ import annotations

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import cast

import pytest
from fastapi.testclient import TestClient

from llm_runtime.api.app import Runtime, create_app
from llm_runtime.domain.models import (
    Capabilities,
    Compatibility,
    HardwareProfile,
    ModelEntry,
    ModelStatus,
    ProviderResponse,
    Usage,
)
from llm_runtime.domain.registry import ModelRegistry
from llm_runtime.errors import LLMRuntimeError, RuntimeErrorCode
from llm_runtime.providers.mock import MockProvider
from llm_runtime.runtime.health import RuntimeState, RuntimeStateMachine
from llm_runtime.runtime.process import ExternalProcessBinding, ManagedProcess, ProcessMode
from llm_runtime.runtime.registry import ProviderDefinition, ProviderRegistry
from llm_runtime.runtime.service import RuntimeService


def _entry(logical: str, provider_model: str, *, fallback: str | None = None) -> ModelEntry:
    return ModelEntry(
        logical_model_id=logical,
        contract_model_id=f"MODEL_{logical}",
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


def test_state_machine_rejects_invalid_transition():
    machine = RuntimeStateMachine()
    machine.transition(RuntimeState.STARTING)
    machine.transition(RuntimeState.READY)
    with pytest.raises(LLMRuntimeError) as error:
        machine.transition(RuntimeState.STOPPED)
    assert error.value.code is RuntimeErrorCode.CONFIGURATION_ERROR


def test_provider_registry_rejects_non_loopback_endpoint():
    provider = MockProvider(("primary",))
    definition = ProviderDefinition(
        provider_id="mock",
        provider_type="MockProvider",
        endpoint="http://203.0.113.10:8080",
    )
    with pytest.raises(ValueError, match="loopback"):
        ProviderRegistry({"mock": provider}, definitions={"mock": definition})


def test_provider_registry_starts_and_stops_only_owned_process(tmp_path):
    provider = MockProvider(("primary",))
    binding = ExternalProcessBinding(
        mode=ProcessMode.MANAGED,
        command=(sys.executable, "-c", "import time; time.sleep(30)"),
        stdout_path=str(tmp_path / "stdout.log"),
        stderr_path=str(tmp_path / "stderr.log"),
    )
    definition = ProviderDefinition(
        provider_id="mock",
        provider_type="MockProvider",
        endpoint="in-process",
        mode=ProcessMode.MANAGED,
        process_binding=binding,
    )
    registry = ProviderRegistry({"mock": provider}, definitions={"mock": definition})
    started = registry.start_managed()
    assert started["mock"]["pid"] > 0
    assert registry.process_health()["mock"]["owned"] is True
    registry.close(timeout_seconds=2)
    assert registry.process_health()["mock"]["state"] == "STOPPED"


class InvalidStructuredProvider(MockProvider):
    def __init__(self) -> None:
        super().__init__(("primary", "fallback"))
        self.seen: list[str] = []

    def generate(self, request):
        self.seen.append(request.effective_provider_model_id)
        if request.effective_provider_model_id == "primary":
            return ProviderResponse(
                text='{"wrong": "value"}',
                provider=self.name,
                provider_model="primary",
                runtime_version="mock-0.1.0",
                usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )
        return super().generate(request)


def test_invalid_structured_output_does_not_fallback(hardware, request_factory):
    provider = InvalidStructuredProvider()
    registry = ModelRegistry(
        [
            _entry("primary", "primary", fallback="fallback"),
            _entry("fallback", "fallback"),
        ]
    )
    service = RuntimeService(registry, {"mock": provider}, hardware=hardware, backoff_seconds=(0,))
    request = request_factory(
        logical_model_id="primary",
        structured_schema={
            "type": "object",
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
        },
    )
    with pytest.raises(LLMRuntimeError) as error:
        service.generate(request)
    assert error.value.code is RuntimeErrorCode.INVALID_STRUCTURED_OUTPUT
    assert provider.seen == ["primary"]


def test_fallback_exhaustion_is_explicit(hardware, request_factory):
    provider = MockProvider(("primary", "fallback"), unavailable_models=("primary", "fallback"))
    registry = ModelRegistry(
        [
            _entry("primary", "primary", fallback="fallback"),
            _entry("fallback", "fallback"),
        ]
    )
    service = RuntimeService(registry, {"mock": provider}, hardware=hardware, backoff_seconds=(0,))
    request = request_factory(logical_model_id="primary", prompt="__unavailable__")
    with pytest.raises(LLMRuntimeError) as error:
        service.generate(request)
    assert error.value.code is RuntimeErrorCode.FALLBACK_EXHAUSTED
    assert error.value.details["trace_id"] == request.trace_id
    trace = service.last_trace(request.request_id)
    assert trace is not None
    assert trace.fallback_count == 1


class SlowMockProvider(MockProvider):
    def __init__(self) -> None:
        super().__init__(("primary",))
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def generate(self, request):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.15)
            return super().generate(request)
        finally:
            with self.lock:
                self.active -= 1


def test_generation_concurrency_is_bounded(hardware, request_factory):
    provider = SlowMockProvider()
    registry = ModelRegistry([_entry("primary", "primary")])
    service = RuntimeService(
        registry,
        {"mock": provider},
        hardware=hardware,
        acquire_timeout_seconds=0.03,
        backoff_seconds=(0,),
    )
    requests = [request_factory(request_id=f"REQ_concurrency_{index}") for index in range(2)]

    def run(request):
        try:
            service.generate(request)
            return "success"
        except LLMRuntimeError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, requests))
    assert provider.max_active == 1
    assert "success" in results
    assert RuntimeErrorCode.RUNTIME_BUSY in results


def test_fastapi_lifespan_routes_and_buffered_generation(hardware, request_factory):
    provider = MockProvider(("primary",))
    registry = ModelRegistry([_entry("primary", "primary")])
    service = RuntimeService(registry, {"mock": provider}, hardware=hardware, backoff_seconds=(0,))
    app = create_app(runtime=Runtime(service))
    with TestClient(app) as client:
        assert client.get("/health/live").json()["status"] == "LIVE"
        assert client.get("/health/ready").status_code == 200
        assert (
            client.get("/internal/llm/models").json()["models"][0]["logical_model_id"]
            == "primary"
        )
        payload = {
            "request_id": "REQ_api_001",
            "trace_id": "TRACE_api_001",
            "generation_id": "GEN_api_001",
            "assessment_id": "ASSESS_api_001",
            "subject_id": "SUBJ_api_001",
            "target_role": "teacher",
            "purpose": "education_support",
            "language": "zh-CN",
            "safety_mode": "standard",
            "retrieval_id": "RETR_api_001",
            "chunk_ids": ["CHUNK_api_001"],
            "prompt_id": "PROMPT_api_v1",
            "prompt_version": "0.1.0",
            "contract_model_id": "MODEL_primary",
            "logical_model_id": "primary",
            "prompt": "synthetic request",
            "stream": False,
        }
        response = client.post("/internal/llm/generate", json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["data"]["logical_model_id"] == "primary"
        assert body["data"]["buffered"] is True
        assert body["data"]["synthetic_fixture_only"] is True
    assert service.state is RuntimeState.STOPPED


def test_deepseek_internal_routes_require_bearer_before_body_validation(hardware):
    provider = MockProvider(("primary",))
    registry = ModelRegistry([_entry("primary", "primary")])
    service = RuntimeService(registry, {"mock": provider}, hardware=hardware)
    token = "a" * 48
    app = create_app(runtime=Runtime(service), internal_auth_token=token)

    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/docs").status_code == 404
        assert client.get("/internal/llm/models").status_code == 401
        assert client.get(
            "/internal/llm/models",
            headers={"Authorization": "Bearer wrong-token"},
        ).status_code == 401
        assert client.get(
            "/internal/llm/models",
            headers={"Authorization": f"Bearer {token}"},
        ).status_code == 200
        assert client.post("/internal/llm/generations", json={}).status_code == 401

    assert service.state is RuntimeState.STOPPED


def test_managed_process_does_not_use_shell(tmp_path):
    manager = ManagedProcess(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
    )
    manager.start()
    command = cast(list[str], manager.metadata()["command"])
    assert command[0] == sys.executable
    manager.stop(timeout_seconds=2)
