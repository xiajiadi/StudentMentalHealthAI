from __future__ import annotations

import httpx
import pytest

from smhai_backend.adapters.memory.repositories import InMemorySessionStore
from smhai_backend.core.config import BackendSettings, RateLimitSettings
from smhai_backend.core.errors import ErrorCode
from smhai_backend.core.request_context import RequestContext
from smhai_backend.integrations.common_http import LongLivedHttpClient, UpstreamError
from smhai_backend.integrations.safety import ContractFakeSafetyClient, HttpSafetyClient

from .conftest import completed_assessment, login


@pytest.mark.asyncio
async def test_app_factory_lifespan_health_and_dependency_matrix(client, app):
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ready"

    response = await client.get("/health/dependencies")
    assert response.status_code == 200
    assert response.json()["data"]["safety"]["integration"] == "CONTRACT_FAKE"

    app.state.container.rag.available = False
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "degraded"
    assert response.json()["data"]["dependencies"]["rag"]["status"] == "UNAVAILABLE"
    assert (await client.get("/api/v1/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_auth_argon2_rotation_csrf_and_logout_invalidation(client, app):
    first_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "student_a", "password": "synthetic-student-a"},
    )
    assert first_login.status_code == 200
    cookie_name = app.state.container.settings.cookie_name
    first_session = client.cookies.get(cookie_name)
    assert first_session
    set_cookie = first_login.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Path=/" in set_cookie
    assert "Secure" not in set_cookie
    assert app.state.container.users.get_by_username("student_a").password_hash.startswith(
        "$argon2"
    )

    second_csrf = await login(client)
    second_session = client.cookies.get(cookie_name)
    assert second_session and second_session != first_session
    assert app.state.container.sessions.is_revoked(first_session)

    response = await client.post("/api/v1/assessments", json={})
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")

    response = await client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": second_csrf},
    )
    assert response.status_code == 200
    assert app.state.container.sessions.is_revoked(second_session)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={cookie_name: second_session},
    ) as old_client:
        response = await old_client.get("/api/v1/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_invalid_credentials_and_session_expiry_are_explicit(client):
    unknown = await client.post(
        "/api/v1/auth/login",
        json={"username": "unknown-user", "password": "wrong-password"},
    )
    wrong_password = await client.post(
        "/api/v1/auth/login",
        json={"username": "student_a", "password": "wrong-password"},
    )
    assert unknown.status_code == wrong_password.status_code == 401
    assert unknown.json()["code"] == wrong_password.json()["code"] == "auth_invalid_credentials"
    assert unknown.json()["detail"] == wrong_password.json()["detail"]

    current_time = [100.0]
    store = InMemorySessionStore(clock=lambda: current_time[0])
    session = store.create("USER_student_a", ttl_seconds=60)
    assert len(session.session_id) >= 43
    assert store.get(session.session_id) is not None
    current_time[0] = 161.0
    assert store.get(session.session_id) is None
    assert store.is_revoked(session.session_id)


@pytest.mark.asyncio
async def test_problem_details_and_origin_fetch_metadata(client):
    response = await client.get("/api/v1/auth/me", headers={"X-Request-ID": "bad"})
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"].startswith("urn:smhai:problem:")
    assert body["title"] == "Authentication required"
    assert body["status"] == 401
    assert body["detail"] == "authentication is required"
    assert body["request_id"].startswith("REQ_")
    assert body["trace_id"].startswith("TRACE_")

    response = await client.post(
        "/api/v1/auth/login",
        headers={"Origin": "https://attacker.invalid"},
        json={"username": "student_a", "password": "synthetic-student-a"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "csrf_failed"

    response = await client.post(
        "/api/v1/auth/login",
        headers={"Sec-Fetch-Site": "cross-site"},
        json={"username": "student_a", "password": "synthetic-student-a"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_vertical_slice_normal_crisis_review_and_output_gate(client, app, capfd):
    csrf_token = await login(client)
    assessment_id = await completed_assessment(client, csrf_token)

    normal = await client.post(
        "/api/v1/support/requests",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "assessment_id": assessment_id,
            "target_role": "student",
            "message": "我想把今天的任务拆成小步骤。",
        },
    )
    assert normal.status_code == 202
    normal_data = normal.json()["data"]
    assert normal_data["status"] == "generated"
    assert normal_data["normal_generation"] is True
    assert normal_data["content"]["suggestions"][0]["source_chunk_ids"] == ["CHUNK_backend_0"]
    assert normal_data["trace_id"] == normal.headers["x-trace-id"]
    assert any(
        event.event == "SUPPORT_REQUESTED" and event.trace_id == normal_data["trace_id"]
        for event in app.state.container.audits.list()
    )
    assert app.state.container.support.call_order[-3:] == [
        "safety_retrieval",
        "llm",
        "safety_output",
    ]

    unsafe = await client.post(
        "/api/v1/support/requests",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "assessment_id": assessment_id,
            "target_role": "student",
            "message": "SYNTHETIC_UNSAFE_OUTPUT",
        },
    )
    assert unsafe.status_code == 202
    unsafe_data = unsafe.json()["data"]
    assert unsafe_data["status"] == "needs_review"
    assert unsafe_data["normal_generation"] is False
    assert unsafe_data["content"] is None
    assert "SYNTHETIC_UNSAFE_OUTPUT" not in unsafe.text

    before_rag = app.state.container.rag.calls
    before_llm = app.state.container.llm.calls
    crisis = await client.post(
        "/api/v1/support/requests",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "assessment_id": assessment_id,
            "target_role": "student",
            "message": "SYNTHETIC_CRISIS_SIGNAL",
        },
    )
    assert crisis.status_code == 202
    crisis_data = crisis.json()["data"]
    assert crisis_data["safety_action"] == "CRISIS_ROUTE"
    assert crisis_data["status"] == "needs_review"
    assert crisis_data["normal_generation"] is False
    assert crisis_data["crisis_response"]
    assert crisis_data["review_reference"]
    assert app.state.container.rag.calls == before_rag
    assert app.state.container.llm.calls == before_llm

    reviewer_csrf = await login(client, "reviewer")
    response = await client.get("/api/v1/reviews")
    assert response.status_code == 200
    pending = response.json()["data"]
    assert any(item["review_id"] == crisis_data["review_reference"] for item in pending)

    response = await client.get(f"/api/v1/reviews/{crisis_data['review_reference']}")
    assert response.status_code == 200
    assert response.json()["data"]["review_id"] == crisis_data["review_reference"]

    response = await client.post(
        f"/api/v1/reports/{crisis_data['report_id']}/reviews",
        headers={"X-CSRF-Token": reviewer_csrf},
        json={"decision": "approved"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["review_status"] == "approved"

    captured = capfd.readouterr().out
    for sensitive_value in (
        "synthetic-student-a",
        "SYNTHETIC_CRISIS_SIGNAL",
        "我想把今天的任务拆成小步骤。",
        csrf_token,
        reviewer_csrf,
    ):
        assert sensitive_value not in captured


@pytest.mark.asyncio
async def test_bola_bopla_and_bfla(client):
    csrf_token = await login(client)
    assessment_id = await completed_assessment(client, csrf_token)
    support = await client.post(
        "/api/v1/support/requests",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "assessment_id": assessment_id,
            "target_role": "student",
            "message": "只用于合成授权测试。",
        },
    )
    report_id = support.json()["data"]["report_id"]

    await login(client, "student_b")
    response = await client.get(f"/api/v1/reports/{report_id}")
    assert response.status_code == 403

    response = await client.get("/api/v1/reviews")
    assert response.status_code == 403

    await login(client, "student_a")
    csrf_token = await login(client, "student_a")
    response = await client.post(
        "/api/v1/support/requests",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "assessment_id": assessment_id,
            "target_role": "student",
            "message": "safe",
            "subject_id": "SUBJ_demo_b",
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"


@pytest.mark.asyncio
async def test_idempotency_and_rate_limit():
    from smhai_backend.app_factory import create_app

    settings = BackendSettings(
        environment="test",
        rate_limit=RateLimitSettings(
            login_max_requests=1,
            support_max_requests=1,
            window_seconds=60,
        ),
    )
    app = create_app(settings=settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            body = {
                "subject_id": "SUBJ_demo_a",
                "instrument_id": "instrument.synthetic",
                "instrument_version": "1.0",
            }
            csrf_token = await login(client)
            response = await client.post(
                "/api/v1/assessments",
                headers={"X-CSRF-Token": csrf_token, "Idempotency-Key": "start-1"},
                json=body,
            )
            assert response.status_code == 201
            first_body = response.json()
            assessment_id = response.json()["data"]["assessment_id"]
            calls = app.state.container.cat.call_count

            response = await client.post(
                "/api/v1/assessments",
                headers={"X-CSRF-Token": csrf_token, "Idempotency-Key": "start-1"},
                json=body,
            )
            assert response.status_code == 201
            assert response.json() == first_body
            assert app.state.container.cat.call_count == calls

            response = await client.post(
                "/api/v1/assessments",
                headers={"X-CSRF-Token": csrf_token, "Idempotency-Key": "start-1"},
                json={**body, "instrument_version": "2.0"},
            )
            assert response.status_code == 409

            response = await client.post(
                "/api/v1/auth/login",
                json={"username": "student_a", "password": "synthetic-student-a"},
            )
            assert response.status_code == 429
            assert response.headers["retry-after"] == "60"

            assert assessment_id.startswith("ASSESS_")


@pytest.mark.asyncio
async def test_safety_down_fails_closed(client, app):
    csrf_token = await login(client)
    assessment_id = await completed_assessment(client, csrf_token)
    app.state.container.safety.available = False
    response = await client.post(
        "/api/v1/support/requests",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "assessment_id": assessment_id,
            "target_role": "student",
            "message": "Safety unavailable fixture",
        },
    )
    assert response.status_code == 503
    assert response.json()["code"] == "dependency_unavailable"
    assert app.state.container.rag.calls == 0
    assert app.state.container.llm.calls == 0


@pytest.mark.asyncio
async def test_long_lived_httpx_local_policy_and_explicit_timeouts():
    settings = BackendSettings()
    client = LongLivedHttpClient(settings.safety)
    try:
        assert client.client._trust_env is False
        assert client.client.timeout.connect == 1.0
        assert client.client.timeout.read == 8.0
        assert client.client.timeout.write == 8.0
        assert client.client.timeout.pool == 1.0
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_httpx_upstream_validation_and_failure_mapping(monkeypatch):
    client = LongLivedHttpClient(BackendSettings().safety)
    context = RequestContext("REQ_httpx", "TRACE_httpx")
    try:
        captured_headers = {}

        async def success(method, url, **kwargs):
            captured_headers.update(kwargs["headers"])
            return httpx.Response(200, json={"ok": True})

        monkeypatch.setattr(client.client, "request", success)
        assert await client.get_json("/health", context=context) == {"ok": True}
        assert captured_headers["X-Request-ID"] == "REQ_httpx"
        assert captured_headers["X-Trace-ID"] == "TRACE_httpx"

        async def server_error(method, url, **kwargs):
            return httpx.Response(500, json={"detail": "must not leak"})

        monkeypatch.setattr(client.client, "request", server_error)
        with pytest.raises(UpstreamError) as server_exc:
            await client.get_json("/health", context=context)
        assert server_exc.value.code == ErrorCode.DEPENDENCY_UNAVAILABLE

        async def bad_json(method, url, **kwargs):
            return httpx.Response(200, content=b"not-json")

        monkeypatch.setattr(client.client, "request", bad_json)
        with pytest.raises(UpstreamError) as json_exc:
            await client.get_json("/health", context=context)
        assert json_exc.value.code == ErrorCode.DEPENDENCY_INVALID_RESPONSE

        async def wrong_shape(method, url, **kwargs):
            return httpx.Response(200, json=["wrong", "shape"])

        monkeypatch.setattr(client.client, "request", wrong_shape)
        with pytest.raises(UpstreamError) as shape_exc:
            await client.get_json("/health", context=context)
        assert shape_exc.value.code == ErrorCode.DEPENDENCY_INVALID_RESPONSE

        async def timeout(method, url, **kwargs):
            raise httpx.ReadTimeout("synthetic timeout")

        monkeypatch.setattr(client.client, "request", timeout)
        with pytest.raises(UpstreamError) as timeout_exc:
            await client.get_json("/health", context=context)
        assert timeout_exc.value.code == ErrorCode.DEPENDENCY_TIMEOUT

        async def transport_error(method, url, **kwargs):
            raise httpx.ConnectError("synthetic connection failure")

        monkeypatch.setattr(client.client, "request", transport_error)
        with pytest.raises(UpstreamError) as transport_exc:
            await client.get_json("/health", context=context)
        assert transport_exc.value.code == ErrorCode.DEPENDENCY_UNAVAILABLE
    finally:
        await client.close()


def test_http_safety_retrieval_projection_is_contract_explicit():
    projected = HttpSafetyClient._retrieval_chunk_for_safety(
        {
            "chunk_id": "CHUNK_backend_0",
            "text": "合成教育支持资料",
            "review_status": "approved",
            "rights_status": "verified",
            "citation": {"title": "not forwarded"},
        }
    )
    assert projected == {
        "content": "合成教育支持资料",
        "metadata": {
            "chunk_id": "CHUNK_backend_0",
            "review_status": "approved",
            "rights_status": "verified",
        },
    }


@pytest.mark.asyncio
async def test_fake_safety_contract_and_review_action():
    safety = ContractFakeSafetyClient()
    context = RequestContext("REQ_test", "TRACE_test")
    result = await safety.check_input(
        {"current_user_message": "SYNTHETIC_CRISIS_SIGNAL"},
        context,
    )
    assert result.decision.action == "CRISIS_ROUTE"
    assert result.decision.requires_human is True
    assert result.review_reference
