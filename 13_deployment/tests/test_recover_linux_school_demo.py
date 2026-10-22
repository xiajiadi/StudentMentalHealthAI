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
    for relative, patch_revision in recovery.EXPECTED_RELEASE_PATCHES:
        patch_archive = subprocess.check_output(
            ["git", "-C", str(repository_root), "archive", patch_revision, relative]
        )
        with tarfile.open(fileobj=io.BytesIO(patch_archive), mode="r:") as archive:
            patch_file = next(
                member for member in archive.getmembers() if member.isfile()
            )
            content = archive.extractfile(patch_file)
            assert content is not None
            selected_files[relative] = content.read()
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


def _checkpoint(*, phase="MIGRATOR_PREPARED", migrator_user="psynova_migrator_0123456789abcdef"):
    return {
        "schema": recovery.STATE_SCHEMA,
        "operation_id": "a" * 32,
        "source_revision": recovery.EXPECTED_SOURCE_REVISION,
        "hostname": recovery.EXPECTED_HOSTNAME,
        "runtime_user": recovery.RUNTIME_USER,
        "migrator_user": migrator_user,
        "phase": phase,
        "sequence": 6,
        "created_at": "2026-10-22T00:00:00+00:00",
        "updated_at": "2026-10-22T00:00:00+00:00",
    }


def _repair_crypto_mocks(monkeypatch, tmp_path):
    credstore = tmp_path / "credstore"
    credstore.mkdir()
    monkeypatch.setattr(recovery, "CREDSTORE", credstore)
    monkeypatch.setattr(
        recovery,
        "_encrypt_credential",
        lambda _name, payload: b"encrypted:" + base64.b64encode(payload),
    )
    monkeypatch.setattr(
        recovery,
        "_read_credential",
        lambda _name, path: base64.b64decode(path.read_bytes().removeprefix(b"encrypted:")),
    )
    monkeypatch.setattr(recovery, "_require_root_owned", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(recovery, "_require_no_extended_acl", lambda _path: None)
    monkeypatch.setattr(recovery, "_sync_directory", lambda _path: None)
    monkeypatch.setattr(recovery._LINUX_OS, "chown", lambda *_args: None, raising=False)


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


def test_mysql_command_failure_exposes_only_the_server_error_number(monkeypatch):
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args,
            1,
            b"",
            b"ERROR 1819 (HY000): rejected SYNTHETIC_DO_NOT_EXPOSE\n",
        )

    monkeypatch.setattr(recovery.subprocess, "run", fake_run)

    with pytest.raises(recovery.RecoveryError) as error:
        recovery._command(["/usr/bin/mysql", "--batch"], check=True)

    assert str(error.value) == "mysql_statement_error_1819"
    assert "SYNTHETIC_DO_NOT_EXPOSE" not in str(error.value)


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


def test_start_oneshot_restarts_a_remained_completed_unit(monkeypatch):
    unit_name = "psynova-school-seed.service"
    calls = []
    monkeypatch.setattr(
        recovery,
        "_unit_show",
        lambda _unit: {
            "LoadState": "loaded",
            "ActiveState": "active",
            "SubState": "exited",
        },
    )
    monkeypatch.setattr(
        recovery, "_command", lambda command, **_kwargs: calls.append(command)
    )
    monkeypatch.setattr(
        recovery,
        "_unit_invocation_json",
        lambda _unit, *, expected_key: {expected_key: "VERIFIED"},
    )

    result = recovery._start_oneshot(
        unit_name, expected_key="seed", timeout=300
    )

    assert result == {"seed": "VERIFIED"}
    assert calls == [
        ["systemctl", "stop", unit_name],
        ["systemctl", "start", unit_name],
    ]


def test_start_oneshot_refuses_a_running_unit(monkeypatch):
    monkeypatch.setattr(
        recovery,
        "_unit_show",
        lambda _unit: {
            "LoadState": "loaded",
            "ActiveState": "active",
            "SubState": "running",
        },
    )
    monkeypatch.setattr(
        recovery, "_command", lambda *_args, **_kwargs: pytest.fail("unexpected command")
    )

    with pytest.raises(
        recovery.RecoveryError, match="systemd_oneshot_unit_already_running"
    ):
        recovery._start_oneshot("psynova-school-seed.service", expected_key="seed")


@pytest.mark.parametrize(
    "unit_name",
    [
        "psynova-school-credential-probe.service",
        "psynova-school-migrate.service",
        "psynova-school-seed.service",
    ],
)
def test_recovery_oneshot_units_retain_invocation_metadata(unit_name):
    unit_path = pathlib.Path(__file__).resolve().parents[1] / "systemd" / unit_name
    assert "Type=oneshot\nRemainAfterExit=yes\n" in unit_path.read_text()


def test_mysql_show_grants_privilege_order_is_canonicalized():
    username = "psynova_migrator_0123456789abcde"
    mysql_canonical_order = [
        "GRANT USAGE ON *.* TO " + f"'{username}'@'127.0.0.1'",
        (
            "GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, REFERENCES, INDEX, ALTER "
            "ON `smhai_school_demo`.* TO " + f"'{username}'@'127.0.0.1'"
        ),
    ]

    recovery._verify_migration_grants(mysql_canonical_order)
    assert (
        recovery._normalize_grant(mysql_canonical_order[1])
        == recovery._MIGRATOR_SCHEMA_GRANT
    )


def test_runtime_show_grants_privilege_order_is_canonicalized():
    recovery._verify_runtime_grants(
        [
            "GRANT USAGE ON *.* TO runtime",
            "GRANT SELECT, INSERT, UPDATE, DELETE ON `smhai_school_demo`.* TO runtime",
        ]
    )


def test_mysql_show_grants_privilege_order_keeps_expansion_rejected():
    grants = [
        "GRANT USAGE ON *.* TO migrator",
        (
            "GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, REFERENCES, INDEX, ALTER, "
            "DROP ON smhai_school_demo.* TO migrator"
        ),
    ]

    with pytest.raises(recovery.RecoveryError, match="migration_grants_not_minimal"):
        recovery._verify_migration_grants(grants)


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


def test_mysql_account_regex_keeps_new_migrator_names_within_limit():
    assert recovery._ACCOUNT_RE.fullmatch("psynova_runtime_" + "a" * 16)
    assert recovery._ACCOUNT_RE.fullmatch("psynova_migrator_" + "b" * 15)
    assert recovery._ACCOUNT_RE.fullmatch("psynova_migrator_" + "c" * 16)
    assert not recovery._ACCOUNT_RE.fullmatch("psynova_migrator_" + "d" * 17)
    assert len("psynova_migrator_" + "b" * 15) == 32


def test_new_recovery_state_generates_mysql_compatible_migrator_name(monkeypatch):
    monkeypatch.setattr(recovery.secrets, "token_hex", lambda _n: "e" * 32)
    monkeypatch.setattr(recovery, "_mysql", lambda _sql: "")

    state = recovery._new_state({"hostname": recovery.EXPECTED_HOSTNAME})

    assert state["migrator_user"] == "psynova_migrator_" + "e" * 15
    assert len(str(state["migrator_user"])) == 32


def test_checkpoint_validates_only_the_authenticated_legacy_username_repair():
    old_user = "psynova_migrator_" + "a" * 16
    state = _checkpoint(migrator_user=old_user)
    assert recovery._validate_state(state) == state

    repaired = _checkpoint(migrator_user="psynova_migrator_" + "b" * 15)
    repaired["migrator_repaired_from"] = old_user
    assert recovery._validate_state(repaired) == repaired

    repaired["phase"] = "MIGRATION_STARTED"
    with pytest.raises(recovery.RecoveryError, match="checkpoint_format_invalid"):
        recovery._validate_state(repaired)


def test_begin_migrator_repair_checkpoints_new_identity_without_database_mutation(
    monkeypatch,
):
    old_user = "psynova_migrator_" + "a" * 16
    state = _checkpoint(migrator_user=old_user)
    old_payload = recovery._new_database_credential(
        old_user, "legacy-migration-password-012345", csrf=None
    )
    saved = []
    sql_calls = []
    monkeypatch.setattr(recovery, "_schema_state", lambda _database: "EMPTY")
    monkeypatch.setattr(
        recovery,
        "_database_accounts",
        lambda _database: [{"user": recovery.RUNTIME_USER}],
    )
    monkeypatch.setattr(recovery, "_read_credential_candidates", lambda _name: old_payload)
    monkeypatch.setattr(recovery.secrets, "token_hex", lambda _n: "b" * 32)
    monkeypatch.setattr(
        recovery, "_mysql", lambda sql: sql_calls.append(sql) or ""
    )
    monkeypatch.setattr(
        recovery, "_save_state", lambda value: saved.append(dict(value)) or value
    )
    monkeypatch.setattr(recovery, "_emit", lambda *_args, **_kwargs: None)

    result = recovery._begin_migrator_identity_repair(state, {})

    assert result["migrator_user"] == "psynova_migrator_" + "b" * 15
    assert result["migrator_repaired_from"] == old_user
    assert len(str(result["migrator_user"])) == 32
    assert saved == [result]
    assert len(sql_calls) == 1 and sql_calls[0].startswith("SELECT User FROM mysql.user")


@pytest.mark.parametrize("fail_on_replace", [1, 2, 3])
def test_migrator_credential_handoff_resumes_after_each_atomic_rename(
    monkeypatch, tmp_path, fail_on_replace
):
    _repair_crypto_mocks(monkeypatch, tmp_path)
    old_user = "psynova_migrator_" + "a" * 16
    new_user = "psynova_migrator_" + "b" * 15
    state = _checkpoint(migrator_user=new_user)
    state["migrator_repaired_from"] = old_user
    target = recovery._credential_path(recovery.MIGRATION_CREDENTIAL_NAME)
    old_payload = recovery._new_database_credential(
        old_user, "legacy-migration-password-012345", csrf=None
    )
    target.write_bytes(recovery._encrypt_credential(recovery.MIGRATION_CREDENTIAL_NAME, old_payload))

    real_replace = recovery.os.replace
    replace_count = 0

    def interrupted_replace(source, destination):
        nonlocal replace_count
        replace_count += 1
        if replace_count == fail_on_replace:
            raise OSError("simulated interruption")
        return real_replace(source, destination)

    monkeypatch.setattr(recovery.os, "replace", interrupted_replace)
    with pytest.raises(
        recovery.RecoveryError, match="migrator_repair_credential_handoff_failed"
    ):
        recovery._resume_migrator_credential_repair(state)

    recovery._validate_migrator_repair_objects(state)
    monkeypatch.setattr(recovery.os, "replace", real_replace)
    recovery._resume_migrator_credential_repair(state)
    recovery._validate_migrator_repair_objects(state)

    current = recovery._read_optional_migrator_repair_credential(target)
    original = recovery._read_optional_migrator_repair_credential(
        recovery._migrator_repair_backup_path()
    )
    assert current is not None and current["user"] == new_user
    assert original is not None and original["user"] == old_user


def test_migrator_repair_cleanup_waits_for_authenticated_checkpoint(monkeypatch, tmp_path):
    _repair_crypto_mocks(monkeypatch, tmp_path)
    old_user = "psynova_migrator_" + "a" * 16
    new_user = "psynova_migrator_" + "b" * 15
    state = _checkpoint(migrator_user=new_user)
    state["migrator_repaired_from"] = old_user
    target = recovery._credential_path(recovery.MIGRATION_CREDENTIAL_NAME)
    backup = recovery._migrator_repair_backup_path()
    target.write_bytes(
        recovery._encrypt_credential(
            recovery.MIGRATION_CREDENTIAL_NAME,
            recovery._new_database_credential(
                new_user, "new-migration-password-012345", csrf=None
            ),
        )
    )
    backup.write_bytes(
        recovery._encrypt_credential(
            recovery.MIGRATION_CREDENTIAL_NAME,
            recovery._new_database_credential(
                old_user, "legacy-migration-password-012345", csrf=None
            ),
        )
    )
    saved = []
    monkeypatch.setattr(
        recovery,
        "_set_state_phase",
        lambda value, phase: dict(value, phase=phase),
    )
    monkeypatch.setattr(
        recovery, "_save_state", lambda value: saved.append(dict(value)) or value
    )
    monkeypatch.setattr(recovery, "_emit", lambda *_args, **_kwargs: None)

    result = recovery._finish_migrator_identity_repair(state)

    assert result["phase"] == "MIGRATOR_AUTH_VERIFIED"
    assert "migrator_repaired_from" not in result
    assert not backup.exists()
    assert len(saved) == 1 and "migrator_repaired_from" not in saved[0]
