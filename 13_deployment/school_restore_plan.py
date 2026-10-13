"""Pure preflight and ordering plan for synthetic school backup restoration.

This module reads trusted local SQLAlchemy metadata only. It never connects to
MySQL, creates a target, executes archived DDL, or decrypts protected content.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from school_backup import (
    SUPPORTED_BACKUP_REVISIONS,
    SUPPORTED_REVISION,
    decode_value,
    validate_backup_package,
)
from school_schema import (
    CAT_ASSETS_REVISION,
    CAT_TASK_BINDING_REVISION,
    POST_ASSESSMENT_JOB_OUTBOX_REVISION,
    PROFESSIONAL_REVIEW_REVISION,
    RESEARCH_CAT_SESSIONS_REVISION,
    SCHOOL_FEEDBACK_PUBLICATION_REVISION,
)

REVISION_TABLE = "database_alembic_version"
MODEL_TABLE_COUNT = 27
EXPECTED_MODEL_TABLES = frozenset(
    {
        "account_roles",
        "account_school_memberships",
        "accounts",
        "assessment_responses",
        "assessment_results",
        "assessment_sessions",
        "audit_events",
        "auth_sessions",
        "consent_records",
        "idempotency_records",
        "measurement_tasks",
        "membership_roles",
        "review_cases",
        "review_events",
        "roles",
        "safety_decisions",
        "school_class_students",
        "school_class_teachers",
        "school_classes",
        "schools",
        "subject_access_grants",
        "subjects",
        "support_evidence",
        "support_messages",
        "support_runs",
        "support_sessions",
        "task_enrollments",
    }
)
RECOVERY_REVOCATION_REASON = "RECOVERY_RELOGIN_REQUIRED"
DIRECTORY_TABLES = frozenset({"school_account_batches", "school_account_provisions"})
DIRECTORY_NAME_TABLES = frozenset({"schools", "school_classes", "account_school_memberships"})
PROFESSIONAL_REVIEW_TABLES = frozenset({
    "school_task_specialist_assignments", "school_professional_review_cases",
    "school_professional_review_events",
})
CAT_ASSET_TABLES = frozenset({
    "school_cat_item_banks", "school_cat_item_bank_versions",
    "school_cat_plans", "school_cat_plan_versions",
})
CAT_TASK_BINDING_TABLES = frozenset({
    "school_cat_activations", "school_cat_task_bindings", "school_cat_session_bindings",
})
CAT_TASK_BINDING_MODE_TABLES = frozenset({"measurement_tasks", "assessment_sessions"})
SCHOOL_FEEDBACK_TABLES = frozenset({"school_feedback_records", "school_feedback_events"})
POST_ASSESSMENT_JOB_TABLES = frozenset({"school_post_assessment_jobs"})
RESEARCH_PROFILE_TABLES = frozenset({"school_research_profile_versions"})
RESEARCH_BINDING_TABLES = frozenset({"school_research_task_bindings"})
RESEARCH_SESSION_TABLES = frozenset({"school_research_sessions"})
RESEARCH_CAT_TABLES = (
    RESEARCH_PROFILE_TABLES | RESEARCH_BINDING_TABLES | RESEARCH_SESSION_TABLES
)


@dataclass(frozen=True, slots=True)
class ForeignKeySpec:
    local_columns: tuple[str, ...]
    remote_table: str
    remote_columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TableSpec:
    columns: tuple[str, ...]
    nullable_columns: frozenset[str]
    primary_key: tuple[str, ...]
    foreign_keys: tuple[ForeignKeySpec, ...] = ()


def _load_trusted_tables(revision: str = SUPPORTED_REVISION) -> dict[str, TableSpec]:
    """Load and completeness-check the local revision's ORM mappings."""
    repository = Path(__file__).resolve().parents[1]
    database_root = (repository / "11_database").resolve()
    database_root_text = str(database_root)
    if database_root_text not in sys.path:
        sys.path.insert(0, database_root_text)

    try:
        from database_layer import models
        from database_layer.base import Base
    except ImportError as exc:
        raise RuntimeError("Trusted local database models are unavailable") from exc

    model_path = Path(models.__file__).resolve()
    if database_root not in model_path.parents:
        raise RuntimeError("Database models resolved outside the repository")

    metadata_tables = dict(Base.metadata.tables)
    mapped_tables = {
        mapped.__table__.name
        for mapped in vars(models).values()
        if isinstance(mapped, type)
        and getattr(mapped, "__table__", None) is not None
        and mapped.__table__.metadata is Base.metadata
    }
    expected_current = (
        EXPECTED_MODEL_TABLES | DIRECTORY_TABLES | PROFESSIONAL_REVIEW_TABLES
        | CAT_ASSET_TABLES | CAT_TASK_BINDING_TABLES | SCHOOL_FEEDBACK_TABLES
        | POST_ASSESSMENT_JOB_TABLES | RESEARCH_CAT_TABLES
    )
    if revision not in SUPPORTED_BACKUP_REVISIONS:
        raise ValueError("Unsupported restore revision")
    if (
        len(metadata_tables) != len(expected_current)
        or set(metadata_tables) != expected_current
        or mapped_tables != expected_current
    ):
        raise RuntimeError("Trusted model table manifest is incomplete or changed")

    tables: dict[str, TableSpec] = {}
    for table_name, table in metadata_tables.items():
        if (
            revision not in {
                CAT_TASK_BINDING_REVISION, SCHOOL_FEEDBACK_PUBLICATION_REVISION,
                POST_ASSESSMENT_JOB_OUTBOX_REVISION, RESEARCH_CAT_SESSIONS_REVISION,
            }
            and table_name in CAT_TASK_BINDING_TABLES
        ):
            continue
        if (
            revision not in {
                SCHOOL_FEEDBACK_PUBLICATION_REVISION,
                POST_ASSESSMENT_JOB_OUTBOX_REVISION,
                RESEARCH_CAT_SESSIONS_REVISION,
            }
            and table_name in SCHOOL_FEEDBACK_TABLES
        ):
            continue
        if revision not in {POST_ASSESSMENT_JOB_OUTBOX_REVISION, RESEARCH_CAT_SESSIONS_REVISION} and table_name in POST_ASSESSMENT_JOB_TABLES:
            continue
        if revision != RESEARCH_CAT_SESSIONS_REVISION and table_name in RESEARCH_CAT_TABLES:
            continue
        if (
            revision not in {
                CAT_ASSETS_REVISION, CAT_TASK_BINDING_REVISION,
                SCHOOL_FEEDBACK_PUBLICATION_REVISION, POST_ASSESSMENT_JOB_OUTBOX_REVISION,
                RESEARCH_CAT_SESSIONS_REVISION,
            }
            and table_name in CAT_ASSET_TABLES
        ):
            continue
        if (
            revision not in {
                PROFESSIONAL_REVIEW_REVISION, CAT_ASSETS_REVISION, CAT_TASK_BINDING_REVISION,
                SCHOOL_FEEDBACK_PUBLICATION_REVISION, POST_ASSESSMENT_JOB_OUTBOX_REVISION,
                RESEARCH_CAT_SESSIONS_REVISION,
            }
            and table_name in PROFESSIONAL_REVIEW_TABLES
        ):
            continue
        if revision == SUPPORTED_REVISION and table_name in DIRECTORY_TABLES:
            continue
        columns = tuple(column.name for column in table.columns)
        nullable = frozenset(column.name for column in table.columns if column.nullable)
        if (
            revision not in {
                CAT_TASK_BINDING_REVISION, SCHOOL_FEEDBACK_PUBLICATION_REVISION,
                POST_ASSESSMENT_JOB_OUTBOX_REVISION, RESEARCH_CAT_SESSIONS_REVISION,
            }
            and table_name in CAT_TASK_BINDING_MODE_TABLES
        ):
            columns = tuple(column for column in columns if column != "cat_binding_mode")
            nullable = nullable - {"cat_binding_mode"}
        if revision == SUPPORTED_REVISION and table_name in DIRECTORY_NAME_TABLES:
            columns = tuple(column for column in columns if column != "display_name")
            nullable = nullable - {"display_name"}
        primary_key = tuple(column.name for column in table.primary_key.columns)
        foreign_keys = tuple(
            ForeignKeySpec(
                local_columns=tuple(element.parent.name for element in constraint.elements),
                remote_table=constraint.referred_table.name,
                remote_columns=tuple(element.column.name for element in constraint.elements),
            )
            for constraint in table.foreign_key_constraints
        )
        tables[table_name] = TableSpec(columns, nullable, primary_key, foreign_keys)

    tables[REVISION_TABLE] = TableSpec(
        columns=("version_num",),
        nullable_columns=frozenset(),
        primary_key=("version_num",),
    )
    return tables


def trusted_manifest(revision: str = SUPPORTED_REVISION) -> dict[str, list[str]]:
    """Return the supported revision's exact local table-to-column manifest."""
    tables = _load_trusted_tables(revision)
    return {name: list(tables[name].columns) for name in sorted(tables)}


def _parent_first_order(tables: dict[str, TableSpec]) -> list[str]:
    model_names = set(tables) - {REVISION_TABLE}
    dependencies: dict[str, set[str]] = {}
    for name in model_names:
        parents = {foreign_key.remote_table for foreign_key in tables[name].foreign_keys}
        if not parents <= model_names:
            raise ValueError(f"Foreign key target is outside the trusted manifest: {name}")
        dependencies[name] = parents

    order: list[str] = []
    remaining = set(model_names)
    while remaining:
        ready = sorted(name for name in remaining if dependencies[name].isdisjoint(remaining))
        if not ready:
            raise ValueError("Foreign-key dependency cycle in trusted model")
        order.extend(ready)
        remaining.difference_update(ready)
    return order


def _decode_rows(
    package: dict[str, Any], tables: dict[str, TableSpec]
) -> dict[str, list[dict[str, Any]]]:
    snapshot_tables = package["tables"]
    if set(snapshot_tables) != set(tables):
        missing = sorted(set(tables) - set(snapshot_tables))
        extra = sorted(set(snapshot_tables) - set(tables))
        raise ValueError(f"Snapshot table manifest mismatch (missing={missing}, extra={extra})")

    decoded: dict[str, list[dict[str, Any]]] = {}
    for table_name, spec in tables.items():
        table = snapshot_tables[table_name]
        columns = table["columns"]
        if set(columns) != set(spec.columns):
            missing = sorted(set(spec.columns) - set(columns))
            extra = sorted(set(columns) - set(spec.columns))
            raise ValueError(
                f"Snapshot column manifest mismatch for {table_name} "
                f"(missing={missing}, extra={extra})"
            )
        rows: list[dict[str, Any]] = []
        for encoded_row in table["rows"]:
            values = [decode_value(value) for value in encoded_row]
            row = dict(zip(columns, values, strict=True))
            rows.append(row)
        decoded[table_name] = rows
    return decoded


def _validate_rows(
    rows_by_table: dict[str, list[dict[str, Any]]], tables: dict[str, TableSpec]
) -> None:
    for table_name, rows in rows_by_table.items():
        spec = tables[table_name]
        for row in rows:
            for column in spec.columns:
                if column not in spec.nullable_columns and row[column] is None:
                    raise ValueError(f"NULL in non-null column {table_name}.{column}")

        if spec.primary_key:
            seen: set[tuple[Any, ...]] = set()
            for row in rows:
                key = tuple(row[column] for column in spec.primary_key)
                if key in seen:
                    raise ValueError(f"Duplicate primary key in {table_name}")
                seen.add(key)

    for table_name, rows in rows_by_table.items():
        for foreign_key in tables[table_name].foreign_keys:
            parent_rows = rows_by_table[foreign_key.remote_table]
            parent_keys = {
                tuple(parent[column] for column in foreign_key.remote_columns)
                for parent in parent_rows
            }
            for row in rows:
                child_key = tuple(row[column] for column in foreign_key.local_columns)
                # MySQL's default MATCH SIMPLE skips a composite FK if any
                # referencing component is NULL.
                if any(value is None for value in child_key):
                    continue
                if child_key not in parent_keys:
                    raise ValueError(f"Foreign-key reference missing for {table_name}")


def _utc_as_mysql_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("restored_at must be an explicit UTC datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError("restored_at must be UTC")
    return value.astimezone(UTC).replace(tzinfo=None)


def plan_restore(package: dict, *, restored_at: datetime) -> dict[str, Any]:
    """Validate a v2 package and return a decoded, FK-safe import plan.

    This is a pure planning operation. It does not create or connect to a
    restore target. The original package and snapshot rows remain untouched.
    """
    validate_backup_package(package)
    if package["revision"] not in SUPPORTED_BACKUP_REVISIONS:
        raise ValueError("Unsupported restore revision")
    recovery_time = _utc_as_mysql_datetime(restored_at)

    tables = _load_trusted_tables(package["revision"])
    rows_by_table = _decode_rows(package, tables)
    revision_rows = rows_by_table[REVISION_TABLE]
    if len(revision_rows) != 1 or revision_rows[0]["version_num"] != package["revision"]:
        raise ValueError("Snapshot revision table must contain exactly the supported revision")

    auth_spec = tables["auth_sessions"]
    session_columns = auth_spec.columns
    if "revoked_at" not in session_columns or "revocation_reason" not in session_columns:
        raise RuntimeError("Auth-session recovery fields are missing from trusted models")
    revoked_session_count = 0
    for row in rows_by_table["auth_sessions"]:
        if row["revoked_at"] is None:
            row["revoked_at"] = recovery_time
            row["revocation_reason"] = RECOVERY_REVOCATION_REASON
            revoked_session_count += 1

    _validate_rows(rows_by_table, tables)
    table_order = _parent_first_order(tables)
    planned_tables: dict[str, dict[str, Any]] = {}
    row_counts: dict[str, int] = {}
    for table_name in table_order:
        columns = tables[table_name].columns
        planned_tables[table_name] = {
            "columns": list(columns),
            "rows": [[row[column] for column in columns] for row in rows_by_table[table_name]],
        }
        row_counts[table_name] = len(rows_by_table[table_name])

    return {
        "revision": package["revision"],
        "table_order": table_order,
        "tables": planned_tables,
        "row_counts": row_counts,
        "revoked_session_count": revoked_session_count,
    }


__all__ = ["plan_restore", "trusted_manifest"]
