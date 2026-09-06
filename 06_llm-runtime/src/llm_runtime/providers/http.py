"""Small standard-library HTTP client used by local providers."""

from __future__ import annotations

import json
import socket
import threading
from dataclasses import dataclass
from http.client import HTTPResponse
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..errors import LLMRuntimeError, RuntimeErrorCode, map_http_error, map_provider_error


@dataclass
class ActiveHTTPStream:
    response: HTTPResponse
    cancel_event: threading.Event


class LocalHTTPClient:
    def __init__(self, base_url: str, *, provider: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.provider = provider
        self._active: dict[str, ActiveHTTPStream] = {}
        self._lock = threading.Lock()

    def request_json(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout: float,
    ) -> dict[str, Any]:
        request = self._build_request(method, path, payload)
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            body = exc.read(1_048_576)
            raise map_http_error(exc.code, body, provider=self.provider) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise LLMRuntimeError(
                RuntimeErrorCode.REQUEST_TIMEOUT,
                f"{self.provider} request timed out.",
                retryable=True,
                provider=self.provider,
            ) from exc
        except (URLError, OSError) as exc:
            raise map_provider_error(str(exc), provider=self.provider) from exc
        if not raw:
            return {}
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LLMRuntimeError(
                RuntimeErrorCode.RUNTIME_ERROR,
                f"{self.provider} returned invalid JSON.",
                provider=self.provider,
            ) from exc
        if not isinstance(value, dict):
            raise LLMRuntimeError(
                RuntimeErrorCode.RUNTIME_ERROR,
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
        request = self._build_request(method, path, payload)
        try:
            response = urlopen(request, timeout=timeout)
        except HTTPError as exc:
            body = exc.read(1_048_576)
            raise map_http_error(exc.code, body, provider=self.provider) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise LLMRuntimeError(
                RuntimeErrorCode.REQUEST_TIMEOUT,
                f"{self.provider} stream timed out before it started.",
                retryable=True,
                provider=self.provider,
            ) from exc
        except (URLError, OSError) as exc:
            raise map_provider_error(str(exc), provider=self.provider) from exc
        active = ActiveHTTPStream(response=response, cancel_event=threading.Event())
        with self._lock:
            self._active[request_id] = active
        return active

    def cancel(self, request_id: str) -> bool:
        with self._lock:
            active = self._active.get(request_id)
        if active is None:
            return False
        active.cancel_event.set()
        try:
            active.response.close()
        except OSError:
            pass
        return True

    def close_stream(self, request_id: str, active: ActiveHTTPStream) -> None:
        try:
            active.response.close()
        except OSError:
            pass
        with self._lock:
            self._active.pop(request_id, None)

    def _build_request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None,
    ) -> Request:
        data = None
        headers = {"Accept": "application/json", "User-Agent": "StudentMentalHealthAI-LLMRuntime/0.1.0"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        return Request(self.base_url + path, data=data, headers=headers, method=method.upper())

