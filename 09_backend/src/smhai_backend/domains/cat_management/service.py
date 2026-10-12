"""Authorization and strict projections for synthetic CAT management."""

from __future__ import annotations

from pydantic import ValidationError

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.cat_management.schemas import (
    CatalogResponseDto,
    SimulationRequestDto,
    SimulationResponseDto,
)
from smhai_backend.domains.models import Actor, BackendRole


class SchoolCatManagementService:
    def __init__(self, *, persistence) -> None:
        self.persistence = persistence

    @staticmethod
    def _require_specialist(actor: Actor) -> None:
        if (
            actor.scope_profile != "school_tenant"
            or actor.role is not BackendRole.PSYCHOLOGICAL_SPECIALIST
            or actor.school_id is None
            or actor.school_id <= 0
            or not actor.school_ref
        ):
            raise error(ErrorCode.FORBIDDEN, detail="access denied")

    @staticmethod
    def _project(dto_type, row):
        try:
            return dto_type.model_validate(row, strict=True).model_dump(mode="python")
        except (ValidationError, TypeError, ValueError) as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="CAT management response is invalid",
            ) from exc

    async def catalog(self, actor: Actor):
        self._require_specialist(actor)
        return self._project(
            CatalogResponseDto,
            await self.persistence.school_cat_management_catalog(actor),
        )

    async def simulate(self, actor: Actor, *, n_examinees: int):
        self._require_specialist(actor)
        try:
            request = SimulationRequestDto(n_examinees=n_examinees)
        except ValidationError as exc:
            raise error(ErrorCode.VALIDATION_FAILED, detail="simulation batch is invalid") from exc
        value = await self.persistence.school_cat_management_simulate(actor, request.n_examinees)
        projected = self._project(SimulationResponseDto, value)
        if projected["n_examinees"] != request.n_examinees:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="CAT management response is invalid",
            )
        return projected


__all__ = ["SchoolCatManagementService"]
