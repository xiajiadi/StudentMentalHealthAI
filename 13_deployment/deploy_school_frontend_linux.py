"""Build and safely deploy the synthetic school frontend and public Nginx site."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any

BASE_RELEASE_REVISION = "f3047642aa3466f9b4f210f4f704d57fd2cdf3cc"
SERVER_HOSTNAME = "iZ0xic24d9gxb9udjbfo0kZ"
APP_ROOT = Path("/opt/psynova-school-demo")
RELEASE_ROOT = APP_ROOT / "release"
WEB_ROOT = APP_ROOT / "web"
WEB_RELEASES_ROOT = APP_ROOT / "web-releases"
STATE_ROOT = Path("/var/lib/psynova-school-demo")
STAGING_ROOT = Path("/home/psynova/apps/psynova/staging/linux-school-demo")
STATE_SCHEMA = "psynova.school-public-site-state.v1"
BUNDLE_SCHEMA = "psynova.school-public-site.v1"
STATE_PREFIX = "public-site-"
NGINX_AVAILABLE = Path("/etc/nginx/sites-available/psynova-school-demo.conf")
NGINX_ENABLED = Path("/etc/nginx/sites-enabled/psynova-school-demo.conf")
NGINX_DEFAULT = Path("/etc/nginx/sites-enabled/default")
ORIGIN_DROPIN = Path(
    "/etc/systemd/system/psynova-school-demo.service.d/30-public-origin.conf"
)
BACKEND_SERVICE = "psynova-school-demo.service"
NGINX_SERVICE = "nginx.service"
BACKEND_HEALTH_URL = "http://127.0.0.1:8088/api/v1/health"
HTTP_PROBE_URL = "http://127.0.0.1/"
ACME_ROOT = Path("/var/www/letsencrypt")
LOCK_PATH = Path("/run/psynova-school-public-deploy/public-site.lock")
ACME_CONFIG_PATH = Path("13_deployment/nginx/psynova-school-demo-acme.conf")
HTTPS_CONFIG_PATH = Path("13_deployment/nginx/psynova-school-demo.conf")
MAX_BUNDLE_BYTES = 50_000_000
MAX_MEMBER_BYTES = 5_000_000
MAX_FILES = 2_000
ALLOWED_PACKAGE_PATHS = {"nginx/acme.conf", "nginx/https.conf"}
STATE_PHASES = {
    "PREPARED",
    "WEB_INSTALLED",
    "ORIGIN_INSTALLED",
    "HTTP_CONFIGURED",
    "BACKEND_RESTART_REQUESTED",
    "BACKEND_RESTARTED",
    "HTTP_READY",
    "HTTPS_CONFIGURED",
    "TLS_READY",
}


class DeployError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_text(repo_root: Path, *arguments: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo_root), *arguments],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        raise DeployError("git_source_unavailable") from None


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    return info


def _make_manifest(files: dict[str, bytes], source_commit: str) -> dict[str, Any]:
    if "web/index.html" not in files or not ALLOWED_PACKAGE_PATHS.issubset(files):
        raise DeployError("bundle_required_files_missing")
    if len(files) > MAX_FILES or set(files) - (ALLOWED_PACKAGE_PATHS | {
        name for name in files if name.startswith("web/")
    }):
        raise DeployError("bundle_member_inventory_invalid")
    records = []
    for name in sorted(files):
        path = PurePosixPath(name)
        data = files[name]
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in name
            or (not name.startswith("web/") and name not in ALLOWED_PACKAGE_PATHS)
            or len(data) > MAX_MEMBER_BYTES
        ):
            raise DeployError("bundle_member_rejected")
        records.append({"path": name, "size_bytes": len(data), "sha256": _sha256(data)})
    return {
        "schema": BUNDLE_SCHEMA,
        "source_commit": source_commit,
        "frontend_api_mode": "real",
        "api_base_url": "/",
        "files": records,
    }


def _package_files(repo_root: Path) -> tuple[dict[str, bytes], str]:
    root = repo_root.resolve(strict=True)
    tracked_paths = [
        "10_frontend/package.json",
        "10_frontend/package-lock.json",
        "10_frontend/src",
        ACME_CONFIG_PATH.as_posix(),
        HTTPS_CONFIG_PATH.as_posix(),
    ]
    if _git_text(root, "status", "--porcelain", "--", *tracked_paths):
        raise DeployError("source_worktree_dirty")
    source_commit = _git_text(root, "rev-parse", "HEAD")
    frontend_root = root / "10_frontend"
    environment = os.environ.copy()
    environment["VITE_API_MODE"] = "real"
    environment["VITE_API_BASE_URL"] = "/"
    build_command = _frontend_build_command()
    try:
        result = subprocess.run(
            build_command,
            cwd=frontend_root,
            env=environment,
            capture_output=True,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise DeployError("frontend_build_failed") from None
    if result.returncode != 0:
        raise DeployError("frontend_build_failed")
    dist_root = frontend_root / "dist"
    if not dist_root.is_dir() or not (dist_root / "index.html").is_file():
        raise DeployError("frontend_build_output_missing")
    files: dict[str, bytes] = {}
    for path in sorted(dist_root.rglob("*")):
        if path.is_symlink():
            raise DeployError("frontend_symlink_rejected")
        if path.is_dir():
            continue
        if not path.is_file():
            raise DeployError("frontend_output_entry_rejected")
        relative = path.relative_to(dist_root).as_posix()
        files[f"web/{relative}"] = path.read_bytes()
    files["nginx/acme.conf"] = (root / ACME_CONFIG_PATH).read_bytes()
    files["nginx/https.conf"] = (root / HTTPS_CONFIG_PATH).read_bytes()
    _make_manifest(files, source_commit)
    return files, source_commit


def _frontend_build_command(platform: str | None = None) -> list[str]:
    current_platform = os.name if platform is None else platform
    if current_platform == "nt":
        # npm is installed as npm.cmd on Windows; CreateProcess cannot launch it directly.
        return ["cmd.exe", "/d", "/c", "npm run build"]
    return ["npm", "run", "build"]


def build_package(repo_root: Path, output: Path) -> dict[str, object]:
    files, source_commit = _package_files(repo_root)
    manifest = _make_manifest(files, source_commit)
    output_path = output.resolve()
    if not output_path.parent.is_dir() or output_path.exists():
        raise DeployError("bundle_output_path_unavailable")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr(_zip_info("manifest.json"), json.dumps(manifest, sort_keys=True).encode())
        for name, content in sorted(files.items()):
            archive.writestr(_zip_info(name), content)
    data = buffer.getvalue()
    if len(data) > MAX_BUNDLE_BYTES:
        raise DeployError("bundle_size_invalid")
    output_path.write_bytes(data)
    return {
        "status": "PACKAGED",
        "source_commit": source_commit,
        "bundle_sha256": _sha256(data),
        "file_count": len(files),
        "size_bytes": len(data),
        "path": str(output_path),
    }


def _validate_bundle_bytes(raw: bytes) -> tuple[dict[str, Any], dict[str, bytes]]:
    if not raw or len(raw) > MAX_BUNDLE_BYTES:
        raise DeployError("bundle_size_invalid")
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except (OSError, zipfile.BadZipFile):
        raise DeployError("bundle_archive_invalid") from None
    with archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if len(names) != len(set(names)) or "manifest.json" not in names:
            raise DeployError("bundle_inventory_invalid")
        values: dict[str, bytes] = {}
        for item in infos:
            path = PurePosixPath(item.filename)
            mode = (item.external_attr >> 16) & 0xFFFF
            if (
                item.is_dir()
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in item.filename
                or stat.S_ISLNK(mode)
                or item.file_size > MAX_MEMBER_BYTES
            ):
                raise DeployError("bundle_member_rejected")
            try:
                content = archive.read(item)
            except (OSError, RuntimeError, zipfile.BadZipFile):
                raise DeployError("bundle_member_unreadable") from None
            if len(content) != item.file_size:
                raise DeployError("bundle_member_size_mismatch")
            values[item.filename] = content
    try:
        manifest = json.loads(values["manifest.json"])
    except (UnicodeError, json.JSONDecodeError):
        raise DeployError("bundle_manifest_invalid") from None
    if (
        type(manifest) is not dict
        or set(manifest) != {"schema", "source_commit", "frontend_api_mode", "api_base_url", "files"}
        or manifest.get("schema") != BUNDLE_SCHEMA
        or type(manifest.get("source_commit")) is not str
        or not manifest["source_commit"]
        or manifest.get("frontend_api_mode") != "real"
        or manifest.get("api_base_url") != "/"
        or type(manifest.get("files")) is not list
    ):
        raise DeployError("bundle_manifest_invalid")
    files = {name: content for name, content in values.items() if name != "manifest.json"}
    expected = _make_manifest(files, manifest["source_commit"])
    if manifest != expected:
        raise DeployError("bundle_manifest_mismatch")
    return manifest, files


def _require_root() -> None:
    if os.geteuid() != 0:
        raise DeployError("root_required")


def _require_root_snapshot() -> None:
    path = Path(__file__)
    _require_owned(path, mode=0o500, regular=True)
    prefix = "deploy_school_frontend_"
    suffix = ".py"
    if not path.name.startswith(prefix) or not path.name.endswith(suffix):
        raise DeployError("release_fingerprint_mismatch")
    expected = path.name[len(prefix) : -len(suffix)]
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise DeployError("release_fingerprint_mismatch")
    try:
        actual = _hash_file(path)
    except OSError:
        raise DeployError("release_fingerprint_unavailable") from None
    if actual != expected:
        raise DeployError("release_fingerprint_mismatch")


def _require_owned(path: Path, *, mode: int | None = None, regular: bool = False) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError:
        raise DeployError("required_path_missing") from None
    if info.st_uid != 0 or (regular and not stat.S_ISREG(info.st_mode)):
        raise DeployError("path_ownership_or_type_invalid")
    if mode is not None and stat.S_IMODE(info.st_mode) != mode:
        raise DeployError("path_mode_invalid")
    if stat.S_ISLNK(info.st_mode):
        raise DeployError("symlink_rejected")
    return info


def _ensure_directory(path: Path, mode: int) -> None:
    if os.path.lexists(path):
        _require_owned(path, mode=mode)
        if not stat.S_ISDIR(path.lstat().st_mode):
            raise DeployError("directory_type_invalid")
        return
    try:
        path.mkdir(mode=mode, parents=True)
        os.chown(path, 0, 0)
        os.chmod(path, mode)
    except OSError:
        raise DeployError("directory_create_failed") from None


def _atomic_write(path: Path, content: bytes, mode: int = 0o644) -> None:
    if os.path.lexists(path.parent):
        _require_owned(path.parent)
        if not stat.S_ISDIR(path.parent.lstat().st_mode):
            raise DeployError("parent_directory_type_invalid")
    else:
        _ensure_directory(path.parent, 0o755)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.deploy-", dir=path.parent)
    try:
        os.fchown(fd, 0, 0)
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise DeployError("atomic_write_failed") from None


def _state_path(bundle_sha: str) -> Path:
    return STATE_ROOT / f"{STATE_PREFIX}{bundle_sha}.json"


def _load_state(bundle_sha: str) -> dict[str, Any] | None:
    path = _state_path(bundle_sha)
    if not os.path.lexists(path):
        return None
    _require_owned(path, mode=0o600, regular=True)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise DeployError("state_file_invalid") from None
    expected_keys = {
        "schema",
        "base_release_revision",
        "source_commit",
        "bundle_sha256",
        "phase",
        "web_release",
        "default_site_link_saved",
        "updated_at_epoch",
    }
    if (
        type(value) is not dict
        or set(value) != expected_keys
        or value.get("schema") != STATE_SCHEMA
        or value.get("base_release_revision") != BASE_RELEASE_REVISION
        or value.get("bundle_sha256") != bundle_sha
        or value.get("phase") not in STATE_PHASES
        or type(value.get("source_commit")) is not str
        or type(value.get("web_release")) is not str
        or value.get("web_release") != str(WEB_RELEASES_ROOT / bundle_sha)
        or type(value.get("default_site_link_saved")) is not bool
        or type(value.get("updated_at_epoch")) is not int
    ):
        raise DeployError("state_checkpoint_mismatch")
    return value


def _write_state(bundle_sha: str, manifest: dict[str, Any], phase: str, *, default_saved: bool) -> None:
    _ensure_directory(STATE_ROOT, 0o700)
    state = {
        "schema": STATE_SCHEMA,
        "base_release_revision": BASE_RELEASE_REVISION,
        "source_commit": manifest["source_commit"],
        "bundle_sha256": bundle_sha,
        "phase": phase,
        "web_release": str(WEB_RELEASES_ROOT / bundle_sha),
        "default_site_link_saved": default_saved,
        "updated_at_epoch": int(time.time()),
    }
    content = json.dumps(state, sort_keys=True).encode("utf-8") + b"\n"
    path = _state_path(bundle_sha)
    fd, temporary = tempfile.mkstemp(prefix=".public-site-state-", dir=STATE_ROOT)
    try:
        os.fchown(fd, 0, 0)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
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


def _read_bundle(bundle_sha: str) -> tuple[dict[str, Any], dict[str, bytes]]:
    path = STAGING_ROOT / f"public-site-{bundle_sha}.zip"
    try:
        info = path.lstat()
    except OSError:
        raise DeployError("bundle_unavailable") from None
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or info.st_size > MAX_BUNDLE_BYTES:
        raise DeployError("bundle_permissions_invalid")
    try:
        raw = path.read_bytes()
    except OSError:
        raise DeployError("bundle_unreadable") from None
    if _sha256(raw) != bundle_sha:
        raise DeployError("bundle_fingerprint_mismatch")
    return _validate_bundle_bytes(raw)


def _preflight() -> None:
    _require_owned(APP_ROOT, mode=0o755)
    if not stat.S_ISDIR(APP_ROOT.lstat().st_mode):
        raise DeployError("application_root_type_invalid")
    _require_owned(RELEASE_ROOT)
    if not stat.S_ISDIR(RELEASE_ROOT.lstat().st_mode):
        raise DeployError("release_root_type_invalid")
    try:
        revision = (RELEASE_ROOT / "SOURCE_REVISION").read_text(encoding="utf-8").strip()
        hostname = Path("/etc/hostname").read_text(encoding="utf-8").strip()
    except OSError:
        raise DeployError("host_identity_unavailable") from None
    if revision != BASE_RELEASE_REVISION or hostname != SERVER_HOSTNAME:
        raise DeployError("host_identity_mismatch")
    _require_owned(STATE_ROOT, mode=0o700)
    if not shutil.which("nginx") or not shutil.which("systemctl"):
        raise DeployError("required_service_tool_missing")
    if not _service_active(BACKEND_SERVICE):
        raise DeployError("backend_not_active")


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


def _run(arguments: list[str], error_code: str, timeout: int = 120) -> str:
    try:
        result = subprocess.run(
            arguments,
            capture_output=True,
            timeout=timeout,
            check=False,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        raise DeployError(error_code) from None
    if result.returncode != 0:
        raise DeployError(error_code)
    return result.stdout.strip()


def _health_ready(*, timeout_seconds: float = 90.0, poll_interval: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            with urllib.request.urlopen(BACKEND_HEALTH_URL, timeout=3) as response:
                if response.status == 200:
                    return True
        except (OSError, urllib.error.URLError):
            pass
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(poll_interval, remaining))


_PUBLIC_ORIGIN_ENV = b"PSYNOVA_PUBLIC_ORIGIN=https://psynova.top"


def _process_has_public_origin(environment: bytes) -> bool:
    return _PUBLIC_ORIGIN_ENV in environment.split(b"\0")


def _backend_process_has_public_origin() -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "show", "--property=MainPID", "--value", BACKEND_SERVICE],
            capture_output=True,
            timeout=10,
            check=False,
            text=True,
        )
        if result.returncode != 0:
            return False
        main_pid = result.stdout.strip()
        if not main_pid.isdecimal() or main_pid == "0":
            return False
        environment = Path(f"/proc/{main_pid}/environ").read_bytes()
    except (OSError, subprocess.SubprocessError):
        return False
    return _process_has_public_origin(environment)


def _http_status(host: str, path: str = "/") -> int:
    request = urllib.request.Request(HTTP_PROBE_URL + path, headers={"Host": host})
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (OSError, urllib.error.URLError):
        return 0


def _verify_static_release(release_dir: Path, files: dict[str, bytes]) -> None:
    expected_paths = {
        PurePosixPath(name).relative_to("web").as_posix()
        for name in files
        if name.startswith("web/")
    }
    actual_paths: set[str] = set()
    for path in release_dir.rglob("*"):
        if path.is_symlink():
            raise DeployError("web_asset_symlink_rejected")
        if path.is_file():
            actual_paths.add(path.relative_to(release_dir).as_posix())
        elif not path.is_dir():
            raise DeployError("web_release_entry_rejected")
    if actual_paths != expected_paths:
        raise DeployError("web_release_inventory_mismatch")
    for name, content in files.items():
        if not name.startswith("web/"):
            continue
        target = release_dir / PurePosixPath(name).relative_to("web")
        try:
            info = target.lstat()
        except OSError:
            raise DeployError("web_asset_missing") from None
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o644:
            raise DeployError("web_asset_metadata_invalid")
        if _hash_file(target) != _sha256(content):
            raise DeployError("web_asset_fingerprint_mismatch")


def _web_release_hash(target: Path) -> str | None:
    resolved_target = target.resolve(strict=False)
    resolved_root = WEB_RELEASES_ROOT.resolve(strict=False)
    try:
        relative = resolved_target.relative_to(resolved_root)
    except ValueError:
        return None
    if (
        len(relative.parts) != 1
        or len(relative.name) != 64
        or any(char not in "0123456789abcdef" for char in relative.name)
    ):
        return None
    return relative.name


def _validate_existing_web_root() -> Path:
    if not WEB_ROOT.is_symlink():
        raise DeployError("web_root_unrecognized")
    target = WEB_ROOT.resolve(strict=False)
    previous_bundle_sha = _web_release_hash(target)
    if previous_bundle_sha is None:
        raise DeployError("web_root_unrecognized")
    state = _load_state(previous_bundle_sha)
    if state is None:
        raise DeployError("web_root_checkpoint_missing")
    manifest, previous_files = _read_bundle(previous_bundle_sha)
    if state["source_commit"] != manifest["source_commit"]:
        raise DeployError("web_root_checkpoint_mismatch")
    _require_owned(target, mode=0o755)
    if not stat.S_ISDIR(target.lstat().st_mode):
        raise DeployError("web_release_type_invalid")
    _verify_static_release(target, previous_files)
    return target


def _write_web_release(bundle_sha: str, files: dict[str, bytes]) -> Path:
    _ensure_directory(WEB_RELEASES_ROOT, 0o755)
    release_dir = WEB_RELEASES_ROOT / bundle_sha
    if os.path.lexists(release_dir):
        _require_owned(release_dir, mode=0o755)
        if not stat.S_ISDIR(release_dir.lstat().st_mode):
            raise DeployError("web_release_type_invalid")
        _verify_static_release(release_dir, files)
        return release_dir
    release_dir.mkdir(mode=0o755)
    os.chown(release_dir, 0, 0)
    os.chmod(release_dir, 0o755)
    for name, content in files.items():
        if name.startswith("web/"):
            relative = PurePosixPath(name).relative_to("web")
            _atomic_write(release_dir.joinpath(*relative.parts), content)
    _verify_static_release(release_dir, files)
    return release_dir


def _switch_web_root(release_dir: Path) -> None:
    if os.path.lexists(WEB_ROOT):
        current_release = _validate_existing_web_root()
        if current_release == release_dir:
            return
        if _web_release_hash(current_release) is None:
            raise DeployError("web_root_unrecognized")
    temporary = APP_ROOT / f".web-{release_dir.name}.tmp"
    if os.path.lexists(temporary):
        raise DeployError("web_root_temporary_path_exists")
    try:
        os.symlink(release_dir, temporary, target_is_directory=True)
        os.replace(temporary, WEB_ROOT)
    except OSError:
        if os.path.lexists(temporary):
            os.unlink(temporary)
        raise DeployError("web_root_switch_failed") from None


def _backup_root(bundle_sha: str) -> Path:
    return APP_ROOT / "backups" / f"public-site-{bundle_sha}"


def _disable_default_site(bundle_sha: str) -> bool:
    backup_dir = _backup_root(bundle_sha)
    _ensure_directory(backup_dir.parent, 0o755)
    _ensure_directory(backup_dir, 0o700)
    saved_link = backup_dir / "default-site.enabled"
    if os.path.lexists(NGINX_DEFAULT):
        if not NGINX_DEFAULT.is_symlink():
            raise DeployError("default_site_type_unrecognized")
        target = (NGINX_DEFAULT.parent / os.readlink(NGINX_DEFAULT)).resolve()
        if target != Path("/etc/nginx/sites-available/default"):
            raise DeployError("default_site_target_unrecognized")
        if not os.path.lexists(saved_link):
            os.symlink(target, saved_link)
        NGINX_DEFAULT.unlink()
        return True
    return os.path.lexists(saved_link)


def _install_site_config(content: bytes) -> None:
    if os.path.lexists(NGINX_AVAILABLE):
        _require_owned(NGINX_AVAILABLE, mode=0o644, regular=True)
        if NGINX_AVAILABLE.read_bytes() != content:
            raise DeployError("nginx_site_unrecognized")
    else:
        _atomic_write(NGINX_AVAILABLE, content)
    _ensure_directory(NGINX_ENABLED.parent, 0o755)
    if os.path.lexists(NGINX_ENABLED):
        if not NGINX_ENABLED.is_symlink() or NGINX_ENABLED.resolve(strict=True) != NGINX_AVAILABLE:
            raise DeployError("nginx_enabled_link_unrecognized")
    else:
        os.symlink(NGINX_AVAILABLE, NGINX_ENABLED)


def _check_known_targets(bundle_sha: str, files: dict[str, bytes]) -> None:
    expected_web_link = WEB_RELEASES_ROOT / bundle_sha
    if os.path.lexists(WEB_ROOT):
        current_release = _validate_existing_web_root()
        if current_release != expected_web_link and _web_release_hash(current_release) is None:
            raise DeployError("web_root_unrecognized")
    if os.path.lexists(NGINX_AVAILABLE):
        _require_owned(NGINX_AVAILABLE, mode=0o644, regular=True)
        if NGINX_AVAILABLE.read_bytes() not in {files["nginx/acme.conf"], files["nginx/https.conf"]}:
            raise DeployError("nginx_site_unrecognized")
    if os.path.lexists(NGINX_ENABLED) and (
        not NGINX_ENABLED.is_symlink()
        or NGINX_ENABLED.resolve(strict=False) != NGINX_AVAILABLE
    ):
        raise DeployError("nginx_enabled_link_unrecognized")
    if os.path.lexists(ORIGIN_DROPIN):
        _require_owned(ORIGIN_DROPIN, mode=0o644, regular=True)
        if ORIGIN_DROPIN.read_bytes() != _ORIGIN_CONFIG:
            raise DeployError("public_origin_dropin_unrecognized")
    if os.path.lexists(NGINX_DEFAULT):
        if not NGINX_DEFAULT.is_symlink():
            raise DeployError("default_site_type_unrecognized")
        target = (NGINX_DEFAULT.parent / os.readlink(NGINX_DEFAULT)).resolve()
        if target != Path("/etc/nginx/sites-available/default"):
            raise DeployError("default_site_target_unrecognized")


_ORIGIN_CONFIG = (
    b"[Service]\n"
    b"Environment=PSYNOVA_PUBLIC_ORIGIN=https://psynova.top\n"
)
def _install_origin_config() -> None:
    _ensure_directory(ORIGIN_DROPIN.parent, 0o755)
    if os.path.lexists(ORIGIN_DROPIN):
        _require_owned(ORIGIN_DROPIN, mode=0o644, regular=True)
        if ORIGIN_DROPIN.read_bytes() != _ORIGIN_CONFIG:
            raise DeployError("public_origin_dropin_unrecognized")
        return
    _atomic_write(ORIGIN_DROPIN, _ORIGIN_CONFIG)


def _install_frontend(bundle_sha: str, manifest: dict[str, Any], files: dict[str, bytes]) -> int:
    _require_root()
    _preflight()
    _check_known_targets(bundle_sha, files)
    state = _load_state(bundle_sha)
    if state is not None and state["source_commit"] != manifest["source_commit"]:
        raise DeployError("state_source_commit_mismatch")
    if state is not None and state["phase"] == "TLS_READY":
        return 0
    if state is not None and state["phase"] == "HTTP_READY":
        if not _service_active(NGINX_SERVICE) or _http_status("psynova.top") != 503:
            raise DeployError("http_site_checkpoint_health_mismatch")
        return 0
    state_default_saved = bool(state and state["default_site_link_saved"])
    if state is None:
        _write_state(bundle_sha, manifest, "PREPARED", default_saved=False)
        state = _load_state(bundle_sha)
    if state is None:
        raise DeployError("state_checkpoint_missing")
    release_dir = _write_web_release(bundle_sha, files)
    _switch_web_root(release_dir)
    if state["phase"] == "PREPARED":
        _write_state(bundle_sha, manifest, "WEB_INSTALLED", default_saved=state_default_saved)
        state = _load_state(bundle_sha)
    _install_origin_config()
    if state is not None and state["phase"] == "WEB_INSTALLED":
        _write_state(bundle_sha, manifest, "ORIGIN_INSTALLED", default_saved=state_default_saved)
        state = _load_state(bundle_sha)
    _ensure_directory(ACME_ROOT, 0o755)
    acme_config = files["nginx/acme.conf"]
    _install_site_config(acme_config)
    state_default_saved = _disable_default_site(bundle_sha) or state_default_saved
    if state is not None and state["phase"] in {"ORIGIN_INSTALLED", "HTTP_CONFIGURED"}:
        _write_state(bundle_sha, manifest, "HTTP_CONFIGURED", default_saved=state_default_saved)
        state = _load_state(bundle_sha)
    _run(["systemctl", "daemon-reload"], "systemd_reload_failed")
    if state is None or state["phase"] != "BACKEND_RESTARTED":
        if not _backend_process_has_public_origin():
            _write_state(
                bundle_sha,
                manifest,
                "BACKEND_RESTART_REQUESTED",
                default_saved=state_default_saved,
            )
            _run(["systemctl", "restart", BACKEND_SERVICE], "backend_restart_failed", timeout=180)
        _write_state(bundle_sha, manifest, "BACKEND_RESTARTED", default_saved=state_default_saved)
        state = _load_state(bundle_sha)
    if not _health_ready():
        raise DeployError("backend_health_failed_after_public_origin")
    _run(["nginx", "-t"], "nginx_configuration_invalid")
    if _service_active(NGINX_SERVICE):
        _run(["systemctl", "reload", NGINX_SERVICE], "nginx_reload_failed")
    else:
        _run(["systemctl", "start", NGINX_SERVICE], "nginx_start_failed", timeout=120)
    if _http_status("psynova.top") != 503:
        raise DeployError("precertificate_http_state_unexpected")
    _require_loopback_application_ports()
    _write_state(bundle_sha, manifest, "HTTP_READY", default_saved=state_default_saved)
    return 0


def _require_loopback_application_ports() -> None:
    result = _run(["ss", "-ltn"], "listener_probe_failed")
    local_addresses: list[str] = []
    for line in result.splitlines()[1:]:
        columns = line.split()
        if len(columns) >= 5:
            local_addresses.append(columns[3])
    for port in (3306, 8088, 8160, 8170, 8180, 8190):
        expected = f"127.0.0.1:{port}"
        if expected not in local_addresses:
            raise DeployError("application_listener_missing")
        for local_address in local_addresses:
            if local_address.endswith(f":{port}") and local_address != expected:
                raise DeployError("application_listener_not_loopback")


def _certificate_ready() -> bool:
    fullchain = Path("/etc/letsencrypt/live/psynova.top/fullchain.pem")
    key = Path("/etc/letsencrypt/live/psynova.top/privkey.pem")
    for path in (fullchain, key):
        if not path.is_symlink():
            return False
        target = path.resolve(strict=False)
        if not target.is_file() or not str(target).startswith("/etc/letsencrypt/archive/psynova.top/"):
            return False
        info = target.stat()
        if info.st_uid != 0:
            return False
    return stat.S_IMODE(key.resolve().stat().st_mode) <= 0o600


def _curl(url: str, host: str, *, resolve: str | None = None) -> tuple[int, str]:
    command = ["curl", "--silent", "--show-error", "--output", "/dev/null", "--write-out", "%{http_code} %{redirect_url}"]
    if resolve is not None:
        command.extend(["--resolve", f"{host}:443:127.0.0.1"])
    command.append(url)
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        raise DeployError("local_https_probe_failed") from None
    if result.returncode != 0:
        raise DeployError("local_https_probe_failed")
    parts = result.stdout.strip().split(" ", 1)
    try:
        status = int(parts[0])
    except (IndexError, ValueError):
        raise DeployError("local_https_probe_invalid") from None
    return status, parts[1] if len(parts) == 2 else ""


def _activate_https(bundle_sha: str, manifest: dict[str, Any], files: dict[str, bytes]) -> int:
    _require_root()
    _preflight()
    _check_known_targets(bundle_sha, files)
    state = _load_state(bundle_sha)
    if state is None or state["phase"] not in {"HTTP_READY", "HTTPS_CONFIGURED", "TLS_READY"}:
        raise DeployError("http_site_checkpoint_required")
    if not _certificate_ready():
        raise DeployError("public_certificate_unavailable")
    https_config = files["nginx/https.conf"]
    backup_dir = _backup_root(bundle_sha)
    _ensure_directory(backup_dir, 0o700)
    acme_backup = backup_dir / "nginx-acme.conf.before-https"
    if not acme_backup.exists():
        current = NGINX_AVAILABLE.read_bytes()
        if current != files["nginx/acme.conf"]:
            raise DeployError("nginx_acme_config_fingerprint_mismatch")
        _atomic_write(acme_backup, current, mode=0o644)
    else:
        _require_owned(acme_backup, mode=0o644, regular=True)
    _write_state(bundle_sha, manifest, "HTTPS_CONFIGURED", default_saved=state["default_site_link_saved"])
    _atomic_write(NGINX_AVAILABLE, https_config)
    try:
        _run(["nginx", "-t"], "nginx_https_configuration_invalid")
        _run(["systemctl", "reload", NGINX_SERVICE], "nginx_https_reload_failed")
        apex_status, _ = _curl("https://psynova.top/", "psynova.top", resolve="127.0.0.1")
        www_status, redirect = _curl("https://www.psynova.top/", "www.psynova.top", resolve="127.0.0.1")
        if apex_status != 200 or www_status != 301 or not redirect.startswith("https://psynova.top/"):
            raise DeployError("local_https_route_verification_failed")
    except DeployError:
        _atomic_write(NGINX_AVAILABLE, acme_backup.read_bytes())
        _run(["nginx", "-t"], "nginx_http_rollback_invalid")
        _run(["systemctl", "reload", NGINX_SERVICE], "nginx_http_rollback_reload_failed")
        _write_state(bundle_sha, manifest, "HTTP_READY", default_saved=state["default_site_link_saved"])
        raise
    _write_state(bundle_sha, manifest, "TLS_READY", default_saved=state["default_site_link_saved"])
    return 0


def _inspect(bundle_sha: str, manifest: dict[str, Any], files: dict[str, bytes]) -> dict[str, Any]:
    state = _load_state(bundle_sha)
    web_release = WEB_RELEASES_ROOT / bundle_sha
    state_phase = state["phase"] if state is not None else "NOT_STARTED"
    target_present = os.path.lexists(web_release)
    if target_present:
        _verify_static_release(web_release, files)
    web_link_ok = (
        WEB_ROOT.is_symlink()
        and WEB_ROOT.resolve(strict=False) == web_release
        if os.path.lexists(WEB_ROOT)
        else False
    )
    return {
        "status": "PASS" if state_phase == "TLS_READY" else "HTTP_READY" if state_phase == "HTTP_READY" else "RESUMABLE" if state is not None else "READY",
        "phase": state_phase,
        "source_commit": manifest["source_commit"],
        "bundle_sha256": bundle_sha,
        "web_release_present": target_present,
        "web_root_link_verified": web_link_ok,
        "backend_active": _service_active(BACKEND_SERVICE),
        "nginx_active": _service_active(NGINX_SERVICE),
        "certificate_present": _certificate_ready(),
        "acme_http_probe": _http_status("psynova.top") if _service_active(NGINX_SERVICE) else None,
        "writes": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--package", action="store_true")
    actions.add_argument("--inspect", action="store_true")
    actions.add_argument("--dry-run", action="store_true")
    actions.add_argument("--resume", action="store_true")
    actions.add_argument("--enable-https", action="store_true")
    parser.add_argument("--bundle-sha256")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    return parser


@contextmanager
def _exclusive_lock() -> Iterator[None]:
    import fcntl

    _ensure_directory(LOCK_PATH.parent, 0o700)
    try:
        descriptor = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
        os.fchown(descriptor, 0, 0)
        os.fchmod(descriptor, 0o600)
    except OSError:
        raise DeployError("deployment_lock_unavailable") from None
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise DeployError("deployment_lock_busy") from None
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(descriptor)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.package:
            if args.output is None:
                raise DeployError("bundle_output_required")
            result = build_package(args.repo_root, args.output)
            print(json.dumps(result, sort_keys=True))
            return 0
        if not isinstance(args.bundle_sha256, str) or len(args.bundle_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in args.bundle_sha256
        ):
            raise DeployError("bundle_sha256_invalid")
        _require_root_snapshot()
        _require_root()
        _ensure_directory(STATE_ROOT, 0o700)
        with _exclusive_lock():
            manifest, files = _read_bundle(args.bundle_sha256)
            _preflight()
            _check_known_targets(args.bundle_sha256, files)
            if args.inspect:
                result = _inspect(args.bundle_sha256, manifest, files)
            elif args.dry_run:
                state = _load_state(args.bundle_sha256)
                if state is not None and state["source_commit"] != manifest["source_commit"]:
                    raise DeployError("state_source_commit_mismatch")
                result = {
                    "status": "READY",
                    "source_commit": manifest["source_commit"],
                    "bundle_sha256": args.bundle_sha256,
                    "file_count": len(files),
                    "actions": [
                        "install_versioned_static_release",
                        "set_secure_backend_public_origin",
                        "enable_acme_only_http_listener",
                        "restart_backend",
                        "start_nginx_http",
                    ],
                    "database_ddl": False,
                }
            elif args.resume:
                _install_frontend(args.bundle_sha256, manifest, files)
                result = _inspect(args.bundle_sha256, manifest, files)
            else:
                _activate_https(args.bundle_sha256, manifest, files)
                result = _inspect(args.bundle_sha256, manifest, files)
            print(json.dumps(result, sort_keys=True))
            return 0
    except DeployError as exc:
        print(json.dumps({"status": "BLOCKED", "error_code": exc.code}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
