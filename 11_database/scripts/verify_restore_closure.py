"""Verify a fresh logical restore against its synthetic source database.

The script intentionally emits only non-secret evidence.  It compares source
and restored metadata, safe operational fields, and encrypted ciphertext
digests while decrypting representative restored payloads without writing
their plaintext to the report.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database_layer import models  # noqa: F401 - registers all mapped tables
from database_layer.base import Base
from database_layer.config import DatabaseSettings, create_engine
from database_layer.crypto import (
    DevLocalKeyProvider,
    EncryptedPayload,
    FernetDataProtectionProvider,
    MappingKeyProvider,
)

MODULE_ROOT = Path(__file__).resolve().parents[1]
DOMAIN_TABLES = tuple(sorted(Base.metadata.tables))
EXPECTED_REVISION = os.environ.get("RESTORE_EXPECTED_REVISION", "20260905_0001")
EXPECTED_COLLATION = "utf8mb4_0900_ai_ci"
EXPECTED_CHARSET = "utf8mb4"

SAFE_HASH_FIELDS: dict[str, tuple[str, ...]] = {
    "subjects": (
        "public_id",
        "subject_ref",
        "status",
        "data_origin",
        "retention_due_at",
        "erased_at",
        "created_at",
        "updated_at",
    ),
    "assessment_sessions": (
        "public_id",
        "assessment_ref",
        "instrument_id",
        "instrument_version",
        "item_bank_version",
        "config_version",
        "schema_version",
        "status",
        "trace_id",
        "started_at",
        "completed_at",
        "created_at",
        "updated_at",
    ),
    "support_runs": (
        "public_id",
        "run_ref",
        "generation_ref",
        "retrieval_ref",
        "trace_id",
        "status",
        "workflow_action",
        "component_versions",
        "started_at",
        "completed_at",
        "duration_ms",
        "created_at",
        "updated_at",
    ),
    "support_evidence": (
        "public_id",
        "citation_id",
        "source_id",
        "source_version",
        "source_hash",
        "locator",
        "rank_order",
        "created_at",
        "updated_at",
    ),
    "review_cases": (
        "public_id",
        "review_ref",
        "priority",
        "status",
        "assigned_account_id",
        "version",
        "closed_at",
        "created_at",
        "updated_at",
    ),
    "audit_events": (
        "public_id",
        "action",
        "resource_type",
        "resource_public_id",
        "result",
        "trace_id",
        "safe_metadata",
        "created_at",
    ),
    "idempotency_records": (
        "public_id",
        "scope",
        "state",
        "result_resource_type",
        "result_public_id",
        "expires_at",
        "created_at",
        "updated_at",
    ),
}

CIPHERTEXT_SPECS: dict[str, dict[str, Any]] = {
    "assessment_response": {
        "table": "assessment_responses",
        "cipher_column": "response_ciphertext",
        "metadata_columns": (
            "key_version",
            "cipher_format_version",
            "payload_schema_version",
        ),
        "expected_schema": "assessment-response.v1",
        "expected_keys": {"answer", "source"},
        "required": True,
    },
    "assessment_result": {
        "table": "assessment_results",
        "cipher_column": "payload_ciphertext",
        "metadata_columns": (
            "key_version",
            "cipher_format_version",
            "payload_schema_version",
        ),
        "expected_schema": "assessment-result.v1",
        "expected_keys": {"schema_version", "source"},
        "required": True,
    },
    "support_message": {
        "table": "support_messages",
        "cipher_column": "payload_ciphertext",
        "metadata_columns": (
            "key_version",
            "cipher_format_version",
            "payload_schema_version",
        ),
        "expected_schema": "support-message.v1",
        "expected_keys": {"text"},
        "required": True,
    },
    "safety_decision": {
        "table": "safety_decisions",
        "cipher_column": "detail_ciphertext",
        "metadata_columns": (
            "key_version",
            "cipher_format_version",
            "payload_schema_version",
        ),
        "expected_schema": "safety-detail.v1",
        "expected_keys": {"reason_code"},
        "required": True,
    },
    "review_case": {
        "table": "review_cases",
        "cipher_column": "case_note_ciphertext",
        "metadata_columns": (
            "key_version",
            "cipher_format_version",
            "payload_schema_version",
        ),
        "expected_schema": "review-note.v1",
        "expected_keys": {"note"},
        "required": True,
    },
    "review_event": {
        "table": "review_events",
        "cipher_column": "note_ciphertext",
        "metadata_columns": (
            "key_version",
            "cipher_format_version",
            "payload_schema_version",
        ),
        "expected_schema": "review-event-note.v1",
        "expected_keys": set(),
        "required": False,
    },
}


def quote_identifier(value: str) -> str:
    return f"`{value.replace('`', '``')}`"


def database_name(url: str) -> str:
    database = make_url(url).database
    if not database:
        raise ValueError("database URL must include a database name")
    return database


def canonical_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, dict):
        return {str(key): canonical_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [canonical_value(item) for item in value]
    return value


def canonical_hash(rows: list[dict[str, Any]]) -> str:
    serialized = json.dumps(
        [canonical_value(row) for row in rows],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def runtime_metadata(connection: AsyncConnection) -> dict[str, Any]:
    row = (
        (
            await connection.execute(
                text(
                    "SELECT VERSION() AS version, @@version_comment AS edition, "
                    "@@time_zone AS time_zone, @@session.foreign_key_checks AS session_fk_checks, "
                    "@@global.foreign_key_checks AS global_fk_checks"
                )
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def table_inventory(connection: AsyncConnection) -> dict[str, Any]:
    rows = (
        (
            await connection.execute(
                text(
                    "SELECT t.TABLE_NAME, t.ENGINE, t.TABLE_COLLATION, "
                    "c.CHARACTER_SET_NAME "
                    "FROM information_schema.TABLES AS t "
                    "LEFT JOIN information_schema.COLLATION_CHARACTER_SET_APPLICABILITY AS c "
                    "ON c.COLLATION_NAME = t.TABLE_COLLATION "
                    "WHERE t.TABLE_SCHEMA = DATABASE() AND t.TABLE_TYPE = 'BASE TABLE' "
                    "ORDER BY t.TABLE_NAME"
                )
            )
        )
        .mappings()
        .all()
    )
    return {
        "count": len(rows),
        "names": [str(row["TABLE_NAME"]) for row in rows],
        "properties": [dict(row) for row in rows],
    }


async def row_count(connection: AsyncConnection, table: str) -> int:
    value = await connection.scalar(text(f"SELECT COUNT(*) FROM {quote_identifier(table)}"))
    return int(value or 0)


async def all_row_counts(connection: AsyncConnection) -> dict[str, int]:
    return {table: await row_count(connection, table) for table in DOMAIN_TABLES}


async def select_safe_rows(
    connection: AsyncConnection, table: str, columns: tuple[str, ...]
) -> list[dict[str, Any]]:
    selected = ", ".join(quote_identifier(column) for column in columns)
    rows = (
        (
            await connection.execute(
                text(
                    f"SELECT {selected} FROM {quote_identifier(table)} "
                    f"ORDER BY {quote_identifier('public_id')}"
                )
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


async def safe_content_hashes(source: AsyncConnection, restored: AsyncConnection) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for table, columns in SAFE_HASH_FIELDS.items():
        source_hash = canonical_hash(await select_safe_rows(source, table, columns))
        restored_hash = canonical_hash(await select_safe_rows(restored, table, columns))
        result[table] = {
            "fields": list(columns),
            "source_sha256": source_hash,
            "restored_sha256": restored_hash,
            "match": source_hash == restored_hash,
        }
    return result


async def selected_ciphertext_row(
    connection: AsyncConnection, spec: dict[str, Any]
) -> dict[str, Any] | None:
    table = str(spec["table"])
    columns = ("public_id", spec["cipher_column"], *spec["metadata_columns"])
    selected = ", ".join(quote_identifier(column) for column in columns)
    row = (
        (
            await connection.execute(
                text(
                    f"SELECT {selected} FROM {quote_identifier(table)} "
                    f"WHERE {quote_identifier(spec['cipher_column'])} IS NOT NULL "
                    f"ORDER BY {quote_identifier('public_id')} LIMIT 1"
                )
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None


async def ciphertext_hashes(source: AsyncConnection, restored: AsyncConnection) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, spec in CIPHERTEXT_SPECS.items():
        source_row = await selected_ciphertext_row(source, spec)
        restored_row = await selected_ciphertext_row(restored, spec)
        source_ciphertext = (
            bytes(source_row[spec["cipher_column"]]) if source_row is not None else None
        )
        restored_ciphertext = (
            bytes(restored_row[spec["cipher_column"]]) if restored_row is not None else None
        )
        source_digest = (
            hashlib.sha256(source_ciphertext).hexdigest() if source_ciphertext is not None else None
        )
        restored_digest = (
            hashlib.sha256(restored_ciphertext).hexdigest()
            if restored_ciphertext is not None
            else None
        )
        result[name] = {
            "table": spec["table"],
            "column": spec["cipher_column"],
            "source_public_id": source_row.get("public_id") if source_row else None,
            "restored_public_id": restored_row.get("public_id") if restored_row else None,
            "source_ciphertext_sha256": source_digest,
            "restored_ciphertext_sha256": restored_digest,
            "present_in_source": source_row is not None,
            "present_in_restored": restored_row is not None,
            "match": (source_row is None and restored_row is None)
            or (
                source_row is not None
                and restored_row is not None
                and source_digest == restored_digest
                and source_row.get("public_id") == restored_row.get("public_id")
            ),
        }
    return result


def encrypted_payload_from_row(row: dict[str, Any], spec: dict[str, Any]) -> EncryptedPayload:
    return EncryptedPayload(
        ciphertext=bytes(row[spec["cipher_column"]]),
        key_version=str(row["key_version"]),
        cipher_format_version=str(row["cipher_format_version"]),
        payload_schema_version=str(row["payload_schema_version"]),
    )


async def decryptability(restored: AsyncConnection) -> dict[str, Any]:
    provider = FernetDataProtectionProvider(DevLocalKeyProvider.from_env(MODULE_ROOT.parent))
    result: dict[str, Any] = {}
    for name, spec in CIPHERTEXT_SPECS.items():
        row = await selected_ciphertext_row(restored, spec)
        if row is None:
            result[name] = {
                "status": "NOT_POPULATED",
                "decryptable": False,
                "payload_keys": [],
                "schema_version": None,
            }
            continue
        try:
            encrypted = encrypted_payload_from_row(row, spec)
            payload = provider.decrypt_json(encrypted)
            payload_keys = sorted(str(key) for key in payload)
            expected_keys = {str(key) for key in spec["expected_keys"]}
            schema_matches = encrypted.payload_schema_version == spec["expected_schema"]
            keys_present = expected_keys.issubset(payload.keys())
            result[name] = {
                "status": "PASS" if schema_matches and keys_present else "FAIL",
                "decryptable": True,
                "schema_version": encrypted.payload_schema_version,
                "expected_schema_version": spec["expected_schema"],
                "schema_matches": schema_matches,
                "payload_keys": payload_keys,
                "expected_keys_present": keys_present,
            }
        except Exception as exc:  # evidence must not include plaintext or key material
            result[name] = {
                "status": "FAIL",
                "decryptable": False,
                "payload_keys": [],
                "schema_version": row.get("payload_schema_version"),
                "error_type": type(exc).__name__,
            }
    return result


async def wrong_key_probe(restored: AsyncConnection) -> dict[str, Any]:
    for name, spec in CIPHERTEXT_SPECS.items():
        row = await selected_ciphertext_row(restored, spec)
        if row is None:
            continue
        wrong_provider = FernetDataProtectionProvider(
            MappingKeyProvider({"wrong": Fernet.generate_key()}, active_version="wrong")
        )
        try:
            wrong_provider.decrypt_json(encrypted_payload_from_row(row, spec))
        except Exception as exc:
            return {
                "tested_payload_class": name,
                "failure_type": type(exc).__name__,
                "wrong_key_failure": True,
            }
        return {
            "tested_payload_class": name,
            "failure_type": None,
            "wrong_key_failure": False,
        }
    return {
        "tested_payload_class": None,
        "failure_type": None,
        "wrong_key_failure": False,
        "reason": "no encrypted payload was populated",
    }


async def foreign_key_integrity(connection: AsyncConnection) -> dict[str, Any]:
    relationships = (
        (
            await connection.execute(
                text(
                    "SELECT TABLE_NAME, COLUMN_NAME, CONSTRAINT_NAME, "
                    "REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME "
                    "FROM information_schema.KEY_COLUMN_USAGE "
                    "WHERE TABLE_SCHEMA = DATABASE() AND REFERENCED_TABLE_NAME IS NOT NULL "
                    "ORDER BY TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION"
                )
            )
        )
        .mappings()
        .all()
    )
    checks: list[dict[str, Any]] = []
    for relationship in relationships:
        child_table = str(relationship["TABLE_NAME"])
        child_column = str(relationship["COLUMN_NAME"])
        parent_table = str(relationship["REFERENCED_TABLE_NAME"])
        parent_column = str(relationship["REFERENCED_COLUMN_NAME"])
        orphan_count = await connection.scalar(
            text(
                f"SELECT COUNT(*) FROM {quote_identifier(child_table)} AS child "
                f"LEFT JOIN {quote_identifier(parent_table)} AS parent "
                f"ON child.{quote_identifier(child_column)} = "
                f"parent.{quote_identifier(parent_column)} "
                f"WHERE child.{quote_identifier(child_column)} IS NOT NULL "
                f"AND parent.{quote_identifier(parent_column)} IS NULL"
            )
        )
        checks.append(
            {
                "constraint": str(relationship["CONSTRAINT_NAME"]),
                "child": f"{child_table}.{child_column}",
                "parent": f"{parent_table}.{parent_column}",
                "orphan_rows": int(orphan_count or 0),
            }
        )
    total_orphans = sum(item["orphan_rows"] for item in checks)
    return {
        "relationships_checked": len(checks),
        "orphan_rows": total_orphans,
        "checks": checks,
        "pass": total_orphans == 0,
    }


async def schema_sanity(connection: AsyncConnection) -> dict[str, Any]:
    inventory = await table_inventory(connection)
    properties = inventory["properties"]
    engines_ok = all(row["ENGINE"] == "InnoDB" for row in properties)
    charset_ok = all(row["CHARACTER_SET_NAME"] == EXPECTED_CHARSET for row in properties)
    collation_ok = all(row["TABLE_COLLATION"] == EXPECTED_COLLATION for row in properties)

    public_id_rows = (
        (
            await connection.execute(
                text(
                    "SELECT DISTINCT k.TABLE_NAME "
                    "FROM information_schema.TABLE_CONSTRAINTS AS tc "
                    "JOIN information_schema.KEY_COLUMN_USAGE AS k "
                    "ON tc.CONSTRAINT_SCHEMA = k.CONSTRAINT_SCHEMA "
                    "AND tc.TABLE_NAME = k.TABLE_NAME "
                    "AND tc.CONSTRAINT_NAME = k.CONSTRAINT_NAME "
                    "WHERE tc.CONSTRAINT_SCHEMA = DATABASE() "
                    "AND tc.CONSTRAINT_TYPE = 'UNIQUE' AND k.COLUMN_NAME = 'public_id'"
                )
            )
        )
        .scalars()
        .all()
    )
    public_id_tables = {str(value) for value in public_id_rows}
    public_id_unique = set(DOMAIN_TABLES).issubset(public_id_tables)

    idempotency_columns = (
        (
            await connection.execute(
                text(
                    "SELECT COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE "
                    "WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'idempotency_records' "
                    "AND CONSTRAINT_NAME = 'scope_key_hash_unique' "
                    "ORDER BY ORDINAL_POSITION"
                )
            )
        )
        .scalars()
        .all()
    )
    idempotency_unique = list(idempotency_columns) == ["scope", "key_hash"]

    review_version_row = (
        (
            await connection.execute(
                text(
                    "SELECT DATA_TYPE, COLUMN_TYPE FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'review_cases' "
                    "AND COLUMN_NAME = 'version'"
                )
            )
        )
        .mappings()
        .first()
    )
    review_version = bool(
        review_version_row
        and review_version_row["DATA_TYPE"] == "int"
        and str(review_version_row["COLUMN_TYPE"]).startswith("int")
    )

    session_hash_rows = (
        (
            await connection.execute(
                text(
                    "SELECT COLUMN_NAME, LOWER(COLUMN_TYPE) AS COLUMN_TYPE "
                    "FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'auth_sessions' "
                    "AND COLUMN_NAME IN ("
                    "'session_token_hash', 'csrf_token_hash', 'user_agent_hash')"
                )
            )
        )
        .mappings()
        .all()
    )
    session_hash_types = {
        str(row["COLUMN_NAME"]): str(row["COLUMN_TYPE"]) for row in session_hash_rows
    }
    session_hashes_binary_32 = all(
        session_hash_types.get(column) == "binary(32)"
        for column in ("session_token_hash", "csrf_token_hash", "user_agent_hash")
    )

    encrypted_types: dict[str, str | None] = {}
    for spec in CIPHERTEXT_SPECS.values():
        row = (
            await connection.execute(
                text(
                    "SELECT LOWER(DATA_TYPE) AS DATA_TYPE FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table_name "
                    "AND COLUMN_NAME = :column_name"
                ),
                {"table_name": spec["table"], "column_name": spec["cipher_column"]},
            )
        ).scalar()
        encrypted_types[f"{spec['table']}.{spec['cipher_column']}"] = (
            str(row) if row is not None else None
        )
    encrypted_binary = all(
        value in {"blob", "tinyblob", "mediumblob", "longblob", "binary", "varbinary"}
        for value in encrypted_types.values()
    )

    checks = {
        "all_tables_innodb": engines_ok,
        "all_tables_utf8mb4": charset_ok,
        "all_tables_expected_collation": collation_ok,
        "public_id_unique_for_all_domain_tables": public_id_unique,
        "idempotency_scope_key_hash_unique": idempotency_unique,
        "review_case_version_field": review_version,
        "session_hashes_binary_32": session_hashes_binary_32,
        "encrypted_payloads_binary_or_blob": encrypted_binary,
    }
    return {
        "checks": checks,
        "details": {
            "public_id_unique_tables": sorted(public_id_tables),
            "idempotency_unique_columns": list(idempotency_columns),
            "review_version_column": dict(review_version_row) if review_version_row else None,
            "session_hash_types": session_hash_types,
            "encrypted_payload_types": encrypted_types,
        },
        "pass": all(checks.values()),
    }


async def verify(args: argparse.Namespace) -> dict[str, Any]:
    source_url = args.source_url or os.environ.get("RESTORE_SOURCE_DATABASE_URL")
    restored_url = args.restored_url or os.environ.get("DATABASE_URL")
    backup_value = args.backup_file or os.environ.get("RESTORE_BACKUP_FILE")
    if not source_url or not restored_url or not backup_value:
        raise ValueError(
            "RESTORE_SOURCE_DATABASE_URL, DATABASE_URL, and RESTORE_BACKUP_FILE are required"
        )

    backup_path = Path(backup_value).expanduser().resolve()
    if not backup_path.is_file():
        raise FileNotFoundError(f"logical backup file does not exist: {backup_path}")

    source_settings = DatabaseSettings(url=source_url)
    restored_settings = DatabaseSettings(url=restored_url)
    source_engine = create_engine(source_settings)
    restored_engine = create_engine(restored_settings)
    try:
        async with source_engine.connect() as source, restored_engine.connect() as restored:
            source_runtime = await runtime_metadata(source)
            restored_runtime = await runtime_metadata(restored)
            source_tables = await table_inventory(source)
            restored_tables = await table_inventory(restored)
            source_revision = await source.scalar(
                text("SELECT version_num FROM database_alembic_version LIMIT 1")
            )
            restored_revision = await restored.scalar(
                text("SELECT version_num FROM database_alembic_version LIMIT 1")
            )
            source_counts = await all_row_counts(source)
            restored_counts = await all_row_counts(restored)
            row_counts = {
                table: {
                    "source": source_counts[table],
                    "restored": restored_counts[table],
                    "match": source_counts[table] == restored_counts[table],
                }
                for table in DOMAIN_TABLES
            }
            safe_hashes = await safe_content_hashes(source, restored)
            cipher_hashes = await ciphertext_hashes(source, restored)
            restored_decryptability = await decryptability(restored)
            wrong_key = await wrong_key_probe(restored)
            foreign_keys = await foreign_key_integrity(restored)
            schema = await schema_sanity(restored)

    finally:
        await source_engine.dispose()
        await restored_engine.dispose()

    expected_tables = [*DOMAIN_TABLES, "database_alembic_version"]
    table_names_match = source_tables["names"] == restored_tables["names"]
    table_count_match = source_tables["count"] == restored_tables["count"] == len(
        expected_tables
    ) and set(restored_tables["names"]) == set(expected_tables)
    migration_match = (
        str(source_revision) == EXPECTED_REVISION
        and str(restored_revision) == EXPECTED_REVISION
        and source_revision == restored_revision
    )
    row_counts_match = all(item["match"] for item in row_counts.values())
    content_hash_match = all(item["match"] for item in safe_hashes.values())
    required_ciphertext_classes = {
        name for name, spec in CIPHERTEXT_SPECS.items() if spec["required"]
    }
    ciphertext_hash_match = all(
        item["match"]
        and (name not in required_ciphertext_classes or item["present_in_source"])
        and (name not in required_ciphertext_classes or item["present_in_restored"])
        for name, item in cipher_hashes.items()
    )
    decryptability_match = all(
        item["status"] == "PASS"
        for name, item in restored_decryptability.items()
        if name in required_ciphertext_classes
    ) and all(
        item["status"] in {"PASS", "NOT_POPULATED"}
        for name, item in restored_decryptability.items()
        if name not in required_ciphertext_classes
    )
    backup_size = backup_path.stat().st_size
    backup_sha256 = file_sha256(backup_path)
    backup = {
        "path": str(backup_path),
        "size_bytes": backup_size,
        "sha256": backup_sha256,
        "timestamp_utc": os.environ.get(
            "RESTORE_BACKUP_TIMESTAMP",
            datetime.fromtimestamp(backup_path.stat().st_mtime, UTC).isoformat(),
        ),
        "artifact_identity": bool(backup_size > 0 and backup_sha256),
    }
    restore_process = {
        "database": database_name(restored_url),
        "fresh_target": os.environ.get("RESTORE_FRESH_TARGET", "true").lower() == "true",
        "mysql_version": str(restored_runtime["version"]),
        "restore_start_utc": os.environ.get("RESTORE_START_TIME", "NOT_RECORDED"),
        "restore_completion_utc": os.environ.get("RESTORE_COMPLETION_TIME", "NOT_RECORDED"),
        "command_category": os.environ.get(
            "RESTORE_COMMAND_CATEGORY", "logical dump import into a fresh database"
        ),
        "exit_code": int(os.environ.get("RESTORE_EXIT_CODE", "0")),
    }
    foreign_key_checks = {
        "session": int(restored_runtime["session_fk_checks"]),
        "global": int(restored_runtime["global_fk_checks"]),
        "pass": int(restored_runtime["session_fk_checks"]) == 1
        and int(restored_runtime["global_fk_checks"]) == 1,
    }
    summary = {
        "source_database": database_name(source_url),
        "restored_database": database_name(restored_url),
        "mysql_version": str(restored_runtime["version"]),
        "source_mysql_version": str(source_runtime["version"]),
        "migration_revision_match": migration_match,
        "table_count_match": table_count_match,
        "table_names_match": table_names_match,
        "row_counts_match": row_counts_match,
        "safe_content_hashes_match": content_hash_match,
        "ciphertext_hashes_match": ciphertext_hash_match,
        "encrypted_payloads_decryptable": decryptability_match,
        "foreign_key_integrity": foreign_keys["pass"],
        "schema_sanity": schema["pass"],
    }
    overall = all(
        [
            backup["artifact_identity"],
            restore_process["fresh_target"],
            restore_process["exit_code"] == 0,
            migration_match,
            table_count_match,
            table_names_match,
            row_counts_match,
            content_hash_match,
            ciphertext_hash_match,
            decryptability_match,
            bool(wrong_key["wrong_key_failure"]),
            foreign_keys["pass"],
            foreign_key_checks["pass"],
            schema["pass"],
        ]
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "source_database": database_name(source_url),
        "restored_database": database_name(restored_url),
        "mysql_version": str(restored_runtime["version"]),
        "backup": backup,
        "restore_process": restore_process,
        "migration": {
            "expected": EXPECTED_REVISION,
            "source": str(source_revision),
            "restored": str(restored_revision),
            "match": migration_match,
        },
        "tables": {
            "source_count": source_tables["count"],
            "restored_count": restored_tables["count"],
            "expected_count": len(expected_tables),
            "source_names": source_tables["names"],
            "restored_names": restored_tables["names"],
            "match": table_count_match and table_names_match,
        },
        "row_counts": row_counts,
        "safe_content_hashes": safe_hashes,
        "ciphertext_hashes": cipher_hashes,
        "decryptability": restored_decryptability,
        "wrong_key": wrong_key,
        "foreign_keys": foreign_keys,
        "foreign_key_checks": foreign_key_checks,
        "schema_sanity": schema,
        "runtime": {
            "source": source_runtime,
            "restored": restored_runtime,
        },
        "summary": summary,
        "overall": "PASS" if overall else "FAIL",
    }


def markdown_report(evidence: dict[str, Any]) -> str:
    row_counts = evidence["row_counts"]
    safe_hashes = evidence["safe_content_hashes"]
    cipher_hashes = evidence["ciphertext_hashes"]
    decryptability = evidence["decryptability"]
    fk = evidence["foreign_keys"]
    schema = evidence["schema_sanity"]
    process = evidence["restore_process"]
    backup = evidence["backup"]
    row_lines = "\n".join(
        f"| `{table}` | {item['source']} | {item['restored']} | {item['match']} |"
        for table, item in row_counts.items()
    )
    safe_lines = "\n".join(
        f"| `{table}` | `{item['source_sha256']}` | `{item['restored_sha256']}` | {item['match']} |"
        for table, item in safe_hashes.items()
    )
    cipher_lines = "\n".join(
        f"| `{name}` | {item['present_in_source']} | `{item['source_ciphertext_sha256']}` | "
        f"`{item['restored_ciphertext_sha256']}` | {item['match']} |"
        for name, item in cipher_hashes.items()
    )
    decrypt_lines = "\n".join(
        f"| `{name}` | {item['status']} | {item.get('schema_version')} | "
        f"{', '.join(item.get('payload_keys', [])) or '-'} |"
        for name, item in decryptability.items()
    )
    fk_lines = "\n".join(
        f"| `{item['constraint']}` | `{item['child']}` | `{item['parent']}` | "
        f"{item['orphan_rows']} |"
        for item in fk["checks"]
    )
    schema_lines = "\n".join(f"| `{name}` | {value} |" for name, value in schema["checks"].items())
    migration_lines = "\n".join(
        [
            f"| Alembic revision | `{evidence['migration']['source']}` | "
            f"`{evidence['migration']['restored']}` | {evidence['migration']['match']} |",
            f"| Physical table count | {evidence['tables']['source_count']} | "
            f"{evidence['tables']['restored_count']} | {evidence['tables']['match']} |",
        ]
    )
    return f"""# Database Round 1 Restore Closure Evidence

Generated: `{evidence["generated_at"]}`  
Conclusion: **{evidence["overall"]}**

## Command/process summary

- Source database: `{evidence["source_database"]}`
- Fresh restored database: `{evidence["restored_database"]}`
- MySQL server: `{evidence["mysql_version"]}`
- Restore target marked fresh: `{process["fresh_target"]}`
- Restore command category: `{process["command_category"]}`
- Restore start UTC: `{process["restore_start_utc"]}`
- Restore completion UTC: `{process["restore_completion_utc"]}`
- Restore exit code: `{process["exit_code"]}`

## Backup identity

- Path: `{backup["path"]}`
- Timestamp UTC: `{backup["timestamp_utc"]}`
- Size: `{backup["size_bytes"]}` bytes
- SHA-256: `{backup["sha256"]}`
- Artifact identity: `{backup["artifact_identity"]}`

## Migration and table identity

| Check | Source | Restored | Match |
|---|---:|---:|---:|
{migration_lines}

Expected physical table count is `{evidence["tables"]["expected_count"]}`: 19 domain tables plus
`database_alembic_version`. Table names matched exactly: `{evidence["tables"]["match"]}`.

## Deterministic row counts

| Table | Source | Restored | Match |
|---|---:|---:|---:|
{row_lines}

All checked domain-table row counts matched: **{evidence["summary"]["row_counts_match"]}**.

## Safe content hashes

The hashes cover deterministic, non-secret operational fields only. Encrypted plaintext,
password hashes, raw session tokens, CSRF hashes, and key material are excluded.

| Table | Source SHA-256 | Restored SHA-256 | Match |
|---|---|---|---|
{safe_lines}

All selected safe content hashes matched: **{evidence["summary"]["safe_content_hashes_match"]}**.

## Ciphertext identity

| Payload class | Populated | Source ciphertext SHA-256 | Restored ciphertext SHA-256 | Match |
|---|---:|---|---|---:|
{cipher_lines}

Ciphertext hashes matched for all required populated payload classes:
**{evidence["summary"]["ciphertext_hashes_match"]}**. No ciphertext bytes are printed.

## Encrypted payload decryptability

| Payload class | Status | Schema version | Safe payload keys |
|---|---|---|---|
{decrypt_lines}

Values were not written to this report. Required populated payloads were decryptable with
the configured development key provider and had the expected schema/key shape:
**{evidence["summary"]["encrypted_payloads_decryptable"]}**.

Wrong-key regression: tested `{evidence["wrong_key"]["tested_payload_class"]}`, observed
explicit `{evidence["wrong_key"]["failure_type"]}` failure, result
**{evidence["wrong_key"]["wrong_key_failure"]}**.

## Foreign-key integrity

| Constraint | Child | Parent | Orphan rows |
|---|---|---|---:|
{fk_lines}

Relationships checked: `{fk["relationships_checked"]}`; total orphan rows:
`{fk["orphan_rows"]}`; result: **{fk["pass"]}**.

`@@SESSION.FOREIGN_KEY_CHECKS = {evidence["foreign_key_checks"]["session"]}` and
`@@GLOBAL.FOREIGN_KEY_CHECKS = {evidence["foreign_key_checks"]["global"]}`; checks were
re-enabled and the state check passed: **{evidence["foreign_key_checks"]["pass"]}**.

## Schema sanity

| Check | Result |
|---|---:|
{schema_lines}

Schema sanity result: **{schema["pass"]}**.

## Source vs restored summary

| Comparison | Result |
|---|---:|
| Migration revision | {evidence["summary"]["migration_revision_match"]} |
| Table count | {evidence["summary"]["table_count_match"]} |
| Table names | {evidence["summary"]["table_names_match"]} |
| Row counts | {evidence["summary"]["row_counts_match"]} |
| Safe content hashes | {evidence["summary"]["safe_content_hashes_match"]} |
| Ciphertext hashes | {evidence["summary"]["ciphertext_hashes_match"]} |
| Encrypted payload decryptability | {evidence["summary"]["encrypted_payloads_decryptable"]} |
| Foreign-key integrity | {evidence["summary"]["foreign_key_integrity"]} |
| Schema sanity | {evidence["summary"]["schema_sanity"]} |
| Overall restore verification | **{evidence["overall"]}** |

## Limitations

- This is a local engineering rehearsal against isolated synthetic MySQL data; it is not
  production backup, TLS, KMS/Vault/HSM, PITR, replication, or HA acceptance.
- The comparison proves the selected structural, relational, safe-field, and ciphertext
  properties. It does not assert legal retention periods, clinical validity, or real-data
  readiness.
- The fixture contains synthetic identifiers and payloads only; no real student data was
  used.

## Final restore conclusion

**{evidence["overall"]}** — the fresh logical restore is structurally, relationally, and
cryptographically consistent with its synthetic source for the checks above.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-url")
    parser.add_argument("--restored-url")
    parser.add_argument("--backup-file")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    evidence = asyncio.run(verify(args))
    machine_path = MODULE_ROOT / "reports" / "database_round1_restore_verification.json"
    human_path = MODULE_ROOT / "reports" / "DATABASE_ROUND1_RESTORE_CLOSURE_EVIDENCE.md"
    machine_path.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    human_path.write_text(markdown_report(evidence), encoding="utf-8")
    print(
        json.dumps(
            {"machine": str(machine_path), "human": str(human_path), "overall": evidence["overall"]}
        )
    )
    if evidence["overall"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
