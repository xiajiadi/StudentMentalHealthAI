from __future__ import annotations

import pytest

from smhai_backend.adapters.memory.repositories import (
    InMemoryAssessmentRepository,
    InMemoryReportRepository,
)
from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.domains.authorization import NativeAuthorizationProvider
from smhai_backend.domains.models import Actor, AssessmentRecord, BackendRole, ReportRecord
from smhai_backend.domains.teacher.service import TeacherDashboardService


def _assessment(
    assessment_id: str,
    subject_id: str,
    *,
    origin: str = "SYNTHETIC",
    status: str = "completed",
    started_at: str = "2026-10-01T10:00:00Z",
    completed_at: str | None = "2026-10-01T10:05:00Z",
) -> AssessmentRecord:
    return AssessmentRecord(
        assessment_id=assessment_id,
        subject_id=subject_id,
        data_origin=origin,
        assessment={
            "schema_version": "assessment.v1",
            "assessment_id": assessment_id,
            "subject_id": subject_id,
            "population_scope": "synthetic_demo",
            "status": status,
            "timestamps": {"started_at": started_at, "completed_at": completed_at},
            "response_summary": {"items_answered": 3},
            "dimensions": {"must_not_disclose": {"theta": 99, "se": 0}},
        },
        responses={"private_answer": "must not be returned"},
    )


def _service() -> tuple[
    TeacherDashboardService,
    InMemoryAssessmentRepository,
    InMemoryReportRepository,
]:
    assessments = InMemoryAssessmentRepository()
    reports = InMemoryReportRepository()
    return (
        TeacherDashboardService(
            assessments=assessments,
            reports=reports,
            authorization=NativeAuthorizationProvider(),
        ),
        assessments,
        reports,
    )


@pytest.mark.asyncio
async def test_overview_returns_only_authorized_synthetic_aggregate_and_history_summaries():
    service, assessments, reports = _service()
    teacher = Actor(
        user_id="USER_teacher",
        username="teacher",
        role=BackendRole.TEACHER,
        subject_id=None,
        accessible_subject_ids=frozenset({"SUBJ_allowed", "SUBJ_outside"}),
    )
    assessments.save(_assessment("ASSESS_done", "SUBJ_allowed"))
    assessments.save(
        _assessment(
            "ASSESS_active",
            "SUBJ_allowed",
            status="in_progress",
            completed_at=None,
        )
    )
    assessments.save(_assessment("ASSESS_real", "SUBJ_allowed", origin="REAL"))
    assessments.save(_assessment("ASSESS_other", "SUBJ_ungranted"))
    reports.save(
        ReportRecord(
            report_id="REPORT_synthetic",
            assessment_id="ASSESS_done",
            subject_id="SUBJ_allowed",
            generation_id="GEN_synthetic",
            status="needs_review",
            review_status="pending",
            generation={"content": {"summary": "must not be returned"}},
        )
    )
    reports.save(
        ReportRecord(
            report_id="REPORT_real",
            assessment_id="ASSESS_real",
            subject_id="SUBJ_allowed",
            generation_id="GEN_real",
            status="approved",
            review_status="approved",
            generation={},
        )
    )

    overview = await service.overview(teacher)
    data = overview.model_dump(mode="json")
    assert data["subjects_count"] == 1
    assert data["assessments_count"] == 2
    assert data["completed_count"] == 1
    assert data["in_progress_count"] == 1
    assert data["reports_count"] == 1
    assert data["report_status_counts"] == {"needs_review": 1}
    assert data["review_status_counts"] == {"pending": 1}
    assert data["students"][0]["subject_id"] == "SUBJ_allowed"
    serialized = str(data)
    assert "private_answer" not in serialized
    assert "must not be returned" not in serialized
    assert "theta" not in serialized
    assert "ASSESS_real" not in serialized
    assert "SUBJ_ungranted" not in serialized

    history = await service.student_history(teacher, "SUBJ_allowed")
    history_data = history.model_dump(mode="json")
    assert history_data["assessment_count"] == 2
    assert [item["assessment_id"] for item in history_data["assessments"]] == [
        "ASSESS_done",
        "ASSESS_active",
    ]
    assert history_data["assessments"][0]["items_answered"] == 3
    assert history_data["assessments"][1]["items_answered"] == 3
    assert "private_answer" not in str(history_data)
    assert "theta" not in str(history_data)


@pytest.mark.asyncio
async def test_empty_scope_returns_empty_overview_and_denies_subject_history():
    service, _, _ = _service()
    teacher = Actor("USER_teacher", "teacher", BackendRole.TEACHER, None)

    overview = await service.overview(teacher)
    assert overview.subjects_count == 0
    assert overview.students == []

    with pytest.raises(BackendError) as caught:
        await service.student_history(teacher, "SUBJ_unknown")
    assert caught.value.code is ErrorCode.FORBIDDEN


@pytest.mark.asyncio
async def test_non_teacher_role_is_forbidden_even_with_accessible_subject_claims():
    service, _, _ = _service()
    reviewer = Actor(
        "USER_reviewer",
        "reviewer",
        BackendRole.REVIEWER,
        None,
        frozenset({"SUBJ_allowed"}),
    )

    with pytest.raises(BackendError) as caught:
        await service.overview(reviewer)
    assert caught.value.code is ErrorCode.FORBIDDEN
