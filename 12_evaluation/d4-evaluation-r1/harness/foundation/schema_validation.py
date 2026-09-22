"""Schema and semantic-authority validation for the D4 foundation.

This module is deliberately evaluation-local.  It validates the three D4
record schemas and the frozen D4E/D4SUP registry without importing product
modules, starting services, or repairing records.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError

from .hashing import sha256_hex

ROOT = Path(__file__).resolve().parents[2]
SPEC_DIR = ROOT / "spec"
SCHEMA_PATHS = {
    "scenario": SPEC_DIR / "d4_scenario.schema.json",
    "run_manifest": SPEC_DIR / "d4_run_manifest.schema.json",
    "machine_evidence": SPEC_DIR / "d4_machine_evidence.schema.json",
}
AUTHORITY_REGISTRY_PATH = SPEC_DIR / "d4_semantic_authority_registry.json"
FIXTURE_MODES = frozenset({"exact_d3_fixture", "legacy_compatibility_fixture"})
FIXTURE_MAPPINGS = {
    "exact_d3_fixture": "none",
    "legacy_compatibility_fixture": "D3-4_BACKEND_SYNTHETIC_COMPATIBILITY_V1",
}
EXPECTED_RESPONSE_CLASSES = frozenset(
    {"MUST_ANSWER", "SHOULD_ANSWER", "SHOULD_ABSTAIN", "MUST_ROUTE", "MUST_DENY"}
)
SEALED_SPLIT = "SEALED_EVAL"
_SECRET_FIELD_PATTERN = re.compile(
    r"(?:^|_)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|session[_-]?token|"
    r"password|passwd|secret|credential|private[_-]?key|cookie|env[_-]?dump|environment[_-]?dump)(?:$|_)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SchemaIssue:
    """One stable, serializable validation issue."""

    schema: str
    path: tuple[str, ...]
    message: str

    def __str__(self) -> str:
        location = ".".join(self.path) if self.path else "$"
        return f"{self.schema}:{location}: {self.message}"


class FoundationValidationError(ValueError):
    """Raised when a D4 foundation record is invalid."""

    def __init__(self, issues: Iterable[SchemaIssue | str]) -> None:
        self.issues = tuple(
            issue if isinstance(issue, SchemaIssue) else SchemaIssue("semantic", (), str(issue))
            for issue in issues
        )
        super().__init__("; ".join(str(issue) for issue in self.issues))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FoundationValidationError([f"cannot load JSON {path}: {exc}"]) from exc
    if not isinstance(value, dict):
        raise FoundationValidationError([f"JSON root must be an object: {path}"])
    return value


@lru_cache(maxsize=None)
def load_schema(schema_name: str) -> dict[str, Any]:
    """Load one of the foundation schemas by stable short name."""

    try:
        path = SCHEMA_PATHS[schema_name]
    except KeyError as exc:
        raise KeyError(f"unknown D4 schema {schema_name!r}") from exc
    return _read_json(path)


@lru_cache(maxsize=None)
def load_authority_registry() -> dict[str, Any]:
    """Load the controller-frozen D4E/D4SUP semantic registry."""

    return _read_json(AUTHORITY_REGISTRY_PATH)


@lru_cache(maxsize=None)
def _validator(schema_name: str) -> Draft202012Validator:
    schema = load_schema(schema_name)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise FoundationValidationError([f"invalid {schema_name} schema: {exc}"]) from exc
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _issue_from_error(schema_name: str, error: ValidationError) -> SchemaIssue:
    path = tuple(str(part) for part in error.absolute_path)
    return SchemaIssue(schema_name, path, error.message)


def schema_issues(document: Any, schema_name: str) -> list[SchemaIssue]:
    """Return deterministic schema errors sorted by instance path/message."""

    errors = [_issue_from_error(schema_name, error) for error in _validator(schema_name).iter_errors(document)]
    return sorted(errors, key=lambda issue: (issue.path, issue.message))


def _require_mapping(value: Any, label: str, issues: list[SchemaIssue]) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        issues.append(SchemaIssue("semantic", tuple(label.split(".")), "must be an object"))
        return None
    return value


def _fixture_mode_and_mapping(
    record: Mapping[str, Any],
    *,
    schema_name: str,
    issues: list[SchemaIssue],
) -> tuple[str | None, str | None]:
    if schema_name == "scenario":
        mode = record.get("fixture_mode")
        refs = record.get("fixture_refs")
    elif schema_name == "run_manifest":
        audit = _require_mapping(record.get("fixture_audit"), "fixture_audit", issues)
        mode = audit.get("fixture_mode") if audit else None
        refs = [audit] if audit else None
    else:
        binding = _require_mapping(record.get("assessment_binding"), "assessment_binding", issues)
        mode = binding.get("fixture_mode") if binding else None
        refs = [binding] if binding else None

    if mode not in FIXTURE_MODES:
        issues.append(SchemaIssue(schema_name, ("fixture_mode",), "unsupported fixture mode"))
        return None, None

    expected_mapping = FIXTURE_MAPPINGS[mode]
    if not isinstance(refs, list) or not refs:
        issues.append(SchemaIssue(schema_name, ("fixture_refs",), "at least one fixture binding is required"))
        return mode, expected_mapping
    for index, ref in enumerate(refs):
        if not isinstance(ref, Mapping):
            continue
        if ref.get("compatibility_mapping") != expected_mapping:
            issues.append(
                SchemaIssue(
                    schema_name,
                    ("fixture_refs", str(index), "compatibility_mapping"),
                    f"must equal {expected_mapping!r} for {mode}",
                )
            )
    if schema_name == "run_manifest":
        bootstrap = record.get("bootstrap_modes")
        if bootstrap != [mode]:
            issues.append(
                SchemaIssue(
                    schema_name,
                    ("bootstrap_modes",),
                    "must contain exactly fixture_audit.fixture_mode",
                )
            )
    return mode, expected_mapping


def _check_unique_field(
    records: Iterable[Mapping[str, Any]],
    field: str,
    *,
    label: str,
    issues: list[SchemaIssue],
) -> None:
    seen: dict[Any, int] = {}
    for index, record in enumerate(records):
        value = record.get(field)
        if value in seen:
            issues.append(
                SchemaIssue(
                    label,
                    (str(index), field),
                    f"duplicates {field} from record {seen[value]}: {value!r}",
                )
            )
        else:
            try:
                seen[value] = index
            except TypeError:
                issues.append(SchemaIssue(label, (str(index), field), "must be hashable"))


def _secret_field_issues(value: Any, *, schema_name: str, path: tuple[str, ...] = ()) -> list[SchemaIssue]:
    """Reject secret-shaped keys even inside intentionally bounded payloads."""

    issues: list[SchemaIssue] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_path = path + (key_text,)
            if _SECRET_FIELD_PATTERN.search(key_text):
                issues.append(
                    SchemaIssue(
                        schema_name,
                        child_path,
                        "secret-shaped fields are forbidden in evaluation evidence",
                    )
                )
            issues.extend(_secret_field_issues(child, schema_name=schema_name, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            issues.extend(_secret_field_issues(child, schema_name=schema_name, path=path + (str(index),)))
    return issues


def _semantic_issues(document: Mapping[str, Any], schema_name: str) -> list[SchemaIssue]:
    issues: list[SchemaIssue] = []
    _fixture_mode_and_mapping(document, schema_name=schema_name, issues=issues)

    if schema_name == "scenario":
        d4e_ids = document.get("d4e_ids")
        if not isinstance(d4e_ids, list) or not d4e_ids:
            issues.append(
                SchemaIssue(
                    schema_name,
                    ("d4e_ids",),
                    "every formal scenario requires at least one D4E authority ID",
                )
            )
        turns = document.get("turns")
        if isinstance(turns, list):
            _check_unique_field(turns, "turn_id", label=schema_name, issues=issues)
        refs = document.get("fixture_refs")
        if isinstance(refs, list):
            seen_refs: set[tuple[Any, Any]] = set()
            for index, ref in enumerate(refs):
                if not isinstance(ref, Mapping):
                    continue
                identity = (ref.get("path"), ref.get("sha256"))
                if identity in seen_refs:
                    issues.append(
                        SchemaIssue(
                            schema_name,
                            ("fixture_refs", str(index)),
                            "fixture path and sha256 must be unique",
                        )
                    )
                seen_refs.add(identity)

    if schema_name == "machine_evidence":
        d4e_ids = document.get("d4e_ids")
        if not isinstance(d4e_ids, list) or not d4e_ids:
            issues.append(SchemaIssue(schema_name, ("d4e_ids",), "at least one D4E authority ID is required"))
        if "response_class" in document:
            issues.append(
                SchemaIssue(
                    schema_name,
                    ("response_class",),
                    "deprecated mixed expected/observed field; use expected_response_class, observed_response_class, and observed_outcome",
                )
            )
        expected = document.get("expected_response_class")
        if expected not in EXPECTED_RESPONSE_CLASSES:
            issues.append(SchemaIssue(schema_name, ("expected_response_class",), "must be an expected response class"))
        review = document.get("human_review")
        if isinstance(review, Mapping) and review.get("required") is True and document.get("run_mode") == "SEALED_FINAL":
            if review.get("status") != "COMPLETE":
                issues.append(SchemaIssue(schema_name, ("human_review", "status"), "SEALED_FINAL required review must be COMPLETE"))
            if review.get("unresolved_decision") is not False:
                issues.append(SchemaIssue(schema_name, ("human_review", "unresolved_decision"), "SEALED_FINAL required review cannot remain unresolved"))

    if schema_name == "run_manifest":
        closure = document.get("human_review_closure")
        if document.get("run_mode") == "SEALED_FINAL" and isinstance(closure, Mapping):
            closure_complete = (
                closure.get("status") == "COMPLETE"
                and closure.get("mandatory_complete") is True
            )
            closure_not_required = (
                closure.get("status") == "NOT_REQUIRED"
                and closure.get("mandatory_complete") is False
            )
            if not (closure_complete or closure_not_required):
                issues.append(
                    SchemaIssue(
                        schema_name,
                        ("human_review_closure",),
                        "SEALED_FINAL requires COMPLETE or NOT_REQUIRED review closure",
                    )
                )
            if closure.get("unresolved_count") != 0:
                issues.append(SchemaIssue(schema_name, ("human_review_closure", "unresolved_count"), "SEALED_FINAL cannot contain unresolved required review"))

    return issues


def validate_document(document: Any, schema_name: str) -> Mapping[str, Any]:
    """Validate schema and semantic invariants; return the original mapping."""

    if not isinstance(document, Mapping):
        raise FoundationValidationError([SchemaIssue(schema_name, (), "document must be an object")])
    issues = schema_issues(document, schema_name)
    if not issues:
        issues.extend(_semantic_issues(document, schema_name))
    if schema_name in {"machine_evidence", "run_manifest"}:
        issues.extend(_secret_field_issues(document, schema_name=schema_name))
    if issues:
        raise FoundationValidationError(issues)
    return document


def validate_scenario(document: Mapping[str, Any]) -> Mapping[str, Any]:
    return validate_document(document, "scenario")


def validate_run_manifest(document: Mapping[str, Any]) -> Mapping[str, Any]:
    return validate_document(document, "run_manifest")


def validate_machine_evidence(document: Mapping[str, Any]) -> Mapping[str, Any]:
    return validate_document(document, "machine_evidence")


def validate_scenario_collection(records: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Validate scenarios and reject duplicate case/turn/fixture identities."""

    materialized = list(records)
    for record in materialized:
        validate_scenario(record)
    issues: list[SchemaIssue] = []
    _check_unique_field(materialized, "case_id", label="scenario_collection", issues=issues)
    modes = {record.get("fixture_mode") for record in materialized}
    if not modes.issubset(FIXTURE_MODES):
        issues.append(SchemaIssue("scenario_collection", ("fixture_mode",), "unsupported fixture mode"))
    if len(modes) > 1:
        issues.append(SchemaIssue("scenario_collection", ("fixture_mode",), "fixture modes cannot be pooled in one run"))
    if issues:
        raise FoundationValidationError(issues)
    return materialized


def validate_authority_registry(registry: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
    """Require exactly D4E-01..60 and D4SUP-01..20 with meanings."""

    value = registry if registry is not None else load_authority_registry()
    issues: list[SchemaIssue] = []
    source = value.get("authority_source") if isinstance(value, Mapping) else None
    if not isinstance(source, Mapping):
        issues.append(SchemaIssue("authority_registry", ("authority_source",), "must be an object"))
    else:
        if source.get("path") != "14_docs/project-controller/D4_EVALUATION_TECHNICAL_DECISION_V1.md":
            issues.append(SchemaIssue("authority_registry", ("authority_source", "path"), "must bind the frozen D4 technical decision"))
        if source.get("status") != "FROZEN FOR BOUNDED IMPLEMENTATION":
            issues.append(SchemaIssue("authority_registry", ("authority_source", "status"), "must record the frozen decision status"))
        if not isinstance(source.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", source["sha256"]):
            issues.append(SchemaIssue("authority_registry", ("authority_source", "sha256"), "must be a lowercase SHA-256"))
        else:
            source_path = Path(__file__).resolve().parents[4] / str(source["path"])
            if not source_path.is_file():
                issues.append(SchemaIssue("authority_registry", ("authority_source", "path"), "bound technical decision file does not exist"))
            elif sha256_hex(source_path.read_bytes()) != source["sha256"]:
                issues.append(SchemaIssue("authority_registry", ("authority_source", "sha256"), "does not match the bound technical decision file"))
    expected_d4e = [f"D4E-{index:02d}" for index in range(1, 61)]
    expected_d4sup = [f"D4SUP-{index:02d}" for index in range(1, 21)]
    for group, expected in (("d4e", expected_d4e), ("d4sup", expected_d4sup)):
        entries = value.get(group) if isinstance(value, Mapping) else None
        if not isinstance(entries, list):
            issues.append(SchemaIssue("authority_registry", (group,), "must be an array"))
            continue
        ids = [entry.get("id") if isinstance(entry, Mapping) else None for entry in entries]
        if ids != expected:
            issues.append(SchemaIssue("authority_registry", (group,), f"IDs must be exactly {expected[0]}..{expected[-1]} in order"))
        for index, entry in enumerate(entries):
            if not isinstance(entry, Mapping) or not isinstance(entry.get("semantic_meaning"), str) or not entry["semantic_meaning"].strip():
                issues.append(SchemaIssue("authority_registry", (group, str(index), "semantic_meaning"), "must be non-empty"))
    if issues:
        raise FoundationValidationError(issues)
    return value


def validate_records(
    *,
    scenarios: Iterable[Mapping[str, Any]] = (),
    machine_evidence: Iterable[Mapping[str, Any]] = (),
) -> dict[str, int]:
    """Validate a foundation batch and return counts only."""

    validate_authority_registry()
    scenario_records = validate_scenario_collection(list(scenarios))
    evidence_records = list(machine_evidence)
    for evidence in evidence_records:
        validate_machine_evidence(evidence)
    evidence_issues: list[SchemaIssue] = []
    _check_unique_field(
        evidence_records,
        "case_id",
        label="machine_evidence_collection",
        issues=evidence_issues,
    )
    evidence_modes: set[Any] = set()
    for index, evidence in enumerate(evidence_records):
        binding = evidence.get("assessment_binding")
        if isinstance(binding, Mapping):
            evidence_modes.add(binding.get("fixture_mode"))
        else:
            evidence_issues.append(
                SchemaIssue(
                    "machine_evidence_collection",
                    (str(index), "assessment_binding"),
                    "must be an object",
                )
            )
    if not evidence_modes.issubset(FIXTURE_MODES):
        evidence_issues.append(
            SchemaIssue(
                "machine_evidence_collection",
                ("assessment_binding", "fixture_mode"),
                "unsupported fixture mode",
            )
        )
    if len(evidence_modes) > 1:
        evidence_issues.append(
            SchemaIssue(
                "machine_evidence_collection",
                ("assessment_binding", "fixture_mode"),
                "fixture modes cannot be pooled in one run",
            )
        )
    if evidence_issues:
        raise FoundationValidationError(evidence_issues)
    return {"scenarios": len(scenario_records), "machine_evidence": len(evidence_records)}


# Short aliases used by focused tests and scripts.
validate_schema_document = validate_document
check_schema = schema_issues
