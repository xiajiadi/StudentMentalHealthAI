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


def test_package_cli_returns_success_for_packaged_output(tmp_path, capsys):
    output = tmp_path / "overlay.zip"

    exit_code = deploy.main(
        ["--package", "--repo-root", str(REPO_ROOT), "--output", str(output)]
    )
    result = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert result["status"] == "PACKAGED"
    assert output.is_file()


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


def test_resume_installs_restarts_checks_health_and_records_completion(
    tmp_path, monkeypatch
):
    previous = deploy._git_bytes(
        REPO_ROOT, deploy.PREVIOUS_FILE_REVISION, deploy.TARGET_PATH
    )
    target_bytes = deploy._git_bytes(
        REPO_ROOT, deploy.SOURCE_COMMIT, deploy.TARGET_PATH
    )
    target = tmp_path.joinpath(*Path(deploy.TARGET_PATH).parts)
    target.parent.mkdir(parents=True)
    target.write_bytes(previous)
    state = None
    service_commands: list[str] = []

    class Lock:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(deploy, "_require_root", lambda: None)
    monkeypatch.setattr(deploy, "_require_snapshot", lambda: None)
    monkeypatch.setattr(
        deploy, "_assert_no_conflicting_deployment_process", lambda: None
    )
    monkeypatch.setattr(deploy, "_service_active", lambda: True)
    monkeypatch.setattr(deploy, "_ExclusiveLock", Lock)
    monkeypatch.setattr(
        deploy,
        "_require_server_and_release",
        lambda: (target, deploy._sha256(target.read_bytes())),
    )
    monkeypatch.setattr(
        deploy,
        "_read_bundle",
        lambda: (
            {"source_commit": deploy.SOURCE_COMMIT},
            target_bytes,
            "b" * 64,
        ),
    )
    monkeypatch.setattr(
        deploy,
        "_ensure_backup",
        lambda content: assert_backup_hash(content, deploy.PREVIOUS_SHA256),
    )

    def write_state(bundle_hash: str, phase: str) -> None:
        nonlocal state
        state = {"bundle_sha256": bundle_hash, "phase": phase}

    monkeypatch.setattr(deploy, "_write_state", write_state)
    monkeypatch.setattr(deploy, "_load_state", lambda: state)
    monkeypatch.setattr(
        deploy, "_atomic_write", lambda path, content: path.write_bytes(content)
    )
    monkeypatch.setattr(
        deploy, "_run_systemctl", lambda action: service_commands.append(action)
    )
    monkeypatch.setattr(deploy, "_wait_for_health", lambda: True)

    result = deploy.resume()

    assert result["status"] == "PASS"
    assert result["phase"] == "HTTP_VERIFIED"
    assert deploy._sha256(target.read_bytes()) == deploy.TARGET_SHA256
    assert service_commands == ["restart"]
    assert state == {"bundle_sha256": "b" * 64, "phase": "HTTP_VERIFIED"}


def assert_backup_hash(content: bytes, expected: str) -> None:
    assert deploy._sha256(content) == expected
