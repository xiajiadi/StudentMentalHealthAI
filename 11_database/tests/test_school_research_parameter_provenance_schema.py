from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
import sqlalchemy as sa
from database_layer.base import Base
from database_layer.models import SchoolResearchProfileVersion
from sqlalchemy import CheckConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20261014_0013_research_parameter_provenance.py"
    )
    spec = spec_from_file_location("migration_20261014_0013", path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _load_0012_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20261014_0012_research_cat_sessions.py"
    )
    spec = spec_from_file_location("migration_20261014_0012_projection", path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_profile_parameter_provenance_schema_is_additive_locked_and_mysql_compilable():
    assert len(Base.metadata.tables) == 65
    table = SchoolResearchProfileVersion.__table__
    assert table.c.fit_sha256.nullable is True
    assert table.c.calibration_sha256.nullable is True
    assert table.c.published_parameter_crosswalk_sha256.nullable is True
    assert (
        table.c.published_parameter_crosswalk_sha256.type.compile(dialect=mysql.dialect())
        == "VARCHAR(64) COLLATE ascii_bin"
    )
    assert table.c.parameter_origin.type.compile(dialect=mysql.dialect()) == (
        "VARCHAR(32) COLLATE ascii_bin"
    )
    assert table.c.parameter_origin.nullable is False
    assert table.c.parameter_origin.server_default.arg == "LOCAL_RESEARCH_FIT"
    assert table.c.parameter_origin.default.arg == "LOCAL_RESEARCH_FIT"

    columns = list(table.c.keys())
    assert columns.index("parameter_origin") == columns.index("disabled_at") + 1
    assert (
        columns.index("published_parameter_crosswalk_sha256")
        == columns.index("parameter_origin") + 1
    )
    assert columns.index("id") > columns.index("published_parameter_crosswalk_sha256")

    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    origin_check = checks["ck_school_research_profile_versions_parameter_origin_allowed"]
    provenance_check = checks["ck_school_research_profile_versions_parameter_provenance_shape"]
    assert "LOCAL_RESEARCH_FIT" in origin_check
    assert "PUBLISHED_ROUNDED_REFERENCE" in origin_check
    assert "fit_sha256 IS NOT NULL" in provenance_check
    assert "calibration_sha256 IS NOT NULL" in provenance_check
    assert "published_parameter_crosswalk_sha256 IS NULL" in provenance_check
    assert "fit_sha256 IS NULL" in provenance_check
    assert "calibration_sha256 IS NULL" in provenance_check
    assert "published_parameter_crosswalk_sha256 IS NOT NULL" in provenance_check
    assert any(name.endswith("_research_only_locked") for name in checks)
    assert any(name.endswith("_human_curated_false") for name in checks)
    assert any(name.endswith("_interpretation_forbidden") for name in checks)

    compiled = str(CreateTable(table).compile(dialect=mysql.dialect()))
    assert "CREATE TABLE school_research_profile_versions" in compiled
    assert "parameter_origin VARCHAR(32) COLLATE ascii_bin NOT NULL" in compiled
    assert "DEFAULT 'LOCAL_RESEARCH_FIT'" in compiled
    assert "published_parameter_crosswalk_sha256 VARCHAR(64) COLLATE ascii_bin" in compiled
    for name in checks:
        assert len(name.encode("ascii")) <= 64
        assert f"CONSTRAINT {name} CHECK" in compiled


def test_0013_upgrade_alters_fit_nullability_and_appends_columns_in_model_order(monkeypatch):
    migration = _load_migration()
    assert migration.revision == "20261014_0013"
    assert migration.down_revision == "20261014_0012"
    operations = []

    class _Operations:
        def __getattr__(self, name):
            def record(*args, **kwargs):
                operations.append((name, args, kwargs))

            return record

    monkeypatch.setattr(migration, "op", _Operations())
    migration.upgrade()
    assert [operation[0] for operation in operations] == [
        "alter_column",
        "alter_column",
        "execute",
        "execute",
        "create_check_constraint",
        "create_check_constraint",
    ]
    for operation in operations[:2]:
        assert operation[1][0] == "school_research_profile_versions"
        assert operation[2]["existing_nullable"] is False
        assert operation[2]["nullable"] is True
    origin_ddl = str(operations[2][1][0])
    crosswalk_ddl = str(operations[3][1][0])
    assert "ADD COLUMN parameter_origin" in origin_ddl
    assert "DEFAULT 'LOCAL_RESEARCH_FIT' AFTER disabled_at" in origin_ddl
    assert "ADD COLUMN published_parameter_crosswalk_sha256" in crosswalk_ddl
    assert "AFTER parameter_origin" in crosswalk_ddl
    assert [operation[1][0] for operation in operations[4:]] == [
        "parameter_origin_allowed",
        "parameter_provenance_shape",
    ]


def test_0012_then_0013_ddl_projection_matches_current_profile_orm(monkeypatch):
    base_migration = _load_0012_migration()
    migration = _load_migration()
    created = {}

    class _BaseOperations:
        def drop_constraint(self, *_args, **_kwargs):
            return None

        def create_check_constraint(self, *_args, **_kwargs):
            return None

        def create_table(self, name, *elements, **kwargs):
            created[name] = sa.Table(name, sa.MetaData(), *elements, **kwargs)

    monkeypatch.setattr(base_migration, "op", _BaseOperations())
    base_migration.upgrade()
    baseline = created["school_research_profile_versions"]
    additions = []
    added_checks = []

    class _ProvenanceOperations:
        def alter_column(self, table_name, column_name, **kwargs):
            assert table_name == "school_research_profile_versions"
            baseline.c[column_name].nullable = kwargs["nullable"]

        def execute(self, statement):
            sql = str(statement)
            if "ADD COLUMN parameter_origin" in sql:
                additions.append(
                    (
                        sa.Column(
                            "parameter_origin",
                            sa.String(32, collation="ascii_bin"),
                            nullable=False,
                            server_default="LOCAL_RESEARCH_FIT",
                        ),
                        "disabled_at",
                    )
                )
            elif "ADD COLUMN published_parameter_crosswalk_sha256" in sql:
                additions.append(
                    (
                        sa.Column(
                            "published_parameter_crosswalk_sha256",
                            sa.String(64, collation="ascii_bin"),
                            nullable=True,
                        ),
                        "parameter_origin",
                    )
                )
            else:
                raise AssertionError("unexpected 0013 DDL")

        def create_check_constraint(self, name, table_name, expression):
            assert table_name == "school_research_profile_versions"
            added_checks.append((name, expression))

    monkeypatch.setattr(migration, "op", _ProvenanceOperations())
    migration.upgrade()

    final_columns = list(baseline.columns)
    for column, after_name in additions:
        index = next(i for i, existing in enumerate(final_columns) if existing.name == after_name)
        final_columns.insert(index + 1, column)
    expected = SchoolResearchProfileVersion.__table__
    assert [column.name for column in final_columns] == list(expected.c.keys())
    for actual, target in zip(final_columns, expected.c, strict=True):
        assert actual.type.compile(dialect=mysql.dialect()) == target.type.compile(
            dialect=mysql.dialect()
        )
        assert actual.nullable is target.nullable
        actual_default = str(actual.server_default.arg) if actual.server_default else None
        expected_default = str(target.server_default.arg) if target.server_default else None
        assert actual_default == expected_default

    baseline_checks = {
        (constraint.name, str(constraint.sqltext))
        for constraint in baseline.constraints
        if isinstance(constraint, CheckConstraint)
    }
    current_checks = {
        (
            constraint.name.removeprefix("ck_school_research_profile_versions_"),
            str(constraint.sqltext),
        )
        for constraint in expected.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert baseline_checks | set(added_checks) == current_checks


@pytest.mark.parametrize(
    "counts",
    ([1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]),
)
def test_0013_downgrade_checks_every_profile_binding_session_and_task_before_ddl(
    monkeypatch, counts
):
    migration = _load_migration()
    operations = []

    class _Result:
        def __init__(self, value):
            self.value = value

        def scalar_one(self):
            return self.value

    class _Connection:
        def __init__(self):
            self.counts = iter(counts)

        def execute(self, statement):
            operations.append(("count", str(statement)))
            return _Result(next(self.counts))

    class _Operations:
        def __init__(self):
            self.connection = _Connection()

        def get_bind(self):
            return self.connection

        def __getattr__(self, name):
            def record(*args, **kwargs):
                operations.append((name, args, kwargs))

            return record

    monkeypatch.setattr(migration, "op", _Operations())
    with pytest.raises(RuntimeError, match="research rows or tasks exist"):
        migration.downgrade()
    assert [operation[0] for operation in operations] == ["count"] * 4
    sql = [operation[1] for operation in operations]
    assert "FROM school_research_profile_versions" in sql[0]
    assert "FROM school_research_task_bindings" in sql[1]
    assert "FROM school_research_sessions" in sql[2]
    assert "FROM measurement_tasks" in sql[3]
    assert "cat_binding_mode = 'RESEARCH_PROFILE'" in sql[3]


def test_0013_empty_downgrade_restores_required_fit_hashes_after_all_prechecks(
    monkeypatch,
):
    migration = _load_migration()
    operations = []

    class _Result:
        def scalar_one(self):
            return 0

    class _Connection:
        def execute(self, statement):
            operations.append(("count", str(statement)))
            return _Result()

    class _Operations:
        def get_bind(self):
            return _Connection()

        def __getattr__(self, name):
            def record(*args, **kwargs):
                operations.append((name, args, kwargs))

            return record

    monkeypatch.setattr(migration, "op", _Operations())
    migration.downgrade()
    assert [operation[0] for operation in operations[:4]] == ["count"] * 4
    assert [operation[0] for operation in operations[4:]] == [
        "drop_constraint",
        "drop_constraint",
        "drop_column",
        "drop_column",
        "alter_column",
        "alter_column",
    ]
    for operation in operations[-2:]:
        assert operation[2]["existing_nullable"] is True
        assert operation[2]["nullable"] is False
