"""Authorization and closed projection for school operations audit."""

from __future__ import annotations

from uuid import UUID

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.models import Actor, BackendRole

from .schemas import AuditAction, AuditCategory, SchoolOperationsAuditPageDto

_ACTION_CATEGORY: dict[AuditAction, AuditCategory] = {
    "school_directory.rename_school": "organization",
    "school_directory.rename_class": "class",
    "school_directory.rename_member": "member",
    "school_directory.import_accounts": "account_batch",
    "school_directory.activate_account": "account",
    "school_tasks.task.published": "task",
}


class SchoolOperationsAuditService:
    """Expose only allowlisted school-owned operational events."""

    def __init__(self, *, persistence) -> None:
        self.persistence = persistence

    @staticmethod
    def _require_admin(actor: Actor) -> None:
        if (
            actor.scope_profile != "school_tenant"
            or actor.role is not BackendRole.ADMIN
            or actor.school_id is None
            or not actor.school_ref
        ):
            raise error(ErrorCode.FORBIDDEN, detail="access denied")

    async def list_events(
        self,
        actor: Actor,
        *,
        offset: int = 0,
        limit: int = 25,
        category: AuditCategory | None = None,
    ) -> SchoolOperationsAuditPageDto:
        self._require_admin(actor)
        if type(offset) is not int or not 0 <= offset <= 10_000:
            raise error(ErrorCode.VALIDATION_FAILED, detail="invalid audit page")
        if type(limit) is not int or not 1 <= limit <= 50:
            raise error(ErrorCode.VALIDATION_FAILED, detail="invalid audit page")
        rows = await self.persistence.school_operations_audit_list(
            actor, offset=offset, limit=limit, category=category
        )
        items = []
        for row in rows["items"]:
            action = row.get("action")
            if type(action) is not str or action not in _ACTION_CATEGORY:
                continue
            category_value = _ACTION_CATEGORY[action]
            if category is not None and category_value != category:
                continue
            event_ref = row.get("event_ref")
            try:
                if type(event_ref) is not str or str(UUID(event_ref)) != event_ref:
                    continue
            except ValueError:
                continue
            result = row.get("result")
            if type(result) is not str or result not in {"SUCCESS", "FAILURE", "DENIED"}:
                continue
            count = (
                row.get("record_count") if action == "school_directory.import_accounts" else None
            )
            if count is not None and (type(count) is not int or not 1 <= count <= 100):
                count = None
            items.append(
                {
                    "event_ref": event_ref,
                    "created_at": row.get("created_at"),
                    "action": action,
                    "result": result,
                    "resource_category": category_value,
                    "record_count": count,
                }
            )
        return SchoolOperationsAuditPageDto(
            items=items,
            offset=offset,
            limit=limit,
            has_more=rows["has_more"],
        )
