"""Install and verify the pinned loopback-only synthetic CAT service."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import http.client
import json
import os
import shutil
import stat
import subprocess
import tarfile
import time
from pathlib import Path, PurePosixPath
from typing import Any

APP_ROOT = Path("/opt/psynova-school-demo")
BASE_RELEASE = APP_ROOT / "release"
BASE_REVISION = "f3047642aa3466f9b4f210f4f704d57fd2cdf3cc"
SOURCE_COMMIT = "b7773176acd151f4a2cb7110a43162719a4f8c2a"
SERVICE_ROOT = APP_ROOT / "services" / "cat"
RELEASE_ROOT = SERVICE_ROOT / "release"
PYTHON_ROOT = SERVICE_ROOT / "python"
VENV_ROOT = SERVICE_ROOT / "venv"
UV_CACHE_ROOT = Path("/var/cache/psynova-school-cat/uv")
UNIT_PATH = Path("/etc/systemd/system/psynova-school-cat.service")
STATE_PATH = Path("/var/lib/psynova-school-demo/cat-install-state.json")
LOCK_PATH = Path("/run/lock/psynova-school-cat-install.lock")
BUNDLE_PATH = Path(
    "/home/psynova/apps/psynova/staging/linux-school-demo/"
    "psynova-school-cat-b777317.tar.gz"
)
BUNDLE_SHA256 = "2e658eb972ba4c7c96e5691b3f2cb8faeb24879e352e2e2431e23418a8faf71e"
MAX_BUNDLE_SIZE = 12 * 1024 * 1024
MAX_MEMBER_SIZE = 2 * 1024 * 1024
MAX_TOTAL_MEMBER_SIZE = 8 * 1024 * 1024
PYTHON_VERSION = "3.14.6"
ADAPTIVETESTING_VERSION = "1.2.1"
FASTAPI_VERSION = "0.141.1"
UVICORN_VERSION = "0.52.4"
CAT_URL_HOST = "127.0.0.1"
CAT_PORT = 8180
SERVICE_NAME = "psynova-school-cat.service"
REQUIRED_LOOPBACK_PORTS = {3306: "mysql.service", 8088: "psynova-school-demo.service", 8170: "psynova-school-rag.service", 8181: "psynova-school-safety.service", 8190: "psynova-school-safety.service"}
PHASES = (
    "INITIALIZED",
    "PAYLOAD_READY",
    "DEPENDENCIES_READY",
    "UNIT_READY",
    "SERVICE_STARTED",
    "HTTP_VERIFIED",
)
REQUIRED_PAYLOAD = {
    "release/ADAPTIVETESTING_COMPATIBILITY_REPORT.md",
    "release/README.md",
    "release/pyproject.toml",
    "release/uv.lock",
    "release/fixtures/demo_cat_config.v1.json",
    "release/fixtures/synthetic_item_bank.v1.json",
    "systemd/psynova-school-cat.service",
}
CAT_FINGERPRINTS = {
    "source": "eb993e7c3de8d61a101e3a9d7787ebb6e204ea02071f2361372267d0cf15995e",
    "entrypoint": "f92345a15666241490d87e1dfbedbbce771e99e6f51d5bc2eb71e4849631c490",
    "config": "e7da9e073f2cc5fc5ed28c4118c456feda0b798866ea3ca8623193f0224be8a4",
    "item_bank": "250fa3f9868c73e2e1c962ffb78e0308d8d13e8144168ac19edfb7174da9fa56",
}


class GateError(RuntimeError):
    def __init__(self, code: str, phase: str) -> None:
        super().__init__(code)
        self.code = code
        self.phase = phase


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run(
    args: list[str],
    *,
    phase: str,
    timeout: int = 60,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        raise GateError("required_command_failed", phase) from None
    if result.returncode:
        raise GateError("required_command_failed", phase)
    return result


def _require_root_directory(path: Path, code: str, mode: int | None = None) -> None:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError:
        raise GateError(code, "filesystem_verify") from None
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or mode is not None and stat.S_IMODE(metadata.st_mode) != mode
    ):
        raise GateError(code, "filesystem_verify")


def _require_root_snapshot() -> None:
    if os.geteuid() != 0:
        raise GateError("root_required", "startup")
    snapshot = Path(__file__)
    if snapshot.is_symlink():
        raise GateError("root_snapshot_symlink_rejected", "startup")
    try:
        resolved = snapshot.resolve(strict=True)
        metadata = resolved.stat(follow_symlinks=False)
        suffix = resolved.stem.removeprefix("install_linux_school_cat_service_")
        app_root = APP_ROOT.resolve(strict=True)
    except OSError:
        raise GateError("root_snapshot_unavailable", "startup") from None
    if (
        resolved.parent != app_root
        or not resolved.name.startswith("install_linux_school_cat_service_")
        or len(suffix) != 64
        or any(character not in "0123456789abcdef" for character in suffix)
        or metadata.st_uid != 0
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o500
        or _sha256_file(resolved) != suffix
    ):
        raise GateError("root_snapshot_fingerprint_mismatch", "startup")
    _require_root_directory(Path("/opt"), "application_parent_metadata_mismatch")
    _require_root_directory(APP_ROOT, "application_root_metadata_mismatch")
    _require_root_directory(BASE_RELEASE, "base_release_metadata_mismatch")


@contextlib.contextmanager
def _deployment_lock():
    import fcntl

    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(LOCK_PATH, flags, 0o600)
        metadata = os.fstat(descriptor)
        if metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != 0o600:
            os.close(descriptor)
            raise GateError("deployment_lock_metadata_mismatch", "startup")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except GateError:
        raise
    except BlockingIOError:
        raise GateError("deployment_already_running", "startup") from None
    except OSError:
        raise GateError("deployment_lock_unavailable", "startup") from None
    try:
        yield
    finally:
        os.close(descriptor)


def _check_no_active_lock() -> None:
    if not os.path.lexists(LOCK_PATH):
        return
    import fcntl

    if LOCK_PATH.is_symlink():
        raise GateError("deployment_lock_metadata_mismatch", "startup")
    try:
        descriptor = os.open(LOCK_PATH, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        metadata = os.fstat(descriptor)
        if metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != 0o600:
            os.close(descriptor)
            raise GateError("deployment_lock_metadata_mismatch", "startup")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise GateError("deployment_already_running", "startup") from None
        finally:
            os.close(descriptor)
    except GateError:
        raise
    except OSError:
        raise GateError("deployment_lock_unavailable", "startup") from None


def _unit_active(name: str) -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", name],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise GateError("systemd_query_failed", "host_preflight") from None
    return result.returncode == 0


def _unit_enabled(name: str) -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "is-enabled", "--quiet", name],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise GateError("systemd_query_failed", "host_preflight") from None
    return result.returncode == 0


def _listeners_for_port(port: int) -> list[str]:
    result = _run(["ss", "-ltnH"], phase="listener_check")
    listeners: list[str] = []
    for line in result.stdout.decode("utf-8", errors="replace").splitlines():
        columns = line.split()
        if len(columns) >= 4 and columns[3].endswith(f":{port}"):
            listeners.append(columns[3])
    return listeners


def _require_port_loopback(port: int, *, allow_absent: bool) -> None:
    listeners = _listeners_for_port(port)
    if not listeners and allow_absent:
        return
    if not listeners or any(address != f"127.0.0.1:{port}" for address in listeners):
        raise GateError("service_listener_not_loopback", "listener_check")


def _safe_member_name(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        bool(name)
        and not path.is_absolute()
        and ".." not in path.parts
        and "" not in path.parts
        and "\\" not in name
    )


def _allowed_payload_path(name: str) -> bool:
    return (
        name in REQUIRED_PAYLOAD
        or name.startswith("release/src/cat_engine/") and name.endswith(".py")
    )


def _canonical_fingerprint(files: dict[str, bytes]) -> str:
    source_names = sorted(
        name
        for name in files
        if name.startswith("release/src/cat_engine/") and name.endswith(".py")
    )
    source_names.append("release/pyproject.toml")
    digest = hashlib.sha256()
    for name in source_names:
        relative = ("01_cat-engine/" + name.removeprefix("release/")).encode("utf-8")
        data = files[name].replace(b"\r\n", b"\n")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _validate_fixture_contract(files: dict[str, bytes]) -> None:
    try:
        config = json.loads(files["release/fixtures/demo_cat_config.v1.json"])
        bank = json.loads(files["release/fixtures/synthetic_item_bank.v1.json"])
    except (KeyError, UnicodeError, json.JSONDecodeError):
        raise GateError("synthetic_fixture_invalid", "bundle_preflight") from None
    metadata = bank.get("metadata") if type(bank) is dict else None
    items = bank.get("items") if type(bank) is dict else None
    if (
        type(config) is not dict
        or config.get("config_version") != "demo.cat.v1"
        or config.get("min_items") != 3
        or config.get("max_items") != 8
        or type(bank) is not dict
        or bank.get("item_bank_id") != "ITEMBANK_demo_cat"
        or bank.get("instrument_id") != "CURRENT_SYNTHETIC_GRM"
        or bank.get("target_population") != "SYNTHETIC_STUDENT_DEMO"
        or type(metadata) is not dict
        or metadata.get("synthetic") is not True
        or metadata.get("intended_use") != "engineering_test_only"
        or metadata.get("psychological_interpretation_allowed") is not False
        or type(items) is not list
        or not items
        or any(
            type(item) is not dict or item.get("source") != "synthetic_engineering_fixture"
            for item in items
        )
    ):
        raise GateError("synthetic_fixture_contract_mismatch", "bundle_preflight")


def _load_bundle() -> tuple[dict[str, Any], dict[str, bytes]]:
    if not BUNDLE_PATH.is_file() or BUNDLE_PATH.is_symlink():
        raise GateError("bundle_missing", "bundle_preflight")
    try:
        metadata = BUNDLE_PATH.stat(follow_symlinks=False)
    except OSError:
        raise GateError("bundle_metadata_unavailable", "bundle_preflight") from None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or metadata.st_size > MAX_BUNDLE_SIZE
        or _sha256_file(BUNDLE_PATH) != BUNDLE_SHA256
    ):
        raise GateError("bundle_fingerprint_mismatch", "bundle_preflight")
    files: dict[str, bytes] = {}
    total = 0
    try:
        with tarfile.open(BUNDLE_PATH, mode="r:gz") as archive:
            for member in archive.getmembers():
                if not _safe_member_name(member.name) or not member.isfile():
                    raise GateError("bundle_member_rejected", "bundle_preflight")
                if member.size < 0 or member.size > MAX_MEMBER_SIZE:
                    raise GateError("bundle_member_size_rejected", "bundle_preflight")
                total += member.size
                if total > MAX_TOTAL_MEMBER_SIZE or member.name in files:
                    raise GateError("bundle_inventory_rejected", "bundle_preflight")
                stream = archive.extractfile(member)
                if stream is None:
                    raise GateError("bundle_member_unreadable", "bundle_preflight")
                data = stream.read(MAX_MEMBER_SIZE + 1)
                if len(data) != member.size:
                    raise GateError("bundle_member_size_mismatch", "bundle_preflight")
                files[member.name] = data
    except GateError:
        raise
    except (tarfile.TarError, OSError):
        raise GateError("bundle_archive_invalid", "bundle_preflight") from None

    try:
        manifest = json.loads(files["PAYLOAD_MANIFEST.json"])
    except (KeyError, UnicodeError, json.JSONDecodeError):
        raise GateError("bundle_manifest_invalid", "bundle_preflight") from None
    if (
        type(manifest) is not dict
        or manifest.get("schema") != "psynova.school-cat-bundle.v1"
        or manifest.get("source_commit") != SOURCE_COMMIT
        or manifest.get("python_version") != PYTHON_VERSION
        or manifest.get("synthetic_fixture_only") is not True
        or manifest.get("psychological_interpretation_allowed") is not False
        or manifest.get("cat_fingerprints") != CAT_FINGERPRINTS
        or type(manifest.get("files")) is not list
    ):
        raise GateError("bundle_manifest_scope_mismatch", "bundle_preflight")
    declared: dict[str, dict[str, Any]] = {}
    for record in manifest["files"]:
        if (
            type(record) is not dict
            or set(record) != {"path", "size_bytes", "sha256"}
            or not isinstance(record.get("path"), str)
            or not _safe_member_name(record["path"])
            or not _allowed_payload_path(record["path"])
            or record["path"] in declared
            or type(record.get("size_bytes")) is not int
            or not isinstance(record.get("sha256"), str)
            or len(record["sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in record["sha256"])
        ):
            raise GateError("bundle_manifest_entry_rejected", "bundle_preflight")
        declared[record["path"]] = record
    actual = set(files) - {"PAYLOAD_MANIFEST.json"}
    if actual != set(declared) or not REQUIRED_PAYLOAD.issubset(actual):
        raise GateError("bundle_file_inventory_mismatch", "bundle_preflight")
    for name, record in declared.items():
        if record["size_bytes"] != len(files[name]) or record["sha256"] != _sha256_bytes(files[name]):
            raise GateError("bundle_file_fingerprint_mismatch", "bundle_preflight")
    computed = {
        "source": _canonical_fingerprint(files),
        "entrypoint": _sha256_bytes(files["release/src/cat_engine/api/app.py"]),
        "config": _sha256_bytes(files["release/fixtures/demo_cat_config.v1.json"]),
        "item_bank": _sha256_bytes(files["release/fixtures/synthetic_item_bank.v1.json"]),
    }
    if computed != CAT_FINGERPRINTS:
        raise GateError("bundle_cat_fingerprint_mismatch", "bundle_preflight")
    _validate_fixture_contract(files)
    _check_unit_bytes(files)
    return manifest, files


def _check_unit_bytes(files: dict[str, bytes]) -> None:
    try:
        unit = files["systemd/psynova-school-cat.service"].decode("utf-8", errors="strict")
    except (KeyError, UnicodeError):
        raise GateError("systemd_unit_invalid", "bundle_preflight") from None
    required = (
        "User=psynova-school-demo",
        "Group=psynova-school-demo",
        "SMHAI_CAT_PORT=8180",
        "MPLCONFIGDIR=/tmp/mplconfig",
        "PrivateTmp=yes",
        "ProtectSystem=strict",
        "NoNewPrivileges=yes",
        "IPAddressDeny=any",
        "IPAddressAllow=127.0.0.1/32",
        "/opt/psynova-school-demo/services/cat/venv/bin/python -m cat_engine.api.app",
    )
    if any(line not in unit for line in required) or "0.0.0.0" in unit or "::" in unit:
        raise GateError("systemd_unit_scope_mismatch", "bundle_preflight")


def _read_state() -> dict[str, Any] | None:
    if not os.path.lexists(STATE_PATH):
        return None
    try:
        metadata = STATE_PATH.stat(follow_symlinks=False)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise GateError("checkpoint_metadata_mismatch", "checkpoint_read")
        state = json.loads(STATE_PATH.read_bytes())
    except GateError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise GateError("checkpoint_unreadable", "checkpoint_read") from None
    if (
        type(state) is not dict
        or state.get("schema") != "psynova.school-cat-install-state.v1"
        or state.get("source_commit") != SOURCE_COMMIT
        or state.get("base_release_revision") != BASE_REVISION
        or state.get("bundle_sha256") != BUNDLE_SHA256
        or state.get("phase") not in PHASES
        or type(state.get("checks")) is not dict
    ):
        raise GateError("checkpoint_identity_mismatch", "checkpoint_read")
    return state


def _write_state(state: dict[str, Any]) -> None:
    if not STATE_PATH.parent.is_dir() or STATE_PATH.parent.is_symlink():
        raise GateError("checkpoint_parent_unavailable", "checkpoint_write")
    _require_root_directory(STATE_PATH.parent, "checkpoint_parent_metadata_mismatch")
    data = json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")
    temporary = STATE_PATH.parent / f".{STATE_PATH.name}.{os.getpid()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temporary, 0, 0)
        os.chmod(temporary, 0o600)
        os.replace(temporary, STATE_PATH)
    except FileExistsError:
        raise GateError("checkpoint_temporary_path_exists", "checkpoint_write") from None
    except OSError:
        raise GateError("checkpoint_write_failed", "checkpoint_write") from None


def _new_state() -> dict[str, Any]:
    return {
        "schema": "psynova.school-cat-install-state.v1",
        "phase": "INITIALIZED",
        "source_commit": SOURCE_COMMIT,
        "base_release_revision": BASE_REVISION,
        "bundle_sha256": BUNDLE_SHA256,
        "python_version": PYTHON_VERSION,
        "checks": {},
        "updated_at_epoch": int(time.time()),
    }


def _checkpoint(state: dict[str, Any], phase: str, **fields: Any) -> None:
    state["phase"] = phase
    state["updated_at_epoch"] = int(time.time())
    state.update(fields)
    _write_state(state)


def _uncheckpointed_objects_exist() -> bool:
    return any(
        os.path.lexists(path)
        for path in (SERVICE_ROOT, UNIT_PATH, UV_CACHE_ROOT.parent)
    )


def _safe_command_environment(**overrides: str) -> dict[str, str]:
    env = {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": "/root",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "UV_NO_PROGRESS": "1",
        "UV_NO_CONFIG": "1",
        "NETRC": "/dev/null",
    }
    env.update(overrides)
    return env


def _uv() -> Path:
    uv = APP_ROOT / "venv" / "bin" / "uv"
    try:
        metadata = uv.stat(follow_symlinks=False)
    except OSError:
        raise GateError("uv_unavailable", "dependencies_install") from None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or not os.access(uv, os.X_OK)
    ):
        raise GateError("uv_metadata_mismatch", "dependencies_install")
    return uv


def _uv_environment() -> dict[str, str]:
    return _safe_command_environment(
        UV_CACHE_DIR=str(UV_CACHE_ROOT),
        UV_PYTHON_INSTALL_DIR=str(PYTHON_ROOT),
        UV_PYTHON_DOWNLOADS="never",
    )


def _python_install_environment() -> dict[str, str]:
    return _safe_command_environment(
        UV_CACHE_DIR=str(UV_CACHE_ROOT),
        UV_PYTHON_INSTALL_DIR=str(PYTHON_ROOT),
    )


def _find_managed_python() -> Path:
    result = _run(
        [str(_uv()), "python", "list", "--only-installed", "--output-format", "json", "--managed-python"],
        phase="python_verify",
        timeout=60,
        env=_uv_environment(),
    )
    try:
        entries = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise GateError("python_inventory_invalid", "python_verify") from None
    if type(entries) is not list:
        raise GateError("python_inventory_invalid", "python_verify")
    candidates = [
        Path(item["path"])
        for item in entries
        if type(item) is dict
        and item.get("version") == PYTHON_VERSION
        and isinstance(item.get("path"), str)
    ]
    if len(candidates) != 1:
        raise GateError("pinned_python_not_unique", "python_verify")
    candidate = candidates[0]
    try:
        resolved = candidate.resolve(strict=True)
        root = PYTHON_ROOT.resolve(strict=True)
        metadata = resolved.stat(follow_symlinks=False)
    except OSError:
        raise GateError("pinned_python_unavailable", "python_verify") from None
    if not resolved.is_relative_to(root) or not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) & 0o022:
        raise GateError("pinned_python_metadata_mismatch", "python_verify")
    return candidate


def _verify_dependencies(python: Path) -> dict[str, Any]:
    _require_root_directory(SERVICE_ROOT, "cat_service_root_metadata_mismatch")
    _require_root_directory(VENV_ROOT, "cat_venv_metadata_mismatch")
    try:
        resolved_python = (VENV_ROOT / "bin" / "python").resolve(strict=True)
        resolved_root = PYTHON_ROOT.resolve(strict=True)
    except OSError:
        raise GateError("cat_venv_python_unavailable", "dependency_verify") from None
    if not resolved_python.is_relative_to(resolved_root):
        raise GateError("cat_venv_python_outside_pinned_runtime", "dependency_verify")
    code = (
        "import importlib.metadata as m, json, sys, cat_engine, adaptivetesting, fastapi, uvicorn; "
        "v=lambda n:m.version(n); "
        "data={'python':'.'.join(map(str,sys.version_info[:3])),'adaptivetesting':v('adaptivetesting'),"
        "'fastapi':v('fastapi'),'uvicorn':v('uvicorn')}; "
        "print(json.dumps(data,sort_keys=True)); "
        "raise SystemExit(0 if data=={"
        f"'python':'{PYTHON_VERSION}','adaptivetesting':'{ADAPTIVETESTING_VERSION}',"
        f"'fastapi':'{FASTAPI_VERSION}','uvicorn':'{UVICORN_VERSION}'"
        "} else 3)"
    )
    result = _run(
        [str(VENV_ROOT / "bin" / "python"), "-c", code],
        phase="dependency_verify",
        timeout=120,
        env=_safe_command_environment(PYTHONPATH=str(RELEASE_ROOT / "src")),
    )
    try:
        facts = json.loads(result.stdout.decode("utf-8").strip().splitlines()[-1])
    except (UnicodeError, json.JSONDecodeError, IndexError):
        raise GateError("dependency_summary_invalid", "dependency_verify") from None
    expected = {
        "python": PYTHON_VERSION,
        "adaptivetesting": ADAPTIVETESTING_VERSION,
        "fastapi": FASTAPI_VERSION,
        "uvicorn": UVICORN_VERSION,
    }
    if type(facts) is not dict or facts != expected:
        raise GateError("dependency_contract_mismatch", "dependency_verify")
    return expected


def _install_dependencies() -> dict[str, Any]:
    uv = _uv()
    try:
        import grp
        import pwd

        service_group = grp.getgrnam("psynova-school-demo")
        service_user = pwd.getpwnam("psynova-school-demo")
    except KeyError:
        raise GateError("service_account_unavailable", "dependencies_install") from None
    if service_user.pw_uid == 0 or service_user.pw_gid != service_group.gr_gid:
        raise GateError("service_account_identity_mismatch", "dependencies_install")
    _require_root_directory(SERVICE_ROOT.parent, "service_parent_metadata_mismatch")
    _ensure_root_directory(SERVICE_ROOT)
    _ensure_root_directory(PYTHON_ROOT)
    _ensure_root_directory(UV_CACHE_ROOT.parent)
    _ensure_root_directory(UV_CACHE_ROOT, mode=0o700)
    _run(
        [
            str(uv), "python", "install", PYTHON_VERSION,
            "--install-dir", str(PYTHON_ROOT), "--no-bin",
        ],
        phase="python_install",
        timeout=1200,
        env=_python_install_environment(),
    )
    python = _find_managed_python()
    if os.path.lexists(VENV_ROOT):
        _require_root_directory(VENV_ROOT, "cat_venv_metadata_mismatch")
    _run(
        [
            str(uv), "sync", "--project", str(RELEASE_ROOT), "--python", str(python),
            "--locked", "--no-dev", "--no-install-project",
        ],
        phase="dependencies_install",
        timeout=1800,
        env=_safe_command_environment(
            UV_CACHE_DIR=str(UV_CACHE_ROOT),
            UV_PYTHON_INSTALL_DIR=str(PYTHON_ROOT),
            UV_PYTHON_DOWNLOADS="never",
            UV_PROJECT_ENVIRONMENT=str(VENV_ROOT),
        ),
    )
    return _verify_dependencies(python)


def _ensure_root_directory(path: Path, mode: int = 0o755) -> None:
    if os.path.lexists(path):
        _require_root_directory(path, "directory_metadata_mismatch", mode)
        return
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise GateError("directory_parent_unavailable", "filesystem_prepare")
    _require_root_directory(path.parent, "directory_parent_metadata_mismatch")
    try:
        path.mkdir(mode=mode)
        os.chown(path, 0, 0)
        os.chmod(path, mode)
    except OSError:
        raise GateError("directory_create_failed", "filesystem_prepare") from None


def _write_file(path: Path, data: bytes, mode: int = 0o644) -> None:
    if os.path.lexists(path):
        try:
            metadata = path.stat(follow_symlinks=False)
            current = path.read_bytes()
        except OSError:
            raise GateError("existing_payload_unavailable", "payload_install") from None
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) != mode
        ):
            raise GateError("existing_payload_metadata_mismatch", "payload_install")
        if current != data:
            raise GateError("existing_payload_content_mismatch", "payload_install")
        return
    _require_root_directory(path.parent, "payload_parent_metadata_mismatch")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, mode)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(path, 0, 0)
        os.chmod(path, mode)
    except FileExistsError:
        raise GateError("payload_destination_appeared", "payload_install") from None
    except OSError:
        raise GateError("payload_write_failed", "payload_install") from None


def _install_payload(files: dict[str, bytes]) -> None:
    _require_root_directory(SERVICE_ROOT.parent, "service_parent_metadata_mismatch")
    _ensure_root_directory(SERVICE_ROOT)
    _ensure_root_directory(RELEASE_ROOT)
    for name, data in files.items():
        if name == "PAYLOAD_MANIFEST.json":
            _write_file(RELEASE_ROOT / name, data)
        elif name.startswith("release/"):
            relative = PurePosixPath(name).relative_to("release")
            destination = RELEASE_ROOT.joinpath(*relative.parts)
            _ensure_payload_parent(destination.parent)
            _write_file(destination, data)
        elif name == "systemd/psynova-school-cat.service":
            _write_file(UNIT_PATH, data)
        else:
            raise GateError("bundle_path_unexpected", "payload_install")


def _ensure_payload_parent(path: Path) -> None:
    if os.path.lexists(path):
        _require_root_directory(path, "payload_parent_metadata_mismatch")
        return
    _ensure_payload_parent(path.parent)
    try:
        path.mkdir(mode=0o755)
        os.chown(path, 0, 0)
        os.chmod(path, 0o755)
    except OSError:
        raise GateError("payload_directory_create_failed", "payload_install") from None


def _check_checkpoint_objects(state: dict[str, Any], files: dict[str, bytes]) -> None:
    phase_index = PHASES.index(state["phase"])
    if phase_index >= PHASES.index("PAYLOAD_READY"):
        for name, data in files.items():
            if name == "PAYLOAD_MANIFEST.json":
                path = RELEASE_ROOT / name
            elif name.startswith("release/"):
                relative = PurePosixPath(name).relative_to("release")
                path = RELEASE_ROOT.joinpath(*relative.parts)
            elif name == "systemd/psynova-school-cat.service":
                path = UNIT_PATH
            else:
                raise GateError("bundle_path_unexpected", "checkpoint_verify")
            try:
                metadata = path.stat(follow_symlinks=False)
                digest = _sha256_file(path)
            except OSError:
                raise GateError("installed_payload_unavailable", "checkpoint_verify") from None
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != 0o644 or digest != _sha256_bytes(data):
                raise GateError("installed_payload_mismatch", "checkpoint_verify")
    if phase_index >= PHASES.index("DEPENDENCIES_READY"):
        python = _find_managed_python()
        facts = _verify_dependencies(python)
        if facts != state.get("dependency_facts"):
            raise GateError("dependency_checkpoint_mismatch", "checkpoint_verify")


def _host_preflight(*, state: dict[str, Any] | None, require_closed_ingress: bool) -> None:
    try:
        hostname = Path("/etc/hostname").read_text(encoding="utf-8").strip()
        revision = (BASE_RELEASE / "SOURCE_REVISION").read_text(encoding="ascii").strip()
    except OSError:
        raise GateError("base_release_unavailable", "host_preflight") from None
    if hostname != "iZ0xic24d9gxb9udjbfo0kZ":
        raise GateError("server_identity_mismatch", "host_preflight")
    if revision != BASE_REVISION:
        raise GateError("base_release_revision_mismatch", "host_preflight")
    systemd = _run(["systemd", "--version"], phase="host_preflight")
    version_line = systemd.stdout.decode("utf-8", errors="replace").splitlines()[0]
    fields = version_line.split()
    if len(fields) < 2 or fields[1] != "255":
        raise GateError("systemd_version_mismatch", "host_preflight")
    if not STATE_PATH.parent.is_dir() or STATE_PATH.parent.is_symlink():
        raise GateError("checkpoint_parent_unavailable", "host_preflight")
    _require_root_directory(STATE_PATH.parent, "checkpoint_parent_metadata_mismatch")
    for service in ("mysql.service", "psynova-school-demo.service", "psynova-school-rag.service", "psynova-school-safety.service"):
        if not _unit_active(service):
            raise GateError("dependency_service_inactive", "host_preflight")
    try:
        import grp
        import pwd

        account = pwd.getpwnam("psynova-school-demo")
        service_group = grp.getgrnam("psynova-school-demo")
    except KeyError:
        raise GateError("service_account_unavailable", "host_preflight") from None
    if account.pw_uid == 0 or account.pw_gid != service_group.gr_gid:
        raise GateError("service_account_identity_mismatch", "host_preflight")
    for port in (3306, 8088, 8170, 8181, 8190):
        _require_port_loopback(port, allow_absent=False)
    _verify_cat_port_for_checkpoint(state)
    if state is None and (_unit_active(SERVICE_NAME) or _unit_enabled(SERVICE_NAME)):
        raise GateError("uncheckpointed_cat_unit", "host_preflight")
    if require_closed_ingress and (
        _unit_active("nginx.service") or _listeners_for_port(80) or _listeners_for_port(443)
    ):
        raise GateError("public_ingress_open_before_application_gates", "host_preflight")
    try:
        available_kib = int(
            next(
                line.split()[1]
                for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines()
                if line.startswith("MemAvailable:")
            )
        )
        free_bytes = shutil.disk_usage("/").free
    except (OSError, StopIteration, ValueError):
        raise GateError("host_resources_unavailable", "host_preflight") from None
    if available_kib < 2_000_000 or free_bytes < 3 * 1024 * 1024 * 1024:
        raise GateError("host_resource_floor_not_met", "host_preflight")


def _verify_cat_port_for_checkpoint(state: dict[str, Any] | None) -> None:
    service_started = (
        state is not None
        and PHASES.index(state["phase"]) >= PHASES.index("SERVICE_STARTED")
    )
    listeners = _listeners_for_port(CAT_PORT)
    if not service_started:
        if listeners:
            raise GateError("cat_port_unexpectedly_in_use", "listener_check")
        return
    if not listeners or any(address != "127.0.0.1:8180" for address in listeners):
        raise GateError("service_listener_not_loopback", "listener_check")


def _verify_unit_file(files: dict[str, bytes]) -> None:
    expected = files["systemd/psynova-school-cat.service"]
    try:
        actual = UNIT_PATH.read_bytes()
    except OSError:
        raise GateError("systemd_unit_unavailable", "unit_verify") from None
    if actual != expected:
        raise GateError("systemd_unit_content_mismatch", "unit_verify")
    _run(["systemd-analyze", "verify", str(UNIT_PATH)], phase="unit_verify")


def _safe_http_json(method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    connection = http.client.HTTPConnection(CAT_URL_HOST, CAT_PORT, timeout=10)
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {} if body is None else {"Content-Type": "application/json"}
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read(256 * 1024 + 1)
        status = response.status
    except (OSError, http.client.HTTPException):
        raise GateError("cat_http_unavailable", "http_verification") from None
    finally:
        connection.close()
    if len(raw) > 256 * 1024:
        raise GateError("cat_http_response_too_large", "http_verification")
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise GateError("cat_http_response_invalid", "http_verification") from None
    if type(document) is not dict:
        raise GateError("cat_http_response_invalid", "http_verification")
    return status, document


def _verify_http_acceptance() -> dict[str, Any]:
    status, health = _safe_http_json("GET", "/health/ready")
    if (
        status != 200
        or health.get("status") != "READY"
        or health.get("provider") != "adaptivetesting"
        or health.get("provider_version") != f"adaptivetesting-{ADAPTIVETESTING_VERSION}"
        or health.get("item_bank_id") != "ITEMBANK_demo_cat"
        or health.get("synthetic_fixture_only") is not True
        or health.get("supports_saved_versions") is not True
    ):
        raise GateError("cat_readiness_contract_mismatch", "http_verification")
    smoke_payload = {
        "assessment_id": "ASSESS_install_smoke_b777317",
        "subject_id": "SUBJ_install_smoke_b777317",
        "instrument_id": "CURRENT_SYNTHETIC_GRM",
        "instrument_version": "synthetic_item_bank.v1 / demo.v1",
    }
    status, session = _safe_http_json("POST", "/internal/cat/sessions", smoke_payload)
    current_item = session.get("current_item")
    if (
        status != 200
        or session.get("assessment_id") != smoke_payload["assessment_id"]
        or session.get("subject_id") != smoke_payload["subject_id"]
        or session.get("status") != "in_progress"
        or session.get("synthetic_fixture_only") is not True
        or session.get("synthetic_engineering_only") is not True
        or type(current_item) is not dict
        or not str(current_item.get("item_id", "")).startswith("ITEM_demo_")
        or any(key in session for key in ("score", "theta", "raw_answers", "report"))
    ):
        raise GateError("cat_synthetic_session_contract_mismatch", "http_verification")
    status, state = _safe_http_json("GET", "/internal/cat/sessions/ASSESS_install_smoke_b777317")
    if status != 200 or state.get("assessment_id") != smoke_payload["assessment_id"]:
        raise GateError("cat_synthetic_session_state_unavailable", "http_verification")
    return {
        "readiness": True,
        "synthetic_session_started": True,
        "synthetic_item_presented": True,
        "assessment_completed": False,
        "scores_or_interpretation_exposed": False,
    }


def _verify_live_service(*, require_enabled: bool = True) -> dict[str, Any]:
    if not _unit_active(SERVICE_NAME):
        raise GateError("cat_service_inactive", "service_verify")
    if require_enabled and not _unit_enabled(SERVICE_NAME):
        raise GateError("cat_service_not_enabled", "service_verify")
    _require_port_loopback(CAT_PORT, allow_absent=False)
    return {"service_active": True, "service_enabled": _unit_enabled(SERVICE_NAME), "listener": "127.0.0.1:8180"}


def _check_state_objects(state: dict[str, Any], files: dict[str, bytes]) -> None:
    _check_checkpoint_objects(state, files)
    phase_index = PHASES.index(state["phase"])
    if phase_index >= PHASES.index("UNIT_READY"):
        _verify_unit_file(files)
    if phase_index >= PHASES.index("SERVICE_STARTED"):
        _verify_live_service(require_enabled=True)


def _inspect(state: dict[str, Any] | None, files: dict[str, bytes]) -> int:
    if state is None:
        if _uncheckpointed_objects_exist():
            raise GateError("uncheckpointed_cat_partial_install", "inspect")
        print(json.dumps({"cat_service": "NOT_INSTALLED", "phase": "inspect", "writes": False}, sort_keys=True))
        return 0
    _check_state_objects(state, files)
    if state["phase"] == "HTTP_VERIFIED":
        live = _verify_live_service()
        checks = _verify_http_acceptance()
        print(json.dumps({"cat_service": "PASS", "phase": state["phase"], "source_commit": SOURCE_COMMIT, "bundle_sha256": BUNDLE_SHA256, "checks": checks, **live, "writes": False}, sort_keys=True))
    else:
        print(json.dumps({"cat_service": "PARTIAL", "phase": state["phase"], "source_commit": SOURCE_COMMIT, "bundle_sha256": BUNDLE_SHA256, "writes": False}, sort_keys=True))
    return 0


def _dry_run(state: dict[str, Any] | None, files: dict[str, bytes]) -> int:
    if state is None and _uncheckpointed_objects_exist():
        raise GateError("uncheckpointed_cat_partial_install", "dry_run")
    if state is not None:
        _check_state_objects(state, files)
    remaining = list(PHASES[1:]) if state is None else list(PHASES[PHASES.index(state["phase"]) + 1 :])
    print(json.dumps({"cat_service": "READY_TO_RESUME", "current_phase": "NOT_STARTED" if state is None else state["phase"], "remaining_phases": remaining, "bundle_sha256": BUNDLE_SHA256, "source_commit": SOURCE_COMMIT, "synthetic_only": True, "writes": False}, sort_keys=True))
    return 0


def _resume(state: dict[str, Any] | None, files: dict[str, bytes]) -> int:
    if state is None:
        if _uncheckpointed_objects_exist():
            raise GateError("uncheckpointed_cat_partial_install", "resume")
        state = _new_state()
        _write_state(state)
    else:
        _check_state_objects(state, files)
    if state["phase"] == "HTTP_VERIFIED":
        checks = _verify_http_acceptance()
        print(json.dumps({"cat_service": "PASS", "phase": "HTTP_VERIFIED", "checks": checks, "writes": False}, sort_keys=True))
        return 0

    _install_payload(files)
    _checkpoint(state, "PAYLOAD_READY", checks={"payload_sha256_verified": True, "synthetic_fixture_contract": True})

    if state.get("dependency_facts") is None:
        dependency_facts = _install_dependencies()
        _checkpoint(state, "DEPENDENCIES_READY", dependency_facts=dependency_facts)
    else:
        python = _find_managed_python()
        dependency_facts = _verify_dependencies(python)
        if dependency_facts != state["dependency_facts"]:
            raise GateError("dependency_checkpoint_mismatch", "dependency_verify")
        _checkpoint(state, "DEPENDENCIES_READY")

    _verify_unit_file(files)
    _checkpoint(state, "UNIT_READY", checks={"systemd_unit_verified": True})
    _run(["systemctl", "daemon-reload"], phase="systemd_reload")
    _run(["systemctl", "enable", "--now", SERVICE_NAME], phase="service_start", timeout=240)
    _checkpoint(state, "SERVICE_STARTED", checks={"systemd_unit_verified": True, "enabled": True})

    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            _verify_live_service()
            break
        except GateError:
            time.sleep(3)
    else:
        raise GateError("cat_service_not_ready", "service_verify")
    checks = _verify_http_acceptance()
    _require_port_loopback(CAT_PORT, allow_absent=False)
    _checkpoint(state, "HTTP_VERIFIED", checks=checks)
    print(json.dumps({"cat_service": "PASS", "phase": "HTTP_VERIFIED", "source_commit": SOURCE_COMMIT, "bundle_sha256": BUNDLE_SHA256, "checks": checks, "listener": "127.0.0.1:8180", "service_active": True, "service_enabled": True, "secrets_logged": False}, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--inspect", action="store_true")
    actions.add_argument("--dry-run", action="store_true")
    actions.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    lock_context = None
    lock_entered = False
    try:
        _require_root_snapshot()
        if args.resume:
            lock_context = _deployment_lock()
            lock_context.__enter__()
            lock_entered = True
        else:
            _check_no_active_lock()
        state = _read_state()
        _, files = _load_bundle()
        _host_preflight(state=state, require_closed_ingress=state is None or state["phase"] != "HTTP_VERIFIED")
        if args.inspect:
            return _inspect(state, files)
        if args.dry_run:
            return _dry_run(state, files)
        return _resume(state, files)
    except GateError as exc:
        print(json.dumps({"error_code": exc.code, "phase": exc.phase, "recovery": "BLOCKED"}, sort_keys=True))
        return 2
    finally:
        if lock_entered and lock_context is not None:
            lock_context.__exit__(None, None, None)


if __name__ == "__main__":
    raise SystemExit(main())
