"""Pure guards for new synthetic workspace creation; all OS effects are faked."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
spec = importlib.util.spec_from_file_location(
    "school_workspace_creation",
    Path(__file__).resolve().parents[1] / "create_school_workspace.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


SECRET_ENVIRONMENT = {
    "db_password": "synthetic-db-password",
    "SmHaI_demo_secret": "synthetic-csrf-secret",
    "mysql_pwd": "synthetic-mysql-password",
    "database_url": "mysql://synthetic-url",
    "DataBase_Key_File": "synthetic-key-path",
    "PATH": "synthetic-path",
}


def _working_socket(*, bind_error=None):
    class FakeSocket:
        def __init__(self):
            self.options = []
            self.bound = None

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def setsockopt(self, *args):
            self.options.append(args)

        def bind(self, address):
            if bind_error:
                raise bind_error
            self.bound = address

    fake = FakeSocket()
    return fake, lambda *_args, **_kwargs: fake


def _package_create_fakes(monkeypatch, tmp_path, *, actual_directory=None):
    target = tmp_path / "new-restore-workspace"
    repo = tmp_path / "repo"
    bin_dir = tmp_path / "vendor"
    repo.mkdir()
    bin_dir.mkdir()
    (bin_dir / "mysqld.exe").write_bytes(b"synthetic test executable marker")
    events = []
    captured = {"private": [], "marker": None, "popen": None, "sql": []}
    process = SimpleNamespace(pid=4321, poll=lambda: None)

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, statement):
            events.append(("sql", statement))
            captured["sql"].append(statement)

        def fetchone(self):
            return (3309, str(actual_directory or target / "mysql-data"))

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            events.append(("connection", "closed"))

    def run(args, **kwargs):
        events.append(("run", args[0]))
        captured.setdefault("run_calls", []).append((args, kwargs))
        return SimpleNamespace(
            stdout=b"temporary password is generated for root@localhost: synthetic-initial-password\n",
            stderr=b"",
        )

    def popen(args, **kwargs):
        events.append(("popen", args[0]))
        captured["popen"] = (args, kwargs)
        return process

    monkeypatch.setattr(module, "protect_directory", lambda path: events.append(("acl", path)))
    monkeypatch.setattr(module, "write_private", lambda path, values: captured["private"].append((path, values)))
    monkeypatch.setattr(module, "_require_free_loopback_port", lambda port: events.append(("port", port)))
    monkeypatch.setattr(
        module.ResumeOperations,
        "inspect_process",
        lambda self, pid: events.append(("inspect", pid)) or {"fake": "process"},
    )
    monkeypatch.setattr(
        module,
        "_process_matches",
        lambda process_metadata, marker: events.append(("match", process_metadata)) or True,
    )
    monkeypatch.setattr(
        module, "verify_process", lambda marker: events.append(("verify", marker.copy()))
    )
    monkeypatch.setattr(
        module.ResumeOperations,
        "process_creation_time",
        staticmethod(lambda _process: "2026-10-12T04:05:06.123456Z"),
    )
    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module.subprocess, "Popen", popen)
    monkeypatch.setattr(module, "bootstrap_connection", lambda *_args: _connection(events, FakeConnection))
    monkeypatch.setattr(module, "_write_marker", lambda path, value: _capture_marker(path, value, captured))
    monkeypatch.setitem(sys.modules, "pymysql", SimpleNamespace())
    monkeypatch.setattr(module.socket, "create_connection", lambda *_args, **_kwargs: _ReadyProbe())
    monkeypatch.setattr(module.secrets, "token_hex", lambda size: "a" * (size * 2))
    monkeypatch.setattr(module, "_sanitize_child_environment", lambda source=None: {"PATH": "synthetic-path"})
    monkeypatch.setattr(module.subprocess, "STARTUPINFO", _FakeStartupInfo)
    monkeypatch.setattr(module.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    return target, repo, bin_dir, events, captured, process


def _connection(events, constructor):
    events.append(("bootstrap", "connection"))
    return constructor()


def _capture_marker(path, value, captured):
    captured["marker"] = value.copy()
    Path(path).write_text(module.json.dumps(value), encoding="utf-8")


class _ReadyProbe:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class _FakeStartupInfo:
    def __init__(self):
        self.dwFlags = 0
        self.wShowWindow = 0


def test_validate_rejects_repository_and_legacy_workspace_overlap_before_port_probe(
    tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(module, "_require_free_loopback_port", lambda *_: pytest.fail("probed port"))
    with pytest.raises(module.WorkspaceError, match="External absolute"):
        module.validate_target(repo / "new", repo, 3309)

    legacy = tmp_path / "legacy-workspace"
    legacy.mkdir()
    monkeypatch.setattr(module, "OLD_SCHOOL_WORKSPACE", legacy)
    with pytest.raises(module.WorkspaceError, match="External absolute"):
        module.validate_target(legacy / "new", repo, 3309)


def test_raw_target_ancestor_reparse_point_is_rejected_before_resolve(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    parent = tmp_path / "linked-parent"
    parent.mkdir()
    target = parent / "new"
    original_lstat = Path.lstat

    def fake_lstat(path):
        if path == parent:
            return SimpleNamespace(st_file_attributes=0x400)
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    monkeypatch.setattr(Path, "resolve", lambda *_args, **_kwargs: pytest.fail("resolved reparse path"))

    with pytest.raises(module.WorkspaceError, match="reparse"):
        module.validate_target(target, repo, 3309)


def test_missing_parent_component_is_rejected(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    target = tmp_path / "missing-parent" / "new"
    monkeypatch.setattr(module, "_require_free_loopback_port", lambda *_: pytest.fail("probed port"))

    with pytest.raises(module.WorkspaceError, match="parent"):
        module.validate_target(target, repo, 3309)


def test_exclusive_port_probe_binds_loopback_and_fails_closed_on_socket_errors(monkeypatch):
    fake, factory = _working_socket()
    monkeypatch.setattr(module.socket, "socket", factory)
    monkeypatch.setattr(module.socket, "SO_EXCLUSIVEADDRUSE", 0x4, raising=False)

    module._require_free_loopback_port(3309)

    assert fake.options == [(module.socket.SOL_SOCKET, 0x4, 1)]
    assert fake.bound == ("127.0.0.1", 3309)

    _, occupied_factory = _working_socket(bind_error=OSError("port unavailable"))
    monkeypatch.setattr(module.socket, "socket", occupied_factory)
    with pytest.raises(module.WorkspaceError, match="occupied or unavailable"):
        module._require_free_loopback_port(3309)

    _, denied_factory = _working_socket(bind_error=PermissionError("socket denied"))
    monkeypatch.setattr(module.socket, "socket", denied_factory)
    with pytest.raises(module.WorkspaceError, match="occupied or unavailable"):
        module._require_free_loopback_port(3309)


def test_environment_filter_is_case_insensitive_and_keeps_only_safe_entries():
    safe = module._sanitize_child_environment(SECRET_ENVIRONMENT)

    assert safe == {"PATH": "synthetic-path"}


def test_acl_subprocesses_are_stubbed_hidden_and_receive_scrubbed_environment(tmp_path, monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        if args[0] == "pwsh" and len(calls) == 1:
            return SimpleNamespace(stdout="S-1-5-21-123")
        if args[0] == "pwsh":
            return SimpleNamespace(stdout="[]")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module.subprocess, "STARTUPINFO", _FakeStartupInfo)
    monkeypatch.setattr(module.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    with patch.dict(module.os.environ, SECRET_ENVIRONMENT, clear=True):
        module.protect_directory(tmp_path)

    assert len(calls) >= 4
    for _args, kwargs in calls:
        environment = kwargs["env"]
        assert all(
            not key.upper().startswith(("DB_", "SMHAI_"))
            and key.upper() not in {"MYSQL_PWD", "DATABASE_URL", "DATABASE_KEY_FILE"}
            for key in environment
        )
        assert kwargs["creationflags"] == 0x08000000
        assert kwargs["startupinfo"].wShowWindow == 0


def test_guardian_creation_and_database_identity_are_checked_before_schema_ddl(
    tmp_path, monkeypatch
):
    target, repo, bin_dir, events, captured, process = _package_create_fakes(
        monkeypatch, tmp_path
    )

    def verify_marker(marker):
        events.append(("verify", marker.copy()))
        assert "db_password" not in module.os.environ
        assert "MYSQL_PWD" not in module.os.environ
        assert "DATABASE_URL" not in module.os.environ

    monkeypatch.setattr(module, "verify_process", verify_marker)
    with patch.dict(module.os.environ, SECRET_ENVIRONMENT, clear=True):
        result = module.create(target, bin_dir, repo, 3309)

    assert result["state"] == "READY_FOR_MIGRATION"
    event_types = [entry[0] for entry in events]
    assert event_types.index("match") < event_types.index("verify")
    assert event_types.index("verify") < event_types.index("bootstrap")
    assert event_types.index("port", 1) < event_types.index("popen")
    statements = [entry[1] for entry in events if entry[0] == "sql"]
    assert statements[0].startswith("ALTER USER")
    assert statements[1] == "SELECT @@port, @@datadir"
    assert captured["marker"]["parent_creation_time"] == "2026-10-12T04:05:06.123456Z"
    assert len([entry for entry in events if entry[0] == "port"]) == 2

    argv, kwargs = captured["popen"]
    assert "synthetic-initial-password" not in repr(argv)
    assert "synthetic-initial-password" not in repr(kwargs["env"])
    assert not any("password" in arg.casefold() for arg in argv)
    assert kwargs["env"] == {"PATH": "synthetic-path"}
    assert kwargs["creationflags"] == 0x08000000
    assert kwargs["startupinfo"].wShowWindow == 0
    assert kwargs["shell"] is False
    assert process.poll() is None


def test_wrong_connected_datadir_preserves_marker_and_live_process_before_create_user(
    tmp_path, monkeypatch
):
    target, repo, bin_dir, events, captured, process = _package_create_fakes(
        monkeypatch, tmp_path, actual_directory=tmp_path / "foreign-data"
    )

    with pytest.raises(module.WorkspaceError, match="database identity"):
        module.create(target, bin_dir, repo, 3309)

    statements = [entry[1] for entry in events if entry[0] == "sql"]
    assert len(statements) == 2
    assert statements[0].startswith("ALTER USER")
    assert statements[1] == "SELECT @@port, @@datadir"
    assert captured["marker"]["state"] == "SETUP_FAILED_NO_AUTO_STOP"
    assert captured["marker"]["parent_pid"] == process.pid
    assert process.poll() is None
    assert "taskkill" not in repr(captured)
