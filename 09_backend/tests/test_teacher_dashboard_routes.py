from __future__ import annotations

import pytest

from smhai_backend.domains.models import AssessmentRecord

from .conftest import login


def _synthetic_assessment(
    assessment_id: str,
    subject_id: str,
    *,
    status: str,
    completed_at: str | None,
) -> AssessmentRecord:
    return AssessmentRecord(
        assessment_id=assessment_id,
        subject_id=subject_id,
        data_origin="SYNTHETIC",
        assessment={
            "schema_version": "assessment.v1",
            "assessment_id": assessment_id,
            "subject_id": subject_id,
            "population_scope": "SYNTHETIC_STUDENT_DEMO",
            "status": status,
            "timestamps": {
                "started_at": "2026-10-09T10:00:00Z",
                "completed_at": completed_at,
            },
            "response_summary": {"items_answered": 4},
            "dimensions": {"private": {"theta": 99, "se": 0}},
        },
        responses={"private_answer": "must not be returned"},
    )


@pytest.mark.asyncio
async def test_teacher_routes_return_only_authorized_synthetic_assessment_metadata(client, app):
    app.state.container.assessments_repo.save(
        _synthetic_assessment(
            "ASSESS_teacher_done",
            "SUBJ_demo_a",
            status="completed",
            completed_at="2026-10-09T10:05:00Z",
        )
    )
    app.state.container.assessments_repo.save(
        _synthetic_assessment(
            "ASSESS_teacher_active",
            "SUBJ_demo_a",
            status="in_progress",
            completed_at=None,
        )
    )
    await login(client, "teacher")

    overview = await client.get("/api/v1/teacher/overview")
    assert overview.status_code == 200, overview.text
    overview_data = overview.json()["data"]
    assert overview_data["subjects_count"] == 1
    assert overview_data["assessments_count"] == 2
    assert overview_data["completed_count"] == 1
    assert overview_data["in_progress_count"] == 1
    assert overview_data["report_metadata_visible"] is True
    assert overview_data["task_progress_available"] is False
    assert overview_data["reports_count"] == 0
    assert overview_data["report_status_counts"] == {}
    assert overview_data["review_status_counts"] == {}
    assert [item["subject_id"] for item in overview_data["students"]] == ["SUBJ_demo_a"]

    history = await client.get("/api/v1/teacher/students/SUBJ_demo_a")
    assert history.status_code == 200, history.text
    history_data = history.json()["data"]
    assert history_data["assessment_count"] == 2
    serialized = str(history_data)
    assert "private_answer" not in serialized
    assert "theta" not in serialized


@pytest.mark.asyncio
async def test_teacher_routes_fail_closed_for_missing_role_and_subject_scope(client, app):
    unauthenticated = await client.get("/api/v1/teacher/overview")
    assert unauthenticated.status_code == 401

    await login(client, "student_a")
    non_teacher = await client.get("/api/v1/teacher/overview")
    assert non_teacher.status_code == 403

    await login(client, "teacher")
    out_of_scope = await client.get("/api/v1/teacher/students/SUBJ_unknown")
    assert out_of_scope.status_code == 403
