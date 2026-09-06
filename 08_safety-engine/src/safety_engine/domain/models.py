"""Pydantic domain models for the internal Safety Control Plane.

The models are intentionally separate from the frozen root API contracts.  They
carry enough provenance for an auditable engineering decision without placing
raw student content in signals or traces.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import (
    Action,
    ActorRole,
    DisclosurePolicy,
    ReviewStatus,
    SeverityHint,
    SignalSource,
    SignalType,
)

SENSITIVE_KEYS = frozenset(
    {
        "raw_text",
        "raw_content",
        "content",
        "message",
        "prompt",
        "response",
        "candidate_text",
        "matched_text",
        "full_conversation",
        "conversation",
        "transcript",
        "student_name",
        "phone_number",
        "email_address",
        "national_id",
    }
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def digest_text(value: str) -> str:
    """Return a non-reversible content digest for correlation without retention."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _contains_sensitive_key(value: Any, *, path: str = "") -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in SENSITIVE_KEYS:
                return f"{path}.{key}" if path else str(key)
            found = _contains_sensitive_key(child, path=f"{path}.{key}" if path else str(key))
            if found:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _contains_sensitive_key(child, path=f"{path}[{index}]")
            if found:
                return found
    return None


def _safe_metadata(value: dict[str, Any]) -> dict[str, Any]:
    found = _contains_sensitive_key(value)
    if found:
        raise ValueError(f"raw sensitive field is not allowed in safety metadata: {found}")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, str_strip_whitespace=True)


class ComponentHealth(StrictModel):
    component: str
    available: bool
    ready: bool
    version: str | None = None
    detail_code: str | None = None
    checked_at: datetime = Field(default_factory=utc_now)
    latency_ms: float | None = Field(default=None, ge=0)


class SafetySignal(StrictModel):
    """A normalized safety observation, never a final clinical assessment."""

    signal_id: str = Field(default_factory=lambda: new_id("SIG"), min_length=5)
    source: SignalSource
    signal_type: SignalType
    category: str = Field(min_length=1, max_length=120)
    severity_hint: SeverityHint = SeverityHint.UNKNOWN
    confidence: float | None = Field(default=None, ge=0, le=1)
    reason_code: str = Field(min_length=1, max_length=120)
    component: str = Field(min_length=1, max_length=120)
    component_version: str = Field(min_length=1, max_length=120)
    timestamp: datetime = Field(default_factory=utc_now)
    trace_id: str = Field(min_length=1, max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)

    _metadata_is_safe = field_validator("metadata")(_safe_metadata)


class SafetyContext(StrictModel):
    """Input to an internal safety check.

    ``assessment_signals`` are already-produced upstream observations.  The
    Safety Control Plane does not calculate theta, standard error, scores, or
    clinical thresholds from them.
    """

    trace_id: str = Field(min_length=1, max_length=160)
    request_id: str = Field(min_length=1, max_length=160)
    actor_role: ActorRole
    age_group: Literal["CHILD", "ADOLESCENT", "ADULT", "UNKNOWN"] = "UNKNOWN"
    assessment_signals: list[dict[str, Any]] = Field(default_factory=list)
    current_user_message: str = Field(default="", max_length=20_000)
    conversation_metadata: dict[str, Any] = Field(default_factory=dict)
    retrieval_metadata: dict[str, Any] = Field(default_factory=dict)
    generation_metadata: dict[str, Any] = Field(default_factory=dict)
    component_health: dict[str, ComponentHealth] = Field(default_factory=dict)

    @field_validator("assessment_signals")
    @classmethod
    def _assessment_signals_are_safe(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for signal in value:
            _safe_metadata(signal)
        return value

    _conversation_metadata_is_safe = field_validator("conversation_metadata")(_safe_metadata)
    _retrieval_metadata_is_safe = field_validator("retrieval_metadata")(_safe_metadata)
    _generation_metadata_is_safe = field_validator("generation_metadata")(_safe_metadata)


class SafetyDecision(StrictModel):
    """Versioned engineering control decision, explicitly not a diagnosis."""

    decision_id: str = Field(default_factory=lambda: new_id("DEC"), min_length=5)
    action: Action
    reason_codes: list[str] = Field(min_length=1)
    source_signal_ids: list[str] = Field(default_factory=list)
    requires_human: bool
    crisis_template_id: str | None = None
    review_case_id: str | None = None
    disclosure_policy: DisclosurePolicy
    policy_version: str
    policy_revision: str
    safety_service_version: str
    trace_id: str
    timestamp: datetime = Field(default_factory=utc_now)
    decision_type: Literal["ENGINEERING_CONTROL_DECISION"] = "ENGINEERING_CONTROL_DECISION"


class TraceEvent(StrictModel):
    stage: str
    component: str
    outcome: str
    latency_ms: float = Field(ge=0)
    signal_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    _metadata_is_safe = field_validator("metadata")(_safe_metadata)


class SafetyTrace(StrictModel):
    trace_id: str
    request_id: str
    operation: Literal["INPUT", "OUTPUT", "RETRIEVAL"]
    events: list[TraceEvent] = Field(default_factory=list)
    final_action: Action
    action: Action
    signal_count: int = Field(default=0, ge=0)
    signals: list[str] = Field(default_factory=list)
    component_versions: dict[str, str] = Field(default_factory=dict)
    policy_version: str | None = None
    policy_decision_id: str | None = None
    review_case_id: str | None = None
    crisis_template_id: str | None = None
    latencies: dict[str, float] = Field(default_factory=dict)
    failure: bool = False
    degraded: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    trace_version: str = "1.0"


class HumanReviewCase(StrictModel):
    review_case_id: str = Field(default_factory=lambda: new_id("REVIEW"), min_length=8)
    review_id: str | None = None
    case_id: str | None = None
    decision_id: str
    trace_id: str
    status: ReviewStatus = ReviewStatus.PENDING
    reason_codes: list[str] = Field(min_length=1)
    priority: Literal["LOW", "NORMAL", "HIGH", "CRITICAL"] = "HIGH"
    actor_role: ActorRole
    assigned_role: ActorRole | None = None
    disclosure_policy: DisclosurePolicy
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    assigned_reviewer_id: str | None = None
    reviewer_id: str | None = None
    decision: str | None = None
    decision_reason: str | None = None
    audit_event_ids: list[str] = Field(default_factory=list)
    notification_sent: bool = False
    synthetic_fixture_only: bool = True

    @model_validator(mode="after")
    def _mirror_review_identifiers(self) -> HumanReviewCase:
        if self.review_id is None:
            object.__setattr__(self, "review_id", self.review_case_id)
        if self.case_id is None:
            object.__setattr__(self, "case_id", self.review_case_id)
        return self


class ReviewAuditEvent(StrictModel):
    event_id: str = Field(default_factory=lambda: new_id("REVIEW_EVENT"))
    review_case_id: str
    from_status: ReviewStatus | None
    to_status: ReviewStatus
    actor_id: str
    at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    _metadata_is_safe = field_validator("metadata")(_safe_metadata)


class CrisisTemplate(StrictModel):
    template_id: str
    version: str
    language: str
    target_role: ActorRole
    approval_status: Literal["PENDING_PSYCH_REVIEW", "APPROVED", "RETIRED"]
    clinically_approved: bool = False
    content: str = Field(min_length=1, max_length=10_000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    _metadata_is_safe = field_validator("metadata")(_safe_metadata)


def metadata_for_text(value: str) -> dict[str, Any]:
    """Build the only text-related metadata allowed in traces and signals."""

    return {"text_digest": digest_text(value), "text_length": len(value)}


_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,159}$")


def validate_identifier(value: str, field_name: str = "identifier") -> str:
    if not _ID_RE.fullmatch(value):
        raise ValueError(f"invalid {field_name}")
    return value
