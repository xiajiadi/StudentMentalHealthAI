"""Command-line entry points for preparing and executing D4-3B evaluation."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .approved_packet import ApprovedPacketError, load_approved_packet
from .manifest import (
    ManifestError,
    RuntimePreflight,
    build_approved_corpus_manifest,
    build_case_manifest,
    is_loopback_url,
    write_json_once,
)
from .process_lifecycle import LifecycleError, ProcessSpec, ProcessSupervisor
from .runner import CanonicalHttpTransport, RunnerError, run_evaluation

RUNTIME_HTTP_SERVICE_BASE_URL = "http://127.0.0.1:8160"


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
    transport = CanonicalHttpTransport.from_environment(
        backend_base_url=args.backend_url,
        observer_urls={"rag": args.rag_observer_url, "llm": args.llm_observer_url},
        rag_observer_events=args.rag_observer_events,
        llm_observer_events=args.llm_observer_events,
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
    )


def _managed_pythonpath(base: str | None, *paths: Path) -> str:
    ordered = [str(path.resolve()) for path in paths]
    if base:
        ordered.append(base)
    return os.pathsep.join(ordered)


def _evaluation_database_endpoint() -> tuple[str, int]:
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        try:
            parsed = urlparse(database_url)
            host = parsed.hostname or ""
            port = parsed.port or 3306
        except ValueError as exc:
            raise RunnerError("evaluation DATABASE_URL is invalid") from exc
    else:
        host = os.environ.get("DB_HOST", "127.0.0.1")
        try:
            port = int(os.environ.get("DB_PORT", "3306"))
        except ValueError as exc:
            raise RunnerError("evaluation DB_PORT is invalid") from exc
        if not all(os.environ.get(name) for name in ("DB_USER", "DB_PASSWORD", "DB_NAME")):
            raise RunnerError("evaluation MySQL credentials must come from local environment secrets")

    try:
        loopback = host.lower() == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise RunnerError("formal evaluation MySQL must use a loopback endpoint")
    if port == 3306:
        raise RunnerError("formal evaluation must use an isolated MySQL port, not shared port 3306")
    if not 1 <= port <= 65_535:
        raise RunnerError("evaluation MySQL port is invalid")
    return host, port


def _managed_specs(
    *,
    args: argparse.Namespace,
    repo_root: Path,
    service_root: Path,
    corpus_manifest_path: Path,
    runtime: RuntimePreflight,
    rag_events: Path,
    llm_events: Path,
) -> list[ProcessSpec]:
    backend_python = Path(args.backend_python).resolve()
    rag_python = Path(args.rag_python).resolve()
    evaluation_root = repo_root / "12_evaluation" / "d4-evaluation-r1"
    backend_src = repo_root / "09_backend" / "src"
    database_src = repo_root / "11_database"
    if not evaluation_root.is_dir() or not backend_src.is_dir() or not database_src.is_dir():
        raise RunnerError("managed service startup requires the accepted evaluation and Backend source roots")

    _evaluation_database_endpoint()
    cat_url = os.environ.get("SMHAI_CAT__BASE_URL", "http://127.0.0.1:8180")
    safety_url = os.environ.get("SMHAI_SAFETY__BASE_URL", "http://127.0.0.1:8190")
    if not is_loopback_url(cat_url) or not is_loopback_url(safety_url):
        raise RunnerError("formal CAT and Safety endpoints must use HTTP loopback")
    service_root.mkdir(parents=True, exist_ok=True)
    rag_env = {
        "PYTHONPATH": _managed_pythonpath(os.environ.get("PYTHONPATH"), evaluation_root),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    }
    observer_env = {
        "PYTHONPATH": _managed_pythonpath(os.environ.get("PYTHONPATH"), evaluation_root),
    }
    backend_env = {
        "PYTHONPATH": _managed_pythonpath(
            os.environ.get("PYTHONPATH"), evaluation_root, backend_src, database_src
        ),
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
    }
    rag_work = service_root / "isolated-rag-work"
    rag_events.parent.mkdir(parents=True, exist_ok=True)
    runtime_service_endpoint = RUNTIME_HTTP_SERVICE_BASE_URL.rstrip("/")
    if not is_loopback_url(runtime_service_endpoint):
        raise RunnerError("formal Runtime HTTP service must use HTTP loopback")
    return [
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
        ),
        ProcessSpec(
            name="d4-backend",
            executable=backend_python,
            arguments=("-m", "smhai_backend.main"),
            cwd=repo_root,
            environment=backend_env,
            readiness_url="http://127.0.0.1:8080/health/ready",
            readiness_kind="backend",
            log_path=service_root / "d4-backend.log",
        ),
    ]


async def _run_managed(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve()
    output_root = Path(args.output_root).resolve()
    try:
        output_root.relative_to(repo_root)
    except ValueError:
        pass
    else:
        raise RunnerError("managed run output and temporary indexes must be outside the project checkout")
    packet = load_approved_packet(args.packet)
    runtime_mapping = _read_json(args.runtime_preflight)
    runtime = RuntimePreflight.from_mapping(runtime_mapping)
    manifest_dir = output_root / "input-manifests"
    prepared = prepare_assets(args.packet, manifest_dir)
    args.case_manifest = args.case_manifest or prepared["case_manifest_path"]
    args.corpus_manifest = args.corpus_manifest or prepared["corpus_manifest_path"]
    service_root = output_root / "managed-services" / uuid.uuid4().hex
    rag_events = service_root / "events" / "rag.jsonl"
    llm_events = service_root / "events" / "llm.jsonl"
    args.backend_url = "http://127.0.0.1:8080"
    args.rag_observer_url = "http://127.0.0.1:8271"
    args.llm_observer_url = "http://127.0.0.1:8272"
    args.rag_observer_events = str(rag_events)
    args.llm_observer_events = str(llm_events)
    specs = _managed_specs(
        args=args,
        repo_root=repo_root,
        service_root=service_root,
        corpus_manifest_path=Path(args.corpus_manifest),
        runtime=runtime,
        rag_events=rag_events,
        llm_events=llm_events,
    )
    supervisor = ProcessSupervisor(startup_timeout_seconds=args.service_startup_timeout_seconds)
    result: dict[str, Any] | None = None
    startup_error: Exception | None = None
    await supervisor.start(specs)
    managed_identity = {
        "owner": "D4_EVALUATION_HARNESS",
        "cleanup_policy": "TERMINATE_ONLY_HARNESS_OWNED_LOOPBACK_PROCESSES",
        "runtime_process_owned": False,
        "services": supervisor.identities(),
    }
    try:
        result = await _run(args, managed_service_identity=managed_identity)
    except Exception as exc:
        startup_error = exc
    cleanup = await supervisor.close()
    lifecycle = {
        "schema_version": "d4-slice3b-service-lifecycle.v1",
        "run_id": result.get("run_id") if result else None,
        "manifest_hash": result.get("manifest_hash") if result else None,
        "runtime_process_owned": False,
        **cleanup,
    }
    lifecycle_target = (
        output_root / str(result["run_id"]) / "service-lifecycle.json"
        if result and result.get("run_id")
        else service_root / "service-lifecycle.json"
    )
    lifecycle_path = write_json_once(lifecycle_target, lifecycle)
    if startup_error is not None:
        raise RunnerError(f"managed D4-3B run stopped: {type(startup_error).__name__}; cleanup_verified={cleanup['cleanup_verified']}") from startup_error
    assert result is not None
    result["service_lifecycle_path"] = str(lifecycle_path)
    result["cleanup_verified"] = cleanup["cleanup_verified"]
    if not cleanup["cleanup_verified"]:
        result["summary"]["run_status"] = "CONTROLLER_DECISION_REQUIRED"
        result["summary"]["cleanup_verified"] = False
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="D4-3B evaluation-only harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare-assets", help="verify Gold and freeze deterministic case/corpus manifests")
    prepare.add_argument("--packet", default=str(_default_packet()))
    prepare.add_argument("--manifest-dir", required=True)

    run = subparsers.add_parser("run", help="run the 12 approved cases through canonical Backend HTTP")
    run.add_argument("--packet", default=str(_default_packet()))
    run.add_argument("--case-manifest")
    run.add_argument("--corpus-manifest")
    run.add_argument("--runtime-preflight", required=True)
    run.add_argument("--repo-root", required=True)
    run.add_argument("--backend-url", default="http://127.0.0.1:8080")
    run.add_argument("--rag-observer-url", default="http://127.0.0.1:8271")
    run.add_argument("--llm-observer-url", default="http://127.0.0.1:8272")
    run.add_argument("--rag-observer-events")
    run.add_argument("--llm-observer-events")
    run.add_argument("--output-root", required=True)
    run.add_argument("--timeout-seconds", type=float, default=150.0)
    run.add_argument("--backend-python")
    run.add_argument("--rag-python")
    run.add_argument("--service-startup-timeout-seconds", type=float, default=180.0)
    lifecycle = run.add_mutually_exclusive_group()
    lifecycle.add_argument("--manage-local-services", dest="manage_local_services", action="store_true")
    lifecycle.add_argument("--use-existing-services", dest="manage_local_services", action="store_false")
    run.set_defaults(manage_local_services=True)

    args = parser.parse_args()
    try:
        if args.command == "prepare-assets":
            result = prepare_assets(args.packet, args.manifest_dir)
        else:
            if args.manage_local_services:
                if not args.backend_python or not args.rag_python:
                    raise RunnerError("managed mode requires --backend-python and --rag-python")
                result = asyncio.run(_run_managed(args))
            else:
                if not args.rag_observer_events or not args.llm_observer_events:
                    raise RunnerError("existing-service mode requires observer event log paths")
                result = asyncio.run(_run(args))
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (ApprovedPacketError, LifecycleError, ManifestError, RunnerError, OSError, ValueError) as exc:
        print(json.dumps({"status": "CONTROLLER_DECISION_REQUIRED", "error_type": type(exc).__name__, "detail": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
