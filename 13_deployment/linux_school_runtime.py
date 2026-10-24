"""Shared fail-closed Linux school-demo runtime checks."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

from database_layer.crypto import LinuxSystemdCredentialKeyProvider
from database_layer.errors import ConfigurationError, EncryptionKeyUnavailable
from database_layer.systemd_auth import (
    SystemdSchoolDatabaseCredential,
    load_systemd_school_database_credential,
)
from sqlalchemy.engine import URL

DATABASE_CREDENTIAL_ENV = "DATABASE_AUTH_CREDENTIAL"
DATABASE_CREDENTIAL_NAME = "school-runtime.json"
DATABASE_KEY_CREDENTIAL_NAME = "database-keys.json"
EXPECTED_DATABASE_NAME = "smhai_school_demo"
EXPECTED_SCHOOL_REVISION = "20261024_0025"
_FORBIDDEN_DATABASE_ENV = {
    "DATABASE_URL",
    "DB_USER",
    "DB_PASSWORD",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "MYSQL_PWD",
}


def configure_import_paths(repository_root: Path) -> None:
    root = repository_root.resolve(strict=True)
    for path in (
        root / "11_database",
        root / "09_backend" / "src",
        root / "13_deployment",
    ):
        resolved = path.resolve(strict=True)
        if not resolved.is_dir():
            raise RuntimeError("required application source is unavailable")
        value = str(resolved)
        if value in sys.path:
            sys.path.remove(value)
        sys.path.insert(0, value)


def clear_unsafe_database_environment() -> None:
    if any(
        name in _FORBIDDEN_DATABASE_ENV
        or name.startswith("DB_")
        or (
            name.startswith("DATABASE_")
            and name not in {"DATABASE_AUTH_CREDENTIAL", "DATABASE_KEY_FILE"}
        )
        for name in os.environ
    ):
        raise ConfigurationError(
            "Direct database environment credentials are forbidden"
        )
    configured = os.environ.get(DATABASE_CREDENTIAL_ENV)
    if configured != DATABASE_CREDENTIAL_NAME:
        raise ConfigurationError("systemd database credential name is required")
    if (
        os.environ.get("DATABASE_KEY_FILE", DATABASE_KEY_CREDENTIAL_NAME)
        != DATABASE_KEY_CREDENTIAL_NAME
    ):
        raise EncryptionKeyUnavailable(
            "Linux systemd encryption credential is unavailable or invalid"
        )


def load_school_runtime_credentials() -> SystemdSchoolDatabaseCredential:
    clear_unsafe_database_environment()
    return load_systemd_school_database_credential(
        DATABASE_CREDENTIAL_NAME, role="runtime"
    )


def validate_key_credential() -> str:
    provider = LinuxSystemdCredentialKeyProvider.from_env()
    # Only a key version label is returned; no key bytes or path escape this function.
    return provider.active_version


def mysql_url(credential: SystemdSchoolDatabaseCredential) -> str:
    return URL.create(
        "mysql+aiomysql",
        username=credential.username,
        password=credential.password,
        host=credential.host,
        port=credential.port,
        database=credential.database,
        query={"charset": "utf8mb4"},
    ).render_as_string(hide_password=False)


def _supported_mysql_version(value: str) -> bool:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        return False
    major, minor, patch = (int(part) for part in match.groups())
    return major == 8 and ((minor == 0 and patch >= 16) or minor == 4)


def _verify_runtime_grants(grants: list[str], current_role: str) -> None:
    scopes = {grant.split(" TO ", 1)[0] for grant in grants}
    expected = {
        "GRANT USAGE ON *.*",
        "GRANT SELECT, INSERT, UPDATE, DELETE ON `smhai_school_demo`.*",
    }
    if (
        len(grants) != 2
        or scopes != expected
        or current_role != "NONE"
        or any("WITH GRANT OPTION" in grant for grant in grants)
    ):
        raise RuntimeError("runtime database grants are not least-privileged")


def verify_mysql_school_schema(
    credential: SystemdSchoolDatabaseCredential,
    *,
    expected_revision: str = EXPECTED_SCHOOL_REVISION,
    require_runtime_grants: bool = True,
) -> dict[str, Any]:
    """Verify loopback database identity, version, grants, and exact Alembic head."""
    import pymysql

    connection = None
    try:
        connection = pymysql.connect(
            host=credential.host,
            port=credential.port,
            user=credential.username,
            password=credential.password,
            database=credential.database,
            connect_timeout=5,
            read_timeout=10,
            write_timeout=10,
            autocommit=True,
        )
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION(), @@port, DATABASE(), CURRENT_ROLE()")
            row = cursor.fetchone()
            if not row or len(row) != 4:
                raise RuntimeError("database identity could not be verified")
            version, port, database, current_role = row
            if (
                not isinstance(version, str)
                or not _supported_mysql_version(version)
                or port != 3306
                or database != EXPECTED_DATABASE_NAME
            ):
                raise RuntimeError("database target or MySQL version is unsupported")
            if require_runtime_grants:
                cursor.execute("SHOW GRANTS FOR CURRENT_USER()")
                grants = [grant[0] for grant in cursor.fetchall()]
                _verify_runtime_grants(grants, current_role)
            cursor.execute("SELECT version_num FROM database_alembic_version")
            revisions = cursor.fetchall()
            if revisions != ((expected_revision,),):
                raise RuntimeError("required school database revision is unavailable")
            cursor.execute(
                "SELECT DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME "
                "FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s",
                (EXPECTED_DATABASE_NAME,),
            )
            schema = cursor.fetchone()
            if schema != ("utf8mb4", "utf8mb4_0900_ai_ci"):
                raise RuntimeError("school schema character set is unsupported")
        return {
            "database": EXPECTED_DATABASE_NAME,
            "mysql_version": version,
            "port": 3306,
            "revision": expected_revision,
        }
    except Exception as exc:
        # Preserve only safe, typed errors. Driver messages can contain SQL or a URL.
        if isinstance(exc, (ConfigurationError, EncryptionKeyUnavailable)):
            raise
        raise RuntimeError("Linux school database preflight failed") from None
    finally:
        if connection is not None:
            connection.close()


__all__ = [
    "DATABASE_CREDENTIAL_ENV",
    "DATABASE_CREDENTIAL_NAME",
    "DATABASE_KEY_CREDENTIAL_NAME",
    "EXPECTED_DATABASE_NAME",
    "EXPECTED_SCHOOL_REVISION",
    "clear_unsafe_database_environment",
    "configure_import_paths",
    "load_school_runtime_credentials",
    "mysql_url",
    "validate_key_credential",
    "verify_mysql_school_schema",
]
