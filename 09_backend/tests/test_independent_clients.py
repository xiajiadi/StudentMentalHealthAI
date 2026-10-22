from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from smhai_backend.core.config import (
    LLMModuleClientSettings,
    ModuleClientSettings,
    TimeoutSettings,
)
from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.core.request_context import RequestContext
from smhai_backend.integrations.independent import (
    _LLM_BASE_URL,
    _RAG_BASE_URL,
    LLM_ROUTE,
    RAG_ROUTE,
    GenerationResult,
    IndependentLLMRuntimeClient,
    IndependentRagClient,
)
from smhai_backend.integrations.rag import RetrievalResult

CONTEXT = RequestContext(request_id="REQ_demo_01", trace_id="TRACE_demo_01")


def _chunk() -> dict[str, Any]:
    return {
        "schema_version": "knowledge.v1",
        "chunk_id": "CHUNK_demo_01",
        "document_id": "KB_demo_01",
        "text": "Approved synthetic educational support information.",
        "content_type": "approved_summary",
        "location": {"section": "support", "page_start": None, "page_end": None},
        "citation": {
            "title": "Synthetic support source",
            "organization": "StudentMentalHealthAI",
            "locator": "fixture://synthetic/support",
        },
        "population_scope": ["university_student"],
        "role_scope": ["student"],
        "risk_scope": ["normal"],
        "review_status": "approved",
        "rights_status": "verified",
        "content_hash": "sha256:" + "a" * 64,
        "embedding": {"model_id": None, "model_version": "synthetic", "status": "not_indexed"},
    }


def _rag_response(**overrides: Any) -> dict[str, Any]:
    trace = {
        "request_id": CONTEXT.request_id,
        "trace_id": CONTEXT.trace_id,
        "raw_query": "How can I find study support?",
        "index_id": "INDEX_demo",
        "index_version": "1",
    }
    data = {
        "retrieval_id": "RETR_demo_01",
        "chunks": [_chunk()],
        "citations": {},
        "trace": trace,
        "plan": {},
    }
    response = {"request_id": CONTEXT.request_id, "trace_id": CONTEXT.trace_id, "data": data}
    for key, value in overrides.items():
        if key == "data":
            response["data"].update(value)
        else:
            response[key] = value
    return response


def _runtime_attempt(**overrides: Any) -> dict[str, Any]:
    attempt = {
        "attempt_index": 1,
        "provider_id": "ollama",
        "logical_model_id": "qwen2.5-7b-instruct-school-demo",
        "provider_model_id": "qwen2.5:7b-instruct-q4_K_M",
        "started_at": "2026-10-12T01:00:00Z",
        "ended_at": "2026-10-12T01:00:01Z",
        "outcome": "success",
        "error_code": None,
        "fallback_reason": None,
        "retry": False,
    }
    attempt.update(overrides)
    return attempt


def _runtime_trace(attempt: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "request_id": CONTEXT.request_id,
        "trace_id": CONTEXT.trace_id,
        "provider": "ollama",
        "logical_model": "qwen2.5-7b-instruct-school-demo",
        "requested_model": "qwen2.5-7b-instruct-school-demo",
        "actual_model": "qwen2.5-7b-instruct-school-demo",
        "provider_model": "qwen2.5:7b-instruct-q4_K_M",
        "digest": "845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e",
        "retry_count": 0,
        "fallback_count": 0,
        "fallback_attempted": False,
        "attempts": [attempt or _runtime_attempt()],
    }


def _runtime_response(**overrides: Any) -> dict[str, Any]:
    trace = _runtime_trace()
    data = {
        "text": '{"summary":"A","observations":[],"suggestions":[],"disclaimer":"B"}',
        "model_id": "MODEL_local_primary",
        "logical_model_id": "qwen2.5-7b-instruct-school-demo",
        "model_version": "qwen2.5:7b-instruct-q4_K_M",
        "runtime_version": "0.33.3",
        "trace": trace,
        "buffered": True,
        "synthetic_fixture_only": True,
    }
    response = {
        "request_id": CONTEXT.request_id,
        "trace_id": CONTEXT.trace_id,
        "generation_id": "GEN_demo_01",
        "conversation_id": "CONV_demo_01",
        "turn_id": "TURN_demo_01",
        "data": data,
    }
    for key, value in overrides.items():
        if key == "data":
            response["data"].update(value)
        else:
            response[key] = value
    return response


def _deepseek_runtime_response(**overrides: Any) -> dict[str, Any]:
    logical_model_id = "deepseek-flash-education-support"
    contract_model_id = "MODEL_deepseek_flash_education_support"
    provider_model_id = "deepseek-flash"
    attempt = _runtime_attempt(
        provider_id="deepseek",
        logical_model_id=logical_model_id,
        provider_model_id=provider_model_id,
    )
    trace = _runtime_trace(attempt)
    trace.update(
        {
            "provider": "deepseek",
            "logical_model": logical_model_id,
            "requested_model": logical_model_id,
            "actual_model": logical_model_id,
            "provider_model": provider_model_id,
            "digest": None,
        }
    )
    response = _runtime_response(
        data={
            "model_id": contract_model_id,
            "logical_model_id": logical_model_id,
            "model_version": provider_model_id,
            "trace": trace,
            "synthetic_fixture_only": False,
        }
    )
    for key, value in overrides.items():
        if key == "data":
            response["data"].update(value)
        else:
            response[key] = value
    return response


def _fake_http(
    client: IndependentRagClient | IndependentLLMRuntimeClient,
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[list[httpx.Request], httpx.AsyncClient]:
    requests: list[httpx.Request] = []

    def capture(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    client.client = httpx.AsyncClient(
        transport=httpx.MockTransport(capture),
        base_url=client.settings.base_url,
    )
    return requests, client.client


def _json(response: dict[str, Any], status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=response)


def _llm_args() -> dict[str, Any]:
    return {
        "context": CONTEXT,
        "generation_id": "GEN_demo_01",
        "conversation_id": "CONV_demo_01",
        "turn_id": "TURN_demo_01",
        "retrieval_id": "RETR_demo_01",
        "chunk_ids": ["CHUNK_demo_01"],
        "prompt_id": "PROMPT_support_v1",
        "prompt_version": "1.0.0",
        "messages": [
            {"role": "system", "content": "Respond using only the supplied evidence."},
            {"role": "user", "content": "How can I find study support?"},
        ],
        "structured_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["summary", "observations", "suggestions", "disclaimer"],
            "properties": {
                "summary": {"type": "string"},
                "observations": {"type": "array", "items": {"type": "string"}},
                "suggestions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["text", "source_chunk_ids"],
                        "properties": {
                            "text": {"type": "string"},
                            "source_chunk_ids": {"type": "array", "minItems": 1},
                        },
                    },
                },
                "disclaimer": {"type": "string"},
            },
        },
    }


def _client_settings(base_url: str) -> ModuleClientSettings:
    return ModuleClientSettings(mode="http", base_url=base_url, timeout=TimeoutSettings(read=65.0))


_TEST_RUNTIME_TOKEN = "synthetic_runtime_token_" + "x" * 32


def _deepseek_client_settings() -> LLMModuleClientSettings:
    return LLMModuleClientSettings(
        mode="http",
        base_url=_LLM_BASE_URL,
        internal_auth_token=_TEST_RUNTIME_TOKEN,
        logical_model_id="deepseek-flash-education-support",
        timeout=TimeoutSettings(read=65.0),
    )


@pytest.mark.parametrize(
    ("client_type", "allowed_url"),
    [
        (IndependentRagClient, _RAG_BASE_URL),
        (IndependentLLMRuntimeClient, _LLM_BASE_URL),
    ],
)
@pytest.mark.parametrize(
    "invalid_url",
    [
        "http://example.com:8170",
        "http://127.0.0.1:8171",
        "https://127.0.0.1:8170",
        "http://user@127.0.0.1:8170",
        "http://127.0.0.1:8170/internal",
        "http://127.0.0.1:8170?route=elsewhere",
        "http://127.0.0.1:8170#fragment",
    ],
)
def test_independent_client_rejects_non_allowlisted_destination_before_transport(
    client_type, allowed_url, invalid_url, monkeypatch
):
    assert invalid_url != allowed_url
    initialized = []

    def record_transport_initialization(self, settings):
        initialized.append(settings.base_url)

    monkeypatch.setattr(
        "smhai_backend.integrations.independent.LongLivedHttpClient.__init__",
        record_transport_initialization,
    )
    with pytest.raises(ValueError):
        client_type(_client_settings(invalid_url))
    assert initialized == []


@pytest.mark.parametrize("read_timeout", [8.0, 60.0, 64.999])
def test_independent_llm_client_rejects_short_http_read_timeout_before_transport(
    read_timeout, monkeypatch
):
    initialized = []

    def record_transport_initialization(self, settings):
        initialized.append(settings.base_url)

    monkeypatch.setattr(
        "smhai_backend.integrations.independent.LongLivedHttpClient.__init__",
        record_transport_initialization,
    )
    settings = ModuleClientSettings(
        mode="http",
        base_url=_LLM_BASE_URL,
        timeout=TimeoutSettings(read=read_timeout),
    )
    with pytest.raises(ValueError, match="read timeout must be at least 65"):
        IndependentLLMRuntimeClient(settings)
    assert initialized == []


@pytest.mark.asyncio
async def test_independent_rag_posts_assessment_free_body_and_sanitizes_trace():
    client = IndependentRagClient(_client_settings(_RAG_BASE_URL))
    requests, http_client = _fake_http(client, lambda request: _json(_rag_response()))
    try:
        result = await client.retrieve(
            query="How can I find study support?",
            target_population="university_student",
            top_k=5,
            retrieval_id="RETR_demo_01",
            context=CONTEXT,
        )
    finally:
        await http_client.aclose()

    assert isinstance(result, RetrievalResult)
    assert result.retrieval_id == "RETR_demo_01"
    assert result.chunks[0].chunk_id == "CHUNK_demo_01"
    assert "raw_query" not in result.trace
    assert len(requests) == 1
    assert requests[0].url.path == RAG_ROUTE
    assert requests[0].headers["X-Request-ID"] == CONTEXT.request_id
    assert requests[0].headers["X-Trace-ID"] == CONTEXT.trace_id
    body = __import__("json").loads(requests[0].content)
    assert body == {
        "query": "How can I find study support?",
        "target_population": "university_student",
        "top_k": 5,
        "retrieval_id": "RETR_demo_01",
    }
    assert not {"assessment_id", "assessment", "subject_id", "role", "model", "provider"} & set(
        body
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        _rag_response(request_id="REQ_wrong"),
        _rag_response(data={"retrieval_id": "RETR_wrong"}),
        _rag_response(
            data={
                "trace": {
                    "request_id": "REQ_wrong",
                    "trace_id": CONTEXT.trace_id,
                    "raw_query": "How can I find study support?",
                }
            }
        ),
        _rag_response(data={"unexpected": True}),
    ],
)
async def test_independent_rag_rejects_unexpected_or_mismatched_response(response):
    client = IndependentRagClient(_client_settings(_RAG_BASE_URL))
    requests, http_client = _fake_http(client, lambda request: _json(response))
    try:
        with pytest.raises(BackendError) as caught:
            await client.retrieve(
                query="How can I find study support?",
                target_population="university_student",
                top_k=5,
                retrieval_id="RETR_demo_01",
                context=CONTEXT,
            )
    finally:
        await http_client.aclose()
    assert caught.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [422, 503])
async def test_independent_rag_http_failure_is_single_attempt(status_code):
    client = IndependentRagClient(_client_settings(_RAG_BASE_URL))
    requests, http_client = _fake_http(
        client,
        lambda request: httpx.Response(status_code, json={"detail": "synthetic failure"}),
    )
    try:
        with pytest.raises(BackendError) as caught:
            await client.retrieve(
                query="How can I find study support?",
                target_population="university_student",
                top_k=5,
                retrieval_id="RETR_demo_01",
                context=CONTEXT,
            )
    finally:
        await http_client.aclose()
    assert len(requests) == 1
    assert caught.value.code is (
        ErrorCode.DEPENDENCY_UNAVAILABLE
        if status_code == 503
        else ErrorCode.DEPENDENCY_INVALID_RESPONSE
    )


@pytest.mark.asyncio
async def test_independent_llm_posts_fixed_server_identity_and_returns_strict_result():
    client = IndependentLLMRuntimeClient(_client_settings(_LLM_BASE_URL))
    requests, http_client = _fake_http(client, lambda request: _json(_runtime_response()))
    try:
        result = await client.generate(**_llm_args())
    finally:
        await http_client.aclose()

    assert isinstance(result, GenerationResult)
    assert result.generation_id == "GEN_demo_01"
    assert result.conversation_id == "CONV_demo_01"
    assert result.turn_id == "TURN_demo_01"
    assert result.model_id == "MODEL_local_primary"
    assert result.logical_model_id == "qwen2.5-7b-instruct-school-demo"
    assert result.trace["attempt_count"] == 1
    assert len(requests) == 1
    assert requests[0].url.path == LLM_ROUTE
    body = __import__("json").loads(requests[0].content)
    assert set(body) == {
        "request_id",
        "trace_id",
        "generation_id",
        "conversation_id",
        "turn_id",
        "retrieval_id",
        "chunk_ids",
        "prompt_ref",
        "messages",
        "structured_schema",
        "config",
    }
    assert not {"assessment_id", "assessment", "subject_id", "role", "model", "provider"} & set(
        body
    )
    assert body["config"] == {
        "max_output_tokens": 768,
        "temperature": 0.1,
        "top_p": 0.9,
        "context_length": 8192,
        "timeout_seconds": 60.0,
    }
    assert body["request_id"] == CONTEXT.request_id
    assert body["trace_id"] == CONTEXT.trace_id


@pytest.mark.asyncio
async def test_independent_llm_uses_configured_deepseek_identity_without_fallback():
    client = IndependentLLMRuntimeClient(_deepseek_client_settings())
    requests, http_client = _fake_http(
        client, lambda request: _json(_deepseek_runtime_response())
    )
    try:
        result = await client.generate(**_llm_args())
    finally:
        await http_client.aclose()

    assert result.model_id == "MODEL_deepseek_flash_education_support"
    assert result.logical_model_id == "deepseek-flash-education-support"
    assert result.synthetic_fixture_only is False
    assert result.trace["provider"] == "deepseek"
    assert result.trace["provider_model"] == "deepseek-flash"
    assert result.trace["digest"] is None
    assert result.trace["fallback_attempted"] is False
    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == f"Bearer {_TEST_RUNTIME_TOKEN}"


def test_independent_llm_rejects_unallowlisted_configured_model_before_transport():
    settings = LLMModuleClientSettings(
        mode="http",
        base_url=_LLM_BASE_URL,
        logical_model_id="unregistered-school-model",
        timeout=TimeoutSettings(read=65.0),
    )
    with pytest.raises(ValueError, match="model identity is not allowlisted"):
        IndependentLLMRuntimeClient(settings)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        _runtime_response(request_id="REQ_wrong"),
        _runtime_response(trace_id="TRACE_wrong"),
        _runtime_response(generation_id="GEN_wrong"),
        _runtime_response(conversation_id="CONV_wrong"),
        _runtime_response(turn_id="TURN_wrong"),
        _runtime_response(
            data={
                "trace": {
                    "request_id": CONTEXT.request_id,
                    "trace_id": CONTEXT.trace_id,
                    "requested_model": "wrong",
                }
            }
        ),
        _runtime_response(data={"unexpected": "field"}),
        _runtime_response(data={"trace": {**_runtime_trace(), "retry_count": 1}}),
        _runtime_response(data={"trace": _runtime_trace(_runtime_attempt(provider_id="other"))}),
        _runtime_response(
            data={"trace": _runtime_trace(_runtime_attempt(logical_model_id="other"))}
        ),
        _runtime_response(
            data={"trace": _runtime_trace(_runtime_attempt(provider_model_id="other"))}
        ),
        _runtime_response(data={"trace": _runtime_trace(_runtime_attempt(outcome="error"))}),
        _runtime_response(data={"trace": _runtime_trace(_runtime_attempt(retry=True))}),
        _runtime_response(data={"trace": _runtime_trace(_runtime_attempt(unexpected="field"))}),
    ],
)
async def test_independent_llm_rejects_unexpected_or_mismatched_response(response):
    client = IndependentLLMRuntimeClient(_client_settings(_LLM_BASE_URL))
    requests, http_client = _fake_http(client, lambda request: _json(response))
    try:
        with pytest.raises(BackendError) as caught:
            await client.generate(**_llm_args())
    finally:
        await http_client.aclose()
    assert caught.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_independent_llm_rejects_wrong_deepseek_attempt_identity():
    client = IndependentLLMRuntimeClient(_deepseek_client_settings())
    response = _deepseek_runtime_response(
        data={"trace": _runtime_trace(_runtime_attempt(provider_id="ollama"))}
    )
    requests, http_client = _fake_http(client, lambda request: _json(response))
    try:
        with pytest.raises(BackendError) as caught:
            await client.generate(**_llm_args())
    finally:
        await http_client.aclose()
    assert caught.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [422, 503])
async def test_independent_llm_http_failure_is_single_attempt_without_fallback(status_code):
    client = IndependentLLMRuntimeClient(_client_settings(_LLM_BASE_URL))
    requests, http_client = _fake_http(
        client,
        lambda request: httpx.Response(status_code, json={"detail": "synthetic failure"}),
    )
    try:
        with pytest.raises(BackendError) as caught:
            await client.generate(**_llm_args())
    finally:
        await http_client.aclose()

    assert len(requests) == 1
    if status_code == 503:
        assert caught.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE
        assert caught.value.retryable is True
    else:
        assert caught.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE
        assert caught.value.retryable is False
