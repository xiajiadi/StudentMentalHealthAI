"""HTTP integration checks for workspace role, CSRF and confirmation boundaries."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pwdlib import PasswordHash

from smhai_backend.domains.models import BackendRole, SchoolRoleContext, SyntheticUser
from smhai_backend.domains.workspace_agent_history import WorkspaceHistory

BASE = "/api/v1/workspace-agent"
FIRST = "PUBLICDEMO_" + "a" * 64
SECOND = "PUBLICDEMO_" + "b" * 64
ACCOUNT = "workspace-qa"
PASSWORD = "qa-only-synthetic-password"


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
