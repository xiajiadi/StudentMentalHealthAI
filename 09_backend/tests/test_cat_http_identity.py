from __future__ import annotations

import pytest

from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.integrations.cat import CatStart, HttpCatClient


def _http_client() -> HttpCatClient:
    # The adapter methods under test use only the request methods, so this
    # avoids creating a network client or contacting a service.
    return object.__new__(HttpCatClient)


@pytest.mark.asyncio
async def test_cat_start_rejects_session_bound_to_different_assessment(monkeypatch):
    client = _http_client()

    async def post_json(*args, **kwargs):
        return {
            "assessment_id": "ASSESS_other",
            "subject_id": "SUBJ_demo_a",
            "current_item": {"item_id": "ITEM_demo_001"},
        }

    monkeypatch.setattr(client, "post_json", post_json)

    with pytest.raises(BackendError) as caught:
        await client.start(
            assessment_id="ASSESS_expected",
            subject_id="SUBJ_demo_a",
            instrument_id="CURRENT_SYNTHETIC_GRM",
            instrument_version="synthetic_item_bank.v1 / demo.v1",
        )

    assert caught.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE


@pytest.mark.asyncio
async def test_cat_state_rejects_session_bound_to_different_subject(monkeypatch):
    client = _http_client()

    async def get_json(*args, **kwargs):
        return {
            "assessment_id": "ASSESS_expected",
            "subject_id": "SUBJ_other",
            "current_item": {"item_id": "ITEM_demo_002"},
        }

    monkeypatch.setattr(client, "get_json", get_json)
    session = CatStart(
        assessment_id="ASSESS_expected",
        subject_id="SUBJ_demo_a",
        instrument_id="CURRENT_SYNTHETIC_GRM",
        instrument_version="synthetic_item_bank.v1 / demo.v1",
        started_at="2026-10-09T00:00:00Z",
    )

    with pytest.raises(BackendError) as caught:
        await client.state(session)

    assert caught.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE


@pytest.mark.asyncio
async def test_cat_completion_rejects_invalid_frozen_assessment_projection(monkeypatch):
    client = _http_client()

    async def post_json(*args, **kwargs):
        return {"assessment": {"assessment_id": "ASSESS_expected"}}

    monkeypatch.setattr(client, "post_json", post_json)
    session = CatStart(
        assessment_id="ASSESS_expected",
        subject_id="SUBJ_demo_a",
        instrument_id="CURRENT_SYNTHETIC_GRM",
        instrument_version="synthetic_item_bank.v1 / demo.v1",
        started_at="2026-10-09T00:00:00Z",
    )

    with pytest.raises(BackendError) as caught:
        await client.complete(session, responses={})

    assert caught.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE
