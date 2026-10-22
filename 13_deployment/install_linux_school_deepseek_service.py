"""Install the pinned DeepSeek school runtime with host-encrypted credentials."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import ipaddress
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tarfile
import time
from pathlib import Path, PurePosixPath
from typing import Any

APP_ROOT = Path("/opt/psynova-school-demo")
BASE_RELEASE = APP_ROOT / "release"
BASE_REVISION = "f3047642aa3466f9b4f210f4f704d57fd2cdf3cc"
SOURCE_COMMIT = "83620b8fe3adf34fc252b17348861799d33bf1e4"
SERVICE_ROOT = APP_ROOT / "services" / "llm"
RELEASE_ROOT = SERVICE_ROOT / "release"
VENV_ROOT = SERVICE_ROOT / "venv"
UV_CACHE_ROOT = Path("/var/cache/psynova-school-llm/uv")
UNIT_PATH = Path("/etc/systemd/system/psynova-school-llm.service")
BACKEND_DROPIN = Path(
    "/etc/systemd/system/psynova-school-demo.service.d/20-llm.conf"
)
RESOLVER_DROPIN = Path(
    "/etc/systemd/system/psynova-school-llm.service.d/10-resolver.conf"
)
RESOLVER_DROPIN_DATA = b"[Service]\nIPAddressAllow=127.0.0.53/32\n"
STATE_PATH = Path("/var/lib/psynova-school-demo/deepseek-install-state.json")
LOCK_PATH = Path("/run/lock/psynova-school-llm-install.lock")
CREDENTIAL_ROOT = Path("/etc/credstore.encrypted")
API_CREDENTIAL = CREDENTIAL_ROOT / "psynova-school-deepseek-api-key.cred"
API_CREDENTIAL_NAME = "deepseek-api-key"
RUNTIME_CREDENTIAL = CREDENTIAL_ROOT / "psynova-school-llm-runtime-auth.cred"
RUNTIME_CREDENTIAL_NAME = "llm-runtime-auth.json"
BACKEND_HTTP_VERIFIER = BASE_RELEASE / "13_deployment" / "verify_school_http_linux.py"
BACKEND_HTTP_VERIFIER_SHA256 = "da6325afd3230656f7423617b19fd6b94d70da8a20ced6bffb72859b9c22fa46"
BUNDLE_PATH = Path(
    "/home/psynova/apps/psynova/staging/linux-school-demo/"
    "psynova-school-deepseek-83620b8.tar.gz"
)
BUNDLE_SHA256 = "ad0d89b613029122b6b38f710ad4771f4b5ba959b174fa76c00f743726387e59"
PREVIOUS_BUNDLE_SHA256 = "d99f10cb151b2dcf1cda638346d8e80745a924d2981ef7d00cfd96259002fccb"
PREVIOUS_PAYLOAD_FINGERPRINT = "35dbe4020173b09abfc71ce10a49114f4aeb0cb37f403aa76a658f5b79e22269"
PYTHON_VERSION = "3.12.3"
MODEL_ID = "deepseek-flash"
LOGICAL_MODEL_ID = "deepseek-flash-education-support"
API_BASE_URL = "https://api.deepseek.com"
API_ALLOWED_IPV4 = {"3.173.21.63"}
SERVICE_NAME = "psynova-school-llm.service"
BACKEND_SERVICE = "psynova-school-demo.service"
LLM_PORT = 8160
API_KEY_PATTERN = re.compile(rb"sk-[A-Za-z0-9_-]{20,128}\Z")
TOKEN_PATTERN = re.compile(rb"[A-Za-z0-9_-]{32,128}\Z")
MAX_BUNDLE_SIZE = 16 * 1024 * 1024
MAX_MEMBER_SIZE = 5 * 1024 * 1024
MAX_TOTAL_SIZE = 12 * 1024 * 1024
PHASES = (
    "INITIALIZED",
    "PAYLOAD_READY",
    "DEPENDENCIES_READY",
    "API_CREDENTIAL_PENDING",
    "API_CREDENTIAL_READY",
    "RUNTIME_CREDENTIAL_PENDING",
    "CREDENTIALS_READY",
    "UNIT_READY",
    "LLM_SERVICE_STARTED",
    "BACKEND_SWITCHED",
    "BACKEND_HTTP_VERIFIED",
    "HTTP_VERIFIED",
)
REQUIRED_FILES = {
    "release/README.md",
    "release/pyproject.toml",
    "release/uv.lock",
    "release/config/runtime.v1.json",
    "release/config/models.deepseek.v1.json",
    "systemd/psynova-school-llm.service",
    "systemd/psynova-school-demo-llm.conf",
}
REQUIRED_MODULES = {
    "release/src/llm_runtime/api/app.py",
    "release/src/llm_runtime/cli.py",
    "release/src/llm_runtime/providers/deepseek.py",
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
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            args,
            input=input_bytes,
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
        suffix = resolved.stem.removeprefix("install_linux_school_deepseek_service_")
        app_root = APP_ROOT.resolve(strict=True)
    except OSError:
        raise GateError("root_snapshot_unavailable", "startup") from None
    if (
        resolved.parent != app_root
        or not resolved.name.startswith("install_linux_school_deepseek_service_")
        or len(suffix) != 64
        or any(c not in "0123456789abcdef" for c in suffix)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o500
        or _sha256_file(resolved) != suffix
    ):
        raise GateError("root_snapshot_fingerprint_mismatch", "startup")
    for path, code in (
        (Path("/opt"), "application_parent_metadata_mismatch"),
        (APP_ROOT, "application_root_metadata_mismatch"),
        (BASE_RELEASE, "base_release_metadata_mismatch"),
    ):
        _require_root_directory(path, code)


@contextlib.contextmanager
def _deployment_lock():
    import fcntl

    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
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


def _require_loopback_port(port: int, *, allow_absent: bool) -> None:
    listeners = _listeners_for_port(port)
    if not listeners and allow_absent:
        return
    if not listeners or any(address != f"127.0.0.1:{port}" for address in listeners):
        raise GateError("service_listener_not_loopback", "listener_check")


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        bool(name)
        and not path.is_absolute()
        and ".." not in path.parts
        and "\\" not in name
        and "" not in path.parts
    )


def _allowed_payload(name: str) -> bool:
    return (
        name in REQUIRED_FILES
        or name.startswith("release/src/llm_runtime/") and name.endswith(".py")
    )


def _payload_fingerprint(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name in sorted(files):
        data = files[name].replace(b"\r\n", b"\n")
        relative = name.encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _check_unit(files: dict[str, bytes]) -> None:
    try:
        unit = files["systemd/psynova-school-llm.service"].decode("utf-8", errors="strict")
        dropin = files["systemd/psynova-school-demo-llm.conf"].decode("utf-8", errors="strict")
    except (KeyError, UnicodeError):
        raise GateError("llm_unit_invalid", "bundle_preflight") from None
    required = (
        "DynamicUser=yes",
        "SMHAI_LLM_PROVIDER=deepseek",
        "SMHAI_LLM_PORT=8160",
        "LoadCredentialEncrypted=deepseek-api-key:/etc/credstore.encrypted/psynova-school-deepseek-api-key.cred",
        "LoadCredentialEncrypted=llm-runtime-auth.json:/etc/credstore.encrypted/psynova-school-llm-runtime-auth.cred",
        "IPAddressDeny=any",
        "IPAddressAllow=127.0.0.1/32",
        "IPAddressAllow=3.173.21.63/32",
        "/opt/psynova-school-demo/services/llm/venv/bin/python",
    )
    if any(line not in unit for line in required):
        raise GateError("llm_unit_scope_mismatch", "bundle_preflight")
    if any(value in unit for value in ("API_KEY=", "0.0.0.0/0", "127.0.0.1:8160")):
        raise GateError("llm_unit_scope_mismatch", "bundle_preflight")
    expected_dropin = (
        "[Service]\n"
        "Environment=PSYNOVA_LLM_MODEL_ID=deepseek-flash-education-support\n"
        "LoadCredentialEncrypted=llm-runtime-auth.json:/etc/credstore.encrypted/"
        "psynova-school-llm-runtime-auth.cred\n"
    )
    if dropin.replace("\r\n", "\n") != expected_dropin:
        raise GateError("backend_dropin_scope_mismatch", "bundle_preflight")


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
    total_size = 0
    try:
        with tarfile.open(BUNDLE_PATH, mode="r:gz") as archive:
            for member in archive.getmembers():
                if not _safe_member(member.name) or not member.isfile():
                    raise GateError("bundle_member_rejected", "bundle_preflight")
                if member.size < 0 or member.size > MAX_MEMBER_SIZE:
                    raise GateError("bundle_member_size_rejected", "bundle_preflight")
                total_size += member.size
                if total_size > MAX_TOTAL_SIZE or member.name in files:
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
        or manifest.get("schema") != "psynova.school-deepseek-bundle.v1"
        or manifest.get("source_commit") != SOURCE_COMMIT
        or manifest.get("python_version") != PYTHON_VERSION
        or manifest.get("provider") != "deepseek"
        or manifest.get("model_id") != MODEL_ID
        or manifest.get("api_base_url") != API_BASE_URL
        or manifest.get("synthetic_demo_only") is not True
        or manifest.get("cloud_fallback") is not False
        or type(manifest.get("files")) is not list
    ):
        raise GateError("bundle_manifest_scope_mismatch", "bundle_preflight")
    declared: dict[str, dict[str, Any]] = {}
    for record in manifest["files"]:
        if (
            type(record) is not dict
            or set(record) != {"path", "size_bytes", "sha256"}
            or not isinstance(record.get("path"), str)
            or not _safe_member(record["path"])
            or not _allowed_payload(record["path"])
            or record["path"] in declared
            or type(record.get("size_bytes")) is not int
            or not isinstance(record.get("sha256"), str)
            or len(record["sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in record["sha256"])
        ):
            raise GateError("bundle_manifest_entry_rejected", "bundle_preflight")
        declared[record["path"]] = record
    actual = set(files) - {"PAYLOAD_MANIFEST.json"}
    if actual != set(declared) or not REQUIRED_FILES.issubset(actual) or not REQUIRED_MODULES.issubset(actual):
        raise GateError("bundle_file_inventory_mismatch", "bundle_preflight")
    for name, record in declared.items():
        if record["size_bytes"] != len(files[name]) or record["sha256"] != _sha256_bytes(files[name]):
            raise GateError("bundle_file_fingerprint_mismatch", "bundle_preflight")
    if manifest.get("payload_fingerprint") != _payload_fingerprint(
        {name: data for name, data in files.items() if name != "PAYLOAD_MANIFEST.json"}
    ):
        raise GateError("bundle_payload_fingerprint_mismatch", "bundle_preflight")
    try:
        model = json.loads(files["release/config/models.deepseek.v1.json"])
        runtime = json.loads(files["release/config/runtime.v1.json"])
    except (UnicodeError, json.JSONDecodeError):
        raise GateError("deepseek_model_config_invalid", "bundle_preflight") from None
    if (
        type(model) is not dict
        or model.get("cloud_fallback") is not False
        or type(model.get("models")) is not list
        or len(model["models"]) != 1
        or model["models"][0].get("logical_model_id") != LOGICAL_MODEL_ID
        or model["models"][0].get("provider_model_id") != MODEL_ID
        or model["models"][0].get("enabled") is not True
        or model["models"][0].get("fallback_eligible") is not False
    ):
        raise GateError("deepseek_model_scope_mismatch", "bundle_preflight")
    if type(runtime) is not dict or runtime.get("cloud_fallback") is not False:
        raise GateError("llm_runtime_config_scope_mismatch", "bundle_preflight")
    _check_unit(files)
    return manifest, files


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
        or state.get("schema") != "psynova.school-deepseek-install-state.v1"
        or state.get("source_commit") != SOURCE_COMMIT
        or state.get("base_revision") != BASE_REVISION
        or state.get("bundle_sha256") not in {BUNDLE_SHA256, PREVIOUS_BUNDLE_SHA256}
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
    temp = STATE_PATH.parent / f".{STATE_PATH.name}.{os.getpid()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(temp, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temp, 0, 0)
        os.chmod(temp, 0o600)
        os.replace(temp, STATE_PATH)
    except FileExistsError:
        raise GateError("checkpoint_temporary_path_exists", "checkpoint_write") from None
    except OSError:
        raise GateError("checkpoint_write_failed", "checkpoint_write") from None


def _new_state() -> dict[str, Any]:
    return {
        "schema": "psynova.school-deepseek-install-state.v1",
        "phase": "INITIALIZED",
        "source_commit": SOURCE_COMMIT,
        "base_revision": BASE_REVISION,
        "bundle_sha256": BUNDLE_SHA256,
        "checks": {},
        "updated_at_epoch": int(time.time()),
    }


def _checkpoint(state: dict[str, Any], phase: str, **fields: Any) -> None:
    state["phase"] = phase
    state["updated_at_epoch"] = int(time.time())
    state.update(fields)
    _write_state(state)


def _safe_environment(**overrides: str) -> dict[str, str]:
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


def _ensure_nested_directory(path: Path) -> None:
    if os.path.lexists(path):
        _require_root_directory(path, "payload_directory_metadata_mismatch")
        return
    _ensure_nested_directory(path.parent)
    try:
        path.mkdir(mode=0o755)
        os.chown(path, 0, 0)
        os.chmod(path, 0o755)
    except OSError:
        raise GateError("payload_directory_create_failed", "payload_install") from None


def _write_payload_file(path: Path, data: bytes, mode: int = 0o644) -> None:
    if os.path.lexists(path):
        try:
            metadata = path.stat(follow_symlinks=False)
            current = path.read_bytes()
        except OSError:
            raise GateError("existing_payload_unavailable", "payload_install") from None
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != mode:
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


def _replace_payload_manifest(path: Path, data: bytes, *, allow_bundle_upgrade: bool) -> None:
    if not os.path.lexists(path):
        _write_payload_file(path, data)
        return
    try:
        metadata = path.stat(follow_symlinks=False)
        current = path.read_bytes()
    except OSError:
        raise GateError("existing_payload_unavailable", "payload_install") from None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o644
    ):
        raise GateError("existing_payload_metadata_mismatch", "payload_install")
    if current == data:
        return
    if not allow_bundle_upgrade:
        raise GateError("existing_payload_content_mismatch", "payload_install")
    try:
        existing = json.loads(current)
        expected = json.loads(data)
    except (UnicodeError, json.JSONDecodeError):
        raise GateError("payload_manifest_upgrade_rejected", "payload_install") from None
    if (
        type(existing) is not dict
        or type(expected) is not dict
        or existing.get("source_commit") != SOURCE_COMMIT
        or expected.get("source_commit") != SOURCE_COMMIT
        or existing.get("payload_fingerprint")
        not in {PREVIOUS_PAYLOAD_FINGERPRINT, expected.get("payload_fingerprint")}
    ):
        raise GateError("payload_manifest_upgrade_rejected", "payload_install")
    temp = path.parent / f".{path.name}.{os.getpid()}.upgrade.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(temp, flags, 0o644)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temp, 0, 0)
        os.chmod(temp, 0o644)
        os.replace(temp, path)
    except FileExistsError:
        raise GateError("payload_manifest_temporary_path_exists", "payload_install") from None
    except OSError:
        raise GateError("payload_manifest_upgrade_failed", "payload_install") from None


def _install_payload(
    files: dict[str, bytes], *, allow_bundle_upgrade: bool = False
) -> None:
    _require_root_directory(SERVICE_ROOT.parent, "service_parent_metadata_mismatch")
    _ensure_root_directory(SERVICE_ROOT)
    _ensure_root_directory(RELEASE_ROOT)
    for name, data in files.items():
        if name == "PAYLOAD_MANIFEST.json":
            continue
        elif name.startswith("release/"):
            relative = PurePosixPath(name).relative_to("release")
            path = RELEASE_ROOT.joinpath(*relative.parts)
            _ensure_nested_directory(path.parent)
            _write_payload_file(path, data)
        elif name == "systemd/psynova-school-llm.service":
            _write_payload_file(UNIT_PATH, data)
        elif name == "systemd/psynova-school-demo-llm.conf":
            _ensure_root_directory(BACKEND_DROPIN.parent)
            _write_payload_file(BACKEND_DROPIN, data)
        else:
            raise GateError("payload_path_unexpected", "payload_install")
    _replace_payload_manifest(
        RELEASE_ROOT / "PAYLOAD_MANIFEST.json",
        files["PAYLOAD_MANIFEST.json"],
        allow_bundle_upgrade=allow_bundle_upgrade,
    )


def _uv() -> Path:
    path = APP_ROOT / "venv" / "bin" / "uv"
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError:
        raise GateError("uv_unavailable", "dependencies_install") from None
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) & 0o022 or not os.access(path, os.X_OK):
        raise GateError("uv_metadata_mismatch", "dependencies_install")
    return path


def _verify_dependencies() -> dict[str, str]:
    code = (
        "import importlib.metadata as m, json, sys, fastapi, httpx, psutil, uvicorn, llm_runtime; "
        "v=lambda n:m.version(n); "
        "d={'python':'.'.join(map(str,sys.version_info[:3])),'fastapi':v('fastapi'),"
        "'httpx':v('httpx'),'psutil':v('psutil'),'uvicorn':v('uvicorn')}; "
        "print(json.dumps(d,sort_keys=True)); "
        "raise SystemExit(0 if d=={'python':'3.12.3','fastapi':'0.141.1','httpx':'0.28.1',"
        "'psutil':'7.0.0','uvicorn':'0.52.4'} else 3)"
    )
    result = _run(
        [str(VENV_ROOT / "bin" / "python"), "-c", code],
        phase="dependency_verify",
        timeout=120,
        env=_safe_environment(
            PYTHONPATH=f"{RELEASE_ROOT / 'src'}:{BASE_RELEASE / '13_deployment'}"
        ),
    )
    try:
        summary = json.loads(result.stdout.decode("utf-8").strip().splitlines()[-1])
    except (UnicodeError, json.JSONDecodeError, IndexError):
        raise GateError("dependency_summary_invalid", "dependency_verify") from None
    expected = {
        "python": PYTHON_VERSION,
        "fastapi": "0.141.1",
        "httpx": "0.28.1",
        "psutil": "7.0.0",
        "uvicorn": "0.52.4",
    }
    if type(summary) is not dict or summary != expected:
        raise GateError("dependency_contract_mismatch", "dependency_verify")
    return expected


def _install_dependencies() -> dict[str, str]:
    uv = _uv()
    python = Path("/usr/bin/python3.12")
    if not python.is_file() or python.is_symlink():
        raise GateError("system_python_unavailable", "dependencies_install")
    _require_root_directory(SERVICE_ROOT.parent, "service_parent_metadata_mismatch")
    _ensure_root_directory(SERVICE_ROOT)
    _ensure_root_directory(UV_CACHE_ROOT.parent)
    _ensure_root_directory(UV_CACHE_ROOT, mode=0o700)
    _run(
        [
            str(uv), "sync", "--project", str(RELEASE_ROOT), "--python", str(python),
            "--locked", "--no-dev", "--no-install-project",
        ],
        phase="dependencies_install",
        timeout=1800,
        env=_safe_environment(
            UV_CACHE_DIR=str(UV_CACHE_ROOT),
            UV_PROJECT_ENVIRONMENT=str(VENV_ROOT),
            UV_PYTHON_DOWNLOADS="never",
        ),
    )
    return _verify_dependencies()


def _encrypt_credential(name: str, plaintext: bytes | bytearray) -> bytes:
    result = subprocess.run(
        ["systemd-creds", "--with-key=host", f"--name={name}", "encrypt", "-", "-"],
        input=bytes(plaintext),
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode or not result.stdout:
        raise GateError("credential_encryption_failed", "credentials_prepare")
    return result.stdout


def _decrypt_credential(path: Path, name: str) -> bytearray:
    result = subprocess.run(
        ["systemd-creds", "decrypt", f"--name={name}", str(path), "-"],
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode:
        raise GateError("credential_decryption_failed", "credentials_verify")
    return bytearray(result.stdout)


def _credential_stage_path(path: Path, sha256: str) -> Path:
    return path.parent / f".{path.name}.{sha256[:16]}.encrypted-stage"


def _write_credential(path: Path, data: bytes, expected_sha256: str) -> None:
    _require_root_directory(CREDENTIAL_ROOT, "credential_directory_metadata_mismatch", 0o700)
    stage = _credential_stage_path(path, expected_sha256)
    if os.path.lexists(path):
        try:
            metadata = path.stat(follow_symlinks=False)
        except OSError:
            raise GateError("credential_metadata_unavailable", "credentials_write") from None
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) != 0o400
            or _sha256_file(path) != expected_sha256
        ):
            raise GateError("existing_credential_mismatch", "credentials_write")
        if os.path.lexists(stage):
            _remove_owned_encrypted_stage(stage, expected_sha256)
        return
    if not os.path.lexists(stage):
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(stage, flags, 0o400)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chown(stage, 0, 0)
            os.chmod(stage, 0o400)
        except FileExistsError:
            raise GateError("credential_stage_appeared", "credentials_write") from None
        except OSError:
            raise GateError("credential_stage_write_failed", "credentials_write") from None
    _remove_owned_encrypted_stage(stage, expected_sha256, keep=True)
    try:
        os.link(stage, path, follow_symlinks=False)
        os.unlink(stage)
    except FileExistsError:
        raise GateError("credential_destination_appeared", "credentials_write") from None
    except OSError:
        raise GateError("credential_link_failed", "credentials_write") from None
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError:
        raise GateError("credential_destination_unavailable", "credentials_write") from None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o400
        or _sha256_file(path) != expected_sha256
    ):
        raise GateError("credential_destination_mismatch", "credentials_write")


def _remove_owned_encrypted_stage(path: Path, expected_sha256: str, *, keep: bool = False) -> None:
    try:
        metadata = path.stat(follow_symlinks=False)
        digest = _sha256_file(path)
    except OSError:
        raise GateError("credential_stage_unavailable", "credentials_write") from None
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != 0o400 or digest != expected_sha256:
        raise GateError("credential_stage_mismatch", "credentials_write")
    if not keep:
        try:
            path.unlink()
        except OSError:
            raise GateError("credential_stage_cleanup_failed", "credentials_write") from None


def _validate_credential(path: Path, name: str, kind: str, expected_sha256: str) -> None:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError:
        raise GateError("credential_unavailable", "credentials_verify") from None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o400
        or _sha256_file(path) != expected_sha256
    ):
        raise GateError("credential_metadata_or_fingerprint_mismatch", "credentials_verify")
    value = _decrypt_credential(path, name)
    try:
        raw = bytes(value).rstrip(b"\r\n")
        valid = bool(API_KEY_PATTERN.fullmatch(raw)) if kind == "api_key" else bool(TOKEN_PATTERN.fullmatch(raw))
    finally:
        for index in range(len(value)):
            value[index] = 0
    if not valid:
        raise GateError("credential_payload_malformed", "credentials_verify")


def _credential_from_state(
    state: dict[str, Any],
    *,
    state_hash_key: str,
    pending_hash_key: str,
    path: Path,
    name: str,
    kind: str,
    ready_phase: str,
) -> bool:
    expected = state.get(state_hash_key) or state.get(pending_hash_key)
    if not isinstance(expected, str) or len(expected) != 64:
        if os.path.lexists(path):
            raise GateError("uncheckpointed_credential_object", "credentials_verify")
        return False
    if not os.path.lexists(path):
        stage = _credential_stage_path(path, expected)
        if os.path.lexists(stage):
            _remove_owned_encrypted_stage(stage, expected, keep=True)
            try:
                os.link(stage, path, follow_symlinks=False)
                os.unlink(stage)
            except OSError:
                raise GateError("credential_resume_link_failed", "credentials_verify") from None
        else:
            if state.get(state_hash_key) is not None:
                raise GateError("credential_checkpoint_object_missing", "credentials_verify")
            return False
    _validate_credential(path, name, kind, expected)
    changed = state.get(state_hash_key) != expected or pending_hash_key in state
    state.pop(pending_hash_key, None)
    state[state_hash_key] = expected
    if changed:
        _checkpoint(state, ready_phase)
    return True


def _await_api_key() -> bytearray:
    print(json.dumps({"status": "API_KEY_REQUIRED", "phase": "credential_input"}), flush=True)
    try:
        value = bytearray(sys.stdin.buffer.read(257))
    except OSError:
        raise GateError("credential_input_unavailable", "credential_input") from None
    while value.startswith((b"\r", b"\n")):
        value.pop(0)
    while value.endswith((b"\r", b"\n")):
        value.pop()
    if len(value) > 256 or not _valid_api_key(bytes(value)):
        for index in range(len(value)):
            value[index] = 0
        raise GateError("credential_input_malformed", "credential_input")
    return value


def _valid_api_key(value: bytes) -> bool:
    return len(value) <= 256 and API_KEY_PATTERN.fullmatch(value) is not None


def _valid_runtime_token(value: bytes) -> bool:
    return TOKEN_PATTERN.fullmatch(value.rstrip(b"\r\n")) is not None


def _uncheckpointed_objects_exist() -> bool:
    if any(
        os.path.lexists(path)
        for path in (
            SERVICE_ROOT,
            UNIT_PATH,
            BACKEND_DROPIN,
            RESOLVER_DROPIN,
            API_CREDENTIAL,
            RUNTIME_CREDENTIAL,
            UV_CACHE_ROOT.parent,
        )
    ):
        return True
    if any(STATE_PATH.parent.glob(f".{STATE_PATH.name}.*.tmp")):
        return True
    return bool(any(CREDENTIAL_ROOT.glob(".*.encrypted-stage")))


def _installed_payload_path(name: str) -> Path:
    if name.startswith("release/"):
        return RELEASE_ROOT.joinpath(*PurePosixPath(name).relative_to("release").parts)
    if name == "systemd/psynova-school-llm.service":
        return UNIT_PATH
    if name == "systemd/psynova-school-demo-llm.conf":
        return BACKEND_DROPIN
    raise GateError("bundle_path_unexpected", "checkpoint_verify")


def _verify_upgrade_payload_file(name: str, record: dict[str, Any]) -> None:
    path = _installed_payload_path(name)
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError:
        raise GateError("installed_payload_unavailable", "checkpoint_verify") from None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o644
        or metadata.st_size != record.get("size_bytes")
        or _sha256_file(path) != record.get("sha256")
    ):
        raise GateError("installed_payload_mismatch", "checkpoint_verify")


def _verify_previous_bundle_upgrade(state: dict[str, Any], files: dict[str, bytes]) -> None:
    if state.get("bundle_sha256") != PREVIOUS_BUNDLE_SHA256:
        return
    if PHASES.index(state["phase"]) > PHASES.index("LLM_SERVICE_STARTED"):
        raise GateError("bundle_upgrade_checkpoint_phase_rejected", "checkpoint_verify")
    try:
        manifest_path = RELEASE_ROOT / "PAYLOAD_MANIFEST.json"
        metadata = manifest_path.stat(follow_symlinks=False)
        installed_bytes = manifest_path.read_bytes()
        installed_manifest = json.loads(installed_bytes)
        next_manifest = json.loads(files["PAYLOAD_MANIFEST.json"])
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError):
        raise GateError("bundle_upgrade_manifest_unavailable", "checkpoint_verify") from None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o644
        or type(installed_manifest) is not dict
        or type(next_manifest) is not dict
        or installed_manifest.get("source_commit") != SOURCE_COMMIT
        or next_manifest.get("source_commit") != SOURCE_COMMIT
        or next_manifest.get("payload_fingerprint") != _payload_fingerprint(
            {name: data for name, data in files.items() if name != "PAYLOAD_MANIFEST.json"}
        )
        or type(installed_manifest.get("files")) is not list
        or type(next_manifest.get("files")) is not list
    ):
        raise GateError("bundle_upgrade_manifest_mismatch", "checkpoint_verify")
    previous_records = {
        item.get("path"): item
        for item in installed_manifest["files"]
        if type(item) is dict and isinstance(item.get("path"), str)
    }
    next_records = {
        item.get("path"): item
        for item in next_manifest["files"]
        if type(item) is dict and isinstance(item.get("path"), str)
    }
    if (
        len(previous_records) != len(installed_manifest["files"])
        or len(next_records) != len(next_manifest["files"])
    ):
        raise GateError("bundle_upgrade_manifest_mismatch", "checkpoint_verify")
    if installed_manifest.get("payload_fingerprint") == PREVIOUS_PAYLOAD_FINGERPRINT:
        if set(next_records) - set(previous_records) != {"release/config/runtime.v1.json"}:
            raise GateError("bundle_upgrade_file_delta_mismatch", "checkpoint_verify")
        if set(previous_records) != set(next_records) - {"release/config/runtime.v1.json"}:
            raise GateError("bundle_upgrade_file_delta_mismatch", "checkpoint_verify")
        for name, record in previous_records.items():
            if not isinstance(name, str) or type(record) is not dict:
                raise GateError("bundle_upgrade_manifest_mismatch", "checkpoint_verify")
            if record != next_records.get(name):
                raise GateError("bundle_upgrade_existing_file_changed", "checkpoint_verify")
            _verify_upgrade_payload_file(name, record)
        added_record = next_records["release/config/runtime.v1.json"]
        if type(added_record) is not dict:
            raise GateError("bundle_upgrade_manifest_mismatch", "checkpoint_verify")
        added_path = _installed_payload_path("release/config/runtime.v1.json")
        if os.path.lexists(added_path):
            _verify_upgrade_payload_file("release/config/runtime.v1.json", added_record)
    elif (
        installed_bytes == files["PAYLOAD_MANIFEST.json"]
        and installed_manifest.get("payload_fingerprint")
        == next_manifest.get("payload_fingerprint")
    ):
        for name, record in next_records.items():
            if not isinstance(name, str) or type(record) is not dict:
                raise GateError("bundle_upgrade_manifest_mismatch", "checkpoint_verify")
            _verify_upgrade_payload_file(name, record)
    else:
        raise GateError("bundle_upgrade_manifest_mismatch", "checkpoint_verify")


def _check_state_objects(state: dict[str, Any], files: dict[str, bytes]) -> None:
    phase_index = PHASES.index(state["phase"])
    if phase_index >= PHASES.index("PAYLOAD_READY"):
        if state.get("bundle_sha256") == PREVIOUS_BUNDLE_SHA256:
            _verify_previous_bundle_upgrade(state, files)
        else:
            for name, data in files.items():
                path = RELEASE_ROOT / name if name == "PAYLOAD_MANIFEST.json" else _installed_payload_path(name)
                try:
                    metadata = path.stat(follow_symlinks=False)
                except OSError:
                    raise GateError("installed_payload_unavailable", "checkpoint_verify") from None
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_uid != 0
                    or stat.S_IMODE(metadata.st_mode) != 0o644
                    or _sha256_file(path) != _sha256_bytes(data)
                ):
                    raise GateError("installed_payload_mismatch", "checkpoint_verify")
    if phase_index >= PHASES.index("DEPENDENCIES_READY"):
        facts = _verify_dependencies()
        if facts != state.get("dependency_facts"):
            raise GateError("dependency_checkpoint_mismatch", "checkpoint_verify")
    if phase_index >= PHASES.index("API_CREDENTIAL_READY"):
        _credential_from_state(
            state,
            state_hash_key="api_credential_sha256",
            pending_hash_key="api_credential_pending_sha256",
            path=API_CREDENTIAL,
            name=API_CREDENTIAL_NAME,
            kind="api_key",
            ready_phase="API_CREDENTIAL_READY",
        )
    if phase_index >= PHASES.index("RUNTIME_CREDENTIAL_PENDING"):
        _credential_from_state(
            state,
            state_hash_key="runtime_credential_sha256",
            pending_hash_key="runtime_credential_pending_sha256",
            path=RUNTIME_CREDENTIAL,
            name=RUNTIME_CREDENTIAL_NAME,
            kind="token",
            ready_phase="CREDENTIALS_READY",
        )
    if phase_index >= PHASES.index("UNIT_READY"):
        for path in (UNIT_PATH, BACKEND_DROPIN):
            if not path.is_file() or path.is_symlink():
                raise GateError("systemd_payload_unavailable", "checkpoint_verify")
        if _sha256_file(UNIT_PATH) != state.get("unit_sha256") or _sha256_file(BACKEND_DROPIN) != state.get("backend_dropin_sha256"):
            raise GateError("systemd_payload_mismatch", "checkpoint_verify")
        resolver_digest = state.get("resolver_dropin_sha256")
        if resolver_digest is None:
            if state["phase"] != "LLM_SERVICE_STARTED" or os.path.lexists(RESOLVER_DROPIN):
                raise GateError("resolver_dropin_checkpoint_missing", "checkpoint_verify")
        else:
            try:
                metadata = RESOLVER_DROPIN.stat(follow_symlinks=False)
            except OSError:
                raise GateError("resolver_dropin_unavailable", "checkpoint_verify") from None
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != 0
                or stat.S_IMODE(metadata.st_mode) != 0o644
                or _sha256_file(RESOLVER_DROPIN) != resolver_digest
                or resolver_digest != _sha256_bytes(RESOLVER_DROPIN_DATA)
            ):
                raise GateError("resolver_dropin_mismatch", "checkpoint_verify")
    if phase_index >= PHASES.index("LLM_SERVICE_STARTED"):
        if state["phase"] == "LLM_SERVICE_STARTED":
            if not _unit_enabled(SERVICE_NAME):
                raise GateError("llm_service_not_enabled", "checkpoint_verify")
            _verify_unit_files()
            if _unit_active(SERVICE_NAME):
                try:
                    _verify_llm_service(require_enabled=True)
                except GateError:
                    _require_loopback_port(LLM_PORT, allow_absent=False)
        else:
            _verify_llm_service(require_enabled=True)
    if phase_index >= PHASES.index("BACKEND_SWITCHED") and not _unit_active(BACKEND_SERVICE):
        raise GateError("backend_service_inactive", "checkpoint_verify")
    if phase_index >= PHASES.index("BACKEND_HTTP_VERIFIED"):
        checks = state.get("checks")
        if (
            type(checks) is not dict
            or checks.get("backend_http_smoke") is not True
            or checks.get("authenticated_accounts") != 8
            or checks.get("role_boundaries") is not True
            or checks.get("csrf_enforcement") is not True
            or checks.get("session_after_restart") is not True
        ):
            raise GateError("backend_http_checkpoint_mismatch", "checkpoint_verify")


def _dns_ipv4_addresses() -> set[str]:
    result = _run(["getent", "ahostsv4", "api.deepseek.com"], phase="egress_preflight")
    addresses = {
        line.split()[0]
        for line in result.stdout.decode("ascii", errors="replace").splitlines()
        if line.split()
    }
    try:
        normalized = {str(ipaddress.IPv4Address(value)) for value in addresses}
    except ipaddress.AddressValueError:
        raise GateError("deepseek_dns_response_invalid", "egress_preflight") from None
    return normalized


def _host_preflight(*, state: dict[str, Any] | None) -> None:
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
    fields = systemd.stdout.decode("utf-8", errors="replace").splitlines()[0].split()
    if len(fields) < 2 or fields[1] != "255":
        raise GateError("systemd_version_mismatch", "host_preflight")
    if not STATE_PATH.parent.is_dir() or STATE_PATH.parent.is_symlink():
        raise GateError("checkpoint_parent_unavailable", "host_preflight")
    _require_root_directory(STATE_PATH.parent, "checkpoint_parent_metadata_mismatch")
    _require_root_directory(CREDENTIAL_ROOT, "credential_directory_metadata_mismatch", 0o700)
    dependencies = (
        "mysql.service",
        "psynova-school-demo.service",
        "psynova-school-rag.service",
        "psynova-school-safety.service",
        "psynova-school-cat.service",
    )
    if any(not _unit_active(name) for name in dependencies):
        raise GateError("dependency_service_inactive", "host_preflight")
    for port in (3306, 8088, 8170, 8180, 8181, 8190):
        _require_loopback_port(port, allow_absent=False)
    install_complete = state is not None and state["phase"] == "HTTP_VERIFIED"
    _verify_llm_port_for_checkpoint(state)
    if state is None and (_unit_active(SERVICE_NAME) or _unit_enabled(SERVICE_NAME)):
        raise GateError("uncheckpointed_llm_unit", "host_preflight")
    if state is None and (os.path.lexists(BACKEND_DROPIN) or os.path.lexists(API_CREDENTIAL) or os.path.lexists(RUNTIME_CREDENTIAL)):
        raise GateError("uncheckpointed_llm_credential_or_dropin", "host_preflight")
    if state is None and _unit_enabled("nginx.service"):
        raise GateError("public_ingress_open_before_ai_gates", "host_preflight")
    if not install_complete and (_listeners_for_port(80) or _listeners_for_port(443)):
        raise GateError("public_ingress_open_before_ai_gates", "host_preflight")
    if _dns_ipv4_addresses() != API_ALLOWED_IPV4:
        raise GateError("deepseek_dns_allowlist_mismatch", "egress_preflight")
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


def _install_or_verify_dependencies(state: dict[str, Any]) -> None:
    facts = state.get("dependency_facts")
    if facts is None:
        _checkpoint(state, "PAYLOAD_READY")
        facts = _install_dependencies()
        _checkpoint(state, "DEPENDENCIES_READY", dependency_facts=facts)
        return
    verified = _verify_dependencies()
    if verified != facts:
        raise GateError("dependency_checkpoint_mismatch", "dependency_verify")
    if PHASES.index(state["phase"]) < PHASES.index("DEPENDENCIES_READY"):
        _checkpoint(state, "DEPENDENCIES_READY")


def _store_api_credential(state: dict[str, Any]) -> None:
    if _credential_from_state(
        state,
        state_hash_key="api_credential_sha256",
        pending_hash_key="api_credential_pending_sha256",
        path=API_CREDENTIAL,
        name=API_CREDENTIAL_NAME,
        kind="api_key",
        ready_phase="API_CREDENTIAL_READY",
    ):
        return
    api_key = _await_api_key()
    try:
        encrypted = _encrypt_credential(API_CREDENTIAL_NAME, api_key)
    finally:
        for index in range(len(api_key)):
            api_key[index] = 0
    digest = _sha256_bytes(encrypted)
    _checkpoint(state, "API_CREDENTIAL_PENDING", api_credential_pending_sha256=digest)
    _write_encrypted_credential(API_CREDENTIAL, encrypted, digest)
    _validate_credential(API_CREDENTIAL, API_CREDENTIAL_NAME, "api_key", digest)
    state.pop("api_credential_pending_sha256", None)
    _checkpoint(state, "API_CREDENTIAL_READY", api_credential_sha256=digest)


def _write_encrypted_credential(path: Path, data: bytes, expected_sha256: str) -> None:
    _require_root_directory(CREDENTIAL_ROOT, "credential_directory_metadata_mismatch", 0o700)
    stage = _credential_stage_path(path, expected_sha256)
    if os.path.lexists(path):
        try:
            metadata = path.stat(follow_symlinks=False)
        except OSError:
            raise GateError("credential_metadata_unavailable", "credentials_write") from None
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) != 0o400
            or _sha256_file(path) != expected_sha256
        ):
            raise GateError("existing_credential_mismatch", "credentials_write")
        if os.path.lexists(stage):
            _remove_encrypted_stage(stage, expected_sha256)
        return
    if not os.path.lexists(stage):
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(stage, flags, 0o400)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chown(stage, 0, 0)
            os.chmod(stage, 0o400)
        except FileExistsError:
            raise GateError("credential_stage_appeared", "credentials_write") from None
        except OSError:
            raise GateError("credential_stage_write_failed", "credentials_write") from None
    _verify_encrypted_stage(stage, expected_sha256)
    try:
        os.link(stage, path, follow_symlinks=False)
        os.unlink(stage)
    except FileExistsError:
        raise GateError("credential_destination_appeared", "credentials_write") from None
    except OSError:
        raise GateError("credential_link_failed", "credentials_write") from None
    _verify_encrypted_stage(path, expected_sha256)


def _verify_encrypted_stage(path: Path, expected_sha256: str) -> None:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError:
        raise GateError("encrypted_credential_unavailable", "credentials_verify") from None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o400
        or _sha256_file(path) != expected_sha256
    ):
        raise GateError("encrypted_credential_mismatch", "credentials_verify")


def _remove_encrypted_stage(path: Path, expected_sha256: str) -> None:
    _verify_encrypted_stage(path, expected_sha256)
    try:
        path.unlink()
    except OSError:
        raise GateError("encrypted_credential_stage_cleanup_failed", "credentials_verify") from None


def _store_runtime_credential(state: dict[str, Any]) -> None:
    if _credential_from_state(
        state,
        state_hash_key="runtime_credential_sha256",
        pending_hash_key="runtime_credential_pending_sha256",
        path=RUNTIME_CREDENTIAL,
        name=RUNTIME_CREDENTIAL_NAME,
        kind="token",
        ready_phase="CREDENTIALS_READY",
    ):
        return
    token = bytearray(secrets.token_urlsafe(48).encode("ascii"))
    try:
        encrypted = _encrypt_credential(RUNTIME_CREDENTIAL_NAME, token)
    finally:
        for index in range(len(token)):
            token[index] = 0
    digest = _sha256_bytes(encrypted)
    _checkpoint(state, "RUNTIME_CREDENTIAL_PENDING", runtime_credential_pending_sha256=digest)
    _write_encrypted_credential(RUNTIME_CREDENTIAL, encrypted, digest)
    _validate_credential(RUNTIME_CREDENTIAL, RUNTIME_CREDENTIAL_NAME, "token", digest)
    state.pop("runtime_credential_pending_sha256", None)
    _checkpoint(state, "CREDENTIALS_READY", runtime_credential_sha256=digest)


def _safe_http_json(method: str, path: str, payload: dict[str, Any] | None = None, *, token: str | None = None) -> tuple[int, dict[str, Any]]:
    import http.client

    connection = http.client.HTTPConnection("127.0.0.1", LLM_PORT, timeout=10)
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers: dict[str, str] = {} if body is None else {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read(256 * 1024 + 1)
        status = response.status
    except (OSError, http.client.HTTPException):
        raise GateError("llm_http_unavailable", "http_verification") from None
    finally:
        connection.close()
    if len(raw) > 256 * 1024:
        raise GateError("llm_http_response_too_large", "http_verification")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise GateError("llm_http_response_invalid", "http_verification") from None
    if type(data) is not dict:
        raise GateError("llm_http_response_invalid", "http_verification")
    return status, data


def _verify_llm_service(*, require_enabled: bool = True) -> dict[str, Any]:
    if not _unit_active(SERVICE_NAME):
        raise GateError("llm_service_inactive", "service_verify")
    if require_enabled and not _unit_enabled(SERVICE_NAME):
        raise GateError("llm_service_not_enabled", "service_verify")
    _require_loopback_port(LLM_PORT, allow_absent=False)
    status, health = _safe_http_json("GET", "/health/ready")
    if status != 200 or health.get("status") != "READY":
        raise GateError("llm_readiness_contract_mismatch", "http_verification")
    token = _decrypt_credential(RUNTIME_CREDENTIAL, RUNTIME_CREDENTIAL_NAME)
    try:
        token_text = bytes(token).rstrip(b"\r\n").decode("ascii", errors="strict")
        if not TOKEN_PATTERN.fullmatch(token_text.encode("ascii")):
            raise GateError("runtime_auth_token_malformed", "http_verification")
        status, models = _safe_http_json("GET", "/internal/llm/models", token=token_text)
    except (UnicodeError, ValueError):
        raise GateError("runtime_auth_token_malformed", "http_verification") from None
    finally:
        for index in range(len(token)):
            token[index] = 0
    model_entries = models.get("models")
    if (
        status != 200
        or models.get("cloud_fallback") is not False
        or type(model_entries) is not list
        or not any(
            type(item) is dict
            and item.get("logical_model_id") == LOGICAL_MODEL_ID
            and item.get("provider_model_id") == MODEL_ID
            for item in model_entries
        )
    ):
        raise GateError("llm_model_discovery_contract_mismatch", "http_verification")
    return {
        "readiness": True,
        "deepseek_model_available": True,
        "runtime_bearer_enforced": True,
        "cloud_fallback": False,
        "listener": "127.0.0.1:8160",
    }


def _backend_live() -> None:
    import http.client

    connection = http.client.HTTPConnection("127.0.0.1", 8088, timeout=5)
    try:
        connection.request("GET", "/health/live")
        response = connection.getresponse()
        response.read(16 * 1024)
        if response.status != 200:
            raise GateError("backend_live_contract_mismatch", "backend_verify")
    except (OSError, http.client.HTTPException):
        raise GateError("backend_unavailable_after_restart", "backend_verify") from None
    finally:
        connection.close()


def _verify_existing_school_http() -> dict[str, Any]:
    try:
        metadata = BACKEND_HTTP_VERIFIER.stat(follow_symlinks=False)
    except OSError:
        raise GateError("school_http_verifier_unavailable", "backend_verify") from None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o644
        or _sha256_file(BACKEND_HTTP_VERIFIER) != BACKEND_HTTP_VERIFIER_SHA256
    ):
        raise GateError("school_http_verifier_fingerprint_mismatch", "backend_verify")
    result = _run(
        [
            str(APP_ROOT / "venv" / "bin" / "python"),
            str(BACKEND_HTTP_VERIFIER),
            "--repo-root",
            str(BASE_RELEASE),
        ],
        phase="backend_http_verification",
        timeout=420,
    )
    try:
        report = json.loads(result.stdout.decode("utf-8").strip().splitlines()[-1])
    except (UnicodeError, json.JSONDecodeError, IndexError):
        raise GateError("school_http_verification_report_invalid", "backend_verify") from None
    if (
        type(report) is not dict
        or report.get("http_smoke") != "PASS"
        or report.get("authenticated_accounts") != 8
        or report.get("role_boundaries") != "PASS"
        or report.get("cross_school_subject_denial") != "PASS"
        or report.get("csrf_enforcement") != "PASS"
        or report.get("session_after_restart") != "PASS"
        or report.get("response_bodies_or_credentials_logged") is not False
    ):
        raise GateError("school_http_verification_failed", "backend_verify")
    return report


def _verify_live_service(state: dict[str, Any]) -> dict[str, Any]:
    if not _unit_active(BACKEND_SERVICE):
        raise GateError("backend_service_inactive", "backend_verify")
    _require_loopback_port(8088, allow_absent=False)
    _backend_live()
    deepseek = _verify_llm_service()
    backend_report = _verify_existing_school_http()
    return {
        **deepseek,
        "backend_active": True,
        "backend_http_smoke": "PASS",
        "authenticated_accounts": backend_report["authenticated_accounts"],
        "session_after_restart": backend_report["session_after_restart"],
        "e2e_generation_pending": True,
    }


def _ensure_root_snapshot_targets_absent(state: dict[str, Any] | None) -> None:
    if state is None and _uncheckpointed_objects_exist():
        raise GateError("uncheckpointed_llm_partial_install", "host_preflight")


def _verify_llm_port_for_checkpoint(state: dict[str, Any] | None) -> None:
    service_started = (
        state is not None
        and PHASES.index(state["phase"]) >= PHASES.index("LLM_SERVICE_STARTED")
    )
    listeners = _listeners_for_port(LLM_PORT)
    if (
        state is not None
        and state["phase"] == "LLM_SERVICE_STARTED"
        and not _unit_active(SERVICE_NAME)
    ):
        if listeners:
            raise GateError("llm_port_occupied_after_service_failure", "listener_check")
        return
    if not service_started:
        if listeners:
            raise GateError("llm_port_unexpectedly_in_use", "listener_check")
        return
    if not listeners or any(address != "127.0.0.1:8160" for address in listeners):
        raise GateError("service_listener_not_loopback", "listener_check")


def _inspect(state: dict[str, Any] | None, files: dict[str, bytes]) -> int:
    if state is None:
        _ensure_root_snapshot_targets_absent(state)
        print(json.dumps({"deepseek_service": "NOT_INSTALLED", "phase": "inspect", "writes": False}, sort_keys=True))
        return 0
    _check_state_objects(state, files)
    if state["phase"] == "HTTP_VERIFIED":
        deepseek = _verify_llm_service()
        print(json.dumps({"deepseek_service": "PASS", "phase": "HTTP_VERIFIED", "source_commit": SOURCE_COMMIT, "bundle_sha256": BUNDLE_SHA256, **deepseek, "writes": False}, sort_keys=True))
    else:
        print(json.dumps({"deepseek_service": "PARTIAL", "phase": state["phase"], "source_commit": SOURCE_COMMIT, "bundle_sha256": BUNDLE_SHA256, "bundle_upgrade_required": state.get("bundle_sha256") == PREVIOUS_BUNDLE_SHA256, "writes": False}, sort_keys=True))
    return 0


def _dry_run(state: dict[str, Any] | None, files: dict[str, bytes]) -> int:
    if state is None:
        _ensure_root_snapshot_targets_absent(state)
    else:
        _check_state_objects(state, files)
    remaining = list(PHASES[1:]) if state is None else list(PHASES[PHASES.index(state["phase"]) + 1 :])
    print(json.dumps({
        "deepseek_service": "READY_TO_RESUME",
        "current_phase": "NOT_STARTED" if state is None else state["phase"],
        "remaining_phases": remaining,
        "api_key_required": not API_CREDENTIAL.exists(),
        "bundle_upgrade_required": state is not None and state.get("bundle_sha256") == PREVIOUS_BUNDLE_SHA256,
        "source_commit": SOURCE_COMMIT,
        "bundle_sha256": BUNDLE_SHA256,
        "model_id": MODEL_ID,
        "synthetic_demo_only": True,
        "writes": False,
    }, sort_keys=True))
    return 0


def _resume(state: dict[str, Any] | None, files: dict[str, bytes]) -> int:
    if state is None:
        _ensure_root_snapshot_targets_absent(state)
        state = _new_state()
        _write_state(state)
        bundle_upgrade = False
    else:
        _check_state_objects(state, files)
        bundle_upgrade = state.get("bundle_sha256") == PREVIOUS_BUNDLE_SHA256
    if state["phase"] == "HTTP_VERIFIED":
        checks = _verify_llm_service()
        print(json.dumps({"deepseek_service": "PASS", "phase": "HTTP_VERIFIED", "checks": checks, "writes": False}, sort_keys=True))
        return 0
    resume_phase_index = PHASES.index(state["phase"])

    _install_payload(files, allow_bundle_upgrade=bundle_upgrade)
    if bundle_upgrade:
        state["bundle_sha256"] = BUNDLE_SHA256
        state["bundle_upgrade_from"] = PREVIOUS_BUNDLE_SHA256
        state["checks"]["bundle_manifest_upgraded"] = True
        state["updated_at_epoch"] = int(time.time())
        _write_state(state)
    elif resume_phase_index < PHASES.index("PAYLOAD_READY"):
        _checkpoint(state, "PAYLOAD_READY", checks={"source_fingerprints_verified": True, "synthetic_demo_only": True})
    _install_or_verify_dependencies(state)
    _store_api_credential(state)
    _store_runtime_credential(state)
    if not state.get("unit_sha256"):
        _checkpoint(
            state,
            "CREDENTIALS_READY",
            unit_sha256=_sha256_bytes(files["systemd/psynova-school-llm.service"]),
            backend_dropin_sha256=_sha256_bytes(files["systemd/psynova-school-demo-llm.conf"]),
        )
    _install_unit_and_dropin(files)
    resolver_dropin_sha256 = _install_resolver_dropin()
    recorded_resolver_hash = state.get("resolver_dropin_sha256")
    if recorded_resolver_hash not in {None, resolver_dropin_sha256}:
        raise GateError("resolver_dropin_checkpoint_mismatch", "checkpoint_verify")
    if recorded_resolver_hash is None:
        state["resolver_dropin_sha256"] = resolver_dropin_sha256
        state["updated_at_epoch"] = int(time.time())
        _write_state(state)
    _verify_unit_files()
    if resume_phase_index < PHASES.index("UNIT_READY"):
        _checkpoint(state, "UNIT_READY", checks={"systemd_unit_verified": True, "credentials_host_encrypted": True})
    if resume_phase_index < PHASES.index("LLM_SERVICE_STARTED"):
        _run(["systemctl", "daemon-reload"], phase="systemd_reload")
        _run(["systemctl", "enable", "--now", SERVICE_NAME], phase="llm_service_start", timeout=240)
        _checkpoint(state, "LLM_SERVICE_STARTED", checks={"systemd_unit_verified": True, "enabled": True})
    else:
        _run(["systemctl", "daemon-reload"], phase="systemd_reload")
        service_ready = False
        try:
            _verify_llm_service(require_enabled=True)
            service_ready = True
        except GateError:
            service_ready = False
        if not service_ready:
            _run(["systemctl", "reset-failed", SERVICE_NAME], phase="llm_service_reset_failed")
            _run(["systemctl", "restart", SERVICE_NAME], phase="llm_service_restart", timeout=240)
    _wait_for_llm_service(timeout=180)
    if resume_phase_index < PHASES.index("BACKEND_SWITCHED"):
        _run(["systemctl", "restart", BACKEND_SERVICE], phase="backend_restart", timeout=180)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                _backend_live()
                break
            except GateError:
                time.sleep(2)
        else:
            raise GateError("backend_not_ready_after_restart", "backend_verify")
        _checkpoint(state, "BACKEND_SWITCHED", checks={"deepseek_provider_selected": True, "runtime_auth_credential_loaded": True})
    if resume_phase_index < PHASES.index("BACKEND_HTTP_VERIFIED"):
        _backend_live()
        school_http = _verify_existing_school_http()
        _checkpoint(
            state,
            "BACKEND_HTTP_VERIFIED",
            checks={
                "deepseek_provider_selected": True,
                "runtime_auth_credential_loaded": True,
                "backend_http_smoke": True,
                "authenticated_accounts": school_http["authenticated_accounts"],
                "role_boundaries": school_http["role_boundaries"] == "PASS",
                "cross_school_subject_denial": school_http["cross_school_subject_denial"] == "PASS",
                "csrf_enforcement": school_http["csrf_enforcement"] == "PASS",
                "session_after_restart": school_http["session_after_restart"] == "PASS",
                "response_bodies_or_credentials_logged": school_http[
                    "response_bodies_or_credentials_logged"
                ],
            },
        )
    deepseek = _verify_llm_service()
    _backend_live()
    checks = {
        **deepseek,
        **state.get("checks", {}),
        "backend_active": True,
        "generation_verified": False,
    }
    _require_loopback_port(LLM_PORT, allow_absent=False)
    _checkpoint(state, "HTTP_VERIFIED", checks=checks)
    print(json.dumps({
        "deepseek_service": "PASS",
        "phase": "HTTP_VERIFIED",
        "source_commit": SOURCE_COMMIT,
        "bundle_sha256": BUNDLE_SHA256,
        "checks": checks,
        "llm_listener": "127.0.0.1:8160",
        "backend_listener": "127.0.0.1:8088",
        "api_key_logged": False,
        "runtime_token_logged": False,
        "generation_verified": False,
    }, sort_keys=True))
    return 0


def _install_unit_and_dropin(files: dict[str, bytes]) -> None:
    _write_payload_file(UNIT_PATH, files["systemd/psynova-school-llm.service"])
    _ensure_root_directory(BACKEND_DROPIN.parent)
    _write_payload_file(BACKEND_DROPIN, files["systemd/psynova-school-demo-llm.conf"])


def _verify_unit_files() -> None:
    _run(["systemd-analyze", "verify", str(UNIT_PATH), str(Path("/etc/systemd/system/psynova-school-demo.service"))], phase="unit_verify")


def _install_resolver_dropin() -> str:
    _ensure_root_directory(RESOLVER_DROPIN.parent)
    _write_payload_file(RESOLVER_DROPIN, RESOLVER_DROPIN_DATA)
    return _sha256_bytes(RESOLVER_DROPIN_DATA)


def _wait_for_llm_service(*, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            _verify_llm_service()
            return
        except GateError:
            time.sleep(3)
    raise GateError("llm_service_not_ready", "service_verify")


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
        _host_preflight(state=state)
        if args.inspect:
            return _inspect(state, files)
        if args.dry_run:
            return _dry_run(state, files)
        return _resume(state, files)
    except GateError as exc:
        print(json.dumps({"error_code": exc.code, "phase": exc.phase, "recovery": "BLOCKED"}, sort_keys=True), flush=True)
        return 2
    finally:
        if lock_entered and lock_context is not None:
            lock_context.__exit__(None, None, None)


if __name__ == "__main__":
    raise SystemExit(main())
