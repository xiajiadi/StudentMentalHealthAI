from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
import sys

import pytest

from harness.controlled_product_eval.process_lifecycle import ProcessSpec
from harness.controlled_product_eval import service_profiles
from harness.controlled_product_eval.windows_process_identity import (
    capture_process_identity,
    matches_exact_prior_runtime_identity,
    matches_exact_profile,
)


def _spec(tmp_path: Path) -> ProcessSpec:
    executable = Path("D:/fixed/runtime/python.exe")
    cwd = Path("D:/fixed/runtime/source")
    return ProcessSpec(
        name="d4-runtime-prior-r1",
        executable=executable,
        arguments=("-m", "llm_runtime.api.app"),
        cwd=cwd,
        environment={},
        readiness_url="http://127.0.0.1:8160/health/ready",
        readiness_kind="service",
        log_path=tmp_path / "unused.log",
        package_lock_identity={"python_executable_sha256": "a" * 64},
        environment_allowlist=frozenset(),
    )


def _listener(pid: int = 777) -> dict:
    return {"address": "127.0.0.1", "port": 8160, "pid": pid}


def test_formal_port_gate_cleans_only_exact_prior_runtime(tmp_path, monkeypatch):
    spec = _spec(tmp_path)
    identity = {
        "pid": 777,
        "parent_pid": 700,
        "executable": str(spec.executable),
        "executable_sha256": "a" * 64,
        "argv": [str(spec.executable), *spec.arguments],
        "argv_redacted": [str(spec.executable), *spec.arguments],
        "cwd": str(spec.cwd),
        "started_at": "2026-10-01T00:00:00Z",
        "capture_errors": {},
        "identity_complete": True,
    }
    snapshots = [
        {"status": "PASS", "observed_at": "2026-10-01T00:00:00Z", "listeners": [_listener()]},
        {"status": "PASS", "observed_at": "2026-10-01T00:00:01Z", "listeners": []},
    ]
    monkeypatch.setattr(service_profiles, "capture_data_plane_network", lambda **_kwargs: snapshots.pop(0))
    monkeypatch.setattr(
        "harness.controlled_product_eval.windows_process_identity.capture_process_identity",
        lambda _pid, **_kwargs: identity,
    )
    monkeypatch.setattr(
        "harness.controlled_product_eval.windows_process_identity.matches_exact_prior_runtime_identity",
        lambda _identity, _spec: True,
    )
    monkeypatch.setattr(
        "harness.controlled_product_eval.windows_process_identity.stop_exact_stale_process",
        lambda _identity, _spec, **_kwargs: {"pid": 777, "stopped": True, "shutdown_method": "TERMINATE_PROCESS_FALLBACK"},
    )

    evidence = service_profiles.preflight_formal_port_owners(
        profiles={},
        stale_profiles={"d4-runtime-prior-r1": spec},
        evidence_path=tmp_path / "port-preflight.json",
    )
    assert evidence["status"] == "PASS"
    assert evidence["owner_observations"][0]["classification"] == "EXACT_PRIOR_D4_RUNTIME_CLEANED"


def test_formal_port_gate_rejects_unknown_listener_without_cleanup(tmp_path, monkeypatch):
    spec = _spec(tmp_path)
    identity = {
        "pid": 777,
        "executable": "D:/unrelated/service.exe",
        "executable_sha256": "b" * 64,
        "argv_redacted": ["D:/unrelated/service.exe"],
        "cwd": "D:/unrelated",
        "started_at": "2026-10-01T00:00:00Z",
        "capture_errors": {},
        "identity_complete": True,
    }
    monkeypatch.setattr(
        service_profiles,
        "capture_data_plane_network",
        lambda **_kwargs: {"status": "PASS", "observed_at": "2026-10-01T00:00:00Z", "listeners": [_listener()]},
    )
    monkeypatch.setattr(
        "harness.controlled_product_eval.windows_process_identity.capture_process_identity",
        lambda _pid, **_kwargs: identity,
    )
    monkeypatch.setattr(
        "harness.controlled_product_eval.windows_process_identity.matches_exact_prior_runtime_identity",
        lambda _identity, _spec: False,
    )
    monkeypatch.setattr(
        "harness.controlled_product_eval.windows_process_identity.stop_exact_stale_process",
        lambda *_args: pytest.fail("unknown listener must never be stopped"),
    )

    with pytest.raises(service_profiles.ServiceProfileError, match="UNKNOWN_PROCESS_OCCUPIES_REQUIRED_FORMAL_PORT"):
        service_profiles.preflight_formal_port_owners(
            profiles={},
            stale_profiles={"d4-runtime-prior-r1": spec},
            evidence_path=tmp_path / "port-preflight.json",
        )
    evidence = service_profiles.json.loads((tmp_path / "port-preflight.json").read_text(encoding="utf-8"))
    assert evidence["unknown_process_count"] == 1
    assert evidence["owner_observations"][0]["process_identity"]["argv_redacted"] == identity["argv_redacted"]


@pytest.mark.skipif(os.name != "nt", reason="native Windows process identity contract")
def test_native_process_identity_supports_exact_profile_matching():
    identity = capture_process_identity(os.getpid())
    assert identity["identity_complete"] is True
    assert identity["parent_pid"] > 0
    assert identity["executable"]
    assert identity["argv_redacted"]
    assert identity["cwd"]
    launch_executable = Path(identity["argv"][0])
    spec = ProcessSpec(
        name="current-test-process",
        executable=launch_executable,
        arguments=tuple(identity["argv"][1:]),
        cwd=Path(identity["cwd"]),
        environment={},
        readiness_url="http://127.0.0.1:8160/health/ready",
        readiness_kind="service",
        log_path=Path.cwd() / "identity-test.log",
        package_lock_identity={
            "process_image_executable": identity["executable"],
            "process_image_sha256": identity["executable_sha256"],
        },
        environment_allowlist=frozenset(),
    )
    assert matches_exact_profile(identity, spec) is True
    changed = {**identity, "cwd": str(Path.cwd().parent)}
    assert matches_exact_profile(changed, spec) is False


def test_profile_matches_launcher_path_separately_from_process_image(tmp_path):
    launcher = tmp_path / "python-launcher.exe"
    image = tmp_path / "python-image.exe"
    launcher.write_bytes(b"fixed launcher bytes")
    image.write_bytes(b"fixed process image bytes")
    launcher_hash = hashlib.sha256(launcher.read_bytes()).hexdigest()
    image_hash = hashlib.sha256(image.read_bytes()).hexdigest()
    spec = ProcessSpec(
        name="python-launcher-image-pair",
        executable=launcher,
        arguments=("-m", "fixed.module"),
        cwd=tmp_path,
        environment={},
        readiness_url="http://127.0.0.1:8160/health/ready",
        readiness_kind="service",
        log_path=tmp_path / "unused.log",
        package_lock_identity={
            "python_executable_sha256": launcher_hash,
            "process_image_executable": str(image),
            "process_image_sha256": image_hash,
        },
        environment_allowlist=frozenset(),
    )
    identity = {
        "identity_complete": True,
        "executable": str(image),
        "executable_sha256": image_hash,
        "argv": [str(launcher), "-m", "fixed.module"],
        "cwd": str(tmp_path),
    }
    assert matches_exact_profile(identity, spec) is True
    assert matches_exact_profile({**identity, "argv": [str(image), "-m", "fixed.module"]}, spec) is False
    assert matches_exact_profile({**identity, "executable_sha256": "0" * 64}, spec) is False
    wrong_launcher_hash = replace(
        spec,
        package_lock_identity={
            **spec.package_lock_identity,
            "python_executable_sha256": "0" * 64,
        },
    )
    assert matches_exact_profile(identity, wrong_launcher_hash) is False


def test_prior_runtime_cleanup_requires_exact_venv_parent_and_listener_child(monkeypatch, tmp_path):
    from harness.controlled_product_eval.service_profiles import (
        RUNTIME_BASE_PYTHON,
        RUNTIME_BASE_PYTHON_ARGV0,
        RUNTIME_BASE_PYTHON_ARGV0_SHA256,
        RUNTIME_BASE_PYTHON_SHA256,
        RUNTIME_PYTHON,
        RUNTIME_SOURCE_ROOT,
        RUNTIME_VENV_PYTHON_SHA256,
    )

    arguments = ("-m", "llm_runtime.api.app")
    launcher = ProcessSpec(
        name="d4-runtime-prior-r1",
        executable=RUNTIME_PYTHON,
        arguments=arguments,
        cwd=RUNTIME_SOURCE_ROOT,
        environment={},
        readiness_url="http://127.0.0.1:8160/health/ready",
        readiness_kind="service",
        log_path=Path.cwd() / "unused.log",
        package_lock_identity={
            "python_executable_sha256": RUNTIME_VENV_PYTHON_SHA256,
            "process_image_executable": str(RUNTIME_BASE_PYTHON),
            "process_image_sha256": RUNTIME_BASE_PYTHON_SHA256,
        },
        environment_allowlist=frozenset(),
    )
    parent = {
        "pid": 100,
        "executable": str(RUNTIME_PYTHON),
        "executable_sha256": RUNTIME_VENV_PYTHON_SHA256,
        "argv": [str(RUNTIME_PYTHON), *arguments],
        "cwd": str(RUNTIME_SOURCE_ROOT),
        "started_at": "2026-10-01T00:00:00Z",
        "identity_complete": True,
    }
    child = {
        "pid": 101,
        "parent_pid": 100,
        "parent_identity": parent,
        "executable": str(RUNTIME_BASE_PYTHON),
        "executable_sha256": RUNTIME_BASE_PYTHON_SHA256,
        "argv": [str(RUNTIME_BASE_PYTHON_ARGV0), *arguments],
        "cwd": str(RUNTIME_SOURCE_ROOT),
        "started_at": "2026-10-01T00:00:01Z",
        "identity_complete": True,
    }
    assert matches_exact_prior_runtime_identity(child, launcher) is True
    changed_argv0 = {**child, "argv": [str(RUNTIME_BASE_PYTHON), *arguments]}
    assert matches_exact_prior_runtime_identity(changed_argv0, launcher) is False

    temp_cwd = tmp_path / "windows-temp"
    temp_cwd.mkdir()
    monkeypatch.setenv("TEMP", str(temp_cwd))
    monkeypatch.setenv("TMP", str(temp_cwd))
    temp_parent = {**parent, "cwd": str(temp_cwd)}
    assert matches_exact_prior_runtime_identity(
        {**child, "parent_identity": temp_parent}, launcher
    ) is True

    changed = {**child, "parent_identity": {**parent, "cwd": str(Path.cwd())}}
    assert matches_exact_prior_runtime_identity(changed, launcher) is False
    arbitrary_cwd = tmp_path / "unrelated-directory"
    arbitrary_cwd.mkdir()
    changed = {**child, "parent_identity": {**parent, "cwd": str(arbitrary_cwd)}}
    assert matches_exact_prior_runtime_identity(changed, launcher) is False


def test_ollama_profile_uses_attempt_local_userprofile(tmp_path):
    from harness.controlled_product_eval.service_profiles import (
        OLLAMA_MODELS,
        _ollama_profile_environment,
    )

    environment = _ollama_profile_environment(tmp_path)
    expected_home = (tmp_path / "ollama-user-profile").resolve()

    assert Path(environment["USERPROFILE"]) == expected_home
    assert expected_home.is_dir()
    assert environment["OLLAMA_HOST"] == "127.0.0.1:11437"
    assert environment["OLLAMA_MODELS"] == str(OLLAMA_MODELS.resolve())
    assert environment["OLLAMA_NO_CLOUD"] == "1"
    assert "11434" not in environment["OLLAMA_HOST"]


def test_runtime_listener_identity_must_be_the_owned_exact_python_child(tmp_path, monkeypatch):
    from harness.controlled_product_eval import windows_process_identity
    from harness.controlled_product_eval.service_profiles import (
        RUNTIME_BASE_PYTHON,
        RUNTIME_BASE_PYTHON_ARGV0,
        RUNTIME_BASE_PYTHON_SHA256,
    )

    profile = _spec(tmp_path)
    listener = {
        "pid": 101,
        "parent_pid": 100,
        "executable": str(RUNTIME_BASE_PYTHON),
        "executable_sha256": RUNTIME_BASE_PYTHON_SHA256,
        "argv_redacted": [str(RUNTIME_BASE_PYTHON_ARGV0), *profile.arguments],
        "cwd": str(profile.cwd),
        "started_at": "2026-10-01T00:00:01Z",
        "parent_identity": {
            "pid": 100,
            "executable": str(profile.executable),
            "executable_sha256": "a" * 64,
            "argv_redacted": [str(profile.executable), *profile.arguments],
            "cwd": str(profile.cwd),
            "started_at": "2026-10-01T00:00:00Z",
            "identity_complete": True,
        },
        "identity_complete": True,
    }
    monkeypatch.setattr(
        windows_process_identity,
        "capture_process_identity",
        lambda _pid, include_parent=False: listener,
    )
    monkeypatch.setattr(
        windows_process_identity,
        "matches_exact_prior_runtime_identity",
        lambda _identity, _profile: True,
    )

    evidence_path = tmp_path / "runtime-listener-identity.json"
    assert service_profiles._runtime_listener_process_identity(
        listener_pid=101,
        launcher_profile=profile,
        launcher_identity={"pid": 100},
        diagnostic_path=evidence_path,
    ) is listener
    diagnostic = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert diagnostic["status"] == "PASS"
    assert "argv" not in diagnostic["listener_identity"]
    assert diagnostic["listener_identity"]["argv_redacted"] == listener["argv_redacted"]

    mismatched_launcher = {**listener, "parent_pid": 99}
    monkeypatch.setattr(
        windows_process_identity,
        "capture_process_identity",
        lambda _pid, include_parent=False: mismatched_launcher,
    )
    with pytest.raises(service_profiles.ServiceProfileError, match="listener_parent_pid_matches_launcher"):
        service_profiles._runtime_listener_process_identity(
            listener_pid=101,
            launcher_profile=profile,
            launcher_identity={"pid": 100},
        )
