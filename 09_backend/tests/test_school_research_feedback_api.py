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
from smhai_backend.domains.school_research_feedback.router import router
from smhai_backend.domains.school_research_feedback.service import (
    SchoolResearchFeedbackService,
)

from .test_school_research_feedback_service import FakePersistence, actor


def mounted_app(role: BackendRole):
    app = FastAPI()
    persistence = FakePersistence()
    server_actor = actor(
        role,
        subject_id="SUBJ_synthetic_1" if role is BackendRole.STUDENT else None,
    )
    app.state.container = SimpleNamespace(
        school_research_feedback=SchoolResearchFeedbackService(persistence=persistence),
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
    [BackendRole.TEACHER, BackendRole.ADMIN, BackendRole.REVIEWER],
)
async def test_non_specialist_roles_cannot_read_or_write_research_reviews(role):
    app, persistence = mounted_app(role)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/v1/school/research-feedback/tasks")
        assert response.status_code == 403
        response = await client.post(
            "/api/v1/school/research-feedback/tasks/TASK_synthetic_1/cases",
            json={"session_ref": "RSESS_synthetic_1"},
            headers={
                "Idempotency-Key": "synthetic-research-feedback-key",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )
        assert response.status_code == 403
    assert persistence.calls == []


async def test_research_case_create_requires_closed_body_and_idempotency_key():
    app, persistence = mounted_app(BackendRole.PSYCHOLOGICAL_SPECIALIST)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        url = "/api/v1/school/research-feedback/tasks/TASK_synthetic_1/cases"
        extra = await client.post(
            url,
            json={"session_ref": "RSESS_synthetic_1", "assessment_ref": "ASSESS_not_allowed"},
            headers={
                "Idempotency-Key": "synthetic-research-feedback-key",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )
        assert extra.status_code == 422
        assert persistence.calls == []

        missing_key = await client.post(
            url,
            json={"session_ref": "RSESS_synthetic_1"},
            headers={"X-CSRF-Token": "synthetic-csrf-token"},
        )
        assert missing_key.status_code == 422
        assert persistence.calls == []

        created = await client.post(
            url,
            json={"session_ref": "RSESS_synthetic_1"},
            headers={
                "Idempotency-Key": "synthetic-research-feedback-key",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )
        boolean_version = await client.post(
            "/api/v1/school/research-feedback/tasks/TASK_synthetic_1/cases/SRV_synthetic_1/decision",
            json={"expected_version": True, "status": "IN_REVIEW", "note": "合成复核"},
            headers={
                "Idempotency-Key": "synthetic-research-feedback-bool-version",
                "X-CSRF-Token": "synthetic-csrf-token",
            },
        )
    assert created.status_code == 200
    assert created.json()["data"]["case_ref"] == "SRV_synthetic_1"
    assert "assessment_ref" not in created.json()["data"]
    assert boolean_version.status_code == 422
    assert persistence.calls[-1][0] == "create_case"


async def test_research_feedback_write_requires_real_csrf_dependency():
    app, persistence = mounted_app(BackendRole.PSYCHOLOGICAL_SPECIALIST)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/school/research-feedback/tasks/TASK_synthetic_1/cases",
            json={"session_ref": "RSESS_synthetic_1"},
            headers={"Idempotency-Key": "synthetic-research-feedback-key"},
        )
    assert response.status_code == 403
    assert response.json()["code"] == "csrf_failed"
    assert persistence.calls == []


async def test_student_surface_returns_only_published_research_feedback_projection():
    app, persistence = mounted_app(BackendRole.STUDENT)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/v1/school/research-feedback/student")
    assert response.status_code == 200
    row = response.json()["data"]["items"][0]
    assert row["status"] == "PUBLISHED"
    assert row["feedback_kind"] == "GENERAL_EDUCATIONAL_SUPPORT"
    assert row["research_only"] is True
    assert row["psychological_interpretation_allowed"] is False
    assert row["publication_status"] == "not_approved_for_publication_or_operational_use"
    assert "case_ref" not in row
    assert "assessment_ref" not in row
    assert set(row) == {
        "feedback_ref",
        "session_ref",
        "feedback_kind",
        "purpose",
        "research_only",
        "psychological_interpretation_allowed",
        "publication_status",
        "content_revision",
        "state_version",
        "status",
        "title",
        "body",
        "citations",
        "source_cards",
        "source_manifest_sha256",
        "created_at",
        "published_at",
    }
    assert persistence.calls[0][0] == "student_list"
