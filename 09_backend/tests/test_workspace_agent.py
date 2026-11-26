"""HTTP integration checks for workspace role, CSRF and confirmation boundaries."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
    assert review.pending_queue.await_args.args[0].school_ref == FIRST
    messages = model.await_args.args[0]
    assert json.loads(messages[-1]["content"]) == {
        "task_count": 1, "open_count": 4, "in_review_count": 2,
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


async def test_cat_file_plan_approval_and_school_publication(
    client, app, tools, model_lane, monkeypatch
):
    model, _ = model_lane
    base = f"{BASE}/conversation"
    headers = await login(client)
    await select(client, headers, "PSYCHOLOGICAL_SPECIALIST")
    bank = json.loads((FIXTURES / "synthetic_item_bank.v1.json").read_text(encoding="utf-8"))
    config = json.loads((FIXTURES / "demo_cat_config.v1.json").read_text(encoding="utf-8"))
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
                    "configuration": "attachment",
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
    assert views[1]["state"] == "PREVIEW"
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
