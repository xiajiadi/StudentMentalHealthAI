from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "verify_school_deepseek_education_linux.py"
SPEC = importlib.util.spec_from_file_location("verify_school_deepseek_education_linux", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


def _completed_turn() -> dict[str, Any]:
    return {
        "status": "completed",
        "safe_metadata": {
            "stage": "completed",
            "model_id": verifier.EXPECTED_MODEL_ID,
            "attempt_count": 1,
            "evidence_count": 2,
            "input_safety_action": "PROCEED",
            "retrieval_safety_action": "PROCEED",
            "output_safety_action": "PROCEED_WITH_BOUNDARY",
        },
        "citations": [
            {
                "citation_id": "CIT_001",
                "chunk_id": "CHUNK_001",
                "source_hash": "sha256:" + "a" * 64,
            }
        ],
        "content": {
            "summary": "一般学习计划。",
            "observations": ["可分解任务。"],
            "suggestions": [{"text": "安排短时学习。", "source_chunk_ids": ["CHUNK_001"]}],
            "disclaimer": "这不是心理诊断。",
        },
    }


def test_completed_deepseek_turn_requires_safety_evidence_and_citations() -> None:
    report = verifier._validate_completed_turn(_completed_turn())

    assert report["status"] == "PASS"
    assert report["model_id"] == verifier.EXPECTED_MODEL_ID
    assert report["attempt_count"] == 1
    assert report["evidence_count"] == 2
    assert report["citation_count"] == 1
    assert report["answer_text_logged"] is False
    assert "content" not in report


@pytest.mark.parametrize(
    "mutate",
    [
        lambda turn: turn.update({"status": "blocked"}),
        lambda turn: turn["safe_metadata"].update({"model_id": "MODEL_mock"}),
        lambda turn: turn["safe_metadata"].update({"output_safety_action": "BLOCK"}),
        lambda turn: turn.update({"citations": []}),
        lambda turn: turn["safe_metadata"].update({"attempt_count": 2}),
    ],
)
def test_completed_deepseek_turn_fails_closed_on_missing_contract(
    mutate,
) -> None:
    turn = _completed_turn()
    mutate(turn)

    with pytest.raises(verifier.GateError):
        verifier._validate_completed_turn(turn)


def test_http_error_diagnostic_keeps_only_allowlisted_backend_code() -> None:
    class Response:
        def __init__(self, payload: object) -> None:
            self.payload = payload

        def json(self) -> object:
            return self.payload

    assert (
        verifier._safe_http_error_code(
            Response({"error": {"code": "DEPENDENCY_UNAVAILABLE", "message": "private"}})
        )
        == "DEPENDENCY_UNAVAILABLE"
    )
    assert verifier._safe_http_error_code(Response({"error": {"code": "private text"}})) is None


def test_turn_diagnostic_contains_no_generated_text() -> None:
    turn = _completed_turn()
    turn["content"]["summary"] = "synthetic answer body"

    diagnostic = verifier._safe_turn_diagnostic(turn)

    assert diagnostic["turn_status"] == "completed"
    assert diagnostic["configured_model_selected"] is True
    assert diagnostic["citation_count"] == 1
    assert diagnostic["content_fields"] == [
        "disclaimer",
        "observations",
        "suggestions",
        "summary",
    ]
    assert "synthetic answer body" not in repr(diagnostic)


def test_new_generation_run_id_uses_distinct_checkpoint_and_idempotency_keys(
    monkeypatch,
) -> None:
    for name in ("STATE_PATH", "OPERATION_ID", "CONVERSATION_KEY", "MESSAGE_KEY"):
        monkeypatch.setattr(verifier, name, getattr(verifier, name))
    verifier._configure_run_id("a" * 32)

    assert verifier.STATE_PATH.name == f"deepseek-generation-{'a' * 32}.json"
    assert verifier.OPERATION_ID.endswith("a" * 32)
    assert verifier.CONVERSATION_KEY.endswith("a" * 32)
    assert verifier.MESSAGE_KEY.endswith("a" * 32)


def test_pending_generation_reuses_the_durable_turn_without_reposting() -> None:
    turn = {"turn_id": "TURN_synthetic", "status": "requested"}

    assert verifier._existing_turn([turn]) is turn
    assert verifier._existing_turn([], expected_turn_id=None) is None
    assert verifier._existing_turn([turn], expected_turn_id="TURN_synthetic") is turn


def test_pending_generation_fails_closed_on_ambiguous_or_missing_turn() -> None:
    first = {"turn_id": "TURN_first", "status": "requested"}
    second = {"turn_id": "TURN_second", "status": "requested"}

    with pytest.raises(verifier.GateError, match="conversation_turn_state_ambiguous"):
        verifier._existing_turn([first, second])
    with pytest.raises(verifier.GateError, match="stored_turn_reconciliation_failed"):
        verifier._existing_turn([first], expected_turn_id="TURN_missing")


def test_read_only_reconciliation_never_allows_a_generation_post() -> None:
    with pytest.raises(verifier.GateError, match="read_only_reconciliation_no_post"):
        verifier._require_generation_submission_allowed(reconcile_only=True)

    verifier._require_generation_submission_allowed(reconcile_only=False)


@pytest.mark.parametrize("run_id", ["", "A" * 32, "a" * 31, "a" * 33, "../" + "a" * 30])
def test_generation_run_id_rejects_noncanonical_values(run_id: str) -> None:
    with pytest.raises(verifier.GateError, match="run_id_invalid"):
        verifier._configure_run_id(run_id)


def test_failed_turn_diagnostic_contains_only_safe_stage_codes() -> None:
    turn = {
        "status": "failed",
        "action": "DEPENDENCY_FAILURE",
        "safe_metadata": {
            "stage": "input_safety",
            "failure_code": "DEPENDENCY_FAILURE",
            "dependency_error_code": "DEPENDENCY_UNAVAILABLE",
            "private": "do not echo",
        },
    }

    diagnostic = verifier._safe_turn_diagnostic(turn)

    assert diagnostic["turn_status"] == "failed"
    assert diagnostic["stage"] == "input_safety"
    assert diagnostic["turn_action"] == "DEPENDENCY_FAILURE"
    assert diagnostic["failure_code"] == "DEPENDENCY_FAILURE"
    assert diagnostic["dependency_error_code"] == "DEPENDENCY_UNAVAILABLE"
    assert "private" not in repr(diagnostic)
