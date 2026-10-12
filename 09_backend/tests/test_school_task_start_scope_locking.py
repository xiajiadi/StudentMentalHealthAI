from __future__ import annotations

import ast
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from smhai_backend.adapters.database import MySqlBackendAdapter
from smhai_backend.core.errors import BackendError, ErrorCode


class _Expression:
    def __and__(self, _other):
        return self

    def __or__(self, _other):
        return self


class _Column:
    def __eq__(self, _other):
        return _Expression()

    def __le__(self, _other):
        return _Expression()

    def __ge__(self, _other):
        return _Expression()

    def is_(self, _other):
        return _Expression()


class _ModelMeta(type):
    def __getattr__(cls, _name):
        return _Column()


class _Model(metaclass=_ModelMeta):
    pass


class _SchoolClassStudent:
    # Mirror declared ORM columns, deliberately without dynamic attributes.
    id = _Column()
    school_id = _Column()
    class_id = _Column()
    subject_id = _Column()
    status = _Column()
    valid_from = _Column()
    valid_until = _Column()
    revoked_at = _Column()


class _TaskEnrollment(_Model):
    pass


class _SchoolClass(_Model):
    pass


class _MeasurementTask(_Model):
    pass


class _Subject(_Model):
    pass


class _SubjectAccessGrant(_Model):
    pass


class _Query:
    def __init__(self, model):
        self.model = model
        self.locked = False

    def where(self, *_conditions):
        return self

    def with_for_update(self):
        self.locked = True
        return self


class _Session:
    def __init__(self, *, revoked_model=None):
        self.revoked_model = revoked_model
        self.lock_reads = []
        self.rows = {
            _SchoolClassStudent: SimpleNamespace(id=11),
            _TaskEnrollment: SimpleNamespace(
                id=21, class_student_id=11, class_id=31, task_id=41, subject_id=51
            ),
            _SchoolClass: SimpleNamespace(id=31),
            _MeasurementTask: SimpleNamespace(id=41),
            _Subject: SimpleNamespace(id=51),
            _SubjectAccessGrant: SimpleNamespace(id=61),
        }

    async def scalar(self, query):
        assert query.locked is True
        self.lock_reads.append(query.model)
        if query.model is self.revoked_model:
            return None
        return self.rows[query.model]


def _adapter(session):
    adapter = MySqlBackendAdapter.__new__(MySqlBackendAdapter)
    adapter._db_models = SimpleNamespace(
        SchoolClassStudent=_SchoolClassStudent,
        TaskEnrollment=_TaskEnrollment,
        SchoolClass=_SchoolClass,
        MeasurementTask=_MeasurementTask,
        Subject=_Subject,
        SubjectAccessGrant=_SubjectAccessGrant,
    )
    adapter._db_enums = SimpleNamespace(
        SubjectStatus=SimpleNamespace(ACTIVE=SimpleNamespace(value="ACTIVE")),
        DataOrigin=SimpleNamespace(SYNTHETIC=SimpleNamespace(value="SYNTHETIC")),
    )
    adapter._select = _Query
    return adapter


def test_task_candidate_uses_real_declared_roster_and_self_grant_columns():
    root = Path(__file__).resolve().parents[2]
    database_models_path = root / "11_database" / "database_layer" / "models.py"
    model_tree = ast.parse(database_models_path.read_text(encoding="utf-8"))
    roster_class = next(
        node
        for node in model_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SchoolClassStudent"
    )
    roster_columns = {
        node.target.id
        for node in roster_class.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert {
        "school_id",
        "class_id",
        "subject_id",
        "status",
        "valid_from",
        "valid_until",
        "revoked_at",
    } <= roster_columns
    assert "student_account_id" not in roster_columns

    adapter_path = root / "09_backend" / "src" / "smhai_backend" / "adapters" / "database.py"
    adapter_source = adapter_path.read_text(encoding="utf-8")
    assert "m.SchoolClassStudent.student_account_id" not in adapter_source
    assert "m.SubjectAccessGrant.principal_account_id == account_id" in adapter_source
    assert 'm.SubjectAccessGrant.relationship_type == "SELF"' in adapter_source


def test_real_task_candidate_query_compiles_against_database_orm_models():
    pytest.importorskip("sqlalchemy")
    root = Path(__file__).resolve().parents[2]
    database_root = str(root / "11_database")
    sys.path.insert(0, database_root)
    try:
        from database_layer.models import (  # noqa: PLC0415
            MeasurementTask,
            SchoolClassStudent,
            SubjectAccessGrant,
            TaskEnrollment,
        )
        from sqlalchemy import select  # noqa: PLC0415
        from sqlalchemy.dialects import mysql  # noqa: PLC0415
    finally:
        sys.path.remove(database_root)

    statement = (
        select(TaskEnrollment)
        .join(
            MeasurementTask,
            (MeasurementTask.id == TaskEnrollment.task_id)
            & (MeasurementTask.school_id == TaskEnrollment.school_id)
            & (MeasurementTask.class_id == TaskEnrollment.class_id),
        )
        .join(
            SchoolClassStudent,
            (SchoolClassStudent.id == TaskEnrollment.class_student_id)
            & (SchoolClassStudent.school_id == TaskEnrollment.school_id)
            & (SchoolClassStudent.class_id == TaskEnrollment.class_id)
            & (SchoolClassStudent.subject_id == TaskEnrollment.subject_id),
        )
        .join(
            SubjectAccessGrant,
            (SubjectAccessGrant.subject_id == TaskEnrollment.subject_id)
            & (SubjectAccessGrant.school_id == TaskEnrollment.school_id),
        )
        .where(
            SubjectAccessGrant.principal_account_id == 7,
            SubjectAccessGrant.relationship_type == "SELF",
        )
    )
    sql = str(statement.compile(dialect=mysql.dialect()))
    assert "subject_access_grants.principal_account_id" in sql
    assert "subject_access_grants.relationship_type" in sql
    assert "school_class_students.subject_id" in sql


@pytest.mark.asyncio
async def test_task_assessment_scope_locks_roster_before_enrollment_and_all_access_rows():
    session = _Session()
    adapter = _adapter(session)
    enrollment = session.rows[_TaskEnrollment]
    actor = SimpleNamespace(school_id=7)

    locked_enrollment, task, subject = await adapter._lock_school_assessment_write_scope(
        SimpleNamespace(session=session),
        actor,
        9,
        enrollment,
        at=datetime(2026, 10, 13, tzinfo=UTC),
    )

    assert session.lock_reads == [
        _SchoolClassStudent,
        _TaskEnrollment,
        _SchoolClass,
        _MeasurementTask,
        _Subject,
        _SubjectAccessGrant,
    ]
    assert locked_enrollment is enrollment
    assert task is session.rows[_MeasurementTask]
    assert subject is session.rows[_Subject]


@pytest.mark.asyncio
@pytest.mark.parametrize("revoked_model", [_SchoolClassStudent, _TaskEnrollment])
async def test_task_assessment_scope_denies_revocation_seen_by_current_locking_read(revoked_model):
    session = _Session(revoked_model=revoked_model)
    adapter = _adapter(session)

    with pytest.raises(BackendError) as caught:
        await adapter._lock_school_assessment_write_scope(
            SimpleNamespace(session=session),
            SimpleNamespace(school_id=7),
            9,
            session.rows[_TaskEnrollment],
            at=datetime(2026, 10, 13, tzinfo=UTC),
        )

    assert caught.value.code is ErrorCode.RESOURCE_NOT_FOUND
    expected_reads = [_SchoolClassStudent]
    if revoked_model is _TaskEnrollment:
        expected_reads.append(_TaskEnrollment)
    assert session.lock_reads == expected_reads
