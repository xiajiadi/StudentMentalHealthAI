from __future__ import annotations

import importlib.util
import io
import json
import tarfile
from pathlib import Path

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
    assert manifest["source_commit"] == package.SOURCE_COMMIT
    assert manifest["synthetic_demo_only"] is True
    assert manifest["cloud_fallback"] is False
    assert "release/.env" not in names
    assert not any("api-key" in name.lower() or "credential" in name.lower() for name in names)
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


def test_payload_allowlist_rejects_unpinned_files() -> None:
    assert installer._allowed_payload("release/src/llm_runtime/providers/deepseek.py")
    assert installer._allowed_payload("release/config/models.deepseek.v1.json")
    assert not installer._allowed_payload("release/.env")
    assert not installer._allowed_payload("release/src/other.py")
    assert not installer._allowed_payload("systemd/other.service")


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
    unsafe = unit.replace(b"IPAddressAllow=3.173.21.63/32", b"IPAddressAllow=0.0.0.0/0")
    with pytest.raises(installer.GateError, match="llm_unit_scope_mismatch"):
        installer._check_unit(
            {
                "systemd/psynova-school-llm.service": unsafe,
                "systemd/psynova-school-demo-llm.conf": dropin,
            }
        )
