"""Long-lived HTTPX foundation for local module calls."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import httpx

from smhai_backend.core.config import ModuleClientSettings
from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.request_context import RequestContext


class UpstreamError(Exception):
    def __init__(self, code: ErrorCode, *, status_code: int | None = None) -> None:
        super().__init__(code.value)
        self.code = code
        self.status_code = status_code


class LongLivedHttpClient:
    """Own one AsyncClient per dependency and close it during app shutdown."""

    def __init__(self, settings: ModuleClientSettings) -> None:
        parsed = urlparse(settings.base_url)
        self.settings = settings
        self.trust_env = parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        self.client = httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=httpx.Timeout(
                connect=settings.timeout.connect,
                read=settings.timeout.read,
                write=settings.timeout.write,
                pool=settings.timeout.pool,
            ),
            limits=httpx.Limits(
                max_connections=settings.max_connections,
                max_keepalive_connections=settings.max_keepalive_connections,
            ),
            trust_env=False if not self.trust_env else True,
            headers={"Accept": "application/json", "User-Agent": "smhai-backend/0.1.0"},
        )
        self.started = False

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        if not self.client.is_closed:
            await self.client.aclose()
        self.started = False

    async def get_json(
        self, path: str, *, context: RequestContext, headers: Mapping[str, str] | None = None
    ) -> dict[str, Any]:
        return await self._send("GET", path, context=context, headers=headers)

    async def post_json(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        context: RequestContext,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        return await self._send("POST", path, payload=payload, context=context, headers=headers)

    async def _send(
        self,
        method: str,
        path: str,
        *,
        context: RequestContext,
        payload: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        request_headers = {
            "X-Request-ID": context.request_id,
            "X-Trace-ID": context.trace_id,
        }
        if context.traceparent:
            request_headers["traceparent"] = context.traceparent
        if headers:
            request_headers.update(headers)
        try:
            response = await self.client.request(
                method,
                path,
                json=dict(payload) if payload is not None else None,
                headers=request_headers,
            )
        except httpx.TimeoutException as exc:
            raise UpstreamError(ErrorCode.DEPENDENCY_TIMEOUT) from exc
        except httpx.TransportError as exc:
            raise UpstreamError(ErrorCode.DEPENDENCY_UNAVAILABLE) from exc
        if response.status_code >= 500:
            raise UpstreamError(ErrorCode.DEPENDENCY_UNAVAILABLE, status_code=response.status_code)
        if response.status_code >= 400:
            raise UpstreamError(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE, status_code=response.status_code
            )
        try:
            value = response.json()
        except ValueError as exc:
            raise UpstreamError(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE, status_code=response.status_code
            ) from exc
        if not isinstance(value, dict):
            raise UpstreamError(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE, status_code=response.status_code
            )
        return value


def translate_upstream_error(exc: UpstreamError) -> Exception:
    status = {
        ErrorCode.DEPENDENCY_TIMEOUT: 504,
        ErrorCode.DEPENDENCY_UNAVAILABLE: 503,
        ErrorCode.DEPENDENCY_INVALID_RESPONSE: 502,
    }[exc.code]
    return error(
        exc.code,
        status_code=status,
        detail="required dependency could not complete the request",
        retryable=exc.code != ErrorCode.DEPENDENCY_INVALID_RESPONSE,
    )
