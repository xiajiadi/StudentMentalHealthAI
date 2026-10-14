"""Admin authorization and clock boundary for cohort sealing."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.models import Actor, BackendRole


class SchoolResearchCohortsService:
    def __init__(self, *, persistence: Any, clock=None) -> None:
        if persistence is None:
            raise TypeError("school research cohort persistence must be configured")
        self.persistence = persistence
        self._clock = clock or (lambda: datetime.now(UTC))

    async def seal_cohort(
        self,
        actor: Actor,
        *,
        binding_ref: str,
        profile_version_number: int,
        batch_refs: tuple[str, ...],
        idempotency: tuple[str, str, str],
    ):
        _require_admin(actor)
        return await self.persistence.seal_cohort(
            actor,
            binding_ref=binding_ref,
            profile_version_number=profile_version_number,
            batch_refs=batch_refs,
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
