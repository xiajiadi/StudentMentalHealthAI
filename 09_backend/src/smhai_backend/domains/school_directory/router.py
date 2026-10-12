"""Module-local school directory endpoints outside frozen shared OpenAPI."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from smhai_backend.core.api_models import ApiEnvelope
from smhai_backend.core.errors import ErrorCode, problem_responses
from smhai_backend.core.idempotency import fingerprint, request_key
from smhai_backend.core.request_context import current_request_context
from smhai_backend.domains.auth.dependencies import (
    CSRF_SECURITY_OPENAPI_EXTRA,
    CsrfActor,
    CurrentActor,
)

from .schemas import (
    AccountActivationRequest,
    AccountBatchDto,
    AccountBatchRequest,
    AccountImportPreviewDto,
    DisplayNameRequest,
    SchoolDirectoryDto,
)

router = APIRouter(prefix="/school/admin", tags=["school-directory"])


def _envelope(request: Request, data):
    context = current_request_context(request)
    value = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
    return {
        "request_id": context.request_id,
        "trace_id": context.trace_id,
        "data": jsonable_encoder(value),
    }


def _trace_id(request: Request) -> str:
    return current_request_context(request).trace_id


def _responses(*codes):
    return problem_responses(*codes)


@router.get(
    "/directory",
    response_model=ApiEnvelope[SchoolDirectoryDto],
    responses=_responses(ErrorCode.AUTH_SESSION_EXPIRED, ErrorCode.FORBIDDEN),
)
async def get_directory(request: Request, actor: CurrentActor):
    result = await request.app.state.container.school_directory.get_directory(actor)
    return JSONResponse(_envelope(request, SchoolDirectoryDto.model_validate(result)))


@router.post(
    "/school/name",
    response_model=ApiEnvelope[dict],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_responses(
        ErrorCode.AUTH_SESSION_EXPIRED, ErrorCode.FORBIDDEN, ErrorCode.CSRF_FAILED
    ),
)
async def set_school_name(request: Request, payload: DisplayNameRequest, actor: CsrfActor):
    result = await request.app.state.container.school_directory.set_school_name(
        actor, payload.display_name, trace_id=_trace_id(request)
    )
    return JSONResponse(_envelope(request, result))


@router.post(
    "/classes/{class_ref}/name",
    response_model=ApiEnvelope[dict],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_responses(
        ErrorCode.AUTH_SESSION_EXPIRED, ErrorCode.FORBIDDEN, ErrorCode.CSRF_FAILED,
        ErrorCode.RESOURCE_NOT_FOUND,
    ),
)
async def set_class_name(
    request: Request, class_ref: str, payload: DisplayNameRequest, actor: CsrfActor
):
    result = await request.app.state.container.school_directory.set_class_name(
        actor, class_ref, payload.display_name, trace_id=_trace_id(request)
    )
    return JSONResponse(_envelope(request, result))


@router.post(
    "/members/{user_id}/name",
    response_model=ApiEnvelope[dict],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_responses(
        ErrorCode.AUTH_SESSION_EXPIRED, ErrorCode.FORBIDDEN, ErrorCode.CSRF_FAILED,
        ErrorCode.RESOURCE_NOT_FOUND,
    ),
)
async def set_member_name(
    request: Request, user_id: str, payload: DisplayNameRequest, actor: CsrfActor
):
    result = await request.app.state.container.school_directory.set_member_name(
        actor, user_id, payload.display_name, trace_id=_trace_id(request)
    )
    return JSONResponse(_envelope(request, result))


def _batch_idempotency(actor, key: str, request_payload: dict[str, object]):
    operation_scope = fingerprint(
        {
            "actor": actor.user_id,
            "school_id": actor.school_id,
            "school_ref": actor.school_ref,
            "role": actor.role.value,
            "operation": "school_directory:account_import",
        }
    )
    return key, fingerprint(request_payload), operation_scope


@router.post(
    "/accounts/preview",
    response_model=ApiEnvelope[AccountImportPreviewDto],
    responses=_responses(ErrorCode.AUTH_SESSION_EXPIRED, ErrorCode.FORBIDDEN),
)
async def preview_accounts(request: Request, payload: AccountBatchRequest, actor: CurrentActor):
    result = await request.app.state.container.school_directory.preview_accounts(
        actor, payload.class_ref, payload.rows
    )
    return JSONResponse(_envelope(request, AccountImportPreviewDto.model_validate(result)))


@router.post(
    "/accounts/import",
    response_model=ApiEnvelope[AccountBatchDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_responses(
        ErrorCode.AUTH_SESSION_EXPIRED, ErrorCode.FORBIDDEN, ErrorCode.CSRF_FAILED,
        ErrorCode.VALIDATION_FAILED, ErrorCode.WORKFLOW_CONFLICT,
        ErrorCode.RESOURCE_NOT_FOUND,
    ),
)
async def import_accounts(request: Request, payload: AccountBatchRequest, actor: CsrfActor):
    key = request_key(request)
    if key is None:
        from smhai_backend.core.errors import error

        raise error(ErrorCode.VALIDATION_FAILED, detail="Idempotency-Key is required")
    result = await request.app.state.container.school_directory.import_accounts(
        actor,
        payload.class_ref,
        payload.rows,
        idempotency=_batch_idempotency(actor, key, payload.model_dump(mode="json")),
        trace_id=_trace_id(request),
    )
    if "errors" in result:
        preview = AccountImportPreviewDto.model_validate(result)
        return JSONResponse(_envelope(request, preview), status_code=409)
    return JSONResponse(_envelope(request, AccountBatchDto.model_validate(result)), status_code=201)


@router.get(
    "/accounts/batches/{batch_ref}",
    response_model=ApiEnvelope[AccountBatchDto],
    responses=_responses(
        ErrorCode.AUTH_SESSION_EXPIRED, ErrorCode.FORBIDDEN, ErrorCode.RESOURCE_NOT_FOUND
    ),
)
async def get_account_batch(request: Request, batch_ref: str, actor: CurrentActor):
    result = await request.app.state.container.school_directory.get_batch(actor, batch_ref)
    return JSONResponse(_envelope(request, AccountBatchDto.model_validate(result)))


@router.post(
    "/accounts/{user_id}/activate",
    response_model=ApiEnvelope[dict],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_responses(
        ErrorCode.AUTH_SESSION_EXPIRED, ErrorCode.FORBIDDEN, ErrorCode.CSRF_FAILED,
        ErrorCode.RESOURCE_NOT_FOUND, ErrorCode.WORKFLOW_CONFLICT,
        ErrorCode.VALIDATION_FAILED,
    ),
)
async def activate_account(
    request: Request, user_id: str, payload: AccountActivationRequest, actor: CsrfActor
):
    result = await request.app.state.container.school_directory.activate_account(
        actor,
        user_id,
        payload.new_password.get_secret_value(),
        trace_id=_trace_id(request),
    )
    return JSONResponse(_envelope(request, result))
