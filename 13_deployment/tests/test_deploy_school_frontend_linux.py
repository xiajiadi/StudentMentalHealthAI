from __future__ import annotations

import importlib.util
import io
import json
import stat
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Self

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy_school_frontend_linux.py"
SPEC = importlib.util.spec_from_file_location("deploy_school_frontend_linux", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
site = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(site)


def _bundle(files: dict[str, bytes], *, mode: str = "real") -> bytes:
    manifest = site._make_manifest(files, "a" * 40)
    manifest["frontend_api_mode"] = mode
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest).encode())
        for name, content in files.items():
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, content)
    return stream.getvalue()


def _site_files() -> dict[str, bytes]:
    return {
        "web/index.html": b"<!doctype html><html></html>",
        "web/assets/app.js": b"console.log('real API');",
        "nginx/acme.conf": b"server { listen 80; server_name psynova.top www.psynova.top; }",
        "nginx/https.conf": b"server { listen 443 ssl; server_name psynova.top; }",
    }


def test_bundle_validator_accepts_pinned_real_api_site() -> None:
    manifest, files = site._validate_bundle_bytes(_bundle(_site_files()))

    assert manifest["frontend_api_mode"] == "real"
    assert manifest["api_base_url"] == "/"
    assert files["web/index.html"].startswith(b"<!doctype html>")


def test_frontend_build_command_handles_windows_command_wrapper() -> None:
    assert site._frontend_build_command("nt") == [
        "cmd.exe",
        "/d",
        "/c",
        "npm run build",
    ]
    assert site._frontend_build_command("posix") == ["npm", "run", "build"]


def test_deploy_lock_uses_private_runtime_directory() -> None:
    assert site.LOCK_PATH == Path("/run/psynova-school-public-deploy/public-site.lock")


def test_health_probe_waits_through_transient_startup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    class Response:
        status = 200

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    def fake_urlopen(_url: str, *, timeout: float) -> Response:
        nonlocal attempts
        assert timeout == 3
        attempts += 1
        if attempts == 1:
            raise site.urllib.error.URLError("not ready")
        return Response()

    monkeypatch.setattr(site.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(site.time, "sleep", lambda _seconds: None)

    assert site._health_ready(timeout_seconds=10, poll_interval=0.1)
    assert attempts == 2


def test_health_probe_stops_at_its_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    def fake_urlopen(_url: str, *, timeout: float) -> None:
        nonlocal attempts
        attempts += 1
        raise site.urllib.error.URLError("not ready")

    monkeypatch.setattr(site.urllib.request, "urlopen", fake_urlopen)

    assert not site._health_ready(timeout_seconds=0)
    assert attempts == 1


def test_running_backend_origin_check_reads_only_expected_environment_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        site.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="4242\n"),
    )
    monkeypatch.setattr(
        site.Path,
        "read_bytes",
        lambda _path: b"PATH=/usr/bin\0PSYNOVA_PUBLIC_ORIGIN=https://psynova.top\0",
    )

    assert site._backend_process_has_public_origin()
    assert site._process_has_public_origin(b"PSYNOVA_PUBLIC_ORIGIN=https://evil.test\0") is False


def test_bundle_validator_rejects_mock_api_manifest() -> None:
    with pytest.raises(site.DeployError, match="bundle_manifest_invalid"):
        site._validate_bundle_bytes(_bundle(_site_files(), mode="mock"))


def test_bundle_validator_rejects_unlisted_or_traversal_members() -> None:
    files = _site_files()
    files["web/../outside.txt"] = b"not allowed"

    with pytest.raises(site.DeployError, match="bundle_member_rejected"):
        site._make_manifest(files, "a" * 40)


def test_manifest_requires_index_and_both_nginx_stages() -> None:
    with pytest.raises(site.DeployError, match="bundle_required_files_missing"):
        site._make_manifest({"web/app.js": b"x"}, "a" * 40)


def test_static_release_verifier_rejects_unlisted_file(tmp_path: Path) -> None:
    files = _site_files()
    release = tmp_path / "release"
    (release / "assets").mkdir(parents=True)
    (release / "index.html").write_bytes(files["web/index.html"])
    (release / "assets" / "app.js").write_bytes(files["web/assets/app.js"])
    (release / "unexpected.txt").write_text("unexpected", encoding="utf-8")

    with pytest.raises(site.DeployError, match="web_release_inventory_mismatch"):
        site._verify_static_release(release, files)


def test_loopback_listener_check_rejects_wildcard_exposure(monkeypatch: pytest.MonkeyPatch) -> None:
    listeners = [
        "State Recv-Q Send-Q Local Address:Port Peer Address:Port",
        "LISTEN 0 128 127.0.0.1:3306 0.0.0.0:*",
        "LISTEN 0 128 127.0.0.1:8088 0.0.0.0:*",
        "LISTEN 0 128 127.0.0.1:8160 0.0.0.0:*",
        "LISTEN 0 128 127.0.0.1:8170 0.0.0.0:*",
        "LISTEN 0 128 127.0.0.1:8180 0.0.0.0:*",
        "LISTEN 0 128 127.0.0.1:8190 0.0.0.0:*",
        "LISTEN 0 128 [::]:8088 [::]:*",
    ]
    monkeypatch.setattr(site, "_run", lambda *_args, **_kwargs: "\n".join(listeners))

    with pytest.raises(site.DeployError, match="application_listener_not_loopback"):
        site._require_loopback_application_ports()
