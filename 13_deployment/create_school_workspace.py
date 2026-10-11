"""Create a NEW isolated Windows MySQL synthetic workspace, never reuse/reset data.

Requires an existing vendor MySQL bin directory. Credentials and initialization
logs stay in a current-user-only external directory, never in command arguments.
No elevation, system service installation, global configuration or old DB access.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

from private_settings import write_private

DATABASE = "smhai_school_demo"
USER = "psynova_builder"


class WorkspaceError(RuntimeError):
    pass


def validate_target(target: Path, repo: Path, port: int) -> Path:
    resolved = target.resolve()
    if not target.is_absolute() or resolved == repo.resolve() or resolved.is_relative_to(repo.resolve()):
        raise WorkspaceError("External absolute workspace required")
    if resolved == Path(resolved.anchor) or resolved.exists():
        raise WorkspaceError("New non-existing workspace required; no overwrite/reset")
    if not 3308 <= port <= 3399:
        raise WorkspaceError("Use a dedicated port in 3308..3399")
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            raise WorkspaceError("Port already occupied")
    except (ConnectionRefusedError, TimeoutError, OSError):
        pass
    return resolved


def protect_directory(path: Path) -> None:
    if os.name != "nt":
        raise WorkspaceError("This initializer currently supports Windows only")
    result = subprocess.run(["pwsh", "-NoProfile", "-Command", "[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value"], capture_output=True, text=True, check=True, timeout=15)
    sid = result.stdout.strip()
    if not re.fullmatch(r"S-1-[0-9-]+", sid):
        raise WorkspaceError("Cannot determine current-user ACL")
    environment = dict(os.environ, PSYNOVA_PRIVATE_DIRECTORY=str(path), PSYNOVA_PRIVATE_SID=sid)
    # DACL-only operations on this newly created directory; never request
    # SeSecurityPrivilege or modify its SACL/owner/global security policy.
    subprocess.run(["icacls", str(path), "/inheritance:r"], capture_output=True, check=True, timeout=15)
    list_other = """$acl = Get-Acl -LiteralPath $env:PSYNOVA_PRIVATE_DIRECTORY
@($acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]) | Where-Object { $_.IdentityReference.Value -ne $env:PSYNOVA_PRIVATE_SID } | ForEach-Object { $_.IdentityReference.Value } | Select-Object -Unique) | ConvertTo-Json -Compress"""
    result = subprocess.run(["pwsh", "-NoProfile", "-Command", list_other], env=environment, capture_output=True, text=True, check=True, timeout=15)
    others = json.loads(result.stdout) if result.stdout.strip() else []
    if isinstance(others, str):
        others = [others]
    for other in others:
        if not re.fullmatch(r"S-1-[0-9-]+", other):
            raise WorkspaceError("Unexpected directory ACL identity")
        subprocess.run(["icacls", str(path), "/remove", f"*{other}"], capture_output=True, check=True, timeout=15)
    subprocess.run(["icacls", str(path), "/remove:d", f"*{sid}"], capture_output=True, check=True, timeout=15)
    subprocess.run(["icacls", str(path), "/grant:r", f"*{sid}:(OI)(CI)F"], capture_output=True, check=True, timeout=15)
    check = """$acl = Get-Acl -LiteralPath $env:PSYNOVA_PRIVATE_DIRECTORY
$rules = @($acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))
$unexpected = @($rules | Where-Object { $_.IdentityReference.Value -ne $env:PSYNOVA_PRIVATE_SID -or $_.IsInherited -or $_.AccessControlType -ne 'Allow' })
if (-not $acl.AreAccessRulesProtected -or $rules.Count -ne 1 -or $unexpected.Count -gt 0 -or ($rules[0].FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::FullControl) -ne [System.Security.AccessControl.FileSystemRights]::FullControl) { exit 2 }
exit 0"""
    subprocess.run(["pwsh", "-NoProfile", "-Command", check], env=environment, capture_output=True, check=True, timeout=15)


def stop_owned_tree(process: subprocess.Popen) -> None:
    # poll() checks the original process handle; a still-live parent PID cannot
    # have been reused. MySQL on Windows may run a child under that guardian.
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=True, timeout=15)
        else:
            process.terminate()
        process.wait(timeout=15)


def setup_sql(root_password: str, app_password: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{64}", root_password) or not re.fullmatch(r"[a-f0-9]{64}", app_password):
        raise WorkspaceError("Expected generated opaque credentials")
    return (
        f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{root_password}';\n"
        f"CREATE DATABASE `{DATABASE}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;\n"
        f"CREATE USER '{USER}'@'127.0.0.1' IDENTIFIED BY '{app_password}';\n"
        f"GRANT ALL PRIVILEGES ON `{DATABASE}`.* TO '{USER}'@'127.0.0.1';\n"
    )


def bootstrap_connection(port: int, initial_password: str):
    import pymysql

    class InitialPasswordConnection(pymysql.Connection):
        def set_character_set(self, charset, collation=None):
            # The installed driver issues SET NAMES immediately after auth.
            # MySQL's expired-password mode permits only password rotation first.
            # This one-purpose connection sends generated ASCII rotation SQL;
            # ordinary connections retain the driver's normal initialization.
            return None

    return InitialPasswordConnection(host="127.0.0.1", port=port, user="root", password=initial_password, client_flag=1 << 22, autocommit=None, connect_timeout=10, read_timeout=20, write_timeout=20)


def create(target: Path, bin_dir: Path, repo: Path, port: int) -> dict:
    target = validate_target(target, repo, port)
    import pymysql  # Run with 11_database's existing project environment.
    del pymysql  # Dependency preflight happens before directory/server creation.

    server = bin_dir.resolve() / "mysqld.exe"
    if not server.is_file():
        raise WorkspaceError("Existing vendor MySQL executables required")
    target.mkdir(parents=True)
    protect_directory(target)
    marker = {"schema_version": "psynova.synthetic-workspace.v1", "project": "StudentMentalHealthAI", "workspace_id": secrets.token_hex(16), "state": "INITIALIZING", "host": "127.0.0.1", "port": port, "database": DATABASE, "synthetic_only": True}
    marker_path = target / "workspace.json"
    marker_path.write_text(json.dumps(marker, indent=2), encoding="utf-8")
    data = target / "mysql-data"
    initialized = subprocess.run([str(server), "--no-defaults", "--initialize", "--console", f"--datadir={data}"], capture_output=True, check=True, timeout=120)
    initialization_output = (initialized.stdout + initialized.stderr).decode("utf-8", errors="replace")
    match = re.search(r"temporary password is generated for root@localhost: (\S+)", initialization_output)
    if not match:
        raise WorkspaceError("Initialization credential unavailable; preserve workspace for inspection")
    initial_password = match.group(1)
    # Store generated recovery material before any credential-changing operation.
    root_password, app_password = secrets.token_hex(32), secrets.token_hex(32)
    secret_file = target / "database.private.dpapi"
    write_private(secret_file, {"root_password": root_password, "initial_password": initial_password, "DB_USER": USER, "DB_PASSWORD": app_password, "DB_HOST": "127.0.0.1", "DB_PORT": str(port), "DB_NAME": DATABASE})
    encryption = {"active_version": "v1", "keys": {"v1": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")}}
    write_private(target / "database-keys.private.dpapi", encryption)
    environment = {key: value for key, value in os.environ.items() if key not in {"MYSQL_PWD", "DATABASE_URL", "DB_PASSWORD", "DB_USER", "DB_HOST", "DB_PORT", "DB_NAME"}}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    process = subprocess.Popen([str(server), "--no-defaults", f"--datadir={data}", f"--port={port}", "--bind-address=127.0.0.1", "--mysqlx=0", f"--log-error={target / 'mysql.private.log'}", f"--pid-file={target / 'mysql.pid'}"], env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startup)
    try:
        marker.update(parent_pid=process.pid, executable=str(server), data_directory=str(data))
        marker_path.write_text(json.dumps(marker, indent=2), encoding="utf-8")
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise WorkspaceError("Owned database process exited; inspect private log locally")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                    break
            except OSError:
                time.sleep(0.3)
        else:
            raise WorkspaceError("Owned database readiness timed out; no restart loop")
        # No shell, no password argv, no result/SQL echo. Failed setup leaves all
        # recovery material protected and never deletes/repurposes the directory.
        # In-process driver: no password argument, MYSQL_PWD or plaintext cnf.
        # Installed vendor mysql_com.h defines this capability as (1UL << 22);
        # PyMySQL does not expose the constant by name in the local version.
        connection = bootstrap_connection(port, initial_password)
        try:
            with connection.cursor() as cursor:
                for statement in setup_sql(root_password, app_password).splitlines():
                    cursor.execute(statement)
        finally:
            connection.close()
        marker["state"] = "READY_FOR_MIGRATION"
        marker_path.write_text(json.dumps(marker, indent=2), encoding="utf-8")
    except BaseException:
        marker["state"] = "SETUP_FAILED"
        try:
            marker_path.write_text(json.dumps(marker, indent=2), encoding="utf-8")
        finally:
            stop_owned_tree(process)
        raise
    return {key: marker[key] for key in ("schema_version", "workspace_id", "state", "host", "port", "database", "synthetic_only")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--mysql-bin", type=Path, required=True)
    parser.add_argument("--port", type=int, default=3308)
    args = parser.parse_args()
    try:
        result = create(args.workspace, args.mysql_bin, Path(__file__).resolve().parents[1], args.port)
        print(json.dumps(result))
        return 0
    except Exception as exc:  # noqa: BLE001 - SQL/driver exception text can contain credentials.
        # Never print CalledProcessError repr: input/output may contain credentials.
        print(json.dumps({"setup": "BLOCKED", "error_type": type(exc).__name__, "recovery": "Preserve owned files for local recovery."}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
