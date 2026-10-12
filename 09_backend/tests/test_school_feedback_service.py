from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.domains.school_feedback.schemas import (
    FeedbackDraftRequest,
    FeedbackDto,
    FeedbackTransitionRequest,
    StudentFeedbackDto,
)
from smhai_backend.domains.school_feedback.service import SchoolFeedbackService


def actor(role: BackendRole, *, scope="school_tenant", school_id=17, subject_id=None):
    return Actor(
        user_id=f"USER_synthetic_{role.value.lower()}",
        username="synthetic-feedback-actor",
        role=role,
        subject_id=subject_id,
        scope_profile=scope,
        school_id=school_id,
        school_ref="SCHOOL_synthetic" if school_id is not None else None,
    )


def feedback_row(**overrides):
    now = datetime(2026, 10, 13, 1, 2, tzinfo=UTC)
    return {
        "feedback_ref": "FEED_synthetic_1",
        "case_ref": "CASE_synthetic_1",
        "assessment_ref": "ASSESS_synthetic_1",
        "level": "L3",
        "synthetic_only": True,
        "content_revision": 1,
        "state_version": 1,
        "case_version": 3,
        "status": "DRAFT",
        "title": "合成学习支持标题",
        "body": "合成教育支持反馈内容。",
        "created_at": now,
        "published_at": None,
        "revoked_at": None,
        **overrides,
    }


def student_row(**overrides):
    row = feedback_row(
        status="PUBLISHED",
        state_version=2,
        published_at=datetime(2026, 10, 13, 2, 0, tzinfo=UTC),
    )
    row.pop("case_ref")
    row.pop("case_version")
    row.pop("revoked_at")
    row.update(overrides)
    return row


class FakePersistence:
    def __init__(self):
        self.calls = []
        self.case_rows = [feedback_row()]
        self.student_rows = [student_row()]
        self.create_row = feedback_row()
        self.publish_row = feedback_row(
            status="PUBLISHED", state_version=2, published_at=datetime.now(UTC)
        )
        self.revoke_row = feedback_row(
            status="REVOKED", state_version=3, revoked_at=datetime.now(UTC)
        )

    async def school_feedback_list_cases(self, actor_arg, case_ref, *, offset, limit):
        self.calls.append(("list_cases", actor_arg, case_ref, offset, limit))
        return {"items": self.case_rows, "total": len(self.case_rows)}

    async def school_feedback_create(
        self, actor_arg, case_ref, *, expected_case_version, title, body, idempotency, trace_id
    ):
        self.calls.append(
            (
                "create",
                actor_arg,
                case_ref,
                expected_case_version,
                title,
                body,
                idempotency,
                trace_id,
            )
        )
        return self.create_row

    async def school_feedback_publish(
        self,
        actor_arg,
        feedback_ref,
        *,
        expected_case_version,
        expected_state_version,
        idempotency,
        trace_id,
    ):
        self.calls.append(
            (
                "publish",
                actor_arg,
                feedback_ref,
                expected_case_version,
                expected_state_version,
                idempotency,
                trace_id,
            )
        )
        return self.publish_row

    async def school_feedback_revoke(
        self,
        actor_arg,
        feedback_ref,
        *,
        expected_case_version,
        expected_state_version,
        idempotency,
        trace_id,
    ):
        self.calls.append(
            (
                "revoke",
                actor_arg,
                feedback_ref,
                expected_case_version,
                expected_state_version,
                idempotency,
                trace_id,
            )
        )
        return self.revoke_row

    async def school_feedback_list_student(self, actor_arg, *, offset, limit):
        self.calls.append(("list_student", actor_arg, offset, limit))
        return {"items": self.student_rows, "total": len(self.student_rows)}

    async def school_feedback_read_student(self, actor_arg, feedback_ref):
        self.calls.append(("read_student", actor_arg, feedback_ref))
        return self.student_rows[0]


@pytest.mark.asyncio
async def test_specialist_case_history_draft_and_transitions_delegate_versions_and_idempotency():
    persistence = FakePersistence()
    service = SchoolFeedbackService(persistence=persistence)
    specialist = actor(BackendRole.PSYCHOLOGICAL_SPECIALIST)
    draft_key = ("draft-key", "a" * 64, "draft-scope")
    publish_key = ("publish-key", "b" * 64, "publish-scope")
    revoke_key = ("revoke-key", "c" * 64, "revoke-scope")

    history = await service.list_case_feedback(specialist, "CASE_synthetic_1")
    draft = await service.create_draft(
        specialist,
        "CASE_synthetic_1",
        expected_case_version=3,
        title="合成学习支持标题",
        body="合成教育支持反馈内容。",
        idempotency=draft_key,
        trace_id="TRACE_synthetic_feedback",
    )
    published = await service.publish(
        specialist,
        "FEED_synthetic_1",
        expected_case_version=3,
        expected_state_version=1,
        idempotency=publish_key,
        trace_id="TRACE_synthetic_feedback",
    )
    revoked = await service.revoke(
        specialist,
        "FEED_synthetic_1",
        expected_case_version=3,
        expected_state_version=2,
        idempotency=revoke_key,
        trace_id="TRACE_synthetic_feedback",
    )

    assert history["items"][0]["status"] == "DRAFT"
    assert draft["body"] == "合成教育支持反馈内容。"
    assert published["status"] == "PUBLISHED" and published["state_version"] == 2
    assert revoked["status"] == "REVOKED" and revoked["state_version"] == 3
    assert persistence.calls[1] == (
        "create",
        specialist,
        "CASE_synthetic_1",
        3,
        "合成学习支持标题",
        "合成教育支持反馈内容。",
        draft_key,
        "TRACE_synthetic_feedback",
    )
    assert persistence.calls[2][5] is publish_key
    assert persistence.calls[3][5] is revoke_key
    assert all(
        item["synthetic_only"] is True and item["level"] == "L3" for item in history["items"]
    )


@pytest.mark.asyncio
async def test_student_projection_contains_published_content_only_and_current_actor_is_forwarded():
    persistence = FakePersistence()
    service = SchoolFeedbackService(persistence=persistence)
    student = actor(BackendRole.STUDENT, subject_id="SUBJ_synthetic_student")

    listed = await service.list_student_feedback(student)
    detail = await service.get_student_feedback(student, "FEED_synthetic_1")

    assert listed["items"][0]["status"] == "PUBLISHED"
    assert detail["feedback_ref"] == "FEED_synthetic_1"
    assert not {"case_ref", "case_version", "review_note", "raw_answers"}.intersection(detail)
    assert persistence.calls[0][1] is student and persistence.calls[1][1] is student


@pytest.mark.asyncio
async def test_school_student_subject_resolution_is_delegated_to_fresh_persistence_scope():
    persistence = FakePersistence()
    service = SchoolFeedbackService(persistence=persistence)
    # School contexts may not expose a single subject_id on the Actor. The
    # adapter must resolve the current SELF grant within its transaction.
    student = actor(BackendRole.STUDENT, subject_id=None)

    result = await service.list_student_feedback(student)

    assert result["items"][0]["status"] == "PUBLISHED"
    assert persistence.calls == [("list_student", student, 0, 50)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role",
    [BackendRole.STUDENT, BackendRole.TEACHER, BackendRole.ADMIN, BackendRole.REVIEWER],
)
async def test_non_specialists_are_denied_case_feedback_before_persistence(role):
    persistence = FakePersistence()
    service = SchoolFeedbackService(persistence=persistence)

    with pytest.raises(BackendError) as caught:
        await service.list_case_feedback(
            actor(role, subject_id="SUBJ_synthetic"), "CASE_synthetic_1"
        )

    assert caught.value.code is ErrorCode.FORBIDDEN
    assert persistence.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role",
    [
        BackendRole.TEACHER,
        BackendRole.ADMIN,
        BackendRole.REVIEWER,
        BackendRole.PSYCHOLOGICAL_SPECIALIST,
    ],
)
async def test_non_students_are_denied_student_feedback_before_persistence(role):
    persistence = FakePersistence()
    service = SchoolFeedbackService(persistence=persistence)

    with pytest.raises(BackendError) as caught:
        await service.list_student_feedback(actor(role, subject_id="SUBJ_synthetic"))

    assert caught.value.code is ErrorCode.FORBIDDEN
    assert persistence.calls == []


@pytest.mark.asyncio
async def test_legacy_or_unbound_actors_are_denied_before_persistence():
    persistence = FakePersistence()
    service = SchoolFeedbackService(persistence=persistence)
    invalid_actors = [
        actor(BackendRole.PSYCHOLOGICAL_SPECIALIST, scope="legacy_demo"),
        actor(BackendRole.PSYCHOLOGICAL_SPECIALIST, school_id=None),
        actor(BackendRole.STUDENT, scope="legacy_demo", subject_id="SUBJ_synthetic"),
    ]

    for invalid_actor in invalid_actors:
        with pytest.raises(BackendError) as caught:
            if invalid_actor.role is BackendRole.STUDENT:
                await service.list_student_feedback(invalid_actor)
            else:
                await service.list_case_feedback(invalid_actor, "CASE_synthetic_1")
        assert caught.value.code is ErrorCode.FORBIDDEN
    assert persistence.calls == []


@pytest.mark.asyncio
async def test_private_or_malformed_persistence_projections_fail_closed():
    persistence = FakePersistence()
    service = SchoolFeedbackService(persistence=persistence)
    specialist = actor(BackendRole.PSYCHOLOGICAL_SPECIALIST)

    for malformed in (
        feedback_row(review_note="private note"),
        feedback_row(ciphertext="encrypted payload"),
        feedback_row(synthetic_only=1),
        feedback_row(level="L2"),
        feedback_row(case_ref="CASE_other_school"),
    ):
        persistence.case_rows = [malformed]
        with pytest.raises(BackendError) as caught:
            await service.list_case_feedback(specialist, "CASE_synthetic_1")
        assert caught.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE
    assert "private note" not in str(caught.value)

    persistence.student_rows = [student_row(case_ref="CASE_private")]
    with pytest.raises(BackendError) as caught:
        await service.list_student_feedback(actor(BackendRole.STUDENT, subject_id="SUBJ_synthetic"))
    assert caught.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE


@pytest.mark.asyncio
async def test_bad_operation_state_versions_and_pagination_fail_closed():
    persistence = FakePersistence()
    service = SchoolFeedbackService(persistence=persistence)
    specialist = actor(BackendRole.PSYCHOLOGICAL_SPECIALIST)
    persistence.publish_row = feedback_row(status="PUBLISHED", state_version=3)

    with pytest.raises(BackendError) as caught:
        await service.publish(
            specialist,
            "FEED_synthetic_1",
            expected_case_version=3,
            expected_state_version=1,
            idempotency=("k", "f" * 64, "s"),
            trace_id="TRACE_s",
        )
    assert caught.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE

    before = len(persistence.calls)
    with pytest.raises(BackendError) as caught:
        await service.list_case_feedback(specialist, "CASE_synthetic_1", offset=True)
    assert caught.value.code is ErrorCode.VALIDATION_FAILED
    assert len(persistence.calls) == before


def test_requests_reject_coercion_blank_text_l2_and_client_owned_scope_fields():
    for invalid in (
        {"expected_case_version": True, "title": "title", "body": "body"},
        {"expected_case_version": "3", "title": "title", "body": "body"},
        {"expected_case_version": 3, "title": " ", "body": "body"},
        {"expected_case_version": 3, "title": "title", "body": "\t"},
        {"expected_case_version": 3, "title": "title", "body": "body", "level": "L2"},
        {"expected_case_version": 3, "title": "title", "body": "body", "school_id": 17},
        {"expected_case_version": 3, "title": "title", "body": "body", "review_note": "private"},
    ):
        with pytest.raises(ValidationError):
            FeedbackDraftRequest.model_validate(invalid, strict=True)
    with pytest.raises(ValidationError):
        FeedbackTransitionRequest.model_validate(
            {"expected_case_version": 1, "expected_state_version": False}, strict=True
        )


def test_response_dtos_are_strict_allowlists_and_require_l3_synthetic_content():
    for invalid in (
        feedback_row(synthetic_only=1),
        feedback_row(synthetic_only=False),
        feedback_row(level="L2"),
        feedback_row(raw_answer="private"),
        feedback_row(created_at="2026-10-13T00:00:00Z"),
    ):
        with pytest.raises(ValidationError):
            FeedbackDto.model_validate(invalid, strict=True)
    with pytest.raises(ValidationError):
        StudentFeedbackDto.model_validate(student_row(case_ref="CASE_hidden"), strict=True)
