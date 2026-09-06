"""Small HTTP client for future callers such as the 09_backend module.

The client deliberately speaks JSON dictionaries at the module boundary.  It
does not import NeMo, Qwen, Presidio, OPA, or any other implementation type.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import httpx


class SafetyClientError(RuntimeError):
    """A transport or typed service error without echoing submitted content."""

    def __init__(self, code: str, status_code: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class SafetyClient:
    """JSON-only client for the internal loopback Safety Control Plane."""

    def __init__(self, base_url: str = "http://127.0.0.1:8190", *, timeout_seconds: float = 5.0):
        if not base_url.startswith("http://127.0.0.1:"):
            raise ValueError("SafetyClient must use loopback HTTP")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def check_input(self, context: Mapping[str, Any]) -> dict[str, Any]:
        return await self._post("/internal/safety/check-input", {"context": dict(context)})

    async def decide(self, context: Mapping[str, Any]) -> dict[str, Any]:
        return await self._post("/internal/safety/decide", {"context": dict(context)})

    async def check_output(self, context: Mapping[str, Any], candidate_text: str) -> dict[str, Any]:
        return await self._post(
            "/internal/safety/check-output",
            {"context": dict(context), "candidate_text": candidate_text},
        )

    async def check_retrieval(
        self, context: Mapping[str, Any], chunks: Sequence[Mapping[str, Any]]
    ) -> dict[str, Any]:
        return await self._post(
            "/internal/safety/check-retrieval",
            {"context": dict(context), "chunks": [dict(chunk) for chunk in chunks]},
        )

    async def health(self) -> dict[str, Any]:
        return await self._get("/health")

    async def readiness(self) -> dict[str, Any]:
        return await self._get("/health/ready")

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout_seconds
            ) as client:
                response = await client.post(path, json=payload)
        except httpx.HTTPError as exc:
            raise SafetyClientError("SAFETY_SERVICE_UNAVAILABLE") from exc
        return _parse_response(response)

    async def _get(self, path: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout_seconds
            ) as client:
                response = await client.get(path)
        except httpx.HTTPError as exc:
            raise SafetyClientError("SAFETY_SERVICE_UNAVAILABLE") from exc
        return _parse_response(response)


def _parse_response(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise SafetyClientError("SAFETY_SERVICE_UNAVAILABLE", response.status_code) from exc
    if not isinstance(body, dict):
        raise SafetyClientError("SAFETY_SERVICE_UNAVAILABLE", response.status_code)
    if response.is_error:
        error = body.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        raise SafetyClientError(str(code or "SAFETY_SERVICE_UNAVAILABLE"), response.status_code)
    return body
