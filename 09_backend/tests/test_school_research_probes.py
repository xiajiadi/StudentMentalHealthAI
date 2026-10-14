from __future__ import annotations

import datetime as dt
import json
import socket
from pathlib import Path

import pytest

from smhai_backend.domains.school_research.probes import (
    ListenerRecord,
    ProcessIdentity,
    ResearchCATProbeError,
    ResearchCATReadinessProbe,
    WindowsListenerOwnerProbe,
    _decode_ipv4_dword,
    _decode_network_port_dword,
)

_PORT = 58412
_PID = 5240
_BEARER = b"derived-only-probe-token-material-123456789"
_READY = {
    "schema": "psynova.research-service-ready.v1",
    "status": "READY",
    "research_only": True,
    "clinical_approval": False,
    "school_approval": False,
    "service_config_sha256": "a" * 64,
    "registry_fingerprint": "b" * 64,
    "binding_count": 1,
    "school_scope": "school:701",
}


class _FakeResponse:
    def __init__(self, raw: bytes, *, status_code: int = 200, headers=None) -> None:
        self.raw = raw
        self.status_code = status_code
        self.headers = headers or {
            "content-type": "application/json",
            "content-length": str(len(raw)),
        }
        self.iterated = False
        self.chunk_sizes: list[int | None] = []
        self.chunks_emitted = 0

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def iter_raw(self, *, chunk_size=None):
        self.iterated = True
        self.chunk_sizes.append(chunk_size)
        for start in range(0, len(self.raw), chunk_size or len(self.raw) or 1):
            self.chunks_emitted += 1
            yield self.raw[start : start + (chunk_size or len(self.raw) or 1)]


class _FakeClient:
    def __init__(self, response: _FakeResponse, settings: dict[str, object]) -> None:
        self.response = response
        self.settings = settings
        self.requests: list[tuple[str, str, dict[str, str]]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def stream(self, method, url, *, headers):
        self.requests.append((method, url, headers))
        return self.response


def _response(raw: bytes, *, status_code: int = 200, headers=None):
    response = _FakeResponse(raw, status_code=status_code, headers=headers)
    clients: list[_FakeClient] = []

    def factory(**settings):
        client = _FakeClient(response, settings)
        clients.append(client)
        return client

    return response, clients, factory


def test_readiness_probe_uses_literal_loopback_bearer_and_no_environment_proxy():
    raw = json.dumps(_READY, separators=(",", ":")).encode("utf-8")
    response, clients, factory = _response(raw)

    result = ResearchCATReadinessProbe(client_factory=factory)(_PORT, _BEARER, 0.75)

    assert result == _READY
    client = clients[0]
    assert client.settings == {
        "timeout": 0.75,
        "trust_env": False,
        "follow_redirects": False,
    }
    method, url, headers = client.requests[0]
    assert method == "GET"
    assert url == f"http://127.0.0.1:{_PORT}/_research/ready"
    assert headers["Authorization"] == f"Bearer {_BEARER.decode('ascii')}"
    assert headers["Accept-Encoding"] == "identity"
    assert response.iterated is True
    assert response.chunk_sizes == [1024]
    assert _BEARER.decode("ascii") not in repr(ResearchCATReadinessProbe(client_factory=factory))


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema":"one","schema":"two"}',
        json.dumps({**_READY, "extra": "closed schema"}).encode("utf-8"),
        json.dumps({**_READY, "binding_count": True}).encode("utf-8"),
        b'{"value":NaN}',
        b'{"value":1e999}',
        b"\xff",
    ],
)
def test_readiness_probe_rejects_duplicate_open_nonfinite_or_non_utf8_json(raw: bytes):
    _response_value, _clients, factory = _response(raw)

    with pytest.raises(ResearchCATProbeError):
        ResearchCATReadinessProbe(client_factory=factory)(_PORT, _BEARER, 1.0)


def test_readiness_probe_rejects_redirect_oversize_and_non_identity_encoding():
    redirect, _clients, factory = _response(b"{}", status_code=302)
    with pytest.raises(ResearchCATProbeError):
        ResearchCATReadinessProbe(client_factory=factory)(_PORT, _BEARER, 1.0)
    assert redirect.iterated is False

    oversized = b"{" + b" " * (8 * 1024) + b"}"
    body, _clients, factory = _response(oversized, headers={"content-type": "application/json"})
    with pytest.raises(ResearchCATProbeError):
        ResearchCATReadinessProbe(client_factory=factory)(_PORT, _BEARER, 1.0)
    assert body.iterated is True
    assert body.chunk_sizes == [1024]
    assert body.chunks_emitted == 9

    compressed, _clients, factory = _response(
        b"{}", headers={"content-type": "application/json", "content-encoding": "gzip"}
    )
    with pytest.raises(ResearchCATProbeError):
        ResearchCATReadinessProbe(client_factory=factory)(_PORT, _BEARER, 1.0)
    assert compressed.iterated is False


def test_readiness_probe_sanitizes_transport_failure_and_rejects_bad_inputs():
    def failing_factory(**_kwargs):
        raise RuntimeError("Authorization: Bearer do-not-echo")

    with pytest.raises(ResearchCATProbeError) as raised:
        ResearchCATReadinessProbe(client_factory=failing_factory)(_PORT, _BEARER, 1.0)
    assert "do-not-echo" not in str(raised.value)
    assert "Bearer" not in str(raised.value)

    probe = ResearchCATReadinessProbe(client_factory=failing_factory)
    for port, token, timeout in (
        (True, _BEARER, 1.0),
        (_PORT, b"short", 1.0),
        (_PORT, _BEARER, float("inf")),
    ):
        with pytest.raises(ResearchCATProbeError, match="readiness_probe_input_invalid"):
            probe(port, token, timeout)


def test_windows_owner_probe_requires_exact_pid_image_loopback_and_single_listener(
    tmp_path: Path,
):
    executable = tmp_path / "python.exe"
    executable.write_bytes(b"synthetic executable marker")
    identity_calls: list[int] = []
    listener_calls: list[int] = []

    def inspect(pid: int) -> ProcessIdentity:
        identity_calls.append(pid)
        return ProcessIdentity(pid, executable, 700000000000000000)

    def listeners(port: int):
        listener_calls.append(port)
        return (ListenerRecord("127.0.0.1", port, _PID, "LISTEN"),)

    probe = WindowsListenerOwnerProbe(
        executable,
        _process_inspector=inspect,
        _listener_reader=listeners,
    )

    assert probe(_PID, _PORT) is True
    assert identity_calls == [_PID, _PID]
    assert listener_calls == [_PORT]


@pytest.mark.parametrize(
    "row_factory",
    [
        lambda port: (ListenerRecord("127.0.0.1", port, _PID + 1, "LISTEN"),),
        lambda port: (ListenerRecord("0.0.0.0", port, _PID, "LISTEN"),),
        lambda port: (
            ListenerRecord("127.0.0.1", port, _PID, "LISTEN"),
            ListenerRecord("127.0.0.1", port, _PID, "LISTEN"),
        ),
        lambda port: (ListenerRecord("127.0.0.1", port, _PID, "ESTABLISHED"),),
    ],
)
def test_windows_owner_probe_rejects_unowned_or_ambiguous_listeners(tmp_path: Path, row_factory):
    executable = tmp_path / "python.exe"
    executable.write_bytes(b"synthetic executable marker")
    probe = WindowsListenerOwnerProbe(
        executable,
        _process_inspector=lambda pid: ProcessIdentity(pid, executable, 700000000000000000),
        _listener_reader=row_factory,
    )

    assert probe(_PID, _PORT) is False
    assert probe(True, _PORT) is False
    assert probe(_PID, True) is False


def test_windows_owner_probe_pins_expected_executable_and_optional_creation_time(
    tmp_path: Path,
):
    expected_executable = tmp_path / "python.exe"
    wrong_executable = tmp_path / "other.exe"
    expected_executable.write_bytes(b"base interpreter marker")
    wrong_executable.write_bytes(b"different image marker")
    expected_start = dt.datetime(2026, 10, 14, tzinfo=dt.UTC)
    from smhai_backend.domains.school_research.probes import _datetime_to_filetime

    expected_ticks = _datetime_to_filetime(expected_start)
    rows = (ListenerRecord("127.0.0.1", _PORT, _PID, "LISTEN"),)
    probe = WindowsListenerOwnerProbe(
        expected_executable,
        expected_creation_time_utc=expected_start,
        _process_inspector=lambda pid: ProcessIdentity(pid, expected_executable, expected_ticks),
        _listener_reader=lambda _port: rows,
    )
    assert probe(_PID, _PORT) is True

    mismatch = WindowsListenerOwnerProbe(
        expected_executable,
        expected_creation_time_utc=expected_start,
        _process_inspector=lambda pid: ProcessIdentity(
            pid, expected_executable, expected_ticks + 100
        ),
        _listener_reader=lambda _port: rows,
    )
    assert mismatch(_PID, _PORT) is False

    wrong_image = WindowsListenerOwnerProbe(
        expected_executable,
        _process_inspector=lambda pid: ProcessIdentity(pid, wrong_executable, expected_ticks),
        _listener_reader=lambda _port: rows,
    )
    assert wrong_image(_PID, _PORT) is False


def test_windows_owner_probe_os_errors_fail_closed_without_echo(tmp_path: Path):
    executable = tmp_path / "python.exe"
    executable.write_bytes(b"base interpreter marker")

    probe = WindowsListenerOwnerProbe(
        executable,
        _process_inspector=lambda _pid: (_ for _ in ()).throw(
            RuntimeError("CommandLine=Bearer private-value")
        ),
        _listener_reader=lambda _port: (),
    )

    assert probe(_PID, _PORT) is False
    assert "private-value" not in repr(probe)


def test_windows_owner_probe_rechecks_identity_to_reject_pid_reuse(tmp_path: Path):
    executable = tmp_path / "python.exe"
    executable.write_bytes(b"base interpreter marker")
    identity_values = iter(
        (
            ProcessIdentity(_PID, executable, 700000000000000000),
            ProcessIdentity(_PID, executable, 700000000000000001),
        )
    )
    probe = WindowsListenerOwnerProbe(
        executable,
        _process_inspector=lambda _pid: next(identity_values),
        _listener_reader=lambda port: (ListenerRecord("127.0.0.1", port, _PID, "LISTEN"),),
    )

    assert probe(_PID, _PORT) is False


def test_windows_tcp_row_network_order_decode_is_exact():
    address_dword = int.from_bytes(socket.inet_aton("127.0.0.1"), "little")
    port_dword = int.from_bytes(_PORT.to_bytes(2, "big"), "little")

    assert _decode_ipv4_dword(address_dword) == "127.0.0.1"
    assert _decode_network_port_dword(port_dword) == _PORT
