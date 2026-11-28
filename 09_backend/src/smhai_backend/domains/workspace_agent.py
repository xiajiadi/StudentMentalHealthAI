"""Role-scoped workspace tools. Unrecognized text is never forwarded or persisted."""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from database_layer.provenance import is_public_demo_school_ref
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from smhai_backend.core.config import school_csrf_secret_bytes
from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.idempotency import fingerprint
from smhai_backend.core.request_context import current_request_context
from smhai_backend.domains.auth.dependencies import CsrfActor, CurrentActor
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.domains.professional_reviews.schemas import ProfessionalReviewTaskDto
from smhai_backend.domains.school_tasks.schemas import (
    ClassDto,
    StudentTaskDto,
    TaskDto,
    TeacherTaskProgressDto,
)

from .workspace_agent_history import workspace_owner

router = APIRouter(prefix="/workspace-agent", tags=["workspace-agent"])
_ROLE_TO_TOOL = {
    BackendRole.STUDENT: "student_tasks",
    BackendRole.TEACHER: "class_progress",
    BackendRole.PSYCHOLOGICAL_SPECIALIST: "review_tasks",
    BackendRole.ADMIN: "school_tasks",
}
_COMMANDS = {
    BackendRole.STUDENT: (
        r"(?:我的测评(?:任务)?|查看我的测评(?:任务)?|还有哪些测评(?:没做)?|继续测评)"
    ),
    BackendRole.TEACHER: r"(?:班级(?:测评)?(?:进度|完成情况)|查看班级进度|统计班级测评进度)",
    BackendRole.PSYCHOLOGICAL_SPECIALIST: (
        r"(?:我的复核任务|(?:查看|整理)(?:测评)?复核任务|有哪些测评可以复核)"
    ),
    BackendRole.ADMIN: r"(?:学校测评任务|(?:查看|列出)(?:学校)?测评任务)",
}
_CREATE = re.compile(r"(?:新建|创建)(?:班级\s+|\s+班级\s+)([A-Za-z0-9][A-Za-z0-9_.-]{0,47})")
_CONFIRM_TOKEN = re.compile(
    r"([0-9]{10})\.([a-f0-9]{32})\.([A-Za-z0-9][A-Za-z0-9_.-]{0,47})"
    r"(?:~([a-f0-9]{32}))?\.([a-f0-9]{64})"
)
_KNOWLEDGE = {
    "帮我制定复习计划": "weekly_plan",
    "怎样把学习目标拆成小步骤": "small_steps",
    "学习压力大时该怎么办": "study_stress",
}
_LIMIT = 4
STARTABLE_ASSESSMENT_STATES = {"not_started", "created", "in_progress"}


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=160)


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=100, max_length=203)


class ToolRow(BaseModel):
    ref: str
    label: str | None = None
    status: str | None = None
    due_at: datetime | None = None
    completed: int | None = None
    total: int | None = None


class ToolResult(BaseModel):
    schema_version: Literal["workspace_agent.v1"] = "workspace_agent.v1"
    kind: Literal[
        "student_tasks",
        "class_progress",
        "review_tasks",
        "school_tasks",
        "preview_class",
        "class_created",
        "education_topic",
        "unknown",
    ]
    rows: list[ToolRow] = Field(default_factory=list)
    total: int = 0
    class_ref: str | None = None
    token: str | None = None
    topic: Literal["weekly_plan", "small_steps", "study_stress"] | None = None


def _check_actor(actor: Actor) -> None:
    if (
        actor.role not in _ROLE_TO_TOOL
        or actor.scope_profile != "school_tenant"
        or actor.school_id is None
        or not actor.school_ref
    ):
        raise error(ErrorCode.FORBIDDEN, detail="workspace access denied")


def _respond(request: Request, data: ToolResult):
    ctx = current_request_context(request)
    return {"request_id": ctx.request_id, "trace_id": ctx.trace_id, "data": data}


async def _snapshot(request: Request, actor: Actor, *, limit: int | None = _LIMIT) -> ToolResult:
    container = request.app.state.container
    service = container.school_tasks
    if actor.role is BackendRole.STUDENT:
        source = [
            StudentTaskDto.model_validate(row) for row in await service.list_student_tasks(actor)
        ]
        source.sort(
            key=lambda item: (
                (item.assessment_status or "not_started") not in STARTABLE_ASSESSMENT_STATES,
                item.due_at or datetime.max.replace(tzinfo=UTC),
                item.task_ref,
            )
        )
        rows = [
            ToolRow(
                ref=item.task_ref,
                status=item.assessment_status or "not_started",
                due_at=item.due_at,
            )
            for item in source[:limit]
        ]
    elif actor.role is BackendRole.TEACHER:
        source = [
            TeacherTaskProgressDto.model_validate(row)
            for row in await service.teacher_progress(actor)
        ]
        rows = [
            ToolRow(
                ref=item.task_ref,
                label=item.class_ref,
                status=item.task_status,
                due_at=item.due_at,
                completed=item.completed_count,
                total=item.active_enrollment_count,
            )
            for item in source[:limit]
        ]
    elif actor.role is BackendRole.PSYCHOLOGICAL_SPECIALIST:
        if container.professional_reviews is None:
            raise error(ErrorCode.DEPENDENCY_UNAVAILABLE, detail="review tasks unavailable")
        source = [
            ProfessionalReviewTaskDto.model_validate(row)
            for row in await container.professional_reviews.list_tasks(actor)
        ]
        rows = [
            ToolRow(ref=item.task_ref, label=item.class_display_name or item.class_ref)
            for item in source[:limit]
        ]
    else:
        source = [
            TaskDto.model_validate(row) for row in await service.list_class_tasks(actor, None)
        ]
        rows = [
            ToolRow(
                ref=item.task_ref,
                label=item.class_ref,
                status=item.status,
                due_at=item.due_at,
                total=item.active_enrollment_count,
            )
            for item in source[:limit]
        ]
    return ToolResult(kind=_ROLE_TO_TOOL[actor.role], rows=rows, total=len(source))


def _ensure_demo_admin(request: Request, actor: Actor) -> None:
    settings = request.app.state.container.settings
    if (
        actor.role is not BackendRole.ADMIN
        or not settings.public_demo.site_key
        or not is_public_demo_school_ref(actor.school_ref or "")
    ):
        raise error(ErrorCode.FORBIDDEN, detail="synthetic administrator context required")


def _signature(
    request: Request,
    actor: Actor,
    content: str,
    *,
    purpose: str = "workspace-agent/create-class/v1",
) -> str:
    session = request.state.session
    settings = request.app.state.container.settings
    key = school_csrf_secret_bytes(settings.school_csrf_secret)
    message = fingerprint(
        {
            "purpose": purpose,
            "actor": actor.user_id,
            "school": actor.school_id,
            "school_ref": actor.school_ref,
            "role": actor.role.value,
            "session": session.session_id,
            "context": session.active_context_id,
            "content": content,
        }
    )
    return hmac.new(key, message.encode(), hashlib.sha256).hexdigest()


def _class_token(
    request: Request, actor: Actor, class_ref: str, *, run_id: str | None = None
) -> str:
    content = f"{int(datetime.now(UTC).timestamp()) + 300}.{uuid4().hex}.{class_ref}"
    if run_id is not None:
        content = f"{content}~{run_id}"
    return f"{content}.{_signature(request, actor, content)}"


def _ensure_run_preview(
    request: Request, actor: Actor, run_id: str | None, *, token: str | None = None
) -> None:
    history = getattr(request.app.state, "workspace_history", None)
    allowed = (
        history.allows_confirmation(workspace_owner(actor), run_id, token=token)
        if history is not None else run_id is None
    )
    if not allowed:
        raise error(ErrorCode.WORKFLOW_CONFLICT, detail="operation preview no longer active")


@router.get("/snapshot")
async def snapshot(request: Request, actor: CurrentActor):
    _check_actor(actor)
    return _respond(request, await _snapshot(request, actor))


@router.post("/run")
async def run(request: Request, payload: RunRequest, actor: CsrfActor):
    _check_actor(actor)
    request.app.state.container.rate_limiter.check("support", actor.user_id)
    command = payload.text.rstrip("？?。！!").strip()
    if re.fullmatch(_COMMANDS[actor.role], command):
        result = await _snapshot(request, actor)
    elif actor.role is BackendRole.STUDENT and command in _KNOWLEDGE:
        result = ToolResult(kind="education_topic", topic=_KNOWLEDGE[command])
    elif actor.role is BackendRole.ADMIN and (match := _CREATE.fullmatch(command)):
        _ensure_demo_admin(request, actor)
        class_ref = match[1]
        result = ToolResult(
            kind="preview_class",
            class_ref=class_ref,
            token=_class_token(request, actor, class_ref),
        )
    else:
        result = ToolResult(kind="unknown")
    return _respond(request, result)


@router.post("/confirm")
async def confirm(request: Request, payload: ConfirmRequest, actor: CsrfActor):
    _check_actor(actor)
    _ensure_demo_admin(request, actor)
    request.app.state.container.rate_limiter.check("support", actor.user_id)
    match = _CONFIRM_TOKEN.fullmatch(payload.token)
    if not match:
        raise error(ErrorCode.WORKFLOW_CONFLICT, detail="operation preview is invalid or expired")
    expires, nonce, class_ref, run_id, signature = match.groups()
    content = payload.token.rsplit(".", 1)[0]
    if int(expires) < int(datetime.now(UTC).timestamp()) or not hmac.compare_digest(
        signature, _signature(request, actor, content)
    ):
        raise error(ErrorCode.WORKFLOW_CONFLICT, detail="operation preview is invalid or expired")
    _ensure_run_preview(request, actor, run_id, token=payload.token)
    result = await request.app.state.container.school_tasks.create_class(
        actor,
        class_ref,
        agent_trace_id=current_request_context(request).trace_id,
        idempotency=(
            f"workspace-agent-{nonce}",
            fingerprint({"class_ref": class_ref}),
            fingerprint(
                {
                    "operation": "workspace-agent:create-class",
                    "school": actor.school_id,
                    "actor": actor.user_id,
                }
            ),
        ),
    )
    stored = ClassDto.model_validate(result)
    return _respond(request, ToolResult(kind="class_created", class_ref=stored.class_ref))
