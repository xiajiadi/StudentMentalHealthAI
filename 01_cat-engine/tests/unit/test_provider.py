"""Provider adapter behavior tests."""

from __future__ import annotations

from cat_engine.domain.enums import ResponseStatus
from cat_engine.domain.errors import ProviderError


def test_provider_initializes_selects_and_updates(service, item_bank, cat_config) -> None:
    session = service.create_session("ASSESS_provider_001", "SUBJ_provider_001", item_bank, cat_config)
    first = service.next_item(session)
    assert first.item_id.startswith("ITEM_")
    assert first.criterion == "MFI"
    assert first.score is not None
    trace = service.submit_response(session, "always")
    assert trace.response_status is ResponseStatus.ANSWERED
    assert trace.theta_before != trace.theta_after
    assert trace.se_after != trace.se_before
    second = service.next_item(session)
    assert second.item_id != first.item_id


def test_provider_does_not_accept_response_for_non_pending_item(service, item_bank, cat_config) -> None:
    session = service.create_session("ASSESS_provider_002", "SUBJ_provider_002", item_bank, cat_config)
    service.next_item(session)
    assert session.provider_session is not None
    with __import__("pytest").raises(ProviderError, match="currently presented"):
        service.provider.submit_response(session.provider_session, "ITEM_demo_001", 0)


def test_missing_response_is_not_scored(service, item_bank, cat_config) -> None:
    session = service.create_session("ASSESS_provider_003", "SUBJ_provider_003", item_bank, cat_config)
    service.next_item(session)
    before = service.provider.estimate_ability(session.provider_session)
    trace = service.record_missing(session, ResponseStatus.SKIPPED)
    assert trace.response is None
    assert trace.response_status is ResponseStatus.SKIPPED
    assert trace.theta_after == before
    assert trace.se_after == trace.se_before

