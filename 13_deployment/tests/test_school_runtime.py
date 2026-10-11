import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("prepare_school_runtime", ROOT / "prepare_school_runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def workspace(tmp_path):
    target = tmp_path / "workspace"
    target.mkdir()
    marker = dict(schema_version="psynova.synthetic-workspace.v1", project="StudentMentalHealthAI", synthetic_only=True, host="127.0.0.1", database="smhai_school_demo", port=3308, state="READY_FOR_MIGRATION", workspace_id="owned-test-workspace", data_directory=str(target / "mysql-data"))
    (target / "workspace.json").write_text(json.dumps(marker))
    return target, marker


@pytest.mark.parametrize("field,value", [("port",3307),("port",3306),("port","3308"),("synthetic_only",False),("database","smhai_m0_demo"),("host","0.0.0.0"),("state","SETUP_FAILED")])
def test_refuses_other_workspaces(tmp_path, field, value):
    target, marker = workspace(tmp_path)
    marker[field] = value
    (target / "workspace.json").write_text(json.dumps(marker))
    with pytest.raises(runtime.PreparationError):
        runtime.validate_marker(target, tmp_path / "repo")


def test_validates_owned_new_workspace(tmp_path):
    target, marker = workspace(tmp_path)
    assert runtime.validate_marker(target, tmp_path / "repo") == marker


def test_refuses_repository_directory(tmp_path):
    target, _ = workspace(tmp_path)
    with pytest.raises(runtime.PreparationError):
        runtime.validate_marker(target, tmp_path)


def test_existing_settings_never_overwritten(tmp_path, monkeypatch):
    target, _ = workspace(tmp_path)
    protected = target / "runtime.private.dpapi"
    protected.write_bytes(b"preserved")
    monkeypatch.setattr(runtime, "verify_process", lambda marker: None)
    monkeypatch.setattr(runtime, "read_private", lambda path: pytest.fail("must not decrypt"))
    with pytest.raises(runtime.PreparationError):
        runtime.prepare(target, tmp_path / "repo")
    assert protected.read_bytes() == b"preserved"


@pytest.mark.parametrize("revision,role", [("20261011_0003","NONE"), ("20261010_0002","NONE"), ("20261011_0003","unexpected-role")])
def test_provision_checks_revision_before_sealed_write_and_ddl(tmp_path, monkeypatch, revision, role):
    target, marker = workspace(tmp_path)
    calls = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, statement, params=None):
            self.statement = statement
            calls.append(statement)

        def fetchone(self):
            if self.statement == "SELECT CURRENT_ROLE()":
                return (role,)
            return marker["port"], marker["data_directory"], marker["database"]

        def fetchall(self):
            if self.statement == "SHOW GRANTS FOR CURRENT_USER()":
                return (("GRANT USAGE ON *.* TO 'runtime'@'127.0.0.1'",), ("GRANT SELECT, INSERT, UPDATE, DELETE ON `smhai_school_demo`.* TO 'runtime'@'127.0.0.1'",))
            return ((revision,),)

    class Connection:
        def cursor(self):
            return Cursor()

        def commit(self):
            calls.append("commit")

        def close(self):
            calls.append("close")

    class Driver:
        @staticmethod
        def connect(**kwargs):
            return Connection()

    monkeypatch.setitem(sys.modules, "pymysql", Driver)
    monkeypatch.setattr(runtime, "verify_process", lambda marker: None)
    monkeypatch.setattr(runtime, "read_private", lambda path: {"DB_NAME":marker["database"], "DB_PORT":str(marker["port"]), "DB_HOST":"127.0.0.1", "root_password":"test-only-value"})
    monkeypatch.setattr(runtime, "write_private", lambda path, values: calls.append("sealed write"))
    if revision != "20261011_0003":
        with pytest.raises(runtime.PreparationError):
            runtime.prepare(target, tmp_path / "repo")
        assert "sealed write" not in calls
        assert not any(c.startswith("CREATE") for c in calls)
    elif role != "NONE":
        with pytest.raises(runtime.PreparationError):
            runtime.prepare(target, tmp_path / "repo")
        assert "ALTER USER %s@'127.0.0.1' ACCOUNT LOCK" in calls
        assert not (target / "runtime-ready.json").exists()
    else:
        result = runtime.prepare(target, tmp_path / "repo")
        create = "CREATE USER %s@'127.0.0.1' IDENTIFIED BY %s"
        assert calls.index("sealed write") < calls.index(create)
        assert "GRANT SELECT, INSERT, UPDATE, DELETE ON `smhai_school_demo`.* TO %s@'127.0.0.1'" in calls
        assert "test-only-value" not in str(result)
    assert calls[-1] == "close"


@pytest.mark.parametrize("extra,role", [("GRANT SELECT ON *.* TO 'runtime'", "NONE"),("GRANT 'power_role' TO 'runtime'", "NONE"),(None,"`power_role`@`%`"),("GRANT USAGE ON *.* TO 'runtime' WITH GRANT OPTION", "NONE")])
def test_unexpected_permissions_rejected(extra, role):
    grants = ["GRANT USAGE ON *.* TO 'runtime'", "GRANT SELECT, INSERT, UPDATE, DELETE ON `smhai_school_demo`.* TO 'runtime'"]
    if extra:
        grants.append(extra)
    with pytest.raises(runtime.PreparationError):
        runtime.verify_runtime_grants(grants, role)
