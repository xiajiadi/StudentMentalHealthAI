"""Synthetic parsing tests for the Linux systemd school database credential."""

from __future__ import annotations

import json

import pytest
from database_layer import config, systemd_auth
from database_layer.errors import ConfigurationError
from sqlalchemy.engine import make_url

PASSWORD_SENTINEL = "synthetic-only-password-sentinel-0123456789"
CSRF_SENTINEL = "a" * 64


def _credential(*, role: str = "runtime") -> dict[str, object]:
    suffix = "0123456789abcdef" if role == "runtime" else "0123456789abcde"
    user_prefix = "psynova_runtime" if role == "runtime" else "psynova_migrator"
    result: dict[str, object] = {
        "schema": "psynova.school-runtime.v1",
        "database": {
            "host": "127.0.0.1",
            "port": 3306,
            "name": "smhai_school_demo",
            "user": f"{user_prefix}_{suffix}",
            "password": PASSWORD_SENTINEL,
        },
    }
    if role == "runtime":
        result["school_csrf_secret"] = CSRF_SENTINEL
    return result


def _patch_credential(monkeypatch, payload: object) -> None:
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    monkeypatch.setattr(systemd_auth, "read_linux_systemd_credential", lambda _name: raw)
    monkeypatch.setattr(systemd_auth.os, "name", "posix")
    monkeypatch.setattr(systemd_auth.sys, "platform", "linux")


def test_runtime_credential_is_strict_and_secret_safe(monkeypatch):
    _patch_credential(monkeypatch, _credential())
    credential = systemd_auth.load_systemd_school_database_credential()
    assert credential.username == "psynova_runtime_0123456789abcdef"
    assert credential.host == "127.0.0.1"
    assert credential.port == 3306
    assert credential.database == "smhai_school_demo"
    assert credential.csrf_secret == CSRF_SENTINEL
    assert PASSWORD_SENTINEL not in repr(credential)
    assert CSRF_SENTINEL not in repr(credential)


def test_migrator_credential_must_be_explicitly_requested(monkeypatch):
    _patch_credential(monkeypatch, _credential(role="migrator"))
    credential = systemd_auth.load_systemd_school_database_credential(role="migrator")
    assert credential.username == "psynova_migrator_0123456789abcde"
    assert credential.csrf_secret is None
    with pytest.raises(ConfigurationError):
        systemd_auth.load_systemd_school_database_credential(role="runtime")


def test_migrator_credential_rejects_usernames_over_mysql_limit(monkeypatch):
    payload = _credential(role="migrator")
    database = payload["database"]
    assert isinstance(database, dict)
    database["user"] = "psynova_migrator_0123456789abcdef"
    _patch_credential(monkeypatch, payload)

    with pytest.raises(ConfigurationError):
        systemd_auth.load_systemd_school_database_credential(role="migrator")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(extra=True),
        lambda payload: payload.update(schema="wrong.v1"),
        lambda payload: payload["database"].update(host="0.0.0.0"),
        lambda payload: payload["database"].update(port=True),
        lambda payload: payload["database"].update(name="mysql"),
        lambda payload: payload["database"].update(user="root"),
        lambda payload: payload["database"].update(password="short"),
        lambda payload: payload.update(school_csrf_secret="bad"),
    ],
)
def test_malformed_runtime_credential_fails_without_secret_details(monkeypatch, mutate):
    payload = _credential()
    mutate(payload)
    _patch_credential(monkeypatch, payload)
    with pytest.raises(ConfigurationError) as caught:
        systemd_auth.load_systemd_school_database_credential()
    assert str(caught.value) == "Linux school database credential is unavailable or invalid"
    assert PASSWORD_SENTINEL not in str(caught.value)
    assert caught.value.__cause__ is None


def test_duplicate_json_fields_are_rejected(monkeypatch):
    raw = (
        b'{"schema":"psynova.school-runtime.v1","schema":"other",'
        b'"database":{"host":"127.0.0.1","port":3306,"name":"smhai_school_demo",'
        b'"user":"psynova_runtime_0123456789abcdef",'
        b'"password":"synthetic-only-password-sentinel-0123456789"},'
        b'"school_csrf_secret":"' + CSRF_SENTINEL.encode() + b'"}'
    )
    _patch_credential(monkeypatch, raw)
    with pytest.raises(ConfigurationError):
        systemd_auth.load_systemd_school_database_credential()


def test_database_settings_use_systemd_auth_without_environment_secrets(monkeypatch):
    _patch_credential(monkeypatch, _credential())
    monkeypatch.setenv("DATABASE_AUTH_CREDENTIAL", "school-runtime.json")
    for name in ("DATABASE_URL", "DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT", "DB_NAME"):
        monkeypatch.delenv(name, raising=False)
    settings = config.DatabaseSettings.from_env()
    assert make_url(settings.url).username == "psynova_runtime_0123456789abcdef"
    assert make_url(settings.url).password == PASSWORD_SENTINEL
    assert PASSWORD_SENTINEL not in repr(settings)
    assert PASSWORD_SENTINEL not in settings.sanitized_url


@pytest.mark.parametrize("name", ["DB_PASSWORD", "DB_ECHO", "DATABASE_PASSWORD_FILE"])
def test_database_settings_reject_ambiguous_environment_secret(monkeypatch, name):
    _patch_credential(monkeypatch, _credential())
    monkeypatch.setenv("DATABASE_AUTH_CREDENTIAL", "school-runtime.json")
    monkeypatch.setenv(name, PASSWORD_SENTINEL)
    with pytest.raises(ConfigurationError, match="Ambiguous school database credential"):
        config.DatabaseSettings.from_env()
