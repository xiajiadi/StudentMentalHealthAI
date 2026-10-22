"""Resume the reviewed Linux synthetic school-demo install from its exact partial state.

All modes require a root-owned, SHA-256-pinned snapshot under APP_ROOT. The script
never drops or recreates the target schema and only accepts the original partial
install or its own systemd-encrypted, authenticated recovery checkpoint.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import errno
import hashlib
import importlib
import json
import os
import platform
import re
import secrets
import shutil
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

_LINUX_OS = cast(Any, os)

SOURCE_STAGE = Path("/home/psynova/apps/psynova/staging/linux-school-demo")
APP_ROOT = Path("/opt/psynova-school-demo")
RELEASE_ROOT = APP_ROOT / "release"
VENV_ROOT = APP_ROOT / "venv"
SERVICE_USER = "psynova-school-demo"
SERVICE_GROUP = "psynova-school-demo"
SERVICE_UID = 999
SERVICE_GID = 988
EXPECTED_HOSTNAME = "iZ0xic24d9gxb9udjbfo0kZ"
EXPECTED_SOURCE_REVISION = "f3047642aa3466f9b4f210f4f704d57fd2cdf3cc"
EXPECTED_RELEASE_FINGERPRINT = "7a5b70ef9a8ac7cf732823786d8a2d52cae7f6a89ae40ef08ecd4d85baebb8c2"
DATABASE_NAME = "smhai_school_demo"
DATABASE_COLLATION = "utf8mb4_0900_ai_ci"
EXPECTED_REVISION = "20261016_0024"
MYSQL_PORT = 3306
BACKEND_PORT = 8088
CREDSTORE = Path("/etc/credstore.encrypted")
HOST_CREDENTIAL_KEY = Path("/var/lib/systemd/credential.secret")
SYSTEMD_UNITS = Path("/etc/systemd/system")
RUN_UNITS = Path("/run/systemd/system")
RECOVERY_LOCK_PATH = Path("/run/psynova-school-demo-recovery.lock")
STATE_ROOT = Path("/var/lib/psynova-school-demo")
STATE_FILE = STATE_ROOT / "recovery-state.cred"
STATE_NEXT_FILE = STATE_ROOT / "recovery-state.next.cred"
STATE_CREDENTIAL_NAME = "psynova-school-recovery-state.json"
STATE_SCHEMA = "psynova.school-linux-recovery.v1"
RUNTIME_USER = "psynova_runtime_44afa2019427e4b0"
RUNTIME_CREDENTIAL_NAME = "school-runtime.json"
MIGRATION_CREDENTIAL_NAME = "school-migration.json"
KEY_CREDENTIAL_NAME = "database-keys.json"
SEED_CREDENTIAL_NAME = "school-seed-accounts.json"
_ACCOUNT_RE = re.compile(
    r"(?:psynova_runtime_[a-f0-9]{16}|psynova_migrator_[a-f0-9]{15,16})\Z"
)
_LEGACY_OVERSIZED_MIGRATOR_RE = re.compile(r"psynova_migrator_[a-f0-9]{16}\Z")
_PASSWORD_RE = re.compile(r"[!-~]{20,128}\Z")
_CSRF_RE = re.compile(r"[a-f0-9]{64}\Z")
_CREDENTIALS = {
    KEY_CREDENTIAL_NAME: "psynova-school-database-keys.cred",
    RUNTIME_CREDENTIAL_NAME: "psynova-school-runtime.cred",
    MIGRATION_CREDENTIAL_NAME: "psynova-school-migration.cred",
    SEED_CREDENTIAL_NAME: "psynova-school-seed-accounts.cred",
}
_PERMANENT_UNITS = (
    "psynova-school-credential-probe.service",
    "psynova-school-seed.service",
    "psynova-school-demo.service",
)
_MIGRATION_UNIT = "psynova-school-migrate.service"
_SEED_SLOTS = tuple(
    f"{school}.{role}"
    for school in ("alpha", "beta")
    for role in ("student", "teacher", "psychological_specialist", "admin")
)
_SEED_TABLES = (
    "schools",
    "subjects",
    "accounts",
    "account_school_memberships",
    "membership_roles",
    "subject_access_grants",
)
_SEED_COUNTS = {
    "schools": 2,
    "subjects": 2,
    "accounts": 8,
    "account_school_memberships": 8,
    "membership_roles": 8,
    "subject_access_grants": 4,
}
_RELEASE_PATHS = (
    "09_backend/README.md",
    "09_backend/pyproject.toml",
    "09_backend/uv.lock",
    "09_backend/src",
    "11_database/alembic.ini",
    "11_database/pyproject.toml",
    "11_database/uv.lock",
    "11_database/database_layer",
    "11_database/migrations",
    "13_deployment/linux_school_runtime.py",
    "13_deployment/school_backend_linux.py",
    "13_deployment/migrate_school_linux.py",
    "13_deployment/seed_school_linux.py",
    "13_deployment/probe_systemd_credentials.py",
    "13_deployment/verify_school_http_linux.py",
    "13_deployment/systemd/psynova-school-demo.service",
    "13_deployment/systemd/psynova-school-credential-probe.service",
    "13_deployment/systemd/psynova-school-migrate.service",
    "13_deployment/systemd/psynova-school-seed.service",
)
_PHASES = (
    "INITIALIZED",
    "CREDENTIALS_STAGING",
    "CREDENTIALS_STAGED",
    "RUNTIME_ROTATION_PREPARED",
    "RUNTIME_AUTH_VERIFIED",
    "MIGRATOR_PREPARED",
    "MIGRATOR_AUTH_VERIFIED",
    "SYSTEMD_UNITS_INSTALLING",
    "SYSTEMD_UNITS_INSTALLED",
    "CREDENTIAL_PROBE_VERIFIED",
    "MIGRATION_STARTED",
    "SCHEMA_MIGRATED",
    "MIGRATOR_LOCKED",
    "MIGRATION_CREDENTIAL_REMOVED",
    "SEED_PASS_1_STARTED",
    "SEED_PASS_1_VERIFIED",
    "SEED_PASS_2_STARTED",
    "SEED_PASS_2_VERIFIED",
    "NEGATIVE_PREFLIGHTS_VERIFIED",
    "BACKEND_STARTING",
    "BACKEND_STARTED",
    "HTTP_STARTED",
    "HTTP_VERIFIED",
)
MIGRATOR_REPAIR_NEXT = ".psynova-school-migration.cred.repair-next"
MIGRATOR_REPAIR_BACKUP = ".psynova-school-migration.cred.repair-original"
MIGRATOR_REPAIR_TEMP = ".psynova-school-migration.cred.repair-writing"
_DECISION_REQUIRED_CODES = {
    "target_schema_missing_or_incompatible",
    "unexpected_database_object_type",
    "unexpected_database_auxiliary_objects",
    "unexpected_database_account_shape",
    "untracked_schema_privilege_account",
    "mysql_schema_privilege_shape_invalid",
    "mysql_schema_privilege_inventory_invalid",
    "mysql_replication_topology_requires_review",
    "database_account_identity_mismatch",
    "runtime_grants_not_minimal",
    "migration_grants_not_minimal",
    "migrator_existing_account_authentication_failed",
    "migrator_lock_state_mismatch",
    "migrator_repair_schema_not_empty",
    "migrator_repair_requires_absent_account",
    "migrator_repair_original_credential_missing",
    "untracked_migrator_repair_object",
    "migrator_repair_credential_identity_mismatch",
    "migrator_repair_credential_invalid",
    "migrator_repair_credential_layout_invalid",
    "migrator_repair_checkpoint_phase_invalid",
    "duplicate_database_account",
    "initial_partial_install_state_mismatch",
    "untracked_migrator_account_found",
    "multiple_migrator_accounts_found",
    "schema_changed_before_checkpoint",
    "partial_or_unrecognized_migration_state",
    "schema_checkpoint_mismatch",
    "untracked_seed_data_found",
    "untracked_credential_or_unit_found",
    "existing_credential_conflicts_with_checkpoint",
    "staged_credential_conflicts_with_checkpoint",
    "credential_staging_conflicts_with_target",
    "credential_staging_link_mismatch",
    "untracked_credential_staging_object",
    "permanent_unit_differs_from_reviewed_source",
    "migration_unit_differs_from_reviewed_source",
    "existing_systemd_unit_conflicts_with_release",
    "staged_systemd_unit_conflicts_with_release",
    "untracked_systemd_unit_staging_object",
    "checkpoint_directory_has_unknown_objects",
    "checkpoint_format_invalid",
    "checkpoint_pending_state_inconsistent",
}


class RecoveryError(RuntimeError):
    """Safe failure containing no command output, credentials, or SQL text."""


_CURRENT_PHASE = "startup"
_RECOVERY_LOCK_FD: int | None = None


def _emit(event: str, **fields: object) -> None:
    payload: dict[str, object] = {
        "recovery": "IN_PROGRESS",
        "phase": _CURRENT_PHASE,
        "event": event,
    }
    payload.update(fields)
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")), flush=True)


def _set_phase(phase: str) -> None:
    global _CURRENT_PHASE
    if phase not in _PHASES:
        raise RecoveryError("checkpoint_phase_invalid")
    _CURRENT_PHASE = phase


def _acquire_recovery_lock() -> None:
    """Hold a root-owned, nonblocking process lock for the lifetime of this invocation."""
    global _RECOVERY_LOCK_FD
    if _RECOVERY_LOCK_FD is not None:
        return
    lock_directory = RECOVERY_LOCK_PATH.parent
    try:
        directory_metadata = lock_directory.stat(follow_symlinks=False)
    except OSError:
        raise RecoveryError("recovery_lock_directory_unavailable") from None
    if (
        lock_directory.is_symlink()
        or not stat.S_ISDIR(directory_metadata.st_mode)
        or directory_metadata.st_uid != 0
        or directory_metadata.st_mode & 0o022
    ):
        raise RecoveryError("recovery_lock_directory_unsafe")

    descriptor: int | None = None
    try:
        descriptor = os.open(
            RECOVERY_LOCK_PATH,
            os.O_RDWR | os.O_CREAT | _LINUX_OS.O_CLOEXEC | _LINUX_OS.O_NOFOLLOW,
            0o600,
        )
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
            or metadata.st_size != 0
        ):
            raise RecoveryError("recovery_lock_file_unsafe")
        fcntl = cast(Any, importlib.import_module("fcntl"))
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        if descriptor is not None:
            os.close(descriptor)
        raise RecoveryError("another_recovery_instance_active") from None
    except RecoveryError:
        if descriptor is not None:
            os.close(descriptor)
        raise
    except Exception:  # noqa: BLE001 - convert OS lock failures to a sanitized status.
        if descriptor is not None:
            os.close(descriptor)
        raise RecoveryError("recovery_lock_unavailable") from None
    _RECOVERY_LOCK_FD = descriptor


def _command(
    args: Sequence[str],
    *,
    input_bytes: bytes | None = None,
    timeout: int = 60,
    check: bool = True,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    process_env = {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": "/root",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    allowed_extra = {
        "PYTHONPATH",
        "DATABASE_AUTH_CREDENTIAL",
        "DATABASE_KEY_FILE",
        "MYSQL_TEST_LOGIN_FILE",
        "SYSTEMD_PAGER",
        "SYSTEMD_COLORS",
    }
    if env is not None:
        process_env.update({name: value for name, value in env.items() if name in allowed_extra})
    try:
        result = subprocess.run(
            list(args),
            input=input_bytes,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=process_env,
        )
    except (OSError, subprocess.SubprocessError):
        raise RecoveryError("required_command_unavailable") from None
    if check and result.returncode != 0:
        if args and Path(args[0]).name == "mysql":
            mysql_output = (result.stderr or b"") + b"\n" + (result.stdout or b"")
            match = re.search(rb"\bERROR\s+(\d{3,5})\s+\([A-Z0-9]+\)", mysql_output)
            if match is not None:
                raise RecoveryError(f"mysql_statement_error_{match.group(1).decode('ascii')}")
            raise RecoveryError("mysql_command_failed")
        raise RecoveryError("required_command_failed")
    return result


def _text(result: subprocess.CompletedProcess[bytes]) -> str:
    try:
        return result.stdout.decode("utf-8").strip()
    except UnicodeError:
        raise RecoveryError("command_output_invalid") from None


def _mysql(sql: str, *, check: bool = True) -> str:
    client = shutil.which("mysql")
    if not client:
        raise RecoveryError("mysql_client_unavailable")
    result = _command(
        [
            client,
            "--no-defaults",
            "--protocol=socket",
            "--user=root",
            "--batch",
            "--skip-column-names",
            "--raw",
        ],
        input_bytes=sql.encode("utf-8"),
        timeout=60,
        check=check,
        env={"MYSQL_TEST_LOGIN_FILE": "/dev/null"},
    )
    return _text(result)


def _read_single_row(sql: str, *, fields: int) -> list[str]:
    output = _mysql(sql)
    rows = [line.split("\t") for line in output.splitlines() if line]
    if len(rows) != 1 or len(rows[0]) != fields:
        raise RecoveryError("mysql_metadata_shape_invalid")
    return rows[0]


def _validate_mysql_identity_policy(identity: Sequence[str]) -> bool:
    if len(identity) != 7:
        raise RecoveryError("mysql_identity_metadata_shape_invalid")
    user, mysql_version, port, bind_address, general_log, log_raw, log_bin = identity
    if user != "root@localhost":
        raise RecoveryError("mysql_current_user_mismatch")
    if not mysql_version.startswith("8.0.46"):
        raise RecoveryError("mysql_version_mismatch")
    if port != str(MYSQL_PORT):
        raise RecoveryError("mysql_port_mismatch")
    if bind_address != "127.0.0.1":
        raise RecoveryError("mysql_bind_address_mismatch")
    if general_log not in {"0", "OFF"}:
        raise RecoveryError("mysql_general_log_policy_mismatch")
    if log_raw not in {"0", "OFF"}:
        raise RecoveryError("mysql_log_raw_policy_mismatch")
    if log_bin not in {"0", "OFF", "1", "ON"}:
        raise RecoveryError("mysql_binary_log_state_invalid")
    return log_bin in {"1", "ON"}


def _validate_mysql_binary_log_directory(path: Path, uid: int, gid: int) -> None:
    try:
        resolved_path = path.resolve(strict=False)
    except OSError:
        raise RecoveryError("mysql_binary_log_path_invalid") from None
    if path.is_symlink() or not path.is_absolute() or resolved_path != path:
        raise RecoveryError("mysql_binary_log_path_invalid")
    metadata = _path_stat(path)
    if metadata is None or not stat.S_ISDIR(metadata.st_mode):
        raise RecoveryError("mysql_binary_log_directory_invalid")
    mode = stat.S_IMODE(metadata.st_mode)
    if (
        metadata.st_uid != uid
        or metadata.st_gid != gid
        or mode & 0o077
        or mode & 0o700 != 0o700
    ):
        raise RecoveryError("mysql_binary_log_directory_permissions_mismatch")
    _require_no_extended_acl(path)


def _validate_mysql_binary_log_file(path: Path, uid: int, gid: int) -> None:
    try:
        resolved_path = path.resolve(strict=False)
    except OSError:
        raise RecoveryError("mysql_binary_log_path_invalid") from None
    if path.is_symlink() or not path.is_absolute() or resolved_path != path:
        raise RecoveryError("mysql_binary_log_path_invalid")
    metadata = _path_stat(path)
    if (
        metadata is None
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
    ):
        raise RecoveryError("mysql_binary_log_file_invalid")
    mode = stat.S_IMODE(metadata.st_mode)
    if (
        metadata.st_uid != uid
        or metadata.st_gid != gid
        or mode & 0o600 != 0o600
        or mode & 0o037
    ):
        raise RecoveryError("mysql_binary_log_file_permissions_mismatch")
    _require_no_extended_acl(path)


def _validate_mysql_binary_log_policy(enabled: bool) -> dict[str, object]:
    replication_channels = _read_single_row(
        "SELECT COUNT(*) FROM performance_schema.replication_connection_configuration",
        fields=1,
    )[0]
    registered_replicas = len(_mysql("SHOW REPLICAS").splitlines())
    gtid_mode, expiration, server_id, replica_updates = _read_single_row(
        "SELECT @@global.gtid_mode, @@global.binlog_expire_logs_seconds, "
        "@@global.server_id, @@global.log_replica_updates",
        fields=4,
    )
    if replication_channels != "0" or registered_replicas != 0:
        raise RecoveryError("mysql_replication_topology_requires_review")

    protected_files = 0
    if enabled:
        mysql_user = _command(["getent", "passwd", "mysql"], check=False)
        mysql_group = _command(["getent", "group", "mysql"], check=False)
        if mysql_user.returncode != 0 or mysql_group.returncode != 0:
            raise RecoveryError("mysql_binary_log_service_identity_unavailable")
        user_fields = _text(mysql_user).split(":")
        group_fields = _text(mysql_group).split(":")
        if (
            len(user_fields) != 7
            or user_fields[0] != "mysql"
            or len(group_fields) != 4
            or group_fields[0] != "mysql"
            or not user_fields[2].isdigit()
            or not group_fields[2].isdigit()
        ):
            raise RecoveryError("mysql_binary_log_service_identity_invalid")
        mysql_uid = int(user_fields[2])
        mysql_gid = int(group_fields[2])
        base_name, index_name = _read_single_row(
            "SELECT @@global.log_bin_basename, @@global.log_bin_index", fields=2
        )
        base_path = Path(base_name)
        index_path = Path(index_name)
        if (
            not base_path.is_absolute()
            or not index_path.is_absolute()
            or not base_path.name
            or not index_path.name
        ):
            raise RecoveryError("mysql_binary_log_path_invalid")
        log_directory = base_path.parent
        _validate_mysql_binary_log_directory(log_directory, mysql_uid, mysql_gid)
        _validate_mysql_binary_log_directory(index_path.parent, mysql_uid, mysql_gid)
        _validate_mysql_binary_log_file(index_path, mysql_uid, mysql_gid)

        binary_logs = _mysql("SHOW BINARY LOGS")
        rows = [line.split("\t") for line in binary_logs.splitlines() if line]
        if not rows:
            raise RecoveryError("mysql_binary_log_inventory_empty")
        for row in rows:
            if (
                len(row) != 3
                or not row[1].isdigit()
                or row[2] not in {"Yes", "No"}
            ):
                raise RecoveryError("mysql_binary_log_inventory_invalid")
            name = Path(row[0])
            if name.is_absolute():
                log_path = name
            elif name.name == row[0] and row[0] not in {".", ".."}:
                log_path = log_directory / name
            else:
                raise RecoveryError("mysql_binary_log_path_invalid")
            if log_path.parent != log_directory:
                raise RecoveryError("mysql_binary_log_path_invalid")
            _validate_mysql_binary_log_file(log_path, mysql_uid, mysql_gid)
        protected_files = len(rows) + 1

    return {
        "enabled": enabled,
        "protected_files": protected_files,
        "replication_channels": int(replication_channels),
        "registered_replicas": registered_replicas,
        "gtid_mode": gtid_mode,
        "expiration_seconds": int(expiration),
        "server_id": int(server_id),
        "replica_updates": replica_updates in {"1", "ON"},
    }


def _read_credential(name: str, path: Path) -> bytes:
    if not shutil.which("systemd-creds"):
        raise RecoveryError("systemd_creds_unavailable")
    return _command(
        ["systemd-creds", f"--name={name}", "decrypt", str(path), "-"],
        timeout=60,
    ).stdout


def _encrypt_credential(name: str, plaintext: bytes) -> bytes:
    result = _command(
        ["systemd-creds", f"--name={name}", "--with-key=host", "encrypt", "-", "-"],
        input_bytes=plaintext,
        timeout=60,
    )
    if not result.stdout:
        raise RecoveryError("systemd_credential_encryption_failed")
    return result.stdout


def _path_stat(path: Path) -> os.stat_result | None:
    try:
        return path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError:
        raise RecoveryError("filesystem_metadata_unavailable") from None


def _require_root_owned(
    path: Path,
    *,
    mode: int,
    regular: bool | None = None,
    single_link: bool = True,
) -> os.stat_result:
    metadata = _path_stat(path)
    if metadata is None or metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != mode:
        raise RecoveryError("filesystem_ownership_or_mode_mismatch")
    if regular is True and (
        not stat.S_ISREG(metadata.st_mode) or (single_link and metadata.st_nlink != 1)
    ):
        raise RecoveryError("filesystem_object_type_mismatch")
    if regular is False and not stat.S_ISDIR(metadata.st_mode):
        raise RecoveryError("filesystem_object_type_mismatch")
    return metadata


def _verify_root_only_tree(root: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise RecoveryError("application_tree_unavailable")
    for parent, directories, files in os.walk(root, followlinks=False):
        parent_path = Path(parent)
        parent_metadata = parent_path.stat(follow_symlinks=False)
        if parent_metadata.st_uid != 0 or parent_metadata.st_mode & 0o022:
            raise RecoveryError("application_tree_ownership_mismatch")
        for name in (*directories, *files):
            item = parent_path / name
            metadata = item.stat(follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode):
                try:
                    target = item.resolve(strict=True).stat(follow_symlinks=False)
                except OSError:
                    raise RecoveryError("application_tree_symlink_invalid") from None
                if target.st_uid != 0 or target.st_mode & 0o022:
                    raise RecoveryError("application_tree_symlink_target_unsafe")
            elif metadata.st_uid != 0 or metadata.st_mode & 0o022:
                raise RecoveryError("application_tree_ownership_mismatch")


def _require_no_extended_acl(path: Path) -> None:
    for attribute in ("system.posix_acl_access", "system.posix_acl_default"):
        try:
            _LINUX_OS.getxattr(path, attribute, follow_symlinks=False)
        except OSError as exc:
            if exc.errno in {
                errno.ENODATA,
                errno.ENOTSUP,
                getattr(errno, "EOPNOTSUPP", errno.ENOTSUP),
            }:
                continue
            raise RecoveryError("acl_metadata_unavailable") from None
        raise RecoveryError("unexpected_extended_acl")


def _read_text_file(path: Path, *, max_bytes: int = 512) -> str:
    try:
        raw = path.read_bytes()
    except OSError:
        raise RecoveryError("required_file_unavailable") from None
    if len(raw) > max_bytes:
        raise RecoveryError("required_file_invalid")
    try:
        return raw.decode("ascii").strip()
    except UnicodeError:
        raise RecoveryError("required_file_invalid") from None


def _release_fingerprint() -> str:
    if RELEASE_ROOT.is_symlink() or not RELEASE_ROOT.is_dir():
        raise RecoveryError("release_root_invalid")
    candidates: dict[str, Path] = {}
    for relative in _RELEASE_PATHS:
        source = RELEASE_ROOT / relative
        if source.is_symlink() or not source.exists():
            raise RecoveryError("release_file_set_invalid")
        if source.is_dir():
            for parent, directories, files in os.walk(source, followlinks=False):
                parent_path = Path(parent)
                if parent_path.is_symlink():
                    raise RecoveryError("release_symlink_detected")
                parent_metadata = parent_path.stat(follow_symlinks=False)
                if parent_metadata.st_uid != 0 or parent_metadata.st_mode & 0o022:
                    raise RecoveryError("release_directory_ownership_mismatch")
                for child in directories:
                    item = parent_path / child
                    if item.is_symlink():
                        raise RecoveryError("release_symlink_detected")
                    metadata = item.stat(follow_symlinks=False)
                    if metadata.st_uid != 0 or metadata.st_mode & 0o022:
                        raise RecoveryError("release_directory_ownership_mismatch")
                for child in files:
                    item = parent_path / child
                    if item.is_symlink() or not item.is_file():
                        raise RecoveryError("release_symlink_detected")
                    candidates[item.relative_to(RELEASE_ROOT).as_posix()] = item
        elif source.is_file():
            candidates[relative] = source
        else:
            raise RecoveryError("release_file_set_invalid")
    revision_file = RELEASE_ROOT / "SOURCE_REVISION"
    if revision_file.is_symlink() or not revision_file.is_file():
        raise RecoveryError("release_revision_unavailable")
    candidates["SOURCE_REVISION"] = revision_file

    digest = hashlib.sha256()
    for relative, path in sorted(candidates.items()):
        metadata = path.stat(follow_symlinks=False)
        if metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) & 0o022:
            raise RecoveryError("release_file_ownership_mismatch")
        try:
            content_hash = hashlib.sha256(path.read_bytes()).digest()
        except OSError:
            raise RecoveryError("release_read_failed") from None
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(content_hash)
        digest.update(b"\n")
    return digest.hexdigest()


def _verify_executable_snapshot(expected_sha256: str) -> Path:
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise RecoveryError("snapshot_hash_invalid")
    try:
        path = Path(__file__).resolve(strict=True)
    except OSError:
        raise RecoveryError("snapshot_path_invalid") from None
    if path.parent != APP_ROOT or not path.name.startswith("recover_linux_school_demo_"):
        raise RecoveryError("unprotected_program_path")
    metadata = _require_root_owned(path, mode=0o500, regular=True)
    if metadata.st_mode & 0o022:
        raise RecoveryError("unprotected_program_mode")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise RecoveryError("snapshot_hash_mismatch")
    return path


def _verify_http_verifier(path: Path, expected_sha256: str) -> Path:
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise RecoveryError("http_verifier_hash_invalid")
    resolved = path.resolve(strict=True)
    if resolved.parent != APP_ROOT or not resolved.name.startswith("verify_school_http_linux_"):
        raise RecoveryError("unprotected_http_verifier_path")
    _require_root_owned(resolved, mode=0o500, regular=True)
    if hashlib.sha256(resolved.read_bytes()).hexdigest() != expected_sha256:
        raise RecoveryError("http_verifier_hash_mismatch")
    return resolved


def _base_host_preflight() -> dict[str, object]:
    if (
        not callable(getattr(os, "geteuid", None))
        or _LINUX_OS.geteuid() != 0
        or sys.platform != "linux"
    ):
        raise RecoveryError("linux_root_execution_required")
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    if Path(__file__).resolve(strict=True).parent != APP_ROOT:
        raise RecoveryError("unprotected_program_path")

    hostname = _text(_command(["hostnamectl", "--static"]))
    if hostname != EXPECTED_HOSTNAME:
        raise RecoveryError("server_identity_mismatch")
    release = platform.freedesktop_os_release()
    if release.get("ID") != "ubuntu" or release.get("VERSION_ID") != "24.04":
        raise RecoveryError("operating_system_mismatch")

    _require_root_owned(APP_ROOT, mode=0o755, regular=False)
    _require_root_owned(RELEASE_ROOT, mode=0o755, regular=False)
    _require_root_owned(VENV_ROOT, mode=0o755, regular=False)
    for path in (APP_ROOT, RELEASE_ROOT, VENV_ROOT, SYSTEMD_UNITS, RUN_UNITS):
        _require_no_extended_acl(path)
    _verify_root_only_tree(VENV_ROOT)
    for path in (SOURCE_STAGE,):
        if path.is_symlink() or not path.is_dir():
            raise RecoveryError("staged_source_unavailable")
    _require_root_owned(RELEASE_ROOT / "SOURCE_REVISION", mode=0o644, regular=True)
    source_revision = _read_text_file(SOURCE_STAGE / "SOURCE_REVISION")
    release_revision = _read_text_file(RELEASE_ROOT / "SOURCE_REVISION")
    if source_revision != EXPECTED_SOURCE_REVISION or release_revision != source_revision:
        raise RecoveryError("source_revision_mismatch")
    fingerprint = _release_fingerprint()
    if fingerprint != EXPECTED_RELEASE_FINGERPRINT:
        raise RecoveryError("release_fingerprint_mismatch")

    python = VENV_ROOT / "bin/python"
    try:
        resolved_python = python.resolve(strict=True)
    except OSError:
        raise RecoveryError("application_python_unavailable") from None
    if resolved_python != Path("/usr/bin/python3.12"):
        raise RecoveryError("application_python_mismatch")
    dependency_check = _command([str(python), "-m", "pip", "check"], timeout=180, check=False)
    if dependency_check.returncode != 0:
        raise RecoveryError("application_dependencies_invalid")
    import_check = _command(
        [
            str(python),
            "-I",
            "-c",
            (
                "import alembic, cryptography, fastapi, httpx, pymysql, "
                "sqlalchemy, uvicorn; print('PASS')"
            ),
        ],
        timeout=60,
        check=False,
    )
    if import_check.returncode != 0 or _text(import_check) != "PASS":
        raise RecoveryError("application_dependency_imports_invalid")

    passwd_fields = _text(_command(["getent", "passwd", SERVICE_USER])).split(":")
    if (
        len(passwd_fields) != 7
        or passwd_fields[0] != SERVICE_USER
        or passwd_fields[2] != str(SERVICE_UID)
        or passwd_fields[3] != str(SERVICE_GID)
        or passwd_fields[5] != "/nonexistent"
        or passwd_fields[6] != "/usr/sbin/nologin"
    ):
        raise RecoveryError("service_account_mismatch")
    group_fields = _text(_command(["getent", "group", SERVICE_GROUP])).split(":")
    if (
        len(group_fields) != 4
        or group_fields[0] != SERVICE_GROUP
        or group_fields[2] != str(SERVICE_GID)
        or group_fields[3] != ""
    ):
        raise RecoveryError("service_group_mismatch")

    systemd_version = _text(_command(["systemd-creds", "--version"]))
    if not systemd_version.startswith("systemd 255 "):
        raise RecoveryError("systemd_version_mismatch")
    _require_root_owned(CREDSTORE, mode=0o700, regular=False)
    _require_root_owned(HOST_CREDENTIAL_KEY, mode=0o400, regular=True)
    for path in (CREDSTORE, HOST_CREDENTIAL_KEY):
        _require_no_extended_acl(path)
    if not Path("/var/lib/systemd/credential.secret").exists():
        raise RecoveryError("systemd_host_key_unavailable")

    mysql_identity = _read_single_row(
        "SELECT CURRENT_USER(), VERSION(), @@port, @@global.bind_address, "
        "@@global.general_log, @@global.log_raw, @@global.log_bin",
        fields=7,
    )
    binary_log_enabled = _validate_mysql_identity_policy(mysql_identity)
    binary_log_policy = _validate_mysql_binary_log_policy(binary_log_enabled)
    mysql_version = mysql_identity[1]
    audit_plugins = _mysql(
        "SELECT PLUGIN_NAME FROM information_schema.PLUGINS "
        "WHERE PLUGIN_STATUS='ACTIVE' AND PLUGIN_NAME LIKE '%audit%'"
    )
    if audit_plugins:
        raise RecoveryError("mysql_audit_logging_requires_review")
    if _text(_command(["systemctl", "is-active", "mysql.service"])) != "active":
        raise RecoveryError("mysql_service_inactive")
    if _text(_command(["systemctl", "is-active", "nginx.service"], check=False)) != "inactive":
        raise RecoveryError("nginx_state_changed")

    mysql_listeners = _listener_addresses(MYSQL_PORT)
    if mysql_listeners != ["127.0.0.1:3306"]:
        raise RecoveryError("mysql_listener_scope_mismatch")
    backend_listeners = _listener_addresses(BACKEND_PORT)
    if any(address != "127.0.0.1:8088" for address in backend_listeners):
        raise RecoveryError("backend_listener_scope_mismatch")

    return {
        "hostname": hostname,
        "source_revision": source_revision,
        "release_fingerprint": fingerprint,
        "mysql_version": mysql_version,
        "mysql_listener": mysql_listeners,
        "backend_listener": backend_listeners,
        "systemd_version": systemd_version,
        "mysql_binary_log": binary_log_policy,
    }


def _listener_addresses(port: int) -> list[str]:
    result = _command(
        [
            "ss",
            "--listening",
            "--tcp",
            "--numeric",
            "--no-header",
            "sport",
            "=",
            f":{port}",
        ]
    )
    addresses: list[str] = []
    for line in _text(result).splitlines():
        fields = line.split()
        if len(fields) < 4:
            raise RecoveryError("listener_metadata_invalid")
        addresses.append(fields[3])
    return sorted(addresses)


def _database_snapshot() -> dict[str, object]:
    schema_rows = _mysql(
        "SELECT SCHEMA_NAME, DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME "
        "FROM information_schema.SCHEMATA "
        f"WHERE SCHEMA_NAME='{DATABASE_NAME}'"
    )
    schema = [line.split("\t") for line in schema_rows.splitlines() if line]
    if schema != [[DATABASE_NAME, "utf8mb4", DATABASE_COLLATION]]:
        raise RecoveryError("target_schema_missing_or_incompatible")

    table_output = _mysql(
        "SELECT TABLE_NAME, TABLE_TYPE FROM information_schema.TABLES "
        f"WHERE TABLE_SCHEMA='{DATABASE_NAME}' ORDER BY TABLE_NAME"
    )
    table_rows = [line.split("\t") for line in table_output.splitlines() if line]
    if any(len(row) != 2 or row[1] != "BASE TABLE" for row in table_rows):
        raise RecoveryError("unexpected_database_object_type")
    tables = [row[0] for row in table_rows]
    object_counts = _read_single_row(
        "SELECT "
        "(SELECT COUNT(*) FROM information_schema.TRIGGERS "
        f"WHERE TRIGGER_SCHEMA='{DATABASE_NAME}'), "
        "(SELECT COUNT(*) FROM information_schema.ROUTINES "
        f"WHERE ROUTINE_SCHEMA='{DATABASE_NAME}'), "
        "(SELECT COUNT(*) FROM information_schema.EVENTS "
        f"WHERE EVENT_SCHEMA='{DATABASE_NAME}')",
        fields=3,
    )
    if object_counts != ["0", "0", "0"]:
        raise RecoveryError("unexpected_database_auxiliary_objects")
    revision = None
    if "database_alembic_version" in tables:
        revisions = _mysql(f"SELECT version_num FROM `{DATABASE_NAME}`.`database_alembic_version`")
        revision_rows = [line for line in revisions.splitlines() if line]
        if len(revision_rows) != 1:
            raise RecoveryError("alembic_revision_state_inconsistent")
        revision = revision_rows[0]

    account_output = _mysql(
        "SELECT User, Host, plugin, account_locked, password_expired "
        "FROM mysql.user WHERE LEFT(User, 8)='psynova_' ORDER BY User, Host"
    )
    accounts: list[dict[str, str]] = []
    for line in account_output.splitlines():
        if not line:
            continue
        row = line.split("\t")
        if len(row) != 5 or _ACCOUNT_RE.fullmatch(row[0]) is None:
            raise RecoveryError("unexpected_database_account_shape")
        accounts.append(
            {
                "user": row[0],
                "host": row[1],
                "plugin": row[2],
                "locked": row[3],
                "password_expired": row[4],
            }
        )

    grant_output = _mysql(
        "SELECT 'SCHEMA', User, Host FROM mysql.db "
        f"WHERE Db='{DATABASE_NAME}' "
        "UNION ALL SELECT 'TABLE', User, Host FROM mysql.tables_priv "
        f"WHERE Db='{DATABASE_NAME}' "
        "UNION ALL SELECT 'COLUMN', User, Host FROM mysql.columns_priv "
        f"WHERE Db='{DATABASE_NAME}' "
        "UNION ALL SELECT 'ROUTINE', User, Host FROM mysql.procs_priv "
        f"WHERE Db='{DATABASE_NAME}' ORDER BY 1, 2, 3"
    )
    schema_privileges: list[list[str]] = []
    for line in grant_output.splitlines():
        if not line:
            continue
        row = line.split("\t")
        if len(row) != 3:
            raise RecoveryError("mysql_schema_privilege_shape_invalid")
        schema_privileges.append(row)

    return {
        "schema": schema[0][0],
        "character_set": schema[0][1],
        "collation": schema[0][2],
        "tables": tables,
        "revision": revision,
        "accounts": accounts,
        "schema_privileges": schema_privileges,
        "auxiliary_objects": object_counts,
    }


def _normalize_grant(grant: str) -> str:
    cleaned = re.sub(r"`([^`]*)`", r"\1", grant)
    cleaned = re.sub(r"\s+", " ", cleaned.strip())
    if " TO " not in cleaned or "WITH GRANT OPTION" in cleaned.upper():
        raise RecoveryError("database_grant_state_unexpected")
    prefix = cleaned.split(" TO ", 1)[0].upper()
    match = re.fullmatch(r"GRANT (.+) ON (.+)", prefix)
    if match is None:
        raise RecoveryError("database_grant_state_unexpected")
    privileges, scope = match.groups()
    canonical_privileges = ", ".join(
        sorted(privilege.strip() for privilege in privileges.split(","))
    )
    return f"GRANT {canonical_privileges} ON {scope}"


def _grants_for(username: str) -> list[str]:
    if _ACCOUNT_RE.fullmatch(username) is None:
        raise RecoveryError("database_account_name_invalid")
    output = _mysql(f"SHOW GRANTS FOR '{username}'@'127.0.0.1'")
    return [line for line in output.splitlines() if line]


def _verify_runtime_grants(grants: Sequence[str]) -> None:
    actual = {_normalize_grant(grant) for grant in grants}
    expected = {
        "GRANT USAGE ON *.*",
        "GRANT DELETE, INSERT, SELECT, UPDATE ON SMHAI_SCHOOL_DEMO.*",
    }
    if len(grants) != 2 or actual != expected:
        raise RecoveryError("runtime_grants_not_minimal")


def _verify_migration_grants(grants: Sequence[str], *, allow_usage_only: bool = False) -> None:
    usage = "GRANT USAGE ON *.*"
    migration = (
        "GRANT ALTER, CREATE, DELETE, INDEX, INSERT, REFERENCES, SELECT, UPDATE "
        "ON SMHAI_SCHOOL_DEMO.*"
    )
    actual = {_normalize_grant(grant) for grant in grants}
    valid = [{usage, migration}]
    if allow_usage_only:
        valid.append({usage})
    if len(grants) not in {len(expected) for expected in valid} or actual not in valid:
        raise RecoveryError("migration_grants_not_minimal")


def _account(accounts: Sequence[Mapping[str, str]], username: str) -> Mapping[str, str] | None:
    matches = [item for item in accounts if item.get("user") == username]
    if len(matches) > 1:
        raise RecoveryError("duplicate_database_account")
    if not matches:
        return None
    account = matches[0]
    if (
        account.get("host") != "127.0.0.1"
        or account.get("plugin") != "caching_sha2_password"
        or account.get("password_expired") != "N"
    ):
        raise RecoveryError("database_account_identity_mismatch")
    return account


def _database_accounts(database: Mapping[str, object]) -> list[Mapping[str, str]]:
    value = database.get("accounts")
    if not isinstance(value, list) or any(
        not isinstance(account, Mapping)
        or any(
            not isinstance(name, str) or not isinstance(field, str)
            for name, field in account.items()
        )
        for account in value
    ):
        raise RecoveryError("database_account_inventory_invalid")
    return cast(list[Mapping[str, str]], value)


def _seed_counts() -> dict[str, int]:
    result: dict[str, int] = {}
    for table in _SEED_TABLES:
        if not re.fullmatch(r"[a-z_]+", table):
            raise RecoveryError("seed_table_manifest_invalid")
        value = _read_single_row(f"SELECT COUNT(*) FROM `{DATABASE_NAME}`.`{table}`", fields=1)[0]
        try:
            result[table] = int(value)
        except ValueError:
            raise RecoveryError("seed_count_invalid") from None
    return result


def _state_json(state: Mapping[str, object]) -> bytes:
    return json.dumps(dict(state), ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "ascii"
    )


def _validate_state(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RecoveryError("checkpoint_format_invalid")
    sequence = value.get("sequence")
    required = {
        "schema",
        "operation_id",
        "source_revision",
        "hostname",
        "runtime_user",
        "migrator_user",
        "phase",
        "sequence",
        "created_at",
        "updated_at",
    }
    allowed = required | {"migrator_repaired_from"}
    if frozenset(value) not in {frozenset(required), frozenset(allowed)}:
        raise RecoveryError("checkpoint_format_invalid")
    repaired_from = value.get("migrator_repaired_from")
    repair_checkpoint = "migrator_repaired_from" in value
    if (
        value.get("schema") != STATE_SCHEMA
        or value.get("source_revision") != EXPECTED_SOURCE_REVISION
        or value.get("hostname") != EXPECTED_HOSTNAME
        or value.get("runtime_user") != RUNTIME_USER
        or not isinstance(value.get("operation_id"), str)
        or re.fullmatch(r"[a-f0-9]{32}", str(value.get("operation_id"))) is None
        or not isinstance(value.get("migrator_user"), str)
        or _ACCOUNT_RE.fullmatch(str(value.get("migrator_user"))) is None
        or value.get("phase") not in _PHASES
        or not isinstance(sequence, int)
        or isinstance(sequence, bool)
        or sequence < 1
        or not isinstance(value.get("created_at"), str)
        or not isinstance(value.get("updated_at"), str)
        or (
            repair_checkpoint
            and (
                value.get("phase") not in {"MIGRATOR_PREPARED", "MIGRATOR_AUTH_VERIFIED"}
                or not isinstance(repaired_from, str)
                or _LEGACY_OVERSIZED_MIGRATOR_RE.fullmatch(repaired_from) is None
                or repaired_from == value.get("migrator_user")
                or len(str(value.get("migrator_user"))) > 32
            )
        )
    ):
        raise RecoveryError("checkpoint_format_invalid")
    return cast(dict[str, object], value)


def _read_state_file(path: Path) -> dict[str, object]:
    _require_root_owned(path, mode=0o600, regular=True)
    _require_no_extended_acl(path)
    raw = _read_credential(STATE_CREDENTIAL_NAME, path)
    if len(raw) > 8192:
        raise RecoveryError("checkpoint_too_large")
    try:
        return _validate_state(json.loads(raw.decode("ascii")))
    except (UnicodeError, json.JSONDecodeError):
        raise RecoveryError("checkpoint_format_invalid") from None


def _state_candidates() -> tuple[dict[str, object] | None, dict[str, object] | None]:
    metadata = _path_stat(STATE_ROOT)
    if metadata is None:
        return None, None
    _require_root_owned(STATE_ROOT, mode=0o700, regular=False)
    _require_no_extended_acl(STATE_ROOT)
    entries = {entry.name for entry in STATE_ROOT.iterdir()}
    if entries - {STATE_FILE.name, STATE_NEXT_FILE.name}:
        raise RecoveryError("checkpoint_directory_has_unknown_objects")
    current = _read_state_file(STATE_FILE) if STATE_FILE.exists() else None
    pending = _read_state_file(STATE_NEXT_FILE) if STATE_NEXT_FILE.exists() else None
    if pending is not None:
        if current is None:
            if pending["sequence"] != 1 or pending["phase"] != "INITIALIZED":
                raise RecoveryError("checkpoint_pending_state_inconsistent")
        elif (
            pending["operation_id"] != current["operation_id"]
            or cast(int, pending["sequence"]) != cast(int, current["sequence"]) + 1
        ):
            raise RecoveryError("checkpoint_pending_state_inconsistent")
    return current, pending


def _effective_state(
    current: dict[str, object] | None, pending: dict[str, object] | None
) -> dict[str, object] | None:
    return pending if pending is not None else current


def _promote_pending_state(
    current: dict[str, object] | None, pending: dict[str, object] | None
) -> dict[str, object] | None:
    if pending is None:
        return current
    try:
        os.replace(STATE_NEXT_FILE, STATE_FILE)
        directory_fd = os.open(STATE_ROOT, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError:
        raise RecoveryError("checkpoint_promotion_failed") from None
    return pending


def _save_state(state: dict[str, object]) -> dict[str, object]:
    if not STATE_ROOT.exists():
        try:
            STATE_ROOT.mkdir(mode=0o700)
            _LINUX_OS.chown(STATE_ROOT, 0, 0)
            os.chmod(STATE_ROOT, 0o700)
        except OSError:
            raise RecoveryError("checkpoint_directory_creation_failed") from None
    _require_root_owned(STATE_ROOT, mode=0o700, regular=False)
    current, pending = _state_candidates()
    if pending is not None:
        current = _promote_pending_state(current, pending)
    state = dict(state)
    sequence = 1 if current is None else cast(int, current["sequence"]) + 1
    state["sequence"] = sequence
    state["updated_at"] = dt.datetime.now(dt.UTC).isoformat()
    state = _validate_state(state)
    encrypted = _encrypt_credential(STATE_CREDENTIAL_NAME, _state_json(state))
    if STATE_NEXT_FILE.exists():
        existing = _read_state_file(STATE_NEXT_FILE)
        if existing != state:
            raise RecoveryError("checkpoint_pending_state_conflict")
        return existing
    try:
        descriptor = os.open(
            STATE_NEXT_FILE,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
        _LINUX_OS.chown(STATE_NEXT_FILE, 0, 0)
        os.chmod(STATE_NEXT_FILE, 0o600)
    except OSError:
        raise RecoveryError("checkpoint_write_failed") from None
    verified = _read_state_file(STATE_NEXT_FILE)
    if verified != state:
        raise RecoveryError("checkpoint_authentication_failed")
    return _promote_pending_state(current, verified) or verified


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _new_state(host: Mapping[str, object]) -> dict[str, object]:
    while True:
        migration_user = "psynova_migrator_" + secrets.token_hex(8)[:15]
        if _ACCOUNT_RE.fullmatch(migration_user) is None:
            raise RecoveryError("generated_database_account_name_invalid")
        if len(migration_user) > 32:
            raise RecoveryError("generated_database_account_name_too_long")
        existing = _mysql(f"SELECT User FROM mysql.user WHERE User='{migration_user}'")
        if not existing:
            break
    timestamp = _now()
    return {
        "schema": STATE_SCHEMA,
        "operation_id": secrets.token_hex(16),
        "source_revision": EXPECTED_SOURCE_REVISION,
        "hostname": str(host["hostname"]),
        "runtime_user": RUNTIME_USER,
        "migrator_user": migration_user,
        "phase": "INITIALIZED",
        "sequence": 0,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def _begin_migrator_identity_repair(
    state: dict[str, object], database: Mapping[str, object]
) -> dict[str, object]:
    if state.get("phase") != "MIGRATOR_PREPARED" or "migrator_repaired_from" in state:
        return state
    old_user = str(state["migrator_user"])
    if _LEGACY_OVERSIZED_MIGRATOR_RE.fullmatch(old_user) is None:
        return state
    if _schema_state(database) != "EMPTY":
        raise RecoveryError("migrator_repair_schema_not_empty")
    existing_migrators = [
        account
        for account in _database_accounts(database)
        if str(account.get("user", "")).startswith("psynova_migrator_")
    ]
    if existing_migrators:
        raise RecoveryError("migrator_repair_requires_absent_account")
    raw = _read_credential_candidates(MIGRATION_CREDENTIAL_NAME)
    if raw is None:
        raise RecoveryError("migrator_repair_original_credential_missing")
    _decode_migration_payload(raw, expected_user=old_user)
    for path in (
        _migrator_repair_next_path(),
        _migrator_repair_backup_path(),
        _migrator_repair_temp_path(state),
    ):
        if path.exists() or path.is_symlink():
            raise RecoveryError("untracked_migrator_repair_object")

    while True:
        new_user = "psynova_migrator_" + secrets.token_hex(8)[:15]
        if _ACCOUNT_RE.fullmatch(new_user) is None or len(new_user) > 32:
            raise RecoveryError("generated_database_account_name_invalid")
        if not _mysql(f"SELECT User FROM mysql.user WHERE User='{new_user}'"):
            break
    updated = dict(state)
    updated["migrator_user"] = new_user
    updated["migrator_repaired_from"] = old_user
    saved = _save_state(updated)
    _emit("checkpoint", checkpoint=str(saved["phase"]), sequence=saved["sequence"])
    return saved


def _set_state_phase(state: dict[str, object], phase: str) -> dict[str, object]:
    _set_phase(phase)
    updated = dict(state)
    updated["phase"] = phase
    saved = _save_state(updated)
    _emit("checkpoint", checkpoint=phase, sequence=saved["sequence"])
    return saved


def _credential_path(logical_name: str) -> Path:
    try:
        return CREDSTORE / _CREDENTIALS[logical_name]
    except KeyError:
        raise RecoveryError("credential_name_unexpected") from None


def _credential_staging_path(logical_name: str) -> Path:
    path = _credential_path(logical_name)
    return path.with_name(f".{path.name}.recovery-next")


def _migrator_repair_next_path() -> Path:
    return CREDSTORE / MIGRATOR_REPAIR_NEXT


def _migrator_repair_backup_path() -> Path:
    return CREDSTORE / MIGRATOR_REPAIR_BACKUP


def _migrator_repair_temp_path(state: Mapping[str, object]) -> Path:
    if re.fullmatch(r"[a-f0-9]{32}", str(state.get("operation_id", ""))) is None:
        raise RecoveryError("recovery_operation_id_invalid")
    return CREDSTORE / MIGRATOR_REPAIR_TEMP


def _sync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        raise RecoveryError("credential_directory_sync_failed") from None


def _read_credential_candidates(logical_name: str) -> bytes | None:
    target = _credential_path(logical_name)
    staging = _credential_staging_path(logical_name)
    target_exists = target.exists() or target.is_symlink()
    staging_exists = staging.exists() or staging.is_symlink()
    if not target_exists and not staging_exists:
        return None
    contents: list[bytes] = []
    for path in (target, staging):
        if path.exists() or path.is_symlink():
            _require_root_owned(path, mode=0o600, regular=True, single_link=False)
            metadata = _path_stat(path)
            if metadata is None:
                raise RecoveryError("credential_link_state_invalid")
            contents.append(_read_credential(logical_name, path))
    if len(contents) == 2 and contents[0] != contents[1]:
        raise RecoveryError("credential_staging_conflicts_with_target")
    paths = [path for path in (target, staging) if path.exists() or path.is_symlink()]
    if len(paths) == 2:
        left = paths[0].stat(follow_symlinks=False)
        right = paths[1].stat(follow_symlinks=False)
        if (
            (left.st_dev, left.st_ino) != (right.st_dev, right.st_ino)
            or left.st_nlink != 2
            or right.st_nlink != 2
        ):
            raise RecoveryError("credential_staging_link_mismatch")
    elif paths[0].stat(follow_symlinks=False).st_nlink != 1:
        raise RecoveryError("credential_link_state_invalid")
    return contents[0]


def _store_credential(logical_name: str, payload: bytes) -> None:
    if not payload or len(payload) > 65536:
        raise RecoveryError("credential_payload_size_invalid")
    target = _credential_path(logical_name)
    staging = _credential_staging_path(logical_name)
    if target.exists() or target.is_symlink():
        _require_root_owned(target, mode=0o600, regular=True, single_link=False)
        existing = _read_credential(logical_name, target)
        if existing != payload:
            raise RecoveryError("existing_credential_conflicts_with_checkpoint")
    if staging.exists() or staging.is_symlink():
        _require_root_owned(staging, mode=0o600, regular=True, single_link=False)
        staged = _read_credential(logical_name, staging)
        if staged != payload:
            raise RecoveryError("staged_credential_conflicts_with_checkpoint")
    if target.exists() and staging.exists():
        target_stat = target.stat(follow_symlinks=False)
        staging_stat = staging.stat(follow_symlinks=False)
        if (target_stat.st_dev, target_stat.st_ino) != (
            staging_stat.st_dev,
            staging_stat.st_ino,
        ) or target_stat.st_nlink != 2:
            raise RecoveryError("credential_staging_link_mismatch")
        staging.unlink()
        _sync_directory(CREDSTORE)
        target_stat = target.stat(follow_symlinks=False)
        if target_stat.st_nlink != 1:
            raise RecoveryError("credential_link_state_invalid")
        return
    if target.exists():
        if target.stat(follow_symlinks=False).st_nlink != 1:
            raise RecoveryError("credential_link_state_invalid")
        return
    if not staging.exists():
        encrypted = _encrypt_credential(logical_name, payload)
        try:
            descriptor = os.open(
                staging,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            _LINUX_OS.chown(staging, 0, 0)
            os.chmod(staging, 0o600)
            _sync_directory(CREDSTORE)
        except OSError:
            raise RecoveryError("credential_staging_failed") from None
    _require_root_owned(staging, mode=0o600, regular=True)
    if _read_credential(logical_name, staging) != payload:
        raise RecoveryError("credential_staging_roundtrip_failed")
    try:
        os.link(staging, target, follow_symlinks=False)
    except FileExistsError:
        existing = _read_credential(logical_name, target)
        if existing != payload:
            raise RecoveryError("credential_publish_conflict") from None
    except OSError:
        raise RecoveryError("credential_publish_failed") from None
    _sync_directory(CREDSTORE)
    _require_root_owned(target, mode=0o600, regular=True, single_link=False)
    if _read_credential(logical_name, target) != payload:
        raise RecoveryError("credential_roundtrip_failed")
    staging.unlink()
    _sync_directory(CREDSTORE)
    _require_root_owned(target, mode=0o600, regular=True)


def _decode_runtime_payload(raw: bytes, *, expected_user: str) -> dict[str, str]:
    try:
        payload = json.loads(raw.decode("ascii"))
    except (UnicodeError, json.JSONDecodeError):
        raise RecoveryError("runtime_credential_invalid") from None
    if (
        type(payload) is not dict
        or set(payload) != {"schema", "database", "school_csrf_secret"}
        or payload.get("schema") != "psynova.school-runtime.v1"
        or type(payload.get("database")) is not dict
        or set(payload["database"]) != {"host", "port", "name", "user", "password"}
        or payload["database"].get("host") != "127.0.0.1"
        or payload["database"].get("port") != MYSQL_PORT
        or payload["database"].get("name") != DATABASE_NAME
        or payload["database"].get("user") != expected_user
        or not isinstance(payload["database"].get("password"), str)
        or _PASSWORD_RE.fullmatch(payload["database"]["password"]) is None
        or not isinstance(payload.get("school_csrf_secret"), str)
        or _CSRF_RE.fullmatch(payload["school_csrf_secret"]) is None
    ):
        raise RecoveryError("runtime_credential_invalid")
    return {
        "user": payload["database"]["user"],
        "password": payload["database"]["password"],
        "csrf": payload["school_csrf_secret"],
    }


def _decode_migration_payload(raw: bytes, *, expected_user: str) -> dict[str, str]:
    try:
        payload = json.loads(raw.decode("ascii"))
    except (UnicodeError, json.JSONDecodeError):
        raise RecoveryError("migration_credential_invalid") from None
    if (
        type(payload) is not dict
        or set(payload) != {"schema", "database"}
        or payload.get("schema") != "psynova.school-runtime.v1"
        or type(payload.get("database")) is not dict
        or set(payload["database"]) != {"host", "port", "name", "user", "password"}
        or payload["database"].get("host") != "127.0.0.1"
        or payload["database"].get("port") != MYSQL_PORT
        or payload["database"].get("name") != DATABASE_NAME
        or payload["database"].get("user") != expected_user
        or not isinstance(payload["database"].get("password"), str)
        or _PASSWORD_RE.fullmatch(payload["database"]["password"]) is None
    ):
        raise RecoveryError("migration_credential_invalid")
    return {"user": payload["database"]["user"], "password": payload["database"]["password"]}


def _read_optional_migrator_repair_credential(
    path: Path,
) -> dict[str, str] | None:
    if not (path.exists() or path.is_symlink()):
        return None
    _require_root_owned(path, mode=0o600, regular=True)
    _require_no_extended_acl(path)
    raw = _read_credential(MIGRATION_CREDENTIAL_NAME, path)
    try:
        value = json.loads(raw.decode("ascii"))
        username = value["database"]["user"]
    except (UnicodeError, json.JSONDecodeError, KeyError, TypeError):
        raise RecoveryError("migrator_repair_credential_invalid") from None
    if not isinstance(username, str) or _ACCOUNT_RE.fullmatch(username) is None:
        raise RecoveryError("migrator_repair_credential_invalid")
    return _decode_migration_payload(raw, expected_user=username)


def _validate_migrator_repair_objects(state: Mapping[str, object]) -> None:
    if "migrator_repaired_from" not in state:
        for path in (
            _migrator_repair_next_path(),
            _migrator_repair_backup_path(),
            _migrator_repair_temp_path(state),
        ):
            if path.exists() or path.is_symlink():
                raise RecoveryError("untracked_migrator_repair_object")
        return

    old_user = str(state["migrator_repaired_from"])
    new_user = str(state["migrator_user"])
    phase = str(state["phase"])
    target_path = _credential_path(MIGRATION_CREDENTIAL_NAME)
    normal_staging_path = _credential_staging_path(MIGRATION_CREDENTIAL_NAME)
    next_path = _migrator_repair_next_path()
    backup_path = _migrator_repair_backup_path()
    temp_path = _migrator_repair_temp_path(state)
    if normal_staging_path.exists() or normal_staging_path.is_symlink():
        raise RecoveryError("untracked_credential_staging_object")

    target = _read_optional_migrator_repair_credential(target_path)
    staged = _read_optional_migrator_repair_credential(next_path)
    backup = _read_optional_migrator_repair_credential(backup_path)
    temporary = _read_optional_migrator_repair_credential(temp_path)
    target_user = None if target is None else target["user"]
    staged_user = None if staged is None else staged["user"]
    backup_user = None if backup is None else backup["user"]
    temporary_user = None if temporary is None else temporary["user"]

    if any(
        user is not None and user not in {old_user, new_user}
        for user in (target_user, staged_user, backup_user, temporary_user)
    ):
        raise RecoveryError("migrator_repair_credential_identity_mismatch")
    if staged_user not in {None, new_user} or temporary_user not in {None, new_user}:
        raise RecoveryError("migrator_repair_credential_identity_mismatch")
    if backup_user not in {None, old_user}:
        raise RecoveryError("migrator_repair_credential_identity_mismatch")

    if phase == "MIGRATOR_PREPARED":
        original_retained = target_user == old_user and backup is None
        handoff_interrupted = (
            target is None
            and backup_user == old_user
            and staged_user == new_user
            and temporary is None
        )
        handoff_complete = (
            target_user == new_user
            and backup_user == old_user
            and staged is None
            and temporary is None
        )
        if not (original_retained or handoff_interrupted or handoff_complete):
            raise RecoveryError("migrator_repair_credential_layout_invalid")
        if original_retained and staged is not None and temporary is not None:
            raise RecoveryError("migrator_repair_credential_layout_invalid")
    elif phase == "MIGRATOR_AUTH_VERIFIED":
        if target_user != new_user or staged is not None or temporary is not None:
            raise RecoveryError("migrator_repair_credential_layout_invalid")
        if backup_user not in {None, old_user}:
            raise RecoveryError("migrator_repair_credential_layout_invalid")
    else:
        raise RecoveryError("migrator_repair_checkpoint_phase_invalid")


def _write_migrator_repair_temporary_credential(
    state: Mapping[str, object], payload: bytes
) -> Path:
    path = _migrator_repair_temp_path(state)
    if path.exists() or path.is_symlink():
        existing = _read_optional_migrator_repair_credential(path)
        if existing is None or existing["user"] != state["migrator_user"]:
            raise RecoveryError("migrator_repair_credential_identity_mismatch")
        return path
    encrypted = _encrypt_credential(MIGRATION_CREDENTIAL_NAME, payload)
    try:
        descriptor = os.open(
            path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
        _LINUX_OS.chown(path, 0, 0)
        os.chmod(path, 0o600)
        _sync_directory(path.parent)
    except OSError:
        raise RecoveryError("migrator_repair_credential_staging_failed") from None
    _require_root_owned(path, mode=0o600, regular=True)
    _require_no_extended_acl(path)
    if _read_credential(MIGRATION_CREDENTIAL_NAME, path) != payload:
        raise RecoveryError("migrator_repair_credential_roundtrip_failed")
    return path


def _resume_migrator_credential_repair(state: dict[str, object]) -> dict[str, object]:
    if "migrator_repaired_from" not in state:
        return state
    _validate_migrator_repair_objects(state)
    old_user = str(state["migrator_repaired_from"])
    new_user = str(state["migrator_user"])
    target = _credential_path(MIGRATION_CREDENTIAL_NAME)
    staged_path = _migrator_repair_next_path()
    backup = _migrator_repair_backup_path()

    if state["phase"] == "MIGRATOR_AUTH_VERIFIED":
        if backup.exists() or backup.is_symlink():
            original = _read_optional_migrator_repair_credential(backup)
            if original is None or original["user"] != old_user:
                raise RecoveryError("migrator_repair_credential_identity_mismatch")
            try:
                backup.unlink()
            except OSError:
                raise RecoveryError("migrator_repair_backup_cleanup_failed") from None
            _sync_directory(CREDSTORE)
        updated = dict(state)
        updated.pop("migrator_repaired_from", None)
        saved = _save_state(updated)
        _emit("checkpoint", checkpoint=str(saved["phase"]), sequence=saved["sequence"])
        return saved

    target_value = _read_optional_migrator_repair_credential(target)
    staged_value = _read_optional_migrator_repair_credential(staged_path)
    backup_value = _read_optional_migrator_repair_credential(backup)
    temporary_path = _migrator_repair_temp_path(state)

    if target_value is None and backup_value is None:
        raise RecoveryError("migrator_repair_original_credential_missing")
    if target_value is not None and target_value["user"] == old_user:
        if staged_value is None:
            if temporary_path.exists() or temporary_path.is_symlink():
                temporary_value = _read_optional_migrator_repair_credential(temporary_path)
                if temporary_value is None or temporary_value["user"] != new_user:
                    raise RecoveryError("migrator_repair_credential_identity_mismatch")
            else:
                password = secrets.token_urlsafe(48)
                payload = _new_database_credential(new_user, password, csrf=None)
                _write_migrator_repair_temporary_credential(state, payload)
            if not staged_path.exists():
                try:
                    os.replace(temporary_path, staged_path)
                except OSError:
                    raise RecoveryError("migrator_repair_credential_handoff_failed") from None
                _sync_directory(staged_path.parent)
            staged_value = _read_optional_migrator_repair_credential(staged_path)
        if staged_value is None or staged_value["user"] != new_user:
            raise RecoveryError("migrator_repair_credential_identity_mismatch")
        if backup.exists() or backup.is_symlink():
            raise RecoveryError("migrator_repair_credential_layout_invalid")
        try:
            os.replace(target, backup)
        except OSError:
            raise RecoveryError("migrator_repair_credential_handoff_failed") from None
        _sync_directory(CREDSTORE)
        target_value = None
        backup_value = _read_optional_migrator_repair_credential(backup)

    if target_value is None:
        if backup_value is None or backup_value["user"] != old_user:
            raise RecoveryError("migrator_repair_original_credential_missing")
        staged_value = _read_optional_migrator_repair_credential(staged_path)
        if staged_value is None or staged_value["user"] != new_user:
            raise RecoveryError("migrator_repair_staged_credential_missing")
        try:
            os.replace(staged_path, target)
        except OSError:
            raise RecoveryError("migrator_repair_credential_handoff_failed") from None
        _sync_directory(CREDSTORE)
        target_value = _read_optional_migrator_repair_credential(target)

    if target_value is None or target_value["user"] != new_user:
        raise RecoveryError("migrator_repair_credential_promotion_failed")
    return state


def _new_database_credential(username: str, password: str, *, csrf: str | None) -> bytes:
    if _ACCOUNT_RE.fullmatch(username) is None or _PASSWORD_RE.fullmatch(password) is None:
        raise RecoveryError("generated_database_credential_invalid")
    database = {
        "host": "127.0.0.1",
        "port": MYSQL_PORT,
        "name": DATABASE_NAME,
        "user": username,
        "password": password,
    }
    payload: dict[str, object] = {"schema": "psynova.school-runtime.v1", "database": database}
    if csrf is not None:
        if _CSRF_RE.fullmatch(csrf) is None:
            raise RecoveryError("generated_csrf_secret_invalid")
        payload["school_csrf_secret"] = csrf
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def _new_key_payload() -> bytes:
    key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
    return json.dumps(
        {"active_version": "school-demo-v1", "keys": {"school-demo-v1": key}},
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")


def _new_seed_payload() -> bytes:
    nonce = secrets.token_hex(6).upper()
    credentials = {
        f"{school}.{role}": [
            f"SYNTHETIC_{school.upper()}_{role.upper()}_{nonce}",
            secrets.token_urlsafe(32),
        ]
        for school in ("alpha", "beta")
        for role in ("student", "teacher", "psychological_specialist", "admin")
    }
    return json.dumps(
        {"schema": "psynova.school-seed-accounts.v1", "credentials": credentials},
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")


def _validate_key_payload(raw: bytes) -> str:
    try:
        payload = json.loads(raw.decode("ascii"))
        key_text = payload["keys"]["school-demo-v1"]
        key = base64.urlsafe_b64decode(key_text.encode("ascii"))
    except Exception:  # noqa: BLE001 - suppress parsing details that may include key material.
        raise RecoveryError("database_key_credential_invalid") from None
    if (
        type(payload) is not dict
        or set(payload) != {"active_version", "keys"}
        or payload.get("active_version") != "school-demo-v1"
        or type(payload.get("keys")) is not dict
        or set(payload["keys"]) != {"school-demo-v1"}
        or len(key) != 32
    ):
        raise RecoveryError("database_key_credential_invalid")
    return key_text


def _validate_seed_payload(raw: bytes) -> dict[str, tuple[str, str]]:
    try:
        payload = json.loads(raw.decode("ascii"))
    except (UnicodeError, json.JSONDecodeError):
        raise RecoveryError("seed_credential_invalid") from None
    if (
        type(payload) is not dict
        or set(payload) != {"schema", "credentials"}
        or payload.get("schema") != "psynova.school-seed-accounts.v1"
        or type(payload.get("credentials")) is not dict
        or set(payload["credentials"]) != set(_SEED_SLOTS)
    ):
        raise RecoveryError("seed_credential_invalid")
    result: dict[str, tuple[str, str]] = {}
    logins: set[str] = set()
    for slot in _SEED_SLOTS:
        entry = payload["credentials"][slot]
        if (
            type(entry) is not list
            or len(entry) != 2
            or not isinstance(entry[0], str)
            or not entry[0].startswith("SYNTHETIC_")
            or not isinstance(entry[1], str)
            or not 16 <= len(entry[1]) <= 256
            or entry[0].casefold() in logins
        ):
            raise RecoveryError("seed_credential_invalid")
        logins.add(entry[0].casefold())
        result[slot] = (entry[0], entry[1])
    return result


def _validate_staged_credential(logical_name: str, raw: bytes, *, expected_migrator: str) -> None:
    if logical_name == RUNTIME_CREDENTIAL_NAME:
        _decode_runtime_payload(raw, expected_user=RUNTIME_USER)
    elif logical_name == KEY_CREDENTIAL_NAME:
        _validate_key_payload(raw)
    elif logical_name == MIGRATION_CREDENTIAL_NAME:
        _decode_migration_payload(raw, expected_user=expected_migrator)
    elif logical_name == SEED_CREDENTIAL_NAME:
        _validate_seed_payload(raw)
    else:
        raise RecoveryError("credential_name_unexpected")


def _ensure_staged_credentials(state: dict[str, object]) -> dict[str, str]:
    phase = str(state["phase"])
    runtime_raw = _read_credential_candidates(RUNTIME_CREDENTIAL_NAME)
    if runtime_raw is not None:
        runtime = _decode_runtime_payload(runtime_raw, expected_user=RUNTIME_USER)
    else:
        runtime_password = secrets.token_urlsafe(48)
        csrf = secrets.token_hex(32)
        runtime_raw = _new_database_credential(RUNTIME_USER, runtime_password, csrf=csrf)
        runtime = _decode_runtime_payload(runtime_raw, expected_user=RUNTIME_USER)
        _store_credential(RUNTIME_CREDENTIAL_NAME, runtime_raw)

    key_raw = _read_credential_candidates(KEY_CREDENTIAL_NAME)
    if key_raw is not None:
        _validate_key_payload(key_raw)
    else:
        key_raw = _new_key_payload()
        _store_credential(KEY_CREDENTIAL_NAME, key_raw)

    migrator_user = str(state["migrator_user"])
    if _PHASES.index(phase) < _PHASES.index("MIGRATOR_LOCKED"):
        migration_raw = _read_credential_candidates(MIGRATION_CREDENTIAL_NAME)
        if migration_raw is not None:
            migration = _decode_migration_payload(migration_raw, expected_user=migrator_user)
        else:
            migration_password = secrets.token_urlsafe(48)
            migration_raw = _new_database_credential(migrator_user, migration_password, csrf=None)
            migration = _decode_migration_payload(migration_raw, expected_user=migrator_user)
            _store_credential(MIGRATION_CREDENTIAL_NAME, migration_raw)
    else:
        migration = {"user": migrator_user, "password": ""}

    seed_raw = _read_credential_candidates(SEED_CREDENTIAL_NAME)
    if seed_raw is not None:
        _validate_seed_payload(seed_raw)
    else:
        seed_raw = _new_seed_payload()
        _validate_seed_payload(seed_raw)
        _store_credential(SEED_CREDENTIAL_NAME, seed_raw)

    return {
        "runtime_user": runtime["user"],
        "runtime_password": runtime["password"],
        "migrator_user": migration["user"],
        "migrator_password": migration["password"],
    }


def _ensure_mysql_auth(username: str, password: str) -> tuple[bool, list[str]]:
    try:
        venv_site = VENV_ROOT / "lib/python3.12/site-packages"
        if str(venv_site) not in sys.path:
            sys.path.insert(0, str(venv_site))
        import pymysql

        connection = pymysql.connect(
            host="127.0.0.1",
            port=MYSQL_PORT,
            user=username,
            password=password,
            database=DATABASE_NAME,
            connect_timeout=5,
            read_timeout=10,
            write_timeout=10,
            autocommit=True,
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT CURRENT_USER(), CURRENT_ROLE()")
                identity = cursor.fetchone()
                if identity != (username + "@127.0.0.1", "NONE"):
                    raise RecoveryError("database_auth_identity_mismatch")
                cursor.execute("SHOW GRANTS FOR CURRENT_USER()")
                grants = [row[0] for row in cursor.fetchall()]
            return True, grants
        finally:
            connection.close()
    except RecoveryError:
        raise
    except Exception:  # noqa: BLE001 - authentication driver errors are expected here.
        return False, []


def _rotate_runtime_password(password: str) -> None:
    if _PASSWORD_RE.fullmatch(password) is None:
        raise RecoveryError("runtime_password_invalid")
    statement = f"ALTER USER '{RUNTIME_USER}'@'127.0.0.1' IDENTIFIED BY '{password}';"
    _mysql(statement)


def _ensure_runtime_account(
    state: dict[str, object], credentials: Mapping[str, str]
) -> dict[str, object]:
    phase = str(state["phase"])
    authenticated, grants = _ensure_mysql_auth(
        credentials["runtime_user"], credentials["runtime_password"]
    )
    if authenticated:
        _verify_runtime_grants(grants)
        if phase == "RUNTIME_ROTATION_PREPARED":
            return _set_state_phase(state, "RUNTIME_AUTH_VERIFIED")
        if phase not in _PHASES[_PHASES.index("RUNTIME_AUTH_VERIFIED") :]:
            raise RecoveryError("runtime_auth_state_unexpected")
        return state
    if phase not in {"CREDENTIALS_STAGED", "RUNTIME_ROTATION_PREPARED"}:
        raise RecoveryError("runtime_credential_no_longer_authenticates")
    account = _account(_database_accounts(_database_snapshot()), RUNTIME_USER)
    if account is None or account["locked"] != "N":
        raise RecoveryError("runtime_account_state_unexpected")
    _verify_runtime_grants(_grants_for(RUNTIME_USER))
    if phase != "RUNTIME_ROTATION_PREPARED":
        state = _set_state_phase(state, "RUNTIME_ROTATION_PREPARED")
    _rotate_runtime_password(credentials["runtime_password"])
    authenticated, grants = _ensure_mysql_auth(
        credentials["runtime_user"], credentials["runtime_password"]
    )
    if not authenticated:
        raise RecoveryError("runtime_password_rotation_unverified")
    _verify_runtime_grants(grants)
    return _set_state_phase(state, "RUNTIME_AUTH_VERIFIED")


def _finish_migrator_identity_repair(state: dict[str, object]) -> dict[str, object]:
    if "migrator_repaired_from" not in state:
        return state
    if state["phase"] == "MIGRATOR_PREPARED":
        state = _set_state_phase(state, "MIGRATOR_AUTH_VERIFIED")
    if state["phase"] != "MIGRATOR_AUTH_VERIFIED":
        raise RecoveryError("migrator_repair_checkpoint_phase_invalid")
    _validate_migrator_repair_objects(state)
    old_user = str(state["migrator_repaired_from"])
    backup = _migrator_repair_backup_path()
    if backup.exists() or backup.is_symlink():
        original = _read_optional_migrator_repair_credential(backup)
        if original is None or original["user"] != old_user:
            raise RecoveryError("migrator_repair_credential_identity_mismatch")
        try:
            backup.unlink()
        except OSError:
            raise RecoveryError("migrator_repair_backup_cleanup_failed") from None
        _sync_directory(CREDSTORE)
    updated = dict(state)
    updated.pop("migrator_repaired_from", None)
    saved = _save_state(updated)
    _emit("checkpoint", checkpoint=str(saved["phase"]), sequence=saved["sequence"])
    return saved


def _ensure_migrator_account(
    state: dict[str, object], credentials: Mapping[str, str]
) -> dict[str, object]:
    username = credentials["migrator_user"]
    password = credentials["migrator_password"]
    phase = str(state["phase"])
    authenticated, grants = _ensure_mysql_auth(username, password)
    if not authenticated:
        if phase not in {"RUNTIME_AUTH_VERIFIED", "MIGRATOR_PREPARED"}:
            raise RecoveryError("migrator_credential_no_longer_authenticates")
        if phase != "MIGRATOR_PREPARED":
            state = _set_state_phase(state, "MIGRATOR_PREPARED")
        account = _account(_database_accounts(_database_snapshot()), username)
        if account is None:
            statement = f"CREATE USER '{username}'@'127.0.0.1' IDENTIFIED BY '{password}';"
            _mysql(statement)
        else:
            raise RecoveryError("migrator_existing_account_authentication_failed")
        partial_grants = _grants_for(username)
        if {_normalize_grant(item) for item in partial_grants} == {"GRANT USAGE ON *.*"}:
            _mysql(
                "GRANT CREATE, ALTER, INDEX, REFERENCES, SELECT, INSERT, UPDATE, DELETE "
                f"ON `{DATABASE_NAME}`.* TO '{username}'@'127.0.0.1';"
            )
        elif partial_grants:
            _verify_migration_grants(partial_grants)
        authenticated, grants = _ensure_mysql_auth(username, password)
        if not authenticated:
            raise RecoveryError("migrator_authentication_unverified")
    elif phase == "MIGRATOR_PREPARED":
        normalized = {_normalize_grant(item) for item in grants}
        if normalized == {"GRANT USAGE ON *.*"}:
            _mysql(
                "GRANT CREATE, ALTER, INDEX, REFERENCES, SELECT, INSERT, UPDATE, DELETE "
                f"ON `{DATABASE_NAME}`.* TO '{username}'@'127.0.0.1';"
            )
            authenticated, grants = _ensure_mysql_auth(username, password)
            if not authenticated:
                raise RecoveryError("migrator_authentication_unverified")
    _verify_migration_grants(grants)
    if "migrator_repaired_from" in state:
        return _finish_migrator_identity_repair(state)
    if phase in {"RUNTIME_AUTH_VERIFIED", "MIGRATOR_PREPARED"}:
        return _set_state_phase(state, "MIGRATOR_AUTH_VERIFIED")
    if phase not in _PHASES[_PHASES.index("MIGRATOR_AUTH_VERIFIED") :]:
        raise RecoveryError("migrator_auth_state_unexpected")
    return state


def _unit_staging_path(unit_name: str, *, transient: bool) -> Path:
    root = RUN_UNITS if transient else SYSTEMD_UNITS
    return root / f".{unit_name}.recovery-next"


def _install_unit(unit_name: str, *, transient: bool = False) -> None:
    source = RELEASE_ROOT / "13_deployment" / "systemd" / unit_name
    target_root = RUN_UNITS if transient else SYSTEMD_UNITS
    target = target_root / unit_name
    staging = _unit_staging_path(unit_name, transient=transient)
    if source.is_symlink() or not source.is_file():
        raise RecoveryError("systemd_unit_source_unavailable")
    source_bytes = source.read_bytes()
    if target.exists() or target.is_symlink():
        _require_root_owned(target, mode=0o644, regular=True, single_link=False)
        if target.read_bytes() != source_bytes:
            raise RecoveryError("existing_systemd_unit_conflicts_with_release")
    if staging.exists() or staging.is_symlink():
        _require_root_owned(staging, mode=0o644, regular=True, single_link=False)
        if staging.read_bytes() != source_bytes:
            raise RecoveryError("staged_systemd_unit_conflicts_with_release")
    if target.exists() and staging.exists():
        left = target.stat(follow_symlinks=False)
        right = staging.stat(follow_symlinks=False)
        if (left.st_dev, left.st_ino) != (right.st_dev, right.st_ino) or left.st_nlink != 2:
            raise RecoveryError("systemd_unit_staging_link_mismatch")
        staging.unlink()
        _sync_directory(target_root)
        return
    if target.exists():
        if target.stat(follow_symlinks=False).st_nlink != 1:
            raise RecoveryError("systemd_unit_link_state_invalid")
        return
    if not staging.exists():
        try:
            descriptor = os.open(
                staging,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
                0o644,
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(source_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            _LINUX_OS.chown(staging, 0, 0)
            os.chmod(staging, 0o644)
            _sync_directory(target_root)
        except OSError:
            raise RecoveryError("systemd_unit_staging_failed") from None
    _require_root_owned(staging, mode=0o644, regular=True)
    if staging.read_bytes() != source_bytes:
        raise RecoveryError("systemd_unit_staging_verification_failed")
    try:
        os.link(staging, target, follow_symlinks=False)
    except FileExistsError:
        if target.read_bytes() != source_bytes:
            raise RecoveryError("systemd_unit_publish_conflict") from None
    except OSError:
        raise RecoveryError("systemd_unit_publish_failed") from None
    _sync_directory(target_root)
    _require_root_owned(target, mode=0o644, regular=True, single_link=False)
    if target.read_bytes() != source_bytes:
        raise RecoveryError("systemd_unit_publish_verification_failed")
    staging.unlink()
    _sync_directory(target_root)
    _require_root_owned(target, mode=0o644, regular=True)


def _unit_show(unit_name: str) -> dict[str, str]:
    result = _command(
        [
            "systemctl",
            "show",
            unit_name,
            "--property=LoadState",
            "--property=ActiveState",
            "--property=SubState",
            "--property=Result",
            "--property=ExecMainStatus",
            "--property=InvocationID",
        ],
        check=False,
    )
    values: dict[str, str] = {}
    for line in _text(result).splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    if not values:
        raise RecoveryError("systemd_unit_state_unavailable")
    return values


def _unit_invocation_json(unit_name: str, *, expected_key: str) -> dict[str, object]:
    status = _unit_show(unit_name)
    if status.get("Result") != "success" or status.get("ExecMainStatus") != "0":
        raise RecoveryError("systemd_oneshot_failed")
    invocation = status.get("InvocationID", "")
    if re.fullmatch(r"[a-f0-9]{32}", invocation) is None:
        raise RecoveryError("systemd_invocation_id_unavailable")
    output = _text(
        _command(
            [
                "journalctl",
                "--no-pager",
                "--output=cat",
                f"_SYSTEMD_INVOCATION_ID={invocation}",
            ],
            timeout=60,
        )
    )
    rows: list[dict[str, object]] = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if type(value) is dict and expected_key in value:
            rows.append(value)
    if not rows:
        raise RecoveryError("systemd_unit_safe_result_unavailable")
    return rows[-1]


def _start_oneshot(unit_name: str, *, timeout: int = 300) -> dict[str, object]:
    _command(["systemctl", "start", unit_name], timeout=timeout)
    return _unit_invocation_json(
        unit_name, expected_key="migration" if "migrate" in unit_name else "seed"
    )


def _run_probe() -> dict[str, object]:
    _command(["systemctl", "start", "psynova-school-credential-probe.service"], timeout=120)
    result = _unit_invocation_json(
        "psynova-school-credential-probe.service", expected_key="systemd_credential_injection"
    )
    if (
        result.get("systemd_credential_injection") != "PASS"
        or result.get("key_provider") != "LinuxSystemdCredentialKeyProvider"
        or result.get("effective_uid") != SERVICE_UID
    ):
        raise RecoveryError("real_systemd_credential_probe_failed")
    return result


def _verify_seed_result(result: Mapping[str, object]) -> dict[str, object]:
    if (
        result.get("seed") != "VERIFIED"
        or result.get("schools") != 2
        or result.get("subjects") != 2
        or result.get("role_accounts") != 8
        or result.get("idempotent_second_pass") is not True
    ):
        raise RecoveryError("synthetic_seed_verification_failed")
    return dict(result)


def _seed_systemd_unit() -> dict[str, object]:
    _command(["systemctl", "start", "psynova-school-seed.service"], timeout=300)
    result = _unit_invocation_json("psynova-school-seed.service", expected_key="seed")
    return _verify_seed_result(result)


def _last_seed_systemd_result() -> dict[str, object]:
    return _verify_seed_result(
        _unit_invocation_json("psynova-school-seed.service", expected_key="seed")
    )


def _count_seed_systemd_results(since: str) -> int:
    output = _text(
        _command(
            [
                "journalctl",
                "--no-pager",
                "--output=cat",
                f"--since={since}",
                "--unit=psynova-school-seed.service",
            ],
            timeout=120,
        )
    )
    count = 0
    for line in output.splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if type(payload) is dict and payload.get("seed") == "VERIFIED":
            _verify_seed_result(payload)
            count += 1
    return count


def _verify_migrated_schema() -> dict[str, int | str]:
    try:
        site = VENV_ROOT / "lib/python3.12/site-packages"
        if str(site) not in sys.path:
            sys.path.insert(0, str(site))
        sys.path.insert(0, str(RELEASE_ROOT / "11_database"))
        sys.path.insert(0, str(RELEASE_ROOT / "13_deployment"))
        migration = cast(Any, importlib.import_module("migrate_school_linux"))
        sqlalchemy = cast(Any, importlib.import_module("sqlalchemy"))
        sqlalchemy_engine = cast(Any, importlib.import_module("sqlalchemy.engine"))
        migration_revision = migration.EXPECTED_REVISION
        revision_and_tables = migration._revision_and_tables
        verify_schema_structure = migration._verify_schema_structure
        create_engine = sqlalchemy.create_engine
        url_type = sqlalchemy_engine.URL

        url = url_type.create(
            "mysql+pymysql",
            username="root",
            host="localhost",
            database=DATABASE_NAME,
            query={"unix_socket": "/var/run/mysqld/mysqld.sock"},
        )
        engine = create_engine(url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                driver_connection = connection.connection.driver_connection
                revision, tables = revision_and_tables(driver_connection)
                if revision != EXPECTED_REVISION or migration_revision != EXPECTED_REVISION:
                    raise RecoveryError("alembic_revision_not_target")
                if not tables:
                    raise RecoveryError("migrated_schema_has_no_tables")
                structure = verify_schema_structure(connection)
        finally:
            engine.dispose()
    except RecoveryError:
        raise
    except Exception:  # noqa: BLE001 - avoid exposing SQLAlchemy and schema details.
        raise RecoveryError("migrated_schema_validation_failed") from None
    return {"revision": EXPECTED_REVISION, **structure}


def _schema_state(database: Mapping[str, object]) -> str:
    tables = database.get("tables")
    revision = database.get("revision")
    if tables == [] and revision is None:
        return "EMPTY"
    if isinstance(revision, str) and revision == EXPECTED_REVISION:
        return "TARGET_REVISION"
    return "INCONSISTENT"


def _strict_state(
    host: Mapping[str, object],
    database: Mapping[str, object],
    state: Mapping[str, object] | None,
) -> dict[str, object]:
    migrator_repair_active = state is not None and "migrator_repaired_from" in state
    account_list = _database_accounts(database)
    table_value = database.get("tables")
    if not isinstance(table_value, list) or any(
        not isinstance(table, str) for table in table_value
    ):
        raise RecoveryError("database_table_inventory_invalid")
    runtime = _account(account_list, RUNTIME_USER)
    if runtime is None or runtime.get("locked") != "N":
        raise RecoveryError("known_runtime_account_not_available")
    _verify_runtime_grants(_grants_for(RUNTIME_USER))
    schema_privileges = database.get("schema_privileges")
    if not isinstance(schema_privileges, list) or any(
        not isinstance(row, list)
        or len(row) != 3
        or not all(isinstance(value, str) for value in row)
        for row in schema_privileges
    ):
        raise RecoveryError("mysql_schema_privilege_inventory_invalid")
    schema_state = _schema_state(database)
    expected_migrator = None if state is None else str(state["migrator_user"])
    migrators = [
        account
        for account in account_list
        if str(account.get("user", "")).startswith("psynova_migrator_")
    ]
    if state is None:
        state_root_entries: set[str] = set()
        if STATE_ROOT.exists() or STATE_ROOT.is_symlink():
            _require_root_owned(STATE_ROOT, mode=0o700, regular=False)
            state_root_entries = {entry.name for entry in STATE_ROOT.iterdir()}
        if schema_state != "EMPTY" or len(account_list) != 1 or migrators or state_root_entries:
            raise RecoveryError("initial_partial_install_state_mismatch")
    else:
        if any(account.get("user") != expected_migrator for account in migrators):
            raise RecoveryError("untracked_migrator_account_found")
        if len(migrators) > 1:
            raise RecoveryError("multiple_migrator_accounts_found")
        phase = str(state["phase"])
        phase_index = _PHASES.index(phase)
        if phase == "INITIALIZED" and any(
            _path_stat(path) is not None
            for logical in _CREDENTIALS
            for path in (
                _credential_path(logical),
                _credential_staging_path(logical),
            )
        ):
            raise RecoveryError("credentials_precede_staging_checkpoint")
        before_migration = _PHASES.index(phase) < _PHASES.index("MIGRATION_STARTED")
        if before_migration and schema_state != "EMPTY":
            raise RecoveryError("schema_changed_before_checkpoint")
        if not before_migration and schema_state == "INCONSISTENT":
            raise RecoveryError("partial_or_unrecognized_migration_state")
        after_schema = _PHASES.index(phase) >= _PHASES.index("SCHEMA_MIGRATED")
        if after_schema and schema_state != "TARGET_REVISION":
            raise RecoveryError("schema_checkpoint_mismatch")
        if migrators:
            migrator = _account(account_list, expected_migrator or "")
            if migrator is None:
                raise RecoveryError("migrator_checkpoint_mismatch")
            locked = migrator.get("locked")
            phase_index = _PHASES.index(phase)
            if phase_index < _PHASES.index("MIGRATOR_LOCKED"):
                if locked == "Y" and phase_index < _PHASES.index("SCHEMA_MIGRATED"):
                    raise RecoveryError("migrator_lock_state_mismatch")
            elif locked != "Y":
                raise RecoveryError("migrator_lock_state_mismatch")
            grants = _grants_for(expected_migrator or "")
            _verify_migration_grants(
                grants,
                allow_usage_only=(phase == "MIGRATOR_PREPARED"),
            )
        elif _PHASES.index(phase) >= _PHASES.index("MIGRATOR_AUTH_VERIFIED"):
            raise RecoveryError("migrator_missing_after_auth_checkpoint")
    expected_schema_privileges = {("SCHEMA", RUNTIME_USER, "127.0.0.1")}
    if state is not None:
        migrator_name = str(state["migrator_user"])
        migrator = _account(account_list, migrator_name)
        if migrator is not None:
            normalized = {_normalize_grant(item) for item in _grants_for(migrator_name)}
            migration_database_grant = (
                "GRANT CREATE, ALTER, INDEX, REFERENCES, SELECT, INSERT, UPDATE, DELETE "
                "ON SMHAI_SCHOOL_DEMO.*"
            )
            if migration_database_grant in normalized:
                expected_schema_privileges.add(("SCHEMA", migrator_name, "127.0.0.1"))
    if {tuple(row) for row in schema_privileges} != expected_schema_privileges:
        raise RecoveryError("untracked_schema_privilege_account")
    if state is not None:
        phase = str(state["phase"])
        if _PHASES.index(phase) >= _PHASES.index("SEED_PASS_1_VERIFIED"):
            counts = _seed_counts()
            if counts != _SEED_COUNTS:
                raise RecoveryError("synthetic_seed_checkpoint_mismatch")
        elif schema_state == "TARGET_REVISION":
            counts = _seed_counts()
            zero_counts = dict.fromkeys(_SEED_TABLES, 0)
            if phase == "SEED_PASS_1_STARTED":
                bounded = all(
                    type(counts.get(table)) is int and 0 <= counts[table] <= _SEED_COUNTS[table]
                    for table in _SEED_TABLES
                )
                if not bounded:
                    raise RecoveryError("untracked_seed_data_found")
            elif counts != zero_counts:
                raise RecoveryError("untracked_seed_data_found")

    credential_status = {
        logical: (_path_stat(_credential_path(logical)) is not None) for logical in _CREDENTIALS
    }
    credential_staging_status = {
        logical: (_path_stat(_credential_staging_path(logical)) is not None)
        for logical in _CREDENTIALS
    }
    if state is not None:
        _validate_migrator_repair_objects(state)
        for logical in _CREDENTIALS:
            if migrator_repair_active and logical == MIGRATION_CREDENTIAL_NAME:
                continue
            for path in (_credential_path(logical), _credential_staging_path(logical)):
                if path.exists() or path.is_symlink():
                    _require_root_owned(path, mode=0o600, regular=True, single_link=False)
                    metadata = _path_stat(path)
                    if metadata is None or metadata.st_nlink not in {1, 2}:
                        raise RecoveryError("credential_link_state_invalid")
                    raw = _read_credential(logical, path)
                    _validate_staged_credential(
                        logical,
                        raw,
                        expected_migrator=str(state["migrator_user"]),
                    )
                    _require_no_extended_acl(path)
        for staging_present in credential_staging_status.values():
            if staging_present and str(state["phase"]) not in {
                "CREDENTIALS_STAGING",
                "MIGRATOR_LOCKED",
            }:
                raise RecoveryError("untracked_credential_staging_object")
    unit_status: dict[str, bool] = {}
    for unit in _PERMANENT_UNITS:
        path = SYSTEMD_UNITS / unit
        unit_status[unit] = path.exists() or path.is_symlink()
        if unit_status[unit]:
            _require_root_owned(path, mode=0o644, regular=True, single_link=False)
            if (
                path.read_bytes()
                != (RELEASE_ROOT / "13_deployment" / "systemd" / unit).read_bytes()
            ):
                raise RecoveryError("permanent_unit_differs_from_reviewed_source")
            _require_no_extended_acl(path)
    migration_unit_path = RUN_UNITS / _MIGRATION_UNIT
    migration_unit_present = migration_unit_path.exists() or migration_unit_path.is_symlink()
    if migration_unit_present:
        _require_root_owned(migration_unit_path, mode=0o644, regular=True, single_link=False)
        if (
            migration_unit_path.read_bytes()
            != (RELEASE_ROOT / "13_deployment" / "systemd" / _MIGRATION_UNIT).read_bytes()
        ):
            raise RecoveryError("migration_unit_differs_from_reviewed_source")
        _require_no_extended_acl(migration_unit_path)
    unit_staging_status: dict[str, bool] = {}
    for unit in (*_PERMANENT_UNITS, _MIGRATION_UNIT):
        transient = unit == _MIGRATION_UNIT
        staging_path = _unit_staging_path(unit, transient=transient)
        unit_staging_status[unit] = staging_path.exists() or staging_path.is_symlink()
        if unit_staging_status[unit]:
            _require_root_owned(staging_path, mode=0o644, regular=True, single_link=False)
            if (
                staging_path.read_bytes()
                != (RELEASE_ROOT / "13_deployment" / "systemd" / unit).read_bytes()
            ):
                raise RecoveryError("staged_systemd_unit_differs_from_release")
            _require_no_extended_acl(staging_path)
            target_path = (RUN_UNITS if transient else SYSTEMD_UNITS) / unit
            if target_path.exists():
                left = target_path.stat(follow_symlinks=False)
                right = staging_path.stat(follow_symlinks=False)
                if (left.st_dev, left.st_ino) != (right.st_dev, right.st_ino) or left.st_nlink != 2:
                    raise RecoveryError("systemd_unit_staging_link_mismatch")
            elif staging_path.stat(follow_symlinks=False).st_nlink != 1:
                raise RecoveryError("systemd_unit_link_state_invalid")
        target_path = (RUN_UNITS if transient else SYSTEMD_UNITS) / unit
        if (
            target_path.exists()
            and not unit_staging_status[unit]
            and target_path.stat(follow_symlinks=False).st_nlink != 1
        ):
            raise RecoveryError("systemd_unit_link_state_invalid")

    if state is None:
        if (
            any(credential_status.values())
            or any(credential_staging_status.values())
            or any(
                path.exists() or path.is_symlink()
                for path in (
                    _migrator_repair_next_path(),
                    _migrator_repair_backup_path(),
                    CREDSTORE / MIGRATOR_REPAIR_TEMP,
                )
            )
            or any(unit_status.values())
            or migration_unit_present
            or any(unit_staging_status.values())
        ):
            raise RecoveryError("untracked_credential_or_unit_found")
    else:
        phase_index = _PHASES.index(str(state["phase"]))
        cred_stage = phase_index >= _PHASES.index("CREDENTIALS_STAGED")
        if any(unit_staging_status.values()) and str(state["phase"]) != "SYSTEMD_UNITS_INSTALLING":
            raise RecoveryError("untracked_systemd_unit_staging_object")
        if cred_stage and not all(
            credential_status[name]
            for name in (KEY_CREDENTIAL_NAME, RUNTIME_CREDENTIAL_NAME, SEED_CREDENTIAL_NAME)
        ):
            raise RecoveryError("required_credential_missing")
        if (
            phase_index < _PHASES.index("CREDENTIALS_STAGED")
            and any(credential_staging_status.values())
            and str(state["phase"]) != "CREDENTIALS_STAGING"
        ):
            raise RecoveryError("credential_staging_checkpoint_mismatch")
        if str(state["phase"]) == "CREDENTIALS_STAGING":
            for logical, present in credential_status.items():
                if present and credential_staging_status[logical]:
                    target_path = _credential_path(logical)
                    staging_path = _credential_staging_path(logical)
                    left = target_path.stat(follow_symlinks=False)
                    right = staging_path.stat(follow_symlinks=False)
                    if (left.st_dev, left.st_ino) != (right.st_dev, right.st_ino):
                        raise RecoveryError("credential_staging_link_mismatch")
        if (
            phase_index >= _PHASES.index("CREDENTIALS_STAGED")
            and any(credential_staging_status.values())
            and str(state["phase"]) != "MIGRATOR_LOCKED"
        ):
            raise RecoveryError("untracked_credential_staging_object")
        migration_credential_present = credential_status[MIGRATION_CREDENTIAL_NAME]
        migration_credential_staged = credential_staging_status[MIGRATION_CREDENTIAL_NAME]
        if not migrator_repair_active and phase_index >= _PHASES.index("CREDENTIALS_STAGED"):
            if phase_index < _PHASES.index("MIGRATOR_LOCKED"):
                if not migration_credential_present or migration_credential_staged:
                    raise RecoveryError("migration_credential_missing_before_lock")
            elif phase_index > _PHASES.index("MIGRATOR_LOCKED") and (
                migration_credential_present or migration_credential_staged
            ):
                raise RecoveryError("migration_credential_state_mismatch")
        unit_stage = phase_index >= _PHASES.index("SYSTEMD_UNITS_INSTALLED")
        install_started = phase_index >= _PHASES.index("SYSTEMD_UNITS_INSTALLING")
        if unit_stage and not all(unit_status.values()):
            raise RecoveryError("permanent_systemd_unit_missing")
        if not install_started and (any(unit_status.values()) or migration_unit_present):
            raise RecoveryError("systemd_unit_precedes_install_checkpoint")
        if phase_index >= _PHASES.index("MIGRATION_CREDENTIAL_REMOVED") and migration_unit_present:
            raise RecoveryError("migration_unit_state_mismatch")

    seed_counts: dict[str, int] | None = None
    if schema_state == "TARGET_REVISION":
        seed_counts = _seed_counts()
    service_status = _unit_show("psynova-school-demo.service")
    backend_listener = host.get("backend_listener")
    backend_started = state is not None and _PHASES.index(str(state["phase"])) >= _PHASES.index(
        "BACKEND_STARTED"
    )
    backend_start_pending = state is not None and state.get("phase") == "BACKEND_STARTING"
    if backend_started:
        if service_status.get("ActiveState") == "active":
            if backend_listener != ["127.0.0.1:8088"]:
                raise RecoveryError("backend_listener_scope_mismatch")
        elif service_status.get("ActiveState") == "inactive":
            if backend_listener:
                raise RecoveryError("unexpected_backend_listener")
        else:
            raise RecoveryError("backend_listener_scope_mismatch")
    elif backend_start_pending:
        if service_status.get("ActiveState") == "active":
            if backend_listener != ["127.0.0.1:8088"]:
                raise RecoveryError("backend_listener_scope_mismatch")
        elif service_status.get("ActiveState") == "inactive":
            if backend_listener:
                raise RecoveryError("unexpected_backend_listener")
        else:
            raise RecoveryError("backend_start_failed_before_checkpoint")
    elif backend_listener:
        raise RecoveryError("unexpected_backend_listener")
    if (
        not unit_status["psynova-school-demo.service"]
        and service_status.get("LoadState") != "not-found"
    ):
        raise RecoveryError("unexpected_backend_unit_present")
    if unit_status["psynova-school-demo.service"]:
        if service_status.get("LoadState") != "loaded" and not (
            state is not None
            and state.get("phase") == "SYSTEMD_UNITS_INSTALLING"
            and service_status.get("LoadState") == "not-found"
        ):
            raise RecoveryError("backend_unit_not_loaded")
        if (
            not backend_started
            and not backend_start_pending
            and service_status.get("ActiveState") == "active"
        ):
            raise RecoveryError("backend_started_before_checkpoint")
    return {
        "server": dict(host),
        "schema": {
            "name": DATABASE_NAME,
            "state": schema_state,
            "tables": len(table_value),
            "revision": database.get("revision"),
        },
        "accounts": [
            {
                "user": account["user"],
                "host": account["host"],
                "locked": account["locked"],
                "plugin": account["plugin"],
            }
            for account in account_list
        ],
        "credentials_present": credential_status,
        "credential_staging_present": credential_staging_status,
        "units_present": unit_status,
        "migration_unit_present": migration_unit_present,
        "unit_staging_present": unit_staging_status,
        "backend_state": service_status.get("ActiveState", "unknown"),
        "seed_counts": seed_counts,
        "checkpoint": None
        if state is None
        else {
            "phase": state["phase"],
            "sequence": state["sequence"],
            "operation_id": state["operation_id"],
        },
    }


def _inspect() -> tuple[dict[str, object], dict[str, object] | None, bool]:
    host = _base_host_preflight()
    database = _database_snapshot()
    current, pending = _state_candidates()
    state = _effective_state(current, pending)
    report = _strict_state(host, database, state)
    return report, state, pending is not None


def _plan_actions(state: Mapping[str, object] | None, report: Mapping[str, object]) -> list[str]:
    phase = None if state is None else str(state["phase"])
    start = -1 if phase is None else _PHASES.index(phase)
    actions: list[str] = []
    if (
        state is not None
        and phase == "MIGRATOR_PREPARED"
        and "migrator_repaired_from" not in state
        and len(str(state["migrator_user"])) > 32
    ):
        actions.append(
            "checkpoint a recoverable replacement migrator identity within MySQL's 32-character limit"
        )
    if state is not None and "migrator_repaired_from" in state:
        actions.append("resume the authenticated encrypted migrator credential handoff")
    if phase is None:
        actions.append("create an authenticated encrypted recovery checkpoint")
    if start < _PHASES.index("CREDENTIALS_STAGED"):
        actions.append("finish staging four host-encrypted credentials with no plaintext files")
    if start < _PHASES.index("RUNTIME_AUTH_VERIFIED"):
        actions.append(
            "rotate the existing runtime account from the staged credential and verify TCP login"
        )
    if start < _PHASES.index("MIGRATOR_AUTH_VERIFIED"):
        actions.append(
            "create or complete the scoped migrator account and verify least-privilege grants"
        )
    if start < _PHASES.index("SYSTEMD_UNITS_INSTALLED"):
        actions.append("install only the reviewed systemd units and reload systemd")
    if start < _PHASES.index("CREDENTIAL_PROBE_VERIFIED"):
        actions.append("run the real systemd LoadCredentialEncrypted key-provider probe")
    if start < _PHASES.index("SCHEMA_MIGRATED"):
        actions.append(
            "run the existing Alembic chain and verify revision, tables, constraints and storage"
        )
    if start < _PHASES.index("MIGRATOR_LOCKED"):
        actions.append("lock the verified migrator account")
    if start < _PHASES.index("MIGRATION_CREDENTIAL_REMOVED"):
        actions.append(
            "remove only the authenticated migration credential and reviewed transient unit"
        )
    if start < _PHASES.index("SEED_PASS_1_VERIFIED"):
        actions.append("run the first idempotent synthetic seed pass and verify exact counts")
    if start < _PHASES.index("SEED_PASS_2_VERIFIED"):
        actions.append("run the second idempotent synthetic seed pass and verify no count changes")
    if start < _PHASES.index("NEGATIVE_PREFLIGHTS_VERIFIED"):
        actions.append(
            "verify safe failures for missing runtime credential, missing or damaged key, "
            "and unavailable MySQL"
        )
    if start < _PHASES.index("BACKEND_STARTED"):
        actions.append("start the backend only on 127.0.0.1:8088")
    if start < _PHASES.index("HTTP_VERIFIED"):
        actions.append(
            "run the real two-school, four-role HTTP, CSRF, authorization, session and "
            "persistence checks"
        )
    if not actions:
        actions.append("verify the completed checkpoint and current loopback service")
    return actions


def _make_plan(
    expected_hash: str, *, verifier: Path | None, verifier_hash: str | None
) -> dict[str, object]:
    _verify_executable_snapshot(expected_hash)
    if verifier is not None or verifier_hash is not None:
        if verifier is None or verifier_hash is None:
            raise RecoveryError("http_verifier_identity_incomplete")
        _verify_http_verifier(verifier, verifier_hash)
    report, state, pending = _inspect()
    return {
        "status": (
            "READY"
            if state is None
            else "COMPLETE"
            if state["phase"] == "HTTP_VERIFIED"
            else "RESUMABLE"
        ),
        "phase": "INITIAL_STATE" if state is None else state["phase"],
        "pending_checkpoint": pending,
        "current_state": report,
        "planned_actions": _plan_actions(state, report),
        "writes_performed": False,
    }


def _safe_seed_count_result(value: object) -> bool:
    return isinstance(value, Mapping) and dict(value) == _SEED_COUNTS


def _run_negative_preflight(
    state: Mapping[str, object],
    *,
    kind: str,
    with_runtime: bool,
    with_key: bool,
    block_network: bool,
    key_override: Path | None = None,
) -> dict[str, object]:
    operation_id = str(state["operation_id"])
    unit_name = f"psynova-school-recovery-{kind}-{operation_id[:10]}.service"
    status = _unit_show(unit_name)
    if status.get("LoadState") != "not-found":
        raise RecoveryError("negative_probe_unit_name_collision")
    python_path = ":".join(
        (
            str(RELEASE_ROOT / "13_deployment"),
            str(RELEASE_ROOT / "09_backend" / "src"),
            str(RELEASE_ROOT / "11_database"),
        )
    )
    properties = [
        "--property=Type=oneshot",
        f"--property=User={SERVICE_USER}",
        f"--property=Group={SERVICE_GROUP}",
        f"--property=WorkingDirectory={RELEASE_ROOT}",
        "--property=UMask=0077",
        "--property=NoNewPrivileges=yes",
        "--property=RuntimeMaxSec=30s",
        "--property=TimeoutStartSec=30s",
        "--property=Environment=PYTHONDONTWRITEBYTECODE=1",
        f"--property=Environment=PYTHONPATH={python_path}",
        "--property=Environment=DATABASE_AUTH_CREDENTIAL=school-runtime.json",
        "--property=Environment=DATABASE_KEY_FILE=database-keys.json",
        "--property=IPAddressDeny=any",
    ]
    if with_runtime:
        properties.append(
            f"--property=LoadCredentialEncrypted={RUNTIME_CREDENTIAL_NAME}:{_credential_path(RUNTIME_CREDENTIAL_NAME)}"
        )
    if with_key:
        key_path = key_override or _credential_path(KEY_CREDENTIAL_NAME)
        properties.append(f"--property=LoadCredentialEncrypted={KEY_CREDENTIAL_NAME}:{key_path}")
    if not block_network:
        properties.append("--property=RestrictAddressFamilies=AF_UNIX")
    command = [
        "systemd-run",
        "--quiet",
        "--wait",
        "--pipe",
        "--collect",
        f"--unit={unit_name}",
        *properties,
        str(VENV_ROOT / "bin/python"),
        str(RELEASE_ROOT / "13_deployment" / "school_backend_linux.py"),
        "--repo-root",
        str(RELEASE_ROOT),
        "--preflight-only",
    ]
    result = _command(command, timeout=90, check=False)
    try:
        payload = json.loads(result.stdout.decode("utf-8").strip())
    except (UnicodeError, json.JSONDecodeError):
        raise RecoveryError("negative_preflight_output_invalid") from None
    expected_error = (
        {"ConfigurationError", "EncryptionKeyUnavailable"}
        if kind in {"missing-runtime", "missing-key", "damaged-key"}
        else {"RuntimeError"}
    )
    if (
        result.returncode == 0
        or type(payload) is not dict
        or payload.get("school_backend") != "BLOCKED"
        or payload.get("error_type") not in expected_error
    ):
        raise RecoveryError("negative_preflight_did_not_fail_closed")
    after = _unit_show(unit_name)
    if after.get("LoadState") != "not-found":
        raise RecoveryError("negative_preflight_transient_unit_not_collected")
    return {"case": kind, "safe_failure": True, "unit_collected": True}


def _run_negative_preflights(state: Mapping[str, object]) -> list[dict[str, object]]:
    operation_id = str(state["operation_id"])
    if re.fullmatch(r"[a-f0-9]{32}", operation_id) is None:
        raise RecoveryError("recovery_operation_id_invalid")
    damaged_path = Path(f"/run/psynova-school-demo-recovery-{operation_id[:12]}-damaged-key.cred")
    damaged_payload = b'{"active_version":"school-demo-v1","keys":{"school-demo-v1":"damaged"}}'
    if damaged_path.exists() or damaged_path.is_symlink():
        _require_root_owned(damaged_path, mode=0o600, regular=True)
        if _read_credential(KEY_CREDENTIAL_NAME, damaged_path) != damaged_payload:
            raise RecoveryError("damaged_key_probe_artifact_conflict")
    else:
        encrypted = _encrypt_credential(KEY_CREDENTIAL_NAME, damaged_payload)
        try:
            descriptor = os.open(
                damaged_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            _LINUX_OS.chown(damaged_path, 0, 0)
            os.chmod(damaged_path, 0o600)
        except OSError:
            raise RecoveryError("damaged_key_probe_artifact_creation_failed") from None
        _require_root_owned(damaged_path, mode=0o600, regular=True)
        if _read_credential(KEY_CREDENTIAL_NAME, damaged_path) != damaged_payload:
            raise RecoveryError("damaged_key_probe_artifact_verification_failed")

    try:
        return [
            _run_negative_preflight(
                state,
                kind="missing-runtime",
                with_runtime=False,
                with_key=False,
                block_network=True,
            ),
            _run_negative_preflight(
                state,
                kind="missing-key",
                with_runtime=True,
                with_key=False,
                block_network=True,
            ),
            _run_negative_preflight(
                state,
                kind="damaged-key",
                with_runtime=True,
                with_key=True,
                block_network=True,
                key_override=damaged_path,
            ),
            _run_negative_preflight(
                state,
                kind="database-unavailable",
                with_runtime=True,
                with_key=True,
                block_network=False,
            ),
        ]
    finally:
        if damaged_path.exists():
            _require_root_owned(damaged_path, mode=0o600, regular=True)
            if _read_credential(KEY_CREDENTIAL_NAME, damaged_path) != damaged_payload:
                raise RecoveryError("damaged_key_probe_artifact_changed")
            damaged_path.unlink()


def _mysql_account_record(username: str) -> Mapping[str, str] | None:
    return _account(_database_accounts(_database_snapshot()), username)


def _lock_migrator(username: str) -> None:
    if _ACCOUNT_RE.fullmatch(username) is None:
        raise RecoveryError("migrator_account_name_invalid")
    _mysql(f"ALTER USER '{username}'@'127.0.0.1' ACCOUNT LOCK;")
    account = _mysql_account_record(username)
    if account is None or account.get("locked") != "Y":
        raise RecoveryError("migrator_lock_unverified")
    _verify_migration_grants(_grants_for(username))


def _remove_verified_migration_assets(username: str) -> None:
    account = _mysql_account_record(username)
    if account is None or account.get("locked") != "Y":
        raise RecoveryError("migrator_must_be_locked_before_cleanup")
    raw = _read_credential_candidates(MIGRATION_CREDENTIAL_NAME)
    if raw is not None:
        credential = _decode_migration_payload(
            raw,
            expected_user=username,
        )
        if not credential.get("password"):
            raise RecoveryError("migration_credential_not_authenticated")
        for path in (
            _credential_path(MIGRATION_CREDENTIAL_NAME),
            _credential_staging_path(MIGRATION_CREDENTIAL_NAME),
        ):
            if path.exists():
                _require_root_owned(path, mode=0o600, regular=True, single_link=False)
                path.unlink()
        _sync_directory(CREDSTORE)
    expected = (RELEASE_ROOT / "13_deployment" / "systemd" / _MIGRATION_UNIT).read_bytes()
    for unit_path in (
        RUN_UNITS / _MIGRATION_UNIT,
        _unit_staging_path(_MIGRATION_UNIT, transient=True),
    ):
        if unit_path.exists():
            _require_root_owned(unit_path, mode=0o644, regular=True, single_link=False)
            if unit_path.read_bytes() != expected:
                raise RecoveryError("migration_unit_conflicts_before_cleanup")
            unit_path.unlink()
    _sync_directory(RUN_UNITS)
    _command(["systemctl", "daemon-reload"])


def _verify_no_secret_in_logs(secrets_in_memory: Sequence[str], since: str) -> None:
    output = _text(
        _command(
            [
                "journalctl",
                "--no-pager",
                "--output=cat",
                f"--since={since}",
                "--unit=psynova-school-demo.service",
                "--unit=psynova-school-seed.service",
                "--unit=psynova-school-migrate.service",
                "--unit=mysql.service",
            ],
            timeout=120,
        )
    )
    for value in secrets_in_memory:
        if value and value in output:
            raise RecoveryError("secret_detected_in_service_journal")


def _verify_http_result(verifier: Path, *, verifier_sha256: str) -> dict[str, object]:
    _verify_http_verifier(verifier, verifier_sha256)
    result = _command(
        [
            str(VENV_ROOT / "bin/python"),
            str(verifier),
            "--repo-root",
            str(RELEASE_ROOT),
        ],
        timeout=600,
        check=False,
        env={
            name: value
            for name, value in os.environ.items()
            if not name.startswith(("DB_", "DATABASE_", "MYSQL_", "SMHAI_", "PYTHON", "UV_"))
        }
        | {"PYTHONDONTWRITEBYTECODE": "1"},
    )
    try:
        payload = json.loads(result.stdout.decode("utf-8").strip())
    except (UnicodeError, json.JSONDecodeError):
        raise RecoveryError("http_verifier_output_invalid") from None
    expected = {
        "http_smoke": "PASS",
        "authenticated_accounts": 8,
        "role_boundaries": "PASS",
        "cross_school_subject_denial": "PASS",
        "csrf_enforcement": "PASS",
        "session_after_restart": "PASS",
        "response_bodies_or_credentials_logged": False,
    }
    if result.returncode != 0 or payload != expected:
        raise RecoveryError("real_http_role_and_session_verification_failed")
    return payload


def _verify_backend_listener() -> None:
    if _listener_addresses(BACKEND_PORT) != ["127.0.0.1:8088"]:
        raise RecoveryError("backend_listener_scope_mismatch")
    if _text(_command(["systemctl", "is-active", "psynova-school-demo.service"])) != "active":
        raise RecoveryError("backend_service_not_active")
    try:
        with urllib.request.urlopen("http://127.0.0.1:8088/health/live", timeout=5) as response:
            if response.status != 200:
                raise RecoveryError("backend_loopback_health_failed")
    except (OSError, urllib.error.URLError):
        raise RecoveryError("backend_loopback_health_failed") from None


def _run_resume(*, expected_hash: str, verifier: Path, verifier_hash: str) -> dict[str, object]:
    _verify_executable_snapshot(expected_hash)
    _verify_http_verifier(verifier, verifier_hash)
    host = _base_host_preflight()
    current, pending = _state_candidates()
    state = _effective_state(current, pending)
    database = _database_snapshot()
    _strict_state(host, database, state)
    if pending is not None:
        state = _promote_pending_state(current, pending)
    seed_already_completed = state is not None and _PHASES.index(
        str(state["phase"])
    ) >= _PHASES.index("SEED_PASS_2_VERIFIED")
    if state is None:
        state = _save_state(_new_state(host))
        _emit("checkpoint", checkpoint="INITIALIZED", sequence=state["sequence"])

    _set_phase(str(state["phase"]))
    state = _begin_migrator_identity_repair(state, database)
    if "migrator_repaired_from" in state:
        state = _resume_migrator_credential_repair(state)
    if state["phase"] == "INITIALIZED":
        state = _set_state_phase(state, "CREDENTIALS_STAGING")
    credentials = _ensure_staged_credentials(state)
    if _PHASES.index(str(state["phase"])) < _PHASES.index("CREDENTIALS_STAGED"):
        state = _set_state_phase(state, "CREDENTIALS_STAGED")

    state = _ensure_runtime_account(state, credentials)
    if _PHASES.index(str(state["phase"])) < _PHASES.index("MIGRATOR_AUTH_VERIFIED"):
        state = _ensure_migrator_account(state, credentials)

    phase_index = _PHASES.index(str(state["phase"]))
    if phase_index < _PHASES.index("SYSTEMD_UNITS_INSTALLED"):
        state = _set_state_phase(state, "SYSTEMD_UNITS_INSTALLING")
        _set_phase("SYSTEMD_UNITS_INSTALLING")
        for unit in _PERMANENT_UNITS:
            _install_unit(unit)
        _install_unit(_MIGRATION_UNIT, transient=True)
        _command(["systemctl", "daemon-reload"])
        state = _set_state_phase(state, "SYSTEMD_UNITS_INSTALLED")

    phase_index = _PHASES.index(str(state["phase"]))
    if phase_index < _PHASES.index("CREDENTIAL_PROBE_VERIFIED"):
        _set_phase("CREDENTIAL_PROBE_VERIFIED")
        probe_result = _run_probe()
        state = _set_state_phase(state, "CREDENTIAL_PROBE_VERIFIED")
    else:
        probe_result = {"systemd_credential_injection": "PASS", "reused_checkpoint": True}

    database = _database_snapshot()
    schema_state = _schema_state(database)
    phase_index = _PHASES.index(str(state["phase"]))
    if phase_index < _PHASES.index("SCHEMA_MIGRATED"):
        if schema_state == "INCONSISTENT":
            raise RecoveryError("partial_or_unrecognized_migration_state")
        if schema_state == "EMPTY":
            migration_unit_path = RUN_UNITS / _MIGRATION_UNIT
            if not migration_unit_path.exists():
                _install_unit(_MIGRATION_UNIT, transient=True)
                _command(["systemctl", "daemon-reload"])
            if str(state["phase"]) != "MIGRATION_STARTED":
                state = _set_state_phase(state, "MIGRATION_STARTED")
            _set_phase("MIGRATION_STARTED")
            migration_result = _start_oneshot(_MIGRATION_UNIT, timeout=1800)
            if (
                migration_result.get("migration") != "VERIFIED"
                or migration_result.get("revision") != EXPECTED_REVISION
            ):
                raise RecoveryError("existing_alembic_chain_did_not_reach_target")
        else:
            migration_result = {
                "migration": "RECOVERED_VERIFIED_RESULT",
                "revision": database.get("revision"),
            }
        schema_result = _verify_migrated_schema()
        state = _set_state_phase(state, "SCHEMA_MIGRATED")
    else:
        schema_result = _verify_migrated_schema()
        migration_result = {
            "migration": "VERIFIED",
            "revision": schema_result["revision"],
            "reused_checkpoint": True,
        }

    phase_index = _PHASES.index(str(state["phase"]))
    migrator = _mysql_account_record(str(state["migrator_user"]))
    if migrator is None:
        if phase_index < _PHASES.index("MIGRATOR_LOCKED"):
            raise RecoveryError("migrator_missing_before_lock")
    elif phase_index < _PHASES.index("MIGRATOR_LOCKED") or migrator.get("locked") != "Y":
        _set_phase("MIGRATOR_LOCKED")
        _lock_migrator(str(state["migrator_user"]))
        state = _set_state_phase(state, "MIGRATOR_LOCKED")

    phase_index = _PHASES.index(str(state["phase"]))
    if phase_index < _PHASES.index("MIGRATION_CREDENTIAL_REMOVED"):
        _set_phase("MIGRATION_CREDENTIAL_REMOVED")
        _remove_verified_migration_assets(str(state["migrator_user"]))
        state = _set_state_phase(state, "MIGRATION_CREDENTIAL_REMOVED")

    counts_before_seed = _seed_counts()
    if state["phase"] in {"MIGRATION_CREDENTIAL_REMOVED", "SEED_PASS_1_STARTED"}:
        if state["phase"] == "SEED_PASS_1_STARTED" and counts_before_seed == _SEED_COUNTS:
            first_seed = _last_seed_systemd_result()
            counts_after_first = counts_before_seed
            state = _set_state_phase(state, "SEED_PASS_1_VERIFIED")
        else:
            if state["phase"] != "SEED_PASS_1_STARTED":
                state = _set_state_phase(state, "SEED_PASS_1_STARTED")
            _set_phase("SEED_PASS_1_STARTED")
            first_seed = _seed_systemd_unit()
            counts_after_first = _seed_counts()
            if counts_after_first != _SEED_COUNTS:
                raise RecoveryError("first_seed_count_mismatch")
            state = _set_state_phase(state, "SEED_PASS_1_VERIFIED")
    else:
        counts_after_first = _seed_counts()
        if counts_after_first != _SEED_COUNTS:
            raise RecoveryError("first_seed_checkpoint_missing_data")
        first_seed = (
            _last_seed_systemd_result()
            if state["phase"] == "SEED_PASS_1_VERIFIED"
            else {"seed": "VERIFIED", "reused_checkpoint": True}
        )

    if state["phase"] in {"SEED_PASS_1_VERIFIED", "SEED_PASS_2_STARTED"}:
        if state["phase"] != "SEED_PASS_2_STARTED":
            state = _set_state_phase(state, "SEED_PASS_2_STARTED")
        _set_phase("SEED_PASS_2_STARTED")
        second_seed = _seed_systemd_unit()
        counts_after_second = _seed_counts()
        if counts_after_second != _SEED_COUNTS:
            raise RecoveryError("second_seed_count_mismatch")
        state = _set_state_phase(state, "SEED_PASS_2_VERIFIED")
    else:
        counts_after_second = counts_after_first
        second_seed = {"seed": "VERIFIED", "reused_checkpoint": True}

    phase_index = _PHASES.index(str(state["phase"]))
    if phase_index < _PHASES.index("NEGATIVE_PREFLIGHTS_VERIFIED"):
        _set_phase("NEGATIVE_PREFLIGHTS_VERIFIED")
        negative_results = _run_negative_preflights(state)
        state = _set_state_phase(state, "NEGATIVE_PREFLIGHTS_VERIFIED")
    else:
        negative_results = [
            {"case": "missing-runtime", "safe_failure": True, "reused_checkpoint": True},
            {"case": "missing-key", "safe_failure": True, "reused_checkpoint": True},
            {"case": "damaged-key", "safe_failure": True, "reused_checkpoint": True},
            {"case": "database-unavailable", "safe_failure": True, "reused_checkpoint": True},
        ]

    if _PHASES.index(str(state["phase"])) < _PHASES.index("BACKEND_STARTED"):
        if state["phase"] != "BACKEND_STARTING":
            state = _set_state_phase(state, "BACKEND_STARTING")
        _set_phase("BACKEND_STARTING")
        service_state = _unit_show("psynova-school-demo.service")
        if service_state.get("ActiveState") != "active":
            _command(["systemctl", "start", "psynova-school-demo.service"], timeout=180)
        _verify_backend_listener()
        state = _set_state_phase(state, "BACKEND_STARTED")
    else:
        backend_state = _unit_show("psynova-school-demo.service")
        if backend_state.get("ActiveState") != "active":
            _command(["systemctl", "start", "psynova-school-demo.service"], timeout=180)
        _verify_backend_listener()

    if _PHASES.index(str(state["phase"])) < _PHASES.index("HTTP_VERIFIED"):
        if state["phase"] != "HTTP_STARTED":
            state = _set_state_phase(state, "HTTP_STARTED")
        _set_phase("HTTP_STARTED")
        http_result = _verify_http_result(verifier, verifier_sha256=verifier_hash)
        _verify_backend_listener()
        state = _set_state_phase(state, "HTTP_VERIFIED")
    else:
        http_result = {
            "http_smoke": "PASS",
            "authenticated_accounts": 8,
            "role_boundaries": "PASS",
            "cross_school_subject_denial": "PASS",
            "csrf_enforcement": "PASS",
            "session_after_restart": "PASS",
            "response_bodies_or_credentials_logged": False,
            "reused_checkpoint": True,
        }

    runtime_raw = _read_credential(
        RUNTIME_CREDENTIAL_NAME, _credential_path(RUNTIME_CREDENTIAL_NAME)
    )
    runtime = _decode_runtime_payload(runtime_raw, expected_user=RUNTIME_USER)
    key_text = _validate_key_payload(
        _read_credential(KEY_CREDENTIAL_NAME, _credential_path(KEY_CREDENTIAL_NAME))
    )
    seed_credentials = _validate_seed_payload(
        _read_credential(SEED_CREDENTIAL_NAME, _credential_path(SEED_CREDENTIAL_NAME))
    )
    secrets_to_scan = [
        runtime["password"],
        runtime["csrf"],
        credentials["migrator_password"],
        key_text,
        *(value for values in seed_credentials.values() for value in values),
    ]
    _verify_no_secret_in_logs(secrets_to_scan, str(state["created_at"]))
    _verify_backend_listener()
    final_counts = _seed_counts()
    if final_counts != _SEED_COUNTS:
        raise RecoveryError("final_synthetic_counts_mismatch")
    seed_invocations = _count_seed_systemd_results(str(state["created_at"]))
    if seed_invocations < 2 and not seed_already_completed:
        raise RecoveryError("seed_service_invocations_not_verified")

    return {
        "recovery": "VERIFIED",
        "source_revision": EXPECTED_SOURCE_REVISION,
        "database": DATABASE_NAME,
        "revision": EXPECTED_REVISION,
        "schema_tables": schema_result.get("tables"),
        "schema_constraints": {
            "foreign_keys": schema_result.get("foreign_keys"),
            "checks": schema_result.get("checks"),
            "unique_constraints": schema_result.get("unique_constraints"),
        },
        "runtime_account": RUNTIME_USER,
        "runtime_privileges": ["SELECT", "INSERT", "UPDATE", "DELETE"],
        "migrator_account": str(state["migrator_user"]),
        "migrator_state": "ACCOUNT_LOCKED_CREDENTIAL_REMOVED_AFTER_SCHEMA_VERIFICATION",
        "credential_probe": probe_result,
        "seed": {
            "logical_systemd_passes_verified": 2,
            "service_invocations_in_journal": seed_invocations,
            "idempotent_replay_verified": True,
            "first": first_seed,
            "second": second_seed,
            "before": counts_before_seed,
            "after_first": counts_after_first,
            "after_second": counts_after_second,
            "final": final_counts,
        },
        "negative_preflights": negative_results,
        "http": http_result,
        "service": "psynova-school-demo.service active; not enabled",
        "listener": "127.0.0.1:8088",
        "nginx": "unchanged_inactive",
        "mysql_listener": "127.0.0.1:3306",
        "public_ports_opened": False,
        "secrets_in_logs": False,
        "checkpoint": {"phase": state["phase"], "sequence": state["sequence"]},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--inspect", action="store_true", help="read-only state report")
    modes.add_argument("--dry-run", action="store_true", help="read-only recovery plan")
    modes.add_argument("--resume", action="store_true", help="perform the controlled recovery")
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--http-verifier", type=Path)
    parser.add_argument("--http-verifier-sha256")
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    try:
        _verify_executable_snapshot(args.expected_sha256)
        _acquire_recovery_lock()
        if args.inspect or args.dry_run:
            result = _make_plan(
                args.expected_sha256,
                verifier=args.http_verifier,
                verifier_hash=args.http_verifier_sha256,
            )
            if args.inspect:
                result = {"inspect": "PASS", **result}
            else:
                result = {"dry_run": "PASS", **result}
            print(json.dumps(result, sort_keys=True, separators=(",", ":")))
            return 0
        if args.http_verifier is None or args.http_verifier_sha256 is None:
            raise RecoveryError("http_verifier_identity_required_for_resume")
        _verify_http_verifier(args.http_verifier, args.http_verifier_sha256)
        result = _run_resume(
            expected_hash=args.expected_sha256,
            verifier=args.http_verifier,
            verifier_hash=args.http_verifier_sha256,
        )
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except RecoveryError as exc:
        print(
            json.dumps(
                {
                    "recovery": (
                        "DECISION_REQUIRED"
                        if str(exc) in _DECISION_REQUIRED_CODES
                        or "state" in str(exc)
                        or "unknown" in str(exc)
                        else "BLOCKED"
                    ),
                    "phase": _CURRENT_PHASE,
                    "error_code": str(exc),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 2
    except Exception as exc:  # noqa: BLE001 - suppress all OS, SQL, and credential details.
        print(
            json.dumps(
                {
                    "recovery": "BLOCKED",
                    "phase": _CURRENT_PHASE,
                    "error_type": type(exc).__name__,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
