"""Session state-machine and response-path tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from cat_engine import Session
from cat_engine.domain.enums import ResponseStatus, SessionStatus
from cat_engine.domain.errors import ResponseValidationError, SessionStateError, SessionStoppedError


def test_session_starts_initialized_and_completes_at_max(service, item_bank, cat_config) -> None:
    config = replace(cat_config, min_items=1, max_items=1, se_threshold=None)
    session = service.create_session("ASSESS_session_001", "SUBJ_session_001", item_bank, config)
    assert session.status is SessionStatus.INITIALIZED
    service.next_item(session)
    service.submit_response(session, "sometimes")
    assert session.last_stop_decision is not None
    assert session.last_stop_decision.should_stop is True
    result = service.complete(session)
    assert session.status is SessionStatus.COMPLETED
    assert result.stopping_reason.value == "MAX_ITEMS_REACHED"


def test_completed_session_cannot_continue(service, item_bank, cat_config) -> None:
    config = replace(cat_config, min_items=1, max_items=1, se_threshold=None)
    session = service.create_session("ASSESS_session_002", "SUBJ_session_002", item_bank, config)
    service.next_item(session)
    service.submit_response(session, "sometimes")
    service.complete(session)
    with pytest.raises(SessionStateError):
        service.next_item(session)
    with pytest.raises(SessionStateError):
        service.submit_response(session, "sometimes")


def test_response_before_initialization_is_rejected(item_bank, cat_config, service) -> None:
    session = Session.create("ASSESS_session_003", "SUBJ_session_003", item_bank, cat_config)
    with pytest.raises(SessionStateError, match="not been initialized"):
        session.select_next_item(service.provider)
    with pytest.raises(SessionStateError):
        session.submit_response(service.provider, "never")


def test_invalid_response_does_not_consume_pending_item(service, item_bank, cat_config) -> None:
    session = service.create_session("ASSESS_session_004", "SUBJ_session_004", item_bank, cat_config)
    selection = service.next_item(session)
    with pytest.raises(ResponseValidationError):
        service.submit_response(session, "not-a-published-option")
    assert session.selected_item_id == selection.item_id
    assert session.traces == []


def test_all_missing_response_states_are_distinct(service, item_bank, cat_config) -> None:
    for index, status in enumerate(
        (ResponseStatus.SKIPPED, ResponseStatus.TIMEOUT, ResponseStatus.INVALID, ResponseStatus.NOT_PRESENTED),
        start=1,
    ):
        session = service.create_session(
            f"ASSESS_missing_{index:03d}", f"SUBJ_missing_{index:03d}", item_bank, cat_config
        )
        service.next_item(session)
        trace = service.record_missing(session, status)
        assert trace.response_status is status
        assert trace.response is None


def test_stop_guard_prevents_next_item_after_threshold(service, item_bank, cat_config) -> None:
    config = replace(cat_config, min_items=1, max_items=1, se_threshold=None)
    session = service.create_session("ASSESS_session_005", "SUBJ_session_005", item_bank, config)
    service.next_item(session)
    service.submit_response(session, "sometimes")
    with pytest.raises(SessionStoppedError, match="MAX_ITEMS_REACHED"):
        service.next_item(session)

