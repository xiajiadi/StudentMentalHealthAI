"""Exercise the real loopback Safety HTTP service through Backend."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from smhai_backend.app_factory import create_app
from smhai_backend.core.config import BackendSettings, ModuleClientSettings, TimeoutSettings


async def _login(
    client: httpx.AsyncClient,
    username: str = "student_a",
    password: str = "synthetic-student-a",
) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    response.raise_for_status()
    return response.json()["data"]["csrf_token"]


async def run() -> dict[str, Any]:
    settings = BackendSettings(
        environment="test",
        safety=ModuleClientSettings(
            mode="http",
            base_url="http://127.0.0.1:8190",
            timeout=TimeoutSettings(connect=2.0, read=60.0, write=20.0, pool=2.0),
        ),
        support_deadline_seconds=120.0,
    )
    app = create_app(settings=settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            health = await client.get("/health/dependencies")
            health.raise_for_status()
            safety_health = health.json()["data"]["safety"]
            csrf = await _login(client)
            headers = {"X-CSRF-Token": csrf}
            start = await client.post(
                "/api/v1/assessments",
                headers=headers,
                json={
                    "subject_id": "SUBJ_demo_a",
                    "instrument_id": "instrument.synthetic",
                    "instrument_version": "1.0",
                },
            )
            start.raise_for_status()
            assessment_id = start.json()["data"]["assessment_id"]
            response = await client.post(
                f"/api/v1/assessments/{assessment_id}/responses",
                headers=headers,
                json={"item_id": "ITEM_synthetic_1", "response": 1.0},
            )
            response.raise_for_status()
            complete = await client.post(
                f"/api/v1/assessments/{assessment_id}/complete",
                headers=headers,
                json={},
            )
            complete.raise_for_status()

            normal = await client.post(
                "/api/v1/support/requests",
                headers=headers,
                json={
                    "assessment_id": assessment_id,
                    "target_role": "student",
                    "message": "我想安排今天的学习任务。",
                },
            )
            normal.raise_for_status()
            normal_data = normal.json()["data"]
            before_rag = app.state.container.rag.calls
            before_llm = app.state.container.llm.calls
            crisis = await client.post(
                "/api/v1/support/requests",
                headers=headers,
                json={
                    "assessment_id": assessment_id,
                    "target_role": "student",
                    "message": "SYNTHETIC_CRISIS_SIGNAL",
                },
            )
            crisis.raise_for_status()
            crisis_data = crisis.json()["data"]
            reviewer_csrf = await _login(client, "reviewer", "synthetic-reviewer")
            review_action = await client.post(
                f"/api/v1/reports/{crisis_data['report_id']}/reviews",
                headers={"X-CSRF-Token": reviewer_csrf},
                json={"decision": "approved"},
            )
            review_action.raise_for_status()
            return {
                "safety_health": safety_health,
                "safety_label": app.state.container.safety.label,
                "normal": {
                    "status": normal_data["status"],
                    "safety_action": normal_data["safety_action"],
                    "normal_generation": normal_data["normal_generation"],
                    "reason_codes": normal_data["generation"]["safety"]["reason_codes"],
                },
                "crisis": {
                    "safety_action": crisis_data["safety_action"],
                    "normal_generation": crisis_data["normal_generation"],
                    "review_reference": crisis_data["review_reference"],
                    "crisis_response_present": bool(crisis_data["crisis_response"]),
                    "review_action": review_action.json()["data"]["review_status"],
                },
                "crisis_no_rag": app.state.container.rag.calls == before_rag,
                "crisis_no_llm": app.state.container.llm.calls == before_llm,
                "synthetic_fixture_only": True,
            }


def main() -> None:
    print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
