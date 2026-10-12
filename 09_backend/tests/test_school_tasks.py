from __future__ import annotations

from dataclasses import replace

import pytest

from smhai_backend.adapters.database import MySqlBackendAdapter
from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.domains.assessment.service import AssessmentService
from smhai_backend.domains.models import Actor, BackendRole, SchoolRoleContext
from smhai_backend.domains.school_tasks.router import _idempotency_scope
from smhai_backend.domains.school_tasks.service import (
    SchoolTaskService,
    task_ref_for_idempotency,
    utc_now,
)


def school_actor(role: BackendRole) -> Actor:
    return Actor(
        user_id="USER_synthetic-test",
        username="synthetic-test",
        role=role,
        subject_id="SUBJ_synthetic-test" if role is BackendRole.STUDENT else None,
        scope_profile="school_tenant",
        school_id=17,
        school_ref="SCHOOL_synthetic-test",
    )


class FakePersistence:
    def __init__(self):
        self.calls = []

    async def school_list_classes(self, actor):
        self.calls.append(("list_classes", actor.role))
        return []

    async def school_prepare_task_session(self, actor, task_ref, assessment_ref, **kwargs):
        self.calls.append(("prepare", task_ref))
        return {"assessment_id": "ASSESS_bound", "subject_id": actor.subject_id}

    async def school_list_student_task_history(self, actor, *, at):
        self.calls.append(("history", actor.school_ref))
        return [
            {
                "task_ref": "TASK_synthetic",
                "class_ref": "CLASS_synthetic",
                "task_status": "CLOSED",
                "enrollment_status": "REVOKED",
                "assessment_status": "COMPLETED",
                "started_at": None,
                "completed_at": None,
            }
        ]


class FakeCat:
    label = "REAL_HTTP"


class FakeAssessments:
    async def state_for_actor(self, actor, assessment_id, **kwargs):
        return type(
            "Record",
            (),
            {
                "assessment_id": assessment_id,
                "subject_id": actor.subject_id,
                "assessment": {"status": "created"},
                "selected_item_id": "ITEM_synthetic_1",
                "current_item": {"item_id": "ITEM_synthetic_1"},
                "answered_count": 0,
                "administered_count": 1,
                "can_complete": False,
                "max_items": 8,
            },
        )()


@pytest.mark.asyncio
async def test_school_task_operations_require_server_school_role():
    persistence = FakePersistence()
    service = SchoolTaskService(
        persistence=persistence, assessments=FakeAssessments(), cat=FakeCat()
    )
    await service.list_classes(school_actor(BackendRole.ADMIN))
    with pytest.raises(BackendError) as caught:
        await service.list_classes(school_actor(BackendRole.PSYCHOLOGICAL_SPECIALIST))
    assert caught.value.code is ErrorCode.FORBIDDEN
    assert persistence.calls == [("list_classes", BackendRole.ADMIN)]


@pytest.mark.asyncio
async def test_student_task_start_uses_persisted_bound_session_and_cat_state():
    persistence = FakePersistence()
    service = SchoolTaskService(
        persistence=persistence, assessments=FakeAssessments(), cat=FakeCat()
    )
    result = await service.start_task(
        school_actor(BackendRole.STUDENT),
        "TASK_synthetic",
        request_id="REQ_synthetic",
        trace_id="TRACE_synthetic",
        idempotency=("key", "0" * 64, "1" * 64),
    )
    assert result["assessment_id"] == "ASSESS_bound"
    assert result["subject_id"] == "SUBJ_synthetic-test"
    assert persistence.calls == [("prepare", "TASK_synthetic")]


@pytest.mark.asyncio
async def test_school_task_start_never_uses_contract_fake_cat():
    persistence = FakePersistence()
    service = SchoolTaskService(
        persistence=persistence,
        assessments=FakeAssessments(),
        cat=type("FakeCat", (), {"label": "CONTRACT_FAKE"})(),
    )
    with pytest.raises(BackendError) as caught:
        await service.start_task(
            school_actor(BackendRole.STUDENT),
            "TASK_synthetic",
            request_id="REQ_synthetic",
            trace_id="TRACE_synthetic",
            idempotency=("key", "0" * 64, "1" * 64),
        )
    assert caught.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE
    assert persistence.calls == []


@pytest.mark.asyncio
async def test_task_link_guard_runs_before_assessment_repository_read():
    calls = []

    class Repository:
        async def school_get_assessment_for_actor(self, actor, assessment_id, *, at):
            calls.append("guard")
            return None

        async def get(self, assessment_id):
            calls.append("get")
            raise AssertionError("denied task sessions must not load or decrypt")

    class Cat:
        label = "REAL_HTTP"

    class Authorization:
        def require(self, *args, **kwargs):
            return None

    class Audit:
        async def record(self, **kwargs):
            return None

    service = AssessmentService(
        repository=Repository(), cat=Cat(), authorization=Authorization(), audit=Audit()
    )
    with pytest.raises(BackendError) as caught:
        await service.get_for_actor(
            school_actor(BackendRole.STUDENT),
            "ASSESS_revoked",
            action="assessment:read",
            request_id="REQ_synthetic",
            trace_id="TRACE_synthetic",
        )
    assert caught.value.code is ErrorCode.RESOURCE_NOT_FOUND
    assert calls == ["guard"]


@pytest.mark.asyncio
async def test_school_assessment_list_uses_tenant_repository_path():
    calls = []

    class Repository:
        async def school_list_assessments_for_actor(
            self, actor, subject_ids, *, limit=None, skip=0, status=None
        ):
            calls.append((actor.school_ref, set(subject_ids)))
            return []

        async def list_assessments_for_subjects(self, *args, **kwargs):
            raise AssertionError("school list must not use unguarded generic loader")

    class Authorization:
        def can(self, actor, action, *, resource=None):
            return resource.get("subject_id") == actor.subject_id

    service = AssessmentService(
        repository=Repository(), cat=FakeCat(), authorization=Authorization(), audit=None
    )
    result = await service.list_for_actor(school_actor(BackendRole.STUDENT))
    assert result == []
    assert calls == [("SCHOOL_synthetic-test", {"SUBJ_synthetic-test"})]


def test_idempotency_and_task_reference_are_bound_to_active_school_context():
    actor_a = school_actor(BackendRole.ADMIN)
    actor_b = replace(actor_a, school_id=18, school_ref="SCHOOL_synthetic-other")
    assert _idempotency_scope(actor_a, "class:create") != _idempotency_scope(
        actor_b, "class:create"
    )
    assert task_ref_for_idempotency(actor_a, "class-a", "same-key") != task_ref_for_idempotency(
        actor_b, "class-a", "same-key"
    )


@pytest.mark.asyncio
async def test_teacher_with_available_student_context_is_rejected_before_private_read():
    actor = replace(
        school_actor(BackendRole.TEACHER),
        school_contexts=(
            SchoolRoleContext(
                context_id="student-role-id",
                role=BackendRole.STUDENT,
                school_id=17,
                school_ref="SCHOOL_synthetic-test",
                accessible_subject_ids=frozenset({"SUBJ_synthetic-test"}),
            ),
        ),
    )
    adapter = MySqlBackendAdapter.__new__(MySqlBackendAdapter)
    adapter.identity_profile = "school_tenant"
    calls = []

    async def private_reader(*args, **kwargs):
        calls.append("read")
        raise AssertionError("teacher request must stop before private assessment access")

    adapter.get_assessment = private_reader
    result = await adapter.school_get_assessment_for_actor(actor, "ASSESS_synthetic", at=utc_now())
    assert result is None
    assert calls == []


@pytest.mark.asyncio
async def test_student_task_history_returns_only_lifecycle_metadata():
    persistence = FakePersistence()
    service = SchoolTaskService(
        persistence=persistence, assessments=FakeAssessments(), cat=FakeCat()
    )
    rows = await service.list_student_task_history(school_actor(BackendRole.STUDENT))
    assert rows[0]["task_status"] == "CLOSED"
    assert rows[0]["enrollment_status"] == "REVOKED"
    assert not ({"assessment_id", "score", "result", "response", "report_id"} & set(rows[0]))


@pytest.mark.asyncio
async def test_teacher_cannot_read_student_task_history():
    persistence = FakePersistence()
    service = SchoolTaskService(
        persistence=persistence, assessments=FakeAssessments(), cat=FakeCat()
    )
    with pytest.raises(BackendError) as caught:
        await service.list_student_task_history(school_actor(BackendRole.TEACHER))
    assert caught.value.code is ErrorCode.FORBIDDEN
    assert persistence.calls == []
