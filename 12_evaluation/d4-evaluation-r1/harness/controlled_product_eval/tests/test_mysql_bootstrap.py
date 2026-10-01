from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sqlalchemy.engine import make_url

from harness.controlled_product_eval import mysql_bootstrap
from harness.controlled_product_eval.credential_provider import DatabaseCredential


def test_mysql_application_account_is_limited_to_the_fixed_loopback_address():
    script = mysql_bootstrap._MYSQL_BOOTSTRAP_SCRIPT

    assert 'APP_HOST = "127.0.0.1"' in script
    assert 'account = f"`{APP_USER}`@`{APP_HOST}`"' in script
    assert "`%`" not in script


def test_async_database_readiness_uses_same_fixed_credential_without_logging_it(
    tmp_path, monkeypatch
):
    credential = DatabaseCredential(
        host="127.0.0.1",
        port=3307,
        database="smhai_d4_evaluation",
        username="smhai_eval_app",
        password="unit-test-password",
    )
    bootstrap = mysql_bootstrap.IsolatedMySqlBootstrap(
        repo_root=tmp_path / "repo",
        run_root=tmp_path / "attempt",
        backend_python=Path("D:/fixed/backend/python.exe"),
        credential=credential,
    )
    bootstrap.credential = credential
    captured = {}

    def capture_command(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            return_code=0,
            stdout=b"D4_MYSQL_ASYNC_READINESS=PASS",
            stderr=b"",
        )

    monkeypatch.setattr(mysql_bootstrap, "run_managed_command", capture_command)

    bootstrap._verify_async_app_readiness()

    assert captured["environment"]["DB_HOST"] == credential.host
    assert captured["environment"]["DB_PORT"] == str(credential.port)
    assert captured["environment"]["DB_USER"] == credential.username
    assert captured["environment"]["DB_NAME"] == credential.database
    assert "DB_PASSWORD" not in captured["environment"]
    url = make_url(captured["environment"]["DATABASE_URL"])
    assert url.host == credential.host
    assert url.port == credential.port
    assert url.username == credential.username
    assert url.database == credential.database
    assert url.password == credential.password
    assert captured["environment_allowlist"] == frozenset(captured["environment"])
    assert credential.password not in " ".join(captured["arguments"])
    assert credential.password not in str(captured["stdout_path"])
    assert credential.password not in str(captured["stderr_path"])


def test_async_database_readiness_probe_source_compiles():
    compile(mysql_bootstrap._ASYNC_MYSQL_READINESS_SCRIPT, "mysql-async-readiness", "exec")
    assert "read_timeout=" not in mysql_bootstrap._ASYNC_MYSQL_READINESS_SCRIPT
    assert "write_timeout=" not in mysql_bootstrap._ASYNC_MYSQL_READINESS_SCRIPT
    assert "await connection.ensure_closed()" in mysql_bootstrap._ASYNC_MYSQL_READINESS_SCRIPT


def test_alembic_runs_from_fixed_database_directory(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    database_path = repo_root / "11_database"
    database_path.mkdir(parents=True)
    config_path = database_path / "alembic.ini"
    config_path.write_text("[alembic]\nscript_location = migrations\n", encoding="utf-8")
    captured = {}

    def capture_command(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(return_code=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(mysql_bootstrap, "run_managed_command", capture_command)
    bootstrap = mysql_bootstrap.IsolatedMySqlBootstrap(
        repo_root=repo_root,
        run_root=tmp_path / "attempt",
        backend_python=Path("D:/fixed/backend/python.exe"),
        credential=DatabaseCredential(
            host="127.0.0.1",
            port=3307,
            database="smhai_d4_evaluation",
            username="smhai_eval_app",
            password="pw",
        ),
    )

    bootstrap._run_alembic("upgrade", "head")

    assert captured["cwd"] == database_path
    assert captured["arguments"] == (
        "-m",
        "alembic",
        "-c",
        str(config_path),
        "upgrade",
        "head",
    )
    assert captured["environment"]["DB_PASSWORD"] == "pw"
    assert captured["environment"]["USERNAME"] == "d4-evaluation"
    assert "pw" not in " ".join(captured["arguments"])
    assert "pw" not in str(captured["stdout_path"])
    assert "pw" not in str(captured["stderr_path"])
