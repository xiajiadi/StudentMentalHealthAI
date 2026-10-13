from __future__ import annotations

import hashlib
import hmac
import json
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from cat_engine.domain.config import CATConfig
from cat_engine.research import http_app, research_session
from cat_engine.research.http_app import (
    MAX_JSON_DEPTH,
    MAX_JSON_NODES,
    MAX_REQUEST_BODY_BYTES,
    WIRE_SCHEMA,
    ResearchCATBinding,
    create_research_http_app,
)
from cat_engine.research.research_session import ResearchCATProfile

PROFILE_PATH = Path(
    r"D:\Dev\datasets\psynova-public-research\research-profiles\promis-pediatric-anxiety-8-item-subset-20261014-r1\profile.json"
)
PROFILE_SHA256 = "a2720adf10496f495efe21262de0e1890650847a84aff770aa025e9da825acf3"
MANIFEST_SHA256 = "984d395c29c26c1ce728d97790abf99d583ef47518ee6e058e067c8e8c15f524"
SERVICE_TOKEN = b"private-test-service-token-at-least-32-bytes"
BINDING_REF = "promis-ped-anx-research-01"
SESSION_ROUTE = "/v1/sessions"


class _TestAuthenticator:
    def __init__(self) -> None:
        self._key = b"test-only-research-snapshot-signing-key"

    def sign(self, payload: bytes) -> str:
        return hmac.new(self._key, payload, hashlib.sha256).hexdigest()

    def verify(self, payload: bytes, signature: str) -> bool:
        return hmac.compare_digest(self.sign(payload), signature)


def _profile() -> ResearchCATProfile:
    if not PROFILE_PATH.is_file():
        pytest.skip("pinned public PROMIS profile is not mounted in this environment")
    return ResearchCATProfile.load(
        PROFILE_PATH,
        expected_file_sha256=PROFILE_SHA256,
        manifest_path=PROFILE_PATH.with_name("manifest.json"),
        expected_manifest_sha256=MANIFEST_SHA256,
    )


def _config(version: str = "research-http-v1-promis8") -> CATConfig:
    return CATConfig.from_dict(
        {
            "config_version": version,
            "model": "GRM",
            "estimator": "EAP",
            "selection_method": "MFI",
            "min_items": 8,
            "max_items": 8,
            "se_threshold": None,
            "initial_theta": 0.0,
            "prior_mean": 0.0,
            "prior_sd": 1.0,
            "optimization_interval": [-4.0, 4.0],
            "seed": 2026101417,
            "exposure_control": "none",
            "content_balancing": "none",
        }
    )


def _app(*, configs: tuple[CATConfig, ...] | None = None):
    profile = _profile()
    signer = _TestAuthenticator()
    selected_configs = configs or (_config(),)
    bindings = {
        BINDING_REF if index == 0 else f"{BINDING_REF}-alt-{index}": ResearchCATBinding(
            binding_ref=(BINDING_REF if index == 0 else f"{BINDING_REF}-alt-{index}"),
            profile=profile,
            config=config,
        )
        for index, config in enumerate(selected_configs)
    }
    app = create_research_http_app(
        bindings=bindings,
        authenticator=signer,
        service_bearer_token=SERVICE_TOKEN,
    )
    return app, signer


def _asgi_request(
    app,
    method: str,
    path: str,
    payload: object | None = None,
    *,
    token: bytes | None = SERVICE_TOKEN,
    cookie: str | None = None,
    raw_body: bytes | None = None,
    body_chunks: tuple[bytes, ...] | None = None,
    include_content_length: bool = True,
    content_length_value: int | None = None,
    receive_counter: list[int] | None = None,
) -> tuple[int, dict[str, object]]:
    if raw_body is None:
        raw_body = (
            b""
            if payload is None
            else json.dumps(payload, allow_nan=True).encode("utf-8")
        )
    chunks = body_chunks if body_chunks is not None else (raw_body,)
    headers = [(b"host", b"research-bridge.test")]
    if payload is not None or raw_body:
        headers.append((b"content-type", b"application/json"))
    if include_content_length and (payload is not None or raw_body):
        declared_length = (
            len(raw_body) if content_length_value is None else content_length_value
        )
        headers.append((b"content-length", str(declared_length).encode("ascii")))
    if token is not None:
        headers.append((b"authorization", b"Bearer " + token))
    if cookie is not None:
        headers.append((b"cookie", cookie.encode("ascii")))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 56000),
        "server": ("127.0.0.1", 8182),
    }
    chunk_index = 0
    response_start: dict[str, object] = {}
    response_chunks: list[bytes] = []

    async def receive():
        nonlocal chunk_index
        if receive_counter is not None:
            receive_counter.append(1)
        if chunk_index >= len(chunks):
            return {"type": "http.disconnect"}
        chunk = chunks[chunk_index]
        chunk_index += 1
        return {
            "type": "http.request",
            "body": chunk,
            "more_body": chunk_index < len(chunks),
        }

    async def send(message):
        if message["type"] == "http.response.start":
            response_start.update(message)
        elif message["type"] == "http.response.body":
            response_chunks.append(message.get("body", b""))

    import asyncio

    asyncio.run(app(scope, receive, send))
    content = b"".join(response_chunks)
    return int(response_start["status"]), json.loads(content) if content else {}


def _start(app) -> dict[str, object]:
    status, body = _asgi_request(
        app,
        "POST",
        f"{SESSION_ROUTE}/start",
        {"schema": WIRE_SCHEMA, "binding_ref": BINDING_REF},
    )
    assert status == 200
    return body


def _assert_no_sensitive_output(body: object) -> None:
    forbidden_keys = {
        "theta",
        "se",
        "score",
        "ability",
        "estimate",
        "participant_id",
        "participant_ref",
        "actor_id",
        "grant_id",
        "grants",
    }

    def walk(value: object):
        if isinstance(value, dict):
            for key, child in value.items():
                assert key not in forbidden_keys
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(body)


def test_research_http_bridge_start_answer_and_authenticated_stateless_restore() -> None:
    app, _signer = _app()
    started = _start(app)
    assert started["schema"] == WIRE_SCHEMA
    assert started["binding_ref"] == BINDING_REF
    assert started["profile_sha256"] == PROFILE_SHA256
    assert started["research_only"] is True
    assert started["human_curated"] is False
    assert started["publication_status"] == "not_approved"
    assert started["psychological_interpretation_allowed"] is False
    assert started["items_answered"] == 0
    assert started["question"]["step"] == 0
    assert [item["value"] for item in started["question"]["response_options"]] == [
        1,
        2,
        3,
        4,
        5,
    ]
    _assert_no_sensitive_output(started)

    current = started
    for index in range(8):
        if index == 3:
            resume_status, resumed = _asgi_request(
                app,
                "POST",
                f"{SESSION_ROUTE}/resume",
                {
                    "schema": WIRE_SCHEMA,
                    "binding_ref": BINDING_REF,
                    "session_ref": current["session_ref"],
                    "signed_snapshot": current["signed_snapshot"],
                },
            )
            assert resume_status == 200
            assert resumed["question"]["item_id"] == current["question"]["item_id"]
            assert resumed["items_answered"] == index
            current = resumed

        response_status, response = _asgi_request(
            app,
            "POST",
            f"{SESSION_ROUTE}/answer",
            {
                "schema": WIRE_SCHEMA,
                "binding_ref": BINDING_REF,
                "session_ref": current["session_ref"],
                "signed_snapshot": current["signed_snapshot"],
                "item_id": current["question"]["item_id"],
                "raw_value": 1 + (index % 5),
            },
        )
        assert response_status == 200
        assert response["items_answered"] == index + 1
        _assert_no_sensitive_output(response)
        current = response

    assert current["status"] == "COMPLETED"
    assert current["question"] is None
    assert current["completion"]["items_answered"] == 8
    assert current["completion"]["items_administered"] == 8
    assert current["completion"]["status"] == "COMPLETED"
    assert current["research_only"] is True
    assert current["psychological_interpretation_allowed"] is False
    _assert_no_sensitive_output(current)


def test_http_bridge_prefixes_generated_session_refs_to_preserve_safe_ref_contract(
    monkeypatch,
) -> None:
    app, _signer = _app()
    monkeypatch.setattr(http_app.secrets, "token_urlsafe", lambda _length: "_bad")
    started = _start(app)
    assert started["session_ref"] == "r__bad"


def test_http_bridge_trusted_profile_and_binding_state_are_deeply_immutable() -> None:
    app, _signer = _app()
    profile = _profile()
    item = profile.items[0]
    assert isinstance(profile.items, tuple)
    assert isinstance(item.thresholds, tuple)
    assert isinstance(profile.raw_profile_bytes, bytes)
    assert isinstance(profile.source_metadata_json, str)
    with pytest.raises(FrozenInstanceError):
        profile.profile_id = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        item.stem = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        app.state.research_bindings["another-binding"] = app.state.research_bindings[
            BINDING_REF
        ]


def test_http_bridge_bearer_binding_and_health_are_fail_closed() -> None:
    app, _signer = _app()
    payload = {"schema": WIRE_SCHEMA, "binding_ref": BINDING_REF}
    status, body = _asgi_request(
        app, "POST", f"{SESSION_ROUTE}/start", payload, token=b"wrong-token"
    )
    assert status == 401
    assert body["error"]["code"] == "bearer_authentication_required"

    status, body = _asgi_request(
        app,
        "POST",
        f"{SESSION_ROUTE}/start",
        payload,
        cookie="session=not-supported",
    )
    assert status == 401
    assert body["error"]["code"] == "bearer_authentication_required"

    status, body = _asgi_request(
        app,
        "POST",
        f"{SESSION_ROUTE}/start",
        {"schema": WIRE_SCHEMA, "binding_ref": "unknown-binding-ref"},
    )
    assert status == 404
    assert body["error"]["code"] == "research_binding_not_found"
    assert "unknown-binding-ref" not in json.dumps(body)

    status, body = _asgi_request(app, "GET", "/health")
    assert status == 200
    assert body == {
        "status": "RESEARCH_ONLY",
        "research_only": True,
        "clinical_approval": False,
        "school_approval": False,
    }
    assert not any(
        route.path in {"/docs", "/openapi.json", "/redoc"} for route in app.routes
    )
    assert not any("CORSMiddleware" in type(middleware.cls).__name__ for middleware in app.user_middleware)


def test_http_bridge_authenticates_before_reading_or_parsing_request_body() -> None:
    app, _signer = _app()
    receive_counter: list[int] = []
    status, body = _asgi_request(
        app,
        "POST",
        f"{SESSION_ROUTE}/start",
        raw_body=b"{malformed private answer",
        token=b"incorrect-token",
        receive_counter=receive_counter,
    )
    assert status == 401
    assert body["error"]["code"] == "bearer_authentication_required"
    assert receive_counter == []

    status, body = _asgi_request(
        app,
        "POST",
        f"{SESSION_ROUTE}/start",
        raw_body=b"{malformed private answer",
        receive_counter=[],
    )
    assert status == 400
    assert body["error"]["code"] == "request_invalid"
    assert "malformed private answer" not in json.dumps(body)


@pytest.mark.parametrize(
    ("include_content_length", "content_length_value"),
    [(False, None), (True, 1)],
)
def test_http_bridge_caps_actual_streamed_body_bytes_without_trusting_length_header(
    include_content_length, content_length_value
) -> None:
    app, _signer = _app()
    raw_body = b'{"schema":"' + WIRE_SCHEMA.encode("ascii") + b'","filler":"'
    raw_body += b"x" * (MAX_REQUEST_BODY_BYTES + 100) + b'"}'
    midpoint = len(raw_body) // 2
    receive_counter: list[int] = []
    status, body = _asgi_request(
        app,
        "POST",
        f"{SESSION_ROUTE}/resume",
        raw_body=raw_body,
        body_chunks=(raw_body[:midpoint], raw_body[midpoint:]),
        include_content_length=include_content_length,
        content_length_value=content_length_value,
        receive_counter=receive_counter,
    )
    assert status == 413
    assert body["error"]["code"] == "request_too_large"
    assert receive_counter and len(receive_counter) <= 2
    assert b"x" * 32 not in json.dumps(body).encode("utf-8")


@pytest.mark.parametrize(
    "raw_body",
    [
        (
            b'{"schema":"'
            + WIRE_SCHEMA.encode("ascii")
            + b'","nested":'
            + b"[" * (MAX_JSON_DEPTH + 1)
            + b"0"
            + b"]" * (MAX_JSON_DEPTH + 1)
            + b"}"
        ),
        (
            b'{"schema":"'
            + WIRE_SCHEMA.encode("ascii")
            + b'","many":['
            + b"0," * MAX_JSON_NODES
            + b"0]}"
        ),
    ],
)
def test_http_bridge_rejects_json_depth_and_node_overruns(raw_body) -> None:
    app, _signer = _app()
    status, body = _asgi_request(
        app,
        "POST",
        f"{SESSION_ROUTE}/start",
        raw_body=raw_body,
    )
    assert status == 400
    assert body["error"]["code"] == "request_invalid"


def test_http_bridge_maps_invalid_requests_snapshots_and_binding_hash_mismatch_safely() -> None:
    app, signer = _app()
    start = _start(app)
    sentinel = "PRIVATE_ANSWER_SENTINEL_8f4ac9"

    bad_signature = deepcopy(start["signed_snapshot"])
    bad_signature["signature"] = "invalid-signature"
    status, body = _asgi_request(
        app,
        "POST",
        f"{SESSION_ROUTE}/resume",
        {
            "schema": WIRE_SCHEMA,
            "binding_ref": BINDING_REF,
            "session_ref": start["session_ref"],
            "signed_snapshot": bad_signature,
            "private_payload": sentinel,
        },
    )
    assert status == 400
    assert body["error"]["code"] == "request_invalid"
    assert sentinel not in json.dumps(body)

    status, body = _asgi_request(
        app,
        "POST",
        f"{SESSION_ROUTE}/resume",
        {
            "schema": WIRE_SCHEMA,
            "binding_ref": BINDING_REF,
            "session_ref": start["session_ref"],
            "signed_snapshot": bad_signature,
        },
    )
    assert status == 400
    assert body["error"]["code"] == "snapshot_invalid"
    assert sentinel not in json.dumps(body)

    signed_wrong_profile = deepcopy(start["signed_snapshot"])
    payload = signed_wrong_profile["payload"]
    payload["profile_sha256"] = "0" * 64
    encoded = research_session._canonical_json(payload).encode("utf-8")
    signed_wrong_profile["payload_sha256"] = hashlib.sha256(encoded).hexdigest()
    signed_wrong_profile["signature"] = signer.sign(encoded)
    status, body = _asgi_request(
        app,
        "POST",
        f"{SESSION_ROUTE}/resume",
        {
            "schema": WIRE_SCHEMA,
            "binding_ref": BINDING_REF,
            "session_ref": start["session_ref"],
            "signed_snapshot": signed_wrong_profile,
        },
    )
    assert status == 400
    assert body["error"]["code"] == "snapshot_invalid"

    status, body = _asgi_request(
        app,
        "POST",
        f"{SESSION_ROUTE}/resume",
        {
            "schema": WIRE_SCHEMA,
            "binding_ref": BINDING_REF,
            "session_ref": "different-session-ref",
            "signed_snapshot": start["signed_snapshot"],
        },
    )
    assert status == 400
    assert body["error"]["code"] == "session_mismatch"


@pytest.mark.parametrize("bad_value", [True, 1.0, float("nan"), float("inf")])
def test_http_bridge_rejects_boolean_and_nonfinite_ordinal_values(bad_value) -> None:
    app, _signer = _app()
    started = _start(app)
    status, body = _asgi_request(
        app,
        "POST",
        f"{SESSION_ROUTE}/answer",
        {
            "schema": WIRE_SCHEMA,
            "binding_ref": BINDING_REF,
            "session_ref": started["session_ref"],
            "signed_snapshot": started["signed_snapshot"],
            "item_id": started["question"]["item_id"],
            "raw_value": bad_value,
        },
    )
    assert status == 400
    assert body["error"]["code"] == "request_invalid"
    assert bad_value.__class__.__name__ not in json.dumps(body)


@pytest.mark.parametrize("bad_value", [0, 6, -1])
def test_http_bridge_rejects_ordinal_outside_pinned_profile_categories(bad_value) -> None:
    app, _signer = _app()
    started = _start(app)
    status, body = _asgi_request(
        app,
        "POST",
        f"{SESSION_ROUTE}/answer",
        {
            "schema": WIRE_SCHEMA,
            "binding_ref": BINDING_REF,
            "session_ref": started["session_ref"],
            "signed_snapshot": started["signed_snapshot"],
            "item_id": started["question"]["item_id"],
            "raw_value": bad_value,
        },
    )
    assert status == 400
    assert body["error"]["code"] == "answer_invalid"


def test_http_bridge_rejects_wrong_item_config_and_unavailable_factory_defaults() -> None:
    profile = _profile()
    signer = _TestAuthenticator()
    config_a = _config("research-http-config-a")
    config_b = _config("research-http-config-b")
    bindings = {
        BINDING_REF: ResearchCATBinding(BINDING_REF, profile, config_a),
        f"{BINDING_REF}-alt": ResearchCATBinding(
            f"{BINDING_REF}-alt", profile, config_b
        ),
    }
    app = create_research_http_app(
        bindings=bindings,
        authenticator=signer,
        service_bearer_token=SERVICE_TOKEN,
    )
    started = _start(app)

    status, body = _asgi_request(
        app,
        "POST",
        f"{SESSION_ROUTE}/resume",
        {
            "schema": WIRE_SCHEMA,
            "binding_ref": f"{BINDING_REF}-alt",
            "session_ref": started["session_ref"],
            "signed_snapshot": started["signed_snapshot"],
        },
    )
    assert status == 400
    assert body["error"]["code"] == "snapshot_invalid"

    status, body = _asgi_request(
        app,
        "POST",
        f"{SESSION_ROUTE}/answer",
        {
            "schema": WIRE_SCHEMA,
            "binding_ref": BINDING_REF,
            "session_ref": started["session_ref"],
            "signed_snapshot": started["signed_snapshot"],
            "item_id": "wrong-item",
            "raw_value": 1,
        },
    )
    assert status == 400
    assert body["error"]["code"] == "answer_invalid"

    with pytest.raises(TypeError, match="validated CAT config"):
        ResearchCATBinding(BINDING_REF, profile, None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="explicit service token"):
        create_research_http_app(
            bindings=bindings,
            authenticator=signer,
            service_bearer_token=b"short",
        )
