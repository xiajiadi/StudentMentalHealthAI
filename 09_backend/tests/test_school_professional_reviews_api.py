"""Module wiring checks; fake persistence does not prove native tenant authorization."""

from __future__ import annotations

import pytest

from smhai_backend.domains.auth.dependencies import csrf_protected, current_actor
from smhai_backend.domains.models import BackendRole
from smhai_backend.domains.professional_reviews.service import SchoolProfessionalReviewService

from .conftest import login
from .test_school_professional_reviews_service import FakePersistence, actor


@pytest.mark.parametrize("username", ["student_a", "teacher", "reviewer"])
async def test_legacy_authenticated_roles_gain_no_school_review_access(app, client, username):
    await login(client, username)
    response = await client.get("/api/v1/school/professional-reviews/tasks/TASK_synthetic/cases")
    assert response.status_code == 403
    assert "review_note" not in response.text


async def test_review_write_uses_real_csrf_dependency_before_persistence(app, client):
    await login(client)
    response = await client.post(
        "/api/v1/school/professional-reviews/tasks/TASK_synthetic/cases",
        json={"enrollment_ref": "ENROLL_synthetic"},
        headers={"Idempotency-Key": "synthetic-case-create"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "csrf_failed"


async def test_review_routes_are_registered_outside_frozen_openapi(app, client):
    response = await client.get("/api/v1/school/professional-reviews/tasks/TASK_synthetic/cases")
    assert response.status_code == 401
    assert not any("professional-reviews" in path for path in app.openapi()["paths"])


@pytest.mark.parametrize(
    ("role", "path", "payload", "expected_method"),
    [
        (
            BackendRole.ADMIN,
            "assignments",
            {"specialist_user_id": "USER_synthetic_specialist"},
            "assign",
        ),
        (
            BackendRole.PSYCHOLOGICAL_SPECIALIST,
            "cases",
            {"enrollment_ref": "ENROLL_synthetic_1"},
            "ensure_case",
        ),
        (
            BackendRole.PSYCHOLOGICAL_SPECIALIST,
            "cases/CASE_synthetic_1/open",
            {"expected_version": 1},
            "open_case",
        ),
        (
            BackendRole.PSYCHOLOGICAL_SPECIALIST,
            "cases/CASE_synthetic_1/decision",
            {"expected_version": 2, "decision": "APPROVED", "note": "合成工作流复核记录。"},
            "process_case",
        ),
    ],
)
async def test_write_wiring_preserves_actor_key_and_strict_date_projection(
    app,
    client,
    role,
    path,
    payload,
    expected_method,
):
    persistence = FakePersistence()
    app.state.container.professional_reviews = SchoolProfessionalReviewService(
        persistence=persistence
    )
    server_actor = actor(role)

    async def provide_actor():
        return server_actor

    # Only these wiring checks replace auth; the separate test above exercises
    # the actual CSRF dependency. Native role/assignment proof is separate.
    app.dependency_overrides[current_actor] = provide_actor
    app.dependency_overrides[csrf_protected] = provide_actor
    url = f"/api/v1/school/professional-reviews/tasks/TASK_synthetic_1/{path}"
    missing_key = await client.post(url, json=payload)
    assert missing_key.status_code == 422
    assert persistence.calls == []
    result = await client.post(url, json=payload, headers={"Idempotency-Key": "synthetic-api-key"})
    assert result.status_code == 200
    data = result.json()["data"]
    assert data.get("publication_status", "NOT_PUBLISHED") == "NOT_PUBLISHED"
    assert not {"raw_answers", "report", "ciphertext"}.intersection(data)
    assert persistence.calls[-1][0] == expected_method
    assert persistence.calls[-1][1] is server_actor
    assert isinstance(data.get("created_at", data.get("assigned_at")), str)


async def test_unknown_private_fields_are_rejected_before_service_call(app, client):
    persistence = FakePersistence()
    app.state.container.professional_reviews = SchoolProfessionalReviewService(
        persistence=persistence
    )

    async def provide_actor():
        return actor(BackendRole.PSYCHOLOGICAL_SPECIALIST)

    app.dependency_overrides[csrf_protected] = provide_actor
    result = await client.post(
        "/api/v1/school/professional-reviews/tasks/TASK_synthetic/cases",
        json={"enrollment_ref": "ENROLL_synthetic", "school_id": 999, "publish": True},
        headers={"Idempotency-Key": "synthetic-invalid-body"},
    )
    assert result.status_code == 422
    assert persistence.calls == []
