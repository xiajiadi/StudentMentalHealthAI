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
from smhai_backend.domains.school_research_education_candidates.router import router
from smhai_backend.domains.school_research_education_candidates.service import (
    SchoolResearchEducationCandidateService,
)

from .test_school_research_education_candidates_service import FakePersistence, actor


def mounted_app(role: BackendRole):
    app = FastAPI()
    persistence = FakePersistence()
    app.state.container = SimpleNamespace(
        school_research_education_candidates=SchoolResearchEducationCandidateService(
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
        return actor(role)

    app.dependency_overrides[current_actor] = provide_actor
    return app, persistence


@pytest.mark.parametrize(
    "role",
    [BackendRole.STUDENT, BackendRole.TEACHER, BackendRole.ADMIN, BackendRole.REVIEWER],
)
async def test_non_specialist_cannot_read_enqueue_or_resolve(role):
    app, persistence = mounted_app(role)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        root = "/api/v1/school/research-education-candidates"
        tasks = await client.get(f"{root}/tasks")
        listed = await client.get(f"{root}/tasks/TASK_demo/candidates")
        jobs = await client.get(f"{root}/tasks/TASK_demo/generation-jobs")
        detail = await client.get(f"{root}/tasks/TASK_demo/candidates/REEDUC_synthetic_1")
        queued = await client.post(
            f"{root}/tasks/TASK_demo/enqueue",
            json={"limit": 2, "offset": 0},
            headers={"Idempotency-Key": "denied", "X-CSRF-Token": "synthetic-csrf-token"},
        )
        resolved = await client.post(
            f"{root}/tasks/TASK_demo/candidates/REEDUC_synthetic_1/resolve",
            json={"expected_state_version": 1, "target": "ADOPTED"},
            headers={"Idempotency-Key": "denied", "X-CSRF-Token": "synthetic-csrf-token"},
        )
    assert [
        tasks.status_code,
        listed.status_code,
        jobs.status_code,
        detail.status_code,
        queued.status_code,
        resolved.status_code,
    ] == [403] * 6
    assert persistence.calls == []


async def test_specialist_api_is_bounded_csrf_idempotent_and_payload_closed():
    app, persistence = mounted_app(BackendRole.PSYCHOLOGICAL_SPECIALIST)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        root = "/api/v1/school/research-education-candidates"
        tasks = await client.get(f"{root}/tasks")
        listed = await client.get(f"{root}/tasks/TASK_demo/candidates?offset=3&limit=7")
        jobs = await client.get(f"{root}/tasks/TASK_demo/generation-jobs?offset=2&limit=7")
        detail = await client.get(f"{root}/tasks/TASK_demo/candidates/REEDUC_synthetic_1")
        missing_idem = await client.post(
            f"{root}/tasks/TASK_demo/enqueue",
            json={"limit": 2},
            headers={"X-CSRF-Token": "synthetic-csrf-token"},
        )
        missing_csrf = await client.post(
            f"{root}/tasks/TASK_demo/enqueue",
            json={"limit": 2},
            headers={"Idempotency-Key": "batch"},
        )
        queued = await client.post(
            f"{root}/tasks/TASK_demo/enqueue",
            json={"limit": 2, "offset": 9},
            headers={
                "Idempotency-Key": "batch",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )
        bad_payload = await client.post(
            f"{root}/tasks/TASK_demo/enqueue",
            json={"limit": 101},
            headers={
                "Idempotency-Key": "batch-bad",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )
        resolved = await client.post(
            f"{root}/tasks/TASK_demo/candidates/REEDUC_synthetic_1/resolve",
            json={"expected_state_version": 1, "target": "ADOPTED"},
            headers={
                "Idempotency-Key": "resolve",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )
        unapproved_publish_route = await client.post(
            f"{root}/tasks/TASK_demo/candidates/REEDUC_synthetic_1/publish",
            json={},
            headers={
                "Idempotency-Key": "publish",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )

    assert tasks.status_code == 200
    assert listed.status_code == 200
    assert listed.json()["data"]["offset"] == 3
    assert listed.json()["data"]["limit"] == 7
    assert jobs.status_code == 200
    jobs_data = jobs.json()["data"]
    assert jobs_data["offset"] == 2
    assert jobs_data["limit"] == 7
    assert jobs_data["policy_version"] == "RESEARCH_GENERAL_EDUCATION_DRAFT_V1"
    assert set(jobs_data["status_counts"]) == {
        "QUEUED", "LEASED", "RETRY", "HELD", "ABSTAINED", "REVIEW_REQUIRED",
        "CRISIS_ROUTED", "FAILED", "CANCELLED",
    }
    assert not ({"subject_id", "lease_owner", "lease_token", "candidate_payload"}
                & set(jobs_data["items"][0]))
    assert detail.status_code == 200
    detail_data = detail.json()["data"]
    assert detail_data["candidate_payload"]["schema_version"] == (
        "school-research-general-education-candidate.v1"
    )
    assert detail_data["student_feedback_eligible"] is False
    assert not ({"subject_id", "score", "answers", "response_text"} & set(detail_data))
    assert missing_idem.status_code == 422
    assert missing_csrf.status_code == 403
    assert queued.status_code == 200
    assert queued.json()["data"]["policy_version"] == "RESEARCH_GENERAL_EDUCATION_DRAFT_V1"
    assert queued.json()["data"]["student_feedback_eligible"] is False
    assert bad_payload.status_code == 422
    assert resolved.status_code == 200
    assert resolved.json()["data"]["status"] == "ADOPTED"
    assert resolved.json()["data"]["student_feedback_eligible"] is False
    assert unapproved_publish_route.status_code in {404, 405}
    assert [call[0] for call in persistence.calls] == [
        "tasks", "list", "jobs", "get", "queue", "resolve"
    ]
