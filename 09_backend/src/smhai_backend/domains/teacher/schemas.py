"""Response models for the teacher dashboard's synthetic-only projection."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class TeacherStudentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_id: str
    assessment_count: int
    completed_count: int
    in_progress_count: int
    last_activity_at: str | None


class TeacherOverview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subjects_count: int
    assessments_count: int
    completed_count: int
    in_progress_count: int
    reports_count: int
    report_status_counts: dict[str, int]
    review_status_counts: dict[str, int]
    report_metadata_visible: bool
    task_progress_available: bool = False
    students: list[TeacherStudentSummary]


class TeacherAssessmentHistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_id: str
    status: str
    items_answered: int | None
    started_at: str | None
    completed_at: str | None


class TeacherStudentHistory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_id: str
    assessment_count: int
    completed_count: int
    in_progress_count: int
    assessments: list[TeacherAssessmentHistoryItem]
