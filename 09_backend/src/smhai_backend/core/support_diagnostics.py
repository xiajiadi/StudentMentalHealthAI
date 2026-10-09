"""Allowlisted, non-content diagnostics for failed support workflows."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .errors import BackendError, ErrorCode


class SupportDiagnosticStage(StrEnum):
    UNKNOWN = "UNKNOWN"
    NOT_OBSERVED = "NOT_OBSERVED"
    WORKFLOW_REQUESTED = "WORKFLOW_REQUESTED"
    REQUEST_AUTHORIZATION = "REQUEST_AUTHORIZATION"
    INPUT_SAFETY = "INPUT_SAFETY"
    ASSESSMENT_BINDING = "ASSESSMENT_BINDING"
    ASSESSMENT_INTERPRETATION = "ASSESSMENT_INTERPRETATION"
    RAG_RETRIEVAL = "RAG_RETRIEVAL"
    RETRIEVAL_SAFETY = "RETRIEVAL_SAFETY"
    EVIDENCE_BUNDLE = "EVIDENCE_BUNDLE"
    D3_COMPOSITION = "D3_COMPOSITION"
    PROMPT_VALIDATION = "PROMPT_VALIDATION"
    MODEL_POLICY = "MODEL_POLICY"
    LLM_RUNTIME = "LLM_RUNTIME"
    OUTPUT_SAFETY = "OUTPUT_SAFETY"
    CONTENT_VALIDATION = "CONTENT_VALIDATION"
    CLAIM_BOUNDARY = "CLAIM_BOUNDARY"
    CITATION_BINDING = "CITATION_BINDING"
    BLOCKED_RESULT_PROJECTION = "BLOCKED_RESULT_PROJECTION"
    ABSTENTION_RESULT_PROJECTION = "ABSTENTION_RESULT_PROJECTION"
    REPORT_PERSISTENCE = "REPORT_PERSISTENCE"


class SupportDiagnosticComponent(StrEnum):
    UNKNOWN = "UNKNOWN"
    BACKEND = "BACKEND"
    ASSESSMENT = "ASSESSMENT"
    INPUT_SAFETY = "INPUT_SAFETY"
    D3 = "D3"
    RAG = "RAG"
    RETRIEVAL_SAFETY = "RETRIEVAL_SAFETY"
    EVIDENCE = "EVIDENCE"
    LLM_RUNTIME = "LLM_RUNTIME"
    OUTPUT_SAFETY = "OUTPUT_SAFETY"
    DATABASE = "DATABASE"


class SupportDiagnosticFailureCode(StrEnum):
    UNKNOWN = "UNKNOWN"
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


_DIAGNOSTIC_FIELDS = (
    "last_confirmed_stage",
    "failure_stage",
    "failure_code",
    "failure_component",
)
_RUNTIME_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_RUNTIME_DIAGNOSTIC_FIELDS = (
    "runtime_attempt_count",
    "runtime_retry_count",
    "runtime_requested_model_id",
    "runtime_model_id",
    "runtime_hardware_profile",
    "runtime_fallback_attempted",
    "runtime_fallback_count",
)
_RUNTIME_HARDWARE_PROFILES = {"CPU_ONLY", "CONSUMER_GPU", "SERVER_GPU", "UNKNOWN"}


@dataclass(slots=True)
class SupportWorkflowDiagnostics:
    """In-process markers; written only if the existing workflow fails."""

    last_confirmed_stage: SupportDiagnosticStage = SupportDiagnosticStage.UNKNOWN
    _active_stage: SupportDiagnosticStage = SupportDiagnosticStage.NOT_OBSERVED
    _active_component: SupportDiagnosticComponent = SupportDiagnosticComponent.UNKNOWN

    def begin(self, stage: SupportDiagnosticStage, component: SupportDiagnosticComponent) -> None:
        self._active_stage = stage
        self._active_component = component

    def confirm(self) -> None:
        if self._active_stage not in {
            SupportDiagnosticStage.UNKNOWN,
            SupportDiagnosticStage.NOT_OBSERVED,
        }:
            self.last_confirmed_stage = self._active_stage
        self._active_stage = SupportDiagnosticStage.NOT_OBSERVED
        self._active_component = SupportDiagnosticComponent.UNKNOWN

    def failure_metadata(
        self,
        failure_code: SupportDiagnosticFailureCode = SupportDiagnosticFailureCode.UNKNOWN,
    ) -> dict[str, str]:
        return sanitize_support_stage_diagnostics(
            {
                "last_confirmed_stage": self.last_confirmed_stage,
                "failure_stage": self._active_stage,
                "failure_code": failure_code,
                "failure_component": self._active_component,
            }
        )


def failure_code_for_exception(
    exc: BaseException | None = None,
    *,
    code: ErrorCode | None = None,
) -> SupportDiagnosticFailureCode:
    """Expose only a known Backend ErrorCode; never stringify exceptions."""

    candidate = code
    if candidate is None and isinstance(exc, BackendError) and isinstance(exc.code, ErrorCode):
        candidate = exc.code
    if candidate is None:
        return SupportDiagnosticFailureCode.UNKNOWN
    try:
        return SupportDiagnosticFailureCode(candidate.value)
    except ValueError:
        return SupportDiagnosticFailureCode.UNKNOWN


def sanitize_support_stage_diagnostics(values: Mapping[str, object] | None) -> dict[str, Any]:
    """Return fixed stage enums and a complete, validated Runtime attempt projection."""

    values = values or {}
    defaults = {
        "last_confirmed_stage": SupportDiagnosticStage.UNKNOWN.value,
        "failure_stage": SupportDiagnosticStage.NOT_OBSERVED.value,
        "failure_code": SupportDiagnosticFailureCode.UNKNOWN.value,
        "failure_component": SupportDiagnosticComponent.UNKNOWN.value,
    }
    enums = {
        "last_confirmed_stage": SupportDiagnosticStage,
        "failure_stage": SupportDiagnosticStage,
        "failure_code": SupportDiagnosticFailureCode,
        "failure_component": SupportDiagnosticComponent,
    }
    result: dict[str, str] = {}
    for field in _DIAGNOSTIC_FIELDS:
        value = values.get(field)
        try:
            result[field] = enums[field](value).value
        except (TypeError, ValueError):
            result[field] = defaults[field]
    runtime_metadata = _sanitize_runtime_attempt_metadata(values)
    result.update(runtime_metadata)
    return result


def _sanitize_runtime_attempt_metadata(values: Mapping[str, object]) -> dict[str, Any]:
    if not any(field in values for field in _RUNTIME_DIAGNOSTIC_FIELDS):
        return {}
    attempt_count = values.get("runtime_attempt_count")
    retry_count = values.get("runtime_retry_count")
    requested_model = values.get("runtime_requested_model_id")
    actual_model = values.get("runtime_model_id")
    profile = values.get("runtime_hardware_profile")
    fallback_attempted = values.get("runtime_fallback_attempted")
    fallback_count = values.get("runtime_fallback_count")
    if (
        not isinstance(attempt_count, int)
        or isinstance(attempt_count, bool)
        or not 1 <= attempt_count <= 16
        or not isinstance(retry_count, int)
        or isinstance(retry_count, bool)
        or not 0 <= retry_count < attempt_count
        or not isinstance(requested_model, str)
        or not _RUNTIME_MODEL_ID.fullmatch(requested_model)
        or not isinstance(actual_model, str)
        or not _RUNTIME_MODEL_ID.fullmatch(actual_model)
        or not isinstance(profile, str)
        or profile not in _RUNTIME_HARDWARE_PROFILES
        or not isinstance(fallback_attempted, bool)
        or not isinstance(fallback_count, int)
        or isinstance(fallback_count, bool)
        or not 0 <= fallback_count < attempt_count
        or fallback_attempted != (fallback_count > 0)
    ):
        return {}
    return {field: values[field] for field in _RUNTIME_DIAGNOSTIC_FIELDS}


__all__ = [
    "SupportDiagnosticComponent",
    "SupportDiagnosticFailureCode",
    "SupportDiagnosticStage",
    "SupportWorkflowDiagnostics",
    "failure_code_for_exception",
    "sanitize_support_stage_diagnostics",
]
