"""Create a sealed, consistent backup of the owned synthetic school database."""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import math
import os
import re
import sys
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from prepare_school_runtime import (
    validate_marker,
    verify_process,
    verify_runtime_grants,
)
from private_settings import MAGIC, read_private, write_private
from school_backend import (
    BACKUP_NOT_APPLICATION_READY,
    RUNTIME_PURPOSE_BACKUP,
    load_runtime,
)
from school_schema import LEGACY_SCHOOL_SNAPSHOT_REVISION, SUPPORTED_SNAPSHOT_REVISIONS

NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
BACKUP_V1 = "psynova.sealed-school-backup.v1"
BACKUP_V2 = "psynova.sealed-school-backup.v2"
SUPPORTED_REVISION = LEGACY_SCHOOL_SNAPSHOT_REVISION
SUPPORTED_BACKUP_REVISIONS = SUPPORTED_SNAPSHOT_REVISIONS
RECOVERY_SCOPE = "WINDOWS_CURRENT_USER_ONLY"
TARGET_POLICY = "NEW_ISOLATED_INSTANCE_ONLY"
AUTH_SESSION_POLICY = "REVOKE_ALL_AFTER_IMPORT"
SNAPSHOT_FIELDS = frozenset(
    {
        "schema_version",
        "project",
        "synthetic_only",
        "workspace_id",
        "database",
        "port",
        "revision",
        "tables",
    }
)
V2_FIELDS = SNAPSHOT_FIELDS | frozenset(
    {"database_key_container_b64", "recovery_scope", "target_policy", "auth_session_policy"}
)


def encode_value(value):
    if isinstance(value, bytes):
        return {"type": "bytes", "value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, datetime):
        return {"type": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"type": "date", "value": value.isoformat()}
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise TypeError("Non-finite backup value")
        return {"type": "decimal", "value": str(value)}
    if isinstance(value, float) and not math.isfinite(value):
        raise TypeError("Non-finite backup value")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("Unsupported backup value")


def decode_value(value):
    """Decode one v2 JSON value without accepting ambiguous or lossy tags."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite backup value")
        return value
    if not isinstance(value, dict) or set(value) != {"type", "value"}:
        raise ValueError("Invalid typed backup value")

    kind = value["type"]
    raw = value["value"]
    if not isinstance(kind, str) or not isinstance(raw, str):
        raise ValueError("Invalid typed backup value")  # noqa: TRY004 - malformed serialized value.
    if kind == "bytes":
        try:
            return base64.b64decode(raw.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
            raise ValueError("Invalid bytes backup value") from exc
    if kind == "date":
        try:
            parsed = date.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError("Invalid date backup value") from exc
        if parsed.isoformat() != raw:
            raise ValueError("Invalid date backup value")
        return parsed
    if kind == "datetime":
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError("Invalid datetime backup value") from exc
        if "T" not in raw or parsed.isoformat() != raw:
            raise ValueError("Invalid datetime backup value")
        return parsed
    if kind == "decimal":
        try:
            parsed = Decimal(raw)
        except InvalidOperation as exc:
            raise ValueError("Invalid decimal backup value") from exc
        if not parsed.is_finite():
            raise ValueError("Non-finite backup value")
        if str(parsed) != raw:
            raise ValueError("Invalid decimal backup value")
        return parsed
    raise ValueError("Unsupported backup value type")


def package_snapshot(snapshot_content: dict, database_key_container: bytes) -> dict:
    """Create a v2 recovery-preparation package from a v1 database snapshot.

    The application data key is retained only as its original DPAPI-sealed
    container; this function never unprotects or parses its contents. The
    header check does not establish that DPAPI can unseal it or that its keys
    match the database ciphertext.
    """
    if not isinstance(snapshot_content, dict):
        raise ValueError("Supported database snapshot required")  # noqa: TRY004 - invalid snapshot document.
    if not _valid_key_container(database_key_container):
        raise ValueError("DPAPI key-container header required")
    package = dict(snapshot_content)
    if package.get("schema_version") != BACKUP_V1:
        raise ValueError("Supported database snapshot required")
    package.update(
        schema_version=BACKUP_V2,
        database_key_container_b64=base64.b64encode(database_key_container).decode("ascii"),
        recovery_scope=RECOVERY_SCOPE,
        target_policy=TARGET_POLICY,
        auth_session_policy=AUTH_SESSION_POLICY,
    )
    validate_backup_package(package)
    return package


def _valid_key_container(value: object) -> bool:
    return isinstance(value, bytes) and len(value) > len(MAGIC) and value.startswith(MAGIC)


def validate_backup_package(package: dict) -> dict:
    """Validate v2 format structure; this is not a restore preflight.

    Exact table/column compatibility with the trusted revision manifest is a
    separate restore gate. Archived create_sql is evidence and is never run.
    """
    if not isinstance(package, dict):
        raise ValueError("Backup package object required")  # noqa: TRY004 - invalid package document.
    version = package.get("schema_version")
    if version == BACKUP_V1:
        raise ValueError("v1 backup lacks the key bundle and is not independently restorable")
    if version != BACKUP_V2 or set(package) != V2_FIELDS:
        raise ValueError("Unsupported or incomplete backup package")
    if (
        package.get("project") != "StudentMentalHealthAI"
        or package.get("synthetic_only") is not True
        or package.get("revision") not in SUPPORTED_BACKUP_REVISIONS
        or not isinstance(package.get("workspace_id"), str)
        or not package["workspace_id"]
        or package.get("database") != "smhai_school_demo"
        or isinstance(package.get("port"), bool)
        or not isinstance(package.get("port"), int)
        or not 3308 <= package["port"] <= 3399
    ):
        raise ValueError("Unsupported synthetic backup source")
    if (
        package.get("recovery_scope") != RECOVERY_SCOPE
        or package.get("target_policy") != TARGET_POLICY
        or package.get("auth_session_policy") != AUTH_SESSION_POLICY
    ):
        raise ValueError("Unsupported backup recovery policy")

    try:
        key_container = base64.b64decode(
            package["database_key_container_b64"].encode("ascii"), validate=True
        )
    except (AttributeError, UnicodeEncodeError, binascii.Error, ValueError) as exc:
        raise ValueError("Invalid sealed database key container") from exc
    if not _valid_key_container(key_container):
        raise ValueError("DPAPI key-container header required")

    tables = package.get("tables")
    if not isinstance(tables, dict) or not tables:
        raise ValueError("Backup tables required")
    for table_name, table in tables.items():
        if not isinstance(table_name, str) or not NAME.fullmatch(table_name):
            raise ValueError("Invalid backup table name")
        if not isinstance(table, dict) or set(table) != {"create_sql", "columns", "rows"}:
            raise ValueError("Invalid backup table structure")
        # Archived DDL is retained for provenance only. Restore code must use
        # the repository's pinned migrations and must never execute this value.
        if not isinstance(table["create_sql"], str) or not table["create_sql"]:
            raise ValueError("Invalid archived table definition")
        columns = table["columns"]
        rows = table["rows"]
        if (
            not isinstance(columns, list)
            or not columns
            or any(not isinstance(column, str) or not NAME.fullmatch(column) for column in columns)
            or len(columns) != len(set(columns))
            or not isinstance(rows, list)
        ):
            raise ValueError("Invalid backup table columns or rows")
        for row in rows:
            if not isinstance(row, list) or len(row) != len(columns):
                raise ValueError("Backup row width does not match columns")
            for encoded in row:
                decode_value(encoded)
    return package


def _same_directory(left: object, right: object) -> bool:
    return (
        type(left) is str
        and type(right) is str
        and os.path.normcase(os.path.normpath(left))
        == os.path.normcase(os.path.normpath(right))
    )


def _marker_binding(marker: object) -> dict:
    if type(marker) is not dict:
        raise TypeError("Verified backup workspace identity required")
    workspace_id = marker.get("workspace_id")
    database = marker.get("database")
    port = marker.get("port")
    data_directory = marker.get("data_directory")
    if (
        type(workspace_id) is not str
        or not workspace_id
        or type(database) is not str
        or type(port) is not int
        or not 3308 <= port <= 3399
        or type(data_directory) is not str
        or not data_directory
    ):
        raise ValueError("Verified backup workspace identity required")
    return {
        "workspace_id": workspace_id,
        "database": database,
        "port": port,
        "data_directory": data_directory,
    }


def snapshot(
    connection,
    marker: dict,
    *,
    expected_revision: str | None = None,
    expected_binding: dict | None = None,
) -> dict:
    """Read SQL values as stored; never decrypt private application payloads."""
    if expected_revision is not None and (
        type(expected_revision) is not str or expected_revision not in SUPPORTED_BACKUP_REVISIONS
    ):
        raise ValueError("Unsupported backup schema revision")
    binding = _marker_binding(marker)
    if expected_binding is None or type(expected_binding) is not dict:
        raise ValueError("Verified backup preflight binding required")
    if binding != expected_binding:
        raise ValueError("Backup workspace identity changed")
    tables = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SHOW GRANTS FOR CURRENT_USER()")
            grant_rows = cursor.fetchall()
            if (
                type(grant_rows) is not tuple
                or any(type(row) is not tuple or len(row) != 1 or type(row[0]) is not str for row in grant_rows)
            ):
                raise ValueError("Owned runtime privileges required")
            cursor.execute("SELECT CURRENT_ROLE()")
            role_row = cursor.fetchone()
            if type(role_row) is not tuple or len(role_row) != 1 or type(role_row[0]) is not str:
                raise ValueError("Owned runtime privileges required")
            try:
                verify_runtime_grants([row[0] for row in grant_rows], role_row[0])
            except Exception as exc:
                raise ValueError("Owned runtime privileges required") from exc

            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
            cursor.execute(
                "SELECT DATABASE(), @@port, @@datadir, @@transaction_isolation"
            )
            target = cursor.fetchone()
            if (
                type(target) is not tuple
                or len(target) != 4
                or target[0] != binding["database"]
                or type(target[1]) is not int
                or target[1] != binding["port"]
                or not _same_directory(target[2], binding["data_directory"])
                or target[3] != "REPEATABLE-READ"
            ):
                raise ValueError("Owned consistent snapshot target required")
            cursor.execute("SELECT version_num FROM database_alembic_version")
            revision_rows = cursor.fetchall()
            if (
                type(revision_rows) is not tuple
                or len(revision_rows) != 1
                or type(revision_rows[0]) is not tuple
                or len(revision_rows[0]) != 1
                or type(revision_rows[0][0]) is not str
            ):
                raise ValueError("Unsupported backup schema revision")
            revision = revision_rows[0][0]
            if (
                revision not in SUPPORTED_BACKUP_REVISIONS
                or (expected_revision is not None and revision != expected_revision)
            ):
                raise ValueError("Unsupported backup schema revision")
            cursor.execute(
                "SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME"
            )
            inventory = cursor.fetchall()
            for table, engine in inventory:
                if not NAME.fullmatch(table) or engine != "InnoDB":
                    raise ValueError("Unsupported backup table")
                cursor.execute(f"SHOW CREATE TABLE `{table}`")
                create_sql = cursor.fetchone()[1]
                cursor.execute(f"SELECT * FROM `{table}`")
                columns = [column[0] for column in cursor.description]
                if not all(NAME.fullmatch(column) for column in columns):
                    raise ValueError("Unsupported backup column")
                rows = [[encode_value(value) for value in row] for row in cursor.fetchall()]
                tables[table] = {"create_sql": create_sql, "columns": columns, "rows": rows}
        return {
            "schema_version": BACKUP_V1,
            "project": "StudentMentalHealthAI",
            "synthetic_only": True,
            "workspace_id": marker["workspace_id"],
            "database": marker["database"],
            "port": marker["port"],
            "revision": revision,
            "tables": tables,
        }
    finally:
        connection.rollback()


def backup(workspace: Path, repo: Path) -> dict:
    runtime = load_runtime(workspace, repo, purpose=RUNTIME_PURPOSE_BACKUP)
    revision = runtime.get("schema_revision") if isinstance(runtime, dict) else None
    if (
        not isinstance(runtime, dict)
        or runtime.get("purpose") != RUNTIME_PURPOSE_BACKUP
        or runtime.get("scope") != BACKUP_NOT_APPLICATION_READY
        or type(revision) is not str
        or revision not in SUPPORTED_BACKUP_REVISIONS
    ):
        raise ValueError("Verified backup preflight metadata required")
    binding = {
        "workspace_id": runtime.get("workspace_id"),
        "database": runtime.get("database"),
        "port": runtime.get("port"),
        "data_directory": runtime.get("data_directory"),
    }
    if _marker_binding(binding) != binding:
        raise ValueError("Verified backup workspace identity required")
    marker = validate_marker(workspace, repo)
    verify_process(marker)
    if _marker_binding(marker) != binding:
        raise ValueError("Backup workspace identity changed")
    private = read_private(workspace / "runtime.private.dpapi")
    if not isinstance(private, dict) or any(
        type(private.get(name)) is not str
        or type(os.environ.get(name)) is not str
        or private[name] != os.environ[name]
        for name in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")
    ):
        raise ValueError("Sealed runtime settings changed after preflight")
    key_container = (workspace / "database-keys.private.dpapi").read_bytes()
    if not _valid_key_container(key_container):
        raise ValueError("DPAPI key-container header required")
    import pymysql

    connection = pymysql.connect(
        host="127.0.0.1", port=binding["port"], database=binding["database"],
        user=private["DB_USER"], password=private["DB_PASSWORD"],
        autocommit=False, connect_timeout=10, read_timeout=30,
    )
    try:
        content = package_snapshot(
            snapshot(
                connection,
                marker,
                expected_revision=revision,
                expected_binding=binding,
            ),
            key_container,
        )
    finally:
        connection.close()
    target_dir = workspace / "backups"
    target_dir.mkdir(exist_ok=True)
    if target_dir.resolve().parent != workspace.resolve() or target_dir.is_symlink():
        raise ValueError("Owned backup directory required")
    filename = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-") + uuid4().hex + ".private.dpapi"
    target = target_dir / filename
    write_private(target, content, exclusive=True)
    restored = read_private(target)
    validate_backup_package(restored)
    if restored != content:
        raise ValueError("Sealed backup readback failed")
    return {
        "backup": "SEALED_AND_READBACK_VERIFIED",
        "revision": content["revision"],
        "schema_revision": content["revision"],
        "purpose": RUNTIME_PURPOSE_BACKUP,
        "scope": BACKUP_NOT_APPLICATION_READY,
        "table_count": len(content["tables"]),
        "path": str(target),
        "recovery_scope": RECOVERY_SCOPE,
        "target_policy": TARGET_POLICY,
        "auth_session_policy": AUTH_SESSION_POLICY,
        "restore_workflow": "not yet verified",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    for path in (repo / "11_database" / ".venv" / "Lib" / "site-packages",
                 repo / "11_database", repo / "09_backend" / "src"):
        sys.path.insert(0, str(path))
    try:
        print(json.dumps(backup(args.workspace, repo)))
        return 0
    except Exception as exc:  # noqa: BLE001 - never print credential-bearing exceptions.
        print(json.dumps({"backup": "FAIL", "error_type": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
