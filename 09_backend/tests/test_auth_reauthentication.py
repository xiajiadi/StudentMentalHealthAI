from __future__ import annotations

import time

import pytest
from pydantic import SecretStr, ValidationError
from starlette.requests import Request

from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.domains.auth.dependencies import (
    recent_reauthenticated_csrf_protected,
)
from smhai_backend.domains.auth.schemas import ReauthenticateRequest
from smhai_backend.domains.models import Actor, BackendRole, SessionRecord

from .conftest import login


@pytest.mark.asyncio
async def test_reauthenticate_requires_current_password_and_records_recent_auth(client, app):
    csrf = await login(client)
    cookie_name = app.state.container.settings.cookie_name
    session_id = client.cookies.get(cookie_name)
    assert session_id
    session = app.state.container.sessions.get(session_id)
    assert session is not None and session.reauthenticated_at is None

    rejected = await client.post(
        "/api/v1/auth/reauthenticate",
        headers={"X-CSRF-Token": csrf},
        json={"current_password": "wrong-password"},
    )
    assert rejected.status_code == 401
    assert session.reauthenticated_at is None

    accepted = await client.post(
        "/api/v1/auth/reauthenticate",
        headers={"X-CSRF-Token": csrf},
        json={"current_password": "synthetic-student-a"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["data"]["reauthenticated_at"]
    assert session.reauthenticated_at is not None
    assert abs(session.reauthenticated_at - time.time()) < 5


def test_reauthentication_request_masks_secret_and_forbids_extra_fields():
    secret = "synthetic-current-password"
    request = ReauthenticateRequest(current_password=secret)
    assert isinstance(request.current_password, SecretStr)
    assert secret not in repr(request)
    with pytest.raises(ValidationError):
        ReauthenticateRequest(current_password=secret, unexpected="value")


@pytest.mark.asyncio
async def test_recent_reauthentication_dependency_enforces_configured_ttl(app):
    now = time.time()
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/protected",
            "raw_path": b"/protected",
            "query_string": b"",
            "headers": [],
            "server": ("testserver", 80),
            "client": ("testclient", 1),
            "app": app,
        }
    )
    actor = Actor(
        user_id="USER_synthetic",
        username="synthetic",
        role=BackendRole.STUDENT,
        subject_id="SUBJ_synthetic",
    )
    request.state.session = SessionRecord(
        session_id="session",
        user_id=actor.user_id,
        csrf_token="csrf",
        created_at=now - 600,
        expires_at=now + 600,
        last_seen_at=now,
        reauthenticated_at=(
            now - app.state.container.settings.auth.reauthentication_ttl_seconds + 1
        ),
    )

    assert await recent_reauthenticated_csrf_protected(request, actor) is actor

    request.state.session.reauthenticated_at -= 2
    with pytest.raises(BackendError) as expired:
        await recent_reauthenticated_csrf_protected(request, actor)
    assert expired.value.code is ErrorCode.FORBIDDEN
