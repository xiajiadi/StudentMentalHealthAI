from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "13_deployment"))

import install_linux_school_safety_service as installer
import package_linux_school_safety_service as packager


def test_bundle_builder_is_deterministic_and_verifies_every_payload_member(tmp_path, monkeypatch):
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"
    first_result = packager.build_bundle(ROOT, first)
    second_result = packager.build_bundle(ROOT, second)

    assert first_result["source_commit"] == packager.SOURCE_COMMIT
    assert first_result["bundle_sha256"] == second_result["bundle_sha256"]
    assert first.read_bytes() == second.read_bytes()

    monkeypatch.setattr(installer, "BUNDLE_PATH", first)
    monkeypatch.setattr(installer, "BUNDLE_SHA256", first_result["bundle_sha256"])
    manifest, files = installer._load_bundle()
    assert manifest["source_commit"] == installer.SOURCE_COMMIT
    assert manifest["model"]["revision"] == installer.MODEL_REVISION
    assert "release/uv.lock" in files
    assert "systemd/psynova-school-safety.service" in files


@pytest.mark.parametrize(
    "name",
    ["../escape", "/etc/passwd", "release\\secret", "release/../../escape", ""],
)
def test_bundle_path_validation_rejects_escape_paths(name):
    assert installer._safe_member_name(name) is False


def test_bundle_path_validation_accepts_nested_relative_files():
    assert installer._safe_member_name("release/src/safety_engine/api/app.py") is True


def test_model_cache_inventory_accepts_only_pinned_repo_and_hub_metadata(tmp_path, monkeypatch):
    hub_cache = tmp_path / "hub"
    lock_directory = hub_cache / ".locks" / "models--Qwen--Qwen3Guard-Gen-0.6B"
    lock_directory.mkdir(parents=True)
    monkeypatch.setattr(installer, "MODEL_HUB_CACHE", hub_cache)

    installer._validate_hub_cache_inventory(
        {".locks", "CACHEDIR.TAG", "models--Qwen--Qwen3Guard-Gen-0.6B"}
    )

    with pytest.raises(installer.GateError) as error:
        installer._validate_hub_cache_inventory(
            {".locks", "models--Qwen--Qwen3Guard-Gen-0.6B", "models--unrelated"}
        )
    assert error.value.code == "model_cache_inventory_mismatch"


def test_live_safety_acceptance_requires_all_components_and_rejects_injection(monkeypatch):
    health = {
        "status": "READY",
        "components": {
            name: {"ready": True} for name in installer.REQUIRED_HEALTH_COMPONENTS
        },
    }
    normal = {"decision": {"action": "PROCEED"}}
    rejected = {"decision": {"action": "BLOCK"}}
    crisis_case_id = "review-synthetic-001"
    crisis = {
        "decision": {"action": "CRISIS_ROUTE"},
        "normal_llm_invoked": False,
        "review_case": {"status": "PENDING", "review_case_id": crisis_case_id},
    }
    persisted = {"review_case_id": crisis_case_id, "status": "PENDING"}
    responses = iter([health, normal, rejected, crisis, persisted])
    calls = []

    def fake_request(path, payload=None):
        calls.append((path, payload))
        return next(responses)

    written = []
    monkeypatch.setattr(installer, "_safe_http_json", fake_request)
    monkeypatch.setattr(installer, "_checkpoint", lambda state, phase, **fields: written.append((phase, fields)))
    state = {"phase": "SERVICE_STARTED"}

    result = installer._verify_safety_acceptance(state)

    assert result["ready_components"] == len(installer.REQUIRED_HEALTH_COMPONENTS)
    assert result["prompt_injection_rejected"] is True
    assert result["synthetic_crisis_bypassed_generation"] is True
    assert calls[-1] == (f"/internal/safety/reviews/{crisis_case_id}", None)
    assert written[0][0] == "CRISIS_PROBE_VERIFIED"


def test_live_safety_acceptance_reuses_checkpointed_crisis_review(monkeypatch):
    health = {
        "status": "READY",
        "components": {
            name: {"ready": True} for name in installer.REQUIRED_HEALTH_COMPONENTS
        },
    }
    responses = iter(
        [
            health,
            {"decision": {"action": "PROCEED"}},
            {"decision": {"action": "BLOCK"}},
            {"review_case_id": "review-synthetic-002", "status": "PENDING"},
        ]
    )
    paths = []
    monkeypatch.setattr(installer, "_safe_http_json", lambda path, payload=None: (paths.append(path), next(responses))[1])
    monkeypatch.setattr(installer, "_checkpoint", lambda *args, **kwargs: pytest.fail("checkpointed crisis must not be recreated"))

    result = installer._verify_safety_acceptance(
        {"phase": "SERVICE_STARTED", "crisis_review_case_id": "review-synthetic-002"}
    )

    assert result["crisis_review_status"] == "PENDING"
    assert paths.count("/internal/safety/check-input") == 2
    assert paths[-1] == "/internal/safety/reviews/review-synthetic-002"


def test_safety_unit_uses_loopback_and_cpu_only_hardening():
    unit = (ROOT / "13_deployment" / "systemd" / "psynova-school-safety.service").read_text(
        encoding="utf-8"
    )

    assert "Environment=SMHAI_OPA_URL=http://127.0.0.1:8181" in unit
    assert "Environment=SMHAI_HF_HOME=/var/cache/psynova-school-safety/huggingface/hub" in unit
    assert "IPAddressDeny=any" in unit
    assert "IPAddressAllow=127.0.0.1/32" in unit
    assert "MemoryMax=5G" in unit
    assert "0.0.0.0" not in unit


def test_bundle_stage_defers_systemd_validation_until_runtime_dependencies_exist(monkeypatch):
    installed = []

    def install_payload(files):
        installed.append(files)

    monkeypatch.setattr(installer, "_install_payload", install_payload)
    monkeypatch.setattr(
        installer,
        "_run",
        lambda *args, **kwargs: pytest.fail("unit verification must wait for the venv"),
    )

    installer._install_or_verify_bundle({"PAYLOAD_MANIFEST.json": b"{}"})

    assert installed == [{"PAYLOAD_MANIFEST.json": b"{}"}]


def test_bundle_hash_is_sha256_lowercase():
    assert len(installer.MODEL_WEIGHT_SHA256) == hashlib.sha256().digest_size * 2
    assert installer.MODEL_WEIGHT_SHA256 == installer.MODEL_WEIGHT_SHA256.lower()
