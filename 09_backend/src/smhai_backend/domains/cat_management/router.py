"""School specialist gateway for synthetic CAT engineering management."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from smhai_backend.core.api_models import ApiEnvelope
from smhai_backend.core.errors import ErrorCode, problem_responses
from smhai_backend.core.request_context import current_request_context
from smhai_backend.domains.auth.dependencies import (
    CSRF_SECURITY_OPENAPI_EXTRA,
    CsrfActor,
    CurrentActor,
)

from .schemas import CatalogResponseDto, SimulationRequestDto, SimulationResponseDto

router = APIRouter(prefix="/school/cat-management", tags=["school-cat-management"])
_ERRORS = problem_responses(
    ErrorCode.AUTH_SESSION_EXPIRED,
    ErrorCode.FORBIDDEN,
    ErrorCode.VALIDATION_FAILED,
    ErrorCode.WORKFLOW_CONFLICT,
    ErrorCode.CSRF_FAILED,
    ErrorCode.DEPENDENCY_TIMEOUT,
    ErrorCode.DEPENDENCY_UNAVAILABLE,
    ErrorCode.DEPENDENCY_INVALID_RESPONSE,
)


def _response(request: Request, data):
    context = current_request_context(request)
    return JSONResponse(
        {
            "request_id": context.request_id,
            "trace_id": context.trace_id,
            "data": jsonable_encoder(data),
        }
    )


@router.get("/catalog", response_model=ApiEnvelope[CatalogResponseDto], responses=_ERRORS)
async def get_catalog(request: Request, actor: CurrentActor):
    data = await request.app.state.container.cat_management.catalog(actor)
    return _response(request, CatalogResponseDto.model_validate(data).model_dump(mode="json"))


@router.post(
    "/simulations",
    response_model=ApiEnvelope[SimulationResponseDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def run_simulation(request: Request, payload: SimulationRequestDto, actor: CsrfActor):
    data = await request.app.state.container.cat_management.simulate(
        actor, n_examinees=payload.n_examinees
    )
    return _response(request, SimulationResponseDto.model_validate(data).model_dump(mode="json"))


__all__ = ["router"]
