from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from smhai_backend.app_factory import create_app
from smhai_backend.core.config import BackendSettings
from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.rate_limit import InMemoryRateLimiter
from smhai_backend.domains.auth.dependencies import csrf_protected, current_actor
from smhai_backend.domains.conversations.router import router as conversations_router
from smhai_backend.domains.conversations.schemas import (
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationMessageRequest,
    ConversationProjection,
    ConversationTurnResult,
)
from smhai_backend.domains.models import Actor, BackendRole


def _actor(role: BackendRole = BackendRole.STUDENT) -> Actor:
    return Actor(
        user_id="USER_api-test",
        username="api-test",
        role=role,
        subject_id="SUBJ_api-test" if role is BackendRole.STUDENT else None,
        scope_profile="school_tenant",
        school_id=17,
        school_ref="SCHOOL_api-test",
    )


def _projection() -> ConversationProjection:
    return ConversationProjection(
        conversation_id="CONV_api-test",
        status="active",
        created_at="2026-10-12T00:00:00Z",
        updated_at="2026-10-12T00:00:00Z",
    )


class FakeConversationService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.turn_status = "requested"
        self.turn_replayed = True

    async def create(self, actor, *, idempotency_key, context, payload=None):
        self.calls.append(
            (
                "create",
                (actor,),
                {"key": idempotency_key, "payload": payload, "context": context},
            )
        )
        assert isinstance(payload, ConversationCreateRequest)
        return _projection()

    async def list(self, actor, *, offset, limit):
        self.calls.append(("list", (actor,), {"offset": offset, "limit": limit}))
        return ConversationListResponse(
            items=[_projection()], total=1, has_more=False
        )

    async def detail(self, actor, conversation_id, *, offset, limit):
        self.calls.append(("detail", (actor, conversation_id), {"offset": offset, "limit": limit}))
        return ConversationDetailResponse(
            conversation=_projection(),
            messages=[],
            turns=[],
            offset=offset,
            limit=limit,
            total_turns=0,
            has_more=False,
        )

    async def submit_message(
        self, actor, conversation_id, *, payload, idempotency_key, context
    ):
        self.calls.append(
            (
                "submit_message",
                (actor, conversation_id),
                {"payload": payload, "key": idempotency_key, "context": context},
            )
        )
        assert isinstance(payload, ConversationMessageRequest)
        return ConversationTurnResult(
            turn_id="TURN_api-test",
            status=self.turn_status,
            replayed=self.turn_replayed,
            user_message_sequence=1,
        )


def _override_actor(app, actor: Actor) -> None:
    async def provide_actor():
        return actor

    # These route delegation tests isolate router wiring. Real CSRF dependency
    # behavior is exercised separately below without dependency overrides.
    app.dependency_overrides[current_actor] = provide_actor
    app.dependency_overrides[csrf_protected] = provide_actor


async def _login(client) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "student_a", "password": "synthetic-student-a"},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["csrf_token"]


@pytest.mark.asyncio
async def test_routes_delegate_typed_requests_and_preserve_requested_replay_status(app, client):
    service = FakeConversationService()
    actor = _actor()
    app.state.container.independent_conversations = service
    _override_actor(app, actor)

    created = await client.post(
        "/api/v1/student/conversations",
        headers={"Idempotency-Key": "create-key"},
        json={},
    )
    listed = await client.get("/api/v1/student/conversations?offset=2&limit=3")
    detailed = await client.get(
        "/api/v1/student/conversations/CONV_api-test?offset=4&limit=5"
    )
    submitted = await client.post(
        "/api/v1/student/conversations/CONV_api-test/messages",
        headers={"Idempotency-Key": "message-key"},
        json={"text": "合成学生的学习安排问题"},
    )

    assert created.status_code == 201
    assert created.json()["data"]["conversation_id"] == "CONV_api-test"
    assert listed.status_code == 200
    assert listed.json()["data"]["items"][0]["conversation_id"] == "CONV_api-test"
    assert detailed.status_code == 200
    assert detailed.json()["data"]["offset"] == 4
    assert submitted.status_code == 202
    assert submitted.json()["data"]["status"] == "requested"
    assert submitted.json()["data"]["replayed"] is True
    assert [call[0] for call in service.calls] == [
        "create",
        "list",
        "detail",
        "submit_message",
    ]
    assert service.calls[0][1][0] is actor
    assert service.calls[0][2]["key"] == "create-key"
    assert service.calls[1][2] == {"offset": 2, "limit": 3}
    assert service.calls[2][1][1] == "CONV_api-test"
    assert service.calls[2][2] == {"offset": 4, "limit": 5}
    assert service.calls[3][2]["key"] == "message-key"
    assert service.calls[3][2]["payload"].text == "合成学生的学习安排问题"


@pytest.mark.asyncio
async def test_real_csrf_dependency_rejects_missing_and_wrong_tokens(app, client):
    csrf = await _login(client)
    url = "/api/v1/student/conversations"
    headers = {"Idempotency-Key": "csrf-test"}

    missing = await client.post(url, headers=headers, json={})
    wrong = await client.post(
        url,
        headers={**headers, "X-CSRF-Token": f"wrong-{csrf}"},
        json={},
    )

    assert missing.status_code == 403
    assert missing.json()["code"] == "csrf_failed"
    assert wrong.status_code == 403
    assert wrong.json()["code"] == "csrf_failed"


@pytest.mark.asyncio
async def test_teacher_role_is_denied_before_service_and_missing_service_is_503(
    app, client
):
    service = FakeConversationService()
    app.state.container.independent_conversations = service
    _override_actor(app, _actor(BackendRole.TEACHER))
    denied = await client.get("/api/v1/student/conversations")

    assert denied.status_code == 403
    assert denied.json()["code"] == "forbidden"
    assert service.calls == []

    app.dependency_overrides.clear()
    app.state.container.independent_conversations = None
    csrf = await _login(client)
    unavailable = await client.post(
        "/api/v1/student/conversations",
        headers={"Idempotency-Key": "no-service", "X-CSRF-Token": csrf},
        json={},
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["code"] == "dependency_unavailable"


@pytest.mark.parametrize(
    "role",
    [
        BackendRole.TEACHER,
        BackendRole.PSYCHOLOGICAL_SPECIALIST,
        BackendRole.ADMIN,
    ],
    ids=["teacher", "psychological-specialist", "school-admin"],
)
@pytest.mark.asyncio
async def test_non_student_roles_are_denied_on_all_conversation_routes_before_service_work(
    app, client, role
):
    service = FakeConversationService()
    app.state.container.independent_conversations = service
    _override_actor(app, _actor(role))

    responses = [
        await client.get("/api/v1/student/conversations"),
        await client.get("/api/v1/student/conversations/CONV_api-test"),
        await client.post(
            "/api/v1/student/conversations",
            headers={"Idempotency-Key": "role-denied-create"},
            json={},
        ),
        await client.post(
            "/api/v1/student/conversations/CONV_api-test/messages",
            headers={"Idempotency-Key": "role-denied-message"},
            json={"text": "合成请求"},
        ),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403, 403]
    assert all(response.json()["code"] == "forbidden" for response in responses)
    # The conversation service is the only route to stored bodies or model
    # generation. An empty call log proves all four requests stop before it.
    assert service.calls == []


@pytest.mark.asyncio
async def test_student_owner_scope_not_found_remains_404_at_the_api_boundary(app, client):
    class OwnerScopedService(FakeConversationService):
        async def detail(self, actor, conversation_id, *, offset, limit):
            self.calls.append(
                ("detail", (actor, conversation_id), {"offset": offset, "limit": limit})
            )
            raise error(
                ErrorCode.RESOURCE_NOT_FOUND,
                detail="conversation was not found",
            )

    service = OwnerScopedService()
    app.state.container.independent_conversations = service
    actor = _actor(BackendRole.STUDENT)
    _override_actor(app, actor)

    response = await client.get(
        "/api/v1/student/conversations/CONV_owned-by-another-student"
    )

    assert response.status_code == 404
    assert response.json()["code"] == "resource_not_found"
    assert [call[0] for call in service.calls] == ["detail"]
    assert service.calls[0][1] == (actor, "CONV_owned-by-another-student")


@pytest.mark.asyncio
async def test_writes_require_idempotency_key_and_reject_owner_or_model_fields(app, client):
    service = FakeConversationService()
    app.state.container.independent_conversations = service
    _override_actor(app, _actor())

    missing_create_key = await client.post("/api/v1/student/conversations", json={})
    missing_message_key = await client.post(
        "/api/v1/student/conversations/CONV_api-test/messages",
        json={"text": "合成问题"},
    )
    create_extra = await client.post(
        "/api/v1/student/conversations",
        headers={"Idempotency-Key": "extra-owner"},
        json={"subject_id": "SUBJ_forged", "owner_id": "USER_forged", "model": "other"},
    )
    message_extra = await client.post(
        "/api/v1/student/conversations/CONV_api-test/messages",
        headers={"Idempotency-Key": "extra-model"},
        json={"text": "合成问题", "model_id": "other", "owner_id": "USER_forged"},
    )

    assert missing_create_key.status_code == 422
    assert missing_message_key.status_code == 422
    assert create_extra.status_code == 422
    assert message_extra.status_code == 422
    assert service.calls == []


@pytest.mark.asyncio
async def test_message_route_applies_support_rate_limit_before_second_service_call(
    app, client
):
    service = FakeConversationService()
    app.state.container.independent_conversations = service
    app.state.container.rate_limiter = InMemoryRateLimiter(
        limits={"support": 1}, window_seconds=60
    )
    _override_actor(app, _actor())
    url = "/api/v1/student/conversations/CONV_api-test/messages"

    first = await client.post(
        url,
        headers={"Idempotency-Key": "limited-1"},
        json={"text": "合成问题一"},
    )
    second = await client.post(
        url,
        headers={"Idempotency-Key": "limited-2"},
        json={"text": "合成问题二"},
    )

    assert first.status_code == 202
    assert second.status_code == 429
    assert second.json()["code"] == "rate_limited"
    assert len(service.calls) == 1


def test_conversation_routes_remain_hidden_from_frozen_openapi():
    app = create_app(settings=BackendSettings(environment="test"))
    assert {route.path for route in conversations_router.routes} == {
        "/student/conversations",
        "/student/conversations/{conversation_id}",
        "/student/conversations/{conversation_id}/messages",
    }
    assert "/api/v1/student/conversations" not in app.openapi()["paths"]
    assert "/api/v1/student/conversations/{conversation_id}" not in app.openapi()["paths"]
    assert (
        "/api/v1/student/conversations/{conversation_id}/messages"
        not in app.openapi()["paths"]
    )


@pytest.mark.asyncio
async def test_container_lifespan_closes_new_independent_clients():
    @dataclass
    class CloseRecorder:
        calls: int = 0

        async def close(self) -> None:
            self.calls += 1

    app = create_app(settings=BackendSettings(environment="test"))
    rag_client = CloseRecorder()
    llm_client = CloseRecorder()
    app.state.container.independent_rag = rag_client
    app.state.container.independent_llm = llm_client

    async with app.router.lifespan_context(app):
        assert rag_client.calls == 0
        assert llm_client.calls == 0

    assert rag_client.calls == 1
    assert llm_client.calls == 1


@pytest.mark.asyncio
async def test_startup_failure_still_closes_independent_clients(monkeypatch):
    @dataclass
    class CloseRecorder:
        calls: int = 0

        async def close(self):
            self.calls += 1

    app = create_app(settings=BackendSettings(environment="test"))
    rag_client, llm_client = CloseRecorder(), CloseRecorder()
    app.state.container.independent_rag = rag_client
    app.state.container.independent_llm = llm_client

    async def failed_start(_self):
        raise RuntimeError("synthetic startup failure")

    monkeypatch.setattr(type(app.state.container), "start", failed_start)
    with pytest.raises(RuntimeError, match="synthetic startup failure"):
        async with app.router.lifespan_context(app):
            pytest.fail("failed startup must not enter the lifespan")
    assert rag_client.calls == llm_client.calls == 1
    assert app.state.lifecycle_started is False
