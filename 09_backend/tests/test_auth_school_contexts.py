from __future__ import annotations

import pytest
from pwdlib import PasswordHash
from pydantic import ValidationError

from smhai_backend.adapters.memory.repositories import InMemoryUserRepository
from smhai_backend.core.config import BackendSettings
from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.domains.authorization import NativeAuthorizationProvider
from smhai_backend.domains.models import BackendRole, SchoolRoleContext, SyntheticUser


def _tenant_user(*, user_id: str = "USER_tenant_a", username: str = "tenant_a") -> SyntheticUser:
    contexts = (
        SchoolRoleContext(
            context_id=f"{user_id}:role-a",
            role=BackendRole.TEACHER,
            school_id=101,
            school_ref="SCHOOL_synthetic_a",
            accessible_subject_ids=frozenset({"SUBJ_synthetic_a"}),
        ),
        SchoolRoleContext(
            context_id=f"{user_id}:role-b",
            role=BackendRole.PSYCHOLOGICAL_SPECIALIST,
            school_id=202,
            school_ref="SCHOOL_synthetic_b",
        ),
    )
    return SyntheticUser(
        user_id=user_id,
        username=username,
        role=BackendRole.TEACHER,
        subject_id=None,
        password_hash=PasswordHash.recommended().hash("synthetic-tenant-password"),
        scope_profile="school_tenant",
        school_contexts=contexts,
        default_context_id=None,
    )


def _add_user(app, user: SyntheticUser) -> None:
    app.state.container.users._add(user)


def test_school_tenant_profile_does_not_seed_legacy_m0_accounts():
    users = InMemoryUserRepository(identity_profile="school_tenant")
    assert users.get_by_username("student_a") is None
    assert users.get_by_username("teacher") is None


def test_production_configuration_rejects_legacy_demo_identity_profile():
    with pytest.raises(ValidationError, match="school_tenant identity profile"):
        BackendSettings(
            _env_file=None,  # type: ignore[call-arg]  # pydantic-settings injects this argument
            environment="production",
            identity_profile="legacy_demo",
            auth={
                "secure_cookie": True,
                "cookie_name": "__Host-smhai_session",
                "same_site": "lax",
            },
        )


async def _login(client, username: str = "tenant_a") -> tuple[dict, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "synthetic-tenant-password"},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["actor"], response.json()["data"]["csrf_token"]


async def test_login_projects_school_roles_and_context_switch_persists_in_session(app, client):
    user = _tenant_user()
    _add_user(app, user)

    actor, csrf = await _login(client)
    assert actor["role"] == "TEACHER"
    assert actor["authorized_roles"] == ["TEACHER", "PSYCHOLOGICAL_SPECIALIST"]
    assert actor["active_context"] is None
    assert actor["available_contexts"] == [
        {"role": "TEACHER", "school_ref": "SCHOOL_synthetic_a"},
        {"role": "PSYCHOLOGICAL_SPECIALIST", "school_ref": "SCHOOL_synthetic_b"},
    ]
    assert "school_id" not in str(actor)
    assert "context_id" not in str(actor)

    session_id = client.cookies.get("smhai_dev_session")
    assert session_id is not None
    assert app.state.container.sessions.get(session_id).active_context_id is None

    selected = await client.post(
        "/api/v1/auth/active-context",
        headers={"X-CSRF-Token": csrf},
        json={"role": "TEACHER", "school_ref": "SCHOOL_synthetic_a"},
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["data"]["active_context"] == {
        "role": "TEACHER",
        "school_ref": "SCHOOL_synthetic_a",
    }
    assert (
        app.state.container.sessions.get(session_id).active_context_id
        == user.school_contexts[0].context_id
    )

    switched = await client.post(
        "/api/v1/auth/active-context",
        headers={"X-CSRF-Token": csrf},
        json={"role": "PSYCHOLOGICAL_SPECIALIST", "school_ref": "SCHOOL_synthetic_b"},
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["data"]["role"] == "PSYCHOLOGICAL_SPECIALIST"
    assert switched.json()["data"]["active_context"] == {
        "role": "PSYCHOLOGICAL_SPECIALIST",
        "school_ref": "SCHOOL_synthetic_b",
    }
    assert (
        app.state.container.sessions.get(session_id).active_context_id
        == user.school_contexts[1].context_id
    )

    current = await client.get("/api/v1/auth/me")
    assert current.status_code == 200
    assert current.json()["data"]["active_context"]["school_ref"] == "SCHOOL_synthetic_b"
    assert current.json()["data"]["role"] == "PSYCHOLOGICAL_SPECIALIST"


async def test_context_switch_rejects_other_account_context_and_reviewer_role(app, client):
    first = _tenant_user()
    second = _tenant_user(user_id="USER_tenant_b", username="tenant_b")
    second.school_contexts = (
        SchoolRoleContext(
            context_id="USER_tenant_b:role-private",
            role=BackendRole.TEACHER,
            school_id=303,
            school_ref="SCHOOL_synthetic_private",
        ),
    )
    second.default_context_id = second.school_contexts[0].context_id
    _add_user(app, first)
    _add_user(app, second)

    _, csrf = await _login(client)
    session_id = client.cookies.get("smhai_dev_session")
    assert session_id is not None

    other_account_context = await client.post(
        "/api/v1/auth/active-context",
        headers={"X-CSRF-Token": csrf},
        json={"role": "TEACHER", "school_ref": "SCHOOL_synthetic_private"},
    )
    assert other_account_context.status_code == 403
    assert app.state.container.sessions.get(session_id).active_context_id is None

    internal_reviewer = await client.post(
        "/api/v1/auth/active-context",
        headers={"X-CSRF-Token": csrf},
        json={"role": "REVIEWER", "school_ref": "SCHOOL_synthetic_a"},
    )
    assert internal_reviewer.status_code == 422


async def test_session_context_from_another_account_is_revoked(app, client):
    first = _tenant_user()
    second = _tenant_user(user_id="USER_tenant_b", username="tenant_b")
    _add_user(app, first)
    _add_user(app, second)
    _, _ = await _login(client)
    session_id = client.cookies.get("smhai_dev_session")
    assert session_id is not None
    csrf = app.state.container.sessions.get(session_id).csrf_token
    selected = await client.post(
        "/api/v1/auth/active-context",
        headers={"X-CSRF-Token": csrf},
        json={"role": "TEACHER", "school_ref": "SCHOOL_synthetic_a"},
    )
    assert selected.status_code == 200

    # Simulates a mismatched context id in persistent session storage. The
    # user's current membership projection must bind it back to this account.
    app.state.container.sessions.get(session_id).active_context_id = (
        second.school_contexts[0].context_id
    )
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert app.state.container.sessions.get(session_id) is None
    assert app.state.container.sessions.is_revoked(session_id)


async def test_inactive_membership_context_revokes_existing_tenant_session(app, client):
    user = _tenant_user()
    _add_user(app, user)
    _, _ = await _login(client)
    session_id = client.cookies.get("smhai_dev_session")
    assert session_id is not None
    csrf = app.state.container.sessions.get(session_id).csrf_token
    selected = await client.post(
        "/api/v1/auth/active-context",
        headers={"X-CSRF-Token": csrf},
        json={"role": "TEACHER", "school_ref": "SCHOOL_synthetic_a"},
    )
    assert selected.status_code == 200

    # This models membership/role revocation observed by a fresh user lookup.
    user.school_contexts = ()
    user.default_context_id = None
    current = await client.get("/api/v1/auth/me")
    assert current.status_code == 401
    assert app.state.container.sessions.get(session_id) is None
    assert app.state.container.sessions.is_revoked(session_id)


async def test_actor_for_session_uses_latest_valid_context_after_concurrent_switch(
    app, client, monkeypatch
):
    user = _tenant_user()
    _add_user(app, user)
    _, _ = await _login(client)
    session_id = client.cookies.get("smhai_dev_session")
    assert session_id is not None
    sessions = app.state.container.sessions
    assert sessions.set_active_context(session_id, user.school_contexts[0].context_id)
    original_touch = sessions.touch

    def switch_before_touch(session_key: str, ttl_seconds: int):
        assert sessions.set_active_context(session_key, user.school_contexts[1].context_id)
        return original_touch(session_key, ttl_seconds)

    monkeypatch.setattr(sessions, "touch", switch_before_touch)
    actor, current_session = await app.state.container.auth.actor_for_session(
        session_id, request_id="REQ_context_race", trace_id="TRACE_context_race"
    )

    assert current_session.active_context_id == user.school_contexts[1].context_id
    assert actor.role is BackendRole.PSYCHOLOGICAL_SPECIALIST
    assert actor.school_ref == "SCHOOL_synthetic_b"
    assert actor.accessible_subject_ids == frozenset()
    assert not NativeAuthorizationProvider().can(
        actor, "teacher:summary", resource={"subject_id": "SUBJ_synthetic_a"}
    )
    assert sessions.get(session_id) is not None
    assert not sessions.is_revoked(session_id)


@pytest.mark.parametrize("invalid_latest_context", ["revoked", "other_account"])
async def test_actor_for_session_revokes_invalid_context_switched_during_touch(
    app, client, monkeypatch, invalid_latest_context: str
):
    user = _tenant_user()
    other = _tenant_user(user_id="USER_tenant_other", username="tenant_other")
    _add_user(app, user)
    _add_user(app, other)
    _, _ = await _login(client)
    session_id = client.cookies.get("smhai_dev_session")
    assert session_id is not None
    sessions = app.state.container.sessions
    assert sessions.set_active_context(session_id, user.school_contexts[0].context_id)
    original_touch = sessions.touch

    def switch_and_change_membership(session_key: str, ttl_seconds: int):
        if invalid_latest_context == "revoked":
            latest_id = user.school_contexts[1].context_id
            user.school_contexts = (user.school_contexts[0],)
        else:
            latest_id = other.school_contexts[0].context_id
        assert sessions.set_active_context(session_key, latest_id)
        return original_touch(session_key, ttl_seconds)

    monkeypatch.setattr(sessions, "touch", switch_and_change_membership)
    with pytest.raises(BackendError) as caught:
        await app.state.container.auth.actor_for_session(
            session_id, request_id="REQ_context_invalid", trace_id="TRACE_context_invalid"
        )

    assert caught.value.code is ErrorCode.AUTH_SESSION_REVOKED
    assert sessions.get(session_id) is None
    assert sessions.is_revoked(session_id)


async def test_actor_for_session_never_falls_back_when_touch_returns_none(app, client, monkeypatch):
    user = _tenant_user()
    _add_user(app, user)
    _, _ = await _login(client)
    session_id = client.cookies.get("smhai_dev_session")
    assert session_id is not None
    sessions = app.state.container.sessions
    original_touch = sessions.touch

    def revoke_before_touch(session_key: str, ttl_seconds: int):
        sessions.revoke(session_key)
        return original_touch(session_key, ttl_seconds)

    monkeypatch.setattr(sessions, "touch", revoke_before_touch)
    with pytest.raises(BackendError) as caught:
        await app.state.container.auth.actor_for_session(
            session_id, request_id="REQ_context_revoked", trace_id="TRACE_context_revoked"
        )

    assert caught.value.code is ErrorCode.AUTH_SESSION_REVOKED
    assert sessions.get(session_id) is None
    assert sessions.is_revoked(session_id)


async def test_legacy_demo_profile_cannot_enter_school_context_switching(client):
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "student_a", "password": "synthetic-student-a"},
    )
    assert response.status_code == 200
    csrf = response.json()["data"]["csrf_token"]
    response = await client.post(
        "/api/v1/auth/active-context",
        headers={"X-CSRF-Token": csrf},
        json={"role": "TEACHER", "school_ref": "SCHOOL_synthetic_a"},
    )
    assert response.status_code == 403
