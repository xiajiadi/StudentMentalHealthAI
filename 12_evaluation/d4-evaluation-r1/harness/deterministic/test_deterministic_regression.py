from __future__ import annotations

import pytest

from .cases import CASE_SPECS, run_case_sync


@pytest.mark.parametrize("case_id", [spec.case_id for spec in CASE_SPECS])
def test_d4_deterministic_case(case_id: str) -> None:
    observation = run_case_sync(case_id)
    assert observation.observed_outcome == "PASS"
    assert observation.observed_response_class
    assert observation.case_id == case_id
