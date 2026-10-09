from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from smhai_backend.adapters.database import MySqlBackendAdapter
from smhai_backend.adapters.memory.repositories import InMemoryConversationRepository
from smhai_backend.core.errors import BackendError, ErrorCode, error
from smhai_backend.core.request_context import RequestContext
from smhai_backend.core.support_diagnostics import (
    SupportDiagnosticFailureCode,
    SupportWorkflowDiagnostics,
    failure_code_for_exception,
    sanitize_support_stage_diagnostics,
)
from smhai_backend.domains.models import AssessmentRecord
from smhai_backend.domains.support.schemas import SupportRequest

_ASSESSMENT_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "03_assessment-adapter"
    / "fixtures"
    / "synthetic_assessment.v1.json"
)


def test_diagnostics_are_fixed_enum_only_and_unknown_values_fail_closed() -> None:
    safe = sanitize_support_stage_diagnostics(
        {
            "last_confirmed_stage": "LLM_RUNTIME",
            "failure_stage": "CLAIM_BOUNDARY",
            "failure_code": "dependency_invalid_response",
            "failure_component": "BACKEND",
            "exception_text": "PRIVATE_SENTINEL",
            "request_id": "REQ_private",
        }
    )
    assert safe == {
        "last_confirmed_stage": "LLM_RUNTIME",
        "failure_stage": "CLAIM_BOUNDARY",
        "failure_code": "dependency_invalid_response",
        "failure_component": "BACKEND",
    }
    assert sanitize_support_stage_diagnostics(
        {"last_confirmed_stage": "made-up", "failure_stage": None}
    ) == {
        "last_confirmed_stage": "UNKNOWN",
        "failure_stage": "NOT_OBSERVED",
        "failure_code": "UNKNOWN",
        "failure_component": "UNKNOWN",
    }


def test_failure_code_uses_only_typed_backend_error_codes() -> None:
    typed = error(ErrorCode.DEPENDENCY_INVALID_RESPONSE, detail="PRIVATE_SENTINEL")
    assert (
        failure_code_for_exception(typed)
        is SupportDiagnosticFailureCode.DEPENDENCY_INVALID_RESPONSE
    )
    assert (
        failure_code_for_exception(RuntimeError("PRIVATE_SENTINEL"))
        is SupportDiagnosticFailureCode.UNKNOWN
    )


def test_missing_stage_observation_is_explicit() -> None:
    diagnostics = SupportWorkflowDiagnostics()
    assert diagnostics.failure_metadata() == {
        "last_confirmed_stage": "UNKNOWN",
        "failure_stage": "NOT_OBSERVED",
        "failure_code": "UNKNOWN",
        "failure_component": "UNKNOWN",
    }


def test_runtime_attempt_projection_is_bounded_and_drops_unknown_content() -> None:
    sanitized = sanitize_support_stage_diagnostics(
        {
            "last_confirmed_stage": "LLM_RUNTIME",
            "failure_stage": "CLAIM_BOUNDARY",
            "failure_code": "dependency_invalid_response",
            "failure_component": "BACKEND",
            "runtime_attempt_count": 1,
            "runtime_retry_count": 0,
            "runtime_requested_model_id": "qwen2.5-0.5b-engineering",
            "runtime_model_id": "qwen2.5-0.5b-engineering",
            "runtime_hardware_profile": "CONSUMER_GPU",
            "runtime_fallback_attempted": False,
            "runtime_fallback_count": 0,
            "trace": {"candidate": "PRIVATE_CANDIDATE_SENTINEL"},
            "prompt": "PRIVATE_PROMPT_SENTINEL",
            "unrecognized": "PRIVATE_TRACE_SENTINEL",
        }
    )
    assert sanitized == {
        "last_confirmed_stage": "LLM_RUNTIME",
        "failure_stage": "CLAIM_BOUNDARY",
        "failure_code": "dependency_invalid_response",
        "failure_component": "BACKEND",
        "runtime_attempt_count": 1,
        "runtime_retry_count": 0,
        "runtime_requested_model_id": "qwen2.5-0.5b-engineering",
        "runtime_model_id": "qwen2.5-0.5b-engineering",
        "runtime_hardware_profile": "CONSUMER_GPU",
        "runtime_fallback_attempted": False,
        "runtime_fallback_count": 0,
    }


def test_invalid_runtime_attempt_projection_drops_all_runtime_fields() -> None:
    sanitized = sanitize_support_stage_diagnostics(
        {
            "failure_stage": "CLAIM_BOUNDARY",
            "runtime_attempt_count": 1,
            "runtime_retry_count": 1,
            "runtime_requested_model_id": "qwen2.5-0.5b-engineering",
            "runtime_model_id": "qwen2.5-0.5b-engineering",
            "runtime_hardware_profile": "CONSUMER_GPU",
            "runtime_fallback_attempted": False,
            "runtime_fallback_count": 0,
            "runtime_trace_id": "TRACE_unexpected",
        }
    )
    assert sanitized == {
        "last_confirmed_stage": "UNKNOWN",
        "failure_stage": "CLAIM_BOUNDARY",
        "failure_code": "UNKNOWN",
        "failure_component": "UNKNOWN",
    }

    unknown_model = sanitize_support_stage_diagnostics(
        {
            "runtime_attempt_count": 1,
            "runtime_retry_count": 0,
            "runtime_requested_model_id": "unknown",
            "runtime_model_id": "qwen2.5-0.5b-engineering",
            "runtime_hardware_profile": "CPU_ONLY",
            "runtime_fallback_attempted": False,
            "runtime_fallback_count": 0,
        }
    )
    assert "runtime_attempt_count" not in unknown_model


def test_memory_failure_record_has_safe_stage_projection_only() -> None:
    repository = InMemoryConversationRepository()
    repository.fail_workflow(
        "REPORT_synthetic",
        reason_code="BACKENDERROR",
        trace_id="TRACE_synthetic",
        stage_diagnostics={
            "last_confirmed_stage": "WORKFLOW_REQUESTED",
            "failure_stage": "RAG_RETRIEVAL",
            "failure_code": "dependency_unavailable",
            "failure_component": "RAG",
            "request_id": "REQ_private",
            "candidate": "PRIVATE_SENTINEL",
        },
    )
    failure = repository.records[0]
    assert failure["reason_code"] == "BACKENDERROR"
    assert failure["trace_id"] == "TRACE_synthetic"
    assert failure["stage_diagnostics"] == {
        "last_confirmed_stage": "WORKFLOW_REQUESTED",
        "failure_stage": "RAG_RETRIEVAL",
        "failure_code": "dependency_unavailable",
        "failure_component": "RAG",
    }
    assert "REQ_private" not in json.dumps(failure["stage_diagnostics"])
    assert "PRIVATE_SENTINEL" not in json.dumps(failure["stage_diagnostics"])


@pytest.mark.asyncio
async def test_mysql_failure_projection_is_allowlisted_without_database_access() -> None:
    run = SimpleNamespace()

    class Statement:
        def where(self, _condition):
            return self

    class FakeSession:
        async def scalar(self, _statement):
            return run

    class FakeUow:
        session = FakeSession()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class RunModel:
        run_ref = object()

    adapter = object.__new__(MySqlBackendAdapter)
    adapter._db_models = SimpleNamespace(SupportRun=RunModel)
    adapter._db_enums = SimpleNamespace(
        SupportRunStatus=SimpleNamespace(FAILED=SimpleNamespace(value="FAILED"))
    )
    adapter._select = lambda _model: Statement()
    adapter._uow = FakeUow
    adapter._utc_now = lambda: "synthetic-time"

    await adapter.fail_workflow(
        "REPORT_synthetic",
        reason_code="BACKENDERROR",
        trace_id="TRACE_synthetic",
        stage_diagnostics={
            "last_confirmed_stage": "OUTPUT_SAFETY",
            "failure_stage": "CLAIM_BOUNDARY",
            "failure_code": "dependency_invalid_response",
            "failure_component": "BACKEND",
            "exception_text": "PRIVATE_SENTINEL",
            "request_id": "REQ_private",
        },
    )
    assert run.status == "FAILED"
    assert run.workflow_action == "FAILED"
    assert run.trace_id == "TRACE_synthetic"
    assert run.component_versions == {
        "persistence": "MYSQL",
        "reason_code": "BACKENDERROR",
        "candidate_persisted": False,
        "last_confirmed_stage": "OUTPUT_SAFETY",
        "failure_stage": "CLAIM_BOUNDARY",
        "failure_code": "dependency_invalid_response",
        "failure_component": "BACKEND",
    }
    assert "REQ_private" not in json.dumps(run.component_versions)
    assert "PRIVATE_SENTINEL" not in json.dumps(run.component_versions)


@pytest.mark.asyncio
@pytest.mark.parametrize("persistence_fails", [False, True])
async def test_runtime_failure_records_stage_without_masking_error(
    app, monkeypatch, persistence_fails: bool
) -> None:
    assessment = json.loads(_ASSESSMENT_FIXTURE.read_text(encoding="utf-8"))
    app.state.container.assessments_repo.save(
        AssessmentRecord(
            assessment_id=assessment["assessment_id"],
            subject_id=assessment["subject_id"],
            assessment=assessment,
        )
    )
    app.state.container.users.get_by_username("student_a").subject_id = assessment["subject_id"]
    actor = app.state.container.users.get_by_username("student_a").actor()
    payload = SupportRequest.model_validate(
        {
            "assessment_id": assessment["assessment_id"],
            "target_role": "student",
            "message": "synthetic diagnostic input",
            "language": "zh-CN",
        }
    )
    original_error = error(
        ErrorCode.DEPENDENCY_INVALID_RESPONSE,
        status_code=502,
        detail="PRIVATE_SENTINEL",
    )

    async def failed_runtime(_self, **_kwargs):
        raise original_error

    monkeypatch.setattr(type(app.state.container.llm), "generate", failed_runtime)
    if persistence_fails:

        def fail_persistence(*_args, **_kwargs):
            raise RuntimeError("PRIVATE_PERSISTENCE_SENTINEL")

        monkeypatch.setattr(app.state.container.conversations, "fail_workflow", fail_persistence)

    with pytest.raises(BackendError) as caught:
        await app.state.container.support.create(
            actor,
            payload,
            context=RequestContext("REQ_synthetic_diag", "TRACE_synthetic_diag"),
        )

    assert caught.value is original_error
    assert caught.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE
    assert caught.value.status_code == 502
    if not persistence_fails:
        failed = [
            item
            for item in app.state.container.conversations.records
            if item.get("workflow") == "FAILED"
        ]
        assert len(failed) == 1
        assert failed[0]["reason_code"] == "BACKENDERROR"
        assert failed[0]["stage_diagnostics"] == {
            "last_confirmed_stage": "MODEL_POLICY",
            "failure_stage": "LLM_RUNTIME",
            "failure_code": "dependency_invalid_response",
            "failure_component": "LLM_RUNTIME",
        }
        assert "REQ_synthetic_diag" not in json.dumps(failed[0]["stage_diagnostics"])
        assert "PRIVATE_SENTINEL" not in json.dumps(failed[0]["stage_diagnostics"])
    else:
        assert "PRIVATE_PERSISTENCE_SENTINEL" not in str(caught.value)
