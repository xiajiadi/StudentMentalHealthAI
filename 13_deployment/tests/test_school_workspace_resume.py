from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from contextlib import contextmanager, nullcontext
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
        self.listener_ports = []
        self.readiness_ports = []

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
        self.listener_ports.append(port)
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

    def wait_ready(self, _process, port, _timeout):
        self.readiness_ports.append(port)
        if self.ready:
            self.listener_rows = [{"OwningProcess": 2222, "LocalAddress": "127.0.0.1"}]
        return self.ready

    def verify_running_process(self, marker):
        self.verify_calls += 1
        self.last_marker = dict(marker)

    def load_runtime(self, workspace, _repo):
        self.runtime_calls += 1
        marker = json.loads((workspace / "workspace.json").read_text(encoding="utf-8"))
        return {
            "database": marker["database"],
            "port": marker["port"],
            "identity_profile": "school_tenant",
        }


class FreshFakeOperations(FakeOperations):
    def __init__(self):
        super().__init__()
        self.dpapi_calls = 0
        self.fresh_database_calls = 0

    def verify_fresh_dpapi(self, _workspace, _port):
        self.dpapi_calls += 1

    def verify_fresh_database(self, _workspace, _port, _repo):
        self.fresh_database_calls += 1


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


@pytest.fixture
def restored_workspace_pair(tmp_path, monkeypatch, owned_workspace):
    source, repo, source_marker = owned_workspace
    monkeypatch.setattr(resume, "DEFAULT_WORKSPACE", source)
    target = source.parent / ".StudentMentalHealthAI-school-restore-20261012-b"
    data = target / "mysql-data"
    (data / "mysql").mkdir(parents=True)
    (data / "auto.cnf").write_text("synthetic-target", encoding="utf-8")
    (data / "ibdata1").write_bytes(b"restored synthetic target")
    executable = target / "vendor" / "mysqld.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"synthetic target executable fixture")
    target_marker = {
        **source_marker,
        "workspace_id": "synthetic-restored-target",
        "port": 3310,
        "data_directory": str(data),
        "executable": str(executable),
        "parent_pid": 22280,
    }
    (target / "workspace.json").write_text(json.dumps(target_marker), encoding="utf-8")
    restore_state = {
        "schema_version": "psynova.synthetic-restore-target.v1",
        "synthetic_only": True,
        "phase": "DATA_KEYS_RUNTIME_VERIFIED_REQUIRES_BROWSER",
        "database": "smhai_school_demo",
        "host": "127.0.0.1",
        "port": 3310,
        "workspace_id": target_marker["workspace_id"],
        "source_workspace_id": source_marker["workspace_id"],
        "workspace": str(target),
        "data_directory": str(data),
        "snapshot_revision": "20261011_0005",
        "runtime_revision": resume.CURRENT_SCHOOL_REVISION,
    }
    (target / "restore-state.json").write_text(json.dumps(restore_state), encoding="utf-8")
    return source, target, repo, source_marker, target_marker, restore_state


def run_restore_resume(pair, ops, *, expected_port=3310, **kwargs):
    _source, target, repo, *_rest = pair
    return resume.resume_restored_workspace(
        target,
        repo,
        expected_port=expected_port,
        ops=ops,
        lock_factory=lambda _path: nullcontext(),
        **kwargs,
    )


@pytest.fixture
def fresh_workspace(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    workspace = tmp_path / ".StudentMentalHealthAI-school-install-20261013-g"
    data = workspace / "mysql-data"
    (data / "mysql").mkdir(parents=True)
    (data / "auto.cnf").write_text("synthetic", encoding="utf-8")
    (data / "ibdata1").write_bytes(b"existing synthetic fresh data")
    executable = workspace / "vendor" / "mysqld.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"synthetic executable fixture")
    marker = {
        "schema_version": "psynova.synthetic-workspace.v1",
        "project": "StudentMentalHealthAI",
        "workspace_id": "137ffe3243201bf34130b6585764edcf",
        "state": "READY_FOR_MIGRATION",
        "host": "127.0.0.1",
        "port": 3315,
        "database": "smhai_school_demo",
        "synthetic_only": True,
        "data_directory": str(data),
        "executable": str(executable),
        "parent_pid": 11180,
        "parent_creation_time": CREATION_UTC,
    }
    (workspace / "workspace.json").write_text(json.dumps(marker), encoding="utf-8")
    (workspace / "database.private.dpapi").write_bytes(b"sealed-fixture")
    (workspace / "database-keys.private.dpapi").write_bytes(b"sealed-fixture")
    return workspace, repo, marker


@pytest.fixture
def restored_install_pair(tmp_path, owned_workspace):
    source, repo, source_marker = owned_workspace
    source_marker["workspace_id"] = "a" * 32
    source_marker["port"] = 3324
    (source / "workspace.json").write_text(json.dumps(source_marker), encoding="utf-8")
    target = source.parent / ".StudentMentalHealthAI-school-install-20261015-q"
    data = target / "mysql-data"
    (data / "mysql").mkdir(parents=True)
    (data / "auto.cnf").write_text("restored-install", encoding="utf-8")
    (data / "ibdata1").write_bytes(b"preserved restored install data")
    executable = target / "vendor" / "mysqld.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"synthetic target executable fixture")
    target_marker = {
        **source_marker,
        "workspace_id": "b" * 32,
        "port": 3325,
        "data_directory": str(data),
        "executable": str(executable),
        "parent_pid": 33350,
    }
    (target / "workspace.json").write_text(json.dumps(target_marker), encoding="utf-8")
    restore_state = {
        "schema_version": resume.RESTORE_STATE_SCHEMA,
        "synthetic_only": True,
        "phase": resume.RESTORE_VERIFIED_PHASE,
        "database": resume.DATABASE,
        "host": resume.HOST,
        "port": 3325,
        "workspace_id": target_marker["workspace_id"],
        "source_workspace_id": source_marker["workspace_id"],
        "workspace": str(target),
        "data_directory": str(data),
        "snapshot_revision": "20261014_0018",
        "runtime_revision": resume.CURRENT_SCHOOL_REVISION,
    }
    (target / "restore-state.json").write_text(json.dumps(restore_state), encoding="utf-8")
    prepare_runtime_artifacts(target, target_marker)
    return target, source, repo, target_marker, source_marker, restore_state


def run_fresh_resume(workspace, repo, marker, ops, **kwargs):
    return resume.resume_fresh_workspace(
        workspace,
        repo,
        expected_port=marker["port"],
        expected_workspace_id=marker["workspace_id"],
        ops=ops,
        lock_factory=lambda _path: nullcontext(),
        **kwargs,
    )


def prepare_runtime_artifacts(workspace, marker, *, include_all=True):
    (workspace / "runtime.private.dpapi").write_bytes(b"sealed-runtime-fixture")
    if include_all:
        (workspace / "school-auth.private.dpapi").write_bytes(b"sealed-auth-fixture")
        (workspace / "runtime-ready.json").write_text(
            json.dumps(
                {
                    "workspace_id": marker["workspace_id"],
                    "state": "VERIFIED",
                    "database": marker["database"],
                    "port": marker["port"],
                }
            ),
            encoding="utf-8",
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


def test_fresh_resume_starts_existing_target_and_uses_dpapi_and_readonly_database_checks(
    fresh_workspace,
):
    workspace, repo, marker = fresh_workspace
    data_before = (workspace / "mysql-data" / "ibdata1").read_bytes()
    ops = FreshFakeOperations()

    result = run_fresh_resume(workspace, repo, marker, ops, timeout=5)

    assert result == {"status": "STARTED", "database": "smhai_school_demo", "port": 3315}
    assert ops.started == (
        Path(marker["executable"]), workspace, Path(marker["data_directory"]), 3315
    )
    assert ops.dpapi_calls == 2
    assert ops.fresh_database_calls == 1
    assert ops.runtime_calls == 0
    assert (workspace / "mysql-data" / "ibdata1").read_bytes() == data_before
    saved = json.loads((workspace / "workspace.json").read_text(encoding="utf-8"))
    assert saved["resume_state"] == "READY"


def test_prepared_install_resume_uses_full_runtime_verification(fresh_workspace):
    workspace, repo, marker = fresh_workspace
    prepare_runtime_artifacts(workspace, marker)
    ops = FakeOperations()

    result = resume.resume_prepared_install_workspace(
        workspace,
        repo,
        expected_port=3315,
        expected_workspace_id=marker["workspace_id"],
        ops=ops,
        lock_factory=lambda _path: nullcontext(),
        timeout=5,
    )

    assert result == {"status": "STARTED", "database": "smhai_school_demo", "port": 3315}
    assert ops.runtime_calls == 1
    assert ops.verify_calls == 1


def test_restored_install_resume_uses_explicit_source_target_pins_and_existing_guardian_flow(
    restored_install_pair,
):
    target, source, repo, target_marker, source_marker, _state = restored_install_pair
    data_before = (target / "mysql-data" / "ibdata1").read_bytes()
    source_marker_before = (source / "workspace.json").read_bytes()
    ops = FreshFakeOperations()

    result = resume.resume_restored_install_workspace(
        target,
        repo,
        expected_port=target_marker["port"],
        expected_workspace_id=target_marker["workspace_id"],
        source_workspace=source,
        source_port=source_marker["port"],
        expected_source_workspace_id=source_marker["workspace_id"],
        ops=ops,
        lock_factory=lambda _path: nullcontext(),
        timeout=5,
    )

    assert result == {
        "status": "STARTED", "database": resume.DATABASE, "port": target_marker["port"]
    }
    assert ops.started == (
        Path(target_marker["executable"]), target,
        Path(target_marker["data_directory"]), target_marker["port"],
    )
    assert ops.dpapi_calls == 2
    assert ops.fresh_database_calls == 1
    assert ops.runtime_calls == 0
    assert (target / "mysql-data" / "ibdata1").read_bytes() == data_before
    assert (source / "workspace.json").read_bytes() == source_marker_before
    saved = json.loads((target / "workspace.json").read_text(encoding="utf-8"))
    assert saved["resume_state"] == "READY"
    restore = json.loads((target / "restore-state.json").read_text(encoding="utf-8"))
    assert restore == _state


@pytest.mark.parametrize(
    ("bad_case", "expected_code"),
    [
        ("source_id", "Restored install source and target identities"),
        ("same_id", "Restored install identity and distinct ports"),
        ("snapshot_revision", "Restored install evidence"),
        ("runtime_revision", "Restored install evidence"),
        ("same_port", "Restored install identity and distinct ports"),
        ("source_path", "Restored install source and target paths are not isolated"),
    ],
)
def test_restored_install_resume_rejects_mismatched_source_or_restore_proof_before_acl(
    restored_install_pair, bad_case, expected_code
):
    target, source, repo, target_marker, source_marker, state = restored_install_pair
    if bad_case in {"snapshot_revision", "runtime_revision"}:
        changed = dict(state)
        changed[bad_case] = "99999999_9999"
        (target / "restore-state.json").write_text(json.dumps(changed), encoding="utf-8")
    ops = FreshFakeOperations()
    kwargs = {
        "expected_port": target_marker["port"],
        "expected_workspace_id": target_marker["workspace_id"],
        "source_workspace": source,
        "source_port": source_marker["port"],
        "expected_source_workspace_id": source_marker["workspace_id"],
    }
    if bad_case == "source_id":
        kwargs["expected_source_workspace_id"] = "c" * 32
    elif bad_case == "same_id":
        kwargs["expected_source_workspace_id"] = target_marker["workspace_id"]
    elif bad_case == "same_port":
        kwargs["source_port"] = target_marker["port"]
    elif bad_case == "source_path":
        kwargs["source_workspace"] = repo
    with pytest.raises(resume.ResumeError, match=expected_code):
        resume.resume_restored_install_workspace(
            target,
            repo,
            **kwargs,
            ops=ops,
            lock_factory=lambda _path: nullcontext(),
        )
    assert ops.acl_calls == 0
    assert ops.started is None
    assert ops.dpapi_calls == 0


def test_restored_install_proof_is_revalidated_after_lock_acquisition(restored_install_pair):
    target, source, repo, target_marker, source_marker, state = restored_install_pair
    ops = FreshFakeOperations()

    @contextmanager
    def mutate_before_lock(_path):
        changed = dict(state, source_workspace_id="c" * 32)
        (target / "restore-state.json").write_text(json.dumps(changed), encoding="utf-8")
        yield

    with pytest.raises(resume.ResumeError, match="Restored install evidence"):
        resume.resume_restored_install_workspace(
            target,
            repo,
            expected_port=target_marker["port"],
            expected_workspace_id=target_marker["workspace_id"],
            source_workspace=source,
            source_port=source_marker["port"],
            expected_source_workspace_id=source_marker["workspace_id"],
            ops=ops,
            lock_factory=mutate_before_lock,
        )
    assert ops.acl_calls == 1
    assert ops.dpapi_calls == 1
    assert ops.started is None


def test_fresh_mode_rejects_prepared_artifacts_and_prepared_mode_rejects_partial_state(
    fresh_workspace,
):
    workspace, repo, marker = fresh_workspace
    prepare_runtime_artifacts(workspace, marker, include_all=False)
    fresh_ops = FreshFakeOperations()
    with pytest.raises(resume.ResumeError, match="runtime"):
        run_fresh_resume(workspace, repo, marker, fresh_ops)
    assert fresh_ops.acl_calls == 0 and fresh_ops.started is None

    prepared_ops = FakeOperations()
    with pytest.raises(resume.ResumeError, match="incomplete"):
        resume.resume_prepared_install_workspace(
            workspace,
            repo,
            expected_port=3315,
            expected_workspace_id=marker["workspace_id"],
            ops=prepared_ops,
            lock_factory=lambda _path: nullcontext(),
        )
    assert prepared_ops.acl_calls == 0 and prepared_ops.started is None


def test_prepared_install_rejects_reparse_runtime_artifact_before_acl(
    fresh_workspace, monkeypatch
):
    workspace, repo, marker = fresh_workspace
    prepare_runtime_artifacts(workspace, marker)
    runtime_file = workspace / "runtime.private.dpapi"

    def reject_runtime_reparse(path):
        if path == runtime_file:
            raise resume.ResumeError("runtime reparse")
        return original_reject(path)

    original_reject = resume._reject_reparse_path
    monkeypatch.setattr(resume, "_reject_reparse_path", reject_runtime_reparse)
    ops = FakeOperations()
    with pytest.raises(resume.ResumeError, match="runtime reparse"):
        resume.resume_prepared_install_workspace(
            workspace,
            repo,
            expected_port=3315,
            expected_workspace_id=marker["workspace_id"],
            ops=ops,
            lock_factory=lambda _path: nullcontext(),
        )
    assert ops.acl_calls == 0 and ops.started is None


def test_prepared_install_runtime_authority_rejection_fails_closed(fresh_workspace):
    class WrongRuntimeOperations(FakeOperations):
        def load_runtime(self, _workspace, _repo):
            self.runtime_calls += 1
            raise resume.ResumeError("Unexpected runtime privileges")

    workspace, repo, marker = fresh_workspace
    prepare_runtime_artifacts(workspace, marker)
    ops = WrongRuntimeOperations()
    with pytest.raises(resume.ResumeError, match="privileges"):
        resume.resume_prepared_install_workspace(
            workspace,
            repo,
            expected_port=3315,
            expected_workspace_id=marker["workspace_id"],
            ops=ops,
            lock_factory=lambda _path: nullcontext(),
            timeout=5,
        )
    assert ops.runtime_calls == 1
    assert ops.started is not None
    saved = json.loads((workspace / "workspace.json").read_text(encoding="utf-8"))
    assert saved["resume_state"] == "VALIDATION_FAILED_ResumeError"


@pytest.mark.parametrize("bad_id", ["unknown", "137ffe3243201bf34130b6585764edce"])
def test_fresh_resume_rejects_unknown_or_mismatched_workspace_id_before_acl(
    fresh_workspace, bad_id
):
    workspace, repo, _marker = fresh_workspace
    ops = FreshFakeOperations()
    with pytest.raises(resume.ResumeError):
        resume.resume_fresh_workspace(
            workspace,
            repo,
            expected_port=3315,
            expected_workspace_id=bad_id,
            ops=ops,
            lock_factory=lambda _path: nullcontext(),
        )
    assert ops.acl_calls == 0 and ops.started is None


@pytest.mark.parametrize("port", [3306, 3307, 3308, 3314, 3316, True, 3315.0])
def test_fresh_resume_rejects_wrong_port_or_port_type_before_acl(fresh_workspace, port):
    workspace, repo, marker = fresh_workspace
    ops = FreshFakeOperations()
    with pytest.raises(resume.ResumeError):
        resume.resume_fresh_workspace(
            workspace,
            repo,
            expected_port=port,
            expected_workspace_id=marker["workspace_id"],
            ops=ops,
            lock_factory=lambda _path: nullcontext(),
        )
    assert ops.acl_calls == 0 and ops.started is None


@pytest.mark.parametrize("bad_state", ["RESTORED", "UNKNOWN", "READY"])
def test_fresh_resume_rejects_restore_or_unknown_marker_classification_before_acl(
    fresh_workspace, bad_state
):
    workspace, repo, marker = fresh_workspace
    marker["state"] = bad_state
    (workspace / "workspace.json").write_text(json.dumps(marker), encoding="utf-8")
    ops = FreshFakeOperations()
    with pytest.raises(resume.ResumeError):
        run_fresh_resume(workspace, repo, marker, ops)
    assert ops.acl_calls == 0 and ops.started is None


def test_fresh_resume_rejects_reparse_path_before_acl(fresh_workspace, monkeypatch):
    workspace, repo, marker = fresh_workspace
    monkeypatch.setattr(
        resume,
        "_reject_reparse_path",
        lambda path: (_ for _ in ()).throw(resume.ResumeError("reparse path"))
        if path == workspace
        else None,
    )
    ops = FreshFakeOperations()
    with pytest.raises(resume.ResumeError, match="reparse path"):
        run_fresh_resume(workspace, repo, marker, ops)
    assert ops.acl_calls == 0 and ops.started is None


def test_fresh_resume_refuses_unverified_existing_guardian(fresh_workspace):
    workspace, repo, marker = fresh_workspace
    ops = FreshFakeOperations()
    ops.process = {
        "ProcessId": marker["parent_pid"],
        "ExecutablePath": marker["executable"],
        "CommandLine": "wrong guardian arguments",
        "CreationUtc": CREATION_UTC,
    }
    with pytest.raises(resume.ResumeError, match="guardian identity"):
        run_fresh_resume(workspace, repo, marker, ops)
    assert ops.started is None and ops.fresh_database_calls == 0


def test_verified_restore_resume_uses_target_port_and_existing_runtime_checks(
    restored_workspace_pair,
):
    source, target, repo, _source_marker, target_marker, restore_state = restored_workspace_pair
    source_data_before = (source / "mysql-data" / "ibdata1").read_bytes()
    target_data_before = (target / "mysql-data" / "ibdata1").read_bytes()
    original_state = json.loads((target / "restore-state.json").read_text(encoding="utf-8"))
    ops = FakeOperations()

    result = run_restore_resume(restored_workspace_pair, ops, timeout=5)

    saved = json.loads((target / "workspace.json").read_text(encoding="utf-8"))
    assert result == {"status": "STARTED", "database": "smhai_school_demo", "port": 3310}
    assert ops.started == (
        Path(target_marker["executable"]), target, Path(target_marker["data_directory"]), 3310
    )
    assert ops.readiness_ports == [3310]
    assert ops.listener_ports == [3310, 3310]
    assert ops.runtime_calls == 1 and ops.verify_calls == 1
    assert saved["port"] == 3310 and saved["resume_state"] == "READY"
    assert json.loads((target / "restore-state.json").read_text(encoding="utf-8")) == original_state
    assert (source / "mysql-data" / "ibdata1").read_bytes() == source_data_before
    assert (target / "mysql-data" / "ibdata1").read_bytes() == target_data_before
    assert restore_state["workspace_id"] != _source_marker["workspace_id"]
    assert repo not in target.parents


@pytest.mark.parametrize(
    "mutation",
    [
        "schema",
        "phase",
        "source_id",
        "target_id",
        "same_id",
        "workspace_path",
        "data_directory",
        "state_port",
        "nonsynthetic",
        "snapshot_revision",
        "runtime_revision",
    ],
)
def test_restore_resume_rejects_unverified_or_mismatched_restore_state_before_acl(
    restored_workspace_pair, mutation
):
    _source, target, _repo, source_marker, target_marker, state = restored_workspace_pair
    if mutation == "schema":
        state["schema_version"] = "unknown"
    elif mutation == "phase":
        state["phase"] = "FAILED_PRESERVED"
    elif mutation == "source_id":
        state["source_workspace_id"] = "wrong-source"
    elif mutation == "target_id":
        state["workspace_id"] = "wrong-target"
    elif mutation == "same_id":
        state["source_workspace_id"] = state["workspace_id"]
    elif mutation == "workspace_path":
        state["workspace"] = str(_source)
    elif mutation == "data_directory":
        state["data_directory"] = source_marker["data_directory"]
    elif mutation == "state_port":
        state["port"] = 3311
    elif mutation == "nonsynthetic":
        state["synthetic_only"] = False
    elif mutation == "snapshot_revision":
        state["snapshot_revision"] = "head"
    elif mutation == "runtime_revision":
        state["runtime_revision"] = "20261012_0006"
    (target / "restore-state.json").write_text(json.dumps(state), encoding="utf-8")
    ops = FakeOperations()

    with pytest.raises(resume.ResumeError):
        run_restore_resume(restored_workspace_pair, ops)

    assert ops.acl_calls == 0
    assert ops.started is None
    assert ops.runtime_calls == 0
    assert target_marker["port"] == 3310


@pytest.mark.parametrize("expected_port", [3308, 3307, 3400, True, 3310.0])
def test_restore_resume_requires_explicit_dedicated_integer_port(
    restored_workspace_pair, expected_port
):
    ops = FakeOperations()
    with pytest.raises(resume.ResumeError):
        run_restore_resume(restored_workspace_pair, ops, expected_port=expected_port)
    assert ops.acl_calls == 0
    assert ops.started is None


def test_nondefault_core_port_requires_restore_mode(restored_workspace_pair):
    _source, target, repo, *_rest = restored_workspace_pair
    ops = FakeOperations()

    with pytest.raises(resume.ResumeError, match="explicit restore mode"):
        resume.resume_workspace(
            target,
            repo,
            expected_workspace=target,
            expected_port=3310,
            ops=ops,
            lock_factory=lambda _path: nullcontext(),
        )

    assert ops.acl_calls == 0 and ops.started is None


def test_restore_resume_revalidates_original_source_marker(restored_workspace_pair):
    source, _target, _repo, source_marker, *_rest = restored_workspace_pair
    source_marker["port"] = 3309
    (source / "workspace.json").write_text(json.dumps(source_marker), encoding="utf-8")
    ops = FakeOperations()

    with pytest.raises(resume.ResumeError):
        run_restore_resume(restored_workspace_pair, ops)

    assert ops.acl_calls == 0 and ops.started is None


def test_restore_resume_refuses_runtime_identity_mismatch_after_readiness(
    restored_workspace_pair,
):
    class WrongRuntimeOperations(FakeOperations):
        def load_runtime(self, workspace, _repo):
            self.runtime_calls += 1
            marker = json.loads((workspace / "workspace.json").read_text(encoding="utf-8"))
            return {
                "database": marker["database"],
                "port": marker["port"] + 1,
                "identity_profile": "school_tenant",
            }

    _source, target, _repo, *_rest = restored_workspace_pair
    ops = WrongRuntimeOperations()

    with pytest.raises(resume.ResumeError, match="Runtime grants or schema"):
        run_restore_resume(restored_workspace_pair, ops)

    saved = json.loads((target / "workspace.json").read_text(encoding="utf-8"))
    assert ops.readiness_ports == [3310]
    assert saved["resume_state"] == "VALIDATION_FAILED_ResumeError"
    assert ops.started is not None


def test_restore_state_is_revalidated_after_lock_is_acquired(restored_workspace_pair):
    _source, target, repo, *_rest, state = restored_workspace_pair
    ops = FakeOperations()

    @contextmanager
    def mutate_before_lock(_path):
        changed = dict(state, phase="FAILED_PRESERVED")
        (target / "restore-state.json").write_text(json.dumps(changed), encoding="utf-8")
        yield

    with pytest.raises(resume.ResumeError):
        resume.resume_restored_workspace(
            target, repo, expected_port=3310, ops=ops, lock_factory=mutate_before_lock
        )

    assert ops.acl_calls == 1
    assert ops.started is None and ops.runtime_calls == 0


def test_restore_resume_cli_requires_explicit_workspace_and_port(monkeypatch):
    calls = []
    monkeypatch.setattr(resume, "resume_restored_workspace", lambda *args, **kwargs: calls.append((args, kwargs)) or {"status": "STARTED"})
    monkeypatch.setattr(sys, "argv", ["resume_school_workspace.py", "--restore-mode", "--workspace", r"D:\Projects\.StudentMentalHealthAI-school-restore-20261012-b"])

    with pytest.raises(SystemExit) as caught:
        resume.main()

    assert caught.value.code == 2
    assert calls == []


def test_restore_resume_cli_passes_explicit_workspace_and_port(monkeypatch, capsys):
    calls = []
    target = Path(r"D:\Projects\.StudentMentalHealthAI-school-restore-20261012-b")
    monkeypatch.setattr(
        resume,
        "resume_restored_workspace",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {"status": "STARTED"},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["resume_school_workspace.py", "--restore-mode", "--workspace", str(target), "--port", "3310"],
    )

    assert resume.main() == 0

    assert calls == [((target, resume.DEFAULT_REPO), {"expected_port": 3310, "timeout": 45.0})]
    assert json.loads(capsys.readouterr().out) == {"status": "STARTED"}


def test_restored_install_cli_requires_all_explicit_source_and_target_pins(monkeypatch):
    calls = []
    monkeypatch.setattr(
        resume,
        "resume_restored_install_workspace",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {"status": "STARTED"},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "resume_school_workspace.py", "--restored-install-mode",
            "--workspace", r"D:\Projects\.StudentMentalHealthAI-school-install-20261015-q",
            "--port", "3325", "--expected-workspace-id", "b" * 32,
            "--source-workspace", r"D:\Projects\.StudentMentalHealthAI-school-install-20261014-p",
            "--source-port", "3324", "--expected-source-workspace-id", "a" * 32,
        ],
    )

    assert resume.main() == 0
    assert calls == [
        (
            (Path(r"D:\Projects\.StudentMentalHealthAI-school-install-20261015-q"), resume.DEFAULT_REPO),
            {
                "expected_port": 3325,
                "expected_workspace_id": "b" * 32,
                "source_workspace": Path(r"D:\Projects\.StudentMentalHealthAI-school-install-20261014-p"),
                "source_port": 3324,
                "expected_source_workspace_id": "a" * 32,
                "timeout": 45.0,
            },
        )
    ]


def test_restored_install_cli_rejects_missing_source_identity_before_resume(monkeypatch):
    calls = []
    monkeypatch.setattr(
        resume,
        "resume_restored_install_workspace",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {"status": "STARTED"},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "resume_school_workspace.py", "--restored-install-mode",
            "--workspace", r"D:\Projects\.StudentMentalHealthAI-school-install-20261015-q",
            "--port", "3325", "--expected-workspace-id", "b" * 32,
        ],
    )

    with pytest.raises(SystemExit) as caught:
        resume.main()
    assert caught.value.code == 2
    assert calls == []


def test_default_cli_resumes_only_registered_workspace_on_3308(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        resume,
        "resume_workspace",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {"status": "ALREADY_RUNNING"},
    )
    monkeypatch.setattr(sys, "argv", ["resume_school_workspace.py"])

    assert resume.main() == 0

    assert calls == [
        ((resume.DEFAULT_WORKSPACE, resume.DEFAULT_REPO), {"expected_port": 3308, "timeout": 45.0})
    ]
    assert json.loads(capsys.readouterr().out) == {"status": "ALREADY_RUNNING"}


def test_fresh_cli_requires_explicit_target_port_and_expected_id(monkeypatch):
    calls = []
    monkeypatch.setattr(
        resume,
        "resume_fresh_workspace",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {"status": "STARTED"},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["resume_school_workspace.py", "--fresh-mode", "--workspace", r"D:\Projects\.StudentMentalHealthAI-school-install-20261013-g", "--port", "3315"],
    )
    with pytest.raises(SystemExit) as caught:
        resume.main()
    assert caught.value.code == 2
    assert calls == []


def test_fresh_cli_passes_explicit_target_port_and_expected_id(monkeypatch, capsys):
    calls = []
    target = Path(r"D:\Projects\.StudentMentalHealthAI-school-install-20261013-g")
    workspace_id = "137ffe3243201bf34130b6585764edcf"
    monkeypatch.setattr(
        resume,
        "resume_fresh_workspace",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {"status": "STARTED"},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "resume_school_workspace.py",
            "--fresh-mode",
            "--workspace",
            str(target),
            "--port",
            "3315",
            "--expected-workspace-id",
            workspace_id,
        ],
    )

    assert resume.main() == 0
    assert calls == [
        (
            (target, resume.DEFAULT_REPO),
            {"expected_port": 3315, "expected_workspace_id": workspace_id, "timeout": 45.0},
        )
    ]
    assert json.loads(capsys.readouterr().out) == {"status": "STARTED"}


def test_fresh_cli_rejects_combined_restore_classification(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["resume_school_workspace.py", "--fresh-mode", "--restore-mode"],
    )
    with pytest.raises(SystemExit) as caught:
        resume.main()
    assert caught.value.code == 2


def test_prepared_cli_requires_explicit_identity_and_dispatches_separate_mode(
    monkeypatch, capsys
):
    calls = []
    target = Path(r"D:\Projects\.StudentMentalHealthAI-school-install-20261013-g")
    workspace_id = "137ffe3243201bf34130b6585764edcf"
    monkeypatch.setattr(
        resume,
        "resume_prepared_install_workspace",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {"status": "STARTED"},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "resume_school_workspace.py",
            "--prepared-install-mode",
            "--workspace",
            str(target),
            "--port",
            "3315",
            "--expected-workspace-id",
            workspace_id,
        ],
    )
    assert resume.main() == 0
    assert calls == [
        (
            (target, resume.DEFAULT_REPO),
            {"expected_port": 3315, "expected_workspace_id": workspace_id, "timeout": 45.0},
        )
    ]
    assert json.loads(capsys.readouterr().out) == {"status": "STARTED"}


def test_prepared_cli_rejects_combined_restore_classification(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["resume_school_workspace.py", "--prepared-install-mode", "--restore-mode"],
    )
    with pytest.raises(SystemExit) as caught:
        resume.main()
    assert caught.value.code == 2


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
