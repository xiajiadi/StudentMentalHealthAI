"""Student-visible publication and specialist draft workflow endpoints."""

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

from .schemas import (
    FeedbackDraftRequest,
    FeedbackDto,
    FeedbackListDto,
    FeedbackTransitionRequest,
    StudentFeedbackDto,
    StudentFeedbackListDto,
)

router = APIRouter(prefix="/school/feedback", tags=["school-feedback"])
_ERRORS = problem_responses(
    ErrorCode.AUTH_SESSION_EXPIRED,
    ErrorCode.FORBIDDEN,
    ErrorCode.RESOURCE_NOT_FOUND,
    ErrorCode.VALIDATION_FAILED,
    ErrorCode.WORKFLOW_CONFLICT,
    ErrorCode.CSRF_FAILED,
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


async def _write(request: Request, actor, operation: str, payload: dict, call, dto):
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
    trace = current_request_context(request).trace_id
    result = await call((key, fingerprint(payload), scope), trace)
    safe = dto.model_validate(result, strict=True).model_dump(mode="json")
    return _response(request, safe)


@router.get("/cases/{case_ref}", response_model=ApiEnvelope[FeedbackListDto], responses=_ERRORS)
async def list_case_feedback(
    request: Request,
    case_ref: str,
    actor: CurrentActor,
    offset: int = Query(default=0, ge=0, le=100000),
    limit: int = Query(default=50, ge=1, le=50),
):
    result = await request.app.state.container.school_feedback.list_case_feedback(
        actor, case_ref, offset=offset, limit=limit
    )
    safe = FeedbackListDto.model_validate(result, strict=True).model_dump(mode="json")
    return _response(request, safe)


@router.post(
    "/cases/{case_ref}",
    response_model=ApiEnvelope[FeedbackDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def create_draft(
    request: Request, case_ref: str, payload: FeedbackDraftRequest, actor: CsrfActor
):
    service = request.app.state.container.school_feedback
    return await _write(
        request,
        actor,
        f"create:{case_ref}",
        payload.model_dump(),
        lambda idem, trace: service.create_draft(
            actor,
            case_ref,
            expected_case_version=payload.expected_case_version,
            title=payload.title,
            body=payload.body,
            idempotency=idem,
            trace_id=trace,
        ),
        FeedbackDto,
    )


@router.post(
    "/{feedback_ref}/publish",
    response_model=ApiEnvelope[FeedbackDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def publish(
    request: Request,
    feedback_ref: str,
    payload: FeedbackTransitionRequest,
    actor: CsrfActor,
):
    service = request.app.state.container.school_feedback
    return await _write(
        request,
        actor,
        f"publish:{feedback_ref}",
        payload.model_dump(),
        lambda idem, trace: service.publish(
            actor,
            feedback_ref,
            expected_case_version=payload.expected_case_version,
            expected_state_version=payload.expected_state_version,
            idempotency=idem,
            trace_id=trace,
        ),
        FeedbackDto,
    )


@router.post(
    "/{feedback_ref}/revoke",
    response_model=ApiEnvelope[FeedbackDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def revoke(
    request: Request,
    feedback_ref: str,
    payload: FeedbackTransitionRequest,
    actor: CsrfActor,
):
    service = request.app.state.container.school_feedback
    return await _write(
        request,
        actor,
        f"revoke:{feedback_ref}",
        payload.model_dump(),
        lambda idem, trace: service.revoke(
            actor,
            feedback_ref,
            expected_case_version=payload.expected_case_version,
            expected_state_version=payload.expected_state_version,
            idempotency=idem,
            trace_id=trace,
        ),
        FeedbackDto,
    )


@router.get("/student", response_model=ApiEnvelope[StudentFeedbackListDto], responses=_ERRORS)
async def list_student_feedback(
    request: Request,
    actor: CurrentActor,
    offset: int = Query(default=0, ge=0, le=100000),
    limit: int = Query(default=50, ge=1, le=50),
):
    result = await request.app.state.container.school_feedback.list_student_feedback(
        actor, offset=offset, limit=limit
    )
    safe = StudentFeedbackListDto.model_validate(result, strict=True).model_dump(mode="json")
    return _response(request, safe)


@router.get(
    "/student/{feedback_ref}",
    response_model=ApiEnvelope[StudentFeedbackDto],
    responses=_ERRORS,
)
async def get_student_feedback(request: Request, feedback_ref: str, actor: CurrentActor):
    result = await request.app.state.container.school_feedback.get_student_feedback(
        actor, feedback_ref
    )
    safe = StudentFeedbackDto.model_validate(result, strict=True).model_dump(mode="json")
    return _response(request, safe)
