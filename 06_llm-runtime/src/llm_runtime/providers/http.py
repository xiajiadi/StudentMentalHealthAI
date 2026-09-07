"""Small pooled HTTP client used by local providers.

The accepted provider API is synchronous, so this module keeps that public
shape while making the underlying client lifespan-scoped, proxy-independent
for loopback traffic, finite-timeout and explicitly closeable.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Mapping

import httpx

from ..errors import LLMRuntimeError, RuntimeErrorCode, map_http_error, map_provider_error


@dataclass
class ActiveHTTPStream:
    response: Any
    cancel_event: threading.Event
    context: Any = None
    close_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    closed: bool = False


class LocalHTTPClient:
    def __init__(
        self,
        base_url: str,
        *,
        provider: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.provider = provider
        self.timeout_seconds = timeout_seconds
        self._active: dict[str, ActiveHTTPStream] = {}
        self._lock = threading.Lock()
        self._client = httpx.Client(
            base_url=self.base_url,
            follow_redirects=True,
            trust_env=False,
            timeout=self._timeout(timeout_seconds),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=10),
            headers={
                "Accept": "application/json",
                "User-Agent": "StudentMentalHealthAI-LLMRuntime/0.1.0",
            },
        )

    def request_json(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout: float,
    ) -> dict[str, Any]:
        try:
            response = self._client.request(
                method.upper(),
                path,
                json=payload,
                timeout=self._timeout(timeout),
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise map_http_error(
                exc.response.status_code,
                exc.response.text[:1_048_576],
                provider=self.provider,
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMRuntimeError(
                RuntimeErrorCode.REQUEST_TIMEOUT,
                f"{self.provider} request timed out.",
                retryable=True,
                provider=self.provider,
            ) from exc
        except httpx.TransportError as exc:
            raise map_provider_error(str(exc), provider=self.provider) from exc
        except OSError as exc:
            raise map_provider_error(str(exc), provider=self.provider) from exc
        if not response.content:
            return {}
        try:
            value = response.json()
        except (UnicodeDecodeError, ValueError) as exc:
            raise LLMRuntimeError(
                RuntimeErrorCode.PROVIDER_PROTOCOL_ERROR,
                f"{self.provider} returned invalid JSON.",
                provider=self.provider,
            ) from exc
        if not isinstance(value, dict):
            raise LLMRuntimeError(
                RuntimeErrorCode.PROVIDER_PROTOCOL_ERROR,
                f"{self.provider} returned a non-object JSON response.",
                provider=self.provider,
            )
        return value

    def open_stream(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any],
        *,
        timeout: float,
        request_id: str,
    ) -> ActiveHTTPStream:
        context = self._client.stream(
            method.upper(),
            path,
            json=payload,
            timeout=self._timeout(timeout),
        )
        try:
            response = context.__enter__()
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            context.__exit__(type(exc), exc, exc.__traceback__)
            raise map_http_error(
                exc.response.status_code,
                exc.response.text[:1_048_576],
                provider=self.provider,
            ) from exc
        except httpx.TimeoutException as exc:
            context.__exit__(type(exc), exc, exc.__traceback__)
            raise LLMRuntimeError(
                RuntimeErrorCode.REQUEST_TIMEOUT,
                f"{self.provider} stream timed out before it started.",
                retryable=True,
                provider=self.provider,
            ) from exc
        except httpx.TransportError as exc:
            context.__exit__(type(exc), exc, exc.__traceback__)
            raise map_provider_error(str(exc), provider=self.provider) from exc
        except OSError as exc:
            context.__exit__(type(exc), exc, exc.__traceback__)
            raise map_provider_error(str(exc), provider=self.provider) from exc
        active = ActiveHTTPStream(response=response, cancel_event=threading.Event(), context=context)
        with self._lock:
            self._active[request_id] = active
        return active

    def cancel(self, request_id: str) -> bool:
        with self._lock:
            active = self._active.get(request_id)
        if active is None:
            return False
        active.cancel_event.set()
        self._close_active(active)
        return True

    def close_stream(self, request_id: str, active: ActiveHTTPStream) -> None:
        self._close_active(active)
        with self._lock:
            self._active.pop(request_id, None)

    def close(self) -> None:
        with self._lock:
            active = list(self._active.values())
            self._active.clear()
        for stream in active:
            self._close_active(stream)
        self._client.close()

    @staticmethod
    def _timeout(timeout: float) -> httpx.Timeout:
        bounded = max(float(timeout), 0.001)
        return httpx.Timeout(
            timeout=bounded,
            connect=min(3.0, bounded),
            write=min(30.0, bounded),
            pool=min(5.0, bounded),
        )

    @staticmethod
    def _close_active(active: ActiveHTTPStream) -> None:
        with active.close_lock:
            if active.closed:
                return
            active.closed = True
            try:
                if active.context is not None:
                    active.context.__exit__(None, None, None)
                else:
                    active.response.close()
            except (OSError, RuntimeError, ValueError):
                pass
