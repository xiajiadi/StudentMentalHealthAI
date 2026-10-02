"""One-shot D4-3B runner for the canonical Backend support HTTP route."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx
import jsonschema

try:
    from harness.foundation.hashing import canonical_json, canonical_sha256_tag
except ModuleNotFoundError:  # pragma: no cover - package-relative import mode
    from ..foundation.hashing import canonical_json, canonical_sha256_tag

from .approved_packet import ApprovedPacket, ApprovedPacketError, load_approved_packet
from .credential_provider import EXPECTED_SYNTHETIC_SUBJECTS
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
    git_snapshot,
    is_loopback_url,
    verify_case_manifest,
    verify_corpus_manifest,
    write_json_once,
    verify_formal_manifest,
)
from .results import (
    FORMAL_EVIDENCE,
    NONFORMAL_EVIDENCE,
    aggregate_results,
    build_case_result,
    classify_p0_p1,
)
from .runtime_audit import (
    RUNTIME_AUDIT_SCHEMA,
    capture_runtime_audit_snapshot,
    runtime_audit_after_invocation_issues,
    runtime_audit_pre_case_issues,
    validate_runtime_audit_snapshot,
    write_runtime_audit_snapshot,
)
from .summary_hash import canonical_summary_hash
from .network_integrity import LoopbackNetworkMonitor

EXPECTED_RUNTIME_HTTP_ENDPOINT = "http://127.0.0.1:8160"
# Logical key published by the immutable R1 Runtime profile; provider identity
# is independently checked against EXPECTED_RUNTIME_IDENTITY below.
EXPECTED_RUNTIME_LOGICAL_MODEL_ID = "qwen2.5-7b-instruct-gpu-acceptance"
SYNTHETIC_CAT_INSTRUMENT_ID = "instrument_demo_cat_v0_1"
SYNTHETIC_CAT_INSTRUMENT_VERSION = "demo.v1"


CORRELATION_SAFE = re.compile(r"^D4RUN-[A-Za-z0-9][A-Za-z0-9._-]*$")
_CASE_ID_SAFE = re.compile(r"^AW-[A-Z0-9][A-Z0-9_-]*$")
_ERROR_AUDIT_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "spec" / "d4_slice3b_error_audit.schema.json"


class RunnerError(RuntimeError):
    """A fail-closed runner preflight or one-shot execution error."""


class PostPrepareIntegrityError(RunnerError):
    """The authoritative post-prepare integrity gate did not pass."""

    def __init__(self, violation_codes: Sequence[str], *, error_type: str | None = None) -> None:
        codes = {code for code in violation_codes if isinstance(code, str) and code}
        self.violation_codes = tuple(sorted(codes or {"POST_PREPARE_INTEGRITY_NOT_PASS"}))
        self.error_type = error_type
        super().__init__("post-prepare integrity gate did not pass")


@dataclass(frozen=True, slots=True)
class TransportObservation:
    http_status: int
    response_body: Mapping[str, Any]
    rag_events: tuple[Mapping[str, Any], ...] = ()
    llm_events: tuple[Mapping[str, Any], ...] = ()
    external_network_detected: bool = False
    integrity_observation: Mapping[str, Any] = field(default_factory=dict)


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

    async def check_execution_integrity(self, baseline: Mapping[str, Any]) -> Mapping[str, Any]: ...

    async def close(self) -> None: ...


def assert_post_prepare_integrity_state(state: Any) -> Mapping[str, Any]:
    """Require the canonical integrity result and its captured network state to pass."""

    codes: set[str] = set()
    if not isinstance(state, Mapping):
        raise PostPrepareIntegrityError(("POST_PREPARE_INTEGRITY_STATE_UNAVAILABLE",))

    violations = state.get("violations")
    if not isinstance(violations, Sequence) or isinstance(violations, (str, bytes)):
        codes.add("POST_PREPARE_INTEGRITY_VIOLATIONS_UNAVAILABLE")
    else:
        for violation in violations:
            code = violation.get("code") if isinstance(violation, Mapping) else violation
            if isinstance(code, str) and code.isascii() and code.replace("_", "").isalnum():
                codes.add(code)
            elif violation:
                codes.add("POST_PREPARE_INTEGRITY_VIOLATION")

    if state.get("status") != "PASS":
        if not codes:
            codes.add("POST_PREPARE_INTEGRITY_NOT_PASS")

    network = state.get("network_observation")
    if not isinstance(network, Mapping):
        codes.add("POST_PREPARE_NETWORK_OBSERVATION_UNAVAILABLE")
    else:
        if network.get("status") != "PASS":
            codes.add("POST_PREPARE_NETWORK_INTEGRITY_NOT_PASS")
        issues = network.get("issues")
        if not isinstance(issues, Sequence) or isinstance(issues, (str, bytes)):
            codes.add("POST_PREPARE_NETWORK_ISSUES_UNAVAILABLE")
        else:
            for issue in issues:
                code = issue.get("code") if isinstance(issue, Mapping) else issue
                if isinstance(code, str) and code.isascii() and code.replace("_", "").isalnum():
                    codes.add(code)
                elif issue:
                    codes.add("POST_PREPARE_NETWORK_INTEGRITY_ISSUE")

    if codes:
        raise PostPrepareIntegrityError(tuple(codes))
    return state


async def assert_post_prepare_integrity(
    transport: ProductTransport,
    baseline: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Run the same authoritative integrity comparison for smoke and formal paths."""

    try:
        state = await transport.check_execution_integrity(baseline)
    except Exception as exc:
        raise PostPrepareIntegrityError(
            ("POST_PREPARE_INTEGRITY_CHECK_FAILED",),
            error_type=type(exc).__name__,
        ) from None
    return assert_post_prepare_integrity_state(state)


def classify_execution_integrity(
    *,
    observation: TransportObservation | None = None,
    result: Mapping[str, Any] | None = None,
    input_issues: Sequence[str] = (),
    postflight: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify whether formal execution evidence remains trustworthy.

    Product P0/P1 counts are intentionally not inspected here. They describe
    observed behavior; only explicit integrity evidence can stop the case loop.
    """

    violations = [str(issue) for issue in input_issues]
    if observation is not None:
        if observation.external_network_detected:
            violations.append("EXTERNAL_NETWORK_EGRESS")
        network = observation.integrity_observation
        for issue in network.get("issues", ()) if isinstance(network, Mapping) else ():
            if isinstance(issue, Mapping):
                code = issue.get("code")
                if isinstance(code, str):
                    violations.append(code)
            elif isinstance(issue, str):
                violations.append(issue)

    if isinstance(postflight, Mapping):
        for issue in postflight.get("violations", ()):
            if isinstance(issue, Mapping):
                code = issue.get("code")
                if isinstance(code, str):
                    violations.append(code)
            elif isinstance(issue, str):
                violations.append(issue)
        if postflight.get("status") == "FAIL" and not postflight.get("violations"):
            violations.append("POST_CASE_INTEGRITY_CHECK_FAILED")

    if isinstance(result, Mapping):
        runtime_requirement = runtime_observer_requirement(
            result,
            response_body=observation.response_body if observation is not None else None,
        )
        if runtime_requirement == "INCONSISTENT":
            violations.append("GENERATION_OBSERVER_EVIDENCE_INCONSISTENCY")

        governance = result.get("governance")
        governance = governance if isinstance(governance, Mapping) else {}
        for field_name, reason in (
            ("external_network_detected", "EXTERNAL_NETWORK_EGRESS"),
            ("cloud_fallback", "RUNTIME_FALLBACK"),
            ("product_source_changed", "PRODUCT_SOURCE_CHANGED"),
            ("human_gold_changed", "HUMAN_GOLD_CHANGED"),
            ("contract_changed", "FROZEN_CONTRACT_CHANGED"),
            ("real_student_data", "REAL_STUDENT_DATA_DETECTED"),
        ):
            if governance.get(field_name) is True:
                violations.append(reason)

        fallback = result.get("fallback")
        if isinstance(fallback, Mapping) and fallback.get("used") is True:
            violations.append("RUNTIME_FALLBACK")
        runtime = result.get("runtime_identity")
        if isinstance(runtime, Mapping):
            if runtime.get("identity_mismatch") is True:
                violations.append("RUNTIME_IDENTITY_DRIFT")
            observations = runtime.get("per_generation_observed")
            if isinstance(observations, Sequence) and not isinstance(observations, (str, bytes)):
                for identity in observations:
                    if not isinstance(identity, Mapping):
                        violations.append("RUNTIME_OBSERVER_EVIDENCE_INVALID")
                        continue
                    if (
                        identity.get("digest") != EXPECTED_RUNTIME_IDENTITY["digest"]
                        or (identity.get("provider_model") or identity.get("model_id"))
                        != EXPECTED_RUNTIME_IDENTITY["model"]
                    ):
                        violations.append("RUNTIME_IDENTITY_DRIFT")
                    for field_name, expected_name in (
                        ("context_length", "num_ctx"),
                        ("output_budget", "output_budget"),
                        ("kv_cache_type", "kv_cache_type"),
                        ("num_parallel", "num_parallel"),
                        ("max_loaded_models", "max_loaded_models"),
                    ):
                        observed_value = identity.get(field_name)
                        expected_value = EXPECTED_RUNTIME_IDENTITY.get(expected_name)
                        if observed_value is not None and observed_value != expected_value:
                            violations.append("RUNTIME_IDENTITY_DRIFT")

        if runtime_requirement == "REQUIRED":
            observed = (
                runtime.get("per_generation_observed")
                if isinstance(runtime, Mapping)
                else None
            )
            if not isinstance(observed, Sequence) or isinstance(observed, (str, bytes)) or not observed:
                violations.append("RUNTIME_OBSERVER_EVIDENCE_MISSING")
            if not isinstance(fallback, Mapping) or not isinstance(fallback.get("used"), bool):
                violations.append("RUNTIME_FALLBACK_EVIDENCE_MISSING")

    unique = list(dict.fromkeys(violations))
    return {
        "status": "FAIL" if unique else "PASS",
        "abort_reason": unique[0] if unique else None,
        "violations": unique,
    }


def runtime_observer_requirement(
    result: Mapping[str, Any],
    *,
    response_body: Mapping[str, Any] | None = None,
) -> Literal["REQUIRED", "NOT_REQUIRED", "INCONSISTENT"]:
    """Decide observer need from execution state and observer evidence, never IDs.

    The normalized case result preserves the selected status; the source
    response is also inspected so conflicting explicit generation fields are
    not hidden by that projection.
    """

    actual = result.get("actual")
    actual = actual if isinstance(actual, Mapping) else {}
    runtime = result.get("runtime_identity")
    runtime = runtime if isinstance(runtime, Mapping) else {}
    observed = runtime.get("per_generation_observed")
    has_observer_event = (
        isinstance(observed, Sequence)
        and not isinstance(observed, (str, bytes))
        and bool(observed)
    )

    data: Mapping[str, Any] = {}
    if isinstance(response_body, Mapping):
        value = response_body.get("data")
        data = value if isinstance(value, Mapping) else response_body
    generation = data.get("generation")
    generation = generation if isinstance(generation, Mapping) else {}
    provenance = generation.get("provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}

    status_values = (
        actual.get("generation_status"),
        data.get("generation_status"),
        generation.get("status"),
        provenance.get("generation_status"),
        data.get("status"),
    )
    statuses = {
        value.strip().upper()
        for value in status_values
        if isinstance(value, str) and value.strip()
    }
    explicitly_not_run = "NOT_RUN" in statuses
    explicitly_executed = bool(
        statuses
        & {"EXECUTED", "GENERATING", "GENERATED", "APPROVED"}
    )

    normal_generation_values = {
        value
        for value in (actual.get("normal_generation"), data.get("normal_generation"))
        if isinstance(value, bool)
    }
    if len(normal_generation_values) > 1:
        return "INCONSISTENT"
    normal_generation = next(iter(normal_generation_values), None)
    response_class = actual.get("response_class")
    safety_route = actual.get("safety_route")

    if explicitly_not_run and (
        explicitly_executed
        or normal_generation is True
        or has_observer_event
        or response_class == "ANSWERED"
    ):
        return "INCONSISTENT"
    if explicitly_not_run:
        # NOT_RUN without the paired negative execution flag is incomplete
        # evidence, so retain the observer requirement and fail closed.
        return "NOT_REQUIRED" if normal_generation is False else "REQUIRED"
    if explicitly_executed or normal_generation is True or has_observer_event:
        return "REQUIRED"

    # These outcomes explicitly bypass ordinary Runtime generation in the
    # current product flow. Unknown states remain fail-closed below.
    if normal_generation is False and (
        response_class in {"ABSTAINED", "DENIED"}
        or (response_class == "ROUTED" and safety_route == "CRISIS_ROUTE")
    ):
        return "NOT_REQUIRED"
    # A response that contains no generation execution state does not prove
    # Runtime was invoked. Do not turn absent metadata (or a correlation ID)
    # into a positive invocation claim. Unknown explicit states remain closed.
    return "REQUIRED" if statuses else "NOT_REQUIRED"


def runtime_invocation_evidence_sources(
    *,
    response_body: Mapping[str, Any] | None,
    llm_events: Sequence[Mapping[str, Any]],
    trace_id: str,
) -> tuple[str, ...]:
    """Return only positive, trace-correlated evidence that a model call occurred."""

    sources: list[str] = []
    data: Mapping[str, Any] = {}
    if isinstance(response_body, Mapping):
        value = response_body.get("data")
        data = value if isinstance(value, Mapping) else response_body
    generation = data.get("generation")
    generation = generation if isinstance(generation, Mapping) else {}
    provenance = generation.get("provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}

    if data.get("normal_generation") is True:
        sources.append("NORMAL_GENERATION_TRUE")

    positive_statuses = {"EXECUTED", "GENERATING", "GENERATED", "APPROVED"}
    status_values = (
        data.get("generation_status"),
        generation.get("status"),
        provenance.get("generation_status"),
        data.get("status"),
    )
    if any(isinstance(value, str) and value.strip().upper() in positive_statuses for value in status_values):
        sources.append("POSITIVE_GENERATION_STATUS")

    if any(isinstance(event, Mapping) and event.get("trace_id") == trace_id for event in llm_events):
        sources.append("CORRELATED_LLM_OBSERVER_EVENT")
    return tuple(sources)


def _runtime_invocation_observed_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


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
        passwords: Mapping[str, str],
        cat_instrument_id: str = SYNTHETIC_CAT_INSTRUMENT_ID,
        cat_instrument_version: str = SYNTHETIC_CAT_INSTRUMENT_VERSION,
        timeout_seconds: float = 150.0,
        network_monitor: LoopbackNetworkMonitor | None = None,
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
        if set(passwords) != set(EXPECTED_SYNTHETIC_SUBJECTS) or not all(passwords.values()):
            raise RunnerError("frozen synthetic login credentials are incomplete")
        if not cat_instrument_id or not cat_instrument_version:
            raise RunnerError("fixed synthetic CAT instrument identity is incomplete")
        self.passwords = dict(passwords)
        self.cat_instrument_id = cat_instrument_id
        self.cat_instrument_version = cat_instrument_version
        self.timeout_seconds = timeout_seconds
        self.network_monitor = network_monitor or LoopbackNetworkMonitor()
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._csrf: dict[str, str] = {}
        self._subjects: dict[str, str] = {}
        self._foreign_assessment_id: str | None = None
        self._login_gate_passed = False
        self._login_gate_result: dict[str, dict[str, str]] | None = None
        self._prepared = False

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
        try:
            network_observation = self.network_monitor.start()
        except Exception as exc:
            network_observation = {
                "status": "FAIL",
                "listeners": [],
                "external_established_connections": [],
                "issues": [{"code": "NETWORK_OBSERVER_FAILURE", "error_type": type(exc).__name__}],
            }
        backend = httpx.AsyncClient(
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

        for issue in network_observation.get("issues", ()):
            if isinstance(issue, Mapping):
                code = issue.get("code")
                if isinstance(code, str):
                    unexpected_configuration.append(f"network_integrity.{code}")

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
                if upstream.rstrip("/") != EXPECTED_RUNTIME_HTTP_ENDPOINT:
                    raise RunnerError("LLM observer is not bound to the exact Runtime service endpoint")
                models = service_identity.get("models")
                expected_model = (
                    models.get(EXPECTED_RUNTIME_LOGICAL_MODEL_ID)
                    if isinstance(models, Mapping)
                    else None
                )
                if (
                    not isinstance(expected_model, Mapping)
                    or expected_model.get("provider_model_id")
                    != EXPECTED_RUNTIME_IDENTITY["model"]
                ):
                    raise RunnerError("live Runtime model identity does not match the frozen model")
                runtime_endpoint_identity = dict(service_identity)
        return {
            "backend": {"status": "READY", "url": self.backend_base_url},
            "observers": observer_status,
            "rag_service_identity": rag_service_identity,
            "runtime_endpoint_health_identity": runtime_endpoint_identity,
            "backend_dependency_identity": dependency_identity,
            "unexpected_configuration": unexpected_configuration,
            "network_observation": network_observation,
            "network_policy": "LOOPBACK_ONLY",
            "trust_env": False,
            "retry_policy": {"max_retries": 0, "non_idempotent_post_retries": 0},
        }

    async def prepare(self) -> None:
        if self._prepared:
            return
        await self.login_gate()
        self._foreign_assessment_id = await self._create_assessment("student_b", "D4B_FOREIGN")
        self._prepared = True

    async def login_gate(self) -> Mapping[str, Mapping[str, str]]:
        """Authenticate only the frozen synthetic identities, exactly once."""

        if self._login_gate_passed:
            assert self._login_gate_result is not None
            return self._login_gate_result
        result: dict[str, dict[str, str]] = {}
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
            expected_subject_id = EXPECTED_SYNTHETIC_SUBJECTS[username]
            if not isinstance(csrf, str) or not csrf or subject_id != expected_subject_id:
                raise RunnerError("synthetic fixture login returned an unexpected subject identity")
            self._csrf[username] = csrf
            self._subjects[username] = subject_id
            result[username] = {"status": "PASS", "subject_id": expected_subject_id}
        self._login_gate_result = result
        self._login_gate_passed = True
        return result

    async def _create_assessment(self, username: str, nonce: str) -> str:
        client = await self._client(username)
        headers = {"X-CSRF-Token": self._csrf[username]}
        response = await client.post(
            "/api/v1/assessments",
            headers=headers,
            json={
                "subject_id": self._subjects[username],
                "instrument_id": self.cat_instrument_id,
                "instrument_version": self.cat_instrument_version,
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
        state_response = await client.get(
            f"/api/v1/assessments/{assessment_id}/state",
            headers=headers,
        )
        if state_response.status_code != 200:
            raise RunnerError("synthetic assessment state bootstrap failed")
        state = _api_data(state_response.json())
        maximum = state.get("max_items")
        step_limit = maximum if isinstance(maximum, int) and 1 <= maximum <= 64 else 12
        answered = state.get("answered_count", 0)
        if not isinstance(answered, int) or answered < 0:
            raise RunnerError("synthetic assessment answer state is invalid")
        for _ in range(step_limit):
            if state.get("can_complete") is True:
                break
            item_id = state.get("selected_item_id")
            current_item = state.get("current_item")
            if (
                not isinstance(item_id, str)
                or not item_id.startswith("ITEM_")
                or not isinstance(current_item, Mapping)
                or current_item.get("item_id") != item_id
            ):
                raise RunnerError("synthetic CAT did not expose the selected fixture item")
            options = current_item.get("options")
            response_value = next(
                (
                    option.get("value")
                    for option in options
                    if isinstance(option, Mapping)
                    and isinstance(option.get("value"), (str, int, float, bool))
                ),
                None,
            ) if isinstance(options, list) else None
            if response_value is None:
                raise RunnerError("synthetic CAT item exposed no fixture response option")
            response = await client.post(
                f"/api/v1/assessments/{assessment_id}/responses",
                headers=headers,
                json={"item_id": item_id, "response": response_value},
            )
            if response.status_code != 200:
                raise RunnerError("synthetic assessment response bootstrap failed")
            next_state = _api_data(response.json())
            next_answered = next_state.get("answered_count")
            if not isinstance(next_answered, int) or next_answered <= answered:
                raise RunnerError("synthetic CAT did not advance after its fixture response")
            state = next_state
            answered = next_answered
        if state.get("can_complete") is not True:
            raise RunnerError("synthetic CAT fixture did not reach its completion boundary")
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
        try:
            network_observation = self.network_monitor.sample()
        except Exception as exc:
            network_observation = {
                "status": "FAIL",
                "issues": [{"code": "NETWORK_OBSERVER_FAILURE", "error_type": type(exc).__name__}],
            }
        network_issues = network_observation.get("issues", ())
        external_network_detected = any(
            isinstance(issue, Mapping)
            and issue.get("code") == "EXTERNAL_ESTABLISHED_CONNECTION"
            for issue in network_issues
        )
        return TransportObservation(
            http_status=response.status_code,
            response_body=body,
            rag_events=_load_jsonl(self.rag_observer_events, trace_id=trace_id),
            llm_events=_load_jsonl(self.llm_observer_events, trace_id=trace_id),
            external_network_detected=external_network_detected,
            integrity_observation=network_observation,
        )

    async def check_execution_integrity(self, baseline: Mapping[str, Any]) -> Mapping[str, Any]:
        violations: list[dict[str, Any]] = []
        try:
            current = await self.preflight()
        except Exception as exc:
            return {
                "status": "FAIL",
                "violations": [{"code": "DATA_PLANE_UNAVAILABLE", "error_type": type(exc).__name__}],
                "network_observation": {
                    "status": "FAIL",
                    "issues": [{"code": "DATA_PLANE_UNAVAILABLE", "error_type": type(exc).__name__}],
                },
            }

        current_network = current.get("network_observation")
        current_network = current_network if isinstance(current_network, Mapping) else {}
        if current_network.get("status") == "FAIL":
            issues = current_network.get("issues", ())
            if issues:
                violations.extend(issue for issue in issues if isinstance(issue, Mapping))
            else:
                violations.append({"code": "NETWORK_INTEGRITY_UNVERIFIED"})
        for item in current.get("unexpected_configuration", ()):
            violations.append({"code": "UNEXPECTED_CONFIGURATION", "detail": str(item)})

        baseline_rag = baseline.get("rag_service_identity")
        current_rag = current.get("rag_service_identity")
        rag_fields = (
            "index_id", "index_manifest_hash", "corpus_manifest_hash", "source_packet_id",
            "source_packet_hash", "input_manifest_hash", "config_hash", "eligible_chunk_ids",
        )
        if isinstance(baseline_rag, Mapping) and isinstance(current_rag, Mapping):
            if any(baseline_rag.get(key) != current_rag.get(key) for key in rag_fields if key in baseline_rag):
                violations.append({"code": "RAG_CORPUS_OR_INDEX_IDENTITY_DRIFT"})
        else:
            violations.append({"code": "RAG_IDENTITY_UNAVAILABLE"})

        baseline_runtime = baseline.get("runtime_endpoint_health_identity")
        current_runtime = current.get("runtime_endpoint_health_identity")
        if isinstance(baseline_runtime, Mapping) and isinstance(current_runtime, Mapping):
            def stable_runtime(value: Mapping[str, Any]) -> dict[str, Any]:
                models = value.get("models")
                stable_models = {}
                if isinstance(models, Mapping):
                    for logical_id, model in models.items():
                        if isinstance(model, Mapping):
                            stable_models[str(logical_id)] = {
                                key: child for key, child in model.items() if key != "loaded"
                            }
                return {
                    "state": value.get("state"),
                    "readiness": value.get("readiness"),
                    "runtime_version": value.get("runtime_version"),
                    "cloud_fallback": value.get("cloud_fallback"),
                    "provider_ids": value.get("provider_ids"),
                    "models": stable_models,
                }

            if stable_runtime(baseline_runtime) != stable_runtime(current_runtime):
                violations.append({"code": "RUNTIME_IDENTITY_DRIFT"})
        else:
            violations.append({"code": "RUNTIME_IDENTITY_UNAVAILABLE"})

        if current.get("backend_dependency_identity") != baseline.get("backend_dependency_identity"):
            violations.append({"code": "BACKEND_DEPENDENCY_IDENTITY_DRIFT"})
        baseline_network = baseline.get("network_observation")
        baseline_network = baseline_network if isinstance(baseline_network, Mapping) else {}
        def listener_identity(value: Mapping[str, Any]) -> list[tuple[Any, Any, Any]]:
            listeners = value.get("listeners", ())
            if not isinstance(listeners, Sequence) or isinstance(listeners, (str, bytes)):
                return []
            return sorted(
                (item.get("address"), item.get("port"), item.get("pid"))
                for item in listeners if isinstance(item, Mapping)
            )
        if listener_identity(baseline_network) != listener_identity(current_network):
            violations.append({"code": "DATA_PLANE_LISTENER_IDENTITY_CHANGED"})

        return {
            "status": "FAIL" if violations else "PASS",
            "violations": violations,
            "network_observation": dict(current_network),
        }

    async def close(self) -> None:
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()
        self.network_monitor.close()


def _write_case_result(run_dir: Path, result: Mapping[str, Any]) -> Path:
    case_id = str(result.get("case_id", ""))
    if not _CASE_ID_SAFE.fullmatch(case_id):
        raise RunnerError("result case ID cannot be used as a file name")
    path = run_dir / "cases" / f"{case_id}.json"
    return write_json_once(path, result)


def _write_error_audit_record(
    run_dir: Path,
    result: Mapping[str, Any],
    *,
    create: bool,
) -> bool:
    evidence = result.get("normalized_error_evidence")
    if not isinstance(evidence, Mapping):
        return False
    actual = result.get("actual")
    actual = actual if isinstance(actual, Mapping) else {}
    record = {
        "schema_version": "d4-slice3b-error-audit.v1",
        "run_id": result.get("run_id"),
        "case_id": result.get("case_id"),
        "http_status": actual.get("http_status"),
        "request_id": actual.get("request_id"),
        "trace_id": actual.get("trace_id"),
        "normalized_error_evidence": dict(evidence),
    }
    _validate_error_audit_record(record)
    encoded = (
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")
    path = run_dir / "error-audit.jsonl"
    mode = "xb" if create else "ab"
    with path.open(mode) as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    return True


def _error_audit_artifact_ref(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "error-audit.jsonl"
    if not path.is_file():
        return {
            "status": "NO_NON_2XX",
            "path": None,
            "line_count": 0,
            "sha256": None,
        }
    payload = path.read_bytes()
    lines = payload.splitlines()
    if not payload.endswith(b"\n") or not lines:
        raise RunnerError("error audit JSONL is incomplete")
    for line in lines:
        value = json.loads(line)
        if not isinstance(value, Mapping) or value.get("run_id") != run_dir.name:
            raise RunnerError("error audit JSONL is not bound to the formal run")
        _validate_error_audit_record(value)
    return {
        "status": "PRESENT",
        "path": path.name,
        "line_count": len(lines),
        "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
    }


def _validate_error_audit_record(record: Mapping[str, Any]) -> None:
    schema = json.loads(_ERROR_AUDIT_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
    )
    validator.validate(dict(record))


def _sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _frozen_input_issues(
    *,
    packet: ApprovedPacket,
    case_manifest: Mapping[str, Any],
    corpus_manifest: Mapping[str, Any],
    repo_root: str | Path,
    baseline_git_snapshot: Mapping[str, Any],
    case_manifest_path: str | Path | None,
    corpus_manifest_path: str | Path | None,
    baseline_case_file_hash: str | None,
    baseline_corpus_file_hash: str | None,
) -> list[str]:
    issues: list[str] = []
    try:
        packet.verify_unchanged()
        verify_case_manifest(case_manifest, packet=packet)
        verify_corpus_manifest(corpus_manifest, packet=packet)
    except Exception as exc:
        issues.append(f"FROZEN_INPUT_VERIFICATION_FAILED:{type(exc).__name__}")
    for path, expected, changed, unreadable in (
        (case_manifest_path, baseline_case_file_hash, "CASE_MANIFEST_FILE_CHANGED", "CASE_MANIFEST_FILE_UNREADABLE"),
        (corpus_manifest_path, baseline_corpus_file_hash, "APPROVED_CORPUS_MANIFEST_FILE_CHANGED", "APPROVED_CORPUS_MANIFEST_FILE_UNREADABLE"),
    ):
        if path is None:
            continue
        try:
            if _sha256_file(path) != expected:
                issues.append(changed)
        except OSError:
            issues.append(unreadable)
    try:
        if git_snapshot(repo_root) != baseline_git_snapshot:
            issues.append("CHECKOUT_OR_EVALUATION_SOURCE_CHANGED")
    except Exception as exc:
        issues.append(f"CHECKOUT_INTEGRITY_UNAVAILABLE:{type(exc).__name__}")
    return issues


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
    case_manifest_path: str | Path | None = None,
    corpus_manifest_path: str | Path | None = None,
    managed_service_identity: Mapping[str, Any] | None = None,
    timestamp: Any = None,
    run_id: str | None = None,
    entropy: str | bytes | None = None,
    unexpected_configuration: Sequence[str] = (),
    runtime_audit_capture: Callable[..., Mapping[str, Any]] | None = None,
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
    if all_unexpected_configuration:
        stop = {
            "schema_version": "d4-slice3b-preflight-stop.v1",
            "status": "CONTROLLER_DECISION_REQUIRED",
            "reason": "unexpected non-secret configuration failed the premanifest gate",
            "unexpected_configuration": list(all_unexpected_configuration),
            "formal_manifest_created": False,
            "product_requests": 0,
            "runtime_calls": 0,
            "model_calls": 0,
            "formal_case_count": 0,
            "expected_case_count": len(packet.answerability_cases),
            "execution_integrity_status": "FAIL",
            "execution_abort_reason": "PREMANIFEST_CONFIGURATION_OR_INTEGRITY_FAILURE",
        }
        stop_path = write_json_once(Path(output_root) / "preflight-stop.json", stop)
        await transport.close()
        return {
            "run_id": None,
            "manifest_path": None,
            "preflight_stop_path": str(stop_path),
            "manifest_hash": None,
            "results": [],
            "summary": stop,
            "abort": stop,
            "evidence_status": FORMAL_EVIDENCE,
        }

    # Complete every setup call before freezing the immutable formal manifest.
    # login_gate() is cached, so this does not send a second login request.
    await transport.prepare()
    try:
        await assert_post_prepare_integrity(transport, preflight_observation)
    except PostPrepareIntegrityError as exc:
        stop = {
            "schema_version": "d4-slice3b-preflight-stop.v1",
            "status": "CONTROLLER_DECISION_REQUIRED",
            "reason": "post-prepare integrity gate did not pass",
            "reason_code": "PREMANIFEST_POST_PREPARE_INTEGRITY_FAILURE",
            "prepare_completed": True,
            "integrity_status": "FAIL",
            "integrity_violation_codes": list(exc.violation_codes),
            "integrity_error_type": exc.error_type,
            "formal_manifest_created": False,
            "formal_manifest_count": 0,
            "formal_support_post_count": 0,
            "support_post_count": 0,
            "formal_case_count": 0,
            "formal_case_retries": 0,
            "retry_count": 0,
            "execution_integrity_status": "FAIL",
            "execution_abort_reason": "PREMANIFEST_POST_PREPARE_INTEGRITY_FAILURE",
            "expected_case_count": len(packet.answerability_cases),
        }
        stop_path = write_json_once(Path(output_root) / "preflight-stop.json", stop)
        await transport.close()
        return {
            "run_id": None,
            "manifest_path": None,
            "preflight_stop_path": str(stop_path),
            "manifest_hash": None,
            "results": [],
            "summary": stop,
            "abort": stop,
            "evidence_status": FORMAL_EVIDENCE,
        }

    baseline_git_snapshot = git_snapshot(repo_root)
    baseline_case_file_hash = _sha256_file(case_manifest_path) if case_manifest_path else None
    baseline_corpus_file_hash = _sha256_file(corpus_manifest_path) if corpus_manifest_path else None

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
    audit_capture = runtime_audit_capture or capture_runtime_audit_snapshot
    before_snapshot: Mapping[str, Any] | None = None
    before_issues: tuple[str, ...] = ()
    before_error_type: str | None = None
    try:
        captured = await asyncio.to_thread(
            audit_capture,
            run_id=actual_run_id,
            phase="BEFORE_CASES",
            runtime_preflight=runtime_preflight,
            managed_service_identity=managed_service_identity or {},
            evidence_root=output_root,
        )
        if not isinstance(captured, Mapping):
            raise RunnerError("Runtime audit capture returned a non-object")
        before_snapshot = dict(captured)
        validate_runtime_audit_snapshot(before_snapshot)
        before_issues = runtime_audit_pre_case_issues(before_snapshot, run_id=actual_run_id)
        if before_snapshot.get("runtime_preflight_hash") != runtime_preflight.preflight_hash:
            before_issues = (*before_issues, "RUNTIME_AUDIT_PREFLIGHT_HASH_MISMATCH")
    except Exception as exc:
        before_error_type = type(exc).__name__
        before_issues = ("RUNTIME_AUDIT_CAPTURE_FAILED",)

    if before_issues:
        stop_root = Path(output_root) / "preflight-stops" / actual_run_id
        audit_path: Path | None = None
        audit_hash: str | None = None
        artifact_error_type: str | None = None
        if before_snapshot is not None:
            try:
                audit_path, audit_hash = write_runtime_audit_snapshot(
                    stop_root / "runtime-audit-before-cases.json", before_snapshot
                )
            except Exception as exc:
                artifact_error_type = type(exc).__name__
        stop = {
            "schema_version": "d4-slice3b-preflight-stop.v1",
            "status": "CONTROLLER_DECISION_REQUIRED",
            "reason": "run-bound Runtime audit evidence did not pass before formal requests",
            "reason_code": "PREMANIFEST_RUNTIME_AUDIT_FAILURE",
            "attempted_run_id": actual_run_id,
            "runtime_audit_schema_version": RUNTIME_AUDIT_SCHEMA,
            "runtime_audit_issues": list(before_issues),
            "runtime_audit_error_type": before_error_type,
            "runtime_audit_artifact_error_type": artifact_error_type,
            "runtime_audit_artifact_path": (
                audit_path.relative_to(Path(output_root)).as_posix() if audit_path else None
            ),
            "runtime_audit_artifact_sha256": audit_hash,
            "formal_manifest_created": False,
            "formal_product_requests": 0,
            "runtime_inference_calls": 0,
            "model_calls": 0,
            "formal_case_count": 0,
            "expected_case_count": len(packet.answerability_cases),
            "execution_integrity_status": "FAIL",
            "execution_abort_reason": "PREMANIFEST_RUNTIME_AUDIT_FAILURE",
        }
        stop_path = write_json_once(stop_root / "preflight-stop.json", stop)
        await transport.close()
        return {
            "run_id": None,
            "attempted_run_id": actual_run_id,
            "manifest_path": None,
            "preflight_stop_path": str(stop_path),
            "manifest_hash": None,
            "results": [],
            "summary": stop,
            "abort": stop,
            "evidence_status": FORMAL_EVIDENCE,
        }

    assert before_snapshot is not None
    before_path, before_hash = write_runtime_audit_snapshot(
        run_dir / "runtime-audit-before-cases.json", before_snapshot
    )
    before_ref = {
        "run_id": actual_run_id,
        "phase": "BEFORE_CASES",
        "path": before_path.name,
        "captured_at": before_snapshot.get("captured_at"),
        "sha256": before_hash,
    }
    manifest["runtime_audit_evidence"] = {"before_cases": before_ref}
    manifest["manifest_hash"] = canonical_sha256_tag(manifest, self_field="manifest_hash")
    verify_formal_manifest(manifest, packet=packet, case_manifest=case_manifest)
    manifest_path = write_json_once(run_dir / "manifest.json", manifest)
    results: list[dict[str, Any]] = []
    abort: dict[str, Any] | None = None
    error_audit_created = False
    first_invocation_seen = False
    first_invocation_ref: dict[str, Any] | None = None
    first_invocation_capture_status = "NOT_REQUIRED"
    first_invocation_error_type: str | None = None
    try:
        for ordinal, case in enumerate(packet.answerability_cases):
            if abort is not None:
                break
            case_id = str(case["case_id"])
            request_id = _stable_correlation("REQ", actual_run_id, case_id)
            trace_id = _stable_correlation("TRACE", actual_run_id, case_id)
            input_issues = _frozen_input_issues(
                packet=packet,
                case_manifest=case_manifest,
                corpus_manifest=corpus_manifest,
                repo_root=repo_root,
                baseline_git_snapshot=baseline_git_snapshot,
                case_manifest_path=case_manifest_path,
                corpus_manifest_path=corpus_manifest_path,
                baseline_case_file_hash=baseline_case_file_hash,
                baseline_corpus_file_hash=baseline_corpus_file_hash,
            )
            if input_issues:
                integrity = classify_execution_integrity(input_issues=input_issues)
                abort = {
                    "case_id": case_id,
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "retry_performed": False,
                    "request_sent": False,
                    "reason_code": integrity["abort_reason"],
                    "integrity_violations": integrity["violations"],
                    "disposition": "STOPPED_FOR_EXECUTION_INTEGRITY",
                }
                break
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
                    "request_sent": "UNKNOWN",
                    "reason_code": "REQUEST_OUTCOME_UNCERTAIN",
                    "disposition": "STOPPED_WITH_REQUEST_OUTCOME_UNCERTAIN",
                }
                break
            case_runtime_audit: dict[str, Any] | None = None
            case_invocation_issues: tuple[str, ...] = ()
            if not first_invocation_seen:
                evidence_sources = runtime_invocation_evidence_sources(
                    response_body=observation.response_body,
                    llm_events=observation.llm_events,
                    trace_id=trace_id,
                )
                if evidence_sources:
                    first_invocation_seen = True
                    invocation_binding = {
                        "case_id": case_id,
                        "request_id": request_id,
                        "trace_id": trace_id,
                        "evidence_sources": list(evidence_sources),
                        "observed_at": _runtime_invocation_observed_at(),
                    }
                    invocation_snapshot: Mapping[str, Any] | None = None
                    invocation_artifact_ref: dict[str, Any] | None = None
                    invocation_error_type: str | None = None
                    invocation_issue_list: list[str] = []
                    try:
                        captured_invocation = await asyncio.to_thread(
                            audit_capture,
                            run_id=actual_run_id,
                            phase="AFTER_INVOCATION",
                            runtime_preflight=runtime_preflight,
                            managed_service_identity=managed_service_identity or {},
                            evidence_root=output_root,
                            invocation_binding=invocation_binding,
                        )
                        if not isinstance(captured_invocation, Mapping):
                            raise RunnerError("Runtime invocation audit returned a non-object")
                        invocation_snapshot = dict(captured_invocation)
                        try:
                            validate_runtime_audit_snapshot(invocation_snapshot)
                        except Exception as exc:
                            invocation_error_type = type(exc).__name__
                            invocation_issue_list.append("RUNTIME_INVOCATION_AUDIT_SCHEMA_INVALID")
                        else:
                            invocation_issue_list.extend(
                                runtime_audit_after_invocation_issues(
                                    invocation_snapshot,
                                    run_id=actual_run_id,
                                    invocation_binding=invocation_binding,
                                    runtime_preflight_hash=runtime_preflight.preflight_hash,
                                    expected_execution_binding=runtime_preflight.execution_binding,
                                )
                            )
                            try:
                                invocation_path, invocation_hash = write_runtime_audit_snapshot(
                                    run_dir / "runtime-audit-after-first-invocation.json",
                                    invocation_snapshot,
                                )
                                invocation_artifact_ref = {
                                    "run_id": actual_run_id,
                                    "phase": "AFTER_INVOCATION",
                                    "path": invocation_path.name,
                                    "captured_at": invocation_snapshot.get("captured_at"),
                                    "sha256": invocation_hash,
                                }
                            except Exception as exc:
                                invocation_error_type = type(exc).__name__
                                invocation_issue_list.append("RUNTIME_INVOCATION_AUDIT_ARTIFACT_WRITE_FAILED")
                    except Exception as exc:
                        invocation_error_type = type(exc).__name__
                        invocation_issue_list.append("RUNTIME_INVOCATION_AUDIT_CAPTURE_FAILED")
                    if invocation_artifact_ref is None and "RUNTIME_INVOCATION_AUDIT_ARTIFACT_WRITE_FAILED" not in invocation_issue_list:
                        invocation_issue_list.append("RUNTIME_INVOCATION_AUDIT_ARTIFACT_MISSING")
                    case_invocation_issues = tuple(dict.fromkeys(invocation_issue_list))
                    first_invocation_ref = invocation_artifact_ref
                    first_invocation_error_type = invocation_error_type
                    first_invocation_capture_status = "FAILED" if case_invocation_issues else "CAPTURED"
                    case_runtime_audit = {
                        "status": first_invocation_capture_status,
                        "phase": "AFTER_INVOCATION",
                        "artifact": invocation_artifact_ref,
                        "issues": list(case_invocation_issues),
                        "error_type": invocation_error_type,
                    }
            try:
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
            except Exception as exc:
                abort = {
                    "case_id": case_id,
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "error_type": type(exc).__name__,
                    "retry_performed": False,
                    "request_sent": True,
                    "response_received": True,
                    "evidence_recorded": False,
                    "reason_code": "CASE_EVIDENCE_BUILD_FAILED",
                    "disposition": "STOPPED_FOR_EXECUTION_INTEGRITY",
                }
                break
            if case_runtime_audit is not None:
                result["runtime_execution_audit"] = case_runtime_audit
            result["retrieval_evidence"]["corpus_identity"] = {
                "corpus_id": corpus_manifest["corpus_id"],
                "corpus_hash": corpus_manifest["corpus_hash"],
            }
            try:
                postflight = await transport.check_execution_integrity(preflight_observation)
            except Exception as exc:
                postflight = {
                    "status": "FAIL",
                    "violations": [{"code": "POST_CASE_INTEGRITY_CHECK_FAILED", "error_type": type(exc).__name__}],
                }
            post_input_issues = _frozen_input_issues(
                packet=packet,
                case_manifest=case_manifest,
                corpus_manifest=corpus_manifest,
                repo_root=repo_root,
                baseline_git_snapshot=baseline_git_snapshot,
                case_manifest_path=case_manifest_path,
                corpus_manifest_path=corpus_manifest_path,
                baseline_case_file_hash=baseline_case_file_hash,
                baseline_corpus_file_hash=baseline_corpus_file_hash,
            )
            integrity = classify_execution_integrity(
                observation=observation,
                result=result,
                input_issues=(*case_invocation_issues, *post_input_issues),
                postflight=postflight,
            )
            result["execution_integrity"] = integrity
            result.pop("result_hash", None)
            result["result_hash"] = canonical_sha256_tag(result, self_field="result_hash")
            try:
                _write_case_result(run_dir, result)
                if _write_error_audit_record(run_dir, result, create=not error_audit_created):
                    error_audit_created = True
            except Exception as exc:
                abort = {
                    "case_id": case_id,
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "error_type": type(exc).__name__,
                    "retry_performed": False,
                    "request_sent": True,
                    "response_received": True,
                    "evidence_recorded": False,
                    "reason_code": "CASE_EVIDENCE_RECORDER_FAILED",
                    "disposition": "STOPPED_FOR_EXECUTION_INTEGRITY",
                }
                break
            results.append(result)
            if integrity["status"] == "FAIL":
                abort = {
                    "case_id": case_id,
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "retry_performed": False,
                    "request_sent": True,
                    "response_received": True,
                    "evidence_recorded": True,
                    "reason_code": integrity["abort_reason"],
                    "integrity_violations": integrity["violations"],
                    "disposition": "STOPPED_FOR_EXECUTION_INTEGRITY",
                }
                break
    finally:
        await transport.close()

    after_ref: dict[str, Any] | None = None
    after_capture_status = "CAPTURED"
    after_error_type: str | None = None
    try:
        after_snapshot = await asyncio.to_thread(
            audit_capture,
            run_id=actual_run_id,
            phase="AFTER_CASES",
            runtime_preflight=runtime_preflight,
            managed_service_identity=managed_service_identity or {},
            evidence_root=output_root,
        )
        if (
            not isinstance(after_snapshot, Mapping)
            or after_snapshot.get("schema_version") != RUNTIME_AUDIT_SCHEMA
            or after_snapshot.get("run_id") != actual_run_id
            or after_snapshot.get("phase") != "AFTER_CASES"
        ):
            raise RunnerError("post-run Runtime audit binding is invalid")
        validate_runtime_audit_snapshot(after_snapshot)
        if after_snapshot.get("runtime_preflight_hash") != runtime_preflight.preflight_hash:
            raise RunnerError("post-run Runtime audit preflight hash is invalid")
        after_path, after_hash = write_runtime_audit_snapshot(
            run_dir / "runtime-audit-after-cases.json", after_snapshot
        )
        after_ref = {
            "run_id": actual_run_id,
            "phase": "AFTER_CASES",
            "path": after_path.name,
            "captured_at": after_snapshot.get("captured_at"),
            "sha256": after_hash,
        }
    except Exception as exc:
        after_capture_status = "FAILED"
        after_error_type = type(exc).__name__

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
    p0_p1_reports = [classify_p0_p1(result) for result in results]
    summary["product_p0_count"] = sum(item["p0_count"] for item in p0_p1_reports)
    summary["product_p1_count"] = sum(item["p1_count"] for item in p0_p1_reports)
    summary["execution_integrity_status"] = "FAIL" if abort else "PASS"
    summary["execution_abort_reason"] = abort.get("reason_code") if abort else None
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
    summary["error_evidence_audit"] = _error_audit_artifact_ref(run_dir)
    summary["runtime_audit_evidence"] = {
        "before_cases": before_ref,
        "after_cases": after_ref,
        "after_capture_status": after_capture_status,
        "after_capture_error_type": after_error_type,
        "first_invocation": first_invocation_ref,
        "first_invocation_capture_status": first_invocation_capture_status,
        "first_invocation_error_type": first_invocation_error_type,
    }
    if first_invocation_seen:
        summary["runtime_execution_status"] = (
            "MODEL_INVOCATION_AUDIT_FAILED"
            if first_invocation_capture_status == "FAILED"
            else "MODEL_INVOCATION_AUDITED"
        )
    elif len(results) == len(packet.answerability_cases):
        summary["runtime_execution_status"] = "NO_MODEL_INVOCATION_OBSERVED"
    else:
        summary["runtime_execution_status"] = "INCOMPLETE_NO_MODEL_INVOCATION_OBSERVED"
    summary["run_summary_hash"] = canonical_summary_hash(summary)
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
    summary["run_summary_hash"] = canonical_summary_hash(summary)
    return {
        "run_id": mock_id,
        "results": results,
        "summary": summary,
        "case_manifest": case_manifest,
        "corpus_manifest": corpus_manifest,
        "evidence_status": NONFORMAL_EVIDENCE,
    }
