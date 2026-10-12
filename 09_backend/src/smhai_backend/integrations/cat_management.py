"""Dedicated bounded HTTP transport for synthetic CAT management."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from smhai_backend.core.config import ModuleClientSettings
from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.request_context import RequestContext
from smhai_backend.domains.cat_management.schemas import (
    CatalogResponseDto,
    SimulationResponseDto,
)

CAT_MANAGEMENT_READ_TIMEOUT_SECONDS = 600.0
_BUSY_DETAIL = "synthetic_cat_simulation_busy"


class HttpCatManagementClient:
    """Dedicated client so management simulations get a bounded 600s read budget."""

    label = "REAL_HTTP"

    def __init__(
        self,
        settings: ModuleClientSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        parsed = urlparse(settings.base_url)
        self.client = httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=httpx.Timeout(
                connect=settings.timeout.connect,
                read=CAT_MANAGEMENT_READ_TIMEOUT_SECONDS,
                write=settings.timeout.write,
                pool=settings.timeout.pool,
            ),
            limits=httpx.Limits(
                max_connections=settings.max_connections,
                max_keepalive_connections=settings.max_keepalive_connections,
            ),
            trust_env=parsed.hostname not in {"localhost", "127.0.0.1", "::1"},
            headers={"Accept": "application/json", "User-Agent": "smhai-backend/0.1.0"},
            transport=transport,
        )

    async def close(self) -> None:
        if not self.client.is_closed:
            await self.client.aclose()

    async def catalog(self, *, context: RequestContext) -> dict[str, Any]:
        value = await self._request("GET", "/internal/cat/management/catalog", context=context)
        return self._project(CatalogResponseDto, value)

    async def simulate(self, n_examinees: int, *, context: RequestContext) -> dict[str, Any]:
        value = await self._request(
            "POST",
            "/internal/cat/management/simulations",
            context=context,
            payload={"n_examinees": n_examinees},
        )
        projected = self._project(SimulationResponseDto, value)
        if projected["n_examinees"] != n_examinees:
            raise self._invalid_response()
        return projected

    async def _request(
        self,
        method: str,
        path: str,
        *,
        context: RequestContext,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {"X-Request-ID": context.request_id, "X-Trace-ID": context.trace_id}
        if context.traceparent:
            headers["traceparent"] = context.traceparent
        try:
            response = await self.client.request(
                method, path, json=dict(payload) if payload is not None else None, headers=headers
            )
        except httpx.TimeoutException as exc:
            raise error(
                ErrorCode.DEPENDENCY_TIMEOUT,
                detail="CAT management request timed out",
                retryable=True,
            ) from exc
        except httpx.TransportError as exc:
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="CAT management service is unavailable",
                retryable=True,
            ) from exc

        if response.status_code == 409:
            try:
                detail = response.json().get("detail")
            except (ValueError, AttributeError):
                detail = None
            if detail == _BUSY_DETAIL:
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail=_BUSY_DETAIL)
            raise self._invalid_response()
        if response.status_code >= 500:
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="CAT management service is unavailable",
                retryable=True,
            )
        if response.status_code >= 400:
            raise self._invalid_response()
        try:
            value = response.json()
        except ValueError as exc:
            raise self._invalid_response() from exc
        if not isinstance(value, dict):
            raise self._invalid_response()
        return value

    @classmethod
    def _project(cls, dto_type, value: Mapping[str, Any]) -> dict[str, Any]:
        try:
            return dto_type.model_validate(value, strict=True).model_dump(mode="json")
        except (ValidationError, TypeError, ValueError) as exc:
            raise cls._invalid_response() from exc

    @staticmethod
    def _invalid_response():
        return error(
            ErrorCode.DEPENDENCY_INVALID_RESPONSE,
            detail="CAT management response is invalid",
        )


__all__ = ["CAT_MANAGEMENT_READ_TIMEOUT_SECONDS", "HttpCatManagementClient"]
