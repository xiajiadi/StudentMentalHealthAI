"""Task-scoped school review endpoints, separate from frozen Safety review routes."""

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
    ProfessionalEligibleEnrollmentListDto,
    ProfessionalReviewCaseDto,
    ProfessionalReviewCaseListDto,
    ProfessionalReviewTaskDto,
    ProfessionalSpecialistDto,
    ReviewCaseCreateRequest,
    ReviewCaseDecisionRequest,
    ReviewCaseOpenRequest,
    SpecialistAssignmentDto,
    SpecialistAssignmentRequest,
)

router = APIRouter(prefix="/school/professional-reviews", tags=["school-professional-reviews"])
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
    return _response(request, dto.model_validate(result).model_dump(mode="json"))


@router.get(
    "/specialists", response_model=ApiEnvelope[list[ProfessionalSpecialistDto]], responses=_ERRORS
)
async def list_specialists(request: Request, actor: CurrentActor):
    rows = await request.app.state.container.professional_reviews.list_specialists(actor)
    return _response(
        request,
        [ProfessionalSpecialistDto.model_validate(row).model_dump(mode="json") for row in rows],
    )


@router.get(
    "/tasks", response_model=ApiEnvelope[list[ProfessionalReviewTaskDto]], responses=_ERRORS
)
async def list_tasks(request: Request, actor: CurrentActor):
    rows = await request.app.state.container.professional_reviews.list_tasks(actor)
    return _response(
        request,
        [ProfessionalReviewTaskDto.model_validate(row).model_dump(mode="json") for row in rows],
    )


@router.get(
    "/tasks/{task_ref}/eligible-enrollments",
    response_model=ApiEnvelope[ProfessionalEligibleEnrollmentListDto],
    responses=_ERRORS,
)
async def list_eligible_enrollments(
    request: Request,
    task_ref: str,
    actor: CurrentActor,
    offset: int = Query(default=0, ge=0, le=100000),
    limit: int = Query(default=20, ge=1, le=50),
):
    result = await request.app.state.container.professional_reviews.list_eligible_enrollments(
        actor, task_ref, offset=offset, limit=limit
    )
    return _response(
        request,
        ProfessionalEligibleEnrollmentListDto.model_validate(result).model_dump(mode="json"),
    )


@router.get(
    "/assignments", response_model=ApiEnvelope[list[SpecialistAssignmentDto]], responses=_ERRORS
)
async def list_assignments(request: Request, actor: CurrentActor, task_ref: str | None = None):
    rows = await request.app.state.container.professional_reviews.list_assignments(
        actor, task_ref=task_ref
    )
    return _response(
        request,
        [SpecialistAssignmentDto.model_validate(row).model_dump(mode="json") for row in rows],
    )


@router.post(
    "/tasks/{task_ref}/assignments",
    response_model=ApiEnvelope[SpecialistAssignmentDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def assign(
    request: Request, task_ref: str, payload: SpecialistAssignmentRequest, actor: CsrfActor
):
    service = request.app.state.container.professional_reviews
    return await _write(
        request,
        actor,
        f"assign:{task_ref}",
        payload.model_dump(),
        lambda idem, trace: service.assign(
            actor, task_ref, payload.specialist_user_id, idempotency=idem, trace_id=trace
        ),
        SpecialistAssignmentDto,
    )


@router.post(
    "/tasks/{task_ref}/assignments/{assignment_ref}/revoke",
    response_model=ApiEnvelope[SpecialistAssignmentDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def revoke(request: Request, task_ref: str, assignment_ref: str, actor: CsrfActor):
    service = request.app.state.container.professional_reviews
    return await _write(
        request,
        actor,
        f"revoke:{task_ref}:{assignment_ref}",
        {},
        lambda idem, trace: service.revoke(
            actor, task_ref, assignment_ref, idempotency=idem, trace_id=trace
        ),
        SpecialistAssignmentDto,
    )


@router.get(
    "/tasks/{task_ref}/cases",
    response_model=ApiEnvelope[ProfessionalReviewCaseListDto],
    responses=_ERRORS,
)
async def list_cases(
    request: Request,
    task_ref: str,
    actor: CurrentActor,
    offset: int = Query(default=0, ge=0, le=100000),
    limit: int = Query(default=20, ge=1, le=50),
):
    result = await request.app.state.container.professional_reviews.list_cases(
        actor, task_ref, offset=offset, limit=limit
    )
    return _response(
        request, ProfessionalReviewCaseListDto.model_validate(result).model_dump(mode="json")
    )


@router.get(
    "/tasks/{task_ref}/cases/{case_ref}",
    response_model=ApiEnvelope[ProfessionalReviewCaseDto],
    responses=_ERRORS,
)
async def get_case(request: Request, task_ref: str, case_ref: str, actor: CurrentActor):
    result = await request.app.state.container.professional_reviews.get_case(
        actor, task_ref, case_ref
    )
    return _response(
        request, ProfessionalReviewCaseDto.model_validate(result).model_dump(mode="json")
    )


@router.post(
    "/tasks/{task_ref}/cases",
    response_model=ApiEnvelope[ProfessionalReviewCaseDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def ensure_case(
    request: Request, task_ref: str, payload: ReviewCaseCreateRequest, actor: CsrfActor
):
    service = request.app.state.container.professional_reviews
    return await _write(
        request,
        actor,
        f"case-create:{task_ref}",
        payload.model_dump(),
        lambda idem, trace: service.ensure_case(
            actor, task_ref, payload.enrollment_ref, idempotency=idem, trace_id=trace
        ),
        ProfessionalReviewCaseDto,
    )


@router.post(
    "/tasks/{task_ref}/cases/{case_ref}/open",
    response_model=ApiEnvelope[ProfessionalReviewCaseDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def open_case(
    request: Request, task_ref: str, case_ref: str, payload: ReviewCaseOpenRequest, actor: CsrfActor
):
    service = request.app.state.container.professional_reviews
    return await _write(
        request,
        actor,
        f"case-open:{task_ref}:{case_ref}",
        payload.model_dump(),
        lambda idem, trace: service.open_case(
            actor,
            task_ref,
            case_ref,
            expected_version=payload.expected_version,
            idempotency=idem,
            trace_id=trace,
        ),
        ProfessionalReviewCaseDto,
    )


@router.post(
    "/tasks/{task_ref}/cases/{case_ref}/decision",
    response_model=ApiEnvelope[ProfessionalReviewCaseDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def process_case(
    request: Request,
    task_ref: str,
    case_ref: str,
    payload: ReviewCaseDecisionRequest,
    actor: CsrfActor,
):
    service = request.app.state.container.professional_reviews
    return await _write(
        request,
        actor,
        f"case-decision:{task_ref}:{case_ref}",
        payload.model_dump(),
        lambda idem, trace: service.process_case(
            actor,
            task_ref,
            case_ref,
            expected_version=payload.expected_version,
            decision=payload.decision,
            note=payload.note,
            idempotency=idem,
            trace_id=trace,
        ),
        ProfessionalReviewCaseDto,
    )
