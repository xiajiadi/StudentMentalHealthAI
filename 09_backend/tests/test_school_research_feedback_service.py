from __future__ import annotations

from datetime import UTC, datetime

import pytest

from smhai_backend.core.errors import BackendError
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.domains.school_research_feedback.service import (
    SchoolResearchFeedbackService,
)


def actor(role: BackendRole, *, subject_id: str | None = None) -> Actor:
    return Actor(
        user_id=f"USER_synthetic_{role.value.lower()}",
        username="synthetic-research-feedback",
        role=role,
        subject_id=subject_id,
        scope_profile="school_tenant",
        school_id=17,
        school_ref="SCHOOL_synthetic",
    )


def case_row(**overrides):
    now = datetime(2026, 10, 14, tzinfo=UTC)
    return {
        "case_ref": "SRV_synthetic_1",
        "task_ref": "TASK_synthetic_1",
        "session_ref": "RSESS_synthetic_1",
        "status": "OPEN",
        "version": 1,
        "created_at": now,
        "updated_at": now,
        "review_note": None,
        **overrides,
    }


def feedback_row(**overrides):
    now = datetime(2026, 10, 14, tzinfo=UTC)
    return {
        "feedback_ref": "RFEED_synthetic_1",
        "case_ref": "SRV_synthetic_1",
        "session_ref": "RSESS_synthetic_1",
        "feedback_kind": "GENERAL_EDUCATIONAL_SUPPORT",
        "purpose": "RESEARCH_SIMULATION",
        "research_only": True,
        "psychological_interpretation_allowed": False,
        "publication_status": "not_approved_for_publication_or_operational_use",
        "content_revision": 1,
        "case_version": 2,
        "state_version": 1,
        "status": "DRAFT",
        "title": "一般教育支持",
        "body": "这是一般学习支持内容，不包含测评分数或测评解释。",
        "created_at": now,
        "published_at": None,
        "revoked_at": None,
        **overrides,
    }


def student_feedback_row(**overrides):
    row = feedback_row(
        status="PUBLISHED",
        state_version=2,
        published_at=datetime(2026, 10, 14, 1, tzinfo=UTC),
    )
    row.pop("case_ref")
    row.pop("case_version")
    row.pop("revoked_at")
    row.update(overrides)
    return row


class FakePersistence:
    def __init__(self):
        self.calls = []
        self.case = case_row()
        self.feedback = feedback_row()
        self.student_feedback = student_feedback_row()

    async def school_research_feedback_list_tasks(self, actor_arg):
        self.calls.append(("list_tasks", actor_arg))
        return [
            {
                "task_ref": "TASK_synthetic_1",
                "class_ref": "CLASS_synthetic_1",
                "class_display_name": "合成班级",
                "published_at": datetime(2026, 10, 13, tzinfo=UTC),
            }
        ]

    async def school_research_feedback_list_eligible_sessions(
        self, actor_arg, task_ref, *, offset, limit
    ):
        self.calls.append(("eligible", actor_arg, task_ref, offset, limit))
        return {
            "items": [
                {
                    "session_ref": "RSESS_synthetic_1",
                    "task_ref": task_ref,
                    "status": "COMPLETED",
                    "items_answered": 8,
                    "completed_at": datetime(2026, 10, 14, tzinfo=UTC),
                    "case_ref": None,
                }
            ],
            "total": 1,
        }

    async def school_research_feedback_list_cases(
        self, actor_arg, task_ref, *, status, offset, limit
    ):
        self.calls.append(("list_cases", actor_arg, task_ref, status, offset, limit))
        return {"items": [self.case], "total": 1}

    async def school_research_feedback_get_case(self, actor_arg, task_ref, case_ref):
        self.calls.append(("get_case", actor_arg, task_ref, case_ref))
        return self.case

    async def school_research_feedback_create_case(
        self, actor_arg, task_ref, session_ref, *, idempotency, trace_id
    ):
        self.calls.append(("create_case", actor_arg, task_ref, session_ref, idempotency, trace_id))
        return self.case

    async def school_research_feedback_transition_case(
        self,
        actor_arg,
        task_ref,
        case_ref,
        *,
        expected_version,
        status,
        note,
        idempotency,
        trace_id,
    ):
        self.calls.append(
            (
                "transition_case",
                actor_arg,
                task_ref,
                case_ref,
                expected_version,
                status,
                note,
                idempotency,
                trace_id,
            )
        )
        return self.case

    async def school_research_feedback_create_draft(
        self,
        actor_arg,
        case_ref,
        *,
        expected_case_version,
        title,
        body,
        idempotency,
        trace_id,
        candidate_ref=None,
    ):
        self.calls.append(
            (
                "create_draft",
                actor_arg,
                case_ref,
                expected_case_version,
                title,
                body,
                candidate_ref,
                idempotency,
                trace_id,
            )
        )
        return self.feedback

    async def school_research_feedback_list_for_case(self, actor_arg, case_ref, *, offset, limit):
        self.calls.append(("list_feedback", actor_arg, case_ref, offset, limit))
        return {"items": [self.feedback], "total": 1}

    async def school_research_feedback_publish(
        self,
        actor_arg,
        feedback_ref,
        *,
        expected_state_version,
        expected_case_version,
        idempotency,
        trace_id,
    ):
        self.calls.append(
            (
                "publish",
                actor_arg,
                feedback_ref,
                expected_state_version,
                expected_case_version,
                idempotency,
                trace_id,
            )
        )
        return feedback_row(
            status="PUBLISHED",
            state_version=expected_state_version + 1,
            published_at=datetime(2026, 10, 14, 1, tzinfo=UTC),
        )

    async def school_research_feedback_revoke(
        self,
        actor_arg,
        feedback_ref,
        *,
        expected_state_version,
        idempotency,
        trace_id,
    ):
        self.calls.append(("revoke", actor_arg, feedback_ref, expected_state_version))
        return feedback_row(
            status="REVOKED",
            state_version=expected_state_version + 1,
            published_at=datetime(2026, 10, 14, 1, tzinfo=UTC),
            revoked_at=datetime(2026, 10, 14, 2, tzinfo=UTC),
        )

    async def school_research_feedback_list_student(self, actor_arg, *, offset, limit):
        self.calls.append(("student_list", actor_arg, offset, limit))
        return {"items": [self.student_feedback], "total": 1}

    async def school_research_feedback_read_student(self, actor_arg, feedback_ref):
        self.calls.append(("student_get", actor_arg, feedback_ref))
        return self.student_feedback


async def test_research_case_review_and_explicit_feedback_publication_flow():
    persistence = FakePersistence()
    service = SchoolResearchFeedbackService(persistence=persistence)
    specialist = actor(BackendRole.PSYCHOLOGICAL_SPECIALIST)
    student = actor(BackendRole.STUDENT, subject_id="SUBJ_synthetic_1")

    tasks = await service.list_tasks(specialist)
    assert tasks[0]["task_ref"] == "TASK_synthetic_1"
    eligible = await service.list_eligible_sessions(specialist, "TASK_synthetic_1")
    assert eligible["items"][0]["status"] == "COMPLETED"
    case = await service.create_case(
        specialist,
        "TASK_synthetic_1",
        session_ref="RSESS_synthetic_1",
        idempotency=("key", "fingerprint", "scope"),
        trace_id="TRACE_synthetic",
    )
    assert case["case_ref"] == "SRV_synthetic_1"
    await service.transition_case(
        specialist,
        "TASK_synthetic_1",
        case["case_ref"],
        expected_version=1,
        status="APPROVED",
        note="已完成合成工作流审查。",
        idempotency=("key2", "fingerprint2", "scope"),
        trace_id="TRACE_synthetic",
    )
    draft = await service.create_draft(
        specialist,
        case["case_ref"],
        expected_case_version=2,
        title="一般教育支持",
        body="这是一般学习支持内容，不包含测评分数或测评解释。",
        idempotency=("key3", "fingerprint3", "scope"),
        trace_id="TRACE_synthetic",
    )
    assert draft["status"] == "DRAFT"
    assert persistence.calls[-1][0] == "create_draft"
    assert persistence.calls[-1][6] is None
    published = await service.publish(
        specialist,
        draft["feedback_ref"],
        expected_state_version=1,
        expected_case_version=2,
        idempotency=("key4", "fingerprint4", "scope"),
        trace_id="TRACE_synthetic",
    )
    assert published["status"] == "PUBLISHED"
    assert published["publication_status"] == "not_approved_for_publication_or_operational_use"
    student_items = await service.list_student_feedback(student)
    assert student_items["items"][0]["status"] == "PUBLISHED"
    assert "case_ref" not in student_items["items"][0]
    assert "body" in student_items["items"][0]
    assert "title" in student_items["items"][0]
    assert "theta" not in student_items["items"][0]
    assert "assessment_ref" not in student_items["items"][0]
    assert all(call[0] != "student_list" or call[1] is student for call in persistence.calls)

    revoked = await service.revoke(
        specialist,
        draft["feedback_ref"],
        expected_state_version=2,
        idempotency=("key5", "fingerprint5", "scope"),
        trace_id="TRACE_synthetic",
    )
    assert revoked["status"] == "REVOKED"


async def test_roles_and_unsupported_content_fail_before_persistence():
    persistence = FakePersistence()
    service = SchoolResearchFeedbackService(persistence=persistence)
    teacher = actor(BackendRole.TEACHER)
    student = actor(BackendRole.STUDENT, subject_id="SUBJ_synthetic_1")

    with pytest.raises(BackendError):
        await service.list_tasks(teacher)
    with pytest.raises(BackendError):
        await service.create_draft(
            student,
            "SRV_synthetic_1",
            expected_case_version=2,
            title="一般教育支持",
            body="诊断内容",
            idempotency=("key", "fingerprint", "scope"),
            trace_id="TRACE_synthetic",
        )
    assert persistence.calls == []


async def test_candidate_reference_is_forwarded_only_as_optional_feedback_lineage():
    persistence = FakePersistence()
    service = SchoolResearchFeedbackService(persistence=persistence)
    specialist = actor(BackendRole.PSYCHOLOGICAL_SPECIALIST)

    await service.create_draft(
        specialist,
        "SRV_synthetic_1",
        expected_case_version=2,
        title="人工修订标题",
        body="人工修订后的教育支持正文。",
        candidate_ref="REEDUC_synthetic_candidate",
        idempotency=("key-candidate", "fingerprint-candidate", "scope"),
        trace_id="TRACE_synthetic",
    )

    assert persistence.calls[-1][0] == "create_draft"
    assert persistence.calls[-1][6] == "REEDUC_synthetic_candidate"
