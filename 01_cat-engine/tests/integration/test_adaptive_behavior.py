"""Evidence that later selection responds to different response paths."""

from __future__ import annotations


def administered_sequence(service, item_bank, cat_config, option: str, suffix: str) -> list[str]:
    session = service.create_session(f"ASSESS_adaptive_{suffix}", f"SUBJ_adaptive_{suffix}", item_bank, cat_config)
    sequence: list[str] = []
    for _ in range(4):
        selection = service.next_item(session)
        sequence.append(selection.item_id)
        service.submit_response(session, option)
        if session.last_stop_decision and session.last_stop_decision.should_stop:
            break
    return sequence


def test_different_response_paths_change_later_item_selection(service, item_bank, cat_config) -> None:
    low_path = administered_sequence(service, item_bank, cat_config, "never", "low")
    high_path = administered_sequence(service, item_bank, cat_config, "always", "high")
    assert low_path[0] == high_path[0]
    assert low_path[1:] != high_path[1:]
