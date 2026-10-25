from __future__ import annotations

import importlib.util
import io
import json
import zipfile
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1] / "deploy_school_account_credentials_linux.py"
)
REPO_ROOT = SCRIPT.parents[1]
SPEC = importlib.util.spec_from_file_location(
    "deploy_school_account_credentials_linux", SCRIPT
)
assert SPEC is not None and SPEC.loader is not None
deploy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy)


def _bundle(source: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json", json.dumps(deploy._manifest(source), sort_keys=True)
        )
        archive.writestr(deploy.TARGET_PATH, source)
    return buffer.getvalue()


def test_pinned_source_file_and_package_build_are_reproducible(tmp_path):
    source = deploy._git_bytes(REPO_ROOT, deploy.SOURCE_COMMIT, deploy.TARGET_PATH)
    assert deploy._sha256(source) == deploy.TARGET_SHA256
    output = tmp_path / "overlay.zip"

    result = deploy.build_package(REPO_ROOT, output)
    manifest, packaged_source = deploy._validate_bundle_bytes(output.read_bytes())

    assert result["status"] == "PACKAGED"
    assert manifest["source_commit"] == deploy.SOURCE_COMMIT
    assert packaged_source == source


def test_bundle_rejects_an_unapproved_file_path_or_changed_source():
    source = deploy._git_bytes(REPO_ROOT, deploy.SOURCE_COMMIT, deploy.TARGET_PATH)
    valid = _bundle(source)
    _manifest, extracted = deploy._validate_bundle_bytes(valid)
    assert extracted == source

    tampered_buffer = io.BytesIO()
    with zipfile.ZipFile(
        tampered_buffer, "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        archive.writestr(
            "manifest.json", json.dumps(deploy._manifest(source), sort_keys=True)
        )
        archive.writestr(deploy.TARGET_PATH, source + b"# changed")
    with pytest.raises(deploy.DeployError, match="source_file_fingerprint_mismatch"):
        deploy._validate_bundle_bytes(tampered_buffer.getvalue())

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json", json.dumps(deploy._manifest(source), sort_keys=True)
        )
        archive.writestr("../outside.py", source)
    with pytest.raises(deploy.DeployError, match="bundle_inventory_mismatch"):
        deploy._validate_bundle_bytes(buffer.getvalue())
