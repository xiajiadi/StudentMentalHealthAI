from __future__ import annotations

import io
import json
import socket
import sys
from pathlib import Path

import pytest

from harness.controlled_product_eval.process_lifecycle import (
    LifecycleError,
    ProcessSpec,
    ProcessSupervisor,
    build_child_environment,
)
from harness.controlled_product_eval.supervisor import (
    DEFAULT_TOOLS_ROOT,
    JsonlSupervisor,
    OWNED_GROUPS,
    START_ORDER,
    SupervisorConfig,
    build_service_profiles,
)
from harness.controlled_product_eval.runner import RunnerError


def _free_loopback_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_child_environment_is_profile_allowlisted_and_does_not_copy_parent_secrets(monkeypatch):
    monkeypatch.setenv("UNRELATED_SECRET", "parent-only-value")
    child = build_child_environment(
        {"APP_MODE": "test"},
        allowed_names=frozenset({"APP_MODE"}),
    )
    assert child["APP_MODE"] == "test"
    assert "UNRELATED_SECRET" not in child

    with pytest.raises(LifecycleError, match="allowlist"):
        build_child_environment(
            {"UNAPPROVED_SETTING": "value"},
            allowed_names=frozenset({"APP_MODE"}),
        )


@pytest.mark.asyncio
async def test_direct_child_capture_redacts_secrets_and_records_process_identity(tmp_path):
    port = _free_loopback_port()
    script = (
        "import os; from http.server import BaseHTTPRequestHandler,HTTPServer; "
        "print(os.environ['TEST_SECRET'], flush=True); "
        "import sys; print(os.environ['TEST_SECRET'], file=sys.stderr, flush=True); "
        "H=type('H',(BaseHTTPRequestHandler,),{'do_GET':lambda self:(self.send_response(200),"
        "self.send_header('Content-Type','application/json'),self.end_headers(),"
        "self.wfile.write(b'{\\\"status\\\":\\\"READY\\\"}')),'log_message':lambda *a:None}); "
        f"HTTPServer(('127.0.0.1',{port}),H).serve_forever()"
    )
    sentinel = "unit-redaction-sentinel-never-a-real-credential"
    supervisor = ProcessSupervisor(startup_timeout_seconds=5, shutdown_timeout_seconds=2)
    spec = ProcessSpec(
        name="test-service",
        executable=Path(sys.executable).resolve(),
        arguments=("-c", script),
        cwd=tmp_path.resolve(),
        environment={"TEST_SECRET": sentinel},
        readiness_url=f"http://127.0.0.1:{port}/health",
        readiness_kind="service",
        log_path=tmp_path / "service.stdout.log",
        stderr_log_path=tmp_path / "service.stderr.log",
        interpreter_version="3.12.test",
        package_lock_identity={"test_lock_sha256": "0" * 64},
        environment_allowlist=frozenset({"TEST_SECRET"}),
    )
    try:
        identities = await supervisor.start([spec])
        identity = identities[0]
        assert identity["executable"] == str(Path(sys.executable).resolve())
        assert identity["pid"] > 0
        assert identity["parent_pid"] > 0
        assert identity["cwd"] == str(tmp_path.resolve())
        assert identity["interpreter_version"] == "3.12.test"
        assert identity["package_lock_identity"] == {"test_lock_sha256": "0" * 64}
        cleanup = await supervisor.close()
        assert cleanup["cleanup_verified"] is True
        stopped = cleanup["services"][0]
        assert stopped["stopped"] is True
        assert stopped["return_code"] is not None
        assert stopped["parent_pid"] > 0
        assert stopped["started_at"] and stopped["stopped_at"]
        assert Path(stopped["stdout_log"]).is_file()
        assert Path(stopped["stderr_log"]).is_file()
        stdout = Path(stopped["stdout_log"]).read_text(encoding="utf-8")
        stderr = Path(stopped["stderr_log"]).read_text(encoding="utf-8")
        assert sentinel not in stdout + stderr
        assert "<redacted>" in stdout
        assert "<redacted>" in stderr
    finally:
        if not supervisor._closed:
            await supervisor.close()


class _FakeProcessSupervisor:
    def __init__(self):
        self.started: list[str] = []
        self.stopped: list[str] = []

    def identities(self):
        return [{"name": name} for name in self.started if name not in self.stopped]

    async def start_service(self, spec):
        self.started.append(spec.name)
        return {"name": spec.name, "pid": 1234}

    async def stop_service(self, name):
        self.stopped.append(name)
        return {"cleanup_verified": True, "service": {"name": name}}

    async def close(self):
        self.stopped.extend(name for name in self.started if name not in self.stopped)
        return {"cleanup_verified": True, "services": [], "errors": []}


def _protocol(tmp_path):
    profiles = {
        name: ProcessSpec(
            name=name,
            executable=Path(sys.executable).resolve(),
            arguments=("-c", "pass"),
            cwd=tmp_path.resolve(),
            environment={},
            readiness_url=f"tcp://127.0.0.1:{_free_loopback_port()}",
            readiness_kind="tcp",
            log_path=tmp_path / f"{name}.log",
        )
        for name in START_ORDER
    }
    manager = _FakeProcessSupervisor()
    service = JsonlSupervisor(
        profiles=profiles,
        supervisor=manager,
        event_log=tmp_path / "events.jsonl",
    )
    return service, manager


def test_supervisor_protocol_rejects_arbitrary_commands_and_external_ownership(tmp_path, monkeypatch):
    service, manager = _protocol(tmp_path)
    denied = service.dispatch({"op": "start", "service": "mysql"})
    assert denied["ok"] is False
    assert denied["error_type"] == "OwnershipError"
    assert manager.started == []

    malformed = service.dispatch({"op": "start", "service": "rag", "command": "whoami"})
    assert malformed["ok"] is False
    assert malformed["error_type"] == "RequestError"
    assert manager.started == []

    arbitrary = service.dispatch({"op": "exec", "command": "python -c pass"})
    assert arbitrary["ok"] is False
    assert manager.started == []


def test_supervisor_jsonl_audit_omits_unrecognized_request_values(tmp_path):
    service, _manager = _protocol(tmp_path)
    marker = "never-write-this-request-value"
    source = io.StringIO(json.dumps({"op": "start", "service": "rag", "extra": marker}) + "\n")
    output = io.StringIO()
    service.serve(source, output)

    response = json.loads(output.getvalue())
    audit = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert response["ok"] is False
    assert marker not in audit
    assert '"operation":"start"' in audit


def test_supervisor_group_allowlist_is_fixed_and_excludes_external_services():
    assert OWNED_GROUPS == {
        "rag": ("d4-rag",),
        "observers": ("d4-rag-observer", "d4-llm-observer"),
        "backend": ("d4-backend",),
    }
    assert "mysql" not in OWNED_GROUPS
    assert "runtime" not in OWNED_GROUPS
    assert "safety" not in OWNED_GROUPS


def test_supervisor_rejects_caller_selected_tools_root(tmp_path):
    config = SupervisorConfig(
        repo_root=tmp_path,
        tools_root=tmp_path,
        service_root=tmp_path / "run",
        corpus_manifest=tmp_path / "corpus.json",
        backend_python=tmp_path / "python.exe",
        rag_python=tmp_path / "python.exe",
    )
    assert DEFAULT_TOOLS_ROOT.is_absolute()
    with pytest.raises(RunnerError, match="pinned"):
        build_service_profiles(config)
