"""Resume the existing isolated synthetic school MySQL workspace safely.

This entrypoint never initializes, migrates, seeds, changes credentials, or
changes ACLs. It either verifies the exact running guardian or starts the
already initialized data directory once and records recoverable process state.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from prepare_school_runtime import PreparationError, validate_marker, verify_process
from school_schema import CURRENT_SCHOOL_REVISION, SCHOOL_REVISION_CHAIN

DEFAULT_WORKSPACE = Path(r"D:\Projects\.StudentMentalHealthAI-school-workspace-20261011")
DEFAULT_REPO = Path(__file__).resolve().parents[1]
DATABASE = "smhai_school_demo"
HOST = "127.0.0.1"
PORT = 3308
MIN_DATABASE_PORT = 3308
MAX_DATABASE_PORT = 3399
MAX_READINESS_SECONDS = 60
RESTORE_STATE_SCHEMA = "psynova.synthetic-restore-target.v1"
RESTORE_VERIFIED_PHASE = "DATA_KEYS_RUNTIME_VERIFIED_REQUIRES_BROWSER"
_RESTORE_TARGET_NAME = re.compile(
    r"^\.StudentMentalHealthAI-school-restore-\d{8}-[a-z0-9][a-z0-9-]{0,31}$",
    re.IGNORECASE,
)
_FRESH_TARGET_NAME = re.compile(
    r"^\.StudentMentalHealthAI-school-install-\d{8}-[a-z0-9][a-z0-9-]{0,31}$",
    re.IGNORECASE,
)
_WORKSPACE_ID = re.compile(r"^[a-f0-9]{32}$")


class ResumeError(RuntimeError):
    """Safe, non-secret failure for resuming the owned workspace."""


def _validate_expected_port(expected_port: int) -> int:
    if (
        type(expected_port) is not int
        or not MIN_DATABASE_PORT <= expected_port <= MAX_DATABASE_PORT
    ):
        raise ResumeError(
            f"Expected database port must be within {MIN_DATABASE_PORT}-{MAX_DATABASE_PORT}"
        )
    return expected_port


def guardian_arguments(
    executable: Path, workspace: Path, data_directory: Path, port: int
) -> list[str]:
    """Build the immutable, non-destructive server argv (no initialize/reset)."""
    return [
        str(executable),
        "--no-defaults",
        f"--datadir={data_directory}",
        f"--port={port}",
        "--bind-address=127.0.0.1",
        "--mysqlx=0",
        f"--log-error={workspace / 'mysql.private.log'}",
        f"--pid-file={workspace / 'mysql.pid'}",
    ]


def guardian_environment(source: dict[str, str]) -> dict[str, str]:
    """Strip inherited DB credentials/config from the guardian environment."""
    return {
        key: value
        for key, value in source.items()
        if not (
            key.upper().startswith("DB_")
            or key.upper().startswith("SMHAI_")
            or key.upper() in {"DATABASE_URL", "DATABASE_KEY_FILE", "MYSQL_PWD"}
        )
    }


def _reject_reparse_path(path: Path) -> None:
    """Reject a reparse point in any existing component without following it."""
    if not path.is_absolute() or ".." in path.parts:
        raise ResumeError("Absolute normalized workspace paths are required")
    cursor = Path(path.anchor)
    for part in path.parts[1:]:
        cursor = cursor / part
        try:
            info = cursor.lstat()
        except FileNotFoundError:
            raise ResumeError("Owned workspace path is incomplete") from None
        attributes = getattr(info, "st_file_attributes", 0)
        if attributes & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
            raise ResumeError("Reparse points are not allowed in the workspace path")


def validate_existing_workspace(
    workspace: Path,
    repo: Path,
    *,
    expected_workspace: Path = DEFAULT_WORKSPACE,
    expected_port: int = PORT,
) -> dict[str, Any]:
    """Validate the existing marker, protected paths, vendor binary and datadir."""
    _validate_expected_port(expected_port)
    if not workspace.is_absolute():
        raise ResumeError("Absolute external workspace required")
    _reject_reparse_path(workspace)
    root = workspace.resolve(strict=True)
    repository = repo.resolve(strict=True)
    if root == repository or root.is_relative_to(repository):
        raise ResumeError("Workspace must remain outside the repository")
    if root != expected_workspace.resolve(strict=False):
        raise ResumeError("Only the registered school workspace can be resumed")

    marker_path = root / "workspace.json"
    _reject_reparse_path(marker_path)
    try:
        marker = validate_marker(root, repository)
    except (PreparationError, OSError, ValueError, TypeError, json.JSONDecodeError):
        raise ResumeError("Owned synthetic workspace marker is invalid") from None
    if marker.get("port") != expected_port or marker.get("database") != DATABASE:
        raise ResumeError("Workspace target does not match the registered school database")

    data_directory = Path(marker.get("data_directory", ""))
    executable = Path(marker.get("executable", ""))
    if not data_directory.is_absolute() or not executable.is_absolute():
        raise ResumeError("Marker paths must be absolute")
    _reject_reparse_path(data_directory)
    _reject_reparse_path(executable)
    if data_directory.resolve(strict=True) != (root / "mysql-data").resolve(strict=True):
        raise ResumeError("Marker data directory does not match the owned workspace")
    if executable.name.casefold() != "mysqld.exe" or not executable.is_file():
        raise ResumeError("Registered vendor MySQL server executable is unavailable")

    # These are files/directories created by mysqld --initialize. They are
    # existence checks only; no database file contents are opened or changed.
    if not (data_directory / "auto.cnf").is_file() or not (data_directory / "ibdata1").is_file():
        raise ResumeError("Initialized MySQL data directory is incomplete")
    if not (data_directory / "mysql").is_dir():
        raise ResumeError("Initialized MySQL system data is unavailable")
    for name in ("mysql.private.log", "mysql.pid"):
        try:
            (root / name).lstat()
        except FileNotFoundError:
            continue
        _reject_reparse_path(root / name)
    return marker


def _paths_overlap(first: Path, second: Path) -> bool:
    first_path = first.resolve(strict=False)
    second_path = second.resolve(strict=False)
    return (
        first_path == second_path
        or first_path.is_relative_to(second_path)
        or second_path.is_relative_to(first_path)
    )


def validate_restored_workspace(
    workspace: Path,
    repo: Path,
    *,
    source_workspace: Path,
    expected_port: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind an isolated restored target to the original source and restore proof."""
    _validate_expected_port(expected_port)
    if expected_port == PORT:
        raise ResumeError("A restored target must use a separate database port")

    target_path = Path(workspace)
    source_path = Path(source_workspace)
    repository = Path(repo)
    _reject_reparse_path(target_path)
    _reject_reparse_path(source_path)
    target_root = target_path.resolve(strict=True)
    source_root = source_path.resolve(strict=True)
    repo_root = repository.resolve(strict=True)
    if (
        target_root.parent != source_root.parent
        or not _RESTORE_TARGET_NAME.fullmatch(target_root.name)
        or _paths_overlap(target_root, source_root)
        or _paths_overlap(target_root, repo_root)
        or _paths_overlap(source_root, repo_root)
    ):
        raise ResumeError("Restored workspace path is not isolated")

    source_marker = validate_existing_workspace(
        source_root,
        repo_root,
        expected_workspace=source_root,
        expected_port=PORT,
    )
    target_marker = validate_existing_workspace(
        target_root,
        repo_root,
        expected_workspace=target_root,
        expected_port=expected_port,
    )
    source_id = source_marker.get("workspace_id")
    target_id = target_marker.get("workspace_id")
    if (
        not isinstance(source_id, str)
        or not source_id
        or not isinstance(target_id, str)
        or not target_id
        or source_id == target_id
        or source_marker.get("host") != HOST
        or target_marker.get("host") != HOST
        or source_marker.get("synthetic_only") is not True
        or target_marker.get("synthetic_only") is not True
        or source_marker.get("data_directory") == target_marker.get("data_directory")
    ):
        raise ResumeError("Restore source and target identities do not match")

    restore_state_path = target_root / "restore-state.json"
    _reject_reparse_path(restore_state_path)
    try:
        restore_state = json.loads(restore_state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ResumeError("Verified restore state is unavailable") from None
    if not isinstance(restore_state, dict):
        raise ResumeError("Verified restore state is invalid")
    try:
        recorded_workspace = Path(restore_state.get("workspace", ""))
        recorded_data_directory = Path(restore_state.get("data_directory", ""))
    except (TypeError, ValueError):
        raise ResumeError("Verified restore paths are invalid") from None
    if (
        restore_state.get("schema_version") != RESTORE_STATE_SCHEMA
        or restore_state.get("phase") != RESTORE_VERIFIED_PHASE
        or restore_state.get("synthetic_only") is not True
        or restore_state.get("host") != HOST
        or restore_state.get("database") != DATABASE
        or type(restore_state.get("port")) is not int
        or restore_state.get("port") != expected_port
        or restore_state.get("workspace_id") != target_id
        or restore_state.get("source_workspace_id") != source_id
        or not recorded_workspace.is_absolute()
        or recorded_workspace.resolve(strict=False) != target_root
        or not recorded_data_directory.is_absolute()
        or recorded_data_directory.resolve(strict=False)
        != Path(target_marker["data_directory"]).resolve(strict=True)
        or restore_state.get("snapshot_revision") not in SCHOOL_REVISION_CHAIN
        or restore_state.get("runtime_revision") != CURRENT_SCHOOL_REVISION
    ):
        raise ResumeError("Restore evidence does not match the isolated target")
    return source_marker, target_marker


def validate_restored_install_workspace(
    workspace: Path,
    repo: Path,
    *,
    source_workspace: Path,
    expected_port: int,
    source_port: int,
    expected_workspace_id: str,
    expected_source_workspace_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate an explicitly pinned restored install before resuming its DB.

    Unlike the legacy restore mode, this supports a restored target whose
    directory uses the install naming scheme. Both source and target remain
    explicit and are bound by workspace IDs, ports, restore-state, and data
    directories; this does not trust the target filename or marker alone.
    """
    _validate_expected_port(expected_port)
    _validate_expected_port(source_port)
    if (
        expected_port == source_port
        or expected_port == PORT
        or not isinstance(expected_workspace_id, str)
        or not _WORKSPACE_ID.fullmatch(expected_workspace_id)
        or not isinstance(expected_source_workspace_id, str)
        or not _WORKSPACE_ID.fullmatch(expected_source_workspace_id)
        or expected_workspace_id == expected_source_workspace_id
    ):
        raise ResumeError("Restored install identity and distinct ports are required")

    target_path = Path(workspace)
    source_path = Path(source_workspace)
    repository = Path(repo)
    _reject_reparse_path(target_path)
    _reject_reparse_path(source_path)
    target_root = target_path.resolve(strict=True)
    source_root = source_path.resolve(strict=True)
    repo_root = repository.resolve(strict=True)
    if (
        target_root == source_root
        or target_root.parent != source_root.parent
        or _paths_overlap(target_root, source_root)
        or _paths_overlap(target_root, repo_root)
        or _paths_overlap(source_root, repo_root)
    ):
        raise ResumeError("Restored install source and target paths are not isolated")

    target_marker = _validate_install_target_identity(
        target_root,
        repo_root,
        expected_workspace=target_root,
        expected_port=expected_port,
        expected_workspace_id=expected_workspace_id,
    )
    try:
        source_marker = validate_existing_workspace(
            source_root,
            repo_root,
            expected_workspace=source_root,
            expected_port=source_port,
        )
    except (PreparationError, OSError, ValueError, TypeError, json.JSONDecodeError):
        raise ResumeError("Explicit restore source marker is invalid") from None

    source_data = Path(source_marker.get("data_directory", ""))
    target_data = Path(target_marker.get("data_directory", ""))
    if (
        source_marker.get("workspace_id") != expected_source_workspace_id
        or source_marker.get("host") != HOST
        or target_marker.get("workspace_id") != expected_workspace_id
        or target_marker.get("host") != HOST
        or source_marker.get("database") != DATABASE
        or target_marker.get("database") != DATABASE
        or source_marker.get("synthetic_only") is not True
        or target_marker.get("synthetic_only") is not True
        or source_data.resolve(strict=True) == target_data.resolve(strict=True)
        or _paths_overlap(source_data, target_data)
    ):
        raise ResumeError("Restored install source and target identities do not match")

    restore_state_path = target_root / "restore-state.json"
    _reject_reparse_path(restore_state_path)

    def unique_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise ResumeError("Restore state contains duplicate fields")
            value[key] = item
        return value

    try:
        restore_state = json.loads(
            restore_state_path.read_text(encoding="utf-8"),
            object_pairs_hook=unique_pairs,
        )
    except ResumeError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        raise ResumeError("Restored install proof is unavailable") from None
    if not isinstance(restore_state, dict):
        raise ResumeError("Restored install proof is invalid")
    try:
        recorded_workspace = Path(restore_state.get("workspace", ""))
        recorded_data_directory = Path(restore_state.get("data_directory", ""))
    except (TypeError, ValueError):
        raise ResumeError("Restored install proof paths are invalid") from None
    if (
        restore_state.get("schema_version") != RESTORE_STATE_SCHEMA
        or restore_state.get("phase") != RESTORE_VERIFIED_PHASE
        or restore_state.get("synthetic_only") is not True
        or restore_state.get("host") != HOST
        or restore_state.get("database") != DATABASE
        or type(restore_state.get("port")) is not int
        or restore_state.get("port") != expected_port
        or restore_state.get("workspace_id") != expected_workspace_id
        or restore_state.get("source_workspace_id") != expected_source_workspace_id
        or not recorded_workspace.is_absolute()
        or recorded_workspace.resolve(strict=False) != target_root
        or not recorded_data_directory.is_absolute()
        or recorded_data_directory.resolve(strict=False) != target_data.resolve(strict=True)
        or restore_state.get("snapshot_revision") not in SCHOOL_REVISION_CHAIN
        or restore_state.get("runtime_revision") != CURRENT_SCHOOL_REVISION
    ):
        raise ResumeError("Restored install evidence does not match pinned source and target")
    return source_marker, target_marker


def _validate_install_target_identity(
    workspace: Path,
    repo: Path,
    *,
    expected_workspace: Path,
    expected_port: int,
    expected_workspace_id: str,
) -> dict[str, Any]:
    """Pin an install target to its operator-supplied path and ID.

    The JSON marker is not a cryptographic attestation. The explicit path and
    ID bind this invocation to one existing target; later DPAPI/process/database
    checks provide runtime evidence.
    """
    _validate_expected_port(expected_port)
    if not isinstance(expected_workspace_id, str) or not _WORKSPACE_ID.fullmatch(
        expected_workspace_id
    ):
        raise ResumeError("Explicit install workspace ID is required")
    target = Path(workspace)
    if not target.is_absolute():
        raise ResumeError("Absolute install workspace path required")
    _reject_reparse_path(target)
    root = target.resolve(strict=True)
    repository = Path(repo).resolve(strict=True)
    if (
        root == repository
        or root.is_relative_to(repository)
        or root == Path(DEFAULT_WORKSPACE).resolve(strict=False)
        or not _FRESH_TARGET_NAME.fullmatch(root.name)
        or root != Path(expected_workspace).resolve(strict=False)
    ):
        raise ResumeError("Target path is not an explicitly named install workspace")
    marker = validate_existing_workspace(
        root, repository, expected_workspace=root, expected_port=expected_port
    )
    if (
        marker.get("workspace_id") != expected_workspace_id
        or marker.get("state") != "READY_FOR_MIGRATION"
        or marker.get("host") != HOST
        or marker.get("synthetic_only") is not True
    ):
        raise ResumeError("Install workspace marker does not match the expected target")
    return marker


def _workspace_artifacts(workspace: Path) -> dict[str, Path]:
    names = (
        "database.private.dpapi",
        "database-keys.private.dpapi",
        "runtime.private.dpapi",
        "school-auth.private.dpapi",
        "runtime-ready.json",
        "restore-state.json",
    )
    artifacts: dict[str, Path] = {}
    for name in names:
        entry = workspace / name
        try:
            entry.lstat()
        except FileNotFoundError:
            continue
        _reject_reparse_path(entry)
        if not entry.is_file():
            raise ResumeError("Workspace settings artifact is invalid")
        artifacts[name] = entry
    return artifacts


def validate_fresh_workspace(
    workspace: Path,
    repo: Path,
    *,
    expected_workspace: Path,
    expected_port: int,
    expected_workspace_id: str,
) -> dict[str, Any]:
    """Validate an install target before runtime provisioning has occurred."""
    marker = _validate_install_target_identity(
        workspace,
        repo,
        expected_workspace=expected_workspace,
        expected_port=expected_port,
        expected_workspace_id=expected_workspace_id,
    )
    artifacts = _workspace_artifacts(Path(workspace))
    if any(
        name in artifacts
        for name in (
            "runtime.private.dpapi",
            "school-auth.private.dpapi",
            "runtime-ready.json",
            "restore-state.json",
        )
    ):
        raise ResumeError("Fresh target contains runtime or restore state")
    for name in ("database.private.dpapi", "database-keys.private.dpapi"):
        if name not in artifacts:
            raise ResumeError("Fresh workspace DPAPI settings are incomplete")
    return marker


def validate_prepared_install_workspace(
    workspace: Path,
    repo: Path,
    *,
    expected_workspace: Path,
    expected_port: int,
    expected_workspace_id: str,
) -> dict[str, Any]:
    """Validate a completely runtime-prepared install target, never a partial one."""
    marker = _validate_install_target_identity(
        workspace,
        repo,
        expected_workspace=expected_workspace,
        expected_port=expected_port,
        expected_workspace_id=expected_workspace_id,
    )
    artifacts = _workspace_artifacts(Path(workspace))
    required = {
        "database.private.dpapi",
        "database-keys.private.dpapi",
        "runtime.private.dpapi",
        "school-auth.private.dpapi",
        "runtime-ready.json",
    }
    if "restore-state.json" in artifacts or not required.issubset(artifacts):
        raise ResumeError("Prepared install runtime artifacts are incomplete or misclassified")
    try:
        ready = json.loads(artifacts["runtime-ready.json"].read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ResumeError("Prepared install readiness marker is invalid") from None
    if (
        not isinstance(ready, dict)
        or ready.get("workspace_id") != marker["workspace_id"]
        or ready.get("state") != "VERIFIED"
        or ready.get("database") != DATABASE
        or type(ready.get("port")) is not int
        or ready.get("port") != expected_port
    ):
        raise ResumeError("Prepared install readiness marker does not match target")
    return marker


def atomic_write_marker(workspace: Path, marker: dict[str, Any]) -> None:
    """Atomically replace workspace.json while preserving all caller fields."""
    target = workspace / "workspace.json"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=".workspace.",
            suffix=".tmp",
            dir=workspace,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(marker, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except OSError:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise ResumeError(
            "Workspace marker update failed; preserve all files for recovery"
        ) from None


@contextmanager
def workspace_lock(workspace: Path) -> Iterator[None]:
    """Hold a per-workspace Windows byte lock; the OS releases it on exit/crash."""
    if os.name != "nt":
        raise ResumeError("Workspace resume requires Windows")
    import msvcrt

    lock_path = workspace / ".resume.lock"
    try:
        lock_path.lstat()
    except FileNotFoundError:
        pass
    else:
        _reject_reparse_path(lock_path)
    with lock_path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise ResumeError("Another workspace resume operation is active") from None
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def _utc_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return ""
    if parsed.tzinfo is None:
        return ""
    return parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


class ResumeOperations:
    """Windows effects isolated behind methods so tests never touch live services."""

    @staticmethod
    def is_supported_platform() -> bool:
        return os.name == "nt"

    def verify_acl(self, workspace: Path) -> None:
        if os.name != "nt":
            raise ResumeError("Workspace resume requires Windows")
        script = r"""
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$acl = Get-Acl -LiteralPath $env:PSYNOVA_RESUME_WORKSPACE
$rules = @($acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))
$unexpected = @(
    $rules | Where-Object {
        $_.IdentityReference.Value -ne $sid -or $_.IsInherited -or
        $_.AccessControlType -ne 'Allow'
    }
)
$fullControl = [System.Security.AccessControl.FileSystemRights]::FullControl
$hasFullControl = ($rules[0].FileSystemRights -band $fullControl) -eq $fullControl
$private = $acl.AreAccessRulesProtected -and $rules.Count -eq 1 -and
    $unexpected.Count -eq 0 -and $hasFullControl
if ($private) { 'PRIVATE' } else { 'NOT_PRIVATE' }
"""
        environment = dict(os.environ, PSYNOVA_RESUME_WORKSPACE=str(workspace))
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-Command", script],
            env=environment,
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        if result.stdout.strip() != "PRIVATE":
            raise ResumeError("Workspace ACL is not current-user-only")

    def inspect_process(self, pid: int) -> dict[str, Any] | None:
        script = r"""
$p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $env:PSYNOVA_RESUME_PID)
if ($null -eq $p) { 'null'; exit 0 }
@{
    ProcessId = $p.ProcessId
    ExecutablePath = $p.ExecutablePath
    CommandLine = $p.CommandLine
    CreationUtc = $p.CreationDate.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffffffZ')
} | ConvertTo-Json -Compress
"""
        environment = dict(os.environ, PSYNOVA_RESUME_PID=str(pid))
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-Command", script],
            env=environment,
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        value = json.loads(result.stdout or "null")
        return value if isinstance(value, dict) else None

    @staticmethod
    def process_creation_time(process) -> str:
        """Read creation time from the Popen handle, immune to PID reuse."""
        if os.name != "nt":
            raise ResumeError("Workspace resume requires Windows")
        from ctypes import wintypes

        class FileTime(ctypes.Structure):
            _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

        created = FileTime()
        exited = FileTime()
        kernel = FileTime()
        user = FileTime()
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_times = kernel32.GetProcessTimes
        get_times.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(FileTime),
            ctypes.POINTER(FileTime),
            ctypes.POINTER(FileTime),
            ctypes.POINTER(FileTime),
        ]
        get_times.restype = wintypes.BOOL
        if not get_times(
            wintypes.HANDLE(process._handle),
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            raise ResumeError("Guardian creation time could not be verified")
        filetime_ticks = (created.high << 32) | created.low
        unix_microseconds = filetime_ticks // 10 - 11644473600000000
        timestamp = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
            microseconds=unix_microseconds
        )
        return timestamp.isoformat(timespec="microseconds").replace("+00:00", "Z")

    def listeners(self, port: int) -> list[dict[str, Any]]:
        script = r"""
$values = @(
    Get-NetTCPConnection -State Listen `
        -LocalPort $env:PSYNOVA_RESUME_PORT `
        -ErrorAction SilentlyContinue |
        Select-Object OwningProcess,LocalAddress,LocalPort
)
$values | ConvertTo-Json -Depth 3 -Compress
"""
        environment = dict(os.environ, PSYNOVA_RESUME_PORT=str(port))
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-Command", script],
            env=environment,
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        value = json.loads(result.stdout or "[]")
        if value is None:
            return []
        return value if isinstance(value, list) else [value]

    @staticmethod
    def port_is_free(port: int) -> bool:
        try:
            with socket.create_connection((HOST, port), timeout=0.3):
                return False
        except OSError:
            return True

    @staticmethod
    def verify_running_process(marker: dict[str, Any]) -> None:
        try:
            verify_process(marker)
        except (PreparationError, OSError, subprocess.SubprocessError, ValueError, KeyError):
            raise ResumeError("Recorded guardian or listener verification failed") from None

    @staticmethod
    def load_runtime(workspace: Path, repo: Path) -> dict[str, Any]:
        for entry in (
            repo / "11_database" / ".venv" / "Lib" / "site-packages",
            repo / "11_database",
            repo / "09_backend" / "src",
        ):
            path = str(entry)
            if path not in sys.path:
                sys.path.insert(0, path)
        from school_backend import load_runtime

        try:
            return load_runtime(workspace, repo)
        except Exception as exc:  # noqa: BLE001 - redact credential-bearing driver exceptions.
            # Never surface driver/SQL exceptions; they may contain connection data.
            raise ResumeError(f"Runtime validation failed ({type(exc).__name__})") from None

    @staticmethod
    def verify_fresh_dpapi(workspace: Path, port: int) -> None:
        """Unseal existing current-user settings without exposing values."""
        try:
            import base64

            from private_settings import read_private

            database = read_private(workspace / "database.private.dpapi")
            keys = read_private(workspace / "database-keys.private.dpapi")
            root_password = database.get("root_password")
            active = keys.get("active_version")
            key_values = keys.get("keys")
            if (
                not isinstance(root_password, str)
                or not re.fullmatch(r"[a-f0-9]{64}", root_password)
                or database.get("DB_NAME") != DATABASE
                or database.get("DB_HOST") != HOST
                or str(database.get("DB_PORT")) != str(port)
                or not isinstance(active, str)
                or not isinstance(key_values, dict)
                or not isinstance(key_values.get(active), str)
                or not key_values[active]
            ):
                raise ValueError("settings mismatch")
            if len(base64.b64decode(key_values[active], altchars=b"-_", validate=True)) != 32:
                raise ValueError("key length mismatch")
        except Exception as exc:  # noqa: BLE001 - redact DPAPI/parser details.
            raise ResumeError(
                f"Fresh workspace DPAPI validation failed ({type(exc).__name__})"
            ) from None

    @staticmethod
    def verify_fresh_database(workspace: Path, port: int, repo: Path) -> None:
        """Read-only verification of the already migrated fresh target."""
        for entry in (
            repo / "11_database" / ".venv" / "Lib" / "site-packages",
            repo / "11_database",
        ):
            if str(entry) not in sys.path:
                sys.path.insert(0, str(entry))
        try:
            import pymysql
            from private_settings import read_private
            from school_schema import CURRENT_SCHOOL_REVISION

            settings = read_private(workspace / "database.private.dpapi")
            connection = pymysql.connect(
                host=HOST,
                port=port,
                user="root",
                password=settings["root_password"],
                database=DATABASE,
                connect_timeout=5,
                read_timeout=5,
                write_timeout=5,
                autocommit=True,
            )
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT @@port, @@datadir, DATABASE()")
                    actual_port, actual_directory, database = cursor.fetchone()
                    if (
                        actual_port != port
                        or Path(actual_directory).resolve(strict=True)
                        != (workspace / "mysql-data").resolve(strict=True)
                        or database != DATABASE
                    ):
                        raise ResumeError("Connected database identity does not match target")
                    cursor.execute("SELECT version_num FROM database_alembic_version")
                    if cursor.fetchall() != ((CURRENT_SCHOOL_REVISION,),):
                        raise ResumeError("Fresh database migration version is not current")
            finally:
                connection.close()
        except ResumeError:
            raise
        except Exception as exc:  # noqa: BLE001 - redact DB details and credentials.
            raise ResumeError(
                f"Fresh database validation failed ({type(exc).__name__})"
            ) from None

    @staticmethod
    def start_guardian(executable: Path, workspace: Path, data_directory: Path, port: int):
        if os.name != "nt":
            raise ResumeError("Workspace resume requires Windows")
        environment = guardian_environment(dict(os.environ))
        argv = guardian_arguments(executable, workspace, data_directory, port)
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        try:
            return subprocess.Popen(
                argv,
                cwd=workspace,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                startupinfo=startup,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                close_fds=True,
                shell=False,
            )
        except OSError as exc:
            raise ResumeError(f"Guardian launch failed ({type(exc).__name__})") from None

    @staticmethod
    def wait_ready(process, port: int, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return False
            try:
                with socket.create_connection((HOST, port), timeout=0.3):
                    return True
            except OSError:
                time.sleep(min(0.3, max(0.0, deadline - time.monotonic())))
        return False


def _marker_creation_time(marker: dict[str, Any]) -> str:
    return _utc_timestamp(str(marker.get("parent_creation_time", "")))


def _command_arguments(command: str) -> list[str]:
    """Use Windows argument parsing, preserving spaces inside quoted paths."""
    from ctypes import wintypes

    count = ctypes.c_int()
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    parse = shell32.CommandLineToArgvW
    parse.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    parse.restype = ctypes.POINTER(wintypes.LPWSTR)
    values = parse(command, ctypes.byref(count))
    if not values:
        raise ResumeError("Guardian arguments could not be parsed")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    try:
        return [values[index] for index in range(count.value)]
    finally:
        kernel32.LocalFree(ctypes.cast(values, wintypes.HLOCAL))


def _process_matches(process: dict[str, Any], marker: dict[str, Any]) -> bool:
    try:
        if int(process.get("ProcessId")) != int(marker.get("parent_pid")):
            return False
        actual_exe = Path(str(process.get("ExecutablePath", "")))
        expected_exe = Path(str(marker.get("executable", "")))
        if (
            not actual_exe.is_absolute()
            or actual_exe.resolve(strict=True) != expected_exe.resolve(strict=True)
        ):
            return False
        expected_time = _marker_creation_time(marker)
        if not expected_time or _utc_timestamp(str(process.get("CreationUtc", ""))) != expected_time:
            return False
        actual = _command_arguments(str(process.get("CommandLine", "")))
        required = guardian_arguments(
            expected_exe, Path(marker["data_directory"]).parent,
            Path(marker["data_directory"]), int(marker["port"]),
        )
        def normalize(value: str) -> str:
            return value.replace("/", "\\").casefold()
        return (
            bool(actual)
            and len(actual) == len(required)
            and normalize(actual[0]) == normalize(required[0])
            and sorted(map(normalize, actual[1:])) == sorted(map(normalize, required[1:]))
        )
    except (OSError, TypeError, ValueError, KeyError):
        return False


def _require_loopback_listeners(listeners: list[dict[str, Any]], port: int) -> None:
    if not listeners:
        raise ResumeError("No listener exists for the recorded guardian")
    for listener in listeners:
        if (
            int(listener.get("LocalPort", -1)) != port
            or listener.get("LocalAddress") != HOST
        ):
            raise ResumeError("Listener does not match the loopback workspace endpoint")


def _new_process_creation_time(ops: ResumeOperations, process) -> str:
    try:
        return _utc_timestamp(ops.process_creation_time(process))
    except (OSError, ResumeError, AttributeError, TypeError, ValueError):
        return ""


def _load_verified_runtime(
    operations: ResumeOperations, workspace: Path, repo: Path, expected_port: int
) -> dict[str, Any]:
    runtime = operations.load_runtime(workspace, repo)
    if (
        not isinstance(runtime, dict)
        or runtime.get("database") != DATABASE
        or type(runtime.get("port")) is not int
        or runtime.get("port") != expected_port
        or runtime.get("identity_profile") != "school_tenant"
    ):
        raise ResumeError("Runtime grants or schema revision do not match the workspace")
    return runtime


def _validate_resume_scope(
    workspace: Path,
    repo: Path,
    *,
    expected_workspace: Path,
    expected_port: int,
    restore_source_workspace: Path | None,
    fresh_expected_workspace_id: str | None,
    prepared_expected_workspace_id: str | None,
    restored_install_source_workspace: Path | None,
    restored_install_source_workspace_id: str | None,
    restored_install_source_port: int | None,
    restored_install_expected_workspace_id: str | None,
) -> dict[str, Any]:
    if restored_install_source_workspace is not None:
        if (
            restore_source_workspace is not None
            or fresh_expected_workspace_id is not None
            or prepared_expected_workspace_id is not None
            or restored_install_source_workspace_id is None
            or restored_install_source_port is None
            or restored_install_expected_workspace_id is None
        ):
            raise ResumeError("Restored-install, fresh, prepared, and legacy modes are exclusive")
        _, marker = validate_restored_install_workspace(
            workspace,
            repo,
            source_workspace=restored_install_source_workspace,
            expected_port=expected_port,
            source_port=restored_install_source_port,
            expected_workspace_id=restored_install_expected_workspace_id,
            expected_source_workspace_id=restored_install_source_workspace_id,
        )
        return marker
    if prepared_expected_workspace_id is not None:
        if restore_source_workspace is not None or fresh_expected_workspace_id is not None:
            raise ResumeError("Prepared, fresh, and restore classifications cannot be combined")
        if expected_port == PORT:
            raise ResumeError("Prepared install requires a port separate from legacy 3308")
        return validate_prepared_install_workspace(
            workspace,
            repo,
            expected_workspace=expected_workspace,
            expected_port=expected_port,
            expected_workspace_id=prepared_expected_workspace_id,
        )
    if fresh_expected_workspace_id is not None:
        if restore_source_workspace is not None:
            raise ResumeError("Fresh and restore classifications cannot be combined")
        if expected_port == PORT:
            raise ResumeError("Fresh workspace requires a port separate from legacy 3308")
        return validate_fresh_workspace(
            workspace,
            repo,
            expected_workspace=expected_workspace,
            expected_port=expected_port,
            expected_workspace_id=fresh_expected_workspace_id,
        )
    if restore_source_workspace is not None:
        _, marker = validate_restored_workspace(
            workspace,
            repo,
            source_workspace=restore_source_workspace,
            expected_port=expected_port,
        )
        return marker
    if expected_port != PORT:
        raise ResumeError("Non-default database ports require explicit restore mode")
    return validate_existing_workspace(
        workspace,
        repo,
        expected_workspace=expected_workspace,
        expected_port=expected_port,
    )


def resume_workspace(
    workspace: Path = DEFAULT_WORKSPACE,
    repo: Path = DEFAULT_REPO,
    *,
    ops: Any | None = None,
    timeout: float = 45.0,
    lock_factory=workspace_lock,
    expected_workspace: Path = DEFAULT_WORKSPACE,
    expected_port: int = PORT,
    _restore_source_workspace: Path | None = None,
    _fresh_expected_workspace_id: str | None = None,
    _prepared_expected_workspace_id: str | None = None,
    _restored_install_source_workspace: Path | None = None,
    _restored_install_source_workspace_id: str | None = None,
    _restored_install_source_port: int | None = None,
    _restored_install_expected_workspace_id: str | None = None,
) -> dict[str, Any]:
    """Verify the running instance or start the existing initialized data once."""
    _validate_expected_port(expected_port)
    if not math.isfinite(timeout) or not 0 < timeout <= MAX_READINESS_SECONDS:
        raise ResumeError("Readiness observation must be bounded to 60 seconds")
    if _restore_source_workspace is not None and expected_port == PORT:
        raise ResumeError("A restored target must use a separate database port")
    if _fresh_expected_workspace_id is not None and expected_port == PORT:
        raise ResumeError("A fresh target must use a separate database port")
    if _prepared_expected_workspace_id is not None and expected_port == PORT:
        raise ResumeError("Prepared install requires a port separate from legacy 3308")
    restored_install_values = (
        _restored_install_source_workspace,
        _restored_install_source_workspace_id,
        _restored_install_source_port,
        _restored_install_expected_workspace_id,
    )
    restored_install_requested = any(value is not None for value in restored_install_values)
    if restored_install_requested and not all(value is not None for value in restored_install_values):
        raise ResumeError("Restored-install mode requires explicit source and target identity")
    if restored_install_requested and expected_port == PORT:
        raise ResumeError("Restored install requires a port separate from legacy 3308")
    if sum(
        value is not None
        for value in (
            _restore_source_workspace,
            _fresh_expected_workspace_id,
            _prepared_expected_workspace_id,
            _restored_install_source_workspace,
        )
    ) > 1:
        raise ResumeError("Prepared, fresh, and restore classifications cannot be combined")
    if restored_install_requested and _restored_install_source_port is None:
        raise ResumeError("Restored-install source port is required")
    if (
        expected_port != PORT
        and _restore_source_workspace is None
        and _fresh_expected_workspace_id is None
        and _prepared_expected_workspace_id is None
        and _restored_install_source_workspace is None
    ):
        raise ResumeError("Non-default database ports require explicit restore mode")
    if (
        _restore_source_workspace is not None
        and Path(_restore_source_workspace).resolve(strict=False)
        != Path(DEFAULT_WORKSPACE).resolve(strict=False)
    ):
        raise ResumeError("Restore mode is bound to the registered source workspace")
    operations = ops or ResumeOperations()
    if not operations.is_supported_platform():
        raise ResumeError("Workspace resume requires Windows")
    if Path(workspace).resolve(strict=False) != Path(expected_workspace).resolve(strict=False):
        raise ResumeError("Only the registered school workspace can be resumed")

    workspace_path = Path(workspace)
    # Verify the protected parent before creating the mutual-exclusion file.
    _validate_resume_scope(
        workspace_path,
        Path(repo),
        expected_workspace=Path(expected_workspace),
        expected_port=expected_port,
        restore_source_workspace=_restore_source_workspace,
        fresh_expected_workspace_id=_fresh_expected_workspace_id,
        prepared_expected_workspace_id=_prepared_expected_workspace_id,
        restored_install_source_workspace=_restored_install_source_workspace,
        restored_install_source_workspace_id=_restored_install_source_workspace_id,
        restored_install_source_port=_restored_install_source_port,
        restored_install_expected_workspace_id=_restored_install_expected_workspace_id,
    )
    operations.verify_acl(workspace_path)
    if _fresh_expected_workspace_id is not None or restored_install_requested:
        operations.verify_fresh_dpapi(workspace_path, expected_port)
    with lock_factory(Path(workspace)):
        marker = _validate_resume_scope(
            workspace_path,
            Path(repo),
            expected_workspace=Path(expected_workspace),
            expected_port=expected_port,
            restore_source_workspace=_restore_source_workspace,
            fresh_expected_workspace_id=_fresh_expected_workspace_id,
            prepared_expected_workspace_id=_prepared_expected_workspace_id,
            restored_install_source_workspace=_restored_install_source_workspace,
            restored_install_source_workspace_id=_restored_install_source_workspace_id,
            restored_install_source_port=_restored_install_source_port,
            restored_install_expected_workspace_id=_restored_install_expected_workspace_id,
        )
        operations.verify_acl(Path(workspace))
        if _fresh_expected_workspace_id is not None or restored_install_requested:
            operations.verify_fresh_dpapi(workspace_path, expected_port)
        pid_value = marker.get("parent_pid")
        process = operations.inspect_process(int(pid_value)) if isinstance(pid_value, int) else None
        listeners = operations.listeners(expected_port)

        if process is not None:
            if not _process_matches(process, marker):
                raise ResumeError("Recorded guardian identity does not match; refusing to start")
            _require_loopback_listeners(listeners, expected_port)
            operations.verify_running_process(marker)
            try:
                if _fresh_expected_workspace_id is not None or restored_install_requested:
                    operations.verify_fresh_database(workspace_path, expected_port, Path(repo))
                else:
                    _load_verified_runtime(operations, workspace_path, Path(repo), expected_port)
            except Exception as exc:
                marker["resume_state"] = f"RUNTIME_VALIDATION_FAILED_{type(exc).__name__}"
                atomic_write_marker(Path(workspace), marker)
                raise
            if marker.get("resume_state") != "READY":
                marker["resume_state"] = "READY"
                marker["resume_updated_at"] = (
                    datetime.now(UTC)
                    .isoformat(timespec="microseconds")
                    .replace("+00:00", "Z")
                )
                atomic_write_marker(Path(workspace), marker)
            return {"status": "ALREADY_RUNNING", "database": DATABASE, "port": expected_port}

        if listeners or not operations.port_is_free(expected_port):
            raise ResumeError("Port is occupied by an unverified listener")

        executable = Path(marker["executable"])
        data_directory = Path(marker["data_directory"])
        process = operations.start_guardian(
            executable, workspace_path, data_directory, expected_port
        )
        # A launched process is never killed here. Persist its identity before
        # readiness work so any later failure has a recoverable handoff.
        updated = dict(marker)
        updated["parent_pid"] = int(process.pid)
        updated["parent_creation_time"] = _new_process_creation_time(operations, process)
        updated["resume_state"] = "STARTING"
        updated["resume_updated_at"] = (
            datetime.now(UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
        atomic_write_marker(Path(workspace), updated)
        marker.clear()
        marker.update(updated)
        if not marker["parent_creation_time"]:
            marker["resume_state"] = "IDENTITY_UNAVAILABLE"
            atomic_write_marker(Path(workspace), marker)
            raise ResumeError("Started guardian identity unavailable; preserve it for recovery")

        try:
            if not operations.wait_ready(process, expected_port, timeout):
                marker["resume_state"] = "READINESS_OBSERVATION_FAILED"
                atomic_write_marker(Path(workspace), marker)
                raise ResumeError(
                    "Readiness was not observed; guardian remains running for recovery"
                )
            current = operations.inspect_process(int(process.pid))
            if current is None or not _process_matches(current, marker):
                marker["resume_state"] = "GUARDIAN_IDENTITY_CHANGED"
                atomic_write_marker(Path(workspace), marker)
                raise ResumeError("Started guardian identity changed; preserve it for recovery")
            _require_loopback_listeners(operations.listeners(expected_port), expected_port)
            operations.verify_running_process(marker)
            if _fresh_expected_workspace_id is not None or restored_install_requested:
                operations.verify_fresh_database(workspace_path, expected_port, Path(repo))
            else:
                _load_verified_runtime(operations, workspace_path, Path(repo), expected_port)
        except Exception as exc:
            if marker.get("resume_state") == "STARTING":
                marker["resume_state"] = f"VALIDATION_FAILED_{type(exc).__name__}"
                atomic_write_marker(Path(workspace), marker)
            raise

        marker["resume_state"] = "READY"
        atomic_write_marker(Path(workspace), marker)
        return {"status": "STARTED", "database": DATABASE, "port": expected_port}


def resume_restored_workspace(
    workspace: Path,
    repo: Path = DEFAULT_REPO,
    *,
    expected_port: int,
    ops: Any | None = None,
    timeout: float = 45.0,
    lock_factory=workspace_lock,
) -> dict[str, Any]:
    """Resume a verified isolated restore bound to the registered source workspace."""
    target = Path(workspace)
    return resume_workspace(
        target,
        repo,
        ops=ops,
        timeout=timeout,
        lock_factory=lock_factory,
        expected_workspace=target,
        expected_port=expected_port,
        _restore_source_workspace=Path(DEFAULT_WORKSPACE),
    )


def resume_restored_install_workspace(
    workspace: Path,
    repo: Path = DEFAULT_REPO,
    *,
    expected_port: int,
    expected_workspace_id: str,
    source_workspace: Path,
    source_port: int,
    expected_source_workspace_id: str,
    ops: Any | None = None,
    timeout: float = 45.0,
    lock_factory=workspace_lock,
) -> dict[str, Any]:
    """Resume a restored install bound to an explicitly named source install."""
    target = Path(workspace)
    return resume_workspace(
        target,
        repo,
        ops=ops,
        timeout=timeout,
        lock_factory=lock_factory,
        expected_workspace=target,
        expected_port=expected_port,
        _restored_install_source_workspace=Path(source_workspace),
        _restored_install_source_workspace_id=expected_source_workspace_id,
        _restored_install_source_port=source_port,
        _restored_install_expected_workspace_id=expected_workspace_id,
    )


def resume_fresh_workspace(
    workspace: Path,
    repo: Path = DEFAULT_REPO,
    *,
    expected_port: int,
    expected_workspace_id: str,
    ops: Any | None = None,
    timeout: float = 45.0,
    lock_factory=workspace_lock,
) -> dict[str, Any]:
    """Resume an explicitly named, already initialized and migrated install target."""
    target = Path(workspace)
    return resume_workspace(
        target,
        repo,
        ops=ops,
        timeout=timeout,
        lock_factory=lock_factory,
        expected_workspace=target,
        expected_port=expected_port,
        _fresh_expected_workspace_id=expected_workspace_id,
    )


def resume_prepared_install_workspace(
    workspace: Path,
    repo: Path = DEFAULT_REPO,
    *,
    expected_port: int,
    expected_workspace_id: str,
    ops: Any | None = None,
    timeout: float = 45.0,
    lock_factory=workspace_lock,
) -> dict[str, Any]:
    """Resume an install whose runtime identity was fully provisioned earlier."""
    target = Path(workspace)
    return resume_workspace(
        target,
        repo,
        ops=ops,
        timeout=timeout,
        lock_factory=lock_factory,
        expected_workspace=target,
        expected_port=expected_port,
        _prepared_expected_workspace_id=expected_workspace_id,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--restore-mode", action="store_true")
    parser.add_argument("--fresh-mode", action="store_true")
    parser.add_argument("--prepared-install-mode", action="store_true")
    parser.add_argument("--restored-install-mode", action="store_true")
    parser.add_argument("--port", type=int)
    parser.add_argument("--expected-workspace-id")
    parser.add_argument("--source-workspace", type=Path)
    parser.add_argument("--source-port", type=int)
    parser.add_argument("--expected-source-workspace-id")
    parser.add_argument("--timeout", type=float, default=45.0)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    modes = (
        args.restore_mode,
        args.fresh_mode,
        args.prepared_install_mode,
        args.restored_install_mode,
    )
    if sum(modes) > 1:
        parser.error("Restore, fresh, prepared-install, and restored-install modes are mutually exclusive")
    if (
        args.expected_workspace_id is not None
        and not args.fresh_mode
        and not args.prepared_install_mode
        and not args.restored_install_mode
    ):
        parser.error("--expected-workspace-id requires an explicit install resume mode")
    if args.restored_install_mode:
        if (
            args.workspace is None
            or args.port is None
            or args.expected_workspace_id is None
            or args.source_workspace is None
            or args.source_port is None
            or args.expected_source_workspace_id is None
        ):
            parser.error("--restored-install-mode requires explicit source and target path, ID, and port")
        if args.port == args.source_port:
            parser.error("Restored-install source and target ports must differ")
        if args.port <= PORT:
            parser.error("Restored-install target port must be separate from legacy 3308")
    elif any(
        value is not None
        for value in (args.source_workspace, args.source_port, args.expected_source_workspace_id)
    ):
        parser.error("Source workspace arguments require --restored-install-mode")
    if args.fresh_mode or args.prepared_install_mode:
        if args.workspace is None or args.port is None or args.expected_workspace_id is None:
            parser.error("Install mode requires explicit --workspace, --port, and --expected-workspace-id")
        if args.port <= PORT:
            parser.error("Install mode requires a port separate from the legacy workspace")
    elif not (args.restore_mode or args.restored_install_mode) and args.port is not None and args.port != PORT:
        parser.error("--port changes require --restore-mode or --fresh-mode")
    if args.restore_mode:
        if args.workspace is None or args.port is None:
            parser.error("--restore-mode requires explicit --workspace and --port")
        if args.port == PORT:
            parser.error("--restore-mode requires a separate database port")
    elif not (args.fresh_mode or args.prepared_install_mode or args.restored_install_mode) and args.port is not None and args.port != PORT:
        parser.error("--port changes require --restore-mode or --fresh-mode")
    try:
        if args.restore_mode:
            result = resume_restored_workspace(
                args.workspace,
                DEFAULT_REPO,
                expected_port=args.port,
                timeout=args.timeout,
            )
        elif args.fresh_mode:
            result = resume_fresh_workspace(
                args.workspace,
                DEFAULT_REPO,
                expected_port=args.port,
                expected_workspace_id=args.expected_workspace_id,
                timeout=args.timeout,
            )
        elif args.prepared_install_mode:
            result = resume_prepared_install_workspace(
                args.workspace,
                DEFAULT_REPO,
                expected_port=args.port,
                expected_workspace_id=args.expected_workspace_id,
                timeout=args.timeout,
            )
        elif args.restored_install_mode:
            result = resume_restored_install_workspace(
                args.workspace,
                DEFAULT_REPO,
                expected_port=args.port,
                expected_workspace_id=args.expected_workspace_id,
                source_workspace=args.source_workspace,
                source_port=args.source_port,
                expected_source_workspace_id=args.expected_source_workspace_id,
                timeout=args.timeout,
            )
        else:
            result = resume_workspace(
                args.workspace or DEFAULT_WORKSPACE,
                DEFAULT_REPO,
                expected_port=PORT,
                timeout=args.timeout,
            )
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:  # noqa: BLE001 - avoid emitting process/database details.
        print(json.dumps({"status": "BLOCKED", "error_type": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
