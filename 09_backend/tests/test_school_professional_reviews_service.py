from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.domains.professional_reviews.schemas import (
    ProfessionalReviewCaseDto,
    ReviewCaseCreateRequest,
    ReviewCaseDecisionRequest,
    ReviewCaseOpenRequest,
    SpecialistAssignmentDto,
    SpecialistAssignmentRequest,
)
from smhai_backend.domains.professional_reviews.service import SchoolProfessionalReviewService


def actor(role: BackendRole, *, scope: str = "school_tenant", school_id: int | None = 17):
    return Actor(
        user_id="USER_synthetic-reviewer",
        username="synthetic-reviewer",
        role=role,
        subject_id=None,
        scope_profile=scope,
        school_id=school_id,
        school_ref="SCHOOL_synthetic" if school_id is not None else None,
    )


def assignment_row(**overrides):
    return {
        "assignment_ref": "ASSIGN_synthetic_1",
        "task_ref": "TASK_synthetic_1",
        "specialist_user_id": "USER_synthetic_specialist",
        "status": "ACTIVE",
        "assigned_at": datetime(2026, 10, 12, tzinfo=UTC),
        "revoked_at": None,
        **overrides,
    }


def case_row(**overrides):
    return {
        "case_ref": "CASE_synthetic_1",
        "task_ref": "TASK_synthetic_1",
        "enrollment_ref": "ENROLL_synthetic_1",
        "assessment_ref": "ASSESS_synthetic_1",
        "status": "OPEN",
        "publication_status": "NOT_PUBLISHED",
        "version": 1,
        "created_at": datetime(2026, 10, 12, tzinfo=UTC),
        "updated_at": datetime(2026, 10, 12, tzinfo=UTC),
        "decision": None,
        "review_note": None,
        **overrides,
    }


class FakePersistence:
    def __init__(self):
        self.calls = []
        self.next_assignment = assignment_row()
        self.next_case = case_row()

    async def school_professional_review_list_assignments(self, actor_arg, *, task_ref=None):
        self.calls.append(("list_assignments", actor_arg, task_ref))
        return [self.next_assignment]

    async def school_professional_review_assign(
        self, actor_arg, task_ref, specialist_user_id, *, idempotency, trace_id
    ):
        self.calls.append(
            ("assign", actor_arg, task_ref, specialist_user_id, idempotency, trace_id)
        )
        return self.next_assignment

    async def school_professional_review_revoke(
        self, actor_arg, task_ref, assignment_ref, *, idempotency, trace_id
    ):
        self.calls.append(
            ("revoke", actor_arg, task_ref, assignment_ref, idempotency, trace_id)
        )
        return self.next_assignment

    async def school_professional_review_list_cases(
        self, actor_arg, task_ref, *, offset, limit
    ):
        self.calls.append(("list_cases", actor_arg, task_ref, offset, limit))
        return {"items": [self.next_case], "total": 1}

    async def school_professional_review_get_case(self, actor_arg, task_ref, case_ref):
        self.calls.append(("get_case", actor_arg, task_ref, case_ref))
        return self.next_case

    async def school_professional_review_ensure_case(
        self, actor_arg, task_ref, enrollment_ref, *, idempotency, trace_id
    ):
        self.calls.append(
            ("ensure_case", actor_arg, task_ref, enrollment_ref, idempotency, trace_id)
        )
        return self.next_case

    async def school_professional_review_open_case(
        self,
        actor_arg,
        task_ref,
        case_ref,
        *,
        expected_version,
        idempotency,
        trace_id,
    ):
        self.calls.append(
            (
                "open_case",
                actor_arg,
                task_ref,
                case_ref,
                expected_version,
                idempotency,
                trace_id,
            )
        )
        return self.next_case

    async def school_professional_review_process_case(
        self,
        actor_arg,
        task_ref,
        case_ref,
        *,
        expected_version,
        decision,
        note,
        idempotency,
        trace_id,
    ):
        self.calls.append(
            (
                "process_case",
                actor_arg,
                task_ref,
                case_ref,
                expected_version,
                decision,
                note,
                idempotency,
                trace_id,
            )
        )
        return self.next_case


@pytest.mark.asyncio
async def test_admin_can_manage_assignments_and_actor_is_passed_to_persistence():
    persistence = FakePersistence()
    service = SchoolProfessionalReviewService(persistence=persistence)
    admin = actor(BackendRole.ADMIN)

    listed = await service.list_assignments(admin, task_ref="TASK_synthetic_1")
    assigned = await service.assign(
        admin,
        "TASK_synthetic_1",
        "USER_synthetic_specialist",
        idempotency=("key", "f" * 64, "scope"),
        trace_id="TRACE_synthetic",
    )
    revoked = await service.revoke(
        admin,
        "TASK_synthetic_1",
        "ASSIGN_synthetic_1",
        idempotency=("revoke", "e" * 64, "scope"),
        trace_id="TRACE_synthetic",
    )

    assert listed[0]["assignment_ref"] == "ASSIGN_synthetic_1"
    # HTTP routers validate the DTO once more before final JSON serialization.
    # Keep dates as datetime values so strict output validation remains valid.
    assert SpecialistAssignmentDto.model_validate(assigned).assigned_at.tzinfo is UTC
    assert assigned["status"] == revoked["status"] == "ACTIVE"
    assert [call[1] for call in persistence.calls] == [admin, admin, admin]


@pytest.mark.asyncio
async def test_only_school_specialist_can_list_read_open_or_decide_cases():
    persistence = FakePersistence()
    service = SchoolProfessionalReviewService(persistence=persistence)
    specialist = actor(BackendRole.PSYCHOLOGICAL_SPECIALIST)

    listed = await service.list_cases(specialist, "TASK_synthetic_1", offset=0, limit=20)
    fetched = await service.get_case(specialist, "TASK_synthetic_1", "CASE_synthetic_1")
    opened = await service.open_case(
        specialist,
        "TASK_synthetic_1",
        "CASE_synthetic_1",
        expected_version=1,
        idempotency=("open", "d" * 64, "scope"),
        trace_id="TRACE_synthetic",
    )
    ensured = await service.ensure_case(
        specialist,
        "TASK_synthetic_1",
        "ENROLL_synthetic_1",
        idempotency=("ensure", "c" * 64, "scope"),
        trace_id="TRACE_synthetic",
    )
    decided = await service.process_case(
        specialist,
        "TASK_synthetic_1",
        "CASE_synthetic_1",
        expected_version=2,
        decision="APPROVED",
        note="Synthetic workflow review note.",
        idempotency=("decision", "b" * 64, "scope"),
        trace_id="TRACE_synthetic",
    )

    assert listed == {"items": [fetched], "total": 1}
    assert opened["status"] == ensured["status"] == decided["status"] == "OPEN"
    assert decided["publication_status"] == "NOT_PUBLISHED"
    assert all(call[1] is specialist for call in persistence.calls)
    assert persistence.calls[-1][6] == "Synthetic workflow review note."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "denied_actor",
    [
        actor(BackendRole.STUDENT),
        actor(BackendRole.TEACHER),
        actor(BackendRole.ADMIN),
        actor(BackendRole.PSYCHOLOGICAL_SPECIALIST, scope="legacy_demo"),
        actor(BackendRole.PSYCHOLOGICAL_SPECIALIST, school_id=None),
    ],
)
async def test_nonassigned_role_or_invalid_school_context_is_denied_before_persistence(
    denied_actor,
):
    persistence = FakePersistence()
    service = SchoolProfessionalReviewService(persistence=persistence)

    with pytest.raises(BackendError) as caught:
        await service.list_cases(denied_actor, "TASK_synthetic_1")

    assert caught.value.code is ErrorCode.FORBIDDEN
    assert persistence.calls == []


@pytest.mark.asyncio
async def test_specialist_cannot_manage_assignments_and_admin_cannot_read_cases():
    persistence = FakePersistence()
    service = SchoolProfessionalReviewService(persistence=persistence)

    with pytest.raises(BackendError) as caught:
        await service.list_assignments(actor(BackendRole.PSYCHOLOGICAL_SPECIALIST))
    assert caught.value.code is ErrorCode.FORBIDDEN
    assert persistence.calls == []


@pytest.mark.asyncio
async def test_rejects_extra_private_case_data_in_persistence_projection():
    persistence = FakePersistence()
    persistence.next_case = case_row(raw_answers={"synthetic": True})
    service = SchoolProfessionalReviewService(persistence=persistence)

    with pytest.raises(BackendError) as caught:
        await service.get_case(
            actor(BackendRole.PSYCHOLOGICAL_SPECIALIST),
            "TASK_synthetic_1",
            "CASE_synthetic_1",
        )

    assert caught.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE
    assert "synthetic" not in str(caught.value)


@pytest.mark.asyncio
async def test_pagination_rejects_bool_and_bad_adapter_total():
    persistence = FakePersistence()
    service = SchoolProfessionalReviewService(persistence=persistence)
    specialist = actor(BackendRole.PSYCHOLOGICAL_SPECIALIST)

    with pytest.raises(BackendError) as caught:
        await service.list_cases(specialist, "TASK_synthetic_1", offset=True)
    assert caught.value.code is ErrorCode.VALIDATION_FAILED
    assert persistence.calls == []

    async def malformed_total(*_args, **_kwargs):
        return {"items": [], "total": True}

    persistence.school_professional_review_list_cases = malformed_total
    with pytest.raises(BackendError) as caught:
        await service.list_cases(specialist, "TASK_synthetic_1")
    assert caught.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE


def test_request_dtos_forbid_extra_fields_and_coercive_versions_or_dates():
    with pytest.raises(ValidationError):
        SpecialistAssignmentRequest(
            specialist_user_id="USER_synthetic_specialist", school_id=17
        )
    with pytest.raises(ValidationError):
        ReviewCaseOpenRequest(expected_version=True)
    with pytest.raises(ValidationError):
        ReviewCaseOpenRequest(expected_version="1")
    with pytest.raises(ValidationError):
        ReviewCaseDecisionRequest(
            expected_version=1,
            decision="APPROVED",
            note="ok",
            generated_report="private",
        )
    with pytest.raises(ValidationError):
        ReviewCaseDecisionRequest(expected_version=1, decision="APPROVED", note="   ")
    with pytest.raises(ValidationError):
        ReviewCaseCreateRequest(
            enrollment_ref="ENROLL_synthetic_1", student_user_id="forbidden"
        )


def test_response_dto_rejects_datetime_string_coercion_and_unknown_fields():
    values = case_row()
    values["created_at"] = "2026-10-12T00:00:00Z"
    with pytest.raises(ValidationError):
        ProfessionalReviewCaseDto.model_validate(values, strict=True)

    values = case_row(report_text="must never be projected")
    with pytest.raises(ValidationError):
        ProfessionalReviewCaseDto.model_validate(values, strict=True)


@pytest.mark.asyncio
async def test_idempotency_and_expected_version_are_transparent_to_persistence():
    persistence = FakePersistence()
    service = SchoolProfessionalReviewService(persistence=persistence)
    specialist = actor(BackendRole.PSYCHOLOGICAL_SPECIALIST)
    token = ("same-key", "a" * 64, "same-scope")

    await service.open_case(
        specialist,
        "TASK_synthetic_1",
        "CASE_synthetic_1",
        expected_version=7,
        idempotency=token,
        trace_id="TRACE_synthetic",
    )
    call = persistence.calls[0]
    assert call[4] == 7
    assert call[5] is token
