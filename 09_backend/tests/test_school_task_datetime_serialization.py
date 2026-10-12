from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.domains.school_tasks.schemas import (
    StudentTaskDto,
    StudentTaskHistoryDto,
    TaskDto,
    TaskPublishRequest,
    TeacherTaskProgressDto,
)
from smhai_backend.domains.school_tasks.service import _naive_utc


def test_task_output_datetimes_are_serialized_as_utc_z_and_keep_nullable_values():
    task = TaskDto.model_validate(
        {
            "task_ref": "TASK_synthetic",
            "class_ref": "CLASS_synthetic",
            "status": "PUBLISHED",
            "opens_at": datetime(2026, 10, 11, 8, 0),
            "due_at": None,
            "published_at": datetime(
                2026, 10, 11, 12, 0, tzinfo=timezone(timedelta(hours=8))
            ),
            "published_enrollment_count": 2,
            "active_enrollment_count": 2,
            "revoked_enrollment_count": 0,
            "instrument_id": "SYNTHETIC_INSTRUMENT",
            "instrument_version": "1.0",
        }
    )

    assert task.opens_at.tzinfo is UTC
    assert task.published_at.tzinfo is UTC
    assert task.due_at is None
    assert task.model_dump(mode="json")["opens_at"] == "2026-10-11T08:00:00Z"
    assert task.model_dump(mode="json")["published_at"] == "2026-10-11T04:00:00Z"
    assert task.model_dump(mode="json")["due_at"] is None


def test_student_task_and_history_metadata_are_utc_aware_and_preserve_nulls():
    task = StudentTaskDto.model_validate(
        {
            "task_ref": "TASK_synthetic",
            "class_ref": "CLASS_synthetic",
            "status": "PUBLISHED",
            "opens_at": datetime(2026, 10, 11, 8, 0),
            "due_at": None,
        }
    )
    history = StudentTaskHistoryDto.model_validate(
        {
            "task_ref": "TASK_synthetic",
            "class_ref": "CLASS_synthetic",
            "task_status": "CLOSED",
            "enrollment_status": "REVOKED",
            "assessment_status": "created",
            "started_at": datetime(2026, 10, 11, 8, 30),
            "completed_at": None,
        }
    )

    assert task.opens_at.tzinfo is UTC
    assert task.due_at is None
    assert history.started_at is not None and history.started_at.tzinfo is UTC
    assert history.completed_at is None
    assert task.model_dump(mode="json")["opens_at"] == "2026-10-11T08:00:00Z"
    assert history.model_dump(mode="json")["started_at"] == "2026-10-11T08:30:00Z"
    assert history.model_dump(mode="json")["completed_at"] is None


def test_teacher_task_metadata_normalizes_aware_and_naive_times_to_utc():
    progress = TeacherTaskProgressDto.model_validate(
        {
            "class_ref": "CLASS_synthetic",
            "task_ref": "TASK_synthetic",
            "task_status": "PUBLISHED",
            "opens_at": datetime(2026, 10, 11, 8, 0),
            "due_at": datetime(
                2026, 10, 11, 18, 0, tzinfo=timezone(timedelta(hours=8))
            ),
            "published_enrollment_count": 2,
            "active_enrollment_count": 2,
            "revoked_enrollment_count": 0,
            "not_started_count": 1,
            "created_count": 0,
            "in_progress_count": 1,
            "completed_count": 0,
            "abandoned_count": 0,
            "invalid_count": 0,
        }
    )

    serialized = progress.model_dump(mode="json")
    assert serialized["opens_at"] == "2026-10-11T08:00:00Z"
    assert serialized["due_at"] == "2026-10-11T10:00:00Z"


def test_publish_request_does_not_inherit_output_timezone_conversion():
    request = TaskPublishRequest.model_validate({"opens_at": "2026-10-11T08:00:00"})
    assert request.opens_at.tzinfo is None
    with pytest.raises(BackendError) as caught:
        _naive_utc(request.opens_at)
    assert caught.value.code is ErrorCode.VALIDATION_FAILED


def test_student_task_and_history_serialize_known_assessment_status_as_lowercase():
    task = StudentTaskDto.model_validate(
        {
            "task_ref": "TASK_synthetic",
            "class_ref": "CLASS_synthetic",
            "status": "PUBLISHED",
            "opens_at": datetime(2026, 10, 11, 8, 0),
            "due_at": None,
            "assessment_status": "IN_PROGRESS",
        }
    )
    completed_history = StudentTaskHistoryDto.model_validate(
        {
            "task_ref": "TASK_synthetic",
            "class_ref": "CLASS_synthetic",
            "task_status": "CLOSED",
            "enrollment_status": "ACTIVE",
            "assessment_status": "COMPLETED",
            "started_at": datetime(2026, 10, 11, 8, 30),
            "completed_at": datetime(2026, 10, 11, 9, 0),
        }
    )
    empty_history = StudentTaskHistoryDto.model_validate(
        {
            "task_ref": "TASK_synthetic-empty",
            "class_ref": "CLASS_synthetic",
            "task_status": "PUBLISHED",
            "enrollment_status": "ACTIVE",
            "assessment_status": None,
            "started_at": None,
            "completed_at": None,
        }
    )

    assert task.model_dump(mode="json")["assessment_status"] == "in_progress"
    assert completed_history.model_dump(mode="json")["assessment_status"] == "completed"
    assert empty_history.assessment_status is None
    assert empty_history.model_dump(mode="json")["assessment_status"] is None


@pytest.mark.parametrize("dto_type", [StudentTaskDto, StudentTaskHistoryDto])
def test_student_task_dtos_reject_unknown_assessment_status(dto_type):
    value = {
        "task_ref": "TASK_synthetic",
        "class_ref": "CLASS_synthetic",
        "assessment_status": "UNKNOWN",
    }
    if dto_type is StudentTaskDto:
        value.update({"status": "PUBLISHED", "opens_at": datetime(2026, 10, 11, 8, 0)})
    else:
        value.update({"task_status": "PUBLISHED", "enrollment_status": "ACTIVE"})

    with pytest.raises(ValidationError):
        dto_type.model_validate(value)
