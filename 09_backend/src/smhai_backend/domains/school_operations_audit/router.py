"""Read-only school-scoped operations audit endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from smhai_backend.core.api_models import ApiEnvelope
from smhai_backend.core.errors import ErrorCode, problem_responses
from smhai_backend.core.request_context import current_request_context
from smhai_backend.domains.auth.dependencies import CurrentActor

from .schemas import AuditCategory, SchoolOperationsAuditPageDto

router = APIRouter(prefix="/school/operations-audit", tags=["school-operations-audit"])


def _envelope(request: Request, data: BaseModel) -> dict[str, object]:
    context = current_request_context(request)
    return {
        "request_id": context.request_id,
        "trace_id": context.trace_id,
        "data": jsonable_encoder(data.model_dump(mode="json")),
    }


@router.get(
    "",
    response_model=ApiEnvelope[SchoolOperationsAuditPageDto],
    responses=problem_responses(ErrorCode.AUTH_SESSION_EXPIRED, ErrorCode.FORBIDDEN),
)
async def list_school_operations_audit(
    request: Request,
    actor: CurrentActor,
    offset: int = Query(default=0, ge=0, le=10_000),
    limit: int = Query(default=25, ge=1, le=50),
    category: Annotated[AuditCategory | None, Query()] = None,
):
    data = await request.app.state.container.school_operations_audit.list_events(
        actor,
        offset=offset,
        limit=limit,
        category=category,
    )
    return JSONResponse(_envelope(request, data))
