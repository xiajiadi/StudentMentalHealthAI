from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from smhai_backend.core.config import BackendSettings
from smhai_backend.core.errors import (
    BackendError,
    backend_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from smhai_backend.core.request_context import make_context
from smhai_backend.domains.auth.dependencies import current_actor
from smhai_backend.domains.models import BackendRole
from smhai_backend.domains.school_research_programme_candidates.router import router
from smhai_backend.domains.school_research_programme_candidates.service import (
    SchoolResearchProgrammeCandidateService,
)

from .test_school_research_programme_candidates_service import FakePersistence, actor


def mounted_app(role: BackendRole):
    app = FastAPI()
    persistence = FakePersistence()
    server_actor = actor(role)
    app.state.container = SimpleNamespace(
        school_research_programme_candidates=SchoolResearchProgrammeCandidateService(
            persistence=persistence
        ),
        settings=BackendSettings(),
    )
    app.add_exception_handler(BackendError, backend_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    from fastapi.exceptions import RequestValidationError

    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.include_router(router, prefix="/api/v1")

    @app.middleware("http")
    async def request_context(request, call_next):
        request.state.request_context = make_context(request)
        request.state.session = SimpleNamespace(csrf_token="synthetic-csrf-token")
        return await call_next(request)

    async def provide_actor():
        return server_actor

    app.dependency_overrides[current_actor] = provide_actor
    return app, persistence


@pytest.mark.parametrize(
    "role",
    [BackendRole.STUDENT, BackendRole.TEACHER, BackendRole.ADMIN, BackendRole.REVIEWER],
)
async def test_non_specialist_cannot_read_or_change_staff_candidates(role):
    app, persistence = mounted_app(role)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        listed = await client.get("/api/v1/school/research-programme-candidates/tasks/TASK_demo")
        detail = await client.get(
            "/api/v1/school/research-programme-candidates/tasks/TASK_demo/RPCAND_synthetic_1"
        )
        adopted = await client.post(
            "/api/v1/school/research-programme-candidates/tasks/TASK_demo/RPCAND_synthetic_1/adopt",
            json={"expected_state_version": 1},
            headers={
                "Idempotency-Key": "candidate-adopt-key",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )
    assert [listed.status_code, detail.status_code, adopted.status_code] == [403, 403, 403]
    assert persistence.calls == []


async def test_specialist_candidate_review_has_closed_scope_and_staff_only_adoption():
    app, persistence = mounted_app(BackendRole.PSYCHOLOGICAL_SPECIALIST)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        root = "/api/v1/school/research-programme-candidates/tasks/TASK_demo"
        listed = await client.get(root)
        detail = await client.get(f"{root}/RPCAND_synthetic_1")
        bad_adopt = await client.post(
            f"{root}/RPCAND_synthetic_1/adopt",
            json={"expected_state_version": 1, "case_ref": "not-allowed"},
            headers={
                "Idempotency-Key": "candidate-bad-key",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )
        missing_csrf = await client.post(
            f"{root}/RPCAND_synthetic_1/adopt",
            json={"expected_state_version": 1},
            headers={"Idempotency-Key": "candidate-no-csrf"},
        )
        adopted = await client.post(
            f"{root}/RPCAND_synthetic_1/adopt",
            json={"expected_state_version": 1},
            headers={
                "Idempotency-Key": "candidate-adopt-key",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )
        forged_student_route = await client.get(
            "/api/v1/school/research-programme-candidates/student"
        )
        public_create_route = await client.post(
            f"{root}/generate",
            json={"candidate": "browser cannot create candidate"},
            headers={
                "Idempotency-Key": "candidate-create-key",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )
    assert listed.status_code == 200
    assert listed.json()["data"]["items"][0]["student_feedback_eligible"] is False
    assert listed.json()["data"]["items"][0]["output_boundary"] == "STAFF_REFERENCE_ONLY"
    assert detail.status_code == 200
    detail_row = detail.json()["data"]
    assert detail_row["output_boundary"] == "STAFF_REFERENCE_ONLY"
    assert detail_row["student_feedback_eligible"] is False
    assert detail_row["content"]["content_origin"] == "VERIFIED_SOURCE_METADATA"
    assert detail_row["content"]["generation_mode"] == "MODEL_SOURCE_SELECTION"
    assert detail_row["content"]["citations"][0]["citation_id"] == "S1"
    assert bad_adopt.status_code == 422
    assert missing_csrf.status_code == 403
    assert adopted.status_code == 200
    assert adopted.json()["data"]["status"] == "ADOPTED"
    assert adopted.json()["data"]["student_feedback_eligible"] is False
    assert adopted.json()["data"]["output_boundary"] == "STAFF_REFERENCE_ONLY"
    assert forged_student_route.status_code == 404
    assert public_create_route.status_code == 405
    assert [call[0] for call in persistence.calls] == ["list", "get", "adopt"]


async def test_generation_queue_is_specialist_csrf_idempotency_and_policy_closed():
    app, persistence = mounted_app(BackendRole.STUDENT)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        root = "/api/v1/school/research-programme-candidates/tasks/TASK_demo/queue-generation"
        denied = await client.post(root, json={})
    assert denied.status_code == 403
    assert persistence.calls == []

    app, persistence = mounted_app(BackendRole.PSYCHOLOGICAL_SPECIALIST)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        root = "/api/v1/school/research-programme-candidates/tasks/TASK_demo/queue-generation"
        no_idempotency = await client.post(
            root, json={}, headers={"X-CSRF-Token": "synthetic-csrf-token"}
        )
        no_csrf = await client.post(root, json={}, headers={"Idempotency-Key": "queue-key"})
        queued = await client.post(
            root,
            json={},
            headers={
                "Idempotency-Key": "queue-key",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )
        extra = await client.post(
            root,
            json={"session_ref": "client-cannot-select-session"},
            headers={
                "Idempotency-Key": "queue-extra",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )
    assert no_idempotency.status_code == 422
    assert no_csrf.status_code == 403
    assert queued.status_code == 200
    assert queued.json()["data"]["status"] == "QUEUED"
    assert queued.json()["data"]["student_feedback_eligible"] is False
    assert "policy_hash" not in queued.json()["data"]
    assert extra.status_code == 422
    assert [call[0] for call in persistence.calls] == ["queue"]
