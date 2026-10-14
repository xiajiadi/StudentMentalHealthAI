from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pytest
from database_layer.errors import NotFound
from database_layer.repositories import SchoolOperationsRepository, TaskProgressCounts
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import mysql


class _AsyncSessionBridge:
    """Async-shaped repository adapter over a synthetic in-memory SQLite DB."""

    def __init__(self, connection):
        self.connection = connection
        self.statements: list[Any] = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.connection.execute(statement)


def _progress_db(
    *,
    task_mode: str,
    task_id: int,
    school_id: int,
    class_id: int,
    enrollments: Iterable[tuple[int, int, int, int, int, str]],
    ordinary_sessions: Iterable[tuple[int, int, int, str, str]] = (),
    research_sessions: Iterable[tuple[int, int, int, int, int, int, str]] = (),
):
    engine = create_engine("sqlite:///:memory:")
    connection = engine.connect()
    connection.execute(
        text(
            "CREATE TABLE measurement_tasks "
            "(id INTEGER PRIMARY KEY, school_id INTEGER, class_id INTEGER, cat_binding_mode TEXT)"
        )
    )
    connection.execute(
        text(
            "CREATE TABLE task_enrollments "
            "(id INTEGER PRIMARY KEY, task_id INTEGER, school_id INTEGER, "
            "class_id INTEGER, subject_id INTEGER, status TEXT)"
        )
    )
    connection.execute(
        text(
            "CREATE TABLE assessment_sessions "
            "(id INTEGER PRIMARY KEY, task_enrollment_id INTEGER, subject_id INTEGER, "
            "cat_binding_mode TEXT, status TEXT)"
        )
    )
    connection.execute(
        text(
            "CREATE TABLE school_research_sessions "
            "(id INTEGER PRIMARY KEY, task_enrollment_id INTEGER, subject_id INTEGER, "
            "task_id INTEGER, school_id INTEGER, class_id INTEGER, status TEXT)"
        )
    )
    connection.execute(
        text("INSERT INTO measurement_tasks VALUES (:id, :school, :class_id, :mode)"),
        {"id": task_id, "school": school_id, "class_id": class_id, "mode": task_mode},
    )
    enrollment_rows = [
        {
            "id": enrollment_id,
            "task_id": enrollment_task_id,
            "school_id": enrollment_school_id,
            "class_id": enrollment_class_id,
            "subject_id": subject_id,
            "status": enrollment_status,
        }
        for (
            enrollment_id,
            enrollment_task_id,
            enrollment_school_id,
            enrollment_class_id,
            subject_id,
            enrollment_status,
        ) in enrollments
    ]
    if enrollment_rows:
        connection.execute(
            text(
                "INSERT INTO task_enrollments VALUES "
                "(:id, :task_id, :school_id, :class_id, :subject_id, :status)"
            ),
            enrollment_rows,
        )
    ordinary_rows = list(ordinary_sessions)
    if ordinary_rows:
        connection.execute(
            text(
                "INSERT INTO assessment_sessions VALUES "
                "(:id, :enrollment_id, :subject_id, :mode, :status)"
            ),
            [
                {
                    "id": session_id,
                    "enrollment_id": enrollment_id,
                    "subject_id": subject_id,
                    "mode": mode,
                    "status": status,
                }
                for session_id, enrollment_id, subject_id, mode, status in ordinary_rows
            ],
        )
    research_rows = list(research_sessions)
    if research_rows:
        connection.execute(
            text(
                "INSERT INTO school_research_sessions VALUES "
                "(:id, :enrollment_id, :subject_id, :task_id, :school_id, :class_id, :status)"
            ),
            [
                {
                    "id": session_id,
                    "enrollment_id": enrollment_id,
                    "subject_id": subject_id,
                    "task_id": linked_task_id,
                    "school_id": linked_school_id,
                    "class_id": linked_class_id,
                    "status": status,
                }
                for (
                    session_id,
                    enrollment_id,
                    subject_id,
                    linked_task_id,
                    linked_school_id,
                    linked_class_id,
                    status,
                ) in research_rows
            ],
        )
    connection.commit()
    return engine, connection


async def _query_counts(connection, *, task_id: int, school_id: int):
    session = _AsyncSessionBridge(connection)
    counts = await SchoolOperationsRepository(session).task_progress_counts(
        task_id=task_id, school_id=school_id
    )
    return counts, session.statements[0]


@pytest.mark.parametrize("task_mode", ["FIXTURE", "SAVED_VERSION"])
async def test_ordinary_task_progress_keeps_existing_status_counts_and_ignores_bad_scope(
    task_mode: str,
):
    enrollments = [
        (1, 100, 7, 21, 101, "ACTIVE"),
        (2, 100, 7, 21, 102, "ACTIVE"),
        (3, 100, 7, 21, 103, "ACTIVE"),
        (4, 100, 7, 21, 104, "ACTIVE"),
        (5, 100, 7, 21, 105, "ACTIVE"),
        (6, 100, 7, 21, 106, "ACTIVE"),
        (7, 100, 7, 21, 107, "REVOKED"),
    ]
    ordinary_sessions = [
        (21, 1, 999, task_mode, "COMPLETED"),  # wrong subject; remains not started
        (22, 2, 102, task_mode, "CREATED"),
        (23, 3, 103, task_mode, "IN_PROGRESS"),
        (24, 4, 104, task_mode, "COMPLETED"),
        (25, 5, 105, task_mode, "ABANDONED"),
        (26, 6, 106, task_mode, "INVALID"),
        (27, 7, 107, task_mode, "COMPLETED"),  # revoked enrollment is not active completion
    ]
    research_sessions = [(31, 1, 101, 100, 7, 21, "COMPLETED")]  # wrong task mode
    engine, connection = _progress_db(
        task_mode=task_mode,
        task_id=100,
        school_id=7,
        class_id=21,
        enrollments=enrollments,
        ordinary_sessions=ordinary_sessions,
        research_sessions=research_sessions,
    )
    try:
        counts, statement = await _query_counts(connection, task_id=100, school_id=7)
        assert counts == TaskProgressCounts(7, 6, 1, 1, 1, 1, 1, 1, 1)
        _assert_scope_a_aggregate_query(statement)
    finally:
        connection.close()
        engine.dispose()


async def test_research_task_progress_counts_only_exact_research_session_metadata():
    enrollments = [
        (101, 200, 7, 22, 201, "ACTIVE"),
        (102, 200, 7, 22, 202, "ACTIVE"),
        (103, 200, 7, 22, 203, "ACTIVE"),
        (104, 200, 7, 22, 204, "ACTIVE"),
        (105, 200, 7, 22, 205, "ACTIVE"),
        (106, 200, 7, 22, 206, "REVOKED"),
    ]
    ordinary_sessions = [
        (41, 101, 201, "FIXTURE", "COMPLETED"),  # wrong session family for this task
    ]
    research_sessions = [
        (51, 101, 999, 200, 7, 22, "COMPLETED"),  # wrong subject
        (52, 101, 201, 999, 7, 22, "COMPLETED"),  # wrong task
        (53, 101, 201, 200, 8, 22, "COMPLETED"),  # wrong school
        (54, 101, 201, 200, 7, 99, "COMPLETED"),  # wrong class
        (55, 102, 202, 200, 7, 22, "IN_PROGRESS"),
        (56, 103, 203, 200, 7, 22, "COMPLETED"),
        (57, 104, 204, 200, 7, 22, "ABANDONED"),
        (58, 105, 205, 200, 7, 22, "FAILED"),
        (59, 106, 206, 200, 7, 22, "COMPLETED"),  # revoked enrollment is not active completion
    ]
    engine, connection = _progress_db(
        task_mode="RESEARCH_PROFILE",
        task_id=200,
        school_id=7,
        class_id=22,
        enrollments=enrollments,
        ordinary_sessions=ordinary_sessions,
        research_sessions=research_sessions,
    )
    try:
        counts, statement = await _query_counts(connection, task_id=200, school_id=7)
        assert counts == TaskProgressCounts(6, 5, 1, 1, 0, 1, 1, 1, 1)
        _assert_scope_a_aggregate_query(statement)
        sql = str(statement.compile(dialect=mysql.dialect())).lower()
        assert "school_research_sessions.task_id = measurement_tasks.id" in sql
        assert "school_research_sessions.school_id = measurement_tasks.school_id" in sql
        assert "school_research_sessions.class_id = measurement_tasks.class_id" in sql
        assert "school_research_sessions.subject_id = task_enrollments.subject_id" in sql
        assert "assessment_sessions.cat_binding_mode = measurement_tasks.cat_binding_mode" in sql
    finally:
        connection.close()
        engine.dispose()


async def test_task_progress_returns_not_found_for_wrong_school_scope():
    engine, connection = _progress_db(
        task_mode="RESEARCH_PROFILE",
        task_id=300,
        school_id=8,
        class_id=31,
        enrollments=[],
    )
    try:
        with pytest.raises(NotFound):
            await SchoolOperationsRepository(_AsyncSessionBridge(connection)).task_progress_counts(
                task_id=300, school_id=7
            )
    finally:
        connection.close()
        engine.dispose()


def _assert_scope_a_aggregate_query(statement) -> None:
    selected = set(statement.selected_columns.keys())
    assert selected == {
        "published_enrollment_count",
        "active_enrollment_count",
        "revoked_enrollment_count",
        "not_started_count",
        "created_count",
        "in_progress_count",
        "completed_count",
        "abandoned_count",
        "invalid_count",
    }
    sql = str(statement.compile(dialect=mysql.dialect())).lower()
    assert "task_enrollments.school_id = measurement_tasks.school_id" in sql
    assert "task_enrollments.task_id = measurement_tasks.id" in sql
    assert "assessment_responses" not in sql
    assert "assessment_results" not in sql
    assert "snapshot_ciphertext" not in sql
    assert "payload_ciphertext" not in sql
    assert "school_research_sessions.snapshot_ciphertext" not in sql
    assert "school_research_sessions.status" in sql
