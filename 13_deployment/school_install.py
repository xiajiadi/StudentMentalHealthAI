"""Prepare a fresh, synthetic school workspace with existing offline tools.

This command composes dependency preparation, the isolated workspace tools,
the owned preview lifecycle, and the four-role browser check. It never
downloads or redistributes model/service assets and never resets an existing
workspace.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DEPLOYMENT = REPO / "13_deployment"
STATE_SCHEMA = "psynova.school-install-checkpoint.v1"
STATE_SUFFIX = ".school-install-state.json"
STATE_TEMP_SUFFIX = ".school-install-state.json.tmp"
PYTHON_MODULES = (
    "01_cat-engine",
    "09_backend",
    "11_database",
    "05_rag-engine",
    "06_llm-runtime",
    "08_safety-engine",
)
DEPENDENCY_PLAN_STAGE_NAMES = (*PYTHON_MODULES, "10_frontend")
DEPENDENCY_RECEIPT_STAGE_NAMES = (*DEPENDENCY_PLAN_STAGE_NAMES, "manifest_integrity")
STAGE_NAMES = (
    "dependencies",
    "workspace",
    "schema",
    "runtime_identity",
    "synthetic_seed",
    "application",
    "four_role_browser",
)

SYNTHETIC_SEED_EXPECTED_RESULT = {
    "recipe": "school-contexts-v1",
    "schools": 2,
    "subjects": 2,
    "role_accounts": 8,
    "credentials": "current-user DPAPI",
    "specialist_subject_grants": 0,
    "admin_subject_grants": 0,
}
CHECKPOINT_FIELDS = {
    "schema", "created_at", "updated_at", "source_head", "dependency_target_head",
    "source_root", "dependency_target", "mysql_bin", "python_specs", "workspace",
    "workspace_id", "schema_revision", "ports", "frontend_mode", "llm_profile",
    "dependency_module_manifest_sha256", "research_profile_sha256",
    "workspace_profile_import_state", "stages", "whole_ready",
}
PRE_IMPORT_CHECKPOINT_FIELDS = CHECKPOINT_FIELDS - {"workspace_profile_import_state"}
LEGACY_CHECKPOINT_FIELDS = PRE_IMPORT_CHECKPOINT_FIELDS - {"research_profile_sha256"}
WORKSPACE_PROFILE_IMPORT_STATES = {
    "NOT_REQUIRED", "PENDING", "RUNNING", "COMPLETED", "UNTRACKED",
}
RECOVERABLE_PROFILE_IMPORT_FAILURES = {
    "RESEARCH_PROFILE_TARGET_CONFLICT", "RESEARCH_PROFILE_TARGET_WRITE_FAILED",
}
STAGE_STATUSES = {"PENDING", "RUNNING", "COMPLETED", "FAILED", "PENDING_VERIFICATION"}
SAFE_STAGE_CODES = {
    "VERIFIED_BY_ROLE_LOGIN", "ABSOLUTE_PATH_REQUIRED", "ABSOLUTE_WORKSPACE_REQUIRED",
    "APPLICATION_OWNER_OR_READINESS_UNVERIFIED", "APPLICATION_PORT_INVALID", "APPLICATION_START_FAILED",
    "CHECKPOINT_ALREADY_EXISTS", "CHECKPOINT_FIELDS_INVALID", "CHECKPOINT_INVALID",
    "CHECKPOINT_CONTENT_INVALID", "CHECKPOINT_PERSIST_FAILED", "CHECKPOINT_STAGE_ORDER_INVALID",
    "CHECKPOINT_STAGE_SHAPE_INVALID", "CHECKPOINT_TEMP_CONFLICT",
    "DATABASE_PORT_INVALID", "DEPENDENCY_LOCK_FILE_MISSING", "DEPENDENCY_LOCK_PIN_CHANGED",
    "DEPENDENCY_LOCK_RECEIPT_INVALID", "DEPENDENCY_MANIFEST_PIN_CHANGED", "DEPENDENCY_MANIFEST_PIN_INVALID",
    "DEPENDENCY_RECEIPT_NOT_COMPLETE", "DEPENDENCY_RECEIPT_UNAVAILABLE", "DEPENDENCY_TARGET_NOT_CLEAN",
    "FOUR_ROLE_BROWSER_CHECK_FAILED", "FOUR_ROLE_BROWSER_RESULT_INVALID", "FRESH_TARGET_ALREADY_EXISTS",
    "FRONTEND_ENVIRONMENT_MISSING", "GIT_HEAD_INVALID", "GIT_PREFLIGHT_FAILED", "GIT_ROOT_REQUIRED",
    "INCOMPLETE_STAGE_PRESERVED_FOR_INSPECTION", "OFFLINE_DEPENDENCY_PLAN_FAILED",
    "OFFLINE_DEPENDENCY_PLAN_INVALID",
    "OFFLINE_DEPENDENCY_PREPARATION_FAILED", "PATH_RESOLUTION_FAILED", "PORT_COLLISION", "PORT_INVALID",
    "PORT_UNAVAILABLE", "PYTHON_ENVIRONMENT_MISSING", "PYTHON_INTERPRETER_UNAVAILABLE",
    "PYTHON_SPEC_INVALID", "PYTHON_SPEC_SET_INCOMPLETE", "REPARSE_PATH_REJECTED",
    "RESUME_CONFIGURATION_MISMATCH", "RESUME_STATE_UNAVAILABLE", "RUNTIME_IDENTITY_CREATION_FAILED",
    "RUNTIME_PREFLIGHT_FAILED", "SCHEMA_MIGRATION_DDL_FAILED",
    "RESEARCH_PROFILE_HASH_MISMATCH", "RESEARCH_PROFILE_INVALID",
    "RESEARCH_PROFILE_PATH_INVALID", "RESEARCH_PROFILE_TARGET_CONFLICT",
    "RESEARCH_PROFILE_TARGET_WRITE_FAILED", "RESEARCH_PROFILE_INCOMPLETE",
    "SCHEMA_MIGRATION_FAILED", "SCHEMA_MIGRATION_POSTCHECK_FAILED", "SOURCE_OR_TARGET_MISSING",
    "SOURCE_TARGET_HEAD_MISMATCH", "SOURCE_TARGET_OVERLAP", "SOURCE_TRACKED_FILES_DIRTY",
    "STAGE_PROCESS_UNAVAILABLE", "STAGE_RESULT_INVALID", "STAGE_TIMEOUT_PRESERVE_AND_INSPECT",
    "SYNTHETIC_SEED_FAILED", "SYNTHETIC_SEED_STAGE_INVALID", "VENDOR_MYSQL_BINARY_UNAVAILABLE",
    "WORKSPACE_CREATE_FAILED", "WORKSPACE_DATABASE_SETTINGS_UNAVAILABLE", "WORKSPACE_ID_INVALID",
    "WORKSPACE_IDENTITY_CHANGED", "WORKSPACE_MARKER_INVALID", "WORKSPACE_MARKER_UNAVAILABLE",
    "WORKSPACE_PARENT_UNAVAILABLE", "WORKSPACE_REPOSITORY_OVERLAP", "WORKSPACE_STAGE_NOT_RESTARTABLE",
}
PYTHON_SPEC_RE = re.compile(r"^([0-9]{2}_[a-z0-9-]+)=(.+)$")
WORKSPACE_ID_RE = re.compile(r"^[a-f0-9]{32}$")
RESEARCH_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
RESEARCH_FILE_PAIRS = (
    ("research_runtime_file", "research_runtime_sha256", "--research-runtime-file", "--research-runtime-sha256", 1024 * 1024),
    ("research_service_file", "research_service_sha256", "--research-service-file", "--research-service-sha256", 1024 * 1024),
    ("research_study_use_file", "research_study_use_sha256", "--research-study-use-file", "--research-study-use-sha256", 64 * 1024),
    ("research_programme_manifest_file", "research_programme_manifest_sha256", "--research-programme-manifest-file", "--research-programme-manifest-sha256", 4 * 1024 * 1024),
    ("research_student_config_file", "research_student_config_sha256", "--research-student-config-file", "--research-student-config-sha256", 16 * 1024),
    ("research_education_draft_config_file", "research_education_draft_config_sha256", "--research-education-draft-config-file", "--research-education-draft-config-sha256", 8192),
)
RESEARCH_PATH_ARGUMENTS = (
    ("research_cat_python", "--research-cat-python", "file"),
    ("research_cat_source", "--research-cat-source", "directory"),
    ("research_cat_dependencies", "--research-cat-dependencies", "directory"),
)
RESEARCH_VALUE_ARGUMENTS = (
    ("research_latest_study_end", "--research-latest-study-end"),
)
RESEARCH_BOOLEAN_ARGUMENTS = (
    ("research_source_rights_verified", "--research-source-rights-verified"),
    ("enable_research_education_worker", "--enable-research-education-worker"),
    ("enable_research_programme_worker", "--enable-research-programme-worker"),
    ("enable_research_education_input_review_continuation", "--enable-research-education-input-review-continuation"),
)
WORKSPACE_RESEARCH_FILES = (
    ("research_runtime_file", "research_runtime_sha256", "research-runtime.json"),
    ("research_service_file", "research_service_sha256", "research-service.json"),
    ("research_study_use_file", "research_study_use_sha256", "research-study-use.json"),
)
_EMPTY_RESEARCH_ARGUMENTS = {
    **{name: None for pair in RESEARCH_FILE_PAIRS for name in pair[:2]},
    **{name: None for name, _flag, _kind in RESEARCH_PATH_ARGUMENTS},
    **{name: None for name, _flag in RESEARCH_VALUE_ARGUMENTS},
    **{name: False for name, _flag in RESEARCH_BOOLEAN_ARGUMENTS},
}
RESEARCH_PROFILE_EMPTY_SHA256 = hashlib.sha256(
    json.dumps(
        _EMPTY_RESEARCH_ARGUMENTS,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
).hexdigest()

sys.path.insert(0, str(DEPLOYMENT))
from school_schema import CURRENT_SCHOOL_REVISION


class InstallError(RuntimeError):
    def __init__(self, code: str, *, details: dict[str, Any] | None = None) -> None:
        self.code = code
        self.details = details
        super().__init__(code)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _path(value: Path, *, exists: bool) -> Path:
    if not value.is_absolute():
        raise InstallError("ABSOLUTE_PATH_REQUIRED")
    try:
        resolved = value.resolve(strict=exists)
    except (OSError, RuntimeError):
        raise InstallError("PATH_RESOLUTION_FAILED") from None
    return resolved


def _overlaps(left: Path, right: Path) -> bool:
    try:
        left.relative_to(right)
        return True
    except ValueError:
        pass
    try:
        right.relative_to(left)
        return True
    except ValueError:
        return False


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _is_reparse(path: Path) -> bool:
    try:
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
    except OSError:
        return False


def _reject_reparse_ancestors(path: Path) -> None:
    current = path
    while current != current.parent:
        if _is_reparse(current):
            raise InstallError("REPARSE_PATH_REJECTED")
        current = current.parent


def _parse_python_specs(values: list[str]) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for value in values:
        match = PYTHON_SPEC_RE.fullmatch(value)
        if not match:
            raise InstallError("PYTHON_SPEC_INVALID")
        module, raw_path = match.groups()
        path = Path(raw_path)
        if module not in PYTHON_MODULES or module in parsed or not path.is_absolute():
            raise InstallError("PYTHON_SPEC_INVALID")
        parsed[module] = path
    if set(parsed) != set(PYTHON_MODULES):
        raise InstallError("PYTHON_SPEC_SET_INCOMPLETE")
    return parsed


def _validate_ports(database: int, backend: int, frontend: int, cat: int) -> None:
    values = (database, backend, frontend, cat)
    if any(type(value) is not int for value in values):
        raise InstallError("PORT_INVALID")
    if not 3308 <= database <= 3399:
        raise InstallError("DATABASE_PORT_INVALID")
    if any(not 1024 <= value <= 65535 for value in values[1:]):
        raise InstallError("APPLICATION_PORT_INVALID")
    if len(set(values)) != len(values):
        raise InstallError("PORT_COLLISION")


def _port_available(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


def _check_ports_available(ports: tuple[int, ...]) -> None:
    if any(not _port_available(port) for port in ports):
        raise InstallError("PORT_UNAVAILABLE")


def _git_output(args: list[str], *, cwd: Path) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True,
            timeout=20, check=False, shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise InstallError("GIT_PREFLIGHT_FAILED") from None
    if result.returncode != 0:
        raise InstallError("GIT_PREFLIGHT_FAILED")
    return result.stdout.strip()


def _validate_git_root(root: Path, *, require_clean: bool) -> str:
    if not (root / ".git").exists():
        raise InstallError("GIT_ROOT_REQUIRED")
    head = _git_output(["-C", str(root), "rev-parse", "HEAD"], cwd=REPO)
    if not re.fullmatch(r"[0-9a-f]{40,64}", head):
        raise InstallError("GIT_HEAD_INVALID")
    if require_clean:
        dirty = _git_output(
            ["-C", str(root), "status", "--porcelain", "--untracked-files=all"], cwd=REPO
        )
        if dirty:
            raise InstallError("DEPENDENCY_TARGET_NOT_CLEAN")
    else:
        dirty = _git_output(
            ["-C", str(root), "status", "--porcelain", "--untracked-files=no"], cwd=REPO
        )
        if dirty:
            raise InstallError("SOURCE_TRACKED_FILES_DIRTY")
    return head


def _state_path(workspace: Path) -> Path:
    return workspace.parent / f".{workspace.name}{STATE_SUFFIX}"


def _state_temp_path(workspace: Path) -> Path:
    return workspace.parent / f".{workspace.name}{STATE_TEMP_SUFFIX}"


def _research_argument_values(args: argparse.Namespace) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for name, sha_name, _flag, _sha_flag, _limit in RESEARCH_FILE_PAIRS:
        raw_path = getattr(args, name, None)
        values[name] = str(raw_path) if raw_path is not None else None
        values[sha_name] = getattr(args, sha_name, None)
    for name, _flag, _kind in RESEARCH_PATH_ARGUMENTS:
        raw_path = getattr(args, name, None)
        values[name] = str(raw_path) if raw_path is not None else None
    for name, _flag in RESEARCH_VALUE_ARGUMENTS:
        values[name] = getattr(args, name, None)
    for name, _flag in RESEARCH_BOOLEAN_ARGUMENTS:
        raw_value = getattr(args, name, False)
        if type(raw_value) is not bool:
            raise InstallError("RESEARCH_PROFILE_INVALID")
        values[name] = raw_value
    return values


def _read_pinned_research_file(
    raw_path: Any, expected_sha256: Any, *, max_bytes: int
) -> tuple[Path, bytes]:
    if not isinstance(raw_path, Path) or not raw_path.is_absolute() or ".." in raw_path.parts:
        raise InstallError("RESEARCH_PROFILE_PATH_INVALID")
    if type(expected_sha256) is not str or RESEARCH_SHA256_RE.fullmatch(expected_sha256) is None:
        raise InstallError("RESEARCH_PROFILE_INVALID")
    _reject_reparse_ancestors(raw_path)
    resolved = _path(raw_path, exists=True)
    if not resolved.is_file():
        raise InstallError("RESEARCH_PROFILE_PATH_INVALID")
    try:
        with resolved.open("rb") as stream:
            raw = stream.read(max_bytes + 1)
    except OSError:
        raise InstallError("RESEARCH_PROFILE_PATH_INVALID") from None
    if not raw or len(raw) > max_bytes:
        raise InstallError("RESEARCH_PROFILE_INVALID")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise InstallError("RESEARCH_PROFILE_HASH_MISMATCH")
    return resolved, raw


def _validate_research_profile(
    args: argparse.Namespace, *, source: Path
) -> dict[str, Any]:
    """Validate the opt-in profile inputs without persisting their contents."""
    arguments = _research_argument_values(args)
    file_paths: dict[str, Path] = {}
    for path_name, sha_name, _flag, _sha_flag, max_bytes in RESEARCH_FILE_PAIRS:
        raw_path = getattr(args, path_name, None)
        expected_sha = getattr(args, sha_name, None)
        if (raw_path is None) != (expected_sha is None):
            raise InstallError("RESEARCH_PROFILE_INCOMPLETE")
        if raw_path is None:
            continue
        resolved, _raw = _read_pinned_research_file(
            raw_path, expected_sha, max_bytes=max_bytes
        )
        file_paths[path_name] = resolved
        arguments[path_name] = str(resolved)

    for name, _flag, kind in RESEARCH_PATH_ARGUMENTS:
        raw_path = getattr(args, name, None)
        if raw_path is None:
            continue
        if not isinstance(raw_path, Path) or not raw_path.is_absolute() or ".." in raw_path.parts:
            raise InstallError("RESEARCH_PROFILE_PATH_INVALID")
        _reject_reparse_ancestors(raw_path)
        resolved = _path(raw_path, exists=True)
        if (kind == "file" and not resolved.is_file()) or (
            kind == "directory" and not resolved.is_dir()
        ):
            raise InstallError("RESEARCH_PROFILE_PATH_INVALID")
        arguments[name] = str(resolved)

    core_names = {
        "research_runtime_file", "research_service_file", "research_cat_python",
        "research_cat_source", "research_cat_dependencies",
    }
    core_supplied = any(arguments.get(name) is not None for name in core_names)
    if core_supplied and any(arguments.get(name) is None for name in core_names):
        raise InstallError("RESEARCH_PROFILE_INCOMPLETE")
    study_supplied = any(
        arguments.get(name) is not None
        for name in (
            "research_study_use_file", "research_study_use_sha256",
            "research_latest_study_end",
        )
    ) or arguments["research_source_rights_verified"]
    if study_supplied and (
        not core_supplied
        or arguments.get("research_study_use_file") is None
        or arguments.get("research_study_use_sha256") is None
        or arguments.get("research_latest_study_end") is None
        or arguments["research_source_rights_verified"] is not True
    ):
        raise InstallError("RESEARCH_PROFILE_INCOMPLETE")

    programme_enabled = arguments["enable_research_programme_worker"]
    programme_manifest_supplied = (
        arguments.get("research_programme_manifest_file") is not None
        or arguments.get("research_programme_manifest_sha256") is not None
    )
    if programme_enabled != programme_manifest_supplied:
        raise InstallError("RESEARCH_PROFILE_INCOMPLETE")
    if (arguments["enable_research_education_worker"] or programme_enabled) and not study_supplied:
        raise InstallError("RESEARCH_PROFILE_INCOMPLETE")
    if programme_enabled:
        from school_backend import RESEARCH_PROGRAMME_MANIFEST_SHA256

        if arguments.get("research_programme_manifest_sha256") != RESEARCH_PROGRAMME_MANIFEST_SHA256:
            raise InstallError("RESEARCH_PROFILE_INVALID")

    student_supplied = (
        arguments.get("research_student_config_file") is not None
        or arguments.get("research_student_config_sha256") is not None
    )
    draft_supplied = (
        arguments.get("research_education_draft_config_file") is not None
        or arguments.get("research_education_draft_config_sha256") is not None
    )
    if student_supplied != (
        arguments.get("research_student_config_file") is not None
        and arguments.get("research_student_config_sha256") is not None
    ):
        raise InstallError("RESEARCH_PROFILE_INCOMPLETE")
    if draft_supplied != (
        arguments.get("research_education_draft_config_file") is not None
        and arguments.get("research_education_draft_config_sha256") is not None
    ):
        raise InstallError("RESEARCH_PROFILE_INCOMPLETE")
    if draft_supplied and (not student_supplied or not study_supplied):
        raise InstallError("RESEARCH_PROFILE_INCOMPLETE")
    if arguments["enable_research_education_input_review_continuation"] and not draft_supplied:
        raise InstallError("RESEARCH_PROFILE_INCOMPLETE")

    if core_supplied:
        try:
            backend_source = str(source / "09_backend" / "src")
            if backend_source not in sys.path:
                sys.path.insert(0, backend_source)
            from school_backend import (
                _parse_study_end,
                _research_service_base_url,
                _validate_study_use_policy,
            )
            from smhai_backend.domains.school_research.managed import (
                validate_managed_research_config_pair,
            )

            validate_managed_research_config_pair(
                runtime_config_file=file_paths["research_runtime_file"],
                expected_runtime_config_sha256=arguments["research_runtime_sha256"],
                service_config_file=file_paths["research_service_file"],
                expected_service_config_sha256=arguments["research_service_sha256"],
            )
            if study_supplied:
                base_url = _research_service_base_url(
                    file_paths["research_service_file"],
                    arguments["research_service_sha256"],
                )
                _validate_study_use_policy(
                    study_file=file_paths["research_study_use_file"],
                    study_sha256=arguments["research_study_use_sha256"],
                    latest_end=_parse_study_end(arguments["research_latest_study_end"]),
                    runtime_file=file_paths["research_runtime_file"],
                    runtime_sha256=arguments["research_runtime_sha256"],
                    service_file=file_paths["research_service_file"],
                    service_sha256=arguments["research_service_sha256"],
                    base_url=base_url,
                )
        except InstallError:
            raise
        except (AttributeError, ImportError, OSError, RuntimeError, TypeError, ValueError):
            raise InstallError("RESEARCH_PROFILE_INVALID") from None

    if student_supplied or draft_supplied:
        try:
            if str(DEPLOYMENT) not in sys.path:
                sys.path.insert(0, str(DEPLOYMENT))
            from school_research_education_draft_config import (
                load_research_education_draft_config,
            )
            from school_research_student_config import load_student_research_config

            student = (
                load_student_research_config(
                    file_paths["research_student_config_file"],
                    arguments["research_student_config_sha256"],
                )
                if student_supplied else None
            )
            if draft_supplied:
                draft = load_research_education_draft_config(
                    file_paths["research_education_draft_config_file"],
                    arguments["research_education_draft_config_sha256"],
                )
                if student is None or draft.student_source != student:
                    raise ValueError
        except (AttributeError, ImportError, OSError, TypeError, ValueError):
            raise InstallError("RESEARCH_PROFILE_INVALID") from None

    digest_material = json.dumps(
        arguments, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    digest = hashlib.sha256(digest_material).hexdigest()
    workspace_files = {
        path_name: {
            "source_path": str(file_paths[path_name]),
            "sha256": arguments[sha_name],
            "target_name": target_name,
            "max_bytes": next(item[4] for item in RESEARCH_FILE_PAIRS if item[0] == path_name),
        }
        for path_name, sha_name, target_name in WORKSPACE_RESEARCH_FILES
        if path_name in file_paths
    }
    return {
        "arguments": arguments,
        "file_paths": file_paths,
        "workspace_files": workspace_files,
        "sha256": digest,
        "enabled": any(value is not None and value is not False for value in arguments.values()),
    }


def _validate_configuration(args: argparse.Namespace, *, mode: str) -> dict[str, Any]:
    raw_source = Path(args.source_root)
    raw_target = Path(args.dependency_target_root)
    raw_workspace = Path(args.workspace)
    raw_mysql_bin = Path(args.mysql_bin)
    for raw_path in (raw_source, raw_target, raw_workspace, raw_mysql_bin):
        if raw_path.is_absolute():
            _reject_reparse_ancestors(raw_path)
    source = _path(Path(args.source_root), exists=True)
    dependency_target = _path(Path(args.dependency_target_root), exists=True)
    workspace_arg = raw_workspace
    if not workspace_arg.is_absolute():
        raise InstallError("ABSOLUTE_WORKSPACE_REQUIRED")
    workspace = workspace_arg.resolve(strict=False)
    mysql_bin = _path(Path(args.mysql_bin), exists=True)
    python_specs = _parse_python_specs(args.python)
    _validate_ports(args.database_port, args.backend_port, args.frontend_port, args.standard_cat_port)
    if not source.is_dir() or not dependency_target.is_dir():
        raise InstallError("SOURCE_OR_TARGET_MISSING")
    if not mysql_bin.is_dir() or not (mysql_bin / "mysqld.exe").is_file():
        raise InstallError("VENDOR_MYSQL_BINARY_UNAVAILABLE")
    if not workspace.parent.is_dir() or workspace == Path(workspace.anchor):
        raise InstallError("WORKSPACE_PARENT_UNAVAILABLE")
    _reject_reparse_ancestors(source)
    _reject_reparse_ancestors(dependency_target)
    _reject_reparse_ancestors(workspace.parent)
    if workspace.exists():
        _reject_reparse_ancestors(workspace)
    if _overlaps(source, dependency_target):
        raise InstallError("SOURCE_TARGET_OVERLAP")
    if any(_overlaps(workspace, root) for root in (source, dependency_target)):
        raise InstallError("WORKSPACE_REPOSITORY_OVERLAP")
    source_head = _validate_git_root(source, require_clean=False)
    target_head = _validate_git_root(dependency_target, require_clean=mode != "resume")
    if source_head != target_head:
        raise InstallError("SOURCE_TARGET_HEAD_MISMATCH")
    state_path = _state_path(workspace)
    state_temp_path = _state_temp_path(workspace)
    _reject_reparse_ancestors(state_path)
    _reject_reparse_ancestors(state_temp_path)
    if state_path.exists() and _is_reparse(state_path):
        raise InstallError("REPARSE_PATH_REJECTED")
    if state_temp_path.exists() and _is_reparse(state_temp_path):
        raise InstallError("REPARSE_PATH_REJECTED")
    if mode == "install":
        if workspace.exists() or state_path.exists() or state_temp_path.exists():
            raise InstallError("FRESH_TARGET_ALREADY_EXISTS")
    else:
        if not state_path.is_file() or state_temp_path.exists():
            raise InstallError("RESUME_STATE_UNAVAILABLE")
    for module, interpreter in python_specs.items():
        _reject_reparse_ancestors(interpreter)
        resolved = _path(interpreter, exists=True)
        if not resolved.is_file():
            raise InstallError("PYTHON_INTERPRETER_UNAVAILABLE")
        python_specs[module] = resolved
    research_profile = _validate_research_profile(args, source=source)
    return {
        "source": source,
        "dependency_target": dependency_target,
        "workspace": workspace,
        "mysql_bin": mysql_bin,
        "python_specs": python_specs,
        "source_head": source_head,
        "target_head": target_head,
        "state_path": state_path,
        "state_temp_path": state_temp_path,
        "ports": {
            "database": args.database_port,
            "backend": args.backend_port,
            "frontend": args.frontend_port,
            "standard_cat": args.standard_cat_port,
        },
        "frontend_mode": args.frontend_mode,
        "llm_profile": args.llm_profile,
        "research_profile": research_profile,
    }


def _minimal_env(*, include_caches: bool = False) -> dict[str, str]:
    allowed = {
        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERNAME", "USERPROFILE",
        "LOCALAPPDATA", "APPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
        "PLAYWRIGHT_BROWSERS_PATH",
    }
    if include_caches:
        allowed.update({
            "UV_CACHE_DIR", "PIP_CACHE_DIR", "NPM_CONFIG_CACHE", "NPM_CONFIG_TMP",
            "HF_HOME", "TRANSFORMERS_CACHE", "TORCH_HOME",
        })
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def _run_json(command: list[str], *, timeout: int, include_caches: bool = False) -> tuple[int, dict[str, Any]]:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", timeout=timeout,
            check=False, shell=False, env=_minimal_env(include_caches=include_caches),
        )
    except subprocess.TimeoutExpired:
        raise InstallError("STAGE_TIMEOUT_PRESERVE_AND_INSPECT") from None
    except OSError:
        raise InstallError("STAGE_PROCESS_UNAVAILABLE") from None
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        raise InstallError("STAGE_RESULT_INVALID") from None
    if type(payload) is not dict:
        raise InstallError("STAGE_RESULT_INVALID")
    return result.returncode, payload


def _write_state(state_path: Path, temp_path: Path, state: dict[str, Any], *, initial: bool = False) -> None:
    if set(state) != CHECKPOINT_FIELDS:
        raise InstallError("CHECKPOINT_FIELDS_INVALID")
    _validate_checkpoint_metadata(state)
    if (
        type(state.get("stages")) is not dict
        or set(state["stages"]) != set(STAGE_NAMES)
        or any(
            type(value) is not dict
            or set(value) != {"status", "code"}
            or value.get("status") not in STAGE_STATUSES
            or (value.get("code") is not None and value.get("code") not in SAFE_STAGE_CODES)
            for value in state["stages"].values()
        )
    ):
        raise InstallError("CHECKPOINT_STAGE_SHAPE_INVALID")
    _validate_stage_progression(state["stages"])
    if temp_path.exists():
        raise InstallError("CHECKPOINT_TEMP_CONFLICT")
    if initial and state_path.exists():
        raise InstallError("CHECKPOINT_ALREADY_EXISTS")
    state["updated_at"] = _utc_now()
    raw = (json.dumps(state, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(temp_path, flags, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, state_path)
    except OSError:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise InstallError("CHECKPOINT_PERSIST_FAILED") from None


def _read_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise InstallError("CHECKPOINT_INVALID") from None
    if type(value) is dict and set(value) == LEGACY_CHECKPOINT_FIELDS:
        value["research_profile_sha256"] = RESEARCH_PROFILE_EMPTY_SHA256
    if type(value) is dict and set(value) == PRE_IMPORT_CHECKPOINT_FIELDS:
        stages = value.get("stages")
        stage = stages.get("workspace", {}) if type(stages) is dict else {}
        if type(stage) is dict and stage.get("status") == "COMPLETED":
            value["workspace_profile_import_state"] = (
                "NOT_REQUIRED"
                if value.get("research_profile_sha256") == RESEARCH_PROFILE_EMPTY_SHA256
                else "COMPLETED"
            )
        else:
            # Prior versions did not persist the copy boundary. Never infer
            # resumability for a RUNNING/FAILED workspace from its file tree.
            value["workspace_profile_import_state"] = "UNTRACKED"
    if (
        type(value) is not dict
        or set(value) != CHECKPOINT_FIELDS
        or value.get("schema") != STATE_SCHEMA
        or type(value.get("stages")) is not dict
        or set(value["stages"]) != set(STAGE_NAMES)
        or any(
            type(stage) is not dict
            or set(stage) != {"status", "code"}
            or stage.get("status") not in STAGE_STATUSES
            or (stage.get("code") is not None and stage.get("code") not in SAFE_STAGE_CODES)
            for stage in value["stages"].values()
        )
    ):
        raise InstallError("CHECKPOINT_INVALID")
    try:
        _validate_checkpoint_metadata(value)
        _validate_stage_progression(value["stages"])
    except InstallError:
        raise InstallError("CHECKPOINT_INVALID") from None
    return value


def _validate_checkpoint_metadata(value: dict[str, Any]) -> None:
    if (
        value.get("schema") != STATE_SCHEMA
        or not re.fullmatch(r"[0-9a-f]{40,64}", str(value.get("source_head", "")))
        or not re.fullmatch(r"[0-9a-f]{40,64}", str(value.get("dependency_target_head", "")))
        or value.get("schema_revision") != CURRENT_SCHOOL_REVISION
        or value.get("whole_ready") is not False
        or value.get("frontend_mode") != "preview"
        or value.get("llm_profile") != "school-gpu-7b"
        or type(value.get("ports")) is not dict
        or set(value["ports"]) != {"database", "backend", "frontend", "standard_cat"}
        or type(value.get("python_specs")) is not dict
        or set(value["python_specs"]) != set(PYTHON_MODULES)
        or any(not isinstance(path, str) or not Path(path).is_absolute() for path in value["python_specs"].values())
        or any(not isinstance(value.get(key), str) or not Path(value[key]).is_absolute()
               for key in ("source_root", "dependency_target", "mysql_bin", "workspace"))
        or value.get("workspace_id") is not None
        and (not isinstance(value.get("workspace_id"), str) or not WORKSPACE_ID_RE.fullmatch(value["workspace_id"]))
        or value.get("dependency_module_manifest_sha256") is not None
        and (not isinstance(value.get("dependency_module_manifest_sha256"), str)
             or not re.fullmatch(r"[a-f0-9]{64}", value["dependency_module_manifest_sha256"]))
        or not isinstance(value.get("research_profile_sha256"), str)
        or not RESEARCH_SHA256_RE.fullmatch(value["research_profile_sha256"])
        or type(value.get("workspace_profile_import_state")) is not str
        or value["workspace_profile_import_state"] not in WORKSPACE_PROFILE_IMPORT_STATES
    ):
        raise InstallError("CHECKPOINT_CONTENT_INVALID")
    for key in ("created_at", "updated_at"):
        timestamp = value.get(key)
        if not isinstance(timestamp, str) or len(timestamp) > 64:
            raise InstallError("CHECKPOINT_CONTENT_INVALID")
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            raise InstallError("CHECKPOINT_CONTENT_INVALID") from None


def _validate_stage_progression(stages: dict[str, Any]) -> None:
    statuses = [stages[name]["status"] for name in STAGE_NAMES]
    if all(value == "COMPLETED" for value in statuses):
        return
    seed_index = STAGE_NAMES.index("synthetic_seed")
    if statuses[seed_index] == "PENDING_VERIFICATION":
        if any(value != "COMPLETED" for value in statuses[:seed_index]):
            raise InstallError("CHECKPOINT_STAGE_ORDER_INVALID")
        if statuses[-1] == "COMPLETED":
            raise InstallError("CHECKPOINT_STAGE_ORDER_INVALID")
        if statuses[-1] != "PENDING" and statuses[-2] != "COMPLETED":
            raise InstallError("CHECKPOINT_STAGE_ORDER_INVALID")
        if statuses[-2] in {"RUNNING", "FAILED"} and statuses[-1] != "PENDING":
            raise InstallError("CHECKPOINT_STAGE_ORDER_INVALID")
        return
    saw_incomplete = False
    for status in statuses:
        if status != "COMPLETED":
            saw_incomplete = True
        elif saw_incomplete:
            raise InstallError("CHECKPOINT_STAGE_ORDER_INVALID")


def _new_state(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": STATE_SCHEMA,
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "source_head": config["source_head"],
        "dependency_target_head": config["target_head"],
        "source_root": str(config["source"]),
        "dependency_target": str(config["dependency_target"]),
        "mysql_bin": str(config["mysql_bin"]),
        "python_specs": {name: str(path) for name, path in config["python_specs"].items()},
        "workspace": str(config["workspace"]),
        "workspace_id": None,
        "schema_revision": CURRENT_SCHOOL_REVISION,
        "ports": config["ports"],
        "frontend_mode": config["frontend_mode"],
        "llm_profile": config["llm_profile"],
        "research_profile_sha256": config.get("research_profile", {}).get(
            "sha256", RESEARCH_PROFILE_EMPTY_SHA256
        ),
        "workspace_profile_import_state": (
            "PENDING"
            if config.get("research_profile", {}).get("workspace_files")
            else "NOT_REQUIRED"
        ),
        "dependency_module_manifest_sha256": None,
        "stages": {name: {"status": "PENDING", "code": None} for name in STAGE_NAMES},
        "whole_ready": False,
    }


def _match_state(state: dict[str, Any], config: dict[str, Any]) -> None:
    expected = {
        "source_head": config["source_head"],
        "dependency_target_head": config["target_head"],
        "source_root": str(config["source"]),
        "dependency_target": str(config["dependency_target"]),
        "mysql_bin": str(config["mysql_bin"]),
        "python_specs": {name: str(path) for name, path in config["python_specs"].items()},
        "workspace": str(config["workspace"]),
        "schema_revision": CURRENT_SCHOOL_REVISION,
        "ports": config["ports"],
        "frontend_mode": config["frontend_mode"],
        "llm_profile": config["llm_profile"],
        "research_profile_sha256": config.get("research_profile", {}).get(
            "sha256", RESEARCH_PROFILE_EMPTY_SHA256
        ),
    }
    if any(state.get(key) != value for key, value in expected.items()):
        raise InstallError("RESUME_CONFIGURATION_MISMATCH")


def _validate_resume_workspace_binding(
    state: dict[str, Any], *, workspace_exists: bool,
    allow_profile_import_recovery: bool = False,
) -> None:
    stage_status = state["stages"]["workspace"]["status"]
    workspace_id = state.get("workspace_id")
    if stage_status in {"RUNNING", "FAILED"}:
        code = state["stages"]["workspace"].get("code")
        recoverable = (
            allow_profile_import_recovery
            and workspace_exists
            and isinstance(workspace_id, str)
            and WORKSPACE_ID_RE.fullmatch(workspace_id) is not None
            and (
                (
                    stage_status == "RUNNING"
                    and code is None
                    and state.get("workspace_profile_import_state")
                    in {"PENDING", "RUNNING", "COMPLETED"}
                )
                or (
                    stage_status == "FAILED"
                    and code in RECOVERABLE_PROFILE_IMPORT_FAILURES
                    and state.get("workspace_profile_import_state") in {"PENDING", "RUNNING"}
                )
            )
            and state["stages"]["dependencies"]["status"] == "COMPLETED"
            and all(
                state["stages"][name]["status"] == "PENDING"
                for name in STAGE_NAMES[STAGE_NAMES.index("workspace") + 1:]
            )
        )
        if not recoverable:
            raise InstallError("INCOMPLETE_STAGE_PRESERVED_FOR_INSPECTION")
        return
    if not workspace_exists:
        if (
            stage_status != "PENDING"
            or workspace_id is not None
            or any(state["stages"][name]["status"] != "PENDING"
                   for name in STAGE_NAMES[STAGE_NAMES.index("workspace") + 1:])
        ):
            raise InstallError("WORKSPACE_STAGE_NOT_RESTARTABLE")
        return
    if stage_status != "COMPLETED" or not isinstance(workspace_id, str) or not WORKSPACE_ID_RE.fullmatch(workspace_id):
        raise InstallError("WORKSPACE_STAGE_NOT_RESTARTABLE")


def _workspace_marker(path: Path) -> dict[str, Any]:
    try:
        marker = json.loads((path / "workspace.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise InstallError("WORKSPACE_MARKER_UNAVAILABLE") from None
    if (
        type(marker) is not dict
        or marker.get("schema_version") != "psynova.synthetic-workspace.v1"
        or marker.get("project") != "StudentMentalHealthAI"
        or marker.get("synthetic_only") is not True
        or marker.get("state") != "READY_FOR_MIGRATION"
        or marker.get("host") != "127.0.0.1"
        or marker.get("database") != "smhai_school_demo"
        or type(marker.get("port")) is not int
        or type(marker.get("workspace_id")) is not str
        or not WORKSPACE_ID_RE.fullmatch(marker["workspace_id"])
    ):
        raise InstallError("WORKSPACE_MARKER_INVALID")
    return marker


def _verify_profile_import_workspace_identity(
    config: dict[str, Any], state: dict[str, Any],
) -> None:
    """Revalidate the already-created workspace before completing file imports."""
    workspace = config["workspace"]
    marker = _workspace_marker(workspace)
    if (
        marker.get("workspace_id") != state.get("workspace_id")
        or marker.get("port") != config["ports"]["database"]
    ):
        raise InstallError("WORKSPACE_IDENTITY_CHANGED")
    private_path = workspace / "database.private.dpapi"
    _reject_reparse_ancestors(private_path)
    if not private_path.is_file():
        raise InstallError("WORKSPACE_DATABASE_SETTINGS_UNAVAILABLE")
    private: dict[str, Any] | None = None
    try:
        from prepare_school_runtime import validate_marker, verify_process
        from private_settings import read_private

        verified_marker = validate_marker(workspace, REPO)
        if (
            verified_marker.get("workspace_id") != state.get("workspace_id")
            or verified_marker.get("port") != config["ports"]["database"]
        ):
            raise ValueError
        verify_process(verified_marker)
        private = read_private(private_path)
        if (
            private.get("DB_HOST") != "127.0.0.1"
            or private.get("DB_NAME") != verified_marker.get("database")
            or type(private.get("DB_PORT")) is not str
            or int(private["DB_PORT"]) != verified_marker.get("port")
        ):
            raise ValueError
    except Exception:  # noqa: BLE001 - identity failures remain content-free.
        raise InstallError("WORKSPACE_IDENTITY_CHANGED") from None
    finally:
        if private is not None:
            private.clear()


def _dependency_receipt(config: dict[str, Any]) -> dict[str, Any]:
    state_file = config["dependency_target"] / ".school-dependency-preparation-state.json"
    try:
        receipt = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise InstallError("DEPENDENCY_RECEIPT_UNAVAILABLE") from None
    stages = receipt.get("stages") if type(receipt) is dict else None
    if (
        receipt.get("schema_version") != "school-dependency-preparation.v1"
        or receipt.get("mode") != "install"
        or receipt.get("run_state") != "completed"
        or receipt.get("source_head") != config["source_head"]
        or receipt.get("target_head") != config["target_head"]
        or receipt.get("module_manifest_sha256") != receipt.get("target_module_manifest_sha256")
        or receipt.get("lock_sha256") != receipt.get("target_lock_sha256")
        or receipt.get("state_persistence") != "succeeded"
        or not _dependency_stages_match(
            stages, DEPENDENCY_RECEIPT_STAGE_NAMES, expected_state="succeeded", require_success_exit=True,
        )
    ):
        raise InstallError("DEPENDENCY_RECEIPT_NOT_COMPLETE")
    return receipt


DEPENDENCY_RETRY_SCHEMA = "psynova.school-install-dependency-retry.v1"
DEPENDENCY_RETRY_START_FIELDS = {
    "schema", "source_root", "dependency_target", "workspace", "source_head",
    "dependency_target_head", "attempt", "prior_failure_code", "started_at",
}
DEPENDENCY_RETRY_RESULT_FIELDS = {
    "schema", "source_root", "dependency_target", "workspace", "source_head",
    "dependency_target_head", "attempt", "status", "finished_at", "exit_code",
    "stage", "error_code", "install_code",
}
DEPENDENCY_CHILD_STAGES = frozenset((*DEPENDENCY_RECEIPT_STAGE_NAMES, "preflight", "runner", "child_output", "process"))
DEPENDENCY_CHILD_ERROR_CODES = frozenset({
    "CommandFailed", "DuplicatePythonMapping", "FileNotFoundError", "FrontendCheckFailed",
    "GitInspectionFailed", "ImportCheckFailed", "InterpreterMustBeAbsolute", "InterpreterProbeFailed",
    "InvalidFrontendLock", "InvalidGitHead", "InvalidInterpreter", "InvalidJson", "InvalidPath", "InvalidResponse",
    "InvalidPythonManifest", "InvalidPythonMapping", "MissingManifestOrLock", "MissingPythonMapping",
    "MissingTargetManifest", "MissingTargetModule", "MissingTool", "MissingTrustedModuleManifest",
    "MissingTrustedNpmCli", "NpmConfigArtifactCreationFailed", "NpmConfigArtifactExists", "NestedRepository",
    "PermissionError", "PostInstallManifestChanged", "PostInstallManifestCheckFailed",
    "PythonRequirementMismatch", "PythonVersionMismatch", "ReparsePoint", "RepositoryRootMismatch",
    "RootsMustBeAbsolute", "SourceCannotBeInstallTarget", "SourceTargetOverlap", "StatePersistenceFailed",
    "SystemTarget", "TargetEnvironmentExists", "TargetHasUntrackedOrIgnoredFiles", "TargetHeadMismatch",
    "TargetLockMismatch", "TargetManifestMismatch", "TargetModuleNotDirectory", "TimeoutExpired",
    "TrackedFilesDifferFromHead", "UnknownGitConfig", "UnregisteredModule", "UnexpectedError",
    "UnsupportedBuildSystem", "UnsupportedFrontendLockSource", "UnsupportedGitlink", "UnsupportedIndexFlags",
    "UnsupportedPackageManagerConfig", "UnsupportedPythonLockSource", "UnsupportedUvProjectConfig",
    "UntrustedExecutableWrapper", "MissingTool:node.exe", "MissingTool:uv.exe",
})
DEPENDENCY_CHILD_FAILURE_INSTALL_CODES = {
    "MissingManifestOrLock": "DEPENDENCY_LOCK_FILE_MISSING",
    "TargetHasUntrackedOrIgnoredFiles": "DEPENDENCY_TARGET_NOT_CLEAN",
    "TargetLockMismatch": "DEPENDENCY_LOCK_PIN_CHANGED",
    "TargetManifestMismatch": "DEPENDENCY_MANIFEST_PIN_CHANGED",
    "SourceTargetOverlap": "SOURCE_TARGET_OVERLAP",
}
DEPENDENCY_PIN_FILES = (
    "MODULES.md",
    *(f"{module}/{filename}" for module in PYTHON_MODULES for filename in ("pyproject.toml", "uv.lock")),
    "10_frontend/package.json",
    "10_frontend/package-lock.json",
)


def _dependency_failure_detail(exit_code: int | None, payload: Any, *, stage: str = "child_output") -> dict[str, Any]:
    child_stage = stage if stage in DEPENDENCY_CHILD_STAGES else "child_output"
    child_code = "UnexpectedError"
    if type(payload) is dict:
        rows = payload.get("stages")
        if type(rows) is list:
            for row in rows:
                if type(row) is not dict or row.get("state") != "failed":
                    continue
                candidate_stage = row.get("name")
                if type(candidate_stage) is str and candidate_stage in DEPENDENCY_CHILD_STAGES:
                    child_stage = candidate_stage
                candidate_code = row.get("error_class")
                if type(candidate_code) is str and candidate_code in DEPENDENCY_CHILD_ERROR_CODES:
                    child_code = candidate_code
                break
        if child_code == "UnexpectedError":
            candidate_code = payload.get("error_class")
            if type(candidate_code) is str and candidate_code in DEPENDENCY_CHILD_ERROR_CODES:
                child_code = candidate_code
                child_stage = "preflight"
    return {
        "exit_code": exit_code if type(exit_code) is int else None,
        "stage": child_stage,
        "error_code": child_code,
    }


def _dependency_failure_install_code(details: dict[str, Any]) -> str:
    return DEPENDENCY_CHILD_FAILURE_INSTALL_CODES.get(
        details["error_code"], "OFFLINE_DEPENDENCY_PREPARATION_FAILED"
    )


def _run_dependency_preparation(command: list[str], *, timeout: int) -> tuple[int, dict[str, Any]]:
    env = _minimal_env(include_caches=True)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        result = subprocess.run(
            command, capture_output=True, timeout=timeout, check=False, shell=False, env=env,
        )
    except subprocess.TimeoutExpired:
        details = _dependency_failure_detail(None, None, stage="process")
        details["error_code"] = "TimeoutExpired"
        raise InstallError("STAGE_TIMEOUT_PRESERVE_AND_INSPECT", details=details) from None
    except OSError:
        details = _dependency_failure_detail(None, None, stage="process")
        details["error_code"] = "MissingTool"
        raise InstallError("STAGE_PROCESS_UNAVAILABLE", details=details) from None
    try:
        payload = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        details = _dependency_failure_detail(result.returncode, None)
        details["error_code"] = "InvalidJson"
        raise InstallError("STAGE_RESULT_INVALID", details=details) from None
    if type(payload) is not dict:
        details = _dependency_failure_detail(result.returncode, None)
        details["error_code"] = "InvalidResponse"
        raise InstallError("STAGE_RESULT_INVALID", details=details)
    return result.returncode, payload


def _dependency_report_is_failure(exit_code: int, payload: dict[str, Any]) -> bool:
    status = payload.get("status")
    return (
        exit_code != 0
        or payload.get("mode") != "install"
        or payload.get("schema_version") != "school-dependency-preparation.v1"
        or payload.get("run_state") != "completed"
        or (status is not None and (type(status) is not str or status != "completed"))
        or payload.get("error_class") is not None
    )


def _dependency_retry_paths(config: dict[str, Any], attempt: int) -> tuple[Path, Path]:
    stem = f"{config['state_path'].name}.dependency-retry-{attempt:03d}"
    return tuple(config["state_path"].with_name(f"{stem}-{kind}.json") for kind in ("start", "result"))


def _read_retry_record(path: Path, fields: set[str], *, attempt: int, config: dict[str, Any]) -> dict[str, Any]:
    _reject_reparse_ancestors(path)
    if _is_reparse(path):
        raise InstallError("REPARSE_PATH_REJECTED")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise InstallError("CHECKPOINT_INVALID") from None
    expected = {
        "schema": DEPENDENCY_RETRY_SCHEMA,
        "source_root": str(config["source"]),
        "dependency_target": str(config["dependency_target"]),
        "workspace": str(config["workspace"]),
        "source_head": config["source_head"],
        "dependency_target_head": config["target_head"],
        "attempt": attempt,
    }
    if type(record) is not dict or set(record) != fields or any(record.get(k) != v for k, v in expected.items()):
        raise InstallError("RESUME_CONFIGURATION_MISMATCH")
    return record


def _write_retry_record(path: Path, record: dict[str, Any]) -> None:
    _reject_reparse_ancestors(path)
    temp_path = path.with_name(path.name + ".tmp")
    if path.exists() or _is_reparse(path) or temp_path.exists() or _is_reparse(temp_path):
        raise InstallError("CHECKPOINT_TEMP_CONFLICT")
    raw = (json.dumps(record, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(temp_path, flags, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    except OSError:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise InstallError("CHECKPOINT_PERSIST_FAILED") from None


def _validate_dependency_retry(config: dict[str, Any], state: dict[str, Any]) -> None:
    prior_failure_code = state["stages"]["dependencies"].get("code")
    if (
        state["stages"]["dependencies"]["status"] != "FAILED"
        or any(state["stages"][name]["status"] != "PENDING" for name in STAGE_NAMES if name != "dependencies")
        or state.get("workspace_id") is not None
        or _path_entry_exists(config["workspace"])
        or state.get("dependency_module_manifest_sha256") is not None
        or type(prior_failure_code) is not str
        or prior_failure_code not in SAFE_STAGE_CODES
    ):
        raise InstallError("INCOMPLETE_STAGE_PRESERVED_FOR_INSPECTION")
    source_head = _validate_git_root(config["source"], require_clean=False)
    target_head = _validate_git_root(config["dependency_target"], require_clean=True)
    if source_head != config["source_head"] or target_head != config["target_head"]:
        raise InstallError("SOURCE_TARGET_HEAD_MISMATCH")
    for relative in DEPENDENCY_PIN_FILES:
        source_file = config["source"] / relative
        target_file = config["dependency_target"] / relative
        if not source_file.is_file() or not target_file.is_file():
            raise InstallError("DEPENDENCY_LOCK_FILE_MISSING")
        if _sha256(source_file) != _sha256(target_file):
            code = "DEPENDENCY_MANIFEST_PIN_CHANGED" if relative == "MODULES.md" else "DEPENDENCY_LOCK_PIN_CHANGED"
            raise InstallError(code)
    status = _git_output(
        ["-C", str(config["dependency_target"]), "status", "--porcelain=v1", "--untracked-files=normal", "--ignored=traditional"],
        cwd=REPO,
    )
    if any(entry[:2] in {"??", "!!"} for entry in status.splitlines() if entry):
        raise InstallError("DEPENDENCY_TARGET_NOT_CLEAN")


def _start_dependency_retry(config: dict[str, Any], state: dict[str, Any]) -> tuple[int, Path]:
    pattern = f"{config['state_path'].name}.dependency-retry-*-start.json"
    starts = sorted(config["state_path"].parent.glob(pattern))
    results = {path.name.replace("-result.json", "-start.json") for path in config["state_path"].parent.glob(
        f"{config['state_path'].name}.dependency-retry-*-result.json"
    )}
    indexes: list[int] = []
    for path in starts:
        match = re.fullmatch(re.escape(config["state_path"].name) + r"\.dependency-retry-([0-9]{3})-start\.json", path.name)
        if match is None:
            raise InstallError("CHECKPOINT_INVALID")
        indexes.append(int(match.group(1)))
    if indexes != list(range(1, len(indexes) + 1)) or results != {path.name for path in starts}:
        raise InstallError("INCOMPLETE_STAGE_PRESERVED_FOR_INSPECTION")
    for index, start_path in enumerate(starts, start=1):
        start = _read_retry_record(start_path, DEPENDENCY_RETRY_START_FIELDS, attempt=index, config=config)
        if (
            type(start.get("prior_failure_code")) is not str
            or start["prior_failure_code"] not in SAFE_STAGE_CODES
            or not isinstance(start.get("started_at"), str)
        ):
            raise InstallError("CHECKPOINT_INVALID")
        _start, result_path = _dependency_retry_paths(config, index)
        result = _read_retry_record(result_path, DEPENDENCY_RETRY_RESULT_FIELDS, attempt=index, config=config)
        if (
            type(result.get("status")) is not str
            or result["status"] not in {"COMPLETED", "FAILED"}
            or not isinstance(result.get("finished_at"), str)
            or (result.get("exit_code") is not None and type(result["exit_code"]) is not int)
            or (result.get("stage") is not None and (type(result["stage"]) is not str or result["stage"] not in DEPENDENCY_CHILD_STAGES))
            or (result.get("error_code") is not None and (type(result["error_code"]) is not str or result["error_code"] not in DEPENDENCY_CHILD_ERROR_CODES))
            or (result.get("install_code") is not None and (type(result["install_code"]) is not str or result["install_code"] not in SAFE_STAGE_CODES))
        ):
            raise InstallError("CHECKPOINT_INVALID")
    attempt = len(indexes) + 1
    start_path, result_path = _dependency_retry_paths(config, attempt)
    _reject_reparse_ancestors(result_path)
    if result_path.exists() or _is_reparse(result_path):
        raise InstallError("CHECKPOINT_TEMP_CONFLICT")
    start = {
        "schema": DEPENDENCY_RETRY_SCHEMA,
        "source_root": str(config["source"]),
        "dependency_target": str(config["dependency_target"]),
        "workspace": str(config["workspace"]),
        "source_head": config["source_head"],
        "dependency_target_head": config["target_head"],
        "attempt": attempt,
        "prior_failure_code": state["stages"]["dependencies"]["code"],
        "started_at": _utc_now(),
    }
    _write_retry_record(start_path, start)
    return attempt, start_path


def _finish_dependency_retry(
    config: dict[str, Any], attempt: int, *, status: str, error: InstallError | None = None,
) -> None:
    start_path, result_path = _dependency_retry_paths(config, attempt)
    start = _read_retry_record(start_path, DEPENDENCY_RETRY_START_FIELDS, attempt=attempt, config=config)
    details = error.details if error is not None and type(error.details) is dict else {}
    child_stage = details.get("stage")
    child_code = details.get("error_code")
    record = {key: start[key] for key in (
        "schema", "source_root", "dependency_target", "workspace", "source_head", "dependency_target_head", "attempt",
    )}
    record.update(
        status=status,
        finished_at=_utc_now(),
        exit_code=details.get("exit_code") if type(details.get("exit_code")) is int else None,
        stage=child_stage if type(child_stage) is str and child_stage in DEPENDENCY_CHILD_STAGES else None,
        error_code=child_code if type(child_code) is str and child_code in DEPENDENCY_CHILD_ERROR_CODES else None,
        install_code=error.code if error is not None and error.code in SAFE_STAGE_CODES else None,
    )
    _write_retry_record(result_path, record)


def _dependency_stages_match(
    stages: Any,
    expected_names: tuple[str, ...],
    *,
    expected_state: str,
    require_success_exit: bool,
) -> bool:
    if not isinstance(stages, list) or len(stages) != len(expected_names):
        return False
    for row, expected_name in zip(stages, expected_names, strict=True):
        if type(row) is not dict or row.get("name") != expected_name or row.get("state") != expected_state:
            return False
        if require_success_exit and (type(row.get("exit_code")) is not int or row["exit_code"] != 0):
            return False
    return True


def _dependency_plan_stages_valid(stages: Any) -> bool:
    if not _dependency_stages_match(
        stages, DEPENDENCY_PLAN_STAGE_NAMES, expected_state="planned", require_success_exit=False,
    ):
        return False
    for module, row in zip(DEPENDENCY_PLAN_STAGE_NAMES, stages, strict=True):
        expected_target = "node_modules" if module == "10_frontend" else ".venv"
        if row.get("target") != expected_target:
            return False
        if module == "10_frontend":
            if "python" in row:
                return False
        elif not isinstance(row.get("python"), str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", row["python"]):
            return False
    return True


def _commands(config: dict[str, Any]) -> dict[str, list[str]]:
    target = config["dependency_target"]
    workspace = config["workspace"]
    python = {name: str(target / name / ".venv" / "Scripts" / "python.exe") for name in PYTHON_MODULES}
    def scripts(name: str) -> str:
        return str(target / "13_deployment" / name)
    common = ["--workspace", str(workspace)]
    db_port = str(config["ports"]["database"])
    lifecycle_common = [
        *common,
        "--backend-port", str(config["ports"]["backend"]),
        "--frontend-port", str(config["ports"]["frontend"]),
        "--frontend-mode", config["frontend_mode"],
        "--llm-profile", config["llm_profile"],
        "--enable-standard-cat",
        "--standard-cat-port", str(config["ports"]["standard_cat"]),
    ]
    research_args = _research_cli_arguments(config)
    return {
        "dependencies": [
            sys.executable, "-B", str(config["source"] / "13_deployment" / "school_prepare_dependencies.py"),
            "install", "--source-root", str(config["source"]), "--target-root", str(target),
            *[arg for module in PYTHON_MODULES for arg in ("--python", f"{module}={config['python_specs'][module]}")],
        ],
        "workspace": [python["11_database"], scripts("create_school_workspace.py"),
                      *common, "--mysql-bin", str(config["mysql_bin"]), "--port", db_port],
        "schema_upgrade": [python["11_database"], scripts("migrate_school_workspace.py"), "upgrade",
                           *common, "--expected-port", db_port, "--workspace-id", "{workspace_id}"],
        "runtime_identity": [python["11_database"], scripts("prepare_school_runtime.py"), *common],
        "backend_preflight": [python["09_backend"], scripts("school_backend.py"), *common,
                              "--port", str(config["ports"]["backend"]),
                              "--frontend-port", str(config["ports"]["frontend"]),
                              "--llm-profile", config["llm_profile"], *research_args,
                              "--preflight-only"],
        "synthetic_seed": [python["09_backend"], scripts("seed_school_workspace.py"), *common],
        "application_start": [python["09_backend"], scripts("school_app_lifecycle.py"), "start",
                              *lifecycle_common, *research_args],
        "application_status": [python["09_backend"], scripts("school_app_lifecycle.py"), "status", *common],
        "four_role_browser": [python["09_backend"], scripts("school_browser_qa.py"), *common,
                               "--backend-port", str(config["ports"]["backend"]),
                               "--frontend-port", str(config["ports"]["frontend"])],
    }


def _research_cli_arguments(config: dict[str, Any]) -> list[str]:
    profile = config.get("research_profile")
    if not isinstance(profile, dict):
        return []
    arguments = profile.get("arguments")
    if not isinstance(arguments, dict):
        raise InstallError("RESEARCH_PROFILE_INVALID")
    result: list[str] = []
    for path_name, sha_name, path_flag, sha_flag, _limit in RESEARCH_FILE_PAIRS:
        path_value = arguments.get(path_name)
        sha_value = arguments.get(sha_name)
        if path_value is None:
            continue
        if type(path_value) is not str or type(sha_value) is not str:
            raise InstallError("RESEARCH_PROFILE_INVALID")
        workspace_file = profile.get("workspace_files", {}).get(path_name)
        if workspace_file is not None:
            path_value = str(
                config["workspace"] / ".school-research-profile" / workspace_file["target_name"]
            )
        result.extend((path_flag, path_value, sha_flag, sha_value))
    for name, flag, _kind in RESEARCH_PATH_ARGUMENTS:
        value = arguments.get(name)
        if value is not None:
            if type(value) is not str:
                raise InstallError("RESEARCH_PROFILE_INVALID")
            result.extend((flag, value))
    for name, flag in RESEARCH_VALUE_ARGUMENTS:
        value = arguments.get(name)
        if value is not None:
            if type(value) is not str:
                raise InstallError("RESEARCH_PROFILE_INVALID")
            result.extend((flag, value))
    for name, flag in RESEARCH_BOOLEAN_ARGUMENTS:
        value = arguments.get(name)
        if type(value) is not bool:
            raise InstallError("RESEARCH_PROFILE_INVALID")
        if value:
            result.append(flag)
    return result


def _workspace_research_profile_dir(config: dict[str, Any]) -> Path:
    return config["workspace"] / ".school-research-profile"


def _path_entry_exists(path: Path) -> bool:
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        raise InstallError("RESEARCH_PROFILE_TARGET_CONFLICT") from None


def _write_workspace_research_file(
    destination_dir: Path, path_name: str, record: dict[str, Any],
) -> None:
    _, raw = _read_pinned_research_file(
        Path(record["source_path"]), record["sha256"], max_bytes=record["max_bytes"]
    )
    target = destination_dir / record["target_name"]
    _reject_reparse_ancestors(destination_dir)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(target, flags, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        raise InstallError("RESEARCH_PROFILE_TARGET_CONFLICT") from None
    except OSError:
        raise InstallError("RESEARCH_PROFILE_TARGET_WRITE_FAILED") from None
    _read_pinned_research_file(target, record["sha256"], max_bytes=record["max_bytes"])


def _materialize_workspace_research_files(config: dict[str, Any]) -> None:
    profile = config.get("research_profile", {})
    workspace_files = profile.get("workspace_files", {}) if isinstance(profile, dict) else {}
    destination_dir = _workspace_research_profile_dir(config)
    if not workspace_files:
        if _path_entry_exists(destination_dir):
            raise InstallError("RESEARCH_PROFILE_TARGET_CONFLICT")
        return
    _reject_reparse_ancestors(config["workspace"])
    try:
        destination_dir.mkdir()
    except FileExistsError:
        raise InstallError("RESEARCH_PROFILE_TARGET_CONFLICT") from None
    except OSError:
        raise InstallError("RESEARCH_PROFILE_TARGET_WRITE_FAILED") from None
    if destination_dir.is_symlink() or _is_reparse(destination_dir):
        raise InstallError("RESEARCH_PROFILE_TARGET_CONFLICT")
    for path_name, record in workspace_files.items():
        if path_name not in {name for name, _sha, _target in WORKSPACE_RESEARCH_FILES}:
            raise InstallError("RESEARCH_PROFILE_INVALID")
        _write_workspace_research_file(destination_dir, path_name, record)


def _resume_workspace_research_file_import(config: dict[str, Any]) -> None:
    """Complete only missing exact pinned imports; never overwrite partial files."""
    profile = config.get("research_profile", {})
    workspace_files = profile.get("workspace_files", {}) if isinstance(profile, dict) else {}
    if not workspace_files:
        raise InstallError("RESEARCH_PROFILE_TARGET_CONFLICT")
    expected_names = {record["target_name"] for record in workspace_files.values()}
    destination_dir = _workspace_research_profile_dir(config)
    if _path_entry_exists(destination_dir):
        if destination_dir.is_symlink() or _is_reparse(destination_dir) or not destination_dir.is_dir():
            raise InstallError("RESEARCH_PROFILE_TARGET_CONFLICT")
        try:
            names = {entry.name for entry in destination_dir.iterdir()}
        except OSError:
            raise InstallError("RESEARCH_PROFILE_TARGET_CONFLICT") from None
        if not names.issubset(expected_names):
            raise InstallError("RESEARCH_PROFILE_TARGET_CONFLICT")
        for path_name, record in workspace_files.items():
            target = destination_dir / record["target_name"]
            if _path_entry_exists(target):
                _read_pinned_research_file(
                    target, record["sha256"], max_bytes=record["max_bytes"]
                )
    else:
        _reject_reparse_ancestors(config["workspace"])
        try:
            destination_dir.mkdir()
        except OSError:
            raise InstallError("RESEARCH_PROFILE_TARGET_WRITE_FAILED") from None
    if destination_dir.is_symlink() or _is_reparse(destination_dir):
        raise InstallError("RESEARCH_PROFILE_TARGET_CONFLICT")
    for path_name, record in workspace_files.items():
        if path_name not in {name for name, _sha, _target in WORKSPACE_RESEARCH_FILES}:
            raise InstallError("RESEARCH_PROFILE_INVALID")
        if not _path_entry_exists(destination_dir / record["target_name"]):
            _write_workspace_research_file(destination_dir, path_name, record)
    _verify_workspace_research_files(config)


def _research_profile_import_recovery_eligible(
    config: dict[str, Any], state: dict[str, Any], *, workspace_exists: bool,
) -> bool:
    profile = config.get("research_profile", {})
    workspace_files = profile.get("workspace_files", {}) if isinstance(profile, dict) else {}
    workspace_stage = state["stages"]["workspace"]
    stage_status = workspace_stage["status"]
    stage_code = workspace_stage.get("code")
    import_state = state.get("workspace_profile_import_state")
    valid_boundary = (
        stage_status == "RUNNING"
        and stage_code is None
        and import_state in {"PENDING", "RUNNING", "COMPLETED"}
    ) or (
        stage_status == "FAILED"
        and stage_code in RECOVERABLE_PROFILE_IMPORT_FAILURES
        and import_state in {"PENDING", "RUNNING"}
    )
    return bool(
        workspace_files
        and workspace_exists
        and valid_boundary
        and state.get("workspace_id") is not None
        and state["stages"]["dependencies"]["status"] == "COMPLETED"
        and all(
            state["stages"][name]["status"] == "PENDING"
            for name in STAGE_NAMES[STAGE_NAMES.index("workspace") + 1:]
        )
    )


def _verify_workspace_research_files(config: dict[str, Any]) -> None:
    profile = config.get("research_profile", {})
    workspace_files = profile.get("workspace_files", {}) if isinstance(profile, dict) else {}
    destination_dir = _workspace_research_profile_dir(config)
    if not workspace_files:
        if _path_entry_exists(destination_dir):
            raise InstallError("RESEARCH_PROFILE_TARGET_CONFLICT")
        return
    if not destination_dir.is_dir() or destination_dir.is_symlink() or _is_reparse(destination_dir):
        raise InstallError("RESEARCH_PROFILE_TARGET_CONFLICT")
    try:
        names = {item.name for item in destination_dir.iterdir()}
    except OSError:
        raise InstallError("RESEARCH_PROFILE_TARGET_CONFLICT") from None
    expected_names = {record["target_name"] for record in workspace_files.values()}
    if names != expected_names:
        raise InstallError("RESEARCH_PROFILE_TARGET_CONFLICT")
    for record in workspace_files.values():
        target = destination_dir / record["target_name"]
        _read_pinned_research_file(
            target, record["sha256"], max_bytes=record["max_bytes"]
        )


def _verify_app_status(payload: dict[str, Any], config: dict[str, Any], workspace_id: str) -> bool:
    if (
        payload.get("status") != "RUNNING"
        or payload.get("workspace_id") != workspace_id
        or payload.get("manifest_is_current_revision") is not True
        or payload.get("manifest_revision") != CURRENT_SCHOOL_REVISION
        or payload.get("database") != "VERIFIED"
    ):
        return False
    services = payload.get("services")
    if not isinstance(services, dict):
        return False
    for name, port in (("backend", config["ports"]["backend"]), ("frontend", config["ports"]["frontend"]),
                       ("standard_cat", config["ports"]["standard_cat"])):
        service = services.get(name)
        if (
            not isinstance(service, dict)
            or service.get("port") != port
            or service.get("owned_process") is not True
            or service.get("listener") != "OWNED"
            or service.get("ready") is not True
        ):
            return False
    standard = payload.get("standard_cat")
    return isinstance(standard, dict) and standard.get("readiness") == "READY" and standard.get("port") == config["ports"]["standard_cat"]


def _verify_completed_dependencies(config: dict[str, Any], state: dict[str, Any]) -> None:
    receipt = _dependency_receipt(config)
    module_hash = receipt.get("target_module_manifest_sha256")
    if not isinstance(module_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", module_hash):
        raise InstallError("DEPENDENCY_MANIFEST_PIN_INVALID")
    if state.get("dependency_module_manifest_sha256") != module_hash:
        raise InstallError("DEPENDENCY_MANIFEST_PIN_CHANGED")
    target = config["dependency_target"]
    locked = receipt.get("target_lock_sha256")
    if not isinstance(locked, dict) or not locked:
        raise InstallError("DEPENDENCY_LOCK_RECEIPT_INVALID")
    for relative, expected in locked.items():
        if not isinstance(relative, str) or Path(relative).is_absolute() or not isinstance(expected, str):
            raise InstallError("DEPENDENCY_LOCK_RECEIPT_INVALID")
        try:
            path = (target / relative).resolve(strict=True)
        except (OSError, RuntimeError):
            raise InstallError("DEPENDENCY_LOCK_FILE_MISSING") from None
        if not _inside(path, target) or _sha256(path) != expected:
            raise InstallError("DEPENDENCY_LOCK_PIN_CHANGED")
    for module in PYTHON_MODULES:
        if not (target / module / ".venv" / "Scripts" / "python.exe").is_file():
            raise InstallError("PYTHON_ENVIRONMENT_MISSING")
    if not all((target / "10_frontend" / "node_modules" / package / "package.json").is_file()
               for package in ("vue", "vite", "typescript")):
        raise InstallError("FRONTEND_ENVIRONMENT_MISSING")


def _verify_completed_workspace(config: dict[str, Any], state: dict[str, Any], commands: dict[str, list[str]]) -> None:
    marker = _workspace_marker(config["workspace"])
    if marker.get("workspace_id") != state.get("workspace_id") or marker.get("port") != config["ports"]["database"]:
        raise InstallError("WORKSPACE_IDENTITY_CHANGED")
    if not (config["workspace"] / "database.private.dpapi").is_file():
        raise InstallError("WORKSPACE_DATABASE_SETTINGS_UNAVAILABLE")
    _verify_workspace_research_files(config)


def _verify_completed_schema(config: dict[str, Any], state: dict[str, Any], commands: dict[str, list[str]]) -> None:
    _verify_completed_workspace(config, state, commands)
    # `migrate ... plan` is intentionally NOT_INSPECTED. The next official
    # runtime preparation or Backend preflight is the current-schema verifier.
    if state["stages"]["runtime_identity"]["status"] == "COMPLETED":
        _verify_runtime(config, commands)


def _verify_runtime(config: dict[str, Any], commands: dict[str, list[str]]) -> None:
    code, result = _run_json(commands["backend_preflight"], timeout=120)
    marker = _workspace_marker(config["workspace"])
    if (
        code != 0
        or result.get("preflight") != "PASS"
        or result.get("module_clients") != "HTTP"
        or result.get("workspace_id") != marker["workspace_id"]
        or result.get("port") != config["ports"]["database"]
        or result.get("schema_revision") != CURRENT_SCHOOL_REVISION
    ):
        raise InstallError("RUNTIME_PREFLIGHT_FAILED")


def _verify_lifecycle(config: dict[str, Any], state: dict[str, Any], commands: dict[str, list[str]]) -> None:
    code, status = _run_json(commands["application_status"], timeout=90)
    if code != 0 or not _verify_app_status(status, config, str(state.get("workspace_id"))):
        raise InstallError("APPLICATION_OWNER_OR_READINESS_UNVERIFIED")


def _verify_browser(config: dict[str, Any], commands: dict[str, list[str]]) -> dict[str, Any]:
    code, result = _run_json(commands["four_role_browser"], timeout=360)
    if code != 0 or result.get("status") != "PASS" or result.get("pass_count") != 4 or result.get("fail_count") != 0:
        raise InstallError("FOUR_ROLE_BROWSER_CHECK_FAILED")
    rows = result.get("results")
    expected_roles = {
        "alpha.student", "alpha.teacher", "alpha.psychological_specialist", "alpha.admin",
    }
    if (
        not isinstance(rows, list)
        or len(rows) != 4
        or any(not isinstance(row, dict) or row.get("status") != "PASS" for row in rows)
        or {row.get("slot") for row in rows if isinstance(row, dict)} != expected_roles
    ):
        raise InstallError("FOUR_ROLE_BROWSER_RESULT_INVALID")
    return {"status": "PASS", "role_count": 4}


def _mark_stage(config: dict[str, Any], state: dict[str, Any], name: str, status: str, code: str | None = None) -> None:
    state["stages"][name] = {"status": status, "code": code}
    _write_state(config["state_path"], config["state_temp_path"], state)


def _begin_stage(config: dict[str, Any], state: dict[str, Any], name: str) -> None:
    _mark_stage(config, state, name, "RUNNING")


def _schema_migration_failure_code(exit_code: int, payload: dict[str, Any]) -> str:
    """Project only the migrator's exact, known partial-failure results."""
    if (
        type(exit_code) is not int
        or exit_code != 2
        or type(payload) is not dict
        or set(payload) != {"status", "code"}
    ):
        return "SCHEMA_MIGRATION_FAILED"
    status = payload.get("status")
    code = payload.get("code")
    if type(status) is not str or type(code) is not str:
        return "SCHEMA_MIGRATION_FAILED"
    known_failures = {
        ("PARTIAL_FAILURE", "MIGRATION_FAILED"): "SCHEMA_MIGRATION_DDL_FAILED",
        ("PARTIAL_FAILURE", "POST_MIGRATION_CHECK_FAILED"):
            "SCHEMA_MIGRATION_POSTCHECK_FAILED",
    }
    return known_failures.get((status, code), "SCHEMA_MIGRATION_FAILED")


def _synthetic_seed_result_matches(result: Any) -> bool:
    if type(result) is not dict or set(result) != set(SYNTHETIC_SEED_EXPECTED_RESULT):
        return False
    for key in ("recipe", "credentials"):
        if type(result.get(key)) is not str or result[key] != SYNTHETIC_SEED_EXPECTED_RESULT[key]:
            return False
    for key in (
        "schools",
        "subjects",
        "role_accounts",
        "specialist_subject_grants",
        "admin_subject_grants",
    ):
        if type(result.get(key)) is not int or result[key] != SYNTHETIC_SEED_EXPECTED_RESULT[key]:
            return False
    return True


def _run_stage(
    config: dict[str, Any],
    state: dict[str, Any],
    commands: dict[str, list[str]],
    name: str,
    *,
    allow_failed_dependency_retry: bool = False,
) -> None:
    current = state["stages"][name]["status"]
    if current == "COMPLETED":
        return
    if current == "PENDING_VERIFICATION":
        return
    retry_failed_dependency = (
        allow_failed_dependency_retry is True and name == "dependencies" and current == "FAILED"
    )
    if allow_failed_dependency_retry and not retry_failed_dependency:
        raise InstallError("INCOMPLETE_STAGE_PRESERVED_FOR_INSPECTION")
    if current != "PENDING" and not retry_failed_dependency:
        raise InstallError("INCOMPLETE_STAGE_PRESERVED_FOR_INSPECTION")
    try:
        # A failed dependency stage moves directly to RUNNING only on the explicitly
        # validated retry path. Never persist an intermediate PENDING state that a
        # later ordinary resume could mistake for permission to rerun the child.
        _begin_stage(config, state, name)
        if name == "dependencies":
            code, result = _run_dependency_preparation(commands["dependencies"], timeout=1800)
            if _dependency_report_is_failure(code, result):
                details = _dependency_failure_detail(code, result)
                raise InstallError(_dependency_failure_install_code(details), details=details)
            receipt = _dependency_receipt(config)
            if receipt.get("run_state") != "completed":
                raise InstallError("OFFLINE_DEPENDENCY_PREPARATION_FAILED")
            state["dependency_module_manifest_sha256"] = receipt["target_module_manifest_sha256"]
        elif name == "workspace":
            code, result = _run_json(commands["workspace"], timeout=600)
            if code != 0 or result.get("state") != "READY_FOR_MIGRATION" or result.get("synthetic_only") is not True:
                raise InstallError("WORKSPACE_CREATE_FAILED")
            workspace_id = result.get("workspace_id")
            if not isinstance(workspace_id, str) or not WORKSPACE_ID_RE.fullmatch(workspace_id):
                raise InstallError("WORKSPACE_ID_INVALID")
            state["workspace_id"] = workspace_id
            workspace_files = config.get("research_profile", {}).get("workspace_files", {})
            state["workspace_profile_import_state"] = "PENDING" if workspace_files else "NOT_REQUIRED"
            _write_state(config["state_path"], config["state_temp_path"], state)
            if workspace_files:
                state["workspace_profile_import_state"] = "RUNNING"
                _write_state(config["state_path"], config["state_temp_path"], state)
            _materialize_workspace_research_files(config)
            if workspace_files:
                state["workspace_profile_import_state"] = "COMPLETED"
                _write_state(config["state_path"], config["state_temp_path"], state)
        elif name == "schema":
            workspace_id = str(state["workspace_id"])
            upgrade_command = [item.format(workspace_id=workspace_id) for item in commands["schema_upgrade"]]
            code, result = _run_json(upgrade_command, timeout=900)
            if code != 0 or result.get("status") != "MIGRATED" or result.get("revision") != CURRENT_SCHOOL_REVISION:
                raise InstallError(_schema_migration_failure_code(code, result))
        elif name == "runtime_identity":
            code, result = _run_json(commands["runtime_identity"], timeout=180)
            if code != 0 or result.get("runtime_identity") != "CREATED" or result.get("port") != config["ports"]["database"]:
                raise InstallError("RUNTIME_IDENTITY_CREATION_FAILED")
            _verify_runtime(config, commands)
        elif name == "synthetic_seed":
            code, result = _run_json(commands["synthetic_seed"], timeout=180)
            if code != 0 or not _synthetic_seed_result_matches(result):
                raise InstallError("SYNTHETIC_SEED_FAILED")
            state["stages"][name] = {"status": "PENDING_VERIFICATION", "code": None}
            _write_state(config["state_path"], config["state_temp_path"], state)
            return
        elif name == "application":
            code, started = _run_json(commands["application_start"], timeout=900)
            if code != 0 or started.get("status") != "RUNNING":
                raise InstallError("APPLICATION_START_FAILED")
            status_code, status = _run_json(commands["application_status"], timeout=120)
            if status_code != 0 or not _verify_app_status(status, config, str(state.get("workspace_id"))):
                raise InstallError("APPLICATION_OWNER_OR_READINESS_UNVERIFIED")
            state["whole_ready"] = False
        elif name == "four_role_browser":
            _verify_browser(config, commands)
            state["stages"]["synthetic_seed"] = {"status": "COMPLETED", "code": "VERIFIED_BY_ROLE_LOGIN"}
        _mark_stage(config, state, name, "COMPLETED")
    except InstallError as exc:
        _mark_stage(config, state, name, "FAILED", exc.code)
        raise


def _verify_completed(config: dict[str, Any], state: dict[str, Any], commands: dict[str, list[str]]) -> None:
    statuses = state["stages"]
    if statuses["dependencies"]["status"] == "COMPLETED":
        _verify_completed_dependencies(config, state)
    if statuses["workspace"]["status"] == "COMPLETED":
        _verify_completed_workspace(config, state, commands)
    if statuses["schema"]["status"] == "COMPLETED":
        _verify_completed_schema(config, state, commands)
    if statuses["runtime_identity"]["status"] == "COMPLETED":
        _verify_runtime(config, commands)
    if statuses["application"]["status"] == "COMPLETED":
        _verify_lifecycle(config, state, commands)
    if statuses["four_role_browser"]["status"] == "COMPLETED":
        _verify_browser(config, commands)
    if statuses["synthetic_seed"]["status"] not in {"PENDING", "PENDING_VERIFICATION", "COMPLETED"}:
        raise InstallError("SYNTHETIC_SEED_STAGE_INVALID")


def _summary(state: dict[str, Any]) -> dict[str, Any]:
    complete = all(state["stages"][name]["status"] == "COMPLETED" for name in STAGE_NAMES)
    return {
        "schema": "psynova.school-install-result.v1",
        "status": "APP_AND_ROLE_BROWSER_VERIFIED" if complete else "INSTALL_IN_PROGRESS",
        "source_head": state["source_head"],
        "workspace_id": state.get("workspace_id"),
        "schema_revision": state["schema_revision"],
        "stages": {name: state["stages"][name]["status"] for name in STAGE_NAMES},
        "whole_ready": False,
        "asset_distribution": "NOT_INCLUDED",
        "external_ai_assets": "HOST_LOCAL_PREREQUISITE_NOT_INSTALLED_OR_REDISTRIBUTED",
    }


def plan(args: argparse.Namespace) -> dict[str, Any]:
    config = _validate_configuration(args, mode="install")
    _check_ports_available(tuple(config["ports"].values()))
    command = [
        sys.executable,
        "-B",
        str(config["source"] / "13_deployment" / "school_prepare_dependencies.py"),
        "plan", "--source-root", str(config["source"]), "--target-root", str(config["dependency_target"]),
        *[arg for module in PYTHON_MODULES for arg in ("--python", f"{module}={config['python_specs'][module]}")],
    ]
    code, dependency_plan = _run_json(command, timeout=120, include_caches=True)
    if code != 0 or dependency_plan.get("mode") != "plan":
        raise InstallError("OFFLINE_DEPENDENCY_PLAN_FAILED")
    plan_stages = dependency_plan.get("stages")
    if (
        dependency_plan.get("schema_version") != "school-dependency-preparation.v1"
        or dependency_plan.get("source_head") != config["source_head"]
        or not isinstance(dependency_plan.get("module_manifest_sha256"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", dependency_plan["module_manifest_sha256"])
        or not isinstance(dependency_plan.get("lock_sha256"), dict)
        or not _dependency_plan_stages_valid(plan_stages)
    ):
        raise InstallError("OFFLINE_DEPENDENCY_PLAN_INVALID")
    return {
        "schema": "psynova.school-install-plan.v1",
        "status": "PLAN_READY",
        "source_head": config["source_head"],
        "dependency_target_head": config["target_head"],
        "workspace_path": str(config["workspace"]),
        "schema_revision": CURRENT_SCHOOL_REVISION,
        "ports": config["ports"],
        "dependency_mode": "CACHED_OFFLINE_ONLY",
        "external_assets": "MUST_ALREADY_EXIST_LOCALLY; NOT_COPIED_OR_DOWNLOADED",
        "stages": list(STAGE_NAMES),
        "execution_performed": False,
    }


def install(args: argparse.Namespace) -> dict[str, Any]:
    config = _validate_configuration(args, mode="install")
    _check_ports_available(tuple(config["ports"].values()))
    state = _new_state(config)
    _write_state(config["state_path"], config["state_temp_path"], state, initial=True)
    commands = _commands(config)
    for name in STAGE_NAMES:
        _run_stage(config, state, commands, name)
    return _summary(state)


def resume(args: argparse.Namespace) -> dict[str, Any]:
    config = _validate_configuration(args, mode="resume")
    state = _read_state(config["state_path"])
    _match_state(state, config)
    retry_failed_dependencies = getattr(args, "retry_failed_dependencies", False) is True
    if retry_failed_dependencies:
        _validate_dependency_retry(config, state)
    workspace_exists = config["workspace"].exists()
    recover_profile_import = _research_profile_import_recovery_eligible(
        config, state, workspace_exists=workspace_exists
    )
    _validate_resume_workspace_binding(
        state,
        workspace_exists=workspace_exists,
        allow_profile_import_recovery=recover_profile_import,
    )
    _verify_completed(config, state, _commands(config))
    if config["workspace"].exists():
        marker = _workspace_marker(config["workspace"])
        if state.get("workspace_id") != marker.get("workspace_id"):
            raise InstallError("WORKSPACE_IDENTITY_CHANGED")
    commands = _commands(config)
    if retry_failed_dependencies:
        retry_attempt, _start_path = _start_dependency_retry(config, state)
        try:
            _run_stage(
                config,
                state,
                commands,
                "dependencies",
                allow_failed_dependency_retry=True,
            )
        except InstallError as exc:
            _finish_dependency_retry(config, retry_attempt, status="FAILED", error=exc)
            raise
        _finish_dependency_retry(config, retry_attempt, status="COMPLETED")
    if recover_profile_import:
        _verify_profile_import_workspace_identity(config, state)
        _resume_workspace_research_file_import(config)
        state["workspace_profile_import_state"] = "COMPLETED"
        _write_state(config["state_path"], config["state_temp_path"], state)
        _mark_stage(config, state, "workspace", "COMPLETED")
    for name in STAGE_NAMES:
        if state["stages"][name]["status"] == "PENDING_VERIFICATION":
            continue
        _run_stage(config, state, commands, name)
    return _summary(state)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "install", "resume"):
        command = commands.add_parser(name)
        if name == "resume":
            command.add_argument(
                "--retry-failed-dependencies",
                action="store_true",
                help="Retry only a failed dependency stage when every later install stage is still pending.",
            )
        command.add_argument("--source-root", type=Path, default=REPO)
        command.add_argument("--dependency-target-root", type=Path, required=True)
        command.add_argument("--workspace", type=Path, required=True)
        command.add_argument("--mysql-bin", type=Path, required=True)
        command.add_argument("--database-port", type=int, required=True)
        command.add_argument("--backend-port", type=int, required=True)
        command.add_argument("--frontend-port", type=int, required=True)
        command.add_argument("--standard-cat-port", type=int, default=8182)
        command.add_argument("--frontend-mode", choices=("preview",), default="preview")
        command.add_argument("--llm-profile", choices=("school-gpu-7b",), default="school-gpu-7b")
        command.add_argument("--python", action="append", required=True, metavar="MODULE=ABSOLUTE_PATH")
        for name, _sha_name, path_flag, sha_flag, _limit in RESEARCH_FILE_PAIRS:
            command.add_argument(path_flag, dest=name, type=Path)
            command.add_argument(sha_flag, dest=_sha_name)
        for name, flag, _kind in RESEARCH_PATH_ARGUMENTS:
            command.add_argument(flag, dest=name, type=Path)
        for name, flag in RESEARCH_VALUE_ARGUMENTS:
            command.add_argument(flag, dest=name)
        for name, flag in RESEARCH_BOOLEAN_ARGUMENTS:
            command.add_argument(flag, dest=name, action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "plan":
            result = plan(args)
        elif args.command == "install":
            result = install(args)
        else:
            result = resume(args)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0 if result.get("status") in {"PLAN_READY", "APP_AND_ROLE_BROWSER_VERIFIED"} else 1
    except InstallError as exc:
        payload = {"schema": "psynova.school-install-result.v1", "status": "BLOCKED", "code": exc.code}
        if exc.details is not None:
            payload["dependency_failure"] = exc.details
        print(json.dumps(payload, separators=(",", ":")))
        return 2
    except Exception as exc:  # noqa: BLE001 - subprocess/DPAPI details stay closed.
        print(json.dumps({
            "schema": "psynova.school-install-result.v1",
            "status": "BLOCKED",
            "code": f"UNEXPECTED_{type(exc).__name__}",
        }, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
