from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from harness.controlled_product_eval import cat_compatibility_gate as gate_module
from harness.controlled_product_eval.cat_compatibility_gate import (
    GATE_SCHEMA_VERSION,
    ITEM_BANK_RELATIVE_PATH,
    MAPPER_RELATIVE_PATH,
    build_cat_d3_compatibility_gate,
    validate_cat_d3_compatibility_gate,
)
from harness.controlled_product_eval.credential_provider import EXPECTED_SYNTHETIC_SUBJECTS
from harness.controlled_product_eval.evaluation_compatibility import (
    FIXTURE_DOCUMENT,
    SOURCE_IDENTITY,
    _build_fixture_activation_record,
    canonical_json_bytes,
)
from harness.controlled_product_eval.manifest import ACCEPTED_D4_3A_COMMIT

ROOT = Path(__file__).resolve().parents[5]
SPEC_ROOT = ROOT / "12_evaluation" / "d4-evaluation-r1" / "spec"


def _inputs(tmp_path: Path, run_id: str = "D4RUN-20261002T000000Z-GATE000001"):
    attempt_root = tmp_path / "attempt"
    evidence_dir = attempt_root / "managed-services" / "backend" / "cat-compatibility"
    evidence_dir.mkdir(parents=True)
    fixture_bytes = canonical_json_bytes(FIXTURE_DOCUMENT)
    (evidence_dir / "approved-cat-d3-compatibility-fixture.json").write_bytes(fixture_bytes)
    pid = 63124
    activation_path = evidence_dir / "fixture-activation.json"
    activation = _build_fixture_activation_record(
        run_id=run_id,
        fixture_path=evidence_dir / "approved-cat-d3-compatibility-fixture.json",
        document=FIXTURE_DOCUMENT,
        fixture_bytes=fixture_bytes,
        activated_at="2026-10-02T00:00:00Z",
        process_pid=pid,
        fixture_instance_count=1,
        d3_policy_version="1.0.0",
        d3_policy_hash="sha256:" + "a" * 64,
    )
    activation_path.write_text(json.dumps(activation), encoding="utf-8")

    item_bank_path = ROOT / "01_cat-engine" / "fixtures" / "synthetic_item_bank.v1.json"
    item_bank_raw = item_bank_path.read_bytes()
    item_bank = json.loads(item_bank_raw)
    profile = {
        "instrument_id": item_bank["instrument_id"],
        "instrument_version": item_bank["version"],
        "item_bank_id": item_bank["item_bank_id"],
        "item_bank_version": item_bank["version"],
        "item_bank_sha256": hashlib.sha256(item_bank_raw).hexdigest(),
    }
    assessment = {
        "assessment_id": "ASSESS_gate_fixture",
        "subject_id": EXPECTED_SYNTHETIC_SUBJECTS["student_b"],
        "instrument": {"instrument_id": SOURCE_IDENTITY["instrument_id"], "version": SOURCE_IDENTITY["instrument_version"]},
        "population_scope": SOURCE_IDENTITY["population_scope"],
        "status": "completed",
        "dimensions": {"demo_trait": {}},
        "provenance": {
            "source_adapter": "cat_engine",
            "adapter_version": "0.1.0",
            "cat_engine_version": "0.1.0",
            "item_bank_version": "demo.v1",
        },
    }
    return {
        "run_id": run_id,
        "completed_assessment": assessment,
        "fixture_activation_path": activation_path,
        "attempt_root": attempt_root,
        "backend_process_pids": {pid},
        "cat_profile_evidence": profile,
        "cat_health": {
            "status": "READY",
            "service": "cat",
            "provider": "adaptivetesting",
            "provider_version": "adaptivetesting-1.2.1",
            "item_bank_id": item_bank["item_bank_id"],
            "item_bank_version": "demo.v1",
            "synthetic_fixture_only": True,
        },
        "repo_root": ROOT,
        "accepted_baseline_commit": ACCEPTED_D4_3A_COMMIT,
        "synthetic_subject_ids": tuple(EXPECTED_SYNTHETIC_SUBJECTS.values()),
    }


def _build(inputs):
    return build_cat_d3_compatibility_gate(**inputs)


def _set_activation(field: str, value):
    def mutate(inputs):
        path = inputs["fixture_activation_path"]
        activation = json.loads(path.read_text(encoding="utf-8"))
        activation[field] = value
        path.write_text(json.dumps(activation), encoding="utf-8")

    return mutate


def test_gate_passes_only_with_activated_fixture_and_completed_source_provenance(tmp_path):
    gate = _build(_inputs(tmp_path))

    assert gate["schema_version"] == GATE_SCHEMA_VERSION
    assert gate["status"] == "PASS", gate["issues"]
    assert gate["issues"] == []
    validate_cat_d3_compatibility_gate(gate, run_id=gate["run_id"])
    schema = json.loads((SPEC_ROOT / "d4_cat_d3_compatibility_gate.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER).validate(gate)


@pytest.mark.parametrize(
    ("mutate", "expected_issue"),
    [
        (lambda data: data["completed_assessment"].update(status="in_progress"), "COMPLETED_ASSESSMENT_PROVENANCE_MISMATCH"),
        (lambda data: data["completed_assessment"].update(population_scope="other_population"), "COMPLETED_ASSESSMENT_PROVENANCE_MISMATCH"),
        (lambda data: data["completed_assessment"]["provenance"].update(adapter_version="wrong"), "COMPLETED_ASSESSMENT_PROVENANCE_MISMATCH"),
        (lambda data: data["completed_assessment"].update(dimensions={"other": {}}), "COMPLETED_ASSESSMENT_PROVENANCE_MISMATCH"),
        (lambda data: data["completed_assessment"].update(subject_id="SUBJ_real"), "COMPLETED_ASSESSMENT_PROVENANCE_MISMATCH"),
        (lambda data: data["cat_profile_evidence"].update(item_bank_version="wrong"), "CAT_PROFILE_SOURCE_IDENTITY_MISMATCH"),
        (lambda data: data["cat_health"].update(provider_version="wrong"), "CAT_LIVE_HEALTH_IDENTITY_MISMATCH"),
        (_set_activation("fixture_id", "wrong"), "FIXTURE_NOT_ACTIVE_IN_MANAGED_BACKEND"),
        (_set_activation("approval_reference", "wrong"), "FIXTURE_NOT_ACTIVE_IN_MANAGED_BACKEND"),
        (_set_activation("dimension_map", {"demo_trait": "demo_trait"}), "FIXTURE_NOT_ACTIVE_IN_MANAGED_BACKEND"),
        (lambda data: data["backend_process_pids"].clear(), "FIXTURE_NOT_ACTIVE_IN_MANAGED_BACKEND"),
    ],
)
def test_gate_fails_closed_on_mismatched_identity_or_activation(tmp_path, mutate, expected_issue):
    inputs = _inputs(tmp_path)
    mutate(inputs)

    gate = _build(inputs)

    assert gate["status"] == "FAIL"
    assert expected_issue in gate["issues"]
    with pytest.raises(ValueError, match="CAT_D3_COMPATIBILITY_GATE_FAILED"):
        validate_cat_d3_compatibility_gate(gate, run_id=gate["run_id"])


def test_gate_rejects_noncanonical_or_wrong_approved_fixture_file(tmp_path):
    inputs = _inputs(tmp_path)
    fixture_path = inputs["fixture_activation_path"].with_name("approved-cat-d3-compatibility-fixture.json")
    fixture_path.write_bytes(b"{}")

    gate = _build(inputs)

    assert gate["status"] == "FAIL"
    assert "APPROVED_FIXTURE_FILE_MISMATCH" in gate["issues"]


def test_gate_rejects_missing_activation_evidence(tmp_path):
    inputs = _inputs(tmp_path)
    inputs["fixture_activation_path"].unlink()

    gate = _build(inputs)

    assert gate["status"] == "FAIL"
    assert "FIXTURE_ACTIVATION_EVIDENCE_MISSING_OR_INVALID" in gate["issues"]


@pytest.mark.parametrize("relative_path", [ITEM_BANK_RELATIVE_PATH, MAPPER_RELATIVE_PATH])
def test_gate_rejects_wrong_accepted_source_blob(tmp_path, monkeypatch, relative_path):
    inputs = _inputs(tmp_path)
    original = gate_module._git_blob

    def wrong_blob(repo_root, commit, path):
        result = original(repo_root, commit, path)
        return "0" * 40 if path == relative_path else result

    monkeypatch.setattr(gate_module, "_git_blob", wrong_blob)

    gate = _build(inputs)

    assert gate["status"] == "FAIL"
    expected_issue = "CAT_ITEM_BANK_GIT_BLOB_MISMATCH" if relative_path == ITEM_BANK_RELATIVE_PATH else "CAT_MAPPER_GIT_BLOB_MISMATCH"
    assert expected_issue in gate["issues"]


def test_gate_rejects_wrong_run_binding_in_activation(tmp_path):
    inputs = _inputs(tmp_path)
    activation_path = inputs["fixture_activation_path"]
    activation = json.loads(activation_path.read_text(encoding="utf-8"))
    activation["run_id"] = "D4RUN-OTHER"
    activation_path.write_text(json.dumps(activation), encoding="utf-8")

    gate = _build(inputs)

    assert gate["status"] == "FAIL"
    assert "FIXTURE_NOT_ACTIVE_IN_MANAGED_BACKEND" in gate["issues"]
