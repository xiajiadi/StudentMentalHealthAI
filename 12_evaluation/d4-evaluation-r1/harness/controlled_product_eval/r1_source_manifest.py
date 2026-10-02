"""Fail-closed binding for the one Controller-authorized R1 Backend commit."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from . import service_profiles
from .runner import RunnerError

R1_PRODUCT_BASELINE_COMMIT = "466fef4bf59d10b7d115bf522e9f53b2730adb91"
R1_TIMEOUT_REMEDIATION_COMMIT = "1ff7b55c6577eaf49158a1daaaae079f9e3c55f8"
R1_REMEDIATION_SOURCE_MANIFEST_PATH = (
    "12_evaluation/d4-evaluation-r1/spec/r1_remediation_source_manifest.json"
)

PRODUCT_SOURCE_PATHS = (
    "01_cat-engine",
    "03_assessment-adapter",
    "04_knowledge-pipeline",
    "05_rag-engine",
    "06_llm-runtime",
    "08_safety-engine",
    "09_backend",
    "11_database",
    "CONTRACTS.md",
    "openapi.json",
    "openapi.hardened.candidate.json",
)

_EXPECTED_SEMANTIC_DELTA: dict[str, Any] = {
    "runtime_request_timeout_seconds": 60,
    "backend_llm_read_timeout_seconds": 65,
    "backend_support_deadline_seconds": 80,
    "retry_policy_changed": False,
    "warmup_added": False,
    "unbounded_timeout_added": False,
    "rag_safety_timeouts_changed": False,
}
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_BLOB_RE = re.compile(r"^[0-9a-f]{40}$")


def _git(repo_root: Path, *arguments: str) -> str:
    try:
        return service_profiles._git(repo_root, *arguments)
    except service_profiles.ServiceProfileError:
        raise RunnerError("D4SMOKE committed product-source binding could not be verified") from None


def _changed_product_paths(repo_root: Path, left: str, right: str) -> list[str]:
    output = _git(
        repo_root,
        "diff",
        "--name-only",
        "--no-renames",
        left,
        right,
        "--",
        *PRODUCT_SOURCE_PATHS,
    )
    return sorted(path.replace("\\", "/") for path in output.splitlines() if path)


def _strict_mapping(value: Any, *, keys: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise RunnerError(f"D4SMOKE remediation source manifest has invalid {label}")
    return value


def _validate_semantic_delta(value: Any) -> dict[str, Any]:
    delta = _strict_mapping(
        value,
        keys=set(_EXPECTED_SEMANTIC_DELTA),
        label="semantic delta",
    )
    if any(
        type(delta[key]) is not type(expected) or delta[key] != expected
        for key, expected in _EXPECTED_SEMANTIC_DELTA.items()
    ):
        raise RunnerError("D4SMOKE remediation source manifest semantic delta is not authorized")
    return dict(delta)


def resolve_r1_product_source_binding(
    repo_root: Path,
    *,
    head_commit: str,
    dirty_paths: Sequence[str],
) -> dict[str, Any]:
    """Return the exact committed product baseline or validate the R1 manifest."""

    if not _COMMIT_RE.fullmatch(head_commit):
        raise RunnerError("D4SMOKE evaluation source commit is malformed")

    changed_paths = _changed_product_paths(repo_root, R1_PRODUCT_BASELINE_COMMIT, head_commit)
    if not changed_paths:
        return {
            "schema_version": "d4-r1-product-source-binding.v1",
            "status": "PASS",
            "source_mode": "accepted_r1_baseline",
            "baseline_commit": R1_PRODUCT_BASELINE_COMMIT,
            "product_source_commit": R1_PRODUCT_BASELINE_COMMIT,
            "product_parent_commit": None,
            "product_files": [],
            "manifest_path": None,
            "manifest_blob_oid": None,
            "authorized_semantic_delta": None,
        }

    if dirty_paths:
        raise RunnerError("D4SMOKE remediation source manifest requires a clean worktree")

    try:
        manifest_text = _git(
            repo_root,
            "show",
            f"{head_commit}:{R1_REMEDIATION_SOURCE_MANIFEST_PATH}",
        )
        manifest = json.loads(manifest_text)
    except (json.JSONDecodeError, RunnerError):
        raise RunnerError("D4SMOKE committed R1 remediation source manifest is missing or invalid") from None

    manifest = _strict_mapping(
        manifest,
        keys={
            "schema_version",
            "baseline_commit",
            "parent_commit",
            "product_commit",
            "files",
            "authorized_semantic_delta",
        },
        label="top-level fields",
    )
    if manifest.get("schema_version") != "d4-r1-remediation-source-manifest.v1":
        raise RunnerError("D4SMOKE remediation source manifest version is unsupported")
    if manifest.get("baseline_commit") != R1_PRODUCT_BASELINE_COMMIT:
        raise RunnerError("D4SMOKE remediation source manifest baseline does not match the pinned R1 baseline")
    if manifest.get("product_commit") != R1_TIMEOUT_REMEDIATION_COMMIT:
        raise RunnerError("D4SMOKE remediation source manifest product commit is not authorized")

    product_commit = R1_TIMEOUT_REMEDIATION_COMMIT
    parent_commit = _git(repo_root, "rev-parse", f"{product_commit}^")
    if manifest.get("parent_commit") != parent_commit:
        raise RunnerError("D4SMOKE remediation source manifest parent commit does not match Git")
    _git(repo_root, "merge-base", "--is-ancestor", R1_PRODUCT_BASELINE_COMMIT, product_commit)
    _git(repo_root, "merge-base", "--is-ancestor", product_commit, head_commit)

    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise RunnerError("D4SMOKE remediation source manifest file bindings are invalid")
    file_bindings: list[dict[str, str]] = []
    for item in files:
        entry = _strict_mapping(item, keys={"path", "git_blob_oid"}, label="file binding")
        path = entry.get("path")
        blob_oid = entry.get("git_blob_oid")
        if not isinstance(path, str) or not isinstance(blob_oid, str) or not _BLOB_RE.fullmatch(blob_oid):
            raise RunnerError("D4SMOKE remediation source manifest contains an invalid file hash")
        file_bindings.append({"path": path.replace("\\", "/"), "git_blob_oid": blob_oid})
    if file_bindings != sorted(file_bindings, key=lambda item: item["path"]):
        raise RunnerError("D4SMOKE remediation source manifest file bindings are not canonical")
    file_paths = [item["path"] for item in file_bindings]
    if len(file_paths) != len(set(file_paths)):
        raise RunnerError("D4SMOKE remediation source manifest contains duplicate file bindings")

    product_commit_changes = _changed_product_paths(repo_root, parent_commit, product_commit)
    if changed_paths != file_paths or product_commit_changes != file_paths:
        raise RunnerError("D4SMOKE product-source changes do not exactly match the committed manifest")

    for entry in file_bindings:
        path = entry["path"]
        product_blob = _git(repo_root, "rev-parse", f"{product_commit}:{path}")
        head_blob = _git(repo_root, "rev-parse", f"{head_commit}:{path}")
        if product_blob != entry["git_blob_oid"] or head_blob != entry["git_blob_oid"]:
            raise RunnerError("D4SMOKE product-source blob differs from the committed manifest")

    semantic_delta = _validate_semantic_delta(manifest.get("authorized_semantic_delta"))
    manifest_blob_oid = _git(
        repo_root,
        "rev-parse",
        f"{head_commit}:{R1_REMEDIATION_SOURCE_MANIFEST_PATH}",
    )
    if not _BLOB_RE.fullmatch(manifest_blob_oid):
        raise RunnerError("D4SMOKE remediation source manifest blob identity is malformed")

    return {
        "schema_version": "d4-r1-product-source-binding.v1",
        "status": "PASS",
        "source_mode": "committed_r1_remediation_manifest",
        "baseline_commit": R1_PRODUCT_BASELINE_COMMIT,
        "product_source_commit": product_commit,
        "product_parent_commit": parent_commit,
        "product_files": file_bindings,
        "manifest_path": R1_REMEDIATION_SOURCE_MANIFEST_PATH,
        "manifest_blob_oid": manifest_blob_oid,
        "authorized_semantic_delta": semantic_delta,
    }
