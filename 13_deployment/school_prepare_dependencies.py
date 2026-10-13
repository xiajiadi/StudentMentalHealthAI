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
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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

PYTHON_MODULES = tuple(name for name, value in MODULES.items() if value["runtime"] == "python")
FRONTEND_MODULE = "10_frontend"
LOCK_FILES = {
    "01_cat-engine": ("pyproject.toml", "uv.lock"),
    "09_backend": ("pyproject.toml", "uv.lock"),
    "11_database": ("pyproject.toml", "uv.lock"),
    "10_frontend": ("package.json", "package-lock.json"),
}
EXPECTED_HEAD_RE = re.compile(r"^[0-9a-f]{40,64}$")
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)")
SAFE_CACHE_ENV = (
    "UV_CACHE_DIR",
    "PIP_CACHE_DIR",
    "npm_config_cache",
    "npm_config_tmp",
    "HF_HOME",
    "TRANSFORMERS_CACHE",
    "TORCH_HOME",
)
BASE_ENV = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
ERROR_EXIT = 2


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
        return os.path.commonpath((str(child), str(parent))) == str(parent)
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


def _git(root: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
            env=_child_environment(root=root),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PreparationError("GitInspectionFailed") from exc
    return result.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise PreparationError("MissingManifestOrLock") from exc
    return digest.hexdigest()


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
    return RepoSnapshot(head, _sha256(manifest), lock_sha)


def _child_environment(*, root: Path | None = None, venv: Path | None = None) -> dict[str, str]:
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
        if root and _overlap(resolved, root):
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
            timeout=10,
            env=_child_environment(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
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


def _check_python_requirement(root: Path, module: str, version: tuple[int, int, int]) -> None:
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
    return root / module / (".venv" if MODULES[module]["runtime"] == "python" else "node_modules")


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


def _public_import_check(module: str, interpreter: Path, root: Path) -> None:
    import_names = MODULES[module]["imports"]
    source_prefix = ""
    if module == "11_database":
        source_prefix = f"import sys; sys.path.insert(0, {str(root / module)!r}); "
    source = source_prefix + "import importlib; " + "; ".join(
        f"importlib.import_module({name!r})" for name in import_names
    )
    executable = _target_path(root, module) / "Scripts" / "python.exe"
    try:
        result = subprocess.run(
            [str(executable), "-I", "-c", source],
            capture_output=True,
            text=True,
            timeout=30,
            env=_child_environment(root=root),
            cwd=root / module,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PreparationError("ImportCheckFailed") from exc
    if result.returncode != 0:
        raise PreparationError("ImportCheckFailed")
    version = _python_version(executable)
    _check_python_requirement(root, module, version)


def _frontend_check(root: Path, node: str) -> None:
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
            text=True,
            timeout=15,
            env=_child_environment(root=root),
            cwd=root / FRONTEND_MODULE,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PreparationError("FrontendCheckFailed") from exc
    if result.returncode != 0:
        raise PreparationError("FrontendCheckFailed")


def _run_step(
    *, name: str, command: list[str], cwd: Path, root: Path, venv: Path | None = None
) -> dict[str, Any]:
    stage: dict[str, Any] = {"name": name, "state": "running", "exit_code": None}
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=_child_environment(root=root, venv=venv),
            capture_output=True,
            text=True,
            timeout=60 * 60,
        )
    except subprocess.TimeoutExpired:
        stage.update(state="failed", error_class="TimeoutExpired")
        return stage
    except OSError as exc:
        stage.update(state="failed", error_class=type(exc).__name__)
        return stage
    stage["exit_code"] = result.returncode
    if result.returncode != 0:
        stage.update(state="failed", error_class="CommandFailed")
        return stage
    stage["state"] = "succeeded"
    return stage


def _report(*, mode: str, snapshot: RepoSnapshot, stages: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "school-dependency-preparation.v1",
        "mode": mode,
        "source_head": snapshot.head,
        "module_manifest_sha256": snapshot.manifest_sha256,
        "lock_sha256": snapshot.lock_sha256,
        "stages": stages,
    }


def execute(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
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
            **({"python": ".".join(map(str, versions[module]))} if module in versions else {}),
        }
        for module in MODULES
    ]
    if args.mode == "plan":
        return _report(mode="plan", snapshot=source_snapshot, stages=stages), 0

    _assert_target_layout(source, target)
    if target == source:
        raise PreparationError("SourceCannotBeInstallTarget")
    target_snapshot = _check_target_snapshot(source_snapshot, target)
    uv = _tool("uv")
    npm = _tool("npm")
    for module in MODULES:
        target_module = target / module
        if not target_module.is_dir():
            raise PreparationError("MissingTargetModule")
        if not (target_module / next(iter(LOCK_FILES[module]))).is_file():
            raise PreparationError("MissingTargetManifest")

    for module in PYTHON_MODULES:
        venv = _target_path(target, module)
        command = [
            uv,
            "sync",
            "--project",
            str(target / module),
            "--frozen",
            "--offline",
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
        )
        stages[tuple(MODULES).index(module)] = stage
        if stage["state"] != "succeeded":
            break
        try:
            _public_import_check(module, python_paths[module], target)
        except PreparationError as exc:
            stage.update(state="failed", error_class=exc.args[0])
            break
        stage["verification"] = "version_and_public_imports_passed"

    if all(item["state"] == "succeeded" for item in stages[: len(PYTHON_MODULES)]):
        frontend_index = tuple(MODULES).index(FRONTEND_MODULE)
        frontend = _run_step(
            name=FRONTEND_MODULE,
            command=[npm, "ci", "--offline", "--ignore-scripts"],
            cwd=target / FRONTEND_MODULE,
            root=target,
        )
        stages[frontend_index] = frontend
        if frontend["state"] == "succeeded":
            node = _tool("node")
            try:
                _frontend_check(target, node)
                frontend["verification"] = "locked_packages_read"
            except PreparationError as exc:
                frontend.update(state="failed", error_class=exc.args[0])

    integrity = {"name": "manifest_integrity", "state": "succeeded", "exit_code": 0}
    try:
        final_snapshot = _snapshot(target)
    except PreparationError as exc:
        integrity.update(state="failed", exit_code=None, error_class="PostInstallManifestCheckFailed")
        stages.append(integrity)
        report = _report(mode="install", snapshot=source_snapshot, stages=stages)
        report["target_head"] = target_snapshot.head
        return report, 1
    if final_snapshot != target_snapshot:
        integrity.update(state="failed", exit_code=None, error_class="PostInstallManifestChanged")
        stages.append(integrity)
        report = _report(mode="install", snapshot=source_snapshot, stages=stages)
        report["target_head"] = target_snapshot.head
        return report, 1
    stages.append(integrity)
    report = _report(mode="install", snapshot=source_snapshot, stages=stages)
    report["target_head"] = target_snapshot.head
    report["target_module_manifest_sha256"] = target_snapshot.manifest_sha256
    report["target_lock_sha256"] = target_snapshot.lock_sha256
    return report, 1 if any(stage["state"] == "failed" for stage in stages) else 0


def main(argv: list[str] | None = None) -> int:
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
        status = ERROR_EXIT
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
