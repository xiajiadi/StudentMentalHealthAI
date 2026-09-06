from __future__ import annotations

from evaluation.root_contract_check import run_root_contract_check


def test_frozen_root_contract_fixtures_remain_compatible():
    result = run_root_contract_check(__import__("pathlib").Path(__file__).resolve().parents[3])
    assert result["status"] == "PASS", result
    assert result["modified"] is False
