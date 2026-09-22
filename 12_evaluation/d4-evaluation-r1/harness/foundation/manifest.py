"""D4 machine run manifest construction and immutable persistence."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .errors import ManifestError
from .fixtures import (
    FIXTURE_MODES,
    compatibility_mapping_for,
    enforce_fixture_mode_isolation,
)
from .hashing import canonical_dataset_hash, canonical_json, canonical_sha256, validate_sha256_hex
from .paths import (
    safe_artifact_path,
    validate_artifact_paths,
    validate_result_path,
)
from .run_ids import create_run_id, validate_run_id
from .sealed import freeze_sealed_dataset
from .splits import DATASET_SPLITS, SPLIT_DIRECTORY_NAMES, enforce_split_integrity, load_dataset_records

RUN_MODES = frozenset({"FAST_REGRESSION", "FULL_ENGINEERING", "SEALED_FINAL"})
ZERO_SHA256 = "0" * 64
ZERO_GIT_COMMIT = "0" * 40
GIT_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SEMVER_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$")
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
LOOPBACK_PATTERN = re.compile(
    r"^(https?://)?(127\.0\.0\.1|localhost|\[?::1\]?)(:[0-9]+)?(/.*)?$"
)

MANIFEST_REQUIRED_FIELDS = (
    "schema_version",
    "run_id",
    "run_mode",
    "timestamp",
    "git_commit",
    "accepted_tags",
    "dataset_versions",
    "dataset_hashes",
    "sealed_hash",
    "promptfoo_version",
    "promptfoo_config_hash",
    "provider_identities",
    "runtime",
    "template_ids_hashes",
    "policy_ids_hashes",
    "rag_corpus_identity",
    "seed",
    "repeat_settings",
    "hardware",
    "network_policy",
    "test_groups",
    "result_paths",
    "network_observation",
    "bootstrap_modes",
    "real_student_data",
    "cloud_fallback",
    "retry_policy",
    "human_review_closure",
    "node_runtime",
    "lock_hash",
    "wrapper_identity",
    "endpoint_inventory",
    "fixture_audit",
    "sealed_evaluation",
)


def _timestamp_text(timestamp: datetime | str | None) -> str:
    if timestamp is None:
        value = datetime.now(timezone.utc).replace(microsecond=0)
    elif isinstance(timestamp, str):
        text = timestamp.strip()
        if not text:
            raise ManifestError("timestamp must not be empty")
        return text
    elif isinstance(timestamp, datetime):
        if timestamp.tzinfo is None:
            raise ManifestError("timestamp must be timezone-aware")
        value = timestamp.astimezone(timezone.utc).replace(microsecond=0)
    else:
        raise ManifestError("timestamp must be datetime, ISO text, or None")
    return value.isoformat().replace("+00:00", "Z")


def _hash_or_none(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ManifestError(f"{field} must be a SHA-256 string or null")
    if value.startswith("sha256:"):
        raise ManifestError(f"{field} must contain bare lowercase hexadecimal")
    try:
        return validate_sha256_hex(value, allow_tag=True)
    except Exception as exc:
        raise ManifestError(f"{field} is invalid: {exc}") from exc


def _records_by_split(
    *,
    datasets_root: str | Path | None,
    dataset_records: Mapping[str, Iterable[Mapping[str, Any]]] | None,
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {split: [] for split in DATASET_SPLITS}
    if dataset_records is not None:
        for split, values in dataset_records.items():
            normalized_split = str(split).upper()
            if normalized_split == "SEALED":
                normalized_split = "SEALED_EVAL"
            if normalized_split not in DATASET_SPLITS:
                raise ManifestError(f"invalid dataset split: {split}")
            result[normalized_split] = [dict(value) for value in values]
    if datasets_root is not None:
        root = Path(datasets_root)
        for split, dirname in SPLIT_DIRECTORY_NAMES.items():
            split_path = safe_artifact_path(root, dirname)
            if split_path.exists():
                result[split] = load_dataset_records(split_path, expected_split=split)
    return result


def _default_manifest(
    *,
    run_id: str,
    run_mode: str,
    timestamp: str,
    git_commit: str,
    accepted_tags: Iterable[str],
    fixture_mode: str,
) -> dict[str, Any]:
    mapping = compatibility_mapping_for(fixture_mode)
    return {
        "schema_version": "d4-run-v1",
        "run_id": run_id,
        "run_mode": run_mode,
        "timestamp": timestamp,
        "git_commit": git_commit,
        "accepted_tags": list(accepted_tags),
        "dataset_versions": {
            "dev": "d4-dev-v1",
            "regression": "d4-regression-v1",
            "sealed": "d4-sealed-v1",
        },
        "dataset_hashes": {"dev": ZERO_SHA256, "regression": ZERO_SHA256, "sealed": ZERO_SHA256},
        "sealed_hash": None,
        "promptfoo_version": None,
        "promptfoo_config_hash": None,
        "provider_identities": {"target": "unconfigured", "attacker": None, "grader": None},
        "runtime": {"model": None, "digest": None},
        "template_ids_hashes": {},
        "policy_ids_hashes": {},
        "rag_corpus_identity": None,
        "seed": None,
        "repeat_settings": {"repeats": 1, "concurrency": 1},
        "hardware": {},
        "network_policy": "loopback_only",
        "test_groups": [],
        "result_paths": [],
        "network_observation": "NOT_RUN",
        "bootstrap_modes": [fixture_mode],
        "real_student_data": False,
        "cloud_fallback": False,
        "retry_policy": {"max_retries": 0, "non_idempotent_post_retries": 0},
        "human_review_closure": {
            "status": "NOT_RUN",
            "mandatory_complete": False,
            "unresolved_count": 0,
            "disagreement_preserved": True,
        },
        "node_runtime": None,
        "lock_hash": None,
        "wrapper_identity": None,
        "endpoint_inventory": [],
        "fixture_audit": {
            "fixture_mode": fixture_mode,
            "source_identity": "CURRENT_SYNTHETIC_GRM",
            "target_identity": "SYNTHETIC_STUDENT_DEMO",
            "compatibility_mapping": mapping,
            "separation_rule": "one_mode_per_run",
        },
        "sealed_evaluation": {
            "status": "NOT_RUN",
            "case_count": None,
            "scenario_family_distribution": {},
            "creation_provenance": "not_run",
            "approval_ref": None,
        },
    }


def build_run_manifest(
    *,
    run_id: str | None = None,
    run_mode: str = "FAST_REGRESSION",
    timestamp: datetime | str | None = None,
    git_commit: str = ZERO_GIT_COMMIT,
    accepted_tags: Iterable[str] = (),
    fixture_mode: str = "exact_d3_fixture",
    datasets_root: str | Path | None = None,
    dataset_records: Mapping[str, Iterable[Mapping[str, Any]]] | None = None,
    sealed_records: Iterable[Mapping[str, Any]] | None = None,
    artifact_root: str | Path | None = None,
    result_paths: Iterable[str | Path] = (),
    **overrides: Any,
) -> dict[str, Any]:
    """Build one schema-shaped D4 manifest with deterministic defaults.

    The function is intentionally strict about formal ``SEALED_FINAL`` input:
    caller must provide the pinned provider/runtime/network/review/approval
    fields rather than receiving a plausible-looking placeholder manifest.
    ``FAST_REGRESSION`` and ``FULL_ENGINEERING`` may retain ``NOT_RUN`` values
    for those formal-only fields.
    """

    if run_mode not in RUN_MODES:
        raise ManifestError(f"invalid run_mode: {run_mode}")
    if fixture_mode not in FIXTURE_MODES:
        raise ManifestError(f"invalid fixture_mode: {fixture_mode}")
    actual_run_id = run_id or create_run_id(
        timestamp=timestamp if isinstance(timestamp, datetime) else None
    )
    try:
        validate_run_id(actual_run_id)
    except Exception as exc:
        raise ManifestError(str(exc)) from exc
    if not isinstance(git_commit, str) or not GIT_COMMIT_PATTERN.fullmatch(git_commit):
        raise ManifestError("git_commit must be 40 lowercase hexadecimal characters")
    accepted = list(accepted_tags)
    if any(
        not isinstance(tag, str)
        or not tag.strip()
        or not IDENTIFIER_PATTERN.fullmatch(tag)
        for tag in accepted
    ):
        raise ManifestError("accepted_tags must contain non-empty strings")
    manifest = _default_manifest(
        run_id=actual_run_id,
        run_mode=run_mode,
        timestamp=_timestamp_text(timestamp),
        git_commit=git_commit,
        accepted_tags=accepted,
        fixture_mode=fixture_mode,
    )

    records_by_split = _records_by_split(
        datasets_root=datasets_root,
        dataset_records=dataset_records,
    )
    all_records = [record for values in records_by_split.values() for record in values]
    if all_records:
        try:
            summary = enforce_split_integrity(all_records)
        except Exception as exc:
            raise ManifestError(f"dataset integrity failed: {exc}") from exc
        if summary["fixture_mode"] not in (None, fixture_mode):
            raise ManifestError(
                f"dataset fixture mode {summary['fixture_mode']} conflicts with {fixture_mode}"
            )
        manifest["dataset_hashes"] = {
            split.lower().replace("_eval", ""): canonical_dataset_hash(
                records_by_split[split]
            )
            for split in sorted(DATASET_SPLITS)
        }
    if sealed_records is not None:
        sealed = [dict(record) for record in sealed_records]
        if run_mode == "SEALED_FINAL" and not str(
            overrides.get("sealed_approval_ref", "")
        ).strip():
            raise ManifestError(
                "SEALED_FINAL sealed_records require explicit sealed_approval_ref"
            )
        version_override = overrides.get("dataset_versions")
        if isinstance(version_override, Mapping):
            sealed_version = version_override.get("sealed", "d4-sealed-v1")
        else:
            sealed_version = "d4-sealed-v1"
        try:
            snapshot = freeze_sealed_dataset(
                sealed,
                version=str(sealed_version),
                creation_provenance=str(overrides.get("sealed_creation_provenance", "synthetic_foundation_fixture")),
                approval_ref=str(overrides.get("sealed_approval_ref", "CONTROLLER_PENDING")),
            )
        except Exception as exc:
            raise ManifestError(f"sealed dataset cannot be frozen: {exc}") from exc
        manifest["dataset_hashes"]["sealed"] = snapshot.dataset_hash
        manifest["sealed_hash"] = snapshot.dataset_hash
        manifest["sealed_evaluation"] = snapshot.as_manifest_fields()
    # Explicit field overrides are restricted to schema-shaped fields.  A
    # caller cannot smuggle a second run ID or prohibited data flag through a
    # convenience dict.
    for key, value in overrides.items():
        if key in {"sealed_creation_provenance", "sealed_approval_ref"}:
            continue
        if key not in manifest:
            raise ManifestError(f"unknown manifest field: {key}")
        if key == "run_id":
            raise ManifestError("run_id must be supplied through the run_id argument")
        manifest[key] = deepcopy(value)
    manifest["result_paths"] = list(result_paths)
    if artifact_root is not None:
        try:
            manifest["result_paths"] = validate_artifact_paths(
                manifest["result_paths"], root=artifact_root
            )
        except Exception as exc:
            raise ManifestError(f"unsafe result_paths: {exc}") from exc
    else:
        try:
            manifest["result_paths"] = [
                validate_result_path(value) for value in manifest["result_paths"]
            ]
        except Exception as exc:
            raise ManifestError(f"unsafe result_paths: {exc}") from exc
    # The fixture audit is derived from the selected mode after overrides; a
    # conflicting override is rejected rather than silently repaired.
    _validate_fixture_audit(manifest, expected_mode=fixture_mode)
    validate_run_manifest(manifest, artifact_root=artifact_root)
    return manifest


def _validate_fixture_audit(
    manifest: Mapping[str, Any],
    *,
    expected_mode: str | None = None,
) -> None:
    audit = manifest.get("fixture_audit")
    if not isinstance(audit, Mapping):
        raise ManifestError("fixture_audit must be an object")
    mode = audit.get("fixture_mode")
    if mode not in FIXTURE_MODES:
        raise ManifestError("fixture_audit.fixture_mode is invalid")
    if expected_mode is not None and mode != expected_mode:
        raise ManifestError(
            "fixture_audit.fixture_mode conflicts with the requested fixture_mode"
        )
    if audit.get("compatibility_mapping") != compatibility_mapping_for(mode):
        raise ManifestError("fixture_audit compatibility mapping is invalid")
    if audit.get("separation_rule") != "one_mode_per_run":
        raise ManifestError("fixture_audit separation_rule must be one_mode_per_run")
    modes = manifest.get("bootstrap_modes")
    if modes != [mode]:
        raise ManifestError("bootstrap_modes must contain only fixture_audit.fixture_mode")


def validate_run_manifest(
    manifest: Mapping[str, Any],
    *,
    artifact_root: str | Path | None = None,
) -> bool:
    """Validate the D4 manifest invariants used by the foundation layer."""

    missing = [field for field in MANIFEST_REQUIRED_FIELDS if field not in manifest]
    if missing:
        raise ManifestError("manifest missing required fields: " + ", ".join(missing))
    if manifest.get("schema_version") != "d4-run-v1":
        raise ManifestError("manifest schema_version must be d4-run-v1")
    try:
        validate_run_id(manifest["run_id"])
    except Exception as exc:
        raise ManifestError(str(exc)) from exc
    if manifest.get("run_mode") not in RUN_MODES:
        raise ManifestError("manifest run_mode is invalid")
    if not isinstance(manifest.get("timestamp"), str) or not manifest["timestamp"].strip():
        raise ManifestError("manifest timestamp is required")
    try:
        parsed_timestamp = datetime.fromisoformat(manifest["timestamp"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ManifestError("manifest timestamp must be ISO-8601 date-time") from exc
    if parsed_timestamp.tzinfo is None:
        raise ManifestError("manifest timestamp must include a timezone")
    commit = manifest.get("git_commit")
    if not isinstance(commit, str) or not GIT_COMMIT_PATTERN.fullmatch(commit):
        raise ManifestError("manifest git_commit is invalid")
    tags = manifest.get("accepted_tags")
    if not isinstance(tags, list) or any(
        not isinstance(tag, str) or not IDENTIFIER_PATTERN.fullmatch(tag)
        for tag in tags
    ):
        raise ManifestError("accepted_tags must contain identifier strings")
    for field in ("dev", "regression", "sealed"):
        versions = manifest.get("dataset_versions")
        hashes = manifest.get("dataset_hashes")
        if (
            not isinstance(versions, Mapping)
            or not isinstance(versions.get(field), str)
            or not IDENTIFIER_PATTERN.fullmatch(versions[field])
        ):
            raise ManifestError(f"dataset_versions.{field} is required")
        if not isinstance(hashes, Mapping):
            raise ManifestError("dataset_hashes must be an object")
        try:
            validate_sha256_hex(hashes.get(field))
        except Exception as exc:
            raise ManifestError(f"dataset_hashes.{field} is invalid: {exc}") from exc
    _hash_or_none(manifest.get("sealed_hash"), field="sealed_hash")
    _hash_or_none(manifest.get("promptfoo_config_hash"), field="promptfoo_config_hash")
    _hash_or_none(manifest.get("lock_hash"), field="lock_hash")
    for field in ("template_ids_hashes", "policy_ids_hashes"):
        values = manifest.get(field)
        if not isinstance(values, Mapping) or any(
            not isinstance(key, str)
            or not IDENTIFIER_PATTERN.fullmatch(key)
            or not isinstance(value, str)
            or not re.fullmatch(r"[0-9a-f]{64}", value)
            for key, value in values.items()
        ):
            raise ManifestError(f"{field} must map identifiers to bare SHA-256 hashes")
    providers = manifest.get("provider_identities")
    if not isinstance(providers, Mapping) or not all(
        key in providers for key in ("target", "attacker", "grader")
    ):
        raise ManifestError("provider_identities must contain target, attacker, grader")
    if not isinstance(providers.get("target"), str) or not providers["target"].strip():
        raise ManifestError("provider_identities.target is required")
    for key in ("attacker", "grader"):
        if providers[key] is not None and (
            not isinstance(providers[key], str) or not providers[key].strip()
        ):
            raise ManifestError(f"provider_identities.{key} must be non-empty or null")
    runtime = manifest.get("runtime")
    if not isinstance(runtime, Mapping) or not all(key in runtime for key in ("model", "digest")):
        raise ManifestError("runtime must contain model and digest")
    for key in ("model", "digest"):
        if runtime[key] is not None and (
            not isinstance(runtime[key], str) or not runtime[key].strip()
        ):
            raise ManifestError(f"runtime.{key} must be non-empty or null")
    promptfoo_version = manifest.get("promptfoo_version")
    if promptfoo_version is not None and (
        not isinstance(promptfoo_version, str)
        or not VERSION_PATTERN.fullmatch(promptfoo_version)
    ):
        raise ManifestError("promptfoo_version must be a semantic version or null")
    repeats = manifest.get("repeat_settings")
    if not isinstance(repeats, Mapping) or not isinstance(repeats.get("repeats"), int) or repeats["repeats"] < 1:
        raise ManifestError("repeat_settings.repeats must be >= 1")
    if not isinstance(repeats.get("concurrency"), int) or repeats["concurrency"] < 1:
        raise ManifestError("repeat_settings.concurrency must be >= 1")
    if "cache" in repeats and repeats["cache"] not in {"disabled", "enabled"}:
        raise ManifestError("repeat_settings.cache is invalid")
    retry = manifest.get("retry_policy")
    if (
        not isinstance(retry, Mapping)
        or not isinstance(retry.get("max_retries"), int)
        or retry["max_retries"] < 0
        or retry.get("non_idempotent_post_retries") != 0
    ):
        raise ManifestError("non-idempotent POST retries must be zero")
    if manifest.get("real_student_data") is not False:
        raise ManifestError("D4 manifest must set real_student_data=false")
    if manifest.get("cloud_fallback") is not False:
        raise ManifestError("D4 manifest must set cloud_fallback=false")
    if manifest.get("network_policy") not in {"loopback_only", "observed_loopback_only", "controller_exception"}:
        raise ManifestError("network_policy is invalid")
    if manifest.get("network_observation") not in {
        "NOT_RUN",
        "observed_loopback_only",
        "non_loopback_detected",
        "controller_exception",
    }:
        raise ManifestError("network_observation is invalid")
    bootstrap = manifest.get("bootstrap_modes")
    if not isinstance(bootstrap, list) or len(bootstrap) != 1 or bootstrap[0] not in FIXTURE_MODES:
        raise ManifestError("bootstrap_modes must contain one fixture mode")
    _validate_fixture_audit(manifest)
    endpoints = manifest.get("endpoint_inventory")
    if not isinstance(endpoints, list):
        raise ManifestError("endpoint_inventory must be an array")
    for endpoint in endpoints:
        if not isinstance(endpoint, Mapping):
            raise ManifestError("endpoint_inventory entries must be objects")
        if (
            not isinstance(endpoint.get("name"), str)
            or not IDENTIFIER_PATTERN.fullmatch(endpoint["name"])
            or not isinstance(endpoint.get("endpoint"), str)
            or not endpoint["endpoint"].strip()
            or not isinstance(endpoint.get("approved"), bool)
        ):
            raise ManifestError("endpoint_inventory entry is invalid")
    closure = manifest.get("human_review_closure")
    if not isinstance(closure, Mapping):
        raise ManifestError("human_review_closure must be an object")
    if closure.get("status") not in {
        "NOT_REQUIRED",
        "NOT_RUN",
        "PENDING",
        "COMPLETE",
        "ESCALATED",
    }:
        raise ManifestError("human_review_closure.status is invalid")
    if not isinstance(closure.get("mandatory_complete"), bool) or not isinstance(
        closure.get("unresolved_count"), int
    ) or closure["unresolved_count"] < 0 or not isinstance(
        closure.get("disagreement_preserved"), bool
    ):
        raise ManifestError("human_review_closure fields are invalid")
    if closure["status"] in {"NOT_RUN", "NOT_REQUIRED"} and (
        closure["mandatory_complete"] is not False or closure["unresolved_count"] != 0
    ):
        raise ManifestError("unstarted/not-required review closure must be empty")
    if closure["status"] == "COMPLETE" and (
        closure["mandatory_complete"] is not True or closure["unresolved_count"] != 0
    ):
        raise ManifestError("complete review closure must have zero unresolved items")
    if closure["status"] in {"PENDING", "ESCALATED"} and (
        closure["mandatory_complete"] is not False or closure["unresolved_count"] < 1
    ):
        raise ManifestError("pending/escalated review closure must retain unresolved items")
    sealed = manifest.get("sealed_evaluation")
    if not isinstance(sealed, Mapping):
        raise ManifestError("sealed_evaluation must be an object")
    if sealed.get("status") not in {"NOT_RUN", "PENDING", "COMPLETE"}:
        raise ManifestError("sealed_evaluation.status is invalid")
    if sealed.get("case_count") is not None and (
        not isinstance(sealed["case_count"], int) or sealed["case_count"] < 0
    ):
        raise ManifestError("sealed_evaluation.case_count is invalid")
    distribution = sealed.get("scenario_family_distribution")
    if not isinstance(distribution, Mapping) or any(
        not isinstance(key, str)
        or not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", key)
        or not isinstance(value, int)
        or value < 0
        for key, value in distribution.items()
    ):
        raise ManifestError("sealed_evaluation.scenario_family_distribution is invalid")
    if not isinstance(sealed.get("creation_provenance"), str) or not sealed["creation_provenance"].strip():
        raise ManifestError("sealed_evaluation.creation_provenance is required")
    if sealed["status"] == "NOT_RUN" and (
        sealed.get("case_count") is not None
        or sealed.get("scenario_family_distribution") != {}
        or sealed.get("creation_provenance") != "not_run"
        or sealed.get("approval_ref") is not None
    ):
        raise ManifestError("NOT_RUN sealed evaluation must contain no result metadata")
    if sealed["status"] == "PENDING" and sealed.get("approval_ref") is not None:
        raise ManifestError("PENDING sealed evaluation cannot contain approval_ref")
    if sealed["status"] == "COMPLETE" and (
        not isinstance(sealed.get("case_count"), int)
        or sealed["case_count"] < 1
        or not distribution
        or not isinstance(sealed.get("approval_ref"), str)
        or not sealed["approval_ref"].strip()
    ):
        raise ManifestError("COMPLETE sealed evaluation requires count, distribution, and approval")
    if artifact_root is not None:
        try:
            validate_artifact_paths(manifest.get("result_paths", []), root=artifact_root)
        except Exception as exc:
            raise ManifestError(str(exc)) from exc
    else:
        for path in manifest.get("result_paths", []):
            try:
                validate_result_path(path)
            except Exception as exc:
                raise ManifestError(f"unsafe result path: {exc}") from exc
    if manifest.get("run_mode") == "SEALED_FINAL":
        _validate_sealed_final(manifest)
    # The imperative checks above provide stable domain errors.  The final
    # schema pass closes gaps such as unknown nested fields, date-time format,
    # minimum run-ID length, and strict type/enumeration checks when callers
    # invoke this low-level validator directly.
    try:
        from .schema_validation import validate_document

        validate_document(manifest, "run_manifest")
    except Exception as exc:
        raise ManifestError(f"run manifest schema/semantic validation failed: {exc}") from exc
    return True


def _validate_sealed_final(manifest: Mapping[str, Any]) -> None:
    if not isinstance(manifest.get("sealed_hash"), str):
        raise ManifestError("SEALED_FINAL requires sealed_hash")
    validate_sha256_hex(manifest["sealed_hash"])
    promptfoo = manifest.get("promptfoo_version")
    if not isinstance(promptfoo, str) or not VERSION_PATTERN.fullmatch(promptfoo):
        raise ManifestError("SEALED_FINAL requires pinned Promptfoo semver")
    validate_sha256_hex(manifest["promptfoo_config_hash"])
    if manifest.get("network_policy") != "observed_loopback_only" or manifest.get("network_observation") != "observed_loopback_only":
        raise ManifestError("SEALED_FINAL requires observed loopback network")
    providers = manifest["provider_identities"]
    if any(not isinstance(providers.get(key), str) or not providers[key].strip() for key in ("target", "attacker", "grader")):
        raise ManifestError("SEALED_FINAL requires explicit target/attacker/grader identities")
    runtime = manifest["runtime"]
    if any(not isinstance(runtime.get(key), str) or not runtime[key].strip() for key in ("model", "digest")):
        raise ManifestError("SEALED_FINAL requires runtime model and digest")
    for field in ("node_runtime", "wrapper_identity"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            raise ManifestError(f"SEALED_FINAL requires {field}")
    validate_sha256_hex(manifest["lock_hash"])
    endpoints = manifest.get("endpoint_inventory")
    if not isinstance(endpoints, list) or not endpoints:
        raise ManifestError("SEALED_FINAL requires endpoint inventory")
    for endpoint in endpoints:
        if not isinstance(endpoint, Mapping) or endpoint.get("approved") is not True:
            raise ManifestError("all SEALED_FINAL endpoints must be approved")
        if not isinstance(endpoint.get("endpoint"), str) or not LOOPBACK_PATTERN.fullmatch(endpoint["endpoint"]):
            raise ManifestError("SEALED_FINAL endpoint must be loopback")
    closure = manifest.get("human_review_closure")
    closure_complete = (
        isinstance(closure, Mapping)
        and closure.get("status") == "COMPLETE"
        and closure.get("mandatory_complete") is True
    )
    closure_not_required = (
        isinstance(closure, Mapping)
        and closure.get("status") == "NOT_REQUIRED"
        and closure.get("mandatory_complete") is False
    )
    if (
        not (closure_complete or closure_not_required)
        or closure.get("unresolved_count") != 0
        or closure.get("disagreement_preserved") is not True
    ):
        raise ManifestError("SEALED_FINAL requires complete or not-required human-review closure")
    sealed = manifest["sealed_evaluation"]
    if sealed.get("status") != "COMPLETE" or not isinstance(sealed.get("case_count"), int) or sealed["case_count"] < 1 or not sealed.get("scenario_family_distribution") or not isinstance(sealed.get("creation_provenance"), str) or not sealed["creation_provenance"].strip() or not isinstance(sealed.get("approval_ref"), str) or not sealed["approval_ref"].strip():
        raise ManifestError("SEALED_FINAL requires complete sealed evaluation metadata")


def manifest_content_hash(manifest: Mapping[str, Any]) -> str:
    """Hash a manifest without adding a mutable self-hash field."""

    return canonical_sha256(manifest, self_field="manifest_hash")


def write_run_manifest(
    path: str | Path,
    manifest: Mapping[str, Any],
    *,
    artifact_root: str | Path | None = None,
) -> Path:
    """Write a manifest once; a changed existing manifest is rejected."""

    validate_run_manifest(manifest, artifact_root=artifact_root)
    target = Path(path)
    if artifact_root is not None:
        root = Path(artifact_root).resolve(strict=False)
        try:
            relative = (
                target
                if not target.is_absolute()
                else target.resolve(strict=False).relative_to(root)
            )
            target = safe_artifact_path(root, relative)
        except ValueError as exc:
            raise ManifestError("manifest path must be inside artifact_root") from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = (canonical_json(manifest) + "\n").encode("utf-8")
    if target.exists():
        try:
            existing = target.read_bytes()
        except OSError as exc:
            raise ManifestError(f"cannot read existing manifest: {exc}") from exc
        if existing != payload:
            raise ManifestError(
                f"manifest is immutable and already differs: {target}"
            )
        return target
    try:
        with target.open("xb") as handle:
            handle.write(payload)
    except FileExistsError:
        # A concurrent writer wins only if it wrote the identical bytes.
        if target.read_bytes() != payload:
            raise ManifestError(f"manifest changed during immutable write: {target}")
    except OSError as exc:
        raise ManifestError(f"cannot write manifest: {exc}") from exc
    return target


class RunManifestBuilder:
    """Small reusable builder wrapper around :func:`build_run_manifest`."""

    def __init__(self, **defaults: Any) -> None:
        self._defaults = dict(defaults)

    def build(self, **overrides: Any) -> dict[str, Any]:
        values = dict(self._defaults)
        values.update(overrides)
        return build_run_manifest(**values)


# Compatibility names for scripts that use a more explicit noun.
create_run_manifest = build_run_manifest
save_run_manifest = write_run_manifest
build_manifest = build_run_manifest
write_manifest = write_run_manifest
