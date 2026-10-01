"""Read-only native Windows process identity capture for formal-port ownership checks."""

from __future__ import annotations

import ctypes
import hashlib
import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .process_lifecycle import ProcessSpec, redact_argv


class _FileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]


class _ProcessEntry32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("cntUsage", ctypes.c_uint32),
        ("th32ProcessID", ctypes.c_uint32),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", ctypes.c_uint32),
        ("cntThreads", ctypes.c_uint32),
        ("th32ParentProcessID", ctypes.c_uint32),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_uint32),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


class _UnicodeString(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint16), ("maximum_length", ctypes.c_uint16), ("buffer", ctypes.c_void_p)]


class _ProcessBasicInformation(ctypes.Structure):
    _fields_ = [
        ("reserved1", ctypes.c_void_p),
        ("peb_base_address", ctypes.c_void_p),
        ("reserved2_0", ctypes.c_void_p),
        ("reserved2_1", ctypes.c_void_p),
        ("unique_process_id", ctypes.c_size_t),
        ("inherited_from_unique_process_id", ctypes.c_size_t),
    ]


def _raise_winerror(label: str) -> RuntimeError:
    return RuntimeError(f"{label}:winerror-{ctypes.get_last_error()}")


def _process_parent_map() -> dict[int, int]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ProcessEntry32W)]
    kernel32.Process32FirstW.restype = ctypes.c_int
    kernel32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ProcessEntry32W)]
    kernel32.Process32NextW.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if not snapshot or snapshot == ctypes.c_void_p(-1).value:
        raise _raise_winerror("toolhelp-snapshot")
    result: dict[int, int] = {}
    try:
        entry = _ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(entry)
        found = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            result[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            found = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return result


def _read_process_memory(kernel32: Any, process: int, address: int, length: int) -> bytes:
    buffer = ctypes.create_string_buffer(length)
    read = ctypes.c_size_t()
    if not kernel32.ReadProcessMemory(
        ctypes.c_void_p(process), ctypes.c_void_p(address), buffer, length, ctypes.byref(read)
    ) or read.value != length:
        raise _raise_winerror("read-process-memory")
    return buffer.raw


def _command_line(ntdll: Any, process: int) -> str:
    returned = ctypes.c_uint32()
    status = ntdll.NtQueryInformationProcess(
        ctypes.c_void_p(process), 60, None, 0, ctypes.byref(returned)
    )
    if returned.value < ctypes.sizeof(_UnicodeString) or returned.value > 1_048_576:
        raise RuntimeError(f"process-command-line-size-invalid:ntstatus-{status & 0xffffffff:08x}")
    buffer = ctypes.create_string_buffer(returned.value)
    status = ntdll.NtQueryInformationProcess(
        ctypes.c_void_p(process), 60, ctypes.byref(buffer), returned.value, ctypes.byref(returned)
    )
    if status < 0:
        raise RuntimeError(f"process-command-line-query-failed:ntstatus-{status & 0xffffffff:08x}")
    value = _UnicodeString.from_buffer(buffer)
    if value.length % 2 or value.length > value.maximum_length or value.length > 65_536:
        raise RuntimeError("process-command-line-buffer-invalid")
    return ctypes.string_at(value.buffer, value.length).decode("utf-16-le", errors="replace")


def _current_directory(kernel32: Any, ntdll: Any, process: int, is_wow64: bool) -> str:
    basic = _ProcessBasicInformation()
    returned = ctypes.c_uint32()
    status = ntdll.NtQueryInformationProcess(
        ctypes.c_void_p(process), 0, ctypes.byref(basic), ctypes.sizeof(basic), ctypes.byref(returned)
    )
    if status < 0 or not basic.peb_base_address:
        raise RuntimeError(f"process-basic-information-failed:ntstatus-{status & 0xffffffff:08x}")
    pointer_size = 4 if is_wow64 else ctypes.sizeof(ctypes.c_void_p)
    peb_address = int(basic.peb_base_address)
    if is_wow64:
        peb32 = ctypes.c_size_t()
        status = ntdll.NtQueryInformationProcess(
            ctypes.c_void_p(process), 26, ctypes.byref(peb32), ctypes.sizeof(peb32), ctypes.byref(returned)
        )
        if status < 0 or not peb32.value:
            raise RuntimeError(f"wow64-peb-query-failed:ntstatus-{status & 0xffffffff:08x}")
        peb_address = int(peb32.value)
    process_parameters_offset = 0x10 if pointer_size == 4 else 0x20
    pointer_bytes = _read_process_memory(
        kernel32, process, peb_address + process_parameters_offset, pointer_size
    )
    process_parameters = int.from_bytes(pointer_bytes, "little")
    current_dir_offset = 0x24 if pointer_size == 4 else 0x38
    unicode_size = 8 if pointer_size == 4 else 16
    raw = _read_process_memory(
        kernel32, process, process_parameters + current_dir_offset, unicode_size
    )
    byte_length = int.from_bytes(raw[0:2], "little")
    if byte_length == 0 or byte_length > 32_768 or byte_length % 2:
        raise RuntimeError("process-current-directory-length-invalid")
    pointer_offset = 4 if pointer_size == 4 else 8
    string_address = int.from_bytes(raw[pointer_offset : pointer_offset + pointer_size], "little")
    text = _read_process_memory(kernel32, process, string_address, byte_length)
    return text.decode("utf-16-le", errors="replace")


def _file_sha256(path: str) -> str | None:
    try:
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return None


def _normalized_absolute_path(value: str | Path) -> str | None:
    """Normalize a process path without resolving aliases to another executable."""

    candidate = Path(str(value))
    if not candidate.is_absolute():
        return None
    return os.path.normcase(os.path.normpath(os.path.abspath(str(candidate))))


def capture_process_identity(process_id: int, *, include_parent: bool = False) -> dict[str, Any]:
    """Capture exact process identity fields where Windows grants read access."""

    if os.name != "nt":
        raise RuntimeError("native Windows process identity capture is unavailable")
    if isinstance(process_id, bool) or not isinstance(process_id, int) or process_id <= 0:
        raise ValueError("process id must be a positive integer")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32)]
    kernel32.QueryFullProcessImageNameW.restype = ctypes.c_int
    kernel32.GetProcessTimes.argtypes = [ctypes.c_void_p, ctypes.POINTER(_FileTime), ctypes.POINTER(_FileTime), ctypes.POINTER(_FileTime), ctypes.POINTER(_FileTime)]
    kernel32.GetProcessTimes.restype = ctypes.c_int
    kernel32.IsWow64Process.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
    kernel32.IsWow64Process.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    ntdll.NtQueryInformationProcess.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
    ntdll.NtQueryInformationProcess.restype = ctypes.c_long

    handle = kernel32.OpenProcess(0x1000 | 0x0400 | 0x0010, 0, process_id)
    if not handle:
        raise _raise_winerror("open-process-query")
    errors: dict[str, str] = {}
    try:
        image_buffer = ctypes.create_unicode_buffer(32_768)
        image_length = ctypes.c_uint32(len(image_buffer))
        executable = None
        if kernel32.QueryFullProcessImageNameW(handle, 0, image_buffer, ctypes.byref(image_length)):
            executable = image_buffer.value
        else:
            errors["executable"] = f"winerror-{ctypes.get_last_error()}"

        command_line = None
        argv: list[str] | None = None
        try:
            command_line = _command_line(ntdll, int(handle))
            shell32 = ctypes.WinDLL("shell32", use_last_error=True)
            shell32.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
            shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
            count = ctypes.c_int()
            command_args = shell32.CommandLineToArgvW(command_line, ctypes.byref(count))
            if command_args:
                argv = [command_args[index] for index in range(count.value)]
                kernel32.LocalFree.argtypes = [ctypes.c_void_p]
                kernel32.LocalFree.restype = ctypes.c_void_p
                kernel32.LocalFree(command_args)
            else:
                errors["argv"] = f"winerror-{ctypes.get_last_error()}"
        except Exception as exc:
            errors["command_line"] = type(exc).__name__

        cwd = None
        is_wow64 = ctypes.c_int()
        if not kernel32.IsWow64Process(handle, ctypes.byref(is_wow64)):
            errors["architecture"] = f"winerror-{ctypes.get_last_error()}"
        else:
            try:
                cwd = _current_directory(kernel32, ntdll, int(handle), bool(is_wow64.value))
            except Exception as exc:
                errors["cwd"] = type(exc).__name__

        creation = _FileTime()
        exit_time = _FileTime()
        kernel_time = _FileTime()
        user_time = _FileTime()
        started_at = None
        if kernel32.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(kernel_time), ctypes.byref(user_time)):
            ticks = (int(creation.high) << 32) | int(creation.low)
            unix_seconds = ticks / 10_000_000 - 11_644_473_600
            started_at = datetime.fromtimestamp(unix_seconds, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        else:
            errors["start_time"] = f"winerror-{ctypes.get_last_error()}"
    finally:
        kernel32.CloseHandle(handle)
    parents = _process_parent_map()
    parent_pid = parents.get(process_id)
    result = {
        "pid": process_id,
        "parent_pid": parent_pid,
        "executable": executable,
        "executable_sha256": _file_sha256(executable) if executable else None,
        "command_line": command_line,
        "argv": argv,
        "argv_redacted": redact_argv(argv) if argv else None,
        "cwd": cwd,
        "started_at": started_at,
        "capture_errors": errors,
        "identity_complete": bool(executable and argv and cwd and started_at),
    }
    if include_parent and parent_pid:
        try:
            result["parent_identity"] = capture_process_identity(parent_pid)
        except Exception as exc:
            result["parent_identity_error"] = type(exc).__name__
    return result


def matches_exact_profile(identity: dict[str, Any], spec: ProcessSpec) -> bool:
    """Return true only when executable, argv, cwd, and binary hash all match."""

    if not identity.get("identity_complete"):
        return False
    try:
        lock = spec.package_lock_identity or {}
        expected_executable = _normalized_absolute_path(spec.executable)
        executable = _normalized_absolute_path(identity["executable"])
        expected_image = _normalized_absolute_path(
            lock.get("process_image_executable", spec.executable)
        )
        cwd = _normalized_absolute_path(identity["cwd"])
        expected_cwd = _normalized_absolute_path(spec.cwd)
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        return False
    if not all((expected_executable, executable, expected_image, cwd, expected_cwd)):
        return False
    actual_argv = identity.get("argv")
    expected_argv = [expected_executable, *spec.arguments]
    expected_image_hash = next(
        (
            str(lock[key])
            for key in (
                "process_image_sha256",
                "binary_sha256",
                "mysql_executable_sha256",
                "python_executable_sha256",
            )
            if lock.get(key)
        ),
        _file_sha256(str(expected_image)),
    )
    expected_launch_hash = next(
        (
            str(lock[key])
            for key in (
                "launch_executable_sha256",
                "python_executable_sha256",
                "mysql_executable_sha256",
                "binary_sha256",
            )
            if lock.get(key)
        ),
        None,
    )
    actual_argv0 = (
        _normalized_absolute_path(actual_argv[0])
        if isinstance(actual_argv, list) and actual_argv
        else None
    )
    return (
        executable == expected_image
        and cwd == expected_cwd
        and isinstance(actual_argv, list)
        and len(actual_argv) == len(expected_argv)
        and actual_argv0 == expected_executable
        and actual_argv[1:] == list(spec.arguments)
        and identity.get("executable_sha256") == expected_image_hash
        and (
            expected_launch_hash is None
            or _file_sha256(str(expected_executable)) == expected_launch_hash
        )
    )


def matches_exact_prior_runtime_identity(identity: dict[str, Any], launcher_spec: ProcessSpec) -> bool:
    """Match the accepted R1 venv launcher plus its known CPython listener child."""

    from .service_profiles import (
        RUNTIME_BASE_PYTHON,
        RUNTIME_BASE_PYTHON_ARGV0,
        RUNTIME_BASE_PYTHON_ARGV0_SHA256,
        RUNTIME_BASE_PYTHON_SHA256,
    )

    parent = identity.get("parent_identity")
    if not isinstance(parent, dict):
        return False
    launcher_lock = {
        key: value
        for key, value in (launcher_spec.package_lock_identity or {}).items()
        if key not in {"process_image_executable", "process_image_sha256"}
    }
    parent_profile = replace(launcher_spec, package_lock_identity=launcher_lock)
    try:
        parent_cwd = _normalized_absolute_path(parent["cwd"])
        allowed_parent_cwds = {
            _normalized_absolute_path(launcher_spec.cwd),
            *(
                _normalized_absolute_path(os.environ[name])
                for name in ("TEMP", "TMP")
                if os.environ.get(name)
            ),
        }
        allowed_parent_cwds.discard(None)
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        return False
    if parent_cwd not in allowed_parent_cwds:
        return False
    # Windows' venv launcher can change its own CWD to the inherited temp path
    # after spawning the base-Python listener. Accept only that exact inherited
    # TEMP/TMP directory; the listener itself must retain the fixed source CWD.
    parent_profile = replace(parent_profile, cwd=Path(parent["cwd"]))
    if not matches_exact_profile(parent, parent_profile):
        return False
    listener_spec = ProcessSpec(
        name="d4-runtime-prior-r1-listener",
        executable=RUNTIME_BASE_PYTHON_ARGV0,
        arguments=launcher_spec.arguments,
        cwd=launcher_spec.cwd,
        environment={},
        readiness_url=launcher_spec.readiness_url,
        readiness_kind=launcher_spec.readiness_kind,
        log_path=launcher_spec.log_path,
        package_lock_identity={
            "python_executable_sha256": RUNTIME_BASE_PYTHON_ARGV0_SHA256,
            "process_image_executable": str(RUNTIME_BASE_PYTHON),
            "process_image_sha256": RUNTIME_BASE_PYTHON_SHA256,
        },
        environment_allowlist=frozenset(),
    )
    if not matches_exact_profile(identity, listener_spec):
        return False
    return int(parent.get("pid", -1)) == int(identity.get("parent_pid", -2))


def stop_exact_stale_process(
    identity: dict[str, Any],
    spec: ProcessSpec,
    *,
    matcher: Any = None,
) -> dict[str, Any]:
    """Stop only an exact, single-process prior D4 profile; never kill an unknown owner."""

    exact_match = matcher or matches_exact_profile
    if os.name != "nt" or not exact_match(identity, spec):
        raise RuntimeError("stale-process-identity-does-not-match-fixed-profile")
    process_id = int(identity["pid"])
    parents = _process_parent_map()
    if any(parent == process_id for parent in parents.values()):
        raise RuntimeError("stale-profile-has-descendants-and-cannot-be-safely-detached")
    current = capture_process_identity(
        process_id,
        include_parent=bool(identity.get("parent_identity")),
    )
    if (
        not exact_match(current, spec)
        or current.get("started_at") != identity.get("started_at")
    ):
        raise RuntimeError("stale-process-identity-changed-before-stop")

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GenerateConsoleCtrlEvent.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    kernel32.GenerateConsoleCtrlEvent.restype = ctypes.c_int
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.TerminateProcess.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    handle = kernel32.OpenProcess(0x00100001, 0, process_id)
    if not handle:
        raise _raise_winerror("open-process-stop")
    graceful = False
    try:
        # This can succeed only for the exact process group whose ID is its leader PID.
        graceful = bool(kernel32.GenerateConsoleCtrlEvent(1, process_id))
        if kernel32.WaitForSingleObject(handle, 1500) == 0:
            return {"pid": process_id, "stopped": True, "shutdown_method": "CTRL_BREAK_EVENT"}
        if not kernel32.TerminateProcess(handle, 0xD403):
            raise _raise_winerror("terminate-exact-stale-process")
        if kernel32.WaitForSingleObject(handle, 3000) != 0:
            raise RuntimeError("exact-stale-process-did-not-exit-within-bound")
        return {
            "pid": process_id,
            "stopped": True,
            "shutdown_method": "TERMINATE_PROCESS_FALLBACK",
            "graceful_signal_sent": graceful,
        }
    finally:
        kernel32.CloseHandle(handle)
