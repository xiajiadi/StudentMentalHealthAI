"""Task-scoped review and student-only research feedback endpoints."""

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
    ResearchCaseCreateRequest,
    ResearchCaseDecisionRequest,
    ResearchEligibleSessionListDto,
    ResearchFeedbackDraftRequest,
    ResearchFeedbackDto,
    ResearchFeedbackListDto,
    ResearchFeedbackPublishRequest,
    ResearchFeedbackRevokeRequest,
    ResearchReviewCaseDto,
    ResearchReviewCaseListDto,
    ResearchReviewTaskListDto,
    StudentResearchFeedbackDto,
    StudentResearchFeedbackListDto,
)

router = APIRouter(prefix="/school/research-feedback", tags=["school-research-feedback"])
_ERRORS = problem_responses(
    ErrorCode.AUTH_SESSION_EXPIRED,
    ErrorCode.FORBIDDEN,
    ErrorCode.RESOURCE_NOT_FOUND,
    ErrorCode.VALIDATION_FAILED,
    ErrorCode.WORKFLOW_CONFLICT,
    ErrorCode.CSRF_FAILED,
    ErrorCode.DEPENDENCY_UNAVAILABLE,
)


def _service(request: Request):
    container = getattr(request.app.state, "container", None)
    service = getattr(container, "school_research_feedback", None)
    if service is None:
        raise error(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            detail="research feedback is unavailable",
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


@router.get("/tasks", response_model=ApiEnvelope[ResearchReviewTaskListDto], responses=_ERRORS)
async def list_tasks(request: Request, actor: CurrentActor):
    rows = await _service(request).list_tasks(actor)
    safe = ResearchReviewTaskListDto(items=rows).model_dump(mode="json")
    return _response(request, safe)


@router.get(
    "/tasks/{task_ref}/eligible-sessions",
    response_model=ApiEnvelope[ResearchEligibleSessionListDto],
    responses=_ERRORS,
)
async def list_eligible_sessions(
    request: Request,
    task_ref: str,
    actor: CurrentActor,
    offset: int = Query(default=0, ge=0, le=100_000),
    limit: int = Query(default=20, ge=1, le=50),
):
    result = await _service(request).list_eligible_sessions(
        actor, task_ref, offset=offset, limit=limit
    )
    return _response(
        request,
        ResearchEligibleSessionListDto.model_validate(result, strict=True).model_dump(mode="json"),
    )


@router.get(
    "/tasks/{task_ref}/cases",
    response_model=ApiEnvelope[ResearchReviewCaseListDto],
    responses=_ERRORS,
)
async def list_cases(
    request: Request,
    task_ref: str,
    actor: CurrentActor,
    status: str | None = None,
    offset: int = Query(default=0, ge=0, le=100_000),
    limit: int = Query(default=20, ge=1, le=50),
):
    result = await _service(request).list_cases(
        actor, task_ref, status=status, offset=offset, limit=limit
    )
    return _response(
        request,
        ResearchReviewCaseListDto.model_validate(result, strict=True).model_dump(mode="json"),
    )


@router.get(
    "/tasks/{task_ref}/cases/{case_ref}",
    response_model=ApiEnvelope[ResearchReviewCaseDto],
    responses=_ERRORS,
)
async def get_case(request: Request, task_ref: str, case_ref: str, actor: CurrentActor):
    row = await _service(request).get_case(actor, task_ref, case_ref)
    return _response(
        request, ResearchReviewCaseDto.model_validate(row, strict=True).model_dump(mode="json")
    )


@router.post(
    "/tasks/{task_ref}/cases",
    response_model=ApiEnvelope[ResearchReviewCaseDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def create_case(
    request: Request, task_ref: str, payload: ResearchCaseCreateRequest, actor: CsrfActor
):
    service = _service(request)
    return await _write(
        request,
        actor,
        f"research-case-create:{task_ref}",
        payload.model_dump(),
        lambda idem, trace: service.create_case(
            actor, task_ref, session_ref=payload.session_ref, idempotency=idem, trace_id=trace
        ),
        ResearchReviewCaseDto,
    )


@router.post(
    "/tasks/{task_ref}/cases/{case_ref}/decision",
    response_model=ApiEnvelope[ResearchReviewCaseDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def transition_case(
    request: Request,
    task_ref: str,
    case_ref: str,
    payload: ResearchCaseDecisionRequest,
    actor: CsrfActor,
):
    service = _service(request)
    return await _write(
        request,
        actor,
        f"research-case-decision:{task_ref}:{case_ref}",
        payload.model_dump(),
        lambda idem, trace: service.transition_case(
            actor,
            task_ref,
            case_ref,
            expected_version=payload.expected_version,
            status=payload.status,
            note=payload.note,
            idempotency=idem,
            trace_id=trace,
        ),
        ResearchReviewCaseDto,
    )


@router.post(
    "/cases/{case_ref}/draft",
    response_model=ApiEnvelope[ResearchFeedbackDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def create_draft(
    request: Request,
    case_ref: str,
    payload: ResearchFeedbackDraftRequest,
    actor: CsrfActor,
):
    service = _service(request)
    return await _write(
        request,
        actor,
        f"research-feedback-draft:{case_ref}",
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
        ResearchFeedbackDto,
    )


@router.get(
    "/cases/{case_ref}/feedback",
    response_model=ApiEnvelope[ResearchFeedbackListDto],
    responses=_ERRORS,
)
async def list_case_feedback(
    request: Request,
    case_ref: str,
    actor: CurrentActor,
    offset: int = Query(default=0, ge=0, le=100_000),
    limit: int = Query(default=20, ge=1, le=50),
):
    result = await _service(request).list_feedback(actor, case_ref, offset=offset, limit=limit)
    return _response(
        request, ResearchFeedbackListDto.model_validate(result, strict=True).model_dump(mode="json")
    )


@router.post(
    "/feedback/{feedback_ref}/publish",
    response_model=ApiEnvelope[ResearchFeedbackDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def publish(
    request: Request,
    feedback_ref: str,
    payload: ResearchFeedbackPublishRequest,
    actor: CsrfActor,
):
    service = _service(request)
    return await _write(
        request,
        actor,
        f"research-feedback-publish:{feedback_ref}",
        payload.model_dump(),
        lambda idem, trace: service.publish(
            actor,
            feedback_ref,
            expected_state_version=payload.expected_state_version,
            expected_case_version=payload.expected_case_version,
            idempotency=idem,
            trace_id=trace,
        ),
        ResearchFeedbackDto,
    )


@router.post(
    "/feedback/{feedback_ref}/revoke",
    response_model=ApiEnvelope[ResearchFeedbackDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def revoke(
    request: Request,
    feedback_ref: str,
    payload: ResearchFeedbackRevokeRequest,
    actor: CsrfActor,
):
    service = _service(request)
    return await _write(
        request,
        actor,
        f"research-feedback-revoke:{feedback_ref}",
        payload.model_dump(),
        lambda idem, trace: service.revoke(
            actor,
            feedback_ref,
            expected_state_version=payload.expected_state_version,
            idempotency=idem,
            trace_id=trace,
        ),
        ResearchFeedbackDto,
    )


@router.get(
    "/student",
    response_model=ApiEnvelope[StudentResearchFeedbackListDto],
    responses=_ERRORS,
)
async def list_student_feedback(
    request: Request,
    actor: CurrentActor,
    offset: int = Query(default=0, ge=0, le=100_000),
    limit: int = Query(default=20, ge=1, le=50),
):
    result = await _service(request).list_student_feedback(actor, offset=offset, limit=limit)
    return _response(
        request,
        StudentResearchFeedbackListDto.model_validate(result, strict=True).model_dump(mode="json"),
    )


@router.get(
    "/student/{feedback_ref}",
    response_model=ApiEnvelope[StudentResearchFeedbackDto],
    responses=_ERRORS,
)
async def get_student_feedback(request: Request, feedback_ref: str, actor: CurrentActor):
    row = await _service(request).get_student_feedback(actor, feedback_ref)
    return _response(
        request, StudentResearchFeedbackDto.model_validate(row, strict=True).model_dump(mode="json")
    )
