"""HTTP integration checks for workspace role, CSRF and confirmation boundaries."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pwdlib import PasswordHash

from smhai_backend.domains.models import BackendRole, SchoolRoleContext, SyntheticUser

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
