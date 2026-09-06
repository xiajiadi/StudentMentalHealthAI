"""Generate a Mermaid ERD from the actual SQLAlchemy metadata."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database_layer import models  # noqa: F401 - registers all mapped tables
from database_layer.base import Base


def mermaid_type(column: object) -> str:
    """Render a compact Mermaid type from the SQLAlchemy column type."""

    type_name = column.type.__class__.__name__.lower()  # type: ignore[attr-defined]
    mapped = {
        "string": "varchar",
        "integer": "int",
        "bigint": "bigint",
        "binary": "binary",
        "datetime": "datetime",
        "mediumblob": "mediumblob",
        "json": "json",
    }.get(type_name)
    return mapped or type_name


def render() -> str:
    lines = ["erDiagram"]
    for table in Base.metadata.sorted_tables:
        lines.append(f"    {table.name} {{")
        for column in table.columns:
            nullable = "NULL" if column.nullable else "NOT_NULL"
            lines.append(f'        {mermaid_type(column)} {column.name} "{nullable}"')
        lines.append("    }")
    for table in Base.metadata.sorted_tables:
        for foreign_key in table.foreign_keys:
            lines.append(
                f"    {foreign_key.column.table.name} ||--o{{ {table.name} : "
                f'"{foreign_key.parent.name}"'
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
