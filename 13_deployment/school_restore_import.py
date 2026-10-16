"""Import a validated synthetic snapshot into a verified empty restore schema.

This library does not create targets, execute archived DDL, change grants or
publish readiness. The launcher must exclusively own a newly created workspace
and hold its restore lock before calling it. All application inserts use one
transaction with foreign keys enabled; existing business rows are rejected.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from school_backup import encode_value
from school_restore_plan import plan_restore, trusted_manifest
from school_schema import (
    INDEPENDENT_EDUCATION_REVIEW_REVISION,
    LEGACY_SCHOOL_SNAPSHOT_REVISION,
    RESEARCH_EDUCATION_INPUT_REVIEW_CONTINUATION_REVISION,
    RESEARCH_EDUCATION_OUTPUT_REVIEW_REVISION,
)

SUPPORTED_REVISION = LEGACY_SCHOOL_SNAPSHOT_REVISION


class RestoreImportError(RuntimeError):
    """Redacted restore failure; preserve the isolated target for inspection."""


def _ordered_snapshot_rows(plan: dict):
    """Yield continuation rows in FK-safe order without disabling constraints."""
    round_one_jobs = []
    continuation_snapshot = (
        plan.get("revision")
        in {
            RESEARCH_EDUCATION_INPUT_REVIEW_CONTINUATION_REVISION,
            RESEARCH_EDUCATION_OUTPUT_REVIEW_REVISION,
            INDEPENDENT_EDUCATION_REVIEW_REVISION,
        }
    )
    job_table = "school_research_education_jobs"
    review_table = "school_research_education_input_reviews"
    review_event_table = "school_research_education_input_review_events"
    jobs_seen = False
    reviews_seen = False
    review_events_seen = False
    for name in plan["table_order"]:
        rows = plan["tables"][name]["rows"]
        if continuation_snapshot and name == job_table:
            jobs_seen = True
            columns = plan["tables"][name]["columns"]
            if "generation_round" not in columns:
                raise RestoreImportError("Continuation snapshot job layout is invalid")
            round_index = columns.index("generation_round")
            for row in rows:
                if type(row[round_index]) is not int or row[round_index] not in {0, 1}:
                    raise RestoreImportError("Continuation snapshot job round is invalid")
                if row[round_index] == 0:
                    yield name, row
                else:
                    round_one_jobs.append((name, row))
            continue
        if continuation_snapshot and name == review_table:
            reviews_seen = True
            for row in rows:
                yield name, row
            continue
        if continuation_snapshot and name == review_event_table:
            review_events_seen = True
            for row in rows:
                yield name, row
            yield from round_one_jobs
            round_one_jobs.clear()
            continue
        for row in rows:
            yield name, row
    if continuation_snapshot and (
        not jobs_seen or not reviews_seen or not review_events_seen or round_one_jobs
    ):
        raise RestoreImportError("Continuation snapshot row ordering is incomplete")


def validate_target_marker(target: dict, package: dict) -> None:
    """Require a distinct provisioned restore target, never the source workspace."""
    if (
        target.get("schema_version") != "psynova.synthetic-restore-target.v1"
        or target.get("synthetic_only") is not True
        or target.get("phase") != "SCHEMA_READY"
        or target.get("database") != "smhai_school_demo"
        or target.get("host") != "127.0.0.1"
        or not isinstance(target.get("port"), int)
        or isinstance(target.get("port"), bool)
        or not 3309 <= target["port"] <= 3399
        or target["port"] == package.get("port")
        or not isinstance(target.get("workspace_id"), str)
        or not target["workspace_id"]
        or target["workspace_id"] == package.get("workspace_id")
        or target.get("source_workspace_id") != package.get("workspace_id")
    ):
        raise RestoreImportError("Distinct provisioned synthetic restore target required")
    root = Path(target.get("workspace", ""))
    directory = Path(target.get("data_directory", ""))
    if not root.is_absolute() or directory != root / "mysql-data":
        raise RestoreImportError("Owned restore data directory required")


def import_snapshot(connection, package: dict, target: dict, *, restored_at: datetime) -> dict:
    """Validate the empty live target, insert and verify, then commit once.

    No app service may write to this target during import. The source snapshot
    and source database are never modified. SQL driver messages and row contents
    are intentionally omitted from exceptions and returned evidence.
    """
    plan = plan_restore(package, restored_at=restored_at)
    validate_target_marker(target, package)
    manifest = trusted_manifest(plan["revision"])
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT DATABASE(), @@port, @@datadir, @@session.foreign_key_checks")
            identity = cursor.fetchone()
            if (
                not identity or len(identity) != 4
                or identity[0] != target["database"] or identity[1] != target["port"]
                or Path(identity[2]).resolve() != Path(target["data_directory"]).resolve()
                or identity[3] != 1
            ):
                raise RestoreImportError("Live restore target identity or foreign keys do not match")
            cursor.execute(
                "SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE'"
            )
            inventory = cursor.fetchall()
            if {row[0] for row in inventory} != set(manifest) or any(
                row[1] != "InnoDB" for row in inventory
            ):
                raise RestoreImportError("Live restore table inventory does not match")
            cursor.execute(
                "SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME, ORDINAL_POSITION"
            )
            live_columns: dict[str, list[str]] = {}
            for table, column in cursor.fetchall():
                live_columns.setdefault(table, []).append(column)
            if set(live_columns) != set(manifest) or any(
                set(live_columns[name]) != set(columns) or len(live_columns[name]) != len(columns)
                for name, columns in manifest.items()
            ):
                raise RestoreImportError("Live restore column manifest does not match")
            cursor.execute("SELECT version_num FROM database_alembic_version")
            if list(cursor.fetchall()) != [(plan["revision"],)]:
                raise RestoreImportError("Pinned restore schema revision required")
            for name in plan["table_order"]:
                cursor.execute(f"SELECT COUNT(*) FROM `{name}`")
                if cursor.fetchone()[0] != 0:
                    raise RestoreImportError("Restore target contains existing business rows")

            # The launcher supplies autocommit=False. Explicit BEGIN also keeps
            # inserts atomic if a caller supplied an autocommit connection.
            cursor.execute("START TRANSACTION")
            for name, row in _ordered_snapshot_rows(plan):
                table = plan["tables"][name]
                columns = table["columns"]
                names = ", ".join(f"`{column}`" for column in columns)
                placeholders = ", ".join("%s" for _ in columns)
                statement = f"INSERT INTO `{name}` ({names}) VALUES ({placeholders})"
                cursor.execute(statement, tuple(row))
            for name, expected in plan["row_counts"].items():
                cursor.execute(f"SELECT COUNT(*) FROM `{name}`")
                if cursor.fetchone()[0] != expected:
                    raise RestoreImportError("Restored row counts do not match")
                table = plan["tables"][name]
                names = ", ".join(f"`{column}`" for column in table["columns"])
                cursor.execute(f"SELECT {names} FROM `{name}`")

                def canonical_rows(rows):
                    return sorted(
                        json.dumps([encode_value(value) for value in row], sort_keys=True,
                                   ensure_ascii=True, separators=(",", ":"))
                        for row in rows
                    )

                if canonical_rows(cursor.fetchall()) != canonical_rows(table["rows"]):
                    raise RestoreImportError("Restored stored values do not match the import plan")
            cursor.execute("SELECT COUNT(*) FROM auth_sessions WHERE revoked_at IS NULL")
            if cursor.fetchone()[0] != 0:
                raise RestoreImportError("Imported authentication sessions must be revoked")
        connection.commit()
    except Exception as exc:
        try:
            connection.rollback()
        except Exception:  # noqa: BLE001 - retain the redacted primary failure.
            raise RestoreImportError("Restore failed; rollback could not be confirmed") from None
        if isinstance(exc, RestoreImportError):
            raise exc from None
        raise RestoreImportError(f"Restore import failed ({type(exc).__name__})") from None
    return {
        "status": "IMPORTED_REQUIRES_FINAL_VALIDATION", "revision": plan["revision"],
        "table_count": len(plan["table_order"]),
        "row_count": sum(plan["row_counts"].values()),
        "revoked_session_count": plan["revoked_session_count"],
        "ready": False,
    }
