"""Hidden-from-frozen-OpenAPI school CAT asset CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from smhai_backend.core.api_models import ApiEnvelope
from smhai_backend.core.errors import ErrorCode, error, problem_responses
from smhai_backend.core.idempotency import fingerprint, request_key
from smhai_backend.core.request_context import current_request_context
from smhai_backend.domains.auth.dependencies import (
    CSRF_SECURITY_OPENAPI_EXTRA,
    CsrfActor,
    CurrentActor,
)
from smhai_backend.domains.cat_assets.schemas import (
    BankCreateRequest,
    BankDetailResponseDto,
    BankListDto,
    BankPatchRequest,
    BankVersionRequest,
    BankVersionResponseDto,
    BankWriteResponseDto,
    PlanCreateRequest,
    PlanDetailResponseDto,
    PlanListDto,
    PlanPatchRequest,
    PlanVersionRequest,
    PlanVersionResponseDto,
    PlanWriteResponseDto,
    SavedSimulationRequestDto,
    SavedSimulationResponseDto,
    TemplateResponseDto,
)

router = APIRouter(prefix="/school/cat-assets", tags=["school-cat-assets"])
_ERRORS = problem_responses(
    ErrorCode.AUTH_SESSION_EXPIRED,
    ErrorCode.FORBIDDEN,
    ErrorCode.RESOURCE_NOT_FOUND,
    ErrorCode.VALIDATION_FAILED,
    ErrorCode.WORKFLOW_CONFLICT,
    ErrorCode.CSRF_FAILED,
    ErrorCode.DEPENDENCY_TIMEOUT,
    ErrorCode.DEPENDENCY_UNAVAILABLE,
    ErrorCode.DEPENDENCY_INVALID_RESPONSE,
)


def _response(request: Request, data, *, status_code: int = 200):
    context = current_request_context(request)
    return JSONResponse(
        status_code=status_code,
        content={
            "request_id": context.request_id,
            "trace_id": context.trace_id,
            "data": jsonable_encoder(data),
        },
    )


def _idempotency(request: Request, actor, operation: str, payload: dict):
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
    return key, fingerprint(payload), scope


def _trace_id(request: Request) -> str:
    return current_request_context(request).trace_id


@router.get("/template", response_model=ApiEnvelope[TemplateResponseDto], responses=_ERRORS)
async def get_template(request: Request, actor: CurrentActor):
    data = await request.app.state.container.cat_assets.template(actor)
    return _response(request, TemplateResponseDto.model_validate(data).model_dump(mode="json"))


@router.get("/banks", response_model=ApiEnvelope[BankListDto], responses=_ERRORS)
async def list_banks(
    request: Request,
    actor: CurrentActor,
    limit: int = Query(default=30, ge=1, le=100),
    skip: int = Query(default=0, ge=0, le=100000),
):
    data = await request.app.state.container.cat_assets.list_banks(actor, limit=limit, skip=skip)
    return _response(request, BankListDto.model_validate(data).model_dump(mode="json"))


@router.post(
    "/banks",
    status_code=201,
    response_model=ApiEnvelope[BankWriteResponseDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def create_bank(request: Request, payload: BankCreateRequest, actor: CsrfActor):
    service = request.app.state.container.cat_assets
    data = await service.create_bank(
        actor,
        payload=payload.model_dump(mode="python"),
        idempotency=_idempotency(
            request, actor, "school_cat_assets:create_bank", payload.model_dump(mode="json")
        ),
        trace_id=_trace_id(request),
    )
    return _response(
        request,
        BankWriteResponseDto.model_validate(data).model_dump(mode="json"),
        status_code=201,
    )


@router.get(
    "/banks/{bank_ref}", response_model=ApiEnvelope[BankDetailResponseDto], responses=_ERRORS
)
async def get_bank(request: Request, bank_ref: str, actor: CurrentActor):
    data = await request.app.state.container.cat_assets.get_bank(actor, bank_ref)
    return _response(request, BankDetailResponseDto.model_validate(data).model_dump(mode="json"))


@router.patch(
    "/banks/{bank_ref}",
    response_model=ApiEnvelope[BankDetailResponseDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def patch_bank(request: Request, bank_ref: str, payload: BankPatchRequest, actor: CsrfActor):
    data = await request.app.state.container.cat_assets.patch_bank(
        actor,
        bank_ref,
        payload=payload.model_dump(mode="python"),
        idempotency=_idempotency(
            request,
            actor,
            f"school_cat_assets:patch_bank:{bank_ref}",
            payload.model_dump(mode="json"),
        ),
        trace_id=_trace_id(request),
    )
    return _response(request, BankDetailResponseDto.model_validate(data).model_dump(mode="json"))


@router.post(
    "/banks/{bank_ref}/versions",
    response_model=ApiEnvelope[BankWriteResponseDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def create_bank_version(
    request: Request, bank_ref: str, payload: BankVersionRequest, actor: CsrfActor
):
    data = await request.app.state.container.cat_assets.create_bank_version(
        actor,
        bank_ref,
        payload=payload.model_dump(mode="python"),
        idempotency=_idempotency(
            request,
            actor,
            f"school_cat_assets:create_bank_version:{bank_ref}",
            payload.model_dump(mode="json"),
        ),
        trace_id=_trace_id(request),
    )
    return _response(request, BankWriteResponseDto.model_validate(data).model_dump(mode="json"))


@router.get(
    "/bank-versions/{version_ref}",
    response_model=ApiEnvelope[BankVersionResponseDto],
    responses=_ERRORS,
)
async def get_bank_version(request: Request, version_ref: str, actor: CurrentActor):
    data = await request.app.state.container.cat_assets.get_bank_version(actor, version_ref)
    return _response(request, BankVersionResponseDto.model_validate(data).model_dump(mode="json"))


@router.get("/plans", response_model=ApiEnvelope[PlanListDto], responses=_ERRORS)
async def list_plans(
    request: Request,
    actor: CurrentActor,
    limit: int = Query(default=30, ge=1, le=100),
    skip: int = Query(default=0, ge=0, le=100000),
):
    data = await request.app.state.container.cat_assets.list_plans(actor, limit=limit, skip=skip)
    return _response(request, PlanListDto.model_validate(data).model_dump(mode="json"))


@router.post(
    "/plans",
    status_code=201,
    response_model=ApiEnvelope[PlanWriteResponseDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def create_plan(request: Request, payload: PlanCreateRequest, actor: CsrfActor):
    data = await request.app.state.container.cat_assets.create_plan(
        actor,
        payload=payload.model_dump(mode="python"),
        idempotency=_idempotency(
            request, actor, "school_cat_assets:create_plan", payload.model_dump(mode="json")
        ),
        trace_id=_trace_id(request),
    )
    return _response(
        request,
        PlanWriteResponseDto.model_validate(data).model_dump(mode="json"),
        status_code=201,
    )


@router.get(
    "/plans/{plan_ref}", response_model=ApiEnvelope[PlanDetailResponseDto], responses=_ERRORS
)
async def get_plan(request: Request, plan_ref: str, actor: CurrentActor):
    data = await request.app.state.container.cat_assets.get_plan(actor, plan_ref)
    return _response(request, PlanDetailResponseDto.model_validate(data).model_dump(mode="json"))


@router.patch(
    "/plans/{plan_ref}",
    response_model=ApiEnvelope[PlanDetailResponseDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def patch_plan(request: Request, plan_ref: str, payload: PlanPatchRequest, actor: CsrfActor):
    data = await request.app.state.container.cat_assets.patch_plan(
        actor,
        plan_ref,
        payload=payload.model_dump(mode="python"),
        idempotency=_idempotency(
            request,
            actor,
            f"school_cat_assets:patch_plan:{plan_ref}",
            payload.model_dump(mode="json"),
        ),
        trace_id=_trace_id(request),
    )
    return _response(request, PlanDetailResponseDto.model_validate(data).model_dump(mode="json"))


@router.post(
    "/plans/{plan_ref}/versions",
    response_model=ApiEnvelope[PlanWriteResponseDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def create_plan_version(
    request: Request, plan_ref: str, payload: PlanVersionRequest, actor: CsrfActor
):
    data = await request.app.state.container.cat_assets.create_plan_version(
        actor,
        plan_ref,
        payload=payload.model_dump(mode="python"),
        idempotency=_idempotency(
            request,
            actor,
            f"school_cat_assets:create_plan_version:{plan_ref}",
            payload.model_dump(mode="json"),
        ),
        trace_id=_trace_id(request),
    )
    return _response(request, PlanWriteResponseDto.model_validate(data).model_dump(mode="json"))


@router.get(
    "/plan-versions/{version_ref}",
    response_model=ApiEnvelope[PlanVersionResponseDto],
    responses=_ERRORS,
)
async def get_plan_version(request: Request, version_ref: str, actor: CurrentActor):
    data = await request.app.state.container.cat_assets.get_plan_version(actor, version_ref)
    return _response(request, PlanVersionResponseDto.model_validate(data).model_dump(mode="json"))


@router.post(
    "/plan-versions/{version_ref}/simulations",
    response_model=ApiEnvelope[SavedSimulationResponseDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def simulate_plan_version(
    request: Request,
    version_ref: str,
    payload: SavedSimulationRequestDto,
    actor: CsrfActor,
):
    data = await request.app.state.container.cat_assets.simulate_plan_version(
        actor, version_ref, payload=payload.model_dump(mode="python")
    )
    return _response(
        request, SavedSimulationResponseDto.model_validate(data).model_dump(mode="json")
    )


__all__ = ["router"]
