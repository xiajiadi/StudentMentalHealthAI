"""HTTP endpoints for the authorized synthetic teacher projection."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from smhai_backend.core.api_models import ApiEnvelope
from smhai_backend.core.errors import ErrorCode, problem_responses
from smhai_backend.core.request_context import current_request_context
from smhai_backend.domains.auth.dependencies import CurrentActor

from .schemas import TeacherOverview, TeacherStudentHistory

router = APIRouter(prefix="/teacher", tags=["teacher"])


def _envelope(request: Request, data: object) -> dict[str, object]:
    context = current_request_context(request)
    return {
        "request_id": context.request_id,
        "trace_id": context.trace_id,
        "data": data.model_dump(mode="json"),
    }


@router.get(
    "/overview",
    operation_id="getTeacherOverview",
    response_model=ApiEnvelope[TeacherOverview],
    responses=problem_responses(ErrorCode.AUTH_SESSION_EXPIRED, ErrorCode.FORBIDDEN),
    summary="Read synthetic assessment and report counts within the teacher's assigned scope",
)
async def get_teacher_overview(request: Request, actor: CurrentActor) -> JSONResponse:
    result = await request.app.state.container.teacher_dashboard.overview(actor)
    return JSONResponse(_envelope(request, result))


@router.get(
    "/students/{subject_id}",
    operation_id="getTeacherStudentHistory",
    response_model=ApiEnvelope[TeacherStudentHistory],
    responses=problem_responses(ErrorCode.AUTH_SESSION_EXPIRED, ErrorCode.FORBIDDEN),
    summary="Read synthetic assessment lifecycle history for an assigned subject",
)
async def get_teacher_student_history(
    subject_id: str, request: Request, actor: CurrentActor
) -> JSONResponse:
    result = await request.app.state.container.teacher_dashboard.student_history(
        actor, subject_id
    )
    return JSONResponse(_envelope(request, result))
