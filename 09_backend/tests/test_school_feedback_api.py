from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from smhai_backend.core.errors import (
    BackendError,
    backend_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from smhai_backend.core.idempotency import fingerprint
from smhai_backend.core.request_context import make_context
from smhai_backend.domains.auth.dependencies import csrf_protected, current_actor
from smhai_backend.domains.models import BackendRole
from smhai_backend.domains.school_feedback.router import router
from smhai_backend.domains.school_feedback.service import SchoolFeedbackService

from .test_school_feedback_service import FakePersistence, actor


def mounted_app(role: BackendRole):
    app = FastAPI()
    persistence = FakePersistence()
    server_actor = actor(
        role,
        subject_id="SUBJ_synthetic_student" if role is BackendRole.STUDENT else None,
    )
    app.state.container = SimpleNamespace(
        school_feedback=SchoolFeedbackService(persistence=persistence)
    )
    app.add_exception_handler(BackendError, backend_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    from fastapi.exceptions import RequestValidationError

    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.include_router(router, prefix="/api/v1")

    @app.middleware("http")
    async def request_context(request, call_next):
        request.state.request_context = make_context(request)
        return await call_next(request)

    async def provide_actor():
        return server_actor

    app.dependency_overrides[current_actor] = provide_actor
    app.dependency_overrides[csrf_protected] = provide_actor
    return app, persistence, server_actor


@pytest.mark.parametrize("role", [BackendRole.TEACHER, BackendRole.ADMIN, BackendRole.REVIEWER])
async def test_teacher_admin_and_reviewer_cannot_access_either_feedback_surface(role):
    app, persistence, _ = mounted_app(role)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        specialist_paths = [
            ("GET", "/api/v1/school/feedback/cases/CASE_synthetic_1", None),
            (
                "POST",
                "/api/v1/school/feedback/cases/CASE_synthetic_1",
                {
                    "expected_case_version": 3,
                    "title": "合成标题",
                    "body": "合成反馈",
                },
            ),
            (
                "POST",
                "/api/v1/school/feedback/FEED_synthetic_1/publish",
                {
                    "expected_case_version": 3,
                    "expected_state_version": 1,
                },
            ),
            (
                "POST",
                "/api/v1/school/feedback/FEED_synthetic_1/revoke",
                {
                    "expected_case_version": 3,
                    "expected_state_version": 2,
                },
            ),
        ]
        student_paths = [
            ("GET", "/api/v1/school/feedback/student", None),
            ("GET", "/api/v1/school/feedback/student/FEED_synthetic_1", None),
        ]
        for method, path, body in specialist_paths + student_paths:
            headers = {"Idempotency-Key": "synthetic-feedback-key"} if method == "POST" else None
            response = await client.request(method, path, json=body, headers=headers)
            assert response.status_code == 403
            assert "合成反馈" not in response.text
    assert persistence.calls == []


@pytest.mark.parametrize(
    ("role", "path"),
    [
        (BackendRole.STUDENT, "/api/v1/school/feedback/cases/CASE_synthetic_1"),
        (BackendRole.PSYCHOLOGICAL_SPECIALIST, "/api/v1/school/feedback/student"),
    ],
)
async def test_wrong_primary_role_is_denied_at_api_boundary(role, path):
    app, persistence, _ = mounted_app(role)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(path)
    assert response.status_code == 403
    assert persistence.calls == []


async def test_write_requires_stable_idempotency_key_and_strict_body_before_port_call():
    app, persistence, _ = mounted_app(BackendRole.PSYCHOLOGICAL_SPECIALIST)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        url = "/api/v1/school/feedback/cases/CASE_synthetic_1"
        missing_key = await client.post(
            url, json={"expected_case_version": 3, "title": "合成标题", "body": "合成反馈"}
        )
        unknown_scope = await client.post(
            url,
            json={
                "expected_case_version": 3,
                "title": "合成标题",
                "body": "合成反馈",
                "school_id": 17,
            },
            headers={"Idempotency-Key": "synthetic-feedback-key"},
        )
    assert missing_key.status_code == 422
    assert unknown_scope.status_code == 422
    assert persistence.calls == []


async def test_create_route_passes_stable_body_scope_and_trace_to_persistence():
    app, persistence, server_actor = mounted_app(BackendRole.PSYCHOLOGICAL_SPECIALIST)
    transport = httpx.ASGITransport(app=app)
    payload = {
        "expected_case_version": 3,
        "title": "合成学习支持标题",
        "body": "合成教育支持反馈内容。",
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/school/feedback/cases/CASE_synthetic_1",
            json=payload,
            headers={
                "Idempotency-Key": "synthetic-feedback-create",
                "X-Trace-ID": "TRACE_feedback_api_test",
            },
        )
    assert response.status_code == 200
    call = persistence.calls[-1]
    idempotency = call[6]
    assert call[:6] == (
        "create",
        server_actor,
        "CASE_synthetic_1",
        3,
        "合成学习支持标题",
        "合成教育支持反馈内容。",
    )
    assert idempotency[0] == "synthetic-feedback-create"
    assert idempotency[1] == fingerprint(payload)
    assert idempotency[2] == fingerprint(
        {
            "actor": server_actor.user_id,
            "school_id": server_actor.school_id,
            "school_ref": server_actor.school_ref,
            "role": server_actor.role.value,
            "operation": "create:CASE_synthetic_1",
        }
    )
    assert call[7] == response.json()["trace_id"] == "TRACE_feedback_api_test"


async def test_api_projections_are_allowlisted_for_specialist_and_student():
    specialist_app, specialist_persistence, _ = mounted_app(BackendRole.PSYCHOLOGICAL_SPECIALIST)
    student_app, student_persistence, _ = mounted_app(BackendRole.STUDENT)
    specialist_transport = httpx.ASGITransport(app=specialist_app)
    student_transport = httpx.ASGITransport(app=student_app)
    async with (
        httpx.AsyncClient(
            transport=specialist_transport, base_url="http://testserver"
        ) as specialist_client,
        httpx.AsyncClient(
            transport=student_transport, base_url="http://testserver"
        ) as student_client,
    ):
        specialist = await specialist_client.get("/api/v1/school/feedback/cases/CASE_synthetic_1")
        student = await student_client.get("/api/v1/school/feedback/student/FEED_synthetic_1")
    assert specialist.status_code == 200
    assert student.status_code == 200
    specialist_data = specialist.json()["data"]["items"][0]
    student_data = student.json()["data"]
    assert specialist_data["level"] == student_data["level"] == "L3"
    assert specialist_data["synthetic_only"] is student_data["synthetic_only"] is True
    assert not {"case_ref", "case_version", "review_note", "ciphertext"}.intersection(student_data)
    assert specialist_persistence.calls and student_persistence.calls
