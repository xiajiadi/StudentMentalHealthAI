"""Psychological-specialist-only routes for candidate research profiles."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from smhai_backend.core.api_models import ApiEnvelope
from smhai_backend.core.errors import ErrorCode, error, problem_responses
from smhai_backend.core.idempotency import fingerprint, request_key
from smhai_backend.core.request_context import current_request_context
from smhai_backend.domains.auth.dependencies import (
    CSRF_SECURITY_OPENAPI_EXTRA,
    CurrentActor,
    require_role,
)
from smhai_backend.domains.models import Actor, BackendRole

from .schemas import (
    ResearchProfileCandidateDto,
    ResearchProfileImportRequest,
    ResearchProfileSimulationEligibilityDto,
    ResearchProfileSimulationEligibilityRequest,
)

router = APIRouter(prefix="/school/research-profiles", tags=["school-research-profiles"])
SpecialistCsrfActor = Annotated[
    Actor, Depends(require_role(BackendRole.PSYCHOLOGICAL_SPECIALIST))
]
_ERRORS = problem_responses(
    ErrorCode.AUTH_SESSION_EXPIRED,
    ErrorCode.FORBIDDEN,
    ErrorCode.CSRF_FAILED,
    ErrorCode.VALIDATION_FAILED,
    ErrorCode.RESOURCE_NOT_FOUND,
    ErrorCode.WORKFLOW_CONFLICT,
    ErrorCode.DEPENDENCY_UNAVAILABLE,
)


def _response(request: Request, value: Any, *, many: bool = False) -> JSONResponse:
    if many:
        data = [
            ResearchProfileCandidateDto.model_validate(item).model_dump(mode="json")
            for item in value
        ]
    else:
        data = ResearchProfileCandidateDto.model_validate(value).model_dump(mode="json")
    context = current_request_context(request)
    return JSONResponse(
        {
            "request_id": context.request_id,
            "trace_id": context.trace_id,
            "data": jsonable_encoder(data),
        }
    )


def _eligibility_response(request: Request, value: Any) -> JSONResponse:
    data = ResearchProfileSimulationEligibilityDto.model_validate(value).model_dump(
        mode="json"
    )
    context = current_request_context(request)
    return JSONResponse(
        {
            "request_id": context.request_id,
            "trace_id": context.trace_id,
            "data": jsonable_encoder(data),
        }
    )


def _require_specialist(actor: Actor) -> None:
    if (
        actor.scope_profile != "school_tenant"
        or actor.role is not BackendRole.PSYCHOLOGICAL_SPECIALIST
        or type(actor.school_id) is not int
        or actor.school_id <= 0
        or type(actor.school_ref) is not str
        or not actor.school_ref
    ):
        raise error(ErrorCode.FORBIDDEN, detail="access denied")


def _configured_service(request: Request) -> Any:
    container = getattr(request.app.state, "container", None)
    service = getattr(container, "school_research_profiles", None)
    if service is None:
        raise error(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            detail="research profile service is not configured",
            retryable=True,
        )
    return service


def _idempotency(
    actor: Actor,
    request: Request,
    payload: ResearchProfileImportRequest,
    *,
    operation: str,
):
    key = request_key(request)
    if key is None:
        raise error(ErrorCode.VALIDATION_FAILED, detail="Idempotency-Key is required")
    scope = fingerprint(
        {
            "actor": actor.user_id,
            "school_id": actor.school_id,
            "school_ref": actor.school_ref,
            "role": actor.role.value,
            "operation": operation,
        }
    )
    body = {"profile_ref": payload.profile_ref, "version_number": payload.version_number}
    return key, fingerprint(body), scope


@router.get(
    "/catalog",
    response_model=ApiEnvelope[list[ResearchProfileCandidateDto]],
    responses=_ERRORS,
)
async def list_research_profile_catalog(request: Request, actor: CurrentActor):
    _require_specialist(actor)
    service = _configured_service(request)
    return _response(request, await service.list_profiles(actor), many=True)


@router.post(
    "/import",
    response_model=ApiEnvelope[ResearchProfileCandidateDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def import_research_profile(
    request: Request,
    actor: SpecialistCsrfActor,
    payload: ResearchProfileImportRequest,
):
    _require_specialist(actor)
    idempotency = _idempotency(
        actor,
        request,
        payload,
        operation="school_research_profiles:import",
    )
    service = _configured_service(request)
    result = await service.import_profile(
        actor,
        payload.profile_ref,
        payload.version_number,
        idempotency=idempotency,
    )
    return _response(request, result)


@router.post(
    "/enable-simulation",
    response_model=ApiEnvelope[ResearchProfileSimulationEligibilityDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def enable_research_profile_simulation(
    request: Request,
    actor: SpecialistCsrfActor,
    payload: ResearchProfileSimulationEligibilityRequest,
):
    _require_specialist(actor)
    idempotency = _idempotency(
        actor,
        request,
        payload,
        operation="school_research_profiles:enable_simulation",
    )
    service = _configured_service(request)
    result = await service.enable_simulation(
        actor,
        payload.profile_ref,
        payload.version_number,
        idempotency=idempotency,
    )
    return _eligibility_response(request, result)
