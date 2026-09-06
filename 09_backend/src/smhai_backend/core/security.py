"""Browser mutation protections shared by auth and domain routers."""

from __future__ import annotations

import hashlib
import hmac
from urllib.parse import urlsplit

from fastapi import Request

from .config import BackendSettings
from .errors import ErrorCode, error
from .middleware import request_origin


def credential_identity(value: str) -> str:
    """Hash a credential identifier before it can become a limiter key."""

    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()


def validate_mutation_origin(request: Request, settings: BackendSettings) -> None:
    origin = request_origin(request)
    if origin is not None and origin not in settings.allowed_origins:
        raise error(ErrorCode.CSRF_FAILED, detail="browser origin is not allowed")
    fetch_site = request.headers.get("Sec-Fetch-Site", "").lower()
    if fetch_site == "cross-site":
        raise error(ErrorCode.CSRF_FAILED, detail="cross-site mutation rejected")


def validate_csrf(request: Request, expected: str, settings: BackendSettings) -> None:
    validate_mutation_origin(request, settings)
    supplied = request.headers.get(settings.auth.csrf_header_name)
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise error(ErrorCode.CSRF_FAILED, detail="csrf token is missing or invalid")


def safe_host(value: str) -> str:
    parsed = urlsplit(value if "://" in value else f"http://{value}")
    return parsed.hostname or ""
