from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from database_layer.base import Base
from database_layer.models import SchoolPostAssessmentJob
from sqlalchemy import CheckConstraint, Column, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable


def _fk(table, name: str):
    return next(item for item in table.foreign_key_constraints if item.name == name)


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20261014_0011_post_assessment_job_outbox.py"
    )
    spec = spec_from_file_location("migration_20261014_0011", path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_job_outbox_is_content_free_idempotent_and_exactly_scoped():
    table = SchoolPostAssessmentJob.__table__
    assert len(Base.metadata.tables) == 46
    assert table.name == "school_post_assessment_jobs"
    assert table.c.status.server_default.arg == "QUEUED"
    assert table.c.attempt_count.server_default.arg == "0"
    assert {
        "payload", "payload_ciphertext", "answers", "response", "prompt", "report",
        "password", "password_hash", "note", "body", "title",
    }.isdisjoint(table.c.keys())

    unique = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert (
        "school_id", "assessment_session_id", "job_kind", "policy_version"
    ) in unique

    expected_scopes = {
        "fk_school_post_assessment_jobs_school": (
            ("school_id",), ("schools.id",),
        ),
        "fk_school_post_assessment_jobs_task_scope": (
            ("task_id", "school_id", "class_id"),
            ("measurement_tasks.id", "measurement_tasks.school_id", "measurement_tasks.class_id"),
        ),
        "fk_school_post_assessment_jobs_roster_scope": (
            ("class_student_id", "subject_id", "class_id", "school_id"),
            (
                "school_class_students.id", "school_class_students.subject_id",
                "school_class_students.class_id", "school_class_students.school_id",
            ),
        ),
        "fk_school_post_assessment_jobs_enrollment_scope": (
            ("task_enrollment_id", "task_id", "school_id", "subject_id"),
            (
                "task_enrollments.id", "task_enrollments.task_id",
                "task_enrollments.school_id", "task_enrollments.subject_id",
            ),
        ),
        "fk_school_post_assessment_jobs_assessment_scope": (
            ("assessment_session_id", "task_enrollment_id", "subject_id"),
            (
                "assessment_sessions.id", "assessment_sessions.task_enrollment_id",
                "assessment_sessions.subject_id",
            ),
        ),
        "fk_school_post_assessment_jobs_subject_scope": (
            ("subject_id", "school_id"), ("subjects.id", "subjects.school_id"),
        ),
    }
    for name, (local, remote) in expected_scopes.items():
        constraint = _fk(table, name)
        assert tuple(element.parent.name for element in constraint.elements) == local
        assert tuple(element.target_fullname for element in constraint.elements) == remote
        assert constraint.ondelete == "RESTRICT"

    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "EDUCATION_SUPPORT" in checks["ck_school_post_assessment_jobs_job_kind_allowed"]
    assert all(
        state in checks["ck_school_post_assessment_jobs_status_allowed"]
        for state in (
            "QUEUED", "LEASED", "RETRY", "HELD", "ABSTAINED", "REVIEW_REQUIRED",
            "CRISIS_ROUTED", "FAILED", "CANCELLED",
        )
    )
    assert "lease_owner" in checks["ck_school_post_assessment_jobs_lease_matches_status"]
    assert "lease_token" in checks["ck_school_post_assessment_jobs_lease_matches_status"]
    CreateTable(table).compile(dialect=mysql.dialect())


def test_outbox_migration_is_additive_and_downgrade_refuses_rows(monkeypatch):
    migration = _load_migration()
    assert migration.revision == "20261014_0011"
    assert migration.down_revision == "20261013_0010"
    operations = []

    class _Connection:
        def __init__(self, row_count=0):
            self.row_count = row_count

        def execute(self, statement):
            operations.append(("guard", str(statement)))
            return type("Result", (), {"scalar_one": lambda _self: self.row_count})()

    class _Ops:
        def __init__(self, row_count=0):
            self.row_count = row_count

        def __getattr__(self, name):
            if name == "get_bind":
                return lambda: _Connection(self.row_count)

            def record(*args, **kwargs):
                operations.append((name, *args, kwargs))

            return record

    monkeypatch.setattr(migration, "op", _Ops())
    migration.upgrade()
    created = [entry for entry in operations if entry[0] == "create_table"]
    assert len(created) == 1 and created[0][1] == "school_post_assessment_jobs"
    migrated_columns = {
        column.name
        for column in created[0][2:]
        if isinstance(column, Column)
    }
    assert migrated_columns == set(SchoolPostAssessmentJob.__table__.c.keys())
    assert not any(
        entry[0] in {"add_column", "drop_column", "drop_constraint", "execute"}
        for entry in operations
    )

    operations.clear()
    monkeypatch.setattr(migration, "op", _Ops(row_count=1))
    with pytest.raises(RuntimeError, match="cannot downgrade post-assessment jobs"):
        migration.downgrade()
    assert len(operations) == 1 and operations[0][0] == "guard"

    operations.clear()
    monkeypatch.setattr(migration, "op", _Ops())
    migration.downgrade()
    assert [entry[1] for entry in operations if entry[0] == "drop_table"] == [
        "school_post_assessment_jobs"
    ]
