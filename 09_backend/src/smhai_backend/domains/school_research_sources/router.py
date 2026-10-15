"""Scope-C read-only API for the currently pinned research source package."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.request_context import current_request_context
from smhai_backend.domains.auth.dependencies import CurrentActor
from smhai_backend.domains.models import BackendRole

from .schemas import ResearchSourceCatalogPageDto, ResearchSourceDetailDto

router = APIRouter(prefix="/school/research-sources", tags=["school-research-sources"])
_SOURCE_REF = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"


def _service(request: Request, actor: Any):
    if (
        actor.scope_profile != "school_tenant"
        or actor.role is not BackendRole.PSYCHOLOGICAL_SPECIALIST
        or type(actor.school_id) is not int
        or actor.school_id <= 0
        or type(actor.school_ref) is not str
        or not actor.school_ref
    ):
        raise error(ErrorCode.FORBIDDEN, detail="access denied")
    service = getattr(request.app.state.container, "school_research_sources", None)
    if service is None:
        raise error(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            detail="research source catalog is not configured",
            retryable=True,
        )
    return service


def _response(request: Request, data):
    context = current_request_context(request)
    return JSONResponse(
        {
            "request_id": context.request_id,
            "trace_id": context.trace_id,
            "data": data.model_dump(mode="json"),
        }
    )


def _closed_query(request: Request) -> None:
    allowed = {"offset", "limit"}
    if set(request.query_params) - allowed or any(
        len(request.query_params.getlist(key)) != 1 for key in request.query_params
    ):
        raise error(ErrorCode.VALIDATION_FAILED, detail="research source query is invalid")


@router.get("/catalog", response_model=None)
async def list_sources(
    request: Request,
    actor: CurrentActor,
    offset: int = Query(default=0, ge=0, le=10_000),
    limit: int = Query(default=20, ge=1, le=50),
):
    _closed_query(request)
    data = ResearchSourceCatalogPageDto.model_validate(
        _service(request, actor).list_sources(actor, limit=limit, offset=offset)
    )
    return _response(request, data)


@router.get("/{source_ref}", response_model=None)
async def get_source(
    request: Request,
    source_ref: str,
    actor: CurrentActor,
):
    if not re.fullmatch(_SOURCE_REF, source_ref):
        raise error(ErrorCode.VALIDATION_FAILED, detail="source reference is invalid")
    data = ResearchSourceDetailDto.model_validate(
        _service(request, actor).get_source(actor, source_ref)
    )
    return _response(request, data)
