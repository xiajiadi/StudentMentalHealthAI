"""Build and safely deploy the synthetic account credential eligibility fix."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, cast

BASE_RELEASE_REVISION = "f3047642aa3466f9b4f210f4f704d57fd2cdf3cc"
SOURCE_COMMIT = "2a6418cbe212c0cc77125ac53ea4bb7055265db8"
PREVIOUS_FILE_REVISION = "1e5f177ab8837cda531ba2f92529151fb0e4dd2b"
SERVER_HOSTNAME = "iZ0xic24d9gxb9udjbfo0kZ"
APP_ROOT = Path("/opt/psynova-school-demo")
RELEASE_ROOT = APP_ROOT / "release"
STATE_ROOT = Path("/var/lib/psynova-school-demo")
STATE_PATH = STATE_ROOT / f"account-credential-overlay-{SOURCE_COMMIT[:12]}-state.json"
BACKUP_ROOT = APP_ROOT / "backups" / f"account-credential-overlay-{SOURCE_COMMIT}"
LOCK_PATH = Path("/run/lock/psynova-school-account-credentials.lock")
BUNDLE_PATH = Path(
    "/home/psynova/apps/psynova/staging/linux-school-demo/"
    f"school-account-credential-overlay-{SOURCE_COMMIT}.zip"
)
SERVICE_NAME = "psynova-school-demo.service"
HEALTH_URL = "http://127.0.0.1:8088/api/v1/health"
STATE_SCHEMA = "psynova.school-account-credential-overlay-state.v1"
BUNDLE_SCHEMA = "psynova.school-account-credential-overlay.v1"
TARGET_PATH = "09_backend/src/smhai_backend/adapters/school_directory.py"
PREVIOUS_SHA256 = "c9dd69604670425ef3e2584a78ae549b4fb1b92c083de41a22f1d4ee936e2dee"
TARGET_SHA256 = "3ff5ecb1b9c4fcdb5560856f6da42763bc1ef1828bce9b4ce77980407adc32e2"
MAX_BUNDLE_BYTES = 2_000_000
MAX_TARGET_BYTES = 1_000_000
HEALTH_WAIT_SECONDS = 90
CONFLICTING_PROCESS_MARKERS = (
    "bootstrap_linux_school_demo.py --install",
    "recover_linux_school_demo.py --resume",
    "migrate_school_linux.py",
    "deploy_school_backend_overlay_linux.py",
    "deploy_school_backend_contract_schemas_linux.py",
    "deploy_school_frontend_linux.py --resume",
    "deploy_school_deepseek_generation_route_linux.py",
)
STATE_PHASES = {
    "BACKUP_VERIFIED",
    "FILES_INSTALLED",
    "RESTARTING",
    "HTTP_VERIFIED",
    "ROLLBACK_STARTED",
    "ROLLBACK_VERIFIED",
    "ROLLBACK_FAILED",
}


class DeployError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_bytes(repo_root: Path, revision: str, relative_path: str) -> bytes:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo_root), "show", f"{revision}:{relative_path}"],
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        raise DeployError("source_file_unavailable") from None


def _manifest(file_bytes: bytes) -> dict[str, Any]:
    if _sha256(file_bytes) != TARGET_SHA256:
        raise DeployError("source_file_fingerprint_mismatch")
    return {
        "schema": BUNDLE_SCHEMA,
        "base_release_revision": BASE_RELEASE_REVISION,
        "source_commit": SOURCE_COMMIT,
        "files": [
            {
                "path": TARGET_PATH,
                "size_bytes": len(file_bytes),
                "previous_sha256": PREVIOUS_SHA256,
                "sha256": TARGET_SHA256,
            }
        ],
    }


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    return info


def build_package(repo_root: Path, output: Path) -> dict[str, object]:
    root = repo_root.resolve(strict=True)
    try:
        dirty = subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain", "--", TARGET_PATH],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        raise DeployError("git_source_unavailable") from None
    if dirty:
        raise DeployError("source_worktree_dirty")
    source = _git_bytes(root, SOURCE_COMMIT, TARGET_PATH)
    manifest = _manifest(source)
    output_path = output.resolve()
    if not output_path.parent.is_dir() or output_path.exists():
        raise DeployError("bundle_output_path_unavailable")
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        archive.writestr(
            _zip_info("manifest.json"), json.dumps(manifest, sort_keys=True).encode()
        )
        archive.writestr(_zip_info(TARGET_PATH), source)
    bundle = buffer.getvalue()
    _validate_bundle_bytes(bundle)
    try:
        with output_path.open("xb") as stream:
            stream.write(bundle)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        raise DeployError("bundle_output_write_failed") from None
    return {
        "status": "PACKAGED",
        "source_commit": SOURCE_COMMIT,
        "bundle_sha256": _sha256(bundle),
        "file_count": 1,
        "size_bytes": len(bundle),
        "path": str(output_path),
    }


def _validate_bundle_bytes(raw: bytes) -> tuple[dict[str, Any], bytes]:
    if not raw or len(raw) > MAX_BUNDLE_BYTES:
        raise DeployError("bundle_size_invalid")
    try:
        archive = zipfile.ZipFile(__import__("io").BytesIO(raw))
    except (OSError, zipfile.BadZipFile):
        raise DeployError("bundle_archive_invalid") from None
    with archive:
        infos = archive.infolist()
        if {info.filename for info in infos} != {"manifest.json", TARGET_PATH} or len(
            infos
        ) != 2:
            raise DeployError("bundle_inventory_mismatch")
        members: dict[str, bytes] = {}
        for info in infos:
            path = PurePosixPath(info.filename)
            mode = (info.external_attr >> 16) & 0xFFFF
            if (
                info.is_dir()
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in info.filename
                or stat.S_ISLNK(mode)
                or info.file_size > MAX_TARGET_BYTES
            ):
                raise DeployError("bundle_member_rejected")
            try:
                content = archive.read(info)
            except (OSError, RuntimeError, zipfile.BadZipFile):
                raise DeployError("bundle_member_unreadable") from None
            if len(content) != info.file_size:
                raise DeployError("bundle_member_size_mismatch")
            members[info.filename] = content
    try:
        manifest = json.loads(members["manifest.json"])
    except (UnicodeError, json.JSONDecodeError):
        raise DeployError("bundle_manifest_invalid") from None
    source = members[TARGET_PATH]
    if manifest != _manifest(source):
        raise DeployError("bundle_manifest_mismatch")
    return manifest, source


def _lstat(path: Path) -> os.stat_result:
    try:
        value = path.lstat()
    except OSError:
        raise DeployError("required_path_unavailable") from None
    if stat.S_ISLNK(value.st_mode):
        raise DeployError("unexpected_symlink")
    return value


def _require_owned(
    path: Path, *, mode: int | None = None, regular: bool = False
) -> os.stat_result:
    value = _lstat(path)
    if value.st_uid != 0 or value.st_gid != 0:
        raise DeployError("unexpected_path_owner")
    if mode is not None and stat.S_IMODE(value.st_mode) != mode:
        raise DeployError("unexpected_path_mode")
    if regular and not stat.S_ISREG(value.st_mode):
        raise DeployError("unexpected_path_type")
    return value


def _require_root() -> None:
    effective_uid = getattr(os, "geteuid", None)
    if not callable(effective_uid) or effective_uid() != 0:
        raise DeployError("root_required")


def _fchown(descriptor: int, uid: int, gid: int) -> None:
    change_owner = getattr(os, "fchown", None)
    if not callable(change_owner):
        raise DeployError("linux_owner_api_unavailable")
    change_owner(descriptor, uid, gid)


def _chown(path: Path, uid: int, gid: int) -> None:
    change_owner = getattr(os, "chown", None)
    if not callable(change_owner):
        raise DeployError("linux_owner_api_unavailable")
    change_owner(path, uid, gid)


def _assert_no_conflicting_deployment_process() -> None:
    current_pid = os.getpid()
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        raise DeployError("process_inventory_unavailable") from None
    for entry in entries:
        if not entry.name.isdigit() or int(entry.name) == current_pid:
            continue
        try:
            command = (
                (entry / "cmdline")
                .read_bytes()
                .replace(b"\0", b" ")
                .decode("utf-8", "ignore")
            )
        except OSError:
            continue
        if any(marker in command for marker in CONFLICTING_PROCESS_MARKERS):
            raise DeployError("conflicting_deployment_process_active")


def _require_snapshot() -> None:
    path = Path(__file__)
    _require_owned(path, mode=0o500, regular=True)
    prefix, suffix = "deploy_school_account_credentials_", ".py"
    if not path.name.startswith(prefix) or not path.name.endswith(suffix):
        raise DeployError("release_fingerprint_mismatch")
    expected = path.name[len(prefix) : -len(suffix)]
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise DeployError("release_fingerprint_mismatch")
    try:
        actual = _sha256(path.read_bytes())
    except OSError:
        raise DeployError("release_fingerprint_unavailable") from None
    if actual != expected:
        raise DeployError("release_fingerprint_mismatch")


def _require_server_and_release() -> tuple[Path, str]:
    if socket.gethostname() != SERVER_HOSTNAME:
        raise DeployError("server_identity_mismatch")
    _require_owned(APP_ROOT)
    _require_owned(RELEASE_ROOT)
    revision_path = RELEASE_ROOT / "SOURCE_REVISION"
    _require_owned(revision_path, mode=0o644, regular=True)
    try:
        revision = revision_path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        raise DeployError("source_revision_unreadable") from None
    if revision != BASE_RELEASE_REVISION:
        raise DeployError("base_release_revision_mismatch")
    target = RELEASE_ROOT.joinpath(*PurePosixPath(TARGET_PATH).parts)
    current_parent = RELEASE_ROOT
    for part in PurePosixPath(TARGET_PATH).parts[:-1]:
        current_parent = current_parent / part
        _require_owned(current_parent)
    _require_owned(target, mode=0o644, regular=True)
    try:
        current_hash = _sha256(target.read_bytes())
    except OSError:
        raise DeployError("release_file_unreadable") from None
    if current_hash not in {PREVIOUS_SHA256, TARGET_SHA256}:
        raise DeployError("release_file_fingerprint_mismatch")
    return target, current_hash


def _read_bundle() -> tuple[dict[str, Any], bytes, str]:
    _lstat(BUNDLE_PATH)
    info = BUNDLE_PATH.stat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_mode & 0o022
        or info.st_size > MAX_BUNDLE_BYTES
    ):
        raise DeployError("bundle_path_permissions_invalid")
    try:
        raw = BUNDLE_PATH.read_bytes()
    except OSError:
        raise DeployError("bundle_unreadable") from None
    manifest, source = _validate_bundle_bytes(raw)
    return manifest, source, _sha256(raw)


def _service_active() -> bool:
    result = subprocess.run(
        ["systemctl", "is-active", "--quiet", SERVICE_NAME],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _write_state(bundle_hash: str, phase: str) -> None:
    _require_owned(STATE_ROOT, mode=0o700)
    state = {
        "schema": STATE_SCHEMA,
        "base_release_revision": BASE_RELEASE_REVISION,
        "source_commit": SOURCE_COMMIT,
        "bundle_sha256": bundle_hash,
        "previous_sha256": PREVIOUS_SHA256,
        "target_sha256": TARGET_SHA256,
        "backup_path": str(BACKUP_ROOT / TARGET_PATH),
        "phase": phase,
        "updated_at_epoch": int(time.time()),
    }
    data = json.dumps(state, sort_keys=True).encode("utf-8") + b"\n"
    fd, temporary = tempfile.mkstemp(
        prefix=".account-credential-state-", dir=STATE_ROOT
    )
    try:
        _fchown(fd, 0, 0)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, STATE_PATH)
        directory = os.open(STATE_ROOT, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise DeployError("checkpoint_write_failed") from None


def _load_state() -> dict[str, Any] | None:
    _require_owned(STATE_ROOT, mode=0o700)
    if not os.path.lexists(STATE_PATH):
        return None
    _require_owned(STATE_PATH, mode=0o600, regular=True)
    try:
        if STATE_PATH.stat().st_size > 16_384:
            raise DeployError("checkpoint_size_invalid")
        value = json.loads(STATE_PATH.read_bytes())
    except DeployError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise DeployError("checkpoint_invalid") from None
    expected = {
        "schema",
        "base_release_revision",
        "source_commit",
        "bundle_sha256",
        "previous_sha256",
        "target_sha256",
        "backup_path",
        "phase",
        "updated_at_epoch",
    }
    if (
        type(value) is not dict
        or set(value) != expected
        or value.get("schema") != STATE_SCHEMA
        or value.get("base_release_revision") != BASE_RELEASE_REVISION
        or value.get("source_commit") != SOURCE_COMMIT
        or value.get("previous_sha256") != PREVIOUS_SHA256
        or value.get("target_sha256") != TARGET_SHA256
        or value.get("backup_path") != str(BACKUP_ROOT / TARGET_PATH)
        or value.get("phase") not in STATE_PHASES
        or type(value.get("bundle_sha256")) is not str
        or len(value["bundle_sha256"]) != 64
        or any(char not in "0123456789abcdef" for char in value["bundle_sha256"])
        or type(value.get("updated_at_epoch")) is not int
    ):
        raise DeployError("checkpoint_mismatch")
    return value


def _ensure_directory(path: Path, mode: int) -> None:
    if os.path.lexists(path):
        _require_owned(path, mode=mode)
        if not stat.S_ISDIR(path.stat().st_mode):
            raise DeployError("backup_directory_invalid")
        return
    path.mkdir(mode=mode, parents=False)
    _chown(path, 0, 0)
    os.chmod(path, mode)


def _atomic_write(target: Path, content: bytes) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}-", dir=target.parent)
    try:
        _fchown(fd, 0, 0)
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise DeployError("atomic_install_failed") from None


def _backup_path() -> Path:
    return BACKUP_ROOT.joinpath(*PurePosixPath(TARGET_PATH).parts)


def _ensure_backup(content: bytes) -> None:
    backup_base = APP_ROOT / "backups"
    if not backup_base.exists():
        backup_base.mkdir(mode=0o755)
        _chown(backup_base, 0, 0)
    _require_owned(backup_base)
    _ensure_directory(BACKUP_ROOT, 0o700)
    current = BACKUP_ROOT
    for part in PurePosixPath(TARGET_PATH).parts[:-1]:
        current = current / part
        if not current.exists():
            current.mkdir(mode=0o755)
            _chown(current, 0, 0)
            os.chmod(current, 0o755)
        _require_owned(current, mode=0o755)
    path = _backup_path()
    if path.exists():
        _require_owned(path, mode=0o644, regular=True)
        try:
            if _sha256(path.read_bytes()) != PREVIOUS_SHA256:
                raise DeployError("backup_fingerprint_mismatch")
        except OSError:
            raise DeployError("backup_unreadable") from None
        return
    _atomic_write(path, content)
    _require_owned(path, mode=0o644, regular=True)
    if _sha256(path.read_bytes()) != PREVIOUS_SHA256:
        raise DeployError("backup_fingerprint_mismatch")


def _run_systemctl(action: str) -> None:
    result = subprocess.run(
        ["systemctl", action, SERVICE_NAME],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        raise DeployError("systemd_action_failed")


def _health_passes() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=3) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError, TimeoutError):
        return False


def _wait_for_health() -> bool:
    deadline = time.monotonic() + HEALTH_WAIT_SECONDS
    while time.monotonic() < deadline:
        if _service_active() and _health_passes():
            return True
        time.sleep(1)
    return False


def _restore_backup(bundle_hash: str) -> bool:
    backup = _backup_path()
    _require_owned(backup, mode=0o644, regular=True)
    try:
        content = backup.read_bytes()
    except OSError:
        raise DeployError("backup_unreadable") from None
    if _sha256(content) != PREVIOUS_SHA256:
        raise DeployError("backup_fingerprint_mismatch")
    _write_state(bundle_hash, "ROLLBACK_STARTED")
    target = RELEASE_ROOT.joinpath(*PurePosixPath(TARGET_PATH).parts)
    _atomic_write(target, content)
    try:
        _run_systemctl("restart")
    except DeployError:
        _write_state(bundle_hash, "ROLLBACK_FAILED")
        return False
    if not _wait_for_health():
        _write_state(bundle_hash, "ROLLBACK_FAILED")
        return False
    _write_state(bundle_hash, "ROLLBACK_VERIFIED")
    return True


class _ExclusiveLock:
    def __enter__(self):
        import fcntl

        fcntl_api = cast(Any, fcntl)
        self._flock = fcntl_api.flock
        self._lock_ex = fcntl_api.LOCK_EX
        self._lock_nb = fcntl_api.LOCK_NB
        self._lock_un = fcntl_api.LOCK_UN
        if os.path.lexists(LOCK_PATH):
            _require_owned(LOCK_PATH, mode=0o600, regular=True)
        _require_owned(LOCK_PATH.parent)
        self.fd = os.open(
            LOCK_PATH,
            os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        _fchown(self.fd, 0, 0)
        os.fchmod(self.fd, 0o600)
        try:
            self._flock(self.fd, self._lock_ex | self._lock_nb)
        except OSError:
            os.close(self.fd)
            raise DeployError("deployment_lock_busy") from None
        return self

    def __exit__(self, *_args):
        self._flock(self.fd, self._lock_un)
        os.close(self.fd)


def inspect() -> dict[str, object]:
    _require_root()
    _require_snapshot()
    target, current_hash = _require_server_and_release()
    state = _load_state()
    phase = state["phase"] if state else "NOT_STARTED"
    if state is None and current_hash != PREVIOUS_SHA256:
        raise DeployError("checkpoint_missing_for_modified_release")
    if state and state["phase"] == "HTTP_VERIFIED" and current_hash != TARGET_SHA256:
        raise DeployError("verified_release_fingerprint_mismatch")
    if (
        state
        and state["phase"] == "ROLLBACK_VERIFIED"
        and current_hash != PREVIOUS_SHA256
    ):
        raise DeployError("rollback_release_fingerprint_mismatch")
    if (
        state
        and state["phase"] in {"FILES_INSTALLED", "RESTARTING"}
        and current_hash != TARGET_SHA256
    ):
        raise DeployError("checkpoint_release_fingerprint_mismatch")
    status = (
        "PASS"
        if state and state["phase"] == "HTTP_VERIFIED" and current_hash == TARGET_SHA256
        else "READY"
    )
    if state and state["phase"] in {"ROLLBACK_STARTED", "ROLLBACK_FAILED"}:
        status = "BLOCKED"
    return {
        "status": status,
        "phase": phase,
        "source_commit": SOURCE_COMMIT,
        "release_path": str(target),
        "release_sha256": current_hash,
        "service_active": _service_active(),
        "database_ddl": False,
    }


def dry_run() -> dict[str, object]:
    _require_root()
    _require_snapshot()
    _target, current_hash = _require_server_and_release()
    manifest, _source, bundle_hash = _read_bundle()
    state = _load_state()
    if state is not None and state["bundle_sha256"] != bundle_hash:
        raise DeployError("bundle_checkpoint_mismatch")
    if state is None and current_hash != PREVIOUS_SHA256:
        raise DeployError("checkpoint_missing_for_modified_release")
    if state and state["phase"] in {
        "ROLLBACK_STARTED",
        "ROLLBACK_FAILED",
        "ROLLBACK_VERIFIED",
    }:
        raise DeployError("overlay_already_rolled_back")
    return {
        "status": "READY",
        "phase": state["phase"] if state else "NOT_STARTED",
        "source_commit": manifest["source_commit"],
        "bundle_sha256": bundle_hash,
        "actions": [
            "preserve_previous_file",
            "install_backend_file_atomically",
            "restart_backend",
            "verify_loopback_health",
        ],
        "database_ddl": False,
    }


def resume() -> dict[str, object]:
    _require_root()
    _require_snapshot()
    _assert_no_conflicting_deployment_process()
    target, current_hash = _require_server_and_release()
    manifest, source, bundle_hash = _read_bundle()
    if manifest["source_commit"] != SOURCE_COMMIT:
        raise DeployError("source_commit_mismatch")
    if not _service_active():
        raise DeployError("backend_not_active_before_update")
    with _ExclusiveLock():
        _assert_no_conflicting_deployment_process()
        target, current_hash = _require_server_and_release()
        state = _load_state()
        if state is not None and state["bundle_sha256"] != bundle_hash:
            raise DeployError("bundle_checkpoint_mismatch")
        if state and state["phase"] in {
            "ROLLBACK_STARTED",
            "ROLLBACK_FAILED",
            "ROLLBACK_VERIFIED",
        }:
            raise DeployError("rollback_checkpoint_requires_inspection")
        if state is None and current_hash != PREVIOUS_SHA256:
            raise DeployError("checkpoint_missing_for_modified_release")
        if (
            state
            and state["phase"] == "HTTP_VERIFIED"
            and current_hash == TARGET_SHA256
        ):
            return {
                "status": "PASS",
                "phase": "HTTP_VERIFIED",
                "replayed": True,
                "database_ddl": False,
            }
        if state is None:
            if current_hash != PREVIOUS_SHA256:
                raise DeployError("release_state_mismatch")
            _ensure_backup(target.read_bytes())
            _write_state(bundle_hash, "BACKUP_VERIFIED")
            state = _load_state()
        if state is None:
            raise DeployError("checkpoint_missing")
        if state["phase"] == "BACKUP_VERIFIED":
            if current_hash == PREVIOUS_SHA256:
                _atomic_write(target, source)
            elif current_hash != TARGET_SHA256:
                raise DeployError("release_state_mismatch")
            _write_state(bundle_hash, "FILES_INSTALLED")
            state = _load_state()
            if state is None:
                raise DeployError("checkpoint_missing")
            current_hash = TARGET_SHA256
        if state["phase"] in {"FILES_INSTALLED", "RESTARTING"}:
            if current_hash != TARGET_SHA256:
                raise DeployError("release_state_mismatch")
            _write_state(bundle_hash, "RESTARTING")
            try:
                _run_systemctl("restart")
            except DeployError:
                restored = _restore_backup(bundle_hash)
                return {
                    "status": "ROLLED_BACK" if restored else "BLOCKED",
                    "phase": "ROLLBACK_VERIFIED" if restored else "ROLLBACK_FAILED",
                    "error_code": "systemd_action_failed",
                    "database_ddl": False,
                }
            if not _wait_for_health():
                restored = _restore_backup(bundle_hash)
                return {
                    "status": "ROLLED_BACK" if restored else "BLOCKED",
                    "phase": "ROLLBACK_VERIFIED" if restored else "ROLLBACK_FAILED",
                    "error_code": "backend_http_verification_failed",
                    "database_ddl": False,
                }
            _write_state(bundle_hash, "HTTP_VERIFIED")
        verified = _sha256(target.read_bytes())
        if verified != TARGET_SHA256:
            raise DeployError("release_postinstall_fingerprint_mismatch")
        return {
            "status": "PASS",
            "phase": "HTTP_VERIFIED",
            "source_commit": manifest["source_commit"],
            "target_sha256": verified,
            "backend_active": True,
            "database_ddl": False,
        }


def rollback() -> dict[str, object]:
    _require_root()
    _require_snapshot()
    _target, current_hash = _require_server_and_release()
    state = _load_state()
    if state is None:
        raise DeployError("checkpoint_missing")
    if current_hash == PREVIOUS_SHA256 and state["phase"] == "ROLLBACK_VERIFIED":
        return {"status": "ROLLED_BACK", "phase": "ROLLBACK_VERIFIED", "replayed": True}
    if current_hash == PREVIOUS_SHA256 and state["phase"] in {
        "BACKUP_VERIFIED",
        "ROLLBACK_STARTED",
        "ROLLBACK_FAILED",
        "HTTP_VERIFIED",
        "FILES_INSTALLED",
        "RESTARTING",
    }:
        if not _service_active() or not _health_passes():
            _run_systemctl("restart")
            if not _wait_for_health():
                _write_state(state["bundle_sha256"], "ROLLBACK_FAILED")
                raise DeployError("rollback_backend_http_verification_failed")
        _write_state(state["bundle_sha256"], "ROLLBACK_VERIFIED")
        return {
            "status": "ROLLED_BACK",
            "phase": "ROLLBACK_VERIFIED",
            "backup_preserved": True,
        }
    if current_hash != TARGET_SHA256:
        raise DeployError("release_state_mismatch")
    with _ExclusiveLock():
        restored = _restore_backup(state["bundle_sha256"])
    if not restored:
        raise DeployError("rollback_backend_http_verification_failed")
    return {
        "status": "ROLLED_BACK",
        "phase": "ROLLBACK_VERIFIED",
        "backup_preserved": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--package", action="store_true")
    actions.add_argument("--inspect", action="store_true")
    actions.add_argument("--dry-run", action="store_true")
    actions.add_argument("--resume", action="store_true")
    actions.add_argument("--rollback", action="store_true")
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.package:
            if args.output is None:
                raise DeployError("bundle_output_required")
            result = build_package(args.repo_root, args.output)
        elif args.inspect:
            result = inspect()
        elif args.dry_run:
            result = dry_run()
        elif args.resume:
            result = resume()
        else:
            result = rollback()
        print(json.dumps(result, sort_keys=True))
        if args.resume and result.get("status") == "ROLLED_BACK":
            return 1
        return (
            0
            if result.get("status") in {"PACKAGED", "PASS", "READY", "ROLLED_BACK"}
            else 2
        )
    except DeployError as exc:
        print(json.dumps({"status": "BLOCKED", "error_code": exc.code}, sort_keys=True))
        return 2
    except OSError:
        print(
            json.dumps(
                {"status": "BLOCKED", "error_code": "host_io_failure"}, sort_keys=True
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
