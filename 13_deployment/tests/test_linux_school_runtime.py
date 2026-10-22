"""Unit checks for the Linux-only synthetic school runtime boundary."""

from __future__ import annotations

import json
import os
import sys
from xml.sax.saxutils import escape

import bootstrap_linux_school_demo as bootstrap
import linux_school_runtime as runtime
import migrate_school_linux as migration
import pytest
from database_layer.errors import ConfigurationError, EncryptionKeyUnavailable
from database_layer.systemd_auth import SystemdSchoolDatabaseCredential


@pytest.fixture
def clean_systemd_environment(monkeypatch):
    for name in tuple(os.environ):
        if name.startswith(("DB_", "DATABASE_")) or name == "MYSQL_PWD":
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(
        runtime.DATABASE_CREDENTIAL_ENV, runtime.DATABASE_CREDENTIAL_NAME
    )


@pytest.mark.parametrize(
    ("version", "supported"),
    [
        ("8.0.46-0ubuntu0.24.04.4", True),
        ("8.0.16", True),
        ("8.0.15", False),
        ("8.4.0", True),
        ("8.3.0", False),
        ("5.7.44", False),
        ("not-mysql", False),
    ],
)
def test_mysql_compatibility_floor_is_explicit(version, supported):
    assert runtime._supported_mysql_version(version) is supported


def test_runtime_grant_verification_accepts_only_schema_scoped_dml():
    runtime._verify_runtime_grants(
        [
            "GRANT USAGE ON *.* TO `psynova_runtime_0123456789abcdef`@`127.0.0.1`",
            (
                "GRANT SELECT, INSERT, UPDATE, DELETE ON `smhai_school_demo`.* "
                "TO `psynova_runtime_0123456789abcdef`@`127.0.0.1`"
            ),
        ],
        "NONE",
    )


@pytest.mark.parametrize(
    ("grants", "current_role"),
    [
        (["GRANT ALL PRIVILEGES ON `smhai_school_demo`.* TO runtime"], "NONE"),
        (["GRANT USAGE ON *.* TO runtime"], "ACTIVE_ROLE"),
        (
            [
                "GRANT USAGE ON *.* TO runtime",
                "GRANT SELECT, INSERT, UPDATE, DELETE ON *.* TO runtime",
            ],
            "NONE",
        ),
    ],
)
def test_runtime_grants_reject_privilege_expansion(grants, current_role):
    with pytest.raises(RuntimeError, match="least-privileged"):
        runtime._verify_runtime_grants(grants, current_role)


def test_migration_grant_verification_accepts_schema_scoped_ddl_only():
    migration._verify_migration_grants(
        [
            "GRANT USAGE ON *.* TO `psynova_migrator_0123456789abcdef`@`127.0.0.1`",
            (
                "GRANT CREATE, ALTER, INDEX, REFERENCES, SELECT, INSERT, UPDATE, DELETE "
                "ON `smhai_school_demo`.* TO `psynova_migrator_0123456789abcdef`@`127.0.0.1`"
            ),
        ],
        "NONE",
    )


def test_migration_grant_verification_rejects_global_ddl():
    with pytest.raises(RuntimeError, match="migration account privileges"):
        migration._verify_migration_grants(
            [
                "GRANT USAGE ON *.* TO migrator",
                "GRANT CREATE, ALTER ON *.* TO migrator",
            ],
            "NONE",
        )


def test_bootstrap_runtime_credential_matches_database_reader(monkeypatch):
    from database_layer import systemd_auth

    password = "!R4nd0m-Db-P4ssw0rd-2026"
    raw = bootstrap._credential_payload(
        "psynova_runtime_0123456789abcdef",
        password,
        csrf="a" * 64,
    )
    monkeypatch.setattr(
        systemd_auth, "read_linux_systemd_credential", lambda _name: raw
    )
    monkeypatch.setattr(systemd_auth.os, "name", "posix")
    monkeypatch.setattr(systemd_auth.sys, "platform", "linux")
    credential = systemd_auth.load_systemd_school_database_credential()
    assert credential.database == "smhai_school_demo"
    assert credential.username == "psynova_runtime_0123456789abcdef"
    assert credential.password == password


def test_mysql_generated_password_xml_result_is_parsed_in_memory_only():
    username = "psynova_runtime_0123456789abcdef"
    password = " p&<>" + "A" * 14 + " "
    fields = {
        "user": username,
        "host": "127.0.0.1",
        "generated password": password,
        "auth_factor": "1",
    }
    result = (
        "<resultset><row>"
        + "".join(
            f'<field name="{escape(name)}">{escape(value)}</field>'
            for name, value in fields.items()
        )
        + "</row></resultset>"
    )
    assert (
        bootstrap._parse_generated_password(
            result, username
        )
        == password
    )


def test_mysql_generated_password_rejects_unexpected_xml_shape():
    with pytest.raises(bootstrap.InstallError, match="unexpected account identity"):
        bootstrap._parse_generated_password(
            "<resultset><row><field name='user'>wrong</field></row></resultset>",
            "psynova_runtime_0123456789abcdef",
        )


def test_install_error_reports_fixed_phase_without_command_output(
    monkeypatch, capsys
):
    def fail_in_parse():
        bootstrap._set_install_phase("mysql_runtime_account_result_parse")
        raise bootstrap.InstallError("SQL_OUTPUT_SECRET_SENTINEL")

    monkeypatch.setattr(bootstrap, "install", fail_in_parse)
    monkeypatch.setattr(sys, "argv", ["bootstrap_linux_school_demo.py", "--install"])
    assert bootstrap.main() == 2
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["phase"] == "mysql_runtime_account_result_parse"
    assert "SQL_OUTPUT_SECRET_SENTINEL" not in output


def test_direct_or_verbose_database_environment_is_rejected(
    monkeypatch, clean_systemd_environment
):
    monkeypatch.setenv("DB_ECHO", "1")
    with pytest.raises(
        ConfigurationError, match="Direct database environment credentials"
    ):
        runtime.clear_unsafe_database_environment()


def test_wrong_key_credential_name_is_rejected(monkeypatch, clean_systemd_environment):
    monkeypatch.setenv("DATABASE_KEY_FILE", "/tmp/plaintext-key.json")
    with pytest.raises(EncryptionKeyUnavailable):
        runtime.clear_unsafe_database_environment()


def test_unavailable_mysql_fails_with_sanitized_error(
    monkeypatch, clean_systemd_environment
):
    import pymysql

    monkeypatch.setattr(
        pymysql,
        "connect",
        lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError("DATABASE_PASSWORD_SENTINEL")
        ),
    )
    credential = SystemdSchoolDatabaseCredential(
        host="127.0.0.1",
        port=3306,
        database="smhai_school_demo",
        username="psynova_runtime_0123456789abcdef",
        password="DATABASE_PASSWORD_SENTINEL",
        csrf_secret="0" * 64,
    )
    with pytest.raises(RuntimeError, match="preflight failed") as caught:
        runtime.verify_mysql_school_schema(credential)
    assert "DATABASE_PASSWORD_SENTINEL" not in str(caught.value)
    assert caught.value.__cause__ is None
