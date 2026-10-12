"""Module-local endpoints for private independent student conversations."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.idempotency import request_key
from smhai_backend.core.request_context import current_request_context
from smhai_backend.domains.auth.dependencies import (
    CSRF_SECURITY_OPENAPI_EXTRA,
    CsrfActor,
    CurrentActor,
)
from smhai_backend.domains.models import BackendRole

from .schemas import ConversationCreateRequest, ConversationMessageRequest

router = APIRouter(prefix="/student/conversations", tags=["student-conversations"])


def _service(request: Request, actor):
    if actor.role != BackendRole.STUDENT:
        raise error(ErrorCode.FORBIDDEN, detail="student access is required")
    service = request.app.state.container.independent_conversations
    if service is None:
        raise error(ErrorCode.DEPENDENCY_UNAVAILABLE, detail="conversation service is unavailable")
    return service


def _key(request: Request) -> str:
    key = request_key(request)
    if key is None:
        raise error(ErrorCode.VALIDATION_FAILED, detail="idempotency key is required")
    return key


def _response(request: Request, result, *, status: int = 200):
    context = current_request_context(request)
    return JSONResponse(
        {
            "request_id": context.request_id,
            "trace_id": context.trace_id,
            "data": result.model_dump(mode="json"),
        },
        status_code=status,
    )


@router.post("", openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA)
async def create_conversation(
    request: Request, payload: ConversationCreateRequest, actor: CsrfActor
):
    result = await _service(request, actor).create(
        actor,
        payload=payload,
        idempotency_key=_key(request),
        context=current_request_context(request),
    )
    return _response(request, result, status=201)


@router.get("")
async def list_conversations(
    request: Request,
    actor: CurrentActor,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=50),
):
    result = await _service(request, actor).list(actor, offset=offset, limit=limit)
    return _response(request, result)


@router.get("/{conversation_id}")
async def conversation_detail(
    request: Request,
    conversation_id: str,
    actor: CurrentActor,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=50),
):
    result = await _service(request, actor).detail(
        actor,
        conversation_id,
        offset=offset,
        limit=limit,
    )
    return _response(request, result)


@router.post("/{conversation_id}/messages", openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA)
async def submit_message(
    request: Request,
    conversation_id: str,
    payload: ConversationMessageRequest,
    actor: CsrfActor,
):
    service = _service(request, actor)
    key = _key(request)
    request.app.state.container.rate_limiter.check("support", actor.user_id)
    result = await service.submit_message(
        actor,
        conversation_id,
        payload=payload,
        idempotency_key=key,
        context=current_request_context(request),
    )
    return _response(request, result, status=202 if result.status == "requested" else 200)
