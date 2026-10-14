"""Admin authorization and clock orchestration for research task publication."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.models import Actor, BackendRole


class SchoolResearchTasksService:
    def __init__(self, *, persistence: Any, clock=None) -> None:
        if persistence is None:
            raise TypeError("school research task persistence must be configured")
        self.persistence = persistence
        self._clock = clock or (lambda: datetime.now(UTC))

    async def list_catalog(self, actor: Actor):
        _require_admin(actor)
        return await self.persistence.list_catalog_options(actor, at=self._clock())

    async def publish_task(
        self,
        actor: Actor,
        *,
        class_ref: str,
        task_ref: str,
        binding_ref: str,
        profile_version_number: int,
        opens_at: datetime,
        due_at: datetime,
        idempotency: tuple[str, str, str],
    ):
        _require_admin(actor)
        return await self.persistence.publish_task(
            actor,
            class_ref=class_ref,
            task_ref=task_ref,
            binding_ref=binding_ref,
            profile_version_number=profile_version_number,
            opens_at=opens_at,
            due_at=due_at,
            at=self._clock(),
            idempotency=idempotency,
        )


def _require_admin(actor: Actor) -> None:
    if (
        actor.scope_profile != "school_tenant"
        or actor.role is not BackendRole.ADMIN
        or type(actor.school_id) is not int
        or actor.school_id <= 0
        or type(actor.school_ref) is not str
        or not actor.school_ref
    ):
        raise error(ErrorCode.FORBIDDEN, detail="access denied")
