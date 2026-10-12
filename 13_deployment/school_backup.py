"""Create a sealed, consistent backup of the owned synthetic school database."""
from __future__ import annotations

import argparse
import base64
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path
import re
import sys
from uuid import uuid4

from private_settings import read_private, write_private
from school_backend import load_runtime

NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def encode_value(value):
    if isinstance(value, bytes):
        return {"type": "bytes", "value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, datetime):
        return {"type": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"type": "date", "value": value.isoformat()}
    if isinstance(value, Decimal):
        return {"type": "decimal", "value": str(value)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("Unsupported backup value")


def snapshot(connection, marker: dict) -> dict:
    """Read SQL values as stored; never decrypt private application payloads."""
    tables = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT DATABASE(), @@port, @@transaction_isolation")
            if cursor.fetchone() != (marker["database"], marker["port"], "REPEATABLE-READ"):
                raise ValueError("Owned consistent snapshot target required")
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
            cursor.execute("SELECT version_num FROM database_alembic_version")
            revision = cursor.fetchone()[0]
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
            "schema_version": "psynova.sealed-school-backup.v1",
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
    load_runtime(workspace, repo)
    marker = json.loads((workspace / "workspace.json").read_text(encoding="utf-8"))
    private = read_private(workspace / "runtime.private.dpapi")
    import pymysql

    connection = pymysql.connect(
        host="127.0.0.1", port=marker["port"], database=marker["database"],
        user=private["DB_USER"], password=private["DB_PASSWORD"],
        autocommit=False, connect_timeout=10, read_timeout=30,
    )
    try:
        content = snapshot(connection, marker)
    finally:
        connection.close()
    target_dir = workspace / "backups"
    target_dir.mkdir(exist_ok=True)
    if target_dir.resolve().parent != workspace.resolve() or target_dir.is_symlink():
        raise ValueError("Owned backup directory required")
    target = target_dir / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex + ".private.dpapi")
    write_private(target, content, exclusive=True)
    restored = read_private(target)
    if restored != content:
        raise ValueError("Sealed backup readback failed")
    return {"backup": "SEALED_AND_READBACK_VERIFIED", "revision": content["revision"],
            "table_count": len(content["tables"]), "path": str(target),
            "restore_workflow": "not yet verified"}


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
    except Exception as exc:
        print(json.dumps({"backup": "FAIL", "error_type": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
