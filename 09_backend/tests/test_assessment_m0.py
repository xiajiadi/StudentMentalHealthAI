from __future__ import annotations

import pytest

from smhai_backend.adapters.memory.repositories import InMemoryReportRepository
from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.domains.models import Actor, AssessmentRecord, BackendRole, ReportRecord
from smhai_backend.integrations.cat import CatStart

from .conftest import login


async def _start_assessment(client, csrf_token: str, subject_id: str = "SUBJ_demo_a") -> str:
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
    return response.json()["data"]["assessment_id"]


@pytest.mark.asyncio
async def test_assessment_list_result_and_scope(client):
    csrf_token = await login(client)
    assessment_id = await _start_assessment(client, csrf_token)

    listing = await client.get("/api/v1/assessments")
    assert listing.status_code == 200
    assert [item["assessment_id"] for item in listing.json()["data"]] == [assessment_id]

    incomplete = await client.get(f"/api/v1/assessments/{assessment_id}")
    assert incomplete.status_code == 200
    assert incomplete.json()["data"]["status"] == "created"

    response = await client.post(
        f"/api/v1/assessments/{assessment_id}/responses",
        headers={"X-CSRF-Token": csrf_token},
        json={"item_id": "ITEM_synthetic_1", "response": 1.0},
    )
    assert response.status_code == 200
    complete = await client.post(
        f"/api/v1/assessments/{assessment_id}/complete",
        headers={"X-CSRF-Token": csrf_token},
        json={},
    )
    assert complete.status_code == 200
    result = await client.get(f"/api/v1/assessments/{assessment_id}")
    assert result.status_code == 200
    assert result.json()["data"]["status"] == "completed"

    await login(client, "student_b")
    other_subject = await client.get("/api/v1/assessments")
    assert other_subject.status_code == 200
    assert other_subject.json()["data"] == []


@pytest.mark.asyncio
async def test_real_cat_completion_requires_configured_stop(client, app):
    csrf_token = await login(client)
    assessment_id = await _start_assessment(client, csrf_token)
    # Exercise the production integration guard while the test CAT fake reports
    # that the configured stopping condition has not been reached.
    app.state.container.cat.label = "REAL_HTTP"
    response = await client.post(
        f"/api/v1/assessments/{assessment_id}/complete",
        headers={"X-CSRF-Token": csrf_token},
        json={},
    )
    assert response.status_code == 409
    assert "stopping condition" in response.json()["detail"]


@pytest.mark.asyncio
async def test_cat_state_is_replayed_from_persisted_response_history(app):
    container = app.state.container
    user = container.users.get_by_username("student_a")
    assert user is not None
    actor = Actor(
        user_id=user.user_id,
        username=user.username,
        role=BackendRole.STUDENT,
        subject_id=user.subject_id,
        accessible_subject_ids=user.accessible_subject_ids,
    )

    class RecoveringCat:
        label = "REAL_HTTP"

        def __init__(self):
            self.available = False
            self.session = None
            self.replayed: list[tuple[str, object]] = []

        async def state(self, session, **kwargs):
            if not self.available:
                raise BackendError(
                    ErrorCode.RESOURCE_NOT_FOUND,
                    detail="session absent",
                    status_code=404,
                )
            return self.session

        async def start(
            self,
            *,
            assessment_id,
            subject_id,
            instrument_id,
            instrument_version,
            **kwargs,
        ):
            self.available = True
            self.session = CatStart(
                assessment_id=assessment_id,
                subject_id=subject_id,
                instrument_id=instrument_id,
                instrument_version=instrument_version,
                started_at="2026-10-07T00:00:00Z",
                current_item={"item_id": "ITEM_demo_replay_1"},
            )
            return self.session

        async def submit_response(self, session, *, item_id, response, **kwargs):
            assert item_id == (session.current_item or {}).get("item_id")
            self.replayed.append((item_id, response))
            self.session = CatStart(
                assessment_id=session.assessment_id,
                subject_id=session.subject_id,
                instrument_id=session.instrument_id,
                instrument_version=session.instrument_version,
                started_at=session.started_at,
                answered_count=1,
                administered_count=1,
                can_complete=True,
                max_items=8,
                item_bank_version="synthetic.v1",
                config_version="demo.cat.v1",
                provider_version="test-provider",
            )

    service = container.assessments
    cat = RecoveringCat()
    service.cat = cat
    record = AssessmentRecord(
        assessment_id="ASSESS_demo_recovery",
        subject_id="SUBJ_demo_a",
        assessment={
            "status": "in_progress",
            "instrument": {"instrument_id": "instrument.synthetic", "version": "1.0"},
            "timestamps": {"started_at": "2026-10-06T00:00:00Z"},
        },
        responses={"ITEM_demo_replay_1": 2},
    )
    container.assessments_repo.save(record)

    state = await service.state_for_actor(
        actor,
        record.assessment_id,
        action="assessment:read",
        request_id="REQ_m0_recovery",
        trace_id="TRACE_m0_recovery",
    )
    assert cat.replayed == [("ITEM_demo_replay_1", 2)]
    assert state.can_complete is True
    assert state.administered_count == 1


@pytest.mark.asyncio
async def test_assessment_list_requires_authentication(client):
    response = await client.get("/api/v1/assessments")
    assert response.status_code == 401


def test_report_list_repository_applies_subject_assessment_and_limit_filters():
    repository = InMemoryReportRepository()
    for index, subject_id in enumerate(
        ("SUBJ_demo_a", "SUBJ_demo_b", "SUBJ_demo_a"), start=1
    ):
        repository.save(
            ReportRecord(
                report_id=f"REPORT_{index}",
                assessment_id=f"ASSESS_{index}",
                subject_id=subject_id,
                generation_id=f"GEN_{index}",
                status="generated",
                generation={"created_at": f"2026-10-0{index}T00:00:00Z"},
            )
        )

    scoped = repository.list_for_subjects({"SUBJ_demo_a"}, limit=1)
    assert [record.report_id for record in scoped] == ["REPORT_3"]
    filtered = repository.list_for_subjects(
        {"SUBJ_demo_a", "SUBJ_demo_b"}, assessment_id="ASSESS_2", limit=100
    )
    assert [record.report_id for record in filtered] == ["REPORT_2"]
