"""Deterministic D4-3B case, corpus, and immutable formal-run manifests."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import shutil
import subprocess
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from harness.foundation.hashing import canonical_json, canonical_sha256_tag
    from harness.foundation.run_ids import create_run_id, validate_run_id
except ModuleNotFoundError:  # pragma: no cover - package-relative import mode
    from ..foundation.hashing import canonical_json, canonical_sha256_tag
    from ..foundation.run_ids import create_run_id, validate_run_id

from .approved_packet import (
    APPROVED_PACKET_HASH,
    APPROVED_PACKET_ID,
    APPROVED_ANSWERABILITY_CASES,
    ApprovedPacket,
    ApprovedPacketError,
    thaw_json,
)
from .cat_compatibility_gate import CatCompatibilityGateError, validate_cat_d3_compatibility_gate


ACCEPTED_D4_3A_TAG = "d4-slice3a-r1-accepted"
ACCEPTED_D4_3A_COMMIT = "dd083d7a9d50e554408571e8b6d8040700d7a88b"
PROFILE_SOURCE_COPY_COMMIT = "f11f72795f2a7f2b01a62f57187e26c38628c4a0"
FORMAL_ROUTE = "/api/v1/support/requests"
RUN_SCHEMA_VERSION_V1 = "d4-slice3b-run-manifest.v1"
RUN_SCHEMA_VERSION = "d4-slice3b-run-manifest.v2"
CASE_SCHEMA_VERSION = "d4-slice3b-case-manifest.v1"
CORPUS_SCHEMA_VERSION = "d4-slice3b-approved-corpus.v1"

EXPECTED_RUNTIME_IDENTITY: dict[str, Any] = {
    "ollama_version": "0.33.3",
    "model": "qwen2.5:7b-instruct-q4_K_M",
    "digest": "845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e",
    "num_ctx": 8192,
    "kv_cache_type": "f16",
    "num_parallel": 1,
    "max_loaded_models": 1,
    "output_budget": 768,
    "cloud_fallback": False,
    "endpoint": "http://127.0.0.1:11437",
}

_EXPECTED_ACTION = {
    "MUST_ANSWER": "ANSWER",
    "SHOULD_ANSWER": "ANSWER_OR_HUMAN_SAFE_ROUTE",
    "SHOULD_ABSTAIN": "ABSTAIN",
    "MUST_ROUTE": "HUMAN_REVIEW_ROUTE",
    "MUST_DENY": "DENY",
}
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_RUN_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class ManifestError(ValueError):
    """A D4-3B manifest or formal preflight is invalid."""


def _canonical_hash(value: Mapping[str, Any], *, self_field: str) -> str:
    return canonical_sha256_tag(value, self_field=self_field)


def _iso_timestamp(value: datetime | str | None) -> str:
    if value is None:
        stamp = datetime.now(timezone.utc).replace(microsecond=0)
        return stamp.isoformat().replace("+00:00", "Z")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ManifestError("run timestamp must include a timezone")
        return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if not isinstance(value, str) or not value.strip():
        raise ManifestError("run timestamp must be non-empty ISO-8601 text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ManifestError("run timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ManifestError("run timestamp must include a timezone")
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def is_loopback_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        host = parsed.hostname
        if parsed.scheme != "http" or not host or parsed.username or parsed.password or parsed.query or parsed.fragment:
            return False
        if host.lower() == "localhost":
            return True
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _unique_sorted(values: Iterable[str]) -> list[str]:
    return sorted(set(values))


def approved_evidence_ids(packet: ApprovedPacket) -> tuple[str, ...]:
    ids: set[str] = set()
    for case in packet.citation_cases:
        evidence = case.get("citations", case.get("evidence", ()))
        if not isinstance(evidence, tuple):
            continue
        for item in evidence:
            if isinstance(item, Mapping) and isinstance(item.get("chunk_id"), str):
                ids.add(item["chunk_id"])
    for case in packet.answerability_cases:
        for binding in case.get("evidence_bindings", ()):
            if isinstance(binding, Mapping) and isinstance(binding.get("evidence_id"), str):
                ids.add(binding["evidence_id"])
    return tuple(sorted(ids))


def build_case_manifest(packet: ApprovedPacket) -> dict[str, Any]:
    """Build the stable 12-case run plan directly from approved Gold records."""

    packet.verify_unchanged()
    cases: list[dict[str, Any]] = []
    for case in packet.answerability_cases:
        scope = case.get("target_scope")
        request = case.get("request")
        if not isinstance(scope, Mapping) or not isinstance(request, str):
            raise ManifestError(f"{case.get('case_id')}: required raw approved fields are missing")
        response_class = case.get("expected_response_class")
        if response_class not in _EXPECTED_ACTION:
            raise ManifestError(f"{case.get('case_id')}: unknown approved response class")
        cases.append(
            {
                "case_id": case["case_id"],
                "source_packet_id": packet.packet_id,
                "source_packet_hash": packet.packet_hash,
                "expected_response_class": response_class,
                "expected_action": _EXPECTED_ACTION[str(response_class)],
                "expected_population": scope.get("population"),
                "expected_role": scope.get("role"),
                "expected_purpose": scope.get("purpose"),
                "request_sha256": "sha256:" + hashlib.sha256(request.encode("utf-8")).hexdigest(),
                "request_length": len(request),
                "required_evidence_ids": list(case.get("required_evidence_ids", ())),
                "available_but_inapplicable_evidence_ids": list(case.get("available_but_inapplicable_evidence_ids", ())),
            }
        )
    if len(cases) != APPROVED_ANSWERABILITY_CASES or len({item["case_id"] for item in cases}) != APPROVED_ANSWERABILITY_CASES:
        raise ManifestError("approved 12-case manifest is incomplete or contains duplicate case IDs")
    manifest: dict[str, Any] = {
        "schema_version": CASE_SCHEMA_VERSION,
        "evaluation_mode": "D4_3B_CONTROLLED_PRODUCT_EVALUATION",
        "source_packet_id": packet.packet_id,
        "source_packet_hash": packet.packet_hash,
        "source_packet_file_sha256": packet.raw_file_sha256,
        "source_provenance": thaw_json(packet.source_provenance),
        "answerability_case_count": APPROVED_ANSWERABILITY_CASES,
        "citation_reference_case_ids": [str(case["case_id"]) for case in packet.citation_cases],
        "citation_reference_case_count": len(packet.citation_cases),
        "approved_case_ids": [item["case_id"] for item in cases],
        "cases": cases,
        "expected_class_distribution": {
            label: sum(item["expected_response_class"] == label for item in cases)
            for label in sorted(_EXPECTED_ACTION)
        },
    }
    manifest["manifest_hash"] = _canonical_hash(manifest, self_field="manifest_hash")
    return manifest


def build_approved_corpus_manifest(packet: ApprovedPacket) -> dict[str, Any]:
    """Build per-case RAG identities while preserving the packet's source IDs."""

    packet.verify_unchanged()
    records: list[dict[str, Any]] = []
    aliases: dict[str, list[str]] = {}
    for case in packet.citation_cases:
        evidence = case.get("citations", case.get("evidence", ()))
        if not isinstance(evidence, tuple):
            continue
        for item in evidence:
            if not isinstance(item, Mapping):
                raise ManifestError(f"{case.get('case_id')}: evidence item is not an object")
            chunk_id = item.get("chunk_id")
            if not isinstance(chunk_id, str) or not chunk_id:
                raise ManifestError(f"{case.get('case_id')}: evidence chunk_id is missing")
            copied = thaw_json(item)
            case_id = str(case.get("case_id") or "")
            if not case_id or not isinstance(copied.get("text"), str) or not copied["text"]:
                raise ManifestError("citation packet evidence is missing a stable case ID or text")
            # Gold reuses a source chunk ID for case-specific evidence text.
            # Keep every source record intact and give its temporary RAG copy
            # an identity derived from both the case ID and source content.
            source_content_hash = str(copied.get("content_hash") or canonical_sha256_tag(copied))
            safe_case = re.sub(r"[^A-Za-z0-9._-]", "_", case_id)
            identity = canonical_sha256_tag(
                {"case_id": case_id, "source_chunk_id": chunk_id, "source_content_hash": source_content_hash}
            ).split(":", 1)[1][:16]
            evaluation_chunk_id = f"CHUNK_D4_3B_{safe_case}_{identity}"
            source_case_ids = [case_id]
            records.append(
                {
                    "chunk_id": evaluation_chunk_id,
                    "source_chunk_id": chunk_id,
                    "source_case_ids": source_case_ids,
                    "source_content_hash": source_content_hash,
                    "evidence": copied,
                }
            )
            aliases.setdefault(chunk_id, []).append(evaluation_chunk_id)

    bound_ids = set(approved_evidence_ids(packet))
    source_ids = {item["source_chunk_id"] for item in records}
    missing_bindings = sorted(bound_ids - source_ids)
    if missing_bindings:
        raise ManifestError("approved answerability evidence has no full citation packet source: " + ", ".join(missing_bindings))
    if source_ids - bound_ids:
        raise ManifestError("citation packet contains evidence outside the approved answerability binding set")

    evidence = []
    rag_records = []
    for projection in sorted(records, key=lambda value: value["chunk_id"]):
        evaluation_chunk_id = projection["chunk_id"]
        source_chunk_id = projection["source_chunk_id"]
        item = projection["evidence"]
        source_metadata = {
            "source_human_gold": item.get("human_gold"),
            "source_review_state": item.get("review_state"),
            "source_data_classification": list(item.get("data_classification", ())),
        }
        evidence.append(
            {
                "chunk_id": evaluation_chunk_id,
                "source_chunk_id": source_chunk_id,
                "source_content_hash": projection["source_content_hash"],
                "source_case_ids": projection["source_case_ids"],
                "evidence": item,
            }
        )
        # This is a disposable RAG input projection for one evaluation run.
        # The original review fields above remain pending/false in the Gold
        # packet. These operational gate values apply only to this synthetic,
        # project-authored, non-D2 temporary index; they are not written back
        # into Human Gold or any publication corpus.
        safe_chunk = re.sub(r"[^A-Za-z0-9._-]", "_", evaluation_chunk_id)
        source_document_id = str(item.get("document_id") or "DOC_D4_SYNTHETIC")
        safe_document = re.sub(r"[^A-Za-z0-9._-]", "_", source_document_id)
        safe_case = re.sub(r"[^A-Za-z0-9._-]", "_", projection["source_case_ids"][0])
        rag_records.append(
            {
                "chunk_id": evaluation_chunk_id,
                "document_id": f"KB_D4_3B_{safe_document}_{safe_case}",
                "text": item["text"],
                "context_text": f"{item.get('source_title') or 'D4 synthetic fixture'}\n{item['text']}",
                "metadata": {
                    "layer": "intervention",
                    "title": item.get("source_title") or "D4 synthetic fixture",
                    "organization": item.get("source_organization") or "D4 Synthetic Evaluation Fixture",
                    "source_filename": f"D4_3B_{safe_document}.synthetic",
                    "source_url": item.get("locator") or f"synthetic://d4-3b/{safe_chunk}",
                    "section": str(item.get("locator") or safe_chunk),
                    "citation_locator": item.get("locator") or f"synthetic://d4-3b/{safe_chunk}",
                    "role_scope": list(item.get("role_scope", ())),
                    "target_population": list(item.get("population_scope", ())),
                    "risk_scope": ["normal"],
                    "review_status": "approved",
                    "rights_status": "verified",
                    "content_hash": item.get("content_hash"),
                    "fixture_identity": "D4_3A_HUMAN_GOLD_SYNTHETIC_EVIDENCE",
                    "fixture_purpose": "D4_3B_TEMPORARY_EVALUATION_INDEX_ONLY",
                    "review_semantics": "APPROVED_CASE_CITATION_USE_ONLY_NOT_PRODUCTION_KNOWLEDGE",
                    "rights_semantics": "PROJECT_SYNTHETIC_FIXTURE_NO_EXTERNAL_SOURCE",
                    "evaluation_only": True,
                    "data_classification": list(item.get("data_classification", ())),
                    "source_annotation": source_metadata,
                    "source_chunk_id": source_chunk_id,
                    "source_content_hash": projection["source_content_hash"],
                    "source_packet_id": packet.packet_id,
                    "source_packet_hash": packet.packet_hash,
                    "source_case_ids": projection["source_case_ids"],
                    "source_document_id": source_document_id,
                    "source_citation_id": item.get("citation_id"),
                },
            }
        )
    manifest: dict[str, Any] = {
        "schema_version": CORPUS_SCHEMA_VERSION,
        "corpus_id": "D4_3B_APPROVED_HUMAN_GOLD_SYNTHETIC_EVIDENCE_R1",
        "source_packet_id": packet.packet_id,
        "source_packet_hash": packet.packet_hash,
        "source_provenance": thaw_json(packet.source_provenance),
        "data_classification": [
            "SYNTHETIC_EVALUATION_ONLY",
            "NOT_D2_PUBLICATION",
            "NOT_PRODUCTION_KNOWLEDGE",
            "NOT_REAL_STUDENT_DATA",
            "NOT_PSYCHOLOGY_VALIDATION",
        ],
        "evidence_ids": sorted(item["chunk_id"] for item in evidence),
        "source_evidence_ids": sorted(source_ids),
        "evidence_aliases": [
            {"source_chunk_id": source_id, "evaluation_chunk_ids": sorted(evaluation_ids)}
            for source_id, evaluation_ids in sorted(aliases.items())
        ],
        "evidence_count": len(evidence),
        "evidence": evidence,
        "rag_embedding_records": rag_records,
        "temporary_index_policy": {
            "fresh_index_per_run": True,
            "persistent_product_index": False,
            "d2_publication": False,
            "source_review_annotations_preserved": True,
            "temporary_rag_gate_projection": "D4_3B_TEMPORARY_EVALUATION_INDEX_ONLY",
        },
    }
    manifest["corpus_hash"] = _canonical_hash(manifest, self_field="corpus_hash")
    return manifest


@dataclass(frozen=True, slots=True)
class RuntimePreflight:
    """Verified exact Runtime Recovery PASS, suitable for a formal run gate."""

    observed_at: str
    identity: Mapping[str, Any]
    preflight_hash: str
    network_observation: str
    execution_binding: Mapping[str, Any] | None = None

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        require_live_binding: bool = False,
    ) -> "RuntimePreflight":
        if value.get("schema_version") != "d4-runtime-preflight.v1":
            raise ManifestError("Runtime preflight schema_version mismatch")
        if value.get("status") != "PASS":
            raise ManifestError("exact Runtime preflight status is not PASS")
        supplied_hash = value.get("preflight_hash")
        if not isinstance(supplied_hash, str) or not _SHA256_RE.fullmatch(supplied_hash):
            raise ManifestError("Runtime preflight hash is missing or malformed")
        expected_hash = _canonical_hash(value, self_field="preflight_hash")
        if supplied_hash != expected_hash:
            raise ManifestError("Runtime preflight canonical hash mismatch")
        observed_at = value.get("observed_at")
        if not isinstance(observed_at, str):
            raise ManifestError("Runtime preflight observed_at is missing")
        _iso_timestamp(observed_at)
        identity = value.get("runtime_identity")
        if not isinstance(identity, Mapping):
            raise ManifestError("Runtime preflight runtime_identity is missing")
        for field, expected in EXPECTED_RUNTIME_IDENTITY.items():
            if identity.get(field) != expected:
                raise ManifestError(f"Runtime preflight identity mismatch: {field}")
        if not is_loopback_url(str(identity.get("endpoint", ""))):
            raise ManifestError("Runtime preflight endpoint must be HTTP loopback")
        observation = value.get("network_observation")
        if observation != "OBSERVED_LOOPBACK_ONLY":
            raise ManifestError("Runtime preflight did not prove loopback-only network activity")
        if value.get("external_network_detected") is not False:
            raise ManifestError("Runtime preflight reports external network activity or unknown status")
        if value.get("cloud_fallback") is not False:
            raise ManifestError("Runtime preflight reports cloud fallback or an unknown fallback state")
        binding_value = value.get("execution_binding")
        if binding_value is not None:
            _validate_runtime_execution_binding(binding_value, observed_at)
        if require_live_binding and binding_value is None:
            raise ManifestError("managed Runtime preflight requires a live supervisor attestation")
        return cls(
            observed_at=_iso_timestamp(observed_at),
            identity=dict(identity),
            preflight_hash=supplied_hash,
            network_observation=observation,
            execution_binding=dict(binding_value) if isinstance(binding_value, Mapping) else None,
        )


def _validate_runtime_execution_binding(binding: Any, observed_at: str) -> None:
    if not isinstance(binding, Mapping):
        raise ManifestError("Runtime execution binding must be an object")
    if binding.get("schema_version") != "d4-runtime-live-attestation.v1":
        raise ManifestError("Runtime execution binding schema_version mismatch")
    attempt_id = binding.get("attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id.strip():
        raise ManifestError("Runtime execution binding attempt_id is missing")
    binding_at = binding.get("observed_at")
    if not isinstance(binding_at, str) or _iso_timestamp(binding_at) != _iso_timestamp(observed_at):
        raise ManifestError("Runtime execution binding timestamp does not match its preflight")
    for field in ("runtime_pid", "ollama_pid"):
        value = binding.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ManifestError(f"Runtime execution binding {field} is invalid")
    for prefix in ("runtime", "ollama"):
        pids = binding.get(f"{prefix}_process_tree_pids")
        if (
            not isinstance(pids, list)
            or not pids
            or any(isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0 for pid in pids)
            or binding[f"{prefix}_pid"] not in pids
        ):
            raise ManifestError(f"Runtime execution binding {prefix} process tree is invalid")
        started_at = binding.get(f"{prefix}_started_at")
        if not isinstance(started_at, str):
            raise ManifestError(f"Runtime execution binding {prefix} start time is missing")
        _iso_timestamp(started_at)
        executable = binding.get(f"{prefix}_executable")
        if not isinstance(executable, str) or not Path(executable).is_absolute():
            raise ManifestError(f"Runtime execution binding {prefix} executable is not absolute")
        executable_hash = binding.get(f"{prefix}_executable_sha256")
        if not isinstance(executable_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", executable_hash):
            raise ManifestError(f"Runtime execution binding {prefix} executable hash is invalid")
    runtime_pids = binding["runtime_process_tree_pids"]
    launcher_pid = binding.get("runtime_launcher_pid")
    if (
        isinstance(launcher_pid, bool)
        or not isinstance(launcher_pid, int)
        or launcher_pid <= 0
        or launcher_pid not in runtime_pids
    ):
        raise ManifestError("Runtime execution binding launcher PID is invalid")
    launcher_started_at = binding.get("runtime_launcher_started_at")
    if not isinstance(launcher_started_at, str):
        raise ManifestError("Runtime execution binding launcher start time is missing")
    _iso_timestamp(launcher_started_at)
    launcher_executable = binding.get("runtime_launcher_executable")
    if not isinstance(launcher_executable, str) or not Path(launcher_executable).is_absolute():
        raise ManifestError("Runtime execution binding launcher executable is not absolute")
    launcher_hash = binding.get("runtime_launcher_executable_sha256")
    if not isinstance(launcher_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", launcher_hash):
        raise ManifestError("Runtime execution binding launcher executable hash is invalid")
    source_hash = binding.get("runtime_source_tree_sha256")
    if not isinstance(source_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", source_hash):
        raise ManifestError("Runtime execution binding source tree hash is invalid")
    if (
        binding.get("runtime_endpoint") != "http://127.0.0.1:8160"
        or binding.get("provider_endpoint") != "http://127.0.0.1:11437"
        or binding.get("ollama_version") != EXPECTED_RUNTIME_IDENTITY["ollama_version"]
        or binding.get("model") != EXPECTED_RUNTIME_IDENTITY["model"]
        or binding.get("model_digest") != EXPECTED_RUNTIME_IDENTITY["digest"]
        or binding.get("num_ctx") != EXPECTED_RUNTIME_IDENTITY["num_ctx"]
        or binding.get("kv_cache_type") != EXPECTED_RUNTIME_IDENTITY["kv_cache_type"]
        or binding.get("num_parallel") != EXPECTED_RUNTIME_IDENTITY["num_parallel"]
        or binding.get("max_loaded_models") != EXPECTED_RUNTIME_IDENTITY["max_loaded_models"]
        or binding.get("output_budget") != EXPECTED_RUNTIME_IDENTITY["output_budget"]
        or binding.get("cloud_fallback") is not False
    ):
        raise ManifestError("Runtime execution binding differs from the accepted identity")
    if (
        binding.get("network_status") != "PASS"
        or binding.get("network_observation") != "OBSERVED_LOOPBACK_ONLY"
        or binding.get("external_established_connection_count") != 0
        or binding.get("forbidden_endpoint_connection_count") != 0
    ):
        raise ManifestError("Runtime execution binding does not prove loopback-only traffic")
    listener_pids = binding.get("verified_listener_pids")
    if not isinstance(listener_pids, Mapping):
        raise ManifestError("Runtime execution binding listener ownership is missing")
    required_listener_pids = {"3307", "8160", "8180", "8181", "8190", "11437"}
    if not required_listener_pids <= set(listener_pids):
        raise ManifestError("Runtime execution binding omits required service listeners")
    if (
        listener_pids.get("8160") != binding.get("runtime_pid")
        or listener_pids.get("11437") != binding.get("ollama_pid")
    ):
        raise ManifestError("Runtime execution binding listener PIDs do not match service processes")
    if any(
        not isinstance(port, str)
        or not port.isdecimal()
        or isinstance(pid, bool)
        or not isinstance(pid, int)
        or pid <= 0
        for port, pid in listener_pids.items()
    ):
        raise ManifestError("Runtime execution binding contains an invalid listener PID")
    network_hash = binding.get("network_observation_sha256")
    if not isinstance(network_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", network_hash):
        raise ManifestError("Runtime execution binding network snapshot hash is invalid")


def build_runtime_preflight(
    *,
    observed_at: datetime | str,
    identity: Mapping[str, Any] | None = None,
    execution_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Test/helper constructor. It does not probe or start a Runtime."""

    preflight: dict[str, Any] = {
        "schema_version": "d4-runtime-preflight.v1",
        "status": "PASS",
        "observed_at": _iso_timestamp(observed_at),
        "runtime_identity": deepcopy(dict(identity or EXPECTED_RUNTIME_IDENTITY)),
        "network_observation": "OBSERVED_LOOPBACK_ONLY",
        "external_network_detected": False,
        "cloud_fallback": False,
    }
    if execution_binding is not None:
        preflight["execution_binding"] = deepcopy(dict(execution_binding))
    preflight["preflight_hash"] = _canonical_hash(preflight, self_field="preflight_hash")
    return preflight


def _git(root: Path, *args: str) -> str:
    git_executable = shutil.which("git.exe") or shutil.which("git")
    if not git_executable:
        raise ManifestError("Git executable is unavailable")
    git_path = Path(git_executable).resolve()
    if not git_path.is_absolute() or not git_path.is_file():
        raise ManifestError("Git executable did not resolve to an absolute file")
    result = subprocess.run(
        [str(git_path), "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        shell=False,
    )
    return result.stdout.strip()


def git_snapshot(root: str | Path) -> dict[str, Any]:
    """Record checkout identity without including file contents in logs."""

    repo = Path(root).resolve()
    try:
        branch = _git(repo, "branch", "--show-current")
        commit = _git(repo, "rev-parse", "HEAD")
        status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
        diff = _git(repo, "diff", "--binary", "HEAD", "--")
        tracked_tree = _git(repo, "ls-files", "--cached", "--others", "--exclude-standard", "12_evaluation/d4-evaluation-r1/harness/controlled_product_eval", "12_evaluation/d4-evaluation-r1/spec/d4_slice3b_*.json")
    except (subprocess.CalledProcessError, OSError) as exc:
        raise ManifestError(f"cannot capture Git run identity: {exc}") from exc
    file_hashes: list[tuple[str, str]] = []
    for relative in sorted(item for item in tracked_tree.splitlines() if item):
        path = repo / relative
        if path.is_file():
            file_hashes.append((relative.replace("\\", "/"), hashlib.sha256(path.read_bytes()).hexdigest()))
    return {
        "git_branch": branch,
        "git_commit": commit,
        "git_dirty": bool(status),
        "git_status_sha256": "sha256:" + hashlib.sha256(status.encode("utf-8")).hexdigest(),
        "git_diff_sha256": "sha256:" + hashlib.sha256(diff.encode("utf-8")).hexdigest(),
        "evaluation_source_tree_sha256": "sha256:" + hashlib.sha256(canonical_json(file_hashes).encode("utf-8")).hexdigest(),
    }


def verify_accepted_baseline(root: str | Path) -> None:
    repo = Path(root).resolve()
    try:
        resolved = _git(repo, "rev-parse", f"{ACCEPTED_D4_3A_TAG}^{{commit}}")
        current = _git(repo, "rev-parse", "HEAD")
        _git(repo, "merge-base", "--is-ancestor", resolved, current)
    except (subprocess.CalledProcessError, OSError) as exc:
        raise ManifestError("D4-3A accepted tag is missing or not an ancestor of this worktree") from exc
    if resolved != ACCEPTED_D4_3A_COMMIT:
        raise ManifestError("D4-3A accepted tag resolves to an unexpected commit")


def write_json_once(path: str | Path, value: Mapping[str, Any]) -> Path:
    """Write canonical JSON atomically once; differing existing bytes fail."""

    target = Path(path)
    payload = (canonical_json(value) + "\n").encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != payload:
            raise ManifestError(f"immutable JSON artifact already differs: {target}")
        return target
    try:
        with target.open("xb") as handle:
            handle.write(payload)
    except FileExistsError:
        if target.read_bytes() != payload:
            raise ManifestError(f"immutable JSON artifact changed during write: {target}")
    return target


def build_formal_manifest(
    *,
    packet: ApprovedPacket,
    case_manifest: Mapping[str, Any],
    corpus_manifest: Mapping[str, Any],
    runtime_preflight: Mapping[str, Any] | RuntimePreflight,
    backend_base_url: str,
    observer_endpoints: Mapping[str, str],
    rag_service_identity: Mapping[str, Any],
    runtime_endpoint_identity: Mapping[str, Any],
    backend_dependency_identity: Mapping[str, Any],
    cat_d3_compatibility_gate: Mapping[str, Any],
    cat_d3_compatibility_gate_evidence: Mapping[str, Any],
    managed_service_identity: Mapping[str, Any] | None,
    repo_root: str | Path,
    timestamp: datetime | str | None = None,
    run_id: str | None = None,
    entropy: str | bytes | None = None,
    unexpected_configuration: Iterable[str] = (),
) -> dict[str, Any]:
    """Freeze one formal D4-3B run manifest before the first product request."""

    packet.verify_unchanged()
    verify_case_manifest(case_manifest, packet=packet)
    verify_corpus_manifest(corpus_manifest, packet=packet)
    runtime = runtime_preflight if isinstance(runtime_preflight, RuntimePreflight) else RuntimePreflight.from_mapping(runtime_preflight)
    if not is_loopback_url(backend_base_url):
        raise ManifestError("formal Backend URL must be HTTP loopback")
    rag_service = dict(rag_service_identity)
    if rag_service.get("status") != "READY":
        raise ManifestError("evaluation RAG service is not READY")
    observed_ids = rag_service.get("eligible_chunk_ids")
    if not isinstance(observed_ids, list) or sorted(observed_ids) != sorted(corpus_manifest["evidence_ids"]):
        raise ManifestError("fresh RAG index evidence IDs differ from the approved temporary corpus")
    if rag_service.get("index_reused") is not False:
        raise ManifestError("D4-3B requires a fresh per-run RAG index")
    if not isinstance(rag_service.get("index_id"), str) or not rag_service.get("index_id"):
        raise ManifestError("RAG service did not report its fresh index identity")
    if not isinstance(rag_service.get("index_manifest_hash"), str) or not _SHA256_RE.fullmatch(rag_service["index_manifest_hash"]):
        raise ManifestError("RAG service did not report the fresh index manifest hash")
    if rag_service.get("corpus_manifest_hash") != corpus_manifest.get("corpus_hash"):
        raise ManifestError("RAG service corpus hash differs from the approved evaluation corpus")
    if rag_service.get("source_packet_id") != packet.packet_id or rag_service.get("source_packet_hash") != packet.packet_hash:
        raise ManifestError("RAG service is not bound to the approved Human Gold packet")
    if rag_service.get("evaluation_only") is not True or rag_service.get("synthetic_fixture_only") is not True:
        raise ManifestError("RAG service is not isolated as a synthetic evaluation fixture")
    runtime_endpoint = dict(runtime_endpoint_identity)
    if runtime_endpoint.get("readiness") != "pass" or runtime_endpoint.get("cloud_fallback") is not False:
        raise ManifestError("live Runtime health is not ready or reports cloud fallback")
    dependencies = deepcopy(dict(backend_dependency_identity))
    for name in ("rag", "llm_runtime", "cat", "safety"):
        item = dependencies.get(name)
        if not isinstance(item, Mapping) or str(item.get("status", "")).upper() != "READY":
            raise ManifestError(f"Backend dependency readiness is missing or not READY: {name}")
        if str(item.get("integration", "")).upper() != "REAL_HTTP":
            raise ManifestError(f"formal Backend dependency must use REAL_HTTP: {name}")

    checked_observers: dict[str, str] = {}
    observer_names = ("rag", "llm", "safety") if "safety" in observer_endpoints else ("rag", "llm")
    for name in observer_names:
        endpoint = observer_endpoints.get(name)
        if not isinstance(endpoint, str) or not is_loopback_url(endpoint):
            raise ManifestError(f"{name} observer endpoint must be HTTP loopback")
        checked_observers[name] = endpoint.rstrip("/")

    actual_timestamp = _iso_timestamp(timestamp)
    actual_run_id = run_id or create_run_id(timestamp=timestamp if isinstance(timestamp, datetime) else None, entropy=entropy)
    try:
        validate_run_id(actual_run_id)
    except Exception as exc:
        raise ManifestError(f"run_id is invalid: {exc}") from exc
    try:
        validate_cat_d3_compatibility_gate(cat_d3_compatibility_gate, run_id=actual_run_id)
    except (CatCompatibilityGateError, AttributeError, TypeError) as exc:
        raise ManifestError("formal manifest CAT D3 compatibility gate is missing or invalid") from exc
    gate_evidence = dict(cat_d3_compatibility_gate_evidence)
    if (
        set(gate_evidence) != {"path", "sha256"}
        or gate_evidence.get("path") != "preflight/cat-d3-compatibility-gate.json"
        or not isinstance(gate_evidence.get("sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", gate_evidence["sha256"])
    ):
        raise ManifestError("formal manifest CAT D3 compatibility gate evidence reference is invalid")
    root = Path(repo_root).resolve()
    verify_accepted_baseline(root)
    git = git_snapshot(root)
    manifest: dict[str, Any] = {
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": actual_run_id,
        "run_timestamp": actual_timestamp,
        **git,
        "evaluation_source_commit": git["git_commit"],
        "accepted_tags": [ACCEPTED_D4_3A_TAG],
        "accepted_d4_3a_commit": ACCEPTED_D4_3A_COMMIT,
        "accepted_product_baseline_commit": ACCEPTED_D4_3A_COMMIT,
        "profile_source_copy_commit": PROFILE_SOURCE_COPY_COMMIT,
        "human_gold_packet_id": packet.packet_id,
        "human_gold_packet_hash": packet.packet_hash,
        "human_gold_packet_file_sha256": packet.raw_file_sha256,
        "source_provenance": packet.provenance_dict()["source_binding"],
        "case_manifest_hash": case_manifest["manifest_hash"],
        "approved_case_ids": list(case_manifest["approved_case_ids"]),
        "citation_reference_case_ids": list(case_manifest["citation_reference_case_ids"]),
        "runtime_preflight_hash": runtime.preflight_hash,
        "runtime_expected_identity": deepcopy(EXPECTED_RUNTIME_IDENTITY),
        "runtime_observed_identity": deepcopy(dict(runtime.identity)),
        "runtime_endpoint_health_identity": runtime_endpoint,
        "backend_dependency_identity": dependencies,
        "managed_service_identity": deepcopy(dict(managed_service_identity or {
            "owner": "CALLER",
            "cleanup_policy": "CALLER_MANAGED",
            "runtime_process_owned": False,
            "services": [],
        })),
        "backend_identity": {
            "base_url": backend_base_url.rstrip("/"),
            "method": "POST",
            "route": FORMAL_ROUTE,
            "transport": "CANONICAL_HTTP",
            "module_endpoints_loopback_only": True,
        },
        "observer_endpoints": checked_observers,
        "rag_corpus_identity": {
            "corpus_id": corpus_manifest["corpus_id"],
            "corpus_hash": corpus_manifest["corpus_hash"],
            "evidence_ids": list(corpus_manifest["evidence_ids"]),
            "rag_service": rag_service,
            "source_packet_id": packet.packet_id,
            "source_packet_hash": packet.packet_hash,
        },
        "safety_identity": {
            "source": "canonical Backend support pipeline",
            "integration": dependencies["safety"]["integration"],
            "status": dependencies["safety"]["status"],
        },
        "cat_d3_compatibility_gate": deepcopy(dict(cat_d3_compatibility_gate)),
        "cat_d3_compatibility_gate_evidence": gate_evidence,
        "evaluation_mode": "FORMAL_PRODUCT_EVALUATION",
        "retry_policy": {"max_retries": 0, "non_idempotent_post_retries": 0},
        "network_policy": "LOOPBACK_ONLY",
        "network_observation": runtime.network_observation,
        "configuration_audit": {
            "expected": {
                "route": FORMAL_ROUTE,
                "real_student_data": False,
                "cloud_fallback": False,
                "retry_policy": {"max_retries": 0, "non_idempotent_post_retries": 0},
                "corpus_hash": corpus_manifest["corpus_hash"],
                "backend_dependencies": dependencies,
            },
            "unexpected": sorted(set(unexpected_configuration)),
        },
        "synthetic_only": True,
        "real_student_data": False,
        "cloud_fallback": False,
        "formal_product_requests_allowed": True,
        "d4_4_started": False,
    }
    manifest["manifest_hash"] = _canonical_hash(manifest, self_field="manifest_hash")
    verify_formal_manifest(manifest, packet=packet, case_manifest=case_manifest)
    return manifest


def verify_case_manifest(manifest: Mapping[str, Any], *, packet: ApprovedPacket | None = None) -> bool:
    if manifest.get("schema_version") != CASE_SCHEMA_VERSION:
        raise ManifestError("case manifest schema_version mismatch")
    if manifest.get("manifest_hash") != _canonical_hash(manifest, self_field="manifest_hash"):
        raise ManifestError("case manifest canonical hash mismatch")
    ids = manifest.get("approved_case_ids")
    cases = manifest.get("cases")
    if not isinstance(ids, list) or not isinstance(cases, list) or len(ids) != APPROVED_ANSWERABILITY_CASES or len(cases) != APPROVED_ANSWERABILITY_CASES:
        raise ManifestError("case manifest must contain exactly 12 cases")
    if len(set(ids)) != len(ids) or ids != [case.get("case_id") for case in cases]:
        raise ManifestError("case manifest case IDs are missing, duplicated, or reordered")
    if packet is not None:
        expected_ids = [str(case["case_id"]) for case in packet.answerability_cases]
        if ids != expected_ids or manifest.get("source_packet_hash") != packet.packet_hash:
            raise ManifestError("case manifest does not bind the approved Human Gold cases")
    return True


def verify_corpus_manifest(manifest: Mapping[str, Any], *, packet: ApprovedPacket | None = None) -> bool:
    if manifest.get("schema_version") != CORPUS_SCHEMA_VERSION:
        raise ManifestError("corpus manifest schema_version mismatch")
    if manifest.get("corpus_hash") != _canonical_hash(manifest, self_field="corpus_hash"):
        raise ManifestError("corpus manifest canonical hash mismatch")
    ids = manifest.get("evidence_ids")
    evidence = manifest.get("evidence")
    if not isinstance(ids, list) or not isinstance(evidence, list) or ids != [item.get("chunk_id") for item in evidence]:
        raise ManifestError("corpus evidence identity list is invalid")
    if len(set(ids)) != len(ids) or len(evidence) != manifest.get("evidence_count"):
        raise ManifestError("corpus contains duplicate evidence identities or invalid count")
    records = manifest.get("rag_embedding_records")
    if not isinstance(records, list) or ids != [item.get("chunk_id") for item in records]:
        raise ManifestError("RAG projection identities differ from the evidence manifest")
    aliases = manifest.get("evidence_aliases")
    if not isinstance(aliases, list):
        raise ManifestError("corpus source evidence mapping is missing")
    alias_source_ids = [item.get("source_chunk_id") for item in aliases]
    mapped_projection_ids = sorted(
        projection_id
        for item in aliases
        for projection_id in item.get("evaluation_chunk_ids", ())
    )
    if alias_source_ids != manifest.get("source_evidence_ids") or mapped_projection_ids != sorted(ids):
        raise ManifestError("corpus source-to-evaluation evidence mapping is invalid")
    for projection, record in zip(evidence, records, strict=True):
        source_chunk_id = projection.get("source_chunk_id")
        if projection.get("evidence", {}).get("chunk_id") != source_chunk_id:
            raise ManifestError("corpus projection does not preserve the source Human Gold chunk ID")
        if record.get("metadata", {}).get("source_chunk_id") != source_chunk_id:
            raise ManifestError("RAG record lost its source Human Gold chunk ID")
    if packet is not None:
        if manifest.get("source_packet_id") != packet.packet_id or manifest.get("source_packet_hash") != packet.packet_hash:
            raise ManifestError("corpus manifest does not bind the approved packet")
        if manifest.get("source_evidence_ids") != list(approved_evidence_ids(packet)):
            raise ManifestError("corpus source evidence IDs do not equal the approved packet allowlist")
    return True


def corpus_projection_source_map(manifest: Mapping[str, Any]) -> dict[str, str]:
    """Map temporary RAG chunk IDs back to the unmodified packet IDs."""

    return {
        str(item["chunk_id"]): str(item["source_chunk_id"])
        for item in manifest.get("evidence", ())
        if isinstance(item, Mapping)
        and isinstance(item.get("chunk_id"), str)
        and isinstance(item.get("source_chunk_id"), str)
    }


def verify_formal_manifest(
    manifest: Mapping[str, Any],
    *,
    packet: ApprovedPacket | None = None,
    case_manifest: Mapping[str, Any] | None = None,
) -> bool:
    schema_version = manifest.get("schema_version")
    if schema_version not in {RUN_SCHEMA_VERSION_V1, RUN_SCHEMA_VERSION}:
        raise ManifestError("formal manifest schema_version mismatch")
    if manifest.get("manifest_hash") != _canonical_hash(manifest, self_field="manifest_hash"):
        raise ManifestError("formal manifest canonical hash mismatch")
    try:
        validate_run_id(str(manifest.get("run_id", "")))
    except Exception as exc:
        raise ManifestError(f"formal manifest run_id invalid: {exc}") from exc
    if schema_version == RUN_SCHEMA_VERSION:
        gate = manifest.get("cat_d3_compatibility_gate")
        if not isinstance(gate, Mapping):
            raise ManifestError("formal manifest CAT D3 compatibility gate is missing")
        try:
            validate_cat_d3_compatibility_gate(gate, run_id=str(manifest.get("run_id", "")))
        except (CatCompatibilityGateError, AttributeError, TypeError) as exc:
            raise ManifestError("formal manifest CAT D3 compatibility gate is invalid") from exc
        gate_evidence = manifest.get("cat_d3_compatibility_gate_evidence")
        if (
            not isinstance(gate_evidence, Mapping)
            or set(gate_evidence) != {"path", "sha256"}
            or gate_evidence.get("path") != "preflight/cat-d3-compatibility-gate.json"
            or not isinstance(gate_evidence.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", gate_evidence["sha256"])
        ):
            raise ManifestError("formal manifest CAT D3 compatibility gate evidence reference is invalid")
    if manifest.get("human_gold_packet_id") != APPROVED_PACKET_ID or manifest.get("human_gold_packet_hash") != APPROVED_PACKET_HASH:
        raise ManifestError("formal manifest Human Gold identity mismatch")
    runtime_health = manifest.get("runtime_endpoint_health_identity")
    if not isinstance(runtime_health, Mapping) or runtime_health.get("readiness") != "pass" or runtime_health.get("cloud_fallback") is not False:
        raise ManifestError("formal manifest does not contain a live loopback Runtime ready observation")
    dependencies = manifest.get("backend_dependency_identity")
    if not isinstance(dependencies, Mapping):
        raise ManifestError("formal manifest is missing Backend dependency identity")
    for name in ("rag", "llm_runtime", "cat", "safety"):
        item = dependencies.get(name)
        if not isinstance(item, Mapping) or str(item.get("status", "")).upper() != "READY":
            raise ManifestError(f"formal manifest Backend dependency is not READY: {name}")
        if str(item.get("integration", "")).upper() != "REAL_HTTP":
            raise ManifestError(f"formal manifest Backend dependency is not REAL_HTTP: {name}")
    lifecycle = manifest.get("managed_service_identity")
    if not isinstance(lifecycle, Mapping) or not isinstance(lifecycle.get("runtime_process_owned"), bool) or not isinstance(lifecycle.get("services"), list):
        raise ManifestError("formal manifest has invalid managed service ownership")
    if lifecycle.get("owner") == "D4_EVALUATION_HARNESS":
        if lifecycle.get("runtime_process_owned") is not True:
            raise ManifestError("managed formal manifest must bind Runtime to the evaluation supervisor")
        service_names = {
            str(item.get("name"))
            for item in lifecycle.get("services", ())
            if isinstance(item, Mapping)
        }
        required_services = {
            "d4-mysql", "d4-opa", "d4-safety", "d4-ollama", "d4-runtime", "d4-cat",
            "d4-backend", "d4-rag", "d4-rag-observer", "d4-llm-observer",
        }
        observer_endpoints = manifest.get("observer_endpoints")
        if isinstance(observer_endpoints, Mapping) and "safety" in observer_endpoints:
            required_services.add("d4-safety-observer")
        if not required_services <= service_names:
            raise ManifestError("managed formal manifest omits one or more supervisor-owned services")
    if manifest.get("backend_identity", {}).get("route") != FORMAL_ROUTE:
        raise ManifestError("formal manifest route is not the canonical Backend endpoint")
    if manifest.get("retry_policy") != {"max_retries": 0, "non_idempotent_post_retries": 0}:
        raise ManifestError("formal manifest must prohibit automatic retries")
    if manifest.get("synthetic_only") is not True or manifest.get("real_student_data") is not False or manifest.get("cloud_fallback") is not False:
        raise ManifestError("formal manifest crosses a fixed D4 data/runtime boundary")
    if not _RUN_COMMIT_RE.fullmatch(str(manifest.get("git_commit", ""))):
        raise ManifestError("formal manifest git_commit is malformed")
    if manifest.get("accepted_tags") != [ACCEPTED_D4_3A_TAG] or manifest.get("accepted_d4_3a_commit") != ACCEPTED_D4_3A_COMMIT:
        raise ManifestError("formal manifest accepted baseline is invalid")
    provenance_fields = {
        "evaluation_source_commit",
        "accepted_product_baseline_commit",
        "profile_source_copy_commit",
    }
    present_provenance_fields = provenance_fields & set(manifest)
    if present_provenance_fields and present_provenance_fields != provenance_fields:
        raise ManifestError("formal manifest provenance fields are incomplete")
    if present_provenance_fields:
        if manifest.get("evaluation_source_commit") != manifest.get("git_commit"):
            raise ManifestError("evaluation_source_commit must match the harness git_commit")
        if manifest.get("accepted_product_baseline_commit") != ACCEPTED_D4_3A_COMMIT:
            raise ManifestError("accepted_product_baseline_commit does not match the accepted D4-3A tag")
        if manifest.get("profile_source_copy_commit") != PROFILE_SOURCE_COPY_COMMIT:
            raise ManifestError("profile_source_copy_commit does not match the fixed profile source copy")
    runtime_audit = manifest.get("runtime_audit_evidence")
    if runtime_audit is not None:
        before = runtime_audit.get("before_cases") if isinstance(runtime_audit, Mapping) else None
        if (
            not isinstance(before, Mapping)
            or before.get("run_id") != manifest.get("run_id")
            or before.get("phase") != "BEFORE_CASES"
            or before.get("path") != "runtime-audit-before-cases.json"
            or not isinstance(before.get("sha256"), str)
            or not _SHA256_RE.fullmatch(before.get("sha256", ""))
        ):
            raise ManifestError("formal manifest Runtime audit evidence is not correctly bound to this run")
    if packet is not None:
        packet.verify_unchanged()
        if manifest.get("human_gold_packet_file_sha256") != packet.raw_file_sha256:
            raise ManifestError("formal manifest approved packet file hash mismatch")
    if case_manifest is not None:
        verify_case_manifest(case_manifest, packet=packet)
        if manifest.get("case_manifest_hash") != case_manifest.get("manifest_hash"):
            raise ManifestError("formal manifest case manifest hash mismatch")
        if manifest.get("approved_case_ids") != case_manifest.get("approved_case_ids"):
            raise ManifestError("formal manifest approved case IDs mismatch")
    return True


def add_manifest_hash(value: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    """Copy a schema object and add its canonical self-hash."""

    if field in value:
        raise ManifestError(f"{field} must not be supplied before hashing")
    result = deepcopy(dict(value))
    result[field] = _canonical_hash(result, self_field=field)
    return result
