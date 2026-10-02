from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone

import jsonschema
import pytest

from harness.controlled_product_eval.approved_packet import load_approved_packet
from harness.controlled_product_eval.error_projection import response_stage
from harness.controlled_product_eval.manifest import (
    ACCEPTED_D4_3A_COMMIT,
    EXPECTED_RUNTIME_IDENTITY,
    PROFILE_SOURCE_COPY_COMMIT,
    git_snapshot,
)
from harness.controlled_product_eval.results import aggregate_results, build_case_result
from harness.controlled_product_eval.manifest import build_runtime_preflight
from harness.controlled_product_eval.runtime_audit import (
    RuntimeAuditError,
    capture_runtime_audit_snapshot,
    runtime_audit_pre_case_issues,
    write_runtime_audit_snapshot,
)
from harness.controlled_product_eval.runner import (
    _error_audit_artifact_ref,
    _write_case_result,
    _write_error_audit_record,
)
from harness.controlled_product_eval.secret_scan import scan_secret_artifacts
from harness.controlled_product_eval.summary_hash import canonical_summary_hash, canonical_summary_json
from harness.controlled_product_eval.service_profiles import build_profile_source_identity_record


EVALUATION_ROOT = Path(__file__).resolve().parents[3]
PACKET = load_approved_packet(EVALUATION_ROOT / "D4_3A_HUMAN_GOLD_REVIEW_PACKET.json")
CASE_SCHEMA = json.loads(
    (EVALUATION_ROOT / "spec" / "d4_slice3b_case_result.schema.json").read_text(encoding="utf-8")
)


def _unknown_case_result(response_body: dict[str, object]) -> dict[str, object]:
    case = next(item for item in PACKET.answerability_cases if item["expected_response_class"] == "MUST_ANSWER")
    request_id = "REQ_D4RUN-AUDIT-CASE"
    trace_id = "TRACE_D4RUN-AUDIT-CASE"
    return build_case_result(
        packet=PACKET,
        case=case,
        run_id="D4RUN-AUDIT-CASE",
        http_status=409,
        response_body=response_body,
        request_id=request_id,
        trace_id=trace_id,
        rag_events=(),
        llm_events=(),
    )


def test_known_conflict_code_is_projected_without_changing_unknown_semantics():
    request_id = "REQ_D4RUN-AUDIT-CASE"
    trace_id = "TRACE_D4RUN-AUDIT-CASE"
    result = _unknown_case_result(
        {
            "request_id": request_id,
            "trace_id": trace_id,
            "error": {
                "code": "WORKFLOW_CONFLICT",
                "message": "free-form conflict text is not retained",
                "retryable": False,
            },
        }
    )

    assert result["actual"]["http_status"] == 409
    assert result["actual"]["response_class"] == "UNKNOWN"
    assert any(item["code"] == "UNKNOWN_SEVERITY" for item in result["findings"])
    assert result["normalized_error_evidence"] == {
        "http_status": 409,
        "error_code_present": True,
        "error_code_projected": True,
        "error_code": "WORKFLOW_CONFLICT",
        "error_category": "WORKFLOW_CONFLICT",
        "retryable": False,
        "request_id": request_id,
        "trace_id": trace_id,
        "response_request_id_match": True,
        "response_trace_id_match": True,
        "response_stage": "UNKNOWN",
    }
    jsonschema.Draft202012Validator(CASE_SCHEMA).validate(result)


def test_unknown_error_code_is_not_retained():
    result = _unknown_case_result(
        {
            "request_id": "REQ_D4RUN-AUDIT-CASE",
            "trace_id": "TRACE_D4RUN-AUDIT-CASE",
            "error": {
                "code": "TOKEN_SENTINEL_UNKNOWN_CODE",
                "message": "FREE_TEXT_SENTINEL",
                "retryable": True,
            },
        }
    )

    projected = result["normalized_error_evidence"]
    assert projected["error_code_present"] is True
    assert projected["error_code_projected"] is False
    assert projected["error_code"] is None
    assert projected["error_category"] == "UNKNOWN_ALLOWED_PROJECTION"
    assert "TOKEN_SENTINEL_UNKNOWN_CODE" not in json.dumps(result)
    assert "FREE_TEXT_SENTINEL" not in json.dumps(result)
    jsonschema.Draft202012Validator(CASE_SCHEMA).validate(result)


@pytest.mark.parametrize(
    ("safety_action", "safety_correlated", "rag_events", "llm_events", "expected"),
    [
        (None, False, (), (), "UNKNOWN"),
        ("REVIEW_REQUIRED", True, (), (), "AFTER_SAFETY"),
        ("REVIEW_REQUIRED", False, (), (), "UNKNOWN"),
        (None, False, ({"trace_id": "TRACE_MATCH"},), (), "AFTER_RAG"),
        (None, False, (), ({"trace_id": "TRACE_MATCH"},), "AFTER_RUNTIME"),
        (None, False, ({"trace_id": "TRACE_OTHER"},), (), "UNKNOWN"),
    ],
)
def test_response_stage_uses_only_positive_correlated_evidence(
    safety_action, safety_correlated, rag_events, llm_events, expected
):
    assert (
        response_stage(
            trace_id="TRACE_MATCH",
            safety_action=safety_action,
            safety_correlated=safety_correlated,
            rag_events=rag_events,
            llm_events=llm_events,
        )
        == expected
    )


def test_unmatched_response_safety_action_does_not_advance_stage():
    result = _unknown_case_result(
        {
            "request_id": "REQ_OTHER",
            "trace_id": "TRACE_OTHER",
            "data": {"safety_action": "REVIEW_REQUIRED"},
            "error": {"code": "WORKFLOW_CONFLICT", "retryable": False},
        }
    )
    assert result["normalized_error_evidence"]["response_stage"] == "UNKNOWN"
    assert result["normalized_error_evidence"]["response_request_id_match"] is False
    assert result["normalized_error_evidence"]["response_trace_id_match"] is False


def test_plaintext_error_sentinels_do_not_reach_artifacts_summary_logs_or_jsonl(tmp_path):
    markers = {
        "password": "PASSWORD_SENTINEL",
        "token": "TOKEN_SENTINEL_UNKNOWN_CODE",
        "credential": "CREDENTIAL_SENTINEL",
        "database_url": "mysql://synthetic:" + "DATABASE_URL_SENTINEL" + "@127.0.0.1:3307/evaluation",
        "free_text": "FREE_TEXT_SENTINEL",
    }
    result = _unknown_case_result(
        {
            "request_id": "REQ_D4RUN-AUDIT-CASE",
            "trace_id": "TRACE_D4RUN-AUDIT-CASE",
            "type": "urn:smhai:problem:" + markers["credential"],
            "detail": markers["free_text"],
            "error": {
                "code": markers["token"],
                "message": "password=" + markers["password"] + "; token=" + markers["token"],
                "retryable": False,
                "credential": markers["credential"],
                "database_url": markers["database_url"],
            },
            "errors": [{"message": markers["free_text"]}],
        }
    )
    summary = aggregate_results([result])
    audit = {
        "run_id": result["run_id"],
        "case_id": result["case_id"],
        "normalized_error_evidence": result["normalized_error_evidence"],
    }
    log_record = {
        "event": "request_completed",
        "case_id": result["case_id"],
        "http_status": result["actual"]["http_status"],
        "response_class": result["actual"]["response_class"],
    }

    run_dir = tmp_path / "D4RUN-AUDIT-CASE"
    logs_dir = run_dir / "logs"
    events_dir = run_dir / "events"
    run_dir.mkdir()
    logs_dir.mkdir()
    events_dir.mkdir()
    _write_case_result(run_dir, result)
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    (logs_dir / "backend.log").write_text(json.dumps(log_record), encoding="utf-8")
    assert _write_error_audit_record(run_dir, result, create=True)
    audit_reference = _error_audit_artifact_ref(run_dir)
    assert audit_reference["line_count"] == 1
    audit_path = run_dir / str(audit_reference["path"])
    audit_lines = audit_path.read_text(encoding="utf-8").splitlines()
    assert len(audit_lines) == 1
    audit_schema = json.loads(
        (EVALUATION_ROOT / "spec" / "d4_slice3b_error_audit.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(audit_schema).validate(json.loads(audit_lines[0]))
    (events_dir / "rag.jsonl").write_text("", encoding="utf-8")
    (events_dir / "llm.jsonl").write_text("", encoding="utf-8")

    scan = scan_secret_artifacts(run_dir, markers.values())
    assert scan["status"] == "PASS"
    assert scan["plaintext_occurrences"] == 0
    for path in run_dir.rglob("*"):
        if path.is_file():
            encoded = path.read_bytes()
            assert all(marker.encode("utf-8") not in encoded for marker in markers.values())


def test_older_case_and_summary_artifacts_remain_schema_readable():
    result = _unknown_case_result(
        {
            "request_id": "REQ_D4RUN-AUDIT-CASE",
            "trace_id": "TRACE_D4RUN-AUDIT-CASE",
            "error": {"code": "WORKFLOW_CONFLICT", "message": "not retained", "retryable": False},
        }
    )
    legacy_case = dict(result)
    legacy_case.pop("normalized_error_evidence")
    jsonschema.Draft202012Validator(CASE_SCHEMA).validate(legacy_case)

    summary_schema = json.loads(
        (EVALUATION_ROOT / "spec" / "d4_slice3b_summary.schema.json").read_text(encoding="utf-8")
    )
    legacy_summary = aggregate_results([legacy_case])
    legacy_summary.pop("error_evidence_summary")
    jsonschema.Draft202012Validator(summary_schema).validate(legacy_summary)


def test_summary_hash_normalizes_integer_and_string_keys_and_round_trips(tmp_path):
    integer_keys = {
        "listener_map": {8180: 1001, 11437: 1002},
        "unicode": "运行时证据",
        "array": [1, "two", None],
    }
    string_keys = {
        "listener_map": {"11437": 1002, "8180": 1001},
        "array": [1, "two", None],
        "unicode": "运行时证据",
    }
    assert canonical_summary_hash(integer_keys) == canonical_summary_hash(string_keys)
    assert canonical_summary_json(integer_keys) == (
        '{"array":[1,"two",null],"listener_map":{"11437":1002,"8180":1001},"unicode":"运行时证据"}'
    )
    assert canonical_summary_json(string_keys) == canonical_summary_json(integer_keys)

    stored = dict(integer_keys)
    stored["run_summary_hash"] = canonical_summary_hash(stored)
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["run_summary_hash"] == canonical_summary_hash(loaded)


def test_summary_hash_rejects_colliding_json_key_normalization():
    with pytest.raises(ValueError, match="collide"):
        canonical_summary_hash({"listener_map": {8180: 1, "8180": 2}})


def test_profile_identity_separates_evaluation_baseline_and_copy_commits():
    repository_root = Path(__file__).resolve().parents[5]
    identity = build_profile_source_identity_record(
        repo_root=repository_root,
        attempt_id="D4SUP-IDENTITY-TEST",
        formal_port_preflight_status="PASS",
        services={"runtime": {"source_tree_sha256": "a" * 64}},
    )
    expected_evaluation_commit = git_snapshot(repository_root)["git_commit"]

    assert identity["evaluation_source_commit"] == expected_evaluation_commit
    assert identity["accepted_product_baseline_commit"] == ACCEPTED_D4_3A_COMMIT
    assert identity["profile_source_copy_commit"] == PROFILE_SOURCE_COPY_COMMIT
    assert identity["evaluation_source_commit"] != identity["accepted_product_baseline_commit"]
    assert "accepted_source_commit" not in identity

    schema = json.loads(
        (EVALUATION_ROOT / "spec" / "d4_service_profile_identities.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema).validate(identity)
    legacy = dict(identity)
    for field in (
        "evaluation_source_commit",
        "accepted_product_baseline_commit",
        "profile_source_copy_commit",
    ):
        legacy.pop(field)
    legacy["accepted_source_commit"] = PROFILE_SOURCE_COPY_COMMIT
    jsonschema.Draft202012Validator(schema).validate(legacy)


def _runtime_audit_inputs(tmp_path: Path):
    run_id = "D4RUN-RUNTIME-AUDIT-TEST"
    stamp = "2026-10-02T00:00:00Z"
    runtime_pid = 20832
    launcher_pid = 10976
    ollama_pid = 11576
    binding = {
        "schema_version": "d4-runtime-live-attestation.v1",
        "attempt_id": run_id,
        "observed_at": stamp,
        "runtime_pid": runtime_pid,
        "runtime_process_tree_pids": [launcher_pid, runtime_pid],
        "runtime_started_at": stamp,
        "runtime_executable": str(Path(sys.executable).resolve()),
        "runtime_executable_sha256": "a" * 64,
        "runtime_launcher_pid": launcher_pid,
        "runtime_launcher_started_at": stamp,
        "runtime_launcher_executable": str(Path(sys.executable).resolve()),
        "runtime_launcher_executable_sha256": "e" * 64,
        "runtime_source_tree_sha256": "b" * 64,
        "runtime_endpoint": "http://127.0.0.1:8160",
        "ollama_pid": ollama_pid,
        "ollama_process_tree_pids": [ollama_pid],
        "ollama_started_at": stamp,
        "ollama_executable": str(Path(sys.executable).resolve()),
        "ollama_executable_sha256": "c" * 64,
        "provider_endpoint": "http://127.0.0.1:11437",
        "ollama_version": "0.33.3",
        "model": "qwen2.5:7b-instruct-q4_K_M",
        "model_digest": "845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e",
        "num_ctx": 8192,
        "kv_cache_type": "f16",
        "num_parallel": 1,
        "max_loaded_models": 1,
        "output_budget": 768,
        "cloud_fallback": False,
        "network_status": "PASS",
        "network_observation": "OBSERVED_LOOPBACK_ONLY",
        "external_established_connection_count": 0,
        "forbidden_endpoint_connection_count": 0,
        "verified_listener_pids": {
            "3307": 2200,
            "8160": runtime_pid,
            "8180": 4400,
            "8181": 5500,
            "8190": 6600,
            "11437": ollama_pid,
        },
        "network_observation_sha256": "d" * 64,
    }
    preflight = build_runtime_preflight(observed_at=stamp, execution_binding=binding)
    log_root = tmp_path / "managed-services" / "attempt" / "logs"
    log_root.mkdir(parents=True)
    runtime_stdout = log_root / "runtime.stdout.log"
    runtime_stderr = log_root / "runtime.stderr.log"
    ollama_stdout = log_root / "ollama.stdout.log"
    ollama_stderr = log_root / "ollama.stderr.log"
    for path, value in (
        (runtime_stdout, "runtime ready\n"),
        (runtime_stderr, ""),
        (ollama_stdout, "ollama ready\n"),
        (ollama_stderr, ""),
    ):
        path.write_text(value, encoding="utf-8")
    identity = {
        "owner": "D4_EVALUATION_HARNESS",
        "runtime_process_owned": True,
        "services": [
            {
                "name": "d4-runtime",
                "pid": launcher_pid,
                "log_path": str(runtime_stdout),
                "stderr_log_path": str(runtime_stderr),
            },
            {
                "name": "d4-ollama",
                "pid": ollama_pid,
                "log_path": str(ollama_stdout),
                "stderr_log_path": str(ollama_stderr),
            },
        ],
    }
    return run_id, preflight, identity, tmp_path


def test_runtime_audit_binds_run_processes_accepted_api_model_logs_and_gpu(tmp_path):
    run_id, preflight, identity, evidence_root = _runtime_audit_inputs(tmp_path)
    requested_urls: list[str] = []
    model_name = "qwen2.5:7b-instruct-q4_K_M"
    digest = "845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e"

    def get_json(url: str):
        requested_urls.append(url)
        if url.endswith("/api/version"):
            return {"version": "0.33.3"}
        if url.endswith("/api/tags"):
            return {
                "models": [
                    {"name": model_name, "digest": digest},
                    {"name": "unrelated-model", "digest": "f" * 64},
                ]
            }
        if url.endswith("/api/ps"):
            return {"models": [{"name": model_name, "digest": digest, "size_vram": 9_000_000_000}]}
        raise AssertionError("unexpected Runtime endpoint")

    def command_runner(arguments, *, timeout):
        if "--query-gpu" in arguments[1]:
            output = "NVIDIA GeForce RTX 3060, GPU-TEST, 12288, 9000, 3288\n"
        else:
            output = "11576, ollama.exe, 8500\n"
        return subprocess.CompletedProcess(arguments, 0, output, "")

    snapshot = capture_runtime_audit_snapshot(
        run_id=run_id,
        phase="BEFORE_CASES",
        runtime_preflight=preflight,
        managed_service_identity=identity,
        evidence_root=evidence_root,
        captured_at="2026-10-02T00:01:00Z",
        get_json=get_json,
        command_runner=command_runner,
        which=lambda _name: "nvidia-smi.exe",
    )

    assert requested_urls == [
        "http://127.0.0.1:11437/api/version",
        "http://127.0.0.1:11437/api/tags",
        "http://127.0.0.1:11437/api/ps",
    ]
    assert all("11434" not in url for url in requested_urls)
    assert snapshot["run_id"] == run_id
    assert snapshot["phase"] == "BEFORE_CASES"
    assert snapshot["runtime"]["pid"] == 20832
    assert snapshot["ollama"]["pid"] == 11576
    assert snapshot["ollama"]["api_status"] == "PASS"
    assert snapshot["ollama"]["catalog_status"] == "PASS"
    assert snapshot["ollama"]["running_model_status"] == "LOADED"
    assert snapshot["ollama"]["running_model_count"] == 1
    assert snapshot["ollama"]["running_models"] == [
        {"name": model_name, "digest": digest, "size_vram_bytes": 9_000_000_000}
    ]
    assert snapshot["gpu"]["ollama_process_visible"] is True
    assert snapshot["gpu"]["ollama_compute_processes"][0]["pid"] == 11576
    assert snapshot["runtime"]["stdout_log"]["status"] == "CAPTURED"
    assert runtime_audit_pre_case_issues(snapshot, run_id=run_id) == ()
    schema = json.loads(
        (EVALUATION_ROOT / "spec" / "d4_runtime_audit_evidence.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema).validate(snapshot)
    missing_ollama_stderr = json.loads(json.dumps(snapshot))
    missing_ollama_stderr["ollama"]["stderr_log"]["status"] = "UNAVAILABLE"
    assert "OLLAMA_PROCESS_LOGS_NOT_CAPTURED" in runtime_audit_pre_case_issues(
        missing_ollama_stderr, run_id=run_id
    )

    path = tmp_path / "D4RUN-RUNTIME-AUDIT-TEST" / "runtime-audit-before-cases.json"
    written, digest_ref = write_runtime_audit_snapshot(path, snapshot)
    assert written == path
    assert digest_ref.startswith("sha256:")
    assert json.loads(path.read_text(encoding="utf-8"))["run_id"] == run_id


def test_runtime_audit_marks_gpu_unavailable_without_accessing_other_ollama_ports(tmp_path):
    run_id, preflight, identity, evidence_root = _runtime_audit_inputs(tmp_path)
    requested_urls: list[str] = []

    def get_json(url: str):
        requested_urls.append(url)
        if url.endswith("/api/version"):
            return {"version": "0.33.3"}
        if url.endswith("/api/tags"):
            return {
                "models": [
                    {
                        "name": "qwen2.5:7b-instruct-q4_K_M",
                        "digest": "845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e",
                    }
                ]
            }
        return {"models": []}

    snapshot = capture_runtime_audit_snapshot(
        run_id=run_id,
        phase="AFTER_CASES",
        runtime_preflight=preflight,
        managed_service_identity=identity,
        evidence_root=evidence_root,
        get_json=get_json,
        which=lambda _name: None,
    )
    assert snapshot["gpu"]["status"] == "COMMAND_UNAVAILABLE"
    assert snapshot["ollama"]["running_model_status"] == "NOT_LOADED"
    assert all(url.startswith("http://127.0.0.1:11437/") for url in requested_urls)
    assert all("11434" not in url for url in requested_urls)


def test_runtime_audit_refuses_mismatched_run_binding(tmp_path):
    run_id, preflight, identity, evidence_root = _runtime_audit_inputs(tmp_path)
    with pytest.raises(RuntimeAuditError, match="run ID"):
        capture_runtime_audit_snapshot(
            run_id="D4RUN-DIFFERENT",
            phase="BEFORE_CASES",
            runtime_preflight=preflight,
            managed_service_identity=identity,
            evidence_root=evidence_root,
            get_json=lambda _url: pytest.fail("must not contact an endpoint"),
            which=lambda _name: None,
        )


@pytest.mark.parametrize(
    ("catalog_digest", "running_models", "expected_issue"),
    [
        ("0" * 64, [{"name": EXPECTED_RUNTIME_IDENTITY["model"], "digest": EXPECTED_RUNTIME_IDENTITY["digest"]}], "OLLAMA_API_OR_MODEL_IDENTITY_NOT_PASS"),
        (EXPECTED_RUNTIME_IDENTITY["digest"], [], "OLLAMA_RUNNING_MODEL_IDENTITY_NOT_PASS"),
        (EXPECTED_RUNTIME_IDENTITY["digest"], [{"name": EXPECTED_RUNTIME_IDENTITY["model"], "digest": "0" * 64}], "OLLAMA_RUNNING_MODEL_IDENTITY_NOT_PASS"),
        (EXPECTED_RUNTIME_IDENTITY["digest"], [{"name": EXPECTED_RUNTIME_IDENTITY["model"]}], "OLLAMA_RUNNING_MODEL_IDENTITY_NOT_PASS"),
    ],
)
def test_runtime_audit_pre_case_gate_rejects_missing_or_mismatched_model_identity(
    tmp_path, catalog_digest, running_models, expected_issue
):
    run_id, preflight, identity, evidence_root = _runtime_audit_inputs(tmp_path)

    def get_json(url: str):
        if url.endswith("/api/version"):
            return {"version": "0.33.3"}
        if url.endswith("/api/tags"):
            return {"models": [{"name": "qwen2.5:7b-instruct-q4_K_M", "digest": catalog_digest}]}
        return {"models": running_models}

    snapshot = capture_runtime_audit_snapshot(
        run_id=run_id,
        phase="BEFORE_CASES",
        runtime_preflight=preflight,
        managed_service_identity=identity,
        evidence_root=evidence_root,
        get_json=get_json,
        which=lambda _name: None,
    )
    assert expected_issue in runtime_audit_pre_case_issues(snapshot, run_id=run_id)
