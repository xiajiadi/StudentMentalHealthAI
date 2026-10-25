"""Role and tenant checks for school account lifecycle operations."""

from __future__ import annotations

from typing import Any

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.models import Actor, BackendRole


class SchoolAccountLifecycleService:
    def __init__(self, *, persistence: Any | None) -> None:
        self.persistence = persistence

    def _require_store(self) -> Any:
        if self.persistence is None:
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="school account lifecycle persistence is unavailable",
            )
        return self.persistence

    @staticmethod
    def _require_school_role(actor: Actor, role: BackendRole) -> None:
        if (
            actor.scope_profile != "school_tenant"
            or actor.role is not role
            or actor.school_id is None
            or not actor.school_ref
        ):
            raise error(ErrorCode.FORBIDDEN, detail="access denied")

    async def account_summary(self, actor: Actor) -> dict[str, int]:
        self._require_school_role(actor, BackendRole.ADMIN)
        return await self._require_store().account_summary(actor)

    async def create_staff_invitation(
        self, actor: Actor, payload: Any, *, ttl_seconds: int, trace_id: str
    ) -> dict[str, Any]:
        self._require_school_role(actor, BackendRole.ADMIN)
        return await self._require_store().create_staff_invitation(
            actor, payload, ttl_seconds=ttl_seconds, trace_id=trace_id
        )

    async def import_school_staff_roster(
        self, actor: Actor, rows: list[Any], *, ttl_seconds: int, trace_id: str
    ) -> dict[str, Any]:
        self._require_school_role(actor, BackendRole.ADMIN)
        return await self._require_store().import_school_staff_roster(
            actor, rows, ttl_seconds=ttl_seconds, trace_id=trace_id
        )

    async def list_staff_invitations(self, actor: Actor) -> list[dict[str, Any]]:
        self._require_school_role(actor, BackendRole.ADMIN)
        return await self._require_store().list_staff_invitations(actor)

    async def revoke_staff_invitation(
        self,
        actor: Actor,
        invitation_ref: str,
        *,
        reason_code: str,
        trace_id: str,
    ) -> dict[str, str]:
        self._require_school_role(actor, BackendRole.ADMIN)
        return await self._require_store().revoke_staff_invitation(
            actor,
            invitation_ref,
            reason_code=reason_code,
            trace_id=trace_id,
        )

    async def reissue_staff_invitation(
        self,
        actor: Actor,
        invitation_ref: str,
        *,
        reason_code: str,
        ttl_seconds: int,
        trace_id: str,
    ) -> dict[str, Any]:
        self._require_school_role(actor, BackendRole.ADMIN)
        return await self._require_store().reissue_staff_invitation(
            actor,
            invitation_ref,
            reason_code=reason_code,
            ttl_seconds=ttl_seconds,
            trace_id=trace_id,
        )

    async def issue_staff_recovery_credential(
        self,
        actor: Actor,
        user_ref: str,
        *,
        reason_code: str,
        verification_method: str,
        ttl_seconds: int,
        trace_id: str,
    ) -> dict[str, Any]:
        self._require_school_role(actor, BackendRole.ADMIN)
        return await self._require_store().issue_staff_recovery_credential(
            actor,
            user_ref,
            reason_code=reason_code,
            verification_method=verification_method,
            ttl_seconds=ttl_seconds,
            trace_id=trace_id,
        )

    async def accept_staff_invitation(
        self,
        *,
        invitation_ref: str,
        token_hash: bytes,
        new_password: str,
        trace_id: str,
    ) -> dict[str, str]:
        return await self._require_store().accept_staff_invitation(
            invitation_ref=invitation_ref,
            token_hash=token_hash,
            new_password=new_password,
            trace_id=trace_id,
        )

    async def create_recovery_request(self, **kwargs: Any) -> dict[str, str]:
        return await self._require_store().create_recovery_request(**kwargs)

    async def list_recovery_requests(self, actor: Actor) -> list[dict[str, Any]]:
        self._require_school_role(actor, BackendRole.ADMIN)
        return await self._require_store().list_recovery_requests(actor)

    async def verify_recovery_request(
        self, actor: Actor, ticket_ref: str, *, reason_code: str, trace_id: str
    ) -> dict[str, str]:
        self._require_school_role(actor, BackendRole.TEACHER)
        return await self._require_store().verify_recovery_request(
            actor, ticket_ref, reason_code=reason_code, trace_id=trace_id
        )

    async def approve_recovery_request(
        self,
        actor: Actor,
        ticket_ref: str,
        *,
        reason_code: str,
        ttl_seconds: int,
        trace_id: str,
    ) -> dict[str, Any]:
        self._require_school_role(actor, BackendRole.ADMIN)
        return await self._require_store().approve_recovery_request(
            actor,
            ticket_ref,
            reason_code=reason_code,
            ttl_seconds=ttl_seconds,
            trace_id=trace_id,
        )

    async def complete_password_reset(self, **kwargs: Any) -> dict[str, str]:
        return await self._require_store().complete_password_reset(**kwargs)

    async def set_account_status(
        self,
        actor: Actor,
        user_ref: str,
        *,
        status: str,
        reason_code: str,
        trace_id: str,
    ) -> dict[str, str]:
        self._require_school_role(actor, BackendRole.ADMIN)
        return await self._require_store().set_account_status(
            actor,
            user_ref,
            status=status,
            reason_code=reason_code,
            trace_id=trace_id,
        )
