"""Module-local school classes and measurement task endpoints."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from smhai_backend.core.api_models import ApiEnvelope
from smhai_backend.core.errors import ErrorCode, problem_responses
from smhai_backend.core.idempotency import fingerprint, request_key
from smhai_backend.core.request_context import current_request_context
from smhai_backend.domains.auth.dependencies import (
    CSRF_SECURITY_OPENAPI_EXTRA,
    CsrfActor,
    CurrentActor,
)

from .schemas import (
    ClassCreateRequest,
    ClassDto,
    EnrollmentDto,
    RevocationDto,
    SchoolMemberDto,
    StudentAssessmentMetadataDto,
    StudentAssignmentDto,
    StudentAssignmentRequest,
    StudentTaskDto,
    StudentTaskHistoryDto,
    TaskDto,
    TaskPublishRequest,
    TaskStartDto,
    TeacherAssignmentDto,
    TeacherAssignmentRequest,
    TeacherTaskProgressDto,
)

router = APIRouter(prefix="/school", tags=["school-tasks"])


def _envelope(request: Request, data):
    context = current_request_context(request)
    value = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
    return {
        "request_id": context.request_id,
        "trace_id": context.trace_id,
        "data": jsonable_encoder(value),
    }


def _idempotency_scope(actor, operation: str) -> str:
    return fingerprint(
        {
            "actor": actor.user_id,
            "school_id": actor.school_id,
            "school_ref": actor.school_ref,
            "role": actor.role.value,
            "operation": operation,
        }
    )


async def _write(
    request: Request, actor, op: str, payload, call, response_dto, status_code: int = 200
):
    key = request_key(request)
    if key is None:
        from smhai_backend.core.errors import error

        raise error(ErrorCode.VALIDATION_FAILED, detail="Idempotency-Key is required")
    body_fingerprint = fingerprint(payload)
    scope = _idempotency_scope(actor, op)
    result = await call((key, body_fingerprint, scope))
    body = _envelope(request, response_dto.model_validate(result))
    return JSONResponse(body, status_code=status_code)


@router.get(
    "/classes",
    response_model=ApiEnvelope[list[ClassDto]],
    responses=problem_responses(ErrorCode.AUTH_SESSION_EXPIRED, ErrorCode.FORBIDDEN),
)
async def list_classes(request: Request, actor: CurrentActor):
    rows = await request.app.state.container.school_tasks.list_classes(actor)
    return JSONResponse(_envelope(request, [ClassDto.model_validate(row) for row in rows]))


@router.get(
    "/members",
    response_model=ApiEnvelope[list[SchoolMemberDto]],
    responses=problem_responses(ErrorCode.AUTH_SESSION_EXPIRED, ErrorCode.FORBIDDEN),
)
async def list_members(
    request: Request,
    actor: CurrentActor,
    role: str = Query(pattern="^(student|teacher)$"),
):
    rows = await request.app.state.container.school_tasks.list_members(actor, role)
    return JSONResponse(_envelope(request, [SchoolMemberDto.model_validate(row) for row in rows]))


@router.post(
    "/classes",
    status_code=201,
    response_model=ApiEnvelope[ClassDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=problem_responses(
        ErrorCode.AUTH_SESSION_EXPIRED,
        ErrorCode.FORBIDDEN,
        ErrorCode.CSRF_FAILED,
        ErrorCode.VALIDATION_FAILED,
        ErrorCode.WORKFLOW_CONFLICT,
    ),
)
async def create_class(request: Request, payload: ClassCreateRequest, actor: CsrfActor):
    return await _write(
        request,
        actor,
        "class:create",
        payload.model_dump(mode="json"),
        lambda idem: request.app.state.container.school_tasks.create_class(
            actor, payload.class_ref, idempotency=idem
        ),
        ClassDto,
        201,
    )


@router.post(
    "/classes/{class_ref}/students",
    response_model=ApiEnvelope[StudentAssignmentDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=problem_responses(
        ErrorCode.AUTH_SESSION_EXPIRED,
        ErrorCode.FORBIDDEN,
        ErrorCode.CSRF_FAILED,
        ErrorCode.RESOURCE_NOT_FOUND,
    ),
)
async def assign_student(
    request: Request, class_ref: str, payload: StudentAssignmentRequest, actor: CsrfActor
):
    return await _write(
        request,
        actor,
        f"class:{class_ref}:student",
        payload.model_dump(mode="json"),
        lambda idem: request.app.state.container.school_tasks.assign_student(
            actor, class_ref, payload.student_user_id, idempotency=idem
        ),
        StudentAssignmentDto,
    )


@router.post(
    "/classes/{class_ref}/teachers",
    response_model=ApiEnvelope[TeacherAssignmentDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=problem_responses(
        ErrorCode.AUTH_SESSION_EXPIRED,
        ErrorCode.FORBIDDEN,
        ErrorCode.CSRF_FAILED,
        ErrorCode.RESOURCE_NOT_FOUND,
    ),
)
async def assign_teacher(
    request: Request, class_ref: str, payload: TeacherAssignmentRequest, actor: CsrfActor
):
    return await _write(
        request,
        actor,
        f"class:{class_ref}:teacher",
        payload.model_dump(mode="json"),
        lambda idem: request.app.state.container.school_tasks.assign_teacher(
            actor, class_ref, payload.teacher_user_id, idempotency=idem
        ),
        TeacherAssignmentDto,
    )


@router.post(
    "/classes/{class_ref}/tasks",
    status_code=201,
    response_model=ApiEnvelope[TaskDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=problem_responses(
        ErrorCode.AUTH_SESSION_EXPIRED,
        ErrorCode.FORBIDDEN,
        ErrorCode.CSRF_FAILED,
        ErrorCode.RESOURCE_NOT_FOUND,
        ErrorCode.VALIDATION_FAILED,
    ),
)
async def publish_task(
    request: Request, class_ref: str, payload: TaskPublishRequest, actor: CsrfActor
):
    return await _write(
        request,
        actor,
        f"class:{class_ref}:task:publish",
        payload.model_dump(mode="json"),
        lambda idem: request.app.state.container.school_tasks.publish_task(
            actor,
            class_ref,
            opens_at=payload.opens_at,
            due_at=payload.due_at,
            idempotency=idem,
        ),
        TaskDto,
        201,
    )


@router.get(
    "/classes/{class_ref}/tasks",
    response_model=ApiEnvelope[list[TaskDto]],
    responses=problem_responses(
        ErrorCode.AUTH_SESSION_EXPIRED, ErrorCode.FORBIDDEN, ErrorCode.RESOURCE_NOT_FOUND
    ),
)
async def list_class_tasks(request: Request, class_ref: str, actor: CurrentActor):
    rows = await request.app.state.container.school_tasks.list_class_tasks(actor, class_ref)
    return JSONResponse(_envelope(request, [TaskDto.model_validate(row) for row in rows]))


@router.get(
    "/tasks/student",
    response_model=ApiEnvelope[list[StudentTaskDto]],
    responses=problem_responses(ErrorCode.AUTH_SESSION_EXPIRED, ErrorCode.FORBIDDEN),
)
async def list_student_tasks(request: Request, actor: CurrentActor):
    rows = await request.app.state.container.school_tasks.list_student_tasks(actor)
    return JSONResponse(_envelope(request, [StudentTaskDto.model_validate(row) for row in rows]))


@router.get(
    "/tasks/student/history",
    response_model=ApiEnvelope[list[StudentTaskHistoryDto]],
    responses=problem_responses(ErrorCode.AUTH_SESSION_EXPIRED, ErrorCode.FORBIDDEN),
)
async def list_student_task_history(request: Request, actor: CurrentActor):
    rows = await request.app.state.container.school_tasks.list_student_task_history(actor)
    return JSONResponse(
        _envelope(request, [StudentTaskHistoryDto.model_validate(row) for row in rows])
    )


@router.get(
    "/assessments",
    response_model=ApiEnvelope[list[StudentAssessmentMetadataDto]],
    responses=problem_responses(ErrorCode.AUTH_SESSION_EXPIRED, ErrorCode.FORBIDDEN),
)
async def list_student_assessments(
    request: Request,
    actor: CurrentActor,
    limit: int = Query(default=30, ge=1, le=100),
    skip: int = Query(default=0, ge=0),
    status: Literal["created", "in_progress", "completed", "abandoned", "invalid"]
    | None = Query(
        default=None,
    ),
):
    rows = await request.app.state.container.school_tasks.list_student_assessments(
        actor, limit=limit, skip=skip, status=status
    )
    return JSONResponse(
        _envelope(
            request,
            [StudentAssessmentMetadataDto.model_validate(row) for row in rows],
        )
    )


@router.get(
    "/tasks/{task_ref}/enrollments",
    response_model=ApiEnvelope[list[EnrollmentDto]],
    responses=problem_responses(
        ErrorCode.AUTH_SESSION_EXPIRED, ErrorCode.FORBIDDEN, ErrorCode.RESOURCE_NOT_FOUND
    ),
)
async def list_task_enrollments(request: Request, task_ref: str, actor: CurrentActor):
    rows = await request.app.state.container.school_tasks.list_enrollments(actor, task_ref)
    return JSONResponse(_envelope(request, [EnrollmentDto.model_validate(row) for row in rows]))


@router.post(
    "/tasks/{task_ref}/start",
    response_model=ApiEnvelope[TaskStartDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=problem_responses(
        ErrorCode.AUTH_SESSION_EXPIRED,
        ErrorCode.FORBIDDEN,
        ErrorCode.CSRF_FAILED,
        ErrorCode.RESOURCE_NOT_FOUND,
        ErrorCode.DEPENDENCY_UNAVAILABLE,
        ErrorCode.WORKFLOW_CONFLICT,
    ),
)
async def start_task(request: Request, task_ref: str, actor: CsrfActor):
    context = current_request_context(request)
    return await _write(
        request,
        actor,
        f"task:{task_ref}:start",
        {"task_ref": task_ref},
        lambda idem: request.app.state.container.school_tasks.start_task(
            actor,
            task_ref,
            request_id=context.request_id,
            trace_id=context.trace_id,
            idempotency=idem,
        ),
        TaskStartDto,
    )


@router.get(
    "/teacher/task-progress",
    response_model=ApiEnvelope[list[TeacherTaskProgressDto]],
    responses=problem_responses(ErrorCode.AUTH_SESSION_EXPIRED, ErrorCode.FORBIDDEN),
)
async def teacher_all_task_progress(request: Request, actor: CurrentActor):
    rows = await request.app.state.container.school_tasks.teacher_progress(actor)
    return JSONResponse(
        _envelope(request, [TeacherTaskProgressDto.model_validate(row) for row in rows])
    )


@router.get(
    "/classes/{class_ref}/task-progress",
    response_model=ApiEnvelope[list[TeacherTaskProgressDto]],
    responses=problem_responses(
        ErrorCode.AUTH_SESSION_EXPIRED, ErrorCode.FORBIDDEN, ErrorCode.RESOURCE_NOT_FOUND
    ),
)
async def teacher_task_progress(request: Request, class_ref: str, actor: CurrentActor):
    rows = await request.app.state.container.school_tasks.teacher_progress(actor, class_ref)
    return JSONResponse(
        _envelope(request, [TeacherTaskProgressDto.model_validate(row) for row in rows])
    )


@router.post(
    "/tasks/{task_ref}/enrollments/{enrollment_ref}/revoke",
    response_model=ApiEnvelope[RevocationDto],
    openapi_extra=CSRF_SECURITY_OPENAPI_EXTRA,
    responses=problem_responses(
        ErrorCode.AUTH_SESSION_EXPIRED,
        ErrorCode.FORBIDDEN,
        ErrorCode.CSRF_FAILED,
        ErrorCode.RESOURCE_NOT_FOUND,
    ),
)
async def revoke_enrollment(request: Request, task_ref: str, enrollment_ref: str, actor: CsrfActor):
    return await _write(
        request,
        actor,
        f"task:{task_ref}:enrollment:{enrollment_ref}:revoke",
        {"task_ref": task_ref, "enrollment_ref": enrollment_ref},
        lambda idem: request.app.state.container.school_tasks.revoke_enrollment(
            actor, task_ref, enrollment_ref, idempotency=idem
        ),
        RevocationDto,
    )
