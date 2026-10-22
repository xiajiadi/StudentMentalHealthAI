"""Loopback-only Linux systemd entry point for the synthetic school backend."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_BACKEND_PORT = 8088
DEFAULT_FRONTEND_PORT = 4178
DEFAULT_CAT_PORT = 8180
_DNS_HOST_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _build_school_backend_settings(csrf_secret: str):
    from smhai_backend.core.config import (
        BackendSettings,
        LLMModuleClientSettings,
        ModuleClientSettings,
    )

    public_origin, public_host = _public_web_origin()
    return BackendSettings(
        _env_file=None,
        environment="demo",
        identity_profile="school_tenant",
        persistence_mode="mysql",
        host="127.0.0.1",
        port=DEFAULT_BACKEND_PORT,
        docs_enabled=False,
        school_csrf_secret=csrf_secret,
        allowed_origins=(
            [public_origin]
            if public_origin is not None
            else [f"http://127.0.0.1:{DEFAULT_FRONTEND_PORT}"]
        ),
        allowed_hosts=(
            [public_host, "127.0.0.1", "localhost"]
            if public_host is not None
            else ["127.0.0.1", "localhost", "testserver", "test"]
        ),
        auth=(
            {
                "cookie_name": "__Host-smhai_session",
                "secure_cookie": True,
                "same_site": "lax",
            }
            if public_origin is not None
            else {"cookie_name": "psynova_school_session"}
        ),
        cat=ModuleClientSettings(
            mode="http", base_url=f"http://127.0.0.1:{DEFAULT_CAT_PORT}"
        ),
        rag=ModuleClientSettings(mode="http", base_url="http://127.0.0.1:8170"),
        llm=LLMModuleClientSettings(mode="http", base_url="http://127.0.0.1:8160"),
        safety=ModuleClientSettings(mode="http", base_url="http://127.0.0.1:8190"),
        post_assessment_worker={"enabled": False},
        research_education_worker={"enabled": False},
    )


def _public_web_origin() -> tuple[str | None, str | None]:
    """Return a strictly validated HTTPS origin and DNS host, if configured."""

    raw_origin = os.environ.get("PSYNOVA_PUBLIC_ORIGIN")
    if raw_origin is None or not raw_origin.strip():
        return None, None
    if raw_origin != raw_origin.strip():
        raise ValueError("public origin configuration is invalid")

    try:
        parsed = urlsplit(raw_origin)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("public origin configuration is invalid") from exc

    if (
        parsed.scheme != "https"
        or host is None
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("public origin must be one HTTPS DNS origin")

    normalized_host = host.lower().rstrip(".")
    if not _DNS_HOST_RE.fullmatch(normalized_host):
        raise ValueError("public origin host is invalid")
    return f"https://{normalized_host}", normalized_host


def main() -> int:
    args = _parser().parse_args()
    try:
        repo = args.repo_root.resolve(strict=True)
        sys.path.insert(0, str(repo / "13_deployment"))
        sys.path.insert(0, str(repo / "09_backend" / "src"))
        sys.path.insert(0, str(repo / "11_database"))

        from linux_school_runtime import (
            configure_import_paths,
            load_school_runtime_credentials,
            validate_key_credential,
            verify_mysql_school_schema,
        )

        configure_import_paths(repo)
        credentials = load_school_runtime_credentials()
        key_version = validate_key_credential()
        database = verify_mysql_school_schema(credentials)

        # Prevent Pydantic's dotenv behavior and inherited deployment overrides.
        for name in tuple(os.environ):
            if name.startswith(("DB_", "SMHAI_")) or name in {
                "DATABASE_URL",
                "MYSQL_PWD",
            }:
                os.environ.pop(name, None)
        os.environ["DATABASE_AUTH_CREDENTIAL"] = "school-runtime.json"
        os.environ["DATABASE_KEY_FILE"] = "database-keys.json"

        from smhai_backend.app_factory import create_app
        settings = _build_school_backend_settings(credentials.csrf_secret)
        app = create_app(settings=settings)
        summary = {
            "backend": "school_tenant",
            "database": database["database"],
            "mysql_version": database["mysql_version"],
            "revision": database["revision"],
            "key_version": key_version,
            "host": "127.0.0.1",
            "port": DEFAULT_BACKEND_PORT,
            "module_clients": "http",
            "cat_safety_rag_status": "not_part_of_this_deployment_stage",
        }
        if args.preflight_only:
            print(json.dumps(dict(summary, preflight="PASS"), sort_keys=True))
            return 0

        import uvicorn

        uvicorn.run(
            app,
            host="127.0.0.1",
            port=DEFAULT_BACKEND_PORT,
            access_log=False,
            log_config=None,
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - no driver or credential details reach logs.
        print(
            json.dumps(
                {"school_backend": "BLOCKED", "error_type": type(exc).__name__},
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
