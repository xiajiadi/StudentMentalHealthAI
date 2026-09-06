"""Stable provider interface used by CAT orchestration."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from random import Random
from typing import Any

from ..domain.config import CATConfig
from ..domain.enums import ResponseStatus, StopReason
from ..domain.item import Item, ResponseValue
from ..domain.item_bank import ItemBank


@dataclass(frozen=True)
class ProviderSession:
    """Opaque provider state held by a domain Session."""

    session_id: str
    provider_name: str
    provider_version: str
    item_bank_version: str
    config_version: str
    _opaque_state: object = field(repr=False, compare=False)

    def opaque_state(self) -> object:
        """Return state for the owning adapter; callers must not inspect it."""

        return self._opaque_state


@dataclass(frozen=True)
class ItemSelection:
    """Provider-neutral next-item decision."""

    item_id: str
    criterion: str
    score: float | None


@dataclass(frozen=True)
class ProviderUpdate:
    """Estimate transition after one item administration."""

    theta: float
    se: float
    response_score: int | None


@dataclass(frozen=True)
class StopDecision:
    """Provider stopping result and explicit reason."""

    should_stop: bool
    reason: StopReason


@dataclass(frozen=True)
class ProviderResultSnapshot:
    """Provider-neutral final estimate counts."""

    theta: float
    se: float
    items_administered: int
    items_answered: int


class CATProvider(ABC):
    """Interface that hides every third-party CAT engine type."""

    provider_name: str
    provider_version: str

    @abstractmethod
    def start_session(self, session_id: str, item_bank: ItemBank, config: CATConfig) -> ProviderSession:
        """Initialize opaque provider state from immutable bank/config versions."""

    @abstractmethod
    def select_next_item(self, session: ProviderSession) -> ItemSelection:
        """Select an unadministered item using the configured criterion."""

    @abstractmethod
    def submit_response(self, session: ProviderSession, item_id: str, response_score: int) -> ProviderUpdate:
        """Submit a validated category index and update theta/uncertainty."""

    @abstractmethod
    def record_non_answer(
        self,
        session: ProviderSession,
        item_id: str,
        status: ResponseStatus,
    ) -> ProviderUpdate:
        """Consume a presented item without converting missingness to a score."""

    @abstractmethod
    def estimate_ability(self, session: ProviderSession) -> float:
        """Return the current theta estimate."""

    @abstractmethod
    def get_uncertainty(self, session: ProviderSession) -> float:
        """Return the current standard error."""

    @abstractmethod
    def should_stop(self, session: ProviderSession) -> StopDecision:
        """Evaluate configured minimum, maximum, SE, and bank exhaustion rules."""

    @abstractmethod
    def get_result(
        self,
        session: ProviderSession,
        stop_decision: StopDecision | None = None,
    ) -> ProviderResultSnapshot:
        """Return a provider-neutral result snapshot."""

    @abstractmethod
    def sample_response(
        self,
        session: ProviderSession,
        item_id: str,
        true_theta: float,
        rng: Random,
    ) -> ResponseValue:
        """Sample a response through the provider/model for simulation only."""

