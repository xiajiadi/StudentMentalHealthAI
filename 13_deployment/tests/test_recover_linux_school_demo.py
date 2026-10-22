"""Offline safety tests for resumable Linux school-demo recovery."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import pathlib
import stat
import subprocess
import tarfile
from types import SimpleNamespace

import pytest
import recover_linux_school_demo as recovery


def test_release_fingerprint_matches_pinned_source_revision():
    repository_root = pathlib.Path(__file__).resolve().parents[2]
    archive_bytes = subprocess.check_output(
        ["git", "-C", str(repository_root), "archive", recovery.EXPECTED_SOURCE_REVISION]
    )
    source_files = {}
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            content = archive.extractfile(member)
            assert content is not None
            source_files[member.name] = content.read()

    selected_files = {}
    for relative in recovery._RELEASE_PATHS:
        selected_files.update(
            {
                name: content
                for name, content in source_files.items()
                if name == relative or name.startswith(relative.rstrip("/") + "/")
            }
        )
    selected_files["SOURCE_REVISION"] = (
        recovery.EXPECTED_SOURCE_REVISION + "\n"
    ).encode("ascii")

    digest = hashlib.sha256()
    for relative, content in sorted(selected_files.items()):
        digest.update(
            relative.encode("utf-8")
            + b"\0"
            + hashlib.sha256(content).digest()
            + b"\n"
        )

    assert len(selected_files) == 266
    assert digest.hexdigest() == recovery.EXPECTED_RELEASE_FINGERPRINT


def _key_payload() -> bytes:
    key = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")
    return json.dumps(
        {"active_version": "school-demo-v1", "keys": {"school-demo-v1": key}},
        separators=(",", ":"),
    ).encode("ascii")


def _seed_payload() -> bytes:
    credentials = {
        f"{school}.{role}": [
            f"SYNTHETIC_{school.upper()}_{role.upper()}_TEST",
            f"synthetic-password-{school}-{role}",
        ]
        for school in ("alpha", "beta")
        for role in ("student", "teacher", "psychological_specialist", "admin")
    }
    return json.dumps(
        {"schema": "psynova.school-seed-accounts.v1", "credentials": credentials},
        separators=(",", ":"),
    ).encode("ascii")


def test_command_does_not_inherit_or_forward_secret_environment(monkeypatch):
    captured = {}

    def fake_run(args, *, input, capture_output, timeout, check, env):
        captured.update(env)
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setenv("MYSQL_PWD", "DO_NOT_FORWARD")
    monkeypatch.setenv("LD_PRELOAD", "DO_NOT_FORWARD")
    monkeypatch.setenv("PYTHONPATH", "UNTRUSTED")
    monkeypatch.setattr(recovery.subprocess, "run", fake_run)

    recovery._command(
        ["true"],
        env={
            "MYSQL_PWD": "DO_NOT_FORWARD",
            "MYSQL_TEST_LOGIN_FILE": "/dev/null",
        },
    )

    assert "MYSQL_PWD" not in captured
    assert "LD_PRELOAD" not in captured
    assert captured["MYSQL_TEST_LOGIN_FILE"] == "/dev/null"
    assert captured["PATH"] == ("/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
    assert captured["PYTHONDONTWRITEBYTECODE"] == "1"


def test_mysql_client_suppresses_login_path_without_unsupported_option(monkeypatch):
    captured = {}

    def fake_command(args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return subprocess.CompletedProcess(args, 0, b"result\n", b"")

    monkeypatch.setattr(recovery.shutil, "which", lambda _name: "/usr/bin/mysql")
    monkeypatch.setattr(recovery, "_command", fake_command)

    assert recovery._mysql("SELECT 1") == "result"
    assert "--no-login-paths" not in captured["args"]
    assert captured["args"][1] == "--no-defaults"
    assert captured["env"] == {"MYSQL_TEST_LOGIN_FILE": "/dev/null"}


@pytest.mark.parametrize(
    ("field", "invalid_value", "error_code"),
    [
        (0, "admin@localhost", "mysql_current_user_mismatch"),
        (1, "8.4.0", "mysql_version_mismatch"),
        (2, "3307", "mysql_port_mismatch"),
        (3, "0.0.0.0", "mysql_bind_address_mismatch"),
        (4, "1", "mysql_general_log_policy_mismatch"),
        (5, "1", "mysql_log_raw_policy_mismatch"),
        (6, "UNKNOWN", "mysql_binary_log_state_invalid"),
    ],
)
def test_mysql_identity_policy_reports_each_field_separately(field, invalid_value, error_code):
    identity = ["root@localhost", "8.0.46.0", "3306", "127.0.0.1", "0", "0", "1"]
    identity[field] = invalid_value

    with pytest.raises(recovery.RecoveryError, match=error_code):
        recovery._validate_mysql_identity_policy(identity)


def test_mysql_identity_policy_accepts_secure_binary_logging():
    identity = ["root@localhost", "8.0.46.0", "3306", "127.0.0.1", "0", "0", "1"]
    assert recovery._validate_mysql_identity_policy(identity) is True
    identity[6] = "OFF"
    assert recovery._validate_mysql_identity_policy(identity) is False


def test_mysql_binary_log_is_preserved_only_with_restricted_file_access(
    monkeypatch, tmp_path
):
    log_directory = tmp_path / "mysql"
    log_directory.mkdir()
    base = log_directory / "binlog"
    index = log_directory / "binlog.index"
    (log_directory / "binlog.000001").write_bytes(b"")
    index.write_bytes(b"")

    def read_single_row(sql, *, fields):
        if "replication_connection_configuration" in sql:
            return ["0"]
        if "@@global.gtid_mode" in sql:
            return ["OFF", "2592000", "1", "1"]
        if "log_bin_basename" in sql:
            return [str(base), str(index)]
        raise AssertionError("unexpected metadata query")

    def fake_mysql(sql, *, check=True):
        assert check is True
        if sql == "SHOW REPLICAS":
            return ""
        if sql == "SHOW BINARY LOGS":
            return "binlog.000001\t180\tNo"
        raise AssertionError("unexpected MySQL statement")

    def fake_command(args, *, check=True):
        if args[1:3] == ["passwd", "mysql"]:
            output = b"mysql:x:111:117::/nonexistent:/usr/sbin/nologin\n"
        elif args[1:3] == ["group", "mysql"]:
            output = b"mysql:x:117:\n"
        else:
            raise AssertionError("unexpected system command")
        return subprocess.CompletedProcess(args, 0, output, b"")

    metadata = {
        log_directory: SimpleNamespace(
            st_uid=111, st_gid=117, st_mode=stat.S_IFDIR | 0o700, st_nlink=1
        ),
        index: SimpleNamespace(
            st_uid=111, st_gid=117, st_mode=stat.S_IFREG | 0o640, st_nlink=1
        ),
        log_directory / "binlog.000001": SimpleNamespace(
            st_uid=111, st_gid=117, st_mode=stat.S_IFREG | 0o640, st_nlink=1
        ),
    }
    monkeypatch.setattr(recovery, "_read_single_row", read_single_row)
    monkeypatch.setattr(recovery, "_mysql", fake_mysql)
    monkeypatch.setattr(recovery, "_command", fake_command)
    monkeypatch.setattr(recovery, "_path_stat", lambda path: metadata[path])
    monkeypatch.setattr(recovery, "_require_no_extended_acl", lambda _path: None)

    result = recovery._validate_mysql_binary_log_policy(True)

    assert result == {
        "enabled": True,
        "protected_files": 2,
        "replication_channels": 0,
        "registered_replicas": 0,
        "gtid_mode": "OFF",
        "expiration_seconds": 2592000,
        "server_id": 1,
        "replica_updates": True,
    }
    metadata[log_directory].st_mode = stat.S_IFDIR | 0o750
    with pytest.raises(
        recovery.RecoveryError,
        match="mysql_binary_log_directory_permissions_mismatch",
    ):
        recovery._validate_mysql_binary_log_policy(True)


def test_recovery_main_acquires_single_instance_lock_before_inspection(monkeypatch, capsys):
    events = []
    monkeypatch.setattr(recovery, "_verify_executable_snapshot", lambda _sha: events.append("sha"))
    monkeypatch.setattr(recovery, "_acquire_recovery_lock", lambda: events.append("lock"))
    monkeypatch.setattr(
        recovery,
        "_make_plan",
        lambda *_args, **_kwargs: events.append("inspect") or {"status": "READY"},
    )
    monkeypatch.setattr(
        recovery.sys,
        "argv",
        ["recover_linux_school_demo.py", "--inspect", "--expected-sha256", "a" * 64],
    )

    assert recovery.main() == 0
    assert events == ["sha", "lock", "inspect"]
    assert '"inspect":"PASS"' in capsys.readouterr().out


def test_runtime_password_rotation_uses_account_ddl(monkeypatch):
    statements = []
    monkeypatch.setattr(recovery, "_mysql", lambda sql: statements.append(sql))

    recovery._rotate_runtime_password("synthetic-runtime-password-1234567890")

    assert len(statements) == 1
    assert statements[0].startswith("ALTER USER ")
    assert "UPDATE mysql.user" not in statements[0]


def test_staging_after_migrator_lock_never_recreates_migration_credential(monkeypatch):
    values = {
        recovery.RUNTIME_CREDENTIAL_NAME: recovery._new_database_credential(
            recovery.RUNTIME_USER, "runtime-password-" + "A" * 32, csrf="a" * 64
        ),
        recovery.KEY_CREDENTIAL_NAME: _key_payload(),
        recovery.SEED_CREDENTIAL_NAME: _seed_payload(),
        recovery.MIGRATION_CREDENTIAL_NAME: None,
    }
    calls = []

    def read_existing(name):
        calls.append(name)
        return values[name]

    def unexpected_store(*_args):
        raise AssertionError("completed migration credentials must not be recreated")

    monkeypatch.setattr(recovery, "_read_credential_candidates", read_existing)
    monkeypatch.setattr(recovery, "_store_credential", unexpected_store)

    result = recovery._ensure_staged_credentials(
        {
            "phase": "MIGRATOR_LOCKED",
            "migrator_user": "psynova_migrator_0123456789abcdef",
        }
    )

    assert recovery.MIGRATION_CREDENTIAL_NAME not in calls
    assert result["migrator_password"] == ""
    assert result["runtime_user"] == recovery.RUNTIME_USER


def test_migrator_prepared_resume_finishes_usage_only_grant(monkeypatch):
    username = "psynova_migrator_0123456789abcdef"
    password = "migration-password-" + "A" * 32
    usage = [f"GRANT USAGE ON *.* TO '{username}'@'127.0.0.1'"]
    full = [
        usage[0],
        (
            "GRANT CREATE, ALTER, INDEX, REFERENCES, SELECT, INSERT, UPDATE, DELETE "
            "ON smhai_school_demo.* TO '{username}'@'127.0.0.1'"
        ),
    ]
    auth_results = iter([(True, usage), (True, full)])
    sql_calls = []
    state_calls = []
    monkeypatch.setattr(recovery, "_ensure_mysql_auth", lambda _user, _password: next(auth_results))
    monkeypatch.setattr(recovery, "_mysql", lambda sql: sql_calls.append(sql) or "")

    def set_phase(state, phase):
        state_calls.append(phase)
        return {**state, "phase": phase}

    monkeypatch.setattr(recovery, "_set_state_phase", set_phase)
    state: dict[str, object] = {
        "phase": "MIGRATOR_PREPARED",
        "migrator_user": username,
    }

    result = recovery._ensure_migrator_account(
        state,
        {"migrator_user": username, "migrator_password": password},
    )

    assert len(sql_calls) == 1
    assert "GRANT CREATE, ALTER, INDEX, REFERENCES" in sql_calls[0]
    assert password not in sql_calls[0]
    assert state_calls == ["MIGRATOR_AUTH_VERIFIED"]
    assert result["phase"] == "MIGRATOR_AUTH_VERIFIED"


def test_credential_candidate_reader_rejects_unlinked_conflicting_sidecar(monkeypatch, tmp_path):
    target = tmp_path / "runtime.cred"
    staging = tmp_path / ".runtime.cred.recovery-next"
    target.write_bytes(b"encrypted-a")
    staging.write_bytes(b"encrypted-a")
    monkeypatch.setattr(recovery, "_credential_path", lambda _name: target)
    monkeypatch.setattr(recovery, "_credential_staging_path", lambda _name: staging)
    monkeypatch.setattr(recovery, "_require_root_owned", lambda *_a, **_k: None)
    monkeypatch.setattr(recovery, "_read_credential", lambda _name, path: b"same-plaintext")

    with pytest.raises(recovery.RecoveryError, match="credential_staging_link_mismatch"):
        recovery._read_credential_candidates(recovery.RUNTIME_CREDENTIAL_NAME)


def test_schema_state_distinguishes_empty_target_and_unrecognized_revision():
    assert recovery._schema_state({"tables": [], "revision": None}) == "EMPTY"
    assert (
        recovery._schema_state(
            {"tables": ["database_alembic_version"], "revision": "20261016_0024"}
        )
        == "TARGET_REVISION"
    )
    assert (
        recovery._schema_state({"tables": ["some_table"], "revision": "unrecognized"})
        == "INCONSISTENT"
    )


def test_seed_account_payload_is_synthetic_and_has_exact_eight_slots():
    accounts = recovery._validate_seed_payload(_seed_payload())
    assert set(accounts) == set(recovery._SEED_SLOTS)
    assert len(accounts) == 8
    assert all(login.startswith("SYNTHETIC_") for login, _ in accounts.values())
