"""Tenant-proven, metadata-only query over existing audit events."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, exists, or_, select

_ACTION_RESOURCE_CATEGORY: tuple[tuple[str, str, str], ...] = (
    ("school_directory.rename_school", "school", "organization"),
    ("school_directory.rename_class", "school_class", "class"),
    ("school_directory.rename_member", "school_membership", "member"),
    ("school_directory.import_accounts", "school_account_batch", "account_batch"),
    ("school_directory.activate_account", "school_account", "account"),
    ("school_tasks.task.published", "measurement_task", "task"),
)
_ACTION_RESOURCE_PAIRS = frozenset(
    (action, resource_type) for action, resource_type, _ in _ACTION_RESOURCE_CATEGORY
)


class SchoolOperationsAuditPersistenceAdapter:
    """Resolve each audit event through its actual school-owned resource.

    `audit_events` has no tenant key. Actor membership is used only to verify
    the caller; it is never used to infer which school owns an event.
    """

    def __init__(self, persistence: Any) -> None:
        self._persistence = persistence

    def __getattr__(self, name: str) -> Any:
        return getattr(self._persistence, name)

    async def school_operations_audit_list(
        self,
        actor: Any,
        *,
        offset: int,
        limit: int,
        category: str | None,
    ) -> dict[str, object]:
        now = self._utc_now()
        m = self._db_models
        e = m.AuditEvent
        async with self._uow() as uow:
            await self._school_actor_role(uow, actor, "admin", now)
            active_school = exists(
                select(1).where(
                    m.School.id == actor.school_id,
                    m.School.school_ref == actor.school_ref,
                    m.School.status == "ACTIVE",
                    m.School.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                )
            )
            account_owned = exists(
                select(1)
                .select_from(m.SchoolAccountProvision)
                .join(m.Account, m.Account.id == m.SchoolAccountProvision.account_id)
                .where(
                    m.SchoolAccountProvision.school_id == actor.school_id,
                    m.Account.public_id == e.resource_public_id,
                )
            )
            resource_owned = {
                "school": exists(
                    select(1).where(
                        m.School.id == actor.school_id,
                        m.School.school_ref == e.resource_public_id,
                    )
                ),
                "school_class": exists(
                    select(1).where(
                        m.SchoolClass.school_id == actor.school_id,
                        m.SchoolClass.public_id == e.resource_public_id,
                    )
                ),
                "school_membership": exists(
                    select(1).where(
                        m.AccountSchoolMembership.school_id == actor.school_id,
                        m.AccountSchoolMembership.public_id == e.resource_public_id,
                    )
                ),
                "school_account_batch": exists(
                    select(1).where(
                        m.SchoolAccountBatch.school_id == actor.school_id,
                        m.SchoolAccountBatch.batch_ref == e.resource_public_id,
                    )
                ),
                "school_account": account_owned,
                "measurement_task": exists(
                    select(1).where(
                        m.MeasurementTask.school_id == actor.school_id,
                        m.MeasurementTask.task_ref == e.resource_public_id,
                    )
                ),
            }
            clauses = [
                and_(
                    e.action == action,
                    e.resource_type == resource_type,
                    resource_owned[resource_type],
                    category is None or resource_category == category,
                )
                for action, resource_type, resource_category in _ACTION_RESOURCE_CATEGORY
            ]
            statement = (
                select(
                    e.public_id,
                    e.action,
                    e.resource_type,
                    e.result,
                    e.created_at,
                    e.safe_metadata,
                )
                .where(active_school, or_(*clauses))
                .order_by(e.created_at.desc(), e.id.desc())
                .offset(offset)
                .limit(limit + 1)
            )
            result = await uow.session.execute(statement)
            rows = result.all()
        has_more = len(rows) > limit
        items: list[dict[str, object]] = []
        for event_ref, action, resource_type, outcome, created_at, metadata in rows[:limit]:
            if (action, resource_type) not in _ACTION_RESOURCE_PAIRS:
                continue
            if not isinstance(created_at, datetime):
                continue
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            else:
                created_at = created_at.astimezone(UTC)
            count = None
            if action == "school_directory.import_accounts" and type(metadata) is dict:
                raw_count = metadata.get("count")
                if type(raw_count) is int and 1 <= raw_count <= 100:
                    count = raw_count
            items.append(
                {
                    "event_ref": event_ref,
                    "action": action,
                    "result": outcome,
                    "created_at": created_at,
                    "record_count": count,
                }
            )
        return {"items": items, "has_more": has_more}
