"""Native Backend authorization with function, object, and data-scope checks."""

from __future__ import annotations

from typing import Any

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.models import Actor, BackendRole


class NativeAuthorizationProvider:
    """Round 1 policy; relationship storage remains an in-memory adapter."""

    def can(self, actor: Actor, action: str, *, resource: dict[str, Any] | None = None) -> bool:
        resource = resource or {}
        subject_id = resource.get("subject_id")

        if action in {"assessment:create", "assessment:write", "assessment:complete"}:
            return actor.role == BackendRole.STUDENT and (
                subject_id is None or subject_id == actor.subject_id
            )
        if action in {"assessment:read", "report:read", "support:create", "retrieval:create"}:
            if actor.role == BackendRole.STUDENT:
                return subject_id == actor.subject_id
            if actor.role in {BackendRole.TEACHER, BackendRole.REVIEWER, BackendRole.ADMIN}:
                return subject_id in actor.accessible_subject_ids
            return False
        if action == "safety:check":
            return self.can(actor, "assessment:read", resource=resource)
        if action == "review:list" or action == "review:read" or action == "review:action":
            return actor.role in {BackendRole.REVIEWER, BackendRole.ADMIN}
        if action == "teacher:summary":
            return actor.role in {
                BackendRole.TEACHER,
                BackendRole.REVIEWER,
                BackendRole.ADMIN,
            } and (subject_id in actor.accessible_subject_ids)
        return False

    def require(self, actor: Actor, action: str, *, resource: dict[str, Any] | None = None) -> None:
        if not self.can(actor, action, resource=resource):
            raise error(ErrorCode.FORBIDDEN, detail="access denied")
