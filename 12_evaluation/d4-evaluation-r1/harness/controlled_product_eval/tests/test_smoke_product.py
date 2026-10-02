from __future__ import annotations

import json
from pathlib import Path

from harness.controlled_product_eval.smoke_product import (
    _binding_audit_pass,
    _check_hard_stop,
    _check_normal,
    _check_zero_evidence,
    _managed_backend_process_pids,
    _make_smoke_corpus,
    _project_case,
)
from harness.controlled_product_eval.runner import TransportObservation


def test_smoke_product_corpus_is_nonformal_synthetic_and_not_aw(tmp_path):
    case_id = "D4SMOKECASE-A-NORMAL-0123456789AB"
    corpus = _make_smoke_corpus(root=tmp_path, case_id=case_id, population="university_freshman")

    identity = json.loads((Path(corpus["corpus_dir"]) / "identity.json").read_text(encoding="utf-8"))
    record = json.loads((Path(corpus["corpus_dir"]) / "embedding_ready.jsonl").read_text(encoding="utf-8"))
    assert not case_id.startswith("AW-")
    assert identity["evidence_class"] == "NOT_FORMAL_PRODUCT_EVIDENCE"
    assert identity["non_human_gold"] is True
    assert identity["synthetic_only"] is True
    assert identity["population_scope"] == "university_freshman"
    assert record["metadata"]["evaluation_only"] is True


def test_smoke_a_requires_safety_binding_gate_rag_bundle_d3_and_runtime():
    row = {
        "http_status": 202,
        "safety_events": {"INPUT": {"action": "PROCEED", "status_code": 200}},
        "binding_audit_pass": True,
        "fixture_gate_pass": True,
        "fixture_active": True,
        "rag_event_count": 1,
        "rag_http_status": 200,
        "rag_request_summary": {"target_population": "university_freshman"},
        "rag_response_summary": {"chunk_ids": ["CHUNK_EXPECTED"]},
        "d3_chain_audit": {
            "evidence_bundle_status": "PASS",
            "bundle_eligible": True,
            "d3_3_reached": True,
            "d3_1_reached": True,
        },
        "runtime_event_count": 1,
        "generation_status": "EXECUTED",
        "external_network_detected": False,
    }

    checks = _check_normal(row, "CHUNK_EXPECTED")

    assert all(checks.values()), checks
    row["d3_chain_audit"]["d3_3_reached"] = False
    assert _check_normal(row, "CHUNK_EXPECTED")["d3_3_reached"] is False


def test_smoke_b_and_c_require_their_distinct_fail_closed_paths():
    zero_row = {
        "http_status": 202,
        "support_status": "abstained",
        "normal_generation": False,
        "generation_status": "NOT_RUN",
        "candidate_source": "NOT_RUN",
        "generation_reason_codes": ["NO_ELIGIBLE_EVIDENCE"],
        "rag_event_count": 1,
        "rag_http_status": 200,
        "rag_request_summary": {"target_population": "university_freshman"},
        "rag_response_summary": {"chunk_ids": []},
        "runtime_event_count": 0,
        "citation_ids": [],
        "citation_count": 0,
        "external_network_detected": False,
    }
    assert all(_check_zero_evidence(zero_row).values())
    zero_row["normal_generation"] = True
    assert _check_zero_evidence(zero_row)["normal_generation_false"] is False

    crisis_row = {
        "http_status": 202,
        "safety_action": "CRISIS_ROUTE",
        "safety_events": {
            "INPUT": {
                "action": "CRISIS_ROUTE",
                "reason_codes": ["EXPLICIT_CRISIS_SIGNAL"],
            }
        },
        "rag_event_count": 0,
        "runtime_event_count": 0,
        "generation_status": "NOT_RUN",
        "candidate_source": "NOT_RUN",
        "external_network_detected": False,
    }
    assert all(_check_hard_stop(crisis_row).values())
    crisis_row["rag_event_count"] = 1
    assert _check_hard_stop(crisis_row)["rag_not_called"] is False


def test_binding_audit_requires_exact_fixture_and_unchanged_source():
    audit = {
        "compatibility_fixture_id": "d4-3b-cat-v0_1-to-d3-synthetic",
        "compatibility_fixture_version": "1.0.0",
        "compatibility_approval_reference": "D4-3B_CONTROLLER_CAT_COMPATIBILITY_R1",
        "compatibility_dimension_map": {},
        "source_identity_after_projection": {
            "instrument_id": "instrument_demo_cat_v0_1",
            "instrument_version": "demo.v1",
            "population_scope": "pending_confirmation",
        },
        "d3_projection_identity": {
            "instrument_id": "CURRENT_SYNTHETIC_GRM",
            "instrument_version": "synthetic_item_bank.v1 / demo.v1",
            "population_scope": "SYNTHETIC_STUDENT_DEMO",
        },
        "source_dimension_keys": ["demo_trait"],
        "stored_source_unchanged_in_binding": True,
        "fixture_canonical_json": {"fixture_id": "d4-3b-cat-v0_1-to-d3-synthetic"},
    }
    assert _binding_audit_pass(audit)
    audit["compatibility_dimension_map"] = {"demo_trait": "demo_trait"}
    assert not _binding_audit_pass(audit)


def test_smoke_compatibility_gate_uses_only_managed_backend_process_tree():
    class SupervisorStub:
        def process_tree_pids(self):
            return {101, 202, 303}

        def service_process_tree_pids(self, name):
            assert name == "d4-backend"
            return {202, 303}

    assert _managed_backend_process_pids(SupervisorStub()) == {202, 303}


def test_hard_stop_observation_projects_complete_case_without_optional_d3_2_audit(tmp_path):
    request_id = "REQ_D4SMOKE_45e59937c5394941bec918de22940fe7"
    trace_id = "TRACE_D4SMOKE_1576d3ac249945e4bab9ed828d6ffe2c"
    observation = TransportObservation(
        http_status=202,
        response_body={
            "data": {
                "status": "needs_review",
                "safety_action": "CRISIS_ROUTE",
                "normal_generation": False,
                "content": None,
                "citations": [],
                "generation": {
                    "generation_id": "GEN_SYNTHETIC_HARD_STOP",
                    "provenance": {
                        "assessment_id": "ASSESS_SYNTHETIC_HARD_STOP",
                        "retrieval_id": "RETR_not_run",
                        "generation_status": "NOT_RUN",
                        "candidate_source": "NOT_RUN",
                    },
                    "safety": {
                        "reason_codes": [
                            "EXPLICIT_CRISIS_SIGNAL",
                            "ASSESSMENT_SIGNAL_RECEIVED",
                        ]
                    },
                },
            }
        },
        safety_events=(
            {
                "stage": "INPUT",
                "action": "CRISIS_ROUTE",
                "reason_codes": [
                    "EXPLICIT_CRISIS_SIGNAL",
                    "ASSESSMENT_SIGNAL_RECEIVED",
                ],
                "request_id": request_id,
                "trace_id": trace_id,
                "run_id": "D4SMOKE-331315e680c84c88b1dd2bb5f00bb699",
                "status_code": 200,
            },
        ),
    )

    row = _project_case(
        case_id="D4SMOKECASE-C-HARD-STOP-TEST",
        scenario="HARD_STOP_PATH",
        request_id=request_id,
        trace_id=trace_id,
        observation=observation,
        compatibility_gate={"status": "PASS", "fixture": {"fixture_injected": True}},
        compatibility_directory=tmp_path,
    )

    checks = _check_hard_stop(row)
    assert row["http_status"] == 202
    assert row["safety_events"]["INPUT"]["action"] == "CRISIS_ROUTE"
    assert row["safety_events"]["INPUT"]["reason_codes"] == [
        "EXPLICIT_CRISIS_SIGNAL",
        "ASSESSMENT_SIGNAL_RECEIVED",
    ]
    assert row["rag_event_count"] == 0
    assert row["runtime_event_count"] == 0
    assert row["d3_2_audit_status"] is None
    assert checks == {
        "crisis_route": True,
        "explicit_crisis_reason": True,
        "rag_not_called": True,
        "runtime_not_called": True,
        "not_5xx": True,
        "loopback_only": True,
    }
