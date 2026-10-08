"""Authorized, synthetic-only teacher dashboard projections.

This service deliberately returns operational counts and assessment lifecycle
metadata only. It never projects answer payloads, generation content, or
psychological measurements.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from smhai_backend.core.async_utils import maybe_await
from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.models import Actor, BackendRole

from .schemas import (
    TeacherAssessmentHistoryItem,
    TeacherOverview,
    TeacherStudentHistory,
    TeacherStudentSummary,
)


class TeacherDashboardService:
    """Build teacher summaries from repositories under the actor's grants."""

    def __init__(self, *, assessments: Any, reports: Any, authorization: Any) -> None:
        self.assessments = assessments
        self.reports = reports
        self.authorization = authorization

    async def overview(self, actor: Actor) -> TeacherOverview:
        self._require_teacher(actor)
        authorized_subjects = self._authorized_subjects(actor)
        if not authorized_subjects:
            return TeacherOverview(
                subjects_count=0,
                assessments_count=0,
                completed_count=0,
                in_progress_count=0,
                reports_count=0,
                report_status_counts={},
                review_status_counts={},
                students=[],
            )

        records = await maybe_await(
            self.assessments.list_assessments_for_subjects(authorized_subjects)
        )
        synthetic_records = [
            record
            for record in records
            if record.subject_id in authorized_subjects and _is_synthetic(record)
        ]
        grouped: dict[str, list[Any]] = {}
        for record in synthetic_records:
            grouped.setdefault(record.subject_id, []).append(record)

        students = [
            _student_summary(subject_id, subject_records)
            for subject_id, subject_records in grouped.items()
        ]
        students.sort(key=lambda item: (item.last_activity_at or "", item.subject_id), reverse=True)

        synthetic_assessment_subjects = {
            record.assessment_id: record.subject_id for record in synthetic_records
        }
        report_records = await maybe_await(
            self.reports.list_for_subjects(authorized_subjects)
        )
        scoped_reports = [
            report
            for report in report_records
            if report.subject_id in authorized_subjects
            and synthetic_assessment_subjects.get(report.assessment_id) == report.subject_id
        ]
        report_status_counts = Counter(_safe_status(report.status) for report in scoped_reports)
        review_status_counts = Counter(
            _safe_status(report.review_status) for report in scoped_reports
        )

        return TeacherOverview(
            subjects_count=len(grouped),
            assessments_count=len(synthetic_records),
            completed_count=sum(_status(record) == "completed" for record in synthetic_records),
            in_progress_count=sum(
                _status(record) == "in_progress" for record in synthetic_records
            ),
            reports_count=len(scoped_reports),
            report_status_counts=dict(sorted(report_status_counts.items())),
            review_status_counts=dict(sorted(review_status_counts.items())),
            students=students,
        )

    async def student_history(self, actor: Actor, subject_id: str) -> TeacherStudentHistory:
        self._require_teacher(actor)
        authorized_subjects = self._authorized_subjects(actor)
        if subject_id not in authorized_subjects:
            raise error(ErrorCode.FORBIDDEN, detail="access denied")

        records = await maybe_await(
            self.assessments.list_assessments_for_subjects({subject_id})
        )
        synthetic_records = [
            record
            for record in records
            if record.subject_id == subject_id and _is_synthetic(record)
        ]
        synthetic_records.sort(
            key=lambda record: _timestamp(record, "started_at") or "",
            reverse=True,
        )
        return _student_history(subject_id, synthetic_records)

    def _require_teacher(self, actor: Actor) -> None:
        if actor.role is not BackendRole.TEACHER:
            raise error(ErrorCode.FORBIDDEN, detail="access denied")

    def _authorized_subjects(self, actor: Actor) -> set[str]:
        return {
            subject_id
            for subject_id in actor.accessible_subject_ids
            if self.authorization.can(
                actor, "teacher:summary", resource={"subject_id": subject_id}
            )
        }


def _is_synthetic(record: Any) -> bool:
    assessment = record.assessment
    return (
        str(record.data_origin or "").upper() == "SYNTHETIC"
        and isinstance(assessment, dict)
        and assessment.get("population_scope")
        in {"synthetic_demo", "SYNTHETIC_STUDENT_DEMO"}
    )


def _status(record: Any) -> str:
    value = record.assessment.get("status")
    allowed = {"created", "in_progress", "completed", "abandoned", "invalid"}
    if isinstance(value, str) and value in allowed:
        return value
    return "unknown"


def _timestamp(record: Any, key: str) -> str | None:
    timestamps = record.assessment.get("timestamps")
    if not isinstance(timestamps, dict):
        return None
    value = timestamps.get(key)
    return value if isinstance(value, str) and value else None


def _student_summary(subject_id: str, records: list[Any]) -> TeacherStudentSummary:
    return TeacherStudentSummary(
        subject_id=subject_id,
        assessment_count=len(records),
        completed_count=sum(_status(record) == "completed" for record in records),
        in_progress_count=sum(_status(record) == "in_progress" for record in records),
        last_activity_at=max(
            (
                timestamp
                for record in records
                if (timestamp := (_timestamp(record, "completed_at") or _timestamp(record, "started_at")))
            ),
            default=None,
        ),
    )


def _student_history(subject_id: str, records: list[Any]) -> TeacherStudentHistory:
    return TeacherStudentHistory(
        subject_id=subject_id,
        assessment_count=len(records),
        completed_count=sum(_status(record) == "completed" for record in records),
        in_progress_count=sum(_status(record) == "in_progress" for record in records),
        assessments=[
            TeacherAssessmentHistoryItem(
                assessment_id=record.assessment_id,
                status=_status(record),
                items_answered=_item_count(record),
                started_at=_timestamp(record, "started_at"),
                completed_at=_timestamp(record, "completed_at"),
            )
            for record in records
        ],
    )


def _item_count(record: Any) -> int | None:
    summary = record.assessment.get("response_summary")
    if not isinstance(summary, dict):
        return None
    value = summary.get("items_answered")
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _safe_status(value: Any) -> str:
    if not isinstance(value, str):
        return "unknown"
    allowed = {
        "requested",
        "safety_blocked",
        "generating",
        "generated",
        "needs_review",
        "approved",
        "rejected",
        "abstained",
        "pending",
        "in_review",
        "not_required",
    }
    return value if value in allowed else "unknown"
