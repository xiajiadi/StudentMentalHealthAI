from __future__ import annotations

import httpx
import pytest

from smhai_backend.app_factory import create_app
from smhai_backend.core.config import AuthSettings, BackendSettings


@pytest.mark.asyncio
async def test_configured_lockout_is_generic_and_expires() -> None:
    app = create_app(
        settings=BackendSettings(
            environment="test",
            auth=AuthSettings(
                login_lock_threshold=2,
                login_lock_duration_seconds=60,
            ),
        )
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            first = await client.post(
                "/api/v1/auth/login",
                json={"username": "student_a", "password": "wrong-one"},
            )
            second = await client.post(
                "/api/v1/auth/login",
                json={"username": "student_a", "password": "wrong-two"},
            )
            user = app.state.container.users._by_username["student_a"]
            lock_until = app.state.container.users._locked_until[user.user_id]
            while_locked = await client.post(
                "/api/v1/auth/login",
                json={"username": "student_a", "password": "synthetic-student-a"},
            )
            unknown = await client.post(
                "/api/v1/auth/login",
                json={"username": "missing_user", "password": "wrong"},
            )

            assert first.status_code == second.status_code == 401
            assert while_locked.status_code == unknown.status_code == 401
            locked_error = while_locked.json()
            unknown_error = unknown.json()
            assert locked_error["code"] == unknown_error["code"]
            assert locked_error["detail"] == unknown_error["detail"]
            assert app.state.container.users._locked_until[user.user_id] == lock_until

            app.state.container.users._clock = lambda: lock_until + 1
            unlocked = await client.post(
                "/api/v1/auth/login",
                json={"username": "student_a", "password": "synthetic-student-a"},
            )

            assert unlocked.status_code == 200
            assert app.state.container.users._failure_counts.get(user.user_id, 0) == 0
            assert user.user_id not in app.state.container.users._locked_until
