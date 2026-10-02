"""Command-line entry points for preparing and executing D4-3B evaluation."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .approved_packet import ApprovedPacketError, load_approved_packet
from .manifest import (
    ACCEPTED_D4_3A_COMMIT,
    ManifestError,
    RuntimePreflight,
    create_run_id,
    build_approved_corpus_manifest,
    build_case_manifest,
    is_loopback_url,
    write_json_once,
)
from .environment_profiles import (
    BACKEND_PYTHON,
    D4_TASK_TOOLS_ROOT,
    EVALUATION_PROCESS_USERNAME,
    RAG_PYTHON,
)
from .credential_provider import (
    ACCEPTED_PRODUCT_BASELINE,
    EXPECTED_SYNTHETIC_SUBJECTS,
    FIXTURE_SOURCE_RELATIVE,
    DatabaseCredential,
    EvaluationCredentialProvider,
    CredentialProviderError,
    credential_evidence_metadata,
)
from .mysql_bootstrap import IsolatedMySqlBootstrap, database_url_for_credential
from .process_lifecycle import (
    LifecycleError,
    ProcessSpec,
    ProcessSupervisor,
    build_child_environment,
)
from .network_integrity import LoopbackNetworkMonitor
from .secret_scan import scan_secret_artifacts
from .service_profiles import (
    HF_CACHE,
    ServiceProfileError,
    build_profile_source_identity_record,
    build_external_service_profiles,
    invalidate_current_runtime_pointer,
    preflight_formal_port_owners,
    verify_external_service_readiness,
    verify_runtime_attestation_still_live,
)
from .runner import (
    CanonicalHttpTransport,
    PostPrepareIntegrityError,
    RunnerError,
    assert_post_prepare_integrity,
    run_evaluation,
)

RUNTIME_HTTP_SERVICE_BASE_URL = "http://127.0.0.1:8160"


def _safe_startup_failure_detail(
    error: Exception, *, stage: str | None = None
) -> str | None:
    """Expose bounded diagnostics for fixed profiles and local smoke preflights."""

    allowed = isinstance(error, (ManifestError, ServiceProfileError)) or (
        stage in {"FULL_REAL_HTTP_PREFLIGHT", "COLD_START_SMOKE", "POST_PREPARE_INTEGRITY_GATE"}
        and isinstance(error, RunnerError)
    )
    if not allowed:
        return None
    return " ".join(str(error).split())[:240]


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs)
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value


def _default_packet() -> Path:
    return Path(__file__).resolve().parents[2] / "D4_3A_HUMAN_GOLD_REVIEW_PACKET.json"


def prepare_assets(packet_path: str | Path, manifest_dir: str | Path) -> dict[str, Any]:
    packet = load_approved_packet(packet_path)
    case_manifest = build_case_manifest(packet)
    corpus_manifest = build_approved_corpus_manifest(packet)
    target = Path(manifest_dir)
    case_path = write_json_once(target / "d4_slice3b_case_manifest.json", case_manifest)
    corpus_path = write_json_once(target / "d4_slice3b_approved_corpus_manifest.json", corpus_manifest)
    return {
        "packet_id": packet.packet_id,
        "packet_hash": packet.packet_hash,
        "packet_file_sha256": packet.raw_file_sha256,
        "answerability_case_count": len(packet.answerability_cases),
        "citation_reference_case_count": len(packet.citation_cases),
        "case_manifest_hash": case_manifest["manifest_hash"],
        "case_manifest_path": str(case_path.resolve()),
        "corpus_manifest_hash": corpus_manifest["corpus_hash"],
        "corpus_evidence_count": corpus_manifest["evidence_count"],
        "corpus_manifest_path": str(corpus_path.resolve()),
    }


async def _run(
    args: argparse.Namespace,
    *,
    managed_service_identity: dict[str, Any] | None = None,
    live_service_process_tree_pids: Callable[[str], Iterable[int]] | None = None,
    transport: CanonicalHttpTransport | None = None,
    synthetic_passwords: Mapping[str, str] | None = None,
    cat_compatibility_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    packet = load_approved_packet(args.packet)
    manifest_dir = Path(args.output_root) / "input-manifests"
    case_path = Path(args.case_manifest) if args.case_manifest else manifest_dir / "d4_slice3b_case_manifest.json"
    corpus_path = Path(args.corpus_manifest) if args.corpus_manifest else manifest_dir / "d4_slice3b_approved_corpus_manifest.json"
    if case_path.exists():
        case_manifest = _read_json(case_path)
    else:
        case_manifest = build_case_manifest(packet)
        write_json_once(case_path, case_manifest)
    if corpus_path.exists():
        corpus_manifest = _read_json(corpus_path)
    else:
        corpus_manifest = build_approved_corpus_manifest(packet)
        write_json_once(corpus_path, corpus_manifest)
    runtime_preflight = _read_json(args.runtime_preflight)
    live_runtime = RuntimePreflight.from_mapping(runtime_preflight, require_live_binding=True)
    if live_runtime.execution_binding is None or live_runtime.execution_binding.get("attempt_id") != getattr(args, "run_id", None):
        raise RunnerError("live Runtime preflight is not bound to this formal run ID")
    if transport is None:
        if synthetic_passwords is None:
            raise RunnerError("frozen synthetic credentials must be provided in memory")
        transport = CanonicalHttpTransport(
            backend_base_url=args.backend_url,
            observer_urls={"rag": args.rag_observer_url, "llm": args.llm_observer_url},
            rag_observer_events=args.rag_observer_events,
            llm_observer_events=args.llm_observer_events,
            passwords=synthetic_passwords,
            timeout_seconds=args.timeout_seconds,
        )
    return await run_evaluation(
        packet=packet,
        case_manifest=case_manifest,
        corpus_manifest=corpus_manifest,
        runtime_preflight=runtime_preflight,
        transport=transport,
        backend_base_url=args.backend_url,
        observer_endpoints={"rag": args.rag_observer_url, "llm": args.llm_observer_url},
        rag_observer_events=args.rag_observer_events,
        llm_observer_events=args.llm_observer_events,
        repo_root=args.repo_root,
        output_root=args.output_root,
        case_manifest_path=case_path,
        corpus_manifest_path=corpus_path,
        managed_service_identity=managed_service_identity,
        cat_compatibility_context=cat_compatibility_context,
        live_service_process_tree_pids=live_service_process_tree_pids,
        run_id=getattr(args, "run_id", None),
    )


def _managed_pythonpath(*paths: Path) -> str:
    """Build an import path only from evaluation-owned, resolved source roots."""

    return os.pathsep.join(str(path.resolve()) for path in paths)


def _python_version(executable: Path) -> str:
    if not executable.is_absolute() or not executable.is_file():
        raise RunnerError("managed service interpreter must be an existing absolute executable")
    try:
        result = subprocess.run(
            [str(executable), "--version"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            env=build_child_environment({}),
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RunnerError(f"cannot verify managed Python interpreter: {type(exc).__name__}") from exc
    version_text = (result.stdout + result.stderr).strip()
    match = re.fullmatch(r"Python\s+(\d+\.\d+\.\d+)(?:\s+.*)?", version_text)
    if not match:
        raise RunnerError("managed interpreter did not report a valid Python version")
    return match.group(1)


def _require_pinned_interpreter(value: str, expected: Path, role: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        raise RunnerError(f"managed {role} interpreter must be supplied as an absolute path")
    resolved = candidate.resolve()
    if resolved != expected.resolve() or resolved.name.lower() != "python.exe":
        raise RunnerError(f"managed {role} interpreter must use its pinned task-local environment")
    return resolved


def _environment_lock_identity(executable: Path, role: str) -> dict[str, str]:
    """Read only the approved task-local lock identity associated with a venv."""

    if role == "backend":
        if executable.resolve() != BACKEND_PYTHON.resolve():
            return {}
        identity_path = (
            D4_TASK_TOOLS_ROOT
            / "pre-manifest-remediation-r2"
            / "environment"
            / "backend-formal-r2-identity.json"
        )
        try:
            identity = json.loads(identity_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if identity.get("status") != "PASS":
            return {}
        if Path(str(identity.get("python_executable", ""))).resolve() != BACKEND_PYTHON.resolve():
            return {}
        return {
            key: str(identity[key])
            for key in (
                "python_version",
                "backend_lock_sha256",
                "database_lock_sha256",
                "installed_freeze_sha256",
            )
            if identity.get(key)
        }
    if role == "rag":
        if executable.resolve() != RAG_PYTHON.resolve():
            return {}
        lock_path = D4_TASK_TOOLS_ROOT / "rag-env-lock-r1" / "accepted-uv.lock"
        expected_path = D4_TASK_TOOLS_ROOT / "rag-env-lock-r1" / "accepted-uv.lock.sha256"
        try:
            digest = hashlib.sha256(lock_path.read_bytes()).hexdigest()
            expected = expected_path.read_text(encoding="ascii").split()[0].lower()
        except (OSError, ValueError, IndexError):
            return {}
        if digest != expected:
            return {}
        return {"accepted_uv_lock_sha256": digest}
    return {}


def _managed_specs(
    *,
    args: argparse.Namespace,
    repo_root: Path,
    service_root: Path,
    corpus_manifest_path: Path,
    runtime: RuntimePreflight,
    rag_events: Path,
    llm_events: Path,
    database_credential: DatabaseCredential,
    credential_redactions: tuple[str, ...] = (),
) -> list[ProcessSpec]:
    backend_python = _require_pinned_interpreter(args.backend_python, BACKEND_PYTHON, "Backend")
    rag_python = _require_pinned_interpreter(args.rag_python, RAG_PYTHON, "RAG")
    evaluation_root = repo_root / "12_evaluation" / "d4-evaluation-r1"
    backend_src = repo_root / "09_backend" / "src"
    database_src = repo_root / "11_database"
    if not evaluation_root.is_dir() or not backend_src.is_dir() or not database_src.is_dir():
        raise RunnerError("managed service startup requires the accepted evaluation and Backend source roots")

    cat_url = "http://127.0.0.1:8180"
    safety_url = "http://127.0.0.1:8190"
    if not is_loopback_url(cat_url) or not is_loopback_url(safety_url):
        raise RunnerError("formal CAT and Safety endpoints must use HTTP loopback")
    service_root.mkdir(parents=True, exist_ok=True)
    rag_home = (service_root / "isolated-rag-user-profile").resolve()
    rag_home.mkdir(parents=True, exist_ok=True)
    rag_env = {
        "PYTHONPATH": _managed_pythonpath(evaluation_root),
        "USERPROFILE": str(rag_home),
        "HOME": str(rag_home),
        "HF_HOME": str(HF_CACHE.resolve()),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    }
    observer_env = {
        "PYTHONPATH": _managed_pythonpath(evaluation_root),
    }
    backend_env = {
        "PYTHONPATH": _managed_pythonpath(
            evaluation_root, backend_src, database_src
        ),
        "USERNAME": EVALUATION_PROCESS_USERNAME,
        "SMHAI_ENVIRONMENT": "local",
        "SMHAI_HOST": "127.0.0.1",
        "SMHAI_PORT": "8080",
        "SMHAI_PERSISTENCE_MODE": "mysql",
        "SMHAI_CAT__MODE": "http",
        "SMHAI_CAT__BASE_URL": cat_url,
        "SMHAI_RAG__MODE": "http",
        "SMHAI_RAG__BASE_URL": "http://127.0.0.1:8271",
        "SMHAI_LLM__MODE": "http",
        "SMHAI_LLM__BASE_URL": "http://127.0.0.1:8272",
        "SMHAI_SAFETY__MODE": "http",
        "SMHAI_SAFETY__BASE_URL": safety_url,
        "DATABASE_URL": database_url_for_credential(database_credential),
        "DB_HOST": database_credential.host,
        "DB_PORT": str(database_credential.port),
        "DB_USER": database_credential.username,
        "DB_NAME": database_credential.database,
    }
    backend_version = _python_version(backend_python)
    rag_version = _python_version(rag_python)
    if not backend_version.startswith("3.12."):
        raise RunnerError("managed Backend must use its dedicated Python 3.12 environment")
    backend_lock_identity = _environment_lock_identity(backend_python, "backend")
    required_backend_identity = {
        "python_version",
        "backend_lock_sha256",
        "database_lock_sha256",
        "installed_freeze_sha256",
    }
    if not required_backend_identity <= set(backend_lock_identity):
        raise RunnerError("managed Backend lock identity is missing or mismatched for the pinned environment")
    if backend_lock_identity["python_version"] != backend_version:
        raise RunnerError("managed Backend interpreter version does not match its environment identity")
    rag_lock_identity = _environment_lock_identity(rag_python, "rag")
    if not rag_lock_identity.get("accepted_uv_lock_sha256"):
        raise RunnerError("managed RAG lock identity is missing or mismatched for the pinned environment")
    rag_work = service_root / "isolated-rag-work"
    rag_events.parent.mkdir(parents=True, exist_ok=True)
    runtime_service_endpoint = RUNTIME_HTTP_SERVICE_BASE_URL.rstrip("/")
    if not is_loopback_url(runtime_service_endpoint):
        raise RunnerError("formal Runtime HTTP service must use HTTP loopback")
    if getattr(args, "command", "run") == "run":
        formal_run_id = getattr(args, "run_id", None)
        if not isinstance(formal_run_id, str) or not formal_run_id.startswith("D4RUN-"):
            raise RunnerError("formal Backend compatibility bootstrap requires the current run ID")
        cat_evidence_dir = (service_root / "cat-compatibility").resolve()
        cat_evidence_dir.mkdir(parents=True, exist_ok=True)
        backend_arguments = (
            "-m",
            "harness.controlled_product_eval.evaluation_compatibility",
            "--evidence-dir",
            str(cat_evidence_dir),
            "--run-id",
            formal_run_id,
        )
    else:
        backend_arguments = ("-m", "smhai_backend.main")

    return [
        ProcessSpec(
            name="d4-backend",
            executable=backend_python,
            arguments=backend_arguments,
            cwd=repo_root,
            environment=backend_env,
            readiness_url="http://127.0.0.1:8080/health/ready",
            readiness_kind="backend",
            log_path=service_root / "d4-backend.log",
            interpreter_version=backend_version,
            package_lock_identity=backend_lock_identity,
            environment_allowlist=frozenset(backend_env),
            redaction_values=credential_redactions,
        ),
        ProcessSpec(
            name="d4-rag",
            executable=rag_python,
            arguments=(
                "-m", "harness.controlled_product_eval.rag_runtime",
                "--repo-root", str(repo_root),
                "--corpus-manifest", str(corpus_manifest_path.resolve()),
                "--work-dir", str(rag_work.resolve()),
                "--port", "8170",
            ),
            cwd=repo_root,
            environment=rag_env,
            readiness_url="http://127.0.0.1:8170/health",
            readiness_kind="service",
            log_path=service_root / "d4-rag.log",
            interpreter_version=rag_version,
            package_lock_identity=rag_lock_identity,
            environment_allowlist=frozenset(rag_env),
        ),
        ProcessSpec(
            name="d4-rag-observer",
            executable=backend_python,
            arguments=(
                "-m", "harness.controlled_product_eval.observer_proxy",
                "--name", "rag", "--upstream", "http://127.0.0.1:8170",
                "--events-file", str(rag_events.resolve()), "--port", "8271",
            ),
            cwd=repo_root,
            environment=observer_env,
            readiness_url="http://127.0.0.1:8271/health",
            readiness_kind="service",
            log_path=service_root / "d4-rag-observer.log",
            interpreter_version=backend_version,
            package_lock_identity=backend_lock_identity,
            environment_allowlist=frozenset(observer_env),
        ),
        ProcessSpec(
            name="d4-llm-observer",
            executable=backend_python,
            arguments=(
                "-m", "harness.controlled_product_eval.observer_proxy",
                "--name", "llm", "--upstream", runtime_service_endpoint,
                "--events-file", str(llm_events.resolve()), "--port", "8272",
            ),
            cwd=repo_root,
            environment=observer_env,
            readiness_url="http://127.0.0.1:8272/health",
            readiness_kind="service",
            log_path=service_root / "d4-llm-observer.log",
            interpreter_version=backend_version,
            package_lock_identity=backend_lock_identity,
            environment_allowlist=frozenset(observer_env),
        ),
    ]


async def _run_managed(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[4]
    output_root = Path(args.output_root).resolve()
    backend_python = BACKEND_PYTHON.resolve()
    rag_python = RAG_PYTHON.resolve()
    backend_version = _python_version(backend_python)
    if not backend_version.startswith("3.12."):
        raise RunnerError("managed Backend must use its dedicated Python 3.12 environment")
    backend_lock_identity = _environment_lock_identity(backend_python, "backend")
    required_backend_identity = {
        "python_version",
        "backend_lock_sha256",
        "database_lock_sha256",
        "installed_freeze_sha256",
    }
    if not required_backend_identity <= set(backend_lock_identity):
        raise RunnerError("managed Backend lock identity is missing or mismatched for the pinned environment")
    if backend_lock_identity["python_version"] != backend_version:
        raise RunnerError("managed Backend interpreter version does not match its environment identity")
    _python_version(rag_python)
    rag_lock_identity = _environment_lock_identity(rag_python, "rag")
    if not rag_lock_identity.get("accepted_uv_lock_sha256"):
        raise RunnerError("managed RAG lock identity is missing or mismatched for the pinned environment")

    if output_root.is_relative_to(repo_root):
        raise RunnerError("managed run output and temporary indexes must be outside the project checkout")
    try:
        output_root.relative_to(D4_TASK_TOOLS_ROOT.resolve())
    except ValueError:
        raise RunnerError("managed run output must stay under the pinned D4 task-tools root") from None
    if output_root == D4_TASK_TOOLS_ROOT.resolve():
        raise RunnerError("managed run output must use a new child directory under the task-tools root")
    if output_root.exists() and any(output_root.iterdir()):
        raise RunnerError("managed run output root must be fresh or empty")
    output_root.mkdir(parents=True, exist_ok=True)

    packet = load_approved_packet(args.packet)
    manifest_dir = output_root / "input-manifests"
    prepared = prepare_assets(args.packet, manifest_dir)
    args.case_manifest = prepared["case_manifest_path"]
    args.corpus_manifest = prepared["corpus_manifest_path"]
    args.repo_root = str(repo_root)
    args.backend_python = str(backend_python)
    args.rag_python = str(rag_python)
    service_root = output_root / "managed-services" / uuid.uuid4().hex
    rag_events = service_root / "events" / "rag.jsonl"
    llm_events = service_root / "events" / "llm.jsonl"
    args.backend_url = "http://127.0.0.1:8080"
    args.rag_observer_url = "http://127.0.0.1:8271"
    args.llm_observer_url = "http://127.0.0.1:8272"
    args.rag_observer_events = str(rag_events)
    args.llm_observer_events = str(llm_events)
    attempt_id = create_run_id() if args.command == "run" else f"D4SMOKE-{uuid.uuid4().hex}"
    if args.command == "run":
        args.run_id = attempt_id
    current_runtime_pointer = D4_TASK_TOOLS_ROOT / "runtime-preflight-current.json"

    provider = EvaluationCredentialProvider()
    preflight_root = output_root / "preflight"
    preflight_root.mkdir(parents=True, exist_ok=True)
    try:
        synthetic_credentials = provider.resolve_frozen_synthetic_credentials(repo_root)
    except CredentialProviderError as exc:
        write_json_once(
            output_root / "premanifest-stop.json",
            {
                "status": "CONTROLLER_DECISION_REQUIRED",
                "stage": "CREDENTIAL_SOURCE_GATE",
                "error_type": type(exc).__name__,
                "formal_manifest_count": 0,
                "formal_support_posts": 0,
                "formal_case_count": 0,
                "credential_values_recorded": False,
            },
        )
        raise RunnerError("evaluation credential provider failed its fixed source gate") from None

    supervisor = ProcessSupervisor(startup_timeout_seconds=args.service_startup_timeout_seconds)
    mysql_bootstrap = IsolatedMySqlBootstrap(
        repo_root=repo_root,
        run_root=service_root,
        backend_python=backend_python,
    )
    database_credential: DatabaseCredential | None = None
    transport: CanonicalHttpTransport | None = None
    result: dict[str, Any] | None = None
    startup_error: Exception | None = None
    current_stage = "FIXED_PROFILE_AND_PORT_PREFLIGHT"
    login_gate_result: Mapping[str, Mapping[str, str]] | None = None
    external_profiles = None
    profiles_by_name: dict[str, ProcessSpec] = {}
    runtime_preflight: dict[str, Any] | None = None
    pointer_published = False
    try:
        external_profiles = build_external_service_profiles(repo_root, service_root)
        mysql_spec = mysql_bootstrap.server_spec()
        port_preflight = preflight_formal_port_owners(
            profiles={**external_profiles.profiles, mysql_spec.name: mysql_spec},
            stale_profiles=external_profiles.stale_profiles,
            evidence_path=preflight_root / "formal-port-inventory.json",
        )
        write_json_once(
            preflight_root / "profile-source-identities.json",
            build_profile_source_identity_record(
                repo_root=repo_root,
                attempt_id=attempt_id,
                formal_port_preflight_status=str(port_preflight["status"]),
                services=external_profiles.source_evidence,
            ),
        )

        current_stage = "FRESH_MYSQL_BOOTSTRAP"
        mysql_server_evidence = await mysql_bootstrap.start_server(supervisor)
        write_json_once(preflight_root / "mysql-server.json", mysql_server_evidence)

        current_stage = "DATABASE_CREDENTIAL_GENERATION"
        database_credential = provider.generate_database_credential()
        write_json_once(
            preflight_root / "credential-bootstrap.json",
            {
                "schema_version": "d4-3b-credential-bootstrap.v1",
                "database_credential": credential_evidence_metadata(),
                "fixture_source": {
                    "path": FIXTURE_SOURCE_RELATIVE.as_posix(),
                    "accepted_baseline_commit": ACCEPTED_PRODUCT_BASELINE,
                    "source_blob_match": True,
                    "expected_subjects": dict(EXPECTED_SYNTHETIC_SUBJECTS),
                },
                "credential_manager_target": "IGNORED_UNCLASSIFIED_CREDENTIAL_TARGET",
            },
        )

        current_stage = "MYSQL_DATABASE_MIGRATION"
        mysql_evidence = mysql_bootstrap.provision_database(database_credential)
        write_json_once(preflight_root / "mysql-bootstrap.json", mysql_evidence.as_dict())

        specs = _managed_specs(
            args=args,
            repo_root=repo_root,
            service_root=service_root,
            corpus_manifest_path=Path(args.corpus_manifest),
            runtime=None,
            rag_events=rag_events,
            llm_events=llm_events,
            database_credential=database_credential,
            credential_redactions=synthetic_credentials.secret_values(),
        )
        profiles_by_name = {
            "d4-mysql": mysql_spec,
            **external_profiles.profiles,
            **{spec.name: spec for spec in specs},
        }
        transport = CanonicalHttpTransport(
            backend_base_url=args.backend_url,
            observer_urls={"rag": args.rag_observer_url, "llm": args.llm_observer_url},
            rag_observer_events=args.rag_observer_events,
            llm_observer_events=args.llm_observer_events,
            passwords=synthetic_credentials.password_mapping(),
            cat_instrument_id=str(external_profiles.source_evidence["cat"]["instrument_id"]),
            cat_instrument_version=str(external_profiles.source_evidence["cat"]["instrument_version"]),
            timeout_seconds=args.timeout_seconds,
            network_monitor=LoopbackNetworkMonitor(owned_pids=supervisor.process_tree_pids),
        )

        current_stage = "EXTERNAL_SERVICE_COLD_START"
        for service_name in ("d4-opa", "d4-safety", "d4-ollama", "d4-runtime", "d4-cat"):
            await supervisor.start_service(profiles_by_name[service_name])
        runtime_attestation = await verify_external_service_readiness(
            supervisor=supervisor,
            profiles=profiles_by_name,
            source_evidence=external_profiles.source_evidence,
            attempt_id=attempt_id,
            run_root=output_root,
            current_pointer=current_runtime_pointer,
        )
        pointer_published = True
        runtime_preflight = dict(runtime_attestation["preflight"])
        RuntimePreflight.from_mapping(runtime_preflight, require_live_binding=True)
        args.runtime_preflight = runtime_attestation["run_preflight_path"]
        write_json_once(
            preflight_root / "external-service-readiness.json",
            {
                "schema_version": "d4-external-service-readiness.v1",
                "attempt_id": attempt_id,
                "status": "PASS",
                "profile_source_evidence": runtime_attestation["profile_source_evidence"],
                "opa_live_http_status": 200,
                "safety_health": runtime_attestation["safety_health"],
                "ollama_version": runtime_attestation["ollama_version"],
                "ollama_model": runtime_attestation["ollama_model"],
                "runtime_health": runtime_attestation["runtime_health"],
                "cat_health": runtime_attestation["cat_health"],
                "network": runtime_attestation["network"],
                "runtime_preflight_path": runtime_attestation["run_preflight_path"],
                "runtime_preflight_hash": runtime_preflight["preflight_hash"],
                "current_pointer_path": str(current_runtime_pointer.resolve()),
            },
        )

        current_stage = "BACKEND_STARTUP_AND_SYNTHETIC_LOGIN_GATE"
        await supervisor.start_service(profiles_by_name["d4-backend"])
        try:
            login_gate_result = await transport.login_gate()
        except Exception:
            write_json_once(
                preflight_root / "synthetic-login-gate.json",
                {
                    "status": "FAIL",
                    "reason_code": "SYNTHETIC_LOGIN_GATE_FAILED",
                    "formal_support_posts": 0,
                    "formal_cases_consumed": 0,
                },
            )
            raise RunnerError("synthetic login gate failed; fresh accounts were not modified") from None
        write_json_once(
            preflight_root / "synthetic-login-gate.json",
            {
                "status": "PASS",
                "students": {key: dict(value) for key, value in login_gate_result.items()},
                "formal_support_posts": 0,
                "formal_cases_consumed": 0,
            },
        )

        current_stage = "FRESH_RAG_INDEX_AND_OBSERVERS"
        await supervisor.start_service(profiles_by_name["d4-rag"])
        await supervisor.start_service(profiles_by_name["d4-rag-observer"])
        await supervisor.start_service(profiles_by_name["d4-llm-observer"])

        full_stack_network = verify_runtime_attestation_still_live(
            runtime_preflight,
            supervisor=supervisor,
            profiles=profiles_by_name,
        )
        write_json_once(preflight_root / "full-stack-network-gate.json", full_stack_network)

        current_stage = "FULL_REAL_HTTP_PREFLIGHT"
        real_http_gate = await transport.preflight()
        write_json_once(
            preflight_root / "full-real-http-gate.json",
            {
                "status": "PASS" if not real_http_gate.get("unexpected_configuration") else "FAIL",
                "attempt_id": attempt_id,
                "backend": real_http_gate.get("backend"),
                "observers": real_http_gate.get("observers"),
                "rag_service_identity": real_http_gate.get("rag_service_identity"),
                "runtime_endpoint_health_identity": real_http_gate.get("runtime_endpoint_health_identity"),
                "backend_dependency_identity": real_http_gate.get("backend_dependency_identity"),
                "unexpected_configuration": list(real_http_gate.get("unexpected_configuration", ())),
                "network_observation": real_http_gate.get("network_observation"),
                "formal_support_posts": 0,
                "formal_cases_consumed": 0,
            },
        )
        if real_http_gate.get("unexpected_configuration"):
            raise RunnerError("full REAL_HTTP preflight found unexpected configuration or network integrity failures")
        verify_runtime_attestation_still_live(
            runtime_preflight,
            supervisor=supervisor,
            profiles=profiles_by_name,
        )

        current_stage = "PREMANIFEST_SECRET_SCAN"
        secret_values = (
            database_credential.password,
            *synthetic_credentials.secret_values(),
        )
        premanifest_scan = scan_secret_artifacts(output_root, secret_values)
        write_json_once(preflight_root / "secret-scan.json", premanifest_scan)
        if premanifest_scan.get("status") != "PASS":
            raise RunnerError("premanifest credential artifact scan failed")

        managed_identity = {
            "owner": "D4_EVALUATION_HARNESS",
            "cleanup_policy": "TERMINATE_ONLY_HARNESS_OWNED_LOOPBACK_PROCESSES",
            "runtime_process_owned": True,
            "services": [
                {
                    "name": row["name"],
                    "pid": int(row["pid"]),
                    "parent_pid": int(row["parent_pid"]),
                    "process_tree_pids": list(row["process_tree_pids"]),
                    "executable": row["executable"],
                    "executable_sha256": row["executable_sha256"],
                    "argv_redacted": list(row["argv_redacted"]),
                    "cwd": row["cwd"],
                    "command_sha256": row["command_sha256"],
                    "readiness_url": row["readiness_url"],
                    "log_path": row["log_path"],
                    "stderr_log_path": row["stderr_log_path"],
                    "started_at": row["started_at"],
                    "health": dict(row["health"]),
                    "ownership": row["ownership"],
                    "interpreter_version": row["interpreter_version"],
                    "package_lock_identity": dict(row["package_lock_identity"]),
                }
                for row in supervisor.identities()
            ],
        }
        current_stage = "COLD_START_SMOKE" if args.command == "smoke-lifecycle" else "FORMAL_EVALUATION"
        if args.command == "smoke-lifecycle":
            await transport.prepare()
            current_stage = "POST_PREPARE_INTEGRITY_GATE"
            post_prepare_integrity = await assert_post_prepare_integrity(transport, real_http_gate)
            network_after_prepare = post_prepare_integrity["network_observation"]
            smoke = {
                "schema_version": "d4-full-stack-cold-start-smoke.v1",
                "status": "PASS",
                "attempt_id": attempt_id,
                "profile_count": len(managed_identity["services"]),
                "formal_manifest_count": 0,
                "formal_support_post_count": 0,
                "formal_case_count": 0,
                "formal_case_retries": 0,
                "runtime_preflight_hash": runtime_preflight["preflight_hash"],
                "synthetic_login_gate": "PASS",
                "full_real_http_gate": "PASS",
                "network_after_prepare": network_after_prepare,
                "service_processes": managed_identity["services"],
            }
            write_json_once(output_root / "cold-start-smoke.json", smoke)
            result = {
                "run_id": None,
                "manifest_path": None,
                "manifest_hash": None,
                "results": [],
                "summary": {
                    "run_status": "COLD_START_SMOKE_PASS",
                    "execution_integrity_status": "PASS",
                    "formal_manifest_count": 0,
                    "formal_support_post_count": 0,
                    "formal_case_count": 0,
                    "formal_case_retries": 0,
                    "cleanup_verified": False,
                },
            }
        else:
            result = await _run(
                args,
                managed_service_identity=managed_identity,
                live_service_process_tree_pids=supervisor.service_process_tree_pids,
                transport=transport,
                cat_compatibility_context={
                    "fixture_activation_path": service_root / "cat-compatibility" / "fixture-activation.json",
                    "attempt_root": output_root,
                    "backend_process_pids": supervisor.service_process_tree_pids("d4-backend"),
                    "cat_profile_evidence": runtime_attestation["profile_source_evidence"].get("cat"),
                    "cat_health": runtime_attestation["cat_health"],
                    "repo_root": repo_root,
                    "accepted_baseline_commit": ACCEPTED_D4_3A_COMMIT,
                    "synthetic_subject_ids": tuple(EXPECTED_SYNTHETIC_SUBJECTS.values()),
                },
            )
    except Exception as exc:
        startup_error = exc
    finally:
        if transport is not None:
            try:
                await transport.close()
            except Exception:
                if startup_error is None:
                    startup_error = RunnerError("managed transport cleanup failed")
                    current_stage = "TRANSPORT_CLEANUP"
        cleanup = await supervisor.close()
        pointer_invalidated = (
            invalidate_current_runtime_pointer(
                current_runtime_pointer,
                attempt_id=attempt_id,
                reason="supervisor_cleanup_verified" if cleanup.get("cleanup_verified") else "supervisor_cleanup_unverified",
            )
            if pointer_published
            else False
        )

    lifecycle = {
        "schema_version": "d4-slice3b-service-lifecycle.v1",
        "run_id": result.get("run_id") if result else None,
        "manifest_hash": result.get("manifest_hash") if result else None,
        "runtime_process_owned": True,
        "attempt_id": attempt_id,
        "runtime_preflight_pointer_invalidated_after_cleanup": pointer_invalidated,
        **cleanup,
    }
    lifecycle_target = (
        output_root / str(result["run_id"]) / "service-lifecycle.json"
        if result and result.get("run_id")
        else service_root / "service-lifecycle.json"
    )
    lifecycle_path = write_json_once(lifecycle_target, lifecycle)

    secret_values = synthetic_credentials.secret_values()
    if database_credential is not None:
        secret_values = (*secret_values, database_credential.password)
    if startup_error is not None and result is None:
        formal_manifests = [
            path
            for path in output_root.rglob("manifest.json")
            if path.is_file()
        ]
        case_result_files = [
            path
            for path in output_root.rglob("cases/*.json")
            if path.is_file()
        ]
        stop_path = (
            output_root / "premanifest-stop.json"
            if not formal_manifests
            else output_root / "post-manifest-execution-stop.json"
        )
        unknown_port = "UNKNOWN_PROCESS_OCCUPIES_REQUIRED_FORMAL_PORT" in str(startup_error)
        post_prepare_integrity_failure = isinstance(startup_error, PostPrepareIntegrityError)
        stop_record = {
            "status": "CONTROLLER_DECISION_REQUIRED" if unknown_port or post_prepare_integrity_failure else "PREMANIFEST_LIFECYCLE_FAILURE",
            "reason_code": (
                "UNKNOWN_PROCESS_OCCUPIES_REQUIRED_FORMAL_PORT"
                if unknown_port
                else "PREMANIFEST_POST_PREPARE_INTEGRITY_FAILURE"
                if post_prepare_integrity_failure
                else type(startup_error).__name__
            ),
            "stage": current_stage,
            "error_type": type(startup_error).__name__,
            "prepare_completed": post_prepare_integrity_failure,
            "integrity_status": "FAIL" if post_prepare_integrity_failure else None,
            "integrity_violation_codes": list(startup_error.violation_codes) if post_prepare_integrity_failure else [],
            "integrity_error_type": startup_error.error_type if post_prepare_integrity_failure else None,
            "formal_manifest_created": bool(formal_manifests),
            "formal_manifest_count": len(formal_manifests),
            "formal_support_post_count": 0 if not formal_manifests else "UNKNOWN",
            "formal_case_result_file_count": len(case_result_files),
            "formal_case_count": len(case_result_files),
            "formal_case_retries": 0 if not formal_manifests else "UNKNOWN",
            "retry_count": 0 if not formal_manifests else "UNKNOWN",
            "credential_values_recorded": False,
        }
        failure_detail = _safe_startup_failure_detail(startup_error, stage=current_stage)
        if failure_detail:
            stop_record["failure_detail"] = failure_detail
        write_json_once(stop_path, stop_record)

    final_scan = scan_secret_artifacts(output_root, secret_values)
    write_json_once(output_root / "final-secret-scan.json", final_scan)
    if final_scan.get("status") != "PASS":
        write_json_once(
            output_root / "post-run-integrity-stop.json",
            {
                "status": "CONTROLLER_DECISION_REQUIRED",
                "reason_code": "PLAINTEXT_CREDENTIAL_ARTIFACT_OR_UNREADABLE_FILE",
                "manifest_created": bool(result and result.get("manifest_path")),
                "formal_case_count": len(result.get("results", ())) if result else 0,
                "plaintext_occurrences": final_scan.get("plaintext_occurrences", 0),
                "unreadable_file_count": final_scan.get("unreadable_file_count", 0),
            },
        )
        if result is not None:
            result.setdefault("summary", {})["run_status"] = "CONTROLLER_DECISION_REQUIRED"
            result["summary"]["execution_integrity_status"] = "FAIL"
    if startup_error is not None:
        failure_detail = _safe_startup_failure_detail(startup_error, stage=current_stage)
        failure_suffix = f"; failure_detail={failure_detail}" if failure_detail else ""
        raise RunnerError(
            f"managed D4-3B run stopped at {current_stage}; "
            f"error_type={type(startup_error).__name__}; "
            f"cleanup_verified={cleanup['cleanup_verified']}{failure_suffix}"
        ) from None
    assert result is not None
    result["service_lifecycle_path"] = str(lifecycle_path)
    result["cleanup_verified"] = cleanup["cleanup_verified"]
    if args.command == "smoke-lifecycle" and isinstance(result.get("summary"), dict):
        result["summary"]["cleanup_verified"] = cleanup["cleanup_verified"]
    if not cleanup["cleanup_verified"]:
        result["summary"]["run_status"] = "CONTROLLER_DECISION_REQUIRED"
        result["summary"]["cleanup_verified"] = False
    if final_scan.get("status") != "PASS":
        result["summary"]["run_status"] = "CONTROLLER_DECISION_REQUIRED"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="D4-3B evaluation-only harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare-assets", help="verify Gold and freeze deterministic case/corpus manifests")
    prepare.add_argument("--packet", default=str(_default_packet()))
    prepare.add_argument("--manifest-dir", required=True)

    for command, help_text in (
        ("run", "cold-start the fixed local stack and run the frozen 12-case evaluation"),
        ("smoke-lifecycle", "cold-start and clean the fixed local stack without formal support requests"),
    ):
        attempt = subparsers.add_parser(command, help=help_text)
        attempt.add_argument("--packet", default=str(_default_packet()))
        attempt.add_argument("--output-root", required=True)
        attempt.add_argument("--timeout-seconds", type=float, default=150.0)
        attempt.add_argument("--service-startup-timeout-seconds", type=float, default=180.0)

    args = parser.parse_args()
    try:
        if args.command == "prepare-assets":
            result = prepare_assets(args.packet, args.manifest_dir)
        else:
            result = asyncio.run(_run_managed(args))
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (ApprovedPacketError, LifecycleError, ManifestError, RunnerError, OSError, ValueError) as exc:
        decision_required = "UNKNOWN_PROCESS_OCCUPIES_REQUIRED_FORMAL_PORT" in str(exc)
        print(json.dumps({"status": "CONTROLLER_DECISION_REQUIRED" if decision_required else "PREMANIFEST_LIFECYCLE_FAILURE", "error_type": type(exc).__name__, "detail": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
