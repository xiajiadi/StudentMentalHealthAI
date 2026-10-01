"""Evaluation-owned loopback process lifecycle for a one-shot D4-3B run."""

from __future__ import annotations

import asyncio
import ctypes
import hashlib
import ipaddress
import json
import math
import os
import re
import signal
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import httpx

if os.name == "nt":  # pragma: no cover - exercised on Windows
    import _winapi
    import msvcrt

try:
    from harness.foundation.hashing import canonical_json
except ModuleNotFoundError:  # pragma: no cover - package-relative import mode
    from ..foundation.hashing import canonical_json


class LifecycleError(RuntimeError):
    """A managed evaluation service failed to start or stop cleanly."""


@dataclass(frozen=True, slots=True)
class ManagedCommandResult:
    return_code: int
    stdout: bytes = dataclass_field(repr=False)
    stderr: bytes = dataclass_field(repr=False)


@dataclass(frozen=True, slots=True)
class ProcessSpec:
    name: str
    executable: Path
    arguments: tuple[str, ...]
    cwd: Path
    environment: Mapping[str, str] = dataclass_field(repr=False)
    readiness_url: str
    readiness_kind: str
    log_path: Path
    readiness_request_timeout_seconds: float = 1.0
    stderr_log_path: Path | None = None
    interpreter_version: str | None = None
    package_lock_identity: Mapping[str, str] | None = None
    ownership_type: str = "D4_EVALUATION_SUPERVISOR_OWNED"
    environment_allowlist: frozenset[str] | None = None
    redaction_values: tuple[str, ...] = dataclass_field(default=(), repr=False)


@dataclass(slots=True)
class _OwnedProcess:
    spec: ProcessSpec
    process: Any
    job: Any | None
    stdout_handle: Any
    stderr_handle: Any
    command_hash: str
    executable_sha256: str
    parent_pid: int
    started_at: str
    log_threads: tuple[threading.Thread, ...] = ()
    stopped_at: str | None = None
    return_code: int | None = None
    readiness_verified: bool = False
    shutdown_method: str | None = None
    shutdown_error: str | None = None


if os.name == "nt":  # pragma: no cover - exercised on Windows
    class _JobBasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("per_process_user_time_limit", ctypes.c_longlong),
            ("per_job_user_time_limit", ctypes.c_longlong),
            ("limit_flags", ctypes.c_uint32),
            ("minimum_working_set_size", ctypes.c_size_t),
            ("maximum_working_set_size", ctypes.c_size_t),
            ("active_process_limit", ctypes.c_uint32),
            ("affinity", ctypes.c_size_t),
            ("priority_class", ctypes.c_uint32),
            ("scheduling_class", ctypes.c_uint32),
        ]


    class _JobIoCounters(ctypes.Structure):
        _fields_ = [
            ("read_operation_count", ctypes.c_ulonglong),
            ("write_operation_count", ctypes.c_ulonglong),
            ("other_operation_count", ctypes.c_ulonglong),
            ("read_transfer_count", ctypes.c_ulonglong),
            ("write_transfer_count", ctypes.c_ulonglong),
            ("other_transfer_count", ctypes.c_ulonglong),
        ]


    class _JobExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("basic_limit_information", _JobBasicLimitInformation),
            ("io_info", _JobIoCounters),
            ("process_memory_limit", ctypes.c_size_t),
            ("job_memory_limit", ctypes.c_size_t),
            ("peak_process_memory_used", ctypes.c_size_t),
            ("peak_job_memory_used", ctypes.c_size_t),
        ]


    class _JobBasicAccountingInformation(ctypes.Structure):
        _fields_ = [
            ("total_user_time", ctypes.c_longlong),
            ("total_kernel_time", ctypes.c_longlong),
            ("this_period_total_user_time", ctypes.c_longlong),
            ("this_period_total_kernel_time", ctypes.c_longlong),
            ("total_page_fault_count", ctypes.c_uint32),
            ("total_processes", ctypes.c_uint32),
            ("active_processes", ctypes.c_uint32),
            ("total_terminated_processes", ctypes.c_uint32),
        ]


    class _WindowsJobObject:
        """A dedicated kill-on-close job that is assigned before a service can run."""

        _EXTENDED_LIMIT_INFORMATION = 9
        _BASIC_ACCOUNTING_INFORMATION = 1
        _BASIC_PROCESS_ID_LIST = 3
        _KILL_ON_JOB_CLOSE = 0x00002000
        _ERROR_MORE_DATA = 234

        def __init__(self) -> None:
            self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self._kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
            self._kernel32.CreateJobObjectW.restype = ctypes.c_void_p
            self._kernel32.SetInformationJobObject.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_void_p,
                ctypes.c_uint32,
            ]
            self._kernel32.SetInformationJobObject.restype = ctypes.c_int
            self._kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            self._kernel32.AssignProcessToJobObject.restype = ctypes.c_int
            self._kernel32.OpenProcess.argtypes = [
                ctypes.c_uint32,
                ctypes.c_int,
                ctypes.c_uint32,
            ]
            self._kernel32.OpenProcess.restype = ctypes.c_void_p
            self._kernel32.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            self._kernel32.TerminateJobObject.restype = ctypes.c_int
            self._kernel32.QueryInformationJobObject.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_uint32),
            ]
            self._kernel32.QueryInformationJobObject.restype = ctypes.c_int
            self._kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            self._kernel32.CloseHandle.restype = ctypes.c_int
            handle = self._kernel32.CreateJobObjectW(None, None)
            if not handle:
                raise LifecycleError("could not create a dedicated Windows service job")
            self._handle: int | None = int(handle)
            limits = _JobExtendedLimitInformation()
            limits.basic_limit_information.limit_flags = self._KILL_ON_JOB_CLOSE
            if not self._kernel32.SetInformationJobObject(
                ctypes.c_void_p(self._handle),
                self._EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            ):
                error = ctypes.get_last_error()
                self.close()
                raise LifecycleError(
                    f"could not configure a dedicated Windows service job ({error})"
                )

        def assign_pid(self, process_id: int) -> None:
            if self._handle is None:
                raise LifecycleError("Windows service job is already closed")
            process_handle = self._kernel32.OpenProcess(0x00000101, 0, process_id)
            if not process_handle:
                error = ctypes.get_last_error()
                raise LifecycleError(
                    f"suspended service process could not be opened for job assignment ({error})"
                )
            try:
                assigned = self._kernel32.AssignProcessToJobObject(
                    ctypes.c_void_p(self._handle), process_handle
                )
            finally:
                self._kernel32.CloseHandle(process_handle)
            if not assigned:
                error = ctypes.get_last_error()
                raise LifecycleError(
                    f"service process could not be assigned to its Windows job ({error})"
                )

        def terminate(self) -> None:
            if self._handle is None:
                raise LifecycleError("Windows service job is already closed")
            if not self._kernel32.TerminateJobObject(ctypes.c_void_p(self._handle), 0xD403):
                error = ctypes.get_last_error()
                raise LifecycleError(f"Windows service job termination failed ({error})")

        def active_process_count(self) -> int:
            if self._handle is None:
                return 0
            info = _JobBasicAccountingInformation()
            returned = ctypes.c_uint32()
            if not self._kernel32.QueryInformationJobObject(
                ctypes.c_void_p(self._handle),
                self._BASIC_ACCOUNTING_INFORMATION,
                ctypes.byref(info),
                ctypes.sizeof(info),
                ctypes.byref(returned),
            ):
                error = ctypes.get_last_error()
                raise LifecycleError(f"Windows service job accounting failed ({error})")
            return int(info.active_processes)

        def process_ids(self) -> list[int]:
            if self._handle is None:
                return []
            pointer_size = ctypes.sizeof(ctypes.c_size_t)
            size = 8 + pointer_size * 128
            while size <= 8 + pointer_size * 65_536:
                buffer = ctypes.create_string_buffer(size)
                returned = ctypes.c_uint32()
                if self._kernel32.QueryInformationJobObject(
                    ctypes.c_void_p(self._handle),
                    self._BASIC_PROCESS_ID_LIST,
                    ctypes.byref(buffer),
                    size,
                    ctypes.byref(returned),
                ):
                    count = int.from_bytes(buffer.raw[4:8], "little")
                    if count > (size - 8) // pointer_size:
                        raise LifecycleError("Windows service job returned an invalid process list")
                    return [
                        int.from_bytes(
                            buffer.raw[8 + index * pointer_size : 8 + (index + 1) * pointer_size],
                            "little",
                        )
                        for index in range(count)
                    ]
                error = ctypes.get_last_error()
                if error != self._ERROR_MORE_DATA:
                    raise LifecycleError(f"Windows service job process list failed ({error})")
                size = max(size * 2, int(returned.value))
            raise LifecycleError("Windows service job process list exceeded its fixed bound")

        def wait_empty(self, timeout_seconds: float) -> bool:
            deadline = time.monotonic() + max(0.0, timeout_seconds)
            while True:
                if self.active_process_count() == 0:
                    return True
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.05)

        def close(self) -> None:
            handle = self._handle
            if handle is None:
                return
            if not self._kernel32.CloseHandle(ctypes.c_void_p(handle)):
                error = ctypes.get_last_error()
                raise LifecycleError(f"Windows service job handle close failed ({error})")
            self._handle = None

        def __del__(self) -> None:
            try:
                self.close()
            except Exception:
                pass


    class _ThreadEntry32(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_uint32),
            ("cntUsage", ctypes.c_uint32),
            ("th32ThreadID", ctypes.c_uint32),
            ("th32OwnerProcessID", ctypes.c_uint32),
            ("tpBasePri", ctypes.c_int32),
            ("tpDeltaPri", ctypes.c_int32),
            ("dwFlags", ctypes.c_uint32),
        ]


    def _resume_suspended_primary_thread(process_id: int) -> None:
        """Resume the only thread of a CREATE_SUSPENDED process after job assignment."""

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        kernel32.Thread32First.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ThreadEntry32)]
        kernel32.Thread32First.restype = ctypes.c_int
        kernel32.Thread32Next.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ThreadEntry32)]
        kernel32.Thread32Next.restype = ctypes.c_int
        kernel32.OpenThread.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel32.OpenThread.restype = ctypes.c_void_p
        kernel32.ResumeThread.argtypes = [ctypes.c_void_p]
        kernel32.ResumeThread.restype = ctypes.c_uint32
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000004, 0)
        if not snapshot or snapshot == ctypes.c_void_p(-1).value:
            error = ctypes.get_last_error()
            raise LifecycleError(f"could not inspect the suspended service thread ({error})")
        thread_ids: list[int] = []
        try:
            entry = _ThreadEntry32()
            entry.dwSize = ctypes.sizeof(entry)
            found = kernel32.Thread32First(snapshot, ctypes.byref(entry))
            while found:
                if int(entry.th32OwnerProcessID) == process_id:
                    thread_ids.append(int(entry.th32ThreadID))
                found = kernel32.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
        if len(thread_ids) != 1:
            raise LifecycleError(
                "suspended service did not have exactly one primary thread"
            )
        thread = kernel32.OpenThread(0x0002, 0, thread_ids[0])
        if not thread:
            error = ctypes.get_last_error()
            raise LifecycleError(f"could not open the suspended service thread ({error})")
        try:
            if kernel32.ResumeThread(thread) != 1:
                error = ctypes.get_last_error()
                raise LifecycleError(f"could not resume the suspended service ({error})")
        finally:
            kernel32.CloseHandle(thread)


    def _start_windows_job_process(
        command: list[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
    ) -> tuple[subprocess.Popen[bytes], _WindowsJobObject]:
        """Create a suspended direct child, assign it to a Job, and return it suspended."""

        job = _WindowsJobObject()
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=dict(environment),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                close_fds=True,
                creationflags=0x00000200 | 0x00000004,
            )
        except OSError as exc:
            job.close()
            raise LifecycleError(
                f"service process could not start ({type(exc).__name__})"
            ) from None
        try:
            job.assign_pid(process.pid)
        except LifecycleError:
            try:
                process.terminate()
                process.wait(timeout=2.0)
            except (OSError, subprocess.SubprocessError):
                pass
            try:
                job.close()
            except LifecycleError:
                pass
            raise
        return process, job


_SAFE_INHERITED_ENVIRONMENT = frozenset(
    {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT"}
)
_SENSITIVE_ARGUMENT = re.compile(
    r"(?i)(?:password|passwd|secret|token|api[_-]?key|authorization|cookie)"
)
_SENSITIVE_ENVIRONMENT = re.compile(
    r"(?i)(?:password|passwd|secret|token|api[_-]?key|authorization|cookie|database_url)"
)
_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_child_environment(
    overrides: Mapping[str, str], *, allowed_names: frozenset[str] | None = None
) -> dict[str, str]:
    """Keep system runtime variables and pass all other values by explicit profile only."""

    environment = {
        name: value
        for name, value in os.environ.items()
        if name.upper() in _SAFE_INHERITED_ENVIRONMENT
    }
    for name, value in overrides.items():
        if not isinstance(name, str) or not _ENVIRONMENT_NAME.fullmatch(name):
            raise LifecycleError("managed service environment contains an invalid variable name")
        if allowed_names is not None and name not in allowed_names:
            raise LifecycleError("managed service environment exceeds its profile allowlist")
        if not isinstance(value, str):
            raise LifecycleError("managed service environment values must be text")
        environment[name] = value
    return environment


def redact_argv(arguments: tuple[str, ...] | list[str]) -> list[str]:
    """Redact values passed after secret-bearing command-line flags."""

    redacted: list[str] = []
    redact_next = False
    for argument in arguments:
        if redact_next:
            redacted.append("<redacted>")
            redact_next = False
            continue
        flag, separator, _value = argument.partition("=")
        if flag.startswith("-") and _SENSITIVE_ARGUMENT.search(flag):
            redacted.append(flag + ("=<redacted>" if separator else ""))
            redact_next = not separator
        else:
            redacted.append(argument)
    if redact_next:
        redacted.append("<missing>")
    return redacted


def _secret_bytes(environment: Mapping[str, str]) -> tuple[bytes, ...]:
    values = {
        value.encode("utf-8", errors="surrogatepass")
        for name, value in environment.items()
        if _SENSITIVE_ENVIRONMENT.search(name) and value
    }
    return tuple(sorted(values, key=len, reverse=True))


def _redaction_bytes(values: tuple[str, ...]) -> tuple[bytes, ...]:
    encoded = {
        value.encode("utf-8", errors="surrogatepass")
        for value in values
        if isinstance(value, str) and value
    }
    return tuple(sorted(encoded, key=len, reverse=True))


def _copy_redacted_log(source: Any, target: Any, secret_values: tuple[bytes, ...]) -> None:
    try:
        while True:
            line = source.readline()
            if not line:
                break
            for secret in secret_values:
                line = line.replace(secret, b"<redacted>")
            target.write(line)
            target.flush()
    finally:
        source.close()


def run_managed_command(
    *,
    name: str,
    executable: Path,
    arguments: tuple[str, ...],
    cwd: Path,
    environment: Mapping[str, str],
    environment_allowlist: frozenset[str],
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: float = 120.0,
    check: bool = True,
    redaction_values: tuple[str, ...] = (),
) -> ManagedCommandResult:
    """Run one fixed evaluation bootstrap command with redacted child output."""

    if not executable.is_absolute() or not cwd.is_absolute():
        raise LifecycleError(f"managed command {name} requires absolute executable and cwd paths")
    executable = executable.resolve()
    cwd = cwd.resolve()
    if not executable.is_file() or not cwd.is_dir():
        raise LifecycleError(f"managed command {name} has an unavailable executable or working directory")
    if timeout_seconds <= 0:
        raise LifecycleError(f"managed command {name} has an invalid timeout")

    secret_values = tuple(
        sorted(set(_secret_bytes(environment) + _redaction_bytes(redaction_values)), key=len, reverse=True)
    )
    secret_text_values = tuple(
        value.decode("utf-8", errors="surrogatepass") for value in secret_values
    )
    if any(secret in argument for secret in secret_text_values for argument in arguments):
        raise LifecycleError(f"managed command {name} must receive secrets through its process environment")
    child_environment = build_child_environment(
        environment,
        allowed_names=environment_allowlist,
    )

    def redact(value: bytes | None) -> bytes:
        output = value or b""
        for secret in secret_values:
            output = output.replace(secret, b"<redacted>")
        return output

    stdout = b""
    stderr = b""
    try:
        result = subprocess.run(
            [str(executable), *arguments],
            cwd=cwd,
            env=child_environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            close_fds=True,
            creationflags=(
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            ),
            timeout=timeout_seconds,
            check=False,
        )
        stdout = redact(result.stdout)
        stderr = redact(result.stderr)
        return_code = result.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = redact(exc.stdout)
        stderr = redact(exc.stderr)
        _write_command_logs(name, stdout_path, stderr_path, stdout, stderr)
        raise LifecycleError(f"managed command {name} timed out") from None
    except OSError as exc:
        raise LifecycleError(
            f"managed command {name} could not start ({type(exc).__name__})"
        ) from None

    _write_command_logs(name, stdout_path, stderr_path, stdout, stderr)
    if check and return_code != 0:
        raise LifecycleError(f"managed command {name} failed with exit code {return_code}")
    return ManagedCommandResult(return_code=return_code, stdout=stdout, stderr=stderr)


def _write_command_logs(
    name: str,
    stdout_path: Path,
    stderr_path: Path,
    stdout: bytes,
    stderr: bytes,
) -> None:
    try:
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_bytes(stdout)
        stderr_path.write_bytes(stderr)
    except OSError as exc:
        raise LifecycleError(
            f"managed command {name} could not save redacted output ({type(exc).__name__})"
        ) from None


def _loopback_parts(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "tcp"} or not parsed.hostname or parsed.port is None:
        raise LifecycleError("managed service readiness URL must be an absolute HTTP or TCP loopback URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise LifecycleError("managed service readiness URL cannot contain credentials or query data")
    if parsed.scheme == "tcp" and parsed.path not in {"", "/"}:
        raise LifecycleError("TCP readiness URLs cannot contain a path")
    try:
        loopback = ipaddress.ip_address(parsed.hostname).is_loopback or parsed.hostname == "localhost"
    except ValueError:
        loopback = parsed.hostname == "localhost"
    if not loopback:
        raise LifecycleError("managed services may bind only to loopback")
    return parsed.hostname, parsed.port


def _assert_port_free(url: str) -> None:
    host, port = _loopback_parts(url)
    try:
        with socket.create_connection((host, port), timeout=0.2):
            raise LifecycleError(f"refusing to adopt an already-running service at {host}:{port}")
    except OSError:
        return


def _profile_port_owners(url: str, owned_pids: set[int]) -> list[dict[str, Any]]:
    _, port = _loopback_parts(url)
    if os.name != "nt":
        _assert_port_free(url)
        return []
    try:
        from .network_integrity import NetworkIntegrityError, capture_data_plane_network
    except ModuleNotFoundError:  # pragma: no cover - package-relative test import
        from harness.controlled_product_eval.network_integrity import NetworkIntegrityError, capture_data_plane_network
    try:
        observation = capture_data_plane_network(
            required_ports=frozenset({port}),
            require_listeners=False,
            owned_pids=owned_pids,
        )
    except NetworkIntegrityError as exc:
        raise LifecycleError("formal listener ownership inventory is unavailable") from exc
    if observation["status"] != "PASS":
        raise LifecycleError("formal listener/network integrity failed before service start")
    return [
        item for item in observation["listeners"]
        if int(item["port"]) == port
    ]


def _is_ready(kind: str, payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if kind == "http-200":
        return True
    if kind == "backend":
        data = payload.get("data")
        return isinstance(data, dict) and data.get("status") == "ready"
    return payload.get("status") == "READY"


class ProcessSupervisor:
    """Own only explicitly started local eval services; Runtime is never a spec."""

    def __init__(self, *, startup_timeout_seconds: float = 180.0, shutdown_timeout_seconds: float = 8.0) -> None:
        self.startup_timeout_seconds = startup_timeout_seconds
        self.shutdown_timeout_seconds = shutdown_timeout_seconds
        self._owned: list[_OwnedProcess] = []
        self._closed = False

    async def start(self, specs: list[ProcessSpec]) -> list[dict[str, Any]]:
        if self._owned or self._closed:
            raise LifecycleError("process supervisor can start exactly one service set")
        try:
            for spec in specs:
                await self._start_one(spec)
            return self.identities()
        except Exception:
            await self.close()
            raise

    async def start_service(self, spec: ProcessSpec) -> dict[str, Any]:
        """Start one allow-listed profile for a persistent local supervisor session."""

        if self._closed:
            raise LifecycleError("process supervisor is closed")
        if any(owned.spec.name == spec.name for owned in self._owned):
            raise LifecycleError(f"managed service {spec.name} is already owned by this supervisor")
        try:
            await self._start_one(spec)
        except Exception:
            owned = next((item for item in self._owned if item.spec.name == spec.name), None)
            if owned is not None:
                _outcome, errors = await self._stop_owned(owned)
                if not errors:
                    self._owned.remove(owned)
                else:
                    raise LifecycleError(
                        f"managed service {spec.name} failed to start and cleanup could not be verified"
                    )
            raise
        return next(item for item in self.identities() if item["name"] == spec.name)

    async def stop_service(self, name: str) -> dict[str, Any]:
        """Stop only the process handle created by this supervisor."""

        owned = next((item for item in self._owned if item.spec.name == name), None)
        if owned is None:
            raise LifecycleError(f"managed service {name} is not owned by this supervisor")
        outcome, errors = await self._stop_owned(owned)
        if not errors:
            self._owned.remove(owned)
        return {"cleanup_verified": not errors, "service": outcome, "errors": errors}

    async def _start_one(self, spec: ProcessSpec) -> None:
        if not spec.executable.is_absolute() or not spec.cwd.is_absolute():
            raise LifecycleError(f"managed service {spec.name} requires absolute executable and cwd paths")
        if (
            isinstance(spec.readiness_request_timeout_seconds, bool)
            or not isinstance(spec.readiness_request_timeout_seconds, (int, float))
            or not math.isfinite(spec.readiness_request_timeout_seconds)
            or not 0 < spec.readiness_request_timeout_seconds <= 60
        ):
            raise LifecycleError(f"managed service {spec.name} has an invalid readiness request timeout")
        executable = spec.executable.resolve()
        cwd = spec.cwd.resolve()
        if not executable.is_file() or not cwd.is_dir():
            raise LifecycleError(f"managed service {spec.name} has an unavailable executable or working directory")
        port_owners = _profile_port_owners(spec.readiness_url, self.process_tree_pids())
        if port_owners:
            owner_pids = sorted({int(item["pid"]) for item in port_owners})
            raise LifecycleError(
                f"managed service {spec.name} target listener is already occupied by PID(s) {owner_pids}"
            )
        spec.log_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path = spec.stderr_log_path or spec.log_path.with_name(
            f"{spec.log_path.stem}.stderr{spec.log_path.suffix}"
        )
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        command = [str(executable), *spec.arguments]
        secret_values = tuple(
            sorted(
                set(_secret_bytes(spec.environment) + _redaction_bytes(spec.redaction_values)),
                key=len,
                reverse=True,
            )
        )
        secret_text_values = [value.decode("utf-8", errors="surrogatepass") for value in secret_values]
        if any(secret in argument for secret in secret_text_values for argument in spec.arguments):
            raise LifecycleError(f"managed service {spec.name} must receive secrets through its process environment")
        safe_command = [str(executable), *redact_argv(list(spec.arguments))]
        command_hash = "sha256:" + hashlib.sha256(canonical_json(safe_command).encode("utf-8")).hexdigest()
        child_environment = build_child_environment(
            spec.environment,
            allowed_names=spec.environment_allowlist,
        )
        stdout_handle = spec.log_path.open("ab")
        stderr_handle = stderr_path.open("ab")
        try:
            if os.name == "nt":
                process, job = _start_windows_job_process(
                    command,
                    cwd=cwd,
                    environment=child_environment,
                )
            else:
                process = subprocess.Popen(
                    command,
                    cwd=cwd,
                    env=child_environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                    close_fds=True,
                    creationflags=0,
                )
                job = None
        except (OSError, LifecycleError) as exc:
            stdout_handle.close()
            stderr_handle.close()
            if isinstance(exc, LifecycleError):
                raise
            raise LifecycleError(
                f"managed service {spec.name} failed to start: {type(exc).__name__}"
            ) from exc
        self._owned.append(
            _OwnedProcess(
                spec=spec,
                process=process,
                job=job,
                stdout_handle=stdout_handle,
                stderr_handle=stderr_handle,
                command_hash=command_hash,
                executable_sha256=_file_sha256(executable),
                parent_pid=os.getpid(),
                started_at=_utc_now(),
            )
        )
        owned = self._owned[-1]
        if owned.job is not None and process.pid not in owned.job.process_ids():
            raise LifecycleError(
                f"managed service {spec.name} root process is not present in its Windows job"
            )
        assert process.stdout is not None and process.stderr is not None
        stdout_thread = threading.Thread(
            target=_copy_redacted_log,
            args=(process.stdout, stdout_handle, secret_values),
            name=f"d4-log-{spec.name}-stdout",
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_copy_redacted_log,
            args=(process.stderr, stderr_handle, secret_values),
            name=f"d4-log-{spec.name}-stderr",
            daemon=True,
        )
        owned.log_threads = (stdout_thread, stderr_thread)
        stdout_thread.start()
        stderr_thread.start()
        if owned.job is not None:
            _resume_suspended_primary_thread(process.pid)
        await self._wait_ready(self._owned[-1])

    async def _wait_ready(self, owned: _OwnedProcess) -> None:
        deadline = time.monotonic() + self.startup_timeout_seconds
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(owned.spec.readiness_request_timeout_seconds),
            trust_env=False,
            follow_redirects=False,
        ) as client:
            while time.monotonic() < deadline:
                if owned.process.poll() is not None:
                    raise LifecycleError(f"managed service {owned.spec.name} exited during startup")
                if urlparse(owned.spec.readiness_url).scheme == "tcp":
                    if await self._tcp_is_open(owned.spec.readiness_url):
                        owned.readiness_verified = True
                        return
                else:
                    try:
                        response = await client.get(owned.spec.readiness_url)
                        if response.status_code == 200:
                            if owned.spec.readiness_kind == "http-200":
                                owned.readiness_verified = True
                                return
                            if _is_ready(owned.spec.readiness_kind, response.json()):
                                owned.readiness_verified = True
                                return
                    except (httpx.HTTPError, ValueError):
                        pass
                await asyncio.sleep(0.25)
        raise LifecycleError(f"managed service {owned.spec.name} did not become ready before timeout")

    def identities(self) -> list[dict[str, Any]]:
        return [
            {
                "name": owned.spec.name,
                "pid": owned.process.pid,
                "parent_pid": owned.parent_pid,
                "process_tree_pids": (
                    owned.job.process_ids() if owned.job is not None else [owned.process.pid]
                ),
                "job_active_process_count": (
                    owned.job.active_process_count() if owned.job is not None else None
                ),
                "executable": str(owned.spec.executable.resolve()),
                "executable_sha256": owned.executable_sha256,
                "argv_redacted": [
                    str(owned.spec.executable.resolve()),
                    *redact_argv(list(owned.spec.arguments)),
                ],
                "cwd": str(owned.spec.cwd.resolve()),
                "command_sha256": owned.command_hash,
                "readiness_url": owned.spec.readiness_url,
                "log_path": str(owned.spec.log_path.resolve()),
                "stderr_log_path": str(
                    (owned.spec.stderr_log_path or owned.spec.log_path.with_name(
                        f"{owned.spec.log_path.stem}.stderr{owned.spec.log_path.suffix}"
                    )).resolve()
                ),
                "started_at": owned.started_at,
                "stopped_at": owned.stopped_at,
                "return_code": owned.return_code if owned.return_code is not None else owned.process.poll(),
                "health": {
                    "readiness_kind": owned.spec.readiness_kind,
                    "verified": owned.readiness_verified,
                },
                "ownership": owned.spec.ownership_type,
                "interpreter_version": owned.spec.interpreter_version,
                "package_lock_identity": dict(owned.spec.package_lock_identity or {}),
                "shutdown_method": owned.shutdown_method,
            }
            for owned in self._owned
        ]

    def process_tree_pids(self) -> set[int]:
        """Return only PIDs currently owned by the fixed service jobs."""

        return {
            int(pid)
            for owned in self._owned
            for pid in (
                owned.job.process_ids()
                if owned.job is not None
                else [owned.process.pid]
            )
        }

    def service_process_tree_pids(self, name: str) -> set[int]:
        owned = next((item for item in self._owned if item.spec.name == name), None)
        if owned is None:
            raise LifecycleError(f"managed service {name} is not owned by this supervisor")
        return {
            int(pid)
            for pid in (
                owned.job.process_ids()
                if owned.job is not None
                else [owned.process.pid]
            )
        }

    def lifecycle_snapshot(self) -> list[dict[str, Any]]:
        """Return auditable identities without serializing environment values."""

        rows: list[dict[str, Any]] = []
        for owned in self._owned:
            executable = str(owned.spec.executable.resolve())
            stderr_path = owned.spec.stderr_log_path or owned.spec.log_path.with_name(
                f"{owned.spec.log_path.stem}.stderr{owned.spec.log_path.suffix}"
            )
            rows.append(
                {
                    "service_name": owned.spec.name,
                    "pid": owned.process.pid,
                    "parent_pid": owned.parent_pid,
                    "process_tree_pids": (
                        owned.job.process_ids()
                        if owned.job is not None
                        else [owned.process.pid]
                    ),
                    "job_active_process_count": (
                        owned.job.active_process_count()
                        if owned.job is not None
                        else None
                    ),
                    "executable": executable,
                    "executable_sha256": owned.executable_sha256,
                    "argv_redacted": [executable, *redact_argv(list(owned.spec.arguments))],
                    "cwd": str(owned.spec.cwd.resolve()),
                    "started_at": owned.started_at,
                    "stopped_at": owned.stopped_at,
                    "return_code": owned.return_code if owned.return_code is not None else owned.process.poll(),
                    "command_sha256": owned.command_hash,
                    "listener": owned.spec.readiness_url,
                    "health": {
                        "readiness_kind": owned.spec.readiness_kind,
                        "verified": owned.readiness_verified,
                    },
                    "ownership": owned.spec.ownership_type,
                    "interpreter_version": owned.spec.interpreter_version,
                    "package_lock_identity": dict(owned.spec.package_lock_identity or {}),
                    "stdout_log": str(owned.spec.log_path.resolve()),
                    "stderr_log": str(stderr_path.resolve()),
                    "shutdown_method": owned.shutdown_method,
                }
            )
        return rows

    async def _stop_owned(self, owned: _OwnedProcess) -> tuple[dict[str, Any], list[str]]:
        if owned.job is not None:
            return await self._stop_job_owned(owned)
        process = owned.process
        errors: list[str] = []
        if process.poll() is None:
            try:
                if os.name == "nt" and hasattr(signal, "CTRL_BREAK_EVENT"):
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                    owned.shutdown_method = "CTRL_BREAK_EVENT"
                else:
                    process.send_signal(signal.SIGTERM)
                    owned.shutdown_method = "SIGTERM"
            except OSError:
                process.terminate()
                owned.shutdown_method = "TERMINATE_FALLBACK"
            try:
                await asyncio.to_thread(process.wait, self.shutdown_timeout_seconds)
            except subprocess.TimeoutExpired:
                process.terminate()
                owned.shutdown_method = "TERMINATE_FALLBACK"
                try:
                    await asyncio.to_thread(process.wait, min(self.shutdown_timeout_seconds, 2.0))
                except subprocess.TimeoutExpired:
                    process.kill()
                    owned.shutdown_method = "KILL_FALLBACK"
                    await asyncio.to_thread(process.wait)
        elif owned.shutdown_method is None:
            owned.shutdown_method = "ALREADY_EXITED"

        exit_code = process.poll()
        owned.return_code = exit_code
        owned.stopped_at = _utc_now()
        if exit_code is None:
            errors.append(f"{owned.spec.name}: process still running")
        for thread in owned.log_threads:
            thread.join(timeout=max(2.0, self.shutdown_timeout_seconds))
            if thread.is_alive():
                errors.append(f"{owned.spec.name}: log capture did not close")
        if not owned.stdout_handle.closed:
            owned.stdout_handle.close()
        if not owned.stderr_handle.closed:
            owned.stderr_handle.close()
        endpoint_down = await self._wait_endpoint_down(owned.spec.readiness_url)
        if not endpoint_down:
            errors.append(f"{owned.spec.name}: readiness endpoint remained available after stop")
        outcome = {
            "name": owned.spec.name,
            "pid": process.pid,
            "parent_pid": owned.parent_pid,
            "executable": str(owned.spec.executable.resolve()),
            "argv_redacted": [
                str(owned.spec.executable.resolve()),
                *redact_argv(list(owned.spec.arguments)),
            ],
            "cwd": str(owned.spec.cwd.resolve()),
            "started_at": owned.started_at,
            "stopped_at": owned.stopped_at,
            "exit_code": exit_code,
            "return_code": exit_code,
            "endpoint_down": endpoint_down,
            "stopped": exit_code is not None and endpoint_down,
            "listener": owned.spec.readiness_url,
            "readiness_verified": owned.readiness_verified,
            "ownership": owned.spec.ownership_type,
            "interpreter_version": owned.spec.interpreter_version,
            "package_lock_identity": dict(owned.spec.package_lock_identity or {}),
            "stdout_log": str(owned.spec.log_path.resolve()),
            "stderr_log": str(
                (owned.spec.stderr_log_path or owned.spec.log_path.with_name(
                    f"{owned.spec.log_path.stem}.stderr{owned.spec.log_path.suffix}"
                )).resolve()
            ),
            "shutdown_method": owned.shutdown_method,
        }
        return outcome, errors

    async def _stop_job_owned(
        self, owned: _OwnedProcess
    ) -> tuple[dict[str, Any], list[str]]:
        """Stop one Windows service and every descendant in its dedicated Job."""

        process = owned.process
        job = owned.job
        errors: list[str] = []
        initial_process_ids: list[int] = []
        try:
            initial_process_ids = job.process_ids()
        except LifecycleError:
            errors.append(f"{owned.spec.name}: process ownership inventory failed")

        graceful_deadline = time.monotonic() + self.shutdown_timeout_seconds
        if process.poll() is None:
            try:
                process.send_signal(signal.CTRL_BREAK_EVENT)
                owned.shutdown_method = "CTRL_BREAK_EVENT"
            except (OSError, LifecycleError):
                owned.shutdown_error = "GRACEFUL_CTRL_BREAK_UNAVAILABLE"
                graceful_deadline = time.monotonic() + min(
                    self.shutdown_timeout_seconds, 1.0
                )
            try:
                wait_seconds = max(0.0, graceful_deadline - time.monotonic())
                await asyncio.to_thread(process.wait, wait_seconds)
            except subprocess.TimeoutExpired:
                pass

        try:
            wait_seconds = max(0.0, graceful_deadline - time.monotonic())
            empty = await asyncio.to_thread(job.wait_empty, wait_seconds)
        except LifecycleError:
            empty = False
            errors.append(f"{owned.spec.name}: Windows job state could not be verified")

        if empty and process.poll() is None:
            empty = False
            errors.append(f"{owned.spec.name}: root process is outside the reported job state")

        if not empty:
            try:
                job.terminate()
                owned.shutdown_method = "JOB_OBJECT_TERMINATE_FALLBACK"
            except LifecycleError:
                errors.append(f"{owned.spec.name}: bounded Windows job termination failed")
            try:
                await asyncio.to_thread(
                    process.wait, min(self.shutdown_timeout_seconds, 2.0)
                )
            except subprocess.TimeoutExpired:
                pass
            try:
                empty = await asyncio.to_thread(
                    job.wait_empty, min(self.shutdown_timeout_seconds, 2.0)
                )
            except LifecycleError:
                empty = False
                errors.append(f"{owned.spec.name}: Windows job state could not be verified")

        remaining_process_ids: list[int] = []
        if not empty:
            try:
                remaining_process_ids = job.process_ids()
            except LifecycleError:
                errors.append(f"{owned.spec.name}: remaining process ownership is unknown")
            errors.append(f"{owned.spec.name}: owned process tree did not exit")
        else:
            if owned.shutdown_method is None:
                owned.shutdown_method = "ALREADY_EXITED"
            try:
                job.close()
                owned.job = None
            except LifecycleError:
                errors.append(f"{owned.spec.name}: Windows job handle did not close")

        exit_code = process.poll()
        if exit_code is None:
            errors.append(f"{owned.spec.name}: process still running")
        owned.return_code = exit_code
        active_after: int | None = None
        if owned.job is not None:
            try:
                active_after = owned.job.active_process_count()
                remaining_process_ids = owned.job.process_ids()
            except LifecycleError:
                errors.append(f"{owned.spec.name}: remaining Windows job state is unknown")
        else:
            active_after = 0
            owned.stopped_at = _utc_now()
            for thread in owned.log_threads:
                thread.join(timeout=max(2.0, self.shutdown_timeout_seconds))
                if thread.is_alive():
                    errors.append(f"{owned.spec.name}: log capture did not close")
            if not owned.stdout_handle.closed:
                owned.stdout_handle.close()
            if not owned.stderr_handle.closed:
                owned.stderr_handle.close()
        endpoint_down = await self._wait_endpoint_down(owned.spec.readiness_url)
        if not endpoint_down:
            errors.append(f"{owned.spec.name}: readiness endpoint remained available after stop")
        outcome = {
            "name": owned.spec.name,
            "pid": process.pid,
            "parent_pid": owned.parent_pid,
            "process_tree_pids_before_stop": initial_process_ids,
            "remaining_process_tree_pids": remaining_process_ids,
            "job_active_process_count_after_stop": active_after,
            "executable": str(owned.spec.executable.resolve()),
            "executable_sha256": owned.executable_sha256,
            "argv_redacted": [
                str(owned.spec.executable.resolve()),
                *redact_argv(list(owned.spec.arguments)),
            ],
            "cwd": str(owned.spec.cwd.resolve()),
            "started_at": owned.started_at,
            "stopped_at": owned.stopped_at,
            "exit_code": exit_code,
            "return_code": exit_code,
            "endpoint_down": endpoint_down,
            "stopped": (
                exit_code is not None
                and owned.job is None
                and active_after == 0
                and not remaining_process_ids
                and endpoint_down
            ),
            "listener": owned.spec.readiness_url,
            "readiness_verified": owned.readiness_verified,
            "ownership": owned.spec.ownership_type,
            "interpreter_version": owned.spec.interpreter_version,
            "package_lock_identity": dict(owned.spec.package_lock_identity or {}),
            "stdout_log": str(owned.spec.log_path.resolve()),
            "stderr_log": str(
                (owned.spec.stderr_log_path or owned.spec.log_path.with_name(
                    f"{owned.spec.log_path.stem}.stderr{owned.spec.log_path.suffix}"
                )).resolve()
            ),
            "shutdown_method": owned.shutdown_method,
            "shutdown_error": owned.shutdown_error,
        }
        return outcome, errors

    async def close(self) -> dict[str, Any]:
        if self._closed:
            return {"cleanup_verified": True, "services": [], "errors": []}
        outcomes: list[dict[str, Any]] = []
        errors: list[str] = []
        for owned in reversed(list(self._owned)):
            outcome, service_errors = await self._stop_owned(owned)
            outcomes.append(outcome)
            errors.extend(service_errors)
            if service_errors:
                continue
            self._owned.remove(owned)
        self._closed = not self._owned
        return {"cleanup_verified": not errors, "services": list(reversed(outcomes)), "errors": errors}

    async def _wait_endpoint_down(self, url: str) -> bool:
        deadline = time.monotonic() + min(self.shutdown_timeout_seconds, 3.0)
        host, port = _loopback_parts(url)
        listener_url = f"tcp://{host}:{port}"
        while time.monotonic() < deadline:
            if not await self._tcp_is_open(listener_url):
                return True
            await asyncio.sleep(0.1)
        return False

    async def _tcp_is_open(self, url: str) -> bool:
        host, port = _loopback_parts(url)
        try:
            _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=0.2)
        except (OSError, TimeoutError):
            return False
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
        return True
