"""Backend-owned records and actor types.

These records are persistence-neutral. A later Database module can implement
the ports without changing the orchestration contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class BackendRole(StrEnum):
    STUDENT = "STUDENT"
    TEACHER = "TEACHER"
    REVIEWER = "REVIEWER"
    PSYCHOLOGICAL_SPECIALIST = "PSYCHOLOGICAL_SPECIALIST"
    PARENT = "PARENT"
    ADMIN = "ADMIN"


@dataclass(frozen=True, slots=True)
class SchoolRoleContext:
    context_id: str
    role: BackendRole
    school_id: int
    school_ref: str
    accessible_subject_ids: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Actor:
    user_id: str
    username: str
    role: BackendRole
    subject_id: str | None
    accessible_subject_ids: frozenset[str] = frozenset()
    scope_profile: str = "legacy_demo"
    school_id: int | None = None
    school_ref: str | None = None
    authorized_roles: tuple[BackendRole, ...] = ()
    school_contexts: tuple[SchoolRoleContext, ...] = ()


@dataclass(slots=True)
class SyntheticUser:
    user_id: str
    username: str
    role: BackendRole
    subject_id: str | None
    password_hash: str = field(repr=False)
    accessible_subject_ids: frozenset[str] = frozenset()
    scope_profile: str = "legacy_demo"
    school_contexts: tuple[SchoolRoleContext, ...] = ()
    default_context_id: str | None = None

    def actor(self, active_context_id: str | None = None) -> Actor | None:
        contexts = self.school_contexts
        if active_context_id is None and self.default_context_id is not None:
            active_context_id = self.default_context_id
        active_context = next(
            (context for context in contexts if context.context_id == active_context_id), None
        )
        if active_context_id is not None and active_context is None:
            return None
        roles = tuple(dict.fromkeys(context.role for context in contexts))
        if not roles:
            roles = (self.role,)
        subject_id = self.subject_id
        if active_context and active_context.role is BackendRole.STUDENT:
            subject_id = (
                next(iter(active_context.accessible_subject_ids))
                if len(active_context.accessible_subject_ids) == 1
                else None
            )
        scoped_subjects = (
            active_context.accessible_subject_ids
            if active_context
            else frozenset()
            if self.scope_profile == "school_tenant"
            else self.accessible_subject_ids
        )
        return Actor(
            user_id=self.user_id,
            username=self.username,
            role=active_context.role if active_context else self.role,
            subject_id=subject_id,
            accessible_subject_ids=scoped_subjects,
            scope_profile=self.scope_profile,
            school_id=active_context.school_id if active_context else None,
            school_ref=active_context.school_ref if active_context else None,
            authorized_roles=roles,
            school_contexts=contexts,
        )


@dataclass(slots=True)
class SessionRecord:
    session_id: str = field(repr=False)
    user_id: str
    csrf_token: str = field(repr=False)
    created_at: float
    expires_at: float
    last_seen_at: float
    active_context_id: str | None = None


@dataclass(slots=True)
class AssessmentRecord:
    assessment_id: str
    subject_id: str
    assessment: dict[str, Any]
    responses: dict[str, Any] = field(default_factory=dict, repr=False)
    selected_item_id: str | None = None
    current_item: dict[str, Any] | None = None
    current_index: int = 0
    answered_count: int = 0
    administered_count: int = 0
    can_complete: bool = False
    max_items: int | None = None
    cat_provider_version: str | None = None
    cat_item_bank_version: str | None = None
    cat_config_version: str | None = None
    data_origin: str | None = None


@dataclass(slots=True)
class ReportRecord:
    report_id: str
    assessment_id: str
    subject_id: str
    generation_id: str
    status: str
    generation: dict[str, Any]
    review_id: str | None = None
    review_status: str = "not_required"
    safety_action: str = "PROCEED"
    citations: list[dict[str, Any]] = field(default_factory=list)
    candidate_source: str = "MODEL_EXECUTED"


@dataclass(slots=True)
class ReviewProjection:
    review_id: str
    report_id: str
    assessment_id: str
    subject_id: str
    generation_id: str
    status: str
    reason_codes: list[str]
    safety_action: str
    safety_review_case_id: str | None = None
    created_at: str = field(
        default_factory=lambda: (
            datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        )
    )
    updated_at: str = field(
        default_factory=lambda: (
            datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        )
    )


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: str
    event: str
    actor_id: str | None
    request_id: str
    trace_id: str
    occurred_at: str
    outcome: str
    metadata: dict[str, Any]


@dataclass(slots=True)
class IdempotencyRecord:
    fingerprint: str
    status_code: int
    body: dict[str, Any]
    created_at: float
