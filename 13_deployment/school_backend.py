"""Run the isolated synthetic school backend on loopback, using sealed settings.

This foreground entrypoint neither migrates databases nor seeds accounts. The
owner's launcher must manage its process lifetime. Real module HTTP clients are
required; an unavailable dependency is an error, never a fake response fallback.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from datetime import UTC, datetime
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
_RESEARCH_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_RESEARCH_SERVICE_SCHEMA = "psynova.research-cat-service.v1"
_RESEARCH_SERVICE_FIELDS = frozenset(
    {
        "schema", "school_scope", "resource_root", "listener", "signing",
        "profiles", "bindings",
    }
)
_RESEARCH_SERVICE_MAX_BYTES = 1024 * 1024
_RESEARCH_CONFIG_ARGUMENTS = (
    "research_runtime_file",
    "research_runtime_sha256",
    "research_service_file",
    "research_service_sha256",
    "research_cat_python",
    "research_cat_source",
    "research_cat_dependencies",
)
_RESEARCH_STUDY_USE_ARGUMENTS = (
    "research_study_use_file",
    "research_study_use_sha256",
    "research_source_rights_verified",
    "research_latest_study_end",
)
_RESEARCH_STUDY_END = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)\Z"
)


class ResearchCLIConfigError(PreparationError):
    """Sanitized launcher error for the optional research process configuration."""

    def __init__(self, code: str) -> None:
        allowed = {
            "research_config_incomplete",
            "research_config_invalid",
            "research_service_config_invalid",
            "research_config_pair_mismatch",
            "study_use_config_incomplete",
            "study_use_config_invalid",
            "research_worker_requires_pinned_study_use",
            "research_worker_config_invalid",
        }
        self.code = code if code in allowed else "research_config_invalid"
        super().__init__(self.code)


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
    parser.add_argument("--research-runtime-file", type=Path)
    parser.add_argument("--research-runtime-sha256")
    parser.add_argument("--research-service-file", type=Path)
    parser.add_argument("--research-service-sha256")
    parser.add_argument("--research-cat-python", type=Path)
    parser.add_argument("--research-cat-source", type=Path)
    parser.add_argument("--research-cat-dependencies", type=Path)
    parser.add_argument("--research-study-use-file", type=Path)
    parser.add_argument("--research-study-use-sha256")
    parser.add_argument("--research-source-rights-verified", action="store_true")
    parser.add_argument("--research-latest-study-end")
    parser.add_argument("--enable-research-education-worker", action="store_true")
    return parser


def build_research_settings_kwargs(args: argparse.Namespace, workspace: Path) -> dict[str, object]:
    """Validate explicit, non-secret research paths and map them to Core settings.

    This only reads the two public configuration files. It never reads profile
    response data, provisions eligibility, or creates/starts the CAT process.
    """
    values = {name: getattr(args, name, None) for name in _RESEARCH_CONFIG_ARGUMENTS}
    supplied = tuple(value is not None for value in values.values())
    study_values = {
        name: getattr(args, name, False if name == "research_source_rights_verified" else None)
        for name in _RESEARCH_STUDY_USE_ARGUMENTS
    }
    study_present = any(
        value is not None and (name != "research_source_rights_verified" or value is True)
        for name, value in study_values.items()
    )
    worker_enabled = getattr(args, "enable_research_education_worker", False)
    if type(worker_enabled) is not bool:
        raise ResearchCLIConfigError("research_worker_config_invalid")
    if not any(supplied) and not study_present:
        if worker_enabled:
            raise ResearchCLIConfigError("research_worker_requires_pinned_study_use")
        return {}
    if not all(supplied):
        raise ResearchCLIConfigError("research_config_incomplete")
    study_supplied = tuple(
        value is not None if name != "research_source_rights_verified" else value is True
        for name, value in study_values.items()
    )
    if any(study_supplied) and not all(study_supplied):
        raise ResearchCLIConfigError("study_use_config_incomplete")
    if worker_enabled and not all(study_supplied):
        raise ResearchCLIConfigError("research_worker_requires_pinned_study_use")

    try:
        root = _validated_absolute_path(workspace, kind="directory")
        runtime_file = _validated_absolute_path(values["research_runtime_file"], kind="file")
        service_file = _validated_absolute_path(values["research_service_file"], kind="file")
        if not runtime_file.is_relative_to(root) or not service_file.is_relative_to(root):
            raise ValueError
        runtime_sha256 = _validated_sha256(values["research_runtime_sha256"])
        service_sha256 = _validated_sha256(values["research_service_sha256"])
        cat_python = _validated_absolute_path(values["research_cat_python"], kind="file")
        cat_source = _validated_absolute_path(values["research_cat_source"], kind="directory")
        cat_dependencies = _validated_absolute_path(
            values["research_cat_dependencies"], kind="directory"
        )
        base_url = _research_service_base_url(service_file, service_sha256)
        study_settings: dict[str, object] = {}
        if all(study_supplied):
            study_file = _validated_absolute_path(
                study_values["research_study_use_file"], kind="file"
            )
            if not study_file.is_relative_to(root):
                raise ValueError
            study_sha256 = _validated_sha256(
                study_values["research_study_use_sha256"]
            )
            if study_values["research_source_rights_verified"] is not True:
                raise ResearchCLIConfigError("study_use_config_invalid")
            study_end = _parse_study_end(study_values["research_latest_study_end"])
            _validate_study_use_policy(
                study_file=study_file,
                study_sha256=study_sha256,
                latest_end=study_end,
                runtime_file=runtime_file,
                runtime_sha256=runtime_sha256,
                service_file=service_file,
                service_sha256=service_sha256,
                base_url=base_url,
            )
            study_settings = {
                "school_research_study_use_file": str(study_file),
                "school_research_study_use_sha256": study_sha256,
                "school_research_source_rights_verified": True,
                "school_research_latest_study_end": study_end,
            }
    except ResearchCLIConfigError:
        raise
    except (OSError, ValueError, TypeError):
        raise ResearchCLIConfigError("research_config_invalid") from None

    return {
        "school_research_enabled": True,
        "school_research_runtime_file": str(runtime_file),
        "school_research_runtime_sha256": runtime_sha256,
        "school_research_base_url": base_url,
        "school_research_managed_enabled": True,
        "school_research_service_file": str(service_file),
        "school_research_service_sha256": service_sha256,
        "school_research_cat_python": str(cat_python),
        "school_research_cat_source": str(cat_source),
        "school_research_cat_dependencies": str(cat_dependencies),
        **(
            {"research_education_worker": {"enabled": True}}
            if worker_enabled else {}
        ),
        **study_settings,
    }


def _parse_study_end(value: object) -> datetime:
    if type(value) is not str or _RESEARCH_STUDY_END.fullmatch(value) is None:
        raise ResearchCLIConfigError("study_use_config_invalid")
    try:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(UTC)
    except (ValueError, OverflowError):
        raise ResearchCLIConfigError("study_use_config_invalid") from None


def _validate_study_use_policy(
    *,
    study_file: Path,
    study_sha256: str,
    latest_end: datetime,
    runtime_file: Path,
    runtime_sha256: str,
    service_file: Path,
    service_sha256: str,
    base_url: str,
) -> None:
    """Validate policy rights and pins against the exact loaded profile registry."""
    try:
        from smhai_backend.domains.school_research.bootstrap import (
            load_research_runtime,
        )
        from smhai_backend.domains.school_research.managed import (
            validate_managed_research_config_pair,
        )
        from smhai_backend.domains.school_research.study_use import (
            load_research_study_use_policy,
        )

        class _NoKeyMaterial:
            @staticmethod
            def get_key(*_args, **_kwargs):
                raise RuntimeError

            @staticmethod
            def versions():
                return ()

        runtime = load_research_runtime(
            configuration_file=runtime_file,
            expected_sha256=runtime_sha256,
            loopback_base_url=base_url,
            retained_key_provider=_NoKeyMaterial(),
        )
        validate_managed_research_config_pair(
            runtime_config_file=runtime_file,
            expected_runtime_config_sha256=runtime_sha256,
            service_config_file=service_file,
            expected_service_config_sha256=service_sha256,
        )
        policy = load_research_study_use_policy(
            study_file,
            expected_sha256=study_sha256,
            source_rights_verified=True,
            latest_allowed_ends_at=latest_end,
        )
        if policy.source_rights_verified is not True or policy.school_id != runtime.school_id:
            raise ValueError

        runtime_document = json.loads(runtime_file.read_text(encoding="utf-8"))
        runtime_refs = {
            entry["profile_ref"]
            for entry in runtime_document["profiles"]
            if type(entry) is dict and type(entry.get("profile_ref")) is str
        }
        if not runtime_refs or any(pin.profile_ref not in runtime_refs for pin in policy.profiles):
            raise ValueError
        for pin in policy.profiles:
            trusted = runtime._registry.load(pin.profile_ref)
            manifest = json.loads(trusted.raw_manifest_bytes.decode("utf-8"))
            if manifest.get("parameter_crosswalk_sha256") != pin.published_crosswalk_sha256:
                raise ValueError
            policy.require_scope(
                school_id=runtime.school_id,
                profile_ref=pin.profile_ref,
                profile_sha256=trusted.profile_sha256,
                manifest_sha256=trusted.manifest_sha256,
                at=datetime.now(UTC),
            )
    except Exception:  # noqa: BLE001 - never expose policy/profile material.
        raise ResearchCLIConfigError("study_use_config_invalid") from None


def _validated_sha256(value: object) -> str:
    if type(value) is not str or _RESEARCH_SHA256.fullmatch(value) is None:
        raise ValueError
    return value


def _validated_absolute_path(value: object, *, kind: str) -> Path:
    if not isinstance(value, Path) or not value.is_absolute() or ".." in value.parts:
        raise ValueError
    _assert_no_reparse_components(value)
    resolved = value.resolve(strict=True)
    mode = resolved.stat().st_mode
    if kind == "file" and not stat.S_ISREG(mode):
        raise ValueError
    if kind == "directory" and not stat.S_ISDIR(mode):
        raise ValueError
    return resolved


def _assert_no_reparse_components(path: Path) -> None:
    """Reject symlinks/junctions in every existing component, including parents."""
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        ):
            raise ValueError
        if hasattr(current, "is_junction") and current.is_junction():
            raise ValueError


def _research_service_base_url(service_file: Path, expected_sha256: str) -> str:
    with service_file.open("rb") as stream:
        raw = stream.read(_RESEARCH_SERVICE_MAX_BYTES + 1)
    if not raw or len(raw) > _RESEARCH_SERVICE_MAX_BYTES:
        raise ResearchCLIConfigError("research_service_config_invalid")
    if not hashlib.sha256(raw).hexdigest() == expected_sha256:
        raise ResearchCLIConfigError("research_service_config_invalid")

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    def reject_constant(_value: str) -> None:
        raise ValueError

    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
        listener = document["listener"]
        if (
            type(document) is not dict
            or set(document) != _RESEARCH_SERVICE_FIELDS
            or document.get("schema") != _RESEARCH_SERVICE_SCHEMA
            or type(listener) is not dict
            or set(listener) != {"host", "port"}
            or listener.get("host") != "127.0.0.1"
            or type(listener.get("port")) is not int
            or not 1024 <= listener["port"] <= 65535
        ):
            raise ValueError
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        raise ResearchCLIConfigError("research_service_config_invalid") from None
    return f"http://127.0.0.1:{listener['port']}"


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


def build_cli_settings_kwargs(
    args: argparse.Namespace,
) -> tuple[dict[str, object], dict[str, object]]:
    """Map CLI options and explicitly override worker environment defaults."""
    settings_kwargs = build_school_settings_kwargs(
        args.port, args.frontend_port, args.llm_profile, cat_port=args.cat_port
    )
    research_kwargs = build_research_settings_kwargs(args, args.workspace)
    settings_kwargs.update(research_kwargs)
    settings_kwargs["research_education_worker"] = {
        "enabled": args.enable_research_education_worker
    }
    return settings_kwargs, research_kwargs


def main() -> int:
    args = build_parser().parse_args()
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo / "11_database" / ".venv" / "Lib" / "site-packages"))
    sys.path.insert(0, str(repo / "11_database"))
    sys.path.insert(0, str(repo / "09_backend" / "src"))
    try:
        settings_kwargs, research_kwargs = build_cli_settings_kwargs(args)
        if research_kwargs:
            try:
                from smhai_backend.domains.school_research.managed import (
                    validate_managed_research_config_pair,
                )

                validate_managed_research_config_pair(
                    runtime_config_file=Path(
                        research_kwargs["school_research_runtime_file"]
                    ),
                    expected_runtime_config_sha256=research_kwargs[
                        "school_research_runtime_sha256"
                    ],
                    service_config_file=Path(
                        research_kwargs["school_research_service_file"]
                    ),
                    expected_service_config_sha256=research_kwargs[
                        "school_research_service_sha256"
                    ],
                )
            except Exception:  # noqa: BLE001 - suppress config paths and low-level details.
                raise ResearchCLIConfigError("research_config_pair_mismatch") from None
        # Configuration validation is pure and precedes sealed runtime/key access.
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
    except ResearchCLIConfigError as exc:
        print(json.dumps({"school_backend": "BLOCKED", "error_code": exc.code}))
        return 2
    except Exception as exc:  # noqa: BLE001 - only emit error type; details may contain credentials.
        print(json.dumps({"school_backend": "BLOCKED", "error_type": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
