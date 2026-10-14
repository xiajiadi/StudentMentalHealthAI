from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from smhai_backend.domains.school_research.process import (
    ResearchCATProcessError,
    ResearchCATProcessManager,
    ResearchCATProcessSpec,
)

_CONFIG_SHA = "a" * 64
_REGISTRY_FINGERPRINT = "d" * 64
_PORT = 48182
_BINDING_COUNT = 2
_SCHOOL_SCOPE = "school:701"
_BEARER = "derived-only-bearer-token-material-123456789"
_HANDSHAKE_SCHEMA = "psynova.research-service-keys.v1"
_READY_SCHEMA = "psynova.research-service-ready.v1"
_STOP = b"PSYNOVA_RESEARCH_STOP\n"


class _FakeStdin:
    def __init__(self, process) -> None:
        self.process = process
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, value: bytes) -> int:
        self.writes.append(value)
        return len(value)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True
        if _STOP in self.writes and not self.process.ignore_stop:
            self.process.returncode = 0


class _FakePopen:
    def __init__(self, argv, **kwargs) -> None:
        self.argv = argv
        self.kwargs = kwargs
        self.pid = 44551
        self.returncode = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self.ignore_stop = False
        self.ignore_terminate = False
        self.stdin = _FakeStdin(self)

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired(self.argv, timeout)
        return self.returncode

    def terminate(self):
        self.terminate_calls += 1
        if not self.ignore_terminate:
            self.returncode = -15

    def kill(self):
        self.kill_calls += 1
        self.returncode = -9


@pytest.fixture
def launch_inputs(tmp_path: Path, monkeypatch):
    cat_source = tmp_path / "cat-source"
    cat_source.mkdir()
    python = tmp_path / "python.exe"
    python.write_bytes(b"synthetic test executable marker")
    config = tmp_path / "service.json"
    config.write_text("{}", encoding="ascii")
    processes: list[_FakePopen] = []

    def fake_popen(argv, **kwargs):
        process = _FakePopen(argv, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(
        "smhai_backend.domains.school_research.process.subprocess.Popen", fake_popen
    )
    readiness_calls: list[tuple[int, bytes, float]] = []

    def ready_probe(port: int, bearer: bytes, timeout: float):
        readiness_calls.append((port, bearer, timeout))
        return _ready_body()

    ownership_calls: list[tuple[int, int]] = []

    def owner_probe(pid: int, port: int) -> bool:
        ownership_calls.append((pid, port))
        return pid == processes[-1].pid and port == _PORT

    spec = ResearchCATProcessSpec(
        python_executable=python,
        cat_source=cat_source,
        serve_config_path=config,
        serve_config_sha256=_CONFIG_SHA,
        expected_registry_fingerprint=_REGISTRY_FINGERPRINT,
        expected_port=_PORT,
        expected_binding_count=_BINDING_COUNT,
        expected_school_scope=_SCHOOL_SCOPE,
        derived_keys_handshake=_handshake(),
    )
    manager = ResearchCATProcessManager(
        spec,
        readiness_probe=ready_probe,
        listener_owner_probe=owner_probe,
        port_available_probe=lambda _port: True,
        startup_timeout_seconds=0.2,
        shutdown_timeout_seconds=0.01,
        probe_timeout_seconds=0.1,
        poll_interval_seconds=0.001,
    )
    return SimpleNamespace(
        manager=manager,
        spec=spec,
        processes=processes,
        cat_source=cat_source,
        python=python,
        config=config,
        readiness_calls=readiness_calls,
        ownership_calls=ownership_calls,
    )


@pytest.mark.asyncio
async def test_start_uses_private_handshake_minimal_environment_and_owned_readiness(
    launch_inputs, monkeypatch
):
    monkeypatch.setenv("SMHAI_DATABASE_PASSWORD", "do-not-inherit")
    monkeypatch.setenv("DATABASE_URL", "mysql://do-not-inherit")
    monkeypatch.setenv("HTTP_PROXY", "http://do-not-inherit")
    monkeypatch.setenv("PYTHONPATH", "untrusted-existing-path")
    monkeypatch.setenv("PATH", "inherited-path-not-needed")
    monkeypatch.setenv("SYSTEMROOT", "C:\\Windows")
    monkeypatch.setenv("USERNAME", "synthetic-user")

    health = await launch_inputs.manager.start()

    process = launch_inputs.processes[0]
    assert health.status == "READY"
    assert launch_inputs.manager._spec is not launch_inputs.spec
    assert launch_inputs.manager._spec.derived_keys_handshake == b""
    assert launch_inputs.spec.derived_keys_handshake == _handshake()
    assert launch_inputs.manager._handshake_line is None
    assert process.argv == [
        str(launch_inputs.python.resolve()),
        "-S",
        "-m",
        "cat_engine.research.serve",
        "--config",
        str(launch_inputs.config.resolve()),
        "--config-sha256",
        _CONFIG_SHA,
    ]
    assert process.kwargs["shell"] is False
    assert process.kwargs["stdin"] == subprocess.PIPE
    assert process.kwargs["stdout"] == subprocess.DEVNULL
    assert process.kwargs["stderr"] == subprocess.DEVNULL
    assert process.kwargs["cwd"] == str(launch_inputs.cat_source.resolve())
    assert process.kwargs["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
    assert process.kwargs["env"]["PYTHONPATH"] == str(launch_inputs.cat_source.resolve())
    assert process.kwargs["env"]["PYTHONNOUSERSITE"] == "1"
    assert process.kwargs["env"]["SYSTEMROOT"] == "C:\\Windows"
    assert process.kwargs["env"]["USERNAME"] == "synthetic-user"
    assert not {"SMHAI_DATABASE_PASSWORD", "DATABASE_URL", "HTTP_PROXY", "PATH"} & set(
        process.kwargs["env"]
    )
    assert process.kwargs["env"]["PYTHONPATH"] != "untrusted-existing-path"

    handoff = process.stdin.writes
    assert len(handoff) == 1
    document = json.loads(handoff[0])
    assert set(document) == {"schema", "bearer_token", "signing_version", "keyring"}
    assert document["schema"] == _HANDSHAKE_SCHEMA
    assert document["bearer_token"] == _BEARER
    assert process.stdin.closed is False  # kept open for the stop channel
    assert launch_inputs.readiness_calls == [(_PORT, _BEARER.encode("ascii"), 0.1)]
    assert launch_inputs.ownership_calls == [(process.pid, _PORT)]
    assert _BEARER not in repr(launch_inputs.manager)
    assert ("AQ" * 32) not in repr(launch_inputs.manager)

    closed = await launch_inputs.manager.close()
    assert closed.status == "STOPPED"
    assert process.stdin.writes[-1] == _STOP
    assert process.terminate_calls == process.kill_calls == 0


@pytest.mark.asyncio
async def test_optional_isolated_cat_dependencies_are_the_only_extra_pythonpath(
    launch_inputs, tmp_path: Path
):
    dependencies = tmp_path / "cat-venv" / "Lib" / "site-packages"
    dependencies.mkdir(parents=True)
    launch_inputs.manager._spec = replace(
        launch_inputs.manager._spec, cat_dependency_path=dependencies
    )

    await launch_inputs.manager.start()

    env = launch_inputs.processes[0].kwargs["env"]
    assert env["PYTHONPATH"] == os.pathsep.join(
        [str(launch_inputs.cat_source.resolve()), str(dependencies.resolve())]
    )
    await launch_inputs.manager.close()


@pytest.mark.asyncio
async def test_port_conflict_refuses_to_spawn_or_adopt_existing_listener(
    launch_inputs, monkeypatch
):
    launch_inputs.manager._port_available_probe = lambda _port: False

    with pytest.raises(ResearchCATProcessError, match="loopback_port_unavailable"):
        await launch_inputs.manager.start()

    assert launch_inputs.processes == []
    assert launch_inputs.manager._health.status == "UNAVAILABLE"
    assert launch_inputs.manager._handshake_line is None


@pytest.mark.asyncio
async def test_health_without_listener_pid_ownership_never_becomes_ready(launch_inputs):
    launch_inputs.manager._listener_owner_probe = lambda _pid, _port: False

    with pytest.raises(ResearchCATProcessError, match="readiness_timeout"):
        await launch_inputs.manager.start()

    process = launch_inputs.processes[0]
    assert process.stdin.writes[-1] == _STOP
    assert process.returncode == 0
    assert launch_inputs.manager._health.status == "UNAVAILABLE"
    assert (await launch_inputs.manager.health()).status == "UNAVAILABLE"


def _ready_body() -> dict[str, object]:
    return {
        "schema": _READY_SCHEMA,
        "status": "READY",
        "research_only": True,
        "clinical_approval": False,
        "school_approval": False,
        "service_config_sha256": _CONFIG_SHA,
        "registry_fingerprint": _REGISTRY_FINGERPRINT,
        "binding_count": _BINDING_COUNT,
        "school_scope": _SCHOOL_SCOPE,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {**_ready_body(), "service_config_sha256": "b" * 64},
        {**_ready_body(), "binding_count": True},
        {**_ready_body(), "registry_fingerprint": "e" * 64},
        {**_ready_body(), "school_scope": "school:702"},
        {**_ready_body(), "research_only": False},
        {**_ready_body(), "clinical_approval": True},
        {**_ready_body(), "extra": "not accepted"},
    ],
)
async def test_readiness_rejects_wrong_or_open_health_payload(launch_inputs, body):
    launch_inputs.manager._readiness_probe = lambda _port, _bearer, _timeout: body

    with pytest.raises(ResearchCATProcessError, match="readiness_timeout"):
        await launch_inputs.manager.start()

    assert launch_inputs.processes[0].stdin.writes[-1] == _STOP
    assert launch_inputs.processes[0].returncode == 0


@pytest.mark.asyncio
async def test_health_reports_child_exit_and_does_not_probe_another_listener(launch_inputs):
    await launch_inputs.manager.start()
    process = launch_inputs.processes[0]
    process.returncode = 17
    readiness_before = len(launch_inputs.readiness_calls)
    ownership_before = len(launch_inputs.ownership_calls)

    health = await launch_inputs.manager.health()

    assert health.status == "UNAVAILABLE"
    assert health.failure_code == "child_exited"
    assert len(launch_inputs.readiness_calls) == readiness_before
    assert len(launch_inputs.ownership_calls) == ownership_before


@pytest.mark.asyncio
async def test_close_escalates_only_through_its_own_popen_handle(launch_inputs):
    await launch_inputs.manager.start()
    process = launch_inputs.processes[0]
    process.ignore_stop = True

    closed = await launch_inputs.manager.close()

    assert closed.status == "STOPPED"
    assert process.stdin.writes[-1] == _STOP
    assert process.terminate_calls == 1
    assert process.kill_calls == 0
    assert process.returncode == -15


@pytest.mark.asyncio
async def test_close_kills_only_owned_popen_after_graceful_and_terminate_timeouts(launch_inputs):
    await launch_inputs.manager.start()
    process = launch_inputs.processes[0]
    process.ignore_stop = True
    process.ignore_terminate = True

    closed = await launch_inputs.manager.close()

    assert closed.status == "STOPPED"
    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert process.returncode == -9


@pytest.mark.asyncio
async def test_cancelled_start_finishes_bounded_owned_child_cleanup(launch_inputs):
    entered_probe = threading.Event()
    release_probe = threading.Event()

    def slow_probe(_port: int, _bearer: bytes, _timeout: float):
        entered_probe.set()
        release_probe.wait(timeout=1)
        return _ready_body()

    launch_inputs.manager._readiness_probe = slow_probe
    start_task = asyncio.create_task(launch_inputs.manager.start())
    assert await asyncio.to_thread(entered_probe.wait, 1)
    start_task.cancel()
    release_probe.set()

    with pytest.raises(asyncio.CancelledError):
        await start_task

    process = launch_inputs.processes[0]
    assert process.stdin.writes[-1] == _STOP
    assert process.returncode == 0
    assert (await launch_inputs.manager.health()).status == "UNAVAILABLE"


@pytest.mark.asyncio
async def test_cancelled_close_still_stops_owned_process_and_preserves_cancellation(launch_inputs):
    await launch_inputs.manager.start()
    process = launch_inputs.processes[0]
    process.ignore_stop = True
    launch_inputs.manager._shutdown_timeout = 0.3

    close_task = asyncio.create_task(launch_inputs.manager.close())
    while not process.stdin.closed:
        await asyncio.sleep(0)
    close_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await close_task

    assert process.terminate_calls == 1
    assert process.returncode == -15
    assert (await launch_inputs.manager.health()).status == "STOPPED"


@pytest.mark.asyncio
async def test_cancellation_during_start_failure_cleanup_still_stops_owned_child(launch_inputs):
    launch_inputs.manager._listener_owner_probe = lambda _pid, _port: False
    launch_inputs.manager._startup_timeout = 0.02
    launch_inputs.manager._shutdown_timeout = 0.3
    process_created = launch_inputs.processes
    stop_started = asyncio.Event()
    original_stop = launch_inputs.manager._stop_owned_process

    async def observe_stop(process):
        process.ignore_stop = True
        stop_started.set()
        await original_stop(process)

    launch_inputs.manager._stop_owned_process = observe_stop
    start_task = asyncio.create_task(launch_inputs.manager.start())
    await stop_started.wait()
    start_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await start_task

    assert process_created
    process = process_created[0]
    assert process.terminate_calls == 1
    assert process.poll() is not None
    assert launch_inputs.manager._handshake_line is None
    assert launch_inputs.manager._spec.derived_keys_handshake == b""
    assert (await launch_inputs.manager.health()).status == "UNAVAILABLE"


@pytest.mark.asyncio
async def test_child_without_private_stdin_is_cleaned_up_without_readiness_probe(
    launch_inputs, monkeypatch
):
    def fake_child_without_pipe(argv, **kwargs):
        process = _FakePopen(argv, **kwargs)
        process.stdin = None
        launch_inputs.processes.append(process)
        return process

    monkeypatch.setattr(
        "smhai_backend.domains.school_research.process.subprocess.Popen",
        fake_child_without_pipe,
    )

    with pytest.raises(ResearchCATProcessError, match="child_pipe_unavailable"):
        await launch_inputs.manager.start()

    process = launch_inputs.processes[0]
    assert process.terminate_calls == 1
    assert process.poll() is not None
    assert launch_inputs.readiness_calls == []


@pytest.mark.asyncio
async def test_hostile_derived_handshake_fails_before_child_creation(launch_inputs):
    altered = json.loads(_handshake())
    altered["master_key"] = "must-not-be-accepted"
    line = json.dumps(altered, separators=(",", ":")).encode("ascii") + b"\n"
    launch_inputs.manager._handshake_line = line

    with pytest.raises(ResearchCATProcessError, match="derived_handshake_invalid"):
        await launch_inputs.manager.start()

    assert launch_inputs.processes == []
    assert "must-not-be-accepted" not in repr(launch_inputs.manager)
    assert launch_inputs.manager._handshake_line is None


@pytest.mark.asyncio
async def test_spawn_exception_is_sanitized_and_never_echoes_child_environment(
    monkeypatch, launch_inputs
):
    monkeypatch.setattr(
        "smhai_backend.domains.school_research.process.subprocess.Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("DATABASE_URL=secret-value")),
    )

    with pytest.raises(ResearchCATProcessError, match="start_failed") as raised:
        await launch_inputs.manager.start()

    assert "secret-value" not in str(raised.value)
    assert "DATABASE_URL" not in str(raised.value)
    assert launch_inputs.manager._health.status == "UNAVAILABLE"


def _handshake() -> bytes:
    encoded_key = base64.urlsafe_b64encode(b"\x01" * 32).decode("ascii").rstrip("=")
    return (
        json.dumps(
            {
                "schema": _HANDSHAKE_SCHEMA,
                "bearer_token": _BEARER,
                "signing_version": "v1",
                "keyring": {"v1": encoded_key},
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        + b"\n"
    )
