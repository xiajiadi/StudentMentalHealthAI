from __future__ import annotations

from datetime import UTC, datetime
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
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.domains.school_operations_audit.router import router
from smhai_backend.domains.school_operations_audit.service import SchoolOperationsAuditService


class FakePersistence:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def school_operations_audit_list(self, actor, **kwargs):
        self.calls.append(kwargs)
        return {
            "items": [
                {
                    "event_ref": "2d6e0c0f-233b-4d62-8f20-d7d0a2f187a3",
                    "action": "school_directory.import_accounts",
                    "result": "SUCCESS",
                    "created_at": datetime(2026, 10, 16, tzinfo=UTC),
                    "record_count": 8,
                    "actor_account_id": 123,
                    "resource_public_id": "hidden-resource-ref",
                    "safe_metadata": {"raw": "must not be projected"},
                    "trace_id": "TRACE_private",
                }
            ],
            "has_more": True,
        }


def actor(role: BackendRole) -> Actor:
    return Actor(
        user_id="USER_synthetic_admin",
        username="synthetic-admin",
        role=role,
        subject_id=None,
        scope_profile="school_tenant",
        school_id=17,
        school_ref="SCHOOL_synthetic",
    )


def mounted_app(role: BackendRole):
    app = FastAPI()
    persistence = FakePersistence()
    app.state.container = SimpleNamespace(
        school_operations_audit=SchoolOperationsAuditService(persistence=persistence),
        settings=BackendSettings(),
    )
    app.add_exception_handler(BackendError, backend_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    from fastapi.exceptions import RequestValidationError

    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[current_actor] = lambda: actor(role)

    @app.middleware("http")
    async def request_context(request, call_next):
        request.state.request_context = make_context(request)
        return await call_next(request)

    return app, persistence


@pytest.mark.asyncio
async def test_admin_can_page_only_closed_metadata_projection():
    app, persistence = mounted_app(BackendRole.ADMIN)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            "/api/v1/school/operations-audit?offset=25&limit=10&category=account_batch"
        )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data == {
        "items": [
            {
                "event_ref": "2d6e0c0f-233b-4d62-8f20-d7d0a2f187a3",
                "created_at": "2026-10-16T00:00:00Z",
                "action": "school_directory.import_accounts",
                "result": "SUCCESS",
                "resource_category": "account_batch",
                "record_count": 8,
            }
        ],
        "offset": 25,
        "limit": 10,
        "has_more": True,
    }
    assert persistence.calls == [{"offset": 25, "limit": 10, "category": "account_batch"}]


@pytest.mark.parametrize(
    "role",
    [BackendRole.TEACHER, BackendRole.STUDENT, BackendRole.PSYCHOLOGICAL_SPECIALIST],
)
@pytest.mark.asyncio
async def test_non_admin_roles_are_denied(role: BackendRole):
    app, persistence = mounted_app(role)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/v1/school/operations-audit")
    assert response.status_code == 403
    assert persistence.calls == []


@pytest.mark.parametrize(
    "query", ["offset=-1", "offset=10001", "limit=0", "limit=51", "category=clinical"]
)
@pytest.mark.asyncio
async def test_malformed_page_or_category_fails_closed(query: str):
    app, persistence = mounted_app(BackendRole.ADMIN)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(f"/api/v1/school/operations-audit?{query}")
    assert response.status_code == 422
    assert persistence.calls == []
