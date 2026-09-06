"""Versioned item-bank loading and runtime eligibility checks."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from .enums import ItemBankStatus
from .errors import ItemBankValidationError
from .item import Item


@dataclass(frozen=True)
class ItemBank:
    """Immutable item bank consumed by online CAT providers."""

    item_bank_id: str
    version: str
    instrument_id: str
    target_population: str
    measurement_model: str
    dimensions: tuple[str, ...]
    items: tuple[Item, ...]
    status: ItemBankStatus
    metadata: Mapping[str, Any]

    @classmethod
    def from_json(cls, path: str | Path) -> "ItemBank":
        """Load a JSON item bank and validate it before returning."""

        source_path = Path(path)
        try:
            source = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ItemBankValidationError(f"cannot load item bank {source_path}: {exc}") from exc
        if not isinstance(source, Mapping):
            raise ItemBankValidationError("item bank root must be an object")
        return cls.from_dict(source)

    @classmethod
    def from_dict(cls, source: Mapping[str, Any]) -> "ItemBank":
        """Build a bank from a JSON-like object with strict required fields."""

        required = {
            "item_bank_id",
            "version",
            "instrument_id",
            "target_population",
            "measurement_model",
            "dimensions",
            "items",
            "status",
            "metadata",
        }
        missing = sorted(required.difference(source))
        if missing:
            raise ItemBankValidationError(f"item bank missing fields: {', '.join(missing)}")
        dimensions = source["dimensions"]
        raw_items = source["items"]
        metadata = source["metadata"]
        if not isinstance(dimensions, (list, tuple)) or not dimensions:
            raise ItemBankValidationError("dimensions must be a non-empty list")
        if len(set(dimensions)) != len(dimensions):
            raise ItemBankValidationError("dimensions must be unique")
        if not isinstance(raw_items, (list, tuple)) or not raw_items:
            raise ItemBankValidationError("items must be a non-empty list")
        if not isinstance(metadata, Mapping):
            raise ItemBankValidationError("metadata must be an object")
        try:
            status = ItemBankStatus(str(source["status"]))
        except ValueError as exc:
            raise ItemBankValidationError(f"unsupported item bank status: {source['status']!r}") from exc
        items = tuple(Item.from_dict(item) for item in raw_items if isinstance(item, Mapping))
        if len(items) != len(raw_items):
            raise ItemBankValidationError("each item must be an object")
        bank = cls(
            item_bank_id=str(source["item_bank_id"]),
            version=str(source["version"]),
            instrument_id=str(source["instrument_id"]),
            target_population=str(source["target_population"]),
            measurement_model=str(source["measurement_model"]),
            dimensions=tuple(str(value) for value in dimensions),
            items=items,
            status=status,
            metadata=dict(metadata),
        )
        bank.validate()
        return bank

    def validate(self) -> None:
        """Validate IDs, dimensions, immutable published parameters, and demo labels."""

        if not self.item_bank_id or not self.version or not self.instrument_id or not self.target_population:
            raise ItemBankValidationError("item bank identity and target population are required")
        if self.measurement_model not in {"GRM", "GPCM"}:
            raise ItemBankValidationError(f"unsupported measurement model: {self.measurement_model}")
        if len({item.item_id for item in self.items}) != len(self.items):
            raise ItemBankValidationError("item bank contains duplicate item_id values")
        dimensions = set(self.dimensions)
        for item in self.items:
            if item.dimension not in dimensions:
                raise ItemBankValidationError(f"item {item.item_id} uses an unknown dimension")
            if item.model != self.measurement_model:
                raise ItemBankValidationError(f"item {item.item_id} model differs from bank measurement_model")
            if item.status not in {"published", "demo", "synthetic"}:
                raise ItemBankValidationError(f"item {item.item_id} is not runtime eligible")
        if self.metadata.get("synthetic") is True:
            if self.metadata.get("intended_use") != "engineering_test_only":
                raise ItemBankValidationError("synthetic bank must declare engineering_test_only")
            if self.metadata.get("psychological_interpretation_allowed") is not False:
                raise ItemBankValidationError("synthetic bank must prohibit psychological interpretation")

    def assert_runtime_ready(self) -> None:
        """Enforce the online rule that only published banks may be loaded."""

        if self.status is not ItemBankStatus.PUBLISHED:
            raise ItemBankValidationError(
                f"online CAT requires a published item bank, got {self.status.value}"
            )

    def item_by_id(self, item_id: str) -> Item:
        """Return an item by stable ID or raise a validation error."""

        for item in self.items:
            if item.item_id == item_id:
                return item
        raise ItemBankValidationError(f"unknown item_id: {item_id}")

    def to_dict(self) -> dict[str, Any]:
        """Return the bank without provider-specific objects."""

        return {
            "item_bank_id": self.item_bank_id,
            "version": self.version,
            "instrument_id": self.instrument_id,
            "target_population": self.target_population,
            "measurement_model": self.measurement_model,
            "dimensions": list(self.dimensions),
            "items": [item.to_dict() for item in self.items],
            "status": self.status.value,
            "metadata": dict(self.metadata),
        }

