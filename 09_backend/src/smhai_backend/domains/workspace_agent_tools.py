"""Role-scoped tools with separate browser and provider projections."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal
from uuid import uuid4

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.domains.school_directory.schemas import SchoolDirectoryDto

from . import workspace_agent_cat as cat_workflow
from .workspace_agent import _ensure_demo_admin, _signature, _snapshot
from .workspace_agent_publishing import TaskPreview
from .workspace_agent_publishing import preview as preview_publication

STUDENT = BackendRole.STUDENT
TEACHER = BackendRole.TEACHER
SPECIALIST = BackendRole.PSYCHOLOGICAL_SPECIALIST
ADMIN = BackendRole.ADMIN


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskWindow(Arguments):
    active_from: date | None = None
    active_through: date | None = None
    include_report: bool = False


class StudentTask(Arguments):
    task: str = Field(pattern=r"^assessment-[a-f0-9]{12}$")


class NewClass(Arguments):
    class_ref: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,47}$")


class Draft(Arguments):
    filename: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,55}\.md$")
    markdown: str = Field(min_length=1, max_length=3800)


class Panel(Arguments):
    workflow: Literal[
        "review", "cat", "resources", "support", "knowledge", "feedback", "publish", "system"
    ]


@dataclass(frozen=True, slots=True)
class Tool:
    label: str
    description: str
    roles: tuple[BackendRole, ...]
    args: type[BaseModel] = Arguments

    def definition(self, name: str) -> dict:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": self.description,
                "parameters": self.args.model_json_schema(),
            },
        }


_ALL = (STUDENT, TEACHER, SPECIALIST, ADMIN)
TOOLS = {
    "list_student_assessments": Tool(
        "查询待完成测评",
        "Read the student's assigned assessments with current status and due dates.",
        (STUDENT,),
    ),
    "open_student_assessment": Tool(
        "准备测评界面",
        "Show an assessment consent and start component. Use the task alias from "
        "list_student_assessments. Only the student can start and answer.",
        (STUDENT,),
        StudentTask,
    ),
    "class_progress": Tool(
        "查询授权班级进度",
        "Read task-level class completion counts. Optional dates select tasks whose open period "
        "overlaps those inclusive dates in China Standard Time. Counts are current totals. "
        "Set include_report=true if the teacher requests a downloadable factual progress summary.",
        (TEACHER,),
        TaskWindow,
    ),
    "make_class_progress_report": Tool(
        "生成班级统计简报",
        "Use this for a teacher asking for a class assignment progress report or export. "
        "Fetch the current authorized task data and create a downloadable Markdown report "
        "with verified counts and the completion ratio. No prose or data arguments are needed.",
        (TEACHER,),
        TaskWindow,
    ),
    "review_tasks": Tool(
        "查询专业复核任务",
        "List tasks the specialist is authorized to review, without results.",
        (SPECIALIST,),
    ),
    "inspect_cat_attachment": Tool(
        "验证合成 CAT 题库",
        "Validate a private school GRM JSON attachment using the real CAT engine. "
        "This is read-only and returns item counts and whether a configuration was supplied.",
        (SPECIALIST,),
    ),
    "prepare_cat_draft": Tool(
        "准备 CAT 方案和任务草案",
        "Prepare a private task handoff using the validated CAT file. Requires a class "
        "designation, plan name and deadline with timezone. Use attachment configuration "
        "when present, otherwise show the existing school engineering template in the "
        "preview. The specialist must separately confirm saving and synthetic eligibility. "
        "Only a school administrator can publish the task.",
        (SPECIALIST,),
        cat_workflow.CatDraftProposal,
    ),
    "list_cat_drafts": Tool(
        "查找我的 CAT 草案",
        "Resume a CAT handoff and check its real status after a specialist approval.",
        (SPECIALIST,),
    ),
    "list_cat_handoffs": Tool(
        "查找已批准的 CAT 任务交接",
        "List synthetic school CAT task handoffs already approved by this school's specialist.",
        (ADMIN,),
    ),
    "preview_cat_publication": Tool(
        "核对 CAT 任务发布",
        "Prepare a confirmation for a specific handoff from list_cat_handoffs. "
        "The class, dates and approved CAT version come from the handoff.",
        (ADMIN,),
        cat_workflow.CatHandoffSelection,
    ),
    "school_tasks": Tool(
        "查询学校测评任务",
        "Read this school's published tasks and enrollment totals.",
        (ADMIN,),
    ),
    "school_student_counts": Tool(
        "核对学生账号和班级人数",
        "Read actual school student account counts and class memberships.",
        (ADMIN,),
    ),
    "preview_new_class": Tool(
        "预览新建班级",
        "Prepare a confirmation for a synthetic class code supplied by the user. "
        "Only the user can confirm the write.",
        (ADMIN,),
        NewClass,
    ),
    "preview_assessment_publication": Tool(
        "预览测评发布",
        "Preview the default synthetic school assessment publication for an existing class. "
        "Use the class alias from school_student_counts, or the exact user-provided class name. "
        "Include a deadline as ISO 8601 with its offset. If the user requests immediate opening, "
        "omit opens_at. Never use this for a custom CAT plan or a real school. "
        "Ask for confirmation through the preview card.",
        (ADMIN,),
        TaskPreview,
    ),
    "open_roster_import": Tool(
        "打开名单导入工作台",
        "Open the roster preview, import and credential download component. "
        "It handles the selected roster privately. The user must confirm the import.",
        (ADMIN,),
    ),
    "open_workflow": Tool(
        "准备业务工作台",
        "Show an authorized embedded workflow: review and cat are for specialists, "
        "resources for specialists, support for students, teachers and specialists, knowledge "
        "and feedback for students, publish and system for school administrators. "
        "Content in the panel is private and does not go to the model.",
        _ALL,
        Panel,
    ),
    "save_markdown": Tool(
        "生成 Markdown 文件",
        "Create a downloadable Markdown document. Use verified figures from "
        "tools. It must contain no personal information or private psychological material.",
        _ALL,
        Draft,
    ),
}
_PANEL_ROLES = {
    "review": (SPECIALIST,),
    "cat": (SPECIALIST,),
    "resources": (SPECIALIST,),
    "support": (STUDENT, TEACHER, SPECIALIST),
    "knowledge": (STUDENT,),
    "feedback": (STUDENT,),
    "publish": (ADMIN,),
    "system": (ADMIN,),
}
_STATES = {
    "PUBLISHED",
    "REVOKED",
    "CLOSED",
    "ACTIVE",
    "INACTIVE",
    "not_started",
    "created",
    "in_progress",
    "completed",
    "abandoned",
    "invalid",
}


def _alias(prefix: str, ref: str) -> str:
    return prefix + "-" + hashlib.sha256(ref.encode()).hexdigest()[:12]


def _date(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


async def preview_cat_handoff(request: Request, actor: Actor, ref: str):
    return await preview_publication(
        request, actor, None, class_alias=lambda key: _alias("class", key), handoff_ref=ref
    )


async def execute_tool(
    request: Request,
    actor: Actor,
    name: str,
    arguments: BaseModel,
    *,
    cat_attachment_ref: str | None = None,
):
    """Return (browser component, model data). Only explicitly projected fields leave."""
    container = request.app.state.container
    if name == "inspect_cat_attachment":
        return await cat_workflow.inspect(request, actor, cat_attachment_ref)
    if name == "prepare_cat_draft" and isinstance(arguments, cat_workflow.CatDraftProposal):
        return await cat_workflow.prepare(request, actor, arguments, cat_attachment_ref)
    if name == "list_cat_drafts":
        return cat_workflow.drafts(request, actor)
    if name == "list_cat_handoffs":
        return cat_workflow.handoffs(request, actor)
    if name == "preview_cat_publication" and isinstance(
        arguments, cat_workflow.CatHandoffSelection
    ):
        return await preview_cat_handoff(request, actor, arguments.handoff_ref)
    if name in {"list_student_assessments", "review_tasks", "school_tasks"}:
        snapshot = await _snapshot(request, actor, limit=24)
        rows = [row.model_dump(mode="json") for row in snapshot.rows]
        model_rows = [
            {
                "task": _alias("assessment", row.ref),
                "status": row.status if row.status in _STATES else None,
                "due_at": _date(row.due_at),
                "total": row.total,
            }
            for row in snapshot.rows
        ]
        return (
            {"kind": snapshot.kind, "rows": rows, "total": snapshot.total},
            {"rows": model_rows, "total": snapshot.total, "shown": len(model_rows)},
        )
    if name == "open_student_assessment" and isinstance(arguments, StudentTask):
        snapshot = await _snapshot(request, actor, limit=24)
        for row in snapshot.rows:
            if _alias("assessment", row.ref) == arguments.task and row.status in {
                "not_started",
                "created",
                "in_progress",
            }:
                return (
                    {"kind": "assessment_picker", "task_ref": row.ref, "due_at": _date(row.due_at)},
                    {"ready_for_student": True},
                )
        raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="assessment task is unavailable")
    if name in {"class_progress", "make_class_progress_report"} and isinstance(
        arguments, TaskWindow
    ):
        from datetime import timedelta, timezone

        from .school_tasks.schemas import TeacherTaskProgressDto

        if (
            arguments.active_from
            and arguments.active_through
            and arguments.active_from > arguments.active_through
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="invalid date range")
        china = timezone(timedelta(hours=8))
        rows = []
        for source in await container.school_tasks.teacher_progress(actor):
            item = TeacherTaskProgressDto.model_validate(source)
            opened = item.opens_at.astimezone(china).date()
            due = item.due_at.astimezone(china).date() if item.due_at else None
            if arguments.active_from and due and due < arguments.active_from:
                continue
            if arguments.active_through and opened > arguments.active_through:
                continue
            rows.append(
                {
                    "ref": item.task_ref,
                    "label": item.class_ref,
                    "due_at": _date(item.due_at),
                    "completed": item.completed_count,
                    "total": item.active_enrollment_count,
                    "status": item.task_status,
                }
            )
        completions = sum(row["completed"] for row in rows)
        enrollments = sum(row["total"] for row in rows)
        view = {"kind": "class_progress", "rows": rows[:30], "total": len(rows)}
        with_report = arguments.include_report or name == "make_class_progress_report"
        if with_report:
            ratio = f"{completions / enrollments:.1%}" if enrollments else "无可计算分母"
            view["artifact"] = {
                "filename": "class-assessment-progress.md",
                "markdown": (
                    "# 班级测评完成情况\n\n"
                    f"- 授权任务数：{len(rows)}\n"
                    f"- 已提交人次：{completions}\n"
                    f"- 有效参测人次：{enrollments}\n"
                    f"- 任务完成率：{ratio}\n\n"
                    "数据来自本次查询。同一名学生在不同任务中的参测分别计数。\n"
                ),
            }
        return (
            view,
            {
                "tasks": len(rows),
                "completions": completions,
                "enrollments": enrollments,
                "artifact_ready": with_report,
                "counts_by_class": dict(
                    Counter(_alias("class", row["label"]) for row in rows[:30])
                ),
                "rows": [
                    {
                        "class": _alias("class", row["label"]),
                        "completed": row["completed"],
                        "total": row["total"],
                        "due_at": row["due_at"],
                    }
                    for row in rows[:30]
                ],
            },
        )
    if name == "school_student_counts":
        directory = SchoolDirectoryDto.model_validate(
            await container.school_directory.get_directory(actor)
        )
        counts = Counter(
            member.account_status for member in directory.members if member.role == "student"
        )
        return (
            {
                "kind": "school_student_counts",
                "total": sum(counts.values()),
                "active": counts["ACTIVE"],
                "rows": [
                    {
                        "ref": item.class_ref,
                        "label": item.display_name or item.class_ref,
                        "total": item.active_student_count,
                    }
                    for item in directory.classes[:60]
                ],
                "class_count": len(directory.classes),
            },
            {
                "total_students": sum(counts.values()),
                "active_accounts": counts["ACTIVE"],
                "class_count": len(directory.classes),
                "memberships": sum(item.active_student_count for item in directory.classes),
                "classes": [
                    {
                        "class": _alias("class", item.class_ref),
                        "active_students": item.active_student_count,
                    }
                    for item in directory.classes[:60]
                ],
            },
        )
    if name == "preview_new_class" and isinstance(arguments, NewClass):
        _ensure_demo_admin(request, actor)
        class_ref = arguments.class_ref
        content = f"{int(datetime.now(UTC).timestamp()) + 300}.{uuid4().hex}.{class_ref}"
        return (
            {
                "kind": "preview_class",
                "class_ref": class_ref,
                "token": f"{content}.{_signature(request, actor, content)}",
            },
            {"confirmation_required": True},
        )
    if name == "open_roster_import":
        return {"kind": "roster_import"}, {"confirmation_required": True, "workbench_ready": True}
    if name == "preview_assessment_publication" and isinstance(arguments, TaskPreview):
        return await preview_publication(
            request, actor, arguments, class_alias=lambda ref: _alias("class", ref)
        )
    if name == "open_workflow" and isinstance(arguments, Panel):
        if actor.role not in _PANEL_ROLES[arguments.workflow]:
            raise error(ErrorCode.FORBIDDEN, detail="workflow is not available to this role")
        return {"kind": "workflow", "workflow": arguments.workflow}, {"workbench_ready": True}
    raise error(ErrorCode.VALIDATION_FAILED, detail="tool arguments are invalid")
