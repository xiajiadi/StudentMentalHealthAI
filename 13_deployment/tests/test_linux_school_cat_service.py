from __future__ import annotations

import hashlib
import importlib.util
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
    "package_linux_school_cat_service",
    DEPLOYMENT_ROOT / "package_linux_school_cat_service.py",
)
installer = _load_module(
    "install_linux_school_cat_service",
    DEPLOYMENT_ROOT / "install_linux_school_cat_service.py",
)


def test_cat_bundle_is_deterministic_and_manifest_is_synthetic(tmp_path: Path) -> None:
    first = tmp_path / "cat-first.tar.gz"
    second = tmp_path / "cat-second.tar.gz"
    first_result = package.build_bundle(REPO_ROOT, first)
    second_result = package.build_bundle(REPO_ROOT, second)

    assert first_result["bundle_sha256"] == second_result["bundle_sha256"]
    assert first.read_bytes() == second.read_bytes()
    with tarfile.open(first, "r:gz") as archive:
        manifest_stream = archive.extractfile("PAYLOAD_MANIFEST.json")
        assert manifest_stream is not None
        manifest = json.load(manifest_stream)
        names = {member.name for member in archive.getmembers()}
    assert manifest["source_commit"] == package.SOURCE_COMMIT
    assert manifest["synthetic_fixture_only"] is True
    assert manifest["psychological_interpretation_allowed"] is False
    assert names - {"PAYLOAD_MANIFEST.json"} == {
        record["path"] for record in manifest["files"]
    }
    assert hashlib.sha256(first.read_bytes()).hexdigest() == first_result["bundle_sha256"]


def test_fixture_contract_rejects_non_synthetic_interpretation() -> None:
    config = (REPO_ROOT / "01_cat-engine/fixtures/demo_cat_config.v1.json").read_bytes()
    bank = json.loads(
        (REPO_ROOT / "01_cat-engine/fixtures/synthetic_item_bank.v1.json").read_text(
            encoding="utf-8"
        )
    )
    files = {
        "release/fixtures/demo_cat_config.v1.json": config,
        "release/fixtures/synthetic_item_bank.v1.json": json.dumps(bank).encode(),
    }
    installer._validate_fixture_contract(files)

    bank["metadata"]["psychological_interpretation_allowed"] = True
    files["release/fixtures/synthetic_item_bank.v1.json"] = json.dumps(bank).encode()
    with pytest.raises(installer.GateError, match="synthetic_fixture_contract_mismatch"):
        installer._validate_fixture_contract(files)


@pytest.mark.parametrize(
    "name",
    ["../outside", "/absolute", "release/../outside", "release\\outside"],
)
def test_tar_member_path_rejects_traversal(name: str) -> None:
    assert not installer._safe_member_name(name)


def test_payload_allowlist_rejects_unpinned_files() -> None:
    assert installer._allowed_payload_path("release/src/cat_engine/api/app.py")
    assert not installer._allowed_payload_path("release/src/other.py")
    assert not installer._allowed_payload_path("release/.env")
    assert not installer._allowed_payload_path("systemd/other.service")


def test_python_download_disabled_only_after_managed_python_install() -> None:
    assert "UV_PYTHON_DOWNLOADS" not in installer._python_install_environment()
    assert installer._uv_environment()["UV_PYTHON_DOWNLOADS"] == "never"


def test_cat_port_policy_tracks_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"phase": "PAYLOAD_READY"}
    monkeypatch.setattr(installer, "_listeners_for_port", lambda port: [])
    installer._verify_cat_port_for_checkpoint(state)

    monkeypatch.setattr(installer, "_listeners_for_port", lambda port: ["0.0.0.0:8180"])
    with pytest.raises(installer.GateError, match="cat_port_unexpectedly_in_use"):
        installer._verify_cat_port_for_checkpoint(state)

    state["phase"] = "SERVICE_STARTED"
    monkeypatch.setattr(installer, "_listeners_for_port", lambda port: ["127.0.0.1:8180"])
    installer._verify_cat_port_for_checkpoint(state)
    monkeypatch.setattr(installer, "_listeners_for_port", lambda port: ["0.0.0.0:8180"])
    with pytest.raises(installer.GateError, match="service_listener_not_loopback"):
        installer._verify_cat_port_for_checkpoint(state)


def test_systemd_contract_rejects_public_listener() -> None:
    unit = (REPO_ROOT / "13_deployment/systemd/psynova-school-cat.service").read_bytes()
    installer._check_unit_bytes({"systemd/psynova-school-cat.service": unit})
    unsafe = unit.replace(b"IPAddressAllow=127.0.0.1/32", b"IPAddressAllow=0.0.0.0/0")
    with pytest.raises(installer.GateError, match="systemd_unit_scope_mismatch"):
        installer._check_unit_bytes({"systemd/psynova-school-cat.service": unsafe})
