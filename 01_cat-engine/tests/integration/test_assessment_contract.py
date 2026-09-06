"""Assessment mapping and frozen schema integration tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from cat_engine import RiskSnapshot
from cat_engine.domain.errors import ValidationError
from cat_engine.validation import validate_assessment_v1


def test_completed_cat_result_maps_to_assessment_v1(service, item_bank, cat_config) -> None:
    config = replace(cat_config, min_items=1, max_items=1, se_threshold=None)
    session = service.create_session("ASSESS_contract_cat_001", "SUBJ_contract_cat_001", item_bank, config)
    service.next_item(session)
    service.submit_response(session, "sometimes")
    result = service.complete(session)
    assessment = service.assessment(
        result,
        RiskSnapshot(
            level="normal",
            need_human_review=False,
            reason_codes=("RULESET_DEMO_ENGINEERING",),
            ruleset_id="RULESET_demo_cat_v1",
        ),
    )
    validate_assessment_v1(assessment)
    assert assessment["schema_version"] == "assessment.v1"
    assert assessment["dimensions"]["demo_trait"]["band"] == "unknown"
    assert assessment["dimensions"]["demo_trait"]["score"] is None
    assert "traces" not in assessment
    assert "response" not in assessment["response_summary"]


def test_high_risk_snapshot_requires_review_but_is_not_calculated_by_cat(service, item_bank, cat_config) -> None:
    config = replace(cat_config, min_items=1, max_items=1, se_threshold=None)
    session = service.create_session("ASSESS_contract_cat_002", "SUBJ_contract_cat_002", item_bank, config)
    service.next_item(session)
    service.submit_response(session, "sometimes")
    result = service.complete(session)
    assessment = service.assessment(
        result,
        RiskSnapshot(
            level="high",
            need_human_review=True,
            reason_codes=("RULESET_EXTERNAL_REVIEW",),
            ruleset_id="RULESET_external_v1",
        ),
    )
    validate_assessment_v1(assessment)
    assert assessment["risk"]["need_human_review"] is True
    with pytest.raises(ValidationError):
        service.assessment(
            result,
            RiskSnapshot(
                level="high",
                need_human_review=False,
                reason_codes=("RULESET_EXTERNAL_REVIEW",),
                ruleset_id="RULESET_external_v1",
            ),
        )

