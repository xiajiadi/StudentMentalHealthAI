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

DEFAULT_WORKSPACE = Path(r"D:\Projects\.StudentMentalHealthAI-school-workspace-20261011")
DEFAULT_REPO = Path(__file__).resolve().parents[1]
DATABASE = "smhai_school_demo"
HOST = "127.0.0.1"
PORT = 3308
MAX_READINESS_SECONDS = 60


class ResumeError(RuntimeError):
    """Safe, non-secret failure for resuming the owned workspace."""


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
    workspace: Path, repo: Path, *, expected_workspace: Path = DEFAULT_WORKSPACE
) -> dict[str, Any]:
    """Validate the existing marker, protected paths, vendor binary and datadir."""
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
    if marker.get("port") != PORT or marker.get("database") != DATABASE:
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
        if (root / name).exists() or (root / name).is_symlink():
            _reject_reparse_path(root / name)
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
            len(actual) == len(required)
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


def resume_workspace(
    workspace: Path = DEFAULT_WORKSPACE,
    repo: Path = DEFAULT_REPO,
    *,
    ops: Any | None = None,
    timeout: float = 45.0,
    lock_factory=workspace_lock,
    expected_workspace: Path = DEFAULT_WORKSPACE,
) -> dict[str, Any]:
    """Verify the running instance or start the existing initialized data once."""
    if not math.isfinite(timeout) or not 0 < timeout <= MAX_READINESS_SECONDS:
        raise ResumeError("Readiness observation must be bounded to 60 seconds")
    operations = ops or ResumeOperations()
    if not operations.is_supported_platform():
        raise ResumeError("Workspace resume requires Windows")
    if Path(workspace).resolve(strict=False) != Path(expected_workspace).resolve(strict=False):
        raise ResumeError("Only the registered school workspace can be resumed")

    workspace_path = Path(workspace)
    # Verify the protected parent before creating the mutual-exclusion file.
    validate_existing_workspace(
        workspace_path, Path(repo), expected_workspace=Path(expected_workspace)
    )
    operations.verify_acl(workspace_path)
    with lock_factory(Path(workspace)):
        marker = validate_existing_workspace(
            Path(workspace), Path(repo), expected_workspace=Path(expected_workspace)
        )
        operations.verify_acl(Path(workspace))
        pid_value = marker.get("parent_pid")
        process = operations.inspect_process(int(pid_value)) if isinstance(pid_value, int) else None
        listeners = operations.listeners(int(marker["port"]))

        if process is not None:
            if not _process_matches(process, marker):
                raise ResumeError("Recorded guardian identity does not match; refusing to start")
            _require_loopback_listeners(listeners, int(marker["port"]))
            operations.verify_running_process(marker)
            try:
                operations.load_runtime(Path(workspace), Path(repo))
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
            return {"status": "ALREADY_RUNNING", "database": DATABASE, "port": PORT}

        if listeners or not operations.port_is_free(int(marker["port"])):
            raise ResumeError("Port is occupied by an unverified listener")

        executable = Path(marker["executable"])
        data_directory = Path(marker["data_directory"])
        process = operations.start_guardian(executable, Path(workspace), data_directory, PORT)
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
            if not operations.wait_ready(process, PORT, timeout):
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
            _require_loopback_listeners(operations.listeners(PORT), PORT)
            operations.verify_running_process(marker)
            operations.load_runtime(Path(workspace), Path(repo))
        except Exception as exc:
            if marker.get("resume_state") == "STARTING":
                marker["resume_state"] = f"VALIDATION_FAILED_{type(exc).__name__}"
                atomic_write_marker(Path(workspace), marker)
            raise

        marker["resume_state"] = "READY"
        atomic_write_marker(Path(workspace), marker)
        return {"status": "STARTED", "database": DATABASE, "port": PORT}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args()
    try:
        result = resume_workspace(args.workspace, DEFAULT_REPO, timeout=args.timeout)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:  # noqa: BLE001 - avoid emitting process/database details.
        print(json.dumps({"status": "BLOCKED", "error_type": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
