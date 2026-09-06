"""FastAPI dependencies for actor, CSRF, and server-side authorization."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.security import validate_csrf
from smhai_backend.domains.models import Actor, BackendRole


def container_for(request: Request):
    return request.app.state.container


async def current_actor(request: Request) -> Actor:
    container = container_for(request)
    cookie_name = container.settings.cookie_name
    session_id = request.cookies.get(cookie_name)
    actor, session = await container.auth.actor_for_session(
        session_id,
        request_id=request.state.request_context.request_id,
        trace_id=request.state.request_context.trace_id,
    )
    request.state.session = session
    request.state.actor = actor
    return actor


async def csrf_protected(
    request: Request, actor: Annotated[Actor, Depends(current_actor)]
) -> Actor:
    container = container_for(request)
    session = getattr(request.state, "session", None)
    if session is None:
        raise error(ErrorCode.AUTH_SESSION_EXPIRED, detail="authentication is required")
    validate_csrf(request, session.csrf_token, container.settings)
    return actor


def require_role(*roles: BackendRole):
    async def dependency(actor: Annotated[Actor, Depends(csrf_protected)]) -> Actor:
        if actor.role not in roles:
            raise error(ErrorCode.FORBIDDEN, detail="access denied")
        return actor

    return dependency


CurrentActor = Annotated[Actor, Depends(current_actor)]
CsrfActor = Annotated[Actor, Depends(csrf_protected)]
