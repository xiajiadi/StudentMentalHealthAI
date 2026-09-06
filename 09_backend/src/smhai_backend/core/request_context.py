"""Request and application trace correlation without accepting arbitrary IDs."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from secrets import token_hex

from fastapi import Request

_ID_PATTERN = re.compile(r"^(REQ|TRACE)_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")


@dataclass(frozen=True, slots=True)
class RequestContext:
    request_id: str
    trace_id: str
    traceparent: str | None = None


_current: ContextVar[RequestContext | None] = ContextVar("smhai_request_context", default=None)


def _new(prefix: str) -> str:
    return f"{prefix}_{token_hex(16)}"


def valid_correlation_id(value: str | None, prefix: str) -> str | None:
    if value is None or not _ID_PATTERN.fullmatch(value):
        return None
    if not value.startswith(f"{prefix}_"):
        return None
    return value


def make_context(request: Request) -> RequestContext:
    request_id = valid_correlation_id(request.headers.get("X-Request-ID"), "REQ") or _new("REQ")
    trace_id = valid_correlation_id(request.headers.get("X-Trace-ID"), "TRACE") or _new("TRACE")
    traceparent = request.headers.get("traceparent")
    return RequestContext(request_id=request_id, trace_id=trace_id, traceparent=traceparent)


def set_request_context(context: RequestContext) -> object:
    return _current.set(context)


def reset_request_context(token: object) -> None:
    _current.reset(token)  # type: ignore[arg-type]


def get_request_context() -> RequestContext:
    return _current.get() or RequestContext(_new("REQ"), _new("TRACE"))


def current_request_context(request: Request) -> RequestContext:
    return getattr(request.state, "request_context", None) or get_request_context()


@contextmanager
def bound_context(context: RequestContext) -> Iterator[RequestContext]:
    token = set_request_context(context)
    try:
        yield context
    finally:
        reset_request_context(token)
