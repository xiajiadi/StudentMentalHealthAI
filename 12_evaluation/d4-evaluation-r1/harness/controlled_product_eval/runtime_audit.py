"""Run-bound, allowlisted Runtime/Ollama/GPU evidence capture."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import jsonschema

from .manifest import EXPECTED_RUNTIME_IDENTITY, RuntimePreflight

OLLAMA_ENDPOINT = "http://127.0.0.1:11437"
RUNTIME_AUDIT_SCHEMA = "d4-runtime-audit-evidence.v1"
_PHASES = {"BEFORE_CASES", "AFTER_CASES"}
_RUNTIME_AUDIT_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "spec" / "d4_runtime_audit_evidence.schema.json"


class RuntimeAuditError(RuntimeError):
    """A required run-bound Runtime evidence field could not be captured."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _get_json(url: str) -> Mapping[str, Any]:
    with httpx.Client(timeout=5.0, follow_redirects=False, trust_env=False) as client:
        response = client.get(url)
        response.raise_for_status()
        value = response.json()
    if not isinstance(value, Mapping):
        raise ValueError("Runtime endpoint returned a non-object")
    return value


def _positive_pid(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _run_command(arguments: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
        check=False,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_file_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _log_file_evidence(value: Any, evidence_root: Path) -> dict[str, Any]:
    if not isinstance(value, str) or not value:
        return {"status": "NOT_RECORDED", "path": None, "size_bytes": None, "sha256": None, "modified_at": None}
    candidate = Path(value)
    try:
        resolved = candidate.resolve(strict=True)
        relative = resolved.relative_to(evidence_root.resolve()).as_posix()
        if not resolved.is_file():
            raise OSError("log path is not a file")
        stat = resolved.stat()
        return {
            "status": "CAPTURED",
            "path": relative,
            "size_bytes": stat.st_size,
            "sha256": _sha256_file(resolved),
            "modified_at": _utc_file_time(stat.st_mtime),
        }
    except (OSError, ValueError):
        return {"status": "UNAVAILABLE", "path": None, "size_bytes": None, "sha256": None, "modified_at": None}


def _service_rows(value: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    services = value.get("services")
    if not isinstance(services, Sequence) or isinstance(services, (str, bytes)):
        return {}
    return {
        str(row.get("name")): row
        for row in services
        if isinstance(row, Mapping) and isinstance(row.get("name"), str)
    }


def _project_model_rows(value: Mapping[str, Any], *, model_name: str) -> list[dict[str, Any]]:
    models = value.get("models")
    if not isinstance(models, Sequence) or isinstance(models, (str, bytes)):
        raise ValueError("Ollama model collection is missing")
    result: list[dict[str, Any]] = []
    for item in models:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name") or item.get("model")
        if name != model_name:
            continue
        projected: dict[str, Any] = {"name": model_name}
        digest = item.get("digest")
        if isinstance(digest, str) and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest):
            projected["digest"] = digest
        for field in ("size",):
            number = item.get(field)
            if isinstance(number, int) and not isinstance(number, bool) and number >= 0:
                projected[field] = number
        number = item.get("size_vram")
        if isinstance(number, int) and not isinstance(number, bool) and number >= 0:
            projected["size_vram_bytes"] = number
        result.append(projected)
    return result


def _parse_csv_rows(value: str) -> list[list[str]]:
    return [[field.strip() for field in row] for row in csv.reader(io.StringIO(value)) if row]


def _integer(value: str) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _gpu_snapshot(
    *,
    ollama_process_tree_pids: set[int],
    command_runner: Callable[..., subprocess.CompletedProcess[str]],
    which: Callable[[str], str | None],
) -> dict[str, Any]:
    executable = which("nvidia-smi")
    if not executable:
        return {
            "status": "COMMAND_UNAVAILABLE",
            "devices": [],
            "ollama_compute_processes": [],
            "ollama_process_visible": False,
        }

    def query(arguments: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return command_runner([executable, *arguments], timeout=10.0)
        except (OSError, subprocess.SubprocessError):
            return subprocess.CompletedProcess([executable, *arguments], 1, "", "")

    device_result = query(
        [
            "--query-gpu=name,uuid,memory.total,memory.used,memory.free",
            "--format=csv,noheader,nounits",
        ]
    )
    process_result = query(
        [
            "--query-compute-apps=pid,process_name,used_memory",
            "--format=csv,noheader,nounits",
        ]
    )
    if device_result.returncode != 0:
        return {
            "status": "COMMAND_FAILED",
            "devices": [],
            "ollama_compute_processes": [],
            "ollama_process_visible": False,
            "exit_code": int(device_result.returncode),
        }

    devices: list[dict[str, Any]] = []
    for row in _parse_csv_rows(device_result.stdout):
        if len(row) < 5:
            continue
        devices.append(
            {
                "name": row[0][:100],
                "uuid": row[1][:80],
                "memory_total_mib": _integer(row[2]),
                "memory_used_mib": _integer(row[3]),
                "memory_free_mib": _integer(row[4]),
            }
        )

    processes: list[dict[str, Any]] = []
    if process_result.returncode == 0:
        for row in _parse_csv_rows(process_result.stdout):
            if len(row) < 3:
                continue
            pid = _integer(row[0])
            if pid is None or pid not in ollama_process_tree_pids:
                continue
            process_name = Path(row[1]).name[:120]
            processes.append(
                {
                    "pid": pid,
                    "process_name": process_name,
                    "used_memory_mib": _integer(row[2]),
                }
            )
    return {
        "status": "CAPTURED",
        "devices": devices,
        "ollama_compute_processes": processes,
        "ollama_process_visible": bool(processes),
        "compute_process_status": "CAPTURED" if process_result.returncode == 0 else "COMMAND_FAILED",
        **({"compute_process_exit_code": int(process_result.returncode)} if process_result.returncode != 0 else {}),
    }


def capture_runtime_audit_snapshot(
    *,
    run_id: str,
    phase: str,
    runtime_preflight: Mapping[str, Any] | RuntimePreflight,
    managed_service_identity: Mapping[str, Any],
    evidence_root: str | Path,
    captured_at: str | None = None,
    get_json: Callable[[str], Mapping[str, Any]] = _get_json,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = _run_command,
    which: Callable[[str], str | None] = shutil.which,
) -> dict[str, Any]:
    """Capture only allowlisted process, API, log-hash, and GPU evidence."""

    if phase not in _PHASES:
        raise RuntimeAuditError("Runtime audit phase is not allow-listed")
    runtime = (
        runtime_preflight
        if isinstance(runtime_preflight, RuntimePreflight)
        else RuntimePreflight.from_mapping(runtime_preflight, require_live_binding=True)
    )
    binding = runtime.execution_binding
    if not isinstance(binding, Mapping):
        raise RuntimeAuditError("live Runtime execution binding is unavailable")
    if binding.get("attempt_id") != run_id:
        raise RuntimeAuditError("Runtime execution binding does not match the formal run ID")
    if binding.get("provider_endpoint") != OLLAMA_ENDPOINT:
        raise RuntimeAuditError("Runtime audit is restricted to the accepted Ollama endpoint")
    if runtime.identity.get("endpoint") != OLLAMA_ENDPOINT:
        raise RuntimeAuditError("Runtime identity endpoint differs from the accepted Ollama endpoint")

    runtime_pid = binding.get("runtime_pid")
    runtime_launcher_pid = binding.get("runtime_launcher_pid")
    ollama_pid = binding.get("ollama_pid")
    runtime_tree = binding.get("runtime_process_tree_pids")
    ollama_tree = binding.get("ollama_process_tree_pids")
    if not all(_positive_pid(item) for item in (runtime_pid, runtime_launcher_pid, ollama_pid)):
        raise RuntimeAuditError("Runtime/Ollama process identity is incomplete")
    if not isinstance(runtime_tree, Sequence) or isinstance(runtime_tree, (str, bytes)):
        raise RuntimeAuditError("Runtime process tree identity is missing")
    if not isinstance(ollama_tree, Sequence) or isinstance(ollama_tree, (str, bytes)):
        raise RuntimeAuditError("Ollama process tree identity is missing")
    runtime_tree_pids = sorted({int(item) for item in runtime_tree if _positive_pid(item)})
    ollama_tree_pids = sorted({int(item) for item in ollama_tree if _positive_pid(item)})
    if runtime_pid not in runtime_tree_pids or runtime_launcher_pid not in runtime_tree_pids or ollama_pid not in ollama_tree_pids:
        raise RuntimeAuditError("Runtime/Ollama process IDs do not match their captured trees")

    service_rows = _service_rows(managed_service_identity)
    runtime_service = service_rows.get("d4-runtime")
    ollama_service = service_rows.get("d4-ollama")
    if not isinstance(runtime_service, Mapping) or not isinstance(ollama_service, Mapping):
        raise RuntimeAuditError("managed Runtime/Ollama process records are missing")
    if runtime_service.get("pid") != runtime_launcher_pid or ollama_service.get("pid") != ollama_pid:
        raise RuntimeAuditError("managed Runtime/Ollama PID differs from the live attestation")

    root = Path(evidence_root).resolve()
    model_name = str(runtime.identity.get("model", ""))
    expected_digest = str(runtime.identity.get("digest", ""))
    try:
        version_response = get_json(OLLAMA_ENDPOINT + "/api/version")
        tags_response = get_json(OLLAMA_ENDPOINT + "/api/tags")
        running_response = get_json(OLLAMA_ENDPOINT + "/api/ps")
        version = version_response.get("version")
        catalog = _project_model_rows(tags_response, model_name=model_name)
        running = _project_model_rows(running_response, model_name=model_name)
        digest = next((item.get("digest") for item in catalog if item.get("digest") == expected_digest), None)
        api_status = (
            "PASS"
            if version == runtime.identity.get("ollama_version") and digest == expected_digest
            else "IDENTITY_MISMATCH"
        )
        running_status = "LOADED" if running else "NOT_LOADED"
    except (OSError, ValueError, httpx.HTTPError):
        version = None
        catalog = []
        running = []
        digest = None
        api_status = "UNAVAILABLE"
        running_status = "UNKNOWN"

    runtime_log = _log_file_evidence(runtime_service.get("log_path"), root)
    runtime_stderr = _log_file_evidence(runtime_service.get("stderr_log_path"), root)
    ollama_log = _log_file_evidence(ollama_service.get("log_path"), root)
    ollama_stderr = _log_file_evidence(ollama_service.get("stderr_log_path"), root)
    gpu = _gpu_snapshot(
        ollama_process_tree_pids=set(ollama_tree_pids),
        command_runner=command_runner,
        which=which,
    )

    return {
        "schema_version": RUNTIME_AUDIT_SCHEMA,
        "run_id": run_id,
        "phase": phase,
        "captured_at": captured_at or _now(),
        "runtime_preflight_hash": runtime.preflight_hash,
        "runtime": {
            "pid": int(runtime_pid),
            "launcher_pid": int(runtime_launcher_pid),
            "process_tree_pids": runtime_tree_pids,
            "started_at": binding.get("runtime_started_at"),
            "executable_sha256": binding.get("runtime_executable_sha256"),
            "source_tree_sha256": binding.get("runtime_source_tree_sha256"),
            "stdout_log": runtime_log,
            "stderr_log": runtime_stderr,
        },
        "ollama": {
            "pid": int(ollama_pid),
            "process_tree_pids": ollama_tree_pids,
            "started_at": binding.get("ollama_started_at"),
            "executable_sha256": binding.get("ollama_executable_sha256"),
            "endpoint": OLLAMA_ENDPOINT,
            "api_status": api_status,
            "version": version,
            "model": model_name,
            "expected_digest": expected_digest,
            "observed_digest": digest,
            "catalog_status": "PASS" if digest == expected_digest else "MISMATCH_OR_MISSING",
            "running_model_status": running_status,
            "running_models": running,
            "stdout_log": ollama_log,
            "stderr_log": ollama_stderr,
        },
        "gpu": gpu,
    }


def runtime_audit_pre_case_issues(snapshot: Mapping[str, Any], *, run_id: str) -> tuple[str, ...]:
    """Gate formal requests on identity, API, and Runtime stdout/stderr evidence."""

    issues: list[str] = []
    if snapshot.get("schema_version") != RUNTIME_AUDIT_SCHEMA or snapshot.get("run_id") != run_id:
        issues.append("RUNTIME_AUDIT_RUN_BINDING_INVALID")
    if snapshot.get("phase") != "BEFORE_CASES":
        issues.append("RUNTIME_AUDIT_PHASE_INVALID")
    runtime = snapshot.get("runtime")
    runtime = runtime if isinstance(runtime, Mapping) else {}
    if not all(
        _positive_pid(runtime.get(field))
        for field in ("pid", "launcher_pid")
    ):
        issues.append("RUNTIME_PROCESS_IDENTITY_MISSING")
    for service_name, service in (("RUNTIME", runtime), ("OLLAMA", snapshot.get("ollama"))):
        service = service if isinstance(service, Mapping) else {}
        for field in ("stdout_log", "stderr_log"):
            item = service.get(field)
            if not isinstance(item, Mapping) or item.get("status") != "CAPTURED":
                issues.append(f"{service_name}_PROCESS_LOGS_NOT_CAPTURED")
                break
    ollama = snapshot.get("ollama")
    ollama = ollama if isinstance(ollama, Mapping) else {}
    if not _positive_pid(ollama.get("pid")):
        issues.append("OLLAMA_PROCESS_IDENTITY_MISSING")
    if (
        ollama.get("api_status") != "PASS"
        or ollama.get("catalog_status") != "PASS"
        or ollama.get("version") != EXPECTED_RUNTIME_IDENTITY["ollama_version"]
        or ollama.get("model") != EXPECTED_RUNTIME_IDENTITY["model"]
        or ollama.get("expected_digest") != EXPECTED_RUNTIME_IDENTITY["digest"]
        or ollama.get("observed_digest") != EXPECTED_RUNTIME_IDENTITY["digest"]
    ):
        issues.append("OLLAMA_API_OR_MODEL_IDENTITY_NOT_PASS")
    if ollama.get("endpoint") != OLLAMA_ENDPOINT:
        issues.append("OLLAMA_ACCEPTED_ENDPOINT_MISMATCH")
    return tuple(issues)


def validate_runtime_audit_snapshot(snapshot: Mapping[str, Any]) -> None:
    schema = json.loads(_RUNTIME_AUDIT_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
    )
    validator.validate(dict(snapshot))


def write_runtime_audit_snapshot(path: str | Path, snapshot: Mapping[str, Any]) -> tuple[Path, str]:
    validate_runtime_audit_snapshot(snapshot)
    payload = (json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return target, "sha256:" + hashlib.sha256(payload).hexdigest()
