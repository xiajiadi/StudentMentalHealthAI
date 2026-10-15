"""Task-bound research education candidate API for assigned specialists."""

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
    ResearchEducationCandidateBatchDto,
    ResearchEducationCandidateBatchRequest,
    ResearchEducationCandidateDetailDto,
    ResearchEducationCandidateListDto,
    ResearchEducationCandidateResolutionRequest,
    ResearchEducationCandidateSummaryDto,
    ResearchEducationCandidateTaskListDto,
)

router = APIRouter(
    prefix="/school/research-education-candidates",
    tags=["school-research-education-candidates"],
)
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
    service = getattr(container, "school_research_education_candidates", None)
    if service is None:
        raise error(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            detail="research education candidates are unavailable",
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
    idem_scope = fingerprint(
        {
            "actor": actor.user_id,
            "school_id": actor.school_id,
            "school_ref": actor.school_ref,
            "role": actor.role.value,
            "operation": operation,
        }
    )
    context = current_request_context(request)
    result = await call((key, fingerprint(payload), idem_scope), context.trace_id)
    safe = dto.model_validate(result, strict=True).model_dump(mode="json")
    return _response(request, safe)


@router.get(
    "/tasks",
    response_model=ApiEnvelope[ResearchEducationCandidateTaskListDto],
    responses=_ERRORS,
)
async def list_tasks(request: Request, actor: CurrentActor):
    return _response(request, await _service(request).list_tasks(actor))


@router.get(
    "/tasks/{task_ref}/candidates",
    response_model=ApiEnvelope[ResearchEducationCandidateListDto],
    responses=_ERRORS,
)
async def list_candidates(
    request: Request,
    task_ref: str,
    actor: CurrentActor,
    status: str = Query(default="HELD", pattern="^(HELD|ADOPTED|DISCARDED)$"),
    offset: int = Query(default=0, ge=0, le=100_000),
    limit: int = Query(default=20, ge=1, le=50),
):
    return _response(
        request,
        await _service(request).list_for_task(
            actor, task_ref, status=status, offset=offset, limit=limit
        ),
    )


@router.get(
    "/tasks/{task_ref}/candidates/{candidate_ref}",
    response_model=ApiEnvelope[ResearchEducationCandidateDetailDto],
    responses=_ERRORS,
)
async def get_candidate(request: Request, task_ref: str, candidate_ref: str, actor: CurrentActor):
    return _response(request, await _service(request).get(actor, task_ref, candidate_ref))


@router.post(
    "/tasks/{task_ref}/enqueue",
    response_model=ApiEnvelope[ResearchEducationCandidateBatchDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def enqueue_candidates(
    request: Request,
    task_ref: str,
    payload: ResearchEducationCandidateBatchRequest,
    actor: CsrfActor,
):
    service = _service(request)
    return await _write(
        request,
        actor,
        f"research-education-candidate-enqueue:{task_ref}",
        payload.model_dump(),
        lambda idem, trace: service.queue_batch(
            actor,
            task_ref,
            limit=payload.limit,
            offset=payload.offset,
            idempotency=idem,
            trace_id=trace,
        ),
        ResearchEducationCandidateBatchDto,
    )


@router.post(
    "/tasks/{task_ref}/candidates/{candidate_ref}/resolve",
    response_model=ApiEnvelope[ResearchEducationCandidateSummaryDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def resolve_candidate(
    request: Request,
    task_ref: str,
    candidate_ref: str,
    payload: ResearchEducationCandidateResolutionRequest,
    actor: CsrfActor,
):
    service = _service(request)
    return await _write(
        request,
        actor,
        f"research-education-candidate-resolve:{task_ref}:{candidate_ref}",
        payload.model_dump(),
        lambda idem, trace: service.resolve(
            actor,
            task_ref,
            candidate_ref,
            expected_state_version=payload.expected_state_version,
            target=payload.target,
            idempotency=idem,
            trace_id=trace,
        ),
        ResearchEducationCandidateSummaryDto,
    )
