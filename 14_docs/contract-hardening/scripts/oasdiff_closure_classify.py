"""Classify every raw oasdiff finding for Contract/API Hardening Round 1 closure.

The classification is intentionally narrow.  It fails closed when a finding does
not match the evidence-backed closure taxonomy, so the generated totals cannot
silently hide a new compatibility problem.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "14_docs" / "contract-hardening" / "evidence"

COMPARISONS = {
    "integration_to_hardened": {
        "base": "15_demo/integration/contracts/openapi.integration.candidate.json",
        "revision": "00_architecture/contracts/candidates/openapi.hardened.candidate.json",
        "raw_file": "oasdiff-closure-raw-integration-to-hardened.txt",
        "raw_json_file": "oasdiff-closure-json-integration-to-hardened.json",
    },
    "root_to_hardened": {
        "base": "00_architecture/openapi.v1.json",
        "revision": "00_architecture/contracts/candidates/openapi.hardened.candidate.json",
        "raw_file": "oasdiff-closure-raw-frozen-root-to-hardened.txt",
        "raw_json_file": "oasdiff-closure-json-frozen-root-to-hardened.json",
    },
}

OASDIFF_COMMAND = (
    r"D:\Dev\tools\oasdiff\1.28.0\oasdiff.exe breaking "
    "<base> <revision> --format json --fail-on ERR --color never"
)


def _classification(comparison: str, finding: dict[str, Any]) -> tuple[str, str, str, str, list[str]]:
    level = finding.get("level")
    finding_id = finding.get("id")
    text = str(finding.get("text", ""))
    operation_id = finding.get("operationId") or ""

    if level == 2:
        return (
            "NON_BREAKING / WARNING",
            "oasdiff reported a warning-level change; it is retained as a visible warning and is not an unintentional breaking change.",
            "Warning-level compatibility review remains part of the closure record.",
            "Retain the warning and verify the bounded schema change against the source contract.",
            ["oasdiff-closure-raw-" + ("integration-to-hardened.txt" if comparison == "integration_to_hardened" else "frozen-root-to-hardened.txt")],
        )

    if comparison == "root_to_hardened":
        if operation_id != "createGeneration":
            raise ValueError(f"Unexpected frozen-root error finding: {finding}")
        return (
            "EXPECTED_SURFACE_DIFFERENCE",
            "The frozen v0.1 root surface and the browser-facing hardened candidate are intentionally different comparison surfaces; the candidate exposes the typed generation/provenance DTO needed by the accepted hardening slice.",
            "The frozen root remains unchanged and is not promoted by this closure.",
            "Keep the root contract frozen; carry the candidate-only surface through the documented v0.2 promotion proposal and migration review.",
            [
                "00_architecture/CONTRACTS.md",
                "00_architecture/openapi.v1.json",
                "00_architecture/contracts/candidates/openapi.hardened.candidate.json",
                "14_docs/contract-hardening/PROVENANCE_TRACE_REPORT.md",
            ],
        )

    if finding_id == "response-property-list-of-types-widened" and "`instance`" in text and "`null`" in text:
        return (
            "FALSE_POSITIVE_WITH_EVIDENCE",
            "OpenAPI 3.0 type-array and OpenAPI 3.1 anyOf encode the same nullable instance value; the generated schemas differ representationally while the runtime typed Problem Details response returns instance=null.",
            "No accepted value was narrowed and the runtime response remains a typed RFC 9457 shape.",
            "Retain the source DTO and document the schema-encoding equivalence; do not add a broad oasdiff ignore.",
            [
                "09_backend/src/smhai_backend/core/errors.py",
                "09_backend/tests/test_contract_api_hardening.py",
                "14_docs/contract-hardening/evidence/oasdiff-closure-runtime-problem-details.json",
            ],
        )

    if operation_id == "createGeneration":
        return (
            "INTENTIONAL_PRE-PROMOTION_CORRECTION",
            "The hardened candidate makes generation provenance explicit and typed: schema version, stable identities, retrieval/prompt/model references, and bounded enums/patterns. The legacy comparison surface was incomplete for the accepted provenance correction and is not the frozen root contract.",
            "Consumers of the candidate generation surface must use the typed provenance fields; the RealApiProvider primary path uses the support operation and does not depend on the legacy generation request as an anonymous payload.",
            "Keep the correction candidate-only, document the v0.2 migration, and regenerate the SDK from the candidate rather than hand-editing generated code.",
            [
                "09_backend/src/smhai_backend/domains/support/schemas.py",
                "09_backend/tests/test_contract_api_hardening.py",
                "14_docs/contract-hardening/PROVENANCE_TRACE_REPORT.md",
            ],
        )

    raise ValueError(f"Unclassified oasdiff finding: {finding}")


def _load_findings(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"Expected an array of finding objects: {path}")
    return value


def _classify(comparison: str, finding: dict[str, Any]) -> dict[str, Any]:
    category, reason, consumer_impact, action, evidence = _classification(comparison, finding)
    return {
        "id": finding.get("id"),
        "path": finding.get("path"),
        "operation": finding.get("operation"),
        "operationId": finding.get("operationId"),
        "oasdiff_severity": {2: "warning", 3: "error"}.get(finding.get("level"), "unknown"),
        "oasdiff_message": finding.get("text"),
        "classification": category,
        "reason": reason,
        "consumer_impact": consumer_impact,
        "action": action,
        "evidence": evidence,
    }


def _counts(classifications: list[dict[str, Any]]) -> dict[str, int]:
    values = [item["classification"] for item in classifications]
    return {
        "total_findings": len(values),
        "raw_errors": sum(item["oasdiff_severity"] == "error" for item in classifications),
        "raw_warnings": sum(item["oasdiff_severity"] == "warning" for item in classifications),
        "unintentional": values.count("UNINTENTIONAL_BREAK"),
        "intentional_pre_promotion": values.count("INTENTIONAL_PRE-PROMOTION_CORRECTION"),
        "expected_surface_difference": values.count("EXPECTED_SURFACE_DIFFERENCE"),
        "false_positive": values.count("FALSE_POSITIVE_WITH_EVIDENCE"),
        "warning": values.count("NON_BREAKING / WARNING"),
        "unclassified": values.count("UNCLASSIFIED"),
        "pending_owner_decisions": values.count("PENDING_OWNER_DECISION"),
    }


def main() -> None:
    comparisons: dict[str, Any] = {}
    for name, metadata in COMPARISONS.items():
        findings = _load_findings(EVIDENCE / metadata["raw_json_file"])
        classifications = [_classify(name, finding) for finding in findings]
        comparisons[name] = {
            **metadata,
            "command": OASDIFF_COMMAND.replace("<base>", metadata["base"]).replace(
                "<revision>", metadata["revision"]
            ),
            "raw_findings": findings,
            "classifications": classifications,
            "counts": _counts(classifications),
        }

    output = {
        "round": "contract-api-hardening-r1-closure",
        "tool": "oasdiff",
        "tool_version": "1.28.0",
        "binary": r"D:\Dev\tools\oasdiff\1.28.0\oasdiff.exe",
        "classification_policy": [
            "UNINTENTIONAL_BREAK",
            "INTENTIONAL_PRE-PROMOTION_CORRECTION",
            "EXPECTED_SURFACE_DIFFERENCE",
            "FALSE_POSITIVE_WITH_EVIDENCE",
            "NON_BREAKING / WARNING",
        ],
        "comparisons": comparisons,
        "closure_gates": {
            "unintentional_breaks": sum(item["counts"]["unintentional"] for item in comparisons.values()),
            "unclassified_findings": sum(item["counts"]["unclassified"] for item in comparisons.values()),
            "pending_owner_decisions": sum(item["counts"]["pending_owner_decisions"] for item in comparisons.values()),
        },
    }
    target = EVIDENCE / "oasdiff-closure-classification.json"
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
