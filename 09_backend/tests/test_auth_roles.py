from __future__ import annotations

from smhai_backend.domains.models import BackendRole

from .conftest import login


async def test_specialist_authentication_remains_separate_from_safety_review(
    app, client
) -> None:
    user = app.state.container.users.get_by_username("reviewer")
    assert user is not None
    user.role = BackendRole.PSYCHOLOGICAL_SPECIALIST

    await login(client, "reviewer")

    current_actor = await client.get("/api/v1/auth/me")
    assert current_actor.status_code == 200
    assert current_actor.json()["data"]["role"] == "PSYCHOLOGICAL_SPECIALIST"

    safety_review_queue = await client.get("/api/v1/reviews")
    assert safety_review_queue.status_code == 403

    teacher_projection = await client.get("/api/v1/teacher/overview")
    assert teacher_projection.status_code == 403
