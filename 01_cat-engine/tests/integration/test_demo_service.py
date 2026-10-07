from __future__ import annotations

import pytest
from fastapi import HTTPException

from cat_engine.api.app import (
    CatRuntime,
    CompleteRequest,
    ResponseRequest,
    StartRequest,
)


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
