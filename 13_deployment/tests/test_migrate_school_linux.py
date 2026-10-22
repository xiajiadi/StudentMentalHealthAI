from __future__ import annotations

import json
import os
import sys

import migrate_school_linux as migration
from alembic import command
from alembic.script import ScriptDirectory


def test_alembic_receives_authenticated_connection_without_database_url(
    tmp_path, monkeypatch
):
    database_root = tmp_path / "11_database"
    database_root.mkdir()
    (database_root / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
    migrations_root = database_root / "migrations"
    migrations_root.mkdir()
    connection = object()
    observed = {}

    def capture_upgrade(config, revision):
        observed["connection"] = config.attributes["connection"]
        observed["revision"] = revision
        observed["script_location"] = ScriptDirectory.from_config(config).dir

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(command, "upgrade", capture_upgrade)

    migration._run_alembic_upgrade(tmp_path, connection)

    assert observed == {
        "connection": connection,
        "revision": migration.EXPECTED_REVISION,
        "script_location": str(migrations_root),
    }
    assert "DATABASE_URL" not in os.environ


def test_migration_stage_error_contains_only_bounded_diagnostics():
    error = migration._MigrationStageError("credential_load", "ConfigurationError")

    assert error.phase == "credential_load"
    assert error.error_type == "ConfigurationError"
    assert "password" not in str(error).lower()


def test_migration_entrypoint_reports_phase_and_error_type_only(
    tmp_path, monkeypatch, capsys
):
    def raise_stage_error(_repository_root):
        raise migration._MigrationStageError("alembic_upgrade", "CommandError")

    monkeypatch.setattr(migration, "migrate", raise_stage_error)
    monkeypatch.setattr(
        sys, "argv", ["migrate_school_linux.py", "--repo-root", str(tmp_path)]
    )

    assert migration.main() == 2
    assert json.loads(capsys.readouterr().out) == {
        "migration": "BLOCKED",
        "phase": "alembic_upgrade",
        "error_type": "CommandError",
    }
