"""Actor-guarded orchestration for research-profile catalog and import."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.models import Actor, BackendRole


class SchoolResearchProfilesService:
    def __init__(self, *, persistence: Any, clock=None) -> None:
        if persistence is None:
            raise TypeError("school research profile persistence must be configured")
        self.persistence = persistence
        self._clock = clock or (lambda: datetime.now(UTC))

    async def list_profiles(self, actor: Actor):
        _require_specialist(actor)
        return await self.persistence.list_profiles(actor)

    async def import_profile(
        self,
        actor: Actor,
        profile_ref: str,
        version_number: int,
        *,
        idempotency: tuple[str, str, str],
    ):
        _require_specialist(actor)
        return await self.persistence.import_profile(
            actor,
            profile_ref,
            version_number,
            at=self._clock(),
            idempotency=idempotency,
        )


def _require_specialist(actor: Actor) -> None:
    if (
        actor.scope_profile != "school_tenant"
        or actor.role is not BackendRole.PSYCHOLOGICAL_SPECIALIST
        or type(actor.school_id) is not int
        or actor.school_id <= 0
        or type(actor.school_ref) is not str
        or not actor.school_ref
    ):
        raise error(ErrorCode.FORBIDDEN, detail="access denied")
