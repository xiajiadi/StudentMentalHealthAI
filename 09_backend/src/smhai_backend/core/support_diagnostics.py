"""Allowlisted, non-content diagnostics for failed support workflows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

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


def sanitize_support_stage_diagnostics(values: Mapping[str, object] | None) -> dict[str, str]:
    """Return exactly the four fixed-enum fields, fail-closed on unknown values."""

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
    return result


__all__ = [
    "SupportDiagnosticComponent",
    "SupportDiagnosticFailureCode",
    "SupportDiagnosticStage",
    "SupportWorkflowDiagnostics",
    "failure_code_for_exception",
    "sanitize_support_stage_diagnostics",
]
