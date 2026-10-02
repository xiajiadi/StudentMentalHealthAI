"""Fixed, evidence-bound service profiles for the D4-3B local evaluation stack."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import httpx

from .environment_profiles import D4_TASK_TOOLS_ROOT, EVALUATION_PROCESS_USERNAME, GIT_EXECUTABLE
from .manifest import (
    ACCEPTED_D4_3A_COMMIT,
    EXPECTED_RUNTIME_IDENTITY,
    PROFILE_SOURCE_COPY_COMMIT,
    RuntimePreflight,
    build_runtime_preflight,
    canonical_json,
    write_json_once,
)
from .network_integrity import FORMAL_DATA_PLANE_PORTS, NetworkIntegrityError, capture_data_plane_network
from .process_lifecycle import LifecycleError, ProcessSpec, ProcessSupervisor, build_child_environment, redact_argv


CAT_PYTHON = D4_TASK_TOOLS_ROOT / "venvs" / "cat-engine-r1-reconciled" / "Scripts" / "python.exe"
CAT_LOCK = D4_TASK_TOOLS_ROOT / "cat-env-lock-r1" / "uv.lock"
CAT_LOCK_SHA256 = "82170ccd6fd6ee6e408288b36445268edc157f73e37d1658552ee06ea9fbf96b"
CAT_PYPROJECT_SHA256 = "20356a13f37ddcf8845d6c7c8d0c1c46290323d41bdea8e154ff91db0261a613"
CAT_CONFIG_SHA256 = "78f9922930e40a8f9f8c436a644e5c7b9548d9d4f32377d30f143619f3f09e8a"
CAT_ITEM_BANK_SHA256 = "b24331693d621d65c3acf0cafbf55960fb24c0a14aa852a3bba3aa9e3cb90216"

SAFETY_PYTHON = D4_TASK_TOOLS_ROOT / "venvs" / "safety-r1" / "Scripts" / "python.exe"
SAFETY_LOCK_SHA256 = "5932ed6da809f51f39281fdfb31f393a44f40e3e47f9a1243e3e77af4d4024e0"
SAFETY_PYPROJECT_SHA256 = "926bdcc895913cdc9efa188c381a46ca5602a36b794539f9cb5f66d317c949cf"
HF_CACHE = Path(r"D:\Dev\caches\huggingface")

OPA_EXECUTABLE = Path(r"D:\Dev\tools\opa\v1.20.2\opa.exe")
OPA_EXECUTABLE_SHA256 = "e2f2e2b735ab98f316171ca47a6b352288cdeb5a616e31aa16335b8934748453"
OPA_VERSION = "1.20.2"
OPA_POLICY_SHA256 = "55c5465ad44170af"

OLLAMA_EXECUTABLE = Path(
    r"D:\Dev\tools\StudentMentalHealthAI\gpu-acceptance\ollama-0.33.3\ollama.exe"
)
OLLAMA_EXECUTABLE_SHA256 = "e4fe6bd835fe146659f5c969dccaff2e25a9de63d90ee204ca5d11b9034b0ca5"
OLLAMA_MODELS = Path(r"D:\Dev\tools\StudentMentalHealthAI\gpu-acceptance\models")
OLLAMA_MODEL = "qwen2.5:7b-instruct-q4_K_M"
OLLAMA_MODEL_DIGEST = "845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e"
OLLAMA_MANIFEST = (
    OLLAMA_MODELS
    / "manifests"
    / "registry.ollama.ai"
    / "library"
    / "qwen2.5"
    / "7b-instruct-q4_K_M"
)

RUNTIME_PYTHON = D4_TASK_TOOLS_ROOT / "venvs" / "runtime-r1" / "Scripts" / "python.exe"
RUNTIME_BASE_PYTHON = Path(r"D:\Dev\pythons\cpython-3.12.13-windows-x86_64-none\python.exe")
RUNTIME_BASE_PYTHON_ARGV0 = Path(r"D:\Dev\pythons\cpython-3.12-windows-x86_64-none\python.exe")
RUNTIME_VENV_PYTHON_SHA256 = "d944dbfda041cc07763560846c5397f46d75c1e84eeeda7814ae54eada846479"
RUNTIME_BASE_PYTHON_SHA256 = "d8e3f0adf246db00358c0c4ed349cf714898178f9558fb0e944f79f5c07f8eaa"
RUNTIME_BASE_PYTHON_ARGV0_SHA256 = "d8e3f0adf246db00358c0c4ed349cf714898178f9558fb0e944f79f5c07f8eaa"
RUNTIME_SOURCE_ROOT = (
    D4_TASK_TOOLS_ROOT
    / "formal-run-r1-20260930T021551Z"
    / "runtime"
    / "app-root"
    / "06_llm-runtime"
)
RUNTIME_RECONSTRUCTION_ROOT = Path(r"D:\Projects\StudentMentalHealthAI-runtime-reconstruction")
RUNTIME_RECONSTRUCTION_COMMIT = "2972be77e537ef03033332039a6ed0eed8e451ef"
RUNTIME_RECONSTRUCTION_LOCK_SHA256 = "bb2ea46b95c05fd17203bc95c062f165da4fa9a2339c0c47a984d2e384b4cea6"
RUNTIME_LOCK_SHA256 = "93012012fe86870d5d7e683cd0b2cc7cbb55834d308a2d348517902fc51349a7"
RUNTIME_CONFIG_SHA256 = "03e77baf90a85d413f4e4934b82e5ede0665a5ac10ff166856e6689d91cde24a"
RUNTIME_MODELS_CONFIG_SHA256 = "4cfd81ff3694b602d3e8912e8d1105be769167f652322126a52ace8e7f5fcbb8"
RUNTIME_PROFILE_TREE_SHA256 = "62287a726f6e804aa13ecd6cc3b515f7d432e162808bccbe31cc44496b925bac"
RUNTIME_READINESS_REQUEST_TIMEOUT_SECONDS = 15.0
SAFETY_BOOTSTRAP_SCRIPT = Path(__file__).with_name("safety_service_bootstrap.py").resolve()

SERVICE_ENDPOINTS = {
    "d4-mysql": "tcp://127.0.0.1:3307",
    "d4-opa": "http://127.0.0.1:8181/health",
    "d4-safety": "http://127.0.0.1:8190/health/ready",
    "d4-ollama": "http://127.0.0.1:11437/api/version",
    "d4-runtime": "http://127.0.0.1:8160/health/ready",
    "d4-cat": "http://127.0.0.1:8180/health/ready",
    "d4-backend": "http://127.0.0.1:8080/health/ready",
    "d4-rag": "http://127.0.0.1:8170/health",
    "d4-rag-observer": "http://127.0.0.1:8271/health",
    "d4-llm-observer": "http://127.0.0.1:8272/health",
}


class ServiceProfileError(RuntimeError):
    """A fixed D4 service identity or local dependency failed its source gate."""


@dataclass(frozen=True, slots=True)
class ExternalProfileSet:
    profiles: Mapping[str, ProcessSpec]
    source_evidence: Mapping[str, Mapping[str, Any]]
    stale_profiles: Mapping[str, ProcessSpec]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _atomic_replace_json(path: Path, value: Mapping[str, Any]) -> None:
    payload = (canonical_json(value) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _profile_process_identity(
    name: str,
    spec: ProcessSpec,
    identities: Mapping[str, Mapping[str, Any]],
    supervisor: ProcessSupervisor,
) -> Mapping[str, Any]:
    value = identities.get(name)
    if not value:
        raise ServiceProfileError(f"required fixed process is not supervisor-owned: {name}")
    expected_executable = str(spec.executable.resolve())
    expected_argv = [expected_executable, *redact_argv(list(spec.arguments))]
    if (
        value.get("executable") != expected_executable
        or value.get("argv_redacted") != expected_argv
        or value.get("cwd") != str(spec.cwd.resolve())
        or value.get("readiness_url") != spec.readiness_url
        or value.get("ownership") != "D4_EVALUATION_SUPERVISOR_OWNED"
    ):
        raise ServiceProfileError(f"supervisor identity does not match the fixed profile: {name}")
    expected_hash = next(
        (
            str(spec.package_lock_identity[key])
            for key in ("binary_sha256", "python_executable_sha256", "mysql_executable_sha256")
            if spec.package_lock_identity and spec.package_lock_identity.get(key)
        ),
        None,
    )
    if expected_hash and value.get("executable_sha256") != expected_hash:
        raise ServiceProfileError(f"supervisor executable digest does not match the fixed profile: {name}")
    pids = {int(pid) for pid in supervisor.service_process_tree_pids(name)}
    if int(value.get("pid", 0)) not in pids or not pids:
        raise ServiceProfileError(f"fixed process ownership tree is no longer live: {name}")
    return value


def _runtime_listener_process_identity(
    *,
    listener_pid: int,
    launcher_profile: ProcessSpec,
    launcher_identity: Mapping[str, Any],
    diagnostic_path: Path | None = None,
) -> Mapping[str, Any]:
    """Capture the exact CPython listener child and bind it to its owned venv launcher."""

    from .windows_process_identity import (
        capture_process_identity,
        matches_exact_prior_runtime_identity,
    )

    try:
        identity = capture_process_identity(listener_pid, include_parent=True)
    except Exception as exc:
        if diagnostic_path is not None:
            write_json_once(
                diagnostic_path,
                {
                    "schema_version": "d4-runtime-listener-identity.v1",
                    "status": "FAIL",
                    "listener_pid": listener_pid,
                    "capture_error_type": type(exc).__name__,
                },
            )
        raise ServiceProfileError(
            f"RUNTIME_LISTENER_IDENTITY_CAPTURE_FAILED:{type(exc).__name__}"
        ) from None
    parent = identity.get("parent_identity")
    launcher_pid = int(launcher_identity.get("pid", -2))
    try:
        actual_pid = int(identity.get("pid", -1))
        actual_parent_pid = int(identity.get("parent_pid", -1))
        captured_parent_pid = int(parent.get("pid", -1)) if isinstance(parent, Mapping) else -1
    except (TypeError, ValueError):
        actual_pid = -1
        actual_parent_pid = -1
        captured_parent_pid = -1
    try:
        exact_pair_matches = matches_exact_prior_runtime_identity(identity, launcher_profile)
    except Exception:
        exact_pair_matches = False
    checks = {
        "identity_complete": identity.get("identity_complete") is True,
        "listener_pid_matches": actual_pid == listener_pid,
        "listener_parent_pid_matches_launcher": actual_parent_pid == launcher_pid,
        "captured_parent_pid_matches_launcher": captured_parent_pid == launcher_pid,
        "exact_launcher_listener_profile_matches": exact_pair_matches,
    }
    if diagnostic_path is not None:
        safe_fields = (
            "pid", "parent_pid", "executable", "executable_sha256", "argv_redacted",
            "cwd", "started_at", "capture_errors", "identity_complete",
        )
        parent_summary = (
            {key: parent.get(key) for key in safe_fields if key in parent}
            if isinstance(parent, Mapping)
            else None
        )
        write_json_once(
            diagnostic_path,
            {
                "schema_version": "d4-runtime-listener-identity.v1",
                "status": "PASS" if all(checks.values()) else "FAIL",
                "expected_launcher": {
                    "pid": launcher_pid,
                    "executable": str(launcher_profile.executable.resolve()),
                    "executable_sha256": (launcher_profile.package_lock_identity or {}).get("python_executable_sha256"),
                    "arguments_redacted": [
                        str(launcher_profile.executable.resolve()),
                        *redact_argv(list(launcher_profile.arguments)),
                    ],
                    "cwd": str(launcher_profile.cwd.resolve()),
                },
                "expected_listener": {
                    "pid": listener_pid,
                    "executable": str(RUNTIME_BASE_PYTHON),
                    "executable_sha256": RUNTIME_BASE_PYTHON_SHA256,
                    "argv0_executable": str(RUNTIME_BASE_PYTHON_ARGV0),
                    "argv0_executable_sha256": RUNTIME_BASE_PYTHON_ARGV0_SHA256,
                    "arguments_redacted": [
                        str(RUNTIME_BASE_PYTHON_ARGV0),
                        *redact_argv(list(launcher_profile.arguments)),
                    ],
                    "cwd": str(launcher_profile.cwd.resolve()),
                },
                "checks": checks,
                "listener_identity": {key: identity.get(key) for key in safe_fields if key in identity},
                "parent_process_identity": parent_summary,
            },
        )
    failed_checks = [name for name, passed in checks.items() if not passed]
    if failed_checks:
        raise ServiceProfileError(
            "RUNTIME_LISTENER_IDENTITY_MISMATCH:" + ",".join(failed_checks)
        )
    return identity


async def _get_json(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    try:
        response = await client.get(url)
        if response.status_code != 200:
            raise ServiceProfileError(f"fixed service readiness failed at {urlparse(url).path}")
        value = response.json()
    except ServiceProfileError:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise ServiceProfileError(f"fixed service health response was invalid: {type(exc).__name__}") from None
    if not isinstance(value, dict):
        raise ServiceProfileError("fixed service health response was not a JSON object")
    return value


def _validate_safety_health(safety: Mapping[str, Any]) -> None:
    components = safety.get("components")
    if safety.get("status") != "READY" or not isinstance(components, dict) or not components:
        raise ServiceProfileError("Safety service did not report full readiness")
    if any(not isinstance(item, dict) or item.get("ready") is not True for item in components.values()):
        raise ServiceProfileError("Safety service has an unhealthy mandatory component")
    opa_component = components.get("opa")
    if (
        not isinstance(opa_component, dict)
        or opa_component.get("available") is not True
        or opa_component.get("ready") is not True
        or opa_component.get("version") != OPA_VERSION
    ):
        raise ServiceProfileError("Safety does not report the accepted mandatory OPA policy service")


def _validate_ollama_identity(version: Mapping[str, Any], tags: Mapping[str, Any]) -> dict[str, Any]:
    if version.get("version") != "0.33.3":
        raise ServiceProfileError("Ollama live version does not match the accepted profile")
    models = tags.get("models")
    if not isinstance(models, list):
        raise ServiceProfileError("Ollama model inventory is invalid")
    exact = [item for item in models if isinstance(item, dict) and item.get("name") == OLLAMA_MODEL]
    if len(exact) != 1 or str(exact[0].get("digest", "")).removeprefix("sha256:") != OLLAMA_MODEL_DIGEST:
        raise ServiceProfileError("Ollama model name or digest does not match the accepted identity")
    return exact[0]


def _validate_runtime_identity(
    health_response: Mapping[str, Any], model_inventory: Mapping[str, Any]
) -> None:
    runtime_health = health_response.get("health")
    if health_response.get("status") != "READY" or not isinstance(runtime_health, dict):
        raise ServiceProfileError("Runtime live readiness response is invalid")
    if runtime_health.get("state") != "READY" or runtime_health.get("readiness") != "pass" or runtime_health.get("cloud_fallback") is not False:
        raise ServiceProfileError("Runtime is not exact READY or reports cloud fallback")
    providers = runtime_health.get("providers")
    provider = providers.get("ollama") if isinstance(providers, dict) else None
    if not isinstance(provider, dict) or provider.get("endpoint") != "http://127.0.0.1:11437" or provider.get("readiness") != "pass" or provider.get("version") != "0.33.3":
        raise ServiceProfileError("Runtime provider health does not match the managed Ollama profile")
    health_models = runtime_health.get("models")
    model_health = health_models.get("qwen2.5-7b-instruct-gpu-acceptance") if isinstance(health_models, dict) else None
    if not isinstance(model_health, dict) or model_health.get("provider_model_id") != OLLAMA_MODEL or model_health.get("availability") != "available" or model_health.get("inference_readiness") not in {"ready", "loaded"}:
        raise ServiceProfileError("Runtime model health does not match the managed model")
    entries = model_inventory.get("models")
    if model_inventory.get("cloud_fallback") is not False or not isinstance(entries, list):
        raise ServiceProfileError("Runtime model registry reports fallback or an invalid model list")
    configured = [item for item in entries if isinstance(item, dict) and item.get("provider_model_id") == OLLAMA_MODEL]
    if len(configured) != 1:
        raise ServiceProfileError("Runtime does not contain exactly one accepted Ollama model entry")
    model_entry = configured[0]
    if model_entry.get("expected_digest") != OLLAMA_MODEL_DIGEST or model_entry.get("context_limit") != 8192 or model_entry.get("provider_version") != "0.33.3" or model_entry.get("fallback_eligible") is not False:
        raise ServiceProfileError("Runtime model registry identity differs from the frozen profile")


def _validate_cat_health(cat: Mapping[str, Any], cat_profile: Mapping[str, Any]) -> None:
    if (
        cat.get("status") != "READY"
        or cat.get("service") != "cat"
        or cat.get("provider") != "adaptivetesting"
        or cat.get("provider_version") != "adaptivetesting-1.2.1"
        or cat.get("item_bank_id") != cat_profile["item_bank_id"]
        or cat.get("item_bank_version") != cat_profile["item_bank_version"]
        or cat.get("config_version") != cat_profile["config_version"]
        or cat.get("synthetic_fixture_only") is not True
    ):
        raise ServiceProfileError("CAT health does not match the accepted synthetic profile")


def _verify_network_ownership(
    supervisor: ProcessSupervisor,
    profiles: Mapping[str, ProcessSpec],
    *,
    include_application_stack: bool,
) -> dict[str, Any]:
    try:
        observation = capture_data_plane_network(
            require_listeners=False,
            owned_pids=supervisor.process_tree_pids(),
        )
    except NetworkIntegrityError as exc:
        raise ServiceProfileError(f"Windows network inventory failed: {type(exc).__name__}") from None
    if observation["status"] != "PASS":
        raise ServiceProfileError("managed stack network integrity failed")
    expected = {
        3307: "d4-mysql",
        8181: "d4-opa",
        8190: "d4-safety",
        11437: "d4-ollama",
        8160: "d4-runtime",
        8180: "d4-cat",
    }
    if include_application_stack:
        expected.update({8080: "d4-backend", 8170: "d4-rag", 8271: "d4-rag-observer", 8272: "d4-llm-observer"})
    listeners_by_port: dict[int, list[dict[str, Any]]] = {}
    for listener in observation["listeners"]:
        listeners_by_port.setdefault(int(listener["port"]), []).append(listener)
    verified: dict[str, int] = {}
    for port, name in expected.items():
        entries = listeners_by_port.get(port, [])
        if len(entries) != 1:
            raise ServiceProfileError(f"fixed listener count mismatch on port {port}")
        listener = entries[0]
        service_pids = supervisor.service_process_tree_pids(name)
        if listener["address"] != "127.0.0.1" or int(listener["pid"]) not in service_pids:
            raise ServiceProfileError(f"fixed listener ownership mismatch on port {port}")
        verified[str(port)] = int(listener["pid"])
    if observation.get("external_established_connections") or observation.get("forbidden_endpoint_connections"):
        raise ServiceProfileError("evaluation-owned process made a forbidden network connection")
    observation["verified_listener_pids"] = verified
    return observation


async def verify_external_service_readiness(
    *,
    supervisor: ProcessSupervisor,
    profiles: Mapping[str, ProcessSpec],
    source_evidence: Mapping[str, Mapping[str, Any]],
    attempt_id: str,
    run_root: Path,
    current_pointer: Path | None = None,
) -> dict[str, Any]:
    """Verify fresh live identities and create an attempt-bound Runtime attestation."""

    identities = {str(row["name"]): row for row in supervisor.identities()}
    for name in ("d4-mysql", "d4-opa", "d4-safety", "d4-ollama", "d4-runtime", "d4-cat"):
        if name not in profiles:
            raise ServiceProfileError(f"required fixed profile is missing: {name}")
        _profile_process_identity(name, profiles[name], identities, supervisor)

    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0), trust_env=False, follow_redirects=False) as client:
        opa_response = await client.get("http://127.0.0.1:8181/health")
        if opa_response.status_code != 200:
            raise ServiceProfileError("OPA live health check failed")

        safety = await _get_json(client, "http://127.0.0.1:8190/health/ready")
        _validate_safety_health(safety)

        ollama_version = await _get_json(client, "http://127.0.0.1:11437/api/version")
        ollama_tags = await _get_json(client, "http://127.0.0.1:11437/api/tags")
        ollama_model_live = _validate_ollama_identity(ollama_version, ollama_tags)

        runtime_response = await _get_json(client, "http://127.0.0.1:8160/health/ready")
        runtime_models = await _get_json(client, "http://127.0.0.1:8160/internal/llm/models")
        _validate_runtime_identity(runtime_response, runtime_models)

        cat = await _get_json(client, "http://127.0.0.1:8180/health/ready")
        _validate_cat_health(cat, source_evidence["cat"])

    runtime_identity = identities["d4-runtime"]
    ollama_identity = identities["d4-ollama"]
    network = _verify_network_ownership(supervisor, profiles, include_application_stack=False)
    listeners = network["verified_listener_pids"]
    runtime_listener = _runtime_listener_process_identity(
        listener_pid=int(listeners["8160"]),
        launcher_profile=profiles["d4-runtime"],
        launcher_identity=runtime_identity,
        diagnostic_path=run_root / "preflight" / "runtime-listener-identity.json",
    )
    runtime_profile = source_evidence["runtime"]
    ollama_profile = source_evidence["ollama"]
    binding = {
        "schema_version": "d4-runtime-live-attestation.v1",
        "attempt_id": attempt_id,
        "observed_at": _now(),
        "runtime_pid": int(runtime_listener["pid"]),
        "runtime_process_tree_pids": sorted(int(pid) for pid in runtime_identity["process_tree_pids"]),
        "runtime_started_at": str(runtime_listener["started_at"]),
        "runtime_executable": str(runtime_listener["executable"]),
        "runtime_executable_sha256": str(runtime_listener["executable_sha256"]),
        "runtime_launcher_pid": int(runtime_identity["pid"]),
        "runtime_launcher_started_at": str(runtime_identity["started_at"]),
        "runtime_launcher_executable": str(runtime_identity["executable"]),
        "runtime_launcher_executable_sha256": str(runtime_identity["executable_sha256"]),
        "runtime_source_tree_sha256": str(runtime_profile["source_tree_sha256"]),
        "runtime_endpoint": "http://127.0.0.1:8160",
        "ollama_pid": int(ollama_identity["pid"]),
        "ollama_process_tree_pids": sorted(int(pid) for pid in ollama_identity["process_tree_pids"]),
        "ollama_started_at": str(ollama_identity["started_at"]),
        "ollama_executable": str(ollama_identity["executable"]),
        "ollama_executable_sha256": str(ollama_identity["executable_sha256"]),
        "provider_endpoint": "http://127.0.0.1:11437",
        "ollama_version": "0.33.3",
        "model": OLLAMA_MODEL,
        "model_digest": OLLAMA_MODEL_DIGEST,
        "num_ctx": 8192,
        "kv_cache_type": "f16",
        "num_parallel": 1,
        "max_loaded_models": 1,
        "output_budget": 768,
        "cloud_fallback": False,
        "network_status": "PASS",
        "network_observation": "OBSERVED_LOOPBACK_ONLY",
        "external_established_connection_count": len(network.get("external_established_connections", [])),
        "forbidden_endpoint_connection_count": len(network.get("forbidden_endpoint_connections", [])),
        "verified_listener_pids": listeners,
        "network_observation_sha256": hashlib.sha256(canonical_json(network).encode("utf-8")).hexdigest(),
    }
    preflight = build_runtime_preflight(
        observed_at=binding["observed_at"],
        identity=EXPECTED_RUNTIME_IDENTITY,
        execution_binding=binding,
    )
    RuntimePreflight.from_mapping(preflight, require_live_binding=True)
    run_preflight = run_root / "preflight" / "runtime-preflight.json"
    if run_preflight.is_file():
        try:
            previous = json.loads(run_preflight.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ServiceProfileError("existing run-local Runtime preflight cannot be verified") from None
        if previous.get("preflight_hash") == preflight.get("preflight_hash"):
            pass
        else:
            prior_hash = str(previous.get("preflight_hash", "unhashed")).replace(":", "_")
            history_path = run_preflight.parent / "runtime-preflight-history" / f"{prior_hash}.json"
            write_json_once(history_path, previous)
            _atomic_replace_json(run_preflight, preflight)
    else:
        write_json_once(run_preflight, preflight)
    if current_pointer is not None:
        _atomic_replace_json(current_pointer, preflight)
    return {
        "preflight": preflight,
        "run_preflight_path": str(run_preflight.resolve()),
        "current_pointer_path": str(current_pointer.resolve()) if current_pointer else None,
        "runtime_health": runtime_response,
        "ollama_version": ollama_version,
        "ollama_model": ollama_model_live,
        "safety_health": safety,
        "cat_health": cat,
        "network": network,
        "profile_source_evidence": {key: dict(value) for key, value in source_evidence.items()},
    }


def verify_runtime_attestation_still_live(
    preflight: Mapping[str, Any],
    *,
    supervisor: ProcessSupervisor,
    profiles: Mapping[str, ProcessSpec],
    include_application_stack: bool = True,
) -> dict[str, Any]:
    verified = RuntimePreflight.from_mapping(preflight, require_live_binding=True)
    binding = preflight["execution_binding"]
    identities = {str(row["name"]): row for row in supervisor.identities()}
    runtime = _profile_process_identity("d4-runtime", profiles["d4-runtime"], identities, supervisor)
    ollama = _profile_process_identity("d4-ollama", profiles["d4-ollama"], identities, supervisor)
    runtime_tree = sorted(int(pid) for pid in runtime["process_tree_pids"])
    if (
        int(runtime["pid"]) != int(binding["runtime_launcher_pid"])
        or str(runtime["started_at"]) != str(binding["runtime_launcher_started_at"])
        or str(runtime["executable"]) != str(binding["runtime_launcher_executable"])
        or str(runtime["executable_sha256"]) != str(binding["runtime_launcher_executable_sha256"])
        or runtime_tree != sorted(int(pid) for pid in binding["runtime_process_tree_pids"])
    ):
        raise ServiceProfileError("Runtime launcher restarted after its live attestation was issued")
    runtime_listener = _runtime_listener_process_identity(
        listener_pid=int(binding["runtime_pid"]),
        launcher_profile=profiles["d4-runtime"],
        launcher_identity=runtime,
    )
    if (
        str(runtime_listener["started_at"]) != str(binding["runtime_started_at"])
        or str(runtime_listener["executable"]) != str(binding["runtime_executable"])
        or str(runtime_listener["executable_sha256"]) != str(binding["runtime_executable_sha256"])
    ):
        raise ServiceProfileError("Runtime listener restarted after its live attestation was issued")
    ollama_tree = sorted(int(pid) for pid in ollama["process_tree_pids"])
    if (
        int(ollama["pid"]) != int(binding["ollama_pid"])
        or str(ollama["started_at"]) != str(binding["ollama_started_at"])
        or ollama_tree != sorted(int(pid) for pid in binding["ollama_process_tree_pids"])
    ):
        raise ServiceProfileError("Ollama restarted after its Runtime attestation was issued")
    network = _verify_network_ownership(
        supervisor,
        profiles,
        include_application_stack=include_application_stack,
    )
    for port in (3307, 8160, 8180, 8181, 8190, 11437):
        if int(network["verified_listener_pids"].get(str(port), -1)) != int(binding["verified_listener_pids"].get(str(port), -2)):
            raise ServiceProfileError(f"Runtime attestation listener changed on port {port}")
    return {
        "status": "PASS",
        "attempt_id": binding["attempt_id"],
        "preflight_hash": verified.preflight_hash,
        "runtime_pid": int(runtime_listener["pid"]),
        "runtime_launcher_pid": int(runtime["pid"]),
        "ollama_pid": int(ollama["pid"]),
        "network": network,
    }


def invalidate_current_runtime_pointer(path: Path, *, attempt_id: str, reason: str) -> bool:
    if not path.is_file():
        return False
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    binding = value.get("execution_binding") if isinstance(value, dict) else None
    if not isinstance(binding, dict) or binding.get("attempt_id") != attempt_id:
        return False
    _atomic_replace_json(
        path,
        {
            "schema_version": "d4-runtime-current-pointer.v1",
            "status": "INVALIDATED",
            "attempt_id": attempt_id,
            "invalidated_at": _now(),
            "reason": reason,
            "former_preflight_hash": value.get("preflight_hash"),
            "runtime_pid": binding.get("runtime_pid"),
            "ollama_pid": binding.get("ollama_pid"),
        },
    )
    return True


def preflight_formal_port_owners(
    *,
    profiles: Mapping[str, ProcessSpec],
    stale_profiles: Mapping[str, ProcessSpec],
    evidence_path: Path,
) -> dict[str, Any]:
    """Reject occupied formal ports; clean only the previously identified exact R1 Runtime."""

    from .windows_process_identity import (
        capture_process_identity,
        matches_exact_prior_runtime_identity,
        stop_exact_stale_process,
    )

    try:
        inventory = capture_data_plane_network(
            required_ports=FORMAL_DATA_PLANE_PORTS,
            require_listeners=False,
        )
    except NetworkIntegrityError as exc:
        raise ServiceProfileError(f"formal port ownership inventory failed: {type(exc).__name__}") from None
    observations: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    stale_runtime_spec = stale_profiles.get("d4-runtime-prior-r1")
    if stale_runtime_spec is None:
        raise ServiceProfileError("exact prior Runtime cleanup profile is missing")
    for listener in inventory["listeners"]:
        port = int(listener["port"])
        pid = int(listener["pid"])
        record: dict[str, Any] = {"address": listener["address"], "port": port, "pid": pid}
        try:
            identity = capture_process_identity(pid, include_parent=port == 8160)
        except Exception as exc:
            identity = {"pid": pid, "identity_complete": False, "capture_errors": {"identity": type(exc).__name__}}
        public_identity = {
            key: identity.get(key)
            for key in (
                "pid", "parent_pid", "executable", "executable_sha256", "argv_redacted",
                "cwd", "started_at", "capture_errors", "identity_complete",
            )
            if key in identity
        }
        parent_identity = identity.get("parent_identity")
        if isinstance(parent_identity, dict):
            public_identity["parent_process_identity"] = {
                key: parent_identity.get(key)
                for key in (
                    "pid", "executable", "executable_sha256", "argv_redacted",
                    "cwd", "started_at", "capture_errors", "identity_complete",
                )
                if key in parent_identity
            }
        record["process_identity"] = public_identity
        if port == 8160 and matches_exact_prior_runtime_identity(identity, stale_runtime_spec):
            try:
                record["cleanup"] = stop_exact_stale_process(
                    identity,
                    stale_runtime_spec,
                    matcher=matches_exact_prior_runtime_identity,
                )
                record["classification"] = "EXACT_PRIOR_D4_RUNTIME_CLEANED"
                observations.append(record)
                continue
            except Exception as exc:
                record["cleanup_error"] = type(exc).__name__
        record["classification"] = "UNKNOWN_PROCESS_OCCUPIES_REQUIRED_FORMAL_PORT"
        unknown.append(record)
        observations.append(record)

    try:
        after = capture_data_plane_network(
            required_ports=FORMAL_DATA_PLANE_PORTS,
            require_listeners=False,
        )
    except NetworkIntegrityError as exc:
        raise ServiceProfileError(f"formal port ownership inventory failed after cleanup: {type(exc).__name__}") from None
    remaining = list(after["listeners"])
    result = {
        "schema_version": "d4-formal-port-preflight.v1",
        "status": "CONTROLLER_DECISION_REQUIRED" if unknown or remaining else "PASS",
        "observed_at": after["observed_at"],
        "formal_ports": sorted(FORMAL_DATA_PLANE_PORTS),
        "before": inventory,
        "owner_observations": observations,
        "remaining_formal_listeners": remaining,
        "unknown_process_count": len(unknown),
        "historical_runtime_disposition": "R6_NOT_REUSED",
    }
    write_json_once(evidence_path, result)
    if unknown or remaining:
        raise ServiceProfileError("UNKNOWN_PROCESS_OCCUPIES_REQUIRED_FORMAL_PORT")
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_file_hash(path: Path, expected: str, label: str) -> str:
    if not path.is_absolute() or not path.is_file():
        raise ServiceProfileError(f"fixed {label} file is missing")
    actual = _sha256(path)
    if actual != expected:
        raise ServiceProfileError(f"fixed {label} identity changed")
    return actual


def _run_fixed(executable: Path, arguments: tuple[str, ...], *, cwd: Path) -> str:
    if not executable.is_absolute() or not executable.is_file() or not cwd.is_absolute() or not cwd.is_dir():
        raise ServiceProfileError("fixed identity probe path is unavailable")
    try:
        result = subprocess.run(
            [str(executable), *arguments],
            cwd=cwd,
            env=build_child_environment({}),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            shell=False,
            timeout=12,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ServiceProfileError(f"fixed identity probe failed: {type(exc).__name__}") from None
    return (result.stdout + result.stderr).decode("utf-8", errors="replace").strip()


def _python_version(executable: Path) -> str:
    text = _run_fixed(executable, ("--version",), cwd=executable.parent)
    match = re.fullmatch(r"Python\s+(\d+\.\d+\.\d+)(?:\s+.*)?", text)
    if not match:
        raise ServiceProfileError("fixed Python interpreter returned an invalid version")
    return match.group(1)


def _git(repo_root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            [str(GIT_EXECUTABLE), "-C", str(repo_root), *arguments],
            cwd=repo_root,
            env=build_child_environment({}),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ServiceProfileError(f"fixed product-source identity check failed: {type(exc).__name__}") from None
    return result.stdout.strip()


def build_profile_source_identity_record(
    *,
    repo_root: str | Path,
    attempt_id: str,
    formal_port_preflight_status: str,
    services: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    evaluation_commit = _git(Path(repo_root).resolve(), "rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", evaluation_commit):
        raise ServiceProfileError("evaluation source commit is malformed")
    return {
        "schema_version": "d4-service-profile-identities.v1",
        "attempt_id": attempt_id,
        "evaluation_source_commit": evaluation_commit,
        "accepted_product_baseline_commit": ACCEPTED_D4_3A_COMMIT,
        "profile_source_copy_commit": PROFILE_SOURCE_COPY_COMMIT,
        "formal_port_preflight_status": formal_port_preflight_status,
        "services": {key: dict(value) for key, value in services.items()},
    }


def _verify_product_source_boundary(repo_root: Path) -> None:
    if repo_root.resolve() != Path(__file__).resolve().parents[4]:
        raise ServiceProfileError("D4 service profiles require the checked-out evaluation worktree")
    base = _git(repo_root, "rev-parse", f"{PROFILE_SOURCE_COPY_COMMIT}^{{commit}}")
    if base != PROFILE_SOURCE_COPY_COMMIT:
        raise ServiceProfileError("accepted service-source baseline is unavailable")
    paths = ("01_cat-engine", "06_llm-runtime", "08_safety-engine", "09_backend", "11_database")
    for revision in ("HEAD",):
        _git(repo_root, "diff", "--quiet", base, revision, "--", *paths)
    _git(repo_root, "diff", "--quiet", "HEAD", "--", *paths)
    status = _git(repo_root, "status", "--porcelain=v1", "--untracked-files=all", "--", *paths)
    if status:
        raise ServiceProfileError("product source tree contains uncommitted or untracked changes")


def _hash_inventory(files: list[tuple[str, Path]]) -> tuple[str, dict[str, str]]:
    entries: list[tuple[str, str]] = []
    file_hashes: dict[str, str] = {}
    for relative, path in sorted(files):
        digest = _sha256(path)
        entries.append((relative.replace("\\", "/"), digest))
        file_hashes[relative.replace("\\", "/")] = digest
    payload = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest(), file_hashes


def _copy_tracked_safety_source(repo_root: Path, service_root: Path) -> tuple[Path, str, int]:
    prefix = "08_safety-engine"
    tracked = [
        item
        for item in _git(repo_root, "ls-files", "--", prefix).splitlines()
        if item and not item.endswith("/")
    ]
    if not tracked:
        raise ServiceProfileError("accepted Safety source tree is empty")
    destination_root = service_root / "profile-sources" / "safety"
    destination_root.mkdir(parents=True, exist_ok=False)
    inventory: list[tuple[str, Path]] = []
    for relative in tracked:
        source = repo_root / Path(relative)
        if not source.is_file() or source.is_symlink():
            raise ServiceProfileError("accepted Safety source tree has a missing or linked file")
        target = destination_root / Path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if _sha256(source) != _sha256(target):
            raise ServiceProfileError("Safety source copy did not preserve exact bytes")
        inventory.append((str(Path(relative).relative_to(prefix)), target))
    tree_hash, _ = _hash_inventory(inventory)
    app_root = destination_root / "08_safety-engine"
    policies = app_root / "policies"
    if not (app_root / "src" / "safety_engine" / "api" / "app.py").is_file():
        raise ServiceProfileError("Safety app source copy is incomplete")
    return app_root, tree_hash, len(tracked)


def _copy_runtime_source(repo_root: Path, service_root: Path) -> tuple[Path, str, dict[str, str]]:
    source = RUNTIME_SOURCE_ROOT
    if not source.is_dir() or not RUNTIME_RECONSTRUCTION_ROOT.is_dir():
        raise ServiceProfileError("accepted Runtime source copy or project source is unavailable")
    if _git(RUNTIME_RECONSTRUCTION_ROOT, "rev-parse", "HEAD") != RUNTIME_RECONSTRUCTION_COMMIT:
        raise ServiceProfileError("Runtime reconstruction source commit differs from its accepted identity")
    _git(RUNTIME_RECONSTRUCTION_ROOT, "diff", "--quiet", "HEAD", "--", "06_llm-runtime")
    reconstruction_status = _git(
        RUNTIME_RECONSTRUCTION_ROOT,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        "06_llm-runtime",
    )
    if reconstruction_status:
        raise ServiceProfileError("Runtime reconstruction source tree contains local changes")
    relative_paths = sorted(
        [p.relative_to(source).as_posix() for p in (source / "src" / "llm_runtime").rglob("*.py")]
        + [p.relative_to(source).as_posix() for p in (source / "config").glob("*.json")]
    )
    if len(relative_paths) != 27 or len(set(relative_paths)) != 27:
        raise ServiceProfileError("accepted Runtime source inventory is not the frozen 27-file set")
    for relative in relative_paths:
        left = source / relative
        if not left.is_file():
            raise ServiceProfileError("accepted Runtime source copy is incomplete")
        if relative.endswith(".py"):
            right = RUNTIME_RECONSTRUCTION_ROOT / "06_llm-runtime" / relative
            if not right.is_file() or left.read_bytes().replace(b"\r\n", b"\n") != right.read_bytes().replace(b"\r\n", b"\n"):
                raise ServiceProfileError("accepted Runtime Python source differs from the frozen reconstruction commit")
    lock_path = repo_root / "06_llm-runtime" / "uv.lock"
    _require_file_hash(lock_path, RUNTIME_LOCK_SHA256, "Runtime lock")
    _require_file_hash(
        RUNTIME_RECONSTRUCTION_ROOT / "06_llm-runtime" / "uv.lock",
        RUNTIME_RECONSTRUCTION_LOCK_SHA256,
        "Runtime reconstruction lock",
    )
    _require_file_hash(source / "config" / "runtime.v1.json", RUNTIME_CONFIG_SHA256, "Runtime configuration")
    _require_file_hash(source / "config" / "models.v1.json", RUNTIME_MODELS_CONFIG_SHA256, "Runtime models configuration")

    destination = service_root / "profile-sources" / "runtime" / "06_llm-runtime"
    destination.mkdir(parents=True, exist_ok=False)
    inventory: list[tuple[str, Path]] = []
    for relative in relative_paths:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)
        if _sha256(source / relative) != _sha256(target):
            raise ServiceProfileError("Runtime source copy did not preserve exact bytes")
        inventory.append((relative, target))
    tree_hash, file_hashes = _hash_inventory(inventory)
    if tree_hash != RUNTIME_PROFILE_TREE_SHA256:
        raise ServiceProfileError("accepted Runtime 27-file profile tree identity changed")
    return destination, tree_hash, file_hashes


def _opa_policy_hash(policy_dir: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    files = sorted(policy_dir.glob("*.rego"), key=lambda item: item.name)
    if len(files) != 6:
        raise ServiceProfileError("frozen OPA policy inventory is not the accepted six-file set")
    for path in files:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    value = digest.hexdigest()[:16]
    if value != OPA_POLICY_SHA256:
        raise ServiceProfileError("frozen OPA policy identity changed")
    return value, len(files)


def _verify_local_ollama_cache() -> dict[str, str]:
    if not OLLAMA_MODELS.is_dir() or not OLLAMA_MANIFEST.is_file():
        raise ServiceProfileError("approved local Ollama model cache is missing")
    try:
        manifest = json.loads(OLLAMA_MANIFEST.read_text(encoding="utf-8"))
        layers = [manifest["config"], *manifest["layers"]]
    except (OSError, ValueError, KeyError, TypeError):
        raise ServiceProfileError("approved local Ollama model manifest is invalid") from None
    verified: set[str] = set()
    for layer in layers:
        digest = layer.get("digest") if isinstance(layer, dict) else None
        expected_size = layer.get("size") if isinstance(layer, dict) else None
        if not isinstance(digest, str) or not digest.startswith("sha256:"):
            raise ServiceProfileError("approved local Ollama manifest contains an invalid blob identity")
        name = digest.removeprefix("sha256:")
        if not re.fullmatch(r"[0-9a-f]{64}", name):
            raise ServiceProfileError("approved local Ollama manifest contains an invalid blob digest")
        blob = OLLAMA_MODELS / "blobs" / f"sha256-{name}"
        if name not in verified:
            if not blob.is_file() or blob.stat().st_size != expected_size or _sha256(blob) != name:
                raise ServiceProfileError("approved local Ollama model blob is missing or changed")
            verified.add(name)
    return {
        "model": OLLAMA_MODEL,
        "expected_model_digest": OLLAMA_MODEL_DIGEST,
        "manifest_sha256": _sha256(OLLAMA_MANIFEST),
        "verified_blob_count": str(len(verified)),
    }


def _ollama_profile_environment(service_root: Path) -> dict[str, str]:
    """Set Ollama's Windows home to a fresh per-attempt directory."""

    profile_home = service_root.resolve() / "ollama-user-profile"
    profile_home.mkdir(parents=True, exist_ok=True)
    return {
        "USERPROFILE": str(profile_home),
        "OLLAMA_HOST": "127.0.0.1:11437",
        "OLLAMA_MODELS": str(OLLAMA_MODELS.resolve()),
        "OLLAMA_NO_CLOUD": "1",
        "OLLAMA_NOPRUNE": "1",
        "OLLAMA_CONTEXT_LENGTH": "8192",
        "OLLAMA_KV_CACHE_TYPE": "f16",
        "OLLAMA_NUM_PARALLEL": "1",
        "OLLAMA_MAX_LOADED_MODELS": "1",
        "HTTP_PROXY": "",
        "HTTPS_PROXY": "",
        "ALL_PROXY": "",
        "http_proxy": "",
        "https_proxy": "",
        "all_proxy": "",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
    }


def build_external_service_profiles(repo_root: str | Path, service_root: str | Path) -> ExternalProfileSet:
    """Create per-attempt clean source copies and return only fixed local profiles."""

    repo = Path(repo_root).resolve()
    run_root = Path(service_root).resolve()
    try:
        run_root.relative_to(D4_TASK_TOOLS_ROOT.resolve())
    except ValueError:
        raise ServiceProfileError("service profile output must stay under the D4 task-tools root") from None
    if run_root == D4_TASK_TOOLS_ROOT.resolve() or run_root.is_relative_to(repo):
        raise ServiceProfileError("service profile output must be a fresh external attempt directory")
    _verify_product_source_boundary(repo)
    if run_root.exists() and any(run_root.iterdir()):
        allowed = {"mysql"}
        if {item.name for item in run_root.iterdir()} - allowed:
            raise ServiceProfileError("service profile output is not a fresh attempt directory")
    run_root.mkdir(parents=True, exist_ok=True)

    cat_pyproject = repo / "01_cat-engine" / "pyproject.toml"
    cat_config = repo / "01_cat-engine" / "fixtures" / "demo_cat_config.v1.json"
    cat_bank = repo / "01_cat-engine" / "fixtures" / "synthetic_item_bank.v1.json"
    _require_file_hash(CAT_LOCK, CAT_LOCK_SHA256, "CAT lock")
    _require_file_hash(cat_pyproject, CAT_PYPROJECT_SHA256, "CAT project metadata")
    _require_file_hash(cat_config, CAT_CONFIG_SHA256, "CAT configuration")
    _require_file_hash(cat_bank, CAT_ITEM_BANK_SHA256, "CAT item bank")
    cat_version = _python_version(CAT_PYTHON)
    if cat_version != "3.14.6":
        raise ServiceProfileError("CAT interpreter version does not match its accepted profile")
    cat_config_value = json.loads(cat_config.read_text(encoding="utf-8"))
    cat_bank_value = json.loads(cat_bank.read_text(encoding="utf-8"))

    safety_lock = repo / "08_safety-engine" / "uv.lock"
    safety_pyproject = repo / "08_safety-engine" / "pyproject.toml"
    _require_file_hash(safety_lock, SAFETY_LOCK_SHA256, "Safety lock")
    _require_file_hash(safety_pyproject, SAFETY_PYPROJECT_SHA256, "Safety project metadata")
    if not SAFETY_BOOTSTRAP_SCRIPT.is_file():
        raise ServiceProfileError("fixed evaluation Safety bootstrap source is missing")
    safety_version = _python_version(SAFETY_PYTHON)
    if not safety_version.startswith("3.12."):
        raise ServiceProfileError("Safety interpreter is not the accepted Python 3.12 environment")
    if not HF_CACHE.is_dir():
        raise ServiceProfileError("approved offline Safety model cache is unavailable")

    opa_hash = _require_file_hash(OPA_EXECUTABLE, OPA_EXECUTABLE_SHA256, "OPA executable")
    opa_version_text = _run_fixed(OPA_EXECUTABLE, ("version",), cwd=OPA_EXECUTABLE.parent)
    if not re.search(rf"(?m)^Version:\s*{re.escape(OPA_VERSION)}\s*$", opa_version_text):
        raise ServiceProfileError("OPA executable version does not match the accepted profile")

    ollama_hash = _require_file_hash(OLLAMA_EXECUTABLE, OLLAMA_EXECUTABLE_SHA256, "Ollama executable")
    ollama_cache = _verify_local_ollama_cache()

    runtime_python_version = _python_version(RUNTIME_PYTHON)
    if not runtime_python_version.startswith("3.12."):
        raise ServiceProfileError("Runtime interpreter is not the accepted Python 3.12 environment")
    _require_file_hash(RUNTIME_PYTHON, RUNTIME_VENV_PYTHON_SHA256, "Runtime venv interpreter")
    _require_file_hash(RUNTIME_BASE_PYTHON, RUNTIME_BASE_PYTHON_SHA256, "Runtime base interpreter")
    _require_file_hash(
        RUNTIME_BASE_PYTHON_ARGV0,
        RUNTIME_BASE_PYTHON_ARGV0_SHA256,
        "Runtime base interpreter argv0",
    )
    if _python_version(RUNTIME_BASE_PYTHON) != runtime_python_version:
        raise ServiceProfileError("Runtime venv and base interpreter versions do not match")
    runtime_root, runtime_tree_hash, runtime_file_hashes = _copy_runtime_source(repo, run_root)
    safety_root, safety_tree_hash, safety_file_count = _copy_tracked_safety_source(repo, run_root)
    policy_dir = safety_root / "policies"
    policy_hash, policy_count = _opa_policy_hash(policy_dir)

    cat_env = {
        "PYTHONPATH": str((repo / "01_cat-engine" / "src").resolve()),
        "SMHAI_CAT_CONFIG": str(cat_config.resolve()),
        "SMHAI_CAT_ITEM_BANK": str(cat_bank.resolve()),
        "SMHAI_CAT_PORT": "8180",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    opa_args = (
        "run", "--server", "--addr=127.0.0.1:8181", "--skip-version-check",
        str(policy_dir.resolve()),
    )
    safety_env = {
        "PYTHONPATH": str((safety_root / "src").resolve()),
        "USERNAME": EVALUATION_PROCESS_USERNAME,
        "SMHAI_MANAGE_OPA": "0",
        "SMHAI_OPA_URL": "http://127.0.0.1:8181",
        "SMHAI_OPA_BINARY": str(OPA_EXECUTABLE.resolve()),
        "SMHAI_HF_HOME": str(HF_CACHE.resolve()),
        "HF_HOME": str(HF_CACHE.resolve()),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "HTTP_PROXY": "",
        "HTTPS_PROXY": "",
        "ALL_PROXY": "",
        "http_proxy": "",
        "https_proxy": "",
        "all_proxy": "",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
    }
    ollama_env = _ollama_profile_environment(run_root)
    runtime_env = {
        "PYTHONPATH": str((runtime_root / "src").resolve()),
        "SMHAI_LLM_PORT": "8160",
        "PYTHONDONTWRITEBYTECODE": "1",
        "HTTP_PROXY": "",
        "HTTPS_PROXY": "",
        "ALL_PROXY": "",
        "http_proxy": "",
        "https_proxy": "",
        "all_proxy": "",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
    }
    runtime_lock = repo / "06_llm-runtime" / "uv.lock"
    profile_evidence: dict[str, dict[str, Any]] = {
        "cat": {
            "python_version": cat_version,
            "python_executable": str(CAT_PYTHON.resolve()),
            "python_executable_sha256": _sha256(CAT_PYTHON),
            "candidate_lock_sha256": CAT_LOCK_SHA256,
            "accepted_repository_lock_sha256": "cd26d492b5800163f3424ed723dd8f5c411debe89bd7e03c003105345dec88f5",
            "pyproject_sha256": CAT_PYPROJECT_SHA256,
            "cat_config_sha256": CAT_CONFIG_SHA256,
            "item_bank_sha256": CAT_ITEM_BANK_SHA256,
            "item_bank_id": str(cat_bank_value["item_bank_id"]),
            "item_bank_version": str(cat_bank_value["version"]),
            "instrument_id": str(cat_bank_value["instrument_id"]),
            "instrument_version": str(cat_bank_value["version"]),
            "config_version": str(cat_config_value["config_version"]),
        },
        "opa": {
            "binary": str(OPA_EXECUTABLE.resolve()),
            "binary_sha256": opa_hash,
            "version": OPA_VERSION,
            "policy_directory": str(policy_dir.resolve()),
            "policy_sha256": policy_hash,
            "policy_file_count": str(policy_count),
        },
        "safety": {
            "python_version": safety_version,
            "python_executable": str(SAFETY_PYTHON.resolve()),
            "python_executable_sha256": _sha256(SAFETY_PYTHON),
            "evaluation_bootstrap_path": str(SAFETY_BOOTSTRAP_SCRIPT),
            "evaluation_bootstrap_sha256": _sha256(SAFETY_BOOTSTRAP_SCRIPT),
            "lock_sha256": SAFETY_LOCK_SHA256,
            "pyproject_sha256": SAFETY_PYPROJECT_SHA256,
            "source_directory": str(safety_root.resolve()),
            "source_tree_sha256": safety_tree_hash,
            "source_file_count": str(safety_file_count),
            "policy_sha256": policy_hash,
        },
        "ollama": {
            "binary": str(OLLAMA_EXECUTABLE.resolve()),
            "binary_sha256": ollama_hash,
            "user_profile_directory": ollama_env["USERPROFILE"],
            "model_cache": str(OLLAMA_MODELS.resolve()),
            **ollama_cache,
            "endpoint": "http://127.0.0.1:11437",
            "version": "0.33.3",
            "context_length": "8192",
            "kv_cache_type": "f16",
            "parallel": "1",
            "max_loaded_models": "1",
            "cloud_fallback": "false",
        },
        "runtime": {
            "python_version": runtime_python_version,
            "python_executable": str(RUNTIME_PYTHON.resolve()),
            "python_executable_sha256": _sha256(RUNTIME_PYTHON),
            "process_image_executable": str(RUNTIME_BASE_PYTHON),
            "process_image_sha256": RUNTIME_BASE_PYTHON_SHA256,
            "readiness_request_timeout_seconds": str(RUNTIME_READINESS_REQUEST_TIMEOUT_SECONDS),
            "base_python_argv0_executable": str(RUNTIME_BASE_PYTHON_ARGV0.resolve()),
            "base_python_argv0_executable_sha256": RUNTIME_BASE_PYTHON_ARGV0_SHA256,
            "base_python_executable": str(RUNTIME_BASE_PYTHON.resolve()),
            "base_python_executable_sha256": RUNTIME_BASE_PYTHON_SHA256,
            "lock_sha256": _sha256(runtime_lock),
            "reconstruction_lock_sha256": RUNTIME_RECONSTRUCTION_LOCK_SHA256,
            "source_directory": str(runtime_root.resolve()),
            "source_tree_sha256": runtime_tree_hash,
            "runtime_config_sha256": RUNTIME_CONFIG_SHA256,
            "models_config_sha256": RUNTIME_MODELS_CONFIG_SHA256,
            "source_file_count": str(len(runtime_file_hashes)),
        },
    }
    profiles = {
        "d4-cat": ProcessSpec(
            name="d4-cat",
            executable=CAT_PYTHON,
            arguments=("-m", "cat_engine.api.app"),
            cwd=repo / "01_cat-engine",
            environment=cat_env,
            readiness_url=SERVICE_ENDPOINTS["d4-cat"],
            readiness_kind="service",
            log_path=run_root / "logs" / "cat.stdout.log",
            stderr_log_path=run_root / "logs" / "cat.stderr.log",
            interpreter_version=cat_version,
            package_lock_identity={key: str(value) for key, value in profile_evidence["cat"].items()},
            environment_allowlist=frozenset(cat_env),
        ),
        "d4-opa": ProcessSpec(
            name="d4-opa",
            executable=OPA_EXECUTABLE,
            arguments=opa_args,
            cwd=policy_dir,
            environment={},
            readiness_url=SERVICE_ENDPOINTS["d4-opa"],
            readiness_kind="http-200",
            log_path=run_root / "logs" / "opa.stdout.log",
            stderr_log_path=run_root / "logs" / "opa.stderr.log",
            package_lock_identity={key: str(value) for key, value in profile_evidence["opa"].items()},
            environment_allowlist=frozenset(),
        ),
        "d4-safety": ProcessSpec(
            name="d4-safety",
            executable=SAFETY_PYTHON,
            arguments=(str(SAFETY_BOOTSTRAP_SCRIPT),),
            cwd=safety_root,
            environment=safety_env,
            readiness_url=SERVICE_ENDPOINTS["d4-safety"],
            readiness_kind="service",
            log_path=run_root / "logs" / "safety.stdout.log",
            stderr_log_path=run_root / "logs" / "safety.stderr.log",
            interpreter_version=safety_version,
            package_lock_identity={key: str(value) for key, value in profile_evidence["safety"].items()},
            environment_allowlist=frozenset(safety_env),
        ),
        "d4-ollama": ProcessSpec(
            name="d4-ollama",
            executable=OLLAMA_EXECUTABLE,
            arguments=("serve",),
            cwd=OLLAMA_EXECUTABLE.parent,
            environment=ollama_env,
            readiness_url=SERVICE_ENDPOINTS["d4-ollama"],
            readiness_kind="http-200",
            log_path=run_root / "logs" / "ollama.stdout.log",
            stderr_log_path=run_root / "logs" / "ollama.stderr.log",
            package_lock_identity={key: str(value) for key, value in profile_evidence["ollama"].items()},
            environment_allowlist=frozenset(ollama_env),
        ),
        "d4-runtime": ProcessSpec(
            name="d4-runtime",
            executable=RUNTIME_PYTHON,
            arguments=("-m", "llm_runtime.api.app"),
            cwd=runtime_root,
            environment=runtime_env,
            readiness_url=SERVICE_ENDPOINTS["d4-runtime"],
            readiness_kind="service",
            log_path=run_root / "logs" / "runtime.stdout.log",
            stderr_log_path=run_root / "logs" / "runtime.stderr.log",
            readiness_request_timeout_seconds=RUNTIME_READINESS_REQUEST_TIMEOUT_SECONDS,
            interpreter_version=runtime_python_version,
            package_lock_identity={key: str(value) for key, value in profile_evidence["runtime"].items()},
            environment_allowlist=frozenset(runtime_env),
        ),
    }
    prior_runtime_env = {
        "PYTHONPATH": str((RUNTIME_SOURCE_ROOT / "src").resolve()),
        "SMHAI_LLM_PORT": "8160",
        "PYTHONDONTWRITEBYTECODE": "1",
        "HTTP_PROXY": "",
        "HTTPS_PROXY": "",
        "ALL_PROXY": "",
        "NO_PROXY": "127.0.0.1,localhost",
    }
    prior_runtime = ProcessSpec(
        name="d4-runtime-prior-r1",
        executable=RUNTIME_PYTHON,
        arguments=("-m", "llm_runtime.api.app"),
        cwd=RUNTIME_SOURCE_ROOT,
        environment=prior_runtime_env,
        readiness_url=SERVICE_ENDPOINTS["d4-runtime"],
        readiness_kind="service",
        log_path=run_root / "logs" / "prior-runtime-unused.log",
        package_lock_identity={
            "python_executable_sha256": _sha256(RUNTIME_PYTHON),
            "process_image_executable": str(RUNTIME_BASE_PYTHON),
            "process_image_sha256": RUNTIME_BASE_PYTHON_SHA256,
            "lock_sha256": RUNTIME_LOCK_SHA256,
        },
        environment_allowlist=frozenset(prior_runtime_env),
    )
    return ExternalProfileSet(
        profiles=profiles,
        source_evidence=profile_evidence,
        stale_profiles={"d4-runtime-prior-r1": prior_runtime},
    )
