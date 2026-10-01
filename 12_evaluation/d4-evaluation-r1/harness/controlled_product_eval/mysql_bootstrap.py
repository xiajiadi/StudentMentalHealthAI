"""Fresh, loopback-only MySQL provisioning for a single D4-3B attempt."""

from __future__ import annotations

import re
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .credential_provider import (
    DatabaseCredential,
    credential_evidence_metadata,
)
from .environment_profiles import (
    D4_TASK_TOOLS_ROOT,
    MYSQL_BASEDIR,
    MYSQLD_EXECUTABLE,
    MYSQL_VERSION,
)
from .process_lifecycle import (
    LifecycleError,
    ProcessSpec,
    ProcessSupervisor,
    run_managed_command,
)


EXPECTED_REVISION = "20260906_0002"
APP_PRIVILEGES = (
    "ALTER",
    "CREATE",
    "DELETE",
    "INDEX",
    "INSERT",
    "REFERENCES",
    "SELECT",
    "UPDATE",
)
_BOOTSTRAP_PASSWORD_ENV = "D4_EVAL_APP_PASSWORD"
_EXPECTED_DATA_DIR_ENV = "D4_EVAL_EXPECTED_DATADIR"
_MYSQL_BOOTSTRAP_SCRIPT = r'''
import os
import sys
import pymysql

APP_USER = "smhai_eval_app"
APP_HOST = "127.0.0.1"
APP_DATABASE = "smhai_d4_evaluation"
APP_PASSWORD = os.environ["D4_EVAL_APP_PASSWORD"]
EXPECTED_DATADIR = os.environ["D4_EVAL_EXPECTED_DATADIR"]

def normalize_path(value):
    return os.path.normcase(os.path.normpath(os.path.abspath(value))).rstrip("\\/")

def connect(user, password, database=None):
    return pymysql.connect(
        host="127.0.0.1",
        port=3307,
        user=user,
        password=password,
        database=database,
        charset="utf8mb4",
        connect_timeout=5,
        read_timeout=5,
        write_timeout=5,
        autocommit=True,
    )

root = None
app = None
try:
    root = connect("root", "")
    with root.cursor() as cursor:
        cursor.execute(
            "SELECT VERSION(), @@datadir, @@port, @@bind_address, @@general_log"
        )
        version, datadir, port, bind_address, general_log = cursor.fetchone()
        if not str(version).startswith("8.4.8"):
            raise RuntimeError("version")
        if normalize_path(datadir) != normalize_path(EXPECTED_DATADIR):
            raise RuntimeError("datadir")
        if int(port) != 3307 or str(bind_address) != "127.0.0.1":
            raise RuntimeError("endpoint")
        if str(general_log).upper() not in {"0", "OFF"}:
            raise RuntimeError("general-log")
        cursor.execute(
            "SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA "
            "WHERE SCHEMA_NAME=%s",
            (APP_DATABASE,),
        )
        if cursor.fetchone() is not None:
            raise RuntimeError("database-exists")
        cursor.execute(
            "CREATE DATABASE `smhai_d4_evaluation` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
        )
        cursor.execute(
            "CREATE USER `smhai_eval_app`@`127.0.0.1` "
            "IDENTIFIED WITH caching_sha2_password BY %s",
            (APP_PASSWORD,),
        )
        cursor.execute(
            "GRANT ALTER, CREATE, DELETE, INDEX, INSERT, REFERENCES, "
            "SELECT, UPDATE ON `smhai_d4_evaluation`.* "
            "TO `smhai_eval_app`@`127.0.0.1`"
        )
        cursor.execute(
            "SHOW GRANTS FOR `smhai_eval_app`@`127.0.0.1`"
        )
        grants = [str(row[0]).upper() for row in cursor.fetchall()]
        schema_grants = [
            grant for grant in grants
            if " ON `SMHAI_D4_EVALUATION`.* " in grant
        ]
        global_grants = [
            grant for grant in grants
            if " ON *.* " in grant and "GRANT USAGE ON *.*" not in grant
        ]
        if len(schema_grants) != 1 or global_grants:
            raise RuntimeError("grant-scope")
        if not all(privilege in schema_grants[0] for privilege in (
            "ALTER", "CREATE", "DELETE", "INDEX", "INSERT",
            "REFERENCES", "SELECT", "UPDATE",
        )):
            raise RuntimeError("grant-list")

    app = connect(APP_USER, APP_PASSWORD, APP_DATABASE)
    with app.cursor() as cursor:
        cursor.execute("SELECT CURRENT_USER(), DATABASE(), @@datadir")
        current_user, database, datadir = cursor.fetchone()
        if not str(current_user).lower().startswith("smhai_eval_app@"):
            raise RuntimeError("app-user")
        if database != APP_DATABASE:
            raise RuntimeError("app-database")
        if normalize_path(datadir) != normalize_path(EXPECTED_DATADIR):
            raise RuntimeError("app-datadir")
    print("D4_MYSQL_BOOTSTRAP=PASS")
except Exception:
    print("D4_MYSQL_BOOTSTRAP=FAIL", file=sys.stderr)
    sys.exit(31)
finally:
    if app is not None:
        app.close()
    if root is not None:
        root.close()
'''


class MySqlBootstrapError(RuntimeError):
    """A fresh isolated MySQL bootstrap failed without exposing details."""


@dataclass(frozen=True, slots=True)
class MySqlBootstrapEvidence:
    host: str
    port: int
    version: str
    database: str
    app_user: str
    privileges: tuple[str, ...]
    datadir: str
    migration_revision: str
    alembic_drift_check: str
    readiness: str
    credential: dict[str, object]

    def as_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "version": self.version,
            "database": self.database,
            "app_user": self.app_user,
            "privileges": list(self.privileges),
            "datadir": self.datadir,
            "migration_revision": self.migration_revision,
            "alembic_drift_check": self.alembic_drift_check,
            "readiness": self.readiness,
            "credential": dict(self.credential),
        }


class IsolatedMySqlBootstrap:
    """Create and own a new MySQL 8.4.8 data directory for this attempt."""

    def __init__(
        self,
        *,
        repo_root: str | Path,
        run_root: str | Path,
        backend_python: str | Path,
        credential: DatabaseCredential | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.run_root = Path(run_root).resolve()
        self.backend_python = Path(backend_python).resolve()
        self.credential = credential
        self.mysql_root = self.run_root / "mysql"
        self.datadir = self.mysql_root / "data"
        self.logs = self.mysql_root / "logs"
        self._started = False

    async def start_server(self, supervisor: ProcessSupervisor) -> dict[str, Any]:
        """Initialize and start the fresh loopback server before app credential generation."""

        self._validate_fixed_profile()
        self._validate_new_datadir()
        self._validate_port_free()
        self._verify_binary_version()
        self.datadir.mkdir(parents=True, exist_ok=False)
        self._initialize_datadir()

        await supervisor.start_service(self.server_spec())
        self._started = True
        self._verify_server_identity()
        return {
            "host": "127.0.0.1",
            "port": 3307,
            "version": MYSQL_VERSION,
            "datadir": str(self.datadir.resolve()),
            "readiness": "PASS",
        }

    def provision_database(self, credential: DatabaseCredential) -> MySqlBootstrapEvidence:
        if not self._started:
            raise MySqlBootstrapError("MYSQL_SERVER_NOT_STARTED")
        self._validate_credential(credential)
        self.credential = credential
        self._create_app_database_and_user()
        self._run_alembic("upgrade", "head")
        current = self._run_alembic("current")
        current_text = (current.stdout + current.stderr).decode(
            "utf-8", errors="replace"
        )
        if EXPECTED_REVISION not in current_text:
            raise MySqlBootstrapError("MYSQL_MIGRATION_REVISION_MISMATCH")
        drift = self._run_alembic("check")
        drift_text = (drift.stdout + drift.stderr).decode(
            "utf-8", errors="replace"
        )
        if "No new upgrade operations detected" not in drift_text:
            raise MySqlBootstrapError("MYSQL_ALEMBIC_DRIFT_CHECK_FAILED")
        self._verify_app_readiness()
        return MySqlBootstrapEvidence(
            host=self.credential.host,
            port=self.credential.port,
            version=MYSQL_VERSION,
            database=self.credential.database,
            app_user=self.credential.username,
            privileges=APP_PRIVILEGES,
            datadir=str(self.datadir.resolve()),
            migration_revision=EXPECTED_REVISION,
            alembic_drift_check="PASS",
            readiness="PASS",
            credential=credential_evidence_metadata(),
        )

    def server_spec(self) -> ProcessSpec:
        pid_file = self.mysql_root / "mysqld.pid"
        arguments = (
            "--no-defaults",
            f"--basedir={MYSQL_BASEDIR.resolve()}",
            f"--datadir={self.datadir.resolve()}",
            "--bind-address=127.0.0.1",
            "--port=3307",
            "--mysqlx=OFF",
            "--general-log=OFF",
            "--slow-query-log=OFF",
            "--local-infile=OFF",
            "--secure-file-priv=NULL",
            f"--pid-file={pid_file.resolve()}",
        )
        return ProcessSpec(
            name="d4-mysql",
            executable=MYSQLD_EXECUTABLE.resolve(),
            arguments=arguments,
            cwd=MYSQL_BASEDIR.resolve(),
            environment={},
            readiness_url="tcp://127.0.0.1:3307",
            readiness_kind="tcp",
            log_path=self.logs / "server.stdout.log",
            stderr_log_path=self.logs / "server.stderr.log",
            package_lock_identity={"mysql_server_version": MYSQL_VERSION},
            environment_allowlist=frozenset(),
        )

    def _validate_fixed_profile(self) -> None:
        if not self.backend_python.is_absolute() or not self.backend_python.is_file():
            raise MySqlBootstrapError("BACKEND_PYTHON_UNAVAILABLE")
        if not MYSQLD_EXECUTABLE.is_absolute() or not MYSQLD_EXECUTABLE.is_file():
            raise MySqlBootstrapError("MYSQL_SERVER_UNAVAILABLE")
        if not MYSQL_BASEDIR.is_absolute() or not MYSQL_BASEDIR.is_dir():
            raise MySqlBootstrapError("MYSQL_BASEDIR_UNAVAILABLE")
        try:
            self.run_root.relative_to(D4_TASK_TOOLS_ROOT.resolve())
        except ValueError:
            raise MySqlBootstrapError("MYSQL_RUN_ROOT_OUTSIDE_PINNED_TASK_TOOLS") from None
        try:
            self.run_root.relative_to(self.repo_root)
        except ValueError:
            pass
        else:
            raise MySqlBootstrapError("MYSQL_RUN_ROOT_MUST_BE_OUTSIDE_REPOSITORY")

    def _validate_credential(self, credential: DatabaseCredential) -> None:
        if credential.host != "127.0.0.1" or credential.port != 3307:
            raise MySqlBootstrapError("MYSQL_ENDPOINT_PROFILE_MISMATCH")
        if credential.database != "smhai_d4_evaluation" or credential.username != "smhai_eval_app":
            raise MySqlBootstrapError("MYSQL_APPLICATION_PROFILE_MISMATCH")
        self.credential = credential

    def _validate_new_datadir(self) -> None:
        try:
            self.datadir.relative_to(self.repo_root)
        except ValueError:
            pass
        else:
            raise MySqlBootstrapError("MYSQL_DATADIR_MUST_BE_OUTSIDE_REPOSITORY")
        if self.datadir.exists():
            raise MySqlBootstrapError("MYSQL_DATADIR_MUST_BE_NEW")

    @staticmethod
    def _validate_port_free() -> None:
        try:
            with socket.create_connection(("127.0.0.1", 3307), timeout=0.2):
                raise MySqlBootstrapError("MYSQL_PORT_3307_ALREADY_IN_USE")
        except OSError:
            return

    def _verify_binary_version(self) -> None:
        self.logs.mkdir(parents=True, exist_ok=True)
        result = run_managed_command(
            name="mysql-version-check",
            executable=MYSQLD_EXECUTABLE.resolve(),
            arguments=("--version",),
            cwd=MYSQL_BASEDIR.resolve(),
            environment={},
            environment_allowlist=frozenset(),
            stdout_path=self.logs / "version.stdout.log",
            stderr_path=self.logs / "version.stderr.log",
            timeout_seconds=10,
        )
        version_text = (result.stdout + result.stderr).decode(
            "utf-8", errors="replace"
        )
        if not re.search(r"\bVer\s+8\.4\.8\b", version_text):
            raise MySqlBootstrapError("MYSQL_SERVER_VERSION_MISMATCH")

    def _initialize_datadir(self) -> None:
        try:
            result = run_managed_command(
                name="mysql-initialize",
                executable=MYSQLD_EXECUTABLE.resolve(),
                arguments=(
                    "--no-defaults",
                    "--initialize-insecure",
                    f"--basedir={MYSQL_BASEDIR.resolve()}",
                    f"--datadir={self.datadir.resolve()}",
                ),
                cwd=MYSQL_BASEDIR.resolve(),
                environment={},
                environment_allowlist=frozenset(),
                stdout_path=self.logs / "initialize.stdout.log",
                stderr_path=self.logs / "initialize.stderr.log",
                timeout_seconds=180,
            )
        except LifecycleError:
            raise MySqlBootstrapError("MYSQL_DATA_DIRECTORY_INITIALIZATION_FAILED") from None
        if result.return_code != 0:
            raise MySqlBootstrapError("MYSQL_DATA_DIRECTORY_INITIALIZATION_FAILED")

    def _verify_server_identity(self) -> None:
        script = r'''
import os
import sys
import pymysql

def normalize_path(value):
    return os.path.normcase(os.path.normpath(os.path.abspath(value))).rstrip("\\/")

connection = None
try:
    connection = pymysql.connect(
        host="127.0.0.1", port=3307, user="root", password="",
        connect_timeout=5, read_timeout=5, write_timeout=5, autocommit=True,
    )
    with connection.cursor() as cursor:
        cursor.execute("SELECT VERSION(), @@datadir, @@port, @@bind_address, @@general_log")
        version, datadir, port, bind_address, general_log = cursor.fetchone()
    expected_datadir = os.environ["D4_EVAL_EXPECTED_DATADIR"]
    if not str(version).startswith("8.4.8"):
        raise RuntimeError("version")
    if normalize_path(datadir) != normalize_path(expected_datadir):
        raise RuntimeError("datadir")
    if int(port) != 3307 or str(bind_address) != "127.0.0.1":
        raise RuntimeError("endpoint")
    if str(general_log).upper() not in {"0", "OFF"}:
        raise RuntimeError("general-log")
    print("D4_MYSQL_SERVER_IDENTITY=PASS")
except Exception:
    print("D4_MYSQL_SERVER_IDENTITY=FAIL", file=sys.stderr)
    sys.exit(31)
finally:
    if connection is not None:
        connection.close()
'''
        environment = {_EXPECTED_DATA_DIR_ENV: str(self.datadir.resolve())}
        try:
            result = run_managed_command(
                name="mysql-server-identity",
                executable=self.backend_python,
                arguments=("-c", script),
                cwd=self.repo_root,
                environment=environment,
                environment_allowlist=frozenset(environment),
                stdout_path=self.logs / "server-identity.stdout.log",
                stderr_path=self.logs / "server-identity.stderr.log",
                timeout_seconds=30,
            )
        except LifecycleError:
            raise MySqlBootstrapError("MYSQL_SERVER_IDENTITY_CHECK_FAILED") from None
        if result.return_code != 0 or b"D4_MYSQL_SERVER_IDENTITY=PASS" not in result.stdout:
            raise MySqlBootstrapError("MYSQL_SERVER_IDENTITY_CHECK_FAILED")

    def _database_secret_environment(self) -> dict[str, str]:
        if self.credential is None:
            raise MySqlBootstrapError("MYSQL_APPLICATION_CREDENTIAL_MISSING")
        return {
            _BOOTSTRAP_PASSWORD_ENV: self.credential.password,
            _EXPECTED_DATA_DIR_ENV: str(self.datadir.resolve()),
        }

    def _create_app_database_and_user(self) -> None:
        try:
            result = run_managed_command(
                name="mysql-application-bootstrap",
                executable=self.backend_python,
                arguments=("-c", _MYSQL_BOOTSTRAP_SCRIPT),
                cwd=self.repo_root,
                environment=self._database_secret_environment(),
                environment_allowlist=frozenset(
                    {_BOOTSTRAP_PASSWORD_ENV, _EXPECTED_DATA_DIR_ENV}
                ),
                stdout_path=self.logs / "application-bootstrap.stdout.log",
                stderr_path=self.logs / "application-bootstrap.stderr.log",
                timeout_seconds=60,
            )
        except LifecycleError:
            raise MySqlBootstrapError("MYSQL_APPLICATION_BOOTSTRAP_FAILED") from None
        if result.return_code != 0 or b"D4_MYSQL_BOOTSTRAP=PASS" not in result.stdout:
            raise MySqlBootstrapError("MYSQL_APPLICATION_BOOTSTRAP_FAILED")

    def _run_alembic(self, *arguments: str):
        if self.credential is None:
            raise MySqlBootstrapError("MYSQL_APPLICATION_CREDENTIAL_MISSING")
        config_path = self.repo_root / "11_database" / "alembic.ini"
        database_path = self.repo_root / "11_database"
        if not config_path.is_file() or not database_path.is_dir():
            raise MySqlBootstrapError("MYSQL_ALEMBIC_CONFIGURATION_UNAVAILABLE")
        password = quote(self.credential.password, safe="-_")
        if password != self.credential.password:
            raise MySqlBootstrapError("MYSQL_CREDENTIAL_ENCODING_UNEXPECTED")
        database_url = (
            f"mysql+aiomysql://{self.credential.username}:{password}@"
            f"{self.credential.host}:{self.credential.port}/{self.credential.database}"
        )
        environment = {
            "PYTHONPATH": str(database_path.resolve()),
            "DATABASE_URL": database_url,
            "DB_PASSWORD": self.credential.password,
        }
        log_stem = "alembic-" + "-".join(arguments)
        try:
            return run_managed_command(
                name="mysql-" + log_stem,
                executable=self.backend_python,
                arguments=("-m", "alembic", "-c", str(config_path.resolve()), *arguments),
                cwd=self.repo_root,
                environment=environment,
                environment_allowlist=frozenset(environment),
                stdout_path=self.logs / f"{log_stem}.stdout.log",
                stderr_path=self.logs / f"{log_stem}.stderr.log",
                timeout_seconds=180,
            )
        except LifecycleError:
            raise MySqlBootstrapError("MYSQL_ALEMBIC_COMMAND_FAILED") from None

    def _verify_app_readiness(self) -> None:
        if self.credential is None:
            raise MySqlBootstrapError("MYSQL_APPLICATION_CREDENTIAL_MISSING")
        script = r'''
import os
import sys
import pymysql
try:
    connection = pymysql.connect(
        host="127.0.0.1", port=3307, user="smhai_eval_app",
        password=os.environ["D4_EVAL_APP_PASSWORD"],
        database="smhai_d4_evaluation", connect_timeout=5,
        read_timeout=5, write_timeout=5, autocommit=True,
    )
    with connection.cursor() as cursor:
        cursor.execute("SELECT version_num FROM database_alembic_version")
        rows = cursor.fetchall()
    connection.close()
    if len(rows) != 1 or rows[0][0] != "20260906_0002":
        raise RuntimeError("revision")
    print("D4_MYSQL_READINESS=PASS")
except Exception:
    print("D4_MYSQL_READINESS=FAIL", file=sys.stderr)
    sys.exit(31)
'''
        environment = {_BOOTSTRAP_PASSWORD_ENV: self.credential.password}
        try:
            result = run_managed_command(
                name="mysql-readiness-check",
                executable=self.backend_python,
                arguments=("-c", script),
                cwd=self.repo_root,
                environment=environment,
                environment_allowlist=frozenset(environment),
                stdout_path=self.logs / "readiness.stdout.log",
                stderr_path=self.logs / "readiness.stderr.log",
                timeout_seconds=30,
            )
        except LifecycleError:
            raise MySqlBootstrapError("MYSQL_READINESS_CHECK_FAILED") from None
        if result.return_code != 0 or b"D4_MYSQL_READINESS=PASS" not in result.stdout:
            raise MySqlBootstrapError("MYSQL_READINESS_CHECK_FAILED")
