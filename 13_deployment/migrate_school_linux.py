"""Apply the existing school schema migrations from a systemd credential."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

EXPECTED_REVISION = "20261016_0024"
EXPECTED_DATABASE = "smhai_school_demo"
MIGRATION_CREDENTIAL = "school-migration.json"
_MIGRATION_PHASES = frozenset(
    {
        "startup",
        "source_validation",
        "credential_load",
        "mysql_connect",
        "mysql_identity",
        "mysql_grants",
        "migration_history",
        "alembic_upgrade",
        "schema_verification",
    }
)
_FORBIDDEN_DATABASE_ENV = {
    "DB_USER",
    "DB_PASSWORD",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "MYSQL_PWD",
}


def _verify_migration_environment() -> None:
    if os.name != "posix" or sys.platform != "linux":
        raise RuntimeError("Linux systemd migration environment is required")
    if os.environ.get("DATABASE_AUTH_CREDENTIAL") != MIGRATION_CREDENTIAL:
        raise RuntimeError("systemd migration credential name is required")
    if "DATABASE_URL" in os.environ or any(
        name in os.environ for name in _FORBIDDEN_DATABASE_ENV
    ):
        raise RuntimeError("direct database environment credentials are forbidden")


def _revision_and_tables(connection) -> tuple[str | None, set[str]]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA=%s AND TABLE_TYPE='BASE TABLE'",
            (EXPECTED_DATABASE,),
        )
        tables = {row[0] for row in cursor.fetchall()}
        if "database_alembic_version" not in tables:
            return None, tables
        cursor.execute("SELECT version_num FROM database_alembic_version")
        rows = cursor.fetchall()
        if len(rows) != 1 or not isinstance(rows[0][0], str):
            raise RuntimeError("school migration state is inconsistent")
        return rows[0][0], tables


def _verify_migration_grants(grants: list[str], current_role: str) -> None:
    expected = {
        "CREATE",
        "ALTER",
        "INDEX",
        "REFERENCES",
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
    }
    if len(grants) != 2 or current_role != "NONE":
        raise RuntimeError("migration account privileges are unexpected")
    scopes: set[str] = set()
    privileges: set[str] = set()
    for grant in grants:
        if " ON " not in grant:
            raise RuntimeError("migration account privileges are unexpected")
        declared, scope = grant.split(" ON ", 1)
        scopes.add(scope.split(" TO ", 1)[0])
        if declared == "GRANT USAGE":
            continue
        if not declared.startswith("GRANT "):
            raise RuntimeError("migration account privileges are unexpected")
        privileges.update(
            value.strip() for value in declared.removeprefix("GRANT ").split(",")
        )
        if "WITH GRANT OPTION" in grant:
            raise RuntimeError("migration account privileges are unexpected")
    if scopes != {"*.*", f"`{EXPECTED_DATABASE}`.*"} or privileges != expected:
        raise RuntimeError("migration account privileges are unexpected")


def _run_alembic_upgrade(repository_root: Path, connection) -> None:
    """Run the existing migration chain over an already authenticated connection."""
    from alembic import command
    from alembic.config import Config

    config = Config(str(repository_root / "11_database" / "alembic.ini"))
    config.set_main_option(
        "script_location", str(repository_root / "11_database" / "migrations")
    )
    config.attributes["connection"] = connection
    command.upgrade(config, EXPECTED_REVISION)


def _verify_schema_structure(connection) -> dict[str, int]:
    from database_layer import (
        models as _models,  # noqa: F401 - register Alembic metadata.
    )
    from database_layer.base import Base
    from sqlalchemy import inspect

    inspector = inspect(connection)
    expected_tables = set(Base.metadata.tables) | {"database_alembic_version"}
    actual_tables = set(inspector.get_table_names())
    if actual_tables != expected_tables:
        raise RuntimeError(
            "migrated schema table set does not match the project metadata"
        )

    expected_foreign_keys = 0
    actual_foreign_keys = 0
    expected_checks = 0
    actual_checks = 0
    actual_unique_constraints = 0
    from sqlalchemy import (
        CheckConstraint,
        ForeignKeyConstraint,
        Index,
        UniqueConstraint,
    )

    expected_unique: set[tuple[str, tuple[str, ...]]] = set()
    actual_unique: set[tuple[str, tuple[str, ...]]] = set()
    for table in Base.metadata.sorted_tables:
        expected_foreign_keys += sum(
            isinstance(constraint, ForeignKeyConstraint)
            for constraint in table.constraints
        )
        expected_checks += sum(
            isinstance(constraint, CheckConstraint) for constraint in table.constraints
        )
        for constraint in table.constraints:
            if isinstance(constraint, UniqueConstraint):
                expected_unique.add(
                    (table.name, tuple(column.name for column in constraint.columns))
                )
        for index in table.indexes:
            if isinstance(index, Index) and index.unique:
                index_columns: list[str] = []
                for expression in index.expressions:
                    column_name = getattr(expression, "name", None)
                    if not isinstance(column_name, str):
                        break
                    index_columns.append(column_name)
                else:
                    expected_unique.add((table.name, tuple(index_columns)))
        actual_foreign_keys += len(inspector.get_foreign_keys(table.name))
        actual_checks += len(inspector.get_check_constraints(table.name))
        for constraint in inspector.get_unique_constraints(table.name):
            actual_unique.add((table.name, tuple(constraint.get("column_names") or ())))
        for index in inspector.get_indexes(table.name):
            if index.get("unique"):
                actual_unique.add((table.name, tuple(index.get("column_names") or ())))
    actual_unique_constraints = len(actual_unique)
    if (
        actual_foreign_keys != expected_foreign_keys
        or actual_checks != expected_checks
        or actual_unique != expected_unique
    ):
        raise RuntimeError(
            "migrated schema constraints do not match the project metadata"
        )

    with connection.exec_driver_sql(
        "SELECT COUNT(*), SUM(ENGINE='InnoDB'), SUM(TABLE_COLLATION='utf8mb4_0900_ai_ci') "
        "FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_TYPE='BASE TABLE'",
        (EXPECTED_DATABASE,),
    ) as result:
        table_total, innodb_total, collation_total = result.one()
    if (
        table_total != len(expected_tables)
        or innodb_total != table_total
        or collation_total != table_total
    ):
        raise RuntimeError("migrated schema table storage settings are inconsistent")
    return {
        "tables": len(expected_tables),
        "foreign_keys": actual_foreign_keys,
        "checks": actual_checks,
        "unique_constraints": actual_unique_constraints,
    }


def migrate(repository_root: Path) -> dict[str, object]:
    phase = "startup"
    try:
        phase = "source_validation"
        repo = repository_root.resolve(strict=True)
        sys.path.insert(0, str(repo / "11_database"))
        sys.path.insert(0, str(repo / "13_deployment"))
        _verify_migration_environment()

        phase = "credential_load"
        from database_layer.systemd_auth import load_systemd_school_database_credential
        from linux_school_runtime import _supported_mysql_version, mysql_url

        credential = load_systemd_school_database_credential(
            MIGRATION_CREDENTIAL, role="migrator"
        )
        import pymysql

        phase = "mysql_connect"
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
        try:
            phase = "mysql_identity"
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT VERSION(), @@port, DATABASE(), CURRENT_USER(), CURRENT_ROLE()"
                )
                identity = cursor.fetchone()
                if identity is None or len(identity) != 5:
                    raise RuntimeError("migration database identity could not be verified")
                version, port, database, current_user, current_role = identity
                if (
                    not isinstance(version, str)
                    or not _supported_mysql_version(version)
                    or port != 3306
                    or database != EXPECTED_DATABASE
                    or current_user != credential.username + "@127.0.0.1"
                ):
                    raise RuntimeError("migration target or MySQL version is unsupported")
                phase = "mysql_grants"
                cursor.execute("SHOW GRANTS FOR CURRENT_USER()")
                _verify_migration_grants(
                    [grant[0] for grant in cursor.fetchall()], current_role
                )
            phase = "migration_history"
            current_revision, tables = _revision_and_tables(connection)
            if tables and current_revision != EXPECTED_REVISION:
                raise RuntimeError(
                    "migration target is nonempty and is not at the expected current revision"
                )
        finally:
            connection.close()

        if not tables:
            phase = "alembic_upgrade"
            from sqlalchemy import create_engine
            from sqlalchemy.engine import make_url

            migration_url = make_url(mysql_url(credential)).set(
                drivername="mysql+pymysql"
            )
            migration_engine = create_engine(migration_url, pool_pre_ping=True)
            try:
                with migration_engine.connect() as migration_connection:
                    _run_alembic_upgrade(repo, migration_connection)
            finally:
                migration_engine.dispose()

        # Reconnect after DDL and verify revision, tables, constraints, engine and collation.
        phase = "schema_verification"
        from sqlalchemy import create_engine
        from sqlalchemy.engine import make_url

        inspection_url = make_url(mysql_url(credential)).set(
            drivername="mysql+pymysql"
        )
        engine = create_engine(inspection_url, pool_pre_ping=True)
        try:
            with engine.connect() as inspection_connection:
                revision, _ = _revision_and_tables(
                    inspection_connection.connection.driver_connection
                )
                if revision != EXPECTED_REVISION:
                    raise RuntimeError("expected Alembic head was not applied")
                structure = _verify_schema_structure(inspection_connection)
        finally:
            engine.dispose()
        return {
            "migration": "VERIFIED",
            "revision": EXPECTED_REVISION,
            "mysql_version": version,
            **structure,
        }
    except Exception as exc:  # noqa: BLE001 - expose only a bounded type and phase.
        error = _MigrationStageError(phase, type(exc).__name__)
        raise error from None


class _MigrationStageError(Exception):
    def __init__(self, phase: str, error_type: str) -> None:
        if phase not in _MIGRATION_PHASES or not error_type.isidentifier():
            phase, error_type = "startup", "InternalError"
        self.phase = phase
        self.error_type = error_type


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    try:
        print(json.dumps(migrate(args.repo_root), sort_keys=True))
        return 0
    except _MigrationStageError as exc:
        print(
            json.dumps(
                {
                    "migration": "BLOCKED",
                    "phase": exc.phase,
                    "error_type": exc.error_type,
                },
                sort_keys=True,
            )
        )
        return 2
    except Exception as exc:  # noqa: BLE001 - credential and SQL details must stay private.
        print(
            json.dumps(
                {
                    "migration": "BLOCKED",
                    "phase": "startup",
                    "error_type": type(exc).__name__,
                },
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
