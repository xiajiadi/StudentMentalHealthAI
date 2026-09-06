"""Provider-neutral LLM interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

from ..domain.models import (
    Capabilities,
    GenerationRequest,
    ModelHealth,
    ProviderHealth,
    ProviderResponse,
    RuntimeStreamEvent,
)


class LLMProvider(ABC):
    """Stable boundary used by RuntimeService and higher layers."""

    name: str

    @abstractmethod
    def discover_models(self) -> list[dict[str, Any]]:
        """Return provider-native model metadata normalized to dictionaries."""

    @abstractmethod
    def get_model_info(self, provider_model_id: str) -> dict[str, Any]:
        """Return metadata for one provider model."""

    @abstractmethod
    def health_check(self) -> ProviderHealth:
        """Report provider liveness and readiness separately."""

    @abstractmethod
    def model_health_check(self, provider_model_id: str) -> ModelHealth:
        """Report model availability and inference readiness."""

    @abstractmethod
    def load_model(self, provider_model_id: str, request: GenerationRequest | None = None) -> dict[str, Any]:
        """Load/preload a model using the provider lifecycle API."""

    @abstractmethod
    def unload_model(self, provider_model_id: str) -> dict[str, Any]:
        """Unload a model without restarting the provider."""

    @abstractmethod
    def generate(self, request: GenerationRequest) -> ProviderResponse:
        """Perform one non-streaming generation."""

    @abstractmethod
    def stream_generate(self, request: GenerationRequest) -> Iterator[RuntimeStreamEvent]:
        """Yield normalized START/DELTA/USAGE/DONE or ERROR events."""

    @abstractmethod
    def cancel(self, request_id: str) -> bool:
        """Request cancellation for an active request."""

    @abstractmethod
    def capabilities(self) -> Capabilities:
        """Return capability flags without exposing provider payload shapes."""

    @abstractmethod
    def runtime_info(self) -> dict[str, Any]:
        """Return non-sensitive runtime metadata."""

