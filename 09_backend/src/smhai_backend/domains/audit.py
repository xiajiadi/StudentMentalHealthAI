"""Awaited, metadata-only audit events."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from smhai_backend.core.async_utils import maybe_await
from smhai_backend.domains.models import Actor, AuditEvent
from smhai_backend.domains.ports import AuditRepository


class AuditService:
    def __init__(self, repository: AuditRepository) -> None:
        self.repository = repository

    async def record(
        self,
        *,
        event: str,
        actor: Actor | None,
        request_id: str,
        trace_id: str,
        outcome: str,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent:
        audit = AuditEvent(
            event_id=f"AUDIT_{uuid4().hex}",
            event=event,
            actor_id=actor.user_id if actor else None,
            request_id=request_id,
            trace_id=trace_id,
            occurred_at=datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            outcome=outcome,
            metadata=dict(metadata or {}),
        )
        await maybe_await(self.repository.append(audit))
        return audit
