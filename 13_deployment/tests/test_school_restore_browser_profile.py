import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_restore_browser_qa as qa


def profile(target_path=qa.TARGET, target_port=3309):
    target_data = target_path / "mysql" / "data"
    source_data = qa.SOURCE / "mysql" / "data"
    source = {
        "workspace_id": "source-workspace-unique",
        "parent_pid": 11001,
        "host": "127.0.0.1",
        "port": qa.SOURCE_DATABASE_PORT,
        "database": "smhai_school_demo",
        "data_directory": str(source_data),
        "synthetic_only": True,
    }
    target = {
        "workspace_id": "target-workspace-unique",
        "parent_pid": 22002,
        "host": "127.0.0.1",
        "port": target_port,
        "database": "smhai_school_demo",
        "data_directory": str(target_data),
        "synthetic_only": True,
    }
    state = {
        "phase": "DATA_KEYS_RUNTIME_VERIFIED_REQUIRES_BROWSER",
        "workspace": str(target_path),
        "workspace_id": target["workspace_id"],
        "source_workspace_id": source["workspace_id"],
        "host": "127.0.0.1",
        "port": target_port,
        "database": target["database"],
        "data_directory": target["data_directory"],
        "synthetic_only": True,
    }
    return state, source, target


def test_default_restore_profile_remains_accepted_without_native_calls():
    validate = qa.validate_restore_profile
    validate(*profile())
    assert qa.TARGET.name.endswith("-a")
    assert qa.DEFAULT_DATABASE_PORT == 3309
    assert qa.DEFAULT_BACKEND_PORT == 8089
    assert qa.DEFAULT_FRONTEND_PORT == 4179


def test_cli_keeps_old_profile_defaults_and_accepts_explicit_target_ports():
    defaults = qa.build_parser().parse_args([])
    assert defaults.target == qa.TARGET
    assert defaults.database_port == 3309
    assert defaults.backend_port == 8089
    assert defaults.frontend_port == 4179

    target_b = Path(r"D:\Projects\.StudentMentalHealthAI-school-restore-20261012-b")
    args = qa.build_parser().parse_args([
        "--target", str(target_b), "--database-port", "3310",
        "--backend-port", "8089", "--frontend-port", "4179",
    ])
    assert args.target == target_b
    assert (args.database_port, args.backend_port, args.frontend_port) == (3310, 8089, 4179)


def test_second_restore_target_accepts_a_distinct_workspace_and_database_port():
    target_path = Path(r"D:\Projects\.StudentMentalHealthAI-school-restore-20261012-b")
    state, source, target = profile(target_path, 3310)

    qa.validate_target_path(target_path)
    qa.validate_service_ports(3310, 8089, 4179)
    qa.validate_restore_profile(state, source, target, target_path=target_path, database_port=3310)


@pytest.mark.parametrize(
    "case",
    [
        "phase", "source", "target", "port", "float_port", "source_port", "overlap", "missing",
        "workspace_path", "data_directory", "shared_data_directory", "duplicate_pid", "nonsynthetic",
    ],
)
def test_wrong_restore_evidence_is_refused(case):
    state, source, target = profile()
    if case == "phase":
        state["phase"] = "FAILED_PRESERVED"
    elif case == "source":
        state["source_workspace_id"] = "other"
    elif case == "target":
        state["workspace_id"] = "other"
    elif case == "port":
        state["port"] = 3308
    elif case == "float_port":
        target["port"] = 3310.0
    elif case == "source_port":
        source["port"] = 3307
    elif case == "overlap":
        source["workspace_id"] = target["workspace_id"]
        state["source_workspace_id"] = source["workspace_id"]
    elif case == "missing":
        source.clear()
        state.pop("source_workspace_id")
    elif case == "workspace_path":
        state["workspace"] = str(qa.SOURCE)
    elif case == "data_directory":
        state["data_directory"] = str(qa.SOURCE / "mysql" / "data")
    elif case == "shared_data_directory":
        target["data_directory"] = source["data_directory"]
        state["data_directory"] = source["data_directory"]
    elif case == "duplicate_pid":
        target["parent_pid"] = source["parent_pid"]
    elif case == "nonsynthetic":
        target["synthetic_only"] = False
    with pytest.raises(ValueError, match="Verified isolated"):
        qa.validate_restore_profile(state, source, target)


@pytest.mark.parametrize(
    "target_path",
    [
        Path(r"D:\Projects\ordinary-directory"),
        Path(r"D:\Projects\.StudentMentalHealthAI-school-workspace-20261011"),
        Path(r"D:\Projects\nested\.StudentMentalHealthAI-school-restore-20261012-c"),
        Path(r"D:\Projects\StudentMentalHealthAI-m0-integration\nested"),
    ],
)
def test_target_path_rejects_unapproved_names_and_overlaps(target_path):
    with pytest.raises(ValueError, match="Verified isolated"):
        qa.validate_target_path(target_path)


@pytest.mark.parametrize(
    "database,backend,frontend",
    [
        (3308, 8089, 4179),  # source DB port is never a restore target
        (3400, 8089, 4179),
        (3310, 8089, 8089),
        (3310, 3310, 4179),
        (3310, 3308, 4179),
        (3310, 8089, 3308),
        (3310, True, 4179),
        (3310, 1023, 4179),
        (3310, 8089, 65536),
        (3310, 8088, 4178),
        (3310, 8090, 4180),
    ],
)
def test_service_port_profile_rejects_out_of_range_or_colliding_ports(database, backend, frontend):
    with pytest.raises(ValueError, match="Invalid loopback"):
        qa.validate_service_ports(database, backend, frontend)


def test_service_port_profile_accepts_finite_loopback_ports():
    qa.validate_service_ports(3310, 8089, 4179)


def _owned_service_fixture(tmp_path, monkeypatch):
    workspace = tmp_path / ".StudentMentalHealthAI-school-restore-20261012-test"
    workspace.mkdir()
    timestamp = "2026-10-12T04:05:06.123456Z"
    parent_pid = 4100
    commands = {}
    processes = {}
    listeners = {}
    services = []
    exe = str(Path(sys.executable).resolve())
    for pid, port, argv in (
        (4101, 8089, ["python.exe", "school_backend.py", "--workspace", str(workspace), "--port", "8089", "--frontend-port", "4179"]),
        (4102, 4179, ["node.exe", "vite.js", "--host", "127.0.0.1", "--port", "4179", "--strictPort"]),
    ):
        command_line = f"fixture-command-{pid}"
        commands[command_line] = argv
        services.append({
            "pid": pid,
            "port": port,
            "executable": exe,
            "parent_executable": exe,
            "parent_pid": parent_pid,
            "creation_time": timestamp,
            "parent_creation_time": timestamp,
            "command_line": command_line,
            "local_address": "127.0.0.1",
            "name": f"Restored owned service {port}",
        })
        processes[pid] = {
            "ProcessId": pid,
            "ExecutablePath": exe,
            "CommandLine": command_line,
            "CreationUtc": timestamp,
        }
        listeners[port] = [{"OwningProcess": pid, "LocalAddress": "127.0.0.1", "LocalPort": port}]
    processes[parent_pid] = {
        "ProcessId": parent_pid,
        "ExecutablePath": exe,
        "CommandLine": "fixture-parent-command",
        "CreationUtc": timestamp,
    }
    manifest = {
        "schema_version": qa._RESTORE_PROCESS_SCHEMA,
        "workspace": str(workspace),
        "services": services,
    }
    (workspace / "restore-processes.json").write_text(json.dumps(manifest), encoding="utf-8")

    class FakeOperations:
        def inspect_process(self, pid):
            return processes.get(pid)

        def listeners(self, port):
            return listeners.get(port, [])

    monkeypatch.setattr(qa, "_command_arguments", lambda command: commands[command])
    monkeypatch.setattr(qa, "_reject_reparse_path", lambda _path: None)
    return workspace, manifest, processes, listeners, commands, FakeOperations()


def test_owned_listener_proof_matches_target_processes_and_loopback_ports(tmp_path, monkeypatch):
    workspace, _manifest, _processes, _listeners, _commands, operations = _owned_service_fixture(
        tmp_path, monkeypatch
    )
    qa.verify_owned_listeners(workspace, operations=operations)


@pytest.mark.parametrize(
    "mutation",
    ["target", "stale_pid", "creation_time", "listener_owner", "backend_workspace", "frontend_host"],
)
def test_owned_listener_proof_fails_closed_on_identity_or_binding_mismatch(
    tmp_path, monkeypatch, mutation
):
    workspace, manifest, processes, listeners, commands, operations = _owned_service_fixture(
        tmp_path, monkeypatch
    )
    if mutation == "target":
        manifest["workspace"] = str(tmp_path / "another-target")
    elif mutation == "stale_pid":
        manifest["services"][0]["pid"] = 4999
    elif mutation == "creation_time":
        processes[4101]["CreationUtc"] = "2026-10-12T04:05:07.000000Z"
    elif mutation == "listener_owner":
        listeners[8089][0]["OwningProcess"] = 4999
    elif mutation in {"backend_workspace", "frontend_host"}:
        service = manifest["services"][0 if mutation == "backend_workspace" else 1]
        argv = list(commands[service["command_line"]])
        if mutation == "backend_workspace":
            argv[argv.index("--workspace") + 1] = str(tmp_path / "another-target")
        else:
            argv[argv.index("127.0.0.1")] = "0.0.0.0"
        commands[service["command_line"]] = argv
    (workspace / "restore-processes.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="Restored service ownership changed"):
        qa.verify_owned_listeners(workspace, operations=operations)


def test_run_builds_target_specific_urls_but_reads_credentials_only_from_fixed_source(tmp_path, monkeypatch):
    source = tmp_path / "source"
    projects = tmp_path / "projects"
    target = projects / ".StudentMentalHealthAI-school-restore-20261012-b"
    (source / "mysql" / "data").mkdir(parents=True)
    (target / "mysql" / "data").mkdir(parents=True)
    target_port = 3310
    state, source_marker, target_marker = profile(target, target_port)
    state["data_directory"] = str(target / "mysql" / "data")
    source_marker["data_directory"] = str(source / "mysql" / "data")
    target_marker["data_directory"] = str(target / "mysql" / "data")
    (source / "workspace.json").write_text(json.dumps(source_marker), encoding="utf-8")
    (target / "workspace.json").write_text(json.dumps(target_marker), encoding="utf-8")
    (target / "restore-state.json").write_text(json.dumps(state), encoding="utf-8")

    monkeypatch.setattr(qa, "SOURCE", source)
    monkeypatch.setattr(qa, "PROJECTS_ROOT", projects)
    monkeypatch.setattr(qa, "REPO", tmp_path / "repo")
    monkeypatch.setattr(qa, "_reject_reparse_path", lambda _path: None)
    monkeypatch.setattr(qa, "load_runtime", lambda workspace, repo: (workspace, repo))
    opened_private_paths = []
    steps = []

    def fake_verify_owned(workspace, backend_port, frontend_port):
        steps.append(("ownership", backend_port, frontend_port))

    monkeypatch.setattr(qa, "verify_owned_listeners", fake_verify_owned)

    def fake_read_private(path):
        steps.append(("credentials", Path(path)))
        opened_private_paths.append(Path(path))
        return {"sealed_source": str(path)}

    monkeypatch.setattr(qa, "read_private", fake_read_private)
    monkeypatch.setattr(qa, "validate_credentials", lambda _private: {slot: {"username": "SYNTHETIC_ACCOUNT", "password": "p" * 24} for slot in qa.ACCOUNT_SLOTS})
    monkeypatch.setattr(qa.ResumeOperations, "inspect_process", lambda _self, _pid: {"owned": True})
    monkeypatch.setattr(qa, "_process_matches", lambda process, marker: bool(process and marker))
    artifacts = target / "browser-qa" / "synthetic-run"
    monkeypatch.setattr(qa, "create_artifact_run_dir", lambda _workspace: artifacts)
    monkeypatch.setattr(qa.shutil, "which", lambda _name: "node")
    monkeypatch.setattr(qa, "safe_node_environment", lambda: {"PATH": "synthetic"})
    monkeypatch.setattr(qa, "sanitize_child_output", lambda *_args, **_kwargs: {"status": "FAIL"})

    captured = {}

    def fake_subprocess(command, **kwargs):
        captured["command"] = command
        captured["payload"] = json.loads(kwargs["input"])
        return SimpleNamespace(stdout="{}", returncode=2)

    monkeypatch.setattr(qa.subprocess, "run", fake_subprocess)

    result = qa.run(target=target, database_port=target_port, backend_port=8089, frontend_port=4179)

    assert captured["payload"]["backend_url"] == "http://127.0.0.1:8089"
    assert captured["payload"]["frontend_url"] == "http://127.0.0.1:4179"
    assert captured["payload"]["credentials"]["alpha.admin"]["password"] == "p" * 24
    assert result["profile"] == {
        "target": str(target),
        "database_port": target_port,
        "backend_port": 8089,
        "frontend_port": 4179,
    }
    # Only the original source's sealed account container is ever opened.
    assert opened_private_paths == [source / qa.ACCOUNT_FILE]
    assert steps == [
        ("ownership", 8089, 4179),
        ("credentials", source / qa.ACCOUNT_FILE),
    ]
