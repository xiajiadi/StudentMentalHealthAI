"""Student-only research task discovery and own-session history routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from smhai_backend.core.api_models import ApiEnvelope
from smhai_backend.core.errors import ErrorCode, error, problem_responses
from smhai_backend.core.request_context import current_request_context
from smhai_backend.domains.auth.dependencies import CurrentActor
from smhai_backend.domains.models import Actor, BackendRole

from .schemas import ResearchDiscoverySessionPage, ResearchDiscoveryTaskPage

router = APIRouter(prefix="/school/research-discovery", tags=["school-research-discovery"])
_ERRORS = problem_responses(
    ErrorCode.AUTH_SESSION_EXPIRED,
    ErrorCode.FORBIDDEN,
    ErrorCode.VALIDATION_FAILED,
    ErrorCode.DEPENDENCY_UNAVAILABLE,
)


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


async def _student_reader(actor: CurrentActor) -> Actor:
    _require_student(actor)
    return actor


StudentActor = Annotated[Actor, Depends(_student_reader)]


def _configured_service(request: Request) -> Any:
    container = getattr(request.app.state, "container", None)
    service = getattr(container, "school_research_discovery", None)
    if service is None:
        raise error(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            detail="research discovery is not configured",
            retryable=True,
        )
    return service


def _require_closed_page_query(request: Request) -> None:
    parameters = request.query_params
    if (
        set(parameters) - {"limit", "offset"}
        or any(len(parameters.getlist(name)) != 1 for name in parameters)
    ):
        raise error(ErrorCode.VALIDATION_FAILED, detail="research page query is invalid")


def _response(request: Request, data: Any) -> JSONResponse:
    context = current_request_context(request)
    return JSONResponse(
        {
            "request_id": context.request_id,
            "trace_id": context.trace_id,
            "data": jsonable_encoder(data.model_dump(mode="json")),
        }
    )


@router.get(
    "/tasks",
    response_model=ApiEnvelope[ResearchDiscoveryTaskPage],
    responses=_ERRORS,
)
async def list_research_discovery_tasks(
    request: Request,
    actor: StudentActor,
    limit: int = Query(default=30, ge=1, le=30),
    offset: int = Query(default=0, ge=0, le=10_000),
):
    _require_student(actor)
    _require_closed_page_query(request)
    page = await _configured_service(request).list_tasks(actor, limit=limit, offset=offset)
    return _response(request, ResearchDiscoveryTaskPage.model_validate(page))


@router.get(
    "/sessions",
    response_model=ApiEnvelope[ResearchDiscoverySessionPage],
    responses=_ERRORS,
)
async def list_research_discovery_sessions(
    request: Request,
    actor: StudentActor,
    limit: int = Query(default=30, ge=1, le=30),
    offset: int = Query(default=0, ge=0, le=10_000),
):
    _require_student(actor)
    _require_closed_page_query(request)
    page = await _configured_service(request).list_sessions(actor, limit=limit, offset=offset)
    return _response(request, ResearchDiscoverySessionPage.model_validate(page))
