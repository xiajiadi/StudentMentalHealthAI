"""Provider registry and local endpoint/process ownership boundary."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from ..domain.models import ProviderHealth
from ..domain.registry import ModelRegistry
from ..errors import LLMRuntimeError, RuntimeErrorCode
from ..providers.base import LLMProvider
from .process import ExternalProcessBinding, ManagedProcess, ProcessMode


@dataclass(frozen=True)
class ProviderDefinition:
    provider_id: str
    provider_type: str
    endpoint: str
    mode: ProcessMode = ProcessMode.EXTERNAL
    enabled: bool = True
    local_only: bool = True
    process_binding: ExternalProcessBinding | None = None


class ProviderRegistry:
    """Resolve provider adapters without putting provider branches in service code."""

    def __init__(
        self,
        providers: (
            Mapping[str, LLMProvider]
            | Iterator[LLMProvider]
            | list[LLMProvider]
            | tuple[LLMProvider, ...]
        ),
        *,
        definitions: Mapping[str, ProviderDefinition] | None = None,
        process_bindings: Mapping[str, ExternalProcessBinding] | None = None,
    ) -> None:
        if isinstance(providers, Mapping):
            provider_map = dict(providers)
        else:
            provider_map = {}
            for provider in providers:
                if provider.name in provider_map:
                    raise ValueError(f"duplicate provider id: {provider.name}")
                provider_map[provider.name] = provider
        if any(not key for key in provider_map):
            raise ValueError("provider ids must be non-empty")
        self._providers = provider_map
        supplied_definitions = dict(definitions or {})
        supplied_bindings = dict(process_bindings or {})
        self._definitions: dict[str, ProviderDefinition] = {}
        self._managed: dict[str, ManagedProcess] = {}
        for provider_id, provider in self._providers.items():
            definition = supplied_definitions.get(provider_id)
            if definition is None:
                binding = supplied_bindings.get(provider_id)
                endpoint = str(getattr(provider, "base_url", "in-process"))
                mode = binding.mode if binding is not None else ProcessMode.EXTERNAL
                definition = ProviderDefinition(
                    provider_id=provider_id,
                    provider_type=type(provider).__name__,
                    endpoint=endpoint,
                    mode=mode,
                    process_binding=binding,
                )
            elif definition.provider_id != provider_id:
                raise ValueError(f"provider definition key mismatch: {provider_id}")
            self._validate_definition(definition)
            self._definitions[provider_id] = definition
        unknown_definitions = set(supplied_definitions) - set(self._providers)
        if unknown_definitions:
            raise ValueError(f"provider definitions have no adapter: {sorted(unknown_definitions)}")
        unknown_bindings = set(supplied_bindings) - set(self._providers)
        if unknown_bindings:
            raise ValueError(f"process bindings have no adapter: {sorted(unknown_bindings)}")

    def resolve(self, provider_id: str) -> LLMProvider:
        if provider_id not in self._providers:
            raise LLMRuntimeError(
                RuntimeErrorCode.CONFIGURATION_ERROR,
                f"Provider {provider_id!r} is not registered.",
                details={"provider_id": provider_id},
            )
        definition = self._definitions[provider_id]
        if not definition.enabled:
            raise LLMRuntimeError(
                RuntimeErrorCode.PROVIDER_NOT_READY,
                f"Provider {provider_id!r} is disabled.",
                provider=provider_id,
            )
        return self._providers[provider_id]

    def all(self) -> tuple[LLMProvider, ...]:
        return tuple(self._providers.values())

    def definitions(self) -> tuple[ProviderDefinition, ...]:
        return tuple(self._definitions.values())

    def definition(self, provider_id: str) -> ProviderDefinition:
        try:
            return self._definitions[provider_id]
        except KeyError as exc:
            raise LLMRuntimeError(
                RuntimeErrorCode.CONFIGURATION_ERROR,
                f"Provider {provider_id!r} is not registered.",
            ) from exc

    def start_managed(self) -> dict[str, dict[str, Any]]:
        process_metadata: dict[str, dict[str, Any]] = {}
        for provider_id, definition in self._definitions.items():
            if not definition.enabled or definition.mode is not ProcessMode.MANAGED:
                continue
            binding = definition.process_binding
            if binding is None or not binding.command:
                raise LLMRuntimeError(
                    RuntimeErrorCode.CONFIGURATION_ERROR,
                    f"Managed provider {provider_id!r} has no executable command.",
                    provider=provider_id,
                )
            manager = self._managed.get(provider_id)
            if manager is None:
                manager = ManagedProcess(
                    binding.command,
                    cwd=binding.cwd,
                    env=binding.env,
                    stdout_path=binding.stdout_path,
                    stderr_path=binding.stderr_path,
                    endpoint=definition.endpoint,
                )
                self._managed[provider_id] = manager
            manager.start()
            process_metadata[provider_id] = manager.metadata()
        return process_metadata

    def stop_managed(self, *, timeout_seconds: float = 10.0) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        first_error: LLMRuntimeError | None = None
        for provider_id, manager in self._managed.items():
            try:
                manager.stop(timeout_seconds=timeout_seconds)
            except LLMRuntimeError as exc:
                first_error = first_error or exc
            result[provider_id] = manager.metadata()
        if first_error is not None:
            raise first_error
        return result

    def process_health(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for provider_id, definition in self._definitions.items():
            if definition.mode is ProcessMode.MANAGED:
                manager = self._managed.get(provider_id)
                result[provider_id] = manager.metadata() if manager is not None else {
                    "mode": ProcessMode.MANAGED.value,
                    "state": "STOPPED",
                    "owned": True,
                    "endpoint": definition.endpoint,
                }
            else:
                result[provider_id] = {
                    "mode": ProcessMode.EXTERNAL.value,
                    "state": "EXTERNAL",
                    "endpoint": definition.endpoint,
                    "owned": False,
                }
        return result

    def health(self) -> dict[str, ProviderHealth]:
        result: dict[str, ProviderHealth] = {}
        for provider_id, provider in self._providers.items():
            if not self._definitions[provider_id].enabled:
                result[provider_id] = ProviderHealth(
                    provider_id,
                    "pass",
                    "fail",
                    None,
                    self._definitions[provider_id].endpoint,
                    RuntimeErrorCode.PROVIDER_NOT_READY.value,
                    "Provider is disabled.",
                )
                continue
            try:
                result[provider_id] = provider.health_check()
            except Exception as exc:  # provider boundary must not break aggregate health
                result[provider_id] = ProviderHealth(
                    provider_id,
                    "fail",
                    "fail",
                    None,
                    self._definitions[provider_id].endpoint,
                    RuntimeErrorCode.PROVIDER_UNAVAILABLE.value,
                    type(exc).__name__,
                )
        return result

    def close(self, *, timeout_seconds: float = 10.0) -> None:
        first_error: LLMRuntimeError | None = None
        try:
            self.stop_managed(timeout_seconds=timeout_seconds)
        except LLMRuntimeError as exc:
            first_error = exc
        for provider in self._providers.values():
            close = getattr(provider, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as exc:
                    first_error = first_error or LLMRuntimeError(
                        RuntimeErrorCode.PROCESS_STOP_FAILED,
                        "Provider client could not be closed.",
                        details={"exception": type(exc).__name__},
                    )
        if first_error is not None:
            raise first_error

    @staticmethod
    def _validate_definition(definition: ProviderDefinition) -> None:
        if not definition.provider_id:
            raise ValueError("provider definition requires provider_id")
        if not definition.local_only:
            raise ValueError("cloud provider definitions are not permitted")
        if definition.endpoint != "in-process":
            parsed = urlparse(definition.endpoint)
            if (
                parsed.scheme not in {"http", "https"}
                or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            ):
                raise ValueError(
                    "runtime provider endpoints must be loopback HTTP(S) or in-process"
                )
        if definition.mode is ProcessMode.MANAGED and definition.process_binding is None:
            raise ValueError("managed providers require a process binding")


__all__ = [
    "ExternalProcessBinding",
    "ManagedProcess",
    "ModelRegistry",
    "ProcessMode",
    "ProviderDefinition",
    "ProviderRegistry",
]
