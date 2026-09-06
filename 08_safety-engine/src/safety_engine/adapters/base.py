"""Adapter protocols and normalized result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from safety_engine.domain import ComponentHealth, SafetySignal


@dataclass(slots=True)
class AdapterResult:
    status: str
    signals: list[SafetySignal] = field(default_factory=list)
    transformed_text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SafetyAdapter(Protocol):
    component: str
    version: str

    def health(self) -> ComponentHealth: ...


class PrivacyAdapter(Protocol):
    component: str
    version: str

    def health(self) -> ComponentHealth: ...

    def detect(self, text: str, *, trace_id: str) -> AdapterResult: ...

    def redact(self, text: str, *, trace_id: str) -> str: ...

    def mask(self, text: str, *, trace_id: str) -> str: ...

    def anonymize_metadata(self, text: str, *, trace_id: str) -> dict[str, Any]: ...


class GuardAdapter(Protocol):
    component: str
    version: str

    def health(self) -> ComponentHealth: ...

    async def check_input(self, text: str, *, trace_id: str) -> AdapterResult: ...

    async def check_output(self, text: str, *, trace_id: str) -> AdapterResult: ...


class ContentGuardAdapter(Protocol):
    component: str
    version: str

    def health(self) -> ComponentHealth: ...

    async def classify_input(self, text: str, *, trace_id: str) -> AdapterResult: ...

    async def classify_response(
        self, user_message: str, candidate: str, *, trace_id: str
    ) -> AdapterResult: ...


class SafetyModelProvider(ContentGuardAdapter, Protocol):
    def load(self) -> ComponentHealth: ...

    async def classify_output(
        self, user_message: str, candidate: str, *, trace_id: str
    ) -> AdapterResult: ...

    def model_info(self) -> dict[str, Any]: ...

    def capabilities(self) -> dict[str, Any]: ...
