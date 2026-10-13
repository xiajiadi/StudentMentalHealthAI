from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
import sqlalchemy as sa
from database_layer.base import Base
from database_layer.models import (
    MeasurementTask,
    SchoolResearchProfileVersion,
    SchoolResearchSession,
    SchoolResearchTaskBinding,
)
from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20261014_0012_research_cat_sessions.py"
    )
    spec = spec_from_file_location("migration_20261014_0012", path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _target_columns(constraint):
    return tuple(element.target_fullname.rsplit(".", 1)[-1] for element in constraint.elements)


def test_research_tables_are_separate_locked_and_mysql_compilable():
    assert len(Base.metadata.tables) == 45
    assert MeasurementTask.__table__.c.cat_binding_mode.server_default.arg == "FIXTURE"
    task_mode_check = next(
        constraint
        for constraint in MeasurementTask.__table__.constraints
        if isinstance(constraint, CheckConstraint) and "cat_binding_mode_allowed" in constraint.name
    )
    assert "RESEARCH_PROFILE" in str(task_mode_check.sqltext)

    expected = {
        "school_research_profile_versions": SchoolResearchProfileVersion,
        "school_research_task_bindings": SchoolResearchTaskBinding,
        "school_research_sessions": SchoolResearchSession,
    }
    for table_name, model in expected.items():
        table = Base.metadata.tables[table_name]
        assert model.__table__ is table
        compiled = str(CreateTable(table).compile(dialect=mysql.dialect()))
        assert "CREATE TABLE" in compiled and "FOREIGN KEY" in compiled
        assert "MEDIUMBLOB" in compiled
        assert {"id", "public_id", "created_at", "updated_at"} <= set(table.c.keys())
        assert not {"theta", "score", "band", "assessment_session_id"} & set(table.c.keys())
        for constraint in table.constraints:
            if isinstance(constraint, CheckConstraint):
                assert len(constraint.name.encode("utf-8")) <= 64
                assert f"CONSTRAINT {constraint.name} CHECK" in compiled

    profile = SchoolResearchProfileVersion.__table__
    binding = SchoolResearchTaskBinding.__table__
    session = SchoolResearchSession.__table__
    assert any(
        isinstance(item, UniqueConstraint)
        and tuple(col.name for col in item.columns)
        == ("id", "school_id", "profile_ref", "version_number", "profile_sha256")
        for item in profile.constraints
    )
    assert any(
        fk.referred_table.name == "task_enrollments"
        and tuple(element.parent.name for element in fk.elements)
        == ("task_enrollment_id", "task_id", "school_id", "subject_id")
        for fk in session.foreign_key_constraints
    )
    assert any(fk.referred_table.name == binding.name for fk in session.foreign_key_constraints)
    assert "PUBLIC_OBSERVED" in str(
        next(
            item.sqltext
            for item in binding.constraints
            if isinstance(item, CheckConstraint) and "response_origin_allowed" in item.name
        )
    )


def test_0012_migration_is_additive_and_refuses_populated_downgrade(monkeypatch):
    migration = _load_migration()
    assert migration.revision == "20261014_0012"
    assert migration.down_revision == "20261014_0011"
    operations = []

    class _Result:
        def __init__(self, value):
            self.value = value

        def scalar_one(self):
            return self.value

    class _Connection:
        def __init__(self, counts):
            self.counts = iter(counts)

        def execute(self, statement):
            operations.append(("count", str(statement)))
            return _Result(next(self.counts))

    class _Operations:
        def __init__(self, counts):
            self.connection = _Connection(counts)

        def get_bind(self):
            return self.connection

        def __getattr__(self, name):
            def record(*args, **kwargs):
                operations.append((name, args, kwargs))

            return record

    monkeypatch.setattr(migration, "op", _Operations([1]))
    with pytest.raises(RuntimeError, match="business rows exist"):
        migration.downgrade()
    assert len(operations) == 1
    assert operations[0][0] == "count"

    operations.clear()
    monkeypatch.setattr(migration, "op", _Operations([0, 0, 0, 0]))
    migration.downgrade()
    assert [entry[0] for entry in operations[:4]] == ["count"] * 4
    ddl = [entry for entry in operations[4:] if entry[0] != "count"]
    assert [entry[0] for entry in ddl] == [
        "drop_index",
        "drop_index",
        "drop_table",
        "drop_index",
        "drop_table",
        "drop_index",
        "drop_table",
        "drop_constraint",
        "create_check_constraint",
    ]
    assert operations[-1][1][1] == "measurement_tasks"
    assert "RESEARCH_PROFILE" not in operations[-1][1][2]


def test_upgrade_table_shapes_match_the_orm_metadata(monkeypatch):
    migration = _load_migration()
    created = {}

    class _Operations:
        def drop_constraint(self, *_args, **_kwargs):
            return None

        def create_check_constraint(self, *_args, **_kwargs):
            return None

        def create_table(self, name, *elements, **kwargs):
            created[name] = sa.Table(name, sa.MetaData(), *elements, **kwargs)

    monkeypatch.setattr(migration, "op", _Operations())
    migration.upgrade()

    for table_name in (
        "school_research_profile_versions",
        "school_research_task_bindings",
        "school_research_sessions",
    ):
        expected = Base.metadata.tables[table_name]
        actual = created[table_name]
        assert tuple(actual.c.keys()) == tuple(expected.c.keys())
        for column_name in expected.c.keys():
            assert actual.c[column_name].nullable is expected.c[column_name].nullable
            assert actual.c[column_name].type.compile(dialect=mysql.dialect()) == expected.c[
                column_name
            ].type.compile(dialect=mysql.dialect())
        expected_fks = {
            (
                tuple(element.parent.name for element in constraint.elements),
                _target_columns(constraint),
            )
            for constraint in expected.foreign_key_constraints
        }
        actual_fks = {
            (
                tuple(element.parent.name for element in constraint.elements),
                _target_columns(constraint),
            )
            for constraint in actual.foreign_key_constraints
        }
        assert actual_fks == expected_fks
        expected_unique = {
            tuple(column.name for column in constraint.columns)
            for constraint in expected.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        actual_unique = {
            tuple(column.name for column in constraint.columns)
            for constraint in actual.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        assert actual_unique == expected_unique
        expected_checks = {
            (
                constraint.name.removeprefix(f"ck_{table_name}_"),
                str(constraint.sqltext),
            )
            for constraint in expected.constraints
            if isinstance(constraint, CheckConstraint)
        }
        actual_checks = {
            (constraint.name, str(constraint.sqltext))
            for constraint in actual.constraints
            if isinstance(constraint, CheckConstraint)
        }
        assert actual_checks == expected_checks
