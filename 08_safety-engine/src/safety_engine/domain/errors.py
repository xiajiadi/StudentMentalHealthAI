"""Stable fail-closed error vocabulary."""

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    SAFETY_SERVICE_UNAVAILABLE = "SAFETY_SERVICE_UNAVAILABLE"
    POLICY_ENGINE_UNAVAILABLE = "POLICY_ENGINE_UNAVAILABLE"
    POLICY_EVALUATION_FAILED = "POLICY_EVALUATION_FAILED"
    GUARD_MODEL_UNAVAILABLE = "GUARD_MODEL_UNAVAILABLE"
    PRIVACY_ENGINE_UNAVAILABLE = "PRIVACY_ENGINE_UNAVAILABLE"
    GUARDRAIL_CHECK_FAILED = "GUARDRAIL_CHECK_FAILED"
    INVALID_SAFETY_CONTEXT = "INVALID_SAFETY_CONTEXT"
    REVIEW_QUEUE_FAILED = "REVIEW_QUEUE_FAILED"
    CRISIS_TEMPLATE_UNAVAILABLE = "CRISIS_TEMPLATE_UNAVAILABLE"
    RETRIEVAL_SAFETY_CHECK_FAILED = "RETRIEVAL_SAFETY_CHECK_FAILED"
    COMPONENT_UNAVAILABLE = "COMPONENT_UNAVAILABLE"


class SafetyError(RuntimeError):
    """An operational error that must never be converted into an allow decision."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = True,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.details = details or {}


def error_code_from_exception(exc: BaseException, default: ErrorCode) -> ErrorCode:
    """Preserve a known safety error code while normalizing third-party failures."""

    return exc.code if isinstance(exc, SafetyError) else default
