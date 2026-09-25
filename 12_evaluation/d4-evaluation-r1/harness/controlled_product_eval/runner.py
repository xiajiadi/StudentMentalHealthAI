"""One-shot D4-3B runner for the canonical Backend support HTTP route."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

try:
    from harness.foundation.hashing import canonical_json, canonical_sha256_tag
except ModuleNotFoundError:  # pragma: no cover - package-relative import mode
    from ..foundation.hashing import canonical_json, canonical_sha256_tag

from .approved_packet import ApprovedPacket, ApprovedPacketError, load_approved_packet
from .manifest import (
    ACCEPTED_D4_3A_TAG,
    EXPECTED_RUNTIME_IDENTITY,
    FORMAL_ROUTE,
    ManifestError,
    RuntimePreflight,
    build_approved_corpus_manifest,
    build_case_manifest,
    build_formal_manifest,
    corpus_projection_source_map,
    is_loopback_url,
    verify_case_manifest,
    verify_corpus_manifest,
    write_json_once,
)
from .results import (
    FORMAL_EVIDENCE,
    NONFORMAL_EVIDENCE,
    aggregate_results,
    build_case_result,
    classify_p0_p1,
)


CORRELATION_SAFE = re.compile(r"^D4RUN-[A-Za-z0-9][A-Za-z0-9._-]*$")
_CASE_ID_SAFE = re.compile(r"^AW-[A-Z0-9][A-Z0-9_-]*$")


class RunnerError(RuntimeError):
    """A fail-closed runner preflight or one-shot execution error."""


@dataclass(frozen=True, slots=True)
class TransportObservation:
    http_status: int
    response_body: Mapping[str, Any]
    rag_events: tuple[Mapping[str, Any], ...] = ()
    llm_events: tuple[Mapping[str, Any], ...] = ()
    external_network_detected: bool = False


class ProductTransport(Protocol):
    formal: bool

    async def preflight(self) -> Mapping[str, Any]: ...

    async def prepare(self) -> None: ...

    async def submit(
        self,
        case: Mapping[str, Any],
        *,
        run_id: str,
        request_id: str,
        trace_id: str,
        ordinal: int,
    ) -> TransportObservation: ...

    async def close(self) -> None: ...


def _load_jsonl(path: str | Path, *, trace_id: str) -> tuple[Mapping[str, Any], ...]:
    target = Path(path)
    if not target.exists():
        return ()
    events: list[Mapping[str, Any]] = []
    try:
        with target.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, Mapping):
                    raise RunnerError(f"observer event line {line_number} is not an object")
                if value.get("trace_id") == trace_id:
                    events.append(value)
    except (OSError, json.JSONDecodeError) as exc:
        raise RunnerError(f"cannot read observer event log: {type(exc).__name__}") from exc
    return tuple(events)


def _stable_correlation(prefix: str, run_id: str, case_id: str) -> str:
    digest = hashlib.sha256(f"{run_id}\x00{case_id}".encode("utf-8")).hexdigest()[:32]
    return f"{prefix}_D43B_{digest}"


def _api_data(body: Mapping[str, Any]) -> Mapping[str, Any]:
    value = body.get("data")
    return value if isinstance(value, Mapping) else {}


class CanonicalHttpTransport:
    """Use only the canonical Backend API; credentials stay in memory."""

    formal = True

    def __init__(
        self,
        *,
        backend_base_url: str,
        observer_urls: Mapping[str, str],
        rag_observer_events: str | Path,
        llm_observer_events: str | Path,
        passwords: Mapping[str, str] | None = None,
        timeout_seconds: float = 150.0,
    ) -> None:
        if not is_loopback_url(backend_base_url):
            raise RunnerError("formal Backend URL must be HTTP loopback")
        self.backend_base_url = backend_base_url.rstrip("/")
        self.observer_urls = dict(observer_urls)
        if set(self.observer_urls) != {"rag", "llm"}:
            raise RunnerError("RAG and LLM observer endpoints are both required")
        if any(not is_loopback_url(url) for url in self.observer_urls.values()):
            raise RunnerError("observer endpoints must be HTTP loopback")
        self.rag_observer_events = Path(rag_observer_events)
        self.llm_observer_events = Path(llm_observer_events)
        self.passwords = dict(passwords or {})
        self.timeout_seconds = timeout_seconds
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._csrf: dict[str, str] = {}
        self._subjects: dict[str, str] = {}
        self._foreign_assessment_id: str | None = None
        self._prepared = False

    @classmethod
    def from_environment(cls, **kwargs: Any) -> "CanonicalHttpTransport":
        passwords = {
            "student_a": os.environ.get("SMHAI_D4_STUDENT_A_PASSWORD", ""),
            "student_b": os.environ.get("SMHAI_D4_STUDENT_B_PASSWORD", ""),
        }
        if not all(passwords.values()):
            raise RunnerError("synthetic student credentials are missing from the environment")
        return cls(passwords=passwords, **kwargs)

    async def _client(self, username: str) -> httpx.AsyncClient:
        client = self._clients.get(username)
        if client is None:
            client = httpx.AsyncClient(
                base_url=self.backend_base_url,
                headers={"Accept": "application/json"},
                timeout=httpx.Timeout(self.timeout_seconds),
                follow_redirects=False,
                trust_env=False,
            )
            self._clients[username] = client
        return client

    async def preflight(self) -> Mapping[str, Any]:
        if not self.passwords or not all(self.passwords.get(name) for name in ("student_a", "student_b")):
            raise RunnerError("both synthetic test account credentials must be configured")
        backend = await httpx.AsyncClient(
            base_url=self.backend_base_url,
            timeout=httpx.Timeout(5.0),
            follow_redirects=False,
            trust_env=False,
        )
        try:
            response = await backend.get("/health/ready")
            dependencies_response = await backend.get("/health/dependencies")
        finally:
            await backend.aclose()
        if response.status_code != 200:
            raise RunnerError(f"Backend readiness returned HTTP {response.status_code}")
        payload = response.json()
        data = _api_data(payload)
        if data.get("status") != "ready":
            raise RunnerError("Backend is not ready")
        if dependencies_response.status_code != 200:
            raise RunnerError(f"Backend dependency readiness returned HTTP {dependencies_response.status_code}")
        dependency_payload = _api_data(dependencies_response.json())
        required_dependencies = ("cat", "rag", "llm_runtime", "safety")
        dependency_identity: dict[str, dict[str, str]] = {}
        unexpected_configuration: list[str] = []
        for dependency in required_dependencies:
            observed_dependency = dependency_payload.get(dependency)
            if not isinstance(observed_dependency, Mapping):
                raise RunnerError(f"Backend dependency identity is missing: {dependency}")
            status = str(observed_dependency.get("status", "UNKNOWN")).upper()
            integration = str(observed_dependency.get("integration", "UNKNOWN"))
            if status != "READY":
                raise RunnerError(f"Backend dependency is not READY: {dependency}")
            dependency_identity[dependency] = {"status": status, "integration": integration}
            if integration.upper() != "REAL_HTTP":
                unexpected_configuration.append(f"backend_dependency.{dependency}.integration={integration}")

        observer_status: dict[str, Any] = {}
        rag_service_identity: Mapping[str, Any] | None = None
        runtime_endpoint_identity: Mapping[str, Any] | None = None
        for name, url in self.observer_urls.items():
            async with httpx.AsyncClient(
                base_url=url,
                timeout=httpx.Timeout(5.0),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                health = await client.get("/health")
            if health.status_code != 200 or health.json().get("status") != "READY":
                raise RunnerError(f"{name} observer is not ready")
            observed = health.json()
            upstream = observed.get("upstream")
            if not isinstance(upstream, str) or not is_loopback_url(upstream):
                raise RunnerError(f"{name} observer upstream is not loopback")
            if observed.get("observer") != name:
                raise RunnerError(f"{name} observer identity mismatch")
            observer_status[name] = {"status": "READY", "upstream": upstream}
            if name == "rag":
                service_identity = observed.get("service_identity")
                if not isinstance(service_identity, Mapping):
                    raise RunnerError("RAG observer did not expose the isolated service identity")
                rag_service_identity = {"status": "READY", **dict(service_identity)}
            else:
                service_identity = observed.get("service_identity")
                if not isinstance(service_identity, Mapping):
                    raise RunnerError("LLM observer did not expose live Runtime readiness identity")
                if service_identity.get("readiness") != "pass" or service_identity.get("cloud_fallback") is not False:
                    raise RunnerError("upstream Runtime is not ready or reports cloud fallback")
                runtime_endpoint_identity = dict(service_identity)
        return {
            "backend": {"status": "READY", "url": self.backend_base_url},
            "observers": observer_status,
            "rag_service_identity": rag_service_identity,
            "runtime_endpoint_health_identity": runtime_endpoint_identity,
            "backend_dependency_identity": dependency_identity,
            "unexpected_configuration": unexpected_configuration,
            "network_policy": "LOOPBACK_ONLY",
            "trust_env": False,
            "retry_policy": {"max_retries": 0, "non_idempotent_post_retries": 0},
        }

    async def prepare(self) -> None:
        if self._prepared:
            return
        for username in ("student_a", "student_b"):
            client = await self._client(username)
            response = await client.post(
                "/api/v1/auth/login",
                json={"username": username, "password": self.passwords[username]},
            )
            if response.status_code != 200:
                raise RunnerError(f"synthetic fixture login failed for {username}: HTTP {response.status_code}")
            data = _api_data(response.json())
            csrf = data.get("csrf_token")
            actor = data.get("actor")
            subject_id = actor.get("subject_id") if isinstance(actor, Mapping) else None
            if not isinstance(csrf, str) or not csrf or not isinstance(subject_id, str) or not subject_id.startswith("SUBJ_"):
                raise RunnerError(f"synthetic fixture login returned an invalid actor for {username}")
            self._csrf[username] = csrf
            self._subjects[username] = subject_id
        self._foreign_assessment_id = await self._create_assessment("student_b", "D4B_FOREIGN")
        self._prepared = True

    async def _create_assessment(self, username: str, nonce: str) -> str:
        client = await self._client(username)
        headers = {"X-CSRF-Token": self._csrf[username]}
        response = await client.post(
            "/api/v1/assessments",
            headers=headers,
            json={
                "subject_id": self._subjects[username],
                "instrument_id": "instrument.synthetic",
                "instrument_version": "1.0",
            },
        )
        if response.status_code != 201:
            raise RunnerError(f"synthetic assessment bootstrap failed for {username}: HTTP {response.status_code}")
        data = _api_data(response.json())
        assessment_id = data.get("assessment_id")
        if not isinstance(assessment_id, str) or not assessment_id.startswith("ASSESS_"):
            raise RunnerError("assessment bootstrap returned an invalid synthetic assessment ID")
        assessment_id = await self._complete_assessment(username, assessment_id)
        return assessment_id

    async def _complete_assessment(self, username: str, assessment_id: str) -> str:
        client = await self._client(username)
        headers = {"X-CSRF-Token": self._csrf[username]}
        response = await client.post(
            f"/api/v1/assessments/{assessment_id}/responses",
            headers=headers,
            json={"item_id": "ITEM_synthetic_1", "response": 1.0},
        )
        if response.status_code != 200:
            raise RunnerError("synthetic assessment response bootstrap failed")
        complete = await client.post(
            f"/api/v1/assessments/{assessment_id}/complete",
            headers=headers,
            json={},
        )
        if complete.status_code != 200 or _api_data(complete.json()).get("status") != "completed":
            raise RunnerError("synthetic assessment did not complete")
        return assessment_id

    async def submit(
        self,
        case: Mapping[str, Any],
        *,
        run_id: str,
        request_id: str,
        trace_id: str,
        ordinal: int,
    ) -> TransportObservation:
        if not self._prepared:
            raise RunnerError("transport.prepare() must complete before product cases run")
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not _CASE_ID_SAFE.fullmatch(case_id):
            raise RunnerError("case ID is unsafe for a formal request")
        gold_case = case
        expected = gold_case.get("expected_response_class")
        if expected == "MUST_DENY":
            username = "student_a"
            assessment_id = self._foreign_assessment_id
        else:
            username = "student_a" if ordinal % 2 == 0 else "student_b"
            assessment_id = await self._create_assessment(username, f"CASE_{ordinal:02d}")
        if not isinstance(assessment_id, str):
            raise RunnerError("synthetic assessment ID was not prepared")
        request_text = gold_case.get("request")
        if not isinstance(request_text, str):
            raise RunnerError(f"{case_id}: approved request text is missing")

        client = await self._client(username)
        key_hash = hashlib.sha256(f"{run_id}\x00{case_id}".encode("utf-8")).hexdigest()[:32]
        headers = {
            "X-CSRF-Token": self._csrf[username],
            "X-Request-ID": request_id,
            "X-Trace-ID": trace_id,
            "Idempotency-Key": f"D4B_{key_hash}",
        }
        response = await client.post(
            FORMAL_ROUTE,
            headers=headers,
            json={
                "assessment_id": assessment_id,
                "target_role": "student",
                "message": request_text,
                "language": "zh-CN",
            },
        )
        try:
            body = response.json()
        except ValueError:
            body = {"response_body_invalid_json": True}
        if not isinstance(body, Mapping):
            body = {"response_body_not_object": True}
        return TransportObservation(
            http_status=response.status_code,
            response_body=body,
            rag_events=_load_jsonl(self.rag_observer_events, trace_id=trace_id),
            llm_events=_load_jsonl(self.llm_observer_events, trace_id=trace_id),
            external_network_detected=False,
        )

    async def close(self) -> None:
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()


def _write_case_result(run_dir: Path, result: Mapping[str, Any]) -> Path:
    case_id = str(result.get("case_id", ""))
    if not _CASE_ID_SAFE.fullmatch(case_id):
        raise RunnerError("result case ID cannot be used as a file name")
    path = run_dir / "cases" / f"{case_id}.json"
    return write_json_once(path, result)


async def run_evaluation(
    *,
    packet: ApprovedPacket,
    case_manifest: Mapping[str, Any],
    corpus_manifest: Mapping[str, Any],
    runtime_preflight: Mapping[str, Any] | RuntimePreflight,
    transport: ProductTransport,
    backend_base_url: str,
    observer_endpoints: Mapping[str, str],
    rag_observer_events: str | Path,
    llm_observer_events: str | Path,
    repo_root: str | Path,
    output_root: str | Path,
    managed_service_identity: Mapping[str, Any] | None = None,
    timestamp: Any = None,
    run_id: str | None = None,
    entropy: str | bytes | None = None,
    unexpected_configuration: Sequence[str] = (),
) -> dict[str, Any]:
    """Run exactly one immutable 12-case plan without automatic retries."""

    if not isinstance(transport, CanonicalHttpTransport):
        raise RunnerError("formal execution requires the canonical HTTP transport")
    packet.verify_unchanged()
    verify_case_manifest(case_manifest, packet=packet)
    verify_corpus_manifest(corpus_manifest, packet=packet)
    # Runtime, protected-source, and loopback gates run before product transport starts.
    if not isinstance(runtime_preflight, RuntimePreflight):
        runtime_preflight = RuntimePreflight.from_mapping(runtime_preflight)
    preflight_observation = await transport.preflight()
    rag_service_identity = preflight_observation.get("rag_service_identity")
    if not isinstance(rag_service_identity, Mapping):
        raise RunnerError("formal preflight has no observed isolated RAG identity")
    if rag_service_identity.get("corpus_manifest_hash") != corpus_manifest.get("corpus_hash"):
        raise RunnerError("running RAG service is bound to a different temporary corpus")
    if rag_service_identity.get("source_packet_hash") != packet.packet_hash:
        raise RunnerError("running RAG service was not built from the approved Human Gold packet")
    if rag_service_identity.get("source_packet_id") != packet.packet_id:
        raise RunnerError("running RAG service has the wrong approved packet ID")
    runtime_endpoint_identity = preflight_observation.get("runtime_endpoint_health_identity")
    if not isinstance(runtime_endpoint_identity, Mapping):
        raise RunnerError("formal preflight has no live Runtime readiness identity")
    backend_dependency_identity = preflight_observation.get("backend_dependency_identity")
    if not isinstance(backend_dependency_identity, Mapping):
        raise RunnerError("formal preflight has no Backend dependency identity")
    observed_unexpected = preflight_observation.get("unexpected_configuration", ())
    if not isinstance(observed_unexpected, Sequence) or isinstance(observed_unexpected, (str, bytes)):
        raise RunnerError("Backend configuration audit is malformed")
    all_unexpected_configuration = tuple(sorted(set(unexpected_configuration) | {str(item) for item in observed_unexpected}))

    manifest = build_formal_manifest(
        packet=packet,
        case_manifest=case_manifest,
        corpus_manifest=corpus_manifest,
        runtime_preflight=runtime_preflight,
        backend_base_url=backend_base_url,
        observer_endpoints=observer_endpoints,
        rag_service_identity=rag_service_identity,
        runtime_endpoint_identity=runtime_endpoint_identity,
        backend_dependency_identity=backend_dependency_identity,
        managed_service_identity=managed_service_identity,
        repo_root=repo_root,
        timestamp=timestamp,
        run_id=run_id,
        entropy=entropy,
        unexpected_configuration=all_unexpected_configuration,
    )
    actual_run_id = str(manifest["run_id"])
    run_dir = Path(output_root) / actual_run_id
    manifest_path = write_json_once(run_dir / "manifest.json", manifest)

    if all_unexpected_configuration:
        stop = {
            "schema_version": "d4-slice3b-preflight-stop.v1",
            "run_id": actual_run_id,
            "status": "CONTROLLER_DECISION_REQUIRED",
            "reason": "unexpected non-secret product configuration was recorded before any support request",
            "unexpected_configuration": list(all_unexpected_configuration),
            "manifest_hash": manifest["manifest_hash"],
            "product_requests": 0,
            "runtime_calls": 0,
            "model_calls": 0,
            "formal_case_count": 0,
            "expected_case_count": len(packet.answerability_cases),
        }
        stop_path = write_json_once(run_dir / "preflight-stop.json", stop)
        await transport.close()
        return {
            "run_id": actual_run_id,
            "manifest_path": str(manifest_path),
            "preflight_stop_path": str(stop_path),
            "manifest_hash": manifest["manifest_hash"],
            "results": [],
            "summary": stop,
            "abort": stop,
            "evidence_status": FORMAL_EVIDENCE,
        }

    results: list[dict[str, Any]] = []
    abort: dict[str, Any] | None = None
    try:
        await transport.prepare()
        for ordinal, case in enumerate(packet.answerability_cases):
            packet.verify_unchanged()
            case_id = str(case["case_id"])
            request_id = _stable_correlation("REQ", actual_run_id, case_id)
            trace_id = _stable_correlation("TRACE", actual_run_id, case_id)
            try:
                observation = await transport.submit(
                    case,
                    run_id=actual_run_id,
                    request_id=request_id,
                    trace_id=trace_id,
                    ordinal=ordinal,
                )
            except Exception as exc:
                # Never retry a non-idempotent support request. A timeout may
                # occur after the Backend accepted it, so stop with uncertainty.
                abort = {
                    "case_id": case_id,
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "error_type": type(exc).__name__,
                    "retry_performed": False,
                    "disposition": "STOPPED_WITH_REQUEST_OUTCOME_UNCERTAIN",
                }
                break
            result = build_case_result(
                packet=packet,
                case=case,
                run_id=actual_run_id,
                http_status=observation.http_status,
                response_body=observation.response_body,
                request_id=request_id,
                trace_id=trace_id,
                rag_events=observation.rag_events,
                llm_events=observation.llm_events,
                runtime_preflight_identity=runtime_preflight.identity,
                allowed_evidence_ids=corpus_manifest["evidence_ids"],
                evaluation_to_source_evidence=corpus_projection_source_map(corpus_manifest),
                evidence_status=FORMAL_EVIDENCE,
                external_network_detected=observation.external_network_detected,
            )
            result["retrieval_evidence"]["corpus_identity"] = {
                "corpus_id": corpus_manifest["corpus_id"],
                "corpus_hash": corpus_manifest["corpus_hash"],
            }
            result.pop("result_hash", None)
            result["result_hash"] = canonical_sha256_tag(result, self_field="result_hash")
            _write_case_result(run_dir, result)
            results.append(result)
            if classify_p0_p1(result)["p0_count"]:
                abort = {
                    "case_id": case_id,
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "error_type": "P0_OBSERVED",
                    "retry_performed": False,
                    "disposition": "STOPPED_FOR_CONTROLLER_REVIEW",
                }
                break
    finally:
        await transport.close()

    if results:
        summary = aggregate_results(results)
    else:
        summary = {
            "schema_version": "d4-slice3b-summary.v1",
            "evidence_status": FORMAL_EVIDENCE,
            "run_id": actual_run_id,
            "case_count": 0,
            "case_ids": [],
            "p0_count": 0,
            "p1_count": 0,
            "p0_findings": [],
            "p1_findings": [],
            "metrics_are_category_reports": True,
            "overall_utility_score": None,
            "d4_4_started": False,
        }
    if abort:
        summary["run_status"] = abort["disposition"]
        summary["abort"] = abort
    elif len(results) == len(packet.answerability_cases):
        summary["run_status"] = "RUN_COMPLETE_FOR_CONTROLLER_REVIEW"
    else:
        summary["run_status"] = "RUN_INCOMPLETE"
    summary["expected_case_count"] = len(packet.answerability_cases)
    summary["product_preflight"] = dict(preflight_observation)
    summary["manifest_hash"] = manifest["manifest_hash"]
    summary["run_summary_hash"] = canonical_sha256_tag(summary, self_field="run_summary_hash")
    summary_path = write_json_once(run_dir / "summary.json", summary)
    return {
        "run_id": actual_run_id,
        "manifest_path": str(manifest_path),
        "summary_path": str(summary_path),
        "manifest_hash": manifest["manifest_hash"],
        "results": results,
        "summary": summary,
        "abort": abort,
        "evidence_status": FORMAL_EVIDENCE,
    }


def _mock_response(
    case: Mapping[str, Any],
    source_to_evaluation_ids: Mapping[str, Sequence[str]],
    allowed_ids: Sequence[str],
) -> tuple[int, dict[str, Any], tuple[Mapping[str, Any], ...], tuple[Mapping[str, Any], ...]]:
    expected = case["expected_response_class"]
    case_id = str(case["case_id"])
    if expected == "MUST_ROUTE":
        return (
            202,
            {"data": {"status": "needs_review", "safety_action": "CRISIS_ROUTE", "normal_generation": False, "content": None}},
            (),
            (),
        )
    if expected == "MUST_DENY":
        return 404, {"code": "resource_not_found"}, (), ()
    if expected == "SHOULD_ABSTAIN":
        content = None
        data = {"status": "abstained", "safety_action": "PROCEED", "normal_generation": False, "content": content}
        rag_events = (
            {
                "trace_id": "MOCK_TRACE",
                "request_summary": {"target_population": "K12学生"},
                "response_summary": {"chunk_ids": [], "document_ids": [], "source_ids": [], "content_hashes": []},
            },
        )
        return 202, {"data": data}, rag_events, ()
    scope = case.get("target_scope", {})
    required = case.get("required_evidence_ids", ())
    cite = next(
        (
            evaluation_id
            for source_id in required
            for evaluation_id in source_to_evaluation_ids.get(str(source_id), ())
            if evaluation_id in allowed_ids
        ),
        allowed_ids[0] if allowed_ids else "",
    )
    if expected == "SHOULD_ANSWER" or expected == "MUST_ANSWER":
        data = {
            "status": "generated",
            "safety_action": "PROCEED",
            "normal_generation": True,
            "report_id": f"REPORT_MOCK_{hashlib.sha256(case_id.encode()).hexdigest()[:8]}",
            "generation": {
                "generation_id": f"GEN_MOCK_{hashlib.sha256(case_id.encode()).hexdigest()[:8]}",
                "status": "generated",
                "provenance": {"generation_status": "EXECUTED", "model_id": "MOCK_ONLY"},
            },
            "content": {
                "summary": "合成模拟回答。",
                "observations": [],
                "suggestions": [{"text": "可以把学习任务拆成几步。", "source_chunk_ids": [cite] if cite else []}],
                "disclaimer": "仅用于 harness 结构测试。",
            },
            "citations": [{"chunk_id": cite, "document_id": "DOC_MOCK"}] if cite else [],
        }
        trace = "MOCK_TRACE"
        rag_events = (
            {
                "trace_id": trace,
                "request_summary": {"target_population": "K12学生"},
                "response_summary": {"chunk_ids": [cite] if cite else [], "document_ids": ["DOC_MOCK"] if cite else [], "source_ids": [], "content_hashes": []},
            },
        )
        llm_events = (
            {
                "trace_id": trace,
                "response_summary": {
                    "model_id": "MOCK_ONLY",
                    "provider_model": "qwen2.5:7b-instruct-q4_K_M",
                    "runtime_version": "MOCK_ONLY",
                    "digest": EXPECTED_RUNTIME_IDENTITY["digest"],
                    "fallback_used": False,
                },
            },
        )
        return 202, {"data": data}, rag_events, llm_events
    return 202, {"data": {"status": "unknown", "normal_generation": False, "content": None}}, (), ()


async def run_mock_validation(packet: ApprovedPacket) -> dict[str, Any]:
    """Exercise all 12 loader/result paths with synthetic data only.

    This function never opens a socket, starts the product, reads Runtime
    identity from the machine, or writes a formal run manifest.
    """

    case_manifest = build_case_manifest(packet)
    corpus_manifest = build_approved_corpus_manifest(packet)
    source_to_evaluation_ids = {
        entry["source_chunk_id"]: entry["evaluation_chunk_ids"]
        for entry in corpus_manifest["evidence_aliases"]
    }
    evaluation_to_source = corpus_projection_source_map(corpus_manifest)
    mock_id = "D4RUN-MOCK-STRUCTURE-ONLY"
    results: list[dict[str, Any]] = []
    for ordinal, case in enumerate(packet.answerability_cases):
        case_id = str(case["case_id"])
        request_id = _stable_correlation("REQ", mock_id, case_id)
        trace_id = _stable_correlation("TRACE", mock_id, case_id)
        status, body, rag_events, llm_events = _mock_response(
            case, source_to_evaluation_ids, corpus_manifest["evidence_ids"]
        )
        # The mock's trace values are structural placeholders; correlate them
        # without suggesting they came from the product.
        rag_events = tuple({**event, "trace_id": trace_id} for event in rag_events)
        llm_events = tuple({**event, "trace_id": trace_id} for event in llm_events)
        result = build_case_result(
            packet=packet,
            case=case,
            run_id=mock_id,
            http_status=status,
            response_body=body,
            request_id=request_id,
            trace_id=trace_id,
            rag_events=rag_events,
            llm_events=llm_events,
            runtime_preflight_identity=EXPECTED_RUNTIME_IDENTITY,
            allowed_evidence_ids=corpus_manifest["evidence_ids"],
            evaluation_to_source_evidence=evaluation_to_source,
            evidence_status=NONFORMAL_EVIDENCE,
        )
        result["retrieval_evidence"]["corpus_identity"] = {
            "corpus_id": corpus_manifest["corpus_id"],
            "corpus_hash": corpus_manifest["corpus_hash"],
            "mock_only": True,
        }
        result.pop("result_hash", None)
        result["result_hash"] = canonical_sha256_tag(result, self_field="result_hash")
        results.append(result)
    summary = aggregate_results(results)
    summary["run_status"] = "HARNESS_STRUCTURE_ONLY"
    summary["evidence_status"] = NONFORMAL_EVIDENCE
    summary["case_manifest_hash"] = case_manifest["manifest_hash"]
    summary["corpus_manifest_hash"] = corpus_manifest["corpus_hash"]
    summary["run_summary_hash"] = canonical_sha256_tag(summary, self_field="run_summary_hash")
    return {
        "run_id": mock_id,
        "results": results,
        "summary": summary,
        "case_manifest": case_manifest,
        "corpus_manifest": corpus_manifest,
        "evidence_status": NONFORMAL_EVIDENCE,
    }
