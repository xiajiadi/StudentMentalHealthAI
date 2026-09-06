"""Read-only compatibility check for the frozen root Contract v0.1.0."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


def run_root_contract_check(project_root: Path) -> dict[str, Any]:
    architecture = project_root / "00_architecture"
    schemas = architecture / "schemas"
    fixtures = architecture / "fixtures"
    mapping = {
        "assessment": ("assessment.v1.schema.json", "valid_assessment.json"),
        "config": ("config.v1.schema.json", "valid_config.json"),
        "generation_request": ("generation.v1.schema.json", "valid_generation_request.json"),
        "generation_result": ("generation.v1.schema.json", "valid_generation_result.json"),
        "knowledge_chunk": ("knowledge.v1.schema.json", "valid_knowledge_chunk.json"),
        "knowledge_document": ("knowledge.v1.schema.json", "valid_knowledge_document.json"),
        "logging": ("logging.v1.schema.json", "valid_log.json"),
    }
    checks: list[dict[str, Any]] = []
    for name, (schema_name, fixture_name) in mapping.items():
        schema = json.loads((schemas / schema_name).read_text(encoding="utf-8"))
        fixture = json.loads((fixtures / fixture_name).read_text(encoding="utf-8"))
        errors = sorted(
            Draft202012Validator(schema).iter_errors(fixture), key=lambda error: list(error.path)
        )
        checks.append(
            {
                "name": name,
                "schema": schema_name,
                "fixture": fixture_name,
                "status": "PASS" if not errors else "FAIL",
                "errors": [error.message for error in errors[:5]],
            }
        )
    contracts_text = (project_root / "CONTRACTS.md").read_text(encoding="utf-8")
    frozen_marker = "v0.1.0" in contracts_text and "FROZEN" in contracts_text
    return {
        "status": "PASS"
        if all(item["status"] == "PASS" for item in checks) and frozen_marker
        else "FAIL",
        "contract_marker": frozen_marker,
        "checks": checks,
        "modified": False,
    }


if __name__ == "__main__":
    result = run_root_contract_check(Path(__file__).resolve().parents[2])
    print(json.dumps(result, ensure_ascii=False, indent=2))
