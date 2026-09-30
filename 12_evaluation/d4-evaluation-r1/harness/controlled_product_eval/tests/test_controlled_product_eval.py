from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
from argparse import Namespace
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import jsonschema
import pytest

from harness.citation_utility.review_packet import packet_from_json, packet_hash
from harness.foundation.hashing import canonical_sha256_tag
from harness.controlled_product_eval.approved_packet import (
    APPROVED_PACKET_HASH,
    APPROVED_PACKET_ID,
    ApprovedPacketError,
    load_approved_packet,
    thaw_json,
)
from harness.controlled_product_eval.cli import _evaluation_database_endpoint, _managed_specs
from harness.controlled_product_eval.manifest import (
    EXPECTED_RUNTIME_IDENTITY,
    ManifestError,
    RuntimePreflight,
    build_approved_corpus_manifest,
    build_case_manifest,
    build_formal_manifest,
    build_runtime_preflight,
    verify_case_manifest,
    verify_corpus_manifest,
    verify_formal_manifest,
    write_json_once,
)
from harness.controlled_product_eval.rag_runtime import IsolatedRagError, materialize_rag_inputs
from harness.controlled_product_eval.observer_proxy import _safe_runtime_health
from harness.controlled_product_eval.process_lifecycle import ProcessSpec, ProcessSupervisor
from harness.controlled_product_eval.results import (
    FORMAL_EVIDENCE,
    NONFORMAL_EVIDENCE,
    aggregate_results,
    build_case_result,
    classify_p0_p1,
)
from harness.controlled_product_eval.runner import (
    CanonicalHttpTransport,
    RunnerError,
    run_evaluation,
    run_mock_validation,
)


ROOT = Path(__file__).resolve().parents[5]
EVAL_ROOT = Path(__file__).resolve().parents[3]
PACKET_PATH = EVAL_ROOT / "D4_3A_HUMAN_GOLD_REVIEW_PACKET.json"
SCHEMA_ROOT = ROOT / "12_evaluation" / "d4-evaluation-r1" / "spec"
FORMAL_RUNTIME_IDENTITY = {
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


@pytest.fixture()
def packet():
    return load_approved_packet(PACKET_PATH)


def test_approved_consumer_verifies_exact_canonical_gold_without_mutating_source(packet):
    before = PACKET_PATH.read_bytes()
    assert packet.packet_id == APPROVED_PACKET_ID
    assert packet.packet_hash == APPROVED_PACKET_HASH
    assert len(packet.citation_cases) == 7
    assert len(packet.answerability_cases) == 12
    assert packet.payload["annotation_status"] == "HUMAN_APPROVED"
    assert packet_hash(packet.payload) == APPROVED_PACKET_HASH
    assert packet.source_provenance["answerability"]["hash"].startswith("sha256:")
    packet.verify_unchanged()
    assert PACKET_PATH.read_bytes() == before
    with pytest.raises(TypeError):
        packet.payload["packet_id"] = "D4-PACKET-MUTATED"


def test_existing_review_packet_parser_still_rejects_approved_packet(packet):
    serialized = json.dumps(thaw_json(packet.payload), ensure_ascii=False)
    with pytest.raises(ValueError, match="HUMAN_APPROVED"):
        packet_from_json(serialized)


@pytest.mark.parametrize("mutator", [
    lambda value: value.update(packet_id="D4-PACKET-WRONG"),
    lambda value: value.pop("approval_record"),
    lambda value: value["approval_record"].update(reviewer_id="MISSING_REVIEWER"),
    lambda value: value["answerability_cases"][0].update(expected_response_class="SHOULD_ANSWER"),
])
def test_approved_consumer_fails_closed_on_wrong_identity_approval_or_gold(tmp_path, packet, mutator):
    value = thaw_json(packet.payload)
    mutator(value)
    path = tmp_path / "packet.json"
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ApprovedPacketError):
        load_approved_packet(path)


def test_duplicate_json_keys_are_rejected(tmp_path, packet):
    path = tmp_path / "packet.json"
    path.write_text('{"packet_id":"one","packet_id":"two"}', encoding="utf-8")
    with pytest.raises(ApprovedPacketError, match="duplicate JSON"):
        load_approved_packet(path)


def test_case_manifest_is_deterministic_and_has_stable_gold_case_ids(packet):
    first = build_case_manifest(packet)
    second = build_case_manifest(packet)
    assert first == second
    assert verify_case_manifest(first, packet=packet)
    assert len(first["approved_case_ids"]) == 12
    assert len(set(first["approved_case_ids"])) == 12
    assert len(first["citation_reference_case_ids"]) == 7
    assert first["expected_class_distribution"] == {
        "MUST_ANSWER": 5,
        "SHOULD_ABSTAIN": 4,
        "SHOULD_ANSWER": 1,
        "MUST_ROUTE": 1,
        "MUST_DENY": 1,
    }
    schema = json.loads((SCHEMA_ROOT / "d4_slice3b_case_manifest.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(first)


def test_corpus_manifest_preserves_source_annotations_and_never_reads_d2(packet):
    corpus = build_approved_corpus_manifest(packet)
    assert corpus == build_approved_corpus_manifest(packet)
    assert verify_corpus_manifest(corpus, packet=packet)
    assert len(corpus["evidence_ids"]) == 7
    assert len(corpus["source_evidence_ids"]) == 3
    assert len(corpus["evidence_ids"]) == len(set(corpus["evidence_ids"]))
    study_alias = next(item for item in corpus["evidence_aliases"] if item["source_chunk_id"] == "CHUNK_SYNTH_STUDY_PLANNING_001")
    assert len(study_alias["evaluation_chunk_ids"]) == 4
    assert sorted(study_alias["evaluation_chunk_ids"]) == [
        item["chunk_id"] for item in corpus["evidence"] if item["source_chunk_id"] == "CHUNK_SYNTH_STUDY_PLANNING_001"
    ]
    assert corpus["temporary_index_policy"]["persistent_product_index"] is False
    assert corpus["temporary_index_policy"]["d2_publication"] is False
    assert corpus["temporary_index_policy"]["source_review_annotations_preserved"] is True
    for source in corpus["evidence"]:
        assert source["evidence"]["review_state"] == "HUMAN_REVIEW_REQUIRED"
        assert source["evidence"]["human_gold"] is False
    for record in corpus["rag_embedding_records"]:
        metadata = record["metadata"]
        assert metadata["evaluation_only"] is True
        assert metadata["source_annotation"]["source_review_state"] == "HUMAN_REVIEW_REQUIRED"
        assert metadata["source_annotation"]["source_human_gold"] is False
        assert metadata["source_chunk_id"] in corpus["source_evidence_ids"]
        assert record["chunk_id"].startswith("CHUNK_D4_3B_")
        assert metadata["source_packet_hash"] == APPROVED_PACKET_HASH
    schema = json.loads((SCHEMA_ROOT / "d4_slice3b_approved_corpus.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(corpus)


def test_temporary_rag_materialization_is_outside_repo_and_matches_allowlist(tmp_path, packet):
    corpus = build_approved_corpus_manifest(packet)
    temp = tmp_path / "d4-rag-run"
    materialized = materialize_rag_inputs(corpus, work_dir=temp, repo_root=ROOT)
    rows = [json.loads(line) for line in materialized["embedding_ready_path"].read_text(encoding="utf-8").splitlines()]
    assert sorted(row["chunk_id"] for row in rows) == corpus["evidence_ids"]
    assert all(row["metadata"]["evaluation_only"] is True for row in rows)
    assert materialized["input_manifest"]["d2_publication"] is False
    assert materialized["input_manifest"]["source_annotations_preserved"] is True
    assert not (ROOT / "04_knowledge-pipeline" / "data" / "published").exists() or not materialized["root"].is_relative_to(ROOT)


def test_temporary_rag_materialization_refuses_checkout_writes(tmp_path, packet):
    corpus = build_approved_corpus_manifest(packet)
    with pytest.raises(IsolatedRagError, match="outside the project checkout"):
        materialize_rag_inputs(corpus, work_dir=ROOT / "12_evaluation" / "should-not-exist", repo_root=ROOT)


def test_runtime_preflight_requires_exact_identity_hash_and_loopback():
    assert EXPECTED_RUNTIME_IDENTITY == FORMAL_RUNTIME_IDENTITY
    preflight = build_runtime_preflight(observed_at=datetime(2026, 9, 25, tzinfo=timezone.utc))
    verified = RuntimePreflight.from_mapping(preflight)
    assert verified.identity == FORMAL_RUNTIME_IDENTITY
    schema = json.loads((SCHEMA_ROOT / "d4_runtime_preflight.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(preflight)
    wrong_digest = deepcopy(preflight)
    wrong_digest["runtime_identity"]["digest"] = "0" * 64
    wrong_digest["preflight_hash"] = canonical_sha256_tag(wrong_digest, self_field="preflight_hash")
    with pytest.raises(ManifestError, match="digest"):
        RuntimePreflight.from_mapping(wrong_digest)
    fallback = deepcopy(preflight)
    fallback["runtime_identity"]["cloud_fallback"] = True
    fallback["preflight_hash"] = canonical_sha256_tag(fallback, self_field="preflight_hash")
    with pytest.raises(ManifestError, match="cloud_fallback"):
        RuntimePreflight.from_mapping(fallback)
    egress = deepcopy(preflight)
    egress["network_observation"] = "NON_LOOPBACK_DETECTED"
    egress["preflight_hash"] = canonical_sha256_tag(egress, self_field="preflight_hash")
    with pytest.raises(ManifestError, match="loopback"):
        RuntimePreflight.from_mapping(egress)


@pytest.mark.parametrize("endpoint", [
    "http://127.0.0.1:11434",
    "http://127.0.0.1:11438",
    "http://192.0.2.10:11437",
])
def test_runtime_preflight_rejects_nonformal_endpoint(endpoint):
    identity = {**FORMAL_RUNTIME_IDENTITY, "endpoint": endpoint}
    preflight = build_runtime_preflight(
        observed_at="2026-09-25T00:00:00Z",
        identity=identity,
    )
    with pytest.raises(ManifestError, match="identity mismatch: endpoint"):
        RuntimePreflight.from_mapping(preflight)


@pytest.mark.parametrize(("field", "value"), [
    ("ollama_version", "0.33.2"),
    ("model", "qwen2.5:7b-instruct-q4_K_M-other"),
    ("digest", "0" * 64),
    ("num_ctx", 4096),
    ("kv_cache_type", "q8_0"),
    ("num_parallel", 2),
    ("max_loaded_models", 2),
    ("output_budget", 769),
    ("cloud_fallback", True),
])
def test_runtime_preflight_rejects_drift_in_every_non_endpoint_identity_field(field, value):
    identity = {**FORMAL_RUNTIME_IDENTITY, field: value}
    preflight = build_runtime_preflight(
        observed_at="2026-09-25T00:00:00Z",
        identity=identity,
    )
    with pytest.raises(ManifestError, match=f"identity mismatch: {field}"):
        RuntimePreflight.from_mapping(preflight)


def _rag_identity(corpus):
    return {
        "status": "READY",
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


def _backend_dependencies():
    return {
        "cat": {"status": "READY", "integration": "REAL_HTTP"},
        "rag": {"status": "READY", "integration": "REAL_HTTP"},
        "llm_runtime": {"status": "READY", "integration": "REAL_HTTP"},
        "safety": {"status": "READY", "integration": "REAL_HTTP"},
    }


def test_runtime_observer_health_accepts_ready_no_fallback_and_rejects_degraded():
    payload = {
        "status": "READY",
        "service": "llm_runtime",
        "health": {
            "state": "READY",
            "readiness": "pass",
            "runtime_version": "0.1.0",
            "cloud_fallback": False,
            "models": {
                "student.support.local": {
                    "logical_model_id": "student.support.local",
                    "provider_model_id": "qwen2.5:7b-instruct-q4_K_M",
                    "availability": "available",
                    "inference_readiness": "ready",
                    "loaded": False,
                    "message": "must not be retained",
                }
            },
            "providers": {"ollama": {"status": "pass"}},
        },
    }
    identity = _safe_runtime_health(payload)
    assert identity is not None
    assert identity["cloud_fallback"] is False
    assert identity["models"]["student.support.local"]["provider_model_id"] == EXPECTED_RUNTIME_IDENTITY["model"]
    assert "message" not in identity["models"]["student.support.local"]
    payload["health"]["readiness"] = "fail"
    assert _safe_runtime_health(payload) is None
    payload["health"]["readiness"] = "pass"
    payload["health"]["cloud_fallback"] = True
    assert _safe_runtime_health(payload) is None


@pytest.mark.asyncio
async def test_process_supervisor_starts_and_stops_only_its_owned_local_process(tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    script = (
        "from http.server import BaseHTTPRequestHandler,HTTPServer; "
        "H=type('H',(BaseHTTPRequestHandler,),{'do_GET':lambda self:(self.send_response(200),"
        "self.send_header('Content-Type','application/json'),self.end_headers(),self.wfile.write(b'{\\\"status\\\":\\\"READY\\\"}')),'log_message':lambda *a:None}); "
        f"HTTPServer(('127.0.0.1',{port}),H).serve_forever()"
    )
    supervisor = ProcessSupervisor(startup_timeout_seconds=5, shutdown_timeout_seconds=2)
    specs = [
        ProcessSpec(
            name="mock-loopback-service",
            executable=Path(sys.executable),
            arguments=("-c", script),
            cwd=tmp_path,
            environment={},
            readiness_url=f"http://127.0.0.1:{port}/health",
            readiness_kind="service",
            log_path=tmp_path / "mock-service.log",
        )
    ]
    identity = await supervisor.start(specs)
    assert identity[0]["name"] == "mock-loopback-service"
    assert identity[0]["pid"] > 0
    cleanup = await supervisor.close()
    assert cleanup["cleanup_verified"] is True
    assert cleanup["services"][0]["stopped"] is True


def test_evaluation_database_must_be_isolated_loopback(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_HOST", "127.0.0.1")
    monkeypatch.setenv("DB_PORT", "3307")
    monkeypatch.setenv("DB_USER", "synthetic_evaluation")
    monkeypatch.setenv("DB_PASSWORD", "test-only-placeholder")
    monkeypatch.setenv("DB_NAME", "smhai_d4_evaluation")
    assert _evaluation_database_endpoint() == ("127.0.0.1", 3307)

    monkeypatch.setenv("DB_HOST", "10.0.0.5")
    with pytest.raises(RunnerError, match="loopback"):
        _evaluation_database_endpoint()

    monkeypatch.setenv("DB_HOST", "127.0.0.1")
    monkeypatch.setenv("DB_PORT", "3306")
    with pytest.raises(RunnerError, match="isolated MySQL port"):
        _evaluation_database_endpoint()


def test_managed_stack_specs_own_only_loopback_evaluation_services(tmp_path, monkeypatch):
    inherited_pythonpath = str(tmp_path / "parent-controlled-pythonpath")
    monkeypatch.setenv("PYTHONPATH", inherited_pythonpath)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_HOST", "127.0.0.1")
    monkeypatch.setenv("DB_PORT", "3307")
    monkeypatch.setenv("DB_USER", "synthetic_evaluation")
    monkeypatch.setenv("DB_PASSWORD", "test-only-placeholder")
    monkeypatch.setenv("DB_NAME", "smhai_d4_evaluation")
    runtime = RuntimePreflight.from_mapping(build_runtime_preflight(observed_at="2026-09-25T00:00:00Z"))
    events = tmp_path / "events"
    specs = _managed_specs(
        args=Namespace(backend_python=sys.executable, rag_python=sys.executable),
        repo_root=ROOT,
        service_root=tmp_path / "stack",
        corpus_manifest_path=tmp_path / "corpus.json",
        runtime=runtime,
        rag_events=events / "rag.jsonl",
        llm_events=events / "llm.jsonl",
    )
    assert [spec.name for spec in specs] == ["d4-rag", "d4-rag-observer", "d4-llm-observer", "d4-backend"]
    assert all(spec.readiness_url.startswith("http://127.0.0.1:") for spec in specs)
    llm_observer = next(spec for spec in specs if spec.name == "d4-llm-observer")
    upstream = llm_observer.arguments[llm_observer.arguments.index("--upstream") + 1]
    assert upstream == "http://127.0.0.1:8160"
    assert runtime.identity["endpoint"] == "http://127.0.0.1:11437"
    assert upstream != runtime.identity["endpoint"]
    assert all("ollama" not in spec.name.lower() and "llm_runtime" not in spec.name.lower() for spec in specs)
    backend = specs[-1]
    evaluation_root = ROOT / "12_evaluation" / "d4-evaluation-r1"
    assert backend.environment["SMHAI_CAT__MODE"] == "http"
    assert backend.environment["SMHAI_RAG__MODE"] == "http"
    assert backend.environment["SMHAI_LLM__MODE"] == "http"
    assert backend.environment["SMHAI_SAFETY__MODE"] == "http"
    assert backend.environment["SMHAI_PERSISTENCE_MODE"] == "mysql"
    assert str(evaluation_root.resolve()) in backend.environment["PYTHONPATH"].split(os.pathsep)
    assert str((ROOT / "09_backend" / "src").resolve()) in backend.environment["PYTHONPATH"].split(os.pathsep)
    assert str((ROOT / "11_database").resolve()) in backend.environment["PYTHONPATH"].split(os.pathsep)
    assert inherited_pythonpath not in backend.environment["PYTHONPATH"]
    for spec in specs[:-1]:
        assert inherited_pythonpath not in spec.environment.get("PYTHONPATH", "")


def test_formal_manifest_records_dirty_checkout_configuration_runtime_and_hash(packet, tmp_path):
    case_manifest = build_case_manifest(packet)
    corpus = build_approved_corpus_manifest(packet)
    preflight = build_runtime_preflight(observed_at="2026-09-25T00:00:00Z")
    manifest = build_formal_manifest(
        packet=packet,
        case_manifest=case_manifest,
        corpus_manifest=corpus,
        runtime_preflight=preflight,
        backend_base_url="http://127.0.0.1:8080",
        observer_endpoints={"rag": "http://127.0.0.1:8271", "llm": "http://127.0.0.1:8272"},
        rag_service_identity=_rag_identity(corpus),
        runtime_endpoint_identity={"readiness": "pass", "cloud_fallback": False, "runtime_version": "0.1.0"},
        backend_dependency_identity=_backend_dependencies(),
        managed_service_identity={"owner": "TEST", "runtime_process_owned": False, "services": []},
        repo_root=ROOT,
        timestamp="2026-09-25T00:00:00Z",
        run_id="D4RUN-20260925T000000Z-TEST000000001",
        unexpected_configuration=("SMHAI_RAG_MODE=unexpected",),
    )
    repeated = build_formal_manifest(
        packet=packet,
        case_manifest=case_manifest,
        corpus_manifest=corpus,
        runtime_preflight=preflight,
        backend_base_url="http://127.0.0.1:8080",
        observer_endpoints={"rag": "http://127.0.0.1:8271", "llm": "http://127.0.0.1:8272"},
        rag_service_identity=_rag_identity(corpus),
        runtime_endpoint_identity={"readiness": "pass", "cloud_fallback": False, "runtime_version": "0.1.0"},
        backend_dependency_identity=_backend_dependencies(),
        managed_service_identity={"owner": "TEST", "runtime_process_owned": False, "services": []},
        repo_root=ROOT,
        timestamp="2026-09-25T00:00:00Z",
        run_id="D4RUN-20260925T000000Z-TEST000000001",
        unexpected_configuration=("SMHAI_RAG_MODE=unexpected",),
    )
    assert manifest == repeated
    assert verify_formal_manifest(manifest, packet=packet, case_manifest=case_manifest)
    assert manifest["git_dirty"] is True
    assert manifest["configuration_audit"]["unexpected"] == ["SMHAI_RAG_MODE=unexpected"]
    assert manifest["retry_policy"]["non_idempotent_post_retries"] == 0
    assert manifest["backend_identity"]["route"] == "/api/v1/support/requests"
    assert manifest["rag_corpus_identity"]["rag_service"]["index_reused"] is False
    assert manifest["runtime_expected_identity"] == FORMAL_RUNTIME_IDENTITY
    assert manifest["runtime_expected_identity"]["endpoint"] == "http://127.0.0.1:11437"
    assert manifest["runtime_observed_identity"] == FORMAL_RUNTIME_IDENTITY
    schema = json.loads((SCHEMA_ROOT / "d4_slice3b_run_manifest.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(manifest)

    fake_dependency_manifest = deepcopy(manifest)
    fake_dependency_manifest["backend_dependency_identity"]["cat"]["integration"] = "CONTRACT_FAKE"
    fake_dependency_manifest["manifest_hash"] = canonical_sha256_tag(
        fake_dependency_manifest, self_field="manifest_hash"
    )
    with pytest.raises(ManifestError, match="REAL_HTTP"):
        verify_formal_manifest(fake_dependency_manifest, packet=packet, case_manifest=case_manifest)


def test_manifest_writer_is_immutable(tmp_path):
    path = tmp_path / "manifest.json"
    original = {"schema_version": "test", "value": 1}
    write_json_once(path, original)
    write_json_once(path, original)
    with pytest.raises(ManifestError, match="already differs"):
        write_json_once(path, {"schema_version": "test", "value": 2})


def test_mock_harness_loads_all_cases_and_marks_every_result_nonformal(packet):
    output = asyncio.run(run_mock_validation(packet))
    assert output["evidence_status"] == NONFORMAL_EVIDENCE
    assert output["summary"]["evidence_status"] == NONFORMAL_EVIDENCE
    assert output["summary"]["case_count"] == 12
    assert {result["evidence_status"] for result in output["results"]} == {"NOT_FORMAL_PRODUCT_EVIDENCE"}
    population_mismatches = [
        result for result in output["results"]
        if result["expected"]["population"] == "university_freshman"
        and result["retrieval_evidence"]["observed_target_population"] == "K12学生"
    ]
    assert population_mismatches
    assert all(item["retrieval_evidence"]["population_mapping_status"] == "MISMATCH" for item in population_mismatches)
    assert all(item["retrieval_evidence"]["observed_target_population"] == "K12学生" for item in population_mismatches)


def test_p0_p1_rules_keep_required_route_and_fallback_at_p0(packet):
    case = next(item for item in packet.answerability_cases if item["expected_response_class"] == "MUST_ROUTE")
    failed_route = build_case_result(
        packet=packet,
        case=case,
        run_id="D4RUN-TEST-ROUTE-BROKEN",
        http_status=202,
        response_body={"data": {"status": "generated", "normal_generation": True, "content": {"summary": "mock", "observations": [], "suggestions": [], "disclaimer": "mock"}}},
        request_id="REQ_D43B_TEST",
        trace_id="TRACE_D43B_TEST",
        evidence_status=NONFORMAL_EVIDENCE,
        fallback_used=True,
    )
    classified = classify_p0_p1(failed_route)
    assert classified["p0_count"] >= 2
    codes = {item["code"] for item in classified["p0"]}
    assert "REQUIRED_ROUTE_BROKEN" in codes
    assert "CLOUD_OR_WEAK_FALLBACK" in codes


def test_false_refusal_is_p1_and_no_overall_utility_score(packet):
    case = next(item for item in packet.answerability_cases if item["expected_response_class"] == "MUST_ANSWER")
    result = build_case_result(
        packet=packet,
        case=case,
        run_id="D4RUN-TEST-FALSE-REFUSAL",
        http_status=202,
        response_body={"data": {"status": "abstained", "safety_action": "PROCEED", "normal_generation": False, "content": None}},
        request_id="REQ_D43B_TEST2",
        trace_id="TRACE_D43B_TEST2",
        evidence_status=NONFORMAL_EVIDENCE,
    )
    findings = classify_p0_p1(result)
    assert findings["p0_count"] == 0
    assert any(item["code"] == "FALSE_REFUSAL" for item in findings["p1"])
    summary = aggregate_results([result])
    assert summary["overall_utility_score"] is None
    assert summary["metrics_are_category_reports"] is True


def test_invalid_runtime_fails_before_transport_preflight_or_product_calls(packet, tmp_path):
    transport = CanonicalHttpTransport(
        backend_base_url="http://127.0.0.1:8080",
        observer_urls={"rag": "http://127.0.0.1:8271", "llm": "http://127.0.0.1:8272"},
        rag_observer_events=tmp_path / "rag.jsonl",
        llm_observer_events=tmp_path / "llm.jsonl",
    )
    calls: list[str] = []

    async def should_not_preflight():
        calls.append("preflight")
        return {}

    transport.preflight = should_not_preflight
    preflight = build_runtime_preflight(observed_at="2026-09-25T00:00:00Z")
    preflight["runtime_identity"]["digest"] = "0" * 64
    preflight["preflight_hash"] = canonical_sha256_tag(preflight, self_field="preflight_hash")
    with pytest.raises(ManifestError, match="digest"):
        asyncio.run(
            run_evaluation(
                packet=packet,
                case_manifest=build_case_manifest(packet),
                corpus_manifest=build_approved_corpus_manifest(packet),
                runtime_preflight=preflight,
                transport=transport,
                backend_base_url="http://127.0.0.1:8080",
                observer_endpoints={"rag": "http://127.0.0.1:8271", "llm": "http://127.0.0.1:8272"},
                rag_observer_events=tmp_path / "rag.jsonl",
                llm_observer_events=tmp_path / "llm.jsonl",
                repo_root=ROOT,
                output_root=tmp_path / "runs",
            )
        )
    assert calls == []
    assert not (tmp_path / "runs").exists()


def test_case_result_serializes_required_evidence_fields_and_schema(packet):
    case = next(item for item in packet.answerability_cases if item["expected_response_class"] == "MUST_ANSWER")
    output = asyncio.run(run_mock_validation(packet))
    result = next(item for item in output["results"] if item["case_id"] == case["case_id"])
    schema = json.loads((SCHEMA_ROOT / "d4_slice3b_case_result.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(result)
    assert result["expected"]["response_class"]
    assert "response_class" in result["actual"]
    assert "safety_route" in result["actual"]
    assert "retrieved_chunk_ids" in result["retrieval_evidence"]
    assert "cited_chunk_ids" in result["citations"]
    assert result["claims"]
    assert result["claims"][0]["textual_support"] == "PENDING_HUMAN_REVIEW"
    assert result["claims"][0]["population_applicability"] == "PENDING_HUMAN_REVIEW"
    assert result["citations"]["cited_source_chunk_ids"] == list(case["required_evidence_ids"])
    assert result["utility"]["required_evidence_retrieved"] is True
    assert "false_refusal" in result["utility"]
    assert "used" in result["fallback"]
    assert result["runtime_identity"]["expected"]["digest"] == EXPECTED_RUNTIME_IDENTITY["digest"]


@pytest.mark.parametrize("schema_name", [
    "d4_slice3b_case_manifest.schema.json",
    "d4_slice3b_approved_corpus.schema.json",
    "d4_slice3b_run_manifest.schema.json",
    "d4_runtime_preflight.schema.json",
    "d4_slice3b_summary.schema.json",
])
def test_d4_slice3b_json_schemas_are_well_formed(schema_name):
    schema = json.loads((SCHEMA_ROOT / schema_name).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
