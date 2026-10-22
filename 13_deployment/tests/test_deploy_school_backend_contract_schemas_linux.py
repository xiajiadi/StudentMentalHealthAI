from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import stat
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy_school_backend_contract_schemas_linux.py"
SPEC = importlib.util.spec_from_file_location("deploy_school_backend_contract_schemas_linux", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
deployer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deployer)


def _bundle(
    *,
    expected_hashes: dict[str, str],
    files: dict[str, bytes],
    source_commit: str = deployer.SOURCE_COMMIT,
    base_revision: str = deployer.BASE_RELEASE_REVISION,
    extra: dict[str, bytes] | None = None,
    symlinks: set[str] | None = None,
) -> bytes:
    records = [
        {"path": path, "size_bytes": len(files[path]), "sha256": expected_hashes[path]}
        for path in sorted(files)
    ]
    manifest = {
        "schema": deployer.BUNDLE_SCHEMA,
        "base_release_revision": base_revision,
        "source_commit": source_commit,
        "files": records,
    }
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest).encode())
        for path, data in files.items():
            info = zipfile.ZipInfo(path)
            if path in (symlinks or set()):
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, data)
        for path, data in (extra or {}).items():
            archive.writestr(path, data)
    return stream.getvalue()


def test_schema_inventory_is_exact_and_matches_frozen_runtime_calls() -> None:
    assert set(deployer.SCHEMAS) == {
        "assessment.v1.schema.json",
        "generation.v1.schema.json",
        "knowledge.v1.schema.json",
    }
    assert set(deployer._schema_paths()) == {
        f"00_architecture/schemas/{name}" for name in deployer.SCHEMAS
    }


def test_bundle_accepts_exact_frozen_schema_package() -> None:
    files = {"00_architecture/schemas/schema.json": b"{}"}
    hashes = {path: hashlib.sha256(data).hexdigest() for path, data in files.items()}
    raw = _bundle(expected_hashes=hashes, files=files)

    manifest, parsed = deployer._validate_bundle(raw, expected_hashes=hashes)

    assert manifest["source_commit"] == deployer.SOURCE_COMMIT
    assert parsed == files


def test_bundle_rejects_unlisted_members() -> None:
    files = {"00_architecture/schemas/schema.json": b"{}"}
    hashes = {path: hashlib.sha256(data).hexdigest() for path, data in files.items()}
    raw = _bundle(expected_hashes=hashes, files=files, extra={"unexpected.txt": b"x"})

    with pytest.raises(deployer.DeployError, match="bundle_inventory_mismatch"):
        deployer._validate_bundle(raw, expected_hashes=hashes)


def test_bundle_rejects_content_not_matching_pinned_hash() -> None:
    files = {"00_architecture/schemas/schema.json": b"modified"}
    hashes = {path: hashlib.sha256(b"approved").hexdigest() for path in files}
    raw = _bundle(expected_hashes=hashes, files=files)

    with pytest.raises(deployer.DeployError, match="bundle_schema_fingerprint_mismatch"):
        deployer._validate_bundle(raw, expected_hashes=hashes)


def test_bundle_rejects_parent_traversal_and_symlink_members() -> None:
    traversal = {"../schema.json": b"{}"}
    traversal_hashes = {path: hashlib.sha256(data).hexdigest() for path, data in traversal.items()}
    traversal_raw = _bundle(expected_hashes=traversal_hashes, files=traversal)
    with pytest.raises(deployer.DeployError, match="bundle_member_rejected"):
        deployer._validate_bundle(traversal_raw, expected_hashes=traversal_hashes)

    files = {"00_architecture/schemas/schema.json": b"{}"}
    hashes = {path: hashlib.sha256(data).hexdigest() for path, data in files.items()}
    symlink_raw = _bundle(expected_hashes=hashes, files=files, symlinks=set(files))
    with pytest.raises(deployer.DeployError, match="bundle_member_rejected"):
        deployer._validate_bundle(symlink_raw, expected_hashes=hashes)


def test_bundle_rejects_wrong_source_or_release_revision() -> None:
    files = {"00_architecture/schemas/schema.json": b"{}"}
    hashes = {path: hashlib.sha256(data).hexdigest() for path, data in files.items()}
    wrong_source = _bundle(expected_hashes=hashes, files=files, source_commit="other")

    with pytest.raises(deployer.DeployError, match="bundle_scope_mismatch"):
        deployer._validate_bundle(wrong_source, expected_hashes=hashes)

