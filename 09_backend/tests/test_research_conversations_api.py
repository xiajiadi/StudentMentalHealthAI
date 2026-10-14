from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from smhai_backend.domains.auth.dependencies import current_actor
from smhai_backend.domains.conversations.service import ConversationLanePolicy
from smhai_backend.domains.models import Actor, BackendRole


def _actor(*, role: BackendRole = BackendRole.STUDENT, school_id: int = 17) -> Actor:
    return Actor(
        user_id="USER_research-capability",
        username="synthetic_student",
        role=role,
        subject_id="SUBJ_research-capability" if role is BackendRole.STUDENT else None,
        scope_profile="school_tenant",
        school_id=school_id,
        school_ref=f"SCHOOL_{school_id}",
    )


def _policy(*, school_id: int = 17, valid_through: datetime | None = None):
    return ConversationLanePolicy.school_research_student(
        school_id=school_id,
        study_ref="school-noncommercial-rag-research-2027-06",
        package_id="student-package-v1",
        manifest_sha256="a" * 64,
        valid_through=valid_through
        or datetime(2027, 6, 30, 15, 59, 59, tzinfo=UTC),
    )


def _override_actor(app, actor: Actor) -> None:
    async def provide_actor():
        return actor

    app.dependency_overrides[current_actor] = provide_actor


@pytest.mark.asyncio
async def test_research_capability_is_a_safe_disabled_metadata_response(app, client):
    _override_actor(app, _actor())

    response = await client.get("/api/v1/student/research-conversations/capability")

    assert response.status_code == 200
    assert response.json()["data"] == {"enabled": False}


@pytest.mark.asyncio
async def test_research_capability_is_enabled_only_for_pinned_current_school(app, client):
    class ReadyResearchSafety:
        async def health(self, request_context):
            return {"status": "READY"}

    service = SimpleNamespace(lane_policy=_policy())
    app.state.container.school_research_student_conversations = service
    app.state.container.school_research_student_safety = ReadyResearchSafety()
    _override_actor(app, _actor())
    enabled = await client.get("/api/v1/student/research-conversations/capability")
    assert enabled.status_code == 200
    assert enabled.json()["data"] == {
        "enabled": True,
        "purpose": "RESEARCH_SIMULATION",
        "consumer_age_min": 14,
        "consumer_age_max": 17,
        "professional_approval": False,
    }

    _override_actor(app, _actor(school_id=18))
    foreign = await client.get("/api/v1/student/research-conversations/capability")
    assert foreign.status_code == 200
    assert foreign.json()["data"] == {"enabled": False}

    expired = SimpleNamespace(
        lane_policy=_policy(valid_through=datetime(2026, 10, 1, tzinfo=UTC))
    )
    app.state.container.school_research_student_conversations = expired
    _override_actor(app, _actor())
    expired_response = await client.get("/api/v1/student/research-conversations/capability")
    assert expired_response.status_code == 200
    assert expired_response.json()["data"] == {"enabled": False}


@pytest.mark.asyncio
async def test_research_capability_is_false_when_private_safety_host_is_unready(app, client):
    class UnreadyResearchSafety:
        async def health(self, request_context):
            raise RuntimeError("private health unavailable")

    app.state.container.school_research_student_conversations = SimpleNamespace(
        lane_policy=_policy()
    )
    app.state.container.school_research_student_safety = UnreadyResearchSafety()
    _override_actor(app, _actor())

    response = await client.get("/api/v1/student/research-conversations/capability")

    assert response.status_code == 200
    assert response.json()["data"] == {"enabled": False}


@pytest.mark.asyncio
async def test_non_student_cannot_read_research_capability(app, client):
    _override_actor(app, _actor(role=BackendRole.ADMIN))

    response = await client.get("/api/v1/student/research-conversations/capability")

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
