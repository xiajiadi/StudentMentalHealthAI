"""Run the Backend-only synthetic vertical slice through the ASGI app."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from smhai_backend.app_factory import create_app
from smhai_backend.core.config import BackendSettings


async def _login(client: httpx.AsyncClient, username: str, password: str) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    response.raise_for_status()
    return response.json()["data"]["csrf_token"]


async def run() -> dict[str, Any]:
    app = create_app(settings=BackendSettings(environment="test"))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            csrf = await _login(client, "student_a", "synthetic-student-a")
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
            await client.post(
                f"/api/v1/assessments/{assessment_id}/responses",
                headers=headers,
                json={"item_id": "ITEM_synthetic_1", "response": 1.0},
            )
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
                    "message": "合成演示：请给出一个可执行的小步骤。",
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
            review_list = await client.get("/api/v1/reviews")
            review_list.raise_for_status()
            review_detail = await client.get(f"/api/v1/reviews/{crisis_data['review_reference']}")
            review_detail.raise_for_status()
            review_action = await client.post(
                f"/api/v1/reports/{crisis_data['report_id']}/reviews",
                headers={"X-CSRF-Token": reviewer_csrf},
                json={"decision": "approved"},
            )
            review_action.raise_for_status()

            return {
                "runtime": {
                    "python": "3.12",
                    "app": "FastAPI ASGI",
                    "transport": "ASGITransport",
                },
                "stages": {
                    "login": "IN_MEMORY",
                    "assessment": "CONTRACT_FAKE_CAT+IN_MEMORY",
                    "normal_support": normal_data["status"],
                    "normal_integration_labels": normal_data["integration_labels"],
                    "crisis_route": crisis_data["safety_action"],
                    "crisis_review_reference": crisis_data["review_reference"],
                    "review_list": review_list.status_code,
                    "review_detail": review_detail.status_code,
                    "review_action": review_action.json()["data"]["review_status"],
                },
                "crisis_no_rag": app.state.container.rag.calls == before_rag,
                "crisis_no_llm": app.state.container.llm.calls == before_llm,
                "call_counts": {
                    "rag": app.state.container.rag.calls,
                    "llm_runtime": app.state.container.llm.calls,
                    "safety_input": app.state.container.safety.input_calls,
                },
                "synthetic_fixture_only": True,
            }


def main() -> None:
    print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
