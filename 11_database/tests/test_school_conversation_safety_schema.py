from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from database_layer.base import Base
from database_layer.models import (
    SchoolConversationSafetyCase,
    SchoolConversationSafetyEvent,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable


def _migration():
    path = Path(__file__).parents[1] / "migrations" / "versions" / (
        "20261015_0019_school_conversation_safety_cases.py"
    )
    spec = importlib.util.spec_from_file_location("school_conversation_safety_0019", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _OperationRecorder:
    def __init__(self, *, case_count: int = 0, event_count: int = 0) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.case_count = case_count
        self.event_count = event_count

    def get_bind(self):
        return self

    def execute(self, statement):
        self.calls.append(("execute", (str(statement),), {}))
        count = self.case_count if "safety_cases" in str(statement) else self.event_count
        return _Scalar(count)

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return record


class _Scalar:
    def __init__(self, value: int) -> None:
        self.value = value

    def scalar_one(self) -> int:
        return self.value


def test_0019_migration_and_model_have_matching_mysql_scope_and_private_columns(monkeypatch):
    migration = _migration()
    assert migration.revision == "20261015_0019"
    assert migration.down_revision == "20261014_0018"

    recorder = _OperationRecorder()
    monkeypatch.setattr(migration, "op", recorder)
    migration.upgrade()
    creates = {
        args[0]: args[1:]
        for name, args, _kwargs in recorder.calls
        if name == "create_table"
    }
    assert set(creates) == {
        "school_conversation_safety_cases",
        "school_conversation_safety_events",
    }

    expected_unique_additions = {
        ("support_sessions", ("id", "subject_id")),
        ("support_runs", ("id", "support_session_id")),
        ("safety_decisions", ("id", "support_run_id")),
    }
    actual_unique_additions = {
        (args[1], tuple(args[2]))
        for name, args, _kwargs in recorder.calls
        if name == "create_unique_constraint"
    }
    assert actual_unique_additions == expected_unique_additions

    metadata = sa.MetaData()
    external_columns = {
        "support_sessions": ("id", "subject_id"),
        "support_runs": ("id", "support_session_id"),
        "safety_decisions": ("id", "support_run_id"),
        "subjects": ("id", "school_id"),
        "school_class_students": ("id", "subject_id", "class_id", "school_id"),
        "membership_roles": ("id", "school_id"),
        "schools": ("id",),
    }
    for external_table, columns in external_columns.items():
        sa.Table(external_table, metadata, *(sa.Column(column, sa.Integer()) for column in columns))

    for table_name, args in creates.items():
        table = sa.Table(table_name, metadata, *args)
        model_table = Base.metadata.tables[table_name]
        assert tuple(table.columns.keys()) == tuple(model_table.columns.keys())
        assert {
            (item.name, tuple(column.name for column in item.columns))
            for item in table.constraints
            if isinstance(item, sa.UniqueConstraint)
        } == {
            (item.name, tuple(column.name for column in item.columns))
            for item in model_table.constraints
            if isinstance(item, sa.UniqueConstraint)
        }
        assert {
            (item.name, str(item.sqltext))
            for item in table.constraints
            if isinstance(item, sa.CheckConstraint)
        } == {
            (item.name, str(item.sqltext))
            for item in model_table.constraints
            if isinstance(item, sa.CheckConstraint)
        }
        assert {
            (
                item.name,
                tuple(element.parent.name for element in item.elements),
                tuple(element.target_fullname for element in item.elements),
            )
            for item in table.foreign_key_constraints
        } == {
            (
                item.name,
                tuple(element.parent.name for element in item.elements),
                tuple(element.target_fullname for element in item.elements),
            )
            for item in model_table.foreign_key_constraints
        }
        for constraint in table.constraints:
            if constraint.name:
                assert len(constraint.name) <= 64
        CreateTable(table).compile(dialect=mysql.dialect())

    case_columns = set(SchoolConversationSafetyCase.__table__.columns.keys())
    event_columns = set(SchoolConversationSafetyEvent.__table__.columns.keys())
    assert "review_note_ciphertext" in case_columns
    assert {"reason_codes", "action", "safety_review_reference"} <= case_columns
    assert not {"message", "content", "payload", "assessment_session_id"}.intersection(case_columns)
    assert not {"message", "content", "payload", "reason_codes"}.intersection(event_columns)


def test_0019_downgrade_refuses_existing_case_data_before_any_ddl(monkeypatch):
    migration = _migration()
    recorder = _OperationRecorder(case_count=1)
    monkeypatch.setattr(migration, "op", recorder)
    try:
        migration.downgrade()
    except RuntimeError as exc:
        assert str(exc) == "0019 downgrade refused because conversation safety data exists"
    else:  # pragma: no cover - guard regression
        raise AssertionError("nonempty conversation safety rows were not protected")
    assert not any(
        name.startswith("drop_") for name, _args, _kwargs in recorder.calls
    )
