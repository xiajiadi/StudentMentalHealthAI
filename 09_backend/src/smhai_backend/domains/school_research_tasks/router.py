"""Admin-only endpoint for atomic public-observed research task publication."""

from __future__ import annotations

from typing import Annotated

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
    ResearchTaskBindingOptionDto,
    ResearchTaskPublicationDto,
    ResearchTaskPublishRequest,
)

router = APIRouter(prefix="/school/research-tasks", tags=["school-research-tasks"])
AdminCsrfActor = Annotated[Actor, Depends(require_role(BackendRole.ADMIN))]
_ERRORS = problem_responses(
    ErrorCode.AUTH_SESSION_EXPIRED,
    ErrorCode.FORBIDDEN,
    ErrorCode.CSRF_FAILED,
    ErrorCode.VALIDATION_FAILED,
    ErrorCode.RESOURCE_NOT_FOUND,
    ErrorCode.WORKFLOW_CONFLICT,
    ErrorCode.DEPENDENCY_UNAVAILABLE,
)


def _require_school_admin(actor: Actor) -> None:
    if (
        actor.scope_profile != "school_tenant"
        or actor.role is not BackendRole.ADMIN
        or type(actor.school_id) is not int
        or actor.school_id <= 0
        or type(actor.school_ref) is not str
        or not actor.school_ref
    ):
        raise error(ErrorCode.FORBIDDEN, detail="access denied")


def _service(request: Request):
    container = getattr(request.app.state, "container", None)
    service = getattr(container, "school_research_tasks", None)
    if service is None:
        raise error(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            detail="research task service is not configured",
            retryable=True,
        )
    return service


def _idempotency(actor: Actor, request: Request, payload: ResearchTaskPublishRequest):
    key = request_key(request)
    if key is None:
        raise error(ErrorCode.VALIDATION_FAILED, detail="Idempotency-Key is required")
    scope = fingerprint(
        {
            "actor": actor.user_id,
            "school_id": actor.school_id,
            "school_ref": actor.school_ref,
            "role": actor.role.value,
            "operation": "school_research_tasks:publish",
        }
    )
    body = payload.model_dump(mode="json", exclude_none=True)
    return key, fingerprint(body), scope


def _envelope(request: Request, data: ResearchTaskPublicationDto) -> JSONResponse:
    context = current_request_context(request)
    return JSONResponse(
        {
            "request_id": context.request_id,
            "trace_id": context.trace_id,
            "data": jsonable_encoder(data.model_dump(mode="json")),
        },
        status_code=201,
    )


def _catalog_envelope(
    request: Request, items: tuple[ResearchTaskBindingOptionDto, ...]
) -> JSONResponse:
    context = current_request_context(request)
    return JSONResponse(
        {
            "request_id": context.request_id,
            "trace_id": context.trace_id,
            "data": jsonable_encoder([item.model_dump(mode="json") for item in items]),
        }
    )


@router.get(
    "/catalog",
    response_model=ApiEnvelope[list[ResearchTaskBindingOptionDto]],
    responses=_ERRORS,
)
async def list_research_task_catalog(request: Request, actor: CurrentActor):
    _require_school_admin(actor)
    result = await _service(request).list_catalog(actor)
    return _catalog_envelope(
        request,
        tuple(ResearchTaskBindingOptionDto.model_validate(item) for item in result),
    )


@router.post(
    "/publish",
    status_code=201,
    response_model=ApiEnvelope[ResearchTaskPublicationDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def publish_research_task(
    request: Request,
    actor: AdminCsrfActor,
    payload: ResearchTaskPublishRequest,
):
    _require_school_admin(actor)
    idempotency = _idempotency(actor, request, payload)
    cohort = {} if payload.cohort_ref is None else {"cohort_ref": payload.cohort_ref}
    result = await _service(request).publish_task(
        actor,
        class_ref=payload.class_ref,
        task_ref=payload.task_ref,
        binding_ref=payload.binding_ref,
        profile_version_number=payload.profile_version_number,
        opens_at=payload.opens_at,
        due_at=payload.due_at,
        idempotency=idempotency,
        **cohort,
    )
    return _envelope(request, ResearchTaskPublicationDto.model_validate(result))
