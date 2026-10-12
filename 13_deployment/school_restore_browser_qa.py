"""Verify four restored school roles using sealed credentials over stdin only."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from private_settings import read_private
from resume_school_workspace import (
    ResumeOperations,
    _command_arguments,
    _process_matches,
    _reject_reparse_path,
    _utc_timestamp,
)
from school_backend import load_runtime
from school_browser_qa import (
    ACCOUNT_FILE,
    ACCOUNT_SLOTS,
    FRONTEND,
    NODE_SCRIPT,
    REPO,
    create_artifact_run_dir,
    safe_node_environment,
    sanitize_child_output,
    validate_credentials,
)

SOURCE = Path(r"D:\Projects\.StudentMentalHealthAI-school-workspace-20261011")
TARGET = Path(r"D:\Projects\.StudentMentalHealthAI-school-restore-20261012-a")
PROJECTS_ROOT = Path(r"D:\Projects")
SOURCE_DATABASE_PORT = 3308
DEFAULT_DATABASE_PORT = 3309
DEFAULT_BACKEND_PORT = 8089
DEFAULT_FRONTEND_PORT = 4179
MIN_DATABASE_PORT = 3308
MAX_DATABASE_PORT = 3399
MIN_APP_PORT = 1024
MAX_APP_PORT = 65535
_RESTORE_TARGET_NAME = re.compile(
    r"^\.StudentMentalHealthAI-school-restore-\d{8}-[a-z0-9][a-z0-9-]{0,31}$",
    re.IGNORECASE,
)
_RESTORE_PROCESS_SCHEMA = "psynova.restore-owned-processes.v1"


def _path_key(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        return None
    return os.path.normcase(os.path.normpath(str(candidate.resolve(strict=False))))


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return child.resolve(strict=False) != parent.resolve(strict=False)
    except ValueError:
        return False


def validate_target_path(target_path: Path, *, source_path: Path = SOURCE, repo: Path = REPO) -> Path:
    """Restrict target selection to an external, named restore workspace sibling."""
    target = Path(target_path)
    projects_root = PROJECTS_ROOT.resolve(strict=False)
    if (
        not target.is_absolute()
        or target.name != target.name.strip()
        or not _RESTORE_TARGET_NAME.fullmatch(target.name)
        or target.parent.resolve(strict=False) != projects_root
    ):
        raise ValueError("Verified isolated restoration required")
    resolved = target.resolve(strict=False)
    source = Path(source_path).resolve(strict=False)
    repository = Path(repo).resolve(strict=False)
    if (
        resolved == source
        or _inside(resolved, source)
        or _inside(source, resolved)
        or resolved == repository
        or _inside(resolved, repository)
        or _inside(repository, resolved)
    ):
        raise ValueError("Verified isolated restoration required")
    return target


def validate_service_ports(
    database_port: int,
    backend_port: int,
    frontend_port: int,
    *,
    source_port: int = SOURCE_DATABASE_PORT,
) -> None:
    if (
        isinstance(database_port, bool)
        or not isinstance(database_port, int)
        or not MIN_DATABASE_PORT <= database_port <= MAX_DATABASE_PORT
        or database_port == source_port
        or isinstance(backend_port, bool)
        or not isinstance(backend_port, int)
        or not MIN_APP_PORT <= backend_port <= MAX_APP_PORT
        or backend_port == source_port
        or isinstance(frontend_port, bool)
        or not isinstance(frontend_port, int)
        or not MIN_APP_PORT <= frontend_port <= MAX_APP_PORT
        or frontend_port == source_port
        or len({database_port, backend_port, frontend_port}) != 3
        # The sealed Playwright child has a deliberately finite origin allowlist.
        # This wrapper only targets the restored pair; source-origin URLs must fail
        # before any account container is opened.
        or backend_port != DEFAULT_BACKEND_PORT
        or frontend_port != DEFAULT_FRONTEND_PORT
    ):
        raise ValueError("Invalid loopback service port profile")


def _normalized_path(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        return None
    try:
        return os.path.normcase(str(candidate.resolve(strict=True)))
    except OSError:
        return None


def _normalized_command(value: str) -> list[str]:
    return [str(part).replace("/", "\\").casefold() for part in _command_arguments(value)]


def _option_value(arguments: list[str], option: str) -> str | None:
    found: list[str] = []
    folded = option.casefold()
    for index, argument in enumerate(arguments):
        current = argument.casefold()
        if current.startswith(folded + "="):
            found.append(argument[len(option) + 1 :])
        elif current == folded and index + 1 < len(arguments):
            found.append(arguments[index + 1])
    return found[0] if len(found) == 1 else None


def _process_identity_matches(process: object, service: dict) -> bool:
    if not isinstance(process, dict):
        return False
    try:
        return (
            type(process.get("ProcessId")) is int
            and process["ProcessId"] == service["pid"]
            and _normalized_path(process.get("ExecutablePath"))
            == _normalized_path(service.get("executable"))
            and bool(_utc_timestamp(str(service.get("creation_time", ""))))
            and _utc_timestamp(str(process.get("CreationUtc", "")))
            == _utc_timestamp(str(service.get("creation_time", "")))
            and _normalized_command(str(process.get("CommandLine", "")))
            == _normalized_command(str(service.get("command_line", "")))
        )
    except (OSError, TypeError, ValueError, KeyError, AttributeError):
        return False


def _verify_service_arguments(service: dict, workspace: Path, backend_port: int, frontend_port: int) -> bool:
    try:
        arguments = _command_arguments(str(service["command_line"]))
        port = service["port"]
        if port == backend_port:
            return (
                any(Path(argument).name.casefold() == "school_backend.py" for argument in arguments)
                and _path_key(_option_value(arguments, "--workspace"))
                == _path_key(str(workspace))
                and _option_value(arguments, "--port") == str(backend_port)
                and _option_value(arguments, "--frontend-port") == str(frontend_port)
            )
        if port == frontend_port:
            return (
                any(Path(argument).name.casefold() in {"vite.js", "vite.mjs"} for argument in arguments)
                and _option_value(arguments, "--host") == "127.0.0.1"
                and _option_value(arguments, "--port") == str(frontend_port)
                and "--strictport" in {argument.casefold() for argument in arguments}
            )
        return False
    except (OSError, TypeError, ValueError, KeyError, AttributeError):
        return False


def verify_owned_listeners(
    workspace: Path,
    backend_port: int = DEFAULT_BACKEND_PORT,
    frontend_port: int = DEFAULT_FRONTEND_PORT,
    *,
    operations: ResumeOperations | None = None,
) -> None:
    """Require live CIM process identities and listeners to match the restore proof."""
    target = Path(workspace)
    manifest_path = target / "restore-processes.json"
    _reject_reparse_path(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_workspace = _path_key(str(target))
        services = manifest.get("services") if isinstance(manifest, dict) else None
        if (
            manifest.get("schema_version") != _RESTORE_PROCESS_SCHEMA
            or _path_key(manifest.get("workspace")) != expected_workspace
            or not isinstance(services, list)
            or len(services) != 2
        ):
            raise ValueError

        by_port: dict[int, dict] = {}
        for service in services:
            if not isinstance(service, dict):
                raise TypeError
            port = service.get("port")
            if type(port) is not int or port in by_port:
                raise ValueError
            by_port[port] = service
        if set(by_port) != {backend_port, frontend_port}:
            raise ValueError

        ops = operations or ResumeOperations()
        process_ids: set[int] = set()
        for port, service in by_port.items():
            pid = service.get("pid")
            parent_pid = service.get("parent_pid")
            executable = service.get("executable")
            parent_executable = service.get("parent_executable")
            creation = _utc_timestamp(str(service.get("creation_time", "")))
            parent_creation = _utc_timestamp(str(service.get("parent_creation_time", "")))
            if (
                type(pid) is not int or pid <= 0 or pid in process_ids
                or type(parent_pid) is not int or parent_pid <= 0 or parent_pid == pid
                or not _normalized_path(executable)
                or not _normalized_path(parent_executable)
                or not creation or not parent_creation
                or not isinstance(service.get("command_line"), str)
                or not service["command_line"]
                or service.get("local_address") != "127.0.0.1"
                or service.get("name") != f"Restored owned service {port}"
                or not _verify_service_arguments(service, target, backend_port, frontend_port)
            ):
                raise ValueError
            process_ids.add(pid)

            process = ops.inspect_process(pid)
            parent = ops.inspect_process(parent_pid)
            if not _process_identity_matches(process, service):
                raise ValueError
            if (
                not isinstance(parent, dict)
                or type(parent.get("ProcessId")) is not int
                or parent["ProcessId"] != parent_pid
                or _normalized_path(parent.get("ExecutablePath")) != _normalized_path(parent_executable)
                or _utc_timestamp(str(parent.get("CreationUtc", ""))) != parent_creation
            ):
                raise ValueError
            listeners = ops.listeners(port)
            if (
                not isinstance(listeners, list)
                or len(listeners) != 1
                or type(listeners[0].get("OwningProcess")) is not int
                or listeners[0].get("OwningProcess") != pid
                or listeners[0].get("LocalAddress") != "127.0.0.1"
                or type(listeners[0].get("LocalPort")) is not int
                or listeners[0].get("LocalPort") != port
            ):
                raise ValueError
    except (OSError, TypeError, ValueError, KeyError, AttributeError, json.JSONDecodeError):
        raise ValueError("Restored service ownership changed") from None


def _valid_workspace_data_dir(workspace: Path, marker: dict) -> str | None:
    value = marker.get("data_directory")
    path_key = _path_key(value)
    if path_key is None:
        return None
    data_dir = Path(value).resolve(strict=False)
    if not _inside(data_dir, workspace):
        return None
    return path_key


def validate_restore_profile(
    state: dict,
    source_marker: dict,
    target_marker: dict,
    *,
    target_path: Path = TARGET,
    database_port: int = DEFAULT_DATABASE_PORT,
) -> None:
    """Bind restore evidence to this exact source, target path, IDs, port, and datadirs."""
    if not all(isinstance(item, dict) for item in (state, source_marker, target_marker)):
        raise ValueError("Verified isolated restoration required")
    try:
        target = validate_target_path(target_path)
        validate_service_ports(database_port, DEFAULT_BACKEND_PORT, DEFAULT_FRONTEND_PORT)
    except (OSError, TypeError, ValueError):
        raise ValueError("Verified isolated restoration required") from None

    source_id = source_marker.get("workspace_id")
    target_id = target_marker.get("workspace_id")
    source_pid = source_marker.get("parent_pid")
    target_pid = target_marker.get("parent_pid")
    source_data_dir = _valid_workspace_data_dir(SOURCE, source_marker)
    target_data_dir = _valid_workspace_data_dir(target, target_marker)
    state_data_dir = _path_key(state.get("data_directory"))
    shared_database = source_marker.get("database")
    target_path_key = _path_key(str(target))
    if (
        state.get("phase") != "DATA_KEYS_RUNTIME_VERIFIED_REQUIRES_BROWSER"
        or state.get("source_workspace_id") != source_id
        or state.get("workspace_id") != target_id
        or state.get("workspace") is None
        or _path_key(state.get("workspace")) != target_path_key
        or not isinstance(source_id, str)
        or not source_id
        or not isinstance(target_id, str)
        or not target_id
        or source_id == target_id
        or type(source_pid) is not int
        or source_pid <= 0
        or type(target_pid) is not int
        or target_pid <= 0
        or source_pid == target_pid
        or source_marker.get("host") != "127.0.0.1"
        or target_marker.get("host") != "127.0.0.1"
        or state.get("host") != "127.0.0.1"
        or type(source_marker.get("port")) is not int
        or source_marker.get("port") != SOURCE_DATABASE_PORT
        or type(target_marker.get("port")) is not int
        or target_marker.get("port") != database_port
        or type(state.get("port")) is not int
        or state.get("port") != database_port
        or source_marker.get("synthetic_only") is not True
        or target_marker.get("synthetic_only") is not True
        or state.get("synthetic_only") is not True
        or not isinstance(shared_database, str)
        or not shared_database
        or target_marker.get("database") != shared_database
        or state.get("database") != shared_database
        or source_data_dir is None
        or target_data_dir is None
        or state_data_dir != target_data_dir
        or source_data_dir == target_data_dir
    ):
        raise ValueError("Verified isolated restoration required")


def run(
    browser_cache: Path | None = None,
    *,
    target: Path = TARGET,
    database_port: int = DEFAULT_DATABASE_PORT,
    backend_port: int = DEFAULT_BACKEND_PORT,
    frontend_port: int = DEFAULT_FRONTEND_PORT,
) -> dict:
    target = Path(target)
    validate_service_ports(database_port, backend_port, frontend_port)
    _reject_reparse_path(target)
    target = validate_target_path(target)
    for root in (SOURCE, target):
        _reject_reparse_path(root)
    _reject_reparse_path(SOURCE / "workspace.json")
    _reject_reparse_path(target / "workspace.json")
    _reject_reparse_path(target / "restore-state.json")
    _reject_reparse_path(target / "restore-processes.json")
    state = json.loads((target / "restore-state.json").read_text(encoding="utf-8"))
    source_marker = json.loads((SOURCE / "workspace.json").read_text(encoding="utf-8"))
    target_marker = json.loads((target / "workspace.json").read_text(encoding="utf-8"))
    validate_restore_profile(
        state, source_marker, target_marker, target_path=target, database_port=database_port,
    )
    for marker, workspace in ((source_marker, SOURCE), (target_marker, target)):
        _reject_reparse_path(Path(marker["data_directory"]))
        if not _inside(Path(marker["data_directory"]), workspace):
            raise ValueError("Verified isolated restoration required")
    process = ResumeOperations().inspect_process(target_marker["parent_pid"])
    if process is None or not _process_matches(process, target_marker):
        raise ValueError("Restored guardian identity changed")
    verify_owned_listeners(target, backend_port, frontend_port)
    load_runtime(target, REPO)
    _reject_reparse_path(SOURCE / ACCOUNT_FILE)
    credentials = validate_credentials(read_private(SOURCE / ACCOUNT_FILE))
    artifact_dir = create_artifact_run_dir(target)
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Existing Node runtime unavailable")
    payload = {
        "credentials": credentials, "artifact_dir": str(artifact_dir),
        "frontend_url": f"http://127.0.0.1:{frontend_port}",
        "backend_url": f"http://127.0.0.1:{backend_port}",
        "accounts": {slot: {"role": frontend_role, "api_role": api_role, "path": route}
                     for slot, (frontend_role, api_role, route) in ACCOUNT_SLOTS.items()},
    }
    environment = safe_node_environment()
    if browser_cache is not None:
        _reject_reparse_path(browser_cache)
        if not browser_cache.is_dir():
            raise ValueError("Existing browser cache directory required")
        environment["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_cache)
    child = subprocess.run(
        [node, str(NODE_SCRIPT)], input=json.dumps(payload), text=True, encoding="utf-8",
        capture_output=True, cwd=FRONTEND, timeout=300, check=False, shell=False,
        env=environment,
    )
    del credentials, payload
    result = sanitize_child_output(child.stdout, artifact_dir=artifact_dir,
                                   child_exit_code=child.returncode)
    result["restored_workspace"] = True
    result["profile"] = {
        "target": str(target),
        "database_port": database_port,
        "backend_port": backend_port,
        "frontend_port": frontend_port,
    }
    result["artifact_dir"] = str(artifact_dir)
    # Child stderr/unsanitized stdout and browser storage never become artifacts.
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-cache", type=Path)
    parser.add_argument("--target", type=Path, default=TARGET)
    parser.add_argument("--database-port", type=int, default=DEFAULT_DATABASE_PORT)
    parser.add_argument("--backend-port", type=int, default=DEFAULT_BACKEND_PORT)
    parser.add_argument("--frontend-port", type=int, default=DEFAULT_FRONTEND_PORT)
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    for path in (REPO / "11_database", REPO / "09_backend" / "src"):
        sys.path.insert(0, str(path))
    try:
        result = run(
            args.browser_cache,
            target=args.target,
            database_port=args.database_port,
            backend_port=args.backend_port,
            frontend_port=args.frontend_port,
        )
        print(json.dumps(result))
        sys.exit(0 if result.get("status") == "PASS" else 2)
    except Exception as exc:  # noqa: BLE001 - emit no credentials, candidate content or driver details.
        print(json.dumps({"status": "FAIL", "error_type": type(exc).__name__}))
        sys.exit(2)
