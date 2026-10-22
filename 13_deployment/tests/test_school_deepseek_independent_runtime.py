from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

DEPLOYMENT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEPLOYMENT_ROOT))
sys.path.insert(0, str(DEPLOYMENT_ROOT.parent / "06_llm-runtime" / "src"))

import school_deepseek_independent_runtime as independent
from llm_runtime.api.app import Runtime
from llm_runtime.domain.models import (
    Capabilities,
    Compatibility,
    HardwareProfile,
    ModelEntry,
    ModelStatus,
)
from llm_runtime.domain.registry import ModelRegistry
from llm_runtime.providers.mock import MockProvider
from llm_runtime.runtime.service import RuntimeService


class CapturingMockProvider(MockProvider):
    def __init__(self) -> None:
        super().__init__((independent.DEEPSEEK_PROVIDER_MODEL_ID,))
        self.seen: list[Any] = []

    def generate(self, request):
        self.seen.append(request)
        return super().generate(request)


class FakeHardware:
    def to_dict(self) -> dict[str, Any]:
        return {"gpu_present": False, "profile": "test"}


@pytest.fixture
def runtime_client():
    provider = CapturingMockProvider()
    entry = ModelEntry(
        logical_model_id=independent.DEEPSEEK_LOGICAL_MODEL_ID,
        contract_model_id=independent.DEEPSEEK_CONTRACT_MODEL_ID,
        display_name="DeepSeek synthetic school demo",
        family="DeepSeek",
        parameters=None,
        provider=independent.DEEPSEEK_PROVIDER_ID,
        provider_model_id=independent.DEEPSEEK_PROVIDER_MODEL_ID,
        capabilities=Capabilities(chat=True, structured_output=True),
        hardware_profile=HardwareProfile.UNKNOWN,
        compatibility=Compatibility.UNKNOWN,
        status=ModelStatus.READY,
        fallback_model_id=None,
        fallback_eligible=False,
        context_limit=8192,
        local_only=False,
    )
    registry = ModelRegistry((entry,), allow_remote=True)
    service = RuntimeService(
        registry,
        {independent.DEEPSEEK_PROVIDER_ID: provider},
        hardware=FakeHardware(),
        max_attempts=1,
        backoff_seconds=(),
        default_model_id=independent.DEEPSEEK_LOGICAL_MODEL_ID,
    )
    app = FastAPI()
    independent.attach_deepseek_independent_route(app, Runtime(service))
    with TestClient(app) as client:
        yield client, service, provider
    service.shutdown()


def _request_payload() -> dict[str, Any]:
    return {
        "request_id": "REQ_deepseek_independent_001",
        "trace_id": "TRACE_deepseek_independent_001",
        "generation_id": "GEN_deepseek_independent_001",
        "conversation_id": "CONV_deepseek_independent_001",
        "turn_id": "TURN_deepseek_independent_001",
        "retrieval_id": "RETR_deepseek_independent_001",
        "chunk_ids": ["CHUNK_synthetic_001"],
        "prompt_ref": {
            "prompt_id": "PROMPT_student_chat_v1",
            "prompt_version": "1.0.0",
        },
        "messages": [
            {"role": "system", "content": "Provide brief education support."},
            {"role": "user", "content": "Help me make a study plan."},
        ],
        "structured_schema": {
            "type": "object",
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
        },
        "config": {
            "max_output_tokens": 64,
            "temperature": 0.1,
            "timeout_seconds": 3.0,
        },
    }


def test_deepseek_route_uses_fixed_model_and_assessment_free_runtime_request(runtime_client) -> None:
    client, service, provider = runtime_client
    response = client.post(independent.ROUTE_PATH, json=_request_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["model_id"] == independent.DEEPSEEK_CONTRACT_MODEL_ID
    assert body["data"]["logical_model_id"] == independent.DEEPSEEK_LOGICAL_MODEL_ID
    assert body["trace_id"] == "TRACE_deepseek_independent_001"
    assert "assessment_id" not in body
    assert "subject_id" not in body["data"]
    assert len(provider.seen) == 1
    request = provider.seen[0]
    assert request.contract_model_id == independent.DEEPSEEK_CONTRACT_MODEL_ID
    assert request.logical_model_id == independent.DEEPSEEK_LOGICAL_MODEL_ID
    assert request.provider_model_id == independent.DEEPSEEK_PROVIDER_MODEL_ID
    assert request.target_role == "student"
    assert request.purpose == "education_support"
    assert request.stream is False
    assert not hasattr(request, "assessment_id")
    assert not hasattr(request, "subject_id")
    assert service.registry.cloud_fallback is False


def test_deepseek_route_fails_closed_if_service_default_does_not_match(runtime_client) -> None:
    client, service, provider = runtime_client
    service.default_model_id = "different-model"

    response = client.post(independent.ROUTE_PATH, json=_request_payload())

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "SCHOOL_RUNTIME_CONFIGURATION_INVALID"
    assert provider.generate_calls == 0


def test_deepseek_launcher_registers_route_and_keeps_loopback_binding(monkeypatch) -> None:
    import school_deepseek_runtime_linux as launcher

    started: list[tuple[Any, dict[str, Any]]] = []
    monkeypatch.setattr(
        launcher.uvicorn,
        "run",
        lambda app, **kwargs: started.append((app, kwargs)),
    )

    launcher.main()

    assert len(started) == 1
    app, options = started[0]
    assert any(route.path == independent.ROUTE_PATH for route in app.routes)
    assert options["host"] == "127.0.0.1"
    assert options["port"] == 8160
    assert options["access_log"] is False

