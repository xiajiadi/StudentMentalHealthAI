"""Shared fixtures for the CAT Round 1 test suite."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cat_engine import AdaptiveTestingProvider, CATConfig, ItemBank
from cat_engine.service.cat_service import CATService


CAT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def item_bank() -> ItemBank:
    """Load the synthetic, runtime-published demo bank."""

    return ItemBank.from_json(CAT_ROOT / "fixtures" / "synthetic_item_bank.v1.json")


@pytest.fixture()
def cat_config() -> CATConfig:
    """Load the versioned demo configuration."""

    source = json.loads((CAT_ROOT / "fixtures" / "demo_cat_config.v1.json").read_text(encoding="utf-8"))
    return CATConfig.from_dict(source)


@pytest.fixture()
def service() -> CATService:
    """Use the real adaptivetesting adapter for integration-facing tests."""

    return CATService(AdaptiveTestingProvider())

