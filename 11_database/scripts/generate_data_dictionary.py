"""Generate DATA_DICTIONARY.md from the SQLAlchemy metadata."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database_layer import models  # noqa: F401 - registers all mapped tables
from database_layer.base import Base
from sqlalchemy.dialects import mysql

ENCRYPTED_SUFFIXES = (
    "_ciphertext",
    "session_token_hash",
    "csrf_token_hash",
    "user_agent_hash",
    "key_hash",
    "request_hash",
)
SENSITIVE_TABLES = {
    "assessment_responses",
    "assessment_results",
    "support_messages",
    "safety_decisions",
    "review_cases",
    "review_events",
}
OPERATIONAL_COLUMNS = {
    "id",
    "public_id",
    "created_at",
    "updated_at",
    "status",
    "priority",
    "version",
    "trace_id",
    "action",
    "result",
    "rank_order",
    "sequence_no",
    "retention_due_at",
    "started_at",
    "completed_at",
    "closed_at",
    "expires_at",
    "last_seen_at",
    "idle_expires_at",
    "absolute_expires_at",
    "revoked_at",
}


def classify(table_name: str, column_name: str) -> tuple[str, str, str, str]:
    if column_name in {
        "password_hash",
        "session_token_hash",
        "csrf_token_hash",
        "user_agent_hash",
        "key_hash",
        "request_hash",
    }:
        return "SECURITY_SECRET", "Yes", "No", "Hash lookup or authentication control"
    if column_name.endswith(ENCRYPTED_SUFFIXES):
        return (
            "PSYCHOLOGICAL_SENSITIVE",
            "Yes",
            "No",
            "Clear ciphertext by retention or synthetic erasure",
        )
    if table_name in SENSITIVE_TABLES and column_name not in OPERATIONAL_COLUMNS:
        return "PSYCHOLOGICAL_SENSITIVE", "No", "No", "Review policy before retention/erasure"
    if table_name in {
        "accounts",
        "subjects",
        "subject_access_grants",
        "consent_records",
        "auth_sessions",
    }:
        return "PERSONAL", "No", "Yes", "Policy-driven; explicit lifecycle"
    if column_name in {"safe_metadata", "component_versions"}:
        return "INTERNAL", "No", "No", "Bounded JSON; purge with parent workflow"
    return "INTERNAL", "No", "Yes", "Policy-driven technical/audit retention"


def render() -> str:
    lines = [
        "# Data Dictionary",
        "",
        "Generated from the SQLAlchemy metadata by `scripts/generate_data_dictionary.py`.",
        "Round 1 contains synthetic fixtures only; sensitivity labels are engineering "
        "classifications.",
        "",
        "| Table | Column | Type | Nullable | Sensitivity | Encrypted/hashed? | "
        "Queryable? | Retention notes |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    dialect = mysql.dialect()
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            sensitivity, protected, queryable, retention = classify(table.name, column.name)
            type_name = str(column.type.compile(dialect=dialect)).replace("|", "\\|")
            lines.append(
                f"| `{table.name}` | `{column.name}` | `{type_name}` | "
                f"{'yes' if column.nullable else 'no'} | {sensitivity} | {protected} | "
                f"{queryable} | {retention} |"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
