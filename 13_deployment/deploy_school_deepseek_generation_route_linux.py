"""Safely overlay the missing DeepSeek education-generation route on the school release."""

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
from typing import Any, Self

BASE_RELEASE_REVISION = "f3047642aa3466f9b4f210f4f704d57fd2cdf3cc"
SOURCE_COMMIT = "ecdd26ed90e1020e6bddbb3682388641e8da8236"
SERVER_HOSTNAME = "iZ0xic24d9gxb9udjbfo0kZ"
APP_ROOT = Path("/opt/psynova-school-demo")
RELEASE_ROOT = APP_ROOT / "release"
STATE_ROOT = Path("/var/lib/psynova-school-demo")
STATE_PATH = STATE_ROOT / "deepseek-generation-route-state.json"
LOCK_PATH = Path("/run/lock/psynova-school-deepseek-generation-route.lock")
BACKUP_ROOT = APP_ROOT / "backups" / f"deepseek-generation-route-{SOURCE_COMMIT[:12]}"
BACKUP_FILE = BACKUP_ROOT / "independent.py.before"
STAGING_ROOT = Path("/home/psynova/apps/psynova/staging/linux-school-demo")
BUNDLE_PATH = STAGING_ROOT / f"deepseek-generation-route-{SOURCE_COMMIT[:12]}.zip"
LLM_SERVICE = "psynova-school-llm.service"
BACKEND_SERVICE = "psynova-school-demo.service"
LLM_READY_URL = "http://127.0.0.1:8160/health/ready"
BACKEND_HEALTH_URL = "http://127.0.0.1:8088/api/v1/health"
STATE_SCHEMA = "psynova.school-deepseek-generation-route-state.v1"
BUNDLE_SCHEMA = "psynova.school-deepseek-generation-route.v1"
MAX_BUNDLE_BYTES = 1_000_000
MAX_MEMBER_BYTES = 512_000
HEALTH_WAIT_SECONDS = 90
PREVIOUS_BACKEND_SHA256 = "ce262d6b420a4bea25223daa1a6daaa51d47620f69d04b82dc1f8c7cb6652a9d"

PACKAGE_FILES = {
    "backend/independent.py": {
        "source": "09_backend/src/smhai_backend/integrations/independent.py",
        "sha256": "62ba1398b9cc296e78398b99d8a6199a0f96b678a5ae57ae1844c528deaf0b0c",
        "destination": RELEASE_ROOT
        / "09_backend/src/smhai_backend/integrations/independent.py",
        "previous_sha256": PREVIOUS_BACKEND_SHA256,
    },
    "release/13_deployment/school_independent_runtime.py": {
        "source": "13_deployment/school_independent_runtime.py",
        "sha256": "94f44ab5836d527a23466288ee46e2643907735fbda58e6a796b498a72f92534",
        "destination": RELEASE_ROOT / "13_deployment/school_independent_runtime.py",
        "previous_sha256": None,
    },
    "release/13_deployment/school_deepseek_independent_runtime.py": {
        "source": "13_deployment/school_deepseek_independent_runtime.py",
        "sha256": "5a5f4207fdd45ad3951a75b935cf446905a3957219ba233aa507d9ec0ee1ea87",
        "destination": RELEASE_ROOT / "13_deployment/school_deepseek_independent_runtime.py",
        "previous_sha256": None,
    },
    "release/13_deployment/school_deepseek_runtime_linux.py": {
        "source": "13_deployment/school_deepseek_runtime_linux.py",
        "sha256": "742eddb8352b11eba2ced025a1b22f3a71e1c0b195f13f8d1c1a46ecc6bf106b",
        "destination": RELEASE_ROOT / "13_deployment/school_deepseek_runtime_linux.py",
        "previous_sha256": None,
    },
    "systemd/30-independent-route.conf": {
        "source": "13_deployment/systemd/psynova-school-llm-independent-route.conf",
        "sha256": "c8bf94d9d64f3f907bb980b7be1e579a7b1b6bc433a95ca2149062218ae5a031",
        "destination": Path(
            "/etc/systemd/system/psynova-school-llm.service.d/30-independent-route.conf"
        ),
        "previous_sha256": None,
    },
}
PHASES = {
    "PREPARED",
    "BACKUP_VERIFIED",
    "PAYLOAD_INSTALLED",
    "LLM_RESTARTED",
    "BACKEND_RESTARTED",
    "VERIFIED",
}


class DeployError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_bytes(repo_root: Path, relative_path: str) -> bytes:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo_root), "show", f"{SOURCE_COMMIT}:{relative_path}"],
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        raise DeployError("source_file_unavailable") from None


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    return info


def _validate_bundle(
    archive_bytes: bytes,
    *,
    file_specs: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    specs = PACKAGE_FILES if file_specs is None else file_specs
    if not archive_bytes or len(archive_bytes) > MAX_BUNDLE_BYTES:
        raise DeployError("bundle_size_invalid")
    try:
        import io

        archive = zipfile.ZipFile(io.BytesIO(archive_bytes))
    except (OSError, zipfile.BadZipFile):
        raise DeployError("bundle_archive_invalid") from None
    with archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if len(names) != len(set(names)) or set(names) != {"manifest.json", *specs}:
            raise DeployError("bundle_inventory_mismatch")
        files: dict[str, bytes] = {}
        for info in infos:
            path = PurePosixPath(info.filename)
            mode = (info.external_attr >> 16) & 0xFFFF
            if (
                info.is_dir()
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in info.filename
                or stat.S_ISLNK(mode)
                or info.file_size > MAX_MEMBER_BYTES
            ):
                raise DeployError("bundle_member_rejected")
            try:
                data = archive.read(info)
            except (OSError, RuntimeError, zipfile.BadZipFile):
                raise DeployError("bundle_member_unreadable") from None
            if len(data) != info.file_size:
                raise DeployError("bundle_member_size_mismatch")
            files[info.filename] = data
    try:
        manifest = json.loads(files["manifest.json"])
    except (UnicodeError, json.JSONDecodeError):
        raise DeployError("bundle_manifest_invalid") from None
    if (
        type(manifest) is not dict
        or set(manifest) != {"schema", "base_release_revision", "source_commit", "files"}
        or manifest.get("schema") != BUNDLE_SCHEMA
        or manifest.get("base_release_revision") != BASE_RELEASE_REVISION
        or manifest.get("source_commit") != SOURCE_COMMIT
        or type(manifest.get("files")) is not list
    ):
        raise DeployError("bundle_scope_mismatch")
    records = []
    for name, spec in sorted(specs.items()):
        data = files.get(name)
        if data is None or _sha256(data) != spec["sha256"]:
            raise DeployError("bundle_file_fingerprint_mismatch")
        records.append({"path": name, "size_bytes": len(data), "sha256": spec["sha256"]})
    if manifest["files"] != records:
        raise DeployError("bundle_manifest_inventory_mismatch")
    return manifest, {name: files[name] for name in specs}


def build_package(repo_root: Path, output: Path) -> dict[str, object]:
    root = repo_root.resolve(strict=True)
    source_paths = [spec["source"] for spec in PACKAGE_FILES.values()]
    try:
        dirty = subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain", "--", *source_paths],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        raise DeployError("git_source_unavailable") from None
    if dirty:
        raise DeployError("source_worktree_dirty")
    files = {
        name: _git_bytes(root, spec["source"])
        for name, spec in PACKAGE_FILES.items()
    }
    records = [
        {"path": name, "size_bytes": len(data), "sha256": _sha256(data)}
        for name, data in sorted(files.items())
    ]
    manifest = {
        "schema": BUNDLE_SCHEMA,
        "base_release_revision": BASE_RELEASE_REVISION,
        "source_commit": SOURCE_COMMIT,
        "files": records,
    }
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr(_zip_info("manifest.json"), json.dumps(manifest, sort_keys=True).encode())
        for name, data in sorted(files.items()):
            archive.writestr(_zip_info(name), data)
    raw = buffer.getvalue()
    _validate_bundle(raw)
    destination = output.resolve()
    if not destination.parent.is_dir() or destination.exists():
        raise DeployError("bundle_output_path_unavailable")
    try:
        with destination.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        raise DeployError("bundle_output_write_failed") from None
    return {
        "status": "PACKAGED",
        "source_commit": SOURCE_COMMIT,
        "bundle_sha256": _sha256(raw),
        "file_count": len(files),
        "size_bytes": len(raw),
        "path": str(destination),
    }


def _require_root() -> None:
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        raise DeployError("root_required")


def _require_server_identity() -> None:
    try:
        hostname = socket.gethostname()
    except OSError:
        raise DeployError("server_identity_unavailable") from None
    if hostname != SERVER_HOSTNAME:
        raise DeployError("server_identity_mismatch")


def _require_owned(path: Path, *, mode: int | None = None, regular: bool = False) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError:
        raise DeployError("required_path_unavailable") from None
    if stat.S_ISLNK(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_gid != 0:
        raise DeployError("unexpected_path_owner_or_type")
    if mode is not None and stat.S_IMODE(metadata.st_mode) != mode:
        raise DeployError("unexpected_path_mode")
    if regular and not stat.S_ISREG(metadata.st_mode):
        raise DeployError("unexpected_path_type")
    return metadata


def _require_release() -> None:
    _require_owned(APP_ROOT, mode=0o755)
    _require_owned(RELEASE_ROOT, mode=0o755)
    revision_file = RELEASE_ROOT / "SOURCE_REVISION"
    _require_owned(revision_file, mode=0o644, regular=True)
    try:
        revision = revision_file.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        raise DeployError("source_revision_unreadable") from None
    if revision != BASE_RELEASE_REVISION:
        raise DeployError("base_release_revision_mismatch")


def _require_baseline_unit(state: dict[str, Any] | None) -> None:
    unit_path = Path("/etc/systemd/system/psynova-school-llm.service")
    _require_owned(unit_path, mode=0o644, regular=True)
    _require_owned(unit_path.parent / "psynova-school-llm.service.d", mode=0o755)
    try:
        result = subprocess.run(
            ["systemctl", "show", LLM_SERVICE, "--property=ExecStart", "--value"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise DeployError("systemd_inspection_unavailable") from None
    baseline = (
        result.returncode == 0
        and "/opt/psynova-school-demo/services/llm/venv/bin/python" in result.stdout
        and "-m llm_runtime.api.app" in result.stdout
    )
    overlay = False
    dropin = PACKAGE_FILES["systemd/30-independent-route.conf"]["destination"]
    if state is not None and os.path.lexists(dropin):
        _require_owned(dropin, mode=0o644, regular=True)
        try:
            dropin_hash = _sha256(dropin.read_bytes())
        except OSError:
            raise DeployError("route_dropin_unreadable") from None
        overlay = (
            result.returncode == 0
            and "/opt/psynova-school-demo/services/llm/venv/bin/python" in result.stdout
            and "-m school_deepseek_runtime_linux" in result.stdout
            and dropin_hash == PACKAGE_FILES["systemd/30-independent-route.conf"]["sha256"]
        )
    if not (baseline or overlay):
        raise DeployError("baseline_llm_unit_mismatch")


def _targets() -> dict[str, Path]:
    return {name: spec["destination"] for name, spec in PACKAGE_FILES.items()}


def _load_state() -> dict[str, Any] | None:
    if not os.path.lexists(STATE_PATH):
        return None
    _require_owned(STATE_ROOT, mode=0o700)
    _require_owned(STATE_PATH, mode=0o600, regular=True)
    try:
        if STATE_PATH.stat().st_size > 16_384:
            raise DeployError("state_size_invalid")
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except DeployError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise DeployError("state_file_invalid") from None
    expected = {
        "schema": STATE_SCHEMA,
        "base_release_revision": BASE_RELEASE_REVISION,
        "source_commit": SOURCE_COMMIT,
        "bundle_sha256": state.get("bundle_sha256") if type(state) is dict else None,
        "phase": state.get("phase") if type(state) is dict else None,
        "previous_backend_sha256": PREVIOUS_BACKEND_SHA256,
        "target_hashes": {name: spec["sha256"] for name, spec in PACKAGE_FILES.items()},
        "backup_file": str(BACKUP_FILE),
        "updated_at_epoch": state.get("updated_at_epoch") if type(state) is dict else None,
    }
    if (
        type(state) is not dict
        or set(state) != set(expected)
        or state != expected
        or state.get("phase") not in PHASES
        or type(state.get("bundle_sha256")) is not str
        or len(state["bundle_sha256"]) != 64
        or any(char not in "0123456789abcdef" for char in state["bundle_sha256"])
        or type(state.get("updated_at_epoch")) is not int
    ):
        raise DeployError("state_checkpoint_mismatch")
    return state


def _write_state(phase: str, bundle_sha256: str) -> None:
    _require_owned(STATE_ROOT, mode=0o700)
    state = {
        "schema": STATE_SCHEMA,
        "base_release_revision": BASE_RELEASE_REVISION,
        "source_commit": SOURCE_COMMIT,
        "bundle_sha256": bundle_sha256,
        "phase": phase,
        "previous_backend_sha256": PREVIOUS_BACKEND_SHA256,
        "target_hashes": {name: spec["sha256"] for name, spec in PACKAGE_FILES.items()},
        "backup_file": str(BACKUP_FILE),
        "updated_at_epoch": int(time.time()),
    }
    data = json.dumps(state, sort_keys=True).encode("utf-8") + b"\n"
    fd, temporary = tempfile.mkstemp(prefix=".deepseek-route-state-", dir=STATE_ROOT)
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
        raise DeployError("state_checkpoint_write_failed") from None


def _read_bundle() -> tuple[dict[str, bytes], str]:
    try:
        metadata = BUNDLE_PATH.lstat()
    except OSError:
        raise DeployError("bundle_unavailable") from None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_mode & 0o022
        or metadata.st_size > MAX_BUNDLE_BYTES
    ):
        raise DeployError("bundle_permissions_invalid")
    try:
        raw = BUNDLE_PATH.read_bytes()
    except OSError:
        raise DeployError("bundle_unreadable") from None
    _, files = _validate_bundle(raw)
    return files, _sha256(raw)


def _target_status(state: dict[str, Any] | None) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for name, spec in PACKAGE_FILES.items():
        path = spec["destination"]
        _require_owned(path.parent)
        if not os.path.lexists(path):
            if spec["previous_sha256"] is None:
                statuses[name] = "ABSENT"
                continue
            raise DeployError("required_backend_file_missing")
        _require_owned(path, mode=0o644, regular=True)
        try:
            digest = _sha256(path.read_bytes())
        except OSError:
            raise DeployError("target_file_unreadable") from None
        if digest == spec["sha256"]:
            if state is None:
                raise DeployError("uncheckpointed_target_file_present")
            statuses[name] = "TARGET"
        elif spec["previous_sha256"] is not None and digest == spec["previous_sha256"]:
            if state is not None and state["phase"] not in {"PREPARED", "BACKUP_VERIFIED"}:
                raise DeployError("checkpoint_target_file_rolled_back")
            statuses[name] = "PREVIOUS"
        else:
            raise DeployError("target_file_fingerprint_mismatch")
    return statuses


def _verify_backup(state: dict[str, Any] | None) -> bool:
    if not os.path.lexists(BACKUP_ROOT):
        return False
    _require_owned(BACKUP_ROOT, mode=0o700)
    if not os.path.lexists(BACKUP_FILE):
        if state is not None and state.get("phase") == "PREPARED":
            return False
        raise DeployError("backup_file_missing")
    _require_owned(BACKUP_FILE, mode=0o644, regular=True)
    try:
        digest = _sha256(BACKUP_FILE.read_bytes())
    except OSError:
        raise DeployError("backup_file_unreadable") from None
    if digest != PREVIOUS_BACKEND_SHA256:
        raise DeployError("backup_file_fingerprint_mismatch")
    if state is None:
        raise DeployError("uncheckpointed_backup_directory_exists")
    return True


def _inspect(state: dict[str, Any] | None, bundle_sha: str, targets: dict[str, str]) -> int:
    if state is not None and state["bundle_sha256"] != bundle_sha:
        raise DeployError("bundle_checkpoint_mismatch")
    backup_present = _verify_backup(state)
    complete = state is not None and state["phase"] == "VERIFIED" and all(
        value == "TARGET" for value in targets.values()
    )
    print(
        json.dumps(
            {
                "status": "PASS" if complete else "RESUMABLE" if state else "READY",
                "phase": state["phase"] if state else "NOT_STARTED",
                "target_files": targets,
                "backup_verified": backup_present,
                "writes": False,
            },
            sort_keys=True,
        )
    )
    return 0


def _dry_run(state: dict[str, Any] | None, bundle_sha: str, targets: dict[str, str]) -> int:
    if state is not None and state["bundle_sha256"] != bundle_sha:
        raise DeployError("bundle_checkpoint_mismatch")
    print(
        json.dumps(
            {
                "status": "READY_TO_RESUME",
                "phase": state["phase"] if state else "NOT_STARTED",
                "target_count": len(targets),
                "target_changes_remaining": sum(value != "TARGET" for value in targets.values()),
                "restart_services": [LLM_SERVICE, BACKEND_SERVICE],
                "database_ddl": False,
                "writes": False,
            },
            sort_keys=True,
        )
    )
    return 0


def _atomic_write(path: Path, data: bytes, *, replace_previous: bool) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.route-overlay-", dir=path.parent)
    try:
        os.fchown(fd, 0, 0)
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if replace_previous:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
            os.unlink(temporary)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except FileExistsError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise DeployError("target_appeared_during_install") from None
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise DeployError("target_install_failed") from None


def _backup_backend_file(*, allow_partial: bool) -> None:
    if os.path.lexists(BACKUP_ROOT):
        _require_owned(BACKUP_ROOT, mode=0o700)
        if os.path.lexists(BACKUP_FILE):
            _require_owned(BACKUP_FILE, mode=0o644, regular=True)
            if _sha256(BACKUP_FILE.read_bytes()) != PREVIOUS_BACKEND_SHA256:
                raise DeployError("backup_file_fingerprint_mismatch")
            return
        if not allow_partial:
            raise DeployError("backup_file_missing")
    else:
        _require_owned(BACKUP_ROOT.parent)
        BACKUP_ROOT.mkdir(mode=0o700)
        os.chown(BACKUP_ROOT, 0, 0)
        os.chmod(BACKUP_ROOT, 0o700)
    source = PACKAGE_FILES["backend/independent.py"]["destination"]
    try:
        data = source.read_bytes()
    except OSError:
        raise DeployError("backend_backup_source_unreadable") from None
    if _sha256(data) != PREVIOUS_BACKEND_SHA256:
        raise DeployError("backend_backup_source_fingerprint_mismatch")
    _atomic_write(BACKUP_FILE, data, replace_previous=False)
    _verify_backup({"phase": "PREPARED"})


def _run(arguments: list[str], code: str, *, timeout: int = 120) -> None:
    try:
        result = subprocess.run(
            arguments,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise DeployError(code) from None
    if result.returncode != 0:
        raise DeployError(code)


def _service_active(name: str) -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _health_ready(url: str, *, backend: bool) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read(64_000))
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
        return False
    if not backend:
        return type(payload) is dict and payload.get("status") == "READY"
    data = payload.get("data") if type(payload) is dict else None
    dependencies = data.get("dependencies") if type(data) is dict else None
    required = {"cat", "rag", "llm_runtime", "safety"}
    return (
        type(dependencies) is dict
        and required.issubset(dependencies)
        and all(
            type(dependencies[name]) is dict
            and dependencies[name].get("status") in {"READY", "OK"}
            and dependencies[name].get("integration") == "REAL_HTTP"
            for name in required
        )
    )


def _require_loopback_listeners() -> None:
    try:
        result = subprocess.run(
            ["ss", "-lnt"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        raise DeployError("listener_check_unavailable") from None
    if result.returncode != 0:
        raise DeployError("listener_check_failed")
    expected = {"127.0.0.1:8160", "127.0.0.1:8088"}
    listeners = {
        part
        for line in result.stdout.splitlines()
        for part in line.split()
        if part.startswith(("127.0.0.1:", "0.0.0.0:", "[::]:", "*:"))
    }
    if not expected.issubset(listeners) or any(
        item.endswith((":8160", ":8088"))
        for item in listeners - expected
    ):
        raise DeployError("service_listener_not_loopback")


def _wait_ready() -> None:
    deadline = time.monotonic() + HEALTH_WAIT_SECONDS
    while time.monotonic() < deadline:
        if (
            _service_active(LLM_SERVICE)
            and _service_active(BACKEND_SERVICE)
            and _health_ready(LLM_READY_URL, backend=False)
            and _health_ready(BACKEND_HEALTH_URL, backend=True)
        ):
            _require_loopback_listeners()
            return
        time.sleep(2)
    raise DeployError("services_not_ready_after_restart")


def _wait_llm_ready() -> None:
    deadline = time.monotonic() + HEALTH_WAIT_SECONDS
    while time.monotonic() < deadline:
        if _service_active(LLM_SERVICE) and _health_ready(LLM_READY_URL, backend=False):
            _require_loopback_listeners()
            return
        time.sleep(2)
    raise DeployError("llm_service_not_ready_after_restart")


def _resume(state: dict[str, Any] | None, bundle_sha: str, files: dict[str, bytes]) -> int:
    if state is not None and state["bundle_sha256"] != bundle_sha:
        raise DeployError("bundle_checkpoint_mismatch")
    targets = _target_status(state)
    if state is not None and state["phase"] == "VERIFIED":
        _wait_ready()
        print(json.dumps({"status": "PASS", "phase": "VERIFIED", "route": "LOOPBACK_AUTHENTICATED", "database_ddl": False}, sort_keys=True))
        return 0
    prior_phase = state["phase"] if state is not None else None
    if state is None:
        state = {"phase": "PREPARED"}
        _write_state("PREPARED", bundle_sha)
    _backup_backend_file(allow_partial=state["phase"] == "PREPARED")
    if state["phase"] in {"PREPARED", "BACKUP_VERIFIED"}:
        _write_state("BACKUP_VERIFIED", bundle_sha)
    for name, spec in PACKAGE_FILES.items():
        target = spec["destination"]
        current = targets[name]
        if current == "TARGET":
            continue
        _atomic_write(
            target,
            files[name],
            replace_previous=current == "PREVIOUS",
        )
    _write_state("PAYLOAD_INSTALLED", bundle_sha)
    _run(["systemctl", "daemon-reload"], "systemd_reload_failed")
    llm_already_ready = (
        prior_phase in {"LLM_RESTARTED", "BACKEND_RESTARTED"}
        and _service_active(LLM_SERVICE)
        and _health_ready(LLM_READY_URL, backend=False)
    )
    if not llm_already_ready:
        _run(["systemctl", "restart", LLM_SERVICE], "llm_service_restart_failed", timeout=180)
        _write_state("LLM_RESTARTED", bundle_sha)
        _wait_llm_ready()
    backend_already_ready = (
        prior_phase == "BACKEND_RESTARTED"
        and _service_active(BACKEND_SERVICE)
        and _health_ready(BACKEND_HEALTH_URL, backend=True)
    )
    if not backend_already_ready:
        _run(["systemctl", "restart", BACKEND_SERVICE], "backend_service_restart_failed", timeout=180)
        _write_state("BACKEND_RESTARTED", bundle_sha)
    _wait_ready()
    _write_state("VERIFIED", bundle_sha)
    print(
        json.dumps(
            {
                "status": "PASS",
                "phase": "VERIFIED",
                "source_commit": SOURCE_COMMIT,
                "route": "LOOPBACK_AUTHENTICATED",
                "llm_listener": "127.0.0.1:8160",
                "backend_listener": "127.0.0.1:8088",
                "database_ddl": False,
            },
            sort_keys=True,
        )
    )
    return 0


def _exclusive_lock():
    import fcntl

    class Lock:
        def __enter__(self) -> Self:
            _require_root()
            self.fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
            os.fchown(self.fd, 0, 0)
            os.fchmod(self.fd, 0o600)
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(self.fd)
                raise DeployError("deployment_lock_busy") from None
            return self

        def __exit__(self, *_: object) -> None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)

    return Lock()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--package", type=Path)
    actions.add_argument("--inspect", action="store_true")
    actions.add_argument("--dry-run", action="store_true")
    actions.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    try:
        if args.package is not None:
            if args.repo_root is None:
                raise DeployError("repo_root_required")
            print(json.dumps(build_package(args.repo_root, args.package), sort_keys=True))
            return 0
        _require_root()
        _require_server_identity()
        _require_release()
        _require_owned(STATE_ROOT, mode=0o700)
        state = _load_state()
        files, bundle_sha = _read_bundle()
        _require_baseline_unit(state)
        targets = _target_status(state)
        if args.inspect:
            return _inspect(state, bundle_sha, targets)
        if args.dry_run:
            return _dry_run(state, bundle_sha, targets)
        with _exclusive_lock():
            return _resume(state, bundle_sha, files)
    except DeployError as exc:
        print(json.dumps({"status": "BLOCKED", "error_code": exc.code}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
