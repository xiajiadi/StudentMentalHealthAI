from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from structlog.contextvars import bind_contextvars, clear_contextvars, get_contextvars
from structlog.testing import capture_logs

from smhai_backend.core.config import BackendSettings
from smhai_backend.core.errors import BackendError
from smhai_backend.core.request_context import RequestContext
from smhai_backend.domains.models import Actor, AssessmentRecord, BackendRole, ReportRecord
from smhai_backend.domains.support import service as support_service_module
from smhai_backend.domains.support.schemas import GenerationContent, SupportRequest
from smhai_backend.integrations.d3 import adapt_legacy_retrieval, default_fixture_config
from smhai_backend.integrations.llm import CandidateResponse
from smhai_backend.integrations.rag import ContractFakeRagClient, RetrievalResult

_ASSESSMENT_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "03_assessment-adapter"
    / "fixtures"
    / "synthetic_assessment.v1.json"
)


def _exact_assessment() -> dict[str, Any]:
    return json.loads(_ASSESSMENT_FIXTURE.read_text(encoding="utf-8"))


def _install_exact_assessment(app) -> dict[str, Any]:
    assessment = _exact_assessment()
    app.state.container.assessments_repo.save(
        AssessmentRecord(
            assessment_id=assessment["assessment_id"],
            subject_id=assessment["subject_id"],
            assessment=copy.deepcopy(assessment),
        )
    )
    # The in-memory test user is deliberately rebound to this synthetic fixture;
    # production identity still comes from the verified session actor.
    app.state.container.users.get_by_username("student_a").subject_id = assessment["subject_id"]
    return assessment


async def _login_fixture(client, app) -> str:
    _install_exact_assessment(app)
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "student_a", "password": "synthetic-student-a"},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["csrf_token"]


def _support_payload(assessment_id: str, message: str) -> dict[str, str]:
    return {
        "assessment_id": assessment_id,
        "target_role": "student",
        "message": message,
        "language": "zh-CN",
    }


def _install_m0_observer_assessment(app) -> AssessmentRecord:
    assessment = _exact_assessment()
    assessment["assessment_id"] = "ASSESS_m0_semantic_observer"
    assessment["subject_id"] = "SUBJ_demo_a"
    assessment["instrument"] = {
        "instrument_id": "CURRENT_SYNTHETIC_GRM",
        "version": "synthetic_item_bank.v1 / demo.v1",
    }
    assessment["status"] = "completed"
    assessment["provenance"]["item_bank_version"] = "demo.v1"
    record = AssessmentRecord(
        assessment_id=assessment["assessment_id"],
        subject_id=assessment["subject_id"],
        assessment=copy.deepcopy(assessment),
        cat_item_bank_version="demo.v1",
        data_origin="SYNTHETIC",
    )
    app.state.container.assessments_repo.save(record)
    app.state.container.users.get_by_username("student_a").subject_id = "SUBJ_demo_a"
    return record


@pytest.mark.asyncio
async def test_legacy_retrieval_compatibility_preserves_observed_chunk_and_trace() -> None:
    retrieval = await ContractFakeRagClient().retrieve(
        assessment={},
        target_role="student",
        query="synthetic scope",
        top_k=2,
        trace_id="TRACE_scope",
        request_id="REQ_scope",
    )
    original_scope = [tuple(chunk.population_scope) for chunk in retrieval.chunks]
    original_trace = retrieval.trace

    adapted = adapt_legacy_retrieval(retrieval, config=default_fixture_config())

    assert adapted is retrieval
    assert [tuple(chunk.population_scope) for chunk in adapted.chunks] == original_scope
    assert adapted.trace == original_trace


@pytest.mark.asyncio
async def test_support_route_runs_bound_d3_chain_once_and_persists_after_output_safety(
    client, app, monkeypatch
) -> None:
    assessment = _install_exact_assessment(app)
    runtime_prompts: list[str] = []
    llm = app.state.container.llm
    llm_type = type(llm)
    original_generate = llm_type.generate

    async def capture_prompt(self, **kwargs):
        runtime_prompts.append(kwargs["prompt"])
        return await original_generate(self, **kwargs)

    monkeypatch.setattr(llm_type, "generate", capture_prompt)
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "student_a", "password": "synthetic-student-a"},
    )
    csrf = response.json()["data"]["csrf_token"]

    response = await client.post(
        "/api/v1/support/requests",
        headers={"X-CSRF-Token": csrf},
        json=_support_payload(assessment["assessment_id"], "normal synthetic support"),
    )

    assert response.status_code == 202, response.text
    body = response.json()["data"]
    assert body["status"] == "generated"
    assert body["generation"]["provenance"]["prompt_id"] == "PROMPT_student_synthetic_v1"
    assert body["generation"]["provenance"]["prompt_version"] == "1.1.0"
    assert len(runtime_prompts) == 1
    assert "summary: provide an education-support summary only" in runtime_prompts[0]
    assert "disclaimer: put the non-diagnostic boundary here" in runtime_prompts[0]
    assert app.state.container.rag.calls == 1
    assert app.state.container.llm.calls == 1
    assert app.state.container.support.call_order[-3:] == [
        "safety_retrieval",
        "llm",
        "safety_output",
    ]
    assert app.state.container.support.d3_call_order[-3:] == [
        "d3_2",
        "d3_3",
        "d3_1",
    ]
    call_order = app.state.container.support.call_order
    assert app.state.container.support.d3_call_order.count("d3_2") == 1
    assert call_order.count("d3_2") == 1
    assert call_order.index("d3_2") < call_order.index("rag")

    ledger = app.state.container.support.stage_ledgers[body["trace_id"]]
    snapshot = ledger.snapshot()
    assert snapshot.state.value == "COMPLETED"
    assert snapshot.stages[-3:] == (
        "GENERATION_BUFFERED",
        "OUTPUT_SAFETY_EVALUATED",
        "PERSISTED",
    )
    support_events = [
        event for event in app.state.container.audits.list() if event.event == "SUPPORT_REQUESTED"
    ]
    assert support_events
    metadata = support_events[-1].metadata
    assert len(metadata["bundle_hash"]) == 64
    assert "normal synthetic support" not in json.dumps(metadata, ensure_ascii=False)


@pytest.mark.asyncio
async def test_report_list_is_subject_scoped_and_returns_summary_only(client, app, monkeypatch):
    assert app.openapi()["paths"]["/api/v1/reports"]["get"]["operationId"] == "listReports"
    assessment = _install_exact_assessment(app)
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"username": "student_a", "password": "synthetic-student-a"},
    )
    assert login_response.status_code == 200
    report = ReportRecord(
        report_id="REPORT_history_demo",
        assessment_id=assessment["assessment_id"],
        subject_id=assessment["subject_id"],
        generation_id="GEN_history_demo",
        status="generated",
        generation={
            "created_at": "2026-10-07T00:00:00Z",
            "content": {"summary": "must not appear in a history row"},
        },
        safety_action="PROCEED",
        citations=[{"citation_id": "CITE_history_demo"}],
    )
    app.state.container.reports.save(report)
    observed: dict[str, Any] = {}

    async def list_for_subjects(subject_ids, *, assessment_id=None, limit=100):
        observed.update(subject_ids=set(subject_ids), assessment_id=assessment_id, limit=limit)
        return [report] if report.subject_id in subject_ids else []

    monkeypatch.setattr(
        app.state.container.reports, "list_for_subjects", list_for_subjects, raising=False
    )
    response = await client.get(
        f"/api/v1/reports?assessment_id={assessment['assessment_id']}&limit=25"
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert observed == {
        "subject_ids": {assessment["subject_id"]},
        "assessment_id": assessment["assessment_id"],
        "limit": 25,
    }
    assert data == {
        "items": [
            {
                "report_id": report.report_id,
                "assessment_id": report.assessment_id,
                "status": "generated",
                "safety_action": "PROCEED",
                "created_at": "2026-10-07T00:00:00Z",
                "citation_count": 1,
            }
        ],
        "next_cursor": None,
    }
    assert "content" not in json.dumps(data, ensure_ascii=False)


@pytest.mark.asyncio
async def test_real_http_freshman_taxonomy_passes_evidence_and_d3_seams(client, app, monkeypatch):
    assessment = _install_exact_assessment(app)
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"username": "student_a", "password": "synthetic-student-a"},
    )
    csrf = login_response.json()["data"]["csrf_token"]
    rag = app.state.container.rag
    fake_retrieval = await rag.retrieve(
        assessment=assessment,
        target_role="student",
        query="seed",
        top_k=2,
        trace_id="TRACE_real_http_seed",
    )
    mapped_retrieval = RetrievalResult(
        "RETR_university_freshman",
        tuple(
            chunk.model_copy(update={"population_scope": ["university_freshman"]})
            for chunk in fake_retrieval.chunks
        ),
        "REAL_HTTP",
    )

    async def mapped_retrieve(self, **_kwargs):
        self.calls += 1
        self.call_order.append("rag")
        return mapped_retrieval

    monkeypatch.setattr(type(rag), "retrieve", mapped_retrieve)
    response = await client.post(
        "/api/v1/support/requests",
        headers={"X-CSRF-Token": csrf},
        json=_support_payload(assessment["assessment_id"], "synthetic mapped normal request"),
    )

    assert response.status_code == 202, response.text
    body = response.json()["data"]
    assert body["status"] == "generated"
    assert app.state.container.llm.calls == 1
    assert app.state.container.support.d3_call_order == ["d3_2", "d3_3", "d3_1"]
    support_events = [
        event
        for event in app.state.container.audits.list()
        if event.event == "SUPPORT_REQUESTED" and event.trace_id == body["trace_id"]
    ]
    metadata = support_events[-1].metadata
    assert (
        metadata["content_population_mapping_id"] == "MAP_UNIVERSITY_FRESHMAN_SUPPORT_TO_RAG_D3_V1"
    )
    assert metadata["content_population_mapping_version"] == "1.0.0"
    assert metadata["content_population"] == "UNIVERSITY_FRESHMEN_SYNTHETIC_DEMO"


@pytest.mark.asyncio
async def test_support_normal_side_effect_order_runs_d3_2_before_rag_once(client, app, monkeypatch):
    assessment = _install_exact_assessment(app)
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"username": "student_a", "password": "synthetic-student-a"},
    )
    csrf = login_response.json()["data"]["csrf_token"]
    events: list[str] = []

    original_interpret = support_service_module.interpret_d3_chain

    def record_interpret(*args, **kwargs):
        events.append("d3_2")
        return original_interpret(*args, **kwargs)

    rag_type = type(app.state.container.rag)
    original_retrieve = rag_type.retrieve

    async def record_retrieve(self, *args, **kwargs):
        events.append("rag")
        return await original_retrieve(self, *args, **kwargs)

    original_bundle = support_service_module.build_retrieval_evidence_bundle

    def record_bundle(*args, **kwargs):
        events.append("evidence_bundle")
        return original_bundle(*args, **kwargs)

    original_compose = support_service_module.compose_d3_chain

    def record_compose(*args, **kwargs):
        events.append("d3_3")
        result = original_compose(*args, **kwargs)
        events.append("d3_1")
        return result

    llm_type = type(app.state.container.llm)
    original_generate = llm_type.generate

    async def record_generate(self, *args, **kwargs):
        events.append("runtime")
        return await original_generate(self, *args, **kwargs)

    monkeypatch.setattr(support_service_module, "interpret_d3_chain", record_interpret)
    monkeypatch.setattr(rag_type, "retrieve", record_retrieve)
    monkeypatch.setattr(support_service_module, "build_retrieval_evidence_bundle", record_bundle)
    monkeypatch.setattr(support_service_module, "compose_d3_chain", record_compose)
    monkeypatch.setattr(llm_type, "generate", record_generate)

    response = await client.post(
        "/api/v1/support/requests",
        headers={"X-CSRF-Token": csrf},
        json=_support_payload(assessment["assessment_id"], "normal synthetic support"),
    )

    assert response.status_code == 202, response.text
    assert response.json()["data"]["status"] == "generated"
    assert events == ["d3_2", "rag", "evidence_bundle", "d3_3", "d3_1", "runtime"]
    assert app.state.container.support.d3_call_order[-3:] == ["d3_2", "d3_3", "d3_1"]
    assert app.state.container.support.d3_call_order.count("d3_2") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "action"),
    [
        ("SYNTHETIC_CRISIS_SIGNAL", "CRISIS_ROUTE"),
        ("SYNTHETIC_REVIEW", "REVIEW_REQUIRED"),
        ("SYNTHETIC_BLOCK", "BLOCK"),
    ],
)
async def test_input_safety_stop_has_zero_normal_downstream_calls(
    client, app, message: str, action: str
) -> None:
    assessment = _install_exact_assessment(app)
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "student_a", "password": "synthetic-student-a"},
    )
    csrf = response.json()["data"]["csrf_token"]

    response = await client.post(
        "/api/v1/support/requests",
        headers={"X-CSRF-Token": csrf},
        json=_support_payload(assessment["assessment_id"], message),
    )

    assert response.status_code == 202, response.text
    body = response.json()["data"]
    assert body["safety_action"] == action
    assert body["generation"]["provenance"]["generation_status"] == "NOT_RUN"
    if action == "CRISIS_ROUTE":
        assert "EXPLICIT_CRISIS_SIGNAL" in body["generation"]["safety"]["reason_codes"]
        assert body["normal_generation"] is False
    assert app.state.container.rag.calls == 0
    assert app.state.container.llm.calls == 0
    ledger = app.state.container.support.stage_ledgers[body["trace_id"]]
    snapshot = ledger.snapshot()
    assert snapshot.state.value == "ABORTED"
    assert [stage.value for stage in snapshot.stages] == [
        "REQUEST_AUTHENTICATED",
        "REQUEST_AUTHORIZED",
        "INPUT_SAFETY_EVALUATED",
    ]


@pytest.mark.asyncio
async def test_zero_evidence_success_is_persisted_as_deterministic_abstention(
    client, app, monkeypatch
) -> None:
    assessment = _install_exact_assessment(app)
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"username": "student_a", "password": "synthetic-student-a"},
    )
    csrf = login_response.json()["data"]["csrf_token"]
    rag = app.state.container.rag

    async def empty_retrieval(self, **_kwargs):
        self.calls += 1
        self.call_order.append("rag")
        return RetrievalResult("RETR_no_evidence", (), "REAL_HTTP")

    monkeypatch.setattr(type(rag), "retrieve", empty_retrieval)
    response = await client.post(
        "/api/v1/support/requests",
        headers={"X-CSRF-Token": csrf},
        json=_support_payload(assessment["assessment_id"], "synthetic no evidence case"),
    )

    assert response.status_code == 202, response.text
    body = response.json()["data"]
    assert body["status"] == "abstained"
    assert body["safety_action"] == "PROCEED"
    assert body["normal_generation"] is False
    assert body["content"] is None
    assert body["citations"] == []
    assert body["generation"]["status"] == "requested"
    assert body["generation"]["safety"]["reason_codes"] == ["NO_ELIGIBLE_EVIDENCE"]
    assert body["generation"]["provenance"]["generation_status"] == "NOT_RUN"
    assert body["generation"]["provenance"]["candidate_source"] == "NOT_RUN"
    assert app.state.container.rag.calls == 1
    assert app.state.container.llm.calls == 0
    assert "safety_output" not in app.state.container.support.call_order
    assert app.state.container.support.d3_call_order == ["d3_2"]

    ledger = app.state.container.support.stage_ledgers[body["trace_id"]]
    snapshot = ledger.snapshot()
    assert snapshot.state.value == "ABSTAINED"
    assert snapshot.terminal_action == "ABSTAINED"
    assert snapshot.terminal_reason == "NO_ELIGIBLE_EVIDENCE"
    assert [stage.value for stage in snapshot.stages][-1] == "RETRIEVAL_BOUND"
    report = app.state.container.reports.get(body["report_id"])
    assert report is not None
    assert report.status == "abstained"
    assert report.candidate_source == "NOT_RUN"
    assert report.citations == []

    audit = [
        event
        for event in app.state.container.audits.list()
        if event.event == "SUPPORT_REQUESTED" and event.trace_id == body["trace_id"]
    ]
    assert audit[-1].metadata["abstention_reason_code"] == "NO_ELIGIBLE_EVIDENCE"
    assert audit[-1].metadata["support_status"] == "abstained"


@pytest.mark.asyncio
async def test_nonempty_k12_evidence_remains_fail_closed(client, app, monkeypatch) -> None:
    assessment = _install_exact_assessment(app)
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"username": "student_a", "password": "synthetic-student-a"},
    )
    csrf = login_response.json()["data"]["csrf_token"]
    rag = app.state.container.rag
    valid_fake = await rag.retrieve(
        assessment=assessment,
        target_role="student",
        query="seed",
        top_k=1,
        trace_id="TRACE_k12_seed",
    )
    k12_chunk = valid_fake.chunks[0].model_copy(update={"population_scope": ["k12"]})

    async def k12_retrieval(self, **_kwargs):
        self.calls += 1
        self.call_order.append("rag")
        return RetrievalResult("RETR_k12_ineligible", (k12_chunk,), "REAL_HTTP")

    monkeypatch.setattr(type(rag), "retrieve", k12_retrieval)
    response = await client.post(
        "/api/v1/support/requests",
        headers={"X-CSRF-Token": csrf},
        json=_support_payload(assessment["assessment_id"], "synthetic K12 mismatch case"),
    )

    assert response.status_code == 502, response.text
    assert response.json()["error"]["code"] == "DEPENDENCY_INVALID_RESPONSE"
    assert app.state.container.llm.calls == 0
    assert app.state.container.support.d3_call_order == ["d3_2"]


@pytest.mark.asyncio
async def test_generation_route_rejects_idor_and_ignores_forged_authority_fields(
    client, app
) -> None:
    assessment = _install_exact_assessment(app)
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "student_a", "password": "synthetic-student-a"},
    )
    csrf = response.json()["data"]["csrf_token"]
    headers = {"X-CSRF-Token": csrf}
    base = {
        "schema_version": "generation.v1",
        "generation_id": "GEN_d3_route_test_001",
        "assessment_id": assessment["assessment_id"],
        "target_role": "student",
        "purpose": "education_support",
        "language": "zh-CN",
        "safety_mode": "standard",
        "retrieval": {"retrieval_id": "RETR_forged", "chunk_ids": ["CHUNK_forged"]},
        "prompt_ref": {"prompt_id": "PROMPT_forged", "prompt_version": "9.9.9"},
        "model_policy": {"model_id": "MODEL_forged", "provider_class": "local"},
    }

    idor = await client.post(
        "/api/v1/generations",
        headers=headers,
        json={**base, "subject_id": "SUBJ_other"},
    )
    assert idor.status_code == 403, idor.text
    assert app.state.container.rag.calls == 0
    assert app.state.container.llm.calls == 0

    valid = await client.post(
        "/api/v1/generations",
        headers=headers,
        json={**base, "subject_id": assessment["subject_id"]},
    )
    assert valid.status_code == 202, valid.text
    generated = valid.json()["data"]
    assert generated["status"] == "generated"
    assert generated["provenance"]["retrieval_id"] != "RETR_forged"
    assert generated["provenance"]["prompt_id"] == "PROMPT_student_synthetic_v1"
    assert generated["provenance"]["model_id"] == "MODEL_backend_fake"
    assert app.state.container.rag.calls == 1
    assert app.state.container.llm.calls == 1


@pytest.mark.asyncio
async def test_output_safety_stops_before_normal_report_persistence(client, app) -> None:
    assessment = _install_exact_assessment(app)
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "student_a", "password": "synthetic-student-a"},
    )
    csrf = response.json()["data"]["csrf_token"]

    response = await client.post(
        "/api/v1/support/requests",
        headers={"X-CSRF-Token": csrf},
        json=_support_payload(assessment["assessment_id"], "SYNTHETIC_UNSAFE_OUTPUT"),
    )

    assert response.status_code == 202, response.text
    body = response.json()["data"]
    assert body["status"] == "needs_review"
    assert body["normal_generation"] is False
    assert body["content"] is None
    report = app.state.container.reports.get(body["report_id"])
    assert report is not None
    assert report.status == "needs_review"
    assert report.generation["provenance"]["generation_status"] == "EXECUTED"
    assert app.state.container.llm.calls == 1
    ledger = app.state.container.support.stage_ledgers[body["trace_id"]]
    snapshot = ledger.snapshot()
    assert snapshot.state.value == "ABORTED"
    assert snapshot.current.value == "OUTPUT_SAFETY_EVALUATED"
    assert "PERSISTED" not in [stage.value for stage in snapshot.stages]


@pytest.mark.asyncio
async def test_direct_retrieval_is_safety_and_evidence_bound(client, app) -> None:
    assessment = _install_exact_assessment(app)
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "student_a", "password": "synthetic-student-a"},
    )
    csrf = response.json()["data"]["csrf_token"]

    response = await client.post(
        "/api/v1/retrievals",
        headers={"X-CSRF-Token": csrf},
        json={
            "assessment_id": assessment["assessment_id"],
            "target_role": "student",
            "query": "direct retrieval route",
            "top_k": 5,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["chunks"]
    assert app.state.container.rag.calls == 1
    assert app.state.container.llm.calls == 0
    ledger = app.state.container.support.stage_ledgers[response.json()["trace_id"]]
    assert [stage.value for stage in ledger.snapshot().stages] == [
        "REQUEST_AUTHENTICATED",
        "REQUEST_AUTHORIZED",
        "INPUT_SAFETY_EVALUATED",
        "ASSESSMENT_BOUND",
    ]


@pytest.mark.asyncio
async def test_admin_report_read_is_coarse_and_contains_no_generation_or_citations(app) -> None:
    report = ReportRecord(
        report_id="REPORT_admin_boundary",
        assessment_id="ASSESS_admin_boundary",
        subject_id="SUBJ_demo_a",
        generation_id="GEN_admin_boundary",
        status="generated",
        generation={"content": {"summary": "private psychological generation"}},
        citations=[{"citation_id": "CITE_private", "chunk_id": "CHUNK_private"}],
    )
    app.state.container.reports.save(report)
    admin = Actor(
        user_id="USER_admin",
        username="admin",
        role=BackendRole.ADMIN,
        subject_id=None,
        accessible_subject_ids=frozenset({"SUBJ_demo_a"}),
    )

    projection = await app.state.container.support.report_for_actor(admin, report.report_id)

    assert projection.status == "generated"
    assert projection.generation == {}
    assert projection.citations == []


@pytest.mark.asyncio
async def test_admin_report_http_projection_does_not_include_generated_content(client, app) -> None:
    report = ReportRecord(
        report_id="REPORT_admin_http_boundary",
        assessment_id="ASSESS_admin_http_boundary",
        subject_id="SUBJ_demo_a",
        generation_id="GEN_admin_http_boundary",
        status="generated",
        generation={"content": {"summary": "private psychological generation"}},
        citations=[{"citation_id": "CITE_private", "chunk_id": "CHUNK_private"}],
    )
    app.state.container.reports.save(report)
    admin = Actor(
        user_id="USER_admin_http",
        username="admin",
        role=BackendRole.ADMIN,
        subject_id=None,
        accessible_subject_ids=frozenset({"SUBJ_demo_a"}),
    )

    from smhai_backend.domains.auth.dependencies import current_actor

    async def admin_dependency():
        return admin

    app.dependency_overrides[current_actor] = admin_dependency
    try:
        response = await client.get(f"/api/v1/reports/{report.report_id}")
    finally:
        app.dependency_overrides.pop(current_actor, None)

    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["status"] == "generated"
    assert body["generation"] is None
    assert body["citations"] == []


@pytest.mark.asyncio
async def test_retrieval_safety_stop_has_no_raw_citations_and_aborts_ledger(
    client, app, monkeypatch
) -> None:
    assessment = _install_exact_assessment(app)
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "student_a", "password": "synthetic-student-a"},
    )
    csrf = response.json()["data"]["csrf_token"]

    safety_type = type(app.state.container.safety)

    async def block_retrieval(self, context, chunks, request_context):
        return self._decision("BLOCK", ["RETRIEVAL_BLOCKED"], request_context)

    monkeypatch.setattr(safety_type, "check_retrieval", block_retrieval)
    response = await client.post(
        "/api/v1/support/requests",
        headers={"X-CSRF-Token": csrf},
        json=_support_payload(assessment["assessment_id"], "retrieval stop"),
    )

    assert response.status_code == 202, response.text
    body = response.json()["data"]
    assert body["status"] == "needs_review"
    assert body["citations"] == []
    report = app.state.container.reports.get(body["report_id"])
    assert report is not None
    assert report.citations == []
    ledger = app.state.container.support.stage_ledgers[body["trace_id"]]
    snapshot = ledger.snapshot()
    assert snapshot.state.value == "ABORTED"
    assert snapshot.current.value == "INTERPRETATION_READY"


@pytest.mark.asyncio
async def test_in_memory_idempotency_claim_prevents_duplicate_generation(client, app) -> None:
    assessment = _install_exact_assessment(app)
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "student_a", "password": "synthetic-student-a"},
    )
    csrf = response.json()["data"]["csrf_token"]
    headers = {"X-CSRF-Token": csrf, "Idempotency-Key": "same-concurrent-support"}

    responses = await asyncio.gather(
        client.post(
            "/api/v1/support/requests",
            headers=headers,
            json=_support_payload(assessment["assessment_id"], "same key"),
        ),
        client.post(
            "/api/v1/support/requests",
            headers=headers,
            json=_support_payload(assessment["assessment_id"], "same key"),
        ),
    )

    assert all(response.status_code in {202, 409} for response in responses)
    successful = [response for response in responses if response.status_code == 202]
    assert successful
    assert len({response.json()["data"]["report_id"] for response in successful}) == 1
    assert len(app.state.container.reports._records) == 1
    assert app.state.container.rag.calls == 1
    assert app.state.container.llm.calls == 1


@pytest.mark.asyncio
async def test_schema_valid_measurement_claim_is_not_published_when_safety_proceeds(
    client, app, monkeypatch
) -> None:
    assessment = _install_exact_assessment(app)
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "student_a", "password": "synthetic-student-a"},
    )
    csrf = response.json()["data"]["csrf_token"]
    llm_type = type(app.state.container.llm)

    async def unsafe_candidate(self, **kwargs):
        return CandidateResponse(
            text=json.dumps(
                {
                    "summary": "theta indicates a diagnosis",
                    "observations": [],
                    "suggestions": [
                        {
                            "text": "Use the cited synthetic guidance.",
                            "source_chunk_ids": ["CHUNK_backend_0"],
                        }
                    ],
                    "disclaimer": "synthetic fixture",
                }
            ),
            model_id=kwargs["model_id"],
            model_version="1.0",
            runtime_version="test-unsafe",
            label="CONTRACT_FAKE",
        )

    monkeypatch.setattr(llm_type, "generate", unsafe_candidate)
    response = await client.post(
        "/api/v1/support/requests",
        headers={"X-CSRF-Token": csrf},
        json=_support_payload(assessment["assessment_id"], "normal"),
    )

    assert response.status_code == 502, response.text
    assert app.state.container.reports._records == {}
    trace_id = response.json()["trace_id"]
    snapshot = app.state.container.support.stage_ledgers[trace_id].snapshot()
    assert snapshot.state.value == "ABORTED"
    assert snapshot.current.value == "OUTPUT_SAFETY_EVALUATED"


def test_boundary_gate_keeps_lexical_behavior_for_negated_substantive_text() -> None:
    affirmative = GenerationContent(
        summary="Synthetic clinical diagnosis claim.",
        observations=[],
        suggestions=[],
        disclaimer="Synthetic fixture.",
    )
    negated_disclaimer = GenerationContent(
        summary="Synthetic education-support summary.",
        observations=["Synthetic observed study routine."],
        suggestions=[],
        disclaimer="This is not a diagnosis or clinical assessment.",
    )
    negated_observation = GenerationContent(
        summary="Synthetic education-support summary.",
        observations=["This is not a diagnosis or clinical assessment."],
        suggestions=[],
        disclaimer="Synthetic fixture.",
    )

    assert support_service_module._contains_forbidden_generated_claim(affirmative)
    assert not support_service_module._contains_forbidden_generated_claim(negated_disclaimer)
    # The gate remains a lexical guard: negation in a substantive field still matches.
    assert support_service_module._contains_forbidden_generated_claim(negated_observation)


@pytest.mark.parametrize(
    ("field", "text"),
    [
        ("summary", "The synthetic assessment confirms a diagnosis."),
        ("observations", "The synthetic assessment confirms a diagnosis."),
        ("suggestions", "The synthetic score proves the diagnosis."),
        ("disclaimer", "This is not a diagnosis or clinical assessment."),
        ("summary", "This is not a diagnosis or clinical assessment."),
        ("observations", "This is not a diagnosis or clinical assessment."),
        ("suggestions", "This is not a diagnosis; the score proves severity."),
        ("disclaimer", "This is not a diagnosis; the score proves severity."),
    ],
)
def test_boundary_gate_field_semantics_remain_lexical(field: str, text: str) -> None:
    values: dict[str, Any] = {
        "summary": "Synthetic education-support summary.",
        "observations": ["Synthetic observed study routine."],
        "suggestions": [
            {
                "text": "Synthetic actionable study suggestion.",
                "source_chunk_ids": ["CHUNK_synthetic_0"],
            }
        ],
        "disclaimer": "Synthetic demo scope.",
    }
    if field == "summary" or field == "disclaimer":
        values[field] = text
    elif field == "observations":
        values[field] = [text]
    else:
        values[field] = [{"text": text, "source_chunk_ids": ["CHUNK_synthetic_0"]}]
    content = GenerationContent.model_validate(values)

    assert support_service_module._contains_forbidden_generated_claim(content) is (
        field != "disclaimer"
    )


def test_m0_observer_scope_requires_default_off_and_server_owned_synthetic_provenance(
    monkeypatch,
) -> None:
    monkeypatch.delenv("SMHAI_M0_CLAIM_BOUNDARY_OBSERVER_ENABLED", raising=False)
    assert BackendSettings(_env_file=None).m0_claim_boundary_observer_enabled is False
    assessment = {
        "status": "completed",
        "instrument": {
            "instrument_id": "CURRENT_SYNTHETIC_GRM",
            "version": "synthetic_item_bank.v1 / demo.v1",
        },
        "provenance": {"item_bank_version": "demo.v1"},
    }
    record = AssessmentRecord(
        assessment_id="ASSESS_m0_scope_test",
        subject_id="SUBJ_demo_a",
        assessment=assessment,
        cat_item_bank_version="demo.v1",
        data_origin="SYNTHETIC",
    )
    actor = Actor(
        user_id="USER_m0_scope_test",
        username="student_a",
        role=BackendRole.STUDENT,
        subject_id="SUBJ_demo_a",
    )
    assert support_service_module._m0_semantic_observer_scope_allows(
        actor=actor,
        record=record,
        message=support_service_module._M0_SEMANTIC_OBSERVER_MESSAGE,
        environment="demo",
        host="127.0.0.1",
    )

    disallowed_contexts = [
        {"environment": "local", "host": "127.0.0.1"},
        {"environment": "demo", "host": "0.0.0.0"},
    ]
    for context in disallowed_contexts:
        assert not support_service_module._m0_semantic_observer_scope_allows(
            actor=actor,
            record=record,
            message=support_service_module._M0_SEMANTIC_OBSERVER_MESSAGE,
            **context,
        )

    assert not support_service_module._m0_semantic_observer_scope_allows(
        actor=Actor(
            user_id=actor.user_id,
            username="other_user",
            role=actor.role,
            subject_id=actor.subject_id,
        ),
        record=record,
        message=support_service_module._M0_SEMANTIC_OBSERVER_MESSAGE,
        environment="demo",
        host="127.0.0.1",
    )
    unsafe_record = copy.copy(record)
    unsafe_record.data_origin = "REAL"
    assert not support_service_module._m0_semantic_observer_scope_allows(
        actor=actor,
        record=unsafe_record,
        message=support_service_module._M0_SEMANTIC_OBSERVER_MESSAGE,
        environment="demo",
        host="127.0.0.1",
    )
    unsafe_record = copy.copy(record)
    unsafe_record.assessment = {**assessment, "status": "in_progress"}
    assert not support_service_module._m0_semantic_observer_scope_allows(
        actor=actor,
        record=unsafe_record,
        message=support_service_module._M0_SEMANTIC_OBSERVER_MESSAGE,
        environment="demo",
        host="127.0.0.1",
    )
    unsafe_record = copy.copy(record)
    unsafe_record.assessment = {
        **assessment,
        "instrument": {**assessment["instrument"], "version": "unapproved"},
    }
    assert not support_service_module._m0_semantic_observer_scope_allows(
        actor=actor,
        record=unsafe_record,
        message=support_service_module._M0_SEMANTIC_OBSERVER_MESSAGE,
        environment="demo",
        host="127.0.0.1",
    )
    unsafe_record = copy.copy(record)
    unsafe_record.cat_item_bank_version = "unapproved"
    assert not support_service_module._m0_semantic_observer_scope_allows(
        actor=actor,
        record=unsafe_record,
        message=support_service_module._M0_SEMANTIC_OBSERVER_MESSAGE,
        environment="demo",
        host="127.0.0.1",
    )
    assert not support_service_module._m0_semantic_observer_scope_allows(
        actor=actor,
        record=record,
        message="different synthetic request",
        environment="demo",
        host="127.0.0.1",
    )


@pytest.mark.asyncio
async def test_m0_semantic_observer_is_one_shot_and_keeps_gate_fail_closed(
    app, monkeypatch
) -> None:
    record = _install_m0_observer_assessment(app)
    support = app.state.container.support
    support._m0_claim_boundary_observer_enabled = True
    support._environment = "demo"
    support._host = "127.0.0.1"
    actor = app.state.container.users.get_by_username("student_a").actor()
    message = support_service_module._M0_SEMANTIC_OBSERVER_MESSAGE
    payload = SupportRequest.model_validate(_support_payload(record.assessment_id, message))
    context = RequestContext("REQ_m0_semantic_observer", "TRACE_m0_semantic_observer")
    candidate_text = json.dumps(
        {
            "summary": "This synthetic result is not a diagnosis; SENTINEL_CANDIDATE_TEXT.",
            "observations": [],
            "suggestions": [
                {
                    "text": "Use the cited synthetic study-planning guidance.",
                    "source_chunk_ids": ["CHUNK_backend_0"],
                }
            ],
            "disclaimer": "Synthetic demo scope.",
        }
    )
    generation_calls = 0

    async def forbidden_candidate(self, **kwargs):
        nonlocal generation_calls
        generation_calls += 1
        return CandidateResponse(
            text=candidate_text,
            model_id=kwargs["model_id"],
            model_version="diagnostic-test",
            runtime_version="diagnostic-test",
            label="CONTRACT_FAKE",
        )

    monkeypatch.setattr(type(app.state.container.llm), "generate", forbidden_candidate)
    with capture_logs() as captured:
        with pytest.raises(BackendError) as caught:
            await support.create(actor, payload, context=context)
        support._observe_m0_claim_boundary_rejection(
            actor=actor,
            record=record,
            message=message,
            request_id="REQ_m0_semantic_observer_second_call",
            trace_id="TRACE_m0_semantic_observer_second_call",
            generation_id="GEN_m0_semantic_observer_second_call",
            candidate_text=candidate_text,
            content=GenerationContent.model_validate_json(candidate_text),
        )

    assert caught.value.status_code == 502
    assert caught.value.code.value == "dependency_invalid_response"
    assert generation_calls == 1
    assert app.state.container.reports._records == {}
    events = [
        event
        for event in captured
        if event.get("event") == "support_generation_semantic_observation"
    ]
    assert len(events) == 1
    event = events[0]
    assert event["request_id"] == context.request_id
    assert event["trace_id"] == context.trace_id
    assert event["candidate_hash"] == hashlib.sha256(candidate_text.encode("utf-8")).hexdigest()
    assert event["matched_field"] == "SUMMARY"
    assert event["field_index"] == 0
    assert event["matched_category"] == "DIAGNOSIS"
    assert event["match_count"] == 1
    assert event["classification_method"] == "HEURISTIC_ONLY"
    assert event["semantic_classification"] == "INDETERMINATE"
    assert event["reviewer_acknowledgement"] == "NOT_REVIEWED"
    assert set(event).issubset(
        {
            "event",
            "log_level",
            "request_id",
            "trace_id",
            "generation_id",
            "candidate_hash",
            "matched_field",
            "field_index",
            "matched_category",
            "match_count",
            "classification_method",
            "semantic_classification",
            "reviewer_acknowledgement",
        }
    )
    assert "SENTINEL_CANDIDATE_TEXT" not in json.dumps(captured, ensure_ascii=False)
    assert candidate_text not in json.dumps(captured, ensure_ascii=False)


@pytest.mark.asyncio
async def test_m0_semantic_observer_failure_does_not_skip_claim_gate(app, monkeypatch) -> None:
    record = _install_m0_observer_assessment(app)
    support = app.state.container.support
    support._m0_claim_boundary_observer_enabled = True
    support._environment = "demo"
    support._host = "127.0.0.1"
    actor = app.state.container.users.get_by_username("student_a").actor()
    message = support_service_module._M0_SEMANTIC_OBSERVER_MESSAGE
    payload = SupportRequest.model_validate(_support_payload(record.assessment_id, message))
    context = RequestContext("REQ_m0_observer_failure", "TRACE_m0_observer_failure")

    async def forbidden_candidate(self, **kwargs):
        return CandidateResponse(
            text=json.dumps(
                {
                    "summary": "Synthetic diagnosis claim.",
                    "observations": [],
                    "suggestions": [],
                    "disclaimer": "Synthetic demo scope.",
                }
            ),
            model_id=kwargs["model_id"],
            model_version="diagnostic-test",
            runtime_version="diagnostic-test",
            label="CONTRACT_FAKE",
        )

    def observer_failure(**_kwargs):
        raise RuntimeError("synthetic observer diagnostic failure")

    monkeypatch.setattr(type(app.state.container.llm), "generate", forbidden_candidate)
    monkeypatch.setattr(
        support_service_module,
        "_log_m0_semantic_observation",
        observer_failure,
    )
    with pytest.raises(BackendError) as caught:
        await support.create(actor, payload, context=context)

    assert caught.value.status_code == 502
    assert caught.value.code.value == "dependency_invalid_response"
    assert "synthetic observer diagnostic failure" not in str(caught.value)
    assert app.state.container.reports._records == {}
    assert support.stage_ledgers[context.trace_id].snapshot().state.value == "ABORTED"


@pytest.mark.asyncio
async def test_boundary_rejection_emits_only_allowlisted_diagnostic_metadata(
    app, monkeypatch
) -> None:
    assessment = _install_exact_assessment(app)
    actor = app.state.container.users.get_by_username("student_a").actor()
    payload = SupportRequest.model_validate(
        _support_payload(assessment["assessment_id"], "USER_INPUT_SENTINEL")
    )
    context = RequestContext("REQ_boundary_diagnostic", "TRACE_boundary_diagnostic")
    candidate_text = json.dumps(
        {
            "summary": "Synthetic summary.",
            "observations": ["Synthetic observation.", "severity SENTINEL severity"],
            "suggestions": [
                {"text": "Synthetic suggestion.", "source_chunk_ids": ["CHUNK_backend_0"]}
            ],
            "disclaimer": "Synthetic fixture.",
        }
    )
    runtime_prompts: list[str] = []
    llm_type = type(app.state.container.llm)
    runtime_attempt_trace = {
        "trace_id": context.trace_id,
        "request_id": context.request_id,
        "requested_model": "qwen2.5-0.5b-engineering",
        "actual_model": "qwen2.5-0.5b-engineering",
        "hardware_profile": "CONSUMER_GPU",
        "attempt_count": 1,
        "retry_count": 0,
        "fallback_attempted": False,
        "fallback_count": 0,
        "prompt": "PRIVATE_PROMPT_SENTINEL",
        "candidate": "PRIVATE_CANDIDATE_SENTINEL",
    }

    async def forbidden_candidate(self, **kwargs):
        runtime_prompts.append(kwargs["prompt"])
        return CandidateResponse(
            text=candidate_text,
            model_id=kwargs["model_id"],
            model_version="diagnostic-test",
            runtime_version="diagnostic-test",
            label="CONTRACT_FAKE",
            runtime_trace=runtime_attempt_trace,
        )

    monkeypatch.setattr(llm_type, "generate", forbidden_candidate)
    clear_contextvars()
    bind_contextvars(route="ROUTE_CONTEXT_SENTINEL", private_context="PRIVATE_CONTEXT_SENTINEL")
    try:
        with capture_logs() as captured:
            with pytest.raises(BackendError) as caught:
                await app.state.container.support.create(actor, payload, context=context)
        restored_context = get_contextvars()
    finally:
        clear_contextvars()

    assert caught.value.status_code == 502
    assert caught.value.code.value == "dependency_invalid_response"
    assert (
        caught.value.detail
        == "LLM Runtime returned content outside the approved generation boundary"
    )
    assert restored_context == {
        "route": "ROUTE_CONTEXT_SENTINEL",
        "private_context": "PRIVATE_CONTEXT_SENTINEL",
    }
    assert app.state.container.reports._records == {}
    assert (
        app.state.container.support.stage_ledgers[context.trace_id].snapshot().state.value
        == "ABORTED"
    )
    failed_runs = [
        item
        for item in app.state.container.conversations.records
        if item.get("workflow") == "FAILED" and item.get("trace_id") == context.trace_id
    ]
    assert len(failed_runs) == 1
    assert failed_runs[0]["stage_diagnostics"]["runtime_attempt_count"] == 1
    assert failed_runs[0]["stage_diagnostics"]["runtime_retry_count"] == 0
    assert failed_runs[0]["stage_diagnostics"]["runtime_model_id"] == ("qwen2.5-0.5b-engineering")
    assert "PRIVATE_CANDIDATE_SENTINEL" not in json.dumps(failed_runs, ensure_ascii=False)
    assert "PRIVATE_PROMPT_SENTINEL" not in json.dumps(failed_runs, ensure_ascii=False)
    assert len(captured) == 1
    event = captured[0]
    assert event["event"] == "support_generation_boundary_rejected"
    assert event["request_id"] == context.request_id
    assert event["trace_id"] == context.trace_id
    assert event["generation_id"].startswith("GEN_")
    assert event["candidate_sha256"] == hashlib.sha256(candidate_text.encode("utf-8")).hexdigest()
    assert event["parse_status"] == "PARSED"
    assert event["output_safety_action"] == "PROCEED"
    assert event["boundary_check_code"] == "FORBIDDEN_GENERATED_CLAIM"
    assert event["field_kind"] == "OBSERVATION"
    assert event["field_index"] == 1
    assert event["matched_category"] == "SEVERITY"
    assert event["match_count"] == 2
    assert event["workflow_disposition"] == "FAILED_CLOSED_NO_REPORT"
    assert event["runtime_attempt_count"] == 1
    assert event["runtime_retry_count"] == 0
    assert event["runtime_requested_model_id"] == "qwen2.5-0.5b-engineering"
    assert event["runtime_model_id"] == "qwen2.5-0.5b-engineering"
    assert event["runtime_hardware_profile"] == "CONSUMER_GPU"
    assert event["runtime_fallback_attempted"] is False
    assert event["runtime_fallback_count"] == 0
    assert set(event).issubset(
        {
            "event",
            "log_level",
            "request_id",
            "trace_id",
            "generation_id",
            "candidate_sha256",
            "parse_status",
            "output_safety_action",
            "boundary_check_code",
            "field_kind",
            "field_index",
            "matched_category",
            "match_count",
            "workflow_disposition",
            "runtime_attempt_count",
            "runtime_retry_count",
            "runtime_requested_model_id",
            "runtime_model_id",
            "runtime_hardware_profile",
            "runtime_fallback_attempted",
            "runtime_fallback_count",
        }
    )
    serialized = json.dumps([event, str(caught.value)], ensure_ascii=False)
    for sentinel in (
        candidate_text,
        runtime_prompts[0],
        "USER_INPUT_SENTINEL",
        "ROUTE_CONTEXT_SENTINEL",
        "PRIVATE_CONTEXT_SENTINEL",
        "PRIVATE_PROMPT_SENTINEL",
        "PRIVATE_CANDIDATE_SENTINEL",
        "severity",
    ):
        assert sentinel not in serialized


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_point", ["calculation", "logging"])
async def test_boundary_diagnostic_failure_still_aborts_and_returns_502(
    app, monkeypatch, failure_point: str
) -> None:
    assessment = _install_exact_assessment(app)
    actor = app.state.container.users.get_by_username("student_a").actor()
    payload = SupportRequest.model_validate(
        _support_payload(assessment["assessment_id"], "safe synthetic input")
    )
    context = RequestContext("REQ_boundary_log_failure", "TRACE_boundary_log_failure")
    llm_type = type(app.state.container.llm)

    async def forbidden_candidate(self, **kwargs):
        return CandidateResponse(
            text=json.dumps(
                {
                    "summary": "clinical synthetic marker",
                    "observations": [],
                    "suggestions": [
                        {"text": "Synthetic suggestion.", "source_chunk_ids": ["CHUNK_backend_0"]}
                    ],
                    "disclaimer": "Synthetic fixture.",
                }
            ),
            model_id=kwargs["model_id"],
            model_version="diagnostic-test",
            runtime_version="diagnostic-test",
            label="CONTRACT_FAKE",
        )

    monkeypatch.setattr(llm_type, "generate", forbidden_candidate)
    if failure_point == "calculation":

        def fail_diagnostic_calculation(_content):
            raise RuntimeError("PRIVATE_DIAGNOSTIC_EXCEPTION_SENTINEL")

        monkeypatch.setattr(
            support_service_module,
            "_first_boundary_match",
            fail_diagnostic_calculation,
        )
    else:

        class BrokenLogger:
            def warning(self, *_args, **_kwargs):
                raise RuntimeError("PRIVATE_LOGGER_EXCEPTION_SENTINEL")

        monkeypatch.setattr(support_service_module, "logger", lambda: BrokenLogger())

    with pytest.raises(BackendError) as caught:
        await app.state.container.support.create(actor, payload, context=context)

    assert caught.value.status_code == 502
    assert caught.value.code.value == "dependency_invalid_response"
    assert (
        caught.value.detail
        == "LLM Runtime returned content outside the approved generation boundary"
    )
    assert app.state.container.reports._records == {}
    assert (
        app.state.container.support.stage_ledgers[context.trace_id].snapshot().state.value
        == "ABORTED"
    )
    assert "PRIVATE_DIAGNOSTIC_EXCEPTION_SENTINEL" not in str(caught.value)
    assert "PRIVATE_LOGGER_EXCEPTION_SENTINEL" not in str(caught.value)


@pytest.mark.asyncio
async def test_normal_and_crisis_direct_paths_do_not_emit_boundary_rejection(
    app, monkeypatch
) -> None:
    assessment = _install_exact_assessment(app)
    actor = app.state.container.users.get_by_username("student_a").actor()
    llm_type = type(app.state.container.llm)
    normal_payload = SupportRequest.model_validate(
        _support_payload(assessment["assessment_id"], "normal synthetic path")
    )
    normal_context = RequestContext("REQ_boundary_normal", "TRACE_boundary_normal")
    candidate = json.dumps(
        {
            "summary": "Synthetic educational support summary.",
            "observations": ["Synthetic observation."],
            "suggestions": [
                {"text": "Synthetic suggestion.", "source_chunk_ids": ["CHUNK_backend_0"]}
            ],
            "disclaimer": "Synthetic fixture.",
        }
    )

    async def normal_candidate(self, **kwargs):
        return CandidateResponse(
            text=candidate,
            model_id=kwargs["model_id"],
            model_version="diagnostic-test",
            runtime_version="diagnostic-test",
            label="CONTRACT_FAKE",
        )

    monkeypatch.setattr(llm_type, "generate", normal_candidate)
    with capture_logs() as normal_logs:
        normal_result = await app.state.container.support.create(
            actor, normal_payload, context=normal_context
        )
    assert normal_result.status == "generated"
    assert app.state.container.reports.get(normal_result.report_id) is not None
    assert not any(
        log.get("event") == "support_generation_boundary_rejected" for log in normal_logs
    )

    async def runtime_must_not_run(self, **_kwargs):
        raise AssertionError("crisis path must not call Runtime")

    monkeypatch.setattr(llm_type, "generate", runtime_must_not_run)
    crisis_payload = SupportRequest.model_validate(
        _support_payload(assessment["assessment_id"], "SYNTHETIC_CRISIS_SIGNAL")
    )
    crisis_context = RequestContext("REQ_boundary_crisis", "TRACE_boundary_crisis")
    with capture_logs() as crisis_logs:
        crisis_result = await app.state.container.support.create(
            actor, crisis_payload, context=crisis_context
        )
    assert crisis_result.safety_action == "CRISIS_ROUTE"
    assert crisis_result.normal_generation is False
    assert not any(
        log.get("event") == "support_generation_boundary_rejected" for log in crisis_logs
    )


@pytest.mark.asyncio
async def test_repeated_suggestion_evidence_is_aggregated_once_in_first_seen_order(
    client, app, monkeypatch
) -> None:
    assessment = _install_exact_assessment(app)
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "student_a", "password": "synthetic-student-a"},
    )
    csrf = response.json()["data"]["csrf_token"]
    source_ids = [
        ["CHUNK_backend_0", "CHUNK_backend_1"],
        ["CHUNK_backend_1", "CHUNK_backend_0"],
    ]
    candidate_text = json.dumps(
        {
            "summary": "这是合成教育支持摘要。",
            "observations": [],
            "suggestions": [
                {"text": "合成建议一。", "source_chunk_ids": source_ids[0]},
                {"text": "合成建议二。", "source_chunk_ids": source_ids[1]},
            ],
            "disclaimer": "这不是诊断或治疗建议。",
        },
        ensure_ascii=False,
    )
    llm_type = type(app.state.container.llm)

    async def repeated_evidence_candidate(self, **kwargs):
        return CandidateResponse(
            text=candidate_text,
            model_id=kwargs["model_id"],
            model_version="1.0",
            runtime_version="test-repeated-evidence",
            label="CONTRACT_FAKE",
        )

    monkeypatch.setattr(llm_type, "generate", repeated_evidence_candidate)
    response = await client.post(
        "/api/v1/support/requests",
        headers={"X-CSRF-Token": csrf},
        json=_support_payload(assessment["assessment_id"], "normal synthetic support"),
    )

    assert response.status_code == 202, response.text
    body = response.json()["data"]
    assert body["status"] == "generated"
    assert [item["chunk_id"] for item in body["citations"]] == [
        "CHUNK_backend_0",
        "CHUNK_backend_1",
    ]
    assert [item["rank"] for item in body["citations"]] == [1, 2]
    assert [
        item["source_chunk_ids"] for item in body["generation"]["content"]["suggestions"]
    ] == source_ids
    assert [item["source_chunk_ids"] for item in body["content"]["suggestions"]] == source_ids
    report = app.state.container.reports.get(body["report_id"])
    assert report is not None
    assert [
        item["source_chunk_ids"] for item in report.generation["content"]["suggestions"]
    ] == source_ids


@pytest.mark.asyncio
async def test_repeated_valid_citation_with_unknown_chunk_still_fails_closed(
    client, app, monkeypatch
) -> None:
    assessment = _install_exact_assessment(app)
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "student_a", "password": "synthetic-student-a"},
    )
    csrf = response.json()["data"]["csrf_token"]
    llm_type = type(app.state.container.llm)
    source_ids = ["CHUNK_backend_0", "CHUNK_not_in_bound_bundle"]
    candidate_text = json.dumps(
        {
            "summary": "这是合成教育支持摘要。",
            "observations": [],
            "suggestions": [
                {"text": "合成建议一。", "source_chunk_ids": [source_ids[0]]},
                {"text": "合成建议二。", "source_chunk_ids": [source_ids[0], source_ids[1]]},
            ],
            "disclaimer": "这不是诊断或治疗建议。",
        },
        ensure_ascii=False,
    )

    async def unknown_evidence_candidate(self, **kwargs):
        return CandidateResponse(
            text=candidate_text,
            model_id=kwargs["model_id"],
            model_version="1.0",
            runtime_version="test-unknown-evidence",
            label="CONTRACT_FAKE",
        )

    monkeypatch.setattr(llm_type, "generate", unknown_evidence_candidate)
    response = await client.post(
        "/api/v1/support/requests",
        headers={"X-CSRF-Token": csrf},
        json=_support_payload(assessment["assessment_id"], "normal synthetic support"),
    )

    assert response.status_code == 502, response.text
    assert response.json()["error"]["code"] == "DEPENDENCY_INVALID_RESPONSE"
    assert app.state.container.reports._records == {}
    assert app.state.container.llm.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_point", ["metadata", "audit", "workflow"])
async def test_normal_generation_side_effect_failure_leaves_no_report_record(
    app, monkeypatch, failure_point: str
) -> None:
    assessment = _install_exact_assessment(app)
    actor = app.state.container.users.get_by_username("student_a").actor()
    payload = SupportRequest.model_validate(
        _support_payload(assessment["assessment_id"], "side effect failure")
    )
    context = RequestContext("REQ_side_effect", f"TRACE_side_effect_{failure_point}")

    def fail_sync(*args, **kwargs):
        raise RuntimeError(f"synthetic {failure_point} failure")

    async def fail_async(*args, **kwargs):
        raise RuntimeError(f"synthetic {failure_point} failure")

    if failure_point == "metadata":
        monkeypatch.setattr(type(app.state.container.conversations), "save_metadata", fail_sync)
    elif failure_point == "workflow":
        monkeypatch.setattr(type(app.state.container.conversations), "complete_workflow", fail_sync)
    else:
        monkeypatch.setattr(type(app.state.container.audit), "record", fail_async)

    with pytest.raises(RuntimeError):
        await app.state.container.support.create(actor, payload, context=context)

    assert app.state.container.reports._records == {}
