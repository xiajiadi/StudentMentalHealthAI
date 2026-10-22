from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy_school_backend_overlay_linux.py"
SPEC = importlib.util.spec_from_file_location("deploy_school_backend_overlay_linux", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
overlay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(overlay)


def _bundle(
    *,
    specs: dict[str, dict[str, str]],
    files: dict[str, bytes],
    source_commit: str = overlay.SOURCE_COMMIT,
    base_revision: str = overlay.BASE_RELEASE_REVISION,
    extra: dict[str, bytes] | None = None,
) -> bytes:
    records = [
        {
            "path": path,
            "size_bytes": len(files[path]),
            "sha256": specs[path]["target"],
            "expected_previous_sha256": specs[path]["previous"],
        }
        for path in sorted(files)
    ]
    manifest = {
        "schema": overlay.BUNDLE_SCHEMA,
        "base_release_revision": base_revision,
        "source_commit": source_commit,
        "files": records,
    }
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest).encode())
        for path, data in files.items():
            archive.writestr(path, data)
        for path, data in (extra or {}).items():
            archive.writestr(path, data)
    return stream.getvalue()


def test_bundle_validator_accepts_exact_allowlisted_source_package() -> None:
    specs = {"module.py": {"previous": "a" * 64, "target": hashlib.sha256(b"new").hexdigest()}}
    archive = _bundle(
        specs=specs,
        files={"module.py": b"new"},
        source_commit="commit-1",
        base_revision="base-1",
    )

    manifest, files = overlay._validate_bundle_bytes(
        archive,
        file_specs=specs,
        source_commit="commit-1",
        base_revision="base-1",
    )

    assert manifest["source_commit"] == "commit-1"
    assert files == {"module.py": b"new"}


def test_bundle_validator_rejects_unlisted_members() -> None:
    specs = {"module.py": {"previous": "a" * 64, "target": hashlib.sha256(b"new").hexdigest()}}
    archive = _bundle(specs=specs, files={"module.py": b"new"}, extra={"extra.py": b"x"})

    with pytest.raises(overlay.OverlayError, match="bundle_file_inventory_mismatch"):
        overlay._validate_bundle_bytes(archive, file_specs=specs)


def test_bundle_validator_rejects_content_that_does_not_match_pinned_hash() -> None:
    specs = {"module.py": {"previous": "a" * 64, "target": hashlib.sha256(b"approved").hexdigest()}}
    archive = _bundle(specs=specs, files={"module.py": b"modified"})

    with pytest.raises(overlay.OverlayError, match="bundle_file_fingerprint_mismatch"):
        overlay._validate_bundle_bytes(archive, file_specs=specs)


def test_bundle_validator_rejects_wrong_source_revision() -> None:
    specs = {"module.py": {"previous": "a" * 64, "target": hashlib.sha256(b"new").hexdigest()}}
    archive = _bundle(specs=specs, files={"module.py": b"new",}, source_commit="other")

    with pytest.raises(overlay.OverlayError, match="bundle_manifest_scope_mismatch"):
        overlay._validate_bundle_bytes(archive, file_specs=specs)


def test_checkpoint_planner_only_accepts_known_pre_and_post_hashes(monkeypatch) -> None:
    specs = {
        "a.py": {"previous": "a" * 64, "target": "b" * 64},
        "b.py": {"previous": "c" * 64, "target": "d" * 64},
    }
    previous = {path: item["previous"] for path, item in specs.items()}
    target = {path: item["target"] for path, item in specs.items()}
    monkeypatch.setattr(overlay, "FILES", specs)

    assert overlay._checkpoint_status(target, {"phase": "HTTP_VERIFIED"}) == ("PASS", None)
    assert overlay._checkpoint_status(
        {"a.py": target["a.py"], "b.py": previous["b.py"]},
        {"phase": "BACKUP_VERIFIED"},
    ) == ("RESUMABLE", None)
    assert overlay._checkpoint_status(
        {"a.py": target["a.py"], "b.py": "e" * 64},
        {"phase": "BACKUP_VERIFIED"},
    ) == ("BLOCKED", "release_file_fingerprint_mismatch")
