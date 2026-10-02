from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from typing import Any

import pytest

from smhai_backend.core.request_context import RequestContext
from smhai_backend.domains.models import Actor, AssessmentRecord, BackendRole, ReportRecord
from smhai_backend.domains.support import service as support_service_module
from smhai_backend.domains.support.schemas import SupportRequest
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
    client, app
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
        json=_support_payload(assessment["assessment_id"], "normal synthetic support"),
    )

    assert response.status_code == 202, response.text
    body = response.json()["data"]
    assert body["status"] == "generated"
    assert body["generation"]["provenance"]["prompt_id"] == "PROMPT_student_synthetic_v1"
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
        metadata["content_population_mapping_id"]
        == "MAP_UNIVERSITY_FRESHMAN_SUPPORT_TO_RAG_D3_V1"
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
