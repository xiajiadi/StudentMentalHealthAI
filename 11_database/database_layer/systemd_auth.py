"""Strict parser for MySQL credentials delivered by systemd credentials."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any

from .crypto import read_linux_systemd_credential
from .errors import ConfigurationError

_CREDENTIAL_SCHEMA = "psynova.school-runtime.v1"
_DATABASE_NAME = "smhai_school_demo"
_DATABASE_USER = re.compile(r"psynova_(?:runtime|migrator)_[a-f0-9]{16}\Z")
_DATABASE_PASSWORD = re.compile(r"[!-~]{20,128}\Z")
_CSRF_SECRET = re.compile(r"[a-f0-9]{64}\Z")


@dataclass(frozen=True, slots=True)
class SystemdSchoolDatabaseCredential:
    host: str
    port: int
    database: str
    username: str
    password: str = field(repr=False)
    csrf_secret: str | None = field(default=None, repr=False)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def load_systemd_school_database_credential(
    credential_name: str = "school-runtime.json",
    *,
    role: str = "runtime",
) -> SystemdSchoolDatabaseCredential:
    """Read and validate a root-encrypted systemd credential without logging it."""
    try:
        if os.name != "posix" or sys.platform != "linux" or role not in {"runtime", "migrator"}:
            raise ValueError
        payload = json.loads(
            read_linux_systemd_credential(credential_name).decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        if type(payload) is not dict or set(payload) not in (
            {"schema", "database"},
            {"schema", "database", "school_csrf_secret"},
        ):
            raise ValueError
        if payload.get("schema") != _CREDENTIAL_SCHEMA:
            raise ValueError
        database = payload.get("database")
        if type(database) is not dict or set(database) != {
            "host",
            "port",
            "name",
            "user",
            "password",
        }:
            raise ValueError
        user = database.get("user")
        if (
            database.get("host") != "127.0.0.1"
            or type(database.get("port")) is not int
            or database["port"] != 3306
            or database.get("name") != _DATABASE_NAME
            or not isinstance(user, str)
            or _DATABASE_USER.fullmatch(user) is None
            or not user.startswith(f"psynova_{role}_")
            or not isinstance(database.get("password"), str)
            or _DATABASE_PASSWORD.fullmatch(database["password"]) is None
        ):
            raise ValueError
        csrf_secret = payload.get("school_csrf_secret")
        if "school_csrf_secret" in payload:
            if not isinstance(csrf_secret, str) or _CSRF_SECRET.fullmatch(csrf_secret) is None:
                raise ValueError
        elif role == "runtime":
            raise ValueError
        return SystemdSchoolDatabaseCredential(
            host="127.0.0.1",
            port=3306,
            database=_DATABASE_NAME,
            username=user,
            password=database["password"],
            csrf_secret=csrf_secret,
        )
    except Exception:
        raise ConfigurationError(
            "Linux school database credential is unavailable or invalid"
        ) from None


__all__ = ["SystemdSchoolDatabaseCredential", "load_systemd_school_database_credential"]
