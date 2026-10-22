from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from llm_runtime.domain.models import GenerationConfig, GenerationRequest
from llm_runtime.errors import LLMRuntimeError, RuntimeErrorCode
from llm_runtime.providers.deepseek import DeepSeekProvider

_TEST_KEY = "sk-" + "a" * 32


def _request(*, structured_schema=None, roles=("system", "user")) -> GenerationRequest:
    return GenerationRequest(
        request_id="REQ_deepseek_001",
        trace_id="TRACE_deepseek_001",
        generation_id="GEN_deepseek_001",
        assessment_id="ASSESS_synthetic_001",
        subject_id="SUBJ_synthetic_001",
        target_role="student",
        purpose="education_support",
        language="en",
        safety_mode="standard",
        retrieval_id="RETR_synthetic_001",
        chunk_ids=("CHUNK_synthetic_001",),
        prompt_id="PROMPT_synthetic_v1",
        prompt_version="1",
        contract_model_id="MODEL_deepseek_flash_education_support",
        logical_model_id="deepseek-flash-education-support",
        messages=tuple(
            {"role": role, "content": "Synthetic integration check."}
            for role in roles
        ),
        provider_model_id="deepseek-flash",
        structured_schema=structured_schema,
        config=GenerationConfig(max_output_tokens=24, temperature=0.0),
        metadata={"private_trace_marker": "must-not-be-forwarded"},
    )


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_generate_sends_only_messages_and_bounded_generation_settings():
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["authorization"] = request.headers["Authorization"]
        observed["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "completion-synthetic",
                "model": "deepseek-flash",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Synthetic reply."},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11},
            },
        )

    provider = DeepSeekProvider(_TEST_KEY, transport=_transport(handler))
    try:
        result = provider.generate(_request())
    finally:
        provider.close()

    body = observed["body"]
    assert observed["url"] == "https://api.deepseek.com/chat/completions"
    assert observed["authorization"] == f"Bearer {_TEST_KEY}"
    assert isinstance(body, dict)
    assert body["model"] == "deepseek-flash"
    assert body["max_tokens"] == 24
    assert body["stream"] is False
    assert body["thinking"] == {"type": "disabled"}
    assert body["messages"] == [
        {"role": "system", "content": "Synthetic integration check."},
        {"role": "user", "content": "Synthetic integration check."},
    ]
    assert "SUBJ_synthetic_001" not in json.dumps(body)
    assert "private_trace_marker" not in json.dumps(body)
    assert result.text == "Synthetic reply."
    assert result.usage.total_tokens == 11
    assert result.provider_model == "deepseek-flash"


def test_structured_output_uses_json_mode_and_local_schema_validation():
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "deepseek-flash",
                "choices": [
                    {
                        "message": {"content": '{"answer":"safe synthetic result"}'},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    schema = {
        "type": "object",
        "required": ["answer"],
        "properties": {"answer": {"type": "string"}},
        "additionalProperties": False,
    }
    provider = DeepSeekProvider(_TEST_KEY, transport=_transport(handler))
    try:
        result = provider.generate(_request(structured_schema=schema))
    finally:
        provider.close()

    body = observed["body"]
    assert isinstance(body, dict)
    assert body["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in body["messages"][0]["content"]
    assert result.structured == {"answer": "safe synthetic result"}


def test_provider_errors_do_not_expose_response_body_or_retry():
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, text="Authorization: Bearer private-error-body")

    provider = DeepSeekProvider(_TEST_KEY, transport=_transport(handler))
    try:
        with pytest.raises(LLMRuntimeError) as caught:
            provider.generate(_request())
    finally:
        provider.close()

    assert calls == 1
    assert caught.value.code is RuntimeErrorCode.CONFIGURATION_ERROR
    assert "private-error-body" not in str(caught.value)
    assert "Authorization" not in str(caught.value)


def test_timeout_is_not_retried_to_avoid_duplicate_paid_requests():
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("synthetic timeout")

    provider = DeepSeekProvider(_TEST_KEY, transport=_transport(handler))
    try:
        with pytest.raises(LLMRuntimeError) as caught:
            provider.generate(_request())
    finally:
        provider.close()

    assert calls == 1
    assert caught.value.code is RuntimeErrorCode.REQUEST_TIMEOUT
    assert caught.value.retryable is False


def test_unsupported_roles_fail_before_network_call():
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    provider = DeepSeekProvider(_TEST_KEY, transport=_transport(handler))
    try:
        with pytest.raises(LLMRuntimeError) as caught:
            provider.generate(_request(roles=("tool",)))
    finally:
        provider.close()

    assert calls == 0
    assert caught.value.code is RuntimeErrorCode.UNSUPPORTED_CAPABILITY


def test_system_credential_file_validation_is_fail_closed(tmp_path: Path):
    key_file = tmp_path / "credential"
    key_file.write_text(_TEST_KEY + "\n", encoding="ascii")
    provider = DeepSeekProvider.from_credential_file(key_file)
    assert "Authorization" not in repr(provider.runtime_info())
    provider.close()

    malformed = tmp_path / "malformed"
    malformed.write_text("not-a-deepseek-key", encoding="ascii")
    with pytest.raises(ValueError, match="malformed"):
        DeepSeekProvider.from_credential_file(malformed)

    with pytest.raises(ValueError, match="unavailable"):
        DeepSeekProvider.from_credential_file(tmp_path / "missing")
