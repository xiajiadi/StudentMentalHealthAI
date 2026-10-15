"""Specialist-only read/adopt/discard routes; no generation or publication route."""

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
    CandidateAdoptRequest,
    CandidateDiscardRequest,
    ProgrammeCandidateDetailDto,
    ProgrammeCandidateListDto,
    ProgrammeCandidateSummaryDto,
    ProgrammeGenerationBatchQueuedDto,
    ProgrammeGenerationQueuedDto,
    QueueProgrammeGenerationBatchRequest,
    QueueProgrammeGenerationRequest,
)

router = APIRouter(
    prefix="/school/research-programme-candidates",
    tags=["school-research-programme-candidates"],
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
    service = getattr(container, "school_research_programme_candidates", None)
    if service is None:
        raise error(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            detail="research programme candidates are unavailable",
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
    trace_id = current_request_context(request).trace_id
    result = await call((key, fingerprint(payload), idem_scope), trace_id)
    safe = dto.model_validate(result, strict=True).model_dump(mode="json")
    return _response(request, safe)


@router.get(
    "/tasks/{task_ref}",
    response_model=ApiEnvelope[ProgrammeCandidateListDto],
    responses=_ERRORS,
)
async def list_task_candidates(
    request: Request,
    task_ref: str,
    actor: CurrentActor,
    offset: int = Query(default=0, ge=0, le=100_000),
    limit: int = Query(default=20, ge=1, le=50),
):
    result = await _service(request).list_for_task(
        actor, task_ref, offset=offset, limit=limit
    )
    return _response(
        request,
        ProgrammeCandidateListDto.model_validate(result, strict=True).model_dump(mode="json"),
    )


@router.get(
    "/tasks/{task_ref}/{candidate_ref}",
    response_model=ApiEnvelope[ProgrammeCandidateDetailDto],
    responses=_ERRORS,
)
async def get_task_candidate(
    request: Request, task_ref: str, candidate_ref: str, actor: CurrentActor
):
    result = await _service(request).get(actor, task_ref, candidate_ref)
    return _response(
        request,
        ProgrammeCandidateDetailDto.model_validate(result, strict=True).model_dump(mode="json"),
    )


@router.post(
    "/tasks/{task_ref}/{candidate_ref}/adopt",
    response_model=ApiEnvelope[ProgrammeCandidateSummaryDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def adopt_candidate(
    request: Request,
    task_ref: str,
    candidate_ref: str,
    payload: CandidateAdoptRequest,
    actor: CsrfActor,
):
    service = _service(request)
    return await _write(
        request,
        actor,
        f"research-programme-candidate-adopt:{task_ref}:{candidate_ref}",
        payload.model_dump(),
        lambda idem, trace: service.adopt(
            actor,
            task_ref,
            candidate_ref,
            expected_state_version=payload.expected_state_version,
            idempotency=idem,
            trace_id=trace,
        ),
        ProgrammeCandidateSummaryDto,
    )


@router.post(
    "/tasks/{task_ref}/{candidate_ref}/discard",
    response_model=ApiEnvelope[ProgrammeCandidateSummaryDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def discard_candidate(
    request: Request,
    task_ref: str,
    candidate_ref: str,
    payload: CandidateDiscardRequest,
    actor: CsrfActor,
):
    service = _service(request)
    return await _write(
        request,
        actor,
        f"research-programme-candidate-discard:{task_ref}:{candidate_ref}",
        payload.model_dump(),
        lambda idem, trace: service.discard(
            actor,
            task_ref,
            candidate_ref,
            expected_state_version=payload.expected_state_version,
            idempotency=idem,
            trace_id=trace,
        ),
        ProgrammeCandidateSummaryDto,
    )


@router.post(
    "/tasks/{task_ref}/queue-generation",
    response_model=ApiEnvelope[ProgrammeGenerationQueuedDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def queue_programme_generation(
    request: Request,
    task_ref: str,
    payload: QueueProgrammeGenerationRequest,
    actor: CsrfActor,
):
    service = _service(request)
    return await _write(
        request,
        actor,
        f"research-programme-generation-queue:{task_ref}",
        payload.model_dump(),
        lambda idem, trace: service.queue_generation(
            actor, task_ref, idempotency=idem, trace_id=trace
        ),
        ProgrammeGenerationQueuedDto,
    )


@router.post(
    "/tasks/{task_ref}/queue-generation/batch",
    response_model=ApiEnvelope[ProgrammeGenerationBatchQueuedDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def queue_programme_generation_batch(
    request: Request,
    task_ref: str,
    payload: QueueProgrammeGenerationBatchRequest,
    actor: CsrfActor,
):
    service = _service(request)
    return await _write(
        request,
        actor,
        f"research-programme-generation-batch-queue:{task_ref}",
        payload.model_dump(),
        lambda idem, trace: service.queue_generation_batch(
            actor,
            task_ref,
            limit=payload.limit,
            after_job_ref=payload.after_job_ref,
            idempotency=idem,
            trace_id=trace,
        ),
        ProgrammeGenerationBatchQueuedDto,
    )
