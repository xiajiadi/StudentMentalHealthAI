"""Execute the repository's frozen knowledge.v1 JSON Schema."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema


class ContractValidator:
    def __init__(self, schema_root: Path) -> None:
        root = Path(schema_root)
        candidates = (
            root / "schemas" / "knowledge.v1.schema.json",
            root / "00_architecture" / "schemas" / "knowledge.v1.schema.json",
        )
        schema_path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
        with schema_path.open("r", encoding="utf-8") as handle:
            self.schema = json.load(handle)
        validator_cls = jsonschema.validators.validator_for(self.schema)
        validator_cls.check_schema(self.schema)
        self.validator = validator_cls(self.schema)

    def errors(self, value: dict[str, Any]) -> list[str]:
        return [error.message for error in self.validator.iter_errors(value)]

    def validate(self, value: dict[str, Any]) -> None:
        errors = self.errors(value)
        if errors:
            raise ValueError("knowledge.v1 validation failed: " + "; ".join(errors))
