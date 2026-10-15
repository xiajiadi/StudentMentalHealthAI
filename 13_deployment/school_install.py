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
STAGE_NAMES = (
    "dependencies",
    "workspace",
    "schema",
    "runtime_identity",
    "synthetic_seed",
    "application",
    "four_role_browser",
)
CHECKPOINT_FIELDS = {
    "schema", "created_at", "updated_at", "source_head", "dependency_target_head",
    "source_root", "dependency_target", "mysql_bin", "python_specs", "workspace",
    "workspace_id", "schema_revision", "ports", "frontend_mode", "llm_profile",
    "dependency_module_manifest_sha256", "stages", "whole_ready",
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
    "RUNTIME_PREFLIGHT_FAILED", "SCHEMA_MIGRATION_FAILED", "SOURCE_OR_TARGET_MISSING",
    "SOURCE_TARGET_HEAD_MISMATCH", "SOURCE_TARGET_OVERLAP", "SOURCE_TRACKED_FILES_DIRTY",
    "STAGE_PROCESS_UNAVAILABLE", "STAGE_RESULT_INVALID", "STAGE_TIMEOUT_PRESERVE_AND_INSPECT",
    "SYNTHETIC_SEED_FAILED", "SYNTHETIC_SEED_STAGE_INVALID", "VENDOR_MYSQL_BINARY_UNAVAILABLE",
    "WORKSPACE_CREATE_FAILED", "WORKSPACE_DATABASE_SETTINGS_UNAVAILABLE", "WORKSPACE_ID_INVALID",
    "WORKSPACE_IDENTITY_CHANGED", "WORKSPACE_MARKER_INVALID", "WORKSPACE_MARKER_UNAVAILABLE",
    "WORKSPACE_PARENT_UNAVAILABLE", "WORKSPACE_REPOSITORY_OVERLAP", "WORKSPACE_STAGE_NOT_RESTARTABLE",
}
PYTHON_SPEC_RE = re.compile(r"^([0-9]{2}_[a-z0-9-]+)=(.+)$")
WORKSPACE_ID_RE = re.compile(r"^[a-f0-9]{32}$")

sys.path.insert(0, str(DEPLOYMENT))
from school_schema import CURRENT_SCHOOL_REVISION


class InstallError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
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
    }
    if any(state.get(key) != value for key, value in expected.items()):
        raise InstallError("RESUME_CONFIGURATION_MISMATCH")


def _validate_resume_workspace_binding(state: dict[str, Any], *, workspace_exists: bool) -> None:
    stage_status = state["stages"]["workspace"]["status"]
    workspace_id = state.get("workspace_id")
    if stage_status in {"RUNNING", "FAILED"}:
        raise InstallError("INCOMPLETE_STAGE_PRESERVED_FOR_INSPECTION")
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
        or not isinstance(stages, list)
        or len(stages) != 8
        or any(not isinstance(row, dict) or row.get("state") != "succeeded" or row.get("exit_code") != 0 for row in stages)
    ):
        raise InstallError("DEPENDENCY_RECEIPT_NOT_COMPLETE")
    return receipt


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
    return {
        "dependencies": [
            sys.executable, str(config["source"] / "13_deployment" / "school_prepare_dependencies.py"),
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
                              "--llm-profile", config["llm_profile"], "--preflight-only"],
        "synthetic_seed": [python["09_backend"], scripts("seed_school_workspace.py"), *common],
        "application_start": [python["09_backend"], scripts("school_app_lifecycle.py"), "start",
                              *lifecycle_common],
        "application_status": [python["09_backend"], scripts("school_app_lifecycle.py"), "status", *common],
        "four_role_browser": [python["09_backend"], scripts("school_browser_qa.py"), *common,
                               "--backend-port", str(config["ports"]["backend"]),
                               "--frontend-port", str(config["ports"]["frontend"])],
    }


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


def _run_stage(config: dict[str, Any], state: dict[str, Any], commands: dict[str, list[str]], name: str) -> None:
    current = state["stages"][name]["status"]
    if current == "COMPLETED":
        return
    if current == "PENDING_VERIFICATION":
        return
    if current != "PENDING":
        raise InstallError("INCOMPLETE_STAGE_PRESERVED_FOR_INSPECTION")
    _begin_stage(config, state, name)
    try:
        if name == "dependencies":
            code, result = _run_json(commands["dependencies"], timeout=1800, include_caches=True)
            receipt = _dependency_receipt(config)
            if code != 0 or result.get("run_state") != "completed" or receipt.get("run_state") != "completed":
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
        elif name == "schema":
            workspace_id = str(state["workspace_id"])
            upgrade_command = [item.format(workspace_id=workspace_id) for item in commands["schema_upgrade"]]
            code, result = _run_json(upgrade_command, timeout=900)
            if code != 0 or result.get("status") != "MIGRATED" or result.get("revision") != CURRENT_SCHOOL_REVISION:
                raise InstallError("SCHEMA_MIGRATION_FAILED")
        elif name == "runtime_identity":
            code, result = _run_json(commands["runtime_identity"], timeout=180)
            if code != 0 or result.get("runtime_identity") != "CREATED" or result.get("port") != config["ports"]["database"]:
                raise InstallError("RUNTIME_IDENTITY_CREATION_FAILED")
            _verify_runtime(config, commands)
        elif name == "synthetic_seed":
            code, result = _run_json(commands["synthetic_seed"], timeout=180)
            if (
                code != 0 or result.get("recipe") != "school-contexts-v1"
                or result.get("schools") != 1
                or type(result.get("subjects")) is not int
                or result.get("subjects", 0) < 1
                or result.get("role_accounts") != 4
                or result.get("specialist_subject_grants") != 0
                or result.get("admin_subject_grants") != 0
            ):
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
        or not isinstance(plan_stages, list)
        or len(plan_stages) != 8
        or any(not isinstance(stage, dict) or stage.get("state") != "planned" for stage in plan_stages)
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
    _validate_resume_workspace_binding(state, workspace_exists=config["workspace"].exists())
    _verify_completed(config, state, _commands(config))
    if config["workspace"].exists():
        marker = _workspace_marker(config["workspace"])
        if state.get("workspace_id") != marker.get("workspace_id"):
            raise InstallError("WORKSPACE_IDENTITY_CHANGED")
    commands = _commands(config)
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
        print(json.dumps({"schema": "psynova.school-install-result.v1", "status": "BLOCKED", "code": exc.code}, separators=(",", ":")))
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
