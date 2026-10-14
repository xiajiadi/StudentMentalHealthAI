from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
RUNTIME_SOURCE = Path(__file__).resolve().parents[2] / "06_llm-runtime" / "src"
sys.path.insert(0, str(RUNTIME_SOURCE))

import school_independent_runtime as independent
import school_llm_runtime as school_host
import school_research_programme_runtime as research_programme
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
        super().__init__((school_host.EXPECTED_PROVIDER_MODEL_ID,))
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
        logical_model_id=school_host.EXPECTED_MODEL_ID,
        contract_model_id=school_host.EXPECTED_CONTRACT_MODEL_ID,
        display_name="school demo model",
        family="qwen2.5",
        parameters="7B",
        provider="ollama",
        provider_model_id=school_host.EXPECTED_PROVIDER_MODEL_ID,
        digest=school_host.EXPECTED_MODEL_DIGEST,
        expected_digest=school_host.EXPECTED_MODEL_DIGEST,
        format="gguf",
        quantization="Q4_K_M",
        size_bytes=school_host.EXPECTED_MODEL_SIZE,
        capabilities=Capabilities(chat=True, stream=False, structured_output=True),
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
        {"ollama": provider},
        hardware=FakeHardware(),
        max_attempts=1,
        backoff_seconds=(),
        default_model_id=school_host.EXPECTED_MODEL_ID,
    )
    app = FastAPI()
    independent.attach_independent_routes(app, Runtime(service))
    research_programme.attach_research_programme_routes(app, Runtime(service))
    with TestClient(app) as client:
        yield client, service, provider, app
    service.shutdown()


def _request_payload() -> dict[str, Any]:
    return {
        "schema_version": research_programme.SCHEMA_VERSION,
        "request_id": "REQ_programme_001",
        "trace_id": "TRACE_programme_001",
        "generation_id": "GEN_programme_001",
        "retrieval_id": "RETR_programme_001",
        "programme_ref": "PROGRAMME_staff_001",
        "source_manifest_sha256": "a" * 64,
        "prompt_ref": {"prompt_id": "PROMPT_school_programme_v1", "prompt_version": "1.0.0"},
        "chunk_ids": ["CHUNK_public_001"],
        "messages": [
            {"role": "system", "content": "Draft a general school programme for staff review."},
            {
                "role": "user",
                "content": "Prepare a short non-clinical school-wide activity outline.",
            },
        ],
        "structured_schema": {
            "type": "object",
            "required": ["title", "outline"],
            "properties": {"title": {"type": "string"}, "outline": {"type": "array"}},
        },
        "config": {"max_output_tokens": 64, "temperature": 0.1, "timeout_seconds": 2.0},
    }


def test_research_programme_route_returns_hold_candidate_without_student_identity(
    runtime_client,
) -> None:
    client, service, provider, app = runtime_client
    response = client.post(research_programme.ROUTE_PATH, json=_request_payload())

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "schema_version", "request_id", "trace_id", "generation_id", "retrieval_id",
        "programme_ref", "source_manifest_sha256", "prompt_ref", "chunk_ids", "purpose",
        "target_role", "production_use", "publication_eligible", "status", "data",
    }
    assert set(body["data"]) == {
        "text", "model_id", "logical_model_id", "model_version", "runtime_version",
        "trace", "buffered",
    }
    assert body["schema_version"] == research_programme.SCHEMA_VERSION
    assert body["request_id"] == "REQ_programme_001"
    assert body["trace_id"] == "TRACE_programme_001"
    assert body["generation_id"] == "GEN_programme_001"
    assert body["retrieval_id"] == "RETR_programme_001"
    assert body["programme_ref"] == "PROGRAMME_staff_001"
    assert body["source_manifest_sha256"] == "a" * 64
    assert body["purpose"] == "staff_school_programme_research"
    assert body["target_role"] == "psychological_specialist"
    assert body["production_use"] is False
    assert body["publication_eligible"] is False
    assert body["status"] == "HOLD_FOR_REVIEW"
    assert body["data"]["logical_model_id"] == school_host.EXPECTED_MODEL_ID
    assert body["data"]["model_id"] == school_host.EXPECTED_CONTRACT_MODEL_ID
    assert body["data"]["trace"]["request_id"] == "REQ_programme_001"
    assert body["data"]["trace"]["trace_id"] == "TRACE_programme_001"
    assert provider.generate_calls == 1
    request = provider.seen[0]
    assert isinstance(request, research_programme.ResearchProgrammeRuntimeRequest)
    assert request.target_role == "psychological_specialist"
    assert request.purpose == "staff_school_programme_research"
    assert request.production_use is False
    assert request.publication_eligible is False
    assert request.stream is False
    assert request.config.max_output_tokens == 64
    assert request.effective_provider_model_id == school_host.EXPECTED_PROVIDER_MODEL_ID
    for forbidden in ("assessment_id", "subject_id", "conversation_id", "turn_id"):
        assert not hasattr(request, forbidden)
        assert forbidden not in body
        assert forbidden not in body["data"]
    paths = {route.path for route in app.routes}
    assert research_programme.ROUTE_PATH in paths
    assert independent.ROUTE_PATH in paths
    assert service.registry.resolve_primary().logical_model_id == school_host.EXPECTED_MODEL_ID


@pytest.mark.parametrize(
    "forbidden_field,value",
    [
        ("assessment_id", "ASSESS_forged"),
        ("subject_id", "SUBJ_forged"),
        ("conversation_id", "CONV_forged"),
        ("turn_id", "TURN_forged"),
        ("target_role", "student"),
        ("purpose", "education_support"),
        ("production_use", True),
        ("publication_eligible", True),
        ("logical_model_id", "other-model"),
        ("provider_model_id", "remote-model"),
    ],
)
def test_research_programme_route_rejects_student_scope_and_policy_overrides(
    runtime_client, forbidden_field: str, value: Any
) -> None:
    client, _service, provider, _app = runtime_client
    payload = _request_payload()
    payload[forbidden_field] = value

    response = client.post(research_programme.ROUTE_PATH, json=payload)

    assert response.status_code == 422
    assert provider.generate_calls == 0


def test_research_programme_route_rejects_invalid_manifest_chunks_and_nested_fields(
    runtime_client,
) -> None:
    client, _service, provider, _app = runtime_client
    invalid_manifest = _request_payload()
    invalid_manifest["source_manifest_sha256"] = "A" * 64
    no_chunks = _request_payload()
    no_chunks["chunk_ids"] = []
    duplicate_chunks = _request_payload()
    duplicate_chunks["chunk_ids"] = ["CHUNK_public_001", "CHUNK_public_001"]
    nested_override = _request_payload()
    nested_override["config"]["fallback_model_id"] = "remote-model"
    bad_prompt = _request_payload()
    bad_prompt["prompt_ref"]["model_id"] = school_host.EXPECTED_CONTRACT_MODEL_ID

    for payload in (invalid_manifest, no_chunks, duplicate_chunks, nested_override, bad_prompt):
        assert client.post(research_programme.ROUTE_PATH, json=payload).status_code == 422
    assert provider.generate_calls == 0


@pytest.mark.parametrize("mutation", ["default_model", "attempt_count", "cloud_fallback", "digest"])
def test_research_programme_route_fails_closed_on_runtime_registry_changes(
    runtime_client, mutation: str
) -> None:
    client, service, provider, _app = runtime_client
    if mutation == "default_model":
        service.default_model_id = "different-model"
    elif mutation == "attempt_count":
        service.max_attempts = 2
    elif mutation == "cloud_fallback":
        service.registry.cloud_fallback = True
    else:
        entry = service.registry.resolve_primary()
        service.registry.update(replace(entry, digest="b" * 64))

    response = client.post(research_programme.ROUTE_PATH, json=_request_payload())

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "SCHOOL_RUNTIME_CONFIGURATION_INVALID"
    assert provider.generate_calls == 0


def test_research_programme_route_rejects_mismatched_runtime_result_identity(
    runtime_client,
) -> None:
    client, service, provider, _app = runtime_client
    model = service.registry.resolve_primary()
    trace = SimpleNamespace(
        to_dict=lambda: {"request_id": "REQ_wrong", "trace_id": "TRACE_programme_001"}
    )
    service.generate = lambda _request: SimpleNamespace(
        status="success",
        request_id="REQ_wrong",
        trace_id="TRACE_programme_001",
        actual_model_id=model.logical_model_id,
        executed_model=model,
        fallback_used=False,
        attempts=(object(),),
        text="candidate",
        trace=trace,
    )

    response = client.post(research_programme.ROUTE_PATH, json=_request_payload())

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "RESEARCH_PROGRAMME_RESULT_SCOPE_MISMATCH"
    assert provider.generate_calls == 0
