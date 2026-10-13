import sys
import types
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_backup
from private_settings import MAGIC


def snapshot_content():
    return {
        "schema_version": school_backup.BACKUP_V1,
        "project": "StudentMentalHealthAI",
        "synthetic_only": True,
        "workspace_id": "synthetic-source-1",
        "database": "smhai_school_demo",
        "port": 3308,
        "revision": school_backup.SUPPORTED_REVISION,
        "tables": {
            "demo_table": {
                "create_sql": "CREATE TABLE `demo_table` (`id` INT)",
                "columns": ["id", "payload"],
                "rows": [[1, {"type": "bytes", "value": "AA=="}]],
            }
        },
    }


def _marker():
    return {
        "workspace_id": "synthetic-source-1",
        "database": "smhai_school_demo",
        "port": 3308,
        "data_directory": r"D:\synthetic\mysql-data",
    }


def _runtime_grants():
    return (
        ("GRANT USAGE ON *.* TO 'runtime'",),
        ("GRANT SELECT, INSERT, UPDATE, DELETE ON `smhai_school_demo`.* TO 'runtime'",),
    )


@pytest.mark.parametrize("value", [None, "stored-json", 17, 2.5, True])
def test_plain_values_retained(value):
    assert school_backup.encode_value(value) == value
    assert school_backup.decode_value(value) == value


def test_typed_database_values_round_trip_without_decryption():
    examples = [
        b"encrypted-bytes",
        datetime(2026, 10, 11, 12, 30, 1, 123456),  # noqa: DTZ001 - MySQL returns naive DATETIME.
        date(2026, 10, 11),
        Decimal("12.30"),
    ]
    for value in examples:
        assert school_backup.decode_value(school_backup.encode_value(value)) == value
    assert school_backup.encode_value(b"encrypted-bytes") == {
        "type": "bytes",
        "value": "ZW5jcnlwdGVkLWJ5dGVz",
    }


@pytest.mark.parametrize(
    "value",
    [
        {"type": "bytes", "value": "%%"},
        {"type": "date", "value": "2026-02-30"},
        {"type": "datetime", "value": "2026-10-11"},
        {"type": "decimal", "value": "NaN"},
        {"type": "decimal", "value": "not-a-number"},
        {"type": "unknown", "value": "x"},
        {"type": "bytes", "value": "AA==", "extra": True},
        {"type": "bytes"},
        float("inf"),
    ],
)
def test_decode_rejects_invalid_or_ambiguous_values(value):
    with pytest.raises(ValueError):
        school_backup.decode_value(value)


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), float("nan"), float("inf")])
def test_encode_rejects_nonfinite_values(value):
    with pytest.raises(TypeError, match="Non-finite backup value"):
        school_backup.encode_value(value)


def test_encode_rejects_unsupported_values():
    with pytest.raises(TypeError, match="Unsupported backup value"):
        school_backup.encode_value(object())


def test_package_v2_contains_only_the_sealed_key_container_and_restore_policy():
    sealed_key_file = MAGIC + b"synthetic-protected-bytes"
    package = school_backup.package_snapshot(snapshot_content(), sealed_key_file)

    assert school_backup.validate_backup_package(package) is package
    assert package["schema_version"] == school_backup.BACKUP_V2
    assert package["database_key_container_b64"] == school_backup.base64.b64encode(
        sealed_key_file
    ).decode("ascii")
    assert package["recovery_scope"] == "WINDOWS_CURRENT_USER_ONLY"
    assert package["target_policy"] == "NEW_ISOLATED_INSTANCE_ONLY"
    assert package["auth_session_policy"] == "REVOKE_ALL_AFTER_IMPORT"
    assert not {"runtime", "root_password", "DB_PASSWORD", "csrf_secret"} & set(package)
    assert "restore_workflow" not in package


def test_v1_backup_is_explicitly_not_independently_restorable():
    with pytest.raises(ValueError, match="v1 backup lacks the key bundle"):
        school_backup.validate_backup_package(snapshot_content())


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: p.update(synthetic_only=False), "Unsupported synthetic backup source"),
        (lambda p: p.update(revision="20261011_0004"), "Unsupported synthetic backup source"),
        (lambda p: p.update(project="other"), "Unsupported synthetic backup source"),
        (lambda p: p.update(workspace_id=""), "Unsupported synthetic backup source"),
        (lambda p: p.update(port=True), "Unsupported synthetic backup source"),
        (
            lambda p: p.update(database_key_container_b64="bad"),
            "Invalid sealed database key container",
        ),
        (
            lambda p: p["tables"]["demo_table"].update(columns=["id", "id"]),
            "Invalid backup table columns or rows",
        ),
        (
            lambda p: p["tables"]["demo_table"].update(columns=["id", "bad-name"]),
            "Invalid backup table columns or rows",
        ),
        (
            lambda p: p["tables"]["demo_table"].update(rows=[[1]]),
            "Backup row width does not match columns",
        ),
        (
            lambda p: p["tables"].update({"demo-table": p["tables"].pop("demo_table")}),
            "Invalid backup table name",
        ),
        (lambda p: p.update(unexpected="secret"), "Unsupported or incomplete backup package"),
    ],
)
def test_package_validation_fails_closed(mutate, message):
    package = school_backup.package_snapshot(
        snapshot_content(), MAGIC + b"synthetic-protected-bytes"
    )
    mutate(package)
    with pytest.raises(ValueError, match=message):
        school_backup.validate_backup_package(package)


def test_package_validator_treats_archived_ddl_as_opaque_data():
    package = school_backup.package_snapshot(
        snapshot_content(), MAGIC + b"synthetic-protected-bytes"
    )
    package["tables"]["demo_table"]["create_sql"] = "DROP DATABASE unrelated"

    assert school_backup.validate_backup_package(package) is package


class WrongTargetConnection:
    def __init__(self):
        self.rolled_back = False
        self.sql = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql):
        self.sql.append(sql)

    def fetchone(self):
        if self.sql[-1] == "SELECT CURRENT_ROLE()":
            return ("NONE",)
        return ("unowned_database", 3306, r"D:\wrong\data", "REPEATABLE-READ")

    def fetchall(self):
        if self.sql[-1] == "SHOW GRANTS FOR CURRENT_USER()":
            return _runtime_grants()
        return ()

    def rollback(self):
        self.rolled_back = True


def test_wrong_database_rejected_before_content_read():
    connection = WrongTargetConnection()
    with pytest.raises(ValueError, match="Owned consistent snapshot target required"):
        school_backup.snapshot(connection, _marker(), expected_binding=school_backup._marker_binding(_marker()))
    assert connection.rolled_back
    assert not any("information_schema" in sql or sql.startswith("SELECT *") for sql in connection.sql)


@pytest.mark.parametrize("revision", sorted(school_backup.SUPPORTED_BACKUP_REVISIONS))
def test_snapshot_accepts_each_explicit_supported_revision(revision):
    class RevisionConnection(WrongTargetConnection):
        def fetchone(self):
            if self.sql[-1] == "SELECT CURRENT_ROLE()":
                return ("NONE",)
            if self.sql[-1].startswith("SELECT DATABASE()"):
                return ("smhai_school_demo", 3308, _marker()["data_directory"], "REPEATABLE-READ")
            return (revision,)

        def fetchall(self):
            if self.sql[-1] == "SHOW GRANTS FOR CURRENT_USER()":
                return _runtime_grants()
            if self.sql[-1].startswith("SELECT version_num"):
                return ((revision,),)
            return []

    connection = RevisionConnection()
    result = school_backup.snapshot(
        connection, _marker(), expected_binding=school_backup._marker_binding(_marker())
    )
    assert result["revision"] == revision
    assert connection.rolled_back


def test_snapshot_requires_one_exact_revision_and_preserves_preflight_revision():
    class RevisionRowsConnection(WrongTargetConnection):
        def __init__(self, revision_rows):
            super().__init__()
            self.revision_rows = revision_rows

        def fetchone(self):
            if self.sql[-1] == "SELECT CURRENT_ROLE()":
                return ("NONE",)
            if self.sql[-1].startswith("SELECT DATABASE()"):
                return ("smhai_school_demo", 3308, _marker()["data_directory"], "REPEATABLE-READ")
            return super().fetchone()

        def fetchall(self):
            if self.sql[-1] == "SHOW GRANTS FOR CURRENT_USER()":
                return _runtime_grants()
            if self.sql[-1].startswith("SELECT version_num"):
                return self.revision_rows
            return []

    known_revision = next(iter(school_backup.SUPPORTED_BACKUP_REVISIONS))
    multi = RevisionRowsConnection(((known_revision,), (known_revision,)))
    with pytest.raises(ValueError, match="Unsupported backup schema revision"):
        school_backup.snapshot(
            multi,
            _marker(),
            expected_revision=known_revision,
            expected_binding=school_backup._marker_binding(_marker()),
        )
    assert multi.rolled_back
    assert not any("information_schema" in sql for sql in multi.sql)

    drifted = RevisionRowsConnection(((known_revision,),))
    other_revision = next(
        revision
        for revision in school_backup.SUPPORTED_BACKUP_REVISIONS
        if revision != known_revision
    )
    with pytest.raises(ValueError, match="Unsupported backup schema revision"):
        school_backup.snapshot(
            drifted,
            _marker(),
            expected_revision=other_revision,
            expected_binding=school_backup._marker_binding(_marker()),
        )
    assert drifted.rolled_back
    assert not any("information_schema" in sql for sql in drifted.sql)


def test_snapshot_rejects_unapproved_revision_before_table_read():
    class FutureConnection(WrongTargetConnection):
        def fetchone(self):
            if self.sql[-1] == "SELECT CURRENT_ROLE()":
                return ("NONE",)
            if self.sql[-1].startswith("SELECT DATABASE()"):
                return ("smhai_school_demo", 3308, _marker()["data_directory"], "REPEATABLE-READ")
            return ("unapproved_head",)

    connection = FutureConnection()
    with pytest.raises(ValueError, match="Unsupported backup schema revision"):
        school_backup.snapshot(connection, _marker(), expected_binding=school_backup._marker_binding(_marker()))
    assert connection.rolled_back
    assert not any("information_schema" in sql for sql in connection.sql)


def test_backup_uses_fake_runtime_and_sealer_and_reports_only_safe_metadata(tmp_path, monkeypatch):
    workspace = tmp_path / "synthetic-workspace"
    workspace.mkdir()
    (workspace / "workspace.json").write_text(
        '{"database":"smhai_school_demo","port":3308,"workspace_id":"synthetic-source-1"}',
        encoding="utf-8",
    )
    sealed_key_file = MAGIC + b"synthetic-protected-bytes"
    (workspace / "database-keys.private.dpapi").write_bytes(sealed_key_file)

    captured = {}
    marker = dict(
        _marker(),
        schema_version="psynova.synthetic-workspace.v1",
        project="StudentMentalHealthAI",
        synthetic_only=True,
        host="127.0.0.1",
        state="READY_FOR_MIGRATION",
        parent_pid=123,
        executable=r"D:\synthetic\mysqld.exe",
    )
    private_settings = {
        "DB_HOST": "127.0.0.1",
        "DB_PORT": "3308",
        "DB_NAME": "smhai_school_demo",
        "DB_USER": "fake-user",
        "DB_PASSWORD": "fake-password",
    }
    monkeypatch.setattr(school_backup, "validate_marker", lambda *_: marker)
    monkeypatch.setattr(school_backup, "verify_process", lambda *_: None)
    monkeypatch.setattr(school_backup.os, "environ", dict(private_settings))

    def fake_load_runtime(_workspace, _repo, *, purpose):
        assert purpose == school_backup.RUNTIME_PURPOSE_BACKUP
        return {
            "schema_revision": snapshot_content()["revision"],
            **_marker(),
            "purpose": purpose,
            "scope": school_backup.BACKUP_NOT_APPLICATION_READY,
        }

    def fake_snapshot(_connection, _marker, *, expected_revision, expected_binding):
        content = snapshot_content()
        assert expected_revision == content["revision"]
        assert expected_binding == school_backup._marker_binding(marker)
        return content

    monkeypatch.setattr(school_backup, "load_runtime", fake_load_runtime)
    monkeypatch.setattr(school_backup, "snapshot", fake_snapshot)

    class FakeConnection:
        closed = False

        def close(self):
            self.closed = True

    connection = FakeConnection()
    monkeypatch.setitem(
        sys.modules,
        "pymysql",
        types.SimpleNamespace(connect=lambda **kwargs: connection),
    )

    def fake_read_private(path):
        if Path(path).name == "runtime.private.dpapi":
            return private_settings
        return captured["package"]

    def fake_write_private(path, package, *, exclusive=False):
        assert exclusive is True
        captured["package"] = package

    monkeypatch.setattr(school_backup, "read_private", fake_read_private)
    monkeypatch.setattr(school_backup, "write_private", fake_write_private)

    result = school_backup.backup(workspace, tmp_path / "repo")

    assert connection.closed
    assert captured["package"]["database_key_container_b64"] == school_backup.base64.b64encode(
        sealed_key_file
    ).decode("ascii")
    assert result["restore_workflow"] == "not yet verified"
    assert result["recovery_scope"] == "WINDOWS_CURRENT_USER_ONLY"
    assert result["target_policy"] == "NEW_ISOLATED_INSTANCE_ONLY"
    assert result["auth_session_policy"] == "REVOKE_ALL_AFTER_IMPORT"
    assert result["schema_revision"] == snapshot_content()["revision"]
    assert result["purpose"] == school_backup.RUNTIME_PURPOSE_BACKUP
    assert result["scope"] == school_backup.BACKUP_NOT_APPLICATION_READY
    assert set(result) == {
        "backup",
        "revision",
        "schema_revision",
        "purpose",
        "scope",
        "table_count",
        "path",
        "recovery_scope",
        "target_policy",
        "auth_session_policy",
        "restore_workflow",
    }


def test_backup_rejects_application_scope_or_inconsistent_preflight_before_reading_key(
    tmp_path, monkeypatch
):
    def fake_load_runtime(_workspace, _repo, *, purpose):
        assert purpose == school_backup.RUNTIME_PURPOSE_BACKUP
        return {
            "schema_revision": next(iter(school_backup.SUPPORTED_BACKUP_REVISIONS)),
            **_marker(),
            "purpose": purpose,
            "scope": "APPLICATION_CURRENT_REVISION",
        }

    monkeypatch.setattr(school_backup, "load_runtime", fake_load_runtime)
    with pytest.raises(ValueError, match="Verified backup preflight metadata required"):
        school_backup.backup(tmp_path, tmp_path / "repo")


def _backup_preflight(monkeypatch, marker, private=None):
    settings = private or {
        "DB_HOST": "127.0.0.1",
        "DB_PORT": "3308",
        "DB_NAME": "smhai_school_demo",
        "DB_USER": "psynova_runtime_test",
        "DB_PASSWORD": "synthetic-only",
    }
    monkeypatch.setattr(
        school_backup,
        "load_runtime",
        lambda *_args, **_kwargs: {
            "schema_revision": next(iter(school_backup.SUPPORTED_BACKUP_REVISIONS)),
            "workspace_id": marker["workspace_id"],
            "database": marker["database"],
            "port": marker["port"],
            "data_directory": marker["data_directory"],
            "purpose": school_backup.RUNTIME_PURPOSE_BACKUP,
            "scope": school_backup.BACKUP_NOT_APPLICATION_READY,
        },
    )
    monkeypatch.setattr(school_backup, "verify_process", lambda *_: None)
    monkeypatch.setattr(school_backup.os, "environ", dict(settings))
    monkeypatch.setattr(school_backup, "write_private", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(school_backup, "read_private", lambda _path: settings)
    return settings


@pytest.mark.parametrize("field", ["workspace_id", "port", "database", "data_directory"])
def test_backup_rejects_marker_change_after_preflight_before_connect(tmp_path, monkeypatch, field):
    original = dict(_marker())
    changed = dict(original)
    changed[field] = {
        "workspace_id": "other",
        "port": 3309,
        "database": "other_db",
        "data_directory": r"D:\other\data",
    }[field]
    _backup_preflight(monkeypatch, original)
    (tmp_path / "database-keys.private.dpapi").write_bytes(MAGIC + b"synthetic")
    monkeypatch.setattr(school_backup, "validate_marker", lambda *_: changed)
    monkeypatch.setitem(
        sys.modules,
        "pymysql",
        types.SimpleNamespace(connect=lambda **_kwargs: pytest.fail("target change must fail before connect")),
    )
    with pytest.raises(ValueError, match="Backup workspace identity changed"):
        school_backup.backup(tmp_path, tmp_path / "repo")


@pytest.mark.parametrize("field", ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"])
def test_backup_rejects_private_settings_change_after_preflight_before_connect(
    tmp_path, monkeypatch, field
):
    marker = dict(_marker())
    settings = {
        "DB_HOST": "127.0.0.1",
        "DB_PORT": "3308",
        "DB_NAME": "smhai_school_demo",
        "DB_USER": "psynova_runtime_test",
        "DB_PASSWORD": "synthetic-only",
    }
    _backup_preflight(monkeypatch, marker, settings)
    (tmp_path / "database-keys.private.dpapi").write_bytes(MAGIC + b"synthetic")
    monkeypatch.setattr(school_backup, "validate_marker", lambda *_: marker)
    changed = dict(settings, **{field: "changed"})
    monkeypatch.setattr(school_backup, "read_private", lambda _path: changed)
    monkeypatch.setitem(
        sys.modules,
        "pymysql",
        types.SimpleNamespace(connect=lambda **_kwargs: pytest.fail("private change must fail before connect")),
    )
    with pytest.raises(ValueError, match="Sealed runtime settings changed after preflight"):
        school_backup.backup(tmp_path, tmp_path / "repo")


@pytest.mark.parametrize("bad_role", ["ACTIVE_ROLE", None])
def test_snapshot_rejects_changed_current_role_before_table_read(bad_role):
    class BadRoleConnection(WrongTargetConnection):
        def fetchone(self):
            if self.sql[-1] == "SELECT CURRENT_ROLE()":
                return (bad_role,)
            return super().fetchone()

    connection = BadRoleConnection()
    with pytest.raises(ValueError, match="Owned runtime privileges required"):
        school_backup.snapshot(connection, _marker(), expected_binding=school_backup._marker_binding(_marker()))
    assert connection.rolled_back
    assert not any("START TRANSACTION" in sql or "information_schema" in sql for sql in connection.sql)


@pytest.mark.parametrize("bad_grants", [(), (("GRANT USAGE ON *.* TO 'runtime'",),)])
def test_snapshot_rejects_changed_grants_before_table_read(bad_grants):
    class BadGrantsConnection(WrongTargetConnection):
        def fetchall(self):
            if self.sql[-1] == "SHOW GRANTS FOR CURRENT_USER()":
                return bad_grants
            return ()

    connection = BadGrantsConnection()
    with pytest.raises(ValueError, match="Owned runtime privileges required"):
        school_backup.snapshot(connection, _marker(), expected_binding=school_backup._marker_binding(_marker()))
    assert connection.rolled_back
    assert not any("START TRANSACTION" in sql or "information_schema" in sql for sql in connection.sql)


@pytest.mark.parametrize("change", ["port", "datadir", "database", "isolation"])
def test_snapshot_rejects_second_connection_target_drift_before_table_read(change):
    class ChangedTargetConnection(WrongTargetConnection):
        def fetchone(self):
            if self.sql[-1] == "SELECT CURRENT_ROLE()":
                return ("NONE",)
            return {
                "port": ("smhai_school_demo", 3309, _marker()["data_directory"], "REPEATABLE-READ"),
                "datadir": ("smhai_school_demo", 3308, r"D:\other\data", "REPEATABLE-READ"),
                "database": ("other_db", 3308, _marker()["data_directory"], "REPEATABLE-READ"),
                "isolation": ("smhai_school_demo", 3308, _marker()["data_directory"], "READ-COMMITTED"),
            }[change]

        def fetchall(self):
            if self.sql[-1] == "SHOW GRANTS FOR CURRENT_USER()":
                return _runtime_grants()
            return ()

    connection = ChangedTargetConnection()
    with pytest.raises(ValueError, match="Owned consistent snapshot target required"):
        school_backup.snapshot(connection, _marker(), expected_binding=school_backup._marker_binding(_marker()))
    assert connection.rolled_back
    assert not any("information_schema" in sql for sql in connection.sql)


def test_package_snapshot_rejects_non_v1_or_unsealed_key_bundle():
    with pytest.raises(ValueError, match="Supported database snapshot required"):
        school_backup.package_snapshot({"schema_version": school_backup.BACKUP_V2}, MAGIC + b"x")
    with pytest.raises(ValueError, match="DPAPI key-container header required"):
        school_backup.package_snapshot(snapshot_content(), b"not-sealed")


def test_package_validator_requires_nonempty_container_after_magic_header():
    package = school_backup.package_snapshot(
        snapshot_content(), MAGIC + b"synthetic-protected-bytes"
    )
    package["database_key_container_b64"] = school_backup.base64.b64encode(MAGIC).decode(
        "ascii"
    )

    with pytest.raises(ValueError, match="DPAPI key-container header required"):
        school_backup.validate_backup_package(package)
