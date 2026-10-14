"""Admin/CSRF/idempotency boundary for server-owned research cohorts."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from smhai_backend.core.api_models import ApiEnvelope
from smhai_backend.core.errors import ErrorCode, error, problem_responses
from smhai_backend.core.idempotency import fingerprint, request_key
from smhai_backend.core.request_context import current_request_context
from smhai_backend.domains.auth.dependencies import CSRF_SECURITY_OPENAPI_EXTRA, require_role
from smhai_backend.domains.models import Actor, BackendRole

from .schemas import ResearchCohortReceiptDto, ResearchCohortSealRequest
from .service import _require_admin

router = APIRouter(prefix="/school/research-cohorts", tags=["school-research-cohorts"])
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


@router.post(
    "/seal",
    status_code=201,
    response_model=ApiEnvelope[ResearchCohortReceiptDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def seal_research_cohort(
    request: Request,
    actor: AdminCsrfActor,
    payload: ResearchCohortSealRequest,
):
    _require_admin(actor)
    key = request_key(request)
    if key is None:
        raise error(ErrorCode.VALIDATION_FAILED, detail="Idempotency-Key is required")
    container = getattr(request.app.state, "container", None)
    service = getattr(container, "school_research_cohorts", None)
    if service is None:
        raise error(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            detail="research cohort service is not configured",
            retryable=True,
        )
    scope = fingerprint({
        "actor": actor.user_id,
        "school_id": actor.school_id,
        "school_ref": actor.school_ref,
        "role": actor.role.value,
        "operation": "school_research_cohorts:seal",
    })
    result = await service.seal_cohort(
        actor,
        binding_ref=payload.binding_ref,
        profile_version_number=payload.profile_version_number,
        batch_refs=tuple(payload.batch_refs),
        idempotency=(key, fingerprint(payload.model_dump(mode="json")), scope),
    )
    receipt = ResearchCohortReceiptDto.model_validate(result)
    context = current_request_context(request)
    return JSONResponse({
        "request_id": context.request_id,
        "trace_id": context.trace_id,
        "data": jsonable_encoder(receipt.model_dump(mode="json")),
    }, status_code=201)
