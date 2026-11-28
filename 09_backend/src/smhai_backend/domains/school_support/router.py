"""Role-scoped school support referral and follow-up routes."""

from __future__ import annotations

from fastapi import APIRouter, Path, Query, Request
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
    SupportActionCreateRequest,
    SupportActionDto,
    SupportActionFeedbackRequest,
    SupportActionPageDto,
    SupportAssigneeListDto,
    SupportCaseCreateRequest,
    SupportCaseDetailDto,
    SupportCasePageDto,
    SupportCaseReceiptDto,
    SupportFeedbackQuestionRequest,
    SupportPlanEvidenceDto,
    SupportStudentListDto,
    SupportTransitionRequest,
)

router = APIRouter(prefix="/school/support", tags=["school-support"])
_ERRORS = problem_responses(
    ErrorCode.AUTH_SESSION_EXPIRED,
    ErrorCode.FORBIDDEN,
    ErrorCode.RESOURCE_NOT_FOUND,
    ErrorCode.VALIDATION_FAILED,
    ErrorCode.WORKFLOW_CONFLICT,
    ErrorCode.CSRF_FAILED,
    ErrorCode.DEPENDENCY_UNAVAILABLE,
    ErrorCode.DEPENDENCY_INVALID_RESPONSE,
)


def _service(request: Request):
    container = getattr(request.app.state, "container", None)
    service = getattr(container, "school_support", None)
    if service is None:
        raise error(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            detail="school support is unavailable",
            retryable=True,
        )
    return service


def _response(request: Request, data):
    context = current_request_context(request)
    return JSONResponse(
        {
            "request_id": context.request_id,
            "trace_id": context.trace_id,
            "data": jsonable_encoder(data),
        }
    )


async def _write(request: Request, actor, operation: str, payload: dict, call, dto, status=200):
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
    result = await call(
        (key, fingerprint(payload), scope),
        current_request_context(request).trace_id,
    )
    safe = dto.model_validate(result, strict=True).model_dump(mode="json")
    body = _response(request, safe)
    body.status_code = status
    return body


@router.get(
    "/students",
    response_model=ApiEnvelope[SupportStudentListDto],
    responses=_ERRORS,
    include_in_schema=False,
)
async def list_students(request: Request, actor: CurrentActor):
    return _response(request, await _service(request).list_students(actor))


@router.get(
    "/cases",
    response_model=ApiEnvelope[SupportCasePageDto],
    responses=_ERRORS,
    include_in_schema=False,
)
async def list_cases(
    request: Request,
    actor: CurrentActor,
    offset: int = Query(default=0, ge=0, le=100_000),
    limit: int = Query(default=20, ge=1, le=50),
    triaged_only: bool = Query(default=False),
):
    service = _service(request)
    if triaged_only:
        response = _response(
            request, await service.list_cases(actor, offset=offset, limit=limit, triaged_only=True)
        )
        response.headers["Cache-Control"] = "private, no-store"
        return response
    return _response(
        request, await service.list_cases(actor, offset=offset, limit=limit)
    )


@router.get(
    "/actions",
    response_model=ApiEnvelope[SupportActionPageDto],
    responses=_ERRORS,
    include_in_schema=False,
)
async def list_actions(
    request: Request,
    actor: CurrentActor,
    offset: int = Query(default=0, ge=0, le=100_000),
    limit: int = Query(default=20, ge=1, le=50),
):
    return _response(
        request, await _service(request).list_actions(actor, offset=offset, limit=limit)
    )


@router.post(
    "/cases",
    status_code=201,
    response_model=ApiEnvelope[SupportCaseReceiptDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
    include_in_schema=False,
)
async def create_case(
    request: Request, payload: SupportCaseCreateRequest, actor: CsrfActor
):
    service = _service(request)
    return await _write(
        request,
        actor,
        "school-support-case:create",
        payload.model_dump(mode="json"),
        lambda idem, trace: service.create_case(
            actor, payload=payload.model_dump(), idempotency=idem, trace_id=trace
        ),
        SupportCaseReceiptDto,
        201,
    )


@router.post(
    "/feedback-questions/{feedback_ref}",
    status_code=201,
    response_model=ApiEnvelope[SupportCaseReceiptDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
    include_in_schema=False,
)
async def ask_about_feedback(
    request: Request,
    payload: SupportFeedbackQuestionRequest,
    actor: CsrfActor,
    feedback_ref: str = Path(pattern=r"^FEED_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}$"),
):
    service = _service(request)
    body = payload.model_dump(mode="json")
    response = await _write(
        request,
        actor,
        "school-support-case:ask-about-feedback",
        {**body, "feedback_ref": feedback_ref},
        lambda idem, trace: service.ask_about_feedback(
            actor, feedback_ref, payload=body, idempotency=idem, trace_id=trace
        ),
        SupportCaseReceiptDto,
        201,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response


@router.get(
    "/cases/{case_ref}",
    response_model=ApiEnvelope[SupportCaseDetailDto],
    responses=_ERRORS,
    include_in_schema=False,
)
async def get_case(request: Request, case_ref: str, actor: CurrentActor):
    return _response(request, await _service(request).get_case(actor, case_ref))


@router.get(
    "/cases/{case_ref}/plan-evidence",
    response_model=ApiEnvelope[SupportPlanEvidenceDto],
    responses=_ERRORS,
    include_in_schema=False,
)
async def get_plan_evidence(request: Request, case_ref: str, actor: CurrentActor):
    response = _response(request, await _service(request).plan_evidence(actor, case_ref))
    response.headers["Cache-Control"] = "private, no-store"
    return response


@router.get(
    "/cases/{case_ref}/assignees",
    response_model=ApiEnvelope[SupportAssigneeListDto],
    responses=_ERRORS,
    include_in_schema=False,
)
async def list_assignees(request: Request, case_ref: str, actor: CurrentActor):
    return _response(request, await _service(request).list_assignees(actor, case_ref))


@router.post(
    "/cases/{case_ref}/transitions",
    response_model=ApiEnvelope[SupportCaseDetailDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
    include_in_schema=False,
)
async def transition_case(
    request: Request,
    case_ref: str,
    payload: SupportTransitionRequest,
    actor: CsrfActor,
):
    service = _service(request)
    return await _write(
        request,
        actor,
        f"school-support-case:transition:{case_ref}",
        payload.model_dump(mode="json"),
        lambda idem, trace: service.transition_case(
            actor,
            case_ref,
            payload=payload.model_dump(),
            idempotency=idem,
            trace_id=trace,
        ),
        SupportCaseDetailDto,
    )


@router.post(
    "/cases/{case_ref}/actions",
    response_model=ApiEnvelope[SupportCaseDetailDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
    include_in_schema=False,
)
async def create_action(
    request: Request,
    case_ref: str,
    payload: SupportActionCreateRequest,
    actor: CsrfActor,
):
    service = _service(request)
    return await _write(
        request,
        actor,
        f"school-support-case:action:{case_ref}",
        payload.model_dump(mode="json"),
        lambda idem, trace: service.create_action(
            actor,
            case_ref,
            payload=payload.model_dump(),
            idempotency=idem,
            trace_id=trace,
        ),
        SupportCaseDetailDto,
    )


@router.post(
    "/actions/{action_ref}/feedback",
    response_model=ApiEnvelope[SupportActionDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
    include_in_schema=False,
)
async def action_feedback(
    request: Request,
    action_ref: str,
    payload: SupportActionFeedbackRequest,
    actor: CsrfActor,
):
    service = _service(request)
    return await _write(
        request,
        actor,
        f"school-support-action:feedback:{action_ref}",
        payload.model_dump(mode="json"),
        lambda idem, trace: service.action_feedback(
            actor,
            action_ref,
            payload=payload.model_dump(),
            idempotency=idem,
            trace_id=trace,
        ),
        SupportActionDto,
    )
