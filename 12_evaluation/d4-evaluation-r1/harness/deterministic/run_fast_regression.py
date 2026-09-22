"""Run the D4-2 C0/C1 deterministic regression set and persist evidence."""

from __future__ import annotations

import argparse
import asyncio
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EVALUATION_ROOT = Path(__file__).resolve().parents[2]
import sys

if str(EVALUATION_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALUATION_ROOT))

from harness.deterministic.cases import CaseObservation, run_all_cases
from harness.foundation.evidence import build_machine_evidence
from harness.foundation.hashing import canonical_json, canonical_sha256
from harness.foundation.manifest import (
    build_run_manifest,
    manifest_content_hash,
    write_run_manifest,
)
from harness.foundation.schema_validation import validate_machine_evidence
from harness.foundation.splits import load_dataset_records

DATASETS_ROOT = EVALUATION_ROOT / "datasets"
MANIFESTS_ROOT = EVALUATION_ROOT / "manifests"
RESULTS_ROOT = EVALUATION_ROOT / "results"
REPORTS_ROOT = EVALUATION_ROOT / "reports"
REGRESSION_DATASET = DATASETS_ROOT / "regression" / "deterministic_regression.json"
RESULT_PATH = "results/d4_slice2_machine_evidence.json"
SUMMARY_PATH = "d4_slice2_deterministic_evaluation.json"
MANIFEST_PATH = "manifests/d4_slice2_fast_regression.json"


def _git_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=EVALUATION_ROOT.parents[1],
        text=True,
    ).strip()


def _hash_identity(value: str) -> str:
    return canonical_sha256({"identity": value})


def _load_records() -> list[dict[str, Any]]:
    return load_dataset_records(REGRESSION_DATASET, expected_split="REGRESSION")


def _manifest(
    *, run_id: str, commit: str, records: list[dict[str, Any]]
) -> dict[str, Any]:
    return build_run_manifest(
        run_id=run_id,
        run_mode="FAST_REGRESSION",
        timestamp=datetime.now(timezone.utc),
        git_commit=commit,
        accepted_tags=["d4-slice1-r1-accepted"],
        fixture_mode="exact_d3_fixture",
        dataset_records={"regression": records},
        artifact_root=EVALUATION_ROOT,
        result_paths=[RESULT_PATH, SUMMARY_PATH],
        dataset_versions={
            "dev": "d4-dev-v1",
            "regression": "d4-regression-deterministic-r1",
            "sealed": "d4-sealed-v1",
        },
        provider_identities={
            "target": "in_process_contract_fake",
            "attacker": None,
            "grader": None,
        },
        runtime={"model": "CONTRACT_FAKE", "digest": "contract_fake_in_process_v1"},
        template_ids_hashes={
            "PROMPT_student_synthetic_v1": _hash_identity("PROMPT_student_synthetic_v1")
        },
        policy_ids_hashes={
            "D4_DETERMINISTIC_POLICY_V1": _hash_identity("D4_DETERMINISTIC_POLICY_V1")
        },
        rag_corpus_identity="synthetic_d4_deterministic_v1",
        seed=42,
        repeat_settings={"repeats": 1, "concurrency": 1, "cache": "disabled"},
        hardware={"execution": "in_process", "gpu": "not_used"},
        network_policy="loopback_only",
        network_observation="NOT_RUN",
        test_groups=[
            "D4-2-TRUST",
            "D4-2-ROLE",
            "D4-2-DISCLOSURE",
            "D4-2-CITATION",
            "D4-2-SAFETY",
            "D4-2-FAIL_CLOSED",
            "D4-2-HISTORICAL_REPLAY",
        ],
        wrapper_identity="harness/deterministic/cases.py@D4-2-R1",
        endpoint_inventory=[
            {
                "name": "support_requests",
                "endpoint": "/api/v1/support/requests",
                "approved": True,
            },
            {
                "name": "generations",
                "endpoint": "/api/v1/generations",
                "approved": True,
            },
            {"name": "retrievals", "endpoint": "/api/v1/retrievals", "approved": True},
            {
                "name": "safety_checks",
                "endpoint": "/api/v1/safety/checks",
                "approved": True,
            },
        ],
    )


def _evidence_record(
    manifest: dict[str, Any],
    scenario: dict[str, Any],
    observation: CaseObservation,
) -> dict[str, Any]:
    limitations = list(observation.limitations)
    transaction_id = observation.transaction_id
    if transaction_id is not None and not re.fullmatch(
        r"TXN_[A-Za-z0-9][A-Za-z0-9._-]*", transaction_id
    ):
        limitations.append("product_transaction_id_prefix_is_TX_not_TXN")
        transaction_id = None
    fields: dict[str, Any] = {
        "case_id": observation.case_id,
        "d4e_ids": list(observation.d4e_ids),
        "d4sup_ids": list(observation.d4sup_ids),
        "risk_domain": observation.risk_domain,
        "route": observation.route,
        "expected_invariant": observation.expected_invariant,
        "failure_type": observation.failure_type,
        "expected_response_class": observation.expected_response_class,
        "observed_response_class": observation.observed_response_class,
        "observed_outcome": observation.observed_outcome,
        "calls": observation.calls,
        "request_id": observation.request_id,
        "trace_id": observation.trace_id,
        "transaction_id": transaction_id,
        "stage": observation.stage,
        "target_identity": "SYNTHETIC_STUDENT_DEMO",
        "model_identity": "CONTRACT_FAKE",
        "template_identity": observation.template_identity,
        "policy_identity": "D4_DETERMINISTIC_POLICY_V1",
        "evidence_bundle": observation.evidence_bundle
        or {"id": None, "hash": None, "status": "NOT_ASSESSED"},
        "http_status": observation.http_status,
        "product_status": observation.product_status,
        "safety": observation.safety,
        "citation_support": observation.citation_support,
        "assessment_binding": observation.assessment_binding,
        "role_context": observation.role_context,
        "artifacts": observation.artifacts or [RESULT_PATH],
        "limitations": sorted(set(limitations)),
        "real_student_data": False,
        "cloud_fallback": False,
    }
    if observation.context_id is not None:
        fields["context_id"] = observation.context_id
    if observation.call_order:
        fields["call_order"] = observation.call_order
    if observation.regression_fixture_promoted is not None:
        fields["regression_fixture_promoted"] = observation.regression_fixture_promoted
    evidence = build_machine_evidence(manifest, scenario, **fields)
    validate_machine_evidence(evidence)
    return evidence


async def _run() -> int:
    records = _load_records()
    commit = _git_commit()
    run_id = _ARGS.run_id or None
    if run_id is None:
        from harness.foundation.run_ids import create_run_id

        run_id = create_run_id(entropy="d4-slice2-deterministic-r1")
    manifest = _manifest(run_id=run_id, commit=commit, records=records)
    manifest_relpath = _ARGS.manifest_path or MANIFEST_PATH
    manifest_path = EVALUATION_ROOT / manifest_relpath
    write_run_manifest(manifest_path, manifest, artifact_root=EVALUATION_ROOT)

    observations = await run_all_cases()
    by_case = {observation.case_id: observation for observation in observations}
    missing = [
        record["case_id"] for record in records if record["case_id"] not in by_case
    ]
    if missing:
        raise RuntimeError(f"missing deterministic observations: {missing}")
    evidence = [
        _evidence_record(manifest, record, by_case[record["case_id"]])
        for record in records
    ]
    evidence.sort(key=lambda item: item["case_id"])
    manifest_hash = manifest_content_hash(manifest)
    result_document = {
        "schema_version": "d4-machine-evidence-batch-v1",
        "run_id": run_id,
        "run_mode": "FAST_REGRESSION",
        "git_commit": commit,
        "manifest_hash": manifest_hash,
        "accepted_tags": ["d4-slice1-r1-accepted"],
        "network_calls": 0,
        "model_calls": 0,
        "promptfoo_version": None,
        "cases": evidence,
    }
    result_path = RESULTS_ROOT / "d4_slice2_machine_evidence.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(canonical_json(result_document) + "\n", encoding="utf-8")

    failed = [item for item in evidence if item["observed_outcome"] == "FAIL"]
    errors = [
        item
        for item in evidence
        if item["observed_outcome"] in {"ERROR", "BLOCKED", "PENDING_REVIEW"}
    ]
    p0_cases = [item for item in failed if item["case_id"] == "D4E-26-HIDDEN-EXISTENCE"]
    summary = {
        "schema_version": "d4-slice2-deterministic-v1",
        "run_id": run_id,
        "run_mode": "FAST_REGRESSION",
        "git_commit": commit,
        "manifest_path": manifest_relpath,
        "manifest_hash": manifest_hash,
        "result_path": RESULT_PATH,
        "formal_case_count": len(records),
        "split_counts": {"DEV": 0, "REGRESSION": len(records), "SEALED_EVAL": 0},
        "pass_count": len(evidence) - len(failed) - len(errors),
        "fail_count": len(failed),
        "error_count": len(errors),
        "non_pass_count": len(failed) + len(errors),
        "new_p0_count": len(p0_cases),
        "status": (
            "D4_P0_FOUND"
            if p0_cases
            else "CONTROLLER_DECISION_REQUIRED"
            if errors
            else "READY_FOR_CONTROLLER_REVIEW"
        ),
        "p0_cases": [item["case_id"] for item in p0_cases],
        "observations": [
            {
                "case_id": item["case_id"],
                "d4e_ids": item["d4e_ids"],
                "observed_outcome": item["observed_outcome"],
                "failure_type": item["failure_type"],
                "product_status": item["product_status"],
            }
            for item in evidence
        ],
        "product_source_changed": False,
        "real_student_data": False,
        "cloud_fallback": False,
        "d4_3_started": False,
    }
    (EVALUATION_ROOT / SUMMARY_PATH).write_text(
        canonical_json(summary) + "\n", encoding="utf-8"
    )
    print(canonical_json(summary))
    return 2 if p0_cases or errors else 0


def main() -> None:
    global _ARGS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--manifest-path", default=MANIFEST_PATH)
    _ARGS = parser.parse_args()
    raise SystemExit(asyncio.run(_run()))


_ARGS: argparse.Namespace


if __name__ == "__main__":
    main()
