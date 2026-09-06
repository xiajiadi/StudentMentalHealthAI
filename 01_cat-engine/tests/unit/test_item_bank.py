"""Item bank and config validation tests."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from cat_engine import CATConfig, ItemBank
from cat_engine.domain.errors import ConfigValidationError, ItemBankValidationError


def load_bank_dict() -> dict:
    path = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic_item_bank.v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_config_dict() -> dict:
    path = Path(__file__).resolve().parents[2] / "fixtures" / "demo_cat_config.v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_synthetic_bank_is_valid_and_explicitly_non_interpretable(item_bank: ItemBank) -> None:
    assert item_bank.status.value == "published"
    assert item_bank.metadata["synthetic"] is True
    assert item_bank.metadata["intended_use"] == "engineering_test_only"
    assert item_bank.metadata["psychological_interpretation_allowed"] is False
    assert len(item_bank.items) == 9


def test_duplicate_item_id_is_rejected() -> None:
    source = load_bank_dict()
    source["items"][1]["item_id"] = source["items"][0]["item_id"]
    with pytest.raises(ItemBankValidationError, match="duplicate"):
        ItemBank.from_dict(source)


def test_missing_item_parameters_are_rejected() -> None:
    source = load_bank_dict()
    del source["items"][0]["parameters"]
    with pytest.raises(ItemBankValidationError, match="missing fields"):
        ItemBank.from_dict(source)


def test_invalid_response_option_mapping_is_rejected() -> None:
    source = load_bank_dict()
    source["items"][0]["response_options"].append("invalid-extra-option")
    with pytest.raises(ItemBankValidationError, match="scoring keys"):
        ItemBank.from_dict(source)


def test_non_published_bank_is_not_runtime_eligible() -> None:
    source = load_bank_dict()
    source["status"] = "draft"
    bank = ItemBank.from_dict(source)
    with pytest.raises(ItemBankValidationError, match="published"):
        bank.assert_runtime_ready()


def test_config_requires_all_algorithm_parameters(cat_config: CATConfig) -> None:
    assert cat_config.model == "GRM"
    assert cat_config.estimator == "EAP"
    assert cat_config.selection_method == "MFI"
    assert cat_config.max_items >= cat_config.min_items

    source = load_config_dict()
    del source["se_threshold"]
    with pytest.raises(ConfigValidationError, match="se_threshold"):
        CATConfig.from_dict(source)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("min_items", 0),
        ("max_items", 2),
        ("prior_sd", 0),
        ("optimization_interval", [1, -1]),
    ],
)
def test_invalid_config_values_are_rejected(field: str, value: object) -> None:
    source = load_config_dict()
    source[field] = value
    with pytest.raises(ConfigValidationError):
        CATConfig.from_dict(source)

