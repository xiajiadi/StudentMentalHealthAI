from __future__ import annotations

import asyncio

import pytest
from cat_engine.api.app import (
    CatRuntime,
    CompleteRequest,
    ResponseRequest,
    StartRequest,
    _same_json_value,
    create_app,
)
from cat_engine.domain.enums import SessionStatus
from fastapi import HTTPException
from test_management_api import asgi_request


def _request(app, method: str, path: str, payload: dict | None = None):
    return asyncio.run(asgi_request(app, method, path, payload))


def _start_payload(assessment_id: str, subject_id: str = "SUBJ_demo_a") -> dict:
    return {
        "assessment_id": assessment_id,
        "subject_id": subject_id,
        "instrument_id": "CURRENT_SYNTHETIC_GRM",
        "instrument_version": "synthetic_item_bank.v1 / demo.v1",
    }


def test_last_answer_retry_returns_current_state_without_provider_replay(monkeypatch):
    runtime = CatRuntime()
    app = create_app(runtime=runtime)
    assessment_id = "ASSESS_m0_response_retry"
    path = f"/internal/cat/sessions/{assessment_id}/responses"
    start_status, started = _request(
        app, "POST", "/internal/cat/sessions", _start_payload(assessment_id)
    )
    assert start_status == 200
    first_request = {
        "item_id": started["current_item"]["item_id"],
        "response": "sometimes",
    }
    first_status, first_state = _request(app, "POST", path, first_request)
    assert first_status == 200

    session = runtime.sessions[assessment_id]
    trace_count = len(session.traces)
    subject_id = session.subject_id
    binding = runtime.session_bindings[assessment_id]
    provider = runtime.service.provider
    provider_advances = []
    original_submit = provider.submit_response
    original_select = provider.select_next_item

    def counted_submit(*args, **kwargs):
        provider_advances.append("submit")
        return original_submit(*args, **kwargs)

    def counted_select(*args, **kwargs):
        provider_advances.append("select")
        return original_select(*args, **kwargs)

    monkeypatch.setattr(provider, "submit_response", counted_submit)
    monkeypatch.setattr(provider, "select_next_item", counted_select)

    retry_status, retry_state = _request(app, "POST", path, first_request)
    assert retry_status == 200
    assert retry_state == first_state
    assert provider_advances == []
    assert len(session.traces) == trace_count
    assert session.subject_id == subject_id
    assert runtime.session_bindings[assessment_id] is binding

    changed_status, _ = _request(
        app,
        "POST",
        path,
        {**first_request, "response": "always"},
    )
    assert changed_status == 409
    assert provider_advances == []

    other_session_status, _ = _request(
        app,
        "POST",
        f"/internal/cat/sessions/{assessment_id}_other/responses",
        first_request,
    )
    assert other_session_status == 404

    assert retry_state["current_item"] is not None
    second_request = {
        "item_id": retry_state["current_item"]["item_id"],
        "response": "always",
    }
    second_status, _ = _request(app, "POST", path, second_request)
    assert second_status == 200
    historical_status, _ = _request(app, "POST", path, first_request)
    assert historical_status == 409


def test_exact_retry_requires_known_session_source_and_answered_trace():
    runtime = CatRuntime()
    assessment_id = "ASSESS_m0_retry_source"
    state = runtime.start(StartRequest(**_start_payload(assessment_id)))
    request = ResponseRequest(item_id=state["current_item"]["item_id"], response="sometimes")
    runtime.submit(assessment_id, request)
    session = runtime.sessions[assessment_id]
    session_binding = runtime.session_bindings[assessment_id]

    alias_assessment_id = "ASSESS_m0_retry_alias"
    runtime.sessions[alias_assessment_id] = session
    with pytest.raises(HTTPException) as different_session:
        runtime.submit(alias_assessment_id, request)
    assert different_session.value.status_code == 409
    runtime.sessions.pop(alias_assessment_id)

    runtime.session_bindings[assessment_id] = type(session_binding)(mode="UNKNOWN")
    with pytest.raises(HTTPException) as unknown_source:
        runtime.submit(assessment_id, request)
    assert unknown_source.value.status_code == 409

    runtime.session_bindings[assessment_id] = session_binding
    runtime.session_bindings.pop(assessment_id)
    with pytest.raises(HTTPException) as missing_source:
        runtime.submit(assessment_id, request)
    assert missing_source.value.status_code == 409

    runtime.session_bindings[assessment_id] = type(session_binding)(
        mode="SAVED_VERSION", binding_ref="CSBIND_incomplete"
    )
    with pytest.raises(HTTPException) as incomplete_saved_binding:
        runtime.submit(assessment_id, request)
    assert incomplete_saved_binding.value.status_code == 409

    runtime.session_bindings[assessment_id] = session_binding
    original_trace = session.traces[-1]
    session.traces[-1] = type(original_trace)(
        **{**original_trace.__dict__, "response_status": type(original_trace.response_status).SKIPPED}
    )
    with pytest.raises(HTTPException) as unanswered:
        runtime.submit(assessment_id, request)
    assert unanswered.value.status_code == 409

    runtime.session_bindings[assessment_id] = session_binding
    provider_session = session.provider_session
    session.provider_session = None
    with pytest.raises(HTTPException) as missing_provider:
        runtime.submit(assessment_id, request)
    assert missing_provider.value.status_code == 409
    session.provider_session = provider_session


def test_api_retry_does_not_equate_boolean_and_integer_json_responses():
    runtime = CatRuntime()
    app = create_app(runtime=runtime)
    assessment_id = "ASSESS_m0_bool_int_retry"
    start_status, started = _request(
        app, "POST", "/internal/cat/sessions", _start_payload(assessment_id)
    )
    assert start_status == 200
    path = f"/internal/cat/sessions/{assessment_id}/responses"
    item_id = started["current_item"]["item_id"]
    accepted_status, _ = _request(
        app, "POST", path, {"item_id": item_id, "response": 1}
    )
    assert accepted_status == 200

    boolean_retry_status, _ = _request(
        app, "POST", path, {"item_id": item_id, "response": True}
    )
    assert boolean_retry_status == 409


def test_response_json_equality_is_recursive_and_type_strict():
    assert _same_json_value(
        {"outer": [{"answer": 1, "flag": True}]},
        {"outer": [{"flag": True, "answer": 1}]},
    )
    assert not _same_json_value(True, 1)
    assert not _same_json_value(1, 1.0)
    assert not _same_json_value({"nested": [True]}, {"nested": [1]})
    assert not _same_json_value({1: "value"}, {1: "value"})
    assert not _same_json_value({"nested": {1: "value"}}, {"nested": {1: "value"}})
    for non_finite in (float("nan"), float("inf"), float("-inf")):
        assert not _same_json_value(non_finite, non_finite)


@pytest.mark.parametrize(
    "status",
    [
        SessionStatus.PAUSED,
        SessionStatus.COMPLETED,
        SessionStatus.CANCELLED,
        SessionStatus.ERROR,
    ],
)
def test_exact_retry_does_not_bypass_non_in_progress_session_guard(status):
    runtime = CatRuntime()
    assessment_id = f"ASSESS_m0_retry_{status.value.lower()}"
    state = runtime.start(StartRequest(**_start_payload(assessment_id)))
    request = ResponseRequest(
        item_id=state["current_item"]["item_id"], response="sometimes"
    )
    runtime.submit(assessment_id, request)
    runtime.sessions[assessment_id].status = status

    with pytest.raises(HTTPException) as retry_on_terminal_state:
        runtime.submit(assessment_id, request)

    assert retry_on_terminal_state.value.status_code == 409


def test_demo_cat_reaches_configured_stop_and_emits_accepted_d3_identity():
    runtime = CatRuntime()
    assessment_id = "ASSESS_m0_cat_identity"
    state = runtime.start(
        StartRequest(
            assessment_id=assessment_id,
            subject_id="SUBJ_demo_a",
            instrument_id="CURRENT_SYNTHETIC_GRM",
            instrument_version="synthetic_item_bank.v1 / demo.v1",
        )
    )

    assert state["current_item"] is not None
    assert state["synthetic_fixture_only"] is True
    while not state["can_complete"]:
        item_id = state["current_item"]["item_id"]
        state = runtime.submit(
            assessment_id,
            ResponseRequest(item_id=item_id, response="sometimes"),
        )
    assert state["current_item"] is None
    assert state["administered_count"] >= 3

    result = runtime.complete(assessment_id, CompleteRequest())
    assessment = result["assessment"]
    assert assessment["instrument"] == {
        "instrument_id": "CURRENT_SYNTHETIC_GRM",
        "version": "synthetic_item_bank.v1 / demo.v1",
    }
    assert assessment["population_scope"] == "SYNTHETIC_STUDENT_DEMO"
    assert set(assessment["dimensions"]) == {"demo_trait"}
    assert result["stopping_reason"] in {
        "SE_THRESHOLD_REACHED",
        "MAX_ITEMS_REACHED",
        "ITEM_BANK_EXHAUSTED",
    }
    assert len(result["trace"]) == result["state"]["administered_count"]
    assert all(trace["selection_criterion"] == "MFI" for trace in result["trace"])


def test_demo_cat_rejects_unknown_instrument_identity():
    runtime = CatRuntime()
    with pytest.raises(HTTPException) as caught:
        runtime.start(
            StartRequest(
                assessment_id="ASSESS_m0_bad_identity",
                subject_id="SUBJ_demo_a",
                instrument_id="unknown.instrument",
                instrument_version="1.0",
            )
        )
    assert caught.value.status_code == 422


def test_demo_cat_rejects_response_for_a_different_current_item():
    runtime = CatRuntime()
    assessment_id = "ASSESS_m0_wrong_item"
    state = runtime.start(
        StartRequest(
            assessment_id=assessment_id,
            subject_id="SUBJ_demo_a",
            instrument_id="CURRENT_SYNTHETIC_GRM",
            instrument_version="synthetic_item_bank.v1 / demo.v1",
        )
    )
    assert state["current_item"] is not None
    with pytest.raises(HTTPException) as caught:
        runtime.submit(
            assessment_id,
            ResponseRequest(item_id="ITEM_not_current", response="sometimes"),
        )
    assert caught.value.status_code == 409


def test_demo_cat_replays_persisted_answers_to_recover_current_selection():
    responses: list[tuple[str, str]] = []
    original = CatRuntime()
    assessment_id = "ASSESS_m0_cat_recovery"
    state = original.start(
        StartRequest(
            assessment_id=assessment_id,
            subject_id="SUBJ_demo_a",
            instrument_id="CURRENT_SYNTHETIC_GRM",
            instrument_version="synthetic_item_bank.v1 / demo.v1",
        )
    )

    for option in ("never", "always", "sometimes"):
        if state["can_complete"]:
            break
        item_id = state["current_item"]["item_id"]
        responses.append((item_id, option))
        state = original.submit(
            assessment_id,
            ResponseRequest(item_id=item_id, response=option),
        )

    recovered = CatRuntime()
    replayed = recovered.start(
        StartRequest(
            assessment_id=assessment_id,
            subject_id="SUBJ_demo_a",
            instrument_id="CURRENT_SYNTHETIC_GRM",
            instrument_version="synthetic_item_bank.v1 / demo.v1",
        )
    )
    for item_id, option in responses:
        assert replayed["current_item"]["item_id"] == item_id
        replayed = recovered.submit(
            assessment_id,
            ResponseRequest(item_id=item_id, response=option),
        )

    assert replayed["current_item"] == state["current_item"]
    assert replayed["answered_count"] == state["answered_count"]
    assert replayed["administered_count"] == state["administered_count"]
    assert replayed["can_complete"] == state["can_complete"]
