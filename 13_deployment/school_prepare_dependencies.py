"""Prepare locked, offline school-demo dependencies in a fresh worktree.

The tool deliberately supports only the CAT, Backend, Database, and Frontend
dependency roots. It is not a project installer and never starts services.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import tomllib

MODULES = {
    "01_cat-engine": {
        "runtime": "python",
        "python_minor": (3, 14),
        "imports": ("cat_engine", "fastapi", "jsonschema"),
        "project_install": True,
    },
    "09_backend": {
        "runtime": "python",
        "python_minor": (3, 12),
        "imports": ("smhai_backend.app_factory", "fastapi", "pydantic"),
        "project_install": True,
    },
    "11_database": {
        "runtime": "python",
        "python_minor": (3, 12),
        "imports": ("database_layer.models", "database_layer.crypto", "aiomysql"),
        "project_install": False,
    },
    "10_frontend": {
        "runtime": "node",
        "verify_packages": ("vue", "vite", "typescript"),
    },
}

PYTHON_MODULES = tuple(
    name for name, value in MODULES.items() if value["runtime"] == "python"
)
FRONTEND_MODULE = "10_frontend"
LOCK_FILES = {
    "01_cat-engine": ("pyproject.toml", "uv.lock"),
    "09_backend": ("pyproject.toml", "uv.lock"),
    "11_database": ("pyproject.toml", "uv.lock"),
    "10_frontend": ("package.json", "package-lock.json"),
}
EXPECTED_HEAD_RE = re.compile(r"^[0-9a-f]{40,64}$")
SAFE_CACHE_ENV = (
    "UV_CACHE_DIR",
    "PIP_CACHE_DIR",
    "npm_config_cache",
    "npm_config_tmp",
    "HF_HOME",
    "TRANSFORMERS_CACHE",
    "TORCH_HOME",
)
BASE_ENV = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERNAME")
ERROR_EXIT = 2
STATE_FILENAME = ".school-dependency-preparation-state.json"
NPM_USER_CONFIG_FILENAME = ".school-deps-user.npmrc"
NPM_GLOBAL_CONFIG_FILENAME = ".school-deps-global.npmrc"
ACTIVE_INSTALL_STATE_ROOT: Path | None = None
PYPI_INDEX = "https://pypi.org/simple"
NPM_REGISTRY_HOST = "registry.npmjs.org"
ALLOWED_GIT_CONFIG_KEYS = {
    "core.repositoryformatversion",
    "core.filemode",
    "core.bare",
    "core.logallrefupdates",
    "core.symlinks",
    "core.ignorecase",
    "core.worktree",
    "extensions.worktreeconfig",
}
BUILD_BACKENDS = {
    "01_cat-engine": ("setuptools.build_meta", ("setuptools>=68",)),
    "09_backend": ("hatchling.build", ("hatchling>=1.27",)),
}


class PreparationError(Exception):
    """A safe, fixed-class error suitable for a machine-readable report."""


@dataclass(frozen=True)
class RepoSnapshot:
    head: str
    manifest_sha256: str
    lock_sha256: dict[str, str]


def _canonical(path: Path, *, must_exist: bool) -> Path:
    try:
        value = path.expanduser().resolve(strict=must_exist)
    except (OSError, RuntimeError) as exc:
        raise PreparationError("InvalidPath") from exc
    return Path(os.path.normcase(str(value)))


def _under(child: Path, parent: Path) -> bool:
    try:
        common = os.path.commonpath((str(child), str(parent)))
        return os.path.normcase(common) == os.path.normcase(str(parent))
    except ValueError:
        return False


def _overlap(first: Path, second: Path) -> bool:
    return _under(first, second) or _under(second, first)


def _reject_reparse_path(path: Path, *, include_missing_leaf: bool = False) -> None:
    current = Path(path.anchor)
    parts = path.parts[1:] if path.anchor else path.parts
    for index, part in enumerate(parts):
        current = current / part
        if not current.exists() and not current.is_symlink():
            if include_missing_leaf:
                continue
            break
        try:
            details = current.lstat()
        except OSError as exc:
            raise PreparationError("InvalidPath") from exc
        attributes = getattr(details, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if stat.S_ISLNK(details.st_mode) or attributes & reparse_flag:
            raise PreparationError("ReparsePoint")


def _is_system_target(path: Path) -> bool:
    windows = os.environ.get("SystemRoot", r"C:\Windows")
    protected = [
        Path(windows),
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
        Path(r"C:\inetpub"),
    ]
    if path.anchor and path == Path(path.anchor):
        return True
    return any(_overlap(path, _canonical(item, must_exist=False)) for item in protected)


def _git_env(root: Path) -> dict[str, str]:
    env = _child_environment(root=root)
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_OPTIONAL_LOCKS="0",
    )
    return env


def _git_command(root: Path, args: list[str]) -> list[str]:
    return [
        "git",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.untrackedCache=false",
        "-C",
        str(root),
        *args,
    ]


def _git(root: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            _git_command(root, args),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            env=_git_env(root),
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise PreparationError("GitInspectionFailed") from exc
    if result.returncode != 0:
        raise PreparationError("GitInspectionFailed")
    return result.stdout.strip()


def _git_diff_clean(root: Path) -> None:
    try:
        result = subprocess.run(
            _git_command(root, ["diff", "--ignore-cr-at-eol", "--quiet", "HEAD", "--"]),
            capture_output=True,
            timeout=30,
            env=_git_env(root),
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PreparationError("GitInspectionFailed") from exc
    if result.returncode == 1:
        raise PreparationError("TrackedFilesDifferFromHead")
    if result.returncode != 0:
        raise PreparationError("GitInspectionFailed")


def _git_config_is_allowed(root: Path) -> None:
    keys = _git(
        root, ["config", "--local", "--no-includes", "--name-only", "--list"]
    ).splitlines()
    config_worktree = Path(_git(root, ["rev-parse", "--git-path", "config.worktree"]))
    if not config_worktree.is_absolute():
        config_worktree = root / config_worktree
    if config_worktree.is_file():
        _reject_reparse_path(config_worktree)
        keys.extend(
            _git(
                root,
                [
                    "config",
                    "--file",
                    str(config_worktree),
                    "--no-includes",
                    "--name-only",
                    "--list",
                ],
            ).splitlines()
        )
    for key in keys:
        allowed = (
            key in ALLOWED_GIT_CONFIG_KEYS
            or re.fullmatch(r"remote\.[^.]+\.(?:url|fetch)", key) is not None
            or re.fullmatch(r"branch\..+\.(?:remote|merge)", key) is not None
        )
        if not allowed:
            raise PreparationError("UnknownGitConfig")


def _git_index_is_supported(root: Path) -> None:
    entries = _git(root, ["ls-files", "-v", "-z"]).split("\0")
    if any(entry and entry[0] != "H" for entry in entries):
        raise PreparationError("UnsupportedIndexFlags")
    staged = _git(root, ["ls-files", "--stage", "-z"]).split("\0")
    for entry in staged:
        if not entry:
            continue
        metadata = entry.partition("\t")[0].split()
        if not metadata or metadata[0] == "160000":
            raise PreparationError("UnsupportedGitlink")


def _assert_source_head_clean(root: Path) -> None:
    _git_config_is_allowed(root)
    _git_index_is_supported(root)
    _git_diff_clean(root)


def _reject_target_tree_artifacts(root: Path) -> None:
    for directory, names, filenames in os.walk(root, followlinks=False):
        parent = Path(directory)
        if parent == root and (".git" in names or ".git" in filenames):
            git_metadata = root / ".git"
            try:
                details = git_metadata.lstat()
            except OSError as exc:
                raise PreparationError("InvalidPath") from exc
            if stat.S_ISLNK(details.st_mode) or getattr(
                details, "st_file_attributes", 0
            ) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                raise PreparationError("ReparsePoint")
            if ".git" in names and not stat.S_ISDIR(details.st_mode):
                raise PreparationError("InvalidRepositoryMetadata")
            if ".git" in names:
                names.remove(".git")
            if ".git" in filenames and not stat.S_ISREG(details.st_mode):
                raise PreparationError("InvalidRepositoryMetadata")
            if ".git" in filenames:
                filenames.remove(".git")
        elif parent != root and (".git" in names or ".git" in filenames):
            raise PreparationError("NestedRepository")
        for name in (*names, *filenames):
            item = parent / name
            try:
                details = item.lstat()
            except OSError as exc:
                raise PreparationError("InvalidPath") from exc
            if stat.S_ISLNK(details.st_mode) or getattr(
                details, "st_file_attributes", 0
            ) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                raise PreparationError("ReparsePoint")


def _assert_target_clean(root: Path) -> None:
    _git_config_is_allowed(root)
    _git_index_is_supported(root)
    _git_diff_clean(root)
    status = _git(
        root,
        [
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=normal",
            "--ignored=traditional",
        ],
    )
    if any(entry[:2] in ("??", "!!") for entry in status.split("\0") if entry):
        raise PreparationError("TargetHasUntrackedOrIgnoredFiles")
    _reject_target_tree_artifacts(root)


def _assert_no_package_manager_config(*roots: Path) -> None:
    for root in roots:
        locations = {root, *(root / module for module in MODULES)}
        for location in locations:
            current = location
            while _under(current, root):
                if (current / "uv.toml").exists() or (current / ".npmrc").exists():
                    raise PreparationError("UnsupportedPackageManagerConfig")
                if current == root:
                    break
                current = current.parent


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise PreparationError("MissingManifestOrLock") from exc
    return digest.hexdigest()


def _validate_python_inputs(root: Path, module: str) -> None:
    try:
        with (root / module / "pyproject.toml").open("rb") as stream:
            project_file = tomllib.load(stream)
        with (root / module / "uv.lock").open("rb") as stream:
            lock = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PreparationError("InvalidPythonManifest") from exc
    if "uv" in project_file.get("tool", {}):
        raise PreparationError("UnsupportedUvProjectConfig")
    project = project_file.get("project", {})
    if not isinstance(project.get("requires-python"), str):
        raise PreparationError("InvalidPythonManifest")
    if MODULES[module]["project_install"]:
        expected_backend, expected_requires = BUILD_BACKENDS[module]
        build_system = project_file.get("build-system", {})
        if (
            build_system.get("build-backend") != expected_backend
            or tuple(build_system.get("requires", ())) != expected_requires
            or build_system.get("backend-path")
        ):
            raise PreparationError("UnsupportedBuildSystem")
    for package in lock.get("package", ()):
        source = package.get("source") or {}
        if "registry" in source and source["registry"] == PYPI_INDEX:
            continue
        if source and source != {"editable": "."} and source != {"virtual": "."}:
            raise PreparationError("UnsupportedPythonLockSource")


def _validate_frontend_inputs(root: Path) -> None:
    try:
        package_lock = json.loads(
            (root / FRONTEND_MODULE / "package-lock.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise PreparationError("InvalidFrontendLock") from exc
    for package in package_lock.get("packages", {}).values():
        resolved = package.get("resolved")
        if not resolved:
            continue
        try:
            url = urlsplit(resolved)
        except ValueError as exc:
            raise PreparationError("UnsupportedFrontendLockSource") from exc
        if (
            url.scheme != "https"
            or url.hostname != NPM_REGISTRY_HOST
            or url.username is not None
            or url.password is not None
            or url.port is not None
            or not url.path
            or url.query
            or url.fragment
        ):
            raise PreparationError("UnsupportedFrontendLockSource")


def _snapshot(root: Path) -> RepoSnapshot:
    top = _git(root, ["rev-parse", "--show-toplevel"])
    if _canonical(Path(top), must_exist=True) != root:
        raise PreparationError("RepositoryRootMismatch")
    head = _git(root, ["rev-parse", "HEAD"])
    if not EXPECTED_HEAD_RE.fullmatch(head):
        raise PreparationError("InvalidGitHead")
    manifest = root / "MODULES.md"
    if not manifest.is_file():
        raise PreparationError("MissingTrustedModuleManifest")
    manifest_text = manifest.read_text(encoding="utf-8")
    lock_sha: dict[str, str] = {}
    for module, files in LOCK_FILES.items():
        if not re.search(rf"(?m)^\|\s*{re.escape(module)}\s*\|", manifest_text):
            raise PreparationError("UnregisteredModule")
        for filename in files:
            lock_path = root / module / filename
            if not lock_path.is_file():
                raise PreparationError("MissingManifestOrLock")
            lock_sha[f"{module}/{filename}"] = _sha256(lock_path)
        if MODULES[module]["runtime"] == "python":
            _validate_python_inputs(root, module)
        else:
            _validate_frontend_inputs(root)
    return RepoSnapshot(head, _sha256(manifest), lock_sha)


def _child_environment(
    *,
    root: Path | None = None,
    venv: Path | None = None,
    protected_roots: tuple[Path, ...] = (),
) -> dict[str, str]:
    """Build a clean environment without application, index, or interpreter overrides."""
    source = os.environ
    env: dict[str, str] = {}
    by_upper = {key.upper(): key for key in source}
    for name in BASE_ENV:
        actual = by_upper.get(name.upper())
        if actual and source[actual]:
            env[name] = source[actual]
    for name in SAFE_CACHE_ENV:
        actual = by_upper.get(name.upper())
        if not actual or not source[actual]:
            continue
        raw = Path(source[actual]).expanduser()
        if not raw.is_absolute() or raw.drive.upper() != "D:":
            continue
        try:
            resolved = _canonical(raw, must_exist=False)
        except PreparationError:
            continue
        if (root and _overlap(resolved, root)) or any(
            _overlap(resolved, protected_root) for protected_root in protected_roots
        ):
            continue
        env[name] = str(resolved)
    if venv is not None:
        env["UV_PROJECT_ENVIRONMENT"] = str(venv)
    return env


def _parse_python_arg(values: list[str]) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for value in values:
        module, sep, raw_path = value.partition("=")
        if not sep or module not in PYTHON_MODULES or not raw_path:
            raise PreparationError("InvalidPythonMapping")
        if module in parsed:
            raise PreparationError("DuplicatePythonMapping")
        interpreter = Path(raw_path)
        if not interpreter.is_absolute():
            raise PreparationError("InterpreterMustBeAbsolute")
        interpreter = _canonical(interpreter, must_exist=True)
        if not interpreter.is_file():
            raise PreparationError("InvalidInterpreter")
        parsed[module] = interpreter
    if set(parsed) != set(PYTHON_MODULES):
        raise PreparationError("MissingPythonMapping")
    return parsed


def _python_version(interpreter: Path) -> tuple[int, int, int]:
    source = "import json,sys; print(json.dumps(list(sys.version_info[:3])))"
    try:
        result = subprocess.run(
            [str(interpreter), "-I", "-S", "-c", source],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            env=_child_environment(),
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise PreparationError("InterpreterProbeFailed") from exc
    if result.returncode != 0:
        raise PreparationError("InterpreterProbeFailed")
    try:
        values = json.loads(result.stdout.strip())
        version = tuple(int(value) for value in values)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise PreparationError("InterpreterProbeFailed") from exc
    if len(version) != 3:
        raise PreparationError("InterpreterProbeFailed")
    return version  # type: ignore[return-value]


def _check_python_requirement(
    root: Path, module: str, version: tuple[int, int, int]
) -> None:
    try:
        with (root / module / "pyproject.toml").open("rb") as stream:
            requirement = tomllib.load(stream)["project"]["requires-python"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        raise PreparationError("InvalidPythonManifest") from exc
    expected = MODULES[module]["python_minor"]
    if version[:2] != expected:
        raise PreparationError("PythonVersionMismatch")
    compact = re.sub(r"\s+", "", requirement)
    wanted = f">={expected[0]}.{expected[1]},<{expected[0]}.{expected[1] + 1}"
    if wanted not in compact:
        raise PreparationError("PythonRequirementMismatch")


def _target_path(root: Path, module: str) -> Path:
    return (
        root
        / module
        / (".venv" if MODULES[module]["runtime"] == "python" else "node_modules")
    )


def _assert_target_layout(source: Path, target: Path) -> None:
    if _overlap(source, target):
        raise PreparationError("SourceTargetOverlap")
    if _is_system_target(target):
        raise PreparationError("SystemTarget")
    _reject_reparse_path(target, include_missing_leaf=True)
    for module in MODULES:
        module_dir = target / module
        _reject_reparse_path(module_dir, include_missing_leaf=True)
        if module_dir.exists() and not module_dir.is_dir():
            raise PreparationError("TargetModuleNotDirectory")
        output = _target_path(target, module)
        _reject_reparse_path(output, include_missing_leaf=True)
        if output.exists() or output.is_symlink():
            raise PreparationError("TargetEnvironmentExists")


def _check_target_snapshot(source_snap: RepoSnapshot, target: Path) -> RepoSnapshot:
    target_snap = _snapshot(target)
    if target_snap.head != source_snap.head:
        raise PreparationError("TargetHeadMismatch")
    if target_snap.manifest_sha256 != source_snap.manifest_sha256:
        raise PreparationError("TargetManifestMismatch")
    if target_snap.lock_sha256 != source_snap.lock_sha256:
        raise PreparationError("TargetLockMismatch")
    return target_snap


def _tool(name: str) -> str:
    choices = (name, f"{name}.exe", f"{name}.cmd") if os.name == "nt" else (name,)
    for candidate in choices:
        found = shutil.which(candidate)
        if found:
            return found
    raise PreparationError(f"MissingTool:{name}")


def _resolve_executable(name: str) -> str:
    executable = Path(_tool(name))
    if os.name == "nt" and executable.suffix.casefold() != ".exe":
        raise PreparationError("UntrustedExecutableWrapper")
    _reject_reparse_path(executable.absolute())
    resolved = _canonical(executable, must_exist=True)
    if not resolved.is_file():
        raise PreparationError("MissingTool")
    return str(resolved)


def _node_and_npm_cli() -> tuple[str, str]:
    node = Path(_resolve_executable("node.exe"))
    npm_cli = node.parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
    _reject_reparse_path(npm_cli)
    npm_cli = _canonical(npm_cli, must_exist=True)
    if not npm_cli.is_file() or not _under(npm_cli, node.parent):
        raise PreparationError("MissingTrustedNpmCli")
    return str(node), str(npm_cli)


def _create_npm_config_files(target: Path) -> tuple[Path, Path]:
    paths = (
        target / FRONTEND_MODULE / NPM_USER_CONFIG_FILENAME,
        target / FRONTEND_MODULE / NPM_GLOBAL_CONFIG_FILENAME,
    )
    for path in paths:
        _reject_reparse_path(path, include_missing_leaf=True)
        if path.exists() or path.is_symlink():
            raise PreparationError("NpmConfigArtifactExists")
    for path in paths:
        try:
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError as exc:
            raise PreparationError("NpmConfigArtifactExists") from exc
        except OSError as exc:
            raise PreparationError("NpmConfigArtifactCreationFailed") from exc
    return paths


def _public_import_check(
    module: str,
    interpreter: Path,
    root: Path,
    *,
    protected_roots: tuple[Path, ...] = (),
) -> None:
    import_names = MODULES[module]["imports"]
    source_prefix = ""
    if module == "11_database":
        source_prefix = f"import sys; sys.path.insert(0, {str(root / module)!r}); "
    source = (
        source_prefix
        + "import importlib; "
        + "; ".join(f"importlib.import_module({name!r})" for name in import_names)
    )
    executable = _target_path(root, module) / "Scripts" / "python.exe"
    try:
        result = subprocess.run(
            [str(executable), "-I", "-c", source],
            capture_output=True,
            timeout=30,
            env=_child_environment(root=root, protected_roots=protected_roots),
            cwd=root / module,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PreparationError("ImportCheckFailed") from exc
    if result.returncode != 0:
        raise PreparationError("ImportCheckFailed")
    version = _python_version(executable)
    _check_python_requirement(root, module, version)


def _frontend_check(
    root: Path, node: str, *, protected_roots: tuple[Path, ...] = ()
) -> None:
    source = r"""
const fs = require('node:fs');
const path = require('node:path');
const base = process.cwd();
const manifest = JSON.parse(fs.readFileSync(path.join(base, 'package.json'), 'utf8'));
const lock = JSON.parse(fs.readFileSync(path.join(base, 'package-lock.json'), 'utf8'));
const names = ['vue', 'vite', 'typescript'];
for (const name of names) {
  const installedPath = path.join(base, 'node_modules', name, 'package.json');
  const installed = JSON.parse(fs.readFileSync(installedPath, 'utf8'));
  const locked = lock.packages['node_modules/' + name];
  const declared = manifest.dependencies?.[name] ?? manifest.devDependencies?.[name];
  if (!locked || !declared || installed.version !== locked.version) process.exit(19);
}
"""
    try:
        result = subprocess.run(
            [node, "-e", source],
            capture_output=True,
            timeout=15,
            env=_child_environment(root=root, protected_roots=protected_roots),
            cwd=root / FRONTEND_MODULE,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PreparationError("FrontendCheckFailed") from exc
    if result.returncode != 0:
        raise PreparationError("FrontendCheckFailed")


def _run_step(
    *,
    name: str,
    command: list[str],
    cwd: Path,
    root: Path,
    venv: Path | None = None,
    extra_env: dict[str, str] | None = None,
    protected_roots: tuple[Path, ...] = (),
    on_update: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    stage: dict[str, Any] = {"name": name, "state": "running", "exit_code": None}
    if on_update and not on_update(stage):
        stage.update(state="failed", error_class="StatePersistenceFailed")
        return stage
    env = _child_environment(root=root, venv=venv, protected_roots=protected_roots)
    if extra_env:
        env.update(extra_env)
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            timeout=60 * 60,
            check=False,
        )
    except subprocess.TimeoutExpired:
        stage.update(state="failed", error_class="TimeoutExpired")
        if on_update and not on_update(stage):
            stage["error_class"] = "StatePersistenceFailed"
        return stage
    except OSError as exc:
        stage.update(state="failed", error_class=type(exc).__name__)
        if on_update and not on_update(stage):
            stage["error_class"] = "StatePersistenceFailed"
        return stage
    stage["exit_code"] = result.returncode
    if result.returncode != 0:
        stage.update(state="failed", error_class="CommandFailed")
        if on_update and not on_update(stage):
            stage["error_class"] = "StatePersistenceFailed"
        return stage
    stage["state"] = "succeeded"
    if on_update and not on_update(stage):
        stage.update(state="failed", error_class="StatePersistenceFailed")
    return stage


def _report(
    *, mode: str, snapshot: RepoSnapshot, stages: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "schema_version": "school-dependency-preparation.v1",
        "mode": mode,
        "source_head": snapshot.head,
        "module_manifest_sha256": snapshot.manifest_sha256,
        "lock_sha256": snapshot.lock_sha256,
        "stages": stages,
    }


def _report_for_target(
    *,
    snapshot: RepoSnapshot,
    target_snapshot: RepoSnapshot,
    stages: list[dict[str, Any]],
    state: str,
) -> dict[str, Any]:
    report = _report(mode="install", snapshot=snapshot, stages=stages)
    report.update(
        run_state=state,
        state_persistence="succeeded",
        target_head=target_snapshot.head,
        target_module_manifest_sha256=target_snapshot.manifest_sha256,
        target_lock_sha256=target_snapshot.lock_sha256,
    )
    return report


def _persist_install_state(
    target: Path, report: dict[str, Any], *, allow_existing: bool
) -> bool:
    destination = target / STATE_FILENAME
    temporary = target / f"{STATE_FILENAME}.tmp"
    try:
        for path in (destination, temporary):
            if path.exists() or path.is_symlink():
                _reject_reparse_path(path)
        if not allow_existing and (destination.exists() or temporary.exists()):
            return False
        if temporary.exists():
            return False
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(
                report,
                stream,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except (OSError, PreparationError):
        return False
    return True


def execute(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    global ACTIVE_INSTALL_STATE_ROOT
    ACTIVE_INSTALL_STATE_ROOT = None
    source_input = Path(args.source_root).expanduser()
    target_input = Path(args.target_root).expanduser()
    if not source_input.is_absolute() or not target_input.is_absolute():
        raise PreparationError("RootsMustBeAbsolute")
    _reject_reparse_path(source_input.absolute())
    _reject_reparse_path(target_input.absolute(), include_missing_leaf=True)
    source = _canonical(source_input, must_exist=True)
    target = _canonical(target_input, must_exist=args.mode == "install")
    if args.mode == "plan" and _overlap(source, target):
        raise PreparationError("SourceTargetOverlap")
    _assert_source_head_clean(source)
    _assert_no_package_manager_config(source)
    source_snapshot = _snapshot(source)
    python_paths = _parse_python_arg(args.python)
    versions: dict[str, tuple[int, int, int]] = {}
    for module, interpreter in python_paths.items():
        version = _python_version(interpreter)
        _check_python_requirement(source, module, version)
        versions[module] = version

    stages = [
        {
            "name": module,
            "state": "planned" if args.mode == "plan" else "pending",
            "target": ".venv" if module != FRONTEND_MODULE else "node_modules",
            **(
                {"python": ".".join(map(str, versions[module]))}
                if module in versions
                else {}
            ),
        }
        for module in MODULES
    ]
    if args.mode == "plan":
        return _report(mode="plan", snapshot=source_snapshot, stages=stages), 0

    _assert_target_layout(source, target)
    if target == source:
        raise PreparationError("SourceCannotBeInstallTarget")
    _assert_target_clean(target)
    _assert_no_package_manager_config(target)
    target_snapshot = _check_target_snapshot(source_snapshot, target)
    uv = _resolve_executable("uv.exe" if os.name == "nt" else "uv")
    node, npm_cli = _node_and_npm_cli()
    for module in MODULES:
        target_module = target / module
        if not target_module.is_dir():
            raise PreparationError("MissingTargetModule")
        if not (target_module / next(iter(LOCK_FILES[module]))).is_file():
            raise PreparationError("MissingTargetManifest")

    report = _report_for_target(
        snapshot=source_snapshot,
        target_snapshot=target_snapshot,
        stages=stages,
        state="running",
    )
    if not _persist_install_state(target, report, allow_existing=False):
        report.update(run_state="blocked", error_class="StatePersistenceFailed")
        return report, ERROR_EXIT
    ACTIVE_INSTALL_STATE_ROOT = target

    def persist_stage(index: int, stage: dict[str, Any]) -> bool:
        stages[index] = stage
        current = _report_for_target(
            snapshot=source_snapshot,
            target_snapshot=target_snapshot,
            stages=stages,
            state="running",
        )
        return _persist_install_state(target, current, allow_existing=True)

    for module in PYTHON_MODULES:
        index = tuple(MODULES).index(module)
        venv = _target_path(target, module)
        command = [
            uv,
            "sync",
            "--project",
            str(target / module),
            "--frozen",
            "--offline",
            "--no-config",
            "--no-python-downloads",
            "--no-dev",
            "--python",
            str(python_paths[module]),
        ]
        if not MODULES[module]["project_install"]:
            command.append("--no-install-project")
        stage = _run_step(
            name=module,
            command=command,
            cwd=target / module,
            root=target,
            venv=venv,
            protected_roots=(source,),
            on_update=lambda stage, stage_index=index: persist_stage(
                stage_index, stage
            ),
        )
        if stage["state"] != "succeeded":
            break
        stage["state"] = "verifying"
        if not persist_stage(index, stage):
            stage.update(state="failed", error_class="StatePersistenceFailed")
            break
        try:
            _public_import_check(
                module, python_paths[module], target, protected_roots=(source,)
            )
        except PreparationError as exc:
            stage.update(state="failed", error_class=exc.args[0])
            if not persist_stage(index, stage):
                stage["error_class"] = "StatePersistenceFailed"
            break
        stage["verification"] = "version_and_public_imports_passed"
        stage["state"] = "succeeded"
        if not persist_stage(index, stage):
            stage.update(state="failed", error_class="StatePersistenceFailed")
            break

    if all(item["state"] == "succeeded" for item in stages[: len(PYTHON_MODULES)]):
        frontend_index = tuple(MODULES).index(FRONTEND_MODULE)
        try:
            npm_user_config, npm_global_config = _create_npm_config_files(target)
        except PreparationError as exc:
            frontend = {
                "name": FRONTEND_MODULE,
                "state": "failed",
                "exit_code": None,
                "error_class": exc.args[0],
            }
            if not persist_stage(frontend_index, frontend):
                frontend["error_class"] = "StatePersistenceFailed"
        else:
            frontend = _run_step(
                name=FRONTEND_MODULE,
                command=[node, npm_cli, "ci", "--offline", "--ignore-scripts"],
                cwd=target / FRONTEND_MODULE,
                root=target,
                protected_roots=(source,),
                extra_env={
                    "NPM_CONFIG_USERCONFIG": str(npm_user_config),
                    "NPM_CONFIG_GLOBALCONFIG": str(npm_global_config),
                },
                on_update=lambda stage: persist_stage(frontend_index, stage),
            )
        if frontend["state"] == "succeeded":
            frontend["state"] = "verifying"
            if not persist_stage(frontend_index, frontend):
                frontend.update(state="failed", error_class="StatePersistenceFailed")
            try:
                if frontend["state"] == "verifying":
                    _frontend_check(target, node, protected_roots=(source,))
                    frontend["verification"] = "locked_packages_read"
                    frontend["state"] = "succeeded"
            except PreparationError as exc:
                frontend.update(state="failed", error_class=exc.args[0])
            if not persist_stage(frontend_index, frontend):
                frontend.update(state="failed", error_class="StatePersistenceFailed")

    integrity = {"name": "manifest_integrity", "state": "running", "exit_code": None}
    stages.append(integrity)
    integrity_state_persisted = _persist_install_state(
        target,
        _report_for_target(
            snapshot=source_snapshot,
            target_snapshot=target_snapshot,
            stages=stages,
            state="running",
        ),
        allow_existing=True,
    )
    if not integrity_state_persisted:
        integrity.update(state="failed", error_class="StatePersistenceFailed")
    try:
        final_snapshot = _snapshot(target)
        _assert_source_head_clean(target)
        _assert_no_package_manager_config(target)
    except PreparationError:
        integrity.update(
            state="failed", exit_code=None, error_class="PostInstallManifestCheckFailed"
        )
        final_snapshot = None
    if final_snapshot is not None and final_snapshot != target_snapshot:
        integrity.update(
            state="failed", exit_code=None, error_class="PostInstallManifestChanged"
        )
    elif final_snapshot is not None and integrity_state_persisted:
        integrity.update(state="succeeded", exit_code=0)
    state = (
        "partial"
        if any(stage["state"] == "failed" for stage in stages)
        else "completed"
    )
    report = _report_for_target(
        snapshot=source_snapshot,
        target_snapshot=target_snapshot,
        stages=stages,
        state=state,
    )
    if not _persist_install_state(target, report, allow_existing=True):
        report.update(run_state="partial", state_persistence="failed")
        return report, 1
    ACTIVE_INSTALL_STATE_ROOT = None
    return report, 1 if state == "partial" else 0


def _mark_active_install_partial(error_class: str) -> dict[str, Any] | None:
    global ACTIVE_INSTALL_STATE_ROOT
    root = ACTIVE_INSTALL_STATE_ROOT
    ACTIVE_INSTALL_STATE_ROOT = None
    if root is None:
        return None
    state_path = root / STATE_FILENAME
    try:
        _reject_reparse_path(state_path)
        report = json.loads(state_path.read_text(encoding="utf-8"))
        if (
            not isinstance(report, dict)
            or report.get("schema_version") != "school-dependency-preparation.v1"
            or report.get("mode") != "install"
            or not isinstance(report.get("stages"), list)
        ):
            return None
        report["run_state"] = "partial"
        report["stages"].append(
            {
                "name": "runner",
                "state": "failed",
                "exit_code": None,
                "error_class": error_class,
            }
        )
        if not _persist_install_state(root, report, allow_existing=True):
            report["state_persistence"] = "failed"
        return report
    except (OSError, PreparationError, json.JSONDecodeError):
        return None


def main(argv: list[str] | None = None) -> int:
    global ACTIVE_INSTALL_STATE_ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "install"))
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--target-root", required=True)
    parser.add_argument(
        "--python",
        action="append",
        default=[],
        metavar="MODULE=ABSOLUTE_PATH",
        help="Existing interpreter path for each Python module (required for plan/install).",
    )
    args = parser.parse_args(argv)
    ACTIVE_INSTALL_STATE_ROOT = None
    try:
        report, status = execute(args)
    except PreparationError as exc:
        report = {
            "schema_version": "school-dependency-preparation.v1",
            "mode": args.mode,
            "status": "blocked",
            "error_class": str(exc),
            "stages": [],
        }
        recovered = _mark_active_install_partial(str(exc))
        if recovered is not None:
            report = recovered
        status = ERROR_EXIT
    except Exception:  # noqa: BLE001 - sanitize unexpected failures without exposing subprocess details.
        report = {
            "schema_version": "school-dependency-preparation.v1",
            "mode": args.mode,
            "status": "failed",
            "error_class": "UnexpectedError",
            "stages": [],
        }
        recovered = _mark_active_install_partial("UnexpectedError")
        if recovered is not None:
            report = recovered
        status = 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
