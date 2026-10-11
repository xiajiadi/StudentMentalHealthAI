"""Provisional session-auth endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from smhai_backend.core.api_models import ApiEnvelope
from smhai_backend.core.errors import ErrorCode, problem_responses
from smhai_backend.core.request_context import current_request_context
from smhai_backend.core.security import credential_identity, validate_mutation_origin

from .dependencies import (
    CSRF_SECURITY_OPENAPI_EXTRA,
    PUBLIC_SECURITY_OPENAPI_EXTRA,
    CsrfActor,
    CurrentActor,
)
from .schemas import (
    ActiveContextRequest,
    ActorDto,
    CsrfResponse,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    RoleContextDto,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def envelope(request: Request, data: object) -> dict[str, object]:
    context = current_request_context(request)
    return {
        "request_id": context.request_id,
        "trace_id": context.trace_id,
        "data": data.model_dump(mode="json") if isinstance(data, BaseModel) else data,
    }


def actor_dto(actor) -> ActorDto:
    contexts = [
        RoleContextDto(role=context.role, school_ref=context.school_ref)
        for context in actor.school_contexts
    ]
    active_context = (
        RoleContextDto(role=actor.role, school_ref=actor.school_ref)
        if actor.school_ref is not None
        else None
    )
    return ActorDto(
        user_id=actor.user_id,
        username=actor.username,
        role=actor.role,
        subject_id=actor.subject_id,
        authorized_roles=list(actor.authorized_roles),
        available_contexts=contexts,
        active_context=active_context,
    )


@router.post(
    "/login",
    operation_id="authLogin",
    response_model=ApiEnvelope[LoginResponse],
    openapi_extra=PUBLIC_SECURITY_OPENAPI_EXTRA,
    responses=problem_responses(
        ErrorCode.AUTH_INVALID_CREDENTIALS,
        ErrorCode.RATE_LIMITED,
        ErrorCode.CSRF_FAILED,
    ),
    summary="Create an opaque server-side session",
)
async def login(request: Request, payload: LoginRequest) -> JSONResponse:
    container = request.app.state.container
    validate_mutation_origin(request, container.settings)
    client_host = request.client.host if request.client else "unknown"
    container.rate_limiter.check(
        "login",
        f"{client_host}:{credential_identity(payload.username)}",
    )
    context = current_request_context(request)
    old_session_id = request.cookies.get(container.settings.cookie_name)
    actor, session = await container.auth.login(
        username=payload.username,
        password=payload.password,
        old_session_id=old_session_id,
        request_id=context.request_id,
        trace_id=context.trace_id,
    )
    data = LoginResponse(
        actor=actor_dto(actor),
        csrf_token=session.csrf_token,
    )
    response = JSONResponse(content=envelope(request, data), status_code=200)
    _set_session_cookie(response, container.settings, session.session_id)
    return response


@router.post(
    "/logout",
    operation_id="authLogout",
    response_model=ApiEnvelope[LogoutResponse],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=problem_responses(ErrorCode.AUTH_SESSION_EXPIRED, ErrorCode.CSRF_FAILED),
    summary="Revoke the current server-side session",
)
async def logout(request: Request, actor: CsrfActor) -> JSONResponse:
    container = request.app.state.container
    context = current_request_context(request)
    await container.auth.logout(
        request.cookies.get(container.settings.cookie_name),
        request_id=context.request_id,
        trace_id=context.trace_id,
    )
    response = JSONResponse(
        content=envelope(request, LogoutResponse()),
        status_code=200,
    )
    response.delete_cookie(
        key=container.settings.cookie_name,
        path="/",
        secure=container.settings.auth.secure_cookie,
        httponly=True,
        samesite=container.settings.auth.same_site,
    )
    return response


@router.get(
    "/me",
    operation_id="authMe",
    response_model=ApiEnvelope[ActorDto],
    responses=problem_responses(ErrorCode.AUTH_SESSION_EXPIRED),
    summary="Read the current actor",
)
async def me(request: Request, actor: CurrentActor) -> dict[str, object]:
    return envelope(request, actor_dto(actor))


@router.post(
    "/active-context",
    operation_id="authSwitchActiveContext",
    response_model=ApiEnvelope[ActorDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=problem_responses(
        ErrorCode.AUTH_SESSION_EXPIRED,
        ErrorCode.FORBIDDEN,
        ErrorCode.CSRF_FAILED,
    ),
    summary="Switch the active school role context",
)
async def switch_active_context(
    request: Request, payload: ActiveContextRequest, actor: CsrfActor
) -> dict[str, object]:
    container = request.app.state.container
    context = current_request_context(request)
    switched = await container.auth.switch_active_context(
        request.cookies.get(container.settings.cookie_name),
        role=payload.role,
        school_ref=payload.school_ref,
        request_id=context.request_id,
        trace_id=context.trace_id,
    )
    return envelope(request, actor_dto(switched))


@router.get(
    "/csrf",
    operation_id="authCsrf",
    response_model=ApiEnvelope[CsrfResponse],
    responses=problem_responses(ErrorCode.AUTH_SESSION_EXPIRED),
    summary="Obtain the session-bound CSRF token",
)
async def csrf(request: Request, actor: CurrentActor) -> dict[str, object]:
    session = request.state.session
    return envelope(request, CsrfResponse(csrf_token=session.csrf_token))


def _set_session_cookie(response: JSONResponse, settings, session_id: str) -> None:
    response.set_cookie(
        key=settings.cookie_name,
        value=session_id,
        max_age=settings.auth.session_ttl_seconds,
        httponly=True,
        secure=settings.auth.secure_cookie,
        samesite=settings.auth.same_site,
        path="/",
    )
