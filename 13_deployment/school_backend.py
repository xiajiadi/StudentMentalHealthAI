"""Run the isolated synthetic school backend on loopback, using sealed settings.

This foreground entrypoint neither migrates databases nor seeds accounts. The
owner's launcher must manage its process lifetime. Real module HTTP clients are
required; an unavailable dependency is an error, never a fake response fallback.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from prepare_school_runtime import PreparationError, validate_marker, verify_process, verify_runtime_grants
from private_settings import read_private


def load_runtime(workspace: Path, repo: Path) -> dict:
    marker = validate_marker(workspace, repo)
    verify_process(marker)
    ready = json.loads((workspace / "runtime-ready.json").read_text(encoding="utf-8"))
    if (ready.get("workspace_id") != marker["workspace_id"] or ready.get("state") != "VERIFIED"
        or ready.get("database") != marker["database"] or ready.get("port") != marker["port"]):
        raise PreparationError("Verified runtime readiness required")
    private = read_private(workspace / "runtime.private.dpapi")
    if (private.get("DB_HOST") != "127.0.0.1" or private.get("DB_NAME") != marker["database"]
        or int(private.get("DB_PORT", 0)) != marker["port"]
        or not str(private.get("DB_USER", "")).startswith("psynova_runtime_")):
        raise PreparationError("Sealed runtime target does not match")
    import pymysql
    connection = pymysql.connect(host="127.0.0.1", port=marker["port"], user=private["DB_USER"], password=private["DB_PASSWORD"], database=marker["database"], connect_timeout=10, read_timeout=20, write_timeout=20)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SHOW GRANTS FOR CURRENT_USER()")
            grants = [row[0] for row in cursor.fetchall()]
            cursor.execute("SELECT CURRENT_ROLE()")
            verify_runtime_grants(grants, cursor.fetchone()[0])
            cursor.execute("SELECT version_num FROM database_alembic_version")
            if cursor.fetchall() != (("20261011_0005",),):
                raise PreparationError("Required school revision unavailable")
    finally:
        connection.close()
    auth = read_private(workspace / "school-auth.private.dpapi")
    secret = auth.get("SMHAI_SCHOOL_CSRF_SECRET")
    import re
    if not isinstance(secret, str) or not re.fullmatch(r"[a-f0-9]{64}", secret):
        raise PreparationError("Sealed school authentication settings unavailable")
    # Mutate only this foreground child process; never inherited credential URLs
    # or a plaintext .env file. Whitelist database keys from the sealed source.
    for name in tuple(os.environ):
        if name.startswith("DB_") or name.startswith("SMHAI_") or name in {"DATABASE_URL", "DATABASE_KEY_FILE", "MYSQL_PWD"}:
            os.environ.pop(name, None)
    for name in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"):
        os.environ[name] = str(private[name])
    os.environ["DATABASE_KEY_FILE"] = str(workspace / "database-keys.private.dpapi")
    os.environ["SMHAI_SCHOOL_CSRF_SECRET"] = secret
    return {"database": marker["database"], "port": marker["port"], "identity_profile": "school_tenant"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo / "11_database" / ".venv" / "Lib" / "site-packages"))
    sys.path.insert(0, str(repo / "11_database"))
    sys.path.insert(0, str(repo / "09_backend" / "src"))
    try:
        result = load_runtime(args.workspace, repo)
        from smhai_backend.core.config import BackendSettings
        from smhai_backend.app_factory import create_app
        settings = BackendSettings(_env_file=None, environment="demo", identity_profile="school_tenant", persistence_mode="mysql", host="127.0.0.1", port=8088, auth={"cookie_name":"psynova_school_session"}, allowed_origins=["http://127.0.0.1:4178"], cat={"mode":"http", "base_url":"http://127.0.0.1:8180"}, rag={"mode":"http", "base_url":"http://127.0.0.1:8170"}, llm={"mode":"http", "base_url":"http://127.0.0.1:8160"}, safety={"mode":"http", "base_url":"http://127.0.0.1:8190"})
        app = create_app(settings=settings)
        if args.preflight_only:
            print(json.dumps(dict(result, preflight="PASS", module_clients="HTTP")))
            return 0
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=8088, access_log=False)
        return 0
    except Exception as exc:
        print(json.dumps({"school_backend": "BLOCKED", "error_type": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
