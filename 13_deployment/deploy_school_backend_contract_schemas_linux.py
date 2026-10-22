"""Package and safely add the frozen Backend contract schemas to the school release."""

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
import zipfile
from pathlib import Path
from typing import Any, Self

BASE_RELEASE_REVISION = "f3047642aa3466f9b4f210f4f704d57fd2cdf3cc"
SOURCE_COMMIT = "ba2a1d0d881212b7f4a941cdef1c2b04dd4d7c3d"
SERVER_HOSTNAME = "iZ0xic24d9gxb9udjbfo0kZ"
APP_ROOT = Path("/opt/psynova-school-demo")
RELEASE_ROOT = APP_ROOT / "release"
STATE_ROOT = Path("/var/lib/psynova-school-demo")
STATE_PATH = STATE_ROOT / "backend-contract-schemas-state.json"
LOCK_PATH = Path("/run/lock/psynova-school-backend-contract-schemas.lock")
BUNDLE_PATH = Path(
    "/home/psynova/apps/psynova/staging/linux-school-demo/"
    f"backend-contract-schemas-{SOURCE_COMMIT}.zip"
)
TARGET_ROOT = RELEASE_ROOT / "00_architecture" / "schemas"
VENV_PYTHON = APP_ROOT / "venv" / "bin" / "python"
STATE_SCHEMA = "psynova.school-backend-contract-schemas-state.v1"
BUNDLE_SCHEMA = "psynova.school-backend-contract-schemas.v1"
MAX_BUNDLE_BYTES = 1_000_000
MAX_SCHEMA_BYTES = 256_000

# These are the only frozen schema files referenced by the deployed Backend.
SCHEMAS = {
    "assessment.v1.schema.json": "c3e3c3bc6570a85e5d178a77efe9c97ac1e6020ca4573a42c157c4fc3b5446e5",
    "generation.v1.schema.json": "8365d7ea825a30d9429361107750e87e8c6446d0a6576c47f3a8ece564dca62c",
    "knowledge.v1.schema.json": "5334533db35b30840f57e8012208037a6809bfed7ce08094bda1517c801d8bcf",
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
        raise DeployError("source_schema_unavailable") from None


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    return info


def _schema_paths() -> dict[str, str]:
    return {f"00_architecture/schemas/{name}": digest for name, digest in SCHEMAS.items()}


def _validate_bundle(
    archive_bytes: bytes,
    *,
    expected_hashes: dict[str, str] | None = None,
    source_commit: str = SOURCE_COMMIT,
    base_revision: str = BASE_RELEASE_REVISION,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    hashes = _schema_paths() if expected_hashes is None else expected_hashes
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
        expected_names = {"manifest.json", *hashes}
        if len(names) != len(set(names)) or set(names) != expected_names:
            raise DeployError("bundle_inventory_mismatch")
        members: dict[str, bytes] = {}
        for info in infos:
            path = Path(info.filename)
            mode = (info.external_attr >> 16) & 0xFFFF
            if (
                info.is_dir()
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in info.filename
                or stat.S_ISLNK(mode)
                or info.file_size > MAX_SCHEMA_BYTES
            ):
                raise DeployError("bundle_member_rejected")
            try:
                data = archive.read(info)
            except (OSError, RuntimeError, zipfile.BadZipFile):
                raise DeployError("bundle_member_unreadable") from None
            if len(data) != info.file_size:
                raise DeployError("bundle_member_size_mismatch")
            members[info.filename] = data
    try:
        manifest = json.loads(members["manifest.json"])
    except (UnicodeError, json.JSONDecodeError):
        raise DeployError("bundle_manifest_invalid") from None
    if (
        type(manifest) is not dict
        or set(manifest) != {"schema", "base_release_revision", "source_commit", "files"}
        or manifest.get("schema") != BUNDLE_SCHEMA
        or manifest.get("base_release_revision") != base_revision
        or manifest.get("source_commit") != source_commit
        or type(manifest.get("files")) is not list
    ):
        raise DeployError("bundle_scope_mismatch")
    expected_records = []
    for path, digest in sorted(hashes.items()):
        data = members.get(path)
        if data is None or _sha256(data) != digest:
            raise DeployError("bundle_schema_fingerprint_mismatch")
        expected_records.append(
            {"path": path, "size_bytes": len(data), "sha256": digest}
        )
    if manifest["files"] != expected_records:
        raise DeployError("bundle_manifest_inventory_mismatch")
    return manifest, {path: members[path] for path in hashes}


def build_package(repo_root: Path, output: Path) -> dict[str, object]:
    root = repo_root.resolve(strict=True)
    paths = list(_schema_paths())
    try:
        dirty = subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain", "--", *paths],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        raise DeployError("git_source_unavailable") from None
    if dirty:
        raise DeployError("source_schema_worktree_dirty")
    files = {path: _git_bytes(root, SOURCE_COMMIT, path) for path in paths}
    for path, data in files.items():
        if _sha256(data) != _schema_paths()[path]:
            raise DeployError("source_schema_fingerprint_mismatch")
    records = [
        {"path": path, "size_bytes": len(data), "sha256": _sha256(data)}
        for path, data in sorted(files.items())
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
        for path, data in sorted(files.items()):
            archive.writestr(_zip_info(path), data)
    package = buffer.getvalue()
    _validate_bundle(package)
    destination = output.resolve()
    if not destination.parent.is_dir() or destination.exists():
        raise DeployError("bundle_output_path_unavailable")
    try:
        with destination.open("xb") as stream:
            stream.write(package)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        raise DeployError("bundle_output_write_failed") from None
    return {
        "status": "PACKAGED",
        "source_commit": SOURCE_COMMIT,
        "bundle_sha256": _sha256(package),
        "file_count": len(files),
        "size_bytes": len(package),
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
        result = path.lstat()
    except OSError:
        raise DeployError("required_path_unavailable") from None
    if stat.S_ISLNK(result.st_mode) or result.st_uid != 0 or result.st_gid != 0:
        raise DeployError("unexpected_path_owner_or_type")
    if mode is not None and stat.S_IMODE(result.st_mode) != mode:
        raise DeployError("unexpected_path_mode")
    if regular and not stat.S_ISREG(result.st_mode):
        raise DeployError("unexpected_path_type")
    return result


def _require_release() -> None:
    _require_owned(APP_ROOT, mode=0o755)
    _require_owned(RELEASE_ROOT, mode=0o755)
    revision_path = RELEASE_ROOT / "SOURCE_REVISION"
    _require_owned(revision_path, mode=0o644, regular=True)
    try:
        revision = revision_path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        raise DeployError("source_revision_unreadable") from None
    if revision != BASE_RELEASE_REVISION:
        raise DeployError("base_release_revision_mismatch")


def _read_bundle() -> tuple[dict[str, Any], dict[str, bytes], str]:
    try:
        info = BUNDLE_PATH.lstat()
    except OSError:
        raise DeployError("bundle_unavailable") from None
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_mode & 0o022
        or info.st_size > MAX_BUNDLE_BYTES
    ):
        raise DeployError("bundle_permissions_invalid")
    try:
        raw = BUNDLE_PATH.read_bytes()
    except OSError:
        raise DeployError("bundle_unreadable") from None
    manifest, files = _validate_bundle(raw)
    return manifest, files, _sha256(raw)


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
        "phase": state.get("phase") if type(state) is dict else None,
        "schema_hashes": _schema_paths(),
        "bundle_sha256": state.get("bundle_sha256") if type(state) is dict else None,
        "updated_at_epoch": state.get("updated_at_epoch") if type(state) is dict else None,
    }
    if (
        type(state) is not dict
        or set(state) != set(expected)
        or state != expected
        or state.get("phase") not in {"PREPARED", "DIRECTORIES_CREATED", "FILES_INSTALLED", "VERIFIED"}
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
        "phase": phase,
        "schema_hashes": _schema_paths(),
        "bundle_sha256": bundle_sha256,
        "updated_at_epoch": int(time.time()),
    }
    data = json.dumps(state, sort_keys=True).encode("utf-8") + b"\n"
    fd, temporary = tempfile.mkstemp(prefix=".backend-contract-schemas-", dir=STATE_ROOT)
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


def _directory_state(state: dict[str, Any] | None) -> str:
    if os.path.lexists(TARGET_ROOT):
        if state is None:
            raise DeployError("uncheckpointed_schema_directory_exists")
        _require_owned(RELEASE_ROOT / "00_architecture", mode=0o755)
        _require_owned(TARGET_ROOT, mode=0o755)
        return "present"
    architecture = RELEASE_ROOT / "00_architecture"
    if os.path.lexists(architecture):
        if state is None:
            raise DeployError("uncheckpointed_schema_parent_exists")
        _require_owned(architecture, mode=0o755)
    return "absent"


def _target_state(state: dict[str, Any] | None) -> dict[str, str]:
    _directory_state(state)
    results: dict[str, str] = {}
    for relative, expected_hash in _schema_paths().items():
        target = RELEASE_ROOT / relative
        if not os.path.lexists(target):
            results[relative] = "ABSENT"
            continue
        if state is None:
            raise DeployError("uncheckpointed_schema_file_exists")
        _require_owned(target, mode=0o644, regular=True)
        try:
            digest = _sha256(target.read_bytes())
        except OSError:
            raise DeployError("schema_file_unreadable") from None
        if digest != expected_hash:
            raise DeployError("schema_file_fingerprint_mismatch")
        results[relative] = "MATCH"
    return results


def _probe_project_root() -> bool:
    code = (
        "import json; from pathlib import Path; "
        "from smhai_backend.integrations.contracts import project_root; "
        f"root=project_root(); expected=Path({str(RELEASE_ROOT)!r}); "
        "assert root == expected; "
        f"[json.loads((root / '00_architecture' / 'schemas' / name).read_text(encoding='utf-8')) "
        f"for name in {list(SCHEMAS)!r}]; "
        "print('PASS')"
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(RELEASE_ROOT / "09_backend" / "src")
    try:
        result = subprocess.run(
            [str(VENV_PYTHON), "-c", code],
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise DeployError("contract_schema_probe_unavailable") from None
    if result.returncode != 0 or result.stdout.strip() != "PASS":
        raise DeployError("contract_schema_probe_failed")
    return True


def _inspect(state: dict[str, Any] | None, bundle_hash: str, targets: dict[str, str]) -> int:
    if state is not None and state["bundle_sha256"] != bundle_hash:
        raise DeployError("bundle_checkpoint_mismatch")
    files_match = all(value == "MATCH" for value in targets.values())
    complete = files_match and state is not None and state["phase"] == "VERIFIED"
    print(
        json.dumps(
            {
                "status": "PASS" if complete else "RESUMABLE" if files_match else "READY",
                "phase": state["phase"] if state is not None else "NOT_STARTED",
                "target_files": targets,
                "project_root_probe": "PASS" if files_match and _probe_project_root() else "NOT_RUN",
                "writes": False,
            },
            sort_keys=True,
        )
    )
    return 0


def _dry_run(state: dict[str, Any] | None, bundle_hash: str, targets: dict[str, str]) -> int:
    if state is not None and state["bundle_sha256"] != bundle_hash:
        raise DeployError("bundle_checkpoint_mismatch")
    remaining = sum(value == "ABSENT" for value in targets.values())
    print(
        json.dumps(
            {
                "status": "READY_TO_RESUME",
                "phase": state["phase"] if state is not None else "NOT_STARTED",
                "files_to_install": remaining,
                "schema_count": len(SCHEMAS),
                "backend_restart_required": False,
                "writes": False,
            },
            sort_keys=True,
        )
    )
    return 0


def _ensure_directory(path: Path) -> None:
    if os.path.lexists(path):
        _require_owned(path, mode=0o755)
        return
    path.mkdir(mode=0o755)
    os.chown(path, 0, 0)
    os.chmod(path, 0o755)
    _require_owned(path, mode=0o755)


def _install_exact(target: Path, data: bytes, expected_hash: str) -> None:
    if os.path.lexists(target):
        _require_owned(target, mode=0o644, regular=True)
        if _sha256(target.read_bytes()) != expected_hash:
            raise DeployError("schema_file_fingerprint_mismatch")
        return
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        os.fchown(fd, 0, 0)
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, target)
        os.unlink(temporary)
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except FileExistsError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise DeployError("schema_target_appeared_during_install") from None
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise DeployError("schema_file_install_failed") from None
    _require_owned(target, mode=0o644, regular=True)
    if _sha256(target.read_bytes()) != expected_hash:
        raise DeployError("schema_file_postinstall_hash_mismatch")


def _resume(state: dict[str, Any] | None, bundle_hash: str, files: dict[str, bytes]) -> int:
    if state is not None and state["bundle_sha256"] != bundle_hash:
        raise DeployError("bundle_checkpoint_mismatch")
    if state is not None and state["phase"] == "VERIFIED":
        targets = _target_state(state)
        if all(value == "MATCH" for value in targets.values()):
            _probe_project_root()
            print(
                json.dumps(
                    {
                        "status": "PASS",
                        "phase": "VERIFIED",
                        "schema_count": len(SCHEMAS),
                        "source_commit": SOURCE_COMMIT,
                        "backend_restart_required": False,
                    },
                    sort_keys=True,
                )
            )
            return 0
    if state is None:
        _write_state("PREPARED", bundle_hash)
        state = _load_state()
    _ensure_directory(RELEASE_ROOT / "00_architecture")
    _ensure_directory(TARGET_ROOT)
    _write_state("DIRECTORIES_CREATED", bundle_hash)
    for relative, digest in _schema_paths().items():
        _install_exact(RELEASE_ROOT / relative, files[relative], digest)
    _write_state("FILES_INSTALLED", bundle_hash)
    targets = _target_state(_load_state())
    if not all(value == "MATCH" for value in targets.values()):
        raise DeployError("schema_file_set_incomplete")
    _probe_project_root()
    _write_state("VERIFIED", bundle_hash)
    print(
        json.dumps(
            {
                "status": "PASS",
                "phase": "VERIFIED",
                "schema_count": len(SCHEMAS),
                "source_commit": SOURCE_COMMIT,
                "backend_restart_required": False,
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
    parser = argparse.ArgumentParser()
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
        if not STATE_ROOT.is_dir():
            raise DeployError("state_root_unavailable")
        _require_owned(STATE_ROOT, mode=0o700)
        _, files, bundle_hash = _read_bundle()
        state = _load_state()
        targets = _target_state(state)
        if args.inspect:
            return _inspect(state, bundle_hash, targets)
        if args.dry_run:
            return _dry_run(state, bundle_hash, targets)
        with _exclusive_lock():
            return _resume(state, bundle_hash, files)
    except DeployError as exc:
        print(json.dumps({"status": "BLOCKED", "error_code": exc.code}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
