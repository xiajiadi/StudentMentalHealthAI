"""Backend liveness, readiness, and dependency capability routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

from smhai_backend.core.api_models import (
    ApiEnvelope,
    ApiHealthDto,
    DependencyStatusDto,
    HealthLiveDto,
    HealthReadyDto,
)
from smhai_backend.core.errors import ErrorCode, problem_responses
from smhai_backend.core.request_context import current_request_context
from smhai_backend.domains.auth.dependencies import PUBLIC_SECURITY_OPENAPI_EXTRA

router = APIRouter(tags=["health"])


def envelope(request: Request, data: object) -> dict[str, object]:
    context = current_request_context(request)
    return {"request_id": context.request_id, "trace_id": context.trace_id, "data": data}


@router.get(
    "/health/live",
    operation_id="healthLive",
    response_model=HealthLiveDto,
    openapi_extra=PUBLIC_SECURITY_OPENAPI_EXTRA,
    summary="Check that the Backend process is alive",
)
async def live() -> dict[str, str]:
    return {"status": "ok", "service": "backend", "contract_version": "v0.1.0"}


@router.get(
    "/health/ready",
    operation_id="healthReady",
    response_model=ApiEnvelope[HealthReadyDto],
    openapi_extra=PUBLIC_SECURITY_OPENAPI_EXTRA,
    responses=problem_responses(ErrorCode.INTERNAL_ERROR),
    summary="Check Backend core readiness",
)
async def ready(request: Request) -> dict[str, object]:
    container = request.app.state.container
    research_ready = await container.research_process_ready()
    core = {"configuration": "READY", "session_store": "READY"}
    if container.school_research_process_factory is not None:
        core["research_cat"] = "READY" if research_ready else "UNAVAILABLE"
    return envelope(
        request,
        {
            "status": "ready"
            if getattr(request.app.state, "lifecycle_started", False) and research_ready
            else "starting",
            "core": core,
            "optional_dependencies_not_used_for_core_readiness": True,
        },
    )


@router.get(
    "/health/dependencies",
    operation_id="healthDependencies",
    response_model=ApiEnvelope[dict[str, DependencyStatusDto]],
    openapi_extra=PUBLIC_SECURITY_OPENAPI_EXTRA,
    responses=problem_responses(ErrorCode.INTERNAL_ERROR, ErrorCode.DEPENDENCY_UNAVAILABLE),
    summary="Read dependency capability statuses",
)
async def dependencies(request: Request) -> dict[str, object]:
    container = request.app.state.container
    statuses = await container.dependency_matrix(current_request_context(request))
    return envelope(request, statuses)


@router.get(
    "/api/v1/health",
    operation_id="getHealth",
    response_model=ApiEnvelope[ApiHealthDto],
    openapi_extra=PUBLIC_SECURITY_OPENAPI_EXTRA,
    responses=problem_responses(ErrorCode.INTERNAL_ERROR, ErrorCode.DEPENDENCY_UNAVAILABLE),
    summary="Read candidate health envelope",
)
async def api_health(request: Request) -> dict[str, object]:
    container = request.app.state.container
    statuses = await container.dependency_matrix(current_request_context(request))
    unavailable = any(value["status"] == "UNAVAILABLE" for value in statuses.values())
    return envelope(
        request,
        {
            "status": "degraded" if unavailable else "ok",
            "contract_version": "v0.1.0",
            "dependencies": statuses,
        },
    )
