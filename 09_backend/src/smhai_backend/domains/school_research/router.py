"""Private, student-only research CAT routes with strict L1 projections."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Path, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from smhai_backend.core.api_models import ApiEnvelope
from smhai_backend.core.errors import ErrorCode, error, problem_responses
from smhai_backend.core.idempotency import fingerprint, request_key
from smhai_backend.core.request_context import current_request_context
from smhai_backend.domains.auth.dependencies import (
    CSRF_SECURITY_OPENAPI_EXTRA,
    require_role,
)
from smhai_backend.domains.models import Actor, BackendRole

from .schemas import EmptyResearchRequest, ResearchAnswerRequest, ResearchL1SessionDto

router = APIRouter(prefix="/school/research", tags=["school-research"])
_REFERENCE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
_EMPTY_BODY = Body(default=None)
StudentCsrfActor = Annotated[Actor, Depends(require_role(BackendRole.STUDENT))]


def _envelope(request: Request, data: BaseModel) -> dict[str, Any]:
    context = current_request_context(request)
    return {
        "request_id": context.request_id,
        "trace_id": context.trace_id,
        "data": jsonable_encoder(data.model_dump(mode="json")),
    }


def _require_student(actor: Actor) -> None:
    if (
        actor.scope_profile != "school_tenant"
        or actor.role is not BackendRole.STUDENT
        or type(actor.school_id) is not int
        or actor.school_id <= 0
        or type(actor.school_ref) is not str
        or not actor.school_ref
    ):
        raise error(ErrorCode.FORBIDDEN, detail="access denied")


def _configured_service(request: Request) -> Any:
    container = getattr(request.app.state, "container", None)
    service = getattr(container, "school_research", None)
    if service is None:
        raise error(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            detail="research CAT service is not configured",
            retryable=True,
        )
    return service


def _idempotency(actor: Actor, request: Request, operation: str, payload: dict[str, Any]):
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


def _response(request: Request, value: Any) -> JSONResponse:
    dto = ResearchL1SessionDto.model_validate(value)
    return JSONResponse(_envelope(request, dto))


@router.post(
    "/tasks/{task_ref}/start",
    response_model=ApiEnvelope[ResearchL1SessionDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=problem_responses(
        ErrorCode.AUTH_SESSION_EXPIRED,
        ErrorCode.FORBIDDEN,
        ErrorCode.CSRF_FAILED,
        ErrorCode.VALIDATION_FAILED,
        ErrorCode.RESOURCE_NOT_FOUND,
        ErrorCode.DEPENDENCY_UNAVAILABLE,
        ErrorCode.DEPENDENCY_INVALID_RESPONSE,
        ErrorCode.WORKFLOW_CONFLICT,
    ),
)
async def start_research_session(
    request: Request,
    actor: StudentCsrfActor,
    task_ref: str = Path(pattern=_REFERENCE_PATTERN),
    payload: EmptyResearchRequest | None = _EMPTY_BODY,
):
    del payload
    _require_student(actor)
    idempotency = _idempotency(
        actor, request, f"research:task:{task_ref}:start", {"task_ref": task_ref}
    )
    service = _configured_service(request)
    context = current_request_context(request)
    value = await service.start_task(
        actor,
        task_ref,
        trace_id=context.trace_id,
        idempotency=idempotency,
    )
    return _response(request, value)


@router.post(
    "/sessions/{session_ref}/resume",
    response_model=ApiEnvelope[ResearchL1SessionDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=problem_responses(
        ErrorCode.AUTH_SESSION_EXPIRED,
        ErrorCode.FORBIDDEN,
        ErrorCode.CSRF_FAILED,
        ErrorCode.VALIDATION_FAILED,
        ErrorCode.RESOURCE_NOT_FOUND,
        ErrorCode.DEPENDENCY_UNAVAILABLE,
        ErrorCode.DEPENDENCY_INVALID_RESPONSE,
        ErrorCode.WORKFLOW_CONFLICT,
    ),
)
async def resume_research_session(
    request: Request,
    actor: StudentCsrfActor,
    session_ref: str = Path(pattern=_REFERENCE_PATTERN),
    payload: EmptyResearchRequest | None = _EMPTY_BODY,
):
    del payload
    _require_student(actor)
    service = _configured_service(request)
    value = await service.resume_session(actor, session_ref)
    return _response(request, value)


@router.post(
    "/sessions/{session_ref}/answers",
    response_model=ApiEnvelope[ResearchL1SessionDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=problem_responses(
        ErrorCode.AUTH_SESSION_EXPIRED,
        ErrorCode.FORBIDDEN,
        ErrorCode.CSRF_FAILED,
        ErrorCode.VALIDATION_FAILED,
        ErrorCode.RESOURCE_NOT_FOUND,
        ErrorCode.DEPENDENCY_UNAVAILABLE,
        ErrorCode.DEPENDENCY_INVALID_RESPONSE,
        ErrorCode.WORKFLOW_CONFLICT,
    ),
)
async def answer_research_session(
    request: Request,
    actor: StudentCsrfActor,
    payload: ResearchAnswerRequest,
    session_ref: str = Path(pattern=_REFERENCE_PATTERN),
):
    _require_student(actor)
    body = payload.model_dump(mode="json")
    idempotency = _idempotency(actor, request, f"research:session:{session_ref}:answer", body)
    service = _configured_service(request)
    value = await service.answer(
        actor,
        session_ref,
        item_id=payload.item_id,
        raw_value=payload.raw_value,
        expected_state_version=payload.expected_state_version,
        idempotency=idempotency,
    )
    return _response(request, value)
