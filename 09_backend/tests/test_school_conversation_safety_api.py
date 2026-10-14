from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from smhai_backend.app_factory import create_app
from smhai_backend.core.config import BackendSettings
from smhai_backend.core.errors import (
    BackendError,
    backend_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from smhai_backend.core.request_context import make_context
from smhai_backend.domains.auth.dependencies import current_actor
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.domains.school_conversation_safety.router import (
    router,
    student_router,
)
from smhai_backend.domains.school_conversation_safety.service import (
    SchoolConversationSafetyService,
)

_NOW = datetime(2026, 10, 15, 0, 0, tzinfo=UTC)


def actor(role: BackendRole, *, subject_id: str | None = None) -> Actor:
    return Actor(
        user_id=f"USER_synthetic_{role.value.lower()}",
        username="synthetic-safety-review",
        role=role,
        subject_id=subject_id,
        scope_profile="school_tenant",
        school_id=17,
        school_ref="SCHOOL_synthetic",
    )


def admin_row(**overrides):
    return {
        "case_ref": "SCS_synthetic_1",
        "status": "UNASSIGNED_PENDING",
        "state_version": 1,
        "class_ref": None,
        "created_at": _NOW,
        "updated_at": _NOW,
        "assigned_at": None,
        **overrides,
    }


def specialist_row(**overrides):
    return {
        "case_ref": "SCS_synthetic_1",
        "class_ref": "CLASS_synthetic_1",
        "action": "CRISIS_ROUTE",
        "reason_codes": ["SYNTHETIC_TEST_CODE"],
        "status": "ASSIGNED",
        "state_version": 2,
        "decision_code": None,
        "created_at": _NOW,
        "updated_at": _NOW,
        "assigned_at": _NOW,
        "reviewed_at": None,
        "closed_at": None,
        "review_note": None,
        **overrides,
    }


class FakePersistence:
    def __init__(self):
        self.calls = []

    async def admin_list_unassigned(self, actor_arg, *, offset, limit):
        self.calls.append(("admin_list_unassigned", actor_arg, offset, limit))
        row = admin_row()
        row.pop("assigned_at")
        return {"items": [row], "total": 1}

    async def specialist_list_assigned(self, actor_arg, *, offset, limit):
        self.calls.append(("specialist_list_assigned", actor_arg, offset, limit))
        row = specialist_row()
        row.pop("review_note")
        return {"items": [row], "total": 3}

    async def specialist_get(self, actor_arg, case_ref, *, include_note):
        self.calls.append(("specialist_get", actor_arg, case_ref, include_note))
        return specialist_row()

    async def admin_assign(self, actor_arg, case_ref, **kwargs):
        self.calls.append(("admin_assign", actor_arg, case_ref, kwargs))
        return {
            "case_ref": case_ref,
            "status": "ASSIGNED",
            "state_version": 2,
            "class_ref": kwargs["class_ref"],
            "assigned_at": _NOW,
            "updated_at": _NOW,
        }

    async def specialist_save_note(self, actor_arg, case_ref, **kwargs):
        self.calls.append(("specialist_save_note", actor_arg, case_ref, kwargs))
        return specialist_row(
            status="IN_REVIEW",
            state_version=kwargs["expected_version"] + 1,
            review_note=kwargs["note"],
        )

    async def specialist_transition(self, actor_arg, case_ref, **kwargs):
        self.calls.append(("specialist_transition", actor_arg, case_ref, kwargs))
        return specialist_row(
            status=kwargs["status"],
            state_version=kwargs["expected_version"] + 1,
            decision_code=kwargs["decision_code"],
        )

    async def student_status(self, actor_arg, conversation_ref, *, target_role):
        self.calls.append(("student_status", actor_arg, conversation_ref, target_role))
        return {
            "case_ref": "SCS_synthetic_1",
            "action": "CRISIS_ROUTE",
            "status": "UNASSIGNED_PENDING",
            "created_at": _NOW,
            "updated_at": _NOW,
        }


def mounted_app(role: BackendRole, *, subject_id: str | None = None):
    app = FastAPI()
    persistence = FakePersistence()
    server_actor = actor(role, subject_id=subject_id)
    app.state.container = SimpleNamespace(
        school_conversation_safety=SchoolConversationSafetyService(persistence=persistence),
        settings=BackendSettings(),
    )
    app.add_exception_handler(BackendError, backend_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.include_router(router, prefix="/api/v1")
    app.include_router(student_router, prefix="/api/v1")

    @app.middleware("http")
    async def request_context(request, call_next):
        request.state.request_context = make_context(request)
        request.state.session = SimpleNamespace(csrf_token="synthetic-csrf-token")
        return await call_next(request)

    async def provide_actor():
        return server_actor

    app.dependency_overrides[current_actor] = provide_actor
    return app, persistence


async def test_admin_list_is_metadata_only_and_specialist_list_is_scoped_projection():
    admin_app, admin_persistence = mounted_app(BackendRole.ADMIN)
    specialist_app, specialist_persistence = mounted_app(BackendRole.PSYCHOLOGICAL_SPECIALIST)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=admin_app), base_url="http://testserver"
    ) as admin_client:
        admin_response = await admin_client.get("/api/v1/school/conversation-safety/unassigned")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=specialist_app), base_url="http://testserver"
    ) as specialist_client:
        specialist_response = await specialist_client.get(
            "/api/v1/school/conversation-safety/assigned?offset=0&limit=2"
        )

    assert admin_response.status_code == 200
    admin_item = admin_response.json()["data"]["items"][0]
    assert set(admin_item) == {
        "case_ref",
        "status",
        "state_version",
        "class_ref",
        "created_at",
        "updated_at",
    }
    assert "reason_codes" not in admin_item and "action" not in admin_item
    assert admin_response.json()["data"]["total"] == 1
    assert specialist_response.status_code == 200
    specialist_data = specialist_response.json()["data"]
    assert specialist_data["total"] == 3
    assert specialist_data["items"][0]["reason_codes"] == ["SYNTHETIC_TEST_CODE"]
    assert "review_note" not in specialist_data["items"][0]
    assert admin_persistence.calls[0][0] == "admin_list_unassigned"
    assert specialist_persistence.calls[0][0] == "specialist_list_assigned"


async def test_role_scope_and_specialist_detail_nullable_note():
    admin_app, admin_persistence = mounted_app(BackendRole.ADMIN)
    specialist_app, specialist_persistence = mounted_app(BackendRole.PSYCHOLOGICAL_SPECIALIST)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=admin_app), base_url="http://testserver"
    ) as admin_client:
        forbidden = await admin_client.get("/api/v1/school/conversation-safety/SCS_synthetic_1")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=specialist_app), base_url="http://testserver"
    ) as specialist_client:
        detail = await specialist_client.get("/api/v1/school/conversation-safety/SCS_synthetic_1")
    assert forbidden.status_code == 403
    assert admin_persistence.calls == []
    assert detail.status_code == 200
    assert detail.json()["data"]["review_note"] is None
    assert specialist_persistence.calls == [
        ("specialist_get", actor(BackendRole.PSYCHOLOGICAL_SPECIALIST), "SCS_synthetic_1", True)
    ]


async def test_assignment_receipt_and_note_are_closed_csrf_idempotent_writes():
    admin_app, admin_persistence = mounted_app(BackendRole.ADMIN)
    specialist_app, specialist_persistence = mounted_app(BackendRole.PSYCHOLOGICAL_SPECIALIST)
    headers = {
        "Idempotency-Key": "synthetic-conversation-safety-assignment",
        "X-CSRF-Token": "synthetic-csrf-token",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=admin_app), base_url="http://testserver"
    ) as admin_client:
        extra = await admin_client.post(
            "/api/v1/school/conversation-safety/SCS_synthetic_1/assignment",
            json={
                "expected_version": 1,
                "class_ref": "CLASS_synthetic_1",
                "specialist_user_id": "USER_synthetic_specialist",
                "subject_id": "SUBJ_not_allowed",
            },
            headers=headers,
        )
        assigned = await admin_client.post(
            "/api/v1/school/conversation-safety/SCS_synthetic_1/assignment",
            json={
                "expected_version": 1,
                "class_ref": "CLASS_synthetic_1",
                "specialist_user_id": "USER_synthetic_specialist",
            },
            headers=headers,
        )
    note_headers = {
        "Idempotency-Key": "synthetic-conversation-safety-note",
        "X-CSRF-Token": "synthetic-csrf-token",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=specialist_app), base_url="http://testserver"
    ) as specialist_client:
        no_csrf = await specialist_client.put(
            "/api/v1/school/conversation-safety/SCS_synthetic_1/note",
            json={"expected_version": 2, "note": "合成复核记录"},
            headers={"Idempotency-Key": note_headers["Idempotency-Key"]},
        )
        saved = await specialist_client.put(
            "/api/v1/school/conversation-safety/SCS_synthetic_1/note",
            json={"expected_version": 2, "note": "合成复核记录"},
            headers=note_headers,
        )

    assert extra.status_code == 422
    assert assigned.status_code == 200
    assert set(assigned.json()["data"]) == {
        "case_ref",
        "status",
        "state_version",
        "class_ref",
        "assigned_at",
        "updated_at",
    }
    assert assigned.json()["data"]["state_version"] == 2
    assert "subject_id" not in assigned.json()["data"]
    assert admin_persistence.calls[-1][0] == "admin_assign"
    assert no_csrf.status_code == 403
    assert saved.status_code == 200
    assert saved.json()["data"]["status"] == "IN_REVIEW"
    assert saved.json()["data"]["review_note"] == "合成复核记录"
    assert specialist_persistence.calls[-1][0] == "specialist_save_note"


@pytest.mark.parametrize(
    ("path", "target"),
    [
        ("/api/v1/student/conversations/CONV_synthetic_1/safety-status", "student"),
        (
            "/api/v1/student/research-conversations/CONV_synthetic_1/safety-status",
            "student_research",
        ),
    ],
)
async def test_student_status_is_self_only_and_lane_specific(path, target):
    app, persistence = mounted_app(BackendRole.STUDENT, subject_id="SUBJ_synthetic_1")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(path)
    assert response.status_code == 200
    data = response.json()["data"]
    assert set(data) == {"case_ref", "action", "status", "created_at", "updated_at"}
    assert "reason_codes" not in data and "review_note" not in data
    assert persistence.calls == [
        (
            "student_status",
            actor(BackendRole.STUDENT, subject_id="SUBJ_synthetic_1"),
            "CONV_synthetic_1",
            target,
        )
    ]


async def test_student_cannot_read_specialist_case_details():
    app, persistence = mounted_app(BackendRole.STUDENT, subject_id="SUBJ_synthetic_1")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/v1/school/conversation-safety/SCS_synthetic_1")
    assert response.status_code == 403
    assert persistence.calls == []


def test_production_app_factory_mounts_both_safety_route_namespaces():
    app = create_app(settings=BackendSettings())
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    for included in app.routes:
        child_router = getattr(included, "original_router", None)
        if child_router is None:
            continue
        prefix = getattr(getattr(included, "include_context", None), "prefix", "")
        paths.update(
            f"{prefix}{route.path}" for route in child_router.routes if hasattr(route, "path")
        )
    assert "/api/v1/school/conversation-safety/unassigned" in paths
    assert "/api/v1/school/conversation-safety/assigned" in paths
    assert "/api/v1/student/conversations/{conversation_ref}/safety-status" in paths
    assert "/api/v1/student/research-conversations/{conversation_ref}/safety-status" in paths
