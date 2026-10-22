"""Package and safely resume the fixed Linux school Backend source overlay."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

BASE_RELEASE_REVISION = "f3047642aa3466f9b4f210f4f704d57fd2cdf3cc"
SOURCE_COMMIT = "05c24d38288258ae2b4725d2b232e30b9f0b6380"
APP_ROOT = Path("/opt/psynova-school-demo")
RELEASE_ROOT = APP_ROOT / "release"
STATE_ROOT = Path("/var/lib/psynova-school-demo")
STATE_PATH = STATE_ROOT / "backend-overlay-state.json"
BACKUP_ROOT = APP_ROOT / "backups" / f"backend-overlay-{SOURCE_COMMIT}"
BUNDLE_PATH = Path(
    "/home/psynova/apps/psynova/staging/linux-school-demo/"
    f"backend-overlay-{SOURCE_COMMIT}.zip"
)
SERVICE_NAME = "psynova-school-demo.service"
HEALTH_URL = "http://127.0.0.1:8088/api/v1/health"
STATE_SCHEMA = "psynova.school-backend-overlay-state.v1"
BUNDLE_SCHEMA = "psynova.school-backend-overlay.v1"
MAX_BUNDLE_BYTES = 2_000_000
MAX_MEMBER_BYTES = 1_000_000
HEALTH_WAIT_SECONDS = 90

FILES = {
    "09_backend/src/smhai_backend/core/config.py": {
        "previous": "f1069718959ffcc88e14650967c364d2220bfd7ddaf5462837f76557ecf792f0",
        "target": "6def055ccd62758229de19811656ceb2bcd36ebb464eb43d191b2f932e1a4956",
    },
    "09_backend/src/smhai_backend/integrations/llm.py": {
        "previous": "5921e27712edcb6c652d8f95bcf69d86caa3a2a3952da591d1abffad30404ad4",
        "target": "5058c6dd699dec691395fdd6bd76428751bacbaac0f100b1c7762d10c4c6372a",
    },
    "13_deployment/school_backend_linux.py": {
        "previous": "929d8c9d504779c7eb1ccd6cbf06cecde4b3ecba02d756dc5895cf4f7e6d22f5",
        "target": "2935d170d8a61ff2cd8a1c335eb861bb41d21b65da95a042424273841a16641e",
    },
}
ALLOWED_BUNDLE_NAMES = {"manifest.json", *FILES}
_CHECKPOINT_PHASES = {
    "BACKUP_PREPARING",
    "BACKUP_VERIFIED",
    "FILES_INSTALLED",
    "STARTING",
    "START_FAILED",
    "HTTP_VERIFIED",
    "ROLLED_BACK",
    "ROLLBACK_HTTP_VERIFIED",
}


class OverlayError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git_bytes(repo_root: Path, revision: str, relative_path: str) -> bytes:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo_root), "show", f"{revision}:{relative_path}"],
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        raise OverlayError("source_file_unavailable") from None


def _package_manifest(file_data: dict[str, bytes]) -> dict[str, Any]:
    if set(file_data) != set(FILES):
        raise OverlayError("bundle_file_inventory_mismatch")
    records = []
    for relative_path in sorted(FILES):
        data = file_data[relative_path]
        expected = FILES[relative_path]
        if _sha256(data) != expected["target"]:
            raise OverlayError("source_file_fingerprint_mismatch")
        records.append(
            {
                "path": relative_path,
                "size_bytes": len(data),
                "sha256": expected["target"],
                "expected_previous_sha256": expected["previous"],
            }
        )
    return {
        "schema": BUNDLE_SCHEMA,
        "base_release_revision": BASE_RELEASE_REVISION,
        "source_commit": SOURCE_COMMIT,
        "files": records,
    }


def _zip_info(filename: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(filename, date_time=(2020, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    return info


def _validate_bundle_bytes(
    archive_bytes: bytes,
    *,
    file_specs: dict[str, dict[str, str]] | None = None,
    source_commit: str = SOURCE_COMMIT,
    base_revision: str = BASE_RELEASE_REVISION,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    specs = FILES if file_specs is None else file_specs
    if not archive_bytes or len(archive_bytes) > MAX_BUNDLE_BYTES:
        raise OverlayError("bundle_size_invalid")
    try:
        import io

        archive = zipfile.ZipFile(io.BytesIO(archive_bytes))
    except (OSError, zipfile.BadZipFile):
        raise OverlayError("bundle_archive_invalid") from None
    with archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        expected_names = {"manifest.json", *specs}
        if len(names) != len(set(names)) or set(names) != expected_names:
            raise OverlayError("bundle_file_inventory_mismatch")
        data_by_name: dict[str, bytes] = {}
        for info in infos:
            path = Path(info.filename)
            mode = (info.external_attr >> 16) & 0xFFFF
            if (
                info.is_dir()
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in info.filename
                or stat.S_ISLNK(mode)
                or info.file_size > MAX_MEMBER_BYTES
            ):
                raise OverlayError("bundle_member_rejected")
            try:
                member = archive.read(info)
            except (OSError, zipfile.BadZipFile, RuntimeError):
                raise OverlayError("bundle_member_unreadable") from None
            if len(member) != info.file_size:
                raise OverlayError("bundle_member_size_mismatch")
            data_by_name[info.filename] = member
    try:
        manifest = json.loads(data_by_name["manifest.json"])
    except (UnicodeError, json.JSONDecodeError):
        raise OverlayError("bundle_manifest_invalid") from None
    if (
        type(manifest) is not dict
        or set(manifest)
        != {"schema", "base_release_revision", "source_commit", "files"}
        or manifest.get("schema") != BUNDLE_SCHEMA
        or manifest.get("base_release_revision") != base_revision
        or manifest.get("source_commit") != source_commit
        or type(manifest.get("files")) is not list
    ):
        raise OverlayError("bundle_manifest_scope_mismatch")
    expected_records = []
    for relative_path in sorted(specs):
        spec = specs[relative_path]
        data = data_by_name.get(relative_path)
        if data is None:
            raise OverlayError("bundle_file_inventory_mismatch")
        expected_records.append(
            {
                "path": relative_path,
                "size_bytes": len(data),
                "sha256": spec["target"],
                "expected_previous_sha256": spec["previous"],
            }
        )
        if _sha256(data) != spec["target"]:
            raise OverlayError("bundle_file_fingerprint_mismatch")
    if manifest["files"] != expected_records:
        raise OverlayError("bundle_manifest_inventory_mismatch")
    return manifest, {name: data_by_name[name] for name in specs}


def build_package(repo_root: Path, output: Path) -> dict[str, object]:
    root = repo_root.resolve(strict=True)
    try:
        changed = subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain", "--", *FILES],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        raise OverlayError("git_source_unavailable") from None
    if changed:
        raise OverlayError("source_worktree_dirty")
    file_data = {path: _git_bytes(root, SOURCE_COMMIT, path) for path in FILES}
    manifest = _package_manifest(file_data)
    output_path = output.resolve()
    if not output_path.parent.is_dir() or output_path.exists():
        raise OverlayError("bundle_output_path_unavailable")
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr(
            _zip_info("manifest.json"),
            json.dumps(manifest, sort_keys=True).encode("utf-8"),
        )
        for relative_path in sorted(file_data):
            archive.writestr(_zip_info(relative_path), file_data[relative_path])
    archive_bytes = buffer.getvalue()
    _validate_bundle_bytes(archive_bytes)
    try:
        with output_path.open("xb") as stream:
            stream.write(archive_bytes)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        raise OverlayError("bundle_output_write_failed") from None
    return {
        "status": "PACKAGED",
        "source_commit": SOURCE_COMMIT,
        "bundle_sha256": _sha256(archive_bytes),
        "file_count": len(file_data),
        "size_bytes": len(archive_bytes),
        "path": str(output_path),
    }


def _require_root() -> None:
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        raise OverlayError("root_required")


def _lstat(path: Path) -> os.stat_result:
    try:
        result = path.lstat()
    except OSError:
        raise OverlayError("required_path_unavailable") from None
    if stat.S_ISLNK(result.st_mode):
        raise OverlayError("unexpected_symlink")
    return result


def _require_owned(path: Path, *, mode: int | None = None, regular: bool = False) -> os.stat_result:
    result = _lstat(path)
    if result.st_uid != 0 or result.st_gid != 0:
        raise OverlayError("unexpected_path_owner")
    if mode is not None and stat.S_IMODE(result.st_mode) != mode:
        raise OverlayError("unexpected_path_mode")
    if regular and not stat.S_ISREG(result.st_mode):
        raise OverlayError("unexpected_path_type")
    return result


def _require_release() -> None:
    _require_owned(APP_ROOT)
    _require_owned(RELEASE_ROOT)
    revision_path = RELEASE_ROOT / "SOURCE_REVISION"
    _require_owned(revision_path, mode=0o644, regular=True)
    try:
        revision = revision_path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        raise OverlayError("source_revision_unreadable") from None
    if revision != BASE_RELEASE_REVISION:
        raise OverlayError("base_release_revision_mismatch")
    for relative_path in FILES:
        current_directory = RELEASE_ROOT
        for part in Path(relative_path).parts[:-1]:
            current_directory = current_directory / part
            _require_owned(current_directory)
        current = RELEASE_ROOT / relative_path
        _require_owned(current, mode=0o644, regular=True)


def _hash_release_files() -> dict[str, str]:
    _require_release()
    values: dict[str, str] = {}
    for relative_path in FILES:
        try:
            data = (RELEASE_ROOT / relative_path).read_bytes()
        except OSError:
            raise OverlayError("release_file_unreadable") from None
        values[relative_path] = _sha256(data)
    return values


def _load_state() -> dict[str, Any] | None:
    if not os.path.lexists(STATE_PATH):
        return None
    _require_owned(STATE_ROOT, mode=0o700)
    _require_owned(STATE_PATH, mode=0o600, regular=True)
    try:
        raw = STATE_PATH.read_bytes()
        if len(raw) > 16_384:
            raise OverlayError("state_size_invalid")
        value = json.loads(raw)
    except OverlayError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise OverlayError("state_file_invalid") from None
    keys = {
        "schema",
        "base_release_revision",
        "source_commit",
        "bundle_sha256",
        "phase",
        "previous_hashes",
        "target_hashes",
        "backup_directory",
        "updated_at_epoch",
    }
    if (
        type(value) is not dict
        or set(value) != keys
        or value.get("schema") != STATE_SCHEMA
        or value.get("base_release_revision") != BASE_RELEASE_REVISION
        or value.get("source_commit") != SOURCE_COMMIT
        or value.get("phase") not in _CHECKPOINT_PHASES
        or value.get("previous_hashes") != {p: s["previous"] for p, s in FILES.items()}
        or value.get("target_hashes") != {p: s["target"] for p, s in FILES.items()}
        or value.get("backup_directory") != str(BACKUP_ROOT)
        or type(value.get("bundle_sha256")) is not str
        or len(value["bundle_sha256"]) != 64
        or any(char not in "0123456789abcdef" for char in value["bundle_sha256"])
        or type(value.get("updated_at_epoch")) is not int
    ):
        raise OverlayError("state_checkpoint_mismatch")
    return value


def _write_state(phase: str, bundle_sha256: str) -> None:
    _require_owned(STATE_ROOT, mode=0o700)
    state = {
        "schema": STATE_SCHEMA,
        "base_release_revision": BASE_RELEASE_REVISION,
        "source_commit": SOURCE_COMMIT,
        "bundle_sha256": bundle_sha256,
        "phase": phase,
        "previous_hashes": {p: s["previous"] for p, s in FILES.items()},
        "target_hashes": {p: s["target"] for p, s in FILES.items()},
        "backup_directory": str(BACKUP_ROOT),
        "updated_at_epoch": int(time.time()),
    }
    data = json.dumps(state, sort_keys=True).encode("utf-8") + b"\n"
    fd, temporary = tempfile.mkstemp(prefix=".backend-overlay-state-", dir=STATE_ROOT)
    try:
        os.fchown(fd, 0, 0)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, STATE_PATH)
        directory_fd = os.open(STATE_ROOT, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise OverlayError("state_checkpoint_write_failed") from None


def _read_bundle() -> tuple[dict[str, Any], dict[str, bytes], str]:
    _lstat(BUNDLE_PATH)
    info = BUNDLE_PATH.stat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_mode & 0o022
        or info.st_size > MAX_BUNDLE_BYTES
    ):
        raise OverlayError("bundle_path_permissions_invalid")
    try:
        bundle_bytes = BUNDLE_PATH.read_bytes()
    except OSError:
        raise OverlayError("bundle_unreadable") from None
    manifest, files = _validate_bundle_bytes(bundle_bytes)
    return manifest, files, _sha256(bundle_bytes)


def _verify_backup(*, allow_partial: bool = False) -> None:
    _require_owned(BACKUP_ROOT, mode=0o700)
    present: set[str] = set()
    for entry in BACKUP_ROOT.rglob("*"):
        if entry.is_symlink():
            raise OverlayError("backup_symlink_rejected")
        if entry.is_file():
            _require_owned(entry, mode=0o644, regular=True)
            present.add(entry.relative_to(BACKUP_ROOT).as_posix())
        elif entry.is_dir():
            _require_owned(entry)
        else:
            raise OverlayError("backup_entry_type_rejected")
    if not present.issubset(FILES):
        raise OverlayError("backup_inventory_mismatch")
    for relative_path, spec in FILES.items():
        backup = BACKUP_ROOT / relative_path
        if not backup.exists():
            if allow_partial:
                continue
            raise OverlayError("backup_file_missing")
        _require_owned(backup, mode=0o644, regular=True)
        try:
            digest = _sha256(backup.read_bytes())
        except OSError:
            raise OverlayError("backup_unreadable") from None
        if digest != spec["previous"]:
            raise OverlayError("backup_fingerprint_mismatch")


def _backup_previous_files() -> None:
    if os.path.lexists(BACKUP_ROOT):
        _verify_backup(allow_partial=True)
    backup_parent = BACKUP_ROOT.parent
    if not backup_parent.exists():
        backup_parent.mkdir(mode=0o755, parents=True)
        os.chown(backup_parent, 0, 0)
        os.chmod(backup_parent, 0o755)
    _require_owned(backup_parent)
    if not os.path.exists(BACKUP_ROOT):
        BACKUP_ROOT.mkdir(mode=0o700)
        os.chown(BACKUP_ROOT, 0, 0)
        os.chmod(BACKUP_ROOT, 0o700)
    for relative_path, spec in FILES.items():
        source = RELEASE_ROOT / relative_path
        target = BACKUP_ROOT / relative_path
        if not target.parent.exists():
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            os.chown(target.parent, 0, 0)
            os.chmod(target.parent, 0o755)
        if target.exists():
            _require_owned(target, mode=0o644, regular=True)
            if _sha256(target.read_bytes()) != spec["previous"]:
                raise OverlayError("backup_fingerprint_mismatch")
            continue
        data = source.read_bytes()
        if _sha256(data) != spec["previous"]:
            raise OverlayError("pre_overlay_file_fingerprint_mismatch")
        _atomic_replace(target, data)
    _verify_backup()


def _atomic_replace(target: Path, data: bytes) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.overlay-", dir=target.parent)
    try:
        os.fchown(fd, 0, 0)
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise OverlayError("release_file_replace_failed") from None


def _run_command(arguments: list[str]) -> None:
    try:
        result = subprocess.run(arguments, capture_output=True, check=False)
    except (OSError, subprocess.SubprocessError):
        raise OverlayError("required_host_command_unavailable") from None
    if result.returncode != 0:
        raise OverlayError("required_host_command_failed")


def _service_active() -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", SERVICE_NAME],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        raise OverlayError("systemd_unavailable") from None
    return result.returncode == 0


def _health_ready() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=3) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read(64_000))
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
        return False
    data = payload.get("data") if type(payload) is dict else None
    dependencies = data.get("dependencies") if type(data) is dict else None
    if type(dependencies) is not dict:
        return False
    required = {"cat", "rag", "llm_runtime", "safety"}
    if not required.issubset(dependencies):
        return False
    return all(
        type(dependencies[name]) is dict
        and dependencies[name].get("status") in {"READY", "OK"}
        and dependencies[name].get("integration") == "REAL_HTTP"
        for name in required
    )


def _wait_for_health() -> bool:
    deadline = time.monotonic() + HEALTH_WAIT_SECONDS
    while time.monotonic() < deadline:
        if _service_active() and _health_ready():
            return True
        time.sleep(1)
    return False


def _checkpoint_status(
    current_hashes: dict[str, str], state: dict[str, Any] | None
) -> tuple[str, str | None]:
    previous = {path: spec["previous"] for path, spec in FILES.items()}
    target = {path: spec["target"] for path, spec in FILES.items()}
    values = set(current_hashes.values())
    if not values.issubset({*previous.values(), *target.values()}):
        return "BLOCKED", "release_file_fingerprint_mismatch"
    if state is None:
        if current_hashes == previous:
            if os.path.lexists(BACKUP_ROOT):
                try:
                    _verify_backup()
                except OverlayError:
                    return "BLOCKED", "unverified_backup_object_present"
                return "RESUMABLE", None
            return "READY", None
        return "BLOCKED", "missing_checkpoint_for_modified_release"
    phase = state["phase"]
    if phase == "BACKUP_PREPARING" and current_hashes == previous:
        return "RESUMABLE", None
    if phase in {"HTTP_VERIFIED"} and current_hashes == target:
        return "PASS", None
    if phase in {"ROLLED_BACK", "ROLLBACK_HTTP_VERIFIED"} and current_hashes == previous:
        return "READY", None
    if phase == "BACKUP_VERIFIED" and all(
        current_hashes[path] in {previous[path], target[path]} for path in FILES
    ):
        return "RESUMABLE", None
    if phase in {"FILES_INSTALLED", "STARTING", "START_FAILED"} and current_hashes == target:
        return "RESUMABLE", None
    return "BLOCKED", "checkpoint_file_state_mismatch"


def inspect() -> dict[str, object]:
    _require_root()
    _require_owned(STATE_ROOT, mode=0o700)
    current = _hash_release_files()
    state = _load_state()
    status, error_code = _checkpoint_status(current, state)
    if state is not None and status in {"RESUMABLE", "PASS"}:
        _verify_backup(allow_partial=state["phase"] == "BACKUP_PREPARING")
    return {
        "status": status,
        "error_code": error_code,
        "base_release_revision": BASE_RELEASE_REVISION,
        "source_commit": SOURCE_COMMIT,
        "phase": state.get("phase") if state else "NOT_STARTED",
        "service_active": _service_active(),
        "files": {
            path: {
                "sha256": current[path],
                "state": (
                    "PREVIOUS"
                    if current[path] == spec["previous"]
                    else "TARGET"
                    if current[path] == spec["target"]
                    else "UNKNOWN"
                ),
            }
            for path, spec in FILES.items()
        },
    }


def dry_run() -> dict[str, object]:
    current = inspect()
    if current["status"] not in {"READY", "RESUMABLE"}:
        raise OverlayError("recovery_start_state_not_approved")
    manifest, _, bundle_sha256 = _read_bundle()
    state = _load_state()
    if state is not None and state["bundle_sha256"] != bundle_sha256:
        raise OverlayError("bundle_changed_after_checkpoint")
    return {
        "status": "READY",
        "phase": current["phase"],
        "source_commit": manifest["source_commit"],
        "bundle_sha256": bundle_sha256,
        "file_count": len(FILES),
        "actions": ["preserve_previous_files", "install_overlay_atomically", "restart_backend", "verify_http_dependencies"],
        "database_ddl": False,
    }


def resume() -> dict[str, object]:
    current = inspect()
    if current["status"] == "PASS":
        state = _load_state()
        return {"status": "PASS", "phase": state["phase"] if state else "UNKNOWN", "replayed": True}
    if current["status"] not in {"READY", "RESUMABLE"}:
        raise OverlayError("recovery_start_state_not_approved")
    manifest, file_data, bundle_sha256 = _read_bundle()
    state = _load_state()
    if state is not None and state["bundle_sha256"] != bundle_sha256:
        raise OverlayError("bundle_changed_after_checkpoint")
    hashes = _hash_release_files()
    if state is None:
        _write_state("BACKUP_PREPARING", bundle_sha256)
        state = _load_state()
    if state is None:
        raise OverlayError("state_checkpoint_missing")
    if state["phase"] == "BACKUP_PREPARING":
        _backup_previous_files()
        _write_state("BACKUP_VERIFIED", bundle_sha256)
        state = _load_state()
    elif state["phase"] != "BACKUP_VERIFIED":
        _verify_backup()
        if state["phase"] in {"ROLLED_BACK", "ROLLBACK_HTTP_VERIFIED"}:
            _write_state("BACKUP_VERIFIED", bundle_sha256)
            state = _load_state()
    if state is None:
        raise OverlayError("state_checkpoint_missing")
    if state["bundle_sha256"] != bundle_sha256:
        raise OverlayError("bundle_changed_after_checkpoint")
    if hashes != {path: spec["target"] for path, spec in FILES.items()}:
        if state["phase"] not in {"BACKUP_VERIFIED"}:
            raise OverlayError("release_file_state_not_resumable")
        if _service_active():
            _run_command(["systemctl", "stop", SERVICE_NAME])
        for relative_path, data in file_data.items():
            target = RELEASE_ROOT / relative_path
            actual = _sha256(target.read_bytes())
            if actual not in {FILES[relative_path]["previous"], FILES[relative_path]["target"]}:
                raise OverlayError("release_file_fingerprint_mismatch")
            if actual != FILES[relative_path]["target"]:
                _atomic_replace(target, data)
        if _hash_release_files() != {path: spec["target"] for path, spec in FILES.items()}:
            raise OverlayError("overlay_install_verification_failed")
        _write_state("FILES_INSTALLED", bundle_sha256)
        state = _load_state()
    if state is None:
        raise OverlayError("state_checkpoint_missing")
    if state["phase"] == "HTTP_VERIFIED":
        return {"status": "PASS", "phase": "HTTP_VERIFIED", "replayed": True}
    _write_state("STARTING", bundle_sha256)
    _run_command(["systemctl", "start", SERVICE_NAME])
    if not _wait_for_health():
        _write_state("START_FAILED", bundle_sha256)
        raise OverlayError("backend_http_dependency_verification_failed")
    _write_state("HTTP_VERIFIED", bundle_sha256)
    return {
        "status": "PASS",
        "phase": "HTTP_VERIFIED",
        "source_commit": manifest["source_commit"],
        "file_count": len(FILES),
        "backend_active": True,
        "database_ddl": False,
        "deepseek_auth_health": "PASS",
        "safety_rag_cat_health": "PASS",
    }


def rollback() -> dict[str, object]:
    state = _load_state()
    if state is None:
        raise OverlayError("rollback_checkpoint_missing")
    _verify_backup()
    current = _hash_release_files()
    previous = {path: spec["previous"] for path, spec in FILES.items()}
    target = {path: spec["target"] for path, spec in FILES.items()}
    if not all(current[path] in {previous[path], target[path]} for path in FILES):
        raise OverlayError("rollback_release_state_mismatch")
    if _service_active():
        _run_command(["systemctl", "stop", SERVICE_NAME])
    for relative_path in FILES:
        data = (BACKUP_ROOT / relative_path).read_bytes()
        _atomic_replace(RELEASE_ROOT / relative_path, data)
    if _hash_release_files() != previous:
        raise OverlayError("rollback_verification_failed")
    _write_state("ROLLED_BACK", state["bundle_sha256"])
    _run_command(["systemctl", "start", SERVICE_NAME])
    if not _wait_for_health():
        raise OverlayError("rollback_backend_http_verification_failed")
    _write_state("ROLLBACK_HTTP_VERIFIED", state["bundle_sha256"])
    return {"status": "ROLLED_BACK", "phase": "ROLLBACK_HTTP_VERIFIED", "backup_preserved": True}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--package", action="store_true")
    group.add_argument("--inspect", action="store_true")
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--resume", action="store_true")
    group.add_argument("--rollback", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.package:
            if args.output is None:
                raise OverlayError("bundle_output_required")
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
        return 0
    except OverlayError as exc:
        print(json.dumps({"status": "BLOCKED", "error_code": exc.code}, sort_keys=True))
        return 2
    except OSError:
        print(json.dumps({"status": "BLOCKED", "error_code": "host_io_failure"}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
