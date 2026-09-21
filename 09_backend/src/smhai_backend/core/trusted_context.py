"""Server-derived trusted state for the bounded D3-4 orchestration.

The public HTTP request is an intent and consistency assertion.  It is never
the source of principal, role, relationship, execution mode, or disclosure
authority.  This module keeps that distinction explicit without introducing a
second authentication or policy service.

The capability marker is a process-local boundary.  It prevents an ordinary
mapping or a direct dataclass construction from being accepted by downstream
typed seams; it is deliberately not presented as cryptographic protection
against hostile code already running in this Python process.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4

from smhai_backend.domains.models import Actor, AssessmentRecord, BackendRole

_CAPABILITY = object()
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_SUBJECT_ID = re.compile(r"^SUBJ_[A-Za-z0-9][A-Za-z0-9_.-]*$")


class TrustedContextError(ValueError):
    """Fail-closed error raised while deriving trusted server state."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


class AudienceRole(StrEnum):
    STUDENT_SELF = "STUDENT_SELF"
    TEACHER_SUPPORT = "TEACHER_SUPPORT"
    PARENT_DEMO = "PARENT_DEMO"
    SYSTEM_ADMIN = "SYSTEM_ADMIN"


class TrustedPurpose(StrEnum):
    SELF_UNDERSTANDING = "SELF_UNDERSTANDING"
    EDUCATIONAL_SUPPORT = "EDUCATIONAL_SUPPORT"
    SYNTHETIC_PARENT_DEMO = "SYNTHETIC_PARENT_DEMO"
    NO_PSYCHOLOGY_PURPOSE = "NO_PSYCHOLOGY_PURPOSE"


class TrustedRelationship(StrEnum):
    SELF = "SELF"
    ASSIGNED_SUPPORT = "ASSIGNED_SUPPORT"
    SYNTHETIC_DEMO = "SYNTHETIC_DEMO"
    NONE = "NONE"


class ExecutionMode(StrEnum):
    SYNTHETIC_DEMO = "SYNTHETIC_DEMO"
    REAL_USER = "REAL_USER"


class DisclosureState(StrEnum):
    NOT_AUTHORIZED = "NOT_AUTHORIZED"
    SYNTHETIC_SELF = "SYNTHETIC_SELF"
    SYNTHETIC_SUPPORT = "SYNTHETIC_SUPPORT"
    SYNTHETIC_PARENT_DEMO = "SYNTHETIC_PARENT_DEMO"


@dataclass(frozen=True, slots=True)
class TrustedRequestContext:
    """Immutable authority context produced from server state.

    ``principal_id`` and ``subject_id`` are anonymous project IDs.  The
    context intentionally carries request and trace IDs so accepted D3
    adapters can construct their own typed integration contexts without
    copying caller mappings.
    """

    transaction_id: str
    principal_id: str
    product_role: BackendRole
    subject_id: str
    purpose: TrustedPurpose
    relationship: TrustedRelationship
    execution_mode: ExecutionMode
    disclosure_state: DisclosureState
    request_id: str
    trace_id: str
    context_id: str
    context_version: str = "d3-4.trusted-request-context.v1"
    audience_role: AudienceRole = AudienceRole.STUDENT_SELF
    _capability: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._capability is not _CAPABILITY:
            raise TypeError("TrustedRequestContext is internal-only")
        for name, value in (
            ("transaction_id", self.transaction_id),
            ("principal_id", self.principal_id),
            ("subject_id", self.subject_id),
            ("request_id", self.request_id),
            ("trace_id", self.trace_id),
            ("context_id", self.context_id),
            ("context_version", self.context_version),
        ):
            if not isinstance(value, str) or not value or not _SAFE_ID.fullmatch(value):
                raise TrustedContextError("TRUSTED_CONTEXT_INVALID", f"{name} is invalid")
        if not _SUBJECT_ID.fullmatch(self.subject_id):
            raise TrustedContextError("TRUSTED_CONTEXT_INVALID", "subject_id is invalid")
        for name, enum_type in (
            ("product_role", BackendRole),
            ("purpose", TrustedPurpose),
            ("relationship", TrustedRelationship),
            ("execution_mode", ExecutionMode),
            ("disclosure_state", DisclosureState),
            ("audience_role", AudienceRole),
        ):
            if not isinstance(getattr(self, name), enum_type):
                raise TrustedContextError("TRUSTED_CONTEXT_INVALID", f"{name} is not typed")

    @property
    def relation(self) -> TrustedRelationship:
        """Compatibility alias used by the D3-3 audience vocabulary."""

        return self.relationship

    @property
    def mode(self) -> ExecutionMode:
        return self.execution_mode

    @property
    def disclosure_authorization(self) -> DisclosureState:
        return self.disclosure_state

    @property
    def role(self) -> BackendRole:
        return self.product_role

    @property
    def audience(self) -> AudienceRole:
        return self.audience_role

    def to_dict(self) -> dict[str, str]:
        """Return only safe, non-capability fields for internal audit use."""

        return {
            "transaction_id": self.transaction_id,
            "principal_id": self.principal_id,
            "product_role": self.product_role.value,
            "audience_role": self.audience_role.value,
            "subject_id": self.subject_id,
            "purpose": self.purpose.value,
            "relationship": self.relationship.value,
            "execution_mode": self.execution_mode.value,
            "disclosure_state": self.disclosure_state.value,
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "context_id": self.context_id,
            "context_version": self.context_version,
        }


@dataclass(frozen=True, slots=True)
class TrustedContextPolicy:
    """Server-owned workflow policy used during context derivation."""

    execution_mode: ExecutionMode = ExecutionMode.SYNTHETIC_DEMO
    context_version: str = "d3-4.trusted-request-context.v1"
    allow_real_user: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.execution_mode, ExecutionMode):
            raise TrustedContextError("TRUSTED_CONTEXT_INVALID", "execution_mode is not typed")
        if self.execution_mode is ExecutionMode.REAL_USER and not self.allow_real_user:
            raise TrustedContextError(
                "EXECUTION_MODE_NOT_ALLOWED", "real-user execution is disabled for this slice"
            )
        if not isinstance(self.context_version, str) or not _SAFE_ID.fullmatch(
            self.context_version
        ):
            raise TrustedContextError("TRUSTED_CONTEXT_INVALID", "context_version is invalid")


_GENERIC_PURPOSES = {None, "", "education_support", "EDUCATION_SUPPORT"}
_FORBIDDEN_ASSERTION_FIELDS = {
    "review_status",
    "rights_status",
    "safety_action",
    "population_scope",
    "risk_scope",
    "citation_approved",
    "citation_approval",
    "rights_verified",
}


def _mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dumped
    raise TrustedContextError("TRUSTED_CONTEXT_INVALID", "request must be a mapping-like object")


def _value(value: object) -> object:
    return getattr(value, "value", value)


def _text(value: object, *, name: str) -> str:
    value = _value(value)
    if not isinstance(value, str) or not value.strip():
        raise TrustedContextError("TRUSTED_CONTEXT_INVALID", f"{name} is invalid")
    return value


def _record_assessment(value: Mapping[str, Any] | AssessmentRecord) -> Mapping[str, Any]:
    if isinstance(value, AssessmentRecord):
        assessment = value.assessment
    else:
        assessment = value
    if not isinstance(assessment, Mapping):
        raise TrustedContextError("ASSESSMENT_BINDING_INVALID", "assessment is not a mapping")
    return assessment


def _assertion(request: object | None, *names: str) -> object | None:
    if request is None:
        return None
    value = _mapping(request)
    for name in names:
        if name in value:
            return value[name]
    return None


def _check_caller_assertions(
    request: object | None,
    *,
    target_role: str,
    expected_audience: AudienceRole,
    expected_purpose: TrustedPurpose,
    expected_relation: TrustedRelationship,
    expected_mode: ExecutionMode,
    expected_disclosure: DisclosureState,
    subject_id: str,
    principal_id: str,
) -> None:
    """Validate consistency assertions without treating them as authority."""

    if request is None:
        return
    values = _mapping(request)
    for field_name in _FORBIDDEN_ASSERTION_FIELDS:
        if field_name in values:
            raise TrustedContextError(
                "CALLER_PRIVILEGE_ASSERTION",
                f"caller field {field_name} cannot provide server authority",
            )

    supplied_target = _assertion(request, "target_role", "audience", "audience_role")
    if supplied_target is not None:
        normalized = str(_value(supplied_target)).lower()
        expected_target = {
            AudienceRole.STUDENT_SELF: "student",
            AudienceRole.TEACHER_SUPPORT: "teacher",
            AudienceRole.PARENT_DEMO: "parent",
            AudienceRole.SYSTEM_ADMIN: "admin",
        }[expected_audience]
        if normalized not in {expected_target, expected_audience.value.lower()}:
            raise TrustedContextError(
                "TRUSTED_CONTEXT_MISMATCH", "target role does not match server role"
            )

    supplied_subject = _assertion(request, "subject_id", "student_id")
    if supplied_subject is not None and str(_value(supplied_subject)) != subject_id:
        raise TrustedContextError(
            "SUBJECT_SCOPE_DENIED", "subject assertion does not match assessment"
        )

    supplied_principal = _assertion(request, "principal_id", "user_id", "actor_id")
    if supplied_principal is not None and str(_value(supplied_principal)) != principal_id:
        raise TrustedContextError(
            "TRUSTED_CONTEXT_MISMATCH", "principal assertion does not match session"
        )

    supplied_role = _assertion(request, "role", "product_role")
    if supplied_role is not None:
        normalized = str(_value(supplied_role)).upper()
        if normalized not in {expected_audience.value, expected_audience.name}:
            # A product-role assertion may use the BackendRole value instead
            # of the D3 audience value.  It remains a consistency check only.
            expected_product = {
                AudienceRole.STUDENT_SELF: BackendRole.STUDENT.value,
                AudienceRole.TEACHER_SUPPORT: BackendRole.TEACHER.value,
                AudienceRole.PARENT_DEMO: BackendRole.PARENT.value,
                AudienceRole.SYSTEM_ADMIN: BackendRole.ADMIN.value,
            }[expected_audience]
            if normalized != expected_product:
                raise TrustedContextError(
                    "CALLER_PRIVILEGE_ASSERTION", "role assertion conflicts with session"
                )

    supplied_purpose = _assertion(request, "purpose", "purpose_of_use")
    if supplied_purpose is not None and supplied_purpose not in _GENERIC_PURPOSES:
        if str(_value(supplied_purpose)).upper() != expected_purpose.value:
            raise TrustedContextError("CALLER_PRIVILEGE_ASSERTION", "purpose is server-derived")

    supplied_relation = _assertion(request, "relationship", "relation", "subject_relation")
    if (
        supplied_relation is not None
        and str(_value(supplied_relation)).upper() != expected_relation.value
    ):
        raise TrustedContextError("CALLER_PRIVILEGE_ASSERTION", "relationship is server-derived")

    supplied_mode = _assertion(request, "execution_mode", "mode", "synthetic", "real_user")
    if supplied_mode is not None:
        normalized = str(_value(supplied_mode)).upper()
        if normalized in {"SYNTHETIC", "SYNTHETIC_DEMO", "TRUE"}:
            normalized = ExecutionMode.SYNTHETIC_DEMO.value
        elif normalized in {"REAL", "REAL_USER", "FALSE"}:
            normalized = ExecutionMode.REAL_USER.value
        if normalized != expected_mode.value:
            raise TrustedContextError(
                "CALLER_PRIVILEGE_ASSERTION", "execution mode is server-derived"
            )

    supplied_disclosure = _assertion(
        request,
        "disclosure_state",
        "disclosure_authorized",
        "disclosure_authorization",
    )
    if supplied_disclosure is not None:
        values = _mapping(request)
        if "disclosure_authorized" in values and values["disclosure_authorized"] is True:
            raise TrustedContextError(
                "CALLER_PRIVILEGE_ASSERTION", "disclosure cannot be granted by the caller"
            )
        normalized = str(_value(supplied_disclosure)).upper()
        if isinstance(supplied_disclosure, bool):
            normalized = (
                expected_disclosure.value
                if supplied_disclosure
                else DisclosureState.NOT_AUTHORIZED.value
            )
        if normalized != expected_disclosure.value:
            raise TrustedContextError("CALLER_PRIVILEGE_ASSERTION", "disclosure is server-derived")

    supplied_transaction = _assertion(request, "transaction_id", "context_id")
    if supplied_transaction is not None:
        raise TrustedContextError(
            "CALLER_PRIVILEGE_ASSERTION", "transaction identity is server-derived"
        )


def derive_trusted_request_context(
    actor: Actor,
    assessment: Mapping[str, Any] | AssessmentRecord,
    *,
    request: object | None = None,
    target_role: str | None = None,
    transaction_id: str | None = None,
    request_id: str = "REQ_d3_context",
    trace_id: str = "TRACE_d3_context",
    policy: TrustedContextPolicy | None = None,
) -> TrustedRequestContext:
    """Derive context from the verified session actor and bound assessment.

    The caller may supply intent and consistency assertions through ``request``
    but cannot select any authority field.  The function is deliberately
    synchronous because all inputs are already server-side values; loading the
    assessment record belongs to :mod:`domains.assessment.binding`.
    """

    if not isinstance(actor, Actor):
        raise TrustedContextError("TRUSTED_CONTEXT_REQUIRED", "verified Actor is required")
    assessment_value = _record_assessment(assessment)
    _text(assessment_value.get("assessment_id"), name="assessment_id")
    subject_id = _text(assessment_value.get("subject_id"), name="subject_id")
    if not _SUBJECT_ID.fullmatch(subject_id):
        raise TrustedContextError("ASSESSMENT_BINDING_INVALID", "subject_id is not anonymous")
    if assessment_value.get("status") != "completed":
        raise TrustedContextError("ASSESSMENT_NOT_COMPLETED", "assessment must be completed")
    if actor.role is BackendRole.STUDENT:
        expected_audience = AudienceRole.STUDENT_SELF
        expected_purpose = TrustedPurpose.SELF_UNDERSTANDING
        expected_relation = TrustedRelationship.SELF
        expected_disclosure = DisclosureState.SYNTHETIC_SELF
        if actor.subject_id != subject_id:
            raise TrustedContextError(
                "SUBJECT_SCOPE_DENIED", "student does not own assessment subject"
            )
    elif actor.role is BackendRole.TEACHER:
        expected_audience = AudienceRole.TEACHER_SUPPORT
        expected_purpose = TrustedPurpose.EDUCATIONAL_SUPPORT
        expected_relation = TrustedRelationship.ASSIGNED_SUPPORT
        expected_disclosure = DisclosureState.SYNTHETIC_SUPPORT
        if subject_id not in actor.accessible_subject_ids:
            raise TrustedContextError("SUBJECT_SCOPE_DENIED", "teacher is not assigned to subject")
    elif actor.role is BackendRole.PARENT:
        expected_audience = AudienceRole.PARENT_DEMO
        expected_purpose = TrustedPurpose.SYNTHETIC_PARENT_DEMO
        expected_relation = TrustedRelationship.SYNTHETIC_DEMO
        expected_disclosure = DisclosureState.SYNTHETIC_PARENT_DEMO
        if subject_id not in actor.accessible_subject_ids and actor.subject_id != subject_id:
            raise TrustedContextError(
                "SUBJECT_SCOPE_DENIED", "parent synthetic relationship is not assigned"
            )
    elif actor.role is BackendRole.ADMIN:
        expected_audience = AudienceRole.SYSTEM_ADMIN
        expected_purpose = TrustedPurpose.NO_PSYCHOLOGY_PURPOSE
        expected_relation = TrustedRelationship.NONE
        expected_disclosure = DisclosureState.NOT_AUTHORIZED
        if subject_id not in actor.accessible_subject_ids:
            raise TrustedContextError(
                "SUBJECT_SCOPE_DENIED", "admin has no implicit assessment scope"
            )
    else:
        raise TrustedContextError("FORBIDDEN", "role cannot enter the generation workflow")

    selected_policy = policy or TrustedContextPolicy()
    if (
        actor.role is BackendRole.PARENT
        and selected_policy.execution_mode is ExecutionMode.REAL_USER
    ):
        raise TrustedContextError(
            "EXECUTION_MODE_NOT_ALLOWED",
            "real-user parent disclosure is disabled for this slice",
        )
    expected_mode = selected_policy.execution_mode
    if expected_mode is ExecutionMode.REAL_USER and not selected_policy.allow_real_user:
        raise TrustedContextError("EXECUTION_MODE_NOT_ALLOWED", "real-user mode is disabled")
    if target_role is not None and str(_value(target_role)).lower() not in {
        {
            AudienceRole.STUDENT_SELF: "student",
            AudienceRole.TEACHER_SUPPORT: "teacher",
            AudienceRole.PARENT_DEMO: "parent",
            AudienceRole.SYSTEM_ADMIN: "admin",
        }[expected_audience],
        expected_audience.value.lower(),
    }:
        raise TrustedContextError(
            "TRUSTED_CONTEXT_MISMATCH", "target role does not match server role"
        )

    _check_caller_assertions(
        request,
        target_role=target_role or "",
        expected_audience=expected_audience,
        expected_purpose=expected_purpose,
        expected_relation=expected_relation,
        expected_mode=expected_mode,
        expected_disclosure=expected_disclosure,
        subject_id=subject_id,
        principal_id=actor.user_id,
    )
    transaction = transaction_id or f"TX_{uuid4().hex}"
    context_id = f"CTX_{transaction.removeprefix('TX_')}"
    for name, value in (
        ("transaction_id", transaction),
        ("request_id", request_id),
        ("trace_id", trace_id),
    ):
        if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
            raise TrustedContextError("TRUSTED_CONTEXT_INVALID", f"{name} is invalid")
    return TrustedRequestContext(
        transaction_id=transaction,
        principal_id=actor.user_id,
        product_role=actor.role,
        subject_id=subject_id,
        purpose=expected_purpose,
        relationship=expected_relation,
        execution_mode=expected_mode,
        disclosure_state=expected_disclosure,
        request_id=request_id,
        trace_id=trace_id,
        context_id=context_id,
        context_version=selected_policy.context_version,
        audience_role=expected_audience,
        _capability=_CAPABILITY,
    )


# Names used by the integration workers and tests; all route to the same
# server-derived implementation and do not expose a mapping constructor.
build_trusted_request_context = derive_trusted_request_context
create_trusted_request_context = derive_trusted_request_context


def is_trusted_request_context(value: object) -> bool:
    return isinstance(value, TrustedRequestContext) and value._capability is _CAPABILITY


__all__ = [
    "AudienceRole",
    "DisclosureState",
    "ExecutionMode",
    "TrustedContextError",
    "TrustedContextPolicy",
    "TrustedPurpose",
    "TrustedRelationship",
    "TrustedRequestContext",
    "build_trusted_request_context",
    "create_trusted_request_context",
    "derive_trusted_request_context",
    "is_trusted_request_context",
]
