from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_restore_import as importer


class FakeConnection:
    def __init__(self, directory):
        self.identity = ("smhai_school_demo", 3310, str(directory), 1)
        self.inventory = [("accounts", "InnoDB"), ("auth_sessions", "InnoDB"),
                          ("database_alembic_version", "InnoDB")]
        self.columns = [("accounts", "id"), ("accounts", "password_hash"),
                        ("auth_sessions", "id"), ("auth_sessions", "revoked_at"),
                        ("database_alembic_version", "version_num")]
        self.revision = [(importer.SUPPORTED_REVISION,)]
        self.rows = {"accounts": 0, "auth_sessions": 0}
        self.initial_rows = dict(self.rows)
        self.sql = []
        self.committed = False
        self.rolled_back = False
        self.fail_insert = False
        self.count_mismatch = False
        self.active_sessions = 0
        self.inserted = {"accounts": [], "auth_sessions": []}
        self.value_mismatch = False

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        self.sql.append((sql, params))
        if sql.startswith("INSERT INTO"):
            if self.fail_insert:
                raise RuntimeError("sensitive synthetic parameter must not appear")
            name = sql.split("`")[1]
            self.rows[name] += 1
            self.inserted[name].append(tuple(params))

    def fetchone(self):
        sql = self.sql[-1][0]
        if sql.startswith("SELECT DATABASE"):
            return self.identity
        if "WHERE revoked_at IS NULL" in sql:
            return (self.active_sessions,)
        name = sql.split("`")[1]
        value = self.rows[name]
        if self.count_mismatch and any(s.startswith("INSERT") for s, _ in self.sql):
            value += 1
        return (value,)

    def fetchall(self):
        sql = self.sql[-1][0]
        if "information_schema.TABLES" in sql:
            return self.inventory
        if "information_schema.COLUMNS" in sql:
            return self.columns
        if "FROM `" in sql:
            values = self.inserted[sql.split("FROM `")[1].split("`")[0]]
            return [(999, "altered")] if self.value_mismatch else values
        return self.revision

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True
        self.rows = dict(self.initial_rows)


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    target = {
        "schema_version": "psynova.synthetic-restore-target.v1", "synthetic_only": True,
        "phase": "SCHEMA_READY", "database": "smhai_school_demo", "host": "127.0.0.1",
        "port": 3310, "workspace_id": "new-target", "source_workspace_id": "old-source",
        "workspace": str(tmp_path / "new-target"),
        "data_directory": str(tmp_path / "new-target" / "mysql-data"),
    }
    package = {"workspace_id": "old-source", "port": 3308}
    plan = {
        "revision": importer.SUPPORTED_REVISION, "table_order": ["accounts", "auth_sessions"],
        "tables": {
            "accounts": {"columns": ["id", "password_hash"], "rows": [[1, "synthetic-hash"]]},
            "auth_sessions": {"columns": ["id", "revoked_at"], "rows": [[1, datetime(2026, 10, 12, tzinfo=UTC)]]},
        },
        "row_counts": {"accounts": 1, "auth_sessions": 1}, "revoked_session_count": 1,
    }
    manifest = {"accounts": ["id", "password_hash"], "auth_sessions": ["id", "revoked_at"],
                "database_alembic_version": ["version_num"]}
    monkeypatch.setattr(importer, "plan_restore", lambda *_args, **_kwargs: plan)
    monkeypatch.setattr(importer, "trusted_manifest", lambda _revision: manifest)
    return FakeConnection(target["data_directory"]), package, target


def run(fixture):
    connection, package, target = fixture
    return importer.import_snapshot(connection, package, target, restored_at=datetime.now(UTC))


def test_import_is_parameterized_atomic_and_does_not_publish_ready(fixture):
    connection, _, _ = fixture
    result = run(fixture)
    assert connection.committed and not connection.rolled_back
    assert result["ready"] is False
    assert result["row_count"] == 2
    statements = [sql for sql, _ in connection.sql]
    assert "START TRANSACTION" in statements
    assert not any("DROP" in sql or "CREATE" in sql or "FOREIGN_KEY_CHECKS=0" in sql for sql in statements)
    inserts = [(sql, params) for sql, params in connection.sql if sql.startswith("INSERT")]
    assert all("%s" in sql for sql, _ in inserts)
    assert all("synthetic-hash" not in sql for sql, _ in inserts)


@pytest.mark.parametrize("case", ["identity", "foreign_keys", "tables", "columns", "revision", "existing"])
def test_live_target_mismatch_refuses_any_insert(fixture, case):
    connection, _, _ = fixture
    if case == "identity":
        connection.identity = ("smhai_school_demo", 3308, connection.identity[2], 1)
    elif case == "foreign_keys":
        connection.identity = (*connection.identity[:3], 0)
    elif case == "tables":
        connection.inventory.append(("unexpected", "InnoDB"))
    elif case == "columns":
        connection.columns.append(("accounts", "unexpected"))
    elif case == "revision":
        connection.revision = [("wrong",)]
    elif case == "existing":
        connection.rows["accounts"] = 1
        connection.initial_rows = dict(connection.rows)
    with pytest.raises(importer.RestoreImportError):
        run(fixture)
    assert not any(sql.startswith("INSERT") for sql, _ in connection.sql)
    assert not connection.committed


@pytest.mark.parametrize("case", ["failure", "count", "sessions", "values"])
def test_import_failure_rolls_back_without_exposing_parameters(fixture, case):
    connection, _, _ = fixture
    connection.fail_insert = case == "failure"
    connection.count_mismatch = case == "count"
    connection.active_sessions = int(case == "sessions")
    connection.value_mismatch = case == "values"
    with pytest.raises(importer.RestoreImportError) as error:
        run(fixture)
    assert "sensitive synthetic" not in str(error.value)
    assert connection.rolled_back and not connection.committed
    assert connection.rows == connection.initial_rows


def test_source_workspace_cannot_be_restore_target(fixture):
    connection, package, target = fixture
    target["workspace_id"] = package["workspace_id"]
    with pytest.raises(importer.RestoreImportError, match="Distinct"):
        run(fixture)
    assert connection.sql == []


def test_invalid_snapshot_stops_before_database_access(fixture, monkeypatch):
    connection, _, _ = fixture

    def reject(*_args, **_kwargs):
        raise ValueError("invalid snapshot")

    monkeypatch.setattr(importer, "plan_restore", reject)
    with pytest.raises(ValueError, match="invalid snapshot"):
        run(fixture)
    assert connection.sql == []
