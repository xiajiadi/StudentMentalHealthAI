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

from prepare_school_runtime import (
    PreparationError,
    validate_marker,
    verify_process,
    verify_runtime_grants,
)
from private_settings import read_private
from school_schema import CURRENT_SCHOOL_REVISION, SUPPORTED_SNAPSHOT_REVISIONS

DEFAULT_BACKEND_PORT = 8088
DEFAULT_FRONTEND_PORT = 4178
DEFAULT_CAT_PORT = 8180
MIN_SERVICE_PORT = 1024
MAX_SERVICE_PORT = 65535
MODULE_ENDPOINTS = {
    "cat": {"mode": "http", "base_url": "http://127.0.0.1:8180"},
    "rag": {"mode": "http", "base_url": "http://127.0.0.1:8170"},
    "llm": {"mode": "http", "base_url": "http://127.0.0.1:8160"},
    "safety": {"mode": "http", "base_url": "http://127.0.0.1:8190"},
}
LLM_PROFILES = ("default", "school-gpu-7b")
SCHOOL_GPU_7B_LOGICAL_MODEL_ID = "qwen2.5-7b-instruct-school-demo"
SCHOOL_GPU_7B_CONTEXT_LENGTH = 8192
RUNTIME_PURPOSE_APPLICATION = "application"
RUNTIME_PURPOSE_BACKUP = "backup"
BACKUP_NOT_APPLICATION_READY = "BACKUP_NOT_APPLICATION_READY"
APPLICATION_CURRENT_REVISION = "APPLICATION_CURRENT_REVISION"


def build_school_settings_kwargs(
    port: int,
    frontend_port: int,
    llm_profile: str = "default",
    *,
    cat_port: int = DEFAULT_CAT_PORT,
) -> dict[str, object]:
    """Build fixed loopback school settings with only validated port choices."""
    for name, value in (
        ("port", port),
        ("frontend_port", frontend_port),
        ("cat_port", cat_port),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not MIN_SERVICE_PORT <= value <= MAX_SERVICE_PORT
        ):
            raise ValueError(f"{name} must be between {MIN_SERVICE_PORT} and {MAX_SERVICE_PORT}")
    if llm_profile not in LLM_PROFILES:
        raise ValueError("unsupported LLM profile")
    fixed_module_ports = {8170, 8160, 8190}
    if cat_port in {port, frontend_port} | fixed_module_ports:
        raise ValueError("cat_port conflicts with another service port")
    cat_settings = dict(MODULE_ENDPOINTS["cat"])
    cat_settings["base_url"] = f"http://127.0.0.1:{cat_port}"
    llm_settings = dict(MODULE_ENDPOINTS["llm"])
    if llm_profile == "school-gpu-7b":
        llm_settings.update(
            {
                "logical_model_id": SCHOOL_GPU_7B_LOGICAL_MODEL_ID,
                "context_length": SCHOOL_GPU_7B_CONTEXT_LENGTH,
            }
        )
    return {
        "environment": "demo",
        "identity_profile": "school_tenant",
        "persistence_mode": "mysql",
        "host": "127.0.0.1",
        "port": port,
        "auth": {"cookie_name": "psynova_school_session"},
        "allowed_origins": [f"http://127.0.0.1:{frontend_port}"],
        "cat": cat_settings,
        "rag": dict(MODULE_ENDPOINTS["rag"]),
        "llm": llm_settings,
        "safety": dict(MODULE_ENDPOINTS["safety"]),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--port", type=int, default=DEFAULT_BACKEND_PORT)
    parser.add_argument("--frontend-port", type=int, default=DEFAULT_FRONTEND_PORT)
    parser.add_argument("--cat-port", type=int, default=DEFAULT_CAT_PORT)
    parser.add_argument("--llm-profile", choices=LLM_PROFILES, default="default")
    return parser


def load_runtime(
    workspace: Path,
    repo: Path,
    *,
    purpose: str = RUNTIME_PURPOSE_APPLICATION,
) -> dict:
    if type(purpose) is not str or purpose not in {
        RUNTIME_PURPOSE_APPLICATION,
        RUNTIME_PURPOSE_BACKUP,
    }:
        raise PreparationError("Unsupported runtime preflight purpose")
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
            revisions = cursor.fetchall()
            if (
                type(revisions) is not tuple
                or len(revisions) != 1
                or type(revisions[0]) is not tuple
                or len(revisions[0]) != 1
                or type(revisions[0][0]) is not str
            ):
                raise PreparationError("Required school revision unavailable")
            revision = revisions[0][0]
            if purpose == RUNTIME_PURPOSE_APPLICATION:
                if revision != CURRENT_SCHOOL_REVISION:
                    raise PreparationError("Required school revision unavailable")
            elif revision not in SUPPORTED_SNAPSHOT_REVISIONS:
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
        if name.startswith(("DB_", "SMHAI_")) or name in {
            "DATABASE_URL",
            "DATABASE_KEY_FILE",
            "MYSQL_PWD",
        }:
            os.environ.pop(name, None)
    for name in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"):
        os.environ[name] = str(private[name])
    os.environ["DATABASE_KEY_FILE"] = str(workspace / "database-keys.private.dpapi")
    os.environ["SMHAI_SCHOOL_CSRF_SECRET"] = secret
    return {
        "database": marker["database"],
        "port": marker["port"],
        "workspace_id": marker["workspace_id"],
        "data_directory": marker["data_directory"],
        "identity_profile": "school_tenant",
        "schema_revision": revision,
        "purpose": purpose,
        "scope": (
            BACKUP_NOT_APPLICATION_READY
            if purpose == RUNTIME_PURPOSE_BACKUP
            else APPLICATION_CURRENT_REVISION
        ),
    }


def main() -> int:
    args = build_parser().parse_args()
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo / "11_database" / ".venv" / "Lib" / "site-packages"))
    sys.path.insert(0, str(repo / "11_database"))
    sys.path.insert(0, str(repo / "09_backend" / "src"))
    try:
        settings_kwargs = build_school_settings_kwargs(
            args.port, args.frontend_port, args.llm_profile, cat_port=args.cat_port
        )
        result = load_runtime(args.workspace, repo)
        from smhai_backend.app_factory import create_app
        from smhai_backend.core.config import BackendSettings
        settings = BackendSettings(_env_file=None, **settings_kwargs)
        app = create_app(settings=settings)
        if args.preflight_only:
            print(json.dumps(dict(result, preflight="PASS", module_clients="HTTP")))
            return 0
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)
        return 0
    except Exception as exc:  # noqa: BLE001 - only emit error type; details may contain credentials.
        print(json.dumps({"school_backend": "BLOCKED", "error_type": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
