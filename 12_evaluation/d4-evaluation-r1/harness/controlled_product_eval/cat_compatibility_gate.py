"""Fail-closed evidence for the approved D4-3B CAT-to-D3 compatibility path."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .environment_profiles import GIT_EXECUTABLE
from .evaluation_compatibility import (
    APPROVAL_REFERENCE,
    FIXTURE_DOCUMENT,
    FIXTURE_ID,
    FIXTURE_VERSION,
    POLICY_ID,
    SOURCE_IDENTITY,
    TARGET_IDENTITY,
    canonical_json_bytes,
)

GATE_SCHEMA_VERSION = "d4-cat-d3-compatibility-gate.v1"
ITEM_BANK_RELATIVE_PATH = "01_cat-engine/fixtures/synthetic_item_bank.v1.json"
MAPPER_RELATIVE_PATH = "01_cat-engine/src/cat_engine/service/assessment_mapper.py"
EXPECTED_ITEM_BANK_GIT_BLOB = "429b0944ba73f811b0bdde580d1266e42c82b524"
EXPECTED_MAPPER_GIT_BLOB = "a0beaefdfbb569cf984453b16d07ee432d241fdc"
EXPECTED_DIMENSIONS = ["demo_trait"]
EXPECTED_ADAPTER = {
    "source_adapter": "cat_engine",
    "adapter_version": "0.1.0",
    "cat_engine_version": "0.1.0",
    "item_bank_version": "demo.v1",
}
EXPECTED_CAT_PROVIDER_VERSION = "adaptivetesting-1.2.1"
_RUN_ID_RE = re.compile(r"^D4RUN-[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_BLOB_RE = re.compile(r"^[0-9a-f]{40}$")


class CatCompatibilityGateError(ValueError):
    """A required CAT provenance or fixture-activation proof did not pass."""

    def __init__(self, issue_codes: Iterable[str]) -> None:
        self.issue_codes = tuple(sorted(set(issue_codes)))
        super().__init__("CAT_D3_COMPATIBILITY_GATE_FAILED")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _git_blob(repo_root: Path, commit: str, relative_path: str) -> str | None:
    if commit != "HEAD" and not _GIT_BLOB_RE.fullmatch(commit):
        return None
    try:
        result = subprocess.run(
            [str(GIT_EXECUTABLE), "rev-parse", f"{commit}:{relative_path}"],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10.0,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip().lower()
    return value if _GIT_BLOB_RE.fullmatch(value) else None


def _read_activation(path: Path) -> tuple[Mapping[str, Any] | None, str | None]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, None
    if not isinstance(value, Mapping):
        return None, None
    return value, _sha256_bytes(raw)


def build_cat_d3_compatibility_gate(
    *,
    run_id: str,
    completed_assessment: Mapping[str, Any] | None,
    fixture_activation_path: str | Path,
    attempt_root: str | Path,
    backend_process_pids: Iterable[int],
    cat_profile_evidence: Mapping[str, Any] | None,
    cat_health: Mapping[str, Any] | None,
    repo_root: str | Path,
    accepted_baseline_commit: str,
    synthetic_subject_ids: Iterable[str],
) -> dict[str, Any]:
    """Create a bounded gate record from the completed assessment and live setup."""

    root = Path(repo_root).resolve()
    attempt = Path(attempt_root).resolve()
    activation_path = Path(fixture_activation_path).resolve()
    issue_codes: set[str] = set()
    if not _RUN_ID_RE.fullmatch(run_id):
        issue_codes.add("RUN_ID_INVALID")
    try:
        activation_path.relative_to(attempt)
    except ValueError:
        issue_codes.add("FIXTURE_ACTIVATION_PATH_OUTSIDE_ATTEMPT")
    activation, activation_sha256 = _read_activation(activation_path)
    if activation is None or activation_sha256 is None:
        issue_codes.add("FIXTURE_ACTIVATION_EVIDENCE_MISSING_OR_INVALID")
        activation = {}

    fixture_bytes = canonical_json_bytes(FIXTURE_DOCUMENT)
    fixture_sha256 = _sha256_bytes(fixture_bytes)
    fixture_file = activation_path.with_name("approved-cat-d3-compatibility-fixture.json")
    try:
        fixture_raw = fixture_file.read_bytes()
    except OSError:
        fixture_raw = b""
        issue_codes.add("APPROVED_FIXTURE_FILE_MISSING")
    if fixture_raw != fixture_bytes:
        issue_codes.add("APPROVED_FIXTURE_FILE_MISMATCH")

    try:
        backend_pids = {int(pid) for pid in backend_process_pids if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0}
    except (TypeError, ValueError):
        backend_pids = set()
    process_pid = activation.get("process_pid")
    activation_valid = (
        activation.get("schema_version") == "d4-3b-runtime-fixture-activation.v1"
        and activation.get("run_id") == run_id
        and activation.get("fixture_id") == FIXTURE_ID
        and activation.get("fixture_version") == FIXTURE_VERSION
        and activation.get("fixture_instantiated") is True
        and activation.get("fixture_injected") is True
        and activation.get("approved") is True
        and activation.get("approval_reference") == APPROVAL_REFERENCE
        and activation.get("source_identity") == SOURCE_IDENTITY
        and activation.get("target_identity") == TARGET_IDENTITY
        and activation.get("policy_id") == POLICY_ID
        and activation.get("dimension_map") == {}
        and activation.get("fixture_sha256") == fixture_sha256
        and activation.get("fixture_canonical_json") == FIXTURE_DOCUMENT
        and activation.get("fixture_instance_count") == 1
        and activation.get("runtime_only") is True
        and activation.get("canonical_product_default_changed") is False
        and isinstance(process_pid, int)
        and not isinstance(process_pid, bool)
        and process_pid in backend_pids
    )
    if not activation_valid:
        issue_codes.add("FIXTURE_NOT_ACTIVE_IN_MANAGED_BACKEND")

    profile = _mapping(cat_profile_evidence) or {}
    health = _mapping(cat_health) or {}
    item_bank_path = root / ITEM_BANK_RELATIVE_PATH
    mapper_path = root / MAPPER_RELATIVE_PATH
    try:
        item_bank_raw = item_bank_path.read_bytes()
        item_bank = json.loads(item_bank_raw.decode("utf-8"))
        item_bank_file_sha256 = _sha256_bytes(item_bank_raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        item_bank = {}
        item_bank_file_sha256 = None
        issue_codes.add("CAT_ITEM_BANK_SOURCE_UNAVAILABLE")
    try:
        mapper_file_sha256 = _sha256_bytes(mapper_path.read_bytes())
    except OSError:
        mapper_file_sha256 = None
        issue_codes.add("CAT_MAPPER_SOURCE_UNAVAILABLE")

    item_bank_accepted_blob = _git_blob(root, accepted_baseline_commit, ITEM_BANK_RELATIVE_PATH)
    item_bank_current_blob = _git_blob(root, "HEAD", ITEM_BANK_RELATIVE_PATH)
    mapper_accepted_blob = _git_blob(root, accepted_baseline_commit, MAPPER_RELATIVE_PATH)
    mapper_current_blob = _git_blob(root, "HEAD", MAPPER_RELATIVE_PATH)
    if item_bank_accepted_blob != EXPECTED_ITEM_BANK_GIT_BLOB or item_bank_current_blob != EXPECTED_ITEM_BANK_GIT_BLOB:
        issue_codes.add("CAT_ITEM_BANK_GIT_BLOB_MISMATCH")
    if mapper_accepted_blob != EXPECTED_MAPPER_GIT_BLOB or mapper_current_blob != EXPECTED_MAPPER_GIT_BLOB:
        issue_codes.add("CAT_MAPPER_GIT_BLOB_MISMATCH")

    bank_dimensions = item_bank.get("dimensions") if isinstance(item_bank, Mapping) else None
    dimensions_valid = (
        isinstance(bank_dimensions, list)
        and all(isinstance(dimension, str) for dimension in bank_dimensions)
    )
    if not dimensions_valid:
        issue_codes.add("CAT_ITEM_BANK_DIMENSIONS_INVALID")
    if (
        not isinstance(item_bank, Mapping)
        or profile.get("instrument_id") != SOURCE_IDENTITY["instrument_id"]
        or profile.get("instrument_version") != SOURCE_IDENTITY["instrument_version"]
        or profile.get("item_bank_id") != item_bank.get("item_bank_id")
        or profile.get("item_bank_version") != SOURCE_IDENTITY["instrument_version"]
        or profile.get("item_bank_sha256") != item_bank_file_sha256
        or item_bank_file_sha256 != profile.get("item_bank_sha256")
        or item_bank.get("instrument_id") != SOURCE_IDENTITY["instrument_id"]
        or item_bank.get("version") != SOURCE_IDENTITY["instrument_version"]
        or item_bank.get("target_population") != SOURCE_IDENTITY["population_scope"]
        or not dimensions_valid
        or sorted(bank_dimensions) != EXPECTED_DIMENSIONS
    ):
        issue_codes.add("CAT_PROFILE_SOURCE_IDENTITY_MISMATCH")
    bank_item_id = item_bank.get("item_bank_id") if isinstance(item_bank, Mapping) else None
    if (
        health.get("status") != "READY"
        or health.get("service") != "cat"
        or health.get("provider") != "adaptivetesting"
        or health.get("provider_version") != EXPECTED_CAT_PROVIDER_VERSION
        or health.get("item_bank_id") != bank_item_id
        or health.get("item_bank_version") != SOURCE_IDENTITY["instrument_version"]
        or health.get("synthetic_fixture_only") is not True
    ):
        issue_codes.add("CAT_LIVE_HEALTH_IDENTITY_MISMATCH")

    assessment = _mapping(completed_assessment) or {}
    instrument = _mapping(assessment.get("instrument")) or {}
    provenance = _mapping(assessment.get("provenance")) or {}
    dimensions = _mapping(assessment.get("dimensions")) or {}
    dimension_ids = sorted(str(key) for key in dimensions) if isinstance(dimensions, Mapping) else []
    source_identity = {
        "instrument_id": instrument.get("instrument_id"),
        "instrument_version": instrument.get("version"),
        "population_scope": assessment.get("population_scope"),
    }
    actual_provenance = {
        key: provenance.get(key)
        for key in (
            "source_adapter",
            "adapter_version",
            "cat_engine_version",
            "item_bank_version",
        )
    }
    assessment_id = assessment.get("assessment_id")
    subject_id = assessment.get("subject_id")
    try:
        allowed_subjects = {value for value in synthetic_subject_ids if isinstance(value, str)}
    except TypeError:
        allowed_subjects = set()
        issue_codes.add("SYNTHETIC_SUBJECT_ALLOWLIST_INVALID")
    if (
        not isinstance(assessment_id, str)
        or not assessment_id.startswith("ASSESS_")
        or assessment.get("status") != "completed"
        or source_identity != SOURCE_IDENTITY
        or actual_provenance != EXPECTED_ADAPTER
        or dimension_ids != EXPECTED_DIMENSIONS
        or not isinstance(subject_id, str)
        or subject_id not in allowed_subjects
    ):
        issue_codes.add("COMPLETED_ASSESSMENT_PROVENANCE_MISMATCH")

    activation_rel = None
    try:
        activation_rel = activation_path.relative_to(attempt).as_posix()
    except ValueError:
        pass
    gate = {
        "schema_version": GATE_SCHEMA_VERSION,
        "run_id": run_id,
        "status": "PASS" if not issue_codes else "FAIL",
        "captured_at": _now(),
        "fixture": {
            "fixture_id": FIXTURE_ID,
            "fixture_version": FIXTURE_VERSION,
            "fixture_instantiated": activation_valid,
            "fixture_injected": activation_valid,
            "fixture_approved": activation.get("approved") is True,
            "source_identity": dict(SOURCE_IDENTITY),
            "target_identity": dict(TARGET_IDENTITY),
            "policy_id": POLICY_ID,
            "approval_reference": APPROVAL_REFERENCE,
            "dimension_map": {},
            "fixture_sha256": fixture_sha256,
        },
        "activation": {
            "path": activation_rel,
            "sha256": activation_sha256,
            "run_id": activation.get("run_id"),
            "backend_pid": process_pid if isinstance(process_pid, int) else None,
            "backend_process_tree_match": bool(isinstance(process_pid, int) and process_pid in backend_pids),
        },
        "source_provenance": {
            "assessment_id_sha256": _sha256_bytes(assessment_id.encode("utf-8"))
            if isinstance(assessment_id, str)
            else None,
            "source_identity": source_identity,
            **actual_provenance,
            "dimensions": dimension_ids,
            "assessment_status": assessment.get("status"),
            "item_bank_git_blob": item_bank_accepted_blob,
            "mapper_git_blob": mapper_accepted_blob,
            "item_bank_file_sha256": item_bank_file_sha256,
            "mapper_file_sha256": mapper_file_sha256,
            "cat_profile_sha256": _sha256_bytes(
                json.dumps(dict(profile), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ),
            "cat_provider_version": health.get("provider_version"),
            "synthetic_demo_only": bool(isinstance(subject_id, str) and subject_id in allowed_subjects),
        },
        "issues": sorted(issue_codes),
    }
    return gate


def validate_cat_d3_compatibility_gate(
    value: Mapping[str, Any], *, run_id: str
) -> None:
    """Reject every missing, stale, or non-approved gate before manifest freeze."""

    fixture = _mapping(value.get("fixture")) or {}
    activation = _mapping(value.get("activation")) or {}
    provenance = _mapping(value.get("source_provenance")) or {}
    expected_fixture_sha256 = _sha256_bytes(canonical_json_bytes(FIXTURE_DOCUMENT))
    if (
        value.get("schema_version") != GATE_SCHEMA_VERSION
        or value.get("run_id") != run_id
        or not _RUN_ID_RE.fullmatch(run_id)
        or value.get("status") != "PASS"
        or value.get("issues") != []
        or fixture.get("fixture_id") != FIXTURE_ID
        or fixture.get("fixture_version") != FIXTURE_VERSION
        or fixture.get("fixture_instantiated") is not True
        or fixture.get("fixture_injected") is not True
        or fixture.get("fixture_approved") is not True
        or fixture.get("source_identity") != SOURCE_IDENTITY
        or fixture.get("target_identity") != TARGET_IDENTITY
        or fixture.get("policy_id") != POLICY_ID
        or fixture.get("approval_reference") != APPROVAL_REFERENCE
        or fixture.get("dimension_map") != {}
        or fixture.get("fixture_sha256") != expected_fixture_sha256
        or activation.get("run_id") != run_id
        or activation.get("backend_process_tree_match") is not True
        or not isinstance(activation.get("backend_pid"), int)
        or not isinstance(activation.get("path"), str)
        or not isinstance(activation.get("sha256"), str)
        or not _SHA256_RE.fullmatch(activation.get("sha256", ""))
        or provenance.get("source_identity") != SOURCE_IDENTITY
        or any(provenance.get(key) != expected for key, expected in EXPECTED_ADAPTER.items())
        or provenance.get("dimensions") != EXPECTED_DIMENSIONS
        or provenance.get("assessment_status") != "completed"
        or provenance.get("item_bank_git_blob") != EXPECTED_ITEM_BANK_GIT_BLOB
        or provenance.get("mapper_git_blob") != EXPECTED_MAPPER_GIT_BLOB
        or provenance.get("synthetic_demo_only") is not True
        or not _SHA256_RE.fullmatch(str(provenance.get("assessment_id_sha256", "")))
        or not _SHA256_RE.fullmatch(str(provenance.get("item_bank_file_sha256", "")))
        or not _SHA256_RE.fullmatch(str(provenance.get("mapper_file_sha256", "")))
        or not _SHA256_RE.fullmatch(str(provenance.get("cat_profile_sha256", "")))
        or provenance.get("cat_provider_version") != EXPECTED_CAT_PROVIDER_VERSION
    ):
        raise CatCompatibilityGateError(value.get("issues", ()))
