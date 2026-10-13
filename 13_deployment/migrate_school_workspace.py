"""Migrate one verified, current-user-owned synthetic school workspace once."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from private_settings import read_private
from resume_school_workspace import (
    DATABASE,
    HOST,
    MAX_DATABASE_PORT,
    MIN_DATABASE_PORT,
    ResumeError,
    ResumeOperations,
    _command_arguments,
    _process_matches,
    _reject_reparse_path,
    _require_loopback_listeners,
    _utc_timestamp,
    guardian_arguments,
    validate_existing_workspace,
    workspace_lock,
)
from resume_school_workspace import (
    DEFAULT_WORKSPACE as SOURCE_WORKSPACE,
)
from resume_school_workspace import (
    PORT as SOURCE_DATABASE_PORT,
)
from school_schema import CURRENT_SCHOOL_REVISION

BUILDER_USER = "psynova_builder"
MIGRATION_TIMEOUT_SECONDS = 900
_WORKSPACE_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_PASSWORD_RE = re.compile(r"^[a-f0-9]{64}$")


class MigrationError(RuntimeError):
    """Fixed, non-sensitive result code for safe CLI reporting."""

    def __init__(self, code: str, *, partial: bool = False):
        super().__init__(code)
        self.code = code
        self.partial = partial


def _validate_request(workspace: Path, repo: Path, port: int, workspace_id: str):
    if type(port) is not int or not MIN_DATABASE_PORT <= port <= MAX_DATABASE_PORT:
        raise MigrationError("INVALID_PORT")
    if port == SOURCE_DATABASE_PORT:
        raise MigrationError("SOURCE_WORKSPACE_PORT_NOT_ALLOWED")
    if Path(workspace).resolve(strict=False) == Path(SOURCE_WORKSPACE).resolve(
        strict=False
    ):
        raise MigrationError("SOURCE_WORKSPACE_PATH_NOT_ALLOWED")
    if not isinstance(workspace_id, str) or not _WORKSPACE_ID_RE.fullmatch(
        workspace_id
    ):
        raise MigrationError("INVALID_WORKSPACE_ID")
    try:
        marker = validate_existing_workspace(
            Path(workspace),
            Path(repo),
            expected_workspace=Path(workspace),
            expected_port=port,
        )
    except (ResumeError, OSError, ValueError, TypeError):
        raise MigrationError("WORKSPACE_INVALID") from None
    if marker.get("workspace_id") != workspace_id:
        raise MigrationError("WORKSPACE_ID_MISMATCH")
    if marker.get("database") != DATABASE or marker.get("port") != port:
        raise MigrationError("WORKSPACE_TARGET_MISMATCH")
    return marker


def _verify_guardian(marker: dict[str, Any], operations: ResumeOperations) -> None:
    workspace = Path(marker["data_directory"]).parent
    try:
        _reject_reparse_path(workspace / "database.private.dpapi")
        operations.verify_acl(workspace)
        operations.verify_running_process(marker)
        guardian_pid = int(marker["parent_pid"])
        process = operations.inspect_process(guardian_pid)
        if process is None or not _process_matches(process, marker):
            raise MigrationError("GUARDIAN_IDENTITY_INVALID")
        expected_argv = _expected_service_argv(marker)
        if not _command_matches(process, expected_argv):
            raise MigrationError("GUARDIAN_ARGUMENTS_INVALID")
        listeners = operations.listeners(int(marker["port"]))
        _require_loopback_listeners(listeners, int(marker["port"]))
        observed_children: dict[int, tuple[Any, ...]] = {}
        for listener in listeners:
            owner_pid = int(listener.get("OwningProcess", -1))
            if owner_pid <= 0:
                raise MigrationError("LISTENER_OWNER_INVALID")
            if owner_pid == guardian_pid:
                continue
            child = operations.inspect_process(owner_pid)
            if child is None or not _direct_guardian_child_matches(
                child, owner_pid, guardian_pid, process, marker, expected_argv
            ):
                raise MigrationError("LISTENER_PROCESS_IDENTITY_INVALID")
            repeated = operations.inspect_process(owner_pid)
            if repeated is None or not _direct_guardian_child_matches(
                repeated, owner_pid, guardian_pid, process, marker, expected_argv
            ):
                raise MigrationError("LISTENER_PROCESS_IDENTITY_INVALID")
            first_identity = _process_identity(child)
            if first_identity != _process_identity(repeated):
                raise MigrationError("LISTENER_PROCESS_CHANGED_DURING_CHECK")
            observed_children[owner_pid] = first_identity

        latest_listeners = operations.listeners(int(marker["port"]))
        _require_loopback_listeners(latest_listeners, int(marker["port"]))
        if _listener_snapshot(latest_listeners) != _listener_snapshot(listeners):
            raise MigrationError("LISTENER_CHANGED_DURING_CHECK")
        final_guardian = operations.inspect_process(guardian_pid)
        if (
            final_guardian is None
            or not _process_matches(final_guardian, marker)
            or not _command_matches(final_guardian, expected_argv)
            or _process_identity(final_guardian) != _process_identity(process)
        ):
            raise MigrationError("GUARDIAN_IDENTITY_CHANGED_DURING_CHECK")
        for owner_pid, identity in observed_children.items():
            final_child = operations.inspect_process(owner_pid)
            if (
                final_child is None
                or not _direct_guardian_child_matches(
                    final_child,
                    owner_pid,
                    guardian_pid,
                    final_guardian,
                    marker,
                    expected_argv,
                )
                or _process_identity(final_child) != identity
            ):
                raise MigrationError("LISTENER_PROCESS_CHANGED_DURING_CHECK")
    except MigrationError:
        raise
    except Exception:  # noqa: BLE001 - PowerShell/process output must stay redacted.
        raise MigrationError("GUARDIAN_VERIFICATION_FAILED") from None


def _expected_service_argv(marker: dict[str, Any]) -> list[str]:
    workspace = Path(marker["data_directory"]).parent
    return guardian_arguments(
        Path(marker["executable"]),
        workspace,
        Path(marker["data_directory"]),
        int(marker["port"]),
    )


def _command_matches(process: dict[str, Any], expected: list[str]) -> bool:
    actual = _command_arguments(str(process.get("CommandLine", "")))
    return (
        bool(actual)
        and len(actual) == len(expected)
        and actual[0].replace("/", "\\").casefold()
        == expected[0].replace("/", "\\").casefold()
        and actual[1:] == expected[1:]
    )


def _process_identity(process: dict[str, Any]) -> tuple[Any, ...]:
    executable = Path(str(process.get("ExecutablePath", ""))).resolve(strict=True)
    argv = _command_arguments(str(process.get("CommandLine", "")))
    normalized_argv = tuple(
        value.replace("/", "\\").casefold() if index == 0 else value
        for index, value in enumerate(argv)
    )
    return (
        int(process.get("ProcessId", -1)),
        int(process.get("ParentProcessId", -1)),
        str(executable).casefold(),
        _utc_timestamp(str(process.get("CreationUtc", ""))),
        normalized_argv,
    )


def _direct_guardian_child_matches(
    child: dict[str, Any],
    child_pid: int,
    guardian_pid: int,
    guardian: dict[str, Any],
    marker: dict[str, Any],
    expected_argv: list[str],
) -> bool:
    try:
        if (
            int(child.get("ProcessId", -1)) != child_pid
            or int(child.get("ParentProcessId", -1)) != guardian_pid
            or not _command_matches(child, expected_argv)
        ):
            return False
        actual_executable = Path(str(child.get("ExecutablePath", ""))).resolve(
            strict=True
        )
        expected_executable = Path(str(marker["executable"])).resolve(strict=True)
        if actual_executable != expected_executable:
            return False
        guardian_time = datetime.fromisoformat(
            _utc_timestamp(str(guardian.get("CreationUtc", ""))).replace("Z", "+00:00")
        )
        child_time = datetime.fromisoformat(
            _utc_timestamp(str(child.get("CreationUtc", ""))).replace("Z", "+00:00")
        )
        return guardian_time <= child_time <= datetime.now(UTC)
    except (OSError, TypeError, ValueError, KeyError):
        return False


def _listener_snapshot(listeners: list[dict[str, Any]]) -> tuple[tuple[Any, ...], ...]:
    return tuple(
        sorted(
            (
                int(item.get("OwningProcess", -1)),
                str(item.get("LocalAddress", "")),
                int(item.get("LocalPort", -1)),
            )
            for item in listeners
        )
    )


def _validate_builder(private: dict[str, Any], marker: dict[str, Any]) -> str:
    try:
        user = private.get("DB_USER")
        password = private.get("DB_PASSWORD")
        host = private.get("DB_HOST")
        port = private.get("DB_PORT")
        database = private.get("DB_NAME")
        if (
            user != BUILDER_USER
            or not isinstance(password, str)
            or not _PASSWORD_RE.fullmatch(password)
            or host != HOST
            or str(port) != str(marker["port"])
            or database != DATABASE
        ):
            raise MigrationError("SEALED_BUILDER_TARGET_MISMATCH")
        data_directory = Path(marker["data_directory"])
        if not data_directory.is_absolute() or not data_directory.is_dir():
            raise MigrationError("WORKSPACE_DATADIR_INVALID")
        return password
    except MigrationError:
        raise
    except Exception:  # noqa: BLE001 - sealed input errors may carry private details.
        raise MigrationError("SEALED_BUILDER_SETTINGS_INVALID") from None


def _verify_builder_grants(grants: list[str], current_role: object) -> None:
    expected = {
        "GRANT USAGE ON *.*",
        f"GRANT ALL PRIVILEGES ON `{DATABASE}`.*",
    }
    try:
        scopes = {grant.split(" TO ", 1)[0].strip() for grant in grants}
        if (
            len(grants) != 2
            or scopes != expected
            or not isinstance(current_role, str)
            or current_role.strip().upper() != "NONE"
            or any("WITH GRANT OPTION" in grant.upper() for grant in grants)
        ):
            raise MigrationError("BUILDER_PRIVILEGES_INVALID")
    except MigrationError:
        raise
    except Exception:  # noqa: BLE001 - database grant data stays private.
        raise MigrationError("BUILDER_PRIVILEGES_INVALID") from None


def _normalized_type(value: Any, dialect: Any) -> str:
    compiler = getattr(value, "compile", None)
    source = str(compiler(dialect=dialect) if compiler else value).strip()
    source = re.sub(
        r"\s+COLLATE\s+[A-Za-z_][\w$]*\s*$", "", source, flags=re.IGNORECASE
    )
    token_pattern = re.compile(
        r"'(?:''|\\.|[^'])*'|\"(?:\"\"|\\.|[^\"])*\"|"
        r"[A-Za-z_][\w$]*|\d+(?:\.\d+)?|\s+|."
    )
    tokens = token_pattern.findall(source)
    normalized: list[str] = []
    integer_types = {"TINYINT", "SMALLINT", "MEDIUMINT", "INTEGER", "INT", "BIGINT"}
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.startswith(("'", '"')):
            normalized.append(token)
            index += 1
            continue
        if token.isspace():
            normalized.append(token)
            index += 1
            continue
        word = token.upper()
        if word == "INTEGER":
            word = "INT"
        elif word in {"BOOL", "BOOLEAN"}:
            word = "TINYINT"
        normalized.append(word)
        if word in integer_types:
            cursor = index + 1
            while cursor < len(tokens) and tokens[cursor].isspace():
                cursor += 1
            if cursor < len(tokens) and tokens[cursor] == "(":
                cursor += 1
                while cursor < len(tokens) and tokens[cursor].isspace():
                    cursor += 1
                if cursor < len(tokens) and tokens[cursor].isdigit():
                    cursor += 1
                    while cursor < len(tokens) and tokens[cursor].isspace():
                        cursor += 1
                    if cursor < len(tokens) and tokens[cursor] == ")":
                        index = cursor + 1
                        continue
        index += 1
    return re.sub(r"\s+", " ", "".join(normalized)).strip()


def _normalized_collation(value: Any) -> str | None:
    collation = getattr(value, "collation", None)
    if collation is None:
        return None
    if not isinstance(collation, str) or not re.fullmatch(r"[A-Za-z0-9_]+", collation):
        raise ValueError("unsupported collation metadata")
    return collation.casefold()


def _normalize_check_sql(value: Any) -> str:
    source = str(value).strip().replace("\\'", "'")
    source = re.sub(r"(?i)\b_(?:utf8mb[0-9]+|ascii)(?=')", "", source)
    token_pattern = re.compile(
        r"\s+|'(?:''|\\.|[^'\\])*'|\"(?:\"\"|\\.|[^\"\\])*\"|"
        r"`(?:``|[^`])*`|<=|>=|<>|!=|=|<|>|\(|\)|,|"
        r"[A-Za-z_$][\w$]*|\d+(?:\.\d+)?"
    )
    tokens: list[tuple[str, str]] = []
    position = 0
    while position < len(source):
        match = token_pattern.match(source, position)
        if match is None:
            raise ValueError("unsupported CHECK syntax")
        token = match.group(0)
        position = match.end()
        if token.isspace():
            continue
        if token.startswith("`"):
            tokens.append(("identifier", token[1:-1].replace("``", "`").casefold()))
        elif token.startswith(("'", '"')):
            tokens.append(("literal", token))
        elif re.fullmatch(r"\d+(?:\.\d+)?", token):
            tokens.append(("number", token))
        elif token in {"(", ")", ",", "=", "<", ">", "<=", ">=", "<>", "!="}:
            tokens.append(("symbol", token))
        else:
            tokens.append(("word", token.casefold()))

    class Parser:
        def __init__(self, items: list[tuple[str, str]]):
            self.items = items
            self.index = 0

        def peek(self, value: str | None = None) -> bool:
            if self.index >= len(self.items):
                return False
            return value is None or self.items[self.index][1] == value

        def take(self, value: str | None = None) -> tuple[str, str]:
            if not self.peek(value):
                raise ValueError("unsupported CHECK syntax")
            item = self.items[self.index]
            self.index += 1
            return item

        def parse(self) -> tuple[Any, ...]:
            expression = self.parse_or()
            if self.index != len(self.items):
                raise ValueError("unsupported CHECK syntax")
            return expression

        def parse_or(self) -> tuple[Any, ...]:
            left = self.parse_and()
            while self.peek("or"):
                self.take("or")
                left = ("or", left, self.parse_and())
            return left

        def parse_and(self) -> tuple[Any, ...]:
            left = self.parse_not()
            while self.peek("and"):
                self.take("and")
                left = ("and", left, self.parse_not())
            return left

        def parse_not(self) -> tuple[Any, ...]:
            if self.peek("not"):
                self.take("not")
                return ("not", self.parse_not())
            return self.parse_predicate()

        def parse_predicate(self) -> tuple[Any, ...]:
            left = self.parse_primary()
            if self.peek("is"):
                self.take("is")
                negate = False
                if self.peek("not"):
                    self.take("not")
                    negate = True
                self.take("null")
                return ("is-null", negate, left)
            if self.peek("in"):
                self.take("in")
                self.take("(")
                values = [self.parse_or()]
                while self.peek(","):
                    self.take(",")
                    values.append(self.parse_or())
                self.take(")")
                return ("in", left, tuple(values))
            if self.peek("between"):
                self.take("between")
                lower = self.parse_primary()
                self.take("and")
                upper = self.parse_primary()
                return ("between", left, lower, upper)
            if self.peek() and self.items[self.index][1] in {
                "=",
                "<>",
                "!=",
                "<",
                "<=",
                ">",
                ">=",
            }:
                operator = self.take()[1]
                return ("compare", operator, left, self.parse_primary())
            return left

        def parse_primary(self) -> tuple[Any, ...]:
            kind, token = self.take()
            if token == "(":
                expression = self.parse_or()
                self.take(")")
                return expression
            if kind == "identifier":
                return ("identifier", token)
            if kind == "literal":
                return ("literal", token)
            if kind == "number":
                return ("number", token)
            if kind == "word" and token == "null":
                return ("null",)
            if kind == "word" and token in {"true", "false"}:
                return ("boolean", token)
            if kind == "word" and token not in {
                "and",
                "or",
                "not",
                "is",
                "in",
                "between",
            }:
                return ("identifier", token)
            raise ValueError("unsupported CHECK syntax")

    expression = Parser(tokens).parse()

    def render(node: tuple[Any, ...]) -> str:
        kind = node[0]
        if kind in {"identifier", "literal", "number", "null", "boolean"}:
            return str(node[1]) if len(node) > 1 else "null"
        if kind == "is-null":
            return f"({render(node[2])} is {'not ' if node[1] else ''}null)"
        if kind == "compare":
            return f"({render(node[2])}{node[1]}{render(node[3])})"
        if kind == "between":
            return (
                f"({render(node[1])} between {render(node[2])} and {render(node[3])})"
            )
        if kind == "in":
            return (
                f"({render(node[1])} in ({','.join(render(item) for item in node[2])}))"
            )
        if kind in {"and", "or"}:
            return f"({render(node[1])} {kind} {render(node[2])})"
        if kind == "not":
            return f"(not {render(node[1])})"
        raise ValueError("unsupported CHECK syntax")

    return render(expression)


def _trusted_current_schema(database_root: Path) -> dict[str, Any]:
    try:
        for dependency_path in (
            database_root / ".venv" / "Lib" / "site-packages",
            database_root,
        ):
            text_path = str(dependency_path)
            if text_path not in sys.path:
                sys.path.insert(0, text_path)
        from database_layer import models
        from database_layer.base import Base
        from school_restore_plan import trusted_manifest
        from sqlalchemy import CheckConstraint, UniqueConstraint
        from sqlalchemy.dialects import mysql

        resolved_root = database_root.resolve(strict=True)
        model_path = Path(models.__file__).resolve(strict=True)
        if resolved_root not in model_path.parents:
            raise ValueError
        metadata = Base.metadata
        manifest = trusted_manifest(CURRENT_SCHOOL_REVISION)
        model_tables = {name: table for name, table in metadata.tables.items()}
        expected_names = set(model_tables) | {"database_alembic_version"}
        if (
            not isinstance(manifest, dict)
            or not manifest
            or set(manifest) != expected_names
            or set(model_tables) != set(metadata.tables)
        ):
            raise ValueError

        dialect = mysql.dialect()
        schema: dict[str, Any] = {}
        for table_name, table in model_tables.items():
            columns: dict[str, dict[str, Any]] = {}
            for column in table.columns:
                key = column.name.casefold()
                if key in columns:
                    raise ValueError
                columns[key] = {
                    "type": _normalized_type(column.type, dialect),
                    "collation": _normalized_collation(column.type),
                    "nullable": bool(column.nullable),
                    "auto_increment": table.autoincrement_column is column,
                }
            primary_key = tuple(
                column.name.casefold() for column in table.primary_key.columns
            )
            uniques = {
                (
                    str(constraint.name).casefold(),
                    tuple(column.name.casefold() for column in constraint.columns),
                )
                for constraint in table.constraints
                if isinstance(constraint, UniqueConstraint)
            }
            foreign_keys = set()
            for constraint in table.foreign_key_constraints:
                if not constraint.name:
                    raise ValueError
                remote_columns = tuple(
                    element.column.name.casefold() for element in constraint.elements
                )
                remote_table = constraint.referred_table.name.casefold()
                foreign_keys.add(
                    (
                        str(constraint.name).casefold(),
                        tuple(
                            element.parent.name.casefold()
                            for element in constraint.elements
                        ),
                        remote_table,
                        remote_columns,
                        _normalize_referential_action(constraint.ondelete),
                        _normalize_referential_action(constraint.onupdate),
                    )
                )
            checks = {
                (
                    str(constraint.name).casefold(),
                    _normalize_check_sql(constraint.sqltext),
                    True,
                )
                for constraint in table.constraints
                if isinstance(constraint, CheckConstraint)
            }
            indexes = set()
            for index in table.indexes:
                index_columns = tuple(
                    expression.name.casefold()
                    for expression in index.expressions
                    if getattr(expression, "name", None)
                )
                if len(index_columns) != len(index.expressions) or not index.name:
                    raise ValueError
                indexes.add((index.name.casefold(), index_columns, bool(index.unique)))
            schema[table_name.casefold()] = {
                "columns": columns,
                "primary_key": primary_key,
                "uniques": uniques,
                "foreign_keys": foreign_keys,
                "checks": checks,
                "indexes": indexes,
            }

        # The Alembic revision table is part of the pinned target too.
        schema["database_alembic_version"] = {
            "columns": {
                "version_num": {
                    "type": "VARCHAR(32)",
                    "collation": None,
                    "nullable": False,
                    "auto_increment": False,
                }
            },
            "primary_key": ("version_num",),
            "uniques": set(),
            "foreign_keys": set(),
            "checks": set(),
            "indexes": set(),
        }
        manifest_columns = {
            str(table).casefold(): {str(column).casefold() for column in columns}
            for table, columns in manifest.items()
        }
        if manifest_columns != {
            table: set(contract["columns"]) for table, contract in schema.items()
        }:
            raise ValueError
        return schema
    except Exception:  # noqa: BLE001 - import/model errors may expose local details.
        raise MigrationError("TRUSTED_SCHEMA_METADATA_UNAVAILABLE") from None


def _normalize_referential_action(action: Any) -> str:
    normalized = str(action or "RESTRICT").upper().replace("_", " ")
    return "RESTRICT" if normalized in {"NO ACTION", "RESTRICT"} else normalized


def _inspect_actual_schema(cursor: Any, table_names: set[str]) -> dict[str, Any]:
    from sqlalchemy.dialects import mysql

    dialect = mysql.dialect()
    schema = {
        table.casefold(): {
            "columns": {},
            "primary_key": (),
            "uniques": set(),
            "foreign_keys": set(),
            "checks": set(),
            "indexes": set(),
        }
        for table in table_names
    }

    cursor.execute(
        "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, COLLATION_NAME, IS_NULLABLE, EXTRA "
        "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s "
        "ORDER BY TABLE_NAME, ORDINAL_POSITION",
        (DATABASE,),
    )
    for table, name, column_type, collation, nullable, extra in cursor.fetchall():
        table_key = str(table).casefold()
        if table_key in schema:
            schema[table_key]["columns"][str(name).casefold()] = {
                "type": _normalized_type(column_type, dialect),
                "collation": str(collation).casefold() if collation else None,
                "nullable": str(nullable).upper() == "YES",
                "auto_increment": "auto_increment" in str(extra).casefold().split(),
            }

    cursor.execute(
        "SELECT tc.TABLE_NAME, tc.CONSTRAINT_NAME, tc.CONSTRAINT_TYPE, "
        "kcu.COLUMN_NAME, kcu.ORDINAL_POSITION "
        "FROM information_schema.TABLE_CONSTRAINTS tc "
        "JOIN information_schema.KEY_COLUMN_USAGE kcu "
        "ON kcu.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA "
        "AND kcu.TABLE_NAME = tc.TABLE_NAME "
        "AND kcu.CONSTRAINT_NAME = tc.CONSTRAINT_NAME "
        "WHERE tc.CONSTRAINT_SCHEMA = %s "
        "AND tc.CONSTRAINT_TYPE IN ('PRIMARY KEY', 'UNIQUE') "
        "ORDER BY tc.TABLE_NAME, tc.CONSTRAINT_NAME, kcu.ORDINAL_POSITION",
        (DATABASE,),
    )
    key_columns: dict[tuple[str, str, str], list[tuple[int, str]]] = {}
    for table, name, kind, column, ordinal in cursor.fetchall():
        table_key = str(table).casefold()
        if table_key in schema:
            key_columns.setdefault(
                (table_key, str(name).casefold(), str(kind).upper()), []
            ).append((int(ordinal), str(column).casefold()))
    for (table, name, kind), values in key_columns.items():
        columns = tuple(column for _, column in sorted(values))
        if kind == "PRIMARY KEY":
            schema[table]["primary_key"] = columns
        else:
            schema[table]["uniques"].add((name, columns))

    cursor.execute(
        "SELECT kcu.TABLE_NAME, kcu.CONSTRAINT_NAME, kcu.REFERENCED_TABLE_SCHEMA, "
        "kcu.COLUMN_NAME, kcu.REFERENCED_TABLE_NAME, kcu.REFERENCED_COLUMN_NAME, "
        "kcu.ORDINAL_POSITION, rc.DELETE_RULE, rc.UPDATE_RULE "
        "FROM information_schema.KEY_COLUMN_USAGE kcu "
        "JOIN information_schema.REFERENTIAL_CONSTRAINTS rc "
        "ON rc.CONSTRAINT_SCHEMA = kcu.CONSTRAINT_SCHEMA "
        "AND rc.TABLE_NAME = kcu.TABLE_NAME "
        "AND rc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME "
        "WHERE kcu.CONSTRAINT_SCHEMA = %s "
        "AND kcu.REFERENCED_TABLE_NAME IS NOT NULL "
        "ORDER BY kcu.TABLE_NAME, kcu.CONSTRAINT_NAME, kcu.ORDINAL_POSITION",
        (DATABASE,),
    )
    foreign_key_rows: dict[tuple[str, str], list[tuple[Any, ...]]] = {}
    for row in cursor.fetchall():
        table, name = str(row[0]).casefold(), str(row[1]).casefold()
        if table in schema:
            foreign_key_rows.setdefault((table, name), []).append(tuple(row[2:]))
    for (table, name), rows in foreign_key_rows.items():
        ordered = sorted(rows, key=lambda row: int(row[4]))
        if any(str(row[0]).casefold() != DATABASE.casefold() for row in ordered):
            raise MigrationError("CURRENT_SCHEMA_DRIFT")
        schema[table]["foreign_keys"].add(
            (
                name,
                tuple(str(row[1]).casefold() for row in ordered),
                str(ordered[0][2]).casefold(),
                tuple(str(row[3]).casefold() for row in ordered),
                _normalize_referential_action(ordered[0][5]),
                _normalize_referential_action(ordered[0][6]),
            )
        )

    cursor.execute(
        "SELECT tc.TABLE_NAME, tc.CONSTRAINT_NAME, cc.CHECK_CLAUSE, tc.ENFORCED "
        "FROM information_schema.TABLE_CONSTRAINTS tc "
        "JOIN information_schema.CHECK_CONSTRAINTS cc "
        "ON cc.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA "
        "AND cc.CONSTRAINT_NAME = tc.CONSTRAINT_NAME "
        "WHERE tc.CONSTRAINT_SCHEMA = %s AND tc.CONSTRAINT_TYPE = 'CHECK'",
        (DATABASE,),
    )
    for table, name, clause, enforced in cursor.fetchall():
        table_key = str(table).casefold()
        if table_key in schema:
            schema[table_key]["checks"].add(
                (
                    str(name).casefold(),
                    _normalize_check_sql(clause),
                    str(enforced).upper() in {"YES", "1", "TRUE"},
                )
            )

    cursor.execute(
        "SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME, EXPRESSION "
        "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = %s "
        "ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX",
        (DATABASE,),
    )
    index_columns: dict[tuple[str, str, bool], list[tuple[int, str]]] = {}
    for table, name, non_unique, ordinal, column, expression in cursor.fetchall():
        table_key, index_name = str(table).casefold(), str(name).casefold()
        if table_key not in schema or index_name == "primary":
            continue
        if column is None or expression is not None:
            raise MigrationError("CURRENT_SCHEMA_DRIFT")
        index_columns.setdefault(
            (table_key, index_name, not bool(non_unique)), []
        ).append((int(ordinal), str(column).casefold()))
    for (table, name, unique), values in index_columns.items():
        columns = tuple(column for _, column in sorted(values))
        schema[table]["indexes"].add((name, columns, unique))
    return schema


def _verify_current_schema(
    actual_tables: dict[str, str],
    has_other_objects: bool,
    cursor: Any,
    database_root: Path,
) -> None:
    expected = _trusted_current_schema(database_root)
    try:
        inspected_tables = set(actual_tables)
        actual = _inspect_actual_schema(cursor, inspected_tables)
    except MigrationError:
        raise
    except Exception:  # noqa: BLE001 - metadata query exceptions may contain connection data.
        raise MigrationError("CURRENT_SCHEMA_INSPECTION_FAILED") from None
    for table_name, observed in actual.items():
        expected_table = expected.get(table_name, {})
        expected_columns = expected_table.get("columns", {})
        for column_name, column in observed.get("columns", {}).items():
            expected_column = expected_columns.get(column_name)
            if expected_column is not None and expected_column.get("collation") is None:
                column["collation"] = None
        expected_indexes = expected_table.get("indexes", set())
        mirrored_unique_indexes = {
            (name, columns, True) for name, columns in observed.get("uniques", set())
        }
        mysql_foreign_key_indexes = {
            (name, local_columns, False)
            for name, local_columns, *_rest in expected_table.get("foreign_keys", set())
        }
        observed["indexes"] = {
            index
            for index in observed.get("indexes", set())
            if index in expected_indexes
            or (
                index not in mirrored_unique_indexes
                and index not in mysql_foreign_key_indexes
            )
        }
    if (
        has_other_objects
        or set(actual_tables) != set(expected)
        or any(kind != "BASE TABLE" for kind in actual_tables.values())
        or inspected_tables != set(expected)
        or actual != expected
    ):
        raise MigrationError("CURRENT_SCHEMA_DRIFT")


def _database_state(
    connection: Any, marker: dict[str, Any], database_root: Path
) -> str:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT @@port, @@datadir, DATABASE()")
            actual_port, actual_directory, actual_database = cursor.fetchone()
            if (
                actual_port != marker["port"]
                or Path(actual_directory).resolve(strict=True)
                != Path(marker["data_directory"]).resolve(strict=True)
                or actual_database != DATABASE
            ):
                raise MigrationError("CONNECTED_DATABASE_IDENTITY_MISMATCH")

            cursor.execute("SHOW GRANTS FOR CURRENT_USER()")
            grants = [str(row[0]) for row in cursor.fetchall()]
            cursor.execute("SELECT CURRENT_ROLE()")
            role_row = cursor.fetchone()
            _verify_builder_grants(grants, role_row[0] if role_row else None)

            cursor.execute(
                "SELECT TABLE_NAME, TABLE_TYPE FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = %s",
                (DATABASE,),
            )
            tables = {
                str(row[0]).casefold(): str(row[1]).upper() for row in cursor.fetchall()
            }
            other_objects = False
            for metadata_table, schema_column in (
                ("ROUTINES", "ROUTINE_SCHEMA"),
                ("EVENTS", "EVENT_SCHEMA"),
                ("TRIGGERS", "TRIGGER_SCHEMA"),
            ):
                cursor.execute(
                    f"SELECT 1 FROM information_schema.{metadata_table} "
                    f"WHERE {schema_column} = %s LIMIT 1",
                    (DATABASE,),
                )
                other_objects = other_objects or bool(cursor.fetchall())

            cursor.execute(
                "SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME, ORDINAL_POSITION",
                (DATABASE,),
            )
            columns: dict[str, set[str]] = {}
            for table_name, column_name in cursor.fetchall():
                columns.setdefault(str(table_name).casefold(), set()).add(
                    str(column_name).casefold()
                )
            version_table = "database_alembic_version"
            if version_table not in tables:
                if tables or columns or other_objects:
                    raise MigrationError("NONEMPTY_UNKNOWN_SCHEMA")
                return "EMPTY"

            cursor.execute("SELECT version_num FROM database_alembic_version")
            revisions = [str(row[0]) for row in cursor.fetchall()]
            if revisions == [CURRENT_SCHOOL_REVISION]:
                _verify_current_schema(tables, other_objects, cursor, database_root)
                return "CURRENT"
            if not revisions:
                raise MigrationError("PARTIAL_SCHEMA")
            raise MigrationError("UNSUPPORTED_SCHEMA_REVISION")
    except MigrationError:
        raise
    except Exception:  # noqa: BLE001 - SQL driver errors may include connection data.
        raise MigrationError("DATABASE_PREFLIGHT_FAILED") from None


def _require_unprepared_workspace_files(workspace: Path) -> None:
    for name in (
        "runtime.private.dpapi",
        "school-auth.private.dpapi",
        "runtime-ready.json",
        "school-accounts.private.dpapi",
    ):
        path = workspace / name
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            raise MigrationError("WORKSPACE_STATE_COULD_NOT_BE_VERIFIED") from None
        try:
            _reject_reparse_path(path)
        except (ResumeError, OSError):
            raise MigrationError("WORKSPACE_STATE_REPARSE_REJECTED") from None
        raise MigrationError("WORKSPACE_ALREADY_PREPARED")


def _migration_environment(source: dict[str, str], database_url: str) -> dict[str, str]:
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERNAME"}
    clean = {key: value for key, value in source.items() if key.upper() in allowed}
    clean["DATABASE_URL"] = database_url
    return clean


_METADATA_ENV_KEYS = {
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "TEMP",
    "TMP",
    "USERNAME",
    "USERPROFILE",
    "LOCALAPPDATA",
}


class MigrationOperations(ResumeOperations):
    """Windows-only effects; tests replace DB connection and Alembic runner."""

    @staticmethod
    def _metadata_environment(
        source: dict[str, str], **parameters: str
    ) -> dict[str, str]:
        environment = {
            key: value
            for key, value in source.items()
            if key.upper() in _METADATA_ENV_KEYS
        }
        environment.update(parameters)
        return environment

    @staticmethod
    def _run_metadata_powershell(
        script: str, environment: dict[str, str], *, error_code: str
    ) -> str:
        try:
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script],
                env=environment,
                capture_output=True,
                text=False,
                check=True,
                timeout=15,
            )
            if not isinstance(result.stdout, bytes):
                raise MigrationError(error_code)
            return result.stdout.decode("utf-8-sig")
        except MigrationError:
            raise
        except Exception:  # noqa: BLE001 - metadata subprocess output remains private.
            raise MigrationError(error_code) from None

    def verify_acl(self, workspace: Path) -> None:
        if os.name != "nt":
            raise MigrationError("WINDOWS_REQUIRED")
        script = r"""
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$acl = Get-Acl -LiteralPath $env:PSYNOVA_MIGRATION_WORKSPACE
$rules = @($acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))
$unexpected = @(
    $rules | Where-Object {
        $_.IdentityReference.Value -ne $sid -or $_.IsInherited -or
        $_.AccessControlType -ne 'Allow'
    }
)
$fullControl = [System.Security.AccessControl.FileSystemRights]::FullControl
$hasFullControl = ($rules[0].FileSystemRights -band $fullControl) -eq $fullControl
$private = $acl.AreAccessRulesProtected -and $rules.Count -eq 1 -and
    $unexpected.Count -eq 0 -and $hasFullControl
if ($private) { 'PRIVATE' } else { 'NOT_PRIVATE' }
"""
        output = self._run_metadata_powershell(
            script,
            self._metadata_environment(
                dict(os.environ), PSYNOVA_MIGRATION_WORKSPACE=str(workspace)
            ),
            error_code="WORKSPACE_ACL_UNAVAILABLE",
        )
        if output.strip() != "PRIVATE":
            raise MigrationError("WORKSPACE_ACL_INVALID")

    def inspect_process(self, pid: int) -> dict[str, Any] | None:
        script = r"""
$p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $env:PSYNOVA_MIGRATION_PID)
if ($null -eq $p) { 'null'; exit 0 }
@{
    ProcessId = $p.ProcessId
    ParentProcessId = $p.ParentProcessId
    ExecutablePath = $p.ExecutablePath
    CommandLine = $p.CommandLine
    CreationUtc = $p.CreationDate.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffffffZ')
} | ConvertTo-Json -Compress
"""
        output = self._run_metadata_powershell(
            script,
            self._metadata_environment(
                dict(os.environ), PSYNOVA_MIGRATION_PID=str(pid)
            ),
            error_code="PROCESS_IDENTITY_UNAVAILABLE",
        )
        try:
            value = json.loads(output or "null")
            return value if isinstance(value, dict) else None
        except Exception:  # noqa: BLE001 - process details stay private.
            raise MigrationError("PROCESS_IDENTITY_UNAVAILABLE") from None

    def listeners(self, port: int) -> list[dict[str, Any]]:
        script = r"""
$values = @(
    Get-NetTCPConnection -State Listen `
        -LocalPort $env:PSYNOVA_MIGRATION_PORT `
        -ErrorAction SilentlyContinue |
        Select-Object OwningProcess,LocalAddress,LocalPort
)
$values | ConvertTo-Json -Depth 3 -Compress
"""
        output = self._run_metadata_powershell(
            script,
            self._metadata_environment(
                dict(os.environ), PSYNOVA_MIGRATION_PORT=str(port)
            ),
            error_code="LISTENER_INSPECTION_UNAVAILABLE",
        )
        try:
            value = json.loads(output or "[]")
            if value is None:
                return []
            return value if isinstance(value, list) else [value]
        except Exception:  # noqa: BLE001 - listener details stay private.
            raise MigrationError("LISTENER_INSPECTION_UNAVAILABLE") from None

    def verify_running_process(self, marker: dict[str, Any]) -> None:
        """Check guardian, listener scope and loopback binding without shared full-env helpers."""
        try:
            guardian_pid = int(marker["parent_pid"])
            guardian = self.inspect_process(guardian_pid)
            if guardian is None or not _process_matches(guardian, marker):
                raise MigrationError("GUARDIAN_IDENTITY_INVALID")
            expected_argv = _expected_service_argv(marker)
            if not _command_matches(guardian, expected_argv):
                raise MigrationError("GUARDIAN_ARGUMENTS_INVALID")
            port = int(marker["port"])
            listeners = self.listeners(port)
            _require_loopback_listeners(listeners, port)
            for listener in listeners:
                owner_pid = int(listener.get("OwningProcess", -1))
                if owner_pid <= 0:
                    raise MigrationError("LISTENER_OWNER_INVALID")
                if owner_pid == guardian_pid:
                    continue
                child = self.inspect_process(owner_pid)
                if child is None or not _direct_guardian_child_matches(
                    child, owner_pid, guardian_pid, guardian, marker, expected_argv
                ):
                    raise MigrationError("LISTENER_PROCESS_IDENTITY_INVALID")
        except MigrationError:
            raise
        except Exception:  # noqa: BLE001 - process details remain private.
            raise MigrationError("GUARDIAN_VERIFICATION_FAILED") from None

    def connect_builder(self, marker: dict[str, Any], password: str):
        try:
            import pymysql

            return pymysql.connect(
                host=HOST,
                port=int(marker["port"]),
                user=BUILDER_USER,
                password=password,
                database=DATABASE,
                connect_timeout=8,
                read_timeout=20,
                write_timeout=20,
                autocommit=False,
            )
        except Exception:  # noqa: BLE001 - driver errors may include connection data.
            raise MigrationError("DATABASE_CONNECTION_FAILED") from None

    def run_alembic(
        self, database_python: Path, database_root: Path, database_url: str
    ) -> int:
        if not database_python.is_file():
            raise MigrationError("DATABASE_ENV_UNAVAILABLE")
        migration_file = (
            database_root
            / "migrations"
            / "versions"
            / f"{CURRENT_SCHOOL_REVISION}_school_feedback_publication.py"
        )
        if not migration_file.is_file():
            raise MigrationError("PINNED_MIGRATION_UNAVAILABLE")
        argv = [
            str(database_python),
            "-m",
            "alembic",
            "-c",
            str(database_root / "alembic.ini"),
            "upgrade",
            CURRENT_SCHOOL_REVISION,
        ]
        environment = _migration_environment(dict(os.environ), database_url)
        options: dict[str, Any] = {
            "cwd": database_root,
            "env": environment,
            "stdin": subprocess.DEVNULL,
            "capture_output": True,
            "text": False,
            "timeout": MIGRATION_TIMEOUT_SECONDS,
            "shell": False,
            "close_fds": True,
        }
        if os.name == "nt":
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            options["startupinfo"] = startup
            options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            return subprocess.run(argv, check=False, **options).returncode
        except subprocess.TimeoutExpired:
            raise MigrationError("MIGRATION_TIMEOUT", partial=True) from None
        except OSError:
            raise MigrationError("MIGRATION_LAUNCH_FAILED") from None


class SchoolWorkspaceMigrator:
    def __init__(
        self,
        repo: Path,
        operations: MigrationOperations | None = None,
        private_reader=read_private,
        lock_factory=workspace_lock,
    ):
        self.repo = Path(repo).resolve(strict=True)
        self.operations = operations or MigrationOperations()
        self.private_reader = private_reader
        self.lock_factory = lock_factory
        self.database_root = self.repo / "11_database"
        self.database_python = self.database_root / ".venv" / "Scripts" / "python.exe"

    def plan(self, workspace: Path, *, expected_port: int, workspace_id: str):
        if not self.operations.is_supported_platform():
            raise MigrationError("WINDOWS_REQUIRED")
        _validate_request(workspace, self.repo, expected_port, workspace_id)
        return {
            "status": "PLAN_ONLY",
            "workspace_id": workspace_id,
            "port": expected_port,
            "database": DATABASE,
            "current_revision": CURRENT_SCHOOL_REVISION,
            "schema_state": "NOT_INSPECTED",
            "database_environment_available": self.database_python.is_file(),
            "guardian_checks": "NOT_RUN",
            "schema_connection": "NOT_RUN",
            "side_effects": [],
        }

    def upgrade(self, workspace: Path, *, expected_port: int, workspace_id: str):
        if not self.operations.is_supported_platform():
            raise MigrationError("WINDOWS_REQUIRED")
        _validate_request(workspace, self.repo, expected_port, workspace_id)
        lock = self.lock_factory(Path(workspace))
        try:
            lock.__enter__()
        except (ResumeError, OSError):
            raise MigrationError("WORKSPACE_LOCK_UNAVAILABLE") from None
        try:
            marker = _validate_request(
                workspace, self.repo, expected_port, workspace_id
            )
            result = self._upgrade_locked(
                workspace, marker, expected_port, workspace_id
            )
        except BaseException as original:
            exception_info = sys.exc_info()
            try:
                lock.__exit__(*exception_info)
            except BaseException:  # noqa: BLE001 - preserve the primary operation result.
                if isinstance(original, MigrationError):
                    raise MigrationError(
                        original.code, partial=original.partial
                    ) from None
                raise original.with_traceback(exception_info[2]) from None
            raise
        try:
            lock.__exit__(None, None, None)
        except Exception:  # noqa: BLE001 - lock errors stay fixed and non-sensitive.
            raise MigrationError(
                "WORKSPACE_LOCK_RELEASE_FAILED",
                partial=result.get("status") == "MIGRATED",
            ) from None
        return result

    def _upgrade_locked(
        self,
        workspace: Path,
        marker: dict[str, Any],
        expected_port: int,
        workspace_id: str,
    ):
        _verify_guardian(marker, self.operations)

        private_path = Path(workspace) / "database.private.dpapi"
        _reject_reparse_path(private_path)
        private: dict[str, Any] | None = None
        password: str | None = None
        database_url: str | None = None
        try:
            private = self.private_reader(private_path)
        except Exception:  # noqa: BLE001 - DPAPI errors must not surface details.
            raise MigrationError("SEALED_BUILDER_SETTINGS_UNAVAILABLE") from None
        try:
            password = _validate_builder(private, marker)

            connection = self.operations.connect_builder(marker, password)
            try:
                state = _database_state(connection, marker, self.database_root)
            finally:
                try:
                    connection.close()
                except Exception:  # noqa: BLE001 - close error details stay private.
                    raise MigrationError("DATABASE_CONNECTION_CLOSE_FAILED") from None

            if state == "CURRENT":
                return {
                    "status": "ALREADY_CURRENT",
                    "workspace_id": workspace_id,
                    "revision": CURRENT_SCHOOL_REVISION,
                    "side_effects": [],
                }
            if state != "EMPTY":
                raise MigrationError("DATABASE_STATE_UNSUPPORTED")
            _require_unprepared_workspace_files(Path(workspace))

            # Repeat process/DACL/listener checks immediately before schema DDL.
            _verify_guardian(marker, self.operations)
            database_url = (
                f"mysql+aiomysql://{BUILDER_USER}:{password}@{HOST}:"
                f"{expected_port}/{DATABASE}?charset=utf8mb4"
            )
            try:
                return_code = self.operations.run_alembic(
                    self.database_python, self.database_root, database_url
                )
            except MigrationError as exc:
                raise MigrationError(exc.code, partial=True) from None
            except Exception:  # noqa: BLE001 - subprocess details may include the URL.
                raise MigrationError("MIGRATION_FAILED", partial=True) from None
            if return_code != 0:
                raise MigrationError("MIGRATION_FAILED", partial=True)

            # DDL is not assumed atomic. Reconnect and require the exact pinned row.
            try:
                _verify_guardian(marker, self.operations)
            except MigrationError as exc:
                raise MigrationError(exc.code, partial=True) from None
            try:
                connection = self.operations.connect_builder(marker, password)
            except MigrationError:
                raise MigrationError(
                    "POST_MIGRATION_CHECK_FAILED", partial=True
                ) from None
            try:
                final_state = _database_state(connection, marker, self.database_root)
            except MigrationError:
                raise MigrationError(
                    "POST_MIGRATION_CHECK_FAILED", partial=True
                ) from None
            finally:
                try:
                    connection.close()
                except Exception:  # noqa: BLE001 - close error details stay private.
                    raise MigrationError(
                        "POST_MIGRATION_CHECK_FAILED", partial=True
                    ) from None
            if final_state != "CURRENT":
                raise MigrationError("POST_MIGRATION_CHECK_FAILED", partial=True)
            return {
                "status": "MIGRATED",
                "workspace_id": workspace_id,
                "revision": CURRENT_SCHOOL_REVISION,
                "side_effects": ["schema_upgrade"],
            }
        finally:
            if private is not None:
                private.clear()
            password = None
            database_url = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "upgrade"))
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--expected-port", type=int, required=True)
    parser.add_argument("--workspace-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    migrator = SchoolWorkspaceMigrator(Path(__file__).resolve().parents[1])
    try:
        if args.command == "plan":
            result = migrator.plan(
                args.workspace,
                expected_port=args.expected_port,
                workspace_id=args.workspace_id,
            )
        else:
            result = migrator.upgrade(
                args.workspace,
                expected_port=args.expected_port,
                workspace_id=args.workspace_id,
            )
        print(json.dumps(result, sort_keys=True))
        return 0
    except MigrationError as exc:
        print(
            json.dumps(
                {
                    "status": "PARTIAL_FAILURE" if exc.partial else "BLOCKED",
                    "code": exc.code,
                },
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
