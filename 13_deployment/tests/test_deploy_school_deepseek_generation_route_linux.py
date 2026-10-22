from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import stat
import zipfile
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy_school_deepseek_generation_route_linux.py"
SPEC = importlib.util.spec_from_file_location("deploy_school_deepseek_generation_route_linux", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
deployer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deployer)


def _bundle(
    *,
    specs: dict[str, dict[str, Any]],
    files: dict[str, bytes],
    extra: dict[str, bytes] | None = None,
    symlinks: set[str] | None = None,
    source_commit: str = deployer.SOURCE_COMMIT,
    base_revision: str = deployer.BASE_RELEASE_REVISION,
) -> bytes:
    records = [
        {"path": name, "size_bytes": len(files[name]), "sha256": specs[name]["sha256"]}
        for name in sorted(files)
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
        for name, data in files.items():
            info = zipfile.ZipInfo(name)
            if name in (symlinks or set()):
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, data)
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return stream.getvalue()


def test_exact_generation_route_bundle_is_accepted() -> None:
    files = {"deployment/route.py": b"fixed source"}
    specs: dict[str, dict[str, Any]] = {
        name: {"sha256": hashlib.sha256(data).hexdigest()} for name, data in files.items()
    }
    raw = _bundle(specs=specs, files=files)

    manifest, parsed = deployer._validate_bundle(raw, file_specs=specs)

    assert manifest["source_commit"] == deployer.SOURCE_COMMIT
    assert parsed == files


def test_bundle_rejects_extra_and_traversal_members() -> None:
    files = {"deployment/route.py": b"fixed source"}
    specs: dict[str, dict[str, Any]] = {
        name: {"sha256": hashlib.sha256(data).hexdigest()} for name, data in files.items()
    }
    extra = _bundle(specs=specs, files=files, extra={"unexpected.txt": b"x"})
    with pytest.raises(deployer.DeployError, match="bundle_inventory_mismatch"):
        deployer._validate_bundle(extra, file_specs=specs)

    traversal = {"../route.py": b"fixed source"}
    traversal_specs: dict[str, dict[str, Any]] = {
        name: {"sha256": hashlib.sha256(data).hexdigest()}
        for name, data in traversal.items()
    }
    traversal_raw = _bundle(specs=traversal_specs, files=traversal)
    with pytest.raises(deployer.DeployError, match="bundle_member_rejected"):
        deployer._validate_bundle(traversal_raw, file_specs=traversal_specs)


def test_bundle_rejects_symlink_and_wrong_file_fingerprint() -> None:
    files = {"deployment/route.py": b"fixed source"}
    specs: dict[str, dict[str, Any]] = {
        name: {"sha256": hashlib.sha256(data).hexdigest()} for name, data in files.items()
    }
    symlink = _bundle(specs=specs, files=files, symlinks=set(files))
    with pytest.raises(deployer.DeployError, match="bundle_member_rejected"):
        deployer._validate_bundle(symlink, file_specs=specs)

    wrong_hash_specs: dict[str, dict[str, Any]] = {
        "deployment/route.py": {"sha256": hashlib.sha256(b"other").hexdigest()}
    }
    wrong_hash = _bundle(specs=wrong_hash_specs, files=files)
    with pytest.raises(deployer.DeployError, match="bundle_file_fingerprint_mismatch"):
        deployer._validate_bundle(wrong_hash, file_specs=wrong_hash_specs)


def test_bundle_rejects_wrong_commit_or_base_revision() -> None:
    files = {"deployment/route.py": b"fixed source"}
    specs: dict[str, dict[str, Any]] = {
        name: {"sha256": hashlib.sha256(data).hexdigest()} for name, data in files.items()
    }
    wrong_commit = _bundle(specs=specs, files=files, source_commit="other")
    with pytest.raises(deployer.DeployError, match="bundle_scope_mismatch"):
        deployer._validate_bundle(wrong_commit, file_specs=specs)

    wrong_base = _bundle(specs=specs, files=files, base_revision="other")
    with pytest.raises(deployer.DeployError, match="bundle_scope_mismatch"):
        deployer._validate_bundle(wrong_base, file_specs=specs)


def test_resume_after_llm_restart_checkpoint_does_not_restart_llm_twice(monkeypatch) -> None:
    bundle_sha = "a" * 64
    state = {"phase": "LLM_RESTARTED", "bundle_sha256": bundle_sha}
    phases: list[str] = []
    commands: list[list[str]] = []
    target_status = {name: "TARGET" for name in deployer.PACKAGE_FILES}
    monkeypatch.setattr(deployer, "_target_status", lambda _state: target_status)
    monkeypatch.setattr(deployer, "_backup_backend_file", lambda **_kwargs: None)
    monkeypatch.setattr(deployer, "_write_state", lambda phase, _sha: phases.append(phase))
    monkeypatch.setattr(deployer, "_run", lambda args, _code, **_kwargs: commands.append(args))
    monkeypatch.setattr(deployer, "_service_active", lambda _service: True)
    monkeypatch.setattr(deployer, "_health_ready", lambda _url, *, backend: True)
    monkeypatch.setattr(deployer, "_wait_ready", lambda: None)

    result = deployer._resume(state, bundle_sha, {})

    assert result == 0
    assert commands == [
        ["systemctl", "daemon-reload"],
        ["systemctl", "restart", deployer.BACKEND_SERVICE],
    ]
    assert phases == ["PAYLOAD_INSTALLED", "BACKEND_RESTARTED", "VERIFIED"]

