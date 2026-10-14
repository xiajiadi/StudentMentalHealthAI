"""School, specialist, and own-status routes for durable conversation safety cases."""

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
    AdminCaseDto,
    AssignmentReceiptDto,
    SafetyAssignmentRequest,
    SafetyNoteRequest,
    SafetyTransitionRequest,
    SafetyVersionRequest,
    SpecialistCaseDetailDto,
    SpecialistSafetyPage,
    StudentSafetyStatusDto,
    UnassignedSafetyPage,
)

router = APIRouter(prefix="/school/conversation-safety", tags=["school-conversation-safety"])
student_router = APIRouter(tags=["student-conversation-safety"])
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
    service = getattr(container, "school_conversation_safety", None)
    if service is None:
        raise error(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            detail="conversation safety review is unavailable",
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
    result = await call(
        (key, fingerprint(payload), scope),
        current_request_context(request).trace_id,
    )
    safe = dto.model_validate(result, strict=True).model_dump(mode="json")
    return _response(request, safe)


@router.get("/unassigned", response_model=ApiEnvelope[UnassignedSafetyPage], responses=_ERRORS)
async def list_unassigned(
    request: Request,
    actor: CurrentActor,
    offset: int = Query(default=0, ge=0, le=100_000),
    limit: int = Query(default=20, ge=1, le=50),
):
    return _response(
        request, await _service(request).list_unassigned(actor, offset=offset, limit=limit)
    )


@router.get("/assigned", response_model=ApiEnvelope[SpecialistSafetyPage], responses=_ERRORS)
async def list_assigned(
    request: Request,
    actor: CurrentActor,
    offset: int = Query(default=0, ge=0, le=100_000),
    limit: int = Query(default=20, ge=1, le=50),
):
    return _response(
        request, await _service(request).list_assigned(actor, offset=offset, limit=limit)
    )


@router.get("/{case_ref}", response_model=ApiEnvelope[SpecialistCaseDetailDto], responses=_ERRORS)
async def get_assigned_case(request: Request, case_ref: str, actor: CurrentActor):
    return _response(request, await _service(request).get_assigned(actor, case_ref))


@router.post(
    "/{case_ref}/assignment",
    response_model=ApiEnvelope[AssignmentReceiptDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def assign_case(
    request: Request, case_ref: str, payload: SafetyAssignmentRequest, actor: CsrfActor
):
    service = _service(request)
    return await _write(
        request,
        actor,
        f"conversation-safety-assignment:{case_ref}",
        payload.model_dump(),
        lambda idem, trace: service.assign(
            actor, case_ref, payload=payload.model_dump(), idempotency=idem, trace_id=trace
        ),
        AssignmentReceiptDto,
    )


@router.post(
    "/{case_ref}/transfer",
    response_model=ApiEnvelope[AssignmentReceiptDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def transfer_case(
    request: Request, case_ref: str, payload: SafetyAssignmentRequest, actor: CsrfActor
):
    service = _service(request)
    return await _write(
        request,
        actor,
        f"conversation-safety-transfer:{case_ref}",
        payload.model_dump(),
        lambda idem, trace: service.transfer(
            actor, case_ref, payload=payload.model_dump(), idempotency=idem, trace_id=trace
        ),
        AssignmentReceiptDto,
    )


@router.post(
    "/{case_ref}/unassign",
    response_model=ApiEnvelope[AdminCaseDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def unassign_case(
    request: Request, case_ref: str, payload: SafetyVersionRequest, actor: CsrfActor
):
    service = _service(request)
    return await _write(
        request,
        actor,
        f"conversation-safety-unassign:{case_ref}",
        payload.model_dump(),
        lambda idem, trace: service.unassign(
            actor, case_ref, payload=payload.model_dump(), idempotency=idem, trace_id=trace
        ),
        AdminCaseDto,
    )


@router.post(
    "/{case_ref}/revoke",
    response_model=ApiEnvelope[AdminCaseDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def revoke_case(
    request: Request, case_ref: str, payload: SafetyVersionRequest, actor: CsrfActor
):
    service = _service(request)
    return await _write(
        request,
        actor,
        f"conversation-safety-revoke:{case_ref}",
        payload.model_dump(),
        lambda idem, trace: service.revoke(
            actor, case_ref, payload=payload.model_dump(), idempotency=idem, trace_id=trace
        ),
        AdminCaseDto,
    )


@router.put(
    "/{case_ref}/note",
    response_model=ApiEnvelope[SpecialistCaseDetailDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def save_note(request: Request, case_ref: str, payload: SafetyNoteRequest, actor: CsrfActor):
    service = _service(request)
    return await _write(
        request,
        actor,
        f"conversation-safety-note:{case_ref}",
        payload.model_dump(),
        lambda idem, trace: service.save_note(
            actor, case_ref, payload=payload.model_dump(), idempotency=idem, trace_id=trace
        ),
        SpecialistCaseDetailDto,
    )


@router.post(
    "/{case_ref}/transition",
    response_model=ApiEnvelope[SpecialistCaseDetailDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=_ERRORS,
)
async def transition_case(
    request: Request, case_ref: str, payload: SafetyTransitionRequest, actor: CsrfActor
):
    service = _service(request)
    return await _write(
        request,
        actor,
        f"conversation-safety-transition:{case_ref}",
        payload.model_dump(),
        lambda idem, trace: service.transition(
            actor, case_ref, payload=payload.model_dump(), idempotency=idem, trace_id=trace
        ),
        SpecialistCaseDetailDto,
    )


@student_router.get(
    "/student/conversations/{conversation_ref}/safety-status",
    response_model=ApiEnvelope[StudentSafetyStatusDto],
    responses=_ERRORS,
)
async def student_conversation_safety_status(
    request: Request, conversation_ref: str, actor: CurrentActor
):
    return _response(
        request, await _service(request).student_status(actor, conversation_ref, research=False)
    )


@student_router.get(
    "/student/research-conversations/{conversation_ref}/safety-status",
    response_model=ApiEnvelope[StudentSafetyStatusDto],
    responses=_ERRORS,
)
async def student_research_conversation_safety_status(
    request: Request, conversation_ref: str, actor: CurrentActor
):
    return _response(
        request, await _service(request).student_status(actor, conversation_ref, research=True)
    )
