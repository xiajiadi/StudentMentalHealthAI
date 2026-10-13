from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request

from smhai_backend.adapters.school_research import (
    ResearchSessionPersistenceResult,
    ResearchSessionReceipt,
)
from smhai_backend.core.errors import (
    BackendError,
    ErrorCode,
    backend_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from smhai_backend.core.idempotency import fingerprint
from smhai_backend.core.request_context import make_context
from smhai_backend.domains.auth.dependencies import csrf_protected, current_actor
from smhai_backend.domains.models import Actor, BackendRole, SchoolRoleContext
from smhai_backend.domains.school_research.client import ResearchCATClientError
from smhai_backend.domains.school_research.router import router
from smhai_backend.domains.school_research.schemas import ResearchL1SessionDto
from smhai_backend.domains.school_research.service import SchoolResearchService

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def _actor(role=BackendRole.STUDENT, *, school=True):
    return Actor(
        user_id="USER_synthetic_student",
        username="synthetic-student",
        role=role,
        subject_id=None,
        scope_profile="school_tenant" if school else "legacy_demo",
        school_id=12 if school else None,
        school_ref="SCHOOL_synthetic" if school else None,
        school_contexts=(
            (
                SchoolRoleContext(
                    context_id="ROLE_synthetic_student",
                    role=role,
                    school_id=12,
                    school_ref="SCHOOL_synthetic",
                ),
            )
            if school
            else ()
        ),
    )


def _receipt(*, session_ref="SESSION_synthetic_1", status="IN_PROGRESS", state_version=1, items=0):
    return ResearchSessionReceipt(
        session_ref=session_ref,
        task_ref="TASK_synthetic_1",
        enrollment_ref="ENROLL_synthetic_1",
        subject_ref="SUBJECT_synthetic_1",
        profile_ref="profile-internal",
        profile_version_number=1,
        profile_sha256="a" * 64,
        config_version="config-private",
        config_sha256="b" * 64,
        status=status,
        state_version=state_version,
        items_answered=items,
        stop_reason="max_items_reached" if status == "COMPLETED" else None,
        started_at=NOW,
        completed_at=NOW if status == "COMPLETED" else None,
    )


def _persisted_result(
    *, status="IN_PROGRESS", state_version=1, items=0, replayed=False, accepted=False
):
    return ResearchSessionPersistenceResult(
        metadata=_receipt(
            status=status,
            state_version=state_version,
            items=items,
        ),
        persisted=True,
        replayed=replayed,
        state_accepted=accepted,
    )


def _question(step=0):
    return SimpleNamespace(
        item_id=f"item-{step + 1}",
        qid=f"qid-{step + 1}",
        stem="合成演示题目内容。",
        step=step,
        response_options=(
            SimpleNamespace(value=0, label="选项零"),
            SimpleNamespace(value=1, label="选项一"),
        ),
    )


def _state(*, status="ACTIVE", items=0):
    completion = (
        SimpleNamespace(
            status="COMPLETED",
            items_administered=items,
            items_answered=items,
            stop_reason="max_items_reached",
        )
        if status == "COMPLETED"
        else None
    )
    return SimpleNamespace(
        session_ref="SESSION_synthetic_1",
        profile_id="profile-internal",
        profile_sha256="a" * 64,
        config_sha256="b" * 64,
        config_version="config-private",
        research_only=True,
        human_curated=False,
        publication_status="not_approved",
        psychological_interpretation_allowed=False,
        status=status,
        items_answered=items,
        question=_question(items) if status == "ACTIVE" else None,
        completion=completion,
    )


class _FakeClient:
    def __init__(self, *, start_state=None, resumed_state=None, answered_state=None):
        self.start_state = start_state or _state()
        self.resumed_state = resumed_state or _state()
        self.answered_state = answered_state or _state(items=1)
        self.calls = []
        self.closed = 0
        self.answer_error: Any = None
        self.resume_error: Any = None

    async def start(self):
        self.calls.append(("start",))
        return self.start_state

    async def resume_from_persisted(self, snapshot, **kwargs):
        self.calls.append(("resume", snapshot, kwargs))
        if self.resume_error:
            raise self.resume_error
        return self.resumed_state

    async def answer(self, state, *, item_id, raw_value):
        self.calls.append(("answer", item_id, raw_value, state))
        if self.answer_error:
            raise self.answer_error
        return self.answered_state

    def snapshot_for_persistence(self, _state):
        return object()

    async def aclose(self):
        self.closed += 1


class _FakePersistence:
    def __init__(self):
        self.calls = []
        self.start_prepared: Any = None
        self.start_committed: Any = None
        self.answer_prepared: Any = None
        self.answer_committed: Any = None
        self.resume_plan: Any = None
        self.commit_error: Any = None

    async def prepare_start(self, actor, task_ref, **kwargs):
        self.calls.append(("prepare_start", actor, task_ref, kwargs))
        return self.start_prepared

    async def commit_start(self, actor, plan, state, **kwargs):
        self.calls.append(("commit_start", actor, plan, state, kwargs))
        if self.commit_error:
            raise self.commit_error
        return self.start_committed

    async def prepare_answer(self, actor, session_ref, **kwargs):
        self.calls.append(("prepare_answer", actor, session_ref, kwargs))
        return self.answer_prepared

    async def commit_answer(self, actor, plan, state, **kwargs):
        self.calls.append(("commit_answer", actor, plan, state, kwargs))
        if self.commit_error:
            raise self.commit_error
        return self.answer_committed

    async def prepare_resume(self, actor, session_ref, **kwargs):
        self.calls.append(("prepare_resume", actor, session_ref, kwargs))
        return self.resume_plan


def _plan(client, *, session_ref="SESSION_synthetic_1", items=0):
    return SimpleNamespace(
        client=client,
        session_ref=session_ref,
        profile_ref="profile-internal",
        config_version="config-private",
        profile_sha256="a" * 64,
        config_sha256="b" * 64,
        expected_state_version=7,
        state_version=7,
        items_answered=items,
        signed_snapshot_json='{"signed_snapshot":"synthetic-private"}',
    )


def _l1_dict(value):
    return value.model_dump(mode="json")


@pytest.mark.asyncio
async def test_service_start_projects_only_l1_after_persisting_same_state_and_closes_client():
    persistence = _FakePersistence()
    client = _FakeClient()
    persistence.start_prepared = _plan(client)
    persistence.start_committed = _persisted_result(accepted=True)
    service = SchoolResearchService(persistence=persistence, clock=lambda: NOW)

    value = await service.start_task(
        _actor(), "TASK_synthetic_1", trace_id="TRACE_synthetic", idempotency=("k", "f", "s")
    )
    data = _l1_dict(value)

    assert data["question"]["item_id"] == "item-1"
    assert data["state_version"] == 1
    assert not data["resume_required"]
    assert data["research_only"] is True
    assert not {
        "answers",
        "signed_snapshot",
        "theta",
        "se",
        "score",
        "profile_ref",
        "profile_sha256",
        "school_id",
        "enrollment_id",
        "qid",
    }.intersection(data)
    assert client.closed == 1
    assert [call[0] for call in persistence.calls] == ["prepare_start", "commit_start"]


@pytest.mark.asyncio
async def test_service_start_idempotency_replay_returns_metadata_without_client_or_question():
    persistence = _FakePersistence()
    persistence.start_prepared = _persisted_result(replayed=True)
    service = SchoolResearchService(persistence=persistence, clock=lambda: NOW)

    value = await service.start_task(
        _actor(), "TASK_synthetic_1", trace_id="TRACE_synthetic", idempotency=("k", "f", "s")
    )

    assert value.resume_required is True
    assert value.question is None
    assert len(persistence.calls) == 1


@pytest.mark.asyncio
async def test_service_discards_concurrent_start_question_when_persisted_session_differs():
    persistence = _FakePersistence()
    client = _FakeClient(
        start_state=SimpleNamespace(**(vars(_state()) | {"session_ref": "discarded"}))
    )
    persistence.start_prepared = _plan(client)
    persistence.start_committed = _persisted_result(accepted=False)
    service = SchoolResearchService(persistence=persistence, clock=lambda: NOW)

    value = await service.start_task(
        _actor(), "TASK_synthetic_1", trace_id="TRACE_synthetic", idempotency=("k", "f", "s")
    )

    assert value.session_ref == "SESSION_synthetic_1"
    assert value.question is None
    assert value.resume_required is True
    assert client.closed == 1


@pytest.mark.asyncio
async def test_service_resume_uses_persisted_snapshot_and_returns_only_question_projection():
    persistence = _FakePersistence()
    client = _FakeClient()
    persistence.resume_plan = _plan(client)
    service = SchoolResearchService(persistence=persistence, clock=lambda: NOW)

    value = await service.resume_session(_actor(), "SESSION_synthetic_1")

    assert value.question is not None
    assert value.question.step == 0
    assert client.calls[0][0] == "resume"
    assert client.calls[0][1] == persistence.resume_plan.signed_snapshot_json
    assert client.closed == 1


@pytest.mark.asyncio
async def test_service_answer_resumes_then_commits_one_state_version_and_closes_on_error():
    persistence = _FakePersistence()
    client = _FakeClient()
    persistence.answer_prepared = _plan(client)
    persistence.answer_committed = _persisted_result(state_version=8, items=1, accepted=True)
    service = SchoolResearchService(persistence=persistence, clock=lambda: NOW)

    value = await service.answer(
        _actor(),
        "SESSION_synthetic_1",
        item_id="item-1",
        raw_value=1,
        expected_state_version=7,
        idempotency=("answer-key", "c" * 64, "d" * 64),
    )

    assert value.state_version == 8
    assert value.items_answered == 1
    assert value.question is not None
    assert value.question.item_id == "item-2"
    assert [call[0] for call in client.calls] == ["resume", "answer"]
    assert persistence.calls[-1][0] == "commit_answer"
    assert persistence.calls[-1][4]["idempotency"][0] == "answer-key"
    assert client.closed == 1


@pytest.mark.asyncio
async def test_service_answer_replay_returns_only_current_metadata():
    persistence = _FakePersistence()
    persistence.answer_prepared = _persisted_result(replayed=True)
    service = SchoolResearchService(persistence=persistence, clock=lambda: NOW)

    value = await service.answer(
        _actor(),
        "SESSION_synthetic_1",
        item_id="item-1",
        raw_value=1,
        expected_state_version=7,
        idempotency=("answer-key", "c" * 64, "d" * 64),
    )

    assert value.resume_required is True
    assert value.question is None
    assert len(persistence.calls) == 1


@pytest.mark.asyncio
async def test_service_answer_compare_and_swap_error_still_closes_client():
    persistence = _FakePersistence()
    client = _FakeClient()
    persistence.answer_prepared = _plan(client)
    persistence.commit_error = BackendError(ErrorCode.WORKFLOW_CONFLICT)
    service = SchoolResearchService(persistence=persistence, clock=lambda: NOW)

    with pytest.raises(BackendError) as exc_info:
        await service.answer(
            _actor(),
            "SESSION_synthetic_1",
            item_id="item-1",
            raw_value=1,
            expected_state_version=7,
            idempotency=("answer-key", "c" * 64, "d" * 64),
        )

    assert exc_info.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert client.closed == 1


@pytest.mark.asyncio
async def test_service_rejects_nonstudent_before_persistence():
    persistence = _FakePersistence()
    service = SchoolResearchService(persistence=persistence)

    with pytest.raises(BackendError) as exc_info:
        await service.start_task(
            _actor(BackendRole.TEACHER),
            "TASK_synthetic_1",
            trace_id="TRACE_synthetic",
            idempotency=("k", "f", "s"),
        )

    assert exc_info.value.code is ErrorCode.FORBIDDEN
    assert persistence.calls == []


@pytest.mark.asyncio
async def test_service_maps_cat_failures_to_stable_error_and_closes_client():
    persistence = _FakePersistence()
    client = _FakeClient()
    client.resume_error = ResearchCATClientError("dependency_unavailable")
    persistence.resume_plan = _plan(client)
    service = SchoolResearchService(persistence=persistence, clock=lambda: NOW)

    with pytest.raises(BackendError) as exc_info:
        await service.resume_session(_actor(), "SESSION_synthetic_1")

    assert exc_info.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE
    assert "dependency_unavailable" not in exc_info.value.detail
    assert client.closed == 1


class _FakeRouteService:
    def __init__(self):
        self.calls = []
        self.value = ResearchL1SessionDto(
            session_ref="SESSION_synthetic_1",
            status="IN_PROGRESS",
            state_version=1,
            items_answered=0,
            research_only=True,
            resume_required=False,
            stop_reason=None,
            question=None,
            completion=None,
        )

    async def start_task(self, actor, task_ref, **kwargs):
        self.calls.append(("start", actor, task_ref, kwargs))
        return self.value

    async def resume_session(self, actor, session_ref):
        self.calls.append(("resume", actor, session_ref))
        return self.value

    async def answer(self, actor, session_ref, **kwargs):
        self.calls.append(("answer", actor, session_ref, kwargs))
        return self.value


def _mounted_app(actor: Actor, service: Any = ...):
    app = FastAPI()
    container = SimpleNamespace(
        settings=SimpleNamespace(
            auth=SimpleNamespace(csrf_header_name="X-CSRF-Token"),
            allowed_origins=[],
        )
    )
    if service is not ...:
        container.school_research = service
    app.state.container = container
    app.add_exception_handler(BackendError, backend_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    from fastapi.exceptions import RequestValidationError

    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.include_router(router, prefix="/api/v1")

    @app.middleware("http")
    async def request_context(request, call_next):
        request.state.request_context = make_context(request)
        return await call_next(request)

    async def provide_actor(request: Request):
        request.state.session = SimpleNamespace(csrf_token="synthetic-csrf")
        return actor

    app.dependency_overrides[current_actor] = provide_actor
    return app


async def _post(app, path, *, payload=None, headers=None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post(path, json=payload, headers=headers)


@pytest.mark.asyncio
async def test_router_role_check_precedes_missing_service_error():
    app = _mounted_app(_actor(BackendRole.TEACHER))
    app.dependency_overrides[csrf_protected] = lambda: _actor(BackendRole.TEACHER)

    response = await _post(
        app,
        "/api/v1/school/research/tasks/TASK_synthetic_1/start",
        headers={"Idempotency-Key": "synthetic-key"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


@pytest.mark.asyncio
async def test_router_returns_stable_503_when_service_is_not_configured():
    app = _mounted_app(_actor())
    app.dependency_overrides[csrf_protected] = lambda: _actor()

    response = await _post(
        app,
        "/api/v1/school/research/tasks/TASK_synthetic_1/start",
        headers={"Idempotency-Key": "synthetic-key"},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "dependency_unavailable"
    assert "profile" not in response.text


@pytest.mark.asyncio
async def test_router_real_csrf_dependency_denies_write_before_service():
    service = _FakeRouteService()
    app = _mounted_app(_actor(), service)

    missing = await _post(
        app,
        "/api/v1/school/research/tasks/TASK_synthetic_1/start",
        headers={"Idempotency-Key": "synthetic-key"},
    )

    assert missing.status_code == 403, missing.text
    assert missing.json()["code"] == "csrf_failed", missing.text
    assert service.calls == []


@pytest.mark.asyncio
async def test_router_start_uses_canonical_idempotency_and_envelope():
    service = _FakeRouteService()
    app = _mounted_app(_actor(), service)
    app.dependency_overrides[csrf_protected] = lambda: _actor()
    key = "synthetic-start-key"

    response = await _post(
        app,
        "/api/v1/school/research/tasks/TASK_synthetic_1/start",
        payload={},
        headers={"Idempotency-Key": key, "X-Trace-ID": "TRACE_research_api"},
    )

    assert response.status_code == 200
    call = service.calls[0]
    assert call[0:3] == ("start", _actor(), "TASK_synthetic_1")
    assert call[3]["idempotency"] == (
        key,
        fingerprint({"task_ref": "TASK_synthetic_1"}),
        fingerprint(
            {
                "actor": _actor().user_id,
                "school_id": _actor().school_id,
                "school_ref": _actor().school_ref,
                "role": _actor().role.value,
                "operation": "research:task:TASK_synthetic_1:start",
            }
        ),
    )
    assert response.json()["trace_id"] == "TRACE_research_api"
    assert set(response.json()["data"]) == {
        "session_ref",
        "status",
        "state_version",
        "items_answered",
        "research_only",
        "resume_required",
        "stop_reason",
        "question",
        "completion",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {
            "item_id": "item-1",
            "raw_value": True,
            "expected_state_version": 1,
        },
        {
            "item_id": "item-1",
            "raw_value": 1,
            "expected_state_version": 1,
            "signed_snapshot": "not-accepted",
        },
        {
            "item_id": "item-1",
            "raw_value": 1,
            "expected_state_version": 1,
            "profile_sha256": "a" * 64,
        },
    ],
)
async def test_router_rejects_boolean_categories_and_private_extra_fields(payload):
    service = _FakeRouteService()
    app = _mounted_app(_actor(), service)
    app.dependency_overrides[csrf_protected] = lambda: _actor()

    response = await _post(
        app,
        "/api/v1/school/research/sessions/SESSION_synthetic_1/answers",
        payload=payload,
        headers={"Idempotency-Key": "synthetic-answer-key"},
    )

    assert response.status_code == 422
    assert service.calls == []


@pytest.mark.asyncio
async def test_router_answer_fingerprint_includes_version_and_distinct_operation_scope():
    service = _FakeRouteService()
    app = _mounted_app(_actor(), service)
    app.dependency_overrides[csrf_protected] = lambda: _actor()
    payload = {"item_id": "item-1", "raw_value": 1, "expected_state_version": 9}
    key = "synthetic-answer-key"

    response = await _post(
        app,
        "/api/v1/school/research/sessions/SESSION_synthetic_1/answers",
        payload=payload,
        headers={"Idempotency-Key": key},
    )

    assert response.status_code == 200
    kwargs = service.calls[0][3]
    assert kwargs["idempotency"] == (
        key,
        fingerprint(payload),
        fingerprint(
            {
                "actor": _actor().user_id,
                "school_id": _actor().school_id,
                "school_ref": _actor().school_ref,
                "role": _actor().role.value,
                "operation": "research:session:SESSION_synthetic_1:answer",
            }
        ),
    )


@pytest.mark.asyncio
async def test_router_requires_idempotency_key_before_calling_start_service():
    service = _FakeRouteService()
    app = _mounted_app(_actor(), service)
    app.dependency_overrides[csrf_protected] = lambda: _actor()

    response = await _post(
        app,
        "/api/v1/school/research/tasks/TASK_synthetic_1/start",
        payload={},
    )

    assert response.status_code == 422
    assert service.calls == []


@pytest.mark.asyncio
async def test_router_resume_is_csrf_protected_but_has_no_write_idempotency_requirement():
    service = _FakeRouteService()
    app = _mounted_app(_actor(), service)
    app.dependency_overrides[csrf_protected] = lambda: _actor()

    response = await _post(
        app,
        "/api/v1/school/research/sessions/SESSION_synthetic_1/resume",
        payload={},
    )

    assert response.status_code == 200
    assert service.calls == [("resume", _actor(), "SESSION_synthetic_1")]
