"""Bounded generation concurrency and cancellation routing."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from ..errors import LLMRuntimeError, RuntimeErrorCode
from ..providers.base import LLMProvider


class GenerationCoordinator:
    """Limit local model work and route cancellation to the active provider."""

    def __init__(self, *, max_concurrency: int = 1, acquire_timeout_seconds: float = 5.0) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if acquire_timeout_seconds <= 0:
            raise ValueError("acquire_timeout_seconds must be positive")
        self.max_concurrency = max_concurrency
        self.acquire_timeout_seconds = acquire_timeout_seconds
        self._slots = threading.BoundedSemaphore(max_concurrency)
        self._active: dict[str, LLMProvider] = {}
        self._lock = threading.RLock()

    @contextmanager
    def slot(self, request_id: str, provider: LLMProvider) -> Iterator[None]:
        acquired = self._slots.acquire(timeout=self.acquire_timeout_seconds)
        if not acquired:
            raise LLMRuntimeError(
                RuntimeErrorCode.RUNTIME_BUSY,
                "The local runtime concurrency limit is currently full.",
                retryable=True,
                status_code=429,
                provider=provider.name,
            )
        with self._lock:
            self._active[request_id] = provider
        try:
            yield
        finally:
            with self._lock:
                self._active.pop(request_id, None)
            self._slots.release()

    def cancel(self, request_id: str) -> bool:
        with self._lock:
            provider = self._active.get(request_id)
        if provider is None:
            return False
        try:
            return bool(provider.cancel(request_id))
        except Exception:
            return False

    def cancel_all(self) -> list[str]:
        with self._lock:
            active = list(self._active.items())
        cancelled: list[str] = []
        for request_id, provider in active:
            try:
                if provider.cancel(request_id):
                    cancelled.append(request_id)
            except Exception:
                continue
        return cancelled

    def active_requests(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._active)


__all__ = ["GenerationCoordinator"]
