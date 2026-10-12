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
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from prepare_school_runtime import verify_process
from private_settings import write_private
from resume_school_workspace import ResumeOperations, _process_matches

DATABASE = "smhai_school_demo"
USER = "psynova_builder"
OLD_SCHOOL_WORKSPACE = Path(
    r"D:\Projects\.StudentMentalHealthAI-school-workspace-20261011"
)


class WorkspaceError(RuntimeError):
    pass


def _reject_reparse_ancestors(path: Path) -> None:
    """Inspect the raw path before resolve() can follow a Windows reparse point."""
    if not path.is_absolute() or ".." in path.parts:
        raise WorkspaceError("Absolute normalized workspace path required")
    cursor = Path(path.anchor)
    try:
        for part in path.parts[1:]:
            cursor = cursor / part
            try:
                info = cursor.lstat()
            except FileNotFoundError:
                if cursor != path:
                    raise WorkspaceError("Existing workspace parent components required") from None
                return
            if getattr(info, "st_file_attributes", 0) & 0x400:
                raise WorkspaceError("Workspace reparse points are not allowed")
    except OSError:
        raise WorkspaceError("Workspace path could not be verified") from None


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _require_free_loopback_port(port: int) -> None:
    exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
    if exclusive is None:
        raise WorkspaceError("Exclusive loopback port validation unavailable")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, exclusive, 1)
            probe.bind(("127.0.0.1", port))
    except OSError:
        raise WorkspaceError("Dedicated loopback port is occupied or unavailable") from None


def _sanitize_child_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    inherited = os.environ if source is None else source
    blocked = {"DATABASE_URL", "DATABASE_KEY_FILE", "MYSQL_PWD"}
    return {
        key: value
        for key, value in inherited.items()
        if not (
            key.upper().startswith("DB_")
            or key.upper().startswith("SMHAI_")
            or key.upper() in blocked
        )
    }


def _hidden_process_options() -> dict[str, object]:
    if os.name != "nt":
        return {}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    return {
        "startupinfo": startup,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }


def _run_hidden(args: list[str], **kwargs):
    environment = kwargs.pop("env", None)
    kwargs["env"] = _sanitize_child_environment(environment)
    kwargs.setdefault("stdin", subprocess.DEVNULL)
    check = kwargs.pop("check", False)
    kwargs.update(_hidden_process_options())
    return subprocess.run(args, check=check, **kwargs)


def _write_marker(path: Path, marker: dict) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", prefix=".workspace.",
            suffix=".tmp", dir=path.parent, delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(marker, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise WorkspaceError("Workspace marker update failed; preserve files") from None


def _normalize_creation_time(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise WorkspaceError("Guardian creation time could not be verified") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise WorkspaceError("Guardian creation time must be UTC")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _verify_guardian_process(marker: dict, process_id: int) -> None:
    """Check exact process/listener ownership without forwarding credentials."""
    inherited = dict(os.environ)
    safe_environment = _sanitize_child_environment(inherited)
    try:
        os.environ.clear()
        os.environ.update(safe_environment)
        process_metadata = ResumeOperations().inspect_process(process_id)
        if process_metadata is None or not _process_matches(process_metadata, marker):
            raise WorkspaceError("Started guardian identity does not match marker")
        verify_process(marker)
    finally:
        os.environ.clear()
        os.environ.update(inherited)


def validate_target(target: Path, repo: Path, port: int) -> Path:
    _reject_reparse_ancestors(target)
    if not 3308 <= port <= 3399:
        raise WorkspaceError("Use a dedicated port in 3308..3399")
    if not target.parent.is_dir():
        raise WorkspaceError("Existing workspace parent directory required")
    resolved = target.resolve(strict=False)
    repository = repo.resolve(strict=False)
    old_workspace = OLD_SCHOOL_WORKSPACE.resolve(strict=False)
    if _paths_overlap(resolved, repository) or _paths_overlap(resolved, old_workspace):
        raise WorkspaceError("External absolute workspace required")
    if resolved == Path(resolved.anchor) or target.exists():
        raise WorkspaceError("New non-existing workspace required; no overwrite/reset")
    _require_free_loopback_port(port)
    return resolved


def protect_directory(path: Path) -> None:
    if os.name != "nt":
        raise WorkspaceError("This initializer currently supports Windows only")
    environment = _sanitize_child_environment()
    result = _run_hidden(["pwsh", "-NoProfile", "-Command", "[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value"], env=environment, capture_output=True, text=True, check=True, timeout=15)
    sid = result.stdout.strip()
    if not re.fullmatch(r"S-1-[0-9-]+", sid):
        raise WorkspaceError("Cannot determine current-user ACL")
    environment.update(PSYNOVA_PRIVATE_DIRECTORY=str(path), PSYNOVA_PRIVATE_SID=sid)
    # DACL-only operations on this newly created directory; never request
    # SeSecurityPrivilege or modify its SACL/owner/global security policy.
    _run_hidden(["icacls", str(path), "/inheritance:r"], env=environment, capture_output=True, check=True, timeout=15)
    list_other = """$acl = Get-Acl -LiteralPath $env:PSYNOVA_PRIVATE_DIRECTORY
@($acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]) | Where-Object { $_.IdentityReference.Value -ne $env:PSYNOVA_PRIVATE_SID } | ForEach-Object { $_.IdentityReference.Value } | Select-Object -Unique) | ConvertTo-Json -Compress"""
    result = _run_hidden(["pwsh", "-NoProfile", "-Command", list_other], env=environment, capture_output=True, text=True, check=True, timeout=15)
    others = json.loads(result.stdout) if result.stdout.strip() else []
    if isinstance(others, str):
        others = [others]
    for other in others:
        if not re.fullmatch(r"S-1-[0-9-]+", other):
            raise WorkspaceError("Unexpected directory ACL identity")
        _run_hidden(["icacls", str(path), "/remove", f"*{other}"], env=environment, capture_output=True, check=True, timeout=15)
    _run_hidden(["icacls", str(path), "/remove:d", f"*{sid}"], env=environment, capture_output=True, check=True, timeout=15)
    _run_hidden(["icacls", str(path), "/grant:r", f"*{sid}:(OI)(CI)F"], env=environment, capture_output=True, check=True, timeout=15)
    check = """$acl = Get-Acl -LiteralPath $env:PSYNOVA_PRIVATE_DIRECTORY
$rules = @($acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))
$unexpected = @($rules | Where-Object { $_.IdentityReference.Value -ne $env:PSYNOVA_PRIVATE_SID -or $_.IsInherited -or $_.AccessControlType -ne 'Allow' })
if (-not $acl.AreAccessRulesProtected -or $rules.Count -ne 1 -or $unexpected.Count -gt 0 -or ($rules[0].FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::FullControl) -ne [System.Security.AccessControl.FileSystemRights]::FullControl) { exit 2 }
exit 0"""
    _run_hidden(["pwsh", "-NoProfile", "-Command", check], env=environment, capture_output=True, check=True, timeout=15)


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
    requested_target = target
    target = validate_target(requested_target, repo, port)
    import pymysql  # Run with 11_database's existing project environment.
    del pymysql  # Dependency preflight happens before directory/server creation.

    server_path = bin_dir / "mysqld.exe"
    _reject_reparse_ancestors(server_path)
    server = server_path.resolve(strict=True)
    if not server.is_file():
        raise WorkspaceError("Existing vendor MySQL executables required")
    _reject_reparse_ancestors(requested_target)
    if requested_target.resolve(strict=False) != target or requested_target.exists():
        raise WorkspaceError("Workspace target changed after validation")
    target.mkdir()
    protect_directory(target)
    marker = {"schema_version": "psynova.synthetic-workspace.v1", "project": "StudentMentalHealthAI", "workspace_id": secrets.token_hex(16), "state": "INITIALIZING", "host": "127.0.0.1", "port": port, "database": DATABASE, "synthetic_only": True}
    marker_path = target / "workspace.json"
    _write_marker(marker_path, marker)
    data = target / "mysql-data"
    initialized = _run_hidden(
        [str(server), "--no-defaults", "--initialize", "--console", f"--datadir={data}"],
        capture_output=True,
        check=True,
        timeout=120,
    )
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
    environment = _sanitize_child_environment()
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    # The earlier preflight is only advisory; recheck after initialization and
    # immediately before starting the listener.
    _require_free_loopback_port(port)
    process = subprocess.Popen(
        [
            str(server),
            "--no-defaults",
            f"--datadir={data}",
            f"--port={port}",
            "--bind-address=127.0.0.1",
            "--mysqlx=0",
            f"--log-error={target / 'mysql.private.log'}",
            f"--pid-file={target / 'mysql.pid'}",
        ],
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        startupinfo=startup,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        close_fds=True,
        shell=False,
    )
    marker.update(
        parent_pid=process.pid,
        executable=str(server),
        data_directory=str(data),
        state="STARTING",
    )
    try:
        _write_marker(marker_path, marker)
        marker["parent_creation_time"] = _normalize_creation_time(
            ResumeOperations.process_creation_time(process)
        )
        _write_marker(marker_path, marker)
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
        # Confirm listener ownership and the protected workspace before the
        # expired initial password is used for its unavoidable first ALTER USER.
        _verify_guardian_process(marker, process.pid)
        connection = bootstrap_connection(port, initial_password)
        try:
            with connection.cursor() as cursor:
                statements = setup_sql(root_password, app_password).splitlines()
                cursor.execute(statements[0])
                cursor.execute("SELECT @@port, @@datadir")
                actual_port, actual_directory = cursor.fetchone()
                if (
                    actual_port != port
                    or Path(actual_directory).resolve(strict=False)
                    != data.resolve(strict=False)
                ):
                    raise WorkspaceError("Connected database identity does not match target")
                for statement in statements[1:]:
                    cursor.execute(statement)
        finally:
            connection.close()
        marker["state"] = "READY_FOR_MIGRATION"
        _write_marker(marker_path, marker)
    except BaseException:
        marker["state"] = "SETUP_FAILED_NO_AUTO_STOP"
        try:
            _write_marker(marker_path, marker)
        except WorkspaceError:
            pass
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
        print(json.dumps({"setup": "BLOCKED", "error_type": type(exc).__name__, "recovery": "Preserve workspace and inspect any recorded process state before retry."}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
