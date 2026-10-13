from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from database_layer.base import Base
from database_layer.models import SchoolFeedbackEvent, SchoolFeedbackRecord
from sqlalchemy import Boolean, CheckConstraint, Column, Integer, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable


def _fk_targets(table, name: str) -> tuple[str, ...]:
    constraint = next(item for item in table.foreign_key_constraints if item.name == name)
    return tuple(element.target_fullname for element in constraint.elements)


def test_feedback_schema_is_separate_encrypted_scoped_and_l3_only() -> None:
    assert len(Base.metadata.tables) == 42
    records = Base.metadata.tables["school_feedback_records"]
    events = Base.metadata.tables["school_feedback_events"]
    assert isinstance(SchoolFeedbackRecord.__table__.c.synthetic_only.type, Boolean)
    assert isinstance(SchoolFeedbackEvent.__table__.c.state_version.type, Integer)

    assert _fk_targets(records, "fk_school_feedback_review_case_exact_scope") == (
        "school_professional_review_cases.id",
        "school_professional_review_cases.school_id",
        "school_professional_review_cases.task_id",
        "school_professional_review_cases.class_id",
        "school_professional_review_cases.task_enrollment_id",
        "school_professional_review_cases.subject_id",
        "school_professional_review_cases.assessment_session_id",
    )
    assert _fk_targets(records, "fk_school_feedback_task_scope") == (
        "measurement_tasks.id",
        "measurement_tasks.school_id",
        "measurement_tasks.class_id",
    )
    assert _fk_targets(records, "fk_school_feedback_enrollment_scope") == (
        "task_enrollments.id",
        "task_enrollments.task_id",
        "task_enrollments.school_id",
        "task_enrollments.subject_id",
    )
    assert _fk_targets(records, "fk_school_feedback_assessment_scope") == (
        "assessment_sessions.id",
        "assessment_sessions.task_enrollment_id",
        "assessment_sessions.subject_id",
    )
    assert _fk_targets(records, "fk_school_feedback_subject_scope") == (
        "subjects.id",
        "subjects.school_id",
    )
    assert _fk_targets(records, "fk_school_feedback_school") == ("schools.id",)
    assert _fk_targets(events, "fk_school_feedback_events_record_scope") == (
        "school_feedback_records.id",
        "school_feedback_records.school_id",
        "school_feedback_records.review_case_id",
        "school_feedback_records.content_revision",
    )
    assert _fk_targets(events, "fk_school_feedback_events_actor_school") == (
        "membership_roles.id",
        "membership_roles.school_id",
    )
    assert _fk_targets(events, "fk_school_feedback_events_school") == ("schools.id",)

    for table in (records, events):
        assert all(
            element.ondelete == "RESTRICT"
            for constraint in table.foreign_key_constraints
            for element in constraint.elements
        )
        CreateTable(table).compile(dialect=mysql.dialect())

    assert records.c.payload_ciphertext.type.python_type is bytes
    for table in (records, events):
        assert {"title", "body", "case_note", "case_note_ciphertext", "note_ciphertext"}.isdisjoint(
            table.c.keys()
        )
    assert "synthetic_only = 1" in str(
        next(
            item
            for item in records.constraints
            if isinstance(item, CheckConstraint)
            and item.name == "ck_school_feedback_records_synthetic_only_locked"
        ).sqltext
    )
    assert "level = 'L3'" in str(
        next(
            item
            for item in records.constraints
            if isinstance(item, CheckConstraint)
            and item.name == "ck_school_feedback_records_level_synthetic_l3_only"
        ).sqltext
    )
    assert any(
        isinstance(item, UniqueConstraint)
        and tuple(column.name for column in item.columns) == ("review_case_id", "content_revision")
        for item in records.constraints
    )
    case = Base.metadata.tables["school_professional_review_cases"]
    assert any(
        isinstance(item, UniqueConstraint)
        and tuple(column.name for column in item.columns)
        == (
            "id",
            "school_id",
            "task_id",
            "class_id",
            "task_enrollment_id",
            "subject_id",
            "assessment_session_id",
        )
        for item in case.constraints
    )


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20261013_0010_school_feedback_publication.py"
    )
    spec = spec_from_file_location("migration_20261013_0010", path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_feedback_migration_is_additive_and_downgrade_refuses_business_rows(monkeypatch) -> None:
    migration = _load_migration()
    assert migration.revision == "20261013_0010"
    assert migration.down_revision == "20261013_0009"
    operations: list[tuple[object, ...]] = []

    class _Connection:
        def __init__(self, populated_table: str | None = None) -> None:
            self.populated_table = populated_table

        def execute(self, statement):
            text = str(statement)
            operations.append(("guard", text))
            populated = self.populated_table is not None and self.populated_table in text
            return type("Result", (), {"scalar_one": lambda _self: int(populated)})()

    class _Ops:
        def __init__(self, populated_table: str | None = None) -> None:
            self.populated_table = populated_table

        def __getattr__(self, name):
            if name == "get_bind":
                return lambda: _Connection(self.populated_table)

            def record(*args, **kwargs):
                operations.append((name, *args, kwargs))

            return record

    monkeypatch.setattr(migration, "op", _Ops())
    migration.upgrade()
    assert ("create_unique_constraint", "school_professional_review_feedback_scope_unique") in [
        (entry[0], entry[1]) for entry in operations if entry[0] == "create_unique_constraint"
    ]
    created = {entry[1]: entry for entry in operations if entry[0] == "create_table"}
    assert set(created) == {"school_feedback_records", "school_feedback_events"}
    assert not any(
        entry[0] in {"add_column", "drop_column", "execute", "drop_constraint"}
        for entry in operations
    )
    record_columns = {
        column.name
        for column in created["school_feedback_records"][2:-1]
        if isinstance(column, Column)
    }
    event_columns = {
        column.name
        for column in created["school_feedback_events"][2:-1]
        if isinstance(column, Column)
    }
    assert record_columns == set(SchoolFeedbackRecord.__table__.c.keys())
    assert event_columns == set(SchoolFeedbackEvent.__table__.c.keys())
    assert {
        "payload_ciphertext",
        "case_version",
        "state_version",
        "retention_due_at",
    } <= record_columns
    assert {"title", "body", "case_note_ciphertext"}.isdisjoint(record_columns)

    for populated_table in migration._BUSINESS_TABLES:
        operations.clear()
        monkeypatch.setattr(migration, "op", _Ops(populated_table))
        with pytest.raises(RuntimeError, match="cannot downgrade school feedback"):
            migration.downgrade()
        assert operations and all(entry[0] == "guard" for entry in operations)

    operations.clear()
    monkeypatch.setattr(migration, "op", _Ops())
    migration.downgrade()
    assert [entry[1] for entry in operations if entry[0] == "drop_table"] == [
        "school_feedback_events",
        "school_feedback_records",
    ]
    assert any(
        entry[0] == "drop_constraint"
        and entry[1] == "school_professional_review_feedback_scope_unique"
        for entry in operations
    )
