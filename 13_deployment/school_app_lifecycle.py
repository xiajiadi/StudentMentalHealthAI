"""Own the Backend and Frontend processes for a prepared synthetic school workspace.

This is an application lifecycle helper, not an installer. It never creates,
migrates, seeds, stops, or resets a database and never manages shared modules.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from resume_school_workspace import _utc_timestamp
from school_backend import (
    DEFAULT_BACKEND_PORT,
    DEFAULT_FRONTEND_PORT,
    LLM_PROFILES,
    ResearchCLIConfigError,
    _parse_study_end,
    build_research_settings_kwargs,
)
from school_schema import CURRENT_SCHOOL_REVISION, SUPPORTED_SNAPSHOT_REVISIONS

SCHEMA = "psynova.school-app-lifecycle.v1"
MANIFEST_NAME = "school-app-lifecycle.json"
PREVIEW_ARTIFACTS_DIR = ".school-app-preview"
SERVICES = ("backend", "frontend")
SECRET_ENV_NAMES = {
    "DATABASE_URL",
    "DATABASE_KEY_FILE",
    "MYSQL_PWD",
    "NODE_OPTIONS",
    "NODE_PATH",
    "PYTHONPATH",
    "PYTHONHOME",
}
READY_PATHS = {"backend": "/health/ready", "frontend": "/"}
START_TIMEOUT_SECONDS = 25.0
IS_WINDOWS = os.name == "nt"
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003
RESEARCH_CONFIG_ARGUMENTS = (
    "research_runtime_file",
    "research_runtime_sha256",
    "research_service_file",
    "research_service_sha256",
    "research_cat_python",
    "research_cat_source",
    "research_cat_dependencies",
)
RESEARCH_CONFIG_FLAGS = {
    "research_runtime_file": "--research-runtime-file",
    "research_runtime_sha256": "--research-runtime-sha256",
    "research_service_file": "--research-service-file",
    "research_service_sha256": "--research-service-sha256",
    "research_cat_python": "--research-cat-python",
    "research_cat_source": "--research-cat-source",
    "research_cat_dependencies": "--research-cat-dependencies",
}
RESEARCH_STUDY_USE_ARGUMENTS = (
    "research_study_use_file",
    "research_study_use_sha256",
    "research_source_rights_verified",
    "research_latest_study_end",
)
RESEARCH_STUDY_USE_FLAGS = {
    "research_study_use_file": "--research-study-use-file",
    "research_study_use_sha256": "--research-study-use-sha256",
    "research_source_rights_verified": "--research-source-rights-verified",
    "research_latest_study_end": "--research-latest-study-end",
}
RESEARCH_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class ResearchProcessConfig:
    """Validated, immutable public paths and pins for the Backend-owned CAT."""

    runtime_file: str
    runtime_sha256: str
    service_file: str
    service_sha256: str
    cat_python: str
    cat_source: str
    cat_dependencies: str
    port: int
    study_use_file: str | None = None
    study_use_sha256: str | None = None
    source_rights_verified: bool = False
    latest_study_end: str | None = None

    def cli_arguments(self) -> list[str]:
        values = {
            "research_runtime_file": self.runtime_file,
            "research_runtime_sha256": self.runtime_sha256,
            "research_service_file": self.service_file,
            "research_service_sha256": self.service_sha256,
            "research_cat_python": self.cat_python,
            "research_cat_source": self.cat_source,
            "research_cat_dependencies": self.cat_dependencies,
        }
        arguments = [
            argument
            for name in RESEARCH_CONFIG_ARGUMENTS
            for argument in (RESEARCH_CONFIG_FLAGS[name], values[name])
        ]
        if self.study_use_file is not None:
            study_values: dict[str, object] = {
                "research_study_use_file": self.study_use_file,
                "research_study_use_sha256": self.study_use_sha256,
                "research_source_rights_verified": self.source_rights_verified,
                "research_latest_study_end": self.latest_study_end,
            }
            for name in RESEARCH_STUDY_USE_ARGUMENTS:
                flag = RESEARCH_STUDY_USE_FLAGS[name]
                if name == "research_source_rights_verified":
                    if study_values[name] is not True:
                        raise LifecycleError("Research study-use flag is invalid")
                    arguments.append(flag)
                else:
                    arguments.extend((flag, str(study_values[name])))
        return arguments

    def manifest_value(self) -> dict[str, str]:
        value = {
            "research_runtime_file": self.runtime_file,
            "research_runtime_sha256": self.runtime_sha256,
            "research_service_file": self.service_file,
            "research_service_sha256": self.service_sha256,
            "research_cat_python": self.cat_python,
            "research_cat_source": self.cat_source,
            "research_cat_dependencies": self.cat_dependencies,
        }
        if self.study_use_file is not None:
            value.update(
                {
                    "research_study_use_file": self.study_use_file,
                    "research_study_use_sha256": self.study_use_sha256,
                    "research_source_rights_verified": self.source_rights_verified,
                    "research_latest_study_end": self.latest_study_end,
                }
            )
        return value


class LifecycleError(RuntimeError):
    """A safe lifecycle error that never carries child output or credentials."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _path_key(value: str | Path) -> str:
    return os.path.normcase(str(Path(value).resolve(strict=False)))


def _normalized_argv(argv: list[str]) -> list[str]:
    return [item.replace("/", "\\").casefold() for item in argv]


def _sanitize_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    source = os.environ if source is None else source
    return {
        key: value
        for key, value in source.items()
        if not key.upper().startswith(("DB_", "SMHAI_", "VITE_"))
        and key.upper() not in SECRET_ENV_NAMES
    }


def _backend_python_paths(repo: Path) -> tuple[Path, Path]:
    launcher = repo / "09_backend" / ".venv" / "Scripts" / "python.exe"
    config = repo / "09_backend" / ".venv" / "pyvenv.cfg"
    try:
        _reject_reparse_path(launcher)
        _reject_reparse_path(config)
        values = {}
        for line in config.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                normalized_key = key.strip().casefold()
                if normalized_key in values:
                    raise ValueError
                values[normalized_key] = value.strip()
        home = Path(values["home"])
        if not home.is_absolute() or ".." in home.parts:
            raise ValueError
        _require_local_absolute_path(home)
        _reject_reparse_path(home.parent)
        home_info = home.lstat()
        attributes = getattr(home_info, "st_file_attributes", 0)
        if attributes & FILE_ATTRIBUTE_REPARSE_POINT:
            if getattr(home_info, "st_reparse_tag", None) != IO_REPARSE_TAG_MOUNT_POINT:
                raise ValueError
        else:
            _reject_reparse_path(home)
        resolved_home = home.resolve(strict=True)
        _require_local_absolute_path(resolved_home)
        if resolved_home.drive.casefold() != home.drive.casefold():
            raise ValueError
        _reject_reparse_path(resolved_home)
        base_python = resolved_home / "python.exe"
        _reject_reparse_path(base_python)
        resolved_base = base_python.resolve(strict=True)
        resolved_launcher = launcher.resolve(strict=True)
        if resolved_base.parent != resolved_home or not resolved_base.is_file():
            raise ValueError
        return resolved_launcher, resolved_base
    except (OSError, KeyError, ValueError, LifecycleError):
        raise LifecycleError(
            "Backend virtual environment base Python cannot be verified"
        ) from None


def _require_local_absolute_path(path: Path) -> None:
    if (
        not path.is_absolute()
        or not path.drive
        or path.drive.startswith("\\\\")
        or len(path.drive) != 2
        or path.drive[1] != ":"
        or not IS_WINDOWS
    ):
        raise LifecycleError("Backend Python home must resolve to a local drive")
    try:
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_drive_type = kernel32.GetDriveTypeW
        get_drive_type.argtypes = [wintypes.LPCWSTR]
        get_drive_type.restype = wintypes.UINT
        drive_type = get_drive_type(path.anchor)
    except (AttributeError, OSError):
        raise LifecycleError("Backend Python drive type cannot be verified") from None
    if drive_type not in {2, 3, 6}:  # removable, fixed, or RAM disk
        raise LifecycleError("Backend Python home must resolve to a local drive")


def _reject_reparse_path(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise LifecycleError("Absolute normalized paths are required")
    cursor = Path(path.anchor)
    for part in path.parts[1:]:
        cursor /= part
        try:
            info = cursor.lstat()
        except FileNotFoundError:
            if cursor != path:
                raise LifecycleError("Workspace path is incomplete") from None
            return
        except OSError:
            raise LifecycleError("Workspace path could not be verified") from None
        if getattr(info, "st_file_attributes", 0) & 0x400:
            raise LifecycleError("Reparse points are not allowed in lifecycle paths")


def _reject_existing_reparse_components(path: Path) -> None:
    """Reject reparse points while allowing a removed preview artifact path."""
    if not path.is_absolute() or ".." in path.parts:
        raise LifecycleError("Absolute normalized paths are required")
    cursor = Path(path.anchor)
    for part in path.parts[1:]:
        cursor /= part
        try:
            info = cursor.lstat()
        except FileNotFoundError:
            # Missing preview output must not prevent verifying or stopping its owner.
            break
        except OSError:
            raise LifecycleError("Lifecycle path could not be verified") from None
        if getattr(info, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
            raise LifecycleError("Reparse points are not allowed in lifecycle paths")


def _new_preview_output_dir(target: Path) -> Path:
    root = target / PREVIEW_ARTIFACTS_DIR
    try:
        _reject_reparse_path(root)
        root.mkdir(exist_ok=True)
        _reject_reparse_path(root)
        output = root / uuid4().hex
        _reject_reparse_path(output)
        output.mkdir()
        _reject_reparse_path(output)
        return output.resolve(strict=True)
    except (OSError, LifecycleError):
        raise LifecycleError(
            "Workspace preview output directory is unavailable"
        ) from None


def _validated_preview_output_dir(value: object, target: Path) -> Path:
    if not isinstance(value, str):
        raise LifecycleError("Lifecycle preview output directory is invalid")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise LifecycleError("Lifecycle preview output directory is invalid")
    root = target / PREVIEW_ARTIFACTS_DIR
    token = path.name
    try:
        token_uuid = UUID(hex=token)
        token_matches = (
            len(token) == 32 and token_uuid.hex == token and token_uuid.version == 4
        )
        _reject_existing_reparse_components(root)
        _reject_existing_reparse_components(path)
        expected = root / token
        exact = _path_key(path) == _path_key(expected)
    except (OSError, ValueError):
        token_matches = False
        exact = False
    if not token_matches or not exact:
        raise LifecycleError(
            "Lifecycle preview output directory is outside its workspace"
        )
    return expected


def _verify_preview_output_dir(value: object, target: Path) -> Path:
    output = _validated_preview_output_dir(value, target)
    try:
        _reject_reparse_path(output)
        index_path = output / "index.html"
        _reject_reparse_path(index_path)
        if not output.is_dir() or not index_path.is_file():
            raise LifecycleError("Workspace preview build output is unavailable")
    except OSError:
        raise LifecycleError(
            "Workspace preview build output could not be verified"
        ) from None
    return output


def _read_manifest(path: Path) -> dict[str, Any]:
    _reject_reparse_path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise LifecycleError("Lifecycle manifest is missing or invalid") from None
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA:
        raise LifecycleError("Lifecycle manifest schema is unknown")
    return data


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    _reject_reparse_path(temporary)
    try:
        temporary.lstat()
    except FileNotFoundError:
        pass
    except OSError:
        raise LifecycleError("Lifecycle temporary file could not be verified") from None
    else:
        raise LifecycleError("Lifecycle temporary file already exists")
    created_by_attempt = False
    try:
        handle_context = temporary.open("x", encoding="utf-8", newline="\n")
        created_by_attempt = True
        with handle_context as handle:
            json.dump(payload, handle, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError:
        if created_by_attempt:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise LifecycleError("Lifecycle manifest could not be saved") from None


def _absolute_external_workspace(workspace: Path, repo: Path) -> Path:
    if not workspace.is_absolute():
        raise LifecycleError("An absolute workspace path is required")
    _reject_reparse_path(workspace)
    try:
        resolved = workspace.resolve(strict=True)
        repository = repo.resolve(strict=True)
    except OSError:
        raise LifecycleError(
            "Prepared workspace or repository is unavailable"
        ) from None
    if resolved == repository or resolved.is_relative_to(repository):
        raise LifecycleError("Workspace must be outside the repository")
    return resolved


def _safe_argv(argv: list[str]) -> list[str]:
    # Child argv is restricted to executable/script paths and public ports/options.
    # Reject accidental credential-like arguments before they reach a manifest.
    joined = " ".join(argv).casefold()
    if any(
        token in joined
        for token in ("password=", "mysql_pwd", "database_url", "secret=")
    ):
        raise LifecycleError("Credential-like child arguments are not allowed")
    return argv


def _validated_research_config(
    value: Mapping[str, object] | None, target: Path
) -> ResearchProcessConfig | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or frozenset(value) not in {
        frozenset(RESEARCH_CONFIG_ARGUMENTS),
        frozenset(RESEARCH_CONFIG_ARGUMENTS + RESEARCH_STUDY_USE_ARGUMENTS),
    }:
        raise LifecycleError("Research process configuration must provide all pinned fields")
    if all(value[name] is None for name in RESEARCH_CONFIG_ARGUMENTS):
        if set(value) == set(RESEARCH_CONFIG_ARGUMENTS + RESEARCH_STUDY_USE_ARGUMENTS) and any(
            value[name] is not None
            and (name != "research_source_rights_verified" or value[name] is True)
            for name in RESEARCH_STUDY_USE_ARGUMENTS
        ):
            raise LifecycleError("Research study-use requires the CAT configuration")
        return None

    args_values: dict[str, object] = {}
    for name in RESEARCH_CONFIG_ARGUMENTS:
        item = value[name]
        if name.endswith("_file") or name in {
            "research_cat_python",
            "research_cat_source",
            "research_cat_dependencies",
        }:
            if isinstance(item, str):
                item = Path(item)
            if not isinstance(item, Path):
                raise LifecycleError("Research process configuration is invalid")
        args_values[name] = item
    if set(value) == set(RESEARCH_CONFIG_ARGUMENTS + RESEARCH_STUDY_USE_ARGUMENTS):
        for name in RESEARCH_STUDY_USE_ARGUMENTS:
            item = value[name]
            if name == "research_study_use_file" and isinstance(item, str):
                item = Path(item)
            if name == "research_study_use_file" and item is not None and not isinstance(item, Path):
                raise LifecycleError("Research study-use configuration is invalid")
            args_values[name] = item

    try:
        settings = build_research_settings_kwargs(
            argparse.Namespace(**args_values), target
        )
    except Exception:  # noqa: BLE001 - hide source paths and parser details.
        raise LifecycleError("Research process configuration failed pinned preflight") from None
    if not settings:
        raise LifecycleError("Research process configuration is incomplete")
    base_url = settings.get("school_research_base_url")
    match = re.fullmatch(r"http://127\.0\.0\.1:([0-9]{1,5})", str(base_url))
    if match is None:
        raise LifecycleError("Research service must use its pinned loopback listener")

    return ResearchProcessConfig(
        runtime_file=str(settings["school_research_runtime_file"]),
        runtime_sha256=str(settings["school_research_runtime_sha256"]),
        service_file=str(settings["school_research_service_file"]),
        service_sha256=str(settings["school_research_service_sha256"]),
        cat_python=str(settings["school_research_cat_python"]),
        cat_source=str(settings["school_research_cat_source"]),
        cat_dependencies=str(settings["school_research_cat_dependencies"]),
        port=int(match.group(1)),
        study_use_file=(
            str(settings["school_research_study_use_file"])
            if "school_research_study_use_file" in settings else None
        ),
        study_use_sha256=settings.get("school_research_study_use_sha256"),
        source_rights_verified=settings.get("school_research_source_rights_verified", False),
        latest_study_end=(
            str(args_values["research_latest_study_end"])
            if args_values.get("research_latest_study_end") is not None else None
        ),
    )


def _research_config_from_manifest(
    manifest: Mapping[str, object], target: Path, backend_port: int, frontend_port: int
) -> ResearchProcessConfig | None:
    has_config = "research_config" in manifest
    has_port = "research_cat_port" in manifest
    if not has_config and not has_port:
        return None
    if has_config != has_port:
        raise LifecycleError("Lifecycle research configuration is incomplete")
    raw = manifest.get("research_config")
    raw_keys = set(raw) if type(raw) is dict else set()
    has_study = raw_keys == set(RESEARCH_CONFIG_ARGUMENTS + RESEARCH_STUDY_USE_ARGUMENTS)
    if type(raw) is not dict or frozenset(raw_keys) not in {
        frozenset(RESEARCH_CONFIG_ARGUMENTS),
        frozenset(RESEARCH_CONFIG_ARGUMENTS + RESEARCH_STUDY_USE_ARGUMENTS),
    }:
        raise LifecycleError("Lifecycle research configuration is invalid")
    for name in RESEARCH_CONFIG_ARGUMENTS:
        value = raw.get(name)
        if name.endswith("_sha256"):
            if type(value) is not str or RESEARCH_SHA256.fullmatch(value) is None:
                raise LifecycleError("Lifecycle research configuration is invalid")
            continue
        if (
            type(value) is not str
            or not Path(value).is_absolute()
            or ".." in Path(value).parts
        ):
            raise LifecycleError("Lifecycle research configuration is invalid")
        if name in {"research_runtime_file", "research_service_file"} and not Path(
            value
        ).is_relative_to(target):
            raise LifecycleError("Lifecycle research configuration escaped its workspace")
    study_values: dict[str, object] = {}
    if has_study:
        study_path = raw.get("research_study_use_file")
        study_sha = raw.get("research_study_use_sha256")
        rights_verified = raw.get("research_source_rights_verified")
        latest_end = raw.get("research_latest_study_end")
        if (
            type(study_path) is not str
            or not Path(study_path).is_absolute()
            or ".." in Path(study_path).parts
            or not Path(study_path).is_relative_to(target)
            or type(study_sha) is not str
            or RESEARCH_SHA256.fullmatch(study_sha) is None
            or rights_verified is not True
            or type(latest_end) is not str
        ):
            raise LifecycleError("Lifecycle research study-use configuration is invalid")
        try:
            _parse_study_end(latest_end)
        except ResearchCLIConfigError:
            raise LifecycleError("Lifecycle research study-use configuration is invalid") from None
        study_values = {
            "study_use_file": study_path,
            "study_use_sha256": study_sha,
            "source_rights_verified": rights_verified,
            "latest_study_end": latest_end,
        }
    elif any(name.startswith("research_study_use") for name in raw_keys):
        raise LifecycleError("Lifecycle research study-use configuration is incomplete")
    port = manifest.get("research_cat_port")
    if (
        type(port) is not int
        or not 1024 <= port <= 65535
        or port in {backend_port, frontend_port, 8160, 8170, 8180, 8190}
    ):
        raise LifecycleError("Lifecycle research CAT port is invalid")
    return ResearchProcessConfig(
        runtime_file=raw["research_runtime_file"],
        runtime_sha256=raw["research_runtime_sha256"],
        service_file=raw["research_service_file"],
        service_sha256=raw["research_service_sha256"],
        cat_python=raw["research_cat_python"],
        cat_source=raw["research_cat_source"],
        cat_dependencies=raw["research_cat_dependencies"],
        port=port,
        **study_values,
    )


def _utc_creation(process: dict[str, Any]) -> str | None:
    value = process.get("CreationUtc") if isinstance(process, dict) else None
    return _utc_timestamp(str(value)) if value else None


class LifecycleOperations:
    """Windows process/network operations, separated for safe fake-based tests."""

    def inspect_process(self, pid: int) -> dict[str, Any] | None:
        try:
            script = r"""
$p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $env:PSYNOVA_LIFECYCLE_PID)
if ($null -eq $p) { 'null'; exit 0 }
@{
    ProcessId = $p.ProcessId
    ParentProcessId = $p.ParentProcessId
    ExecutablePath = $p.ExecutablePath
    CommandLine = $p.CommandLine
    CreationUtc = $p.CreationDate.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffffffZ')
} | ConvertTo-Json -Compress
"""
            env = _sanitize_environment(
                {**os.environ, "PSYNOVA_LIFECYCLE_PID": str(pid)}
            )
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script],
                env=env,
                capture_output=True,
                text=True,
                check=True,
                timeout=15,
            )
            value = json.loads(result.stdout or "null")
            return value if isinstance(value, dict) else None
        except Exception:  # noqa: BLE001 - process metadata must not leak shell output.
            return None

    def listeners(self, port: int) -> list[dict[str, Any]]:
        try:
            script = (
                "$x=@(Get-NetTCPConnection -State Listen -LocalPort $env:PSYNOVA_PORT "
                "-ErrorAction SilentlyContinue | Select-Object OwningProcess,LocalAddress,LocalPort); "
                "$x | ConvertTo-Json -Depth 3 -Compress"
            )
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script],
                env=_sanitize_environment({**os.environ, "PSYNOVA_PORT": str(port)}),
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
            value = json.loads(result.stdout or "[]")
            if value is None:
                return []
            return value if isinstance(value, list) else [value]
        except Exception:  # noqa: BLE001 - fail closed on listener uncertainty.
            raise LifecycleError("Listener ownership could not be verified") from None

    def port_is_free(self, port: int) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
                probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False

    def spawn(
        self, argv: list[str], *, cwd: Path, env: dict[str, str]
    ) -> subprocess.Popen:
        if not IS_WINDOWS:
            raise LifecycleError("Native school application lifecycle requires Windows")
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        try:
            return subprocess.Popen(
                _safe_argv(argv),
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                startupinfo=startup,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                close_fds=True,
                shell=False,
            )
        except OSError as exc:
            raise LifecycleError(
                f"Process launch failed ({type(exc).__name__})"
            ) from None

    def build_frontend(
        self,
        repo: Path,
        backend_port: int,
        preview_output_dir: Path,
        *,
        timeout: float = 360.0,
    ) -> None:
        node = shutil.which("node")
        vue_tsc = (
            repo / "10_frontend" / "node_modules" / "vue-tsc" / "bin" / "vue-tsc.js"
        )
        vite = repo / "10_frontend" / "node_modules" / "vite" / "bin" / "vite.js"
        if not node or not vue_tsc.is_file() or not vite.is_file():
            raise LifecycleError(
                "Existing Node and frontend project dependencies are required"
            )
        try:
            _reject_reparse_path(preview_output_dir)
            if not preview_output_dir.is_dir() or any(preview_output_dir.iterdir()):
                raise LifecycleError("Workspace preview output directory is not empty")
        except OSError:
            raise LifecycleError("Workspace preview output directory is unavailable") from None
        env = _sanitize_environment()
        env.update(
            {
                "VITE_API_MODE": "real",
                "VITE_API_BASE_URL": f"http://127.0.0.1:{backend_port}",
            }
        )
        commands = (
            [node, str(vue_tsc), "--noEmit"],
            [node, str(vite), "build", "--outDir", str(preview_output_dir)],
        )
        for argv in commands:
            try:
                subprocess.run(
                    _safe_argv(list(argv)),
                    cwd=repo / "10_frontend",
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=timeout,
                    check=True,
                    shell=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise LifecycleError(
                    f"Frontend build failed ({type(exc).__name__})"
                ) from None
        try:
            _reject_reparse_path(preview_output_dir)
            index_path = preview_output_dir / "index.html"
            _reject_reparse_path(index_path)
            if not index_path.is_file():
                raise LifecycleError("Frontend preview build did not create index.html")
        except OSError:
            raise LifecycleError("Workspace preview build output could not be verified") from None

    def http_ready(self, port: int, path: str) -> bool:
        try:
            url = f"http://127.0.0.1:{port}{path}"
            if not url.startswith(f"http://127.0.0.1:{port}/"):
                return False
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(url, timeout=1.0) as response:
                if not 200 <= response.status < 300:
                    return False
                if path == "/health/ready":
                    payload = json.loads(response.read(64 * 1024))
                    data = payload.get("data") if isinstance(payload, dict) else None
                    core = data.get("core") if isinstance(data, dict) else None
                    return (
                        isinstance(data, dict)
                        and data.get("status") == "ready"
                        and isinstance(core, dict)
                        and core.get("configuration") == "READY"
                        and core.get("session_store") == "READY"
                    )
                return True
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, ValueError):
            return False

    def wait_ready(
        self, process: subprocess.Popen, port: int, path: str, timeout: float
    ) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return False
            if self.http_ready(port, path):
                return True
            time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
        return False

    def terminate_verified(
        self, service: dict[str, Any], process_identity: dict[str, Any]
    ) -> bool:
        """Pin the process object before validating identity and terminating it."""
        if not IS_WINDOWS:
            raise LifecycleError(
                "Verified Windows process handles are required for stop"
            )
        pid = process_identity.get("pid")
        if type(pid) is not int or pid <= 0:
            raise LifecycleError("Recorded process identity is invalid")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        open_process.restype = ctypes.c_void_p
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [ctypes.c_void_p]
        close_handle.restype = ctypes.c_int
        get_pid = kernel32.GetProcessId
        get_pid.argtypes = [ctypes.c_void_p]
        get_pid.restype = ctypes.c_uint32
        terminate = kernel32.TerminateProcess
        terminate.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        terminate.restype = ctypes.c_int
        wait = kernel32.WaitForSingleObject
        wait.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        wait.restype = ctypes.c_uint32
        handle = open_process(
            0x0001 | 0x1000 | 0x00100000, 0, pid
        )  # TERMINATE | QUERY_LIMITED | SYNCHRONIZE
        if not handle:
            process = self.inspect_process(pid)
            if process is None:
                return False
            raise LifecycleError("Recorded process cannot be opened for verified stop")
        try:
            if get_pid(handle) != pid:
                raise LifecycleError("Process handle identity changed")
            current = self.inspect_process(pid)
            if not _matches_process(current, process_identity):
                raise LifecycleError("Process identity changed; refusing to stop")
            listeners = self.listeners(service["port"])
            if listeners and (
                len(listeners) != 1
                or not isinstance(service.get("listener"), dict)
                or listeners[0].get("OwningProcess") != service["listener"].get("pid")
                or listeners[0].get("LocalAddress") != "127.0.0.1"
            ):
                raise LifecycleError("Listener identity changed; refusing to stop")
            if not terminate(handle, 1):
                raise LifecycleError("Verified process stop failed")
            return wait(handle, 10_000) == 0
        finally:
            close_handle(handle)


def _matches_process(process: object, expected: dict[str, Any]) -> bool:
    if not isinstance(process, dict):
        return False
    expected_argv = expected.get("argv")
    actual_command = process.get("CommandLine")
    if not isinstance(expected_argv, list) or not all(
        isinstance(item, str) for item in expected_argv
    ):
        return False
    try:
        from resume_school_workspace import _command_arguments

        actual_argv = _command_arguments(str(actual_command))
        return (
            type(process.get("ProcessId")) is int
            and process["ProcessId"] == expected.get("pid")
            and process.get("ParentProcessId") == expected.get("parent_pid")
            and _path_key(str(process.get("ExecutablePath", "")))
            == _path_key(str(expected.get("executable", "")))
            and _utc_creation(process)
            == _utc_timestamp(str(expected.get("creation_time", "")))
            and [part.casefold() for part in actual_argv]
            == [part.casefold() for part in expected_argv]
        )
    except (OSError, TypeError, ValueError, KeyError):
        return False


def _same_command_line(command_line: object, expected_argv: list[str]) -> bool:
    if not isinstance(command_line, str):
        return False
    try:
        from resume_school_workspace import _command_arguments

        return _normalized_argv(_command_arguments(command_line)) == _normalized_argv(
            expected_argv
        )
    except (OSError, TypeError, ValueError):
        return False


def _command_line_argv(command_line: object) -> list[str] | None:
    if not isinstance(command_line, str):
        return None
    try:
        from resume_school_workspace import _command_arguments

        return _command_arguments(command_line)
    except (OSError, TypeError, ValueError):
        return None


def _backend_listener_argv_matches(
    actual_argv: list[str], service_argv: list[str], base_executable: object
) -> bool:
    return bool(
        isinstance(base_executable, str)
        and Path(base_executable).is_absolute()
        and len(actual_argv) == len(service_argv)
        and actual_argv
        and _path_key(actual_argv[0]) == _path_key(base_executable)
        and actual_argv[1:] == service_argv[1:]
    )


def _listener_argv_matches(
    service: dict[str, Any], pid: object, actual_argv: list[str]
) -> bool:
    if pid == service.get("pid"):
        return _normalized_argv(actual_argv) == _normalized_argv(service["argv"])
    if service.get("name") == "backend":
        return _backend_listener_argv_matches(
            actual_argv, service["argv"], service.get("base_executable")
        )
    return _normalized_argv(actual_argv) == _normalized_argv(service["argv"])


def _process_record(
    role: str,
    process: dict[str, Any] | None,
    argv: list[str],
    parent: dict[str, Any],
) -> dict[str, Any]:
    process = process or {}
    return {
        "role": role,
        "pid": process.get("ProcessId"),
        "parent_pid": process.get("ParentProcessId"),
        "executable": process.get("ExecutablePath"),
        "creation_time": _utc_creation(process),
        "argv": list(argv),
        "command_line": process.get("CommandLine"),
        "parent": _as_identity(parent),
    }


class SchoolAppLifecycle:
    def __init__(self, repo: Path, operations: LifecycleOperations | None = None):
        self.repo = Path(repo).resolve(strict=True)
        self.ops = operations or LifecycleOperations()

    def _workspace(self, workspace: Path) -> Path:
        return _absolute_external_workspace(Path(workspace), self.repo)

    def plan(
        self,
        workspace: Path,
        *,
        backend_port: int = DEFAULT_BACKEND_PORT,
        frontend_port: int = DEFAULT_FRONTEND_PORT,
        llm_profile: str = "default",
        frontend_mode: str,
    ) -> dict[str, Any]:
        target = self._workspace(workspace)
        _validate_ports(backend_port, frontend_port)
        _validate_options(llm_profile, frontend_mode)
        marker_path = target / "workspace.json"
        manifest_path = target / MANIFEST_NAME
        return {
            "status": "PLAN_ONLY",
            "workspace": str(target),
            "marker_present": marker_path.is_file(),
            "manifest_present": manifest_path.exists(),
            "required_revision": CURRENT_SCHOOL_REVISION,
            "database": "smhai_school_demo",
            "services": ["backend", "frontend"],
            "backend_port": backend_port,
            "frontend_port": frontend_port,
            "llm_profile": llm_profile,
            "frontend_mode": frontend_mode,
            "frontend_api_mode": "real",
            "external_modules": {
                "cat": "UNVERIFIED",
                "rag": "UNVERIFIED",
                "llm": "UNVERIFIED",
                "safety": "UNVERIFIED",
            },
            "whole_ready": False,
            "side_effects": [],
        }

    def start(
        self,
        workspace: Path,
        *,
        backend_port: int = DEFAULT_BACKEND_PORT,
        frontend_port: int = DEFAULT_FRONTEND_PORT,
        llm_profile: str = "default",
        frontend_mode: str,
        timeout: float = START_TIMEOUT_SECONDS,
        research_config: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        if not IS_WINDOWS:
            raise LifecycleError("Native school application lifecycle requires Windows")
        target = self._workspace(workspace)
        _validate_ports(backend_port, frontend_port)
        _validate_options(llm_profile, frontend_mode)
        research_config = _validated_research_config(research_config, target)
        if research_config is not None:
            _validate_research_port(research_config.port, backend_port, frontend_port)
        manifest_path = target / MANIFEST_NAME
        previous_manifest = None
        if manifest_path.exists():
            previous_manifest = _read_manifest(manifest_path)
            self._validate_manifest_scope(previous_manifest, target)
            self._validate_manifest_services(previous_manifest, target)
            if previous_manifest.get("state") != "STOPPED":
                raise LifecycleError(
                    "Existing lifecycle manifest is not a completed stop"
                )
            self._require_stopped_manifest(previous_manifest)
        marker = self._validate_prepared_database(
            target,
            backend_port=backend_port,
            frontend_port=frontend_port,
            llm_profile=llm_profile,
            research_config=research_config,
        )
        ports_to_check = (backend_port, frontend_port) + (
            (research_config.port,) if research_config is not None else ()
        )
        for port in ports_to_check:
            if not self.ops.port_is_free(port) or self.ops.listeners(port):
                raise LifecycleError(
                    "Application port is occupied; refusing to adopt an existing listener"
                )
        if previous_manifest is not None:
            self._archive_stopped_manifest(target, manifest_path, previous_manifest)
        preview_output_dir = (
            _new_preview_output_dir(target) if frontend_mode == "preview" else None
        )
        if frontend_mode == "preview":
            assert preview_output_dir is not None
            self.ops.build_frontend(self.repo, backend_port, preview_output_dir)
            preview_output_dir = _verify_preview_output_dir(
                str(preview_output_dir), target
            )

        parent_identity = self.ops.inspect_process(os.getpid())
        if not parent_identity:
            raise LifecycleError("Lifecycle parent process identity is unavailable")
        manifest: dict[str, Any] = {
            "schema_version": SCHEMA,
            "state": "STARTING",
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "workspace": str(target),
            "workspace_id": marker["workspace_id"],
            "repository": str(self.repo),
            "database": marker["database"],
            "database_port": marker["port"],
            "required_revision": CURRENT_SCHOOL_REVISION,
            "backend_port": backend_port,
            "frontend_port": frontend_port,
            "llm_profile": llm_profile,
            "frontend_mode": frontend_mode,
            "parent": _identity(parent_identity),
            "services": [],
            "external_modules": {
                "cat": "UNVERIFIED",
                "rag": "UNVERIFIED",
                "llm": "UNVERIFIED",
                "safety": "UNVERIFIED",
            },
            "whole_ready": False,
        }
        if research_config is not None:
            manifest["research_config"] = research_config.manifest_value()
            manifest["research_cat_port"] = research_config.port
        if preview_output_dir is not None:
            manifest["frontend_preview_dir"] = str(preview_output_dir)
        _atomic_write(manifest_path, manifest)
        try:
            backend_argv = self._backend_argv(
                target,
                backend_port,
                frontend_port,
                llm_profile,
                research_config=research_config,
            )
            backend = self.ops.spawn(
                backend_argv, cwd=self.repo, env=_sanitize_environment()
            )
            self._record_spawn(
                manifest,
                manifest_path,
                "backend",
                backend,
                backend_port,
                backend_argv,
                parent_identity,
            )
            backend_ready = self.ops.wait_ready(
                backend, backend_port, READY_PATHS["backend"], timeout
            )
            if backend_ready:
                backend_ready = self._confirm_service_listener(manifest["services"][-1])
            manifest["services"][-1]["readiness"] = (
                "READY" if backend_ready else "NOT_OBSERVED"
            )
            _atomic_write(manifest_path, manifest)
            if not backend_ready:
                manifest["state"] = "PARTIAL_READINESS_UNOBSERVED"
                manifest["updated_at"] = _utc_now()
                _atomic_write(manifest_path, manifest)
                return _public_status(manifest)

            if preview_output_dir is not None:
                _verify_preview_output_dir(str(preview_output_dir), target)
            frontend_argv = self._frontend_argv(
                frontend_mode, frontend_port, preview_output_dir
            )
            frontend = self.ops.spawn(
                frontend_argv,
                cwd=self.repo / "10_frontend",
                env=_frontend_environment(backend_port),
            )
            self._record_spawn(
                manifest,
                manifest_path,
                "frontend",
                frontend,
                frontend_port,
                frontend_argv,
                parent_identity,
            )
            frontend_ready = self.ops.wait_ready(
                frontend, frontend_port, READY_PATHS["frontend"], timeout
            )
            if frontend_ready:
                frontend_ready = self._confirm_service_listener(
                    manifest["services"][-1]
                )
            manifest["services"][-1]["readiness"] = (
                "READY" if frontend_ready else "NOT_OBSERVED"
            )
            manifest["state"] = (
                "RUNNING" if frontend_ready else "PARTIAL_READINESS_UNOBSERVED"
            )
            manifest["updated_at"] = _utc_now()
            _atomic_write(manifest_path, manifest)
            return _public_status(manifest)
        except Exception as exc:  # noqa: BLE001 - preserve started processes and redact details.
            manifest["state"] = "PARTIAL_FAILURE"
            manifest["failure_type"] = type(exc).__name__
            manifest["updated_at"] = _utc_now()
            _atomic_write(manifest_path, manifest)
            raise LifecycleError(
                f"School application start incomplete ({type(exc).__name__}); inspect status before recovery"
            ) from None

    def status(self, workspace: Path) -> dict[str, Any]:
        target = self._workspace(workspace)
        manifest = _read_manifest(target / MANIFEST_NAME)
        self._validate_manifest_scope(manifest, target)
        self._validate_manifest_services(manifest, target)
        research_config = _research_config_from_manifest(
            manifest,
            target,
            int(manifest["backend_port"]),
            int(manifest["frontend_port"]),
        )
        listeners: dict[str, Any] = {}
        for service in manifest.get("services", []):
            if not isinstance(service, dict):
                raise LifecycleError("Lifecycle manifest service entry is invalid")
            port = service.get("port")
            if service.get("identity_state") == "UNAVAILABLE":
                try:
                    bound = self.ops.listeners(port)
                    listener_state = (
                        "PRESENT_UNVERIFIED_OWNER" if bound else "ABSENT"
                    )
                except LifecycleError:
                    listener_state = "UNVERIFIED"
                listeners[service.get("name", "unknown")] = {
                    "port": port,
                    "owned_process": False,
                    "spawn_pid_candidate": service.get("pid"),
                    "process_chain": [],
                    "listener_pid": None,
                    "listener": listener_state,
                    "ready": False,
                }
                continue
            try:
                bound = self.ops.listeners(port)
                process_states = []
                for process_identity in service["processes"]:
                    process = self.ops.inspect_process(process_identity["pid"])
                    process_states.append(
                        (
                            process is not None,
                            process is None
                            or _matches_process(process, process_identity),
                        )
                    )
                owned = (
                    bool(process_states)
                    and any(present for present, _matches in process_states)
                    and all(matches for _present, matches in process_states)
                )
                recorded_listener = service.get("listener")
                listener_candidate = service.get("listener_candidate")
                listener_owned = (
                    not bound
                    if recorded_listener is None
                    else len(bound) == 1
                    and bound[0].get("OwningProcess") == recorded_listener.get("pid")
                    and bound[0].get("LocalAddress") == "127.0.0.1"
                    and bound[0].get("LocalPort") == port
                )
                listeners[service.get("name", "unknown")] = {
                    "port": port,
                    "owned_process": owned,
                    "process_chain": [
                        {
                            "role": process_identity.get("role"),
                            "pid": process_identity.get("pid"),
                            "state": process_identity.get(
                                "state",
                                "RUNNING" if process_states[index][0] else "EXITED",
                            ),
                        }
                        for index, process_identity in enumerate(service["processes"])
                    ],
                    "listener_pid": (
                        recorded_listener.get("pid")
                        if recorded_listener
                        else listener_candidate.get("pid")
                        if listener_candidate
                        else None
                    ),
                    "listener": "OWNED"
                    if listener_owned and bound
                    else "MISSING_OR_FOREIGN",
                    "ready": self.ops.http_ready(
                        port, READY_PATHS.get(service.get("name"), "/")
                    )
                    if owned and listener_owned and bound
                    else False,
                }
            except LifecycleError:
                listeners[service.get("name", "unknown")] = {
                    "port": port,
                    "owned_process": False,
                    "listener": "UNVERIFIED",
                    "ready": False,
                }
        try:
            self._validate_prepared_database(
                target,
                backend_port=int(manifest.get("backend_port")),
                frontend_port=int(manifest.get("frontend_port")),
                llm_profile=str(manifest.get("llm_profile")),
            )
            database_status = "VERIFIED"
        except (LifecycleError, TypeError, ValueError) as exc:
            database_status = f"UNAVAILABLE ({type(exc).__name__})"
        result = {
            "status": manifest.get("state"),
            "workspace": str(target),
            "workspace_id": manifest.get("workspace_id"),
            "manifest_revision": manifest.get("required_revision"),
            "manifest_is_current_revision": (
                manifest.get("required_revision") == CURRENT_SCHOOL_REVISION
            ),
            "frontend_artifact_scope": (
                "DEV_SERVER"
                if manifest.get("frontend_mode") != "preview"
                else "TARGET_OWNED"
                if isinstance(manifest.get("frontend_preview_dir"), str)
                else "LEGACY_SHARED_DIST"
            ),
            "services": listeners,
            "database": database_status,
            "external_modules": {
                "cat": "UNVERIFIED",
                "rag": "UNVERIFIED",
                "llm": "UNVERIFIED",
                "safety": "UNVERIFIED",
            },
            "whole_ready": False,
            "current_ready_proof": False,
            "manifest_validated": True,
        }
        if research_config is not None:
            try:
                research_listeners = self.ops.listeners(research_config.port)
                research_listener_state = (
                    "PRESENT_UNVERIFIED_OWNER" if research_listeners else "ABSENT"
                )
            except LifecycleError:
                research_listeners = None
                research_listener_state = "UNVERIFIED"
            if manifest.get("state") == "STOPPED" and research_listeners:
                result["status"] = "STOP_PARTIAL"
            result["research_cat"] = {
                "port": research_config.port,
                "owner": "backend_manager",
                "listener": research_listener_state,
                "native_pid": None,
            }
        return result

    def stop(self, workspace: Path) -> dict[str, Any]:
        if not IS_WINDOWS:
            raise LifecycleError(
                "Verified Windows process handles are required for stop"
            )
        target = self._workspace(workspace)
        manifest_path = target / MANIFEST_NAME
        manifest = _read_manifest(manifest_path)
        self._validate_manifest_scope(manifest, target)
        self._validate_manifest_services(manifest, target)
        services = manifest.get("services")
        if not isinstance(services, list):
            raise LifecycleError("Lifecycle manifest service list is invalid")
        if any(
            isinstance(service, dict)
            and service.get("identity_state") == "UNAVAILABLE"
            for service in services
        ):
            self._mark_stop_blocked(
                manifest,
                manifest_path,
                "STOP_BLOCKED_IDENTITY_UNAVAILABLE",
                failure_type="SpawnedIdentityUnavailable",
            )
            raise LifecycleError(
                "Spawned process identity is unavailable; no services were stopped"
            )
        # First validate every owner and listener before changing any process.
        live: dict[tuple[str, int], bool] = {}
        for service in services:
            port = service["port"]
            listeners = self.ops.listeners(port)
            recorded_listener = service.get("listener")
            if listeners and (
                len(listeners) != 1
                or not isinstance(recorded_listener, dict)
                or listeners[0].get("OwningProcess") != recorded_listener.get("pid")
                or listeners[0].get("LocalAddress") != "127.0.0.1"
                or listeners[0].get("LocalPort") != port
            ):
                self._mark_stop_blocked(
                    manifest, manifest_path, "STOP_BLOCKED_FOREIGN_LISTENER"
                )
                raise LifecycleError(
                    "Foreign or changed listener detected; no process was stopped"
                )
            for process_identity in service["processes"]:
                pid = process_identity["pid"]
                process = self.ops.inspect_process(pid)
                if process is None:
                    if (
                        recorded_listener
                        and recorded_listener.get("pid") == pid
                        and listeners
                    ):
                        self._mark_stop_blocked(
                            manifest, manifest_path, "STOP_BLOCKED_IDENTITY_CHANGED"
                        )
                        raise LifecycleError(
                            "Listener owner identity is unavailable; no process was stopped"
                        )
                    live[(service["name"], pid)] = False
                    continue
                if not _matches_process(process, process_identity):
                    self._mark_stop_blocked(
                        manifest, manifest_path, "STOP_BLOCKED_IDENTITY_CHANGED"
                    )
                    raise LifecycleError(
                        "Recorded process identity changed; no process was stopped"
                    )
                live[(service["name"], pid)] = True

        manifest["state"] = "STOPPING"
        manifest["updated_at"] = _utc_now()
        _atomic_write(manifest_path, manifest)
        for service in reversed(services):
            service["state"] = "STOPPING"
            for process_identity in reversed(service["processes"]):
                pid = process_identity["pid"]
                process = self.ops.inspect_process(pid)
                if not live[(service["name"], pid)]:
                    if process is not None:
                        self._mark_stop_blocked(
                            manifest,
                            manifest_path,
                            "STOP_BLOCKED_IDENTITY_CHANGED",
                        )
                        raise LifecycleError(
                            "Process appeared after stop preflight; refusing to stop"
                        )
                    if self.ops.listeners(service["port"]):
                        service["state"] = "STOP_PARTIAL"
                        self._mark_stop_blocked(
                            manifest,
                            manifest_path,
                            "STOP_BLOCKED_FOREIGN_LISTENER",
                        )
                        raise LifecycleError(
                            "Listener appeared after stop preflight; refusing to stop"
                        )
                    process_identity["state"] = "EXITED"
                    manifest["updated_at"] = _utc_now()
                    _atomic_write(manifest_path, manifest)
                    continue
                if process is None:
                    if self.ops.listeners(service["port"]):
                        service["state"] = "STOP_PARTIAL"
                        self._mark_stop_blocked(
                            manifest,
                            manifest_path,
                            "STOP_BLOCKED_FOREIGN_LISTENER",
                        )
                        raise LifecycleError(
                            "Listener remains after recorded process exit"
                        )
                    process_identity["state"] = "EXITED"
                    manifest["updated_at"] = _utc_now()
                    _atomic_write(manifest_path, manifest)
                    continue
                if not _matches_process(process, process_identity):
                    self._mark_stop_blocked(
                        manifest, manifest_path, "STOP_BLOCKED_IDENTITY_CHANGED"
                    )
                    raise LifecycleError(
                        "Recorded process identity changed; refusing to stop"
                    )
                process_identity["state"] = "STOPPING"
                manifest["updated_at"] = _utc_now()
                _atomic_write(manifest_path, manifest)
                try:
                    stopped = self.ops.terminate_verified(service, process_identity)
                except Exception as exc:  # noqa: BLE001 - preserve exact partial state, redact OS output.
                    process_identity["state"] = "STOP_UNCONFIRMED"
                    service["state"] = "STOP_PARTIAL"
                    self._mark_stop_blocked(
                        manifest,
                        manifest_path,
                        "STOP_PARTIAL",
                        failure_type=type(exc).__name__,
                    )
                    raise LifecycleError(
                        f"Verified stop incomplete ({type(exc).__name__}); inspect status"
                    ) from None
                if not stopped:
                    current = self.ops.inspect_process(pid)
                    listeners = self.ops.listeners(service["port"])
                    if current is None and not listeners:
                        process_identity["state"] = "EXITED"
                        manifest["updated_at"] = _utc_now()
                        _atomic_write(manifest_path, manifest)
                        continue
                    if current is not None and not _matches_process(
                        current, process_identity
                    ):
                        self._mark_stop_blocked(
                            manifest,
                            manifest_path,
                            "STOP_BLOCKED_IDENTITY_CHANGED",
                        )
                        raise LifecycleError(
                            "Recorded process identity changed; refusing to stop"
                        )
                    recorded_listener = service.get("listener")
                    if listeners and (
                        current is None
                        or len(listeners) != 1
                        or not isinstance(recorded_listener, dict)
                        or recorded_listener.get("pid") != pid
                        or listeners[0].get("OwningProcess") != pid
                        or listeners[0].get("LocalAddress") != "127.0.0.1"
                        or listeners[0].get("LocalPort") != service["port"]
                    ):
                        service["state"] = "STOP_PARTIAL"
                        self._mark_stop_blocked(
                            manifest,
                            manifest_path,
                            "STOP_BLOCKED_FOREIGN_LISTENER",
                            failure_type="ListenerRemains",
                        )
                        raise LifecycleError(
                            "Listener remains after unconfirmed process stop"
                        )
                    process_identity["state"] = "STOP_UNCONFIRMED"
                    service["state"] = "STOP_PARTIAL"
                    self._mark_stop_blocked(
                        manifest,
                        manifest_path,
                        "STOP_PARTIAL",
                        failure_type="ProcessExitUnconfirmed",
                    )
                    raise LifecycleError("Verified process exit was not confirmed")
                process_identity["state"] = "STOPPED"
                manifest["updated_at"] = _utc_now()
                _atomic_write(manifest_path, manifest)
            if self.ops.listeners(service["port"]):
                service["state"] = "STOP_PARTIAL"
                self._mark_stop_blocked(
                    manifest,
                    manifest_path,
                    "STOP_PARTIAL",
                    failure_type="ListenerRemains",
                )
                raise LifecycleError("Listener remains after verified process stop")
            service["state"] = "STOPPED"
        research_config = _research_config_from_manifest(
            manifest,
            target,
            int(manifest["backend_port"]),
            int(manifest["frontend_port"]),
        )
        if research_config is not None:
            try:
                research_listeners = self.ops.listeners(research_config.port)
            except LifecycleError:
                manifest["state"] = "STOP_PARTIAL"
                manifest["failure_code"] = "RESEARCH_CAT_LISTENER_UNVERIFIED"
                manifest["updated_at"] = _utc_now()
                _atomic_write(manifest_path, manifest)
                raise LifecycleError(
                    "Research CAT listener state is unverified; stop is partial"
                ) from None
            if research_listeners:
                manifest["state"] = "STOP_PARTIAL"
                manifest["failure_code"] = "RESEARCH_CAT_LISTENER_REMAINS"
                manifest["updated_at"] = _utc_now()
                _atomic_write(manifest_path, manifest)
                raise LifecycleError(
                    "Research CAT listener remains after Backend stop; it is not lifecycle-owned"
                )
        manifest["state"] = "STOPPED"
        manifest["updated_at"] = _utc_now()
        _atomic_write(manifest_path, manifest)
        result = _public_status(manifest)
        if research_config is not None:
            result["research_cat"] = {
                "port": research_config.port,
                "owner": "backend_manager",
                "listener": "ABSENT_AFTER_BACKEND_STOP",
                "native_pid": None,
            }
        return result

    def _mark_stop_blocked(
        self,
        manifest: dict[str, Any],
        path: Path,
        state: str,
        *,
        failure_type: str | None = None,
    ) -> None:
        manifest["state"] = state
        if failure_type:
            manifest["failure_type"] = failure_type
        manifest["updated_at"] = _utc_now()
        _atomic_write(path, manifest)

    def _require_stopped_manifest(self, manifest: dict[str, Any]) -> None:
        for service in manifest["services"]:
            if self.ops.listeners(service["port"]):
                raise LifecycleError(
                    "Stopped manifest still has an application listener"
                )
            for process_identity in service["processes"]:
                if self.ops.inspect_process(process_identity["pid"]) is not None:
                    raise LifecycleError(
                        "Stopped manifest still has a live or reused process id"
                    )
        research_config = _research_config_from_manifest(
            manifest,
            Path(manifest["workspace"]),
            int(manifest["backend_port"]),
            int(manifest["frontend_port"]),
        )
        if research_config is not None and self.ops.listeners(research_config.port):
            raise LifecycleError(
                "Stopped manifest still has a Backend-managed research CAT listener"
            )

    def _archive_stopped_manifest(
        self, target: Path, manifest_path: Path, manifest: dict[str, Any]
    ) -> None:
        stamp = "".join(
            char for char in str(manifest.get("updated_at", "")) if char.isdigit()
        )
        archive = target / f"school-app-lifecycle.stopped-{stamp}.json"
        if archive.exists():
            raise LifecycleError(
                "Lifecycle archive already exists; refusing to overwrite"
            )
        _reject_reparse_path(archive.parent)
        try:
            os.rename(manifest_path, archive)
        except OSError:
            raise LifecycleError(
                "Stopped lifecycle manifest could not be archived"
            ) from None

    def _validate_prepared_database(
        self,
        target: Path,
        *,
        backend_port: int,
        frontend_port: int,
        llm_profile: str,
        research_config: ResearchProcessConfig | None = None,
    ) -> dict[str, Any]:
        try:
            from prepare_school_runtime import validate_marker, verify_process

            marker = validate_marker(target, self.repo)
            verify_process(marker)
        except Exception as exc:  # noqa: BLE001 - redact SQL/path-bearing diagnostics.
            raise LifecycleError(
                f"Prepared workspace validation failed ({type(exc).__name__})"
            ) from None
        ready_path = target / "runtime-ready.json"
        try:
            _reject_reparse_path(ready_path)
            ready = json.loads(ready_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise LifecycleError("Verified runtime-ready marker is required") from None
        if (
            ready.get("workspace_id") != marker.get("workspace_id")
            or ready.get("state") != "VERIFIED"
            or ready.get("database") != marker.get("database")
            or ready.get("port") != marker.get("port")
        ):
            raise LifecycleError(
                "Verified runtime-ready marker does not match workspace"
            )
        # Existing Backend preflight performs the sealed-credential grant/revision check.
        python, _base_python = _backend_python_paths(self.repo)
        argv = [
            str(python),
            str(self.repo / "13_deployment" / "school_backend.py"),
            "--workspace",
            str(target),
            "--port",
            str(backend_port),
            "--frontend-port",
            str(frontend_port),
            "--llm-profile",
            llm_profile,
            "--preflight-only",
        ]
        if research_config is not None:
            argv.extend(research_config.cli_arguments())
        try:
            result = subprocess.run(
                _safe_argv(argv),
                cwd=self.repo,
                env=_sanitize_environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                timeout=45,
                check=False,
                shell=False,
            )
            decoded = json.loads(result.stdout) if result.stdout else {}
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            raise LifecycleError(
                "Backend database preflight could not be completed"
            ) from None
        if (
            result.returncode != 0
            or decoded.get("preflight") != "PASS"
            or decoded.get("database") != "smhai_school_demo"
            or decoded.get("port") != marker.get("port")
        ):
            raise LifecycleError(
                "Backend database grants or current schema revision did not pass preflight"
            )
        return marker

    def _backend_argv(
        self,
        target: Path,
        backend_port: int,
        frontend_port: int,
        profile: str,
        *,
        research_config: ResearchProcessConfig | None = None,
    ) -> list[str]:
        python, _base_python = _backend_python_paths(self.repo)
        argv = [
                str(python),
                str(self.repo / "13_deployment" / "school_backend.py"),
                "--workspace",
                str(target),
                "--port",
                str(backend_port),
                "--frontend-port",
                str(frontend_port),
                "--llm-profile",
                profile,
            ]
        if research_config is not None:
            argv.extend(research_config.cli_arguments())
        return _safe_argv(argv)

    def _frontend_argv(
        self, mode: str, port: int, preview_output_dir: Path | None = None
    ) -> list[str]:
        node = shutil.which("node")
        vite = self.repo / "10_frontend" / "node_modules" / "vite" / "bin" / "vite.js"
        if not node or not vite.is_file():
            raise LifecycleError("Existing Node and Vite installation are required")
        command = "preview" if mode == "preview" else "--host"
        if mode == "preview":
            if preview_output_dir is None:
                return _safe_argv(
                    [
                        node,
                        str(vite),
                        command,
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--strictPort",
                    ]
                )
            return _safe_argv(
                [
                    node,
                    str(vite),
                    command,
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--strictPort",
                    "--outDir",
                    str(preview_output_dir),
                ]
            )
        if preview_output_dir is not None:
            raise LifecycleError("Dev frontend cannot use a preview output directory")
        return _safe_argv(
            [
                node,
                str(vite),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--strictPort",
            ]
        )

    def _record_spawn(
        self,
        manifest: dict[str, Any],
        manifest_path: Path,
        name: str,
        process: Any,
        port: int,
        argv: list[str],
        parent_identity: dict[str, Any],
    ) -> None:
        identity = self.ops.inspect_process(process.pid)
        identity_complete = bool(
            isinstance(identity, dict)
            and type(identity.get("ProcessId")) is int
            and identity.get("ProcessId") == process.pid
            and identity.get("ParentProcessId")
            == parent_identity.get("ProcessId")
            and isinstance(identity.get("ExecutablePath"), str)
            and Path(identity["ExecutablePath"]).is_absolute()
            and _utc_creation(identity) is not None
            and _same_command_line(identity.get("CommandLine"), argv)
        )
        if not identity_complete:
            entry = {
                "name": name,
                "port": port,
                "pid": int(process.pid),
                "executable": argv[0],
                "creation_time": None,
                "argv": list(argv),
                "command_line": None,
                "parent": _identity(parent_identity),
                "processes": [],
                "listener": None,
                "listener_candidate": None,
                "base_executable": (
                    str(_backend_python_paths(self.repo)[1])
                    if name == "backend"
                    else None
                ),
                "state": "IDENTITY_UNAVAILABLE",
                "readiness": "NOT_OBSERVED",
                "identity_state": "UNAVAILABLE",
            }
            manifest["services"].append(entry)
            manifest["updated_at"] = _utc_now()
            _atomic_write(manifest_path, manifest)
            raise LifecycleError(
                "Spawned process identity unavailable; preserving an unverified spawn record"
            )
        launcher = _process_record("launcher", identity, argv, parent_identity)
        base_executable = (
            str(_backend_python_paths(self.repo)[1]) if name == "backend" else None
        )
        entry = {
            "name": name,
            "port": port,
            "pid": int(process.pid),
            "executable": identity.get("ExecutablePath") if identity else argv[0],
            "creation_time": _utc_creation(identity) if identity else None,
            "argv": list(argv),
            "command_line": identity.get("CommandLine") if identity else None,
            "parent": _identity(parent_identity),
            "processes": [launcher],
            "listener": None,
            "listener_candidate": None,
            "base_executable": base_executable,
            "state": "CREATED",
            "readiness": "NOT_OBSERVED",
        }
        manifest["services"].append(entry)
        manifest["updated_at"] = _utc_now()
        _atomic_write(manifest_path, manifest)

    def _confirm_service_listener(self, service: dict[str, Any]) -> bool:
        listeners = self.ops.listeners(service["port"])
        if len(listeners) != 1:
            return False
        listener = listeners[0]
        listener_pid = listener.get("OwningProcess")
        if (
            type(listener_pid) is not int
            or listener.get("LocalAddress") != "127.0.0.1"
            or listener.get("LocalPort") != service["port"]
        ):
            return False
        process = self.ops.inspect_process(listener_pid)
        launcher = service["processes"][0]
        launcher_process = self.ops.inspect_process(service["pid"])
        if not _matches_process(launcher_process, launcher):
            return False
        if listener_pid == service["pid"]:
            process = launcher_process
            expected_parent = launcher.get("parent_pid")
        else:
            expected_parent = service["pid"]
        actual_argv = (
            _command_line_argv(process.get("CommandLine"))
            if isinstance(process, dict)
            else None
        )
        if (
            not isinstance(process, dict)
            or process.get("ParentProcessId") != expected_parent
            or _utc_creation(process) is None
            or not isinstance(process.get("ExecutablePath"), str)
            or actual_argv is None
        ):
            return False
        listener_parent = (
            service["parent"] if listener_pid == service["pid"] else launcher
        )
        process_identity = _process_record(
            "listener", process, actual_argv, listener_parent
        )
        candidate = {
            "pid": listener_pid,
            "local_address": listener["LocalAddress"],
            "local_port": listener["LocalPort"],
            "executable": process["ExecutablePath"],
            "creation_time": _utc_creation(process),
            "parent_pid": process.get("ParentProcessId"),
            "argv": actual_argv,
            "command_line": process["CommandLine"],
            "parent": process_identity["parent"],
        }
        service["listener_candidate"] = candidate
        expected_listener_executable = (
            service["executable"]
            if listener_pid == service["pid"]
            else service.get("base_executable")
            if service["name"] == "backend"
            else shutil.which("node")
        )
        candidate["identity_verified"] = bool(
            expected_listener_executable
            and _path_key(candidate["executable"])
            == _path_key(expected_listener_executable)
            and _listener_argv_matches(service, listener_pid, actual_argv)
        )
        if not candidate["identity_verified"]:
            return False
        if listener_pid != service["pid"]:
            service["processes"].append(process_identity)
        service["listener"] = {
            "pid": listener_pid,
            "local_address": listener["LocalAddress"],
            "local_port": listener["LocalPort"],
            "executable": process["ExecutablePath"],
            "creation_time": _utc_creation(process),
            "parent_pid": process.get("ParentProcessId"),
            "argv": actual_argv,
            "command_line": process["CommandLine"],
        }
        return True

    def _validate_manifest_scope(self, manifest: dict[str, Any], target: Path) -> None:
        workspace_value = manifest.get("workspace")
        repository_value = manifest.get("repository")
        if (
            not isinstance(workspace_value, str)
            or not Path(workspace_value).is_absolute()
            or not isinstance(repository_value, str)
            or not Path(repository_value).is_absolute()
            or _path_key(workspace_value) != _path_key(target)
            or _path_key(repository_value) != _path_key(self.repo)
            or not isinstance(manifest.get("workspace_id"), str)
            or manifest.get("database") != "smhai_school_demo"
            or manifest.get("required_revision") not in SUPPORTED_SNAPSHOT_REVISIONS
            or manifest.get("state")
            not in {
                "STARTING",
                "RUNNING",
                "PARTIAL_READINESS_UNOBSERVED",
                "PARTIAL_FAILURE",
                "STOP_BLOCKED_FOREIGN_LISTENER",
                "STOP_BLOCKED_IDENTITY_CHANGED",
                "STOP_BLOCKED_IDENTITY_UNAVAILABLE",
                "STOP_INCOMPLETE",
                "STOPPING",
                "STOP_PARTIAL",
                "STOPPED",
            }
        ):
            raise LifecycleError(
                "Lifecycle manifest is stale or belongs to another workspace"
            )
        try:
            _reject_reparse_path(target / "workspace.json")
            marker = json.loads((target / "workspace.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise LifecycleError("Prepared workspace marker is unavailable") from None
        if marker.get("workspace_id") != manifest.get("workspace_id"):
            raise LifecycleError("Lifecycle manifest workspace identity changed")

    def _validate_manifest_services(
        self, manifest: dict[str, Any], target: Path
    ) -> None:
        if any(
            key.startswith("research_")
            and key not in {"research_config", "research_cat_port"}
            for key in manifest
        ):
            raise LifecycleError("Lifecycle manifest has unknown research fields")
        services = manifest.get("services")
        if not isinstance(services, list) or len(services) > 2:
            raise LifecycleError("Lifecycle manifest service list is invalid")
        _validate_ports(manifest.get("backend_port"), manifest.get("frontend_port"))
        _validate_options(manifest.get("llm_profile"), manifest.get("frontend_mode"))
        research_config = _research_config_from_manifest(
            manifest,
            target,
            manifest["backend_port"],
            manifest["frontend_port"],
        )
        expected_ports = {
            "backend": manifest["backend_port"],
            "frontend": manifest["frontend_port"],
        }
        seen: set[str] = set()
        for service in services:
            if not isinstance(service, dict):
                raise LifecycleError("Lifecycle manifest service entry is invalid")
            name = service.get("name")
            if (
                name not in expected_ports
                or name in seen
                or service.get("port") != expected_ports[name]
                or type(service.get("pid")) is not int
                or service["pid"] <= 0
                or not isinstance(service.get("argv"), list)
                or not all(isinstance(item, str) for item in service["argv"])
            ):
                raise LifecycleError(
                    "Lifecycle manifest service identity is incomplete"
                )
            if name == "backend":
                expected_launcher, expected_base = _backend_python_paths(self.repo)
                expected_argv = [
                    str(expected_launcher),
                    str(self.repo / "13_deployment" / "school_backend.py"),
                    "--workspace",
                    str(target),
                    "--port",
                    str(manifest["backend_port"]),
                    "--frontend-port",
                    str(manifest["frontend_port"]),
                    "--llm-profile",
                    manifest["llm_profile"],
                ]
                if research_config is not None:
                    expected_argv.extend(research_config.cli_arguments())
                expected_executable = expected_argv[0]
                if not isinstance(service.get("base_executable"), str) or _path_key(
                    service["base_executable"]
                ) != _path_key(expected_base):
                    raise LifecycleError(
                        "Lifecycle Backend base Python differs from the verified venv"
                    )
            else:
                argv = service["argv"]
                expected_vite = str(
                    self.repo
                    / "10_frontend"
                    / "node_modules"
                    / "vite"
                    / "bin"
                    / "vite.js"
                )
                expected_node = shutil.which("node")
                expected_mode = (
                    "preview" if manifest["frontend_mode"] == "preview" else None
                )
                if not expected_node:
                    raise LifecycleError("Existing Node executable is unavailable")
                has_expected_vite = len(argv) > 1 and _path_key(argv[1]) == _path_key(
                    expected_vite
                )
                preview_output_dir = None
                has_preview_dir = "frontend_preview_dir" in manifest
                if expected_mode and has_preview_dir:
                    preview_output_dir = _validated_preview_output_dir(
                        manifest.get("frontend_preview_dir"), target
                    )
                elif not expected_mode and has_preview_dir:
                    raise LifecycleError(
                        "Dev frontend manifest has an unexpected preview artifact"
                    )
                expected_argv = self._frontend_argv(
                    manifest["frontend_mode"],
                    manifest["frontend_port"],
                    preview_output_dir,
                )
                expected_executable = expected_node
                if service.get("base_executable") is not None:
                    raise LifecycleError(
                        "Frontend manifest has an unexpected base runtime"
                    )
                if not has_expected_vite:
                    raise LifecycleError(
                        "Lifecycle Frontend command is outside the approved Vite entrypoint"
                    )
            if _normalized_argv(service["argv"]) != _normalized_argv(
                expected_argv
            ):
                raise LifecycleError("Lifecycle manifest command identity changed")
            if service.get("identity_state") == "UNAVAILABLE":
                if (
                    set(service)
                    != {
                        "name",
                        "port",
                        "pid",
                        "executable",
                        "creation_time",
                        "argv",
                        "command_line",
                        "parent",
                        "processes",
                        "listener",
                        "listener_candidate",
                        "base_executable",
                        "state",
                        "readiness",
                        "identity_state",
                    }
                    or not isinstance(service.get("executable"), str)
                    or _path_key(service["executable"])
                    != _path_key(expected_executable)
                    or service.get("creation_time") is not None
                    or service.get("command_line") is not None
                    or not isinstance(service.get("parent"), dict)
                    or service.get("processes") != []
                    or service.get("listener") is not None
                    or service.get("listener_candidate") is not None
                    or service.get("state") != "IDENTITY_UNAVAILABLE"
                    or service.get("readiness") != "NOT_OBSERVED"
                    or service.get("base_executable")
                    != (str(expected_base) if name == "backend" else None)
                ):
                    raise LifecycleError(
                        "Lifecycle unverified spawn record is invalid"
                    )
                seen.add(name)
                continue
            if "identity_state" in service:
                raise LifecycleError("Lifecycle service identity state is invalid")
            if (
                not isinstance(service.get("executable"), str)
                or not Path(service["executable"]).is_absolute()
                or _path_key(service["executable"])
                != _path_key(expected_executable)
                or not isinstance(service.get("creation_time"), str)
                or not _utc_timestamp(service["creation_time"])
                or not isinstance(service.get("parent"), dict)
            ):
                raise LifecycleError(
                    "Lifecycle manifest service identity is incomplete"
                )
            if not _same_command_line(service.get("command_line"), service["argv"]):
                raise LifecycleError("Lifecycle launcher command line changed")
            processes = service.get("processes")
            if not isinstance(processes, list) or len(processes) not in {1, 2}:
                raise LifecycleError("Lifecycle process chain is invalid")
            launcher = processes[0]
            if (
                not isinstance(launcher, dict)
                or launcher.get("role") != "launcher"
                or launcher.get("pid") != service["pid"]
                or launcher.get("parent_pid") != service["parent"].get("pid")
                or _path_key(str(launcher.get("executable", "")))
                != _path_key(service["executable"])
                or launcher.get("creation_time") != service["creation_time"]
                or _normalized_argv(launcher.get("argv", []))
                != _normalized_argv(service["argv"])
                or launcher.get("command_line") != service["command_line"]
                or not _same_identity(launcher.get("parent"), service["parent"])
            ):
                raise LifecycleError("Lifecycle launcher identity chain changed")
            recorded_listener = service.get("listener")
            candidate = service.get("listener_candidate")
            if candidate is not None:
                candidate_argv = _command_line_argv(candidate.get("command_line"))
                candidate_argv_matches = bool(
                    candidate_argv is not None
                    and isinstance(candidate.get("argv"), list)
                    and _normalized_argv(candidate["argv"])
                    == _normalized_argv(candidate_argv)
                    and _listener_argv_matches(
                        service, candidate.get("pid"), candidate_argv
                    )
                )
                expected_candidate_executable = (
                    service["executable"]
                    if candidate.get("pid") == service["pid"]
                    else service.get("base_executable")
                    if service["name"] == "backend"
                    else shutil.which("node")
                )
                candidate_verified = bool(
                    expected_candidate_executable
                    and isinstance(candidate.get("executable"), str)
                    and Path(candidate["executable"]).is_absolute()
                    and _path_key(candidate["executable"])
                    == _path_key(expected_candidate_executable)
                    and candidate_argv_matches
                )
                if (
                    type(candidate.get("pid")) is not int
                    or candidate.get("identity_verified") is not candidate_verified
                    or candidate.get("local_address") != "127.0.0.1"
                    or candidate.get("local_port") != service["port"]
                    or candidate.get("parent_pid")
                    != (
                        service["parent"].get("pid")
                        if candidate["pid"] == service["pid"]
                        else service["pid"]
                    )
                    or candidate_argv is None
                    or not isinstance(candidate.get("creation_time"), str)
                    or not _utc_timestamp(candidate["creation_time"])
                    or not _same_identity(
                        candidate.get("parent"),
                        service["parent"]
                        if candidate["pid"] == service["pid"]
                        else _identity_from_process(launcher),
                    )
                    or (not candidate_verified and recorded_listener is not None)
                    or (candidate_verified and recorded_listener is None)
                ):
                    raise LifecycleError(
                        "Lifecycle observed listener candidate is invalid"
                    )
            if recorded_listener is None:
                if len(processes) != 1:
                    raise LifecycleError(
                        "Unobserved listener has extra process records"
                    )
            else:
                if (
                    not isinstance(recorded_listener, dict)
                    or recorded_listener.get("local_address") != "127.0.0.1"
                    or recorded_listener.get("local_port") != service["port"]
                    or type(recorded_listener.get("pid")) is not int
                    or not isinstance(recorded_listener.get("executable"), str)
                    or not Path(recorded_listener["executable"]).is_absolute()
                    or not isinstance(recorded_listener.get("creation_time"), str)
                    or not _utc_timestamp(recorded_listener["creation_time"])
                    or not isinstance(recorded_listener.get("argv"), list)
                    or not all(
                        isinstance(item, str) for item in recorded_listener["argv"]
                    )
                    or recorded_listener.get("parent_pid")
                    not in {service["pid"], service["parent"].get("pid")}
                    or not _same_command_line(
                        recorded_listener.get("command_line"),
                        recorded_listener["argv"],
                    )
                    or not _listener_argv_matches(
                        service,
                        recorded_listener.get("pid"),
                        recorded_listener["argv"],
                    )
                ):
                    raise LifecycleError("Lifecycle listener identity is invalid")
                if recorded_listener["pid"] == service["pid"]:
                    if (
                        len(processes) != 1
                        or recorded_listener["parent_pid"]
                        != service["parent"].get("pid")
                        or _path_key(recorded_listener["executable"])
                        != _path_key(service["executable"])
                        or recorded_listener["creation_time"]
                        != service["creation_time"]
                    ):
                        raise LifecycleError(
                            "Direct listener identity does not match launcher"
                        )
                else:
                    child = processes[1] if len(processes) == 2 else None
                    if (
                        not isinstance(child, dict)
                        or child.get("role") != "listener"
                        or child.get("pid") != recorded_listener["pid"]
                        or child.get("parent_pid") != service["pid"]
                        or child.get("executable") != recorded_listener["executable"]
                        or child.get("creation_time")
                        != recorded_listener["creation_time"]
                        or _normalized_argv(child.get("argv", []))
                        != _normalized_argv(recorded_listener["argv"])
                        or child.get("command_line")
                        != recorded_listener["command_line"]
                        or not _same_identity(
                            child.get("parent"), _identity_from_process(launcher)
                        )
                        or service["name"] != "backend"
                        or _path_key(child["executable"])
                        != _path_key(service["base_executable"])
                    ):
                        raise LifecycleError("Backend listener child chain is invalid")
            seen.add(name)


def _identity(process: dict[str, Any]) -> dict[str, Any]:
    return {
        "pid": process.get("ProcessId"),
        "parent_pid": process.get("ParentProcessId"),
        "executable": process.get("ExecutablePath"),
        "creation_time": _utc_creation(process),
        "argv": process.get("CommandLine"),
    }


def _identity_from_process(process: dict[str, Any]) -> dict[str, Any]:
    return {
        "pid": process.get("pid"),
        "parent_pid": process.get("parent_pid"),
        "executable": process.get("executable"),
        "creation_time": process.get("creation_time"),
        "argv": process.get("command_line", process.get("argv")),
    }


def _as_identity(process: dict[str, Any]) -> dict[str, Any]:
    if "ProcessId" in process:
        return _identity(process)
    return _identity_from_process(process)


def _same_identity(left: object, right: object) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    return (
        left.get("pid") == right.get("pid")
        and left.get("parent_pid") == right.get("parent_pid")
        and left.get("creation_time") == right.get("creation_time")
        and left.get("argv") == right.get("argv")
        and isinstance(left.get("executable"), str)
        and isinstance(right.get("executable"), str)
        and _path_key(left["executable"]) == _path_key(right["executable"])
    )


def _frontend_environment(backend_port: int) -> dict[str, str]:
    environment = _sanitize_environment()
    environment.update(
        {
            "VITE_API_MODE": "real",
            "VITE_API_BASE_URL": f"http://127.0.0.1:{backend_port}",
        }
    )
    return environment


def _validate_ports(backend_port: int, frontend_port: int) -> None:
    if (
        type(backend_port) is not int
        or type(frontend_port) is not int
        or not 1024 <= backend_port <= 65535
        or not 1024 <= frontend_port <= 65535
        or backend_port == frontend_port
        or backend_port in {8160, 8170, 8180, 8190}
        or frontend_port in {8160, 8170, 8180, 8190}
    ):
        raise LifecycleError(
            "Distinct application ports in 1024..65535, separate from module ports, are required"
        )


def _validate_research_port(port: int, backend_port: int, frontend_port: int) -> None:
    if (
        type(port) is not int
        or not 1024 <= port <= 65535
        or port in {backend_port, frontend_port, 8160, 8170, 8180, 8190}
    ):
        raise LifecycleError(
            "Research CAT listener port must be distinct from application and module ports"
        )


def _validate_options(profile: str, frontend_mode: str) -> None:
    if profile not in LLM_PROFILES or frontend_mode not in {"dev", "preview"}:
        raise LifecycleError(
            "Explicit supported LLM profile and frontend mode are required"
        )


def _public_status(manifest: dict[str, Any]) -> dict[str, Any]:
    result = {
        "status": manifest.get("state"),
        "workspace_id": manifest.get("workspace_id"),
        "backend_port": manifest.get("backend_port"),
        "frontend_port": manifest.get("frontend_port"),
        "llm_profile": manifest.get("llm_profile"),
        "frontend_mode": manifest.get("frontend_mode"),
        "services": [
            {
                **{
                    key: service.get(key)
                    for key in ("name", "port", "pid", "state", "readiness")
                },
                "listener_pid": (service.get("listener") or {}).get("pid"),
                "listener_candidate_pid": (service.get("listener_candidate") or {}).get(
                    "pid"
                ),
                "process_chain": [
                    {
                        "role": identity.get("role"),
                        "pid": identity.get("pid"),
                        "state": identity.get("state", "RUNNING"),
                    }
                    for identity in service.get("processes", [])
                ],
            }
            for service in manifest.get("services", [])
            if isinstance(service, dict)
        ],
        "external_modules": {
            "cat": "UNVERIFIED",
            "rag": "UNVERIFIED",
            "llm": "UNVERIFIED",
            "safety": "UNVERIFIED",
        },
        "whole_ready": False,
        "manifest": MANIFEST_NAME,
    }
    if "research_config" in manifest and "research_cat_port" in manifest:
        result["research_cat"] = {
            "port": manifest["research_cat_port"],
            "owner": "backend_manager",
            "listener": "NOT_INDEPENDENTLY_OBSERVED",
            "native_pid": None,
        }
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="Read-only command and requirement plan")
    status = commands.add_parser("status", help="Inspect owned processes and readiness")
    start = commands.add_parser(
        "start", help="Start Backend and Frontend for a prepared workspace"
    )
    stop = commands.add_parser(
        "stop", help="Stop only verified Backend and Frontend processes"
    )
    for command in (plan, status, start, stop):
        command.add_argument("--workspace", type=Path, required=True)
    for command in (plan, start):
        command.add_argument("--backend-port", type=int, default=DEFAULT_BACKEND_PORT)
        command.add_argument("--frontend-port", type=int, default=DEFAULT_FRONTEND_PORT)
        command.add_argument("--llm-profile", choices=LLM_PROFILES, default="default")
        command.add_argument(
            "--frontend-mode", choices=("dev", "preview"), required=True
        )
    start.add_argument("--timeout", type=float, default=START_TIMEOUT_SECONDS)
    for name in RESEARCH_CONFIG_ARGUMENTS:
        value_type = (
            str
            if name.endswith("_sha256")
            else Path
        )
        start.add_argument(RESEARCH_CONFIG_FLAGS[name], dest=name, type=value_type)
    for name in RESEARCH_STUDY_USE_ARGUMENTS:
        if name == "research_source_rights_verified":
            start.add_argument(RESEARCH_STUDY_USE_FLAGS[name], dest=name, action="store_true")
        else:
            value_type = Path if name == "research_study_use_file" else str
            start.add_argument(RESEARCH_STUDY_USE_FLAGS[name], dest=name, type=value_type)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        lifecycle = SchoolAppLifecycle(Path(__file__).resolve().parents[1])
        if args.command == "plan":
            result = lifecycle.plan(
                args.workspace,
                backend_port=args.backend_port,
                frontend_port=args.frontend_port,
                llm_profile=args.llm_profile,
                frontend_mode=args.frontend_mode,
            )
        elif args.command == "start":
            supplied_research = {
                name: getattr(args, name, None) for name in RESEARCH_CONFIG_ARGUMENTS
            }
            supplied_research.update(
                {
                    name: getattr(
                        args,
                        name,
                        False if name == "research_source_rights_verified" else None,
                    )
                    for name in RESEARCH_STUDY_USE_ARGUMENTS
                }
            )
            research_config = (
                supplied_research
                if any(
                    value is not None
                    and (name != "research_source_rights_verified" or value is True)
                    for name, value in supplied_research.items()
                )
                else None
            )
            result = lifecycle.start(
                args.workspace,
                backend_port=args.backend_port,
                frontend_port=args.frontend_port,
                llm_profile=args.llm_profile,
                frontend_mode=args.frontend_mode,
                timeout=args.timeout,
                research_config=research_config,
            )
        elif args.command == "status":
            result = lifecycle.status(args.workspace)
        else:
            result = lifecycle.stop(args.workspace)
        print(json.dumps(result, sort_keys=True))
        return (
            0
            if result.get("status")
            not in {
                "PARTIAL_READINESS_UNOBSERVED",
                "PARTIAL_FAILURE",
                "STOP_PARTIAL",
            }
            else 2
        )
    except Exception as exc:  # noqa: BLE001 - type-only diagnostics avoid secrets and child output.
        print(
            json.dumps(
                {"status": "BLOCKED", "error_type": type(exc).__name__}, sort_keys=True
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
