"""Focused deterministic tests for the D4 schema/authority foundation."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from .schema_validation import (
    FoundationValidationError,
    SCHEMA_PATHS,
    load_authority_registry,
    schema_issues,
    validate_authority_registry,
    validate_document,
    validate_machine_evidence,
    validate_run_manifest,
    validate_scenario,
    validate_scenario_collection,
)
from .splits import enforce_split_integrity
from .errors import SplitIntegrityError

HERE = Path(__file__).resolve().parent
VALID = HERE / "fixtures_valid"
NEGATIVE = HERE / "fixtures_negative"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_all_foundation_schemas_are_valid_draft_2020_12_schemas() -> None:
    from jsonschema import Draft202012Validator

    for name, path in SCHEMA_PATHS.items():
        schema = _load(path)
        Draft202012Validator.check_schema(schema)


def test_authority_registry_has_exact_canonical_ranges() -> None:
    registry = validate_authority_registry(load_authority_registry())
    assert [entry["id"] for entry in registry["d4e"]] == [
        f"D4E-{index:02d}" for index in range(1, 61)
    ]
    assert [entry["id"] for entry in registry["d4sup"]] == [
        f"D4SUP-{index:02d}" for index in range(1, 21)
    ]
    assert registry["authority_source"]["status"] == "FROZEN FOR BOUNDED IMPLEMENTATION"


def test_valid_foundation_records_validate() -> None:
    validate_scenario(_load(VALID / "scenario.json"))
    validate_run_manifest(_load(VALID / "run_manifest_SAMPLE_ONLY.json"))
    validate_machine_evidence(_load(VALID / "machine_evidence.json"))


def test_valid_compatibility_and_sealed_review_fixtures_validate() -> None:
    validate_scenario(_load(VALID / "scenario_legacy_compat.json"))
    validate_machine_evidence(_load(VALID / "machine_evidence_sealed_not_required.json"))
    validate_machine_evidence(_load(VALID / "machine_evidence_sealed_complete.json"))


@pytest.mark.parametrize(
    ("path", "schema_name"),
    [
        (NEGATIVE / "scenario_wrong_fixture_mapping.json", "scenario"),
        (NEGATIVE / "manifest_mixed_fixture_modes.json", "run_manifest"),
        (NEGATIVE / "evidence_sealed_pending_review.json", "machine_evidence"),
        (NEGATIVE / "evidence_wrong_fixture_mapping.json", "machine_evidence"),
        (NEGATIVE / "scenario_invalid_authority.json", "scenario"),
        (NEGATIVE / "scenario_invalid_sha.json", "scenario"),
        (NEGATIVE / "scenario_duplicate_authority_ids.json", "scenario"),
        (NEGATIVE / "scenario_path_traversal.json", "scenario"),
    ],
)
def test_negative_fixtures_fail_closed(path: Path, schema_name: str) -> None:
    with pytest.raises(FoundationValidationError):
        validate_document(_load(path), schema_name)


def test_expected_and_observed_fields_are_distinct() -> None:
    evidence = _load(VALID / "machine_evidence.json")
    assert "response_class" not in evidence
    assert evidence["expected_response_class"] == "SHOULD_ANSWER"
    assert evidence["observed_response_class"] == "NOT_OBSERVED"
    assert evidence["observed_outcome"] == "NOT_RUN"

    legacy = copy.deepcopy(evidence)
    legacy.pop("expected_response_class")
    legacy.pop("observed_response_class")
    legacy.pop("observed_outcome")
    legacy["response_class"] = "SHOULD_ANSWER"
    assert schema_issues(legacy, "machine_evidence")


def test_sealed_human_review_condition_is_explicit() -> None:
    evidence = _load(VALID / "machine_evidence.json")
    sealed_without_review = copy.deepcopy(evidence)
    sealed_without_review["run_mode"] = "SEALED_FINAL"
    validate_machine_evidence(sealed_without_review)

    sealed_complete = copy.deepcopy(evidence)
    sealed_complete["run_mode"] = "SEALED_FINAL"
    sealed_complete["human_review"] = {
        "required": True,
        "status": "COMPLETE",
        "packet_id": "D4-PACKET-complete",
        "disagreement_preserved": True,
        "unresolved_decision": False,
    }
    validate_machine_evidence(sealed_complete)

    sealed_pending = copy.deepcopy(sealed_complete)
    sealed_pending["human_review"]["status"] = "PENDING"
    sealed_pending["human_review"]["unresolved_decision"] = True
    with pytest.raises(FoundationValidationError):
        validate_machine_evidence(sealed_pending)


def test_sealed_manifest_accepts_complete_or_not_required_closure() -> None:
    manifest = _load(VALID / "run_manifest_SAMPLE_ONLY.json")
    manifest.update(
        {
            "run_mode": "SEALED_FINAL",
            "sealed_hash": "0" * 64,
            "promptfoo_version": "1.2.3",
            "promptfoo_config_hash": "1" * 64,
            "network_policy": "observed_loopback_only",
            "network_observation": "observed_loopback_only",
            "provider_identities": {
                "target": "local-target",
                "attacker": "local-attacker",
                "grader": "local-grader",
            },
            "runtime": {"model": "local-model", "digest": "2" * 64},
            "node_runtime": "node-v22",
            "lock_hash": "3" * 64,
            "wrapper_identity": "local-wrapper-v1",
            "endpoint_inventory": [
                {
                    "name": "backend",
                    "endpoint": "http://127.0.0.1:8000",
                    "approved": True,
                }
            ],
            "sealed_evaluation": {
                "status": "COMPLETE",
                "case_count": 1,
                "scenario_family_distribution": {"foundation": 1},
                "creation_provenance": "synthetic_fixture",
                "approval_ref": "CONTROLLER-SEALED-APPROVAL",
            },
        }
    )
    manifest["human_review_closure"] = {
        "status": "NOT_REQUIRED",
        "mandatory_complete": False,
        "unresolved_count": 0,
        "disagreement_preserved": True,
    }
    validate_run_manifest(manifest)

    manifest["human_review_closure"] = {
        "status": "COMPLETE",
        "mandatory_complete": True,
        "unresolved_count": 0,
        "disagreement_preserved": True,
    }
    validate_run_manifest(manifest)

    manifest["human_review_closure"] = {
        "status": "PENDING",
        "mandatory_complete": False,
        "unresolved_count": 1,
        "disagreement_preserved": True,
    }
    with pytest.raises(FoundationValidationError):
        validate_run_manifest(manifest)


def test_evidence_collection_rejects_mixed_fixture_modes() -> None:
    first = _load(VALID / "machine_evidence.json")
    second = copy.deepcopy(first)
    second["case_id"] = "D4E-02-mixed-fixture"
    second["assessment_binding"] = {
        **second["assessment_binding"],
        "fixture_mode": "legacy_compatibility_fixture",
        "compatibility_mapping": "D3-4_BACKEND_SYNTHETIC_COMPATIBILITY_V1",
    }
    from .schema_validation import validate_records

    with pytest.raises(FoundationValidationError):
        validate_records(machine_evidence=[first, second])


def test_cross_split_semantic_duplicate_is_rejected() -> None:
    records = _load(NEGATIVE / "scenario_cross_split_semantic_duplicate.json")
    for record in records:
        validate_scenario(record)
    with pytest.raises(SplitIntegrityError):
        enforce_split_integrity(records)


def test_d4e_ids_are_required_and_d4sup_ids_may_be_empty() -> None:
    evidence = _load(VALID / "machine_evidence.json")
    evidence["d4sup_ids"] = []
    validate_machine_evidence(evidence)

    missing_authority = copy.deepcopy(evidence)
    missing_authority["d4e_ids"] = []
    with pytest.raises(FoundationValidationError):
        validate_machine_evidence(missing_authority)


def test_formal_scenarios_require_d4e_authority_and_allow_empty_d4sup() -> None:
    scenario = _load(VALID / "scenario.json")
    scenario["d4sup_ids"] = []
    validate_scenario(scenario)

    missing_authority = copy.deepcopy(scenario)
    missing_authority["d4e_ids"] = []
    with pytest.raises(FoundationValidationError):
        validate_scenario(missing_authority)


def test_duplicate_turn_and_case_ids_are_rejected() -> None:
    scenario = _load(VALID / "scenario.json")
    duplicate_turn = copy.deepcopy(scenario)
    duplicate_turn["turns"].append({"turn_id": "t1", "message": "第二轮"})
    with pytest.raises(FoundationValidationError):
        validate_scenario(duplicate_turn)

    duplicate_case = copy.deepcopy(scenario)
    with pytest.raises(FoundationValidationError):
        validate_scenario_collection([scenario, duplicate_case])

    duplicate_authority = _load(VALID / "machine_evidence.json")
    duplicate_authority["d4e_ids"] = ["D4E-01", "D4E-01"]
    with pytest.raises(FoundationValidationError):
        validate_machine_evidence(duplicate_authority)

    duplicate_result_path = _load(VALID / "run_manifest_SAMPLE_ONLY.json")
    duplicate_result_path["result_paths"] = ["results/a.json", "results/a.json"]
    with pytest.raises(FoundationValidationError):
        validate_run_manifest(duplicate_result_path)


def test_relative_fixture_and_artifact_paths_reject_escape_syntax() -> None:
    scenario = _load(VALID / "scenario.json")
    scenario["fixture_refs"][0]["path"] = "../outside.json"
    with pytest.raises(FoundationValidationError):
        validate_scenario(scenario)

    manifest = _load(VALID / "run_manifest_SAMPLE_ONLY.json")
    manifest["result_paths"] = ["https://example.invalid/result.json"]
    with pytest.raises(FoundationValidationError):
        validate_run_manifest(manifest)


def test_unknown_top_level_fields_are_rejected() -> None:
    scenario = _load(VALID / "scenario.json")
    scenario["unreviewed_extra"] = True
    assert schema_issues(scenario, "scenario")


def test_secret_shaped_nested_fields_are_rejected() -> None:
    evidence = _load(VALID / "machine_evidence.json")
    evidence["structured_output"] = {"access_token": "synthetic-but-forbidden"}
    with pytest.raises(FoundationValidationError):
        validate_machine_evidence(evidence)

    manifest = _load(VALID / "run_manifest_SAMPLE_ONLY.json")
    manifest["hardware"] = {"env_dump": "forbidden"}
    with pytest.raises(FoundationValidationError):
        validate_run_manifest(manifest)


def test_d4sup_case_ids_stop_at_the_authority_registry_boundary() -> None:
    scenario = _load(VALID / "scenario.json")
    scenario["case_id"] = "D4SUP-21-OUT_OF_REGISTRY"
    with pytest.raises(FoundationValidationError):
        validate_scenario(scenario)
