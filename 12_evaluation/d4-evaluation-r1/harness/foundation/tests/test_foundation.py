from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest
import jsonschema

from harness.foundation.errors import (
    ArtifactPathError,
    FixtureModeError,
    HashIntegrityError,
    ManifestError,
    RunIdError,
    SealedMutationError,
    SplitIntegrityError,
)
from harness.foundation.evidence import build_machine_evidence
from harness.foundation.fixtures import enforce_fixture_mode_isolation
from harness.foundation.hashing import (
    canonical_dataset_hash,
    canonical_json,
    canonical_json_bytes,
    canonical_sha256,
    canonical_sha256_tag,
    verify_self_hash,
)
from harness.foundation.manifest import (
    build_run_manifest,
    manifest_content_hash,
    validate_run_manifest,
    write_run_manifest,
)
from harness.foundation.paths import safe_artifact_path, validate_artifact_paths
from harness.foundation.run_ids import ImmutableRunId, create_run_id
from harness.foundation.sealed import (
    SealedEvaluationGuard,
    assert_sealed_unchanged,
    freeze_sealed_dataset,
)
from harness.foundation.splits import (
    detect_cross_split_collisions,
    enforce_split_integrity,
    enforce_split_tree,
    load_dataset_records,
)


ROOT = Path(__file__).resolve().parents[3]
DATASETS = ROOT / "datasets"


def _records() -> list[dict]:
    records: list[dict] = []
    for split, directory in (("DEV", "dev"), ("REGRESSION", "regression"), ("SEALED_EVAL", "sealed")):
        records.extend(load_dataset_records(DATASETS / directory, expected_split=split))
    return records


def test_canonical_json_is_utf8_sorted_compact_and_excludes_only_self_field() -> None:
    value = {"z": "中文", "a": 1, "hash": "ignored", "nested": {"z": 2, "a": 1}}
    original = deepcopy(value)
    assert canonical_json(value, self_field="hash") == '{"a":1,"nested":{"a":1,"z":2},"z":"中文"}'
    assert canonical_json_bytes(value, self_field="hash").decode("utf-8").encode("utf-8")
    assert value == original
    assert canonical_sha256(value, self_field="hash") == canonical_sha256(
        {"z": "中文", "a": 1, "nested": {"z": 2, "a": 1}}, self_field=None
    )
    with pytest.raises(HashIntegrityError):
        canonical_json({"not_finite": float("nan")})


def test_self_hash_and_dataset_hash_are_stable_across_record_order() -> None:
    records = _records()
    for record in records:
        assert verify_self_hash(record)
    reversed_records = list(reversed(records))
    assert canonical_dataset_hash(records) == canonical_dataset_hash(reversed_records)
    tampered = deepcopy(records[0])
    tampered["hash"] = canonical_sha256_tag(tampered, self_field="hash")
    tampered["turns"][0]["message"] = "修改后的合成文本"
    with pytest.raises(HashIntegrityError):
        verify_self_hash(tampered)


def test_run_id_is_opaque_and_immutable() -> None:
    timestamp = datetime(2026, 9, 22, tzinfo=timezone.utc)
    first = create_run_id(timestamp=timestamp, entropy="foundation-test")
    second = create_run_id(timestamp=timestamp, entropy="foundation-test")
    assert first == second
    holder = ImmutableRunId(first)
    assert holder.assign(first) == first
    with pytest.raises(RunIdError):
        holder.assign(create_run_id(timestamp=timestamp, entropy="other"))
    with pytest.raises(RunIdError):
        ImmutableRunId("D4RUN-x")


def test_split_tree_and_fixture_mode_are_isolated() -> None:
    summary = enforce_split_tree(DATASETS)
    assert summary["case_count"] == 3
    assert summary["split_counts"] == {"DEV": 1, "REGRESSION": 1, "SEALED_EVAL": 1}
    assert summary["fixture_mode"] == "exact_d3_fixture"
    mixed = [deepcopy(_records()[0]), deepcopy(_records()[1])]
    mixed[1]["fixture_mode"] = "legacy_compatibility_fixture"
    mixed[1]["fixture_refs"][0]["compatibility_mapping"] = "D3-4_BACKEND_SYNTHETIC_COMPATIBILITY_V1"
    mixed[1]["hash"] = canonical_sha256_tag(mixed[1], self_field="hash")
    with pytest.raises(FixtureModeError):
        enforce_fixture_mode_isolation(mixed)


def test_semantic_family_cross_split_collision_is_hard_failure() -> None:
    records = _records()
    altered = deepcopy(records[1])
    altered["case_id"] = "D4SUP-16-COLLISION"
    altered["semantic_family"] = records[0]["semantic_family"]
    altered["hash"] = canonical_sha256_tag(altered, self_field="hash")
    collisions = detect_cross_split_collisions([records[0], altered])
    assert any(item.field == "semantic_family" for item in collisions)
    with pytest.raises(SplitIntegrityError):
        enforce_split_integrity([records[0], altered])


def test_sealed_snapshot_rejects_mutation_and_tuning_after_observation() -> None:
    sealed = [record for record in _records() if record["split"] == "SEALED_EVAL"]
    snapshot = freeze_sealed_dataset(
        sealed,
        version="1.0.0",
        creation_provenance="synthetic foundation fixture",
        approval_ref="D4-FOUNDATION-APPROVAL",
    )
    assert_sealed_unchanged(snapshot, sealed)
    mutated = deepcopy(sealed)
    mutated[0]["turns"][0]["message"] = "密封集发生修改"
    with pytest.raises(SealedMutationError):
        assert_sealed_unchanged(snapshot, mutated)
    guard = SealedEvaluationGuard.from_records(
        sealed,
        version="1.0.0",
        creation_provenance="synthetic foundation fixture",
        approval_ref="D4-FOUNDATION-APPROVAL",
        protected_inputs={"prompt": "fixed", "policy": "fixed"},
    )
    guard.observe_output(sealed[0]["case_id"])
    with pytest.raises(SealedMutationError):
        guard.assert_tuning_allowed(kind="prompt")
    with pytest.raises(SealedMutationError):
        guard.assert_protected_inputs({"prompt": "tuned", "policy": "fixed"})


def test_artifact_paths_reject_absolute_and_traversal(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    assert safe_artifact_path(root, "results/evidence.json").parent == root / "results"
    assert validate_artifact_paths(["results/evidence.json"], root=root) == [
        "results/evidence.json"
    ]
    for unsafe in ("../secret.json", "C:\\secret.json", "/secret.json", "\\\\server\\share\\x"):
        with pytest.raises(ArtifactPathError):
            safe_artifact_path(root, unsafe)
    for unsafe in ("09_backend/result.json", ".env", "results/access_token.json"):
        with pytest.raises(ArtifactPathError):
            validate_artifact_paths([unsafe], root=root)


def test_manifest_builder_is_schema_shaped_and_write_is_immutable(tmp_path: Path) -> None:
    manifest = build_run_manifest(
        run_id="D4RUN-20260922T000000Z-aaaaaaaaaaaa",
        timestamp="2026-09-22T00:00:00Z",
        git_commit="0" * 40,
        result_paths=["results/evidence.json"],
    )
    assert validate_run_manifest(manifest)
    assert len(manifest_content_hash(manifest)) == 64
    path = tmp_path / "manifests" / "run_manifest.json"
    assert write_run_manifest(path, manifest) == path
    assert write_run_manifest(path, manifest) == path
    changed = deepcopy(manifest)
    changed["test_groups"] = ["changed"]
    with pytest.raises(ManifestError):
        write_run_manifest(path, changed)

    malformed = deepcopy(manifest)
    malformed["timestamp"] = "not-a-date"
    with pytest.raises(ManifestError):
        validate_run_manifest(malformed)
    malformed = deepcopy(manifest)
    malformed["unexpected"] = True
    with pytest.raises(ManifestError):
        validate_run_manifest(malformed)


def test_manifest_builder_rejects_fixture_mode_override_pooling() -> None:
    with pytest.raises(ManifestError):
        build_run_manifest(
            fixture_mode="exact_d3_fixture",
            bootstrap_modes=["legacy_compatibility_fixture"],
            fixture_audit={
                "fixture_mode": "legacy_compatibility_fixture",
                "source_identity": "CURRENT_SYNTHETIC_GRM",
                "target_identity": "SYNTHETIC_STUDENT_DEMO",
                "compatibility_mapping": "D3-4_BACKEND_SYNTHETIC_COMPATIBILITY_V1",
                "separation_rule": "one_mode_per_run",
            },
        )


def test_machine_evidence_shell_validates_against_current_schema() -> None:
    scenario = load_dataset_records(DATASETS / "dev", expected_split="DEV")[0]
    manifest = build_run_manifest(git_commit="0" * 40)
    evidence = build_machine_evidence(manifest, scenario)
    assert evidence["schema_version"] == "d4-evidence-v1"
    assert evidence["expected_response_class"] == "MUST_ANSWER"
    assert evidence["observed_response_class"] == "NOT_OBSERVED"
    assert evidence["observed_outcome"] == "NOT_RUN"
    assert evidence["real_student_data"] is False
    assert evidence["cloud_fallback"] is False
    assert evidence["assessment_binding"]["fixture_identity"] == "synthetic_assessment.v1"
    schema = json.loads(
        (ROOT / "spec" / "d4_machine_evidence.schema.json").read_text(encoding="utf-8")
    )
    assert list(jsonschema.Draft202012Validator(schema).iter_errors(evidence)) == []
    with pytest.raises(ManifestError):
        build_machine_evidence(manifest, scenario, d4e_ids=["D4E-20", "D4E-20"])
    with pytest.raises(ManifestError):
        build_machine_evidence(manifest, scenario, grader={"api_key": "forbidden"})
    with pytest.raises(ManifestError):
        build_machine_evidence(
            manifest,
            scenario,
            answerability={
                "expected": "MUST_DENY",
                "observed": "NOT_OBSERVED",
                "false_refusal": False,
                "false_answer": False,
            },
        )


def test_sealed_builder_never_fabricates_required_human_review() -> None:
    scenario = load_dataset_records(DATASETS / "sealed", expected_split="SEALED_EVAL")[0]
    manifest = build_run_manifest(
        run_mode="SEALED_FINAL",
        git_commit="0" * 40,
        sealed_records=[scenario],
        sealed_approval_ref="D4-FOUNDATION-APPROVAL",
        sealed_creation_provenance="synthetic foundation fixture",
        promptfoo_version="1.2.3",
        promptfoo_config_hash="1" * 64,
        provider_identities={"target": "t", "attacker": "a", "grader": "g"},
        runtime={"model": "m", "digest": "d"},
        network_policy="observed_loopback_only",
        network_observation="observed_loopback_only",
        human_review_closure={
            "status": "COMPLETE",
            "mandatory_complete": True,
            "unresolved_count": 0,
            "disagreement_preserved": True,
        },
        node_runtime="node",
        lock_hash="2" * 64,
        wrapper_identity="wrapper",
        endpoint_inventory=[{"name": "backend", "endpoint": "http://127.0.0.1:8000", "approved": True}],
    )
    with pytest.raises(ManifestError):
        build_machine_evidence(manifest, scenario)

    evidence = build_machine_evidence(
        manifest,
        scenario,
        human_review={
            "required": True,
            "status": "COMPLETE",
            "packet_id": "D4-PACKET-FOUNDATION-COMPLETE",
            "disagreement_preserved": True,
            "unresolved_decision": False,
        },
    )
    assert evidence["human_review"]["status"] == "COMPLETE"


def test_machine_evidence_rejects_manifest_fixture_mode_conflict() -> None:
    scenario = load_dataset_records(DATASETS / "dev", expected_split="DEV")[0]
    manifest = build_run_manifest(
        git_commit="0" * 40,
        fixture_mode="legacy_compatibility_fixture",
    )
    with pytest.raises(ManifestError):
        build_machine_evidence(manifest, scenario)


def test_sealed_manifest_requires_explicit_local_controls() -> None:
    sealed = [record for record in _records() if record["split"] == "SEALED_EVAL"]
    manifest = build_run_manifest(
        run_id="D4RUN-20260922T000000Z-eeeeeeeeeeee",
        run_mode="SEALED_FINAL",
        timestamp="2026-09-22T00:00:00Z",
        git_commit="0" * 40,
        sealed_records=sealed,
        sealed_creation_provenance="synthetic foundation fixture",
        sealed_approval_ref="D4-FOUNDATION-APPROVAL",
        promptfoo_version="1.2.3",
        promptfoo_config_hash="1" * 64,
        provider_identities={
            "target": "backend-local",
            "attacker": "attacker-local",
            "grader": "grader-local",
        },
        runtime={"model": "MODEL_local_primary", "digest": "digest-local"},
        network_policy="observed_loopback_only",
        network_observation="observed_loopback_only",
        human_review_closure={
            "status": "COMPLETE",
            "mandatory_complete": True,
            "unresolved_count": 0,
            "disagreement_preserved": True,
        },
        node_runtime="node-local",
        lock_hash="2" * 64,
        wrapper_identity="wrapper-local",
        endpoint_inventory=[
            {"name": "backend", "endpoint": "http://127.0.0.1:8000", "approved": True}
        ],
    )
    schema = json.loads(
        (ROOT / "spec" / "d4_run_manifest.schema.json").read_text(encoding="utf-8")
    )
    assert list(jsonschema.Draft202012Validator(schema).iter_errors(manifest)) == []
    with pytest.raises(ManifestError):
        build_run_manifest(
            run_mode="SEALED_FINAL",
            git_commit="0" * 40,
            sealed_records=sealed,
            promptfoo_version="1.2.3",
            promptfoo_config_hash="1" * 64,
            provider_identities={
                "target": "backend-local",
                "attacker": "attacker-local",
                "grader": "grader-local",
            },
            runtime={"model": "MODEL_local_primary", "digest": "digest-local"},
            network_policy="observed_loopback_only",
            network_observation="observed_loopback_only",
            human_review_closure={
                "status": "COMPLETE",
                "mandatory_complete": True,
                "unresolved_count": 0,
                "disagreement_preserved": True,
            },
            node_runtime="node-local",
            lock_hash="2" * 64,
            wrapper_identity="wrapper-local",
            endpoint_inventory=[
                {"name": "backend", "endpoint": "http://127.0.0.1:8000", "approved": True}
            ],
        )
