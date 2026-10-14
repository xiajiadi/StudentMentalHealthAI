import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_app_lifecycle as lifecycle


class FakeProcess:
    def __init__(self, pid):
        self.pid = pid

    def poll(self):
        return None


class FakeOperations:
    def __init__(self):
        self.bound = {}
        self.processes = {}
        self.spawned = []
        self.terminated = []
        self.next_pid = 901
        self.research_port = None
        self.cleanup_research_on_backend_stop = True

    def port_is_free(self, port):
        return port not in self.bound

    def listeners(self, port):
        return list(self.bound.get(port, []))

    def inspect_process(self, pid):
        return self.processes.get(pid)

    def spawn(self, argv, *, cwd, env):
        pid = self.next_pid
        self.next_pid += 1
        record = {
            "ProcessId": pid,
            "ParentProcessId": os.getpid(),
            "ExecutablePath": argv[0],
            "CreationUtc": f"2026-10-14T00:00:{pid % 60:02d}Z",
            "CommandLine": subprocess.list2cmdline(argv),
        }
        self.processes[pid] = record
        port = int(argv[argv.index("--port") + 1])
        self.bound[port] = [
            {"OwningProcess": pid, "LocalAddress": "127.0.0.1", "LocalPort": port}
        ]
        if "--research-service-file" in argv:
            service_file = Path(argv[argv.index("--research-service-file") + 1])
            self.research_port = json.loads(service_file.read_text())["listener"][
                "port"
            ]
            self.bound[self.research_port] = [
                {
                    "OwningProcess": 990,
                    "LocalAddress": "127.0.0.1",
                    "LocalPort": self.research_port,
                }
            ]
        self.spawned.append((list(argv), cwd, dict(env)))
        return FakeProcess(pid)

    def wait_ready(self, _process, _port, _path, _timeout):
        return True

    def http_ready(self, _port, _path):
        return True

    def terminate_verified(self, service, process_identity):
        pid = process_identity["pid"]
        self.terminated.append(pid)
        port = service["port"]
        self.bound.pop(port, None)
        self.processes.pop(pid, None)
        if (
            service["name"] == "backend"
            and self.research_port is not None
            and self.cleanup_research_on_backend_stop
        ):
            self.bound.pop(self.research_port, None)
        return True


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    workspace = tmp_path / "external" / "workspace"
    backend_venv = repo / "09_backend" / ".venv"
    launcher = backend_venv / "Scripts" / "python.exe"
    launcher.parent.mkdir(parents=True)
    launcher.touch()
    base_python_home = repo / "backend-base-python"
    base_python_home.mkdir(parents=True)
    (base_python_home / "python.exe").touch()
    (backend_venv / "pyvenv.cfg").write_text(
        f"home = {base_python_home}\nversion_info = 3.12\n", encoding="utf-8"
    )
    vite = repo / "10_frontend" / "node_modules" / "vite" / "bin" / "vite.js"
    vite.parent.mkdir(parents=True)
    vite.touch()
    workspace.mkdir(parents=True)
    marker = {"workspace_id": "synthetic-research-workspace"}
    (workspace / "workspace.json").write_text(json.dumps(marker), encoding="utf-8")
    (workspace / "runtime-ready.json").write_text("{}", encoding="utf-8")
    ops = FakeOperations()
    parent = {
        "ProcessId": os.getpid(),
        "ParentProcessId": 100,
        "ExecutablePath": str(repo / "lifecycle.exe"),
        "CreationUtc": "2026-10-14T00:00:01Z",
        "CommandLine": "synthetic lifecycle",
    }
    ops.processes[os.getpid()] = parent
    app = lifecycle.SchoolAppLifecycle(repo, ops)
    marker_result = {
        "workspace_id": marker["workspace_id"],
        "database": "smhai_school_demo",
        "port": 3314,
    }
    app._validate_prepared_database = lambda *_args, **_kwargs: marker_result
    monkeypatch.setattr(lifecycle, "IS_WINDOWS", True)
    monkeypatch.setattr(lifecycle.shutil, "which", lambda name: str(repo / "node.exe"))
    (repo / "node.exe").touch()
    return repo, workspace, ops, app


def _research_config(workspace: Path, *, port: int = 58540) -> dict[str, object]:
    runtime_file = workspace / "research-runtime.json"
    runtime_file.write_text("{}", encoding="utf-8")
    service_file = workspace / "research-service.json"
    service_doc = {
        "schema": "psynova.research-cat-service.v1",
        "school_scope": {"school_id": 701, "scope": "school:701"},
        "resource_root": str(workspace),
        "listener": {"host": "127.0.0.1", "port": port},
        "signing": {"signing_version": "v1", "accepted_key_versions": ["v1"]},
        "profiles": [],
        "bindings": [],
    }
    service_raw = json.dumps(service_doc, separators=(",", ":")).encode()
    service_file.write_bytes(service_raw)
    cat_python = workspace / "cat-python.exe"
    cat_python.write_bytes(b"test-only executable placeholder")
    cat_source = workspace / "cat-source"
    cat_source.mkdir(exist_ok=True)
    cat_dependencies = workspace / "cat-dependencies"
    cat_dependencies.mkdir(exist_ok=True)
    return {
        "research_runtime_file": runtime_file,
        "research_runtime_sha256": hashlib.sha256(
            runtime_file.read_bytes()
        ).hexdigest(),
        "research_service_file": service_file,
        "research_service_sha256": hashlib.sha256(service_raw).hexdigest(),
        "research_cat_python": cat_python,
        "research_cat_source": cat_source,
        "research_cat_dependencies": cat_dependencies,
    }


def _with_study_use(workspace: Path, config: dict[str, object]) -> dict[str, object]:
    policy_file = workspace / "study-use.json"
    policy_file.write_text("{}", encoding="utf-8")
    config.update(
        {
            "research_study_use_file": policy_file,
            "research_study_use_sha256": hashlib.sha256(policy_file.read_bytes()).hexdigest(),
            "research_source_rights_verified": True,
            "research_latest_study_end": "2027-06-30T15:59:59Z",
        }
    )
    return config


def test_start_passes_exact_research_flags_and_manifest_keeps_only_config_metadata(
    prepared,
):
    _repo, workspace, ops, app = prepared
    config = _research_config(workspace)

    result = app.start(workspace, frontend_mode="dev", research_config=config)

    assert result["status"] == "RUNNING"
    backend_argv = ops.spawned[0][0]
    for name, flag in lifecycle.RESEARCH_CONFIG_FLAGS.items():
        assert backend_argv[backend_argv.index(flag) + 1] == str(config[name])
    manifest = json.loads((workspace / lifecycle.MANIFEST_NAME).read_text())
    assert manifest["research_cat_port"] == 58540
    assert set(manifest["research_config"]) == set(lifecycle.RESEARCH_CONFIG_ARGUMENTS)
    assert [entry["name"] for entry in manifest["services"]] == ["backend", "frontend"]
    assert result["research_cat"]["native_pid"] is None
    assert result["research_cat"]["listener"] == "NOT_INDEPENDENTLY_OBSERVED"


def test_study_use_start_adds_exact_flags_and_manifest_nonsecret_fields(
    prepared, monkeypatch
):
    _repo, workspace, ops, app = prepared
    import school_backend

    monkeypatch.setattr(school_backend, "_validate_study_use_policy", lambda **_kwargs: None)
    config = _with_study_use(workspace, _research_config(workspace))

    result = app.start(workspace, frontend_mode="dev", research_config=config)

    argv = ops.spawned[0][0]
    assert argv[argv.index("--research-study-use-file") + 1] == str(
        config["research_study_use_file"]
    )
    assert argv[argv.index("--research-source-rights-verified")] == (
        "--research-source-rights-verified"
    )
    rights_index = argv.index("--research-source-rights-verified")
    assert argv[rights_index + 1] != "True"
    manifest = json.loads((workspace / lifecycle.MANIFEST_NAME).read_text())
    assert set(manifest["research_config"]) == set(
        lifecycle.RESEARCH_CONFIG_ARGUMENTS + lifecycle.RESEARCH_STUDY_USE_ARGUMENTS
    )
    assert manifest["research_config"]["research_source_rights_verified"] is True
    assert result["status"] == "RUNNING"


def test_research_lifecycle_stop_checks_backend_manager_listener_without_killing_it(
    prepared,
):
    _repo, workspace, ops, app = prepared
    app.start(
        workspace, frontend_mode="dev", research_config=_research_config(workspace)
    )

    stopped = app.stop(workspace)

    assert stopped["status"] == "STOPPED"
    assert stopped["research_cat"]["listener"] == "ABSENT_AFTER_BACKEND_STOP"
    assert 990 not in ops.terminated
    assert 58540 not in ops.bound


def test_residual_research_listener_persists_partial_stop_and_is_never_killed(prepared):
    _repo, workspace, ops, app = prepared
    ops.cleanup_research_on_backend_stop = False
    app.start(
        workspace, frontend_mode="dev", research_config=_research_config(workspace)
    )

    with pytest.raises(lifecycle.LifecycleError, match="Research CAT listener remains"):
        app.stop(workspace)

    manifest = json.loads((workspace / lifecycle.MANIFEST_NAME).read_text())
    assert manifest["state"] == "STOP_PARTIAL"
    assert manifest["failure_code"] == "RESEARCH_CAT_LISTENER_REMAINS"
    assert 58540 in ops.bound
    assert 990 not in ops.terminated
    status = app.status(workspace)
    assert status["status"] == "STOP_PARTIAL"
    assert status["research_cat"]["listener"] == "PRESENT_UNVERIFIED_OWNER"


def test_research_cat_port_must_be_free_and_distinct_before_any_spawn(prepared):
    _repo, workspace, ops, app = prepared
    config = _research_config(workspace)
    ops.bound[58540] = [
        {"OwningProcess": 990, "LocalAddress": "127.0.0.1", "LocalPort": 58540}
    ]

    with pytest.raises(lifecycle.LifecycleError, match="port is occupied"):
        app.start(workspace, frontend_mode="dev", research_config=config)
    assert ops.spawned == []


@pytest.mark.parametrize("port", [8088, 4178, 8180, 8190])
def test_research_cat_port_cannot_collide_with_application_or_module_ports(
    prepared, port
):
    _repo, workspace, ops, app = prepared

    with pytest.raises(lifecycle.LifecycleError, match="distinct"):
        app.start(
            workspace,
            frontend_mode="dev",
            research_config=_research_config(workspace, port=port),
        )
    assert ops.spawned == []


def test_partial_or_cross_workspace_config_is_rejected_without_spawn(prepared):
    _repo, workspace, ops, app = prepared
    config = _research_config(workspace)
    del config["research_cat_dependencies"]
    with pytest.raises(lifecycle.LifecycleError, match="all pinned fields"):
        app.start(workspace, frontend_mode="dev", research_config=config)

    config = _research_config(workspace)
    outside = workspace.parent / "outside-runtime.json"
    outside.write_text("{}", encoding="utf-8")
    config["research_runtime_file"] = outside
    with pytest.raises(lifecycle.LifecycleError, match="pinned preflight"):
        app.start(workspace, frontend_mode="dev", research_config=config)
    assert ops.spawned == []


def test_deleted_config_does_not_block_owned_stop_but_fresh_start_revalidates(prepared):
    _repo, workspace, ops, app = prepared
    config = _research_config(workspace)
    app.start(workspace, frontend_mode="dev", research_config=config)
    runtime_file = config["research_runtime_file"]
    service_file = config["research_service_file"]
    runtime_file.unlink()
    service_file.unlink()

    assert app.status(workspace)["status"] == "RUNNING"
    assert app.stop(workspace)["status"] == "STOPPED"
    spawned_before = len(ops.spawned)
    with pytest.raises(lifecycle.LifecycleError, match="pinned preflight"):
        app.start(workspace, frontend_mode="dev", research_config=config)
    assert len(ops.spawned) == spawned_before
    assert not list(workspace.glob("school-app-lifecycle.stopped-*.json"))


def test_deleted_study_policy_does_not_block_status_or_stop(prepared, monkeypatch):
    _repo, workspace, _ops, app = prepared
    import school_backend

    monkeypatch.setattr(school_backend, "_validate_study_use_policy", lambda **_kwargs: None)
    config = _with_study_use(workspace, _research_config(workspace))
    app.start(workspace, frontend_mode="dev", research_config=config)
    Path(config["research_study_use_file"]).unlink()

    assert app.status(workspace)["status"] == "RUNNING"
    assert app.stop(workspace)["status"] == "STOPPED"


def test_manifest_rejects_partial_research_config_and_unapproved_backend_argv(prepared):
    _repo, workspace, _ops, app = prepared
    app.start(
        workspace, frontend_mode="dev", research_config=_research_config(workspace)
    )
    path = workspace / lifecycle.MANIFEST_NAME
    manifest = json.loads(path.read_text())
    manifest["research_config"].pop("research_service_sha256")
    lifecycle._atomic_write(path, manifest)
    with pytest.raises(lifecycle.LifecycleError, match="configuration is invalid"):
        app.status(workspace)


def test_study_manifest_rejects_false_rights_or_invalid_expiry(prepared, monkeypatch):
    _repo, workspace, _ops, app = prepared
    import school_backend

    monkeypatch.setattr(school_backend, "_validate_study_use_policy", lambda **_kwargs: None)
    config = _with_study_use(workspace, _research_config(workspace))
    app.start(workspace, frontend_mode="dev", research_config=config)
    path = workspace / lifecycle.MANIFEST_NAME
    original = json.loads(path.read_text())
    original["research_config"]["research_source_rights_verified"] = False
    lifecycle._atomic_write(path, original)
    with pytest.raises(lifecycle.LifecycleError, match="study-use configuration"):
        app.status(workspace)

    original["research_config"]["research_source_rights_verified"] = True
    original["research_config"]["research_latest_study_end"] = "2027-06-30T23:59:59+08:00"
    lifecycle._atomic_write(path, original)
    with pytest.raises(lifecycle.LifecycleError, match="study-use configuration"):
        app.status(workspace)


def test_study_backend_argv_flag_tampering_is_rejected(prepared, monkeypatch):
    _repo, workspace, _ops, app = prepared
    import school_backend

    monkeypatch.setattr(school_backend, "_validate_study_use_policy", lambda **_kwargs: None)
    app.start(
        workspace,
        frontend_mode="dev",
        research_config=_with_study_use(workspace, _research_config(workspace)),
    )
    path = workspace / lifecycle.MANIFEST_NAME
    manifest = json.loads(path.read_text())
    backend_service = next(item for item in manifest["services"] if item["name"] == "backend")
    argv = backend_service["argv"]
    argv.remove("--research-source-rights-verified")
    lifecycle._atomic_write(path, manifest)
    with pytest.raises(lifecycle.LifecycleError, match="command identity changed"):
        app.status(workspace)
    manifest["research_config"] = _research_config(workspace)
    manifest["research_config"] = {
        name: str(value) for name, value in manifest["research_config"].items()
    }
    backend_service = next(
        service for service in manifest["services"] if service["name"] == "backend"
    )
    backend_service["argv"].append("--not-approved")
    lifecycle._atomic_write(path, manifest)
    with pytest.raises(lifecycle.LifecycleError, match="command identity changed"):
        app.status(workspace)


def test_start_parser_accepts_seven_cli_flags_as_one_complete_set(tmp_path):
    args = lifecycle.build_parser().parse_args(
        [
            "start",
            "--workspace",
            str(tmp_path),
            "--frontend-mode",
            "dev",
            "--research-runtime-file",
            str(tmp_path / "runtime.json"),
            "--research-runtime-sha256",
            "a" * 64,
            "--research-service-file",
            str(tmp_path / "service.json"),
            "--research-service-sha256",
            "b" * 64,
            "--research-cat-python",
            str(tmp_path / "python.exe"),
            "--research-cat-source",
            str(tmp_path / "cat-source"),
            "--research-cat-dependencies",
            str(tmp_path / "cat-deps"),
        ]
    )
    assert all(
        getattr(args, name) is not None for name in lifecycle.RESEARCH_CONFIG_ARGUMENTS
    )


def test_start_parser_accepts_four_study_use_flags_as_one_complete_set(tmp_path):
    args = lifecycle.build_parser().parse_args(
        [
            "start", "--workspace", str(tmp_path), "--frontend-mode", "dev",
            "--research-runtime-file", str(tmp_path / "runtime.json"),
            "--research-runtime-sha256", "a" * 64,
            "--research-service-file", str(tmp_path / "service.json"),
            "--research-service-sha256", "b" * 64,
            "--research-cat-python", str(tmp_path / "python.exe"),
            "--research-cat-source", str(tmp_path / "cat-source"),
            "--research-cat-dependencies", str(tmp_path / "cat-deps"),
            "--research-study-use-file", str(tmp_path / "policy.json"),
            "--research-study-use-sha256", "c" * 64,
            "--research-source-rights-verified",
            "--research-latest-study-end", "2027-06-30T15:59:59Z",
        ]
    )
    assert all(
        getattr(args, name) is not None for name in lifecycle.RESEARCH_CONFIG_ARGUMENTS
    )
    assert args.research_source_rights_verified is True
    assert args.research_latest_study_end == "2027-06-30T15:59:59Z"


def test_lifecycle_rejects_partial_or_false_study_use_before_spawn(prepared, monkeypatch):
    _repo, workspace, ops, _app = prepared
    import school_backend

    monkeypatch.setattr(school_backend, "_validate_study_use_policy", lambda **_kwargs: None)
    partial = _with_study_use(workspace, _research_config(workspace))
    partial.pop("research_latest_study_end")
    with pytest.raises(lifecycle.LifecycleError, match="all pinned fields"):
        lifecycle._validated_research_config(partial, workspace)

    false_flag = _with_study_use(workspace, _research_config(workspace))
    false_flag["research_source_rights_verified"] = False
    with pytest.raises(lifecycle.LifecycleError, match="pinned preflight"):
        lifecycle._validated_research_config(false_flag, workspace)
    assert ops.spawned == []


def test_lifecycle_cli_rejects_partial_research_flag_set_without_echoing_path(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(lifecycle, "IS_WINDOWS", True)

    code = lifecycle.main(
        [
            "start",
            "--workspace",
            str(tmp_path),
            "--frontend-mode",
            "dev",
            "--research-runtime-file",
            str(tmp_path / "private-path.json"),
        ]
    )

    output = capsys.readouterr().out
    assert code == 2
    assert json.loads(output) == {"error_type": "LifecycleError", "status": "BLOCKED"}
    assert str(tmp_path) not in output


def test_status_cli_returns_failure_exit_for_residual_research_listener(
    tmp_path, monkeypatch, capsys
):
    class FakeLifecycle:
        def __init__(self, _repo):
            pass

        def status(self, _workspace):
            return {
                "status": "STOP_PARTIAL",
                "research_cat": {"listener": "PRESENT_UNVERIFIED_OWNER"},
            }

    monkeypatch.setattr(lifecycle, "SchoolAppLifecycle", FakeLifecycle)

    code = lifecycle.main(["status", "--workspace", str(tmp_path)])

    assert code == 2
    assert json.loads(capsys.readouterr().out)["status"] == "STOP_PARTIAL"


def test_prepared_database_preflight_receives_exact_research_cli_arguments(
    prepared, monkeypatch
):
    _repo, workspace, _ops, app = prepared
    del app._validate_prepared_database
    config_values = _research_config(workspace)
    config = lifecycle._validated_research_config(config_values, workspace)
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "preflight": "PASS",
                    "database": "smhai_school_demo",
                    "port": 3314,
                }
            ),
        )

    marker = workspace / "workspace.json"
    marker.write_text(json.dumps({"workspace_id": "synthetic-research-workspace"}))
    (workspace / "runtime-ready.json").write_text(
        json.dumps(
            {
                "workspace_id": "synthetic-research-workspace",
                "state": "VERIFIED",
                "database": "smhai_school_demo",
                "port": 3314,
            }
        )
    )
    import prepare_school_runtime

    monkeypatch.setattr(
        prepare_school_runtime,
        "validate_marker",
        lambda *_args: {
            "workspace_id": "synthetic-research-workspace",
            "database": "smhai_school_demo",
            "port": 3314,
        },
    )
    monkeypatch.setattr(prepare_school_runtime, "verify_process", lambda *_args: None)
    monkeypatch.setattr(lifecycle.subprocess, "run", run)

    assert (
        app._validate_prepared_database(
            workspace,
            backend_port=8088,
            frontend_port=4178,
            llm_profile="default",
            research_config=config,
        )["workspace_id"]
        == "synthetic-research-workspace"
    )
    argv = calls[0][0]
    for name, flag in lifecycle.RESEARCH_CONFIG_FLAGS.items():
        assert argv[argv.index(flag) + 1] == str(config_values[name])
    assert calls[0][1]["shell"] is False


@pytest.mark.parametrize("identity_failure", ["missing", "incomplete"])
def test_unverified_backend_spawn_is_readable_but_never_adopted_or_stopped(
    prepared, identity_failure
):
    _repo, workspace, ops, app = prepared
    original_inspect = ops.inspect_process

    def inspect(pid):
        identity = original_inspect(pid)
        if pid == 901:
            if identity_failure == "missing":
                return None
            return {key: value for key, value in identity.items() if key != "CommandLine"}
        return identity

    ops.inspect_process = inspect
    with pytest.raises(lifecycle.LifecycleError, match="start incomplete"):
        app.start(
            workspace,
            frontend_mode="dev",
            research_config=_research_config(workspace),
        )

    manifest_path = workspace / lifecycle.MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["state"] == "PARTIAL_FAILURE"
    backend = manifest["services"][0]
    assert backend["identity_state"] == "UNAVAILABLE"
    assert backend["pid"] == 901
    assert backend["processes"] == []

    status = app.status(workspace)
    assert status["manifest_validated"] is True
    assert status["services"]["backend"]["owned_process"] is False
    assert status["services"]["backend"]["spawn_pid_candidate"] == 901
    assert status["services"]["backend"]["listener"] == "PRESENT_UNVERIFIED_OWNER"
    assert status["research_cat"]["listener"] == "PRESENT_UNVERIFIED_OWNER"

    with pytest.raises(lifecycle.LifecycleError, match="identity is unavailable"):
        app.stop(workspace)
    blocked = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert blocked["state"] == "STOP_BLOCKED_IDENTITY_UNAVAILABLE"
    assert ops.terminated == []
    assert 901 in ops.processes
    assert 8088 in ops.bound and 58540 in ops.bound
    assert app.status(workspace)["manifest_validated"] is True
