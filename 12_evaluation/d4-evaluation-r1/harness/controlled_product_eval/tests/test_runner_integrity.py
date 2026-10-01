from __future__ import annotations

import asyncio
import json
from typing import Any, Mapping
from pathlib import Path

import jsonschema
import pytest

from harness.controlled_product_eval.approved_packet import (
    APPROVED_PACKET_HASH,
    APPROVED_PACKET_ID,
    load_approved_packet,
)
from harness.controlled_product_eval.manifest import (
    EXPECTED_RUNTIME_IDENTITY,
    build_approved_corpus_manifest,
    build_case_manifest,
    build_runtime_preflight,
    write_json_once,
)
from harness.controlled_product_eval.network_integrity import parse_netstat_output
from harness.controlled_product_eval.runner import (
    CanonicalHttpTransport,
    EXPECTED_RUNTIME_HTTP_ENDPOINT,
    EXPECTED_RUNTIME_LOGICAL_MODEL_ID,
    SYNTHETIC_CAT_INSTRUMENT_ID,
    SYNTHETIC_CAT_INSTRUMENT_VERSION,
    TransportObservation,
    classify_execution_integrity,
    run_evaluation,
)
from harness.controlled_product_eval import runner as runner_module

SCHEMA_ROOT = Path(__file__).resolve().parents[3] / "spec"


@pytest.fixture()
def packet():
    packet_path = Path(__file__).resolve().parents[3] / "D4_3A_HUMAN_GOLD_REVIEW_PACKET.json"
    return load_approved_packet(packet_path)


def _rag_identity(corpus: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": "READY",
        "service": "rag",
        "retrieval_mode": "hybrid",
        "index_id": "INDEX_TEST_FRESH",
        "index_reused": False,
        "index_manifest_hash": "sha256:" + "1" * 64,
        "corpus_manifest_hash": corpus["corpus_hash"],
        "source_packet_id": APPROVED_PACKET_ID,
        "source_packet_hash": APPROVED_PACKET_HASH,
        "evaluation_only": True,
        "synthetic_fixture_only": True,
        "eligible_chunk_ids": list(corpus["evidence_ids"]),
    }


def _runtime_identity() -> dict[str, Any]:
    return {
        "state": "READY",
        "readiness": "pass",
        "runtime_version": "0.1.0",
        "cloud_fallback": False,
        "models": {
            "qwen2.5-7b-instruct-gpu-acceptance": {
                "logical_model_id": "qwen2.5-7b-instruct-gpu-acceptance",
                "provider_model_id": EXPECTED_RUNTIME_IDENTITY["model"],
                "availability": "available",
                "inference_readiness": "ready",
                "loaded": False,
            }
        },
        "provider_ids": ["ollama"],
    }


def _exact_llm_event(*, fallback: bool = False, drift: bool = False) -> Mapping[str, Any]:
    model = EXPECTED_RUNTIME_IDENTITY["model"]
    digest = EXPECTED_RUNTIME_IDENTITY["digest"]
    return {
        "response_summary": {
            "model_id": model,
            "provider_model": "qwen2.5:0.5b" if drift else model,
            "model_revision": "test-revision",
            "runtime_version": "0.1.0",
            "digest": "0" * 64 if drift else digest,
            "fallback_used": fallback,
            "context_length": EXPECTED_RUNTIME_IDENTITY["num_ctx"],
            "output_budget": EXPECTED_RUNTIME_IDENTITY["output_budget"],
        }
    }


def _product_p0_observation(*, fallback: bool = False, drift: bool = False) -> TransportObservation:
    return TransportObservation(
        http_status=200,
        response_body={
            "data": {
                "status": "generated",
                "normal_generation": True,
                "content": {
                    "summary": "Synthetic test output",
                    "observations": [],
                    "suggestions": [],
                    "disclaimer": "Synthetic test only",
                },
                "citations": [{"chunk_id": "CHUNK_NOT_IN_APPROVED_CORPUS"}],
                "generation": {
                    "generation_id": "GEN_test",
                    "status": "generated",
                    "provenance": {"generation_status": "generated"},
                },
            }
        },
        llm_events=(_exact_llm_event(fallback=fallback, drift=drift),),
    )


def test_canonical_http_preflight_constructs_async_clients_synchronously(monkeypatch):
    backend_url = "http://127.0.0.1:8080"
    observer_urls = {
        "rag": "http://127.0.0.1:8271",
        "llm": "http://127.0.0.1:8272",
    }

    class Response:
        status_code = 200

        def __init__(self, body: Mapping[str, Any]) -> None:
            self._body = body

        def json(self) -> Mapping[str, Any]:
            return self._body

    class FakeClient:
        def __init__(self, *, base_url: str, **_kwargs: Any) -> None:
            self.base_url = base_url

        async def get(self, path: str) -> Response:
            if self.base_url == backend_url and path == "/health/ready":
                return Response({"data": {"status": "ready"}})
            if self.base_url == backend_url and path == "/health/dependencies":
                return Response({
                    "data": {
                        name: {"status": "READY", "integration": "REAL_HTTP"}
                        for name in ("cat", "rag", "llm_runtime", "safety")
                    }
                })
            if path == "/health" and self.base_url == observer_urls["rag"]:
                return Response({
                    "status": "READY",
                    "observer": "rag",
                    "upstream": "http://127.0.0.1:8170",
                    "service_identity": {"status": "READY", "index_reused": False},
                })
            if path == "/health" and self.base_url == observer_urls["llm"]:
                return Response({
                    "status": "READY",
                    "observer": "llm",
                    "upstream": EXPECTED_RUNTIME_HTTP_ENDPOINT,
                    "service_identity": {
                        "readiness": "pass",
                        "cloud_fallback": False,
                        "models": {
                            EXPECTED_RUNTIME_LOGICAL_MODEL_ID: {
                                "provider_model_id": EXPECTED_RUNTIME_IDENTITY["model"],
                            }
                        },
                    },
                })
            pytest.fail(f"unexpected preflight request: {self.base_url}{path}")

        async def aclose(self) -> None:
            return None

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    class FakeNetworkMonitor:
        def start(self) -> Mapping[str, Any]:
            return {
                "status": "PASS",
                "issues": [],
                "external_established_connections": [],
            }

    monkeypatch.setattr(runner_module.httpx, "AsyncClient", FakeClient)
    transport = CanonicalHttpTransport(
        backend_base_url=backend_url,
        observer_urls=observer_urls,
        rag_observer_events="unused-rag-events.jsonl",
        llm_observer_events="unused-llm-events.jsonl",
        passwords={"student_a": "synthetic-a", "student_b": "synthetic-b"},
        network_monitor=FakeNetworkMonitor(),
    )

    result = asyncio.run(transport.preflight())

    assert result["backend"]["status"] == "READY"
    assert result["backend_dependency_identity"] == {
        name: {"status": "READY", "integration": "REAL_HTTP"}
        for name in ("cat", "rag", "llm_runtime", "safety")
    }
    assert result["observers"]["rag"]["status"] == "READY"
    assert result["observers"]["llm"]["upstream"] == EXPECTED_RUNTIME_HTTP_ENDPOINT
    assert result["unexpected_configuration"] == []


def test_synthetic_assessment_uses_fixed_cat_instrument_and_server_offered_options(monkeypatch):
    class Response:
        def __init__(self, status_code: int, body: Mapping[str, Any]) -> None:
            self.status_code = status_code
            self._body = body

        def json(self) -> Mapping[str, Any]:
            return self._body

    def state(*, answered: int, next_index: int | None, can_complete: bool) -> dict[str, Any]:
        if next_index is None:
            return {
                "assessment_id": "ASSESS_fixture",
                "status": "in_progress",
                "answered_count": answered,
                "can_complete": can_complete,
                "max_items": 3,
                "selected_item_id": None,
                "current_item": None,
            }
        return {
            "assessment_id": "ASSESS_fixture",
            "status": "in_progress",
            "answered_count": answered,
            "can_complete": can_complete,
            "max_items": 3,
            "selected_item_id": f"ITEM_demo_00{next_index}",
            "current_item": {
                "item_id": f"ITEM_demo_00{next_index}",
                "options": [{"value": f"fixture-option-{next_index}", "label": "synthetic"}],
            },
        }

    class FakeClient:
        def __init__(self) -> None:
            self.created_payload: Mapping[str, Any] | None = None
            self.responses: list[tuple[str, Any]] = []
            self.response_index = 0
            self.completed = False

        async def post(self, path: str, *, headers: Mapping[str, str], json: Mapping[str, Any]) -> Response:
            if path == "/api/v1/assessments":
                self.created_payload = json
                return Response(201, {"data": {"assessment_id": "ASSESS_fixture"}})
            if path == "/api/v1/assessments/ASSESS_fixture/responses":
                self.responses.append((str(json["item_id"]), json["response"]))
                self.response_index += 1
                return Response(
                    200,
                    {"data": state(
                        answered=self.response_index,
                        next_index=self.response_index + 1 if self.response_index < 3 else None,
                        can_complete=self.response_index == 3,
                    )},
                )
            if path == "/api/v1/assessments/ASSESS_fixture/complete":
                self.completed = True
                return Response(200, {"data": {"status": "completed"}})
            pytest.fail(f"unexpected assessment bootstrap request: {path}")

        async def get(self, path: str, *, headers: Mapping[str, str]) -> Response:
            if path == "/api/v1/assessments/ASSESS_fixture/state":
                return Response(200, {"data": state(answered=0, next_index=1, can_complete=False)})
            pytest.fail(f"unexpected assessment bootstrap request: {path}")

    transport = CanonicalHttpTransport(
        backend_base_url="http://127.0.0.1:8080",
        observer_urls={"rag": "http://127.0.0.1:8271", "llm": "http://127.0.0.1:8272"},
        rag_observer_events="unused-rag-events.jsonl",
        llm_observer_events="unused-llm-events.jsonl",
        passwords={"student_a": "synthetic-a", "student_b": "synthetic-b"},
    )
    transport._csrf["student_b"] = "synthetic-csrf"
    transport._subjects["student_b"] = "SUBJ_synthetic_b"
    client = FakeClient()

    async def use_fake_client(_username: str) -> FakeClient:
        return client

    monkeypatch.setattr(transport, "_client", use_fake_client)
    result = asyncio.run(transport._create_assessment("student_b", "D4B_FOREIGN"))

    assert result == "ASSESS_fixture"
    assert client.created_payload == {
        "subject_id": "SUBJ_synthetic_b",
        "instrument_id": SYNTHETIC_CAT_INSTRUMENT_ID,
        "instrument_version": SYNTHETIC_CAT_INSTRUMENT_VERSION,
    }
    assert client.responses == [
        ("ITEM_demo_001", "fixture-option-1"),
        ("ITEM_demo_002", "fixture-option-2"),
        ("ITEM_demo_003", "fixture-option-3"),
    ]
    assert client.completed is True


class _FormalFakeTransport(CanonicalHttpTransport):
    def __init__(
        self,
        *,
        corpus: Mapping[str, Any],
        response_factory,
        fail_ordinal: int | None = None,
        integrity_failure: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(
            backend_base_url="http://127.0.0.1:8080",
            observer_urls={"rag": "http://127.0.0.1:8271", "llm": "http://127.0.0.1:8272"},
            rag_observer_events="unused-rag-events.jsonl",
            llm_observer_events="unused-llm-events.jsonl",
            passwords={"student_a": "synthetic-a", "student_b": "synthetic-b"},
        )
        self.corpus = corpus
        self.response_factory = response_factory
        self.fail_ordinal = fail_ordinal
        self.integrity_failure = integrity_failure
        self.submitted: list[str] = []
        self.closed = False

    async def preflight(self) -> Mapping[str, Any]:
        return {
            "backend": {"status": "READY", "url": "http://127.0.0.1:8080"},
            "observers": {
                "rag": {"status": "READY", "upstream": "http://127.0.0.1:8170"},
                "llm": {"status": "READY", "upstream": "http://127.0.0.1:8160"},
            },
            "rag_service_identity": _rag_identity(self.corpus),
            "runtime_endpoint_health_identity": _runtime_identity(),
            "backend_dependency_identity": {
                name: {"status": "READY", "integration": "REAL_HTTP"}
                for name in ("cat", "rag", "llm_runtime", "safety")
            },
            "unexpected_configuration": [],
            "network_observation": {"status": "PASS", "listeners": [], "issues": []},
            "network_policy": "LOOPBACK_ONLY",
            "trust_env": False,
            "retry_policy": {"max_retries": 0, "non_idempotent_post_retries": 0},
        }

    async def prepare(self) -> None:
        return None

    async def submit(
        self,
        case: Mapping[str, Any],
        *,
        run_id: str,
        request_id: str,
        trace_id: str,
        ordinal: int,
    ) -> TransportObservation:
        self.submitted.append(str(case["case_id"]))
        if ordinal == self.fail_ordinal:
            raise TimeoutError("support outcome may be uncertain")
        return self.response_factory(ordinal, case, trace_id)

    async def check_execution_integrity(self, baseline: Mapping[str, Any]) -> Mapping[str, Any]:
        return dict(self.integrity_failure or {"status": "PASS", "violations": []})

    async def close(self) -> None:
        self.closed = True


def _normal_observation(*_args) -> TransportObservation:
    return TransportObservation(
        http_status=202,
        response_body={"data": {"status": "abstained", "normal_generation": False, "content": None}},
    )


def _product_http_error(status: int) -> TransportObservation:
    return TransportObservation(
        http_status=status,
        response_body={"error": {"code": "PRODUCT_ERROR", "message": "Deterministic product response"}},
    )


def _gold_respecting_observation(_ordinal, case, _trace) -> TransportObservation:
    expected = case["expected_response_class"]
    if expected == "MUST_ROUTE":
        return TransportObservation(
            http_status=200,
            response_body={"data": {"status": "needs_review", "safety_action": "CRISIS_ROUTE", "normal_generation": False, "content": None}},
        )
    if expected == "MUST_DENY":
        return TransportObservation(http_status=403, response_body={"error": {"code": "AUTH_FORBIDDEN"}})
    if expected == "SHOULD_ABSTAIN":
        return _normal_observation()
    return TransportObservation(
        http_status=200,
        response_body={
            "data": {
                "status": "generated",
                "normal_generation": True,
                "content": {"summary": "", "observations": [], "suggestions": [], "disclaimer": "Synthetic test only"},
                "citations": [],
                "generation": {"generation_id": "GEN_test", "status": "generated", "provenance": {"generation_status": "generated"}},
            }
        },
        llm_events=(_exact_llm_event(),),
    )


def _run(tmp_path, packet, transport, *, suffix: str, case_manifest_path: Path | None = None):
    case_manifest = build_case_manifest(packet)
    corpus_manifest = build_approved_corpus_manifest(packet)
    if case_manifest_path is not None:
        write_json_once(case_manifest_path, case_manifest)
    return asyncio.run(
        run_evaluation(
            packet=packet,
            case_manifest=case_manifest,
            corpus_manifest=corpus_manifest,
            runtime_preflight=build_runtime_preflight(observed_at="2026-09-28T00:00:00Z"),
            transport=transport,
            backend_base_url="http://127.0.0.1:8080",
            observer_endpoints={"rag": "http://127.0.0.1:8271", "llm": "http://127.0.0.1:8272"},
            rag_observer_events=tmp_path / f"rag-{suffix}.jsonl",
            llm_observer_events=tmp_path / f"llm-{suffix}.jsonl",
            repo_root=Path(__file__).resolve().parents[5],
            output_root=tmp_path / f"runs-{suffix}",
            case_manifest_path=case_manifest_path,
            run_id=f"D4RUN-{suffix}",
            timestamp="2026-09-28T00:00:00Z",
        )
    )


def test_case_one_product_p0_is_recorded_and_case_two_continues(tmp_path, packet):
    corpus = build_approved_corpus_manifest(packet)

    def responses(ordinal, _case, _trace):
        return _product_p0_observation() if ordinal == 0 else _normal_observation()

    transport = _FormalFakeTransport(corpus=corpus, response_factory=responses)
    output = _run(tmp_path, packet, transport, suffix="P0-CONTINUE-A")

    assert len(output["results"]) == 12
    assert output["results"][0]["execution_integrity"]["status"] == "PASS"
    assert output["summary"]["run_status"] == "RUN_COMPLETE_FOR_CONTROLLER_REVIEW"
    assert output["summary"]["product_p0_count"] >= 1
    assert output["summary"]["execution_integrity_status"] == "PASS"
    assert transport.submitted == [case["case_id"] for case in packet.answerability_cases]
    case_schema = json.loads((SCHEMA_ROOT / "d4_slice3b_case_result.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(case_schema).validate(output["results"][0])


def test_multiple_product_p0_findings_do_not_stop_the_frozen_order(tmp_path, packet):
    corpus = build_approved_corpus_manifest(packet)

    def responses(ordinal, _case, _trace):
        if ordinal == 0:
            return _product_http_error(502)
        if ordinal == 3:
            return _product_http_error(409)
        if ordinal == 7:
            return _product_p0_observation()
        return _gold_respecting_observation(ordinal, _case, _trace)

    transport = _FormalFakeTransport(corpus=corpus, response_factory=responses)
    output = _run(tmp_path, packet, transport, suffix="P0-CONTINUE-B")

    assert output["summary"]["case_ids"] == [case["case_id"] for case in packet.answerability_cases]
    p0_case_count = sum(
        any(finding["severity"] == "P0" for finding in result["findings"])
        for result in output["results"]
    )
    assert p0_case_count == 3
    assert output["results"][0]["actual"]["http_status"] == 502
    assert output["results"][3]["actual"]["http_status"] == 409
    assert output["summary"]["product_p0_count"] > 0
    assert output["summary"]["execution_integrity_status"] == "PASS"
    assert output["summary"]["execution_abort_reason"] is None


def test_uncertain_transport_outcome_stops_without_retry(tmp_path, packet):
    corpus = build_approved_corpus_manifest(packet)
    transport = _FormalFakeTransport(
        corpus=corpus,
        response_factory=lambda *_args: _normal_observation(),
        fail_ordinal=4,
    )
    output = _run(tmp_path, packet, transport, suffix="UNCERTAIN-STOP")

    assert len(output["results"]) == 4
    assert len(transport.submitted) == 5
    assert len(set(transport.submitted)) == len(transport.submitted)
    assert output["abort"]["reason_code"] == "REQUEST_OUTCOME_UNCERTAIN"
    assert output["summary"]["execution_integrity_status"] == "FAIL"
    assert output["summary"]["run_status"] == "STOPPED_WITH_REQUEST_OUTCOME_UNCERTAIN"


def test_case_manifest_mutation_records_current_case_then_stops(tmp_path, packet):
    corpus = build_approved_corpus_manifest(packet)
    manifest_path = tmp_path / "frozen-case-manifest.json"
    changed = False

    def responses(_ordinal, _case, _trace):
        nonlocal changed
        if not changed:
            manifest_path.write_text("{}", encoding="utf-8")
            changed = True
        return _normal_observation()

    transport = _FormalFakeTransport(corpus=corpus, response_factory=responses)
    output = _run(
        tmp_path,
        packet,
        transport,
        suffix="MANIFEST-DRIFT",
        case_manifest_path=manifest_path,
    )

    assert len(transport.submitted) == 1
    assert len(output["results"]) == 1
    assert output["results"][0]["execution_integrity"]["abort_reason"] == "CASE_MANIFEST_FILE_CHANGED"
    assert output["summary"]["execution_integrity_status"] == "FAIL"
    assert output["summary"]["run_status"] == "STOPPED_FOR_EXECUTION_INTEGRITY"


@pytest.mark.parametrize("integrity_kind", ["external", "fallback", "runtime-drift", "dependency-health"])
def test_execution_integrity_failures_stop_even_when_case_is_recordable(tmp_path, packet, integrity_kind):
    corpus = build_approved_corpus_manifest(packet)
    if integrity_kind == "external":
        observation = TransportObservation(
            http_status=202,
            response_body={"data": {"status": "abstained", "normal_generation": False, "content": None}},
            external_network_detected=True,
        )
    elif integrity_kind == "fallback":
        observation = _product_p0_observation(fallback=True)
    elif integrity_kind == "runtime-drift":
        observation = _product_p0_observation(drift=True)
    else:
        observation = _normal_observation()

    transport = _FormalFakeTransport(
        corpus=corpus,
        response_factory=lambda *_args: observation,
        integrity_failure=(
            {"status": "FAIL", "violations": [{"code": "BACKEND_DEPENDENCY_UNAVAILABLE"}]}
            if integrity_kind == "dependency-health"
            else None
        ),
    )
    output = _run(tmp_path, packet, transport, suffix=f"INTEGRITY-{integrity_kind.upper()}")

    assert len(output["results"]) == 1
    assert output["results"][0]["execution_integrity"]["status"] == "FAIL"
    assert output["summary"]["execution_integrity_status"] == "FAIL"
    assert output["summary"]["run_status"] == "STOPPED_FOR_EXECUTION_INTEGRITY"
    assert len(transport.submitted) == 1


def test_frozen_manifest_order_is_preserved_and_each_case_submits_at_most_once(tmp_path, packet):
    corpus = build_approved_corpus_manifest(packet)
    transport = _FormalFakeTransport(corpus=corpus, response_factory=lambda *_args: _normal_observation())
    output = _run(tmp_path, packet, transport, suffix="ORDER-ONCE")

    expected = [case["case_id"] for case in packet.answerability_cases]
    assert transport.submitted == expected
    assert len(transport.submitted) == len(set(transport.submitted)) == 12
    assert output["summary"]["case_ids"] == expected


def test_twelve_product_p0_cases_complete_with_integrity_pass(tmp_path, packet):
    corpus = build_approved_corpus_manifest(packet)
    transport = _FormalFakeTransport(corpus=corpus, response_factory=lambda *_args: _product_p0_observation())
    output = _run(tmp_path, packet, transport, suffix="TWELVE-P0")

    assert len(output["results"]) == 12
    assert all(any(finding["severity"] == "P0" for finding in result["findings"]) for result in output["results"])
    assert output["summary"]["product_p0_count"] >= 12
    assert output["summary"]["execution_integrity_status"] == "PASS"
    assert output["summary"]["execution_abort_reason"] is None
    assert output["summary"]["run_status"] == "RUN_COMPLETE_FOR_CONTROLLER_REVIEW"
    summary_schema = json.loads((SCHEMA_ROOT / "d4_slice3b_summary.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(summary_schema).validate(output["summary"])


def test_integrity_classifier_does_not_use_product_p0_count_as_abort_signal():
    classified = classify_execution_integrity(
        result={"findings": [{"code": "UNKNOWN_SEVERITY", "severity": "P0", "evidence": "product output"}]}
    )
    assert classified == {"status": "PASS", "abort_reason": None, "violations": []}


def test_netstat_integrity_parser_detects_remote_data_plane_egress():
    output = """
      Proto Local Address          Foreign Address        State           PID
      TCP   127.0.0.1:8080          0.0.0.0:0              LISTENING       100
      TCP   127.0.0.1:8080          127.0.0.1:51234        ESTABLISHED     100
      TCP   10.0.0.4:54000          203.0.113.8:443        ESTABLISHED     100
    """
    observation = parse_netstat_output(output, required_ports=frozenset({8080}), observer_pid=900)
    assert observation["status"] == "FAIL"
    assert any(issue["code"] == "EXTERNAL_ESTABLISHED_CONNECTION" for issue in observation["issues"])


def test_netstat_integrity_parser_monitors_supervisor_tree_listeners_and_forbidden_destinations():
    output = """
      Proto Local Address          Foreign Address        State           PID
      TCP   0.0.0.0:8181            0.0.0.0:0              LISTENING       410
      TCP   127.0.0.1:50000         127.0.0.1:3306         ESTABLISHED     410
      TCP   127.0.0.1:50001         198.51.100.4:443       ESTABLISHED     410
    """
    observation = parse_netstat_output(
        output,
        required_ports=frozenset({8080}),
        observer_pid=900,
        owned_pids={410},
    )
    codes = {issue["code"] for issue in observation["issues"]}
    assert observation["status"] == "FAIL"
    assert "OWNED_NON_LOOPBACK_LISTENER" in codes
    assert "FORBIDDEN_FORMAL_ENDPOINT_CONNECTION" in codes
    assert "EXTERNAL_ESTABLISHED_CONNECTION" in codes
    assert observation["monitored_process_pids"] == [410, 900]
