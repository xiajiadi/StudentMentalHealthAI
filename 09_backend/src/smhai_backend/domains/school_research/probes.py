"""Private CAT process readiness and exact Windows listener ownership probes."""

from __future__ import annotations

import ctypes
import datetime as dt
import json
import math
import os
import re
import socket
import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

_READY_SCHEMA = "psynova.research-service-ready.v1"
_READY_FIELDS = frozenset(
    {
        "schema",
        "status",
        "research_only",
        "clinical_approval",
        "school_approval",
        "service_config_sha256",
        "registry_fingerprint",
        "binding_count",
        "school_scope",
    }
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_BEARER = re.compile(r"[A-Za-z0-9_-]{32,512}\Z")
_SCHOOL_SCOPE = re.compile(r"school:[1-9][0-9]{0,17}\Z")
_MAX_READY_BODY_BYTES = 8 * 1024
_MAX_BINDINGS = 128
_MAX_TCP_TABLE_BYTES = 4 * 1024 * 1024
_WINDOWS_EPOCH = dt.datetime(1601, 1, 1, tzinfo=dt.UTC)
_FILETIME_TICKS_PER_SECOND = 10_000_000


class ResearchCATProbeError(RuntimeError):
    """Fixed-code probe failure that contains no request or OS details."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code) is None:
            code = "probe_failed"
        self.code = code
        super().__init__(code)


class ResearchCATReadinessProbe:
    """Bounded loopback-only readiness callback for ``ResearchCATProcessManager``."""

    def __init__(
        self,
        *,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        if client_factory is not None and not callable(client_factory):
            raise TypeError("HTTP client factory is invalid")
        self._client_factory = client_factory or httpx.Client

    def __repr__(self) -> str:
        return "ResearchCATReadinessProbe(endpoint=<loopback>, bearer=<per-call-redacted>)"

    def __call__(self, port: int, bearer_token: bytes, timeout_seconds: float) -> dict[str, object]:
        if (
            type(port) is not int
            or not 1 <= port <= 65535
            or type(bearer_token) is not bytes
            or type(timeout_seconds) not in {int, float}
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 120
        ):
            raise ResearchCATProbeError("readiness_probe_input_invalid")
        try:
            bearer_text = bearer_token.decode("ascii")
        except UnicodeDecodeError:
            raise ResearchCATProbeError("readiness_probe_input_invalid") from None
        if _BEARER.fullmatch(bearer_text) is None:
            raise ResearchCATProbeError("readiness_probe_input_invalid")

        url = f"http://127.0.0.1:{port}/_research/ready"
        headers = {
            "Authorization": f"Bearer {bearer_text}",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        }
        try:
            with self._client_factory(
                timeout=timeout_seconds,
                trust_env=False,
                follow_redirects=False,
            ) as client:
                with client.stream("GET", url, headers=headers) as response:
                    if response.status_code != 200:
                        raise ResearchCATProbeError("readiness_http_status_invalid")
                    media_type = response.headers.get("content-type", "")
                    if media_type.split(";", 1)[0].strip().casefold() != "application/json":
                        raise ResearchCATProbeError("readiness_content_type_invalid")
                    content_encoding = response.headers.get("content-encoding", "identity")
                    if content_encoding.casefold() not in {"", "identity"}:
                        raise ResearchCATProbeError("readiness_content_encoding_invalid")
                    declared_length = response.headers.get("content-length")
                    if declared_length is not None and (
                        not declared_length.isascii()
                        or not declared_length.isdecimal()
                        or int(declared_length) > _MAX_READY_BODY_BYTES
                    ):
                        raise ResearchCATProbeError("readiness_body_too_large")
                    raw = bytearray()
                    for chunk in response.iter_raw(chunk_size=1024):
                        raw.extend(chunk)
                        if len(raw) > _MAX_READY_BODY_BYTES:
                            raise ResearchCATProbeError("readiness_body_too_large")
                    return _parse_ready_body(bytes(raw))
        except ResearchCATProbeError:
            raise
        except Exception:
            # httpx exceptions can embed URLs, headers or request data. Do not
            # stringify or chain the upstream exception.
            raise ResearchCATProbeError("readiness_unavailable") from None


@dataclass(frozen=True, slots=True, repr=False)
class WindowsListenerOwnerProbe:
    """Read-only exact-Popen-PID and loopback listener ownership callback.

    The process image and creation time are checked independently of the TCP
    table. No command line, environment, process arguments or service payload
    is queried. Native Windows API readers may be replaced in tests only.
    """

    expected_executable: Path = field(repr=False)
    expected_creation_time_utc: dt.datetime | None = field(default=None, repr=False)
    _process_inspector: Callable[[int], ProcessIdentity] = field(
        default_factory=lambda: _windows_process_identity, repr=False, compare=False
    )
    _listener_reader: Callable[[int], tuple[ListenerRecord, ...]] = field(
        default_factory=lambda: _windows_ipv4_listener_rows, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if (
            not isinstance(self.expected_executable, Path)
            or not self.expected_executable.is_absolute()
        ):
            raise ResearchCATProbeError("owner_probe_config_invalid")
        if not callable(self._process_inspector) or not callable(self._listener_reader):
            raise ResearchCATProbeError("owner_probe_config_invalid")
        try:
            expected = self.expected_executable.resolve(strict=True)
        except (OSError, RuntimeError):
            raise ResearchCATProbeError("owner_probe_config_invalid") from None
        if not expected.is_file():
            raise ResearchCATProbeError("owner_probe_config_invalid")
        object.__setattr__(self, "expected_executable", expected)
        if self.expected_creation_time_utc is not None:
            _datetime_to_filetime(self.expected_creation_time_utc)

    def __repr__(self) -> str:
        return "WindowsListenerOwnerProbe(executable=<pinned>, creation_time=<pinned-or-unset>)"

    def __call__(self, pid: int, port: int) -> bool:
        if type(pid) is not int or pid <= 0 or type(port) is not int or not 1 <= port <= 65535:
            return False
        try:
            first = self._process_inspector(pid)
            if not self._identity_matches(pid, first):
                return False
            listeners = self._listener_reader(port)
            if type(listeners) is not tuple or len(listeners) != 1:
                return False
            listener = listeners[0]
            if (
                type(listener) is not ListenerRecord
                or type(listener.local_address) is not str
                or type(listener.local_port) is not int
                or type(listener.owning_pid) is not int
                or type(listener.state) is not str
                or listener.local_address != "127.0.0.1"
                or listener.local_port != port
                or listener.state != "LISTEN"
                or listener.owning_pid != pid
            ):
                return False
            # Guard against PID reuse while the TCP table was read.
            second = self._process_inspector(pid)
            return self._identity_matches(pid, second) and (
                first.creation_time_filetime == second.creation_time_filetime
                and _normcase_path(first.executable) == _normcase_path(second.executable)
            )
        except Exception:
            return False

    def _identity_matches(self, pid: int, identity: ProcessIdentity) -> bool:
        if (
            type(identity) is not ProcessIdentity
            or type(identity.pid) is not int
            or identity.pid != pid
            or type(identity.creation_time_filetime) is not int
            or identity.creation_time_filetime <= 0
            or not isinstance(identity.executable, Path)
        ):
            return False
        try:
            actual = identity.executable.resolve(strict=True)
        except (OSError, RuntimeError):
            return False
        if _normcase_path(actual) != _normcase_path(self.expected_executable):
            return False
        if self.expected_creation_time_utc is not None:
            expected_ticks = _datetime_to_filetime(self.expected_creation_time_utc)
            if abs(identity.creation_time_filetime - expected_ticks) > 10:
                return False
        return True


@dataclass(frozen=True, slots=True, repr=False)
class ProcessIdentity:
    pid: int
    executable: Path = field(repr=False)
    creation_time_filetime: int


@dataclass(frozen=True, slots=True, repr=False)
class ListenerRecord:
    local_address: str
    local_port: int
    owning_pid: int
    state: str


def _parse_ready_body(raw: bytes) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def finite_float(value: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("non-finite number")
        return number

    def reject_constant(_value: str) -> None:
        raise ValueError("non-finite constant")

    try:
        body = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
            parse_float=finite_float,
        )
    except Exception:
        raise ResearchCATProbeError("readiness_json_invalid") from None
    if (
        type(body) is not dict
        or set(body) != _READY_FIELDS
        or body.get("schema") != _READY_SCHEMA
        or body.get("status") != "READY"
        or body.get("research_only") is not True
        or body.get("clinical_approval") is not False
        or body.get("school_approval") is not False
        or type(body.get("service_config_sha256")) is not str
        or _SHA256.fullmatch(body["service_config_sha256"]) is None
        or type(body.get("registry_fingerprint")) is not str
        or _SHA256.fullmatch(body["registry_fingerprint"]) is None
        or type(body.get("binding_count")) is not int
        or not 1 <= body["binding_count"] <= _MAX_BINDINGS
        or type(body.get("school_scope")) is not str
        or _SCHOOL_SCOPE.fullmatch(body["school_scope"]) is None
    ):
        raise ResearchCATProbeError("readiness_schema_invalid")
    return body


def create_windows_listener_owner_probe(
    base_executable: Path,
    expected_creation_time_utc: dt.datetime | None = None,
) -> WindowsListenerOwnerProbe:
    """Pin an exact base-Python image and optional process creation time."""

    return WindowsListenerOwnerProbe(
        expected_executable=base_executable,
        expected_creation_time_utc=expected_creation_time_utc,
    )


def _windows_process_identity(pid: int) -> ProcessIdentity:
    if os.name != "nt":
        raise ResearchCATProbeError("windows_owner_probe_unavailable")
    from ctypes import wintypes

    class _FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    query_image = kernel32.QueryFullProcessImageNameW
    query_image.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.WCHAR),
        ctypes.POINTER(wintypes.DWORD),
    ]
    query_image.restype = wintypes.BOOL
    get_times = kernel32.GetProcessTimes
    get_times.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
    ]
    get_times.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    handle = open_process(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        raise ResearchCATProbeError("process_identity_unavailable")
    try:
        image = ctypes.create_unicode_buffer(32768)
        image_length = wintypes.DWORD(len(image))
        if not query_image(handle, 0, image, ctypes.byref(image_length)):
            raise ResearchCATProbeError("process_identity_unavailable")
        creation = _FILETIME()
        exit_time = _FILETIME()
        kernel_time = _FILETIME()
        user_time = _FILETIME()
        if not get_times(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            raise ResearchCATProbeError("process_identity_unavailable")
        ticks = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        return ProcessIdentity(pid=pid, executable=Path(image.value), creation_time_filetime=ticks)
    finally:
        close_handle(handle)


def _windows_ipv4_listener_rows(port: int) -> tuple[ListenerRecord, ...]:
    if os.name != "nt":
        raise ResearchCATProbeError("windows_owner_probe_unavailable")
    from ctypes import wintypes

    class _TCPROW_OWNER_PID(ctypes.Structure):
        _fields_ = [
            ("dwState", wintypes.DWORD),
            ("dwLocalAddr", wintypes.DWORD),
            ("dwLocalPort", wintypes.DWORD),
            ("dwRemoteAddr", wintypes.DWORD),
            ("dwRemotePort", wintypes.DWORD),
            ("dwOwningPid", wintypes.DWORD),
        ]

    iphlpapi = ctypes.WinDLL("iphlpapi", use_last_error=True)
    get_table = iphlpapi.GetExtendedTcpTable
    get_table.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.BOOL,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
    ]
    get_table.restype = wintypes.DWORD
    size = wintypes.DWORD(0)
    result = get_table(None, ctypes.byref(size), False, socket.AF_INET, 3, 0)
    if result == 0 and size.value <= ctypes.sizeof(wintypes.DWORD):
        return ()
    if (
        result != 122
        or size.value < ctypes.sizeof(wintypes.DWORD)
        or size.value > _MAX_TCP_TABLE_BYTES
    ):
        raise ResearchCATProbeError("listener_table_unavailable")
    buffer = ctypes.create_string_buffer(size.value)
    result = get_table(buffer, ctypes.byref(size), False, socket.AF_INET, 3, 0)
    if result != 0:
        raise ResearchCATProbeError("listener_table_unavailable")
    count = wintypes.DWORD.from_buffer(buffer).value
    row_size = ctypes.sizeof(_TCPROW_OWNER_PID)
    if ctypes.sizeof(wintypes.DWORD) + count * row_size > len(buffer):
        raise ResearchCATProbeError("listener_table_invalid")
    rows: list[ListenerRecord] = []
    for index in range(count):
        row = _TCPROW_OWNER_PID.from_buffer(
            buffer, ctypes.sizeof(wintypes.DWORD) + index * row_size
        )
        local_port = _decode_network_port_dword(row.dwLocalPort)
        if local_port != port:
            continue
        local_address = _decode_ipv4_dword(row.dwLocalAddr)
        rows.append(
            ListenerRecord(
                local_address=local_address,
                local_port=local_port,
                owning_pid=int(row.dwOwningPid),
                state="LISTEN" if row.dwState == 2 else "OTHER",
            )
        )
    return tuple(rows)


def _datetime_to_filetime(value: dt.datetime) -> int:
    if (
        not isinstance(value, dt.datetime)
        or value.tzinfo is None
        or value.utcoffset() != dt.timedelta(0)
    ):
        raise ResearchCATProbeError("owner_probe_config_invalid")
    delta = value.astimezone(dt.UTC) - _WINDOWS_EPOCH
    return (
        delta.days * 86400 + delta.seconds
    ) * _FILETIME_TICKS_PER_SECOND + delta.microseconds * 10


def _normcase_path(path: Path) -> str:
    return os.path.normcase(str(path))


def _decode_ipv4_dword(value: int) -> str:
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise ResearchCATProbeError("listener_table_invalid")
    # MIB_TCPROW_OWNER_PID stores the address in in_addr/DWORD representation.
    return socket.inet_ntoa(struct.pack("<I", value))


def _decode_network_port_dword(value: int) -> int:
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise ResearchCATProbeError("listener_table_invalid")
    # dwLocalPort uses network byte order in the low 16 bits.
    return socket.ntohs(value & 0xFFFF)
