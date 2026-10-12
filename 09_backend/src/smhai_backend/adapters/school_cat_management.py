"""Fresh-role checks and metadata-only audit around external CAT operations."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.request_context import get_request_context
from smhai_backend.domains.cat_management.schemas import (
    CatalogResponseDto,
    SimulationResponseDto,
)
from smhai_backend.domains.models import Actor


class SchoolCatManagementPersistenceAdapter:
    """Keep authorization and success audit in short, separate fresh UOWs."""

    def __init__(self, persistence: Any, client: Any | None) -> None:
        self._persistence = persistence
        self._client = client

    def __getattr__(self, name: str) -> Any:
        return getattr(self._persistence, name)

    async def _authorize(self, actor: Actor) -> int:
        if (
            self.identity_profile != "school_tenant"
            or actor.scope_profile != "school_tenant"
            or getattr(actor.role, "value", actor.role) != "PSYCHOLOGICAL_SPECIALIST"
            or actor.school_id is None
            or actor.school_ref is None
        ):
            raise error(ErrorCode.FORBIDDEN, detail="access denied")
        async with self._uow() as uow:
            account_id, _role_id = await self._school_actor_role(
                uow, actor, "psychological_specialist", self._utc_now()
            )
        return account_id

    async def _call_and_audit(self, actor: Actor, operation: str, *args):
        # Authorization before external work. Never hold a database transaction
        # while the CAT service performs a potentially long CPU simulation.
        await self._authorize(actor)
        if self._client is None:
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="CAT management service is not configured",
                retryable=True,
            )

        context = get_request_context()
        if operation == "catalog_read":
            value = await self._client.catalog(context=context)
        elif operation == "simulation_run":
            value = await self._client.simulate(args[0], context=context)
        else:  # pragma: no cover - internal programming guard
            raise ValueError("unsupported CAT management operation")

        projection = CatalogResponseDto if operation == "catalog_read" else SimulationResponseDto
        try:
            value = projection.model_validate(value, strict=True).model_dump(mode="json")
            if operation == "simulation_run" and value["n_examinees"] != args[0]:
                raise ValueError("sample size mismatch")
        except (ValidationError, TypeError, ValueError) as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="CAT management response is invalid",
            ) from exc

        # Re-resolve the live persisted role and atomically append a safe audit
        # record only after the client has validated the complete projection.
        async with self._uow() as uow:
            account_id, _role_id = await self._school_actor_role(
                uow, actor, "psychological_specialist", self._utc_now()
            )
            await uow.audit.append(
                action=f"school_cat_management.{operation}",
                resource_type="school_cat_management",
                resource_public_id=None,
                result=self._db_enums.AuditResult.SUCCESS,
                trace_id=context.trace_id,
                actor_account_id=account_id,
                safe_metadata={"source": "school_cat_management", "state": "SUCCESS"},
            )
        return value

    async def school_cat_management_catalog(self, actor: Actor) -> dict[str, Any]:
        return await self._call_and_audit(actor, "catalog_read")

    async def school_cat_management_simulate(
        self, actor: Actor, n_examinees: int
    ) -> dict[str, Any]:
        return await self._call_and_audit(actor, "simulation_run", n_examinees)


__all__ = ["SchoolCatManagementPersistenceAdapter"]
