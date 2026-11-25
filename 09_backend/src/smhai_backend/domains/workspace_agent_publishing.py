"""Prepare and confirm a standard assessment using the existing school task service."""

from __future__ import annotations

import base64
import hmac
import re
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.idempotency import fingerprint
from smhai_backend.domains.models import Actor
from smhai_backend.domains.school_tasks.router import _idempotency_scope
from smhai_backend.domains.school_tasks.schemas import TaskDto

from .workspace_agent import _ensure_demo_admin, _signature
from .workspace_agent_cat import authorized_handoff

_PURPOSE = "workspace-agent/publish-task/v1"
_TOKEN = re.compile(r"([0-9]{10})\.([a-f0-9]{32})\.([a-zA-Z0-9_=-]{16,700})\.([a-f0-9]{64})")


class TaskPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    class_designation: str = Field(min_length=1, max_length=128)
    opens_at: AwareDatetime | None = None
    due_at: AwareDatetime


class Schedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    class_ref: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    opens_at: AwareDatetime
    due_at: AwareDatetime
    activation_ref: str | None = Field(default=None, pattern=r"^CACT_[A-Za-z0-9-]{36}$")
    handoff_ref: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class TaskConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=120, max_length=850)


async def preview(
    request: Request,
    actor: Actor,
    proposal: TaskPreview | None,
    *,
    class_alias,
    handoff_ref: str | None = None,
) -> tuple[dict, dict]:
    _ensure_demo_admin(request, actor)
    handoff = await authorized_handoff(request, actor, handoff_ref) if handoff_ref else None
    if handoff:
        proposal = TaskPreview(
            class_designation=handoff["class_designation"],
            opens_at=datetime.fromisoformat(handoff["opens_at"]) if handoff["opens_at"] else None,
            due_at=datetime.fromisoformat(handoff["due_at"]),
        )
    if proposal is None:
        raise error(ErrorCode.VALIDATION_FAILED, detail="task schedule is missing")
    service = request.app.state.container.school_tasks
    target = proposal.class_designation.strip().casefold()
    matches = [
        row
        for row in await service.list_classes(actor)
        if row["status"] == "ACTIVE"
        and target
        in {
            str(row["class_ref"]).casefold(),
            str(row.get("display_name") or "").casefold(),
            class_alias(row["class_ref"]),
        }
    ]
    if len(matches) != 1:
        raise error(
            ErrorCode.RESOURCE_NOT_FOUND, detail="the active class is ambiguous or unavailable"
        )
    now = datetime.now(UTC)
    # A missing opening time means the current time. Persist it in the preview
    # so retries and idempotency replays use the same business parameters.
    schedule = Schedule(
        class_ref=matches[0]["class_ref"],
        opens_at=proposal.opens_at or now,
        due_at=proposal.due_at,
        activation_ref=handoff["activation_ref"] if handoff else None,
        handoff_ref=handoff_ref,
    )
    if schedule.due_at <= max(now, schedule.opens_at):
        raise error(ErrorCode.VALIDATION_FAILED, detail="the deadline must be after opening")
    encoded = base64.urlsafe_b64encode(schedule.model_dump_json(exclude_none=True).encode()).decode(
        "ascii"
    )
    nonce = handoff_ref or uuid4().hex
    content = f"{int(now.timestamp()) + 300}.{nonce}.{encoded}"
    token = f"{content}.{_signature(request, actor, content, purpose=_PURPOSE)}"
    return (
        {
            "kind": "preview_task",
            **schedule.model_dump(mode="json", exclude={"activation_ref", "handoff_ref"}),
            "class_label": matches[0].get("display_name") or schedule.class_ref,
            "plan_label": handoff["plan_name"] if handoff else None,
            "enrolled": matches[0]["active_student_count"],
            "token": token,
        },
        {
            "confirmation_required": True,
            "opens_at": schedule.opens_at.isoformat(),
            "due_at": schedule.due_at.isoformat(),
            "current_students": matches[0]["active_student_count"],
        },
    )


async def confirm(request: Request, actor: Actor, token: str) -> TaskDto:
    _ensure_demo_admin(request, actor)
    conflict = error(ErrorCode.WORKFLOW_CONFLICT, detail="operation preview is invalid or expired")
    match = _TOKEN.fullmatch(token)
    if not match:
        raise conflict
    expires, nonce, encoded, signature = match.groups()
    content = f"{expires}.{nonce}.{encoded}"
    if int(expires) < int(datetime.now(UTC).timestamp()) or not hmac.compare_digest(
        signature, _signature(request, actor, content, purpose=_PURPOSE)
    ):
        raise conflict
    try:
        schedule = Schedule.model_validate_json(base64.urlsafe_b64decode(encoded))
    except (ValueError, ValidationError):
        raise conflict from None
    if schedule.due_at <= datetime.now(UTC):
        raise conflict
    if schedule.handoff_ref:
        handoff = await authorized_handoff(request, actor, schedule.handoff_ref, replay=True)
        if handoff["activation_ref"] != schedule.activation_ref:
            raise conflict
        if task_ref := handoff.get("published_task_ref"):
            tasks = await request.app.state.container.school_tasks.list_class_tasks(
                actor, schedule.class_ref
            )
            for task in tasks:
                if task["task_ref"] == task_ref:
                    return TaskDto.model_validate(task)
            raise conflict
    payload = schedule.model_dump(
        mode="json", exclude={"class_ref", "handoff_ref"}, exclude_none=True
    )
    scope = (
        fingerprint({"school": actor.school_ref, "handoff": schedule.handoff_ref})
        if schedule.handoff_ref
        else _idempotency_scope(actor, f"class:{schedule.class_ref}:task:publish")
    )
    result = await request.app.state.container.school_tasks.publish_task(
        actor,
        schedule.class_ref,
        opens_at=schedule.opens_at,
        due_at=schedule.due_at,
        activation_ref=schedule.activation_ref,
        idempotency=(
            f"workspace-agent-publish-{nonce}",
            fingerprint(payload),
            scope,
        ),
    )
    verified = TaskDto.model_validate(result)
    if schedule.handoff_ref:
        store = request.app.state.workspace_history.cat
        store.mark_published(actor.school_ref, schedule.handoff_ref, verified.task_ref)
    return verified
