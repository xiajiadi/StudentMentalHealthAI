"""Configuration-driven model registry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .models import ModelEntry


class ModelRegistry:
    """Resolve logical model IDs without embedding provider-specific branches."""

    def __init__(self, entries: Iterable[ModelEntry], *, registry_version: str = "0.1.0") -> None:
        self.registry_version = registry_version
        self._entries: dict[str, ModelEntry] = {}
        for entry in entries:
            if entry.logical_model_id in self._entries:
                raise ValueError(f"duplicate logical model id: {entry.logical_model_id}")
            if any(
                existing.contract_model_id == entry.contract_model_id
                for existing in self._entries.values()
            ):
                raise ValueError(f"duplicate contract model id: {entry.contract_model_id}")
            self._entries[entry.logical_model_id] = entry

    @classmethod
    def from_file(cls, path: str | Path) -> "ModelRegistry":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("schema_version") != "llm-runtime.models.v1":
            raise ValueError("unsupported model registry schema")
        if data.get("cloud_fallback") is not False:
            raise ValueError("cloud fallback must be explicitly disabled")
        return cls(
            (ModelEntry.from_dict(value) for value in data.get("models", [])),
            registry_version=str(data.get("registry_version", "0.1.0")),
        )

    def all(self) -> tuple[ModelEntry, ...]:
        return tuple(self._entries.values())

    def resolve(self, model_id: str) -> ModelEntry:
        if model_id in self._entries:
            return self._entries[model_id]
        for entry in self._entries.values():
            if entry.contract_model_id == model_id or entry.provider_model_id == model_id:
                return entry
        raise KeyError(f"unknown logical/provider model id: {model_id}")

    def by_provider(self, provider: str) -> tuple[ModelEntry, ...]:
        return tuple(entry for entry in self._entries.values() if entry.provider == provider)

    def update(self, entry: ModelEntry) -> None:
        if entry.logical_model_id not in self._entries:
            raise KeyError(entry.logical_model_id)
        self._entries[entry.logical_model_id] = entry

    def reconcile_discovery(
        self,
        provider: str,
        discovered: Iterable[Mapping[str, Any]],
    ) -> tuple[ModelEntry, ...]:
        by_provider_id = {
            str(item.get("provider_model_id")): item for item in discovered if item.get("provider_model_id")
        }
        updated: list[ModelEntry] = []
        for entry in self.by_provider(provider):
            item = by_provider_id.get(entry.provider_model_id)
            if item is not None:
                entry = entry.update_from_discovery(item)
                self.update(entry)
                updated.append(entry)
        return tuple(updated)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "llm-runtime.models.v1",
            "registry_version": self.registry_version,
            "cloud_fallback": False,
            "models": [entry.to_dict() for entry in self.all()],
        }

