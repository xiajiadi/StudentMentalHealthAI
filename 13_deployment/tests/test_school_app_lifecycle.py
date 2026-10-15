import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_app_lifecycle as lifecycle
import school_standard_cat as standard_cat


class FakeProcess:
    def __init__(self, pid):
        self.pid = pid

    def poll(self):
        return None


class FakeOperations:
    def __init__(self):
        self.free = {8088, 4178}
        self.bound = {}
        self.processes = {}
        self.ready = {8088: True, 4178: True}
        self.spawned = []
        self.terminated = []
        self.builds = []
        self.next_pid = 501
        self.backend_listener_child = False
        self.backend_base_executable = None
        self.backend_child_executable_override = None
        self.backend_child_tail_override = False
        self.standard_cat_listener_child = False
        self.standard_cat_base_executable = None
        self.standard_cat_child_executable_override = None
        self.standard_cat_child_argv0_override = None
        self.fail_terminate_pid = None
        self.autoexit_parent_after_child = False
        self.exit_before_terminate_pid = None
        self.fail_backend_spawn = False

    def port_is_free(self, port):
        return port in self.free or port not in self.bound

    def listeners(self, port):
        return list(self.bound.get(port, []))

    def inspect_process(self, pid):
        return self.processes.get(pid)

    def spawn(self, argv, *, cwd, env):
        cat_environment = "SMHAI_CAT_PORT" in env
        allowed_cat_environment = {
            "PYTHONPATH",
            "SMHAI_CAT_PORT",
            "SMHAI_CAT_CONFIG",
            "SMHAI_CAT_ITEM_BANK",
        }
        assert not any(name.upper().startswith("DB_") for name in env)
        assert not {"DATABASE_URL", "DATABASE_KEY_FILE", "MYSQL_PWD"} & set(env)
        assert all(
            not name.upper().startswith("SMHAI_")
            or (cat_environment and name in allowed_cat_environment)
            for name in env
        )
        assert "PYTHONPATH" not in env or cat_environment
        if self.fail_backend_spawn and Path(argv[1]).name == "school_backend.py":
            raise lifecycle.LifecycleError("synthetic backend spawn failure")
        pid = self.next_pid
        self.next_pid += 1
        executable = argv[0]
        record = {
            "ProcessId": pid,
            "ParentProcessId": os.getpid(),
            "ExecutablePath": executable,
            "CreationUtc": f"2026-10-13T00:00:{pid % 60:02d}Z",
            "CommandLine": subprocess.list2cmdline(argv),
        }
        self.processes[pid] = record
        port = (
            int(env["SMHAI_CAT_PORT"])
            if cat_environment
            else int(argv[argv.index("--port") + 1])
        )
        listener_pid = pid
        backend_child = (
            self.backend_listener_child
            and Path(argv[1]).name == "school_backend.py"
        )
        cat_child = cat_environment and self.standard_cat_listener_child
        if backend_child or cat_child:
            listener_pid = 900
            if cat_child:
                child_executable = (
                    self.standard_cat_child_executable_override
                    or self.standard_cat_base_executable
                )
            else:
                child_executable = (
                    self.backend_child_executable_override
                    or self.backend_base_executable
                )
            child_argv = [child_executable, *argv[1:]]
            if cat_child and self.standard_cat_child_argv0_override is not None:
                child_argv[0] = self.standard_cat_child_argv0_override
            if self.backend_child_tail_override and backend_child:
                child_argv[child_argv.index("--port") + 1] = "9999"
            self.processes[listener_pid] = {
                "ProcessId": listener_pid,
                "ParentProcessId": pid,
                "ExecutablePath": child_executable,
                "CreationUtc": "2026-10-13T00:01:00Z",
                "CommandLine": subprocess.list2cmdline(child_argv),
            }
        self.bound[port] = [
            {
                "OwningProcess": listener_pid,
                "LocalAddress": "127.0.0.1",
                "LocalPort": port,
            }
        ]
        self.spawned.append((list(argv), cwd, dict(env)))
        return FakeProcess(pid)

    def wait_ready(self, process, port, path, timeout):
        return self.ready.get(port, True)

    def wait_standard_cat_ready(self, process, port, timeout):
        return self.ready.get(port, False)

    def http_ready(self, port, path):
        return self.ready.get(port, False)

    def standard_cat_ready(self, port):
        return self.ready.get(port, False)

    def build_frontend(self, repo, backend_port, preview_output_dir, *, timeout=360.0):
        self.builds.append((repo, backend_port, preview_output_dir))
        (preview_output_dir / "index.html").write_text("synthetic", encoding="utf-8")

    def terminate_verified(self, service, process_identity):
        pid = process_identity["pid"]
        if pid == self.fail_terminate_pid:
            return False
        if pid == self.exit_before_terminate_pid:
            self.processes.pop(pid, None)
            current = self.bound.get(service["port"], [])
            if current and current[0].get("OwningProcess") == pid:
                self.bound.pop(service["port"], None)
            return False
        self.terminated.append(pid)
        current = self.bound.get(service["port"], [])
        if current and current[0].get("OwningProcess") == pid:
            self.bound.pop(service["port"], None)
        process = self.processes.pop(pid, None)
        if pid == 900 and self.autoexit_parent_after_child and process:
            self.processes.pop(process["ParentProcessId"], None)
        return True


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    workspace = tmp_path / "external" / "workspace"
    (repo / "13_deployment").mkdir(parents=True)
    cat_root = repo / "01_cat-engine"
    cat_venv = cat_root / ".venv"
    (cat_venv / "Scripts").mkdir(parents=True)
    (cat_venv / "Scripts" / "python.exe").touch()
    cat_base_home = repo / "cat-base-python"
    cat_base_home.mkdir()
    (cat_base_home / "python.exe").touch()
    (cat_venv / "pyvenv.cfg").write_text(
        f"home = {cat_base_home}\nversion_info = 3.14\n", encoding="utf-8"
    )
    (cat_root / "fixtures").mkdir(parents=True)
    (cat_root / "fixtures" / "demo_cat_config.v1.json").write_text(
        '{"config_version":"synthetic-test"}', encoding="utf-8"
    )
    (cat_root / "fixtures" / "synthetic_item_bank.v1.json").write_text(
        '{"metadata":{"synthetic":true}}', encoding="utf-8"
    )
    cat_app = cat_root / "src" / "cat_engine" / "api" / "app.py"
    cat_app.parent.mkdir(parents=True)
    cat_app.write_text("def main(): pass\n", encoding="utf-8")
    (cat_root / "pyproject.toml").write_text("[project]\nname='synthetic-cat'\n")
    monkeypatch.setattr(
        standard_cat,
        "STANDARD_CAT_CONFIG_SHA256",
        hashlib.sha256(
            (cat_root / "fixtures" / "demo_cat_config.v1.json").read_bytes()
        ).hexdigest(),
    )
    monkeypatch.setattr(
        standard_cat,
        "STANDARD_CAT_BANK_SHA256",
        hashlib.sha256(
            (cat_root / "fixtures" / "synthetic_item_bank.v1.json").read_bytes()
        ).hexdigest(),
    )
    monkeypatch.setattr(
        standard_cat,
        "STANDARD_CAT_ENTRYPOINT_SHA256",
        hashlib.sha256(cat_app.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(
        standard_cat,
        "STANDARD_CAT_SOURCE_SHA256",
        standard_cat.source_fingerprint(repo),
    )
    (repo / "09_backend" / ".venv" / "Scripts").mkdir(parents=True)
    (repo / "09_backend" / ".venv" / "Scripts" / "python.exe").touch()
    backend_venv = repo / "09_backend" / ".venv"
    base_python_home = repo / "backend-base-python"
    base_python_home.mkdir(parents=True)
    base_python = base_python_home / "python.exe"
    base_python.touch()
    (backend_venv / "pyvenv.cfg").write_text(
        f"home = {base_python_home}\nversion_info = 3.12\n", encoding="utf-8"
    )
    (repo / "10_frontend" / "node_modules" / "vite" / "bin").mkdir(parents=True)
    (repo / "10_frontend" / "node_modules" / "vite" / "bin" / "vite.js").touch()
    (workspace).mkdir(parents=True)
    (workspace / "workspace.json").write_text(
        json.dumps({"workspace_id": "ws-synthetic-1"}), encoding="utf-8"
    )
    (workspace / "runtime-ready.json").write_text("{}", encoding="utf-8")
    ops = FakeOperations()
    ops.backend_base_executable = str(base_python.resolve())
    ops.standard_cat_base_executable = str((cat_base_home / "python.exe").resolve())
    app = lifecycle.SchoolAppLifecycle(repo, ops)
    monkeypatch.setattr(
        app,
        "_validate_prepared_database",
        lambda *args, **kwargs: {
            "workspace_id": "ws-synthetic-1",
            "database": "smhai_school_demo",
            "port": 3314,
        },
    )
    monkeypatch.setattr(lifecycle, "IS_WINDOWS", True)
    monkeypatch.setattr(
        app,
        "_parent_identity",
        lambda: {
            "ProcessId": os.getpid(),
            "ExecutablePath": str(repo / "python.exe"),
            "CreationUtc": "2026-10-13T00:00:01Z",
            "CommandLine": "python lifecycle",
        },
        raising=False,
    )
    # start() uses the OS process query directly; fake it through the operation seam.
    original_inspect = ops.inspect_process
    ops.inspect_process = lambda pid: (
        {
            "ProcessId": pid,
            "ParentProcessId": 10,
            "ExecutablePath": str(repo / "python.exe"),
            "CreationUtc": "2026-10-13T00:00:01Z",
            "CommandLine": "python lifecycle",
        }
        if pid == os.getpid()
        else original_inspect(pid)
    )
    return repo, workspace, ops, app


def _rewrite_preview_manifest_as_legacy_0011(app, workspace, ops):
    path = workspace / lifecycle.MANIFEST_NAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["required_revision"] = "20261014_0011"
    manifest.pop("frontend_preview_dir", None)
    service = next(item for item in manifest["services"] if item["name"] == "frontend")
    argv = app._frontend_argv("preview", service["port"])
    command_line = subprocess.list2cmdline(argv)
    service["argv"] = argv
    service["command_line"] = command_line
    for process_identity in service["processes"]:
        process_identity["argv"] = argv
        process_identity["command_line"] = command_line
    for record_key in ("listener", "listener_candidate"):
        record = service.get(record_key)
        if isinstance(record, dict):
            record["argv"] = argv
            record["command_line"] = command_line
    ops.processes[service["pid"]]["CommandLine"] = command_line
    lifecycle._atomic_write(path, manifest)
    return manifest


def test_atomic_write_preserves_file_won_by_exclusive_create_race(
    tmp_path, monkeypatch
):
    manifest = tmp_path / "manifest.json"
    temporary = tmp_path / "manifest.json.tmp"
    temporary.write_bytes(b"pre-existing synthetic temp")
    path_type = type(temporary)
    original_lstat = path_type.lstat
    checks = 0

    def fake_lstat(path):
        nonlocal checks
        if path == temporary:
            checks += 1
            if checks <= 2:
                raise FileNotFoundError(path)
        return original_lstat(path)

    monkeypatch.setattr(path_type, "lstat", fake_lstat)
    with pytest.raises(lifecycle.LifecycleError, match="could not be saved"):
        lifecycle._atomic_write(manifest, {"state": "synthetic"})

    assert temporary.read_bytes() == b"pre-existing synthetic temp"
    assert not manifest.exists()


def test_atomic_write_rejects_raw_dangling_reparse_temp_path(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    temporary = tmp_path / "manifest.json.tmp"
    path_type = type(temporary)
    original_lstat = path_type.lstat

    def fake_lstat(path):
        if path == temporary:
            return SimpleNamespace(
                st_file_attributes=lifecycle.FILE_ATTRIBUTE_REPARSE_POINT,
                st_reparse_tag=lifecycle.IO_REPARSE_TAG_MOUNT_POINT,
            )
        return original_lstat(path)

    monkeypatch.setattr(path_type, "lstat", fake_lstat)
    with pytest.raises(lifecycle.LifecycleError, match="Reparse points"):
        lifecycle._atomic_write(manifest, {"state": "synthetic"})
    assert not manifest.exists()


def test_plan_is_read_only_and_keeps_cpu_gpu_profile_explicit(prepared):
    _repo, workspace, ops, app = prepared
    result = app.plan(workspace, llm_profile="school-gpu-7b", frontend_mode="preview")
    assert result["status"] == "PLAN_ONLY"
    assert result["required_revision"] == lifecycle.CURRENT_SCHOOL_REVISION
    assert result["llm_profile"] == "school-gpu-7b"
    assert result["whole_ready"] is False
    assert all(value == "UNVERIFIED" for value in result["external_modules"].values())
    assert (
        ops.spawned == []
        and ops.builds == []
        and not (workspace / lifecycle.MANIFEST_NAME).exists()
    )


def test_start_dev_records_only_owned_backend_frontend_and_stop(prepared):
    _repo, workspace, ops, app = prepared
    result = app.start(workspace, frontend_mode="dev", llm_profile="default")
    assert result["status"] == "RUNNING"
    assert [
        Path(entry[0][1]).name.casefold() == "school_backend.py"
        for entry in ops.spawned
    ] == [True, False]
    manifest = json.loads(
        (workspace / lifecycle.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    assert manifest["required_revision"] == lifecycle.CURRENT_SCHOOL_REVISION
    assert "--cat-port" not in ops.spawned[0][0]
    assert {service["port"] for service in manifest["services"]} == {8088, 4178}
    assert all(
        service["creation_time"] and service["argv"] and service["parent"]
        for service in manifest["services"]
    )
    assert all(
        service["listener"]["local_address"] == "127.0.0.1"
        for service in manifest["services"]
    )
    assert all(
        service["listener_candidate"]["identity_verified"]
        for service in manifest["services"]
    )
    stopped = app.stop(workspace)
    assert stopped["status"] == "STOPPED"
    assert set(ops.terminated) == {501, 502}
    assert ops.bound == {}


def test_opt_in_standard_cat_starts_first_and_stops_last(prepared):
    _repo, workspace, ops, app = prepared
    ops.ready[8180] = True

    result = app.start(
        workspace,
        frontend_mode="dev",
        llm_profile="default",
        enable_standard_cat=True,
    )

    assert result["status"] == "RUNNING"
    manifest = json.loads(
        (workspace / lifecycle.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    assert [item["name"] for item in manifest["services"]] == [
        "standard_cat",
        "backend",
        "frontend",
    ]
    cat_argv, cat_cwd, cat_env = ops.spawned[0]
    assert cat_argv == [
        str(_repo / "01_cat-engine" / ".venv" / "Scripts" / "python.exe"),
        "-m",
        "cat_engine.api.app",
    ]
    assert cat_cwd == _repo / "01_cat-engine"
    assert cat_env["SMHAI_CAT_PORT"] == "8180"
    assert Path(cat_env["PYTHONPATH"]) == _repo / "01_cat-engine" / "src"
    backend_argv = ops.spawned[1][0]
    assert backend_argv[backend_argv.index("--cat-port") + 1] == "8180"
    assert result["external_modules"]["cat"] == "READY"

    stopped = app.stop(workspace)
    assert stopped["status"] == "STOPPED"
    assert stopped["standard_cat"]["readiness"] == "STOPPED"
    assert ops.terminated == [503, 502, 501]
    assert ops.bound == {}


def test_standard_cat_venv_launcher_owns_only_verified_base_python_listener(prepared):
    _repo, workspace, ops, app = prepared
    ops.ready[8180] = True
    ops.standard_cat_listener_child = True

    result = app.start(
        workspace,
        frontend_mode="dev",
        enable_standard_cat=True,
    )

    assert result["status"] == "RUNNING"
    manifest = json.loads(
        (workspace / lifecycle.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    cat_service = manifest["services"][0]
    assert cat_service["base_executable"] == ops.standard_cat_base_executable
    assert [entry["role"] for entry in cat_service["processes"]] == [
        "launcher",
        "listener",
    ]
    assert cat_service["listener"]["pid"] == 900
    assert app.status(workspace)["standard_cat"]["readiness"] == "READY"

    assert app.stop(workspace)["status"] == "STOPPED"
    assert ops.terminated == [503, 502, 900, 501]
    assert ops.bound == {}


def test_standard_cat_accepts_windows_redirector_argv0_with_exact_base_process(prepared):
    repo, workspace, ops, app = prepared
    ops.ready[8180] = True
    ops.standard_cat_listener_child = True
    launcher = repo / "01_cat-engine" / ".venv" / "Scripts" / "python.exe"
    ops.standard_cat_child_argv0_override = str(launcher.resolve())

    result = app.start(
        workspace,
        frontend_mode="dev",
        enable_standard_cat=True,
    )

    assert result["status"] == "RUNNING"
    manifest = json.loads(
        (workspace / lifecycle.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    cat_service = manifest["services"][0]
    assert cat_service["listener"]["executable"] == ops.standard_cat_base_executable
    assert cat_service["listener"]["argv"][0] == str(launcher.resolve())
    assert cat_service["listener_candidate"]["identity_verified"] is True
    assert app.status(workspace)["standard_cat"]["readiness"] == "READY"
    assert app.stop(workspace)["status"] == "STOPPED"


def test_standard_cat_rejects_unrelated_python_listener_without_stopping_it(prepared):
    _repo, workspace, ops, app = prepared
    ops.ready[8180] = True
    ops.standard_cat_listener_child = True
    ops.standard_cat_child_executable_override = str(
        workspace.parent / "unrelated-python.exe"
    )

    result = app.start(
        workspace,
        frontend_mode="dev",
        enable_standard_cat=True,
    )

    assert result["status"] == "STOP_BLOCKED_FOREIGN_LISTENER"
    manifest = json.loads(
        (workspace / lifecycle.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    cat_service = manifest["services"][0]
    assert cat_service["listener"] is None
    assert cat_service["listener_candidate"]["identity_verified"] is False
    assert ops.terminated == []
    assert ops.listeners(8180)[0]["OwningProcess"] == 900


def test_standard_cat_rejects_unknown_argv0_even_with_pinned_base_executable(prepared):
    _repo, workspace, ops, app = prepared
    ops.ready[8180] = True
    ops.standard_cat_listener_child = True
    ops.standard_cat_child_argv0_override = str(
        workspace.parent / "unrelated-python.exe"
    )

    result = app.start(
        workspace,
        frontend_mode="dev",
        enable_standard_cat=True,
    )

    assert result["status"] == "STOP_BLOCKED_FOREIGN_LISTENER"
    manifest = json.loads(
        (workspace / lifecycle.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    candidate = manifest["services"][0]["listener_candidate"]
    assert candidate["executable"] == ops.standard_cat_base_executable
    assert candidate["argv"][0] == str(workspace.parent / "unrelated-python.exe")
    assert candidate["identity_verified"] is False
    assert ops.terminated == []
    assert ops.listeners(8180)[0]["OwningProcess"] == 900


def test_standard_cat_foreign_listener_is_never_adopted(prepared):
    _repo, workspace, ops, app = prepared
    ops.bound[8180] = [
        {"OwningProcess": 9901, "LocalAddress": "127.0.0.1", "LocalPort": 8180}
    ]

    with pytest.raises(lifecycle.LifecycleError, match="refusing to adopt"):
        app.start(
            workspace,
            frontend_mode="dev",
            enable_standard_cat=True,
        )

    assert ops.spawned == []
    assert not (workspace / lifecycle.MANIFEST_NAME).exists()
    assert 9901 in [row["OwningProcess"] for row in ops.listeners(8180)]


def test_standard_cat_is_cleaned_when_later_service_spawn_fails(prepared):
    _repo, workspace, ops, app = prepared
    ops.ready[8180] = True
    ops.fail_backend_spawn = True

    with pytest.raises(lifecycle.LifecycleError, match="start incomplete"):
        app.start(
            workspace,
            frontend_mode="dev",
            enable_standard_cat=True,
        )

    manifest = json.loads(
        (workspace / lifecycle.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    assert manifest["state"] == "PARTIAL_FAILURE"
    assert manifest["failure_code"] == "START_FAILURE_CLEANED"
    assert [item["name"] for item in manifest["services"]] == ["standard_cat"]
    assert ops.terminated == [501]
    assert ops.bound == {}


def test_standard_cat_stop_restart_keeps_explicit_port_and_backend_target(prepared):
    _repo, workspace, ops, app = prepared
    ops.ready[8181] = True
    first = app.start(
        workspace,
        frontend_mode="dev",
        enable_standard_cat=True,
        standard_cat_port=8181,
    )
    assert first["status"] == "RUNNING"
    assert app.stop(workspace)["status"] == "STOPPED"

    ops.next_pid = 601
    restarted = app.start(
        workspace,
        frontend_mode="dev",
        enable_standard_cat=True,
        standard_cat_port=8181,
    )
    assert restarted["status"] == "RUNNING"
    manifest = json.loads(
        (workspace / lifecycle.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    assert manifest["standard_cat"]["port"] == 8181
    assert manifest["services"][0]["port"] == 8181
    backend_argv = next(
        argv for argv, _cwd, _env in ops.spawned if Path(argv[1]).name == "school_backend.py"
    )
    assert backend_argv[backend_argv.index("--cat-port") + 1] == "8181"
    assert len(list(workspace.glob("school-app-lifecycle.stopped-*.json"))) == 1


def test_standard_cat_readiness_requires_synthetic_cat_health_payload(monkeypatch):
    class Response:
        status = 200

        def __init__(self, value):
            self.value = value

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps(self.value).encode("utf-8")

    class Opener:
        def __init__(self, response):
            self.response = response

        def open(self, url, timeout):
            assert url in {
                "http://127.0.0.1:8180/health/ready",
                "http://127.0.0.1:8088/health/ready",
            }
            assert timeout == 1.0
            return self.response

    payload = {
        "status": "READY",
        "service": "cat",
        "synthetic_fixture_only": True,
    }
    monkeypatch.setattr(
        lifecycle.urllib.request,
        "build_opener",
        lambda *_args: Opener(Response(payload)),
    )
    assert lifecycle.LifecycleOperations().standard_cat_ready(8180) is True
    assert (
        lifecycle.LifecycleOperations().http_ready(8088, "/health/ready") is False
    )

    payload["synthetic_fixture_only"] = False
    assert lifecycle.LifecycleOperations().standard_cat_ready(8180) is False
    assert (
        lifecycle.LifecycleOperations().http_ready(8088, "/health/ready") is False
    )


def test_standard_cat_manifest_validation_rechecks_pinned_assets(prepared):
    repo, workspace, ops, app = prepared
    ops.ready[8180] = True
    app.start(workspace, frontend_mode="dev", enable_standard_cat=True)
    config_path = repo / "01_cat-engine" / "fixtures" / "demo_cat_config.v1.json"
    config_path.write_text('{"config_version":"tampered"}', encoding="utf-8")

    with pytest.raises(lifecycle.LifecycleError, match="pins failed validation"):
        app.status(workspace)
    assert ops.terminated == []


def test_standard_cat_cli_is_opt_in_and_keeps_default_port():
    args = lifecycle.build_parser().parse_args(
        [
            "start",
            "--workspace",
            "C:/synthetic/workspace",
            "--frontend-mode",
            "dev",
        ]
    )
    assert args.enable_standard_cat is False
    assert args.standard_cat_port == 8180

    enabled = lifecycle.build_parser().parse_args(
        [
            "start",
            "--workspace",
            "C:/synthetic/workspace",
            "--frontend-mode",
            "dev",
            "--enable-standard-cat",
            "--standard-cat-port",
            "8181",
        ]
    )
    assert enabled.enable_standard_cat is True
    assert enabled.standard_cat_port == 8181


def test_standard_cat_source_fingerprint_is_stable_for_crlf_worktrees(tmp_path):
    lf_root = tmp_path / "lf"
    crlf_root = tmp_path / "crlf"
    for root, newline in ((lf_root, b"\n"), (crlf_root, b"\r\n")):
        source = root / "01_cat-engine" / "src" / "cat_engine" / "api"
        source.mkdir(parents=True)
        (source / "app.py").write_bytes(b"def main():\n    return 1\n".replace(b"\n", newline))
        project = root / "01_cat-engine" / "pyproject.toml"
        project.write_bytes(b"[project]\nname = 'synthetic-cat'\n".replace(b"\n", newline))

    baseline = standard_cat.source_fingerprint(lf_root)
    assert baseline == standard_cat.source_fingerprint(crlf_root)

    app = crlf_root / "01_cat-engine" / "src" / "cat_engine" / "api" / "app.py"
    app.write_bytes(b"def main():\n    return 2\n".replace(b"\n", b"\r\n"))
    assert standard_cat.source_fingerprint(crlf_root) != baseline


def test_standard_cat_source_edit_fails_pinned_preflight(prepared):
    repo, workspace, ops, app = prepared
    entrypoint = repo / standard_cat.STANDARD_CAT_ENTRYPOINT_RELATIVE
    entrypoint.write_text("def main():\n    return 'changed'\n", encoding="utf-8")

    with pytest.raises(lifecycle.LifecycleError, match="preflight failed"):
        app.plan(
            workspace,
            frontend_mode="dev",
            enable_standard_cat=True,
        )

    assert ops.spawned == []


def test_research_programme_worker_manifest_argv_restore_and_live_status(
    prepared, monkeypatch
):
    repo, workspace, ops, app = prepared
    external_manifest = workspace.parent / "programme-manifest.json"
    manifest_sha = lifecycle.RESEARCH_PROGRAMME_MANIFEST_SHA256
    programme_settings = {
        "enabled": True,
        "package_manifest_file": str(external_manifest),
        "package_manifest_sha256": manifest_sha,
        "processor_policy_sha256": lifecycle.RESEARCH_PROGRAMME_PROCESSOR_POLICY_SHA256,
        "model_ref": lifecycle.RESEARCH_PROGRAMME_MODEL_REF,
        "model_digest_sha256": lifecycle.RESEARCH_PROGRAMME_MODEL_DIGEST_SHA256,
        "prompt_ref": lifecycle.RESEARCH_PROGRAMME_PROMPT_REF,
        "prompt_version": lifecycle.RESEARCH_PROGRAMME_PROMPT_VERSION,
        "poll_interval_seconds": 1.0,
        "lease_seconds": 180,
        "max_attempts": 5,
        "shutdown_drain_seconds": 10.0,
    }
    settings = {
        "school_research_runtime_file": str(workspace / "runtime.json"),
        "school_research_runtime_sha256": "d" * 64,
        "school_research_service_file": str(workspace / "service.json"),
        "school_research_service_sha256": "e" * 64,
        "school_research_cat_python": str(repo / "cat-python.exe"),
        "school_research_cat_source": str(repo / "cat-source"),
        "school_research_cat_dependencies": str(repo / "cat-deps"),
        "school_research_base_url": "http://127.0.0.1:8182",
        "school_research_study_use_file": str(workspace / "study-use.json"),
        "school_research_study_use_sha256": "b" * 64,
        "school_research_source_rights_verified": True,
        "research_programme_runtime": {
            "mode": "http",
            "base_url": lifecycle.RESEARCH_PROGRAMME_RUNTIME_URL,
        },
        "research_programme_worker": programme_settings,
    }
    monkeypatch.setattr(
        lifecycle,
        "build_research_settings_kwargs",
        lambda _args, _workspace: settings,
    )
    monkeypatch.setattr(
        app,
        "_validate_prepared_database",
        lambda *args, **kwargs: {
            "workspace_id": "ws-synthetic-1",
            "database": "smhai_school_demo",
            "port": 3314,
        },
    )
    ops.dependency_status = lambda _port, _dependency: {
        "status": "READY",
        "integration": "RESEARCH_STAFF_PROGRAMME_OUTBOX",
    }
    input_config = {
        name: str(workspace / f"{name}.json")
        for name in lifecycle.RESEARCH_CONFIG_ARGUMENTS
    }
    input_config.update(
        {
            "research_runtime_sha256": "d" * 64,
            "research_service_sha256": "e" * 64,
            "research_study_use_file": workspace / "study-use.json",
            "research_study_use_sha256": "b" * 64,
            "research_source_rights_verified": True,
            "research_latest_study_end": "2027-06-30T15:59:59Z",
            lifecycle.RESEARCH_PROGRAMME_WORKER_ENABLED_INPUT_KEY: True,
            "research_programme_manifest_file": external_manifest,
            "research_programme_manifest_sha256": manifest_sha,
        }
    )

    started = app.start(workspace, frontend_mode="dev", research_config=input_config)
    backend_argv = ops.spawned[0][0]
    assert started["research_programme_worker"] == {
        "enabled": True,
        "status": "READY",
        "integration": "RESEARCH_STAFF_PROGRAMME_OUTBOX",
    }
    assert lifecycle.RESEARCH_PROGRAMME_WORKER_FLAG in backend_argv
    assert backend_argv[
        backend_argv.index("--research-programme-manifest-sha256") + 1
    ] == manifest_sha

    manifest = json.loads((workspace / lifecycle.MANIFEST_NAME).read_text(encoding="utf-8"))
    stored_programme = manifest["research_config"][lifecycle.RESEARCH_PROGRAMME_WORKER_CONFIG_KEY]
    assert stored_programme["runtime_url"] == "http://127.0.0.1:8161"
    assert stored_programme["prompt_version"] == "1.2.0"
    restored = lifecycle._research_config_from_manifest(
        manifest, workspace, manifest["backend_port"], manifest["frontend_port"]
    )
    assert restored is not None and restored.programme_worker is not None
    assert restored.programme_worker.manifest_sha256 == manifest_sha

    status = app.status(workspace)
    assert status["research_programme_worker"]["status"] == "READY"
    stopped = app.stop(workspace)
    assert stopped["status"] == "STOPPED"


def test_general_education_draft_config_roundtrips_argv_and_reports_own_status(
    prepared, monkeypatch
):
    from school_research_education_draft_config import ResearchEducationDraftConfig
    from school_research_student_config import StudentResearchConfig

    repo, workspace, ops, app = prepared
    source_config = StudentResearchConfig(
        config_file=str(workspace / "student-source.json"),
        config_sha256="a" * 64,
        school_id=7,
        manifest_file=str(workspace / "source-r3.json"),
        manifest_sha256="ac9cc1641faa565ff7a18866be1c2dbf8aaf16aff7155ea80c38bfd979429a9b",
    )
    draft_config = ResearchEducationDraftConfig(
        config_file=str(workspace / "education-draft.json"),
        config_sha256="b" * 64,
        school_id=7,
        school_study_ref="school-study-r3",
        student_source=source_config,
    )
    monkeypatch.setattr(
        lifecycle, "load_student_research_config", lambda *_args: source_config
    )
    monkeypatch.setattr(
        lifecycle, "load_research_education_draft_config", lambda *_args: draft_config
    )
    settings = {
        "school_research_runtime_file": str(workspace / "runtime.json"),
        "school_research_runtime_sha256": "c" * 64,
        "school_research_service_file": str(workspace / "service.json"),
        "school_research_service_sha256": "d" * 64,
        "school_research_cat_python": str(repo / "cat-python.exe"),
        "school_research_cat_source": str(repo / "cat-source"),
        "school_research_cat_dependencies": str(repo / "cat-deps"),
        "school_research_base_url": "http://127.0.0.1:8182",
        "school_research_study_use_file": str(workspace / "study-use.json"),
        "school_research_study_use_sha256": "e" * 64,
        "school_research_source_rights_verified": True,
        "school_research_latest_study_end": "2027-06-30T15:59:59Z",
    }
    monkeypatch.setattr(
        lifecycle, "build_research_settings_kwargs", lambda *_args: settings
    )
    ops.dependency_status = lambda _port, dependency: (
        {
            "status": "READY",
            "integration": lifecycle.RESEARCH_GENERAL_EDUCATION_DRAFT_INTEGRATION,
        }
        if dependency == "research_general_education_draft_worker"
        else None
    )
    research_input = {
        name: str(workspace / f"{name}.json")
        for name in lifecycle.RESEARCH_CONFIG_ARGUMENTS
    }
    research_input.update(
        {
            "research_runtime_sha256": "c" * 64,
            "research_service_sha256": "d" * 64,
            "research_study_use_file": workspace / "study-use.json",
            "research_study_use_sha256": "e" * 64,
            "research_source_rights_verified": True,
            "research_latest_study_end": "2027-06-30T15:59:59Z",
        }
    )
    student_input = {
        "research_student_config_file": Path(source_config.config_file),
        "research_student_config_sha256": source_config.config_sha256,
    }
    draft_input = {
        "research_education_draft_config_file": Path(draft_config.config_file),
        "research_education_draft_config_sha256": draft_config.config_sha256,
    }

    started = app.start(
        workspace,
        frontend_mode="dev",
        research_config=research_input,
        student_research_config=student_input,
        research_education_draft_config=draft_input,
        input_review_continuation_enabled=True,
    )

    backend_argv = ops.spawned[0][0]
    assert backend_argv[
        backend_argv.index("--research-education-draft-config-file") + 1
    ] == draft_config.config_file
    assert backend_argv[
        backend_argv.index("--research-education-draft-config-sha256") + 1
    ] == draft_config.config_sha256
    assert "--enable-research-education-input-review-continuation" in backend_argv
    manifest = json.loads(
        (workspace / lifecycle.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    assert manifest[lifecycle.RESEARCH_EDUCATION_DRAFT_CONFIG_KEY] == (
        {
            **draft_config.manifest_value(),
            "input_review_continuation_enabled": True,
        }
    )
    restored = lifecycle._research_education_draft_config_from_manifest(manifest)
    assert restored is not None
    assert restored.cli_arguments() == [
        "--research-education-draft-config-file",
        draft_config.config_file,
        "--research-education-draft-config-sha256",
        draft_config.config_sha256,
        "--enable-research-education-input-review-continuation",
    ]
    legacy_manifest = dict(manifest)
    legacy_draft = dict(legacy_manifest[lifecycle.RESEARCH_EDUCATION_DRAFT_CONFIG_KEY])
    legacy_draft.pop("input_review_continuation_enabled")
    legacy_manifest[lifecycle.RESEARCH_EDUCATION_DRAFT_CONFIG_KEY] = legacy_draft
    legacy_restored = lifecycle._research_education_draft_config_from_manifest(
        legacy_manifest
    )
    assert legacy_restored is not None
    assert legacy_restored.input_review_continuation_enabled is False
    assert started["research_general_education_draft_worker"]["status"] == "UNVERIFIED"

    status = app.status(workspace)
    assert status["research_general_education_draft_worker"] == {
        "enabled": True,
        "status": "READY",
        "integration": lifecycle.RESEARCH_GENERAL_EDUCATION_DRAFT_INTEGRATION,
        "input_review_continuation_enabled": True,
    }
    stopped = app.stop(workspace)
    assert stopped["status"] == "STOPPED"
    stopped_manifest = json.loads(
        (workspace / lifecycle.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    assert stopped_manifest[lifecycle.RESEARCH_EDUCATION_DRAFT_CONFIG_KEY][
        "input_review_continuation_enabled"
    ] is True
    app.start(
        workspace,
        frontend_mode="dev",
        research_config=research_input,
        student_research_config=student_input,
        research_education_draft_config=draft_input,
        input_review_continuation_enabled=True,
    )
    restarted_backend_argv = ops.spawned[-2][0]
    assert "--enable-research-education-input-review-continuation" in restarted_backend_argv
    restarted_manifest = json.loads(
        (workspace / lifecycle.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    assert restarted_manifest[lifecycle.RESEARCH_EDUCATION_DRAFT_CONFIG_KEY][
        "input_review_continuation_enabled"
    ] is True
    app.stop(workspace)


def test_general_education_draft_lifecycle_rejects_missing_source_or_study():
    with pytest.raises(lifecycle.LifecycleError, match="requires the approved study"):
        lifecycle._validated_research_education_draft_config(
            {
                "research_education_draft_config_file": Path("C:/synthetic/draft.json"),
                "research_education_draft_config_sha256": "a" * 64,
            },
            research_config=None,
            student_research_config=None,
        )


def test_research_programme_worker_manifest_rejects_prompt_pin_drift(
    prepared, monkeypatch
):
    _repo, workspace, _ops, _app = prepared
    program = {
        "enabled": True,
        "package_manifest_file": str(workspace.parent / "programme-manifest.json"),
        "package_manifest_sha256": lifecycle.RESEARCH_PROGRAMME_MANIFEST_SHA256,
        "runtime_url": lifecycle.RESEARCH_PROGRAMME_RUNTIME_URL,
        "processor_policy_sha256": lifecycle.RESEARCH_PROGRAMME_PROCESSOR_POLICY_SHA256,
        "model_ref": lifecycle.RESEARCH_PROGRAMME_MODEL_REF,
        "model_digest_sha256": lifecycle.RESEARCH_PROGRAMME_MODEL_DIGEST_SHA256,
        "prompt_ref": lifecycle.RESEARCH_PROGRAMME_PROMPT_REF,
        "prompt_version": "1.1.1",
        "poll_interval_seconds": 1.0,
        "lease_seconds": 180,
        "max_attempts": 5,
        "shutdown_drain_seconds": 10.0,
    }
    config = {
        name: str(workspace / f"{name}.json")
        for name in lifecycle.RESEARCH_CONFIG_ARGUMENTS
    }
    config.update(
        {
            "research_runtime_sha256": "d" * 64,
            "research_service_sha256": "e" * 64,
            "research_study_use_file": str(workspace / "study-use.json"),
            "research_study_use_sha256": "b" * 64,
            "research_source_rights_verified": True,
            "research_latest_study_end": "2027-06-30T15:59:59Z",
            lifecycle.RESEARCH_PROGRAMME_WORKER_CONFIG_KEY: program,
        }
    )
    manifest = {
        "research_config": config,
        "research_cat_port": 8182,
    }
    with pytest.raises(lifecycle.LifecycleError, match="pins no longer validate|settings changed"):
        lifecycle._research_config_from_manifest(
            manifest, workspace, 8088, 4178
        )


def test_stopped_111_manifest_upgrades_only_with_current_pins_and_keeps_archive(
    prepared, monkeypatch
):
    repo, workspace, ops, app = prepared
    external_manifest = workspace.parent / "programme-manifest.json"
    settings = {
        "school_research_runtime_file": str(workspace / "runtime.json"),
        "school_research_runtime_sha256": "d" * 64,
        "school_research_service_file": str(workspace / "service.json"),
        "school_research_service_sha256": "e" * 64,
        "school_research_cat_python": str(repo / "cat-python.exe"),
        "school_research_cat_source": str(repo / "cat-source"),
        "school_research_cat_dependencies": str(repo / "cat-deps"),
        "school_research_base_url": "http://127.0.0.1:8182",
        "school_research_study_use_file": str(workspace / "study-use.json"),
        "school_research_study_use_sha256": "b" * 64,
        "school_research_source_rights_verified": True,
        "research_programme_runtime": {
            "mode": "http",
            "base_url": lifecycle.RESEARCH_PROGRAMME_RUNTIME_URL,
        },
        "research_programme_worker": {
            "enabled": True,
            "package_manifest_file": str(external_manifest),
            "package_manifest_sha256": lifecycle.RESEARCH_PROGRAMME_MANIFEST_SHA256,
            "processor_policy_sha256": lifecycle.RESEARCH_PROGRAMME_PROCESSOR_POLICY_SHA256,
            "model_ref": lifecycle.RESEARCH_PROGRAMME_MODEL_REF,
            "model_digest_sha256": lifecycle.RESEARCH_PROGRAMME_MODEL_DIGEST_SHA256,
            "prompt_ref": lifecycle.RESEARCH_PROGRAMME_PROMPT_REF,
            "prompt_version": lifecycle.RESEARCH_PROGRAMME_PROMPT_VERSION,
            "poll_interval_seconds": 1.0,
            "lease_seconds": 180,
            "max_attempts": 5,
            "shutdown_drain_seconds": 10.0,
        },
    }
    monkeypatch.setattr(
        lifecycle,
        "build_research_settings_kwargs",
        lambda _args, _workspace: settings,
    )
    ops.dependency_status = lambda _port, _dependency: {
        "status": "READY",
        "integration": "RESEARCH_STAFF_PROGRAMME_OUTBOX",
    }
    input_config = {
        name: str(workspace / f"{name}.json")
        for name in lifecycle.RESEARCH_CONFIG_ARGUMENTS
    }
    input_config.update(
        {
            "research_runtime_sha256": "d" * 64,
            "research_service_sha256": "e" * 64,
            "research_study_use_file": workspace / "study-use.json",
            "research_study_use_sha256": "b" * 64,
            "research_source_rights_verified": True,
            "research_latest_study_end": "2027-06-30T15:59:59Z",
            lifecycle.RESEARCH_PROGRAMME_WORKER_ENABLED_INPUT_KEY: True,
            "research_programme_manifest_file": external_manifest,
            "research_programme_manifest_sha256": lifecycle.RESEARCH_PROGRAMME_MANIFEST_SHA256,
        }
    )

    app.start(workspace, frontend_mode="dev", research_config=input_config)
    app.stop(workspace)
    manifest_path = workspace / lifecycle.MANIFEST_NAME
    original = json.loads(manifest_path.read_text(encoding="utf-8"))
    original["research_config"][lifecycle.RESEARCH_PROGRAMME_WORKER_CONFIG_KEY][
        "prompt_version"
    ] = "1.1.1"
    lifecycle._atomic_write(manifest_path, original)

    historical = app.status(workspace)
    assert historical["status"] == "STOPPED"
    assert historical["research_programme_worker"] == {
        "enabled": True,
        "status": "UNAVAILABLE",
        "integration": "RESEARCH_STAFF_PROGRAMME_OUTBOX",
        "reason": "LEGACY_PROMPT_PIN",
    }

    old_config = lifecycle._research_config_from_manifest(
        original,
        workspace,
        8088,
        4178,
        allow_legacy_prompt=True,
    )
    new_config = lifecycle._validated_research_config(input_config, workspace)
    lifecycle._require_legacy_programme_upgrade_config_match(old_config, new_config)
    assert new_config is not None and new_config.programme_worker is not None
    lifecycle._require_legacy_programme_upgrade_config_match(
        old_config,
        replace(new_config, port=new_config.port + 1),
    )
    changed_model = replace(
        new_config,
        programme_worker=replace(new_config.programme_worker, model_ref="other-model"),
    )
    changed_source = replace(
        new_config,
        programme_worker=replace(
            new_config.programme_worker,
            manifest_sha256="9" * 64,
        ),
    )
    changed_study = replace(new_config, study_use_sha256="8" * 64)
    changed_runtime = replace(new_config, runtime_sha256="7" * 64)
    for changed_config in (changed_model, changed_source, changed_study, changed_runtime):
        with pytest.raises(
            lifecycle.LifecycleError,
            match="Stopped legacy research programme pins changed",
        ):
            lifecycle._require_legacy_programme_upgrade_config_match(
                old_config,
                changed_config,
            )

    tampered = json.loads(json.dumps(original))
    tampered["research_config"][lifecycle.RESEARCH_PROGRAMME_WORKER_CONFIG_KEY][
        "processor_policy_sha256"
    ] = "0" * 64
    lifecycle._atomic_write(manifest_path, tampered)
    with pytest.raises(lifecycle.LifecycleError, match="pins no longer validate|settings changed"):
        app.status(workspace)
    lifecycle._atomic_write(manifest_path, original)

    ops.bound[8088] = [
        {"OwningProcess": 9901, "LocalAddress": "127.0.0.1", "LocalPort": 8088}
    ]
    with pytest.raises(lifecycle.LifecycleError, match="still has an application listener"):
        app.start(workspace, frontend_mode="dev", research_config=input_config)
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == original
    assert list(workspace.glob("school-app-lifecycle.stopped-*.json")) == []
    ops.bound.pop(8088)

    with pytest.raises(lifecycle.LifecycleError, match="explicit current pinned configuration"):
        app.start(workspace, frontend_mode="dev")
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == original

    started = app.start(workspace, frontend_mode="dev", research_config=input_config)
    assert started["status"] == "RUNNING"
    current = json.loads(manifest_path.read_text(encoding="utf-8"))
    current_programme = current["research_config"][
        lifecycle.RESEARCH_PROGRAMME_WORKER_CONFIG_KEY
    ]
    assert current_programme["prompt_version"] == "1.2.0"
    archives = list(workspace.glob("school-app-lifecycle.stopped-*.json"))
    assert len(archives) == 1
    archived = json.loads(archives[0].read_text(encoding="utf-8"))
    assert (
        archived["research_config"][lifecycle.RESEARCH_PROGRAMME_WORKER_CONFIG_KEY][
            "prompt_version"
        ]
        == "1.1.1"
    )


def test_preview_build_is_real_api_and_uses_selected_backend_port(prepared):
    _repo, workspace, ops, app = prepared
    app.start(
        workspace,
        backend_port=8098,
        frontend_port=4188,
        frontend_mode="preview",
        llm_profile="school-gpu-7b",
    )
    assert len(ops.builds) == 1
    assert ops.builds[0][0:2] == (app.repo, 8098)
    backend_argv = ops.spawned[0][0]
    assert backend_argv[backend_argv.index("--llm-profile") + 1] == "school-gpu-7b"
    _node, vite, mode, *options = ops.spawned[1][0]
    assert Path(vite).name == "vite.js" and mode == "preview"
    assert "--strictPort" in options
    manifest = json.loads(
        (workspace / lifecycle.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    preview_dir = Path(manifest["frontend_preview_dir"])
    assert preview_dir == ops.builds[0][2]
    assert preview_dir.is_relative_to(workspace / lifecycle.PREVIEW_ARTIFACTS_DIR)
    assert options[options.index("--outDir") + 1] == str(preview_dir)


def test_preview_artifacts_are_isolated_per_workspace(prepared):
    repo, first_workspace, ops, first_app = prepared
    second_workspace = first_workspace.parent / "workspace-second"
    second_workspace.mkdir()
    (second_workspace / "workspace.json").write_text(
        json.dumps({"workspace_id": "ws-synthetic-2"}), encoding="utf-8"
    )
    (second_workspace / "runtime-ready.json").write_text("{}", encoding="utf-8")
    second_app = lifecycle.SchoolAppLifecycle(repo, ops)
    second_app._validate_prepared_database = lambda *args, **kwargs: {
        "workspace_id": "ws-synthetic-2",
        "database": "smhai_school_demo",
        "port": 3314,
    }

    first_app.start(workspace=first_workspace, frontend_mode="preview")
    second_app.start(
        workspace=second_workspace,
        backend_port=8089,
        frontend_port=4179,
        frontend_mode="preview",
    )

    first_manifest = json.loads(
        (first_workspace / lifecycle.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    second_manifest = json.loads(
        (second_workspace / lifecycle.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    first_output = Path(first_manifest["frontend_preview_dir"])
    second_output = Path(second_manifest["frontend_preview_dir"])
    assert first_output != second_output
    assert first_output.is_relative_to(
        first_workspace / lifecycle.PREVIEW_ARTIFACTS_DIR
    )
    assert second_output.is_relative_to(
        second_workspace / lifecycle.PREVIEW_ARTIFACTS_DIR
    )
    assert ops.builds[0][2] == first_output
    assert ops.builds[1][2] == second_output
    assert not (repo / "10_frontend" / "dist").exists()


def test_legacy_0011_preview_can_be_statused_stopped_but_not_adopted(prepared):
    _repo, workspace, ops, app = prepared
    app.start(workspace, frontend_mode="preview")
    _rewrite_preview_manifest_as_legacy_0011(app, workspace, ops)
    original_spawn_count = len(ops.spawned)
    original_build_count = len(ops.builds)

    with pytest.raises(lifecycle.LifecycleError, match="not a completed stop"):
        app.start(
            workspace,
            backend_port=8089,
            frontend_port=4179,
            frontend_mode="preview",
        )
    assert len(ops.spawned) == original_spawn_count
    assert len(ops.builds) == original_build_count

    status = app.status(workspace)
    assert status["manifest_revision"] == "20261014_0011"
    assert status["manifest_is_current_revision"] is False
    assert status["frontend_artifact_scope"] == "LEGACY_SHARED_DIST"
    assert status["current_ready_proof"] is False
    assert status["whole_ready"] is False
    assert app.stop(workspace)["status"] == "STOPPED"

    app.start(
        workspace,
        backend_port=8089,
        frontend_port=4179,
        frontend_mode="preview",
    )
    current_manifest = json.loads(
        (workspace / lifecycle.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    assert current_manifest["required_revision"] == lifecycle.CURRENT_SCHOOL_REVISION
    assert Path(current_manifest["frontend_preview_dir"]) != ops.builds[0][2]
    assert len(list(workspace.glob("school-app-lifecycle.stopped-*.json"))) == 1


def test_old_revision_target_owned_preview_can_be_statused_and_stopped_not_adopted(
    prepared,
):
    _repo, workspace, ops, app = prepared
    app.start(workspace, frontend_mode="preview")
    path = workspace / lifecycle.MANIFEST_NAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["required_revision"] = "20261014_0011"
    lifecycle._atomic_write(path, manifest)
    original_spawn_count = len(ops.spawned)
    original_build_count = len(ops.builds)

    with pytest.raises(lifecycle.LifecycleError, match="not a completed stop"):
        app.start(
            workspace,
            backend_port=8089,
            frontend_port=4179,
            frontend_mode="preview",
        )
    assert len(ops.spawned) == original_spawn_count
    assert len(ops.builds) == original_build_count

    status = app.status(workspace)
    assert status["manifest_revision"] == "20261014_0011"
    assert status["manifest_is_current_revision"] is False
    assert status["frontend_artifact_scope"] == "TARGET_OWNED"
    assert status["current_ready_proof"] is False
    assert status["whole_ready"] is False
    assert app.stop(workspace)["status"] == "STOPPED"
    assert ops.terminated == [502, 501]


def test_preview_manifest_output_path_outside_workspace_is_rejected(prepared):
    _repo, workspace, _ops, app = prepared
    app.start(workspace, frontend_mode="preview")
    path = workspace / lifecycle.MANIFEST_NAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["frontend_preview_dir"] = str(app.repo / "outside-preview")
    lifecycle._atomic_write(path, manifest)
    with pytest.raises(lifecycle.LifecycleError, match="outside its workspace"):
        app.status(workspace)


def test_manifest_revision_must_be_in_static_supported_catalog(prepared):
    _repo, workspace, _ops, app = prepared
    app.start(workspace, frontend_mode="dev")
    path = workspace / lifecycle.MANIFEST_NAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["required_revision"] = "20269999_9999"
    lifecycle._atomic_write(path, manifest)
    with pytest.raises(lifecycle.LifecycleError, match="stale or belongs"):
        app.status(workspace)


def test_preview_manifest_reparse_output_parent_is_rejected(prepared, monkeypatch):
    _repo, workspace, _ops, app = prepared
    app.start(workspace, frontend_mode="preview")
    root = workspace / lifecycle.PREVIEW_ARTIFACTS_DIR
    path_type = type(root)
    original_lstat = path_type.lstat

    def fake_lstat(path):
        if path == root:
            return SimpleNamespace(
                st_file_attributes=lifecycle.FILE_ATTRIBUTE_REPARSE_POINT,
                st_reparse_tag=lifecycle.IO_REPARSE_TAG_MOUNT_POINT,
            )
        return original_lstat(path)

    monkeypatch.setattr(path_type, "lstat", fake_lstat)
    with pytest.raises(lifecycle.LifecycleError, match="Reparse points"):
        app.status(workspace)


def test_frontend_build_passes_target_outdir_without_cleaning_other_output(
    tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    frontend = repo / "10_frontend"
    vue_tsc = frontend / "node_modules" / "vue-tsc" / "bin" / "vue-tsc.js"
    vite = frontend / "node_modules" / "vite" / "bin" / "vite.js"
    vue_tsc.parent.mkdir(parents=True)
    vite.parent.mkdir(parents=True)
    vue_tsc.touch()
    vite.touch()
    output = tmp_path / "workspace" / lifecycle.PREVIEW_ARTIFACTS_DIR / ("a" * 32)
    output.mkdir(parents=True)
    calls = []
    monkeypatch.setattr(lifecycle.shutil, "which", lambda name: "node.exe")

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[1] == str(vite):
            (output / "index.html").write_text("synthetic", encoding="utf-8")

    monkeypatch.setattr(lifecycle.subprocess, "run", fake_run)
    lifecycle.LifecycleOperations().build_frontend(repo, 8091, output)

    assert calls[0][0] == ["node.exe", str(vue_tsc), "--noEmit"]
    assert calls[1][0] == [
        "node.exe",
        str(vite),
        "build",
        "--outDir",
        str(output),
    ]
    assert "--emptyOutDir" not in calls[1][0]


def test_foreign_port_blocks_before_spawn(prepared):
    _repo, workspace, ops, app = prepared
    ops.free.remove(8088)
    ops.bound[8088] = [
        {"OwningProcess": 99, "LocalAddress": "127.0.0.1", "LocalPort": 8088}
    ]
    with pytest.raises(lifecycle.LifecycleError, match="occupied"):
        app.start(workspace, frontend_mode="dev")
    assert ops.spawned == []
    assert not (workspace / lifecycle.MANIFEST_NAME).exists()


def test_database_preflight_failure_precedes_build_and_spawn(prepared, monkeypatch):
    _repo, workspace, ops, app = prepared
    monkeypatch.setattr(
        app,
        "_validate_prepared_database",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            lifecycle.LifecycleError("offline synthetic preflight")
        ),
    )
    with pytest.raises(lifecycle.LifecycleError, match="offline synthetic"):
        app.start(workspace, frontend_mode="preview")
    assert ops.spawned == [] and ops.builds == []
    assert not (workspace / lifecycle.MANIFEST_NAME).exists()


def test_non_windows_start_stop_fail_closed(prepared, monkeypatch):
    _repo, workspace, ops, app = prepared
    monkeypatch.setattr(lifecycle, "IS_WINDOWS", False)
    with pytest.raises(lifecycle.LifecycleError, match="requires Windows"):
        app.start(workspace, frontend_mode="dev")
    with pytest.raises(lifecycle.LifecycleError, match="Windows process handles"):
        app.stop(workspace)
    assert ops.spawned == []


def test_partial_readiness_is_manifested_and_never_auto_killed(prepared):
    _repo, workspace, ops, app = prepared
    ops.ready[8088] = False
    result = app.start(workspace, frontend_mode="dev")
    manifest = json.loads(
        (workspace / lifecycle.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    assert result["status"] == "PARTIAL_READINESS_UNOBSERVED"
    assert len(manifest["services"]) == 1
    assert manifest["services"][0]["readiness"] == "NOT_OBSERVED"
    assert ops.terminated == [] and len(ops.spawned) == 1


def test_frontend_spawn_failure_preserves_backend_record(prepared):
    _repo, workspace, ops, app = prepared
    real_spawn = ops.spawn

    def fail_second(argv, **kwargs):
        if len(ops.spawned) == 1:
            raise lifecycle.LifecycleError("synthetic failure")
        return real_spawn(argv, **kwargs)

    ops.spawn = fail_second
    with pytest.raises(lifecycle.LifecycleError, match="start incomplete"):
        app.start(workspace, frontend_mode="dev")
    manifest = json.loads(
        (workspace / lifecycle.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    assert manifest["state"] == "PARTIAL_FAILURE"
    assert len(manifest["services"]) == 1
    assert ops.terminated == []


def test_stale_manifest_fails_closed(prepared):
    _repo, workspace, ops, app = prepared
    (workspace / lifecycle.MANIFEST_NAME).write_text(
        json.dumps({"schema_version": "old"}), encoding="utf-8"
    )
    with pytest.raises(lifecycle.LifecycleError, match="unknown"):
        app.status(workspace)
    with pytest.raises(lifecycle.LifecycleError, match="unknown"):
        app.stop(workspace)
    assert ops.terminated == []


def test_reused_pid_or_changed_command_blocks_stop(prepared):
    _repo, workspace, ops, app = prepared
    app.start(workspace, frontend_mode="dev")
    frontend = ops.processes[502]
    ops.processes[502] = {**frontend, "CommandLine": "other.exe --port 4178"}
    with pytest.raises(lifecycle.LifecycleError, match="identity changed"):
        app.stop(workspace)
    assert ops.terminated == []


def test_foreign_listener_after_start_blocks_stop(prepared):
    _repo, workspace, ops, app = prepared
    app.start(workspace, frontend_mode="dev")
    ops.bound[4178] = [
        {"OwningProcess": 99, "LocalAddress": "127.0.0.1", "LocalPort": 4178}
    ]
    with pytest.raises(lifecycle.LifecycleError, match="Foreign"):
        app.stop(workspace)
    assert ops.terminated == []


def test_backend_launcher_and_listener_child_are_both_verified_and_stopped(prepared):
    _repo, workspace, ops, app = prepared
    ops.backend_listener_child = True
    app.start(workspace, frontend_mode="dev")
    manifest = json.loads(
        (workspace / lifecycle.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    backend = next(
        service for service in manifest["services"] if service["name"] == "backend"
    )
    assert [process["role"] for process in backend["processes"]] == [
        "launcher",
        "listener",
    ]
    assert backend["listener"]["pid"] == 900
    assert backend["listener"]["executable"] == str(
        (app.repo / "backend-base-python" / "python.exe").resolve()
    )
    assert backend["listener"]["argv"] == [
        backend["base_executable"],
        *backend["argv"][1:],
    ]
    assert backend["processes"][1]["argv"] == backend["listener"]["argv"]
    assert backend["listener_candidate"]["identity_verified"] is True
    assert backend["processes"][1]["parent_pid"] == backend["pid"]
    assert backend["processes"][1]["parent"] == lifecycle._identity_from_process(
        backend["processes"][0]
    )
    status = app.status(workspace)
    assert status["services"]["backend"]["listener"] == "OWNED"
    app.stop(workspace)
    assert ops.terminated == [502, 900, 501]
    assert ops.bound == {}


def test_stop_records_launcher_autoexit_after_listener_child_stops(prepared):
    _repo, workspace, ops, app = prepared
    ops.backend_listener_child = True
    ops.autoexit_parent_after_child = True
    app.start(workspace, frontend_mode="dev")

    result = app.stop(workspace)
    manifest = json.loads(
        (workspace / lifecycle.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    backend = next(
        service for service in manifest["services"] if service["name"] == "backend"
    )
    assert result["status"] == "STOPPED"
    assert [process["state"] for process in backend["processes"]] == [
        "EXITED",
        "STOPPED",
    ]
    assert ops.terminated == [502, 900]
    assert ops.bound == {}


def test_stop_records_exit_between_preflight_and_terminate_handle(prepared):
    _repo, workspace, ops, app = prepared
    app.start(workspace, frontend_mode="dev")
    ops.exit_before_terminate_pid = 502

    result = app.stop(workspace)
    manifest = json.loads(
        (workspace / lifecycle.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    frontend = next(
        service for service in manifest["services"] if service["name"] == "frontend"
    )
    assert result["status"] == "STOPPED"
    assert frontend["processes"][0]["state"] == "EXITED"
    assert ops.terminated == [501]
    assert ops.bound == {}


def test_backend_listener_with_wrong_base_python_is_rejected_without_kill(prepared):
    _repo, workspace, ops, app = prepared
    ops.backend_listener_child = True
    wrong_python = app.repo / "other-python-home" / "python.exe"
    wrong_python.parent.mkdir(parents=True)
    wrong_python.touch()
    ops.backend_child_executable_override = str(wrong_python.resolve())
    result = app.start(workspace, frontend_mode="dev")
    manifest = json.loads(
        (workspace / lifecycle.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    backend = manifest["services"][0]
    assert result["status"] == "PARTIAL_READINESS_UNOBSERVED"
    assert backend["listener"] is None
    assert backend["listener_candidate"]["pid"] == 900
    assert backend["listener_candidate"]["identity_verified"] is False
    with pytest.raises(lifecycle.LifecycleError, match="Foreign or changed listener"):
        app.stop(workspace)
    assert ops.terminated == []


def test_backend_listener_with_wrong_command_tail_is_rejected_without_kill(prepared):
    _repo, workspace, ops, app = prepared
    ops.backend_listener_child = True
    ops.backend_child_tail_override = True
    result = app.start(workspace, frontend_mode="dev")
    manifest = json.loads(
        (workspace / lifecycle.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    backend = manifest["services"][0]
    assert result["status"] == "PARTIAL_READINESS_UNOBSERVED"
    assert backend["listener"] is None
    assert len(backend["processes"]) == 1
    assert backend["listener_candidate"]["identity_verified"] is False
    candidate_argv = backend["listener_candidate"]["argv"]
    assert candidate_argv[candidate_argv.index("--port") + 1] == "9999"
    with pytest.raises(lifecycle.LifecycleError, match="Foreign or changed listener"):
        app.stop(workspace)
    assert ops.terminated == []


def test_stopped_manifest_is_archived_before_repeat_start(prepared):
    _repo, workspace, _ops, app = prepared
    app.start(workspace, frontend_mode="dev")
    app.stop(workspace)
    first_manifest = json.loads(
        (workspace / lifecycle.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    app.start(workspace, frontend_mode="dev")
    archives = list(workspace.glob("school-app-lifecycle.stopped-*.json"))
    assert len(archives) == 1
    assert json.loads(archives[0].read_text(encoding="utf-8"))["state"] == "STOPPED"
    second_manifest = json.loads(
        (workspace / lifecycle.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    assert second_manifest["created_at"] != first_manifest["created_at"]
    app.stop(workspace)


def test_stop_preflights_all_owners_and_records_partial_actual_stop(prepared):
    _repo, workspace, ops, app = prepared
    app.start(workspace, frontend_mode="dev")
    ops.fail_terminate_pid = 501
    with pytest.raises(lifecycle.LifecycleError, match="exit was not confirmed"):
        app.stop(workspace)
    manifest = json.loads(
        (workspace / lifecycle.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    assert manifest["state"] == "STOP_PARTIAL"
    assert (
        next(
            service for service in manifest["services"] if service["name"] == "frontend"
        )["state"]
        == "STOPPED"
    )
    assert (
        next(
            service for service in manifest["services"] if service["name"] == "backend"
        )["state"]
        == "STOP_PARTIAL"
    )
    assert ops.terminated == [502]


def test_environment_filter_removes_sensitive_and_execution_override_keys():
    filtered = lifecycle._sanitize_environment(
        {
            "Path": "safe",
            "db_password": "secret",
            "SMHAI_TEST": "secret",
            "database_url": "secret",
            "Mysql_Pwd": "secret",
            "DATABASE_KEY_FILE": "secret",
            "VITE_API_MODE": "mock",
            "VITE_API_BASE_URL": "https://invalid.example",
            "NODE_OPTIONS": "--require injected.js",
            "NODE_PATH": "C:\\untrusted\\modules",
            "PYTHONPATH": "C:\\untrusted\\python",
            "PYTHONHOME": "C:\\untrusted\\runtime",
            "SystemRoot": "C:\\Windows",
            "TEMP": "D:\\Temp",
            "UV_CACHE_DIR": "D:\\Cache\\uv",
            "HTTPS_PROXY": "http://proxy.invalid",
        }
    )
    assert filtered == {
        "Path": "safe",
        "SystemRoot": "C:\\Windows",
        "TEMP": "D:\\Temp",
        "UV_CACHE_DIR": "D:\\Cache\\uv",
        "HTTPS_PROXY": "http://proxy.invalid",
    }
    frontend_env = lifecycle._frontend_environment(8091)
    assert frontend_env["VITE_API_MODE"] == "real"
    assert frontend_env["VITE_API_BASE_URL"] == "http://127.0.0.1:8091"
    assert not any(
        key.upper().startswith("VITE_")
        for key in lifecycle._sanitize_environment({"VITE_API_MODE": "mock"})
    )


def test_http_readiness_uses_direct_loopback_without_proxy(monkeypatch):
    captured = {}

    class Response:
        status = 200
        body = json.dumps(
            {
                "data": {
                    "status": "ready",
                    "core": {
                        "configuration": "READY",
                        "session_store": "READY",
                    },
                }
            }
        ).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return self.body

    class Opener:
        def open(self, url, *, timeout):
            captured["url"] = url
            captured["timeout"] = timeout
            return Response()

    monkeypatch.setattr(
        lifecycle.urllib.request,
        "ProxyHandler",
        lambda proxy: captured.setdefault("proxy", proxy) or object(),
    )
    monkeypatch.setattr(
        lifecycle.urllib.request, "build_opener", lambda *_handlers: Opener()
    )
    assert lifecycle.LifecycleOperations().http_ready(8088, "/health/ready") is True
    assert captured["url"] == "http://127.0.0.1:8088/health/ready"
    assert captured["proxy"] == {}
    assert captured["timeout"] == 1.0


def test_http_readiness_rejects_backend_core_still_starting(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps(
                {
                    "data": {
                        "status": "starting",
                        "core": {
                            "configuration": "READY",
                            "session_store": "READY",
                        },
                    }
                }
            ).encode()

    class Opener:
        def open(self, _url, *, timeout):
            return Response()

    monkeypatch.setattr(
        lifecycle.urllib.request, "build_opener", lambda *_handlers: Opener()
    )
    assert lifecycle.LifecycleOperations().http_ready(8088, "/health/ready") is False


def test_invalid_ports_and_unknown_frontend_mode_rejected(prepared):
    _repo, workspace, _ops, app = prepared
    with pytest.raises(lifecycle.LifecycleError, match="Distinct application ports"):
        app.plan(workspace, backend_port=4178, frontend_port=4178, frontend_mode="dev")
    with pytest.raises(lifecycle.LifecycleError, match="supported LLM profile"):
        app.plan(workspace, llm_profile="auto", frontend_mode="dev")


def test_backend_base_executable_is_taken_from_exact_venv_configuration(prepared):
    repo, _workspace, _ops, _app = prepared
    launcher, base_python = lifecycle._backend_python_paths(repo)
    assert (
        launcher == (repo / "09_backend" / ".venv" / "Scripts" / "python.exe").resolve()
    )
    assert base_python == (repo / "backend-base-python" / "python.exe").resolve()
    config = repo / "09_backend" / ".venv" / "pyvenv.cfg"
    config.write_text(
        f"home = {repo / 'backend-base-python'}\nhome = {repo / 'other-python-home'}\n",
        encoding="utf-8",
    )
    with pytest.raises(
        lifecycle.LifecycleError, match="base Python cannot be verified"
    ):
        lifecycle._backend_python_paths(repo)


def test_backend_python_home_accepts_only_explicit_leaf_junction(prepared, monkeypatch):
    repo, _workspace, _ops, _app = prepared
    alias_home = repo / "backend-python-home-link"
    alias_home.mkdir()
    canonical_home = repo / "backend-base-python"
    config = repo / "09_backend" / ".venv" / "pyvenv.cfg"
    config.write_text(f"home = {alias_home}\nversion_info = 3.12\n", encoding="utf-8")

    path_type = type(alias_home)
    original_lstat = path_type.lstat
    original_resolve = path_type.resolve

    def fake_lstat(path):
        if path == alias_home:
            return SimpleNamespace(
                st_file_attributes=lifecycle.FILE_ATTRIBUTE_REPARSE_POINT,
                st_reparse_tag=lifecycle.IO_REPARSE_TAG_MOUNT_POINT,
            )
        return original_lstat(path)

    def fake_resolve(path, *args, **kwargs):
        if path == alias_home:
            return original_resolve(canonical_home, *args, **kwargs)
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(path_type, "lstat", fake_lstat)
    monkeypatch.setattr(path_type, "resolve", fake_resolve)
    _launcher, base_python = lifecycle._backend_python_paths(repo)
    assert base_python == (canonical_home / "python.exe").resolve()


@pytest.mark.parametrize("redirect", ["unknown_reparse_tag", "network_target"])
def test_backend_python_home_rejects_unknown_or_network_redirect(
    prepared, monkeypatch, redirect
):
    repo, _workspace, _ops, _app = prepared
    alias_home = repo / "backend-python-home-redirect"
    alias_home.mkdir()
    config = repo / "09_backend" / ".venv" / "pyvenv.cfg"
    config.write_text(f"home = {alias_home}\n", encoding="utf-8")

    path_type = type(alias_home)
    original_lstat = path_type.lstat
    original_resolve = path_type.resolve
    tag = (
        lifecycle.IO_REPARSE_TAG_MOUNT_POINT + 1
        if redirect == "unknown_reparse_tag"
        else lifecycle.IO_REPARSE_TAG_MOUNT_POINT
    )

    def fake_lstat(path):
        if path == alias_home:
            return SimpleNamespace(
                st_file_attributes=lifecycle.FILE_ATTRIBUTE_REPARSE_POINT,
                st_reparse_tag=tag,
            )
        return original_lstat(path)

    def fake_resolve(path, *args, **kwargs):
        if path == alias_home and redirect == "network_target":
            return type(path)(r"\\server\share\python-home")
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(path_type, "lstat", fake_lstat)
    monkeypatch.setattr(path_type, "resolve", fake_resolve)
    with pytest.raises(
        lifecycle.LifecycleError, match="local drive|cannot be verified"
    ):
        lifecycle._backend_python_paths(repo)


def test_cli_failure_projection_reports_guard_location_without_changing_exit_code(
    tmp_path, monkeypatch, capsys
):
    def fail_start(_self, *_args, **_kwargs):
        lifecycle._validate_ports(8095, 8095)

    monkeypatch.setattr(lifecycle.SchoolAppLifecycle, "start", fail_start)

    result = lifecycle.main(
        [
            "start",
            "--workspace",
            str(tmp_path),
            "--backend-port",
            "8095",
            "--frontend-port",
            "8095",
            "--frontend-mode",
            "dev",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    location = payload["failure_location"]
    assert result == 2
    assert payload["status"] == "BLOCKED"
    assert payload["error_type"] == "LifecycleError"
    assert payload["diagnostic_stage"] == "cli_exception_boundary"
    assert location["file"] == Path(lifecycle.__file__).name
    assert lifecycle._validate_ports.__code__.co_firstlineno <= location["line"]
    assert location["line"] < lifecycle._validate_research_port.__code__.co_firstlineno
    assert "Distinct application ports" not in captured.out
    assert str(tmp_path) not in captured.out
    assert captured.err == ""


def test_cli_failure_projection_never_emits_secret_exception_data(
    tmp_path, monkeypatch, capsys
):
    secret = "synthetic-secret-error-text"

    def fail_start(_self, *_args, **_kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(lifecycle.SchoolAppLifecycle, "start", fail_start)
    result = lifecycle.main(
        [
            "start",
            "--workspace",
            str(tmp_path),
            "--frontend-mode",
            "dev",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 2
    assert payload["status"] == "BLOCKED"
    assert payload["error_type"] == "RuntimeError"
    assert payload["diagnostic_stage"] == "cli_exception_boundary"
    assert payload["failure_location"]["file"] == Path(lifecycle.__file__).name
    assert secret not in captured.out
    assert str(tmp_path) not in captured.out
    assert captured.err == ""


def test_safe_failure_location_omits_nonproject_traceback_paths():
    try:
        raise RuntimeError("synthetic external exception")
    except RuntimeError as exc:
        assert lifecycle._safe_project_failure_location(exc) is None


def test_cli_failure_projection_survives_unresolvable_source_path(
    tmp_path, monkeypatch, capsys
):
    path_type = type(Path(lifecycle.__file__))
    original_resolve = path_type.resolve
    source_path = Path(lifecycle.__file__)

    def fail_source_resolve(path, *args, **kwargs):
        if path == source_path:
            raise OSError("synthetic secret source path")
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(path_type, "resolve", fail_source_resolve)
    result = lifecycle.main(
        [
            "start",
            "--workspace",
            str(tmp_path),
            "--frontend-mode",
            "dev",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 2
    assert payload["status"] == "BLOCKED"
    assert payload["error_type"] == "OSError"
    assert payload["failure_location"] is None
    assert "synthetic secret source path" not in captured.out
    assert str(source_path) not in captured.out
    assert captured.err == ""
