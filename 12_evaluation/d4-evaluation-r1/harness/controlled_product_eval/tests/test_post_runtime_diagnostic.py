from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from harness.controlled_product_eval.post_runtime_diagnostic import (
    BACKEND_DETAIL_CODE_BY_EXACT_VALUE,
    INDETERMINATE,
    UNMAPPED_SAFE_DETAIL,
    project_post_runtime_diagnostic,
    project_runtime_candidate,
)
from harness.controlled_product_eval.smoke_product import _smoke_scenario_plan
from harness.controlled_product_eval.runner import CanonicalHttpTransport
from harness.controlled_product_eval.observer_proxy import _safe_response_summary


REQUEST_ID = "REQ_D4SMOKE_0123456789abcdef0123456789abcdef"
TRACE_ID = "TRACE_D4SMOKE_0123456789abcdef0123456789abcdef"
DIAGNOSTIC_SCHEMA = (
    Path(__file__).resolve().parents[3]
    / "spec"
    / "d4_post_runtime_502_diagnostic_record.schema.json"
)


@pytest.mark.parametrize(
    ("detail", "expected_code"),
    list(BACKEND_DETAIL_CODE_BY_EXACT_VALUE.items()),
)
def test_exact_backend_details_project_to_bounded_codes(detail, expected_code):
    projected = project_post_runtime_diagnostic(
        http_status=502,
        response_body={"type": "about:blank", "status": 502, "detail": detail},
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        runtime_events=[
            {
                "request_id": REQUEST_ID,
                "trace_id": TRACE_ID,
                "status_code": 200,
                "response_summary": {"candidate_parse_status": "NOT_OBSERVED"},
            }
        ],
        safety_events=[],
    )

    assert projected["detail_projection_code"] == expected_code
    assert projected["primary_classification"] == expected_code
    assert projected["runtime_http_status"] == 200
    assert detail not in json.dumps(projected)
    schema = json.loads(DIAGNOSTIC_SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(projected)


def test_legacy_error_message_is_exactly_allowlisted_and_unknown_text_is_discarded():
    known_detail, known_code = next(iter(BACKEND_DETAIL_CODE_BY_EXACT_VALUE.items()))
    known = project_post_runtime_diagnostic(
        http_status=502,
        response_body={"error": {"message": known_detail}},
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        runtime_events=[{"request_id": REQUEST_ID, "trace_id": TRACE_ID, "status_code": 200}],
        safety_events=[],
    )
    unknown_detail = "PRIVATE_DETAIL_SENTINEL"
    unknown = project_post_runtime_diagnostic(
        http_status=502,
        response_body={"detail": unknown_detail},
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        runtime_events=[{"request_id": REQUEST_ID, "trace_id": TRACE_ID, "status_code": 200}],
        safety_events=[],
    )

    assert known["detail_projection_code"] == known_code
    assert unknown["detail_projection_code"] == UNMAPPED_SAFE_DETAIL
    assert unknown["primary_classification"] == INDETERMINATE
    assert unknown_detail not in json.dumps(unknown)


def test_conflicting_detail_fields_fail_closed_to_unmapped():
    projected = project_post_runtime_diagnostic(
        http_status=502,
        response_body={"detail": "known", "error": {"message": "different"}},
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        runtime_events=[{"request_id": REQUEST_ID, "trace_id": TRACE_ID, "status_code": 200}],
        safety_events=[],
    )

    assert projected["detail_projection_code"] == UNMAPPED_SAFE_DETAIL
    assert projected["primary_classification"] == INDETERMINATE


def test_output_safety_and_candidate_projection_are_correlated_and_bounded():
    candidate = {
        "summary": "synthetic summary",
        "observations": ["synthetic observation"],
        "suggestions": [{"text": "synthetic suggestion", "source_chunk_ids": ["CHUNK_SYNTHETIC_1"]}],
        "disclaimer": "synthetic disclaimer",
    }
    raw_text = json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))
    candidate_projection = project_runtime_candidate({"data": {"text": raw_text}})
    projected = project_post_runtime_diagnostic(
        http_status=502,
        response_body={"detail": "Safety returned an invalid decision"},
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        runtime_events=[
            {
                "request_id": REQUEST_ID,
                "trace_id": TRACE_ID,
                "status_code": 200,
                "response_summary": candidate_projection,
            }
        ],
        safety_events=[
            {
                "request_id": REQUEST_ID,
                "trace_id": TRACE_ID,
                "stage": "OUTPUT",
                "status_code": 200,
                "action": None,
                "reason_codes": ["SAFE_REASON_SENTINEL"],
            }
        ],
    )

    assert candidate_projection["candidate_text_length_chars"] == len(raw_text)
    assert candidate_projection["candidate_text_sha256"] == "sha256:" + hashlib.sha256(raw_text.encode()).hexdigest()
    assert candidate_projection["candidate_parse_status"] == "VALID_GENERATION_CONTENT"
    assert candidate_projection["source_chunk_ids"] == ["CHUNK_SYNTHETIC_1"]
    assert projected["primary_classification"] == "OUTPUT_SAFETY_DECISION_INVALID"
    assert projected["output_safety_request_issued"] is True
    assert projected["output_safety_http_status"] == 200
    assert projected["output_safety_action"] is None
    assert projected["output_safety_reason_codes"] == []
    serialized = json.dumps({"candidate": candidate_projection, "diagnostic": projected}, ensure_ascii=False)
    assert raw_text not in serialized
    assert "synthetic suggestion" not in serialized
    assert "SAFE_REASON_SENTINEL" not in serialized


def test_invalid_candidate_records_parse_status_without_text_or_chunk_ids():
    raw_text = "PRIVATE_CANDIDATE_SENTINEL"
    projected = project_runtime_candidate({"data": {"text": raw_text}})

    assert projected["candidate_parse_status"] == "INVALID_JSON"
    assert projected["candidate_text_length_chars"] == len(raw_text)
    assert projected["source_chunk_ids"] == []
    assert raw_text not in json.dumps(projected)


def test_runtime_observer_summary_never_persists_candidate_text():
    raw_text = json.dumps(
        {
            "summary": "PRIVATE_CANDIDATE_SENTINEL",
            "observations": [],
            "suggestions": [{"text": "private suggestion", "source_chunk_ids": ["CHUNK_SAFE_1"]}],
            "disclaimer": "synthetic disclaimer",
        },
        ensure_ascii=False,
    )
    summary = _safe_response_summary(
        "llm",
        {"data": {"text": raw_text, "trace": {"runtime_version": "test"}}},
        {},
    )

    assert summary["candidate_text_length_chars"] == len(raw_text)
    assert summary["candidate_parse_status"] == "VALID_GENERATION_CONTENT"
    assert summary["source_chunk_ids"] == ["CHUNK_SAFE_1"]
    assert raw_text not in json.dumps(summary)
    assert "PRIVATE_CANDIDATE_SENTINEL" not in json.dumps(summary)
    assert "private suggestion" not in json.dumps(summary)


def test_runtime_observer_reports_parse_status_when_response_is_not_json():
    summary = _safe_response_summary("llm", None, {})

    assert summary == {
        "candidate_text_length_chars": None,
        "candidate_text_sha256": None,
        "candidate_parse_status": "RUNTIME_RESPONSE_INVALID",
        "source_chunk_ids": [],
    }


def test_diagnostic_scenario_plan_contains_only_case_a():
    cases = _smoke_scenario_plan(
        normal_corpus={"chunk_id": "CHUNK_A"},
        zero_corpus=None,
        diagnostic_only=True,
    )

    assert len(cases) == 1
    assert cases[0][0:2] == ("normal", "NORMAL_EVIDENCE_PATH")


def test_diagnostic_preparation_creates_exactly_one_assessment(monkeypatch):
    transport = object.__new__(CanonicalHttpTransport)
    transport._prepared = False
    transport._smoke_assessment_ids = []
    transport._last_completed_assessment = None
    transport._prepared_assessment = None
    created = []

    async def login_gate():
        return {}

    async def create_assessment(username, case_key):
        created.append((username, case_key))
        transport._last_completed_assessment = {"assessment_id": "ASSESS_D4SMOKE_A"}
        return "ASSESS_D4SMOKE_A"

    monkeypatch.setattr(transport, "login_gate", login_gate)
    monkeypatch.setattr(transport, "_create_assessment", create_assessment)
    asyncio.run(transport.prepare_nonformal_diagnostic())

    assert created == [("student_b", "D4SMOKE_DIAGNOSTIC_A")]
    assert transport._smoke_assessment_ids == ["ASSESS_D4SMOKE_A"]
    assert transport._prepared is True
