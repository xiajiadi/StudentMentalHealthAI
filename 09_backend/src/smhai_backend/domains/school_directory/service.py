"""Authorization and input normalization for school-local directory operations."""

from __future__ import annotations

import re

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.domains.school_directory.schemas import AccountImportRow

_SYNTHETIC_LOGIN = re.compile(r"SYNTHETIC_[A-Za-z0-9_]{1,100}\Z")


def validate_import_rows(rows: list[AccountImportRow]) -> list[dict[str, object]]:
    """Return privacy-safe row errors without including submitted field values."""

    errors: list[dict[str, object]] = []
    seen_rows: set[int] = set()
    seen_logins: set[str] = set()
    for row in rows:
        if row.row_no in seen_rows:
            errors.append({"row_no": row.row_no, "code": "DUPLICATE_ROW_NUMBER"})
        seen_rows.add(row.row_no)
        if _SYNTHETIC_LOGIN.fullmatch(row.login_name) is None:
            errors.append({"row_no": row.row_no, "code": "INVALID_LOGIN_NAME"})
        if not row.display_name.strip():
            errors.append({"row_no": row.row_no, "code": "BLANK_DISPLAY_NAME"})
        normalized_login = row.login_name.casefold()
        if normalized_login in seen_logins:
            errors.append({"row_no": row.row_no, "code": "DUPLICATE_LOGIN_NAME"})
        seen_logins.add(normalized_login)
    return errors


class SchoolDirectoryService:
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

    async def get_directory(self, actor: Actor):
        self._require_admin(actor)
        return await self.persistence.school_directory_get(actor)

    async def set_school_name(self, actor: Actor, display_name: str, *, trace_id: str):
        self._require_admin(actor)
        return await self.persistence.school_directory_set_school_name(
            actor, display_name, trace_id=trace_id
        )

    async def set_class_name(
        self, actor: Actor, class_ref: str, display_name: str, *, trace_id: str
    ):
        self._require_admin(actor)
        return await self.persistence.school_directory_set_class_name(
            actor, class_ref, display_name, trace_id=trace_id
        )

    async def set_member_name(
        self, actor: Actor, user_id: str, display_name: str, *, trace_id: str
    ):
        self._require_admin(actor)
        return await self.persistence.school_directory_set_member_name(
            actor, user_id, display_name, trace_id=trace_id
        )

    async def preview_accounts(self, actor: Actor, class_ref: str | None, rows):
        self._require_admin(actor)
        errors = validate_import_rows(rows)
        if errors:
            return {"valid": False, "row_count": len(rows), "errors": errors}
        return await self.persistence.school_directory_preview_accounts(actor, class_ref, rows)

    async def import_accounts(
        self, actor: Actor, class_ref: str | None, rows, *, idempotency, trace_id: str
    ):
        self._require_admin(actor)
        errors = validate_import_rows(rows)
        if errors:
            return {"valid": False, "row_count": len(rows), "errors": errors}
        result = await self.persistence.school_directory_import_accounts(
            actor, class_ref, rows, idempotency=idempotency, trace_id=trace_id
        )
        if "errors" in result:
            return {"valid": False, "row_count": len(rows), "errors": result["errors"]}
        return result

    async def get_batch(self, actor: Actor, batch_ref: str):
        self._require_admin(actor)
        return await self.persistence.school_directory_get_batch(actor, batch_ref)

    async def activate_account(
        self, actor: Actor, user_id: str, new_password: str, *, trace_id: str
    ):
        self._require_admin(actor)
        return await self.persistence.school_directory_activate_account(
            actor, user_id, new_password, trace_id=trace_id
        )
