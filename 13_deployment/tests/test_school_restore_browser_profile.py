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

    monkeypatch.setattr(qa, "_bootstrap_runtime_import_paths", lambda: steps.append("bootstrap"))

    monkeypatch.setattr(qa, "verify_owned_listeners", fake_verify_owned)

    def fake_read_private(path):
        steps.append(("credentials", Path(path)))
        opened_private_paths.append(Path(path))
        return {"sealed_source": str(path)}

    monkeypatch.setattr(qa, "read_private", fake_read_private)
    monkeypatch.setattr(qa, "validate_credentials", lambda _private: {slot: {"username": "SYNTHETIC_ACCOUNT", "password": "p" * 24} for slot in qa.ACCOUNT_SLOTS})
    monkeypatch.setattr(qa.ResumeOperations, "inspect_process", lambda _self, _pid: {"owned": True})
    monkeypatch.setattr(qa, "_process_matches", lambda process, marker: bool(process and marker))
    artifacts = target / "browser-qa" / "20261013T010203Z-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    artifacts.mkdir(parents=True)
    monkeypatch.setattr(qa, "create_artifact_run_dir", lambda _workspace: artifacts)
    monkeypatch.setattr(qa.shutil, "which", lambda _name: "node")
    monkeypatch.setattr(qa, "safe_node_environment", lambda: {"PATH": "synthetic"})
    monkeypatch.setattr(qa, "sanitize_child_output", lambda *_args, **_kwargs: {"status": "FAIL"})

    captured = {}

    def fake_subprocess(command, **kwargs):
        captured["command"] = command
        captured["payload"] = json.loads(kwargs["input"])
        return SimpleNamespace(stdout='{"credential":"restore-raw-stdout-sentinel"}', returncode=2)

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
    persisted = json.loads((artifacts / qa.RESTORE_RESULT_NAME).read_text(encoding="utf-8"))
    assert persisted == result
    assert "restore-raw-stdout-sentinel" not in json.dumps(persisted)
    # Only the original source's sealed account container is ever opened.
    assert opened_private_paths == [source / qa.ACCOUNT_FILE]
    assert steps == [
        ("ownership", 8089, 4179),
        "bootstrap",
        ("credentials", source / qa.ACCOUNT_FILE),
    ]


def test_runtime_bootstrap_uses_only_existing_project_isolated_import_paths(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    site_packages = repo / "11_database" / ".venv" / "Lib" / "site-packages"
    database = repo / "11_database"
    backend = repo / "09_backend" / "src"
    site_packages.mkdir(parents=True)
    database.mkdir(exist_ok=True)
    backend.mkdir(parents=True)
    monkeypatch.setattr(qa, "REPO", repo)
    monkeypatch.setattr(sys, "path", [])

    added = qa._bootstrap_runtime_import_paths()

    assert [str(path.resolve()) for path in added] == [
        str(site_packages.resolve()), str(database.resolve()), str(backend.resolve()),
    ]
    assert sys.path == [str(site_packages.resolve()), str(database.resolve()), str(backend.resolve())]


def _trusted_result_artifact(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    source = projects / ".StudentMentalHealthAI-school-workspace-20261011"
    repo = tmp_path / "repo"
    target = projects / ".StudentMentalHealthAI-school-restore-20261013-writer"
    source.mkdir()
    repo.mkdir()
    target.mkdir()
    artifact = target / "browser-qa" / "20261013T010203Z-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    artifact.mkdir(parents=True)
    monkeypatch.setattr(qa, "PROJECTS_ROOT", projects)
    monkeypatch.setattr(qa, "SOURCE", source)
    monkeypatch.setattr(qa, "REPO", repo)
    return target, artifact


def test_restore_result_writer_persists_only_the_sanitized_result_exclusively(tmp_path, monkeypatch):
    target, artifact = _trusted_result_artifact(tmp_path, monkeypatch)
    result = {
        "status": "FAIL", "runner_status": "FAIL", "restored_workspace": True,
        "results": [{"slot": "alpha.student", "status": "FAIL", "diagnostic": {
            "stage": "student_history", "substage": "metadata_render",
            "code": "NULL_TIME_LABEL_MISMATCH", "current_path": "student_history",
        }}],
        "profile": {"database_port": 3310, "backend_port": 8089, "frontend_port": 4179},
        "artifact_dir": str(artifact),
    }

    output = qa.write_sanitized_restore_result(target, artifact, result)

    assert output == artifact / qa.RESTORE_RESULT_NAME
    assert json.loads(output.read_text(encoding="utf-8")) == result
    contents = output.read_bytes()
    with pytest.raises(FileExistsError):
        qa.write_sanitized_restore_result(target, artifact, {"status": "PASS"})
    assert output.read_bytes() == contents


def test_restore_result_writer_rejects_reparse_artifact_before_writing(tmp_path, monkeypatch):
    target, artifact = _trusted_result_artifact(tmp_path, monkeypatch)
    observed = []

    def reject_artifact(path):
        observed.append(Path(path))
        if Path(path) == artifact:
            raise ValueError("reparse sentinel")

    monkeypatch.setattr(qa, "_reject_reparse_path", reject_artifact)
    with pytest.raises(ValueError):
        qa.write_sanitized_restore_result(target, artifact, {"status": "FAIL"})
    assert artifact in observed
    assert not (artifact / qa.RESTORE_RESULT_NAME).exists()


def test_restore_child_sanitizer_allowlists_forbidden_route_diagnostic_only(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    sentinel = "ASSESS_private-sentinel-cookie-dom"
    stages = {key: "PASS" for key in ("blank_login", "real_login", "role_route", "auth_me", "screenshot",
                                      "forbidden_route", "forbidden_api", "ui_logout", "blank_restore")}
    stages["forbidden_route"] = "FAIL"
    child = {
        "results": [{
            "slot": "alpha.student", "status": "FAIL", "stages": stages,
            "diagnostic": {
                "stage": "forbidden_route", "substage": "role_redirect",
                "code": "ROLE_REDIRECT_NOT_COMPLETED", "current_path": "admin_overview",
            },
            "raw_path": f"/student/assessment/{sentinel}", "exception": sentinel,
        }],
    }

    result = qa.sanitize_restore_child_output(
        json.dumps(child), artifact_dir=artifact_dir, child_exit_code=2,
    )
    student = next(item for item in result["results"] if item["slot"] == "alpha.student")
    assert student["diagnostic"] == {
        "stage": "forbidden_route", "substage": "role_redirect",
        "code": "ROLE_REDIRECT_NOT_COMPLETED", "current_path": "admin_overview",
    }
    assert sentinel not in json.dumps(result)

    child["results"][0]["diagnostic"] = {
        "stage": "student_history", "substage": "metadata_render",
        "code": "NULL_TIME_LABEL_MISMATCH", "current_path": "student_history",
    }
    history_result = qa.sanitize_restore_child_output(
        json.dumps(child), artifact_dir=artifact_dir, child_exit_code=2,
    )
    history_student = next(item for item in history_result["results"] if item["slot"] == "alpha.student")
    assert history_student["diagnostic"]["stage"] == "student_history"

    child["results"][0]["diagnostic"]["current_path"] = f"/admin/{sentinel}"
    unsafe = qa.sanitize_restore_child_output(
        json.dumps(child), artifact_dir=artifact_dir, child_exit_code=2,
    )
    unsafe_student = next(item for item in unsafe["results"] if item["slot"] == "alpha.student")
    assert "diagnostic" not in unsafe_student

    child["results"][0]["diagnostic"] = {
        "stage": "forbidden_route", "substage": "metadata_render",
        "code": "NULL_TIME_LABEL_MISMATCH", "current_path": "student_history",
    }
    mismatched = qa.sanitize_restore_child_output(
        json.dumps(child), artifact_dir=artifact_dir, child_exit_code=2,
    )
    mismatched_student = next(item for item in mismatched["results"] if item["slot"] == "alpha.student")
    assert "diagnostic" not in mismatched_student


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("stage", []),
        ("substage", []),
        ("code", {}),
        ("current_path", []),
        ("stage", 1),
        ("substage", None),
        ("code", 1),
        ("current_path", None),
    ],
)
def test_restore_child_sanitizer_drops_malformed_diagnostic_fields(tmp_path, field, invalid_value):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    stages = {key: "PASS" for key in (
        "blank_login", "real_login", "role_route", "auth_me", "screenshot",
        "forbidden_route", "forbidden_api", "ui_logout", "blank_restore",
    )}
    stages["forbidden_route"] = "FAIL"
    diagnostic = {
        "stage": "forbidden_route", "substage": "role_redirect",
        "code": "ROLE_REDIRECT_NOT_COMPLETED", "current_path": "admin_overview",
    }
    diagnostic[field] = invalid_value
    child = {"results": [{
        "slot": "alpha.student", "status": "FAIL", "stages": stages,
        "diagnostic": diagnostic,
    }]}
    baseline = qa.sanitize_child_output(
        json.dumps(child), artifact_dir=artifact_dir, child_exit_code=2,
    )

    result = qa.sanitize_restore_child_output(
        json.dumps(child), artifact_dir=artifact_dir, child_exit_code=2,
    )
    student = next(item for item in result["results"] if item["slot"] == "alpha.student")
    baseline_student = next(item for item in baseline["results"] if item["slot"] == "alpha.student")
    assert "diagnostic" not in student
    assert student["status"] == baseline_student["status"]
    assert student["stages"] == baseline_student["stages"]


def test_duplicate_child_slots_do_not_add_or_replace_sanitized_diagnostics(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    stages = {key: "PASS" for key in (
        "blank_login", "real_login", "role_route", "auth_me", "screenshot",
        "forbidden_route", "forbidden_api", "ui_logout", "blank_restore",
    )}
    stages["forbidden_route"] = "FAIL"
    child = {"results": [
        {
            "slot": "alpha.student", "status": "FAIL", "stages": stages,
            "diagnostic": {
                "stage": "forbidden_route", "substage": "role_redirect",
                "code": "ROLE_REDIRECT_NOT_COMPLETED", "current_path": "admin_overview",
            },
        },
        {"slot": "alpha.student", "status": "PASS", "stages": {key: "PASS" for key in stages}},
    ]}
    baseline = qa.sanitize_child_output(
        json.dumps(child), artifact_dir=artifact_dir, child_exit_code=2,
    )
    result = qa.sanitize_restore_child_output(
        json.dumps(child), artifact_dir=artifact_dir, child_exit_code=2,
    )
    student = next(item for item in result["results"] if item["slot"] == "alpha.student")
    baseline_student = next(item for item in baseline["results"] if item["slot"] == "alpha.student")
    assert "diagnostic" not in student
    assert student["status"] == baseline_student["status"]
    assert student["stages"] == baseline_student["stages"]
