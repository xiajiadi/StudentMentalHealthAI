"""Student-scoped read-only orchestration for research discovery."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.models import Actor, BackendRole


class SchoolResearchDiscoveryService:
    def __init__(self, *, persistence: Any, clock=None) -> None:
        if persistence is None:
            raise TypeError("school research discovery persistence must be configured")
        self.persistence = persistence
        self._clock = clock or (lambda: datetime.now(UTC))

    @staticmethod
    def _require_student(actor: Actor) -> None:
        if (
            actor.scope_profile != "school_tenant"
            or actor.role is not BackendRole.STUDENT
            or type(actor.school_id) is not int
            or actor.school_id <= 0
            or type(actor.school_ref) is not str
            or not actor.school_ref
        ):
            raise error(ErrorCode.FORBIDDEN, detail="access denied")

    async def list_tasks(self, actor: Actor, *, limit: int, offset: int):
        self._require_student(actor)
        return await self.persistence.list_tasks(
            actor, limit=limit, offset=offset, at=self._clock()
        )

    async def list_sessions(self, actor: Actor, *, limit: int, offset: int):
        self._require_student(actor)
        return await self.persistence.list_sessions(
            actor, limit=limit, offset=offset, at=self._clock()
        )
