"""Install the isolated Linux synthetic school demo after operator sudo authorization.

The default invocation is a read-only plan. --install performs the documented
one-time host, MySQL, credential-store, migration, seed, and loopback service setup.
It fails closed on any pre-existing target and never resets or drops a schema.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

SOURCE_STAGE = Path("/home/psynova/apps/psynova/staging/linux-school-demo")
APP_ROOT = Path("/opt/psynova-school-demo")
RELEASE_ROOT = APP_ROOT / "release"
VENV_ROOT = APP_ROOT / "venv"
SERVICE_USER = "psynova-school-demo"
SERVICE_GROUP = "psynova-school-demo"
DATABASE_NAME = "smhai_school_demo"
DATABASE_COLLATION = "utf8mb4_0900_ai_ci"
MYSQL_PORT = 3306
BACKEND_PORT = 8088
EXPECTED_REVISION = "20261016_0024"
CREDSTORE = Path("/etc/credstore.encrypted")
SYSTEMD_UNITS = Path("/etc/systemd/system")
RUN_UNITS = Path("/run/systemd/system")
UV_VERSION = "0.12.3"
_CRED_FILES = {
    "database-keys.json": "psynova-school-database-keys.cred",
    "school-runtime.json": "psynova-school-runtime.cred",
    "school-migration.json": "psynova-school-migration.cred",
    "school-seed-accounts.json": "psynova-school-seed-accounts.cred",
}
_PERMANENT_UNITS = (
    "psynova-school-demo.service",
    "psynova-school-credential-probe.service",
    "psynova-school-seed.service",
)
_RELEASE_PATHS = (
    "09_backend/README.md",
    "09_backend/pyproject.toml",
    "09_backend/uv.lock",
    "09_backend/src",
    "11_database/alembic.ini",
    "11_database/pyproject.toml",
    "11_database/uv.lock",
    "11_database/database_layer",
    "11_database/migrations",
    "13_deployment/linux_school_runtime.py",
    "13_deployment/school_backend_linux.py",
    "13_deployment/migrate_school_linux.py",
    "13_deployment/seed_school_linux.py",
    "13_deployment/probe_systemd_credentials.py",
    "13_deployment/verify_school_http_linux.py",
    "13_deployment/systemd/psynova-school-demo.service",
    "13_deployment/systemd/psynova-school-credential-probe.service",
    "13_deployment/systemd/psynova-school-migrate.service",
    "13_deployment/systemd/psynova-school-seed.service",
)
_INSTALL_PHASE = "not_started"
_LINUX_OS = cast(Any, os)


class InstallError(RuntimeError):
    pass


def _command(
    args: Sequence[str],
    *,
    input_bytes: bytes | None = None,
    env: Mapping[str, str] | None = None,
    timeout: int = 60,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            list(args),
            input=input_bytes,
            capture_output=True,
            env=None if env is None else dict(env),
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise InstallError("required host command could not be executed") from None
    if check and result.returncode != 0:
        raise InstallError(
            "required host command failed; inspect host state before retrying"
        )
    return result


def _output(result: subprocess.CompletedProcess[bytes]) -> str:
    try:
        return result.stdout.decode("utf-8").strip()
    except UnicodeError:
        raise InstallError("host command returned invalid metadata") from None


def _mysql(sql: str, *, timeout: int = 30, xml_output: bool = False) -> str:
    client = shutil.which("mysql")
    if not client:
        raise InstallError("MySQL client is unavailable")
    args = [
        client,
        "--no-defaults",
        "--protocol=socket",
        "--user=root",
    ]
    if xml_output:
        args.append("--xml")
    else:
        args.extend(["--batch", "--skip-column-names", "--raw"])
    result = _command(
        args,
        input_bytes=sql.encode("utf-8"),
        env={
            name: value
            for name, value in os.environ.items()
            if not name.startswith(("DB_", "DATABASE_", "MYSQL_", "SMHAI_"))
        },
        timeout=timeout,
    )
    return _output(result)


def _require_empty_output(sql: str) -> None:
    if _mysql(sql):
        raise InstallError("a requested MySQL schema or account already exists")


def _check_host_preconditions() -> dict[str, str]:
    if _LINUX_OS.geteuid() != 0:
        raise InstallError(
            "--install must be run through interactive sudo by the operator"
        )
    if not SOURCE_STAGE.is_dir() or SOURCE_STAGE.is_symlink():
        raise InstallError("staged PsyNova Linux release is unavailable")
    revision_file = SOURCE_STAGE / "SOURCE_REVISION"
    if revision_file.is_symlink() or not revision_file.is_file():
        raise InstallError("staged source revision manifest is unavailable")
    revision = revision_file.read_text(encoding="ascii").strip()
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise InstallError("staged source revision manifest is invalid")

    if APP_ROOT.exists() or APP_ROOT.is_symlink():
        raise InstallError(
            "Linux school demo install path already exists; inspect manually"
        )
    if _output(_command(["getent", "group", SERVICE_GROUP], check=False)):
        raise InstallError("the dedicated service group already exists")
    if _output(_command(["getent", "passwd", SERVICE_USER], check=False)):
        raise InstallError("the dedicated service account already exists")
    for name in _CRED_FILES.values():
        target = CREDSTORE / name
        if target.exists() or target.is_symlink():
            raise InstallError("an encrypted credential target already exists")
    for name in _PERMANENT_UNITS:
        if (SYSTEMD_UNITS / name).exists() or (SYSTEMD_UNITS / name).is_symlink():
            raise InstallError("a PsyNova systemd unit already exists")
        if (RUN_UNITS / name).exists() or (RUN_UNITS / name).is_symlink():
            raise InstallError("a PsyNova runtime unit already exists")
    migration_unit = "psynova-school-migrate.service"
    if (SYSTEMD_UNITS / migration_unit).exists() or (
        RUN_UNITS / migration_unit
    ).exists():
        raise InstallError("a PsyNova migration unit already exists")
    if shutil.which("systemd-creds") is None or shutil.which("systemctl") is None:
        raise InstallError("systemd credential tools are unavailable")
    for name in (*_CRED_FILES.values(),):
        if not name.endswith(".cred"):
            raise InstallError("encrypted credential file manifest is invalid")

    version_rows = _mysql(
        "SELECT CURRENT_USER(), VERSION(), @@port, @@global.bind_address;"
    )
    fields = version_rows.split("\t")
    if len(fields) != 4:
        raise InstallError("MySQL server identity could not be verified")
    admin_identity, version, port, bind_address = fields
    if admin_identity != "root@localhost":
        raise InstallError("MySQL administrator socket identity is not root@localhost")
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        raise InstallError("MySQL server version is unsupported")
    major, minor, patch = (int(part) for part in match.groups())
    if major != 8 or not ((minor == 0 and patch >= 16) or minor == 4):
        raise InstallError(
            "MySQL server version is outside the supported migration range"
        )
    if port != str(MYSQL_PORT) or bind_address != "127.0.0.1":
        raise InstallError("MySQL must bind only to 127.0.0.1:3306")
    _mysql_loopback_listeners()
    _require_empty_output(
        "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA "
        f"WHERE SCHEMA_NAME='{DATABASE_NAME}';"
    )

    systemd_version = _output(_command(["systemd-creds", "--version"]))
    if "systemd 255 " not in systemd_version:
        raise InstallError("the reviewed Ubuntu systemd 255 host baseline changed")
    return {
        "source_revision": revision,
        "mysql_version": version,
        "bind_address": bind_address,
    }


def _copy_source(revision: str) -> None:
    APP_ROOT.mkdir(mode=0o755)
    RELEASE_ROOT.mkdir(mode=0o755)
    for relative in _RELEASE_PATHS:
        source = SOURCE_STAGE / relative
        if source.is_symlink() or not source.exists():
            raise InstallError("staged release is incomplete or contains a symlink")
        destination = RELEASE_ROOT / relative
        destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        if source.is_dir():
            for parent, directories, files in os.walk(source, followlinks=False):
                parent_path = Path(parent)
                if parent_path.is_symlink() or any(
                    (parent_path / name).is_symlink() for name in directories + files
                ):
                    raise InstallError("staged release contains an unsupported symlink")
            shutil.copytree(source, destination, symlinks=False)
        else:
            shutil.copy2(source, destination, follow_symlinks=False)
    (RELEASE_ROOT / "SOURCE_REVISION").write_text(revision + "\n", encoding="ascii")
    for parent, _directories, files in os.walk(APP_ROOT, followlinks=False):
        current = Path(parent)
        _LINUX_OS.chown(current, 0, 0)
        os.chmod(current, 0o755)
        for name in files:
            item = current / name
            if item.is_symlink():
                raise InstallError("installed release contains a symlink")
            _LINUX_OS.chown(item, 0, 0)
            os.chmod(item, 0o644)


def _provision_python() -> Path:
    python = Path("/usr/bin/python3.12")
    if not python.is_file():
        raise InstallError("Python 3.12 is unavailable on the ECS")
    _command([str(python), "-m", "venv", str(VENV_ROOT)], timeout=120)
    venv_python = VENV_ROOT / "bin/python"
    _command(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-cache-dir",
            f"uv=={UV_VERSION}",
        ],
        timeout=600,
    )
    uv = VENV_ROOT / "bin/uv"
    if not uv.is_file():
        raise InstallError("locked dependency installer is unavailable")
    with tempfile.TemporaryDirectory(prefix="psynova-school-lock-") as temporary:
        backend_requirements = Path(temporary) / "backend-requirements.txt"
        database_requirements = Path(temporary) / "database-requirements.txt"
        _command(
            [
                str(uv),
                "export",
                "--directory",
                str(RELEASE_ROOT / "09_backend"),
                "--frozen",
                "--no-dev",
                "--no-emit-package",
                "student-mental-health-ai-backend",
                "--format",
                "requirements.txt",
                "--output-file",
                str(backend_requirements),
            ],
            timeout=120,
        )
        _command(
            [
                str(uv),
                "export",
                "--directory",
                str(RELEASE_ROOT / "11_database"),
                "--frozen",
                "--no-dev",
                "--no-emit-package",
                "student-mental-health-database",
                "--format",
                "requirements.txt",
                "--output-file",
                str(database_requirements),
            ],
            timeout=120,
        )
        if not backend_requirements.is_file() or not database_requirements.is_file():
            raise InstallError("locked dependency export is incomplete")
        _command(
            [
                str(uv),
                "pip",
                "sync",
                "--python",
                str(venv_python),
                "--require-hashes",
                str(backend_requirements),
                str(database_requirements),
            ],
            timeout=1800,
        )
    for item in (VENV_ROOT, *VENV_ROOT.rglob("*")):
        if item.is_symlink():
            continue
        _LINUX_OS.chown(item, 0, 0)
        if item.is_dir():
            os.chmod(item, 0o755)
        elif item.is_file():
            os.chmod(item, 0o755 if os.access(item, os.X_OK) else 0o644)
    return venv_python


def _ensure_service_account() -> None:
    if shutil.which("getent") and _output(
        _command(["getent", "group", SERVICE_GROUP], check=False)
    ):
        raise InstallError("the dedicated service group already exists")
    if shutil.which("getent") and _output(
        _command(["getent", "passwd", SERVICE_USER], check=False)
    ):
        raise InstallError("the dedicated service account already exists")
    _command(["groupadd", "--system", SERVICE_GROUP])
    _command(
        [
            "useradd",
            "--system",
            "--gid",
            SERVICE_GROUP,
            "--no-create-home",
            "--home-dir",
            "/nonexistent",
            "--shell",
            "/usr/sbin/nologin",
            SERVICE_USER,
        ]
    )


def _ensure_credential_store() -> None:
    if not CREDSTORE.exists():
        CREDSTORE.mkdir(mode=0o700, parents=True)
    metadata = CREDSTORE.stat(follow_symlinks=False)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise InstallError("system encrypted credential store is not protected")
    host_key = Path("/var/lib/systemd/credential.secret")
    if not host_key.exists():
        _command(["systemd-creds", "setup"], timeout=60)
    try:
        host_key_stat = host_key.stat(follow_symlinks=False)
    except OSError:
        raise InstallError("systemd host credential key is unavailable") from None
    if (
        not stat.S_ISREG(host_key_stat.st_mode)
        or host_key_stat.st_uid != 0
        or host_key_stat.st_nlink != 1
        or stat.S_IMODE(host_key_stat.st_mode) & 0o077
    ):
        raise InstallError("systemd host credential key is unavailable")


def _store_encrypted_credential(name: str, filename: str, plaintext: bytes) -> None:
    destination = CREDSTORE / filename
    result = _command(
        ["systemd-creds", f"--name={name}", "--with-key=host", "encrypt", "-", "-"],
        input_bytes=plaintext,
        timeout=60,
    )
    ciphertext = result.stdout
    if not ciphertext:
        raise InstallError("systemd could not create an encrypted credential")
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(ciphertext)
            stream.flush()
            os.fsync(stream.fileno())
        _LINUX_OS.chown(destination, 0, 0)
        os.chmod(destination, 0o600)
    except OSError:
        try:
            destination.unlink()
        except OSError:
            pass
        raise InstallError("encrypted credential could not be saved") from None


def _credential_payload(
    database_user: str, database_password: str, *, csrf: str | None
) -> bytes:
    payload = {
        "schema": "psynova.school-runtime.v1",
        "database": {
            "host": "127.0.0.1",
            "port": MYSQL_PORT,
            "name": DATABASE_NAME,
            "user": database_user,
            "password": database_password,
        },
    }
    if csrf is not None:
        payload["school_csrf_secret"] = csrf
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def _parse_generated_password(result: str, username: str) -> str:
    try:
        root = ET.fromstring(result)
    except ET.ParseError:
        raise InstallError("MySQL generated-account result is malformed") from None
    rows = root.findall("row") if root.tag == "resultset" else []
    if len(rows) != 1:
        raise InstallError("MySQL did not return the generated account secret")
    fields: dict[str, str] = {}
    for field in rows[0].findall("field"):
        name = field.get("name")
        if not name or name in fields:
            raise InstallError("MySQL generated an unexpected account result")
        fields[name] = "".join(field.itertext())
    if fields.get("user") != username or fields.get("host") != "127.0.0.1":
        raise InstallError("MySQL generated an unexpected account identity")
    password = fields.get("generated password", "")
    if re.fullmatch(r"[ -~]{20,255}", password) is None:
        raise InstallError("MySQL generated an unsupported account secret format")
    return password


def _set_install_phase(phase: str) -> None:
    global _INSTALL_PHASE
    _INSTALL_PHASE = phase


def _install_systemd_unit(name: str, *, runtime: bool = False) -> Path:
    source = RELEASE_ROOT / "13_deployment" / "systemd" / name
    destination_root = RUN_UNITS if runtime else SYSTEMD_UNITS
    destination = destination_root / name
    if source.is_symlink() or not source.is_file() or destination.exists():
        raise InstallError("systemd unit source or destination is unavailable")
    shutil.copyfile(source, destination, follow_symlinks=False)
    _LINUX_OS.chown(destination, 0, 0)
    os.chmod(destination, 0o644)
    _command(["systemctl", "daemon-reload"])
    return destination


def _start_and_verify_unit(name: str, *, timeout: int = 300) -> None:
    _command(["systemctl", "start", name], timeout=timeout)
    result = _output(
        _command(["systemctl", "show", name, "--property=Result", "--value"])
    )
    if result != "success":
        raise InstallError("a required systemd operation did not complete successfully")


def _mysql_loopback_listeners() -> list[str]:
    result = _output(
        _command(
            [
                "ss",
                "--listening",
                "--tcp",
                "--numeric",
                "--no-header",
                "sport",
                "=",
                f":{MYSQL_PORT}",
            ]
        )
    )
    addresses: list[str] = []
    for line in result.splitlines():
        fields = line.split()
        if len(fields) < 4:
            raise InstallError("MySQL listener could not be verified")
        address = fields[3]
        if address not in {"127.0.0.1:3306", "[::1]:3306"}:
            raise InstallError("MySQL is listening outside loopback")
        addresses.append(address)
    if not addresses:
        raise InstallError("MySQL has no loopback TCP listener")
    return addresses


def _wait_backend() -> None:
    deadline = time.monotonic() + 60
    request = urllib.request.Request("http://127.0.0.1:8088/health/live", method="GET")
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(1)
    raise InstallError("loopback Backend health endpoint did not become ready")


def install() -> dict[str, object]:
    os.umask(0o077)
    _set_install_phase("environment_sanitization")
    for name in tuple(os.environ):
        if name.startswith(
            ("DB_", "DATABASE_", "MYSQL_", "SMHAI_", "PYTHON", "UV_", "PIP_")
        ) or name in {"VIRTUAL_ENV", "CONDA_PREFIX"}:
            os.environ.pop(name, None)
    _set_install_phase("preflight")
    preflight = _check_host_preconditions()
    runtime_user = "psynova_runtime_" + secrets.token_hex(8)
    migration_user = "psynova_migrator_" + secrets.token_hex(8)
    if runtime_user == migration_user:
        raise InstallError("generated account names collided")
    _require_empty_output(
        "SELECT User FROM mysql.user WHERE User IN "
        f"('{runtime_user}','{migration_user}');"
    )
    runtime_password: str | None = None
    migration_password: str | None = None

    _set_install_phase("source_copy")
    _copy_source(preflight["source_revision"])
    _set_install_phase("python_provision")
    python = _provision_python()
    _set_install_phase("service_account")
    _ensure_service_account()
    _set_install_phase("credential_store")
    _ensure_credential_store()

    for account_name, grant_sql in (
        (
            runtime_user,
            (
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON `{DATABASE_NAME}`.* "
                f"TO '{runtime_user}'@'127.0.0.1';"
            ),
        ),
        (
            migration_user,
            (
                "GRANT CREATE, ALTER, INDEX, REFERENCES, SELECT, INSERT, UPDATE, DELETE "
                f"ON `{DATABASE_NAME}`.* TO '{migration_user}'@'127.0.0.1';"
            ),
        ),
    ):
        if not re.fullmatch(r"psynova_(?:runtime|migrator)_[a-f0-9]{16}", account_name):
            raise InstallError("generated database account name is invalid")
        account_phase = (
            "mysql_runtime_account" if account_name == runtime_user else "mysql_migration_account"
        )
        if account_name == runtime_user:
            sql = (
                f"CREATE DATABASE `{DATABASE_NAME}` CHARACTER SET utf8mb4 "
                f"COLLATE {DATABASE_COLLATION};\n"
                f"CREATE USER '{account_name}'@'127.0.0.1' IDENTIFIED BY RANDOM PASSWORD;\n"
                + grant_sql
            )
        else:
            sql = (
                f"CREATE USER '{account_name}'@'127.0.0.1' IDENTIFIED BY RANDOM PASSWORD;\n"
                + grant_sql
            )
        _set_install_phase(f"{account_phase}_sql")
        generated_result = _mysql(sql, xml_output=True)
        _set_install_phase(f"{account_phase}_result_parse")
        generated_password = _parse_generated_password(generated_result, account_name)
        if account_name == runtime_user:
            runtime_password = generated_password
        else:
            migration_password = generated_password

    if runtime_password is None or migration_password is None:
        raise InstallError("dedicated database credentials were not fully generated")

    csrf_secret = secrets.token_hex(32)
    key = _fernet_key()
    # Rebuild the one-version key package with a fresh key generated only in memory.
    key_payload = json.dumps(
        {"active_version": "school-demo-v1", "keys": {"school-demo-v1": key}},
        separators=(",", ":"),
    ).encode("ascii")
    runtime_payload = _credential_payload(
        runtime_user, runtime_password, csrf=csrf_secret
    )
    migration_payload = _credential_payload(
        migration_user, migration_password, csrf=None
    )
    seed_nonce = secrets.token_hex(6).upper()
    seed_credentials = {
        f"{school}.{role}": [
            f"SYNTHETIC_{school.upper()}_{role.upper()}_{seed_nonce}",
            secrets.token_urlsafe(32),
        ]
        for school in ("alpha", "beta")
        for role in ("student", "teacher", "psychological_specialist", "admin")
    }
    seed_payload = json.dumps(
        {"schema": "psynova.school-seed-accounts.v1", "credentials": seed_credentials},
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")

    _set_install_phase("credential_creation")
    _store_encrypted_credential(
        "database-keys.json", _CRED_FILES["database-keys.json"], key_payload
    )
    _store_encrypted_credential(
        "school-runtime.json", _CRED_FILES["school-runtime.json"], runtime_payload
    )
    _store_encrypted_credential(
        "school-migration.json", _CRED_FILES["school-migration.json"], migration_payload
    )
    _store_encrypted_credential(
        "school-seed-accounts.json",
        _CRED_FILES["school-seed-accounts.json"],
        seed_payload,
    )

    _set_install_phase("systemd_unit_installation")
    _install_systemd_unit("psynova-school-credential-probe.service")
    _install_systemd_unit("psynova-school-demo.service")
    _install_systemd_unit("psynova-school-seed.service")
    _install_systemd_unit("psynova-school-migrate.service", runtime=True)
    _set_install_phase("credential_probe")
    _start_and_verify_unit("psynova-school-credential-probe.service")
    _set_install_phase("schema_migration")
    _start_and_verify_unit("psynova-school-migrate.service", timeout=1800)

    _set_install_phase("migration_account_lock")
    _mysql(f"ALTER USER '{migration_user}'@'127.0.0.1' ACCOUNT LOCK;")
    locked = _mysql(
        f"SELECT account_locked FROM mysql.user WHERE User='{migration_user}' "
        "AND Host='127.0.0.1';"
    )
    if locked != "Y":
        raise InstallError("migration identity could not be locked after use")
    (RUN_UNITS / "psynova-school-migrate.service").unlink()
    (CREDSTORE / _CRED_FILES["school-migration.json"]).unlink()
    _command(["systemctl", "daemon-reload"])
    _set_install_phase("synthetic_seed")
    _start_and_verify_unit("psynova-school-seed.service", timeout=300)

    _set_install_phase("backend_start")
    _command(
        ["systemctl", "enable", "--now", "psynova-school-demo.service"], timeout=180
    )
    _wait_backend()
    _set_install_phase("http_verification")
    http_smoke_result = _command(
        [
            str(python),
            str(RELEASE_ROOT / "13_deployment" / "verify_school_http_linux.py"),
            "--repo-root",
            str(RELEASE_ROOT),
        ],
        timeout=180,
    )
    try:
        http_smoke = json.loads(http_smoke_result.stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise InstallError("HTTP smoke evidence could not be verified") from None
    if http_smoke.get("http_smoke") != "PASS":
        raise InstallError("HTTP role and persistence smoke checks failed")
    active = _output(
        _command(["systemctl", "is-active", "psynova-school-demo.service"])
    )
    if active != "active":
        raise InstallError("school Backend service is not active")
    listeners = _mysql_loopback_listeners()
    backend_listeners = _output(
        _command(
            [
                "ss",
                "--listening",
                "--tcp",
                "--numeric",
                "--no-header",
                "sport",
                "=",
                f":{BACKEND_PORT}",
            ]
        )
    )
    if not backend_listeners or any(
        len(line.split()) < 4 or line.split()[3] != f"127.0.0.1:{BACKEND_PORT}"
        for line in backend_listeners.splitlines()
    ):
        raise InstallError("Backend listener is not restricted to loopback")
    _set_install_phase("complete")
    return {
        "deployment": "INSTALLED",
        "source_revision": preflight["source_revision"],
        "mysql_version": preflight["mysql_version"],
        "database": DATABASE_NAME,
        "schema_revision": EXPECTED_REVISION,
        "runtime_database_user": runtime_user,
        "runtime_privileges": ["SELECT", "INSERT", "UPDATE", "DELETE"],
        "migration_user": "ACCOUNT_LOCKED_AND_CREDENTIAL_REMOVED",
        "service": active,
        "http_smoke": http_smoke,
        "mysql_listeners": listeners,
        "backend_listeners": [f"127.0.0.1:{BACKEND_PORT}"],
        "nginx": "unchanged_not_enabled",
        "cat_safety_rag": "not_part_of_this_deployment_stage",
        "python": str(python),
        "credential_files": "systemd_creds_host_encrypted",
        "demo_passwords": "encrypted_at_rest_not_printed",
    }


def _fernet_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--install",
        action="store_true",
        help="perform the one-time install as root after interactive sudo authorization",
    )
    args = parser.parse_args()
    if not args.install:
        print(
            json.dumps(
                {
                    "mode": "PLAN_ONLY",
                    "source_stage": SOURCE_STAGE.as_posix(),
                    "install_root": APP_ROOT.as_posix(),
                    "schema": DATABASE_NAME,
                    "schema_revision": EXPECTED_REVISION,
                    "service_user": SERVICE_USER,
                    "mysql_privileges": {
                        "runtime": ["SELECT", "INSERT", "UPDATE", "DELETE"],
                        "migration": [
                            "CREATE",
                            "ALTER",
                            "INDEX",
                            "REFERENCES",
                            "SELECT",
                            "INSERT",
                            "UPDATE",
                            "DELETE",
                        ],
                    },
                    "effects": [
                        "create dedicated OS service user and root-owned application release",
                        "create an isolated virtual environment from frozen lockfiles",
                        "create systemd host-encrypted credentials",
                        "create the target schema only if absent",
                        "run the existing Alembic chain and synthetic idempotent seed",
                        "start the Backend on 127.0.0.1:8088 only",
                    ],
                    "public_networking": "nginx unchanged; no public app or MySQL listener",
                },
                sort_keys=True,
            )
        )
        return 0
    try:
        _set_install_phase("starting")
        result = install()
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:  # noqa: BLE001 - do not print credential, SQL, or path details.
        print(
            json.dumps(
                {
                    "deployment": "BLOCKED",
                    "error_type": type(exc).__name__,
                    "phase": _INSTALL_PHASE,
                    "recovery": (
                        "Preserve existing files and database state for inspection; "
                        "do not rerun blindly."
                    ),
                },
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
