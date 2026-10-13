from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx
import pytest

from smhai_backend.domains.school_research.client import (
    WIRE_SCHEMA,
    ResearchCATClientError,
    ResearchCATHttpClient,
    ResearchCATSessionState,
)

BASE_URL = "http://127.0.0.1:8182"
TOKEN = b"synthetic-private-research-token-length-is-valid"
BINDING = "promis-ped-anx-r1"
PROFILE_SHA = "a" * 64
CONFIG_SHA = "b" * 64


def _client(transport: httpx.AsyncBaseTransport, **overrides: Any) -> ResearchCATHttpClient:
    settings: dict[str, Any] = {
        "base_url": BASE_URL,
        "service_bearer_token": TOKEN,
        "binding_ref": BINDING,
        "expected_profile_sha256": PROFILE_SHA,
        "expected_config_sha256": CONFIG_SHA,
        "timeout": 2.5,
        "transport": transport,
    }
    settings.update(overrides)
    return ResearchCATHttpClient(**settings)


def _response(
    *, answered: int = 0, completed: bool = False, signature: str = "c" * 64,
    **overrides: Any,
) -> dict[str, Any]:
    status = "COMPLETED" if completed else "ACTIVE"
    question = None if completed else {
        "item_id": f"ITEM_{answered + 1}",
        "qid": f"Q{answered + 1}",
        "stem": "Synthetic study-support item",
        "step": answered,
        "response_options": [
            {"value": 0, "label": "Never"},
            {"value": 1, "label": "Sometimes"},
            {"value": 2, "label": "Often"},
        ],
    }
    stop_reason = "max_items_reached" if completed else None
    payload = {
        "schema": "psynova.research-cat-snapshot.v1",
        "session_id": "SESSION_demo_01",
        "profile_id": "PROFILE_demo_01",
        "profile_sha256": PROFILE_SHA,
        "config_version": "research-test-v1",
        "config_sha256": CONFIG_SHA,
        "step": answered,
        "status": status,
        "stop_reason": stop_reason,
        "pending_item_id": None if completed else question["item_id"],
        "answers": [
            {"item_id": f"ITEM_{index + 1}", "raw_value": index % 3}
            for index in range(answered)
        ],
    }
    payload_hash = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    completion = (
        {
            "status": "COMPLETED",
            "items_administered": answered,
            "items_answered": answered,
            "stop_reason": stop_reason,
        }
        if completed
        else None
    )
    response = {
        "schema": WIRE_SCHEMA,
        "binding_ref": BINDING,
        "session_ref": "SESSION_demo_01",
        "profile_id": "PROFILE_demo_01",
        "profile_sha256": PROFILE_SHA,
        "config_sha256": CONFIG_SHA,
        "research_only": True,
        "human_curated": False,
        "publication_status": "not_approved",
        "psychological_interpretation_allowed": False,
        "status": status,
        "items_answered": answered,
        "signed_snapshot": {
            "payload": payload,
            "payload_sha256": payload_hash,
            "signature": signature,
        },
        "question": question,
        "completion": completion,
    }
    response.update(overrides)
    return response


@pytest.mark.asyncio
async def test_start_answer_resume_and_completion_keep_signed_state_private() -> None:
    requests: list[httpx.Request] = []
    response_index = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal response_index
        requests.append(request)
        assert request.headers["authorization"] == f"Bearer {TOKEN.decode('ascii')}"
        assert "cookie" not in request.headers
        body = json.loads(request.content)
        assert body["schema"] == WIRE_SCHEMA
        if request.url.path == "/v1/sessions/start":
            response = _response()
        elif request.url.path == "/v1/sessions/resume":
            assert body["signed_snapshot"]["payload"]["session_id"] == "SESSION_demo_01"
            response = _response()
        else:
            assert request.url.path == "/v1/sessions/answer"
            assert body["item_id"] == "ITEM_1"
            assert body["raw_value"] == 1
            response = _response(answered=1)
        response_index += 1
        return httpx.Response(200, json=response)

    client = _client(httpx.MockTransport(handler))
    try:
        started = await client.start()
        assert started.status == "ACTIVE"
        assert started.question is not None and started.question.item_id == "ITEM_1"
        assert isinstance(started, ResearchCATSessionState)
        assert "raw_value" not in repr(started)
        assert "signature" not in repr(started)

        resumed = await client.resume(started)
        advanced = await client.answer(resumed, item_id="ITEM_1", raw_value=1)
        assert advanced.items_answered == 1
        assert advanced.question is not None and advanced.question.item_id == "ITEM_2"
        assert response_index == 3
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_answer_validates_current_ordinal_without_network_call() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response())

    client = _client(httpx.MockTransport(handler))
    try:
        state = await client.start()
        with pytest.raises(ResearchCATClientError, match="answer_invalid"):
            await client.answer(state, item_id="ITEM_1", raw_value=True)  # type: ignore[arg-type]
        with pytest.raises(ResearchCATClientError, match="answer_invalid"):
            await client.answer(state, item_id="wrong-item", raw_value=1)
        with pytest.raises(ResearchCATClientError, match="answer_invalid"):
            await client.answer(state, item_id="ITEM_1", raw_value=9)
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "base_url",
    [
        "https://127.0.0.1:8182",
        "http://localhost:8182",
        "http://example.test:8182",
        "http://user:secret@127.0.0.1:8182",
        "http://127.0.0.1:8182/path",
        "http://127.0.0.1:8182/?token=x",
        "http://127.0.0.1:8182/#fragment",
        "http://127.0.0.1:99999",
    ],
)
def test_client_rejects_noncanonical_or_nonloopback_urls(base_url: str) -> None:
    with pytest.raises(ResearchCATClientError):
        _client(httpx.MockTransport(lambda _request: httpx.Response(200)), base_url=base_url)


@pytest.mark.parametrize(
    "settings",
    [
        {"service_bearer_token": "a" * 40},
        {"service_bearer_token": b"short"},
        {"service_bearer_token": b"a" * 31},
        {"service_bearer_token": b"a" * 32 + b" "},
        {"service_bearer_token": b"a" * 32 + b"\xff"},
        {"binding_ref": "bad ref"},
        {"expected_profile_sha256": "A" * 64},
        {"expected_config_sha256": "b" * 63},
        {"timeout": True},
        {"timeout": float("inf")},
    ],
)
def test_client_rejects_invalid_pinned_settings(settings: dict[str, Any]) -> None:
    with pytest.raises(ResearchCATClientError):
        _client(httpx.MockTransport(lambda _request: httpx.Response(200)), **settings)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (lambda data: data.update(unexpected=True), "response_schema_invalid"),
        (lambda data: data.update(binding_ref="other-binding"), "response_binding_invalid"),
        (lambda data: data.update(profile_sha256="d" * 64), "response_binding_invalid"),
        (lambda data: data.update(config_sha256="d" * 64), "response_binding_invalid"),
        (lambda data: data.update(research_only=False), "response_binding_invalid"),
        (lambda data: data.update(human_curated=True), "response_binding_invalid"),
        (
            lambda data: data.update(psychological_interpretation_allowed=True),
            "response_binding_invalid",
        ),
        (lambda data: data.update(status="READY"), "response_binding_invalid"),
        (lambda data: data.update(theta=0.2), "response_schema_invalid"),
        (lambda data: data["signed_snapshot"].update(signature="bad"), "response_snapshot_invalid"),
        (
            lambda data: data["signed_snapshot"].update(signature="rk1.bad.version." + "a" * 64),
            "response_snapshot_invalid",
        ),
        (lambda data: data.update(question=[]), "response_question_invalid"),
        (lambda data: data.update(completion=[]), "response_completion_invalid"),
        (
            lambda data: data["signed_snapshot"].update(payload_sha256="0" * 64),
            "response_snapshot_invalid",
        ),
        (
            lambda data: data["signed_snapshot"]["payload"].update(raw_score=7),
            "response_snapshot_invalid",
        ),
        (
            lambda data: data["signed_snapshot"]["payload"].update(profile_sha256="d" * 64),
            "response_snapshot_invalid",
        ),
        (
            lambda data: data["signed_snapshot"]["payload"].update(session_id="other-session"),
            "response_snapshot_invalid",
        ),
        (
            lambda data: data["signed_snapshot"]["payload"].update(pending_item_id="OTHER_ITEM"),
            "response_snapshot_invalid",
        ),
        (
            lambda data: data["signed_snapshot"]["payload"].update(answers=[None]),
            "response_snapshot_invalid",
        ),
        (
            lambda data: data["signed_snapshot"]["payload"].update(
                answers=[{"item_id": "ITEM_1", "raw_value": True}]
            ),
            "response_snapshot_invalid",
        ),
        (
            lambda data: data["question"].update(extra="not allowed"),
            "response_question_invalid",
        ),
        (
            lambda data: data["question"].update(step=True),
            "response_question_invalid",
        ),
        (
            lambda data: data["question"]["response_options"][0].update(value=True),
            "response_question_invalid",
        ),
    ],
)
async def test_client_rejects_untrusted_or_unknown_response_data(mutation, expected_code) -> None:
    response = _response()
    mutation(response)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response)

    client = _client(httpx.MockTransport(handler))
    try:
        with pytest.raises(ResearchCATClientError, match=expected_code):
            await client.start()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_client_rejects_completed_response_with_score_fields() -> None:
    response = _response(
        answered=1,
        completed=True,
        completion={
            "status": "COMPLETED",
            "items_administered": 1,
            "items_answered": 1,
            "stop_reason": "max_items_reached",
            "score": 12,
        },
    )

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response)

    client = _client(httpx.MockTransport(handler))
    try:
        with pytest.raises(ResearchCATClientError, match="response_completion_invalid"):
            await client.start()
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "signature",
    ["rk1.v1." + "d" * 64, "rk1.future-key_2." + "e" * 64],
)
async def test_client_accepts_bounded_versioned_snapshot_signature_shape(signature: str) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(signature=signature))

    client = _client(httpx.MockTransport(handler))
    try:
        state = await client.start()
        assert state.status == "ACTIVE"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_completed_projection_has_only_safe_completion_metadata() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/start"):
            return httpx.Response(200, json=_response())
        return httpx.Response(200, json=_response(answered=1, completed=True))

    client = _client(httpx.MockTransport(handler))
    try:
        started = await client.start()
        state = await client.answer(started, item_id="ITEM_1", raw_value=1)
        assert state.status == "COMPLETED"
        assert state.question is None
        assert state.completion is not None
        assert state.completion.items_answered == 1
        assert state.completion.stop_reason == "max_items_reached"
        assert not hasattr(state.completion, "theta")
        assert not hasattr(state.completion, "score")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_duplicate_json_key_and_upstream_error_are_sanitized_single_attempt() -> None:
    requests: list[httpx.Request] = []

    async def duplicate_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            content=b'{"schema":"psynova.research-http.v1","schema":"bad"}',
            headers={"content-type": "application/json"},
        )

    client = _client(httpx.MockTransport(duplicate_handler))
    try:
        with pytest.raises(ResearchCATClientError, match="response_invalid") as exc_info:
            await client.start()
        assert "bad" not in str(exc_info.value)
        assert len(requests) == 1
    finally:
        await client.aclose()

    private = "SENSITIVE_BODY_SENTINEL"

    async def error_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(503, json={"detail": private})

    client = _client(httpx.MockTransport(error_handler))
    try:
        with pytest.raises(ResearchCATClientError, match="upstream_rejected") as exc_info:
            await client.start()
        assert private not in str(exc_info.value)
        assert exc_info.value.status_code == 503
        assert len(requests) == 2
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_client_does_not_follow_redirects() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(307, headers={"location": "http://192.0.2.1/steal"})

    client = _client(httpx.MockTransport(handler))
    try:
        with pytest.raises(ResearchCATClientError, match="upstream_rejected"):
            await client.start()
        assert len(requests) == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_timeout_is_sanitized_and_not_retried() -> None:
    attempts = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("PRIVATE_TRANSPORT_DETAIL")

    client = _client(httpx.MockTransport(handler))
    try:
        with pytest.raises(ResearchCATClientError, match="dependency_timeout") as exc_info:
            await client.start()
        assert "PRIVATE_TRANSPORT_DETAIL" not in str(exc_info.value)
        assert attempts == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_response_size_is_bounded() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b" " * (1_048_576 + 1),
            headers={"content-type": "application/json"},
        )

    client = _client(httpx.MockTransport(handler))
    try:
        with pytest.raises(ResearchCATClientError, match="response_invalid"):
            await client.start()
    finally:
        await client.aclose()


def _rehash_snapshot(response: dict[str, Any]) -> None:
    payload = response["signed_snapshot"]["payload"]
    response["signed_snapshot"]["payload_sha256"] = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


@pytest.mark.asyncio
async def test_start_requires_new_active_zero_answer_session() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(answered=1))

    client = _client(httpx.MockTransport(handler))
    try:
        with pytest.raises(ResearchCATClientError, match="response_operation_invalid"):
            await client.start()
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["switch-session", "advance-state"])
async def test_resume_rejects_coherently_valid_but_unexpected_session_progress(mode: str) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/start"):
            return httpx.Response(200, json=_response())
        if mode == "advance-state":
            return httpx.Response(200, json=_response(answered=1))
        response = _response()
        response["session_ref"] = "SESSION_other_02"
        response["signed_snapshot"]["payload"]["session_id"] = "SESSION_other_02"
        _rehash_snapshot(response)
        return httpx.Response(200, json=response)

    client = _client(httpx.MockTransport(handler))
    try:
        state = await client.start()
        with pytest.raises(ResearchCATClientError, match="response_operation_invalid"):
            await client.resume(state)
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["switch-session", "skip-progress"])
async def test_answer_rejects_coherently_valid_but_unexpected_session_transition(mode: str) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/start"):
            return httpx.Response(200, json=_response())
        response = _response(answered=2 if mode == "skip-progress" else 1)
        if mode == "switch-session":
            response["session_ref"] = "SESSION_other_02"
            response["signed_snapshot"]["payload"]["session_id"] = "SESSION_other_02"
            _rehash_snapshot(response)
        return httpx.Response(200, json=response)

    client = _client(httpx.MockTransport(handler))
    try:
        state = await client.start()
        with pytest.raises(ResearchCATClientError, match="response_operation_invalid"):
            await client.answer(state, item_id="ITEM_1", raw_value=1)
    finally:
        await client.aclose()
