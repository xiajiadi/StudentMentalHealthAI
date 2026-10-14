from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

pytest.importorskip("sqlalchemy")

_ALLOWED_MODES = ("FIXTURE", "SAVED_VERSION")
_NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


@dataclass
class _Counts:
    published_enrollment_count: int = 4
    active_enrollment_count: int = 3
    revoked_enrollment_count: int = 1
    not_started_count: int = 1
    created_count: int = 1
    in_progress_count: int = 0
    completed_count: int = 1
    abandoned_count: int = 0
    invalid_count: int = 0


class _Session:
    def __init__(self, models, *, class_row=None, task_rows=(), student_rows=()):
        self.models = models
        self.class_row = class_row
        self.task_rows = list(task_rows)
        self.student_rows = list(student_rows)
        self.compiled: list[str] = []

    @staticmethod
    def _sql(statement) -> str:
        from sqlalchemy.dialects import sqlite

        return str(
            statement.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True})
        )

    async def scalar(self, statement):
        self.compiled.append(self._sql(statement))
        if statement.column_descriptions[0]["entity"] is self.models.SchoolClass:
            return self.class_row
        raise AssertionError("unexpected scalar query")

    async def scalars(self, statement):
        self.compiled.append(self._sql(statement))
        return _Rows(self.task_rows)

    async def execute(self, statement):
        self.compiled.append(self._sql(statement))
        return _Rows(self.student_rows)


class _Uow:
    def __init__(self, session):
        self.session = session

        async def task_progress_counts(**_kwargs):
            return _Counts()

        self.school_operations = SimpleNamespace(task_progress_counts=task_progress_counts)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


def _adapter(*, class_row=None, task_rows=(), student_rows=()):
    from database_layer import models
    from sqlalchemy import select

    from smhai_backend.adapters.database import MySqlBackendAdapter

    session = _Session(
        models,
        class_row=class_row or SimpleNamespace(id=77),
        task_rows=task_rows,
        student_rows=student_rows,
    )
    uow = _Uow(session)
    adapter = MySqlBackendAdapter.__new__(MySqlBackendAdapter)
    adapter.identity_profile = "school_tenant"
    adapter._db_models = models
    adapter._db_enums = SimpleNamespace(
        SubjectStatus=SimpleNamespace(ACTIVE=SimpleNamespace(value="ACTIVE")),
        DataOrigin=SimpleNamespace(SYNTHETIC=SimpleNamespace(value="SYNTHETIC")),
        AccountStatus=SimpleNamespace(ACTIVE=SimpleNamespace(value="ACTIVE")),
    )
    adapter._select = select
    adapter._uow = lambda: uow

    async def authorize(_uow, _actor, role, _at):
        assert role in {"admin", "student"}
        return 13, 17

    adapter._school_actor_role = authorize

    async def binding_fields(_uow, _actor, task):
        assert task.cat_binding_mode in _ALLOWED_MODES
        return {"activation_ref": None, "plan_name": None, "plan_version_number": None}

    adapter._task_cat_binding_fields = binding_fields
    return adapter, session


def _task(task_ref: str, *, mode: str, status="PUBLISHED"):
    return SimpleNamespace(
        id=100 if mode == "FIXTURE" else 101,
        task_ref=task_ref,
        school_id=7,
        class_id=77,
        cat_binding_mode=mode,
        status=status,
        opens_at=datetime(2026, 10, 13),
        due_at=datetime(2026, 10, 20),
        published_at=datetime(2026, 10, 12),
        instrument_id="instrument-synthetic",
        instrument_version="1.0",
    )


def _actor():
    return SimpleNamespace(
        scope_profile="school_tenant",
        role=SimpleNamespace(value="ADMIN"),
        school_id=7,
        school_ref="SCHOOL_synthetic",
    )


@pytest.mark.asyncio
async def test_admin_class_task_projection_compiles_normal_modes_and_preserves_counts():
    normal_fixture = _task("TASK_fixture", mode="FIXTURE")
    normal_saved = _task("TASK_saved", mode="SAVED_VERSION")
    adapter, session = _adapter(task_rows=[normal_fixture, normal_saved])

    rows = await adapter.school_list_class_tasks(
        _actor(), "CLASS_synthetic", at=_NOW.replace(tzinfo=None)
    )

    sql = session.compiled[-1]
    assert "measurement_tasks.cat_binding_mode IN ('FIXTURE', 'SAVED_VERSION')" in sql
    assert "measurement_tasks.school_id = 7" in sql
    assert "measurement_tasks.class_id = 77" in sql
    assert "ORDER BY measurement_tasks.published_at DESC" in sql
    assert [row["task_ref"] for row in rows] == ["TASK_fixture", "TASK_saved"]
    assert [row["published_enrollment_count"] for row in rows] == [4, 4]
    assert [row["active_enrollment_count"] for row in rows] == [3, 3]
    assert [row["revoked_enrollment_count"] for row in rows] == [1, 1]
    assert all(row["status"] == "PUBLISHED" for row in rows)


@pytest.mark.asyncio
async def test_student_task_projection_compiles_normal_modes_and_keeps_own_row_fields():
    adapter, session = _adapter(
        student_rows=[
            (
                "TASK_fixture",
                "CLASS_synthetic",
                "PUBLISHED",
                datetime(2026, 10, 13),
                datetime(2026, 10, 20),
                "ASSESS_own_synthetic",
                "IN_PROGRESS",
            )
        ]
    )

    rows = await adapter.school_list_student_tasks(_actor(), at=_NOW.replace(tzinfo=None))

    sql = session.compiled[-1]
    assert "measurement_tasks.cat_binding_mode IN ('FIXTURE', 'SAVED_VERSION')" in sql
    assert "task_enrollments.school_id = 7" in sql
    assert "task_enrollments.status = 'ACTIVE'" in sql
    assert "measurement_tasks.status = 'PUBLISHED'" in sql
    assert "measurement_tasks.opens_at <= '2026-10-14 12:00:00.000000'" in sql
    assert "DISTINCT" in sql
    assert [row["task_ref"] for row in rows] == ["TASK_fixture"]
    assert rows[0]["assessment_id"] == "ASSESS_own_synthetic"
    assert rows[0]["assessment_status"] == "IN_PROGRESS"
    assert rows[0]["status"] == "PUBLISHED"
