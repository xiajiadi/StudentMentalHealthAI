"""Provision a schema-scoped runtime identity in an owned synthetic workspace.

Never targets legacy/system instances, never resets data, never prints secrets.
Run with 11_database's environment. Failed attempts retain sealed recovery files.
"""
from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
from pathlib import Path

from private_settings import read_private, write_private
from school_schema import CURRENT_SCHOOL_REVISION


class PreparationError(RuntimeError):
    pass


def verify_runtime_grants(grants: list[str], current_role: str) -> None:
    scopes = {grant.split(" TO ", 1)[0] for grant in grants}
    expected = {"GRANT USAGE ON *.*", "GRANT SELECT, INSERT, UPDATE, DELETE ON `smhai_school_demo`.*"}
    if len(grants) != 2 or scopes != expected or current_role != "NONE" or any("WITH GRANT OPTION" in grant for grant in grants):
        raise PreparationError("Unexpected runtime privileges or active roles")


def validate_marker(workspace: Path, repo: Path) -> dict:
    if not workspace.is_absolute():
        raise PreparationError("Absolute external workspace required")
    workspace = workspace.resolve()
    if workspace.is_relative_to(repo.resolve()):
        raise PreparationError("External workspace required")
    marker = json.loads((workspace / "workspace.json").read_text(encoding="utf-8"))
    if (marker.get("schema_version") != "psynova.synthetic-workspace.v1"
        or marker.get("project") != "StudentMentalHealthAI"
        or marker.get("synthetic_only") is not True
        or marker.get("host") != "127.0.0.1"
        or marker.get("database") != "smhai_school_demo"
        or not isinstance(marker.get("port"), int)
        or not 3308 <= marker["port"] <= 3399
        or marker.get("state") != "READY_FOR_MIGRATION"
        or Path(marker.get("data_directory", "")).resolve() != workspace / "mysql-data"):
        raise PreparationError("Owned synthetic workspace marker required")
    return marker


def verify_process(marker: dict) -> None:
    # Capture process metadata privately. No credential-bearing process output.
    script = """$p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $env:PSYNOVA_PARENT_PID) | Select-Object ProcessId,ExecutablePath,CommandLine
$listener = @(Get-NetTCPConnection -State Listen -LocalPort $env:PSYNOVA_DB_PORT -ErrorAction SilentlyContinue | Select-Object OwningProcess,LocalAddress)
$children = @(Get-CimInstance Win32_Process -Filter ('ParentProcessId=' + $env:PSYNOVA_PARENT_PID) | Select-Object ProcessId,ExecutablePath)
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$acl = Get-Acl -LiteralPath $env:PSYNOVA_WORKSPACE
$rules = @($acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))
$unexpected = @($rules | Where-Object { $_.IdentityReference.Value -ne $sid -or $_.IsInherited -or $_.AccessControlType -ne 'Allow' })
$private = $acl.AreAccessRulesProtected -and $rules.Count -eq 1 -and $unexpected.Count -eq 0 -and (($rules[0].FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::FullControl) -eq [System.Security.AccessControl.FileSystemRights]::FullControl)
@{parent=$p; listeners=$listener; children=$children; private_acl=$private} | ConvertTo-Json -Depth 4 -Compress"""
    import os
    env = dict(os.environ, PSYNOVA_PARENT_PID=str(marker["parent_pid"]), PSYNOVA_DB_PORT=str(marker["port"]), PSYNOVA_WORKSPACE=str(Path(marker["data_directory"]).parent))
    result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], env=env, capture_output=True, text=True, check=True, timeout=20)
    metadata = json.loads(result.stdout)
    if metadata.get("private_acl") is not True:
        raise PreparationError("Current-user-only directory ACL required")
    parent = metadata.get("parent")
    if not parent or Path(parent.get("ExecutablePath", "")).resolve() != Path(marker["executable"]).resolve():
        raise PreparationError("Owned guardian is unavailable")
    command = parent.get("CommandLine", "").replace('"', '').lower()
    if f"--datadir={marker['data_directory']}".lower() not in command or f"--port={marker['port']}" not in command:
        raise PreparationError("Owned guardian arguments do not match")
    children = metadata.get("children") or []
    listeners = metadata.get("listeners") or []
    if isinstance(children, dict):
        children = [children]
    if isinstance(listeners, dict):
        listeners = [listeners]
    owned = {parent["ProcessId"]} | {p["ProcessId"] for p in children if p.get("ExecutablePath") == parent.get("ExecutablePath")}
    if not listeners or any(p["OwningProcess"] not in owned or p["LocalAddress"] != "127.0.0.1" for p in listeners):
        raise PreparationError("Loopback listener ownership does not match")


def prepare(workspace: Path, repo: Path) -> dict:
    marker = validate_marker(workspace, repo)
    verify_process(marker)
    destination = workspace / "runtime.private.dpapi"
    if destination.exists() or (workspace / "school-auth.private.dpapi").exists() or (workspace / "runtime-ready.json").exists():
        raise PreparationError("Runtime settings already exist; inspect before recovery")
    private = read_private(workspace / "database.private.dpapi")
    if private.get("DB_NAME") != marker["database"] or int(private.get("DB_PORT", 0)) != marker["port"] or private.get("DB_HOST") != "127.0.0.1":
        raise PreparationError("Sealed configuration does not match workspace")
    import pymysql
    connection = pymysql.connect(host="127.0.0.1", port=marker["port"], user="root", password=private["root_password"], database=marker["database"], connect_timeout=10, read_timeout=20, write_timeout=20)
    created_username = None
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT @@port, @@datadir, DATABASE()")
            port, directory, database = cursor.fetchone()
            if port != marker["port"] or database != marker["database"] or Path(directory).resolve() != Path(marker["data_directory"]).resolve():
                raise PreparationError("Connected database identity does not match")
            cursor.execute("SELECT version_num FROM database_alembic_version")
            if cursor.fetchall() != ((CURRENT_SCHOOL_REVISION,),):
                raise PreparationError("Required school migration is missing")
            username = "psynova_runtime_" + secrets.token_hex(8)
            password = secrets.token_hex(32)
            # Persist sealed recovery material BEFORE nontransactional account DDL.
            write_private(destination, {"DB_USER": username, "DB_PASSWORD": password, "DB_HOST": "127.0.0.1", "DB_PORT": str(port), "DB_NAME": database})
            write_private(workspace / "school-auth.private.dpapi", {"SMHAI_SCHOOL_CSRF_SECRET": secrets.token_hex(32)})
            cursor.execute("CREATE USER %s@'127.0.0.1' IDENTIFIED BY %s", (username, password))
            created_username = username
            cursor.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON `smhai_school_demo`.* TO %s@'127.0.0.1'", (username,))
        connection.commit()
        # Inspect the actual new identity before publishing readiness.
        runtime_connection = pymysql.connect(host="127.0.0.1", port=marker["port"], user=username, password=password, database=marker["database"], connect_timeout=10, read_timeout=20, write_timeout=20)
        try:
            with runtime_connection.cursor() as cursor:
                cursor.execute("SHOW GRANTS FOR CURRENT_USER()")
                grants = [row[0] for row in cursor.fetchall()]
                cursor.execute("SELECT CURRENT_ROLE()")
                verify_runtime_grants(grants, cursor.fetchone()[0])
        finally:
            runtime_connection.close()
        (workspace / "runtime-ready.json").write_text(json.dumps({"workspace_id": marker["workspace_id"], "state": "VERIFIED", "database": marker["database"], "port": marker["port"]}), encoding="utf-8")
    except BaseException:
        if created_username is not None:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("ALTER USER %s@'127.0.0.1' ACCOUNT LOCK", (created_username,))
                connection.commit()
            except Exception:  # noqa: BLE001 - preserve recovery evidence without credential-bearing errors.
                raise PreparationError("Runtime isolation failed; manual owned-workspace inspection required") from None
        raise
    finally:
        connection.close()
    return {"runtime_identity": "CREATED", "port": marker["port"], "database": marker["database"], "privileges": ["SELECT", "INSERT", "UPDATE", "DELETE"], "settings": "current-user DPAPI"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.workspace, Path(__file__).resolve().parents[1])))
        return 0
    except Exception as exc:  # noqa: BLE001 - emit only safe error type.
        print(json.dumps({"runtime_identity": "BLOCKED", "error_type": type(exc).__name__, "recovery": "Preserve sealed settings and inspect owned workspace."}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
