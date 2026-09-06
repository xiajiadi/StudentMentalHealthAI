"""Correlation, response-hardening, and browser-origin middleware."""

from __future__ import annotations

from time import perf_counter
from urllib.parse import urlsplit

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from .config import BackendSettings
from .logging import begin_request_logging, logger
from .request_context import make_context, reset_request_context, set_request_context


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, settings: BackendSettings):
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next) -> Response:
        context = make_context(request)
        request.state.request_context = context
        token = set_request_context(context)
        begin_request_logging(
            request_id=context.request_id,
            trace_id=context.trace_id,
            method=request.method,
            route=request.url.path,
        )
        started = perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = context.request_id
            response.headers["X-Trace-ID"] = context.trace_id
            response.headers.setdefault("Cache-Control", "no-store")
            logger().info(
                "request_completed",
                status=response.status_code,
                latency_ms=round((perf_counter() - started) * 1000, 2),
            )
            return response
        finally:
            reset_request_context(token)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, settings: BackendSettings):
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
        if self.settings.is_production:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


def origin_from_header(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def request_origin(request: Request) -> str | None:
    return origin_from_header(request.headers.get("Origin")) or origin_from_header(
        request.headers.get("Referer")
    )
