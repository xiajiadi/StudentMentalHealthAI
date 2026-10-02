"""Allowlisted, low-sensitivity projection of product error envelopes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


# Values mirror the Backend LegacyError.code enum. Messages and arbitrary
# extension fields are intentionally excluded from evaluation artifacts.
ERROR_CODE_CATEGORY_BY_CODE = {
    "AUTH_INVALID_CREDENTIALS": "AUTHENTICATION",
    "AUTH_SESSION_EXPIRED": "AUTHENTICATION",
    "AUTH_SESSION_REVOKED": "AUTHENTICATION",
    "CSRF_FAILED": "AUTHORIZATION",
    "FORBIDDEN": "AUTHORIZATION",
    "RESOURCE_NOT_FOUND": "RESOURCE_NOT_FOUND",
    "VALIDATION_FAILED": "VALIDATION",
    "WORKFLOW_CONFLICT": "WORKFLOW_CONFLICT",
    "RATE_LIMITED": "RATE_LIMIT",
    "DEPENDENCY_TIMEOUT": "DEPENDENCY",
    "DEPENDENCY_UNAVAILABLE": "DEPENDENCY",
    "DEPENDENCY_INVALID_RESPONSE": "DEPENDENCY",
    "INTERNAL_ERROR": "INTERNAL",
}

UNKNOWN_ALLOWED_PROJECTION = "UNKNOWN_ALLOWED_PROJECTION"
_SAFETY_ACTIONS = {"CRISIS_ROUTE", "REVIEW_REQUIRED", "PROCEED"}


def response_stage(
    *,
    trace_id: str,
    safety_action: Any,
    safety_correlated: bool = False,
    rag_events: Any,
    llm_events: Any,
) -> str:
    """Return the furthest positively observed stage; absence is UNKNOWN."""

    if _has_correlated_event(llm_events, trace_id):
        return "AFTER_RUNTIME"
    if _has_correlated_event(rag_events, trace_id):
        return "AFTER_RAG"
    if safety_correlated and isinstance(safety_action, str) and safety_action in _SAFETY_ACTIONS:
        return "AFTER_SAFETY"
    return "UNKNOWN"


def _has_correlated_event(value: Any, trace_id: str) -> bool:
    if isinstance(value, Mapping):
        events = (value,)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        events = value
    else:
        return False
    return any(isinstance(event, Mapping) and event.get("trace_id") == trace_id for event in events)


def project_error_evidence(
    *,
    http_status: int,
    response_body: Mapping[str, Any],
    request_id: str,
    trace_id: str,
    safety_action: Any,
    rag_events: Any,
    llm_events: Any,
) -> dict[str, Any] | None:
    """Project only Contract-backed identifiers and allowlisted error fields."""

    if 200 <= http_status < 300:
        return None

    error = response_body.get("error")
    error = error if isinstance(error, Mapping) else {}
    code_present = "code" in error
    raw_code = error.get("code")
    projected = isinstance(raw_code, str) and raw_code in ERROR_CODE_CATEGORY_BY_CODE
    code = raw_code if projected else None
    category = ERROR_CODE_CATEGORY_BY_CODE[raw_code] if projected else UNKNOWN_ALLOWED_PROJECTION

    response_request_id = response_body.get("request_id")
    response_trace_id = response_body.get("trace_id")
    request_id_match = response_request_id == request_id if isinstance(response_request_id, str) else None
    trace_id_match = response_trace_id == trace_id if isinstance(response_trace_id, str) else None
    return {
        "http_status": http_status,
        "error_code_present": code_present,
        "error_code_projected": projected,
        "error_code": code,
        "error_category": category,
        "retryable": error.get("retryable") if isinstance(error.get("retryable"), bool) else None,
        "request_id": request_id,
        "trace_id": trace_id,
        "response_request_id_match": request_id_match,
        "response_trace_id_match": trace_id_match,
        "response_stage": response_stage(
            trace_id=trace_id,
            safety_action=safety_action,
            safety_correlated=request_id_match is True and trace_id_match is True,
            rag_events=rag_events,
            llm_events=llm_events,
        ),
    }
