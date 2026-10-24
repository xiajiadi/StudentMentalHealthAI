"""Authorization and input normalization for school-local directory operations."""

from __future__ import annotations

import hashlib
import re
from collections import Counter

from pydantic import SecretStr

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.domains.school_directory.schemas import (
    AccountActivationRequest,
    AccountImportRow,
    SchoolRosterImportRow,
)

_SYNTHETIC_LOGIN = re.compile(r"SYNTHETIC_[A-Za-z0-9_]{1,100}\Z")
_STUDENT_NUMBER = re.compile(r"[A-Z0-9][A-Z0-9_-]{0,63}\Z")
_FORMULA_LIKE_VALUE = re.compile(r"^[\t\r ]*[=+\-@]")


def _roster_class_groups(rows) -> list[dict[str, object]]:
    counts = Counter(row.class_ref for row in rows)
    return [
        {"class_ref": class_ref, "row_count": counts[class_ref]}
        for class_ref in sorted(counts)
    ]


def _decorate_roster_import(result: dict[str, object]) -> dict[str, object]:
    accounts = result.get("accounts")
    if not isinstance(accounts, list):
        return result
    class_refs = [
        account["class_ref"]
        for account in accounts
        if isinstance(account, dict) and isinstance(account.get("class_ref"), str)
    ]
    counts = Counter(class_refs)
    result["class_groups"] = [
        {"class_ref": class_ref, "row_count": counts[class_ref]}
        for class_ref in sorted(counts)
    ]
    row_count = result.get("row_count")
    created_count = result.get("created_count")
    if isinstance(row_count, int) and isinstance(created_count, int):
        result["skipped_count"] = max(0, row_count - created_count)
    return result


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
        elif _FORMULA_LIKE_VALUE.match(row.display_name):
            errors.append({"row_no": row.row_no, "code": "FORMULA_LIKE_VALUE"})
        normalized_login = row.login_name.casefold()
        if normalized_login in seen_logins:
            errors.append({"row_no": row.row_no, "code": "DUPLICATE_LOGIN_NAME"})
        seen_logins.add(normalized_login)
    return errors


def roster_login_name(school_ref: str, student_number: str) -> str:
    """Derive a stable synthetic account name without storing the source identifier."""

    school_slug = re.sub(r"[^A-Za-z0-9_]", "_", school_ref)[:24] or "SCHOOL"
    school_digest = hashlib.sha256(school_ref.encode("utf-8")).hexdigest()[:12]
    student_digest = hashlib.sha256(student_number.encode("utf-8")).hexdigest()[:32]
    return f"SYNTHETIC_ROSTER_{school_slug}_{school_digest}_{student_digest}"


def validate_roster_rows(
    school_ref: str, rows: list[SchoolRosterImportRow]
) -> list[dict[str, object]]:
    """Validate upload rows while returning only row numbers and fixed error codes."""

    errors: list[dict[str, object]] = []
    seen_rows: set[int] = set()
    seen_students: set[str] = set()
    for row in rows:
        if row.row_no in seen_rows:
            errors.append({"row_no": row.row_no, "code": "DUPLICATE_ROW_NUMBER"})
        seen_rows.add(row.row_no)
        student_number = row.student_number
        if _STUDENT_NUMBER.fullmatch(student_number) is None:
            errors.append({"row_no": row.row_no, "code": "INVALID_STUDENT_NUMBER"})
            continue
        if student_number in seen_students:
            errors.append({"row_no": row.row_no, "code": "DUPLICATE_STUDENT_NUMBER"})
        seen_students.add(student_number)
        if not row.display_name.strip():
            errors.append({"row_no": row.row_no, "code": "BLANK_DISPLAY_NAME"})
        elif _FORMULA_LIKE_VALUE.match(row.display_name):
            errors.append({"row_no": row.row_no, "code": "FORMULA_LIKE_VALUE"})
        if len(roster_login_name(school_ref, student_number)) > 112:
            errors.append({"row_no": row.row_no, "code": "INVALID_STUDENT_NUMBER"})
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

    async def preview_roster_import(self, actor: Actor, rows, *, source_sha256: str | None = None):
        self._require_admin(actor)
        assert actor.school_ref is not None
        errors = validate_roster_rows(actor.school_ref, rows)
        if errors:
            return {
                "valid": False,
                "row_count": len(rows),
                "errors": errors,
                "class_groups": _roster_class_groups(rows),
            }
        result = await self.persistence.school_roster_import_preview(
            actor, rows, source_sha256=source_sha256
        )
        result["class_groups"] = _roster_class_groups(rows)
        return result

    async def import_roster(
        self,
        actor: Actor,
        rows,
        *,
        source_sha256: str | None,
        idempotency,
        trace_id: str,
    ):
        self._require_admin(actor)
        assert actor.school_ref is not None
        errors = validate_roster_rows(actor.school_ref, rows)
        if errors:
            return {
                "valid": False,
                "row_count": len(rows),
                "errors": errors,
                "class_groups": _roster_class_groups(rows),
            }
        result = await self.persistence.school_roster_import(
            actor,
            rows,
            source_sha256=source_sha256,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        if "errors" in result:
            result["class_groups"] = _roster_class_groups(rows)
            return result
        return _decorate_roster_import(result)

    async def get_roster_import(self, actor: Actor, run_ref: str):
        self._require_admin(actor)
        return _decorate_roster_import(
            await self.persistence.school_roster_import_get(actor, run_ref)
        )

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

    async def issue_initial_credentials(
        self, actor: Actor, user_ids: list[str], *, ttl_seconds: int, trace_id: str
    ):
        self._require_admin(actor)
        if not 1 <= len(user_ids) <= 200 or len(set(user_ids)) != len(user_ids):
            raise error(ErrorCode.VALIDATION_FAILED, detail="invalid credential targets")
        return await self.persistence.school_directory_issue_initial_credentials(
            actor, user_ids, ttl_seconds=ttl_seconds, trace_id=trace_id
        )

    async def complete_initial_credential(
        self,
        username: str,
        school_ref: str,
        token_hash: bytes,
        new_password: str,
        trace_id: str,
    ):
        validated_password = AccountActivationRequest(
            new_password=SecretStr(new_password)
        ).new_password.get_secret_value()
        return await self.persistence.school_directory_complete_initial_credential(
            username=username,
            school_ref=school_ref,
            token_hash=token_hash,
            new_password=validated_password,
            trace_id=trace_id,
        )
