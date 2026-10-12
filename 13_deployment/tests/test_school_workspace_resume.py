from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location(
    "resume_school_workspace", ROOT / "resume_school_workspace.py"
)
resume = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(resume)


CREATION_UTC = "2026-10-12T00:18:07.433575Z"


class FakeProcess:
    def __init__(self, pid: int):
        self.pid = pid
        self.terminated = False

    def poll(self):
        return None


class FakeOperations:
    def __init__(self):
        self.process = None
        self.listener_rows = []
        self.free = True
        self.ready = True
        self.started = None
        self.acl_calls = 0
        self.verify_calls = 0
        self.runtime_calls = 0
        self.last_marker = None

    def is_supported_platform(self):
        return True

    def verify_acl(self, _workspace):
        self.acl_calls += 1

    def inspect_process(self, pid):
        return self.process if self.process and self.process["ProcessId"] == pid else None

    def process_creation_time(self, process):
        assert process.pid == 2222
        return "2026-10-12T01:00:00.000000Z"

    def listeners(self, port):
        return [dict(row, LocalPort=port) for row in self.listener_rows]

    def port_is_free(self, _port):
        return self.free

    def start_guardian(self, executable, workspace, data_directory, port):
        self.started = (executable, workspace, data_directory, port)
        process = FakeProcess(2222)
        argv = resume.guardian_arguments(executable, workspace, data_directory, port)
        self.process = {
            "ProcessId": process.pid,
            "ExecutablePath": str(executable),
            "CommandLine": " ".join(argv),
            "CreationUtc": "2026-10-12T01:00:00.000000Z",
        }
        return process

    def wait_ready(self, _process, _port, _timeout):
        if self.ready:
            self.listener_rows = [{"OwningProcess": 2222, "LocalAddress": "127.0.0.1"}]
        return self.ready

    def verify_running_process(self, marker):
        self.verify_calls += 1
        self.last_marker = dict(marker)

    def load_runtime(self, _workspace, _repo):
        self.runtime_calls += 1
        return {"database": "smhai_school_demo", "port": 3308}


@pytest.fixture
def owned_workspace(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    workspace = tmp_path / "external-school-workspace"
    workspace.mkdir()
    data = workspace / "mysql-data"
    data.mkdir()
    (data / "mysql").mkdir()
    (data / "auto.cnf").write_text("synthetic", encoding="utf-8")
    (data / "ibdata1").write_bytes(b"existing synthetic data")
    executable = workspace / "vendor" / "mysqld.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"synthetic executable fixture")
    marker = {
        "schema_version": "psynova.synthetic-workspace.v1",
        "project": "StudentMentalHealthAI",
        "workspace_id": "synthetic-workspace-fixture",
        "state": "READY_FOR_MIGRATION",
        "host": "127.0.0.1",
        "port": 3308,
        "database": "smhai_school_demo",
        "synthetic_only": True,
        "data_directory": str(data),
        "executable": str(executable),
        "parent_pid": 11180,
        "parent_creation_time": CREATION_UTC,
        "preserved_operator_field": "retain-me",
    }
    (workspace / "workspace.json").write_text(json.dumps(marker), encoding="utf-8")
    (workspace / "database.private.dpapi").write_bytes(b"sealed-placeholder")
    return workspace, repo, marker


def run_resume(workspace, repo, ops, **kwargs):
    return resume.resume_workspace(
        workspace,
        repo,
        ops=ops,
        lock_factory=lambda _path: nullcontext(),
        expected_workspace=workspace,
        **kwargs,
    )


def test_exact_running_guardian_is_verified_and_not_started_again(owned_workspace):
    workspace, repo, marker = owned_workspace
    ops = FakeOperations()
    ops.process = {
        "ProcessId": marker["parent_pid"],
        "ExecutablePath": marker["executable"],
        "CommandLine": " ".join(
            resume.guardian_arguments(
                Path(marker["executable"]), workspace, Path(marker["data_directory"]), 3308
            )
        ),
        "CreationUtc": CREATION_UTC,
    }
    ops.listener_rows = [{"OwningProcess": marker["parent_pid"], "LocalAddress": "127.0.0.1"}]

    result = run_resume(workspace, repo, ops)

    assert result == {"status": "ALREADY_RUNNING", "database": "smhai_school_demo", "port": 3308}
    assert ops.started is None
    assert ops.acl_calls == 2
    assert ops.verify_calls == 1
    assert ops.runtime_calls == 1


def test_foreign_listener_fails_closed_without_start_or_runtime_read(owned_workspace):
    workspace, repo, _marker = owned_workspace
    ops = FakeOperations()
    ops.listener_rows = [{"OwningProcess": 999, "LocalAddress": "127.0.0.1"}]
    ops.free = False

    with pytest.raises(resume.ResumeError, match="Port is occupied"):
        run_resume(workspace, repo, ops)

    assert ops.started is None
    assert ops.runtime_calls == 0


def test_non_private_acl_fails_before_lock_listener_or_process_operations(owned_workspace):
    workspace, repo, _marker = owned_workspace

    class UnsafeAclOperations(FakeOperations):
        def verify_acl(self, _workspace):
            self.acl_calls += 1
            raise resume.ResumeError("ACL not private")

    ops = UnsafeAclOperations()

    with pytest.raises(resume.ResumeError, match="ACL not private"):
        run_resume(workspace, repo, ops)

    assert ops.acl_calls == 1
    assert ops.started is None
    assert ops.runtime_calls == 0


def test_reused_pid_with_different_creation_time_is_rejected(owned_workspace):
    workspace, repo, marker = owned_workspace
    ops = FakeOperations()
    ops.process = {
        "ProcessId": marker["parent_pid"],
        "ExecutablePath": marker["executable"],
        "CommandLine": " ".join(
            resume.guardian_arguments(
                Path(marker["executable"]), workspace, Path(marker["data_directory"]), 3308
            )
        ),
        "CreationUtc": "2026-10-12T02:00:00.000000Z",
    }

    with pytest.raises(resume.ResumeError, match="identity does not match"):
        run_resume(workspace, repo, ops)

    assert ops.started is None
    assert ops.runtime_calls == 0


def test_missing_marker_is_rejected_before_acl_or_process_operations(owned_workspace):
    workspace, repo, _marker = owned_workspace
    (workspace / "workspace.json").unlink()
    ops = FakeOperations()

    with pytest.raises(resume.ResumeError, match="incomplete"):
        run_resume(workspace, repo, ops)

    assert ops.acl_calls == 0
    assert ops.started is None


def test_mismatched_data_path_is_rejected_without_process_or_acl_side_effects(owned_workspace):
    workspace, repo, marker = owned_workspace
    marker["data_directory"] = str(repo)
    (workspace / "workspace.json").write_text(json.dumps(marker), encoding="utf-8")
    ops = FakeOperations()

    with pytest.raises(resume.ResumeError):
        run_resume(workspace, repo, ops)

    assert ops.acl_calls == 0
    assert ops.started is None


def test_reparse_path_is_rejected_before_marker_or_process_access(owned_workspace, monkeypatch):
    workspace, repo, _marker = owned_workspace
    checked = []

    def reject_workspace(path):
        checked.append(path)
        if path == workspace:
            raise resume.ResumeError("synthetic reparse point")

    monkeypatch.setattr(resume, "_reject_reparse_path", reject_workspace)
    ops = FakeOperations()

    with pytest.raises(resume.ResumeError, match="reparse point"):
        run_resume(workspace, repo, ops)

    assert checked == [workspace]
    assert ops.acl_calls == 0
    assert ops.started is None


def test_start_uses_non_initializing_loopback_args_and_scrubbed_environment(owned_workspace):
    workspace, _repo, _marker = owned_workspace
    executable = workspace / "vendor" / "mysqld.exe"
    data = workspace / "mysql-data"
    argv = resume.guardian_arguments(executable, workspace, data, 3308)
    environment = resume.guardian_environment(
        {
            "PATH": "synthetic-path",
            "DB_PASSWORD": "secret-fixture",
            "SMHAI_SCHOOL_CSRF_SECRET": "secret-fixture",
            "DATABASE_URL": "secret-fixture",
            "DATABASE_KEY_FILE": "secret-fixture",
            "MYSQL_PWD": "secret-fixture",
        }
    )

    assert "--no-defaults" in argv
    assert "--initialize" not in argv
    assert "--bind-address=127.0.0.1" in argv
    assert "--mysqlx=0" in argv
    assert f"--log-error={workspace / 'mysql.private.log'}" in argv
    assert f"--pid-file={workspace / 'mysql.pid'}" in argv
    assert environment == {"PATH": "synthetic-path"}
    assert "secret-fixture" not in repr(argv)
    assert "secret-fixture" not in repr(environment)


def test_start_guardian_uses_hidden_window_and_never_invokes_real_process(
    owned_workspace, monkeypatch
):
    workspace, _repo, marker = owned_workspace
    captured = {}
    sentinel = FakeProcess(3333)
    monkeypatch.setenv("DB_PASSWORD", "synthetic-secret-fixture")
    monkeypatch.setenv("MYSQL_PWD", "synthetic-secret-fixture")

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(resume.subprocess, "Popen", fake_popen)
    process = resume.ResumeOperations.start_guardian(
        Path(marker["executable"]),
        workspace,
        Path(marker["data_directory"]),
        3308,
    )

    assert process is sentinel
    assert captured["shell"] is False
    assert captured["stdin"] is resume.subprocess.DEVNULL
    assert captured["stdout"] is resume.subprocess.DEVNULL
    assert captured["stderr"] is resume.subprocess.DEVNULL
    assert captured["startupinfo"].dwFlags & resume.subprocess.STARTF_USESHOWWINDOW
    assert captured["startupinfo"].wShowWindow == 0
    assert "--initialize" not in captured["argv"]
    assert "synthetic-secret-fixture" not in repr(captured)


def test_readiness_timeout_preserves_new_guardian_marker_and_all_data(owned_workspace):
    workspace, repo, original = owned_workspace
    ops = FakeOperations()
    ops.ready = False
    data_before = (workspace / "mysql-data" / "ibdata1").read_bytes()
    sealed_before = (workspace / "database.private.dpapi").read_bytes()

    with pytest.raises(resume.ResumeError, match="remains running"):
        run_resume(workspace, repo, ops, timeout=1)

    saved = json.loads((workspace / "workspace.json").read_text(encoding="utf-8"))
    assert saved["state"] == original["state"]
    assert saved["preserved_operator_field"] == "retain-me"
    assert saved["parent_pid"] == 2222
    assert saved["parent_creation_time"] == "2026-10-12T01:00:00.000000Z"
    assert saved["resume_state"] == "READINESS_OBSERVATION_FAILED"
    assert ops.started is not None
    assert ops.runtime_calls == 0
    assert (workspace / "mysql-data" / "ibdata1").read_bytes() == data_before
    assert (workspace / "database.private.dpapi").read_bytes() == sealed_before


def test_successful_resume_atomically_records_guardian_then_verifies_runtime(owned_workspace):
    workspace, repo, original = owned_workspace
    ops = FakeOperations()

    result = run_resume(workspace, repo, ops, timeout=5)

    saved = json.loads((workspace / "workspace.json").read_text(encoding="utf-8"))
    assert result == {"status": "STARTED", "database": "smhai_school_demo", "port": 3308}
    assert saved["state"] == original["state"]
    assert saved["preserved_operator_field"] == "retain-me"
    assert saved["parent_pid"] == 2222
    assert saved["parent_creation_time"] == "2026-10-12T01:00:00.000000Z"
    assert saved["resume_state"] == "READY"
    assert ops.verify_calls == 1
    assert ops.runtime_calls == 1
    assert (workspace / "mysql-data" / "ibdata1").read_bytes() == b"existing synthetic data"


def test_marker_update_is_atomic_and_preserves_unknown_fields(owned_workspace):
    workspace, _repo, marker = owned_workspace
    updated = dict(marker, resume_state="STARTING", resume_updated_at=CREATION_UTC)

    resume.atomic_write_marker(workspace, updated)

    saved = json.loads((workspace / "workspace.json").read_text(encoding="utf-8"))
    assert saved["preserved_operator_field"] == "retain-me"
    assert saved["parent_pid"] == marker["parent_pid"]
    assert saved["resume_state"] == "STARTING"
    assert not list(workspace.glob(".workspace.*.tmp"))


def test_marker_replace_failure_leaves_original_marker_intact(owned_workspace, monkeypatch):
    workspace, _repo, marker = owned_workspace
    before = (workspace / "workspace.json").read_bytes()
    monkeypatch.setattr(resume.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("fake")))

    with pytest.raises(resume.ResumeError, match="marker update failed"):
        resume.atomic_write_marker(workspace, dict(marker, resume_state="STARTING"))

    assert (workspace / "workspace.json").read_bytes() == before
    assert not list(workspace.glob(".workspace.*.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="workspace locking is Windows-only")
def test_existing_reparse_lock_is_rejected_before_open(tmp_path, monkeypatch):
    lock_path = tmp_path / ".resume.lock"
    lock_path.write_bytes(b"\0")
    calls = []

    def reject_lock(path):
        calls.append(path)
        if path == lock_path:
            raise resume.ResumeError("synthetic reparse lock")

    monkeypatch.setattr(resume, "_reject_reparse_path", reject_lock)
    with pytest.raises(resume.ResumeError, match="reparse lock"), resume.workspace_lock(tmp_path):
        pytest.fail("reparse lock must not be opened")
    assert calls == [lock_path]


def test_naive_process_creation_timestamp_does_not_match_marker():
    marker = {"parent_creation_time": CREATION_UTC}
    process = {"CreationUtc": "2026-10-12T00:18:07.433575"}
    assert resume._utc_timestamp(process["CreationUtc"]) == ""
    assert resume._marker_creation_time(marker) == "2026-10-12T00:18:07.433575Z"


@pytest.mark.parametrize("mutation", ["missing_time", "port_suffix", "extra_option"])
def test_identity_rejects_incomplete_time_or_nonexact_arguments(owned_workspace, mutation):
    workspace, _repo, marker = owned_workspace
    argv = resume.guardian_arguments(
        Path(marker["executable"]), workspace, Path(marker["data_directory"]), 3308
    )
    if mutation == "port_suffix":
        argv[3] = "--port=33080"
    if mutation == "extra_option":
        argv.append("--skip-grant-tables")
    process = {
        "ProcessId": marker["parent_pid"], "ExecutablePath": marker["executable"],
        "CreationUtc": CREATION_UTC, "CommandLine": subprocess.list2cmdline(argv),
    }
    if mutation == "missing_time":
        marker.pop("parent_creation_time")
        process["CreationUtc"] = ""
    assert not resume._process_matches(process, marker)


def test_windows_quoted_paths_and_forward_slashes_match_exact_arguments(owned_workspace):
    workspace, _repo, marker = owned_workspace
    argv = resume.guardian_arguments(
        Path(marker["executable"]), workspace, Path(marker["data_directory"]), 3308
    )
    process = {
        "ProcessId": marker["parent_pid"], "ExecutablePath": marker["executable"],
        "CreationUtc": CREATION_UTC,
        "CommandLine": subprocess.list2cmdline([item.replace("\\", "/") for item in argv]),
    }
    assert resume._process_matches(process, marker)
    assert resume._command_arguments('"C:\\path with spaces\\mysqld.exe" --port=3308') == [
        "C:\\path with spaces\\mysqld.exe", "--port=3308"
    ]


def test_credential_environment_filter_is_case_insensitive():
    assert resume.guardian_environment({"db_password": "fixture", "mysql_pwd": "fixture", "Path": "keep"}) == {"Path": "keep"}


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), 0, 61])
def test_invalid_readiness_bounds_fail_before_operations(owned_workspace, timeout):
    workspace, repo, _marker = owned_workspace
    ops = FakeOperations()
    with pytest.raises(resume.ResumeError, match="bounded"):
        run_resume(workspace, repo, ops, timeout=timeout)
    assert ops.acl_calls == 0
