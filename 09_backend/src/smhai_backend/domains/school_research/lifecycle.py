"""Lazy Backend lifecycle wiring for the isolated research CAT child process."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .managed import build_managed_research_process
from .probes import ResearchCATReadinessProbe, WindowsListenerOwnerProbe
from .process import ResearchCATProcessManager

_SERVICE_SCHEMA = "psynova.research-cat-service.v1"
_SERVICE_FIELDS = frozenset(
    {
        "schema",
        "school_scope",
        "resource_root",
        "listener",
        "signing",
        "profiles",
        "bindings",
    }
)
_LISTENER_FIELDS = frozenset({"host", "port"})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_SERVICE_CONFIG_BYTES = 1024 * 1024
_MAX_BASE_PROBE_OUTPUT_BYTES = 16 * 1024
_BASE_PROBE_TIMEOUT_SECONDS = 8.0
_REPARSE_POINT = 0x400

_BASE_PROBE_CODE = r"""
import importlib.util, json, os, sys
expected = os.path.normcase(os.path.realpath(sys.argv[1]))
dependency = os.path.realpath(sys.argv[2])
def within(candidate, root):
    try:
        return os.path.commonpath((os.path.normcase(os.path.realpath(candidate)),
                                   os.path.normcase(os.path.realpath(root)))) == \
               os.path.normcase(os.path.realpath(root))
    except (OSError, ValueError):
        return False
def origin(name):
    spec = importlib.util.find_spec(name)
    return None if spec is None else spec.origin
numpy_origin = origin("numpy")
fastapi_origin = origin("fastapi")
paths = [os.path.realpath(value) if value else "" for value in sys.path]
report = {
    "executable": os.path.normcase(os.path.realpath(sys.executable)),
    "version": [sys.version_info.major, sys.version_info.minor],
    "no_site": bool(sys.flags.no_site),
    "paths": paths,
    "numpy_origin": numpy_origin,
    "fastapi_origin": fastapi_origin,
    "origins_from_dependency": bool(numpy_origin and fastapi_origin and
        within(numpy_origin, dependency) and within(fastapi_origin, dependency)),
    "expected_executable_matches": os.path.normcase(os.path.realpath(sys.executable)) == expected,
}
print(json.dumps(report, separators=(",", ":")))
"""


class ResearchCATLifecycleError(RuntimeError):
    """Stable lifecycle-construction failure without config or secret detail."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
            code = "research_lifecycle_invalid"
        self.code = code
        super().__init__(code)


def build_school_research_process_factory(
    settings: Any,
    persistence: Any,
) -> Callable[[], ResearchCATProcessManager] | None:
    """Return a lazy one-shot manager factory, or ``None`` for the inert lane.

    The factory must be invoked only after the caller has started the exact
    school MySQL persistence adapter. It creates no manager and reads no keys
    until invocation. It never starts the returned manager.
    """

    if getattr(settings, "school_research_managed_enabled", False) is not True:
        return None
    _validate_enabled_settings(settings, persistence)

    try:
        runtime_file = _absolute_setting(settings.school_research_runtime_file)
        runtime_sha256 = _setting_sha(settings.school_research_runtime_sha256)
        service_file = _absolute_setting(settings.school_research_service_file)
        service_sha256 = _setting_sha(settings.school_research_service_sha256)
        base_url = settings.school_research_base_url
        cat_python = _absolute_setting(settings.school_research_cat_python)
        cat_source = _absolute_setting(settings.school_research_cat_source)
        cat_dependencies = _absolute_setting(settings.school_research_cat_dependencies)
    except ResearchCATLifecycleError:
        raise
    except Exception:
        raise ResearchCATLifecycleError("managed_settings_invalid") from None
    if type(base_url) is not str or not base_url:
        raise ResearchCATLifecycleError("managed_settings_invalid")

    invocation_lock = threading.Lock()
    manager_created = False

    def create_manager() -> ResearchCATProcessManager:
        nonlocal manager_created
        with invocation_lock:
            if manager_created:
                raise ResearchCATLifecycleError("manager_factory_already_used")
            if getattr(persistence, "_started", False) is not True:
                raise ResearchCATLifecycleError("persistence_not_started")

            port = _read_pinned_service_port(service_file, service_sha256)
            expected_url = f"http://127.0.0.1:{port}"
            if base_url != expected_url:
                raise ResearchCATLifecycleError("base_url_service_mismatch")

            def base_executable_probe(executable: Path) -> bool:
                return _probe_cat_base_executable(
                    executable,
                    cat_source=cat_source,
                    cat_dependencies=cat_dependencies,
                )

            try:
                key_provider = persistence.protection.key_provider
            except Exception:
                raise ResearchCATLifecycleError("retained_key_provider_unavailable") from None
            if key_provider is None:
                raise ResearchCATLifecycleError("retained_key_provider_unavailable")

            try:
                manager = build_managed_research_process(
                    runtime_config_file=runtime_file,
                    expected_runtime_config_sha256=runtime_sha256,
                    service_config_file=service_file,
                    expected_service_config_sha256=service_sha256,
                    cat_source=cat_source,
                    cat_dependency_path=cat_dependencies,
                    base_executable=cat_python,
                    base_executable_probe=base_executable_probe,
                    retained_key_provider=key_provider,
                    readiness_probe=ResearchCATReadinessProbe(),
                    listener_owner_probe=WindowsListenerOwnerProbe(expected_executable=cat_python),
                )
            except Exception:
                raise ResearchCATLifecycleError("managed_process_construction_failed") from None
            manager_created = True
            return manager

    return create_manager


def _validate_enabled_settings(settings: Any, persistence: Any) -> None:
    if (
        settings is None
        or getattr(settings, "school_research_enabled", False) is not True
        or getattr(settings, "environment", None) == "production"
        or getattr(settings, "identity_profile", None) != "school_tenant"
        or getattr(settings, "persistence_mode", None) != "mysql"
        or persistence is None
        or getattr(persistence, "identity_profile", None) != "school_tenant"
    ):
        raise ResearchCATLifecycleError("managed_research_scope_invalid")


def _absolute_setting(value: object) -> Path:
    if type(value) is not str or not value:
        raise ResearchCATLifecycleError("managed_settings_invalid")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ResearchCATLifecycleError("managed_settings_invalid")
    return path


def _setting_sha(value: object) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ResearchCATLifecycleError("managed_settings_invalid")
    return value


def _read_pinned_service_port(path: Path, expected_sha256: str) -> int:
    try:
        _assert_no_reparse_components(path)
        with path.open("rb") as stream:
            raw = stream.read(_MAX_SERVICE_CONFIG_BYTES + 1)
    except Exception:
        raise ResearchCATLifecycleError("service_config_unavailable") from None
    if not raw or len(raw) > _MAX_SERVICE_CONFIG_BYTES:
        raise ResearchCATLifecycleError("service_config_invalid")
    if hashlib_sha256(raw) != expected_sha256:
        raise ResearchCATLifecycleError("service_config_hash_mismatch")
    document = _parse_object(raw)
    if set(document) != _SERVICE_FIELDS or document.get("schema") != _SERVICE_SCHEMA:
        raise ResearchCATLifecycleError("service_config_invalid")
    listener = document.get("listener")
    if (
        type(listener) is not dict
        or set(listener) != _LISTENER_FIELDS
        or listener.get("host") != "127.0.0.1"
        or type(listener.get("port")) is not int
        or not 1 <= listener["port"] <= 65535
    ):
        raise ResearchCATLifecycleError("service_config_invalid")
    return listener["port"]


def _parse_object(raw: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError
            value[key] = item
        return value

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique,
            parse_constant=lambda _constant: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        raise ResearchCATLifecycleError("service_config_invalid") from None
    if type(value) is not dict:
        raise ResearchCATLifecycleError("service_config_invalid")
    return value


def _probe_cat_base_executable(
    executable: Path,
    *,
    cat_source: Path,
    cat_dependencies: Path,
) -> bool:
    """Read-only bounded `-S -P` probe; it never imports CAT or numpy."""

    try:
        executable = _resolve_noreparse(executable)
        cat_source = _resolve_noreparse(cat_source)
        cat_dependencies = _resolve_noreparse(cat_dependencies)
        if not executable.is_file() or not cat_source.is_dir() or not cat_dependencies.is_dir():
            return False
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.casefold() in {"systemroot", "windir", "temp", "tmp"}
        }
        environment["PYTHONPATH"] = os.pathsep.join((str(cat_source), str(cat_dependencies)))
        environment["PYTHONNOUSERSITE"] = "1"
        command = [
            str(executable),
            "-S",
            "-P",
            "-c",
            _BASE_PROBE_CODE,
            str(executable),
            str(cat_dependencies),
        ]
        kwargs: dict[str, object] = {
            "shell": False,
            "check": False,
            "timeout": _BASE_PROBE_TIMEOUT_SECONDS,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.DEVNULL,
            "env": environment,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(command, **kwargs)
        output = result.stdout
        if (
            result.returncode != 0
            or type(output) is not bytes
            or not output
            or len(output) > _MAX_BASE_PROBE_OUTPUT_BYTES
        ):
            return False
        report = _parse_object(output)
        expected_fields = {
            "executable",
            "version",
            "no_site",
            "paths",
            "numpy_origin",
            "fastapi_origin",
            "origins_from_dependency",
            "expected_executable_matches",
        }
        if set(report) != expected_fields:
            return False
        expected_exe = os.path.normcase(os.path.realpath(executable))
        if (
            report.get("executable") != expected_exe
            or report.get("expected_executable_matches") is not True
            or report.get("version")[:2] != [3, 14]
            or report.get("no_site") is not True
            or report.get("origins_from_dependency") is not True
            or type(report.get("paths")) is not list
        ):
            return False
        for raw_path in report["paths"]:
            if type(raw_path) is not str or not raw_path:
                return False
            normalized = os.path.normcase(os.path.realpath(raw_path))
            folded_parts = {part.casefold() for part in Path(raw_path).parts}
            if folded_parts & {"site-packages", "dist-packages"} and not _is_within(
                Path(normalized), cat_dependencies
            ):
                return False
        return _is_within(Path(report["numpy_origin"]), cat_dependencies) and _is_within(
            Path(report["fastapi_origin"]), cat_dependencies
        )
    except Exception:
        # A probe's stderr, exception and executable output are never surfaced.
        return False


def _is_within(path: Path, root: Path) -> bool:
    try:
        normalized_path = Path(os.path.normcase(os.path.realpath(path)))
        normalized_root = Path(os.path.normcase(os.path.realpath(root)))
        normalized_path.relative_to(normalized_root)
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _resolve_noreparse(path: Path) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts:
        raise ValueError
    _assert_no_reparse_components(path)
    return path.resolve(strict=True)


def _assert_no_reparse_components(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    try:
        for part in absolute.parts[1:]:
            current = current / part
            info = os.lstat(current)
            if (
                stat_is_symlink(info.st_mode)
                or bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)
                or (hasattr(current, "is_junction") and current.is_junction())
            ):
                raise ValueError
    except (OSError, RuntimeError, ValueError):
        raise ValueError from None


def stat_is_symlink(mode: int) -> bool:
    # Kept local so importing this lifecycle module remains standard-library-only.
    return stat.S_ISLNK(mode)


def hashlib_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
