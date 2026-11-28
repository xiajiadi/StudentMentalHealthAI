"""HTTP integration checks for workspace role, CSRF and confirmation boundaries."""

import asyncio
import csv
import json
from datetime import UTC, datetime, timedelta
from io import BytesIO, StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zipfile import ZipFile

import pytest
from pwdlib import PasswordHash

from smhai_backend.core.errors import BackendError
from smhai_backend.domains import workspace_agent_feedback_guide, workspace_agent_formula
from smhai_backend.domains.models import BackendRole, SchoolRoleContext, SyntheticUser
from smhai_backend.domains.school_operations_audit.service import SchoolOperationsAuditService
from smhai_backend.domains.school_research_sources import library
from smhai_backend.domains.workspace_agent_documents import (
    completed_workspace_documents,
    select_workspace_document,
)
from smhai_backend.domains.workspace_agent_formula_worker import _checked_formula
from smhai_backend.domains.workspace_agent_history import WorkspaceHistory

BASE = "/api/v1/workspace-agent"
FIRST = "PUBLICDEMO_" + "a" * 64
SECOND = "PUBLICDEMO_" + "b" * 64
ACCOUNT = "workspace-qa"
PASSWORD = "qa-only-synthetic-password"
FIXTURES = Path(__file__).resolve().parents[2] / "01_cat-engine" / "fixtures"


@pytest.fixture
def tools(app, monkeypatch):
    container = app.state.container
    contexts = (
        SchoolRoleContext("qa-admin", BackendRole.ADMIN, 1, FIRST),
        SchoolRoleContext("qa-admin-other", BackendRole.ADMIN, 2, SECOND),
        SchoolRoleContext("qa-teacher", BackendRole.TEACHER, 1, FIRST),
        SchoolRoleContext("qa-student", BackendRole.STUDENT, 1, FIRST),
        SchoolRoleContext("qa-specialist", BackendRole.PSYCHOLOGICAL_SPECIALIST, 1, FIRST),
    )
    user = SyntheticUser(
        user_id="USER_workspace_qa",
        username=ACCOUNT,
        role=BackendRole.ADMIN,
        subject_id=None,
        password_hash=PasswordHash.recommended().hash(PASSWORD),
        scope_profile="school_tenant",
        school_contexts=contexts,
    )
    container.users._add(user)
    monkeypatch.setattr(container.settings, "school_csrf_secret", "fe" * 32)
    monkeypatch.setattr(container.settings.public_demo, "site_key", "test-site-key")
    now = datetime.now(UTC)
    task = dict(
        class_ref="QA-class",
        task_ref="TASK_workspace",
        task_status="PUBLISHED",
        opens_at=now,
        due_at=None,
        published_enrollment_count=5,
        active_enrollment_count=5,
        revoked_enrollment_count=0,
        not_started_count=3,
        created_count=0,
        in_progress_count=0,
        completed_count=2,
        abandoned_count=0,
        invalid_count=0,
        student_name="must-not-leak",
        assessment_id="must-not-leak",
    )
    service = SimpleNamespace(
        teacher_progress=AsyncMock(return_value=[task]),
        list_student_tasks=AsyncMock(return_value=[{**task, "status": "PUBLISHED"}]),
        list_class_tasks=AsyncMock(
            return_value=[
                {
                    **task,
                    "status": "PUBLISHED",
                    "published_at": now,
                    "instrument_id": "synthetic.instrument",
                    "instrument_version": "1",
                }
            ]
        ),
        create_class=AsyncMock(
            return_value={
                "class_ref": "ROOM-1",
                "status": "ACTIVE",
                "active_student_count": 0,
                "active_teacher_count": 0,
            }
        ),
        list_classes=AsyncMock(
            return_value=[
                {
                    "class_ref": "QA-class",
                    "display_name": "合成班",
                    "status": "ACTIVE",
                    "active_student_count": 5,
                    "active_teacher_count": 1,
                }
            ]
        ),
        publish_task=AsyncMock(
            return_value={
                "class_ref": "QA-class",
                "task_ref": "TASK_workspace_published",
                "status": "PUBLISHED",
                "opens_at": now,
                "due_at": now + timedelta(days=3),
                "published_at": now,
                "instrument_id": "synthetic.instrument",
                "instrument_version": "1",
                "published_enrollment_count": 5,
                "active_enrollment_count": 5,
                "revoked_enrollment_count": 0,
            }
        ),
    )
    monkeypatch.setattr(container, "school_tasks", service)
    monkeypatch.setattr(
        container,
        "professional_reviews",
        SimpleNamespace(
            list_tasks=AsyncMock(
                return_value=[
                    dict(
                        task_ref="TASK_workspace",
                        class_ref="QA-class",
                        class_display_name="合成班",
                        published_at=now,
                    )
                ]
            ),
        ),
    )
    return service


async def login(client):
    response = await client.post(
        "/api/v1/auth/login", json={"username": ACCOUNT, "password": PASSWORD}
    )
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["data"]["csrf_token"]}


async def select(client, headers, role, school=FIRST):
    response = await client.post(
        "/api/v1/auth/active-context", headers=headers, json={"role": role, "school_ref": school}
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    ("role", "text", "kind"),
    [
        ("STUDENT", "还有哪些测评没做？", "student_tasks"),
        ("TEACHER", "查看班级进度", "class_progress"),
        ("PSYCHOLOGICAL_SPECIALIST", "查看测评复核任务", "review_tasks"),
        ("ADMIN", "查看学校测评任务", "school_tasks"),
    ],
)
async def test_workspace_executes_only_current_scoped_tool(client, tools, role, text, kind):
    assert (await client.get(f"{BASE}/snapshot")).status_code == 401
    headers = await login(client)
    assert (await client.get(f"{BASE}/snapshot")).status_code == 403
    await select(client, headers, role)
    response = await client.post(f"{BASE}/run", headers=headers, json={"text": text})
    assert response.status_code == 200
    result = response.json()["data"]
    assert result["schema_version"] == "workspace_agent.v1"
    assert result["kind"] == kind
    assert len(result["rows"]) == 1
    assert "must-not-leak" not in response.text
    unexpected = await client.post(
        f"{BASE}/run", headers=headers, json={"text": "读取别校学生的测评结果", "school": SECOND}
    )
    assert unexpected.status_code == 422


async def test_confirmation_is_signed_role_school_and_session_bound(client, tools):
    headers = await login(client)
    await select(client, headers, "ADMIN")
    preview = await client.post(f"{BASE}/run", headers=headers, json={"text": "新建班级 ROOM-1"})
    assert preview.status_code == 200
    assert preview.json()["data"]["kind"] == "preview_class"
    token = preview.json()["data"]["token"]
    tools.create_class.assert_not_called()

    async def confirm(value=token, used_headers=headers):
        return await client.post(f"{BASE}/confirm", headers=used_headers, json={"token": value})

    assert (await confirm(used_headers={})).status_code == 403
    assert (await confirm(token.replace("ROOM-1", "ROOM-2"))).status_code == 409
    await select(client, headers, "ADMIN", SECOND)
    assert (await confirm()).status_code == 409
    await select(client, headers, "TEACHER")
    assert (await confirm()).status_code == 403
    tools.create_class.assert_not_called()
    await select(client, headers, "ADMIN")
    first = await confirm()
    second = await confirm()
    assert first.status_code == second.status_code == 200
    assert first.json()["data"]["kind"] == "class_created"
    calls = tools.create_class.call_args_list
    assert calls[0].kwargs["idempotency"] == calls[1].kwargs["idempotency"]
    assert calls[0].kwargs["agent_trace_id"].startswith("TRACE_")
    assert tools.create_class.call_args.args[0].school_ref == FIRST
    new_headers = await login(client)
    await select(client, new_headers, "ADMIN")
    assert (await confirm(used_headers=new_headers)).status_code == 409


async def test_unrecognized_input_does_not_enter_a_tool_or_model(client, tools):
    headers = await login(client)
    await select(client, headers, "STUDENT")
    response = await client.post(
        f"{BASE}/run", headers=headers, json={"text": "合成私密文本 ANON_TEST"}
    )
    assert response.json()["data"]["kind"] == "unknown"
    assert "ANON_TEST" not in response.text
    tools.list_student_tasks.assert_not_called()
    topic = await client.post(f"{BASE}/run", headers=headers, json={"text": "帮我制定复习计划"})
    assert topic.json()["data"]["topic"] == "weekly_plan"


@pytest.fixture
def model_lane(app, tools, tmp_path, monkeypatch):
    history = WorkspaceHistory(str(tmp_path / "workspace.sqlite3"))
    monkeypatch.setattr(app.state, "workspace_history", history)
    container = app.state.container

    async def check_input(context, _):
        return SimpleNamespace(
            decision=SimpleNamespace(
                action="PROCEED",
                requires_human=False,
                disclosure_policy="SUMMARY" if context["actor_role"] == "TEACHER" else "FULL",
            ),
            sanitized_text=context["current_user_message"],
        )

    async def check_output(context, candidate, _context):
        return SimpleNamespace(
            decision=SimpleNamespace(
                action="PROCEED",
                requires_human=False,
                disclosure_policy="SUMMARY" if context["actor_role"] == "TEACHER" else "FULL",
            ),
            sanitized_text=candidate,
        )

    safety = SimpleNamespace(
        label="REAL_HTTP",
        check_input=AsyncMock(side_effect=check_input),
        check_output=AsyncMock(side_effect=check_output),
        close=AsyncMock(),
    )
    model = AsyncMock()
    monkeypatch.setattr(container, "safety", safety)
    monkeypatch.setattr(
        container, "llm", SimpleNamespace(workspace_agent_step=model, close=AsyncMock())
    )
    return model, safety


def assistant_step(*, tool=None, arguments="{}", text=None):
    calls = (
        []
        if tool is None
        else [
            {
                "id": "call_" + tool,
                "type": "function",
                "function": {"name": tool, "arguments": arguments},
            }
        ]
    )
    return {
        "model": "deepseek-flash",
        "completion_id": "synthetic-model-receipt",
        "message": {"role": "assistant", "tool_calls": calls, "content": text},
    }


async def test_model_selects_role_scoped_tools_and_uses_results(client, tools, model_lane):
    model, _ = model_lane
    url = f"{BASE}/conversation"
    headers = await login(client)
    await select(client, headers, "STUDENT")
    assert (
        await client.post(f"{url}/turn", json={"text": "问候", "synthetic_only": True})
    ).status_code == 403

    async def model_step(messages, definitions, _context):
        assert "preview_new_class" not in {entry["function"]["name"] for entry in definitions}
        if messages[-1]["role"] != "tool":
            return assistant_step(tool="list_student_assessments")
        result = json.loads(messages[-1]["content"])
        if "rows" in result:
            assert "TASK_workspace" not in messages[-1]["content"]
            assert "must-not-leak" not in messages[-1]["content"]
            return assistant_step(
                tool="open_student_assessment",
                arguments=json.dumps({"task": result["rows"][0]["task"]}),
            )
        assert result == {"ready_for_student": True}
        return assistant_step(text="已准备测评，请阅读说明后继续")

    model.side_effect = model_step
    response = await client.post(
        f"{url}/turn",
        headers=headers,
        json={"text": "哪项测验还得处理？帮我选出一项并打开说明", "synthetic_only": True},
    )
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["status"] == "completed"
    assert [event["view"]["kind"] for event in events if event["type"] == "tool_result"] == [
        "student_tasks",
        "assessment_picker",
    ]
    assert model.await_count == 3
    assert all(
        call.args[0].school_ref == FIRST for call in tools.list_student_tasks.await_args_list
    )
    assert (await client.get(url)).json()["data"]["events"] == events
    await select(client, headers, "ADMIN")
    assert (await client.get(url)).json()["data"]["events"] == []
    await select(client, headers, "ADMIN", SECOND)
    assert (await client.get(url)).json()["data"]["events"] == []


async def test_disconnected_client_recovers_the_same_run_and_does_not_execute_it_twice(
    client, tools, model_lane
):
    model, _ = model_lane
    path = f"{BASE}/conversation"
    headers = await login(client)
    await select(client, headers, "TEACHER")
    model_entered = asyncio.Event()
    continue_model = asyncio.Event()

    async def slow_model(messages, _definitions, _context):
        if messages[-1]["role"] == "tool":
            return assistant_step(text="已核对授权班级")
        model_entered.set()
        await continue_model.wait()
        return assistant_step(tool="class_progress")

    model.side_effect = slow_model
    payload = {"text": "查我的班级测评进度", "synthetic_only": True}
    delivery = asyncio.create_task(client.post(f"{path}/turn", headers=headers, json=payload))
    try:
        await asyncio.wait_for(model_entered.wait(), 3)
        active = (await client.get(path)).json()["data"]
        run_id = active["active_run_id"]
        assert active["active"] is True and run_id
        cursor = {"since": active["revision"]}
        unchanged = (await client.get(path, params=cursor)).json()["data"]
        assert unchanged["events"] is None and unchanged["active_run_id"] == run_id
        delivery.cancel()
        with pytest.raises(asyncio.CancelledError):
            await delivery
        assert (await client.get(path)).json()["data"]["active_run_id"] == run_id
        conflict = await client.post(f"{path}/turn", headers=headers, json=payload)
        assert conflict.status_code == 409
        continue_model.set()
        for _ in range(40):
            recovered = (await client.get(path, params=cursor)).json()["data"]
            if not recovered["active"]:
                break
            await asyncio.sleep(0.01)
        assert recovered["active_run_id"] is None
        assert recovered["events"][-1] == {
            "run_id": run_id, "type": "end", "status": "completed",
        }
        tools.teacher_progress.assert_awaited_once()
        assert model.await_count == 2
    finally:
        continue_model.set()
        if not delivery.done():
            delivery.cancel()
            await asyncio.gather(delivery, return_exceptions=True)


async def test_only_the_owner_can_cancel_active_task_and_timeout_allows_new_turn(
    client, model_lane
):
    model, _ = model_lane
    path = f"{BASE}/conversation"
    headers = await login(client)
    await select(client, headers, "ADMIN")
    model_entered = asyncio.Event()

    async def slow_model(*_args):
        model_entered.set()
        await asyncio.Event().wait()

    model.side_effect = slow_model
    payload = {"text": "查系统状态", "synthetic_only": True}
    delivery = asyncio.create_task(client.post(f"{path}/turn", headers=headers, json=payload))
    try:
        await asyncio.wait_for(model_entered.wait(), 3)
        run_id = (await client.get(path)).json()["data"]["active_run_id"]
        await select(client, headers, "ADMIN", SECOND)
        assert (await client.get(path)).json()["data"]["active_run_id"] is None
        wrong_scope = await client.post(f"{path}/cancel", headers=headers, json={"run_id": run_id})
        assert wrong_scope.status_code == 204
        await select(client, headers, "ADMIN")
        assert (await client.get(path)).json()["data"]["active_run_id"] == run_id
        assert (await client.post(f"{path}/cancel", json={"run_id": run_id})).status_code == 403
        cancelled = await client.post(f"{path}/cancel", headers=headers, json={"run_id": run_id})
        assert cancelled.status_code == 204
        response = await asyncio.wait_for(delivery, 3)
        assert json.loads(response.text.splitlines()[-1]) == {
            "run_id": run_id, "type": "end", "status": "interrupted",
        }
    finally:
        if not delivery.done():
            delivery.cancel()
            await asyncio.gather(delivery, return_exceptions=True)

    model.side_effect = [TimeoutError(), assistant_step(text="已重新处理")]
    failed = await client.post(f"{path}/turn", headers=headers, json=payload)
    terminal = json.loads(failed.text.splitlines()[-1])
    assert terminal["status"] == "failed"
    assert terminal["code"] == "dependency_timeout"
    retry = await client.post(f"{path}/turn", headers=headers, json=payload)
    complete = json.loads(retry.text.splitlines()[-1])
    assert complete["status"] == "completed"
    assert complete["run_id"] != terminal["run_id"]
    assert (await client.get(path)).json()["data"]["active"] is False


def test_lost_worker_lease_becomes_an_interruption_and_fences_old_events(tmp_path, monkeypatch):
    now = 1000
    monkeypatch.setattr("smhai_backend.domains.workspace_agent_history.time", lambda: now)
    history = WorkspaceHistory(str(tmp_path / "lost-worker.sqlite3"))
    run, _ = history.acquire("synthetic-owner")
    history.append("synthetic-owner", run, {"type": "user", "text": "查班级任务"})
    _, active, revision = history.read("synthetic-owner")
    assert active == run
    now += 220
    events, active, _ = history.read("synthetic-owner", revision)
    assert active is None
    assert events[-1] == {"type": "end", "status": "interrupted", "run_id": run}
    new_run, prior = history.acquire("synthetic-owner")
    assert new_run != run and prior == events
    with pytest.raises(BackendError, match="workflow_conflict"):
        history.append("synthetic-owner", run, {"type": "answer", "text": "已过期"})


async def test_feedback_guide_uses_the_published_revision_and_stays_out_of_the_model_lane(
    client, app, model_lane, monkeypatch
):
    model, safety = model_lane
    headers = await login(client)
    await select(client, headers, "STUDENT")
    source = "这是一条合成反馈。\n\n【老师建议的下一步】\n写下一个想向老师核对的问题。"
    reference = "FEED_synthetic_guide"
    school = SimpleNamespace(get_student_feedback=AsyncMock(return_value={
        "content_revision": 2, "body": source,
    }))
    monkeypatch.setattr(app.state.container, "school_feedback", school)
    scores = []

    def rank(question, passages):
        scores.append((question, passages))
        return [0.81, 0.31]

    monkeypatch.setattr(workspace_agent_feedback_guide, "_scores", rank)
    route = f"{BASE}/conversation/feedback-guide/{reference}"
    question = "该怎么准备要问老师的内容"
    payload = {"content_revision": 2, "question": question}
    wrong_revision = await client.post(
        route, headers=headers, json={**payload, "content_revision": 1}
    )
    assert wrong_revision.status_code == 409
    assert scores == []
    safety.check_input.assert_not_awaited()

    result = await client.post(route, headers=headers, json=payload)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "private, no-store"
    assert result.json()["data"] == {
        "status": "matched",
        "excerpts": [{"source": "next_steps", "text": "写下一个想向老师核对的问题。"}],
    }
    assert scores == [(question, ["写下一个想向老师核对的问题。", "这是一条合成反馈。"])]
    assert school.get_student_feedback.await_count == 3
    assert all(call.args[1] == reference for call in school.get_student_feedback.await_args_list)
    assert (await client.get(f"{BASE}/conversation")).json()["data"]["events"] == []

    safety.check_input.side_effect = None
    safety.check_input.return_value = SimpleNamespace(
        decision=SimpleNamespace(action="BLOCK", requires_human=True, disclosure_policy="NONE"),
    )
    blocked = await client.post(route, headers=headers, json=payload)
    assert blocked.json()["data"] == {"status": "needs_support", "excerpts": []}
    assert len(scores) == 1
    await select(client, headers, "TEACHER")
    assert (await client.post(route, headers=headers, json=payload)).status_code == 403
    model.assert_not_awaited()


async def test_feedback_measurement_reads_exact_owned_record_without_model(
    client, app, model_lane, monkeypatch
):
    model, safety = model_lane
    headers = await login(client)
    await select(client, headers, "STUDENT")
    reference = "FEED_synthetic_measurement"
    assessment_ref = "ASSESS_synthetic_measurement"
    record = SimpleNamespace(data_origin="SYNTHETIC", assessment={
        "schema_version": "assessment.v1",
        "assessment_id": assessment_ref,
        "subject_id": "SUBJ_synthetic_measurement",
        "instrument": {"instrument_id": "demo", "version": "1"},
        "population_scope": "SYNTHETIC",
        "status": "completed",
        "dimensions": {
            "DIM_A": {
                "theta": -0.2, "se": 0.45, "score": None, "band": "unknown",
                "interpretation_status": "estimated", "items_answered": 8,
            },
            "DIM_B": {
                "theta": None, "se": None, "score": None, "band": "unknown",
                "interpretation_status": "insufficient_data", "items_answered": 0,
            },
        },
        "risk": {
            "level": "normal", "need_human_review": False,
            "reason_codes": ["SYNTHETIC_ENGINEERING_FIXTURE"],
            "ruleset_id": "RULESET_synthetic_cat_v1",
        },
        "response_summary": {"items_answered": 8, "duration_seconds": 30},
        "provenance": {
            "source_adapter": "cat_engine", "adapter_version": "1",
            "cat_engine_version": "1", "item_bank_version": "demo-v1",
        },
        "timestamps": {
            "started_at": "2026-11-27T09:00:00Z", "completed_at": "2026-11-27T09:00:30Z",
        },
    })
    school = SimpleNamespace(get_student_feedback=AsyncMock(return_value={
        "assessment_ref": assessment_ref,
    }))
    monkeypatch.setattr(app.state.container, "school_feedback", school)
    assessment = AsyncMock(return_value=record)
    monkeypatch.setattr(app.state.container.assessments, "get_for_actor", assessment)
    route = f"{BASE}/conversation/feedback-measurement/{reference}"
    result = await client.get(route)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "private, no-store"
    assert result.json()["data"] == {
        "status": "engineering", "completed_at": "2026-11-27T09:00:30Z",
        "answered_count": 8, "item_bank_version": "demo-v1",
        "dimensions": [
            {"label": "DIM_A", "estimate": -0.2, "standard_error": 0.45},
            {"label": "DIM_B", "estimate": None, "standard_error": None},
        ],
    }
    assert school.get_student_feedback.await_args.args[1] == reference
    assert assessment.await_args.args[1] == assessment_ref
    assert assessment.await_args.kwargs["action"] == "assessment:read"
    assert (await client.get(f"{BASE}/conversation")).json()["data"]["events"] == []

    record.assessment["risk"]["ruleset_id"] = "RULESET_unknown"
    hidden = (await client.get(route)).json()["data"]
    assert (hidden["status"], hidden["dimensions"]) == ("not_displayable", [])
    for dimension in record.assessment["dimensions"].values():
        dimension.update(theta=None, se=None, interpretation_status="not_scored")
    unscored = (await client.get(route)).json()["data"]
    assert (unscored["status"], unscored["dimensions"]) == ("unscored", [])

    record.data_origin = "REAL"
    assert (await client.get(route)).status_code == 404
    record.data_origin = "SYNTHETIC"
    record.assessment["assessment_id"] = "ASSESS_some_other_record"
    assert (await client.get(route)).status_code == 404

    assessment.reset_mock()
    school.get_student_feedback.reset_mock()
    for role in ("TEACHER", "PSYCHOLOGICAL_SPECIALIST"):
        await select(client, headers, role)
        assert (await client.get(route)).status_code == 403
    assessment.assert_not_awaited()
    school.get_student_feedback.assert_not_awaited()
    model.assert_not_awaited()
    safety.check_input.assert_not_awaited()


@pytest.mark.parametrize(
    ("selection", "expected"),
    [("earliest_due", "TASK_soon"), ("resume_or_earliest_due", "TASK_started")],
)
async def test_student_selects_by_due_or_progress_across_all_authorized_assignments(
    client, tools, model_lane, selection, expected
):
    model, _ = model_lane
    headers = await login(client)
    await select(client, headers, "STUDENT")
    seed = tools.list_student_tasks.return_value[0]
    due = datetime.now(UTC) + timedelta(days=1)
    tools.list_student_tasks.return_value = [
        {**seed, "task_ref": f"TASK_regular_{i:02}", "due_at": due + timedelta(days=i + 1)}
        for i in range(25)
    ] + [
        {**seed, "task_ref": "TASK_completed", "due_at": due, "assessment_status": "completed"},
        {**seed, "task_ref": "TASK_no_due", "due_at": None},
        {**seed, "task_ref": "TASK_soon", "due_at": due + timedelta(hours=1)},
        {**seed, "task_ref": "TASK_started", "due_at": None, "assessment_status": "in_progress"},
    ]

    async def model_step(messages, _definitions, _context):
        if messages[-1]["role"] != "tool":
            return assistant_step(tool="list_student_assessments")
        result = json.loads(messages[-1]["content"])
        if "rows" in result:
            assert result["total"] == 29
            assert len(result["rows"]) == 24
            assert result["rows"][0]["due_at"] == (due + timedelta(hours=1)).isoformat()
            assert not any(row["status"] == "in_progress" for row in result["rows"])
            return assistant_step(
                tool="open_student_assessment", arguments=json.dumps({"task": selection})
            )
        assert result == {"ready_for_student": True}
        return assistant_step(text="请阅读说明后继续")

    model.side_effect = model_step
    response = await client.post(
        f"{BASE}/conversation/turn",
        headers=headers,
        json={"text": "请按我的测评安排打开一项", "synthetic_only": True},
    )
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    results = [event["view"] for event in events if event["type"] == "tool_result"]
    assert results[-1]["kind"] == "assessment_picker"
    assert results[-1]["task_ref"] == expected


async def test_unapproved_input_never_reaches_provider_or_history(client, model_lane):
    model, safety = model_lane
    safety.check_input.side_effect = None
    safety.check_input.return_value = SimpleNamespace(
        decision=SimpleNamespace(action="REVIEW_REQUIRED", requires_human=True),
    )
    headers = await login(client)
    await select(client, headers, "STUDENT")
    url = f"{BASE}/conversation"
    response = await client.post(
        f"{url}/turn",
        headers=headers,
        json={"text": "PRIVATE_FIXTURE_TEST", "synthetic_only": True},
    )
    assert response.status_code == 200
    assert '"status": "blocked"' in response.text
    model.assert_not_awaited()
    assert "PRIVATE_FIXTURE_TEST" not in (await client.get(url)).text


async def test_validated_tool_context_survives_filtered_answer(client, model_lane):
    model, safety = model_lane
    output_check = safety.check_output.side_effect
    safety.check_output.side_effect = [
        SimpleNamespace(decision=SimpleNamespace(action="BLOCK", disclosure_policy="NONE"))
    ]
    headers = await login(client)
    await select(client, headers, "STUDENT")
    url = f"{BASE}/conversation"
    model.side_effect = [
        assistant_step(tool="list_student_assessments"),
        assistant_step(text="FILTERED_FIXTURE_ONLY"),
    ]
    response = await client.post(
        f"{url}/turn", headers=headers, json={"text": "查询待办", "synthetic_only": True}
    )
    assert '"status": "blocked"' in response.text
    assert "FILTERED_FIXTURE_ONLY" not in response.text
    safety.check_output.side_effect = output_check
    model.side_effect = [assistant_step(text="我可以继续核对")]
    response = await client.post(
        f"{url}/turn", headers=headers, json={"text": "继续刚才的查询", "synthetic_only": True}
    )
    assert '"status": "completed"' in response.text
    prompt = json.dumps(model.await_args.args[0], ensure_ascii=False)
    assert "Prior tool result (list_student_assessments)" in prompt
    assert "FILTERED_FIXTURE_ONLY" not in prompt
    assert "TASK_workspace" not in prompt


async def test_business_turn_follow_up_keeps_references_without_old_status_or_answer(
    client, tools, model_lane
):
    model, _ = model_lane
    headers = await login(client)
    await select(client, headers, "STUDENT")
    url = f"{BASE}/conversation/turn"
    row = {**tools.list_student_tasks.return_value[0], "assessment_status": "completed"}
    tools.list_student_tasks.return_value = [row]
    model.side_effect = [
        assistant_step(tool="list_student_assessments"),
        assistant_step(text="旧查询只有已完成的测评"),
    ]
    await client.post(url, headers=headers, json={"text": "查目前的测评", "synthetic_only": True})

    async def refreshed(messages, _definitions, _context):
        if messages[-1]["role"] == "tool":
            assert json.loads(messages[-1]["content"])["total"] == 2
            return assistant_step(text="已核对当前列表")
        previous = [item["content"] for item in messages if item["role"] == "assistant"]
        assert not any("旧查询只有已完成的测评" in content for content in previous)
        history = next(content for content in previous if "list_student_assessments" in content)
        assert "refresh_required" in history
        assert "prior_references" in history
        assert "completed" not in history
        return assistant_step(tool="list_student_assessments")

    model.side_effect = refreshed
    tools.list_student_tasks.return_value = [
        row,
        {**row, "task_ref": "TASK_new", "assessment_status": None},
    ]
    response = await client.post(
        url, headers=headers, json={"text": "现在还有哪些测评要做", "synthetic_only": True}
    )
    events = [json.loads(line) for line in response.text.splitlines()]
    assert any(event.get("view", {}).get("total") == 2 for event in events)


async def test_student_feedback_resolves_only_visible_publications_without_model_content(
    client, app, model_lane, monkeypatch
):
    model, _ = model_lane
    stamp = datetime.now(UTC)
    feedback = {
        "feedback_ref": "FEED_private_fixture",
        "assessment_ref": "ASSESS_private_fixture",
        "level": "L3",
        "synthetic_only": True,
        "content_revision": 1,
        "state_version": 2,
        "status": "PUBLISHED",
        "title": "PRIVATE_FEEDBACK_TITLE",
        "body": "PRIVATE_FEEDBACK_BODY",
        "created_at": stamp,
        "published_at": stamp,
    }
    service = SimpleNamespace(list_student_feedback=AsyncMock(
        return_value={"total": 1, "items": [feedback]}
    ))
    monkeypatch.setattr(app.state.container, "school_feedback", service)

    async def model_step(messages, tools, _context):
        assert "list_published_feedback" in {tool["function"]["name"] for tool in tools}
        serialized = json.dumps(messages)
        for key in ("feedback_ref", "assessment_ref", "title", "body"):
            assert feedback[key] not in serialized
        if messages[-1]["role"] != "tool":
            return assistant_step(tool="list_published_feedback")
        result = json.loads(messages[-1]["content"])
        if result.get("newest_first"):
            return assistant_step(
                tool="open_published_feedback",
                arguments=json.dumps({"selection": result["newest_first"][0]}),
            )
        assert result == {"ready_for_student": True}
        return assistant_step(text="已准备好阅读已发布的反馈")

    model.side_effect = model_step
    headers = await login(client)
    url = f"{BASE}/conversation"
    await select(client, headers, "STUDENT")
    response = await client.post(
        f"{url}/turn", headers=headers, json={"text": "打开我的反馈", "synthetic_only": True}
    )
    views = [
        event["view"] for line in response.text.splitlines()
        if (event := json.loads(line))["type"] == "tool_result"
    ]
    assert views == [
        {"kind": "feedback_index", "total": 1},
        {"kind": "feedback_picker", "feedback_ref": feedback["feedback_ref"]},
    ]
    history = (await client.get(url)).text
    assert feedback["body"] not in history
    assert feedback["title"] not in history
    assert service.list_student_feedback.await_count == 2
    assert service.list_student_feedback.await_args.args[0].school_ref == FIRST

    await select(client, headers, "TEACHER")
    model.side_effect = [
        assistant_step(tool="list_published_feedback"),
        assistant_step(text="当前工作区无法查看学生反馈"),
    ]
    unauthorized = await client.post(
        f"{url}/turn", headers=headers, json={"text": "查学生反馈", "synthetic_only": True}
    )
    assert '"code": "forbidden"' in unauthorized.text
    assert service.list_student_feedback.await_count == 2


async def test_model_cannot_call_hidden_tool_and_can_recover(client, tools, model_lane):
    model, _ = model_lane
    model.side_effect = [
        assistant_step(tool="preview_new_class", arguments='{"class_ref":"DENIED"}'),
        assistant_step(text="当前角色无法新建班级"),
    ]
    headers = await login(client)
    await select(client, headers, "TEACHER")
    response = await client.post(
        f"{BASE}/conversation/turn",
        headers=headers,
        json={"text": "请创建班级 DENIED", "synthetic_only": True},
    )
    events = [json.loads(line) for line in response.text.splitlines()]
    assert any(event.get("code") == "forbidden" for event in events)
    assert events[-1]["status"] == "completed"
    assert model.await_args.args[0][-1]["content"] == '{"error": "forbidden"}'
    tools.create_class.assert_not_called()


async def test_staff_import_keeps_rows_private_and_rechecks_school_invitation_counts(
    client, app, model_lane, monkeypatch
):
    model, _ = model_lane
    summary = {
        "total_accounts": 20, "active_accounts": 18, "pending_activation": 2,
        "suspended_accounts": 2, "classes": 1, "invitations_issued": 2,
        "invitations_accepted": 4, "invitations_expired": 1, "invitations_revoked": 0,
        "recovery_queue_count": 3,
    }
    lifecycle = SimpleNamespace(
        account_summary=AsyncMock(return_value=summary),
        import_school_staff_roster=AsyncMock(),
    )
    monkeypatch.setattr(app.state.container, "school_account_lifecycle", lifecycle)
    headers = await login(client)
    url = f"{BASE}/conversation/turn"
    attach = {"text": "核对教职工名单", "synthetic_only": True, "attachment": "staff_roster"}
    await select(client, headers, "TEACHER")
    assert (await client.post(url, headers=headers, json=attach)).status_code == 403
    model.assert_not_awaited()
    await select(client, headers, "ADMIN")

    async def prepare(messages, definitions, _context):
        names = {item["function"]["name"] for item in definitions}
        assert "open_staff_roster_import" in names
        assert "open_roster_import" not in names
        if messages[-1]["role"] == "tool":
            assert json.loads(messages[-1]["content"]) == {
                "confirmation_required": True, "workbench_ready": True,
            }
            return assistant_step(text="已打开预览，请核对")
        return assistant_step(tool="open_staff_roster_import")

    model.side_effect = prepare
    started = await client.post(url, headers=headers, json=attach)
    events = [json.loads(line) for line in started.text.splitlines()]
    assert [event["view"] for event in events if event["type"] == "tool_result"] == [
        {"kind": "staff_roster_import"}
    ]
    lifecycle.import_school_staff_roster.assert_not_awaited()

    async def read_status(messages, definitions, _context):
        assert "staff_invitation_status" in {item["function"]["name"] for item in definitions}
        if messages[-1]["role"] == "tool":
            assert json.loads(messages[-1]["content"]) == {
                "issued": summary["invitations_issued"], "accepted": 4, "expired": 1, "revoked": 0,
            }
            return assistant_step(text="已核对学校邀请状态")
        return assistant_step(tool="staff_invitation_status")

    model.side_effect = read_status
    for expected in (2, 3):
        summary["invitations_issued"] = expected
        checked = await client.post(
            url,
            headers=headers,
            json={"text": "重新查询待接受的教职工邀请", "synthetic_only": True},
        )
        events = [json.loads(line) for line in checked.text.splitlines()]
        assert [event["view"] for event in events if event["type"] == "tool_result"] == [
            {"kind": "staff_invitation_status", "issued": expected,
             "accepted": 4, "expired": 1, "revoked": 0}
        ]
    assert lifecycle.account_summary.await_count == 2
    calls = lifecycle.account_summary.await_args_list
    assert {call.args[0].school_ref for call in calls} == {FIRST}


async def test_admin_audit_reads_requested_pages_and_keeps_only_query_for_next_turn(
    client, app, model_lane, monkeypatch
):
    model, _ = model_lane
    row_id = "c9096f3e-caf6-440b-a732-10df405b74e9"
    persistence = SimpleNamespace(school_operations_audit_list=AsyncMock(side_effect=[
        {"items": [{
            "event_ref": row_id,
            "created_at": datetime(2026, 11, 26, 8, tzinfo=UTC),
            "action": "school_tasks.task.published",
            "result": "SUCCESS",
            "actor_name": "private-operator",
            "resource": "private-task-id",
        }], "has_more": True},
        {"items": [], "has_more": False},
    ]))
    monkeypatch.setattr(app.state.container, "school_operations_audit",
                        SchoolOperationsAuditService(persistence=persistence))
    headers = await login(client)
    await select(client, headers, "ADMIN")
    url = f"{BASE}/conversation/turn"
    current_offset = 0

    async def model_step(messages, definitions, _context):
        audit_tool = next(
            item["function"] for item in definitions
            if item["function"]["name"] == "read_school_audit"
        )
        assert "limit" in audit_tool["parameters"]["required"]
        assert row_id not in json.dumps(messages)
        if messages[-1]["role"] == "tool":
            result = json.loads(messages[-1]["content"])
            assert result["query"] == {"category": "task", "offset": current_offset, "limit": 1}
            assert "private-operator" not in messages[-1]["content"]
            assert "private-task-id" not in messages[-1]["content"]
            assert result["visible_count"] == 1 - current_offset
            return assistant_step(text="已查询本页运营记录")
        if current_offset:
            earlier = next(
                item["content"] for item in messages
                if item["content"].startswith("Prior tool result (read_school_audit)")
            )
            assert json.loads(earlier.split(": ", 1)[1]) == {
                "refresh_required": True,
                "previous_query": {"category": "task", "offset": 0, "limit": 1},
            }
        return assistant_step(
            tool="read_school_audit",
            arguments=json.dumps({"category": "task", "offset": current_offset, "limit": 1}),
        )

    model.side_effect = model_step
    for current_offset, prompt in enumerate(("查本校最近一条任务运营记录", "同一类别下一条")):
        response = await client.post(url, headers=headers, json={
            "text": prompt, "synthetic_only": True,
        })
        events = [json.loads(line) for line in response.text.splitlines()]
        view = next(event["view"] for event in events if event["type"] == "tool_result")
        assert view["kind"] == "school_audit"
        assert view["query"]["offset"] == current_offset
        assert len(view["items"]) == 1 - current_offset
        assert row_id not in response.text and "private-operator" not in response.text
    reads = persistence.school_operations_audit_list.await_args_list
    assert [call.args[0].school_ref for call in reads] == [FIRST, FIRST]
    assert [call.kwargs for call in reads] == [
        {"offset": 0, "limit": 1, "category": "task"},
        {"offset": 1, "limit": 1, "category": "task"},
    ]


async def test_system_health_projects_fixed_names_and_states_for_admin_only(
    client, app, model_lane, monkeypatch
):
    model, _ = model_lane
    raw = {
        "cat": {"status": "READY", "integration": "private-url"},
        "post_assessment_worker": {"status": "DISABLED", "integration": "LOCAL_OUTBOX"},
        "safety": {"status": "private-upstream-text", "integration": "REAL_HTTP"},
        "private-service-name": {"status": "READY", "integration": "PRIVATE"},
    }
    matrix = AsyncMock(return_value=raw)
    monkeypatch.setattr(type(app.state.container), "dependency_matrix", matrix)
    headers = await login(client)
    url = f"{BASE}/conversation/turn"
    body = {"text": "查系统依赖情况", "synthetic_only": True}
    await select(client, headers, "TEACHER")

    async def denied(messages, definitions, _context):
        names = {item["function"]["name"] for item in definitions}
        assert {"read_system_health", "read_school_audit"}.isdisjoint(names)
        if messages[-1]["role"] == "tool":
            assert json.loads(messages[-1]["content"]) == {"error": "forbidden"}
            return assistant_step(text="当前角色无法查看此状态")
        return assistant_step(tool="read_system_health")

    model.side_effect = denied
    response = await client.post(url, headers=headers, json=body)
    assert '"code": "forbidden"' in response.text
    matrix.assert_not_awaited()

    await select(client, headers, "ADMIN")
    model.side_effect = [
        assistant_step(tool="read_system_health"),
        assistant_step(text="已查询当前依赖状态"),
    ]
    response = await client.post(url, headers=headers, json=body)
    result = json.loads(model.await_args.args[0][-1]["content"])
    assert result["statuses"]["cat"] == "READY"
    assert result["statuses"]["post_assessment_worker"] == "DISABLED"
    assert result["statuses"]["safety"] == result["statuses"]["rag"] == "UNKNOWN"
    assert "private-" not in response.text and "private-" not in json.dumps(result)
    matrix.assert_awaited_once()


async def test_document_preview_extracts_private_text_without_entering_history(client, model_lane):
    model, _ = model_lane
    source = BytesIO()
    paragraphs = ["Private sample from an isolated document", "测评用合成段落" * 2000]
    with ZipFile(source, "w") as writer:
        writer.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            + "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
            + "</w:document>",
        )
    headers = await login(client)
    await select(client, headers, "STUDENT")
    binary = {**headers, "Content-Type": "application/octet-stream"}
    url = f"{BASE}/conversation"
    result = await client.post(
        f"{url}/document-preview/docx", headers=binary, content=source.getvalue(),
    )
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert result.json()["data"]["text"].startswith(paragraphs[0])
    assert len(result.json()["data"]["text"]) == 12_000
    assert result.json()["data"]["characters"] == len("\n".join(paragraphs))
    malformed = await client.post(f"{url}/document-preview/pdf", headers=binary, content=b"bad")
    assert malformed.status_code >= 400
    assert (await client.get(url)).json()["data"]["events"] == []
    model.assert_not_awaited()


async def test_formula_preview_requires_a_session_and_keeps_formula_out_of_history(
    client, model_lane, monkeypatch
):
    model, _ = model_lane
    calls = []
    formula = r"\frac { 3 } { 4 } + \frac { 1 } { 2 }"

    def extract(content):
        calls.append(content)
        return formula

    monkeypatch.setattr(workspace_agent_formula, "extract_formula", extract)
    url = f"{BASE}/conversation/formula-preview"
    image = workspace_agent_formula.PNG_SIGNATURE + b"formula-preview-fixture"
    assert (await client.post(url, content=image)).status_code == 401
    headers = await login(client)
    await select(client, headers, "STUDENT")
    binary = {**headers, "Content-Type": "application/octet-stream"}
    for rejected in (b"not a PNG", image.ljust(workspace_agent_formula.MAX_BYTES + 1, b"0")):
        assert (await client.post(url, headers=binary, content=rejected)).status_code == 422
    assert (await client.post(url, headers=headers, content=image)).status_code == 422
    assert calls == []

    result = await client.post(url, headers=binary, content=image)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert result.json()["data"] == {"text": formula}
    assert calls == [image]
    history = await client.get(f"{BASE}/conversation")
    assert history.json()["data"]["events"] == []
    model.assert_not_awaited()


async def test_task_feedback_returns_only_the_published_reference_for_the_student(
    client, app, model_lane, monkeypatch
):
    model, _ = model_lane
    lookup = AsyncMock(side_effect=["FEED_private_match", None])
    monkeypatch.setattr(
        app.state.container,
        "school_feedback",
        SimpleNamespace(latest_student_feedback_for_task=lookup),
    )
    path = f"{BASE}/conversation/task-feedback"
    assert (await client.get(f"{path}/TASK_match")).status_code == 401
    headers = await login(client)
    await select(client, headers, "STUDENT")
    match = await client.get(f"{path}/TASK_match")
    assert match.status_code == 200
    assert match.headers["cache-control"] == "no-store"
    assert match.json() == {"data": {"feedback_ref": "FEED_private_match"}}
    assert (await client.get(f"{path}/TASK_pending")).json() == {"data": {"feedback_ref": None}}
    assert [call.args[1] for call in lookup.await_args_list] == ["TASK_match", "TASK_pending"]
    assert all(call.args[0].school_ref == FIRST for call in lookup.await_args_list)
    await select(client, headers, "TEACHER")
    assert (await client.get(f"{path}/TASK_match")).status_code == 403
    assert lookup.await_count == 2
    model.assert_not_awaited()


@pytest.mark.parametrize("latest", [False, True])
async def test_support_plan_tool_only_exposes_workflow_totals(
    client, app, model_lane, monkeypatch, latest,
):
    model, _ = model_lane
    support = SimpleNamespace(list_cases=AsyncMock(return_value={
        "items": [{
            "case_ref": "SSC_" + "a" * 32,
            "source": "TEACHER_REFERRAL",
            "category_code": "PEER_RELATION",
            "status": "TRIAGED",
            "state_version": 2,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }],
        "total": 1,
    }))
    monkeypatch.setattr(app.state.container, "school_support", support)
    headers = await login(client)
    await select(client, headers, "PSYCHOLOGICAL_SPECIALIST")

    async def step(messages, definitions, _context):
        available = {item["function"]["name"] for item in definitions}
        assert "prepare_specialist_support_plan" in available
        if messages[-1]["role"] == "tool":
            expected = {"triaged_count": 1} if latest else {
                "shown": 1, "total": 1, "counts": {"TRIAGED": 1},
            }
            assert json.loads(messages[-1]["content"]) == expected
            return assistant_step(text="可进一步核对这项支持请求")
        return assistant_step(
            tool="prepare_specialist_support_plan",
            arguments='{"selection":"latest_triaged"}' if latest else "{}",
        )

    model.side_effect = step
    response = await client.post(
        f"{BASE}/conversation/turn", headers=headers,
        json={"text": "为授权支持请求准备一份可确认的计划草案", "synthetic_only": True},
    )
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    view = next(event["view"] for event in events if event["type"] == "tool_result")
    kind = "latest_specialist_support_plan" if latest else "specialist_support_plan"
    assert view["kind"] == kind
    assert "SSC_" not in response.text
    assert "PEER_RELATION" not in response.text
    support.list_cases.assert_awaited_once()
    assert support.list_cases.await_args.args[0].school_ref == FIRST
    assert support.list_cases.await_args.kwargs == (
        {"limit": 1, "triaged_only": True} if latest else {"limit": 50}
    )


@pytest.mark.parametrize("formula", ("", "x^2 + \ufffd", r"\frac{1}{2", "a\nb", r"x^2 + \ · 3"))
def test_formula_worker_rejects_incomplete_or_unreadable_output(formula):
    with pytest.raises(ValueError):
        _checked_formula(formula)


async def test_school_library_tool_returns_only_counts(client, model_lane, monkeypatch, tmp_path):
    model, _ = model_lane
    monkeypatch.setenv("SMHAI_DEMO_LIBRARY_DIRECTORY", str(tmp_path))
    with (tmp_path / "sample.txt").open("w+b") as source:
        source.write(b"Worksheet material for the isolated fixture about revision planning.")
        library.add_document(library.library_path(FIRST), "PRIVATE_TITLE.txt", source, "test")
    model.side_effect = [
        assistant_step(tool="inspect_school_library"),
        assistant_step(text="已核对本校资料库"),
    ]
    headers = await login(client)
    await select(client, headers, "PSYCHOLOGICAL_SPECIALIST")
    result = await client.post(
        f"{BASE}/conversation/turn",
        headers=headers,
        json={"text": "查看资料库数量", "synthetic_only": True},
    )
    assert "school_library_inventory" in result.text
    assert "PRIVATE_TITLE" not in result.text
    assert json.loads(model.await_args.args[0][-1]["content"]) == {"total": 1, "chunks": 1}


async def test_education_articles_only_reaches_model_for_selected_topics(client, model_lane):
    model, _ = model_lane
    url = f"{BASE}/conversation/turn"
    headers = await login(client)
    await select(client, headers, "TEACHER")
    topic_query = {"text": "准备一份学习压力的班会活动", "synthetic_only": True}

    async def model_step(messages, definitions, _context):
        assert "read_education_articles" in {item["function"]["name"] for item in definitions}
        if messages[-1]["role"] == "tool":
            articles = json.loads(messages[-1]["content"])["articles"]
            assert [article["id"] for article in articles] == ["stress"]
            assert articles[0]["url"] == (
                "https://www.who.int/zh/news-room/questions-and-answers/item/stress"
            )
            assert articles[0]["paragraphs"]
            return assistant_step(text="可以从一个小步骤开始")
        assert "安排一点休息" not in json.dumps(messages, ensure_ascii=False)
        return assistant_step(
            tool="read_education_articles", arguments='{"topics":["stress","stress"]}'
        )

    model.side_effect = model_step
    response = await client.post(url, headers=headers, json=topic_query)
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    views = [event["view"] for event in events if event["type"] == "tool_result"]
    assert views == [{"kind": "education_articles", "topics": ["stress"]}]
    assert events[-1]["status"] == "completed"

    model.reset_mock()
    model.side_effect = [
        assistant_step(tool="read_education_articles", arguments='{"topics":["private_case"]}'),
        assistant_step(text="看不到那份材料"),
    ]
    rejected = await client.post(url, headers=headers, json=topic_query)
    events = [json.loads(line) for line in rejected.text.splitlines()]
    assert [event["code"] for event in events if event["type"] == "tool_failed"] == [
        "VALIDATION_FAILED"
    ]
    assert not any(event["type"] == "tool_result" for event in events)

    await select(client, headers, "ADMIN")
    model.side_effect = [
        assistant_step(tool="read_education_articles", arguments='{"topics":["stress"]}'),
        assistant_step(text="当前角色无法使用该工具"),
    ]
    forbidden = await client.post(url, headers=headers, json=topic_query)
    events = [json.loads(line) for line in forbidden.text.splitlines()]
    assert [event["code"] for event in events if event["type"] == "tool_failed"] == ["forbidden"]
    assert "read_education_articles" not in {
        item["function"]["name"] for item in model.call_args_list[-2].args[1]
    }


async def test_workspace_csv_summary_is_scoped_and_supplied_only_on_tool_call(client, model_lane):
    model, _ = model_lane
    summary = {
        "rows": 4,
        "columns": [{"column": 2, "count": 3, "min": 15, "max": 45, "mean": 30, "sum": 90}],
    }

    async def model_step(messages, definitions, _context):
        assert "inspect_attached_table" in {item["function"]["name"] for item in definitions}
        if messages[-1]["role"] == "tool":
            assert json.loads(messages[-1]["content"]) == summary
            return assistant_step(text="已准备列统计")
        assert '"sum": 90' not in json.dumps(messages, ensure_ascii=False)
        return assistant_step(tool="inspect_attached_table")

    model.side_effect = model_step
    headers = await login(client)
    await select(client, headers, "TEACHER")
    url = f"{BASE}/conversation/turn"
    turn = {"text": "读取这张表的统计", "synthetic_only": True, "table_summary": summary}
    response = await client.post(url, headers=headers, json=turn)
    views = [
        event["view"] for line in response.text.splitlines()
        if (event := json.loads(line))["type"] == "tool_result"
    ]
    assert views == [{"kind": "table_statistics", **summary}]
    invalid = await client.post(url, headers=headers, json={
        **turn, "table_summary": {**summary, "rows": 1},
    })
    assert invalid.status_code == 422
    await select(client, headers, "ADMIN")
    assert (await client.post(url, headers=headers, json=turn)).status_code == 403


async def test_teacher_referral_draft_is_private_and_does_not_submit(
    client, app, model_lane, monkeypatch
):
    model, safety = model_lane
    observation = "近两次小组活动时坐在一旁"
    now = datetime.now(UTC)
    service = SimpleNamespace(
        create_case=AsyncMock(),
        list_cases=AsyncMock(
            return_value={
                "total": 1,
                "items": [
                    {
                        "case_ref": "SSC_private_fixture",
                        "source": "TEACHER_REFERRAL",
                        "category_code": "PEER_RELATION",
                        "status": "SUBMITTED",
                        "state_version": 1,
                        "created_at": now,
                        "updated_at": now,
                    },
                ],
            }
        ),
    )
    monkeypatch.setattr(app.state.container, "school_support", service)
    model.side_effect = [
        assistant_step(
            tool="prepare_teacher_referral",
            arguments=json.dumps({"category_code": "PEER_RELATION", "observation": observation}),
        ),
        assistant_step(tool="teacher_support_status"),
        assistant_step(text="草案和记录状态已准备"),
    ]
    headers = await login(client)
    await select(client, headers, "TEACHER")
    response = await client.post(
        f"{BASE}/conversation/turn",
        headers=headers,
        json={"text": "准备合成支持草案并核对请求进度", "synthetic_only": True},
    )
    views = [
        event["view"] for line in response.text.splitlines()
        if (event := json.loads(line))["type"] == "tool_result"
    ]
    assert views == [
        {"kind": "teacher_referral", "category_code": "PEER_RELATION", "observation": observation},
        {"kind": "teacher_support_status", "total": 1, "shown": 1, "counts": {"SUBMITTED": 1}},
    ]
    assert any(call.args[1] == observation for call in safety.check_output.await_args_list)
    assert service.list_cases.await_args.args[0].school_ref == FIRST
    service.create_case.assert_not_awaited()
    tool_data = [row["content"] for row in model.await_args.args[0] if row["role"] == "tool"]
    assert all(
        "SSC_private_fixture" not in content and observation not in content for content in tool_data
    )


async def test_specialist_review_queue_only_exposes_workflow_counts_to_model(
    client, app, model_lane, monkeypatch
):
    model, _ = model_lane
    review = SimpleNamespace(pending_queue=AsyncMock(return_value=[{
        "task_ref": "TASK_private_review_fixture",
        "class_ref": "CLASS_private_fixture",
        "class_display_name": "PRIVATE_REVIEW_CLASS_LABEL",
        "published_at": datetime.now(UTC),
        "unfiled_count": 3,
        "open_count": 4,
        "in_review_count": 2,
    }]))
    monkeypatch.setattr(app.state.container, "professional_reviews", review)
    headers = await login(client)
    await select(client, headers, "PSYCHOLOGICAL_SPECIALIST")
    model.side_effect = [
        assistant_step(tool="professional_review_queue"),
        assistant_step(text="复核待办已整理"),
    ]
    response = await client.post(
        f"{BASE}/conversation/turn",
        headers=headers,
        json={"text": "看一下我分配到的复核待办", "synthetic_only": True},
    )
    views = [
        event["view"] for line in response.text.splitlines()
        if (event := json.loads(line))["type"] == "tool_result"
    ]
    assert views[0]["tasks"][0]["task_ref"] == "TASK_private_review_fixture"
    assert views[0]["tasks"][0]["unfiled_count"] == views[0]["unfiled_count"] == 3
    assert review.pending_queue.await_args.args[0].school_ref == FIRST
    messages = model.await_args.args[0]
    assert json.loads(messages[-1]["content"]) == {
        "task_count": 1, "unfiled_count": 3, "open_count": 4, "in_review_count": 2,
    }
    assert "PRIVATE_REVIEW_CLASS_LABEL" not in json.dumps(messages)


async def test_agent_prepares_publication_that_requires_school_admin_confirmation(
    client,
    tools,
    model_lane,
):
    model, _ = model_lane
    deadline = datetime.now(UTC) + timedelta(days=3)
    model.side_effect = [
        assistant_step(
            tool="preview_assessment_publication",
            arguments=json.dumps({"class_designation": "合成班", "due_at": deadline.isoformat()}),
        ),
        assistant_step(text="已准备发布预览"),
    ]
    headers = await login(client)
    await select(client, headers, "ADMIN")
    base = f"{BASE}/conversation"
    response = await client.post(
        f"{base}/turn",
        headers=headers,
        json={"text": "为合成班准备校内默认测评，三天后截止", "synthetic_only": True},
    )
    events = [json.loads(line) for line in response.text.splitlines()]
    preview = next(event["view"] for event in events if event["type"] == "tool_result")
    assert preview["kind"] == "preview_task"
    assert preview["class_ref"] == "QA-class"
    assert preview["enrolled"] == 5
    tools.publish_task.assert_not_awaited()
    path = f"{base}/confirm-publication"
    assert (await client.post(path, json={"token": preview["token"]})).status_code == 403
    await select(client, headers, "ADMIN", SECOND)
    assert (
        await client.post(path, headers=headers, json={"token": preview["token"]})
    ).status_code == 409
    await select(client, headers, "ADMIN")
    for _ in range(2):
        receipt = await client.post(path, headers=headers, json={"token": preview["token"]})
        assert receipt.status_code == 200
        assert receipt.json()["data"]["task_ref"] == "TASK_workspace_published"
    first, second = tools.publish_task.await_args_list
    assert first.kwargs["idempotency"] == second.kwargs["idempotency"]
    assert first.args[0].school_ref == FIRST
    assert first.kwargs["due_at"] == deadline


async def test_teacher_export_comes_from_scoped_database_counts(client, model_lane):
    model, _ = model_lane
    model.side_effect = [
        assistant_step(tool="make_class_progress_report"),
        assistant_step(text="班级简报已生成"),
    ]
    headers = await login(client)
    await select(client, headers, "TEACHER")
    response = await client.post(
        f"{BASE}/conversation/turn",
        headers=headers,
        json={"text": "把现有任务完成数量做成一份简报", "synthetic_only": True},
    )
    events = [json.loads(line) for line in response.text.splitlines()]
    view = next(event["view"] for event in events if event["type"] == "tool_result")
    assert view["artifact"]["filename"] == "class-assessment-progress.md"
    assert "任务完成率：40.0%" in view["artifact"]["markdown"]
    assert "must-not-leak" not in view["artifact"]["markdown"]


async def test_generated_document_revision_requires_a_fresh_scoped_read(client, model_lane):
    model, safety = model_lane
    headers = await login(client)
    await select(client, headers, "ADMIN")
    url = f"{BASE}/conversation"
    original = "# 班会活动\n\n- 保留活动目标\n- 同桌分享"
    revised = original.replace("同桌分享", "匿名纸卡")

    async def turn(prompt):
        response = await client.post(
            f"{url}/turn", headers=headers, json={"text": prompt, "synthetic_only": True}
        )
        assert response.status_code == 200
        return [json.loads(line) for line in response.text.splitlines()]

    model.side_effect = [
        assistant_step(
            tool="save_markdown",
            arguments=json.dumps({"filename": "activity-v1.md", "markdown": original}),
        ),
        assistant_step(text="已生成活动文档"),
    ]
    events = await turn("生成第一版活动文档")
    assert events[-1]["status"] == "completed"
    first = next(event["view"] for event in events if event["type"] == "tool_result")
    ref = first["document_ref"]
    revision = assistant_step(
        tool="save_markdown",
        arguments=json.dumps({
            "filename": "activity-v2.md", "markdown": revised, "revision_of": ref,
        }),
    )
    read = assistant_step(
        tool="read_workspace_document", arguments='{"selection": "activity-v1.md"}'
    )

    async def edit(messages, _definitions, _context):
        if messages[-1]["role"] != "tool":
            assert "保留活动目标" not in json.dumps(messages, ensure_ascii=False)
            return revision
        result = json.loads(messages[-1]["content"])
        if result.get("error") == "workflow_conflict":
            return read
        if "markdown" in result:
            assert result == {
                "document_ref": ref, "filename": "activity-v1.md", "markdown": original,
            }
            return revision
        assert result["filename"] == "activity-v2.md"
        return assistant_step(text="已生成第二版")

    safety.check_output.reset_mock()
    model.side_effect = edit
    events = await turn("请把刚才的活动改用匿名纸卡")
    assert events[-1]["status"] == "completed"
    assert [event["code"] for event in events if event["type"] == "tool_failed"] == [
        "workflow_conflict",
    ]
    viewed, second = [event["view"] for event in events if event["type"] == "tool_result"]
    assert viewed == {"kind": "workspace_document_read", "filename": "activity-v1.md"}
    assert second["revision_of"] == ref
    assert second["document_ref"] != ref
    assert second["previous_filename"] == first["filename"]
    assert second["markdown"] == revised
    assert safety.check_output.await_args_list[0].args[1] == f"activity-v1.md\n{original}"
    history = (await client.get(url)).json()["data"]["events"]
    assert [item["view"] for item in history if item.get("view", {}).get("kind") == "markdown"] == [
        first, second,
    ]

    async def list_docs(messages, _definitions, _context):
        assert "保留活动目标" not in json.dumps(messages, ensure_ascii=False)
        if messages[-1]["role"] != "tool":
            return assistant_step(tool="read_workspace_document", arguments='{"selection":"list"}')
        entries = json.loads(messages[-1]["content"])["documents"]
        assert [entry["filename"] for entry in entries] == ["activity-v2.md", "activity-v1.md"]
        assert all(set(entry) == {"document_ref", "filename"} for entry in entries)
        return assistant_step(text="已列出两份文档")

    model.side_effect = list_docs
    assert (await turn("列出刚才生成的文档"))[-1]["status"] == "completed"

    original_screen = safety.check_output.side_effect

    async def blocked_document(context, candidate, trace):
        if candidate == f"activity-v1.md\n{original}":
            return SimpleNamespace(decision=SimpleNamespace(action="BLOCK"))
        return await original_screen(context, candidate, trace)

    safety.check_output.side_effect = blocked_document
    model.side_effect = [read, assistant_step(text="当前无法读取这份文档")]
    blocked = await turn("读取第一版活动")
    assert any(event.get("code") == "forbidden" for event in blocked)
    assert "保留活动目标" not in json.dumps(model.await_args.args[0], ensure_ascii=False)
    safety.check_output.side_effect = original_screen

    for role, school in [("TEACHER", FIRST), ("ADMIN", SECOND)]:
        await select(client, headers, role, school)
        model.side_effect = [read, assistant_step(text="当前会话中没有这份文档")]
        events = await turn("继续编辑活动第一版")
        assert any(event.get("code") == "resource_not_found" for event in events)
        assert "保留活动目标" not in json.dumps(model.await_args.args[0], ensure_ascii=False)


def test_document_recall_accepts_legacy_results_and_skips_incomplete_runs():
    view = {"kind": "markdown", "filename": "activity.md", "markdown": "# 已完成的旧文档"}
    events = [
        {"run_id": "original", "call_id": "one", "type": "tool_result", "view": view},
        {
            "run_id": "original", "call_id": "two", "type": "tool_result",
            "view": {"kind": "class_progress", "artifact": view},
        },
        {"run_id": "original", "type": "end", "status": "completed"},
        {"run_id": "unfinished", "call_id": "three", "type": "tool_result", "view": view},
        {"run_id": "unfinished", "type": "end", "status": "blocked"},
    ]
    documents = completed_workspace_documents(events)
    assert len(documents) == 1
    document = select_workspace_document(documents, "latest")
    assert document is not None
    assert document.markdown == view["markdown"]
    assert select_workspace_document(documents, document.ref) == document
    assert select_workspace_document(documents, "activity.md") == document


def cat_csv(items: list[dict]) -> bytes:
    stream = StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["id", "stem", "model", "a", "thresholds", "options", "content"])
    for item in items:
        writer.writerow([
            item["item_id"], item["stem"], item["model"], item["parameters"]["a"],
            json.dumps(item["parameters"]["thresholds"]), json.dumps(item["response_options"]),
            "practice",
        ])
    return stream.getvalue().encode("utf-8-sig")


async def test_cat_csv_requires_confirmation_and_rejects_invalid_records_before_storing(
    client, app, model_lane
):
    model, _ = model_lane
    bank = json.loads((FIXTURES / "synthetic_item_bank.v1.json").read_text(encoding="utf-8"))
    private_marker = "private-synthetic-row-marker"
    item = {**bank["items"][0], "stem": private_marker}
    duplicate = {**item, "item_id": item["item_id"].removeprefix("ITEM_")}
    session_headers = await login(client)
    headers = {**session_headers, "Content-Type": "text/csv"}
    route = f"{BASE}/conversation/cat-attachment"
    confirmed = route + "?synthetic_only=true"
    await select(client, session_headers, "TEACHER")
    forbidden = await client.post(confirmed, headers=headers, content=cat_csv([item]))
    assert forbidden.status_code == 403
    await select(client, session_headers, "PSYCHOLOGICAL_SPECIALIST")
    unchecked = await client.post(route, headers=headers, content=cat_csv([item]))
    assert unchecked.json()["detail"] == "CAT CSV needs synthetic confirmation"
    for candidate, detail in [
        (b"id,id,stem,model,a,thresholds,options", "CAT CSV columns are invalid"),
        (cat_csv([item, duplicate]), "CAT CSV record 2 is invalid"),
        (cat_csv([{**item, "model": "2PL"}]), "CAT CSV record 1 is invalid"),
        (
            cat_csv([{**item, "parameters": {"a": 1, "thresholds": [0, 4, 2, 6]}}]),
            "CAT CSV record 1 is invalid",
        ),
    ]:
        invalid = await client.post(confirmed, headers=headers, content=candidate)
        assert invalid.json()["detail"] == detail
        assert private_marker not in invalid.text
    with app.state.workspace_history.cat.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM workspace_cat_attachment").fetchone()[0] == 0
    model.assert_not_awaited()


@pytest.mark.parametrize("file_format", ["json", "csv"])
async def test_cat_file_plan_approval_and_school_publication(
    client, app, tools, model_lane, monkeypatch, file_format
):
    model, _ = model_lane
    base = f"{BASE}/conversation"
    headers = await login(client)
    await select(client, headers, "PSYCHOLOGICAL_SPECIALIST")
    bank = json.loads((FIXTURES / "synthetic_item_bank.v1.json").read_text(encoding="utf-8"))
    config = json.loads((FIXTURES / "demo_cat_config.v1.json").read_text(encoding="utf-8"))
    if file_format == "csv":
        response = await client.post(
            f"{base}/cat-attachment?synthetic_only=true",
            headers={**headers, "Content-Type": "text/csv; charset=utf-8"},
            content=cat_csv(bank["items"]),
        )
    else:
        response = await client.post(
            f"{base}/cat-attachment",
            headers=headers,
            json={"bank_document": bank, "config_document": config},
        )
    assert response.status_code == 201
    upload_ref = response.json()["data"]["ref"]
    now = datetime.now(UTC)
    due = now + timedelta(days=3)
    stamp = now.isoformat()
    bid = "CBVER_10000000-0000-0000-0000-000000000000"
    pid = "CPVER_10000000-0000-0000-0000-000000000000"
    aid = "CACT_10000000-0000-0000-0000-000000000000"
    flags = {"engineering_only": True, "psychological_interpretation_allowed": False}
    bank_count = len(bank["items"])
    version = {"version_number": 1, "created_at": stamp}
    meta = {"created_at": stamp, "updated_at": stamp, "revision": 1, "status": "ACTIVE"}
    activation = {
        "activation_ref": aid,
        "plan_version_ref": pid,
        "bank_version_ref": bid,
        "plan_name": "合成验收方案",
        "bank_name": "合成验收题库",
        "plan_version_number": 1,
        "bank_version_number": 1,
        "status": "ACTIVE",
        "revision": 1,
        "created_at": stamp,
        "revoked_at": None,
    }
    assets = SimpleNamespace(
        template=AsyncMock(return_value={
            **flags, "bank_document": bank, "config_document": config,
            "item_count": bank_count, "dimension_count": 1,
        }),
        validate_documents=AsyncMock(
            return_value=SimpleNamespace(
                item_count=bank_count,
                dimension_count=1,
                config_document=config,
            )
        ),
        create_bank=AsyncMock(
            return_value={
                **flags,
                "version_ref": bid,
                "bank": {
                    **meta,
                    "bank_ref": "CBANK_10000000-0000-0000-0000-000000000000",
                    "display_name": "合成验收题库",
                    "versions": [
                        {
                            **version,
                            "version_ref": bid,
                            "item_count": bank_count,
                            "dimension_count": 1,
                        },
                    ],
                },
            }
        ),
        create_plan=AsyncMock(
            return_value={
                **flags,
                "version_ref": pid,
                "plan": {
                    **meta,
                    "plan_ref": "CPLAN_10000000-0000-0000-0000-000000000000",
                    "display_name": "合成验收方案",
                    "versions": [{**version, "version_ref": pid}],
                },
            }
        ),
        create_activation=AsyncMock(return_value={**flags, "activation": activation}),
        list_activations=AsyncMock(
            return_value={
                **flags,
                "items": [activation],
                "has_more": False,
            }
        ),
    )
    monkeypatch.setattr(app.state.container, "cat_assets", assets)
    model.side_effect = [
        assistant_step(tool="inspect_cat_attachment"),
        assistant_step(
            tool="prepare_cat_draft",
            arguments=json.dumps(
                {
                    "plan_name": "合成验收方案",
                    "class_designation": "合成班",
                    "due_at": due.isoformat(),
                    "configuration": "school_template" if file_format == "csv" else "attachment",
                }
            ),
        ),
        assistant_step(text="已准备方案草案"),
    ]
    response = await client.post(
        f"{base}/turn",
        headers=headers,
        json={
            "text": "请校验附件并给合成班准备测评方案",
            "synthetic_only": True,
            "attachment": "cat_bank",
            "cat_attachment_ref": upload_ref,
        },
    )
    events = [json.loads(line) for line in response.text.splitlines()]
    views = [event["view"] for event in events if event["type"] == "tool_result"]
    assert [view["kind"] for view in views] == ["cat_inspection", "cat_draft"]
    assert views[0]["item_count"] == bank_count
    assert views[0]["attachment_has_config"] == (file_format == "json")
    assert views[1]["state"] == "PREVIEW"
    if file_format == "csv":
        parsed = assets.validate_documents.await_args_list[0].args[1]
        assert parsed["metadata"] == {
            "synthetic": True, "intended_use": "engineering_test_only",
            "psychological_interpretation_allowed": False,
        }
        assert parsed["dimensions"] == ["demo_trait"]
        assert parsed["items"][0]["parameters"] == bank["items"][0]["parameters"]
        assert parsed["items"][0]["scoring"] == bank["items"][0]["scoring"]
        assert parsed["items"][0]["stem"] not in response.text
        assets.template.assert_awaited_once()
    for call in model.await_args_list:
        prompt = json.dumps(call.args[0], ensure_ascii=False)
        assert bank["items"][0]["stem"] not in prompt
        assert upload_ref not in prompt
    draft = {"draft_ref": views[1]["draft_ref"]}
    assets.create_bank.assert_not_awaited()
    assert (
        await client.post(f"{base}/approve-cat-draft", headers=headers, json=draft)
    ).status_code == 409
    saved = await client.post(f"{base}/save-cat-draft", headers=headers, json=draft)
    assert saved.json()["data"]["state"] == "SAVED"
    assets.create_activation.assert_not_awaited()
    approved = await client.post(f"{base}/approve-cat-draft", headers=headers, json=draft)
    assert approved.json()["data"]["state"] == "APPROVED"
    assets.create_activation.assert_awaited_once()
    assert tools.publish_task.await_count == 0
    assert (
        await client.post(
            f"{base}/preview-cat-handoff",
            headers=headers,
            json={"handoff_ref": draft["draft_ref"]},
        )
    ).status_code == 403
    await select(client, headers, "ADMIN", SECOND)
    assert (
        await client.post(
            f"{base}/preview-cat-handoff",
            headers=headers,
            json={"handoff_ref": draft["draft_ref"]},
        )
    ).status_code == 404
    await select(client, headers, "ADMIN")
    model.side_effect = [
        assistant_step(tool="list_cat_handoffs"),
        assistant_step(text="已找到交接"),
    ]
    admin_turn = await client.post(
        f"{base}/turn", headers=headers, json={"text": "查看待发布交接", "synthetic_only": True}
    )
    admin_views = [
        row["view"]
        for line in admin_turn.text.splitlines()
        if (row := json.loads(line))["type"] == "tool_result"
    ]
    assert admin_views[0]["drafts"][0]["state"] == "APPROVED"
    preview = await client.post(
        f"{base}/preview-cat-handoff",
        headers=headers,
        json={"handoff_ref": draft["draft_ref"]},
    )
    assert preview.status_code == 200
    assert preview.json()["data"]["class_ref"] == "QA-class"
    assert preview.json()["data"]["plan_label"] == "合成验收方案"
    tools.publish_task.return_value["activation_ref"] = aid
    tools.publish_task.return_value["due_at"] = due
    confirmed = await client.post(
        f"{base}/confirm-publication",
        headers=headers,
        json={"token": preview.json()["data"]["token"]},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["activation_ref"] == aid
    assert tools.publish_task.await_args.kwargs["due_at"] == due
    assert tools.publish_task.await_args.kwargs["activation_ref"] == aid
    admin_history = await client.get(base)
    admin_receipts = [
        event["view"] for event in admin_history.json()["data"]["events"]
        if event["type"] == "tool_result"
    ]
    assert admin_receipts[0]["drafts"][0]["state"] == "PUBLISHED"
    await select(client, headers, "PSYCHOLOGICAL_SPECIALIST")
    replay = await client.post(f"{base}/save-cat-draft", headers=headers, json=draft)
    assert replay.json()["data"]["state"] == "PUBLISHED"
    assets.create_bank.assert_awaited_once()
