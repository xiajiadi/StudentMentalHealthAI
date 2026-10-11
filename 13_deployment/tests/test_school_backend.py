import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_backend as backend


@pytest.mark.parametrize("state", ["UNVERIFIED", "VERIFIED"])
def test_runtime_readiness_must_match_workspace(tmp_path, monkeypatch, state):
    marker = {"workspace_id":"expected", "database":"smhai_school_demo", "port":3308}
    monkeypatch.setattr(backend, "validate_marker", lambda *args: marker)
    monkeypatch.setattr(backend, "verify_process", lambda *args: None)
    monkeypatch.setattr(backend, "read_private", lambda *args: pytest.fail("mismatched readiness must not decrypt"))
    (tmp_path / "runtime-ready.json").write_text(json.dumps(dict(marker, workspace_id="wrong", state=state)))
    with pytest.raises(backend.PreparationError):
        backend.load_runtime(tmp_path, tmp_path / "repo")


def test_missing_readiness_never_decrypts(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "validate_marker", lambda *args: {})
    monkeypatch.setattr(backend, "verify_process", lambda *args: None)
    monkeypatch.setattr(backend, "read_private", lambda *args: pytest.fail("missing readiness must not decrypt"))
    with pytest.raises(FileNotFoundError):
        backend.load_runtime(tmp_path, tmp_path / "repo")


@pytest.mark.parametrize("revision", ["20261011_0003", "obsolete"])
def test_configuration_uses_only_verified_sealed_target(tmp_path, monkeypatch, revision):
    marker = {"workspace_id":"expected", "database":"smhai_school_demo", "port":3308}
    monkeypatch.setattr(backend, "validate_marker", lambda *args: marker)
    monkeypatch.setattr(backend, "verify_process", lambda *args: None)
    (tmp_path / "runtime-ready.json").write_text(json.dumps(dict(marker,state="VERIFIED")))
    private = dict(DB_HOST="127.0.0.1", DB_PORT="3308", DB_NAME="smhai_school_demo", DB_USER="psynova_runtime_test", DB_PASSWORD="synthetic-only")
    reads = []

    def read(path):
        reads.append(path.name)
        return private if path.name == "runtime.private.dpapi" else {"SMHAI_SCHOOL_CSRF_SECRET":"a" * 64}

    monkeypatch.setattr(backend, "read_private", read)
    environment = dict(DB_PASSWORD="wrong", DATABASE_URL="wrong", SMHAI_IDENTITY_PROFILE="legacy_demo", MYSQL_PWD="wrong", KEEP="preserved")
    monkeypatch.setattr(backend.os, "environ", environment)

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self,*args):
            pass

        def execute(self,sql):
            self.sql = sql

        def fetchone(self):
            return ("NONE",)

        def fetchall(self):
            if self.sql == "SHOW GRANTS FOR CURRENT_USER()":
                return (("GRANT USAGE ON *.* TO 'runtime'",), ("GRANT SELECT, INSERT, UPDATE, DELETE ON `smhai_school_demo`.* TO 'runtime'",))
            return ((revision,),)

    class Connection:
        def cursor(self):
            return Cursor()

        def close(self):
            pass

    class Driver:
        @staticmethod
        def connect(**kwargs):
            assert kwargs["password"] == private["DB_PASSWORD"]
            assert kwargs["port"] == 3308
            return Connection()

    monkeypatch.setitem(sys.modules, "pymysql", Driver)
    if revision == "obsolete":
        with pytest.raises(backend.PreparationError):
            backend.load_runtime(tmp_path, tmp_path / "repo")
        assert reads == ["runtime.private.dpapi"]
        assert environment["DATABASE_URL"] == "wrong"
    else:
        result = backend.load_runtime(tmp_path, tmp_path / "repo")
        assert result["identity_profile"] == "school_tenant"
        assert reads == ["runtime.private.dpapi", "school-auth.private.dpapi"]
        assert all(environment[key] == value for key,value in private.items())
        assert environment["KEEP"] == "preserved"
        assert not {"DATABASE_URL", "MYSQL_PWD", "SMHAI_IDENTITY_PROFILE"} & environment.keys()
        assert environment["DATABASE_KEY_FILE"] == str(tmp_path / "database-keys.private.dpapi")
