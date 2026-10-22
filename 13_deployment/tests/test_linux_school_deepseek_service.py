from __future__ import annotations

import importlib.util
import io
import json
import stat
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT_ROOT = REPO_ROOT / "13_deployment"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


package = _load_module(
    "package_linux_school_deepseek_service",
    DEPLOYMENT_ROOT / "package_linux_school_deepseek_service.py",
)
installer = _load_module(
    "install_linux_school_deepseek_service",
    DEPLOYMENT_ROOT / "install_linux_school_deepseek_service.py",
)


def test_deepseek_bundle_is_deterministic_and_has_no_secret_payload(tmp_path: Path) -> None:
    first = tmp_path / "deepseek-first.tar.gz"
    second = tmp_path / "deepseek-second.tar.gz"
    first_result = package.build_bundle(REPO_ROOT, first)
    second_result = package.build_bundle(REPO_ROOT, second)
    assert first_result["bundle_sha256"] == second_result["bundle_sha256"]
    assert first.read_bytes() == second.read_bytes()
    with tarfile.open(first, "r:gz") as archive:
        stream = archive.extractfile("PAYLOAD_MANIFEST.json")
        assert stream is not None
        manifest = json.load(stream)
        names = {member.name for member in archive.getmembers()}
        old_payload = {
            member.name: archive.extractfile(member).read()
            for member in archive.getmembers()
            if member.name not in {"PAYLOAD_MANIFEST.json", "release/config/runtime.v1.json"}
        }
        runtime_stream = archive.extractfile("release/config/runtime.v1.json")
        assert runtime_stream is not None
        runtime_config = json.load(runtime_stream)
    assert manifest["source_commit"] == package.SOURCE_COMMIT
    assert manifest["synthetic_demo_only"] is True
    assert manifest["cloud_fallback"] is False
    assert "release/.env" not in names
    assert not any("api-key" in name.lower() or "credential" in name.lower() for name in names)
    assert "release/config/runtime.v1.json" in names
    assert runtime_config["cloud_fallback"] is False
    assert package._fingerprint(old_payload) == installer.PREVIOUS_PAYLOAD_FINGERPRINT
    assert names - {"PAYLOAD_MANIFEST.json"} == {item["path"] for item in manifest["files"]}


def test_api_key_shape_is_checked_without_echo_or_persistence() -> None:
    assert installer._valid_api_key(b"sk-" + b"a" * 32)
    assert not installer._valid_api_key(b"not-a-key")
    assert not installer._valid_api_key(b"sk-short")
    assert not installer._valid_api_key(b"sk-" + b"a" * 300)


@pytest.mark.parametrize("separator", [b"\n", b"\r\n", b"\n\r"])
def test_api_key_input_discards_sudo_line_terminators(
    monkeypatch: pytest.MonkeyPatch, separator: bytes
) -> None:
    api_key = b"sk-" + b"a" * 32
    stdin = io.TextIOWrapper(io.BytesIO(separator + api_key + b"\r\n"), encoding="utf-8")
    monkeypatch.setattr(installer.sys, "stdin", stdin)

    received = installer._await_api_key()

    assert received == api_key


def test_runtime_bearer_token_requires_expected_alphabet_and_length() -> None:
    assert installer._valid_runtime_token(b"R" * 48)
    assert not installer._valid_runtime_token(b"short")
    assert not installer._valid_runtime_token(b"R" * 40 + b"/")


def test_deepseek_loopback_listener_policy_tracks_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"phase": "PAYLOAD_READY"}
    monkeypatch.setattr(installer, "_unit_active", lambda name: True)
    monkeypatch.setattr(installer, "_listeners_for_port", lambda port: [])
    installer._verify_llm_port_for_checkpoint(state)
    monkeypatch.setattr(installer, "_listeners_for_port", lambda port: ["0.0.0.0:8160"])
    with pytest.raises(installer.GateError, match="llm_port_unexpectedly_in_use"):
        installer._verify_llm_port_for_checkpoint(state)
    state["phase"] = "LLM_SERVICE_STARTED"
    monkeypatch.setattr(installer, "_listeners_for_port", lambda port: ["127.0.0.1:8160"])
    installer._verify_llm_port_for_checkpoint(state)
    monkeypatch.setattr(installer, "_listeners_for_port", lambda port: ["0.0.0.0:8160"])
    with pytest.raises(installer.GateError, match="service_listener_not_loopback"):
        installer._verify_llm_port_for_checkpoint(state)
    monkeypatch.setattr(installer, "_unit_active", lambda name: False)
    monkeypatch.setattr(installer, "_listeners_for_port", lambda port: [])
    installer._verify_llm_port_for_checkpoint(state)
    monkeypatch.setattr(installer, "_listeners_for_port", lambda port: ["127.0.0.1:8160"])
    with pytest.raises(installer.GateError, match="llm_port_occupied_after_service_failure"):
        installer._verify_llm_port_for_checkpoint(state)


def test_payload_allowlist_rejects_unpinned_files() -> None:
    assert installer._allowed_payload("release/src/llm_runtime/providers/deepseek.py")
    assert installer._allowed_payload("release/config/models.deepseek.v1.json")
    assert not installer._allowed_payload("release/.env")
    assert not installer._allowed_payload("release/src/other.py")
    assert not installer._allowed_payload("systemd/other.service")


def test_previous_bundle_upgrade_accepts_only_the_pinned_runtime_config_addition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path = tmp_path / "deepseek.tar.gz"
    package.build_bundle(REPO_ROOT, bundle_path)
    with tarfile.open(bundle_path, "r:gz") as archive:
        payload = {}
        for member in archive.getmembers():
            stream = archive.extractfile(member)
            assert stream is not None
            payload[member.name] = stream.read()
    next_manifest = json.loads(payload["PAYLOAD_MANIFEST.json"])
    old_records = [
        record
        for record in next_manifest["files"]
        if record["path"] != "release/config/runtime.v1.json"
    ]
    old_manifest = {
        **next_manifest,
        "files": old_records,
        "payload_fingerprint": installer.PREVIOUS_PAYLOAD_FINGERPRINT,
    }
    old_manifest_bytes = json.dumps(old_manifest, sort_keys=True, separators=(",", ":")).encode()

    release_root = tmp_path / "release"
    unit_path = tmp_path / "psynova-school-llm.service"
    dropin_path = tmp_path / "psynova-school-demo-llm.conf"
    release_root.mkdir()
    (release_root / "PAYLOAD_MANIFEST.json").write_bytes(old_manifest_bytes)
    for record in old_records:
        name = record["path"]
        if name.startswith("release/"):
            destination = release_root.joinpath(*Path(name).relative_to("release").parts)
        elif name == "systemd/psynova-school-llm.service":
            destination = unit_path
        else:
            destination = dropin_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload[name])

    monkeypatch.setattr(installer, "RELEASE_ROOT", release_root)
    monkeypatch.setattr(installer, "UNIT_PATH", unit_path)
    monkeypatch.setattr(installer, "BACKEND_DROPIN", dropin_path)
    real_stat = Path.stat

    def trusted_owner_stat(path: Path, *args: object, **kwargs: object) -> object:
        result = real_stat(path, *args, **kwargs)
        if path == unit_path or path == dropin_path or path.is_relative_to(release_root):
            return SimpleNamespace(
                st_mode=stat.S_IFREG | 0o644,
                st_uid=0,
                st_size=result.st_size,
            )
        return result

    monkeypatch.setattr(Path, "stat", trusted_owner_stat)
    state = {
        "phase": "LLM_SERVICE_STARTED",
        "bundle_sha256": installer.PREVIOUS_BUNDLE_SHA256,
    }
    installer._verify_previous_bundle_upgrade(state, payload)

    runtime_path = release_root / "config" / "runtime.v1.json"
    runtime_path.write_bytes(payload["release/config/runtime.v1.json"])
    (release_root / "PAYLOAD_MANIFEST.json").write_bytes(payload["PAYLOAD_MANIFEST.json"])
    installer._verify_previous_bundle_upgrade(state, payload)


def test_unit_and_backend_dropin_keep_secrets_external_and_listener_private() -> None:
    unit = (
        REPO_ROOT / "13_deployment/systemd/psynova-school-llm.service"
    ).read_bytes()
    dropin = (
        REPO_ROOT / "13_deployment/systemd/psynova-school-demo-llm.conf"
    ).read_bytes()
    installer._check_unit(
        {
            "systemd/psynova-school-llm.service": unit,
            "systemd/psynova-school-demo-llm.conf": dropin,
        }
    )
    assert installer.RESOLVER_DROPIN_DATA == b"[Service]\nIPAddressAllow=127.0.0.53/32\n"
    assert b"IPAddressAllow=0.0.0.0/0" not in installer.RESOLVER_DROPIN_DATA
    unsafe = unit.replace(b"IPAddressAllow=3.173.21.63/32", b"IPAddressAllow=0.0.0.0/0")
    with pytest.raises(installer.GateError, match="llm_unit_scope_mismatch"):
        installer._check_unit(
            {
                "systemd/psynova-school-llm.service": unsafe,
                "systemd/psynova-school-demo-llm.conf": dropin,
            }
        )
