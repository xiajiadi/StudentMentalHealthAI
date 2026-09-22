from __future__ import annotations

import httpx
import pytest

from .conftest import completed_assessment, login


def _public_problem(body: dict) -> dict:
    """Return the externally comparable problem fields.

    Request and trace correlation values are intentionally request-specific;
    every other public field must be indistinguishable at this boundary.
    """

    return {
        key: body.get(key)
        for key in (
            "type",
            "title",
            "status",
            "detail",
            "instance",
            "code",
            "retryable",
            "error",
            "errors",
        )
    }


@pytest.mark.asyncio
async def test_assessment_owner_access_remains_successful(client: httpx.AsyncClient) -> None:
    csrf = await login(client, "student_a")
    assessment_id = await completed_assessment(client, csrf)

    response = await client.get(f"/api/v1/assessments/{assessment_id}")

    assert response.status_code == 200, response.text
    assert response.json()["data"]["assessment_id"] == assessment_id


@pytest.mark.asyncio
async def test_assessment_existence_is_concealed_but_audit_reason_is_distinct(client, app) -> None:
    csrf_a = await login(client, "student_a")
    assessment_id = await completed_assessment(client, csrf_a)
    await login(client, "student_b")

    foreign = await client.get(f"/api/v1/assessments/{assessment_id}")
    unknown = await client.get("/api/v1/assessments/ASSESS_D4_2R_UNKNOWN")

    assert foreign.status_code == unknown.status_code == 404
    assert _public_problem(foreign.json()) == _public_problem(unknown.json())
    assert foreign.json()["code"] == unknown.json()["code"] == "resource_not_found"
    assert foreign.json()["detail"] == unknown.json()["detail"] == "assessment not found"

    reasons = {
        event.metadata.get("reason_code")
        for event in app.state.container.audits.list()
        if event.event == "ASSESSMENT_LOOKUP"
    }
    assert reasons == {"ASSESSMENT_ACCESS_DENIED", "ASSESSMENT_NOT_FOUND"}


@pytest.mark.asyncio
async def test_foreign_and_unknown_support_requests_fail_before_normal_pipeline(
    client, app
) -> None:
    csrf_a = await login(client, "student_a")
    assessment_id = await completed_assessment(client, csrf_a)
    csrf_b = await login(client, "student_b")
    payload = {
        "assessment_id": assessment_id,
        "target_role": "student",
        "message": "synthetic minimum disclosure check",
    }

    before = (app.state.container.rag.calls, app.state.container.llm.calls)
    foreign = await client.post(
        "/api/v1/support/requests",
        headers={"X-CSRF-Token": csrf_b},
        json=payload,
    )
    unknown = await client.post(
        "/api/v1/support/requests",
        headers={"X-CSRF-Token": csrf_b},
        json={**payload, "assessment_id": "ASSESS_D4_2R_UNKNOWN"},
    )

    assert foreign.status_code == unknown.status_code == 404
    assert _public_problem(foreign.json()) == _public_problem(unknown.json())
    assert (app.state.container.rag.calls, app.state.container.llm.calls) == before
