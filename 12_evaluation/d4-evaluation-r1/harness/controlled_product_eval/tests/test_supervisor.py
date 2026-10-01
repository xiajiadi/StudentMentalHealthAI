from __future__ import annotations

import asyncio
import io
import json
import socket
import sys
import uuid
from argparse import Namespace
from pathlib import Path

import pytest

from harness.controlled_product_eval.process_lifecycle import (
    LifecycleError,
    ProcessSpec,
    ProcessSupervisor,
    build_child_environment,
    run_managed_command,
)
from harness.controlled_product_eval.cli import _run_managed
from harness.controlled_product_eval.credential_provider import EvaluationCredentialProvider
from harness.controlled_product_eval.supervisor import (
    DEFAULT_TOOLS_ROOT,
    JsonlSupervisor,
    OWNED_GROUPS,
    START_ORDER,
    SupervisorConfig,
    build_service_profiles,
)
import harness.controlled_product_eval.supervisor as supervisor_module
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
        "print(os.environ['DB_PASSWORD'], flush=True); "
        "import sys; print(os.environ['DB_PASSWORD'], file=sys.stderr, flush=True); "
        "H=type('H',(BaseHTTPRequestHandler,),{'do_GET':lambda self:(self.send_response(200),"
        "self.send_header('Content-Type','application/json'),self.end_headers(),"
        "self.wfile.write(b'{\\\"status\\\":\\\"READY\\\"}')),'log_message':lambda *a:None}); "
        f"HTTPServer(('127.0.0.1',{port}),H).serve_forever()"
    )
    sentinel = "unit-redaction-" + uuid.uuid4().hex
    supervisor = ProcessSupervisor(startup_timeout_seconds=5, shutdown_timeout_seconds=2)
    spec = ProcessSpec(
        name="test-service",
        executable=Path(sys.executable).resolve(),
        arguments=("-c", script),
        cwd=tmp_path.resolve(),
        environment={"DB_PASSWORD": sentinel},
        readiness_url=f"http://127.0.0.1:{port}/health",
        readiness_kind="service",
        log_path=tmp_path / "service.stdout.log",
        stderr_log_path=tmp_path / "service.stderr.log",
        interpreter_version="3.12.test",
        package_lock_identity={"test_lock_sha256": "0" * 64},
        environment_allowlist=frozenset({"DB_PASSWORD"}),
    )
    try:
        identities = await supervisor.start([spec])
        identity = identities[0]
        assert sentinel not in json.dumps(identity)
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
        assert sentinel not in json.dumps(supervisor.lifecycle_snapshot())
    finally:
        if not supervisor._closed:
            await supervisor.close()


def test_one_shot_bootstrap_redacts_secret_output_and_rejects_secret_argv(tmp_path):
    sentinel = "bootstrap-" + uuid.uuid4().hex
    script = (
        "import os,sys; value=os.environ['DB_PASSWORD']; "
        "print(value); print(value,file=sys.stderr); "
        "raise RuntimeError(value)"
    )
    result = run_managed_command(
        name="credential-redaction-test",
        executable=Path(sys.executable).resolve(),
        arguments=("-c", script),
        cwd=tmp_path.resolve(),
        environment={"DB_PASSWORD": sentinel},
        environment_allowlist=frozenset({"DB_PASSWORD"}),
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        check=False,
    )
    assert result.return_code != 0
    assert sentinel not in result.stdout.decode("utf-8", errors="replace")
    assert sentinel not in result.stderr.decode("utf-8", errors="replace")
    assert b"<redacted>" in result.stdout
    assert b"<redacted>" in result.stderr
    assert sentinel not in (tmp_path / "stdout.log").read_text(encoding="utf-8")
    assert sentinel not in (tmp_path / "stderr.log").read_text(encoding="utf-8")

    with pytest.raises(LifecycleError) as exc_info:
        run_managed_command(
            name="credential-argv-test",
            executable=Path(sys.executable).resolve(),
            arguments=("-c", sentinel),
            cwd=tmp_path.resolve(),
            environment={"DB_PASSWORD": sentinel},
            environment_allowlist=frozenset({"DB_PASSWORD"}),
            stdout_path=tmp_path / "blocked.stdout.log",
            stderr_path=tmp_path / "blocked.stderr.log",
        )
    assert sentinel not in str(exc_info.value)

    with pytest.raises(LifecycleError) as command_error:
        run_managed_command(
            name="credential-exception-redaction-test",
            executable=Path(sys.executable).resolve(),
            arguments=("-c", script),
            cwd=tmp_path.resolve(),
            environment={"DB_PASSWORD": sentinel},
            environment_allowlist=frozenset({"DB_PASSWORD"}),
            stdout_path=tmp_path / "exception.stdout.log",
            stderr_path=tmp_path / "exception.stderr.log",
            check=True,
        )
    exception_is_safe = sentinel not in str(command_error.value)
    assert exception_is_safe, "bootstrap exception summaries must not expose credential values"


class _FakeProcessSupervisor:
    def __init__(self, started: tuple[str, ...] = ()):
        self.started: list[str] = list(started)
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
    denied = service.dispatch({"op": "start", "service": "powershell"})
    assert denied["ok"] is False
    assert denied["error_type"] == "OwnershipError"
    assert manager.started == []

    no_mysql = service.dispatch({"op": "start_external_stack"})
    assert no_mysql["ok"] is False
    assert no_mysql["error_type"] == "PreconditionError"
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
    marker = "protocol-" + uuid.uuid4().hex
    source = io.StringIO(
        json.dumps(
            {
                "op": "start",
                "service": "backend",
                "password": marker,
                "DB_PASSWORD": marker,
                "DATABASE_URL": "mysql+aiomysql://user:" + marker + "@127.0.0.1/db",
            }
        )
        + "\n"
    )
    output = io.StringIO()
    service.serve(source, output)

    response = json.loads(output.getvalue())
    audit = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert response["ok"] is False
    assert marker not in output.getvalue()
    assert marker not in audit
    assert '"operation":"start"' in audit


def test_supervisor_enforces_login_before_rag_index_start(tmp_path):
    service, manager = _protocol(tmp_path)
    result = service.dispatch({"op": "start", "service": "rag"})
    assert result["ok"] is False
    assert result["error_type"] == "PreconditionError"
    assert manager.started == []


def test_supervisor_external_stack_starts_in_fixed_order_and_publishes_live_attestation(tmp_path, monkeypatch):
    service, manager = _protocol(tmp_path)
    manager.started.append("d4-mysql")
    service.profile_source_evidence = {name: {"status": "PASS"} for name in ("opa", "safety", "ollama", "runtime", "cat")}
    service.attempt_id = "D4SUP_TEST_001"
    service.service_root = tmp_path.resolve()
    service.current_runtime_pointer = (tmp_path / "runtime-preflight-current.json").resolve()

    async def fake_verify(**_kwargs):
        return {
            "preflight": {"preflight_hash": "sha256:" + "a" * 64},
            "run_preflight_path": str(tmp_path / "preflight" / "runtime-preflight.json"),
        }

    monkeypatch.setattr(supervisor_module, "verify_external_service_readiness", fake_verify)
    result = service.dispatch({"op": "start_external_stack"})
    assert result["ok"] is True
    assert manager.started == [
        "d4-mysql", "d4-opa", "d4-safety", "d4-ollama", "d4-runtime", "d4-cat",
    ]
    assert result["runtime_preflight_hash"] == "sha256:" + "a" * 64
    assert service.runtime_preflight["preflight_hash"] == "sha256:" + "a" * 64


def test_supervisor_stops_after_missing_login_gate_and_does_not_retry(tmp_path, monkeypatch):
    service, manager = _protocol(tmp_path)
    manager.started.extend(("d4-mysql", "d4-opa", "d4-safety", "d4-ollama", "d4-runtime", "d4-cat"))
    service.runtime_preflight = {"preflight_hash": "sha256:" + "a" * 64}
    monkeypatch.setattr(supervisor_module, "verify_runtime_attestation_still_live", lambda *_args, **_kwargs: {"status": "PASS"})
    first = service.dispatch({"op": "start", "service": "backend"})
    second = service.dispatch({"op": "start", "service": "backend"})
    assert first["ok"] is False
    assert second["ok"] is False
    assert service.login_gate_failed is True
    assert manager.started[-1] == "d4-backend"
    assert manager.stopped == ["d4-backend"]


def test_supervisor_group_allowlist_is_fixed_and_excludes_external_services():
    assert OWNED_GROUPS == {
        "mysql": ("d4-mysql",),
        "opa": ("d4-opa",),
        "safety": ("d4-safety",),
        "ollama": ("d4-ollama",),
        "runtime": ("d4-runtime",),
        "cat": ("d4-cat",),
        "external": ("d4-opa", "d4-safety", "d4-ollama", "d4-runtime", "d4-cat"),
        "rag": ("d4-rag",),
        "observers": ("d4-rag-observer", "d4-llm-observer"),
        "backend": ("d4-backend",),
    }
    assert START_ORDER[:6] == ("d4-mysql", "d4-opa", "d4-safety", "d4-ollama", "d4-runtime", "d4-cat")
    assert START_ORDER.index("d4-backend") < START_ORDER.index("d4-rag")
    assert "d4-runtime" in START_ORDER
    assert "d4-safety" in START_ORDER


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
        build_service_profiles(
            config,
            database_credential=EvaluationCredentialProvider().generate_database_credential(),
        )


def test_managed_cli_rejects_output_outside_pinned_task_tools_root(tmp_path):
    args = Namespace(
        output_root=str(tmp_path / "output"),
        packet=str(Path(__file__).resolve().parents[5] / "12_evaluation" / "d4-evaluation-r1" / "D4_3A_HUMAN_GOLD_REVIEW_PACKET.json"),
    )
    with pytest.raises(RunnerError, match="pinned D4 task-tools root"):
        asyncio.run(_run_managed(args))


def test_managed_cli_accepts_only_the_pinned_task_local_interpreters():
    from harness.controlled_product_eval.environment_profiles import BACKEND_PYTHON, RAG_PYTHON
    from harness.controlled_product_eval.cli import _require_pinned_interpreter

    assert _require_pinned_interpreter(str(BACKEND_PYTHON), BACKEND_PYTHON, "Backend") == BACKEND_PYTHON.resolve()
    assert _require_pinned_interpreter(str(RAG_PYTHON), RAG_PYTHON, "RAG") == RAG_PYTHON.resolve()
