"""Backend liveness, readiness, and dependency capability routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

from smhai_backend.core.request_context import current_request_context

router = APIRouter(tags=["health"])


def envelope(request: Request, data: object) -> dict[str, object]:
    context = current_request_context(request)
    return {"request_id": context.request_id, "trace_id": context.trace_id, "data": data}


@router.get("/health/live", summary="Check that the Backend process is alive")
async def live() -> dict[str, str]:
    return {"status": "ok", "service": "backend", "contract_version": "v0.1.0"}


@router.get("/health/ready", summary="Check Backend core readiness")
async def ready(request: Request) -> dict[str, object]:
    return envelope(
        request,
        {
            "status": "ready"
            if getattr(request.app.state, "lifecycle_started", False)
            else "starting",
            "core": {"configuration": "READY", "session_store": "READY"},
            "optional_dependencies_not_used_for_core_readiness": True,
        },
    )


@router.get("/health/dependencies", summary="Read dependency capability statuses")
async def dependencies(request: Request) -> dict[str, object]:
    container = request.app.state.container
    statuses = await container.dependency_matrix(current_request_context(request))
    return envelope(request, statuses)


@router.get("/api/v1/health", summary="Read frozen health envelope")
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
