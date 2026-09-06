"""RFC 9457 Problem Details for the provisional Backend API."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from .logging import logger
from .request_context import current_request_context


class ErrorCode(StrEnum):
    AUTH_INVALID_CREDENTIALS = "auth_invalid_credentials"
    AUTH_SESSION_EXPIRED = "auth_session_expired"
    AUTH_SESSION_REVOKED = "auth_session_revoked"
    CSRF_FAILED = "csrf_failed"
    FORBIDDEN = "forbidden"
    RESOURCE_NOT_FOUND = "resource_not_found"
    VALIDATION_FAILED = "validation_failed"
    WORKFLOW_CONFLICT = "workflow_conflict"
    RATE_LIMITED = "rate_limited"
    DEPENDENCY_TIMEOUT = "dependency_timeout"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    DEPENDENCY_INVALID_RESPONSE = "dependency_invalid_response"
    INTERNAL_ERROR = "internal_error"


_TITLES: dict[ErrorCode, str] = {
    ErrorCode.AUTH_INVALID_CREDENTIALS: "Authentication failed",
    ErrorCode.AUTH_SESSION_EXPIRED: "Authentication required",
    ErrorCode.AUTH_SESSION_REVOKED: "Session revoked",
    ErrorCode.CSRF_FAILED: "CSRF validation failed",
    ErrorCode.FORBIDDEN: "Forbidden",
    ErrorCode.RESOURCE_NOT_FOUND: "Resource not found",
    ErrorCode.VALIDATION_FAILED: "Request validation failed",
    ErrorCode.WORKFLOW_CONFLICT: "Workflow conflict",
    ErrorCode.RATE_LIMITED: "Rate limit exceeded",
    ErrorCode.DEPENDENCY_TIMEOUT: "Dependency timeout",
    ErrorCode.DEPENDENCY_UNAVAILABLE: "Dependency unavailable",
    ErrorCode.DEPENDENCY_INVALID_RESPONSE: "Dependency response invalid",
    ErrorCode.INTERNAL_ERROR: "Internal server error",
}


_STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.AUTH_INVALID_CREDENTIALS: 401,
    ErrorCode.AUTH_SESSION_EXPIRED: 401,
    ErrorCode.AUTH_SESSION_REVOKED: 401,
    ErrorCode.CSRF_FAILED: 403,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.RESOURCE_NOT_FOUND: 404,
    ErrorCode.VALIDATION_FAILED: 422,
    ErrorCode.WORKFLOW_CONFLICT: 409,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.DEPENDENCY_TIMEOUT: 504,
    ErrorCode.DEPENDENCY_UNAVAILABLE: 503,
    ErrorCode.DEPENDENCY_INVALID_RESPONSE: 502,
    ErrorCode.INTERNAL_ERROR: 500,
}


class ProblemFieldError(BaseModel):
    """Safe, typed validation detail without echoing submitted values."""

    model_config = ConfigDict(extra="ignore")

    loc: list[str | int] = Field(min_length=1)
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class LegacyError(BaseModel):
    """Typed compatibility projection retained for existing API consumers."""

    model_config = ConfigDict(extra="ignore")

    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$")
    message: str = Field(min_length=1)
    retryable: bool


class ProblemDetails(BaseModel):
    """RFC 9457 problem projection used by every Backend error path."""

    model_config = ConfigDict(extra="ignore")

    type: str
    title: str
    status: int
    detail: str
    instance: str | None
    code: str
    retryable: bool
    request_id: str
    trace_id: str
    error: LegacyError
    errors: list[ProblemFieldError] | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=False)


class BackendError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        *,
        status_code: int | None = None,
        detail: str | None = None,
        retryable: bool = False,
        retry_after: int | None = None,
        field_errors: list[ProblemFieldError] | None = None,
    ) -> None:
        self.code = code
        self.status_code = status_code or _STATUS_BY_CODE[code]
        self.detail = detail or _TITLES[code]
        self.retryable = retryable
        self.retry_after = retry_after
        self.field_errors = field_errors
        super().__init__(code.value)


def error(
    code: ErrorCode,
    *,
    status_code: int | None = None,
    detail: str | None = None,
    retryable: bool = False,
    retry_after: int | None = None,
    field_errors: list[ProblemFieldError] | None = None,
) -> BackendError:
    return BackendError(
        code,
        status_code=status_code,
        detail=detail,
        retryable=retryable,
        retry_after=retry_after,
        field_errors=field_errors,
    )


def problem_response(request: Request, exc: BackendError) -> JSONResponse:
    context = current_request_context(request)
    problem = ProblemDetails(
        type=f"urn:smhai:problem:{exc.code.value}",
        title=_TITLES[exc.code],
        code=exc.code,
        status=exc.status_code,
        detail=exc.detail,
        instance=None,
        request_id=context.request_id,
        trace_id=context.trace_id,
        retryable=exc.retryable,
        error=LegacyError(
            code=exc.code.value.upper(),
            message=exc.detail,
            retryable=exc.retryable,
        ),
        errors=exc.field_errors,
    )
    headers = {"Cache-Control": "no-store"}
    if exc.retry_after is not None:
        headers["Retry-After"] = str(exc.retry_after)
    return JSONResponse(
        status_code=exc.status_code,
        content=problem.as_dict(),
        media_type="application/problem+json",
        headers=headers,
    )


async def backend_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, BackendError):
        return problem_response(request, exc)
    return problem_response(
        request, error(ErrorCode.INTERNAL_ERROR, detail="internal server error")
    )


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    field_errors: list[ProblemFieldError] = []
    if isinstance(exc, RequestValidationError):
        for item in exc.errors():
            location = [
                str(part) if not isinstance(part, int) else part for part in item.get("loc", ())
            ]
            field_errors.append(
                ProblemFieldError(
                    loc=location or ["request"],
                    code=str(item.get("type", "invalid")),
                    message=str(item.get("msg", "request value is invalid")),
                )
            )
    return problem_response(
        request,
        error(
            ErrorCode.VALIDATION_FAILED,
            detail="request validation failed",
            field_errors=field_errors or None,
        ),
    )


def problem_responses(*codes: ErrorCode) -> dict[int | str, dict[str, Any]]:
    """Build OpenAPI response documentation from the single runtime model."""

    selected = list(dict.fromkeys((ErrorCode.VALIDATION_FAILED, *codes)))
    responses: dict[int | str, dict[str, Any]] = {}
    for code in selected:
        status = _STATUS_BY_CODE[code]
        responses[status] = {
            "model": ProblemDetails,
            "description": _TITLES[code],
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ProblemDetails"}
                }
            },
        }
    responses.setdefault(
        400,
        {
            "model": ProblemDetails,
            "description": "Malformed request",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ProblemDetails"}
                }
            },
        },
    )
    return responses


async def http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        return problem_response(
            request,
            error(ErrorCode.INTERNAL_ERROR, detail="internal server error"),
        )
    if exc.status_code == 404:
        backend_exc = error(ErrorCode.RESOURCE_NOT_FOUND, detail="resource not found")
    elif exc.status_code == 405:
        backend_exc = error(
            ErrorCode.VALIDATION_FAILED,
            status_code=405,
            detail="method not allowed",
        )
    else:
        backend_exc = error(
            ErrorCode.VALIDATION_FAILED,
            status_code=exc.status_code,
            detail="request could not be processed",
        )
    response = problem_response(request, backend_exc)
    if exc.headers:
        for name, value in exc.headers.items():
            response.headers[name] = value
    return response


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger().error("unhandled_exception", exception_type=type(exc).__name__)
    del exc
    return problem_response(
        request,
        error(ErrorCode.INTERNAL_ERROR, detail="internal server error"),
    )
