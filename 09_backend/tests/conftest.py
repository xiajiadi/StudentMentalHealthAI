from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest_asyncio

from smhai_backend.app_factory import create_app
from smhai_backend.core.config import BackendSettings, RateLimitSettings


@pytest_asyncio.fixture
async def app():
    settings = BackendSettings(
        environment="test",
        rate_limit=RateLimitSettings(
            login_max_requests=5,
            support_max_requests=10,
            window_seconds=60,
        ),
    )
    application = create_app(settings=settings)
    async with application.router.lifespan_context(application):
        yield application


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Accept": "application/json"},
    ) as value:
        yield value


async def login(client: httpx.AsyncClient, username: str = "student_a") -> str:
    passwords = {
        "student_a": "synthetic-student-a",
        "student_b": "synthetic-student-b",
        "teacher": "synthetic-teacher",
        "reviewer": "synthetic-reviewer",
    }
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": passwords[username]},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["csrf_token"]


async def completed_assessment(
    client: httpx.AsyncClient,
    csrf_token: str,
    *,
    subject_id: str = "SUBJ_demo_a",
) -> str:
    response = await client.post(
        "/api/v1/assessments",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "subject_id": subject_id,
            "instrument_id": "instrument.synthetic",
            "instrument_version": "1.0",
        },
    )
    assert response.status_code == 201, response.text
    assessment_id = response.json()["data"]["assessment_id"]
    response = await client.post(
        f"/api/v1/assessments/{assessment_id}/responses",
        headers={"X-CSRF-Token": csrf_token},
        json={"item_id": "ITEM_synthetic_1", "response": 1.0},
    )
    assert response.status_code == 200, response.text
    response = await client.post(
        f"/api/v1/assessments/{assessment_id}/complete",
        headers={"X-CSRF-Token": csrf_token},
        json={},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "completed"
    return assessment_id
