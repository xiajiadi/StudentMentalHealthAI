from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
RUNTIME_SOURCE = Path(__file__).resolve().parents[2] / "06_llm-runtime" / "src"
sys.path.insert(0, str(RUNTIME_SOURCE))

import school_independent_runtime as independent
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
        super().__init__((independent.SCHOOL_PROVIDER_MODEL_ID,))
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
        logical_model_id=independent.SCHOOL_MODEL_ID,
        contract_model_id=independent.SCHOOL_CONTRACT_MODEL_ID,
        display_name="school demo model",
        family="qwen2.5",
        parameters="7B",
        provider="mock",
        provider_model_id=independent.SCHOOL_PROVIDER_MODEL_ID,
        capabilities=Capabilities(chat=True, structured_output=True),
        hardware_profile=HardwareProfile.CONSUMER_GPU,
        compatibility=Compatibility.SUPPORTED,
        status=ModelStatus.READY,
        fallback_model_id=None,
        fallback_eligible=False,
        context_limit=8192,
        local_only=True,
    )
    service = RuntimeService(
        ModelRegistry((entry,)),
        {"mock": provider},
        hardware=FakeHardware(),
        max_attempts=1,
        backoff_seconds=(),
        default_model_id=independent.SCHOOL_MODEL_ID,
    )
    app = FastAPI()
    independent.attach_independent_routes(app, Runtime(service))
    with TestClient(app) as client:
        yield client, service, provider
    service.shutdown()


def _request_payload() -> dict[str, Any]:
    return {
        "request_id": "REQ_independent_001",
        "trace_id": "TRACE_independent_001",
        "generation_id": "GEN_independent_001",
        "conversation_id": "CONV_independent_001",
        "turn_id": "TURN_independent_001",
        "retrieval_id": "RETR_independent_001",
        "chunk_ids": ["CHUNK_synthetic_001"],
        "prompt_ref": {"prompt_id": "PROMPT_student_chat_v1", "prompt_version": "1.0.0"},
        "messages": [
            {"role": "system", "content": "Provide brief educational support."},
            {"role": "user", "content": "Help me plan a short study break."},
        ],
        "structured_schema": {
            "type": "object",
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
        },
        "config": {"max_output_tokens": 64, "temperature": 0.1, "timeout_seconds": 2.0},
    }


def test_independent_route_uses_runtime_service_duck_type_and_result_shape(runtime_client) -> None:
    client, service, provider = runtime_client
    response = client.post(independent.ROUTE_PATH, json=_request_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == "REQ_independent_001"
    assert body["trace_id"] == "TRACE_independent_001"
    assert body["generation_id"] == "GEN_independent_001"
    assert body["conversation_id"] == "CONV_independent_001"
    assert body["turn_id"] == "TURN_independent_001"
    assert set(body["data"]) == {
        "text",
        "model_id",
        "logical_model_id",
        "model_version",
        "runtime_version",
        "trace",
        "buffered",
        "synthetic_fixture_only",
    }
    assert body["data"]["model_id"] == independent.SCHOOL_CONTRACT_MODEL_ID
    assert body["data"]["logical_model_id"] == independent.SCHOOL_MODEL_ID
    assert body["data"]["trace"]["trace_id"] == "TRACE_independent_001"
    assert "assessment_id" not in body and "subject_id" not in body["data"]
    assert provider.generate_calls == 1
    runtime_request = provider.seen[0]
    assert isinstance(runtime_request, independent.IndependentRuntimeRequest)
    assert runtime_request.contract_model_id == independent.SCHOOL_CONTRACT_MODEL_ID
    assert runtime_request.logical_model_id == independent.SCHOOL_MODEL_ID
    assert runtime_request.provider_model_id == independent.SCHOOL_PROVIDER_MODEL_ID
    assert runtime_request.target_role == "student"
    assert runtime_request.purpose == "education_support"
    assert runtime_request.stream is False
    assert runtime_request.structured_schema == _request_payload()["structured_schema"]
    assert runtime_request.config.max_output_tokens == 64
    assert runtime_request.config.timeout_seconds == 2.0
    assert runtime_request.conversation_id == "CONV_independent_001"
    assert runtime_request.turn_id == "TURN_independent_001"
    assert not hasattr(runtime_request, "assessment_id")
    assert not hasattr(runtime_request, "subject_id")
    assert service.registry.resolve_primary().logical_model_id == independent.SCHOOL_MODEL_ID


@pytest.mark.parametrize(
    "forbidden_field,value",
    [
        ("assessment_id", "ASSESS_forged"),
        ("subject_id", "SUBJ_forged"),
        ("target_role", "teacher"),
        ("purpose", "diagnosis"),
        ("logical_model_id", "other-model"),
        ("contract_model_id", "MODEL_other"),
        ("provider_model_id", "other-provider-model"),
        ("stream", True),
    ],
)
def test_independent_route_rejects_forged_or_unsupported_fields(
    runtime_client,
    forbidden_field: str,
    value: Any,
) -> None:
    client, _service, provider = runtime_client
    payload = _request_payload()
    payload[forbidden_field] = value

    response = client.post(independent.ROUTE_PATH, json=payload)

    assert response.status_code == 422
    assert provider.generate_calls == 0


def test_independent_route_rejects_zero_chunks_and_missing_required_objects(runtime_client) -> None:
    client, _service, provider = runtime_client
    no_chunks = _request_payload()
    no_chunks["chunk_ids"] = []
    missing_config = _request_payload()
    del missing_config["config"]
    missing_schema = _request_payload()
    del missing_schema["structured_schema"]

    assert client.post(independent.ROUTE_PATH, json=no_chunks).status_code == 422
    assert client.post(independent.ROUTE_PATH, json=missing_config).status_code == 422
    assert client.post(independent.ROUTE_PATH, json=missing_schema).status_code == 422
    assert provider.generate_calls == 0


def test_independent_route_forbids_unknown_nested_fields(runtime_client) -> None:
    client, _service, provider = runtime_client
    bad_prompt_ref = _request_payload()
    bad_prompt_ref["prompt_ref"]["model_id"] = independent.SCHOOL_CONTRACT_MODEL_ID
    bad_config = _request_payload()
    bad_config["config"]["stream"] = True
    bad_message = _request_payload()
    bad_message["messages"][0]["provider"] = "mock"

    for body in (bad_prompt_ref, bad_config, bad_message):
        assert client.post(independent.ROUTE_PATH, json=body).status_code == 422
    assert provider.generate_calls == 0


def test_independent_route_rejects_wrong_default_model_before_generation(runtime_client) -> None:
    client, service, provider = runtime_client
    service.default_model_id = "different-model"

    response = client.post(independent.ROUTE_PATH, json=_request_payload())

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "SCHOOL_RUNTIME_CONFIGURATION_INVALID"
    assert provider.generate_calls == 0
