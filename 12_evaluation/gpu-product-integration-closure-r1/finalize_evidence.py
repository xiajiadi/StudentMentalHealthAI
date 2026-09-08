"""Assemble final machine evidence from the closure run and regressions."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent


def load_json(name: str) -> Any:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def log_tail(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8", errors="replace")


def summary(name: str) -> dict[str, Any]:
    text = log_tail(name)
    last = text.strip().splitlines()[-1:] or [""]
    return {"status": "PASS" if "passed" in text.lower() and "failed" not in text.lower() else "REVIEW", "tail": last[0]}


def main() -> int:
    evaluation = load_json("gpu_product_integration_closure_evaluation.json")
    before = load_json("frozen_root_hashes_before.json")
    after = load_json("frozen_root_hashes_after.json")
    same = before["files"] == after["files"] and before["baseline_commit"] == after["baseline_commit"]

    evaluation["regressions"] = {
        "cat": summary("regression_cat.log"),
        "knowledge": summary("regression_knowledge.log"),
        "rag": summary("regression_rag.log"),
        "runtime": summary("regression_runtime.log"),
        "safety": summary("regression_safety.log"),
        "backend": summary("regression_backend.log"),
        "database": summary("regression_database.log"),
        "root_contract": {
            "status": "PASS" if "A-phase contract, Schema, and OpenAPI checks passed." in log_tail("regression_root.log") else "FAIL",
            "tail": (ROOT / "regression_root.log").read_text(encoding="utf-8", errors="replace").strip().splitlines()[-1],
        },
    }
    evaluation["frozen_root_integrity"] = {
        "status": "UNCHANGED" if same else "MODIFIED",
        "baseline_commit": after["baseline_commit"],
        "file_count": len(after["files"]),
        "before": "frozen_root_hashes_before.json",
        "after": "frozen_root_hashes_after.json",
    }
    evaluation["structured_output_diagnosis"] = [
        item for item in load_jsonl("ollama_structured_output_diagnosis.jsonl")
    ]
    cleanup = load_json_from_path(ROOT / "logs" / "cleanup.json")
    evaluation["cleanup"] = {
        "status": "PASS" if cleanup.get("processes_cleaned_by_explicit_pid") and cleanup.get("exit_code") == 0 else "REVIEW",
        "processes_cleaned_by_explicit_pid": cleanup.get("processes_cleaned_by_explicit_pid"),
        "database": cleanup.get("database"),
        "mysql_run_root": cleanup.get("mysql_run_root"),
        "ports": load_json("port_cleanup.json"),
    }
    evaluation["remaining_p0"] = [
        "GPI-25 normal product hard gate: 0/3 due reproducible RuntimeService INVALID_STRUCTURED_OUTPUT.",
        "GPI-29 citation round trip cannot pass without a generated normal response.",
    ]
    evaluation["remaining_p1"] = [
        "Resolve the exact accepted-publication structured-output blocker without weakening the frozen RAG boundary.",
        "Rerun the three normal product flows and citation round trip after the product-level fix.",
    ]
    evaluation["controller_review"] = {
        "required": True,
        "candidate_commit_created": False,
        "push": False,
        "merge": False,
        "tag": False,
    }
    evaluation["evidence_files"] = {
        "live_evaluation": "gpu_product_integration_closure_evaluation.json",
        "normal": "full_real_normal_flows.json",
        "crisis": "full_real_crisis_flows.json",
        "controlled_output": "controlled_output_safety.json",
        "safety_down": "safety_down_results.json",
        "fallback": "product_fallback_results.json",
        "calls": "call_count_matrix.json",
        "persistence": "persistence_evidence.json",
        "readiness": "service_readiness.json",
        "resources": "gpu_resource_ownership.json",
        "rag_boundary": "synthetic_rag_boundary.json",
        "diagnosis": "ollama_structured_output_diagnosis.jsonl",
        "port_cleanup": "port_cleanup.json",
    }
    (ROOT / "gpu_product_integration_closure_evaluation.json").write_text(
        json.dumps(evaluation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": evaluation["status"], "frozen_root": evaluation["frozen_root_integrity"]["status"], "blockers": len(evaluation["remaining_p0"])}, ensure_ascii=False))
    return 0


def load_json_from_path(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(name: str) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
        if line.strip():
            values.append(json.loads(line))
    return values


if __name__ == "__main__":
    raise SystemExit(main())
