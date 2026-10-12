from datetime import UTC, datetime

import pytest

from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.domains.professional_reviews.service import SchoolProfessionalReviewService


def actor(role):
    return Actor(
        user_id="USER_synthetic",
        username="synthetic",
        role=role,
        subject_id=None,
        scope_profile="school_tenant",
        school_id=17,
        school_ref="SCHOOL_synthetic",
    )


class MetadataPort:
    def __init__(self):
        self.calls = []
        self.tasks = [
            {
                "task_ref": "TASK_synthetic",
                "class_ref": "CLASS_synthetic",
                "class_display_name": None,
                "published_at": datetime(2026, 10, 12, tzinfo=UTC),
            }
        ]
        self.page = {
            "items": [
                {
                    "enrollment_ref": "ENROLL_synthetic",
                    "assessment_ref": "ASSESS_synthetic",
                    "completed_at": datetime(2026, 10, 12, tzinfo=UTC),
                    "case_ref": None,
                }
            ],
            "total": 1,
        }
        self.specialists = [{"user_id": "USER_synthetic", "display_name": None}]

    async def school_professional_review_list_tasks(self, value):
        self.calls.append(value)
        return self.tasks

    async def school_professional_review_list_eligible_enrollments(self, value, task_ref, **kwargs):
        self.calls.append((value, task_ref, kwargs))
        return self.page

    async def school_professional_review_list_specialists(self, value):
        self.calls.append(value)
        return self.specialists


@pytest.mark.asyncio
async def test_metadata_supports_nullable_names_and_native_dates():
    port = MetadataPort()
    service = SchoolProfessionalReviewService(persistence=port)
    specialist = actor(BackendRole.PSYCHOLOGICAL_SPECIALIST)
    rows = await service.list_tasks(specialist)
    assert rows[0]["class_display_name"] is None
    assert rows[0]["published_at"].tzinfo is UTC
    page = await service.list_eligible_enrollments(specialist, "TASK_synthetic", offset=0, limit=1)
    assert page["items"][0]["case_ref"] is None
    assert port.calls[-1][2] == {"offset": 0, "limit": 1}
    assert await service.list_specialists(actor(BackendRole.ADMIN)) == port.specialists


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [BackendRole.ADMIN, BackendRole.TEACHER, BackendRole.STUDENT])
async def test_specialist_metadata_denies_other_roles_before_port(role):
    port = MetadataPort()
    service = SchoolProfessionalReviewService(persistence=port)
    with pytest.raises(BackendError) as caught:
        await service.list_tasks(actor(role))
    assert caught.value.code is ErrorCode.FORBIDDEN
    assert port.calls == []


@pytest.mark.asyncio
async def test_admin_picker_denies_specialist_before_port():
    port = MetadataPort()
    service = SchoolProfessionalReviewService(persistence=port)
    with pytest.raises(BackendError) as caught:
        await service.list_specialists(actor(BackendRole.PSYCHOLOGICAL_SPECIALIST))
    assert caught.value.code is ErrorCode.FORBIDDEN
    assert port.calls == []


@pytest.mark.asyncio
async def test_metadata_rejects_private_payload_and_overlong_pages():
    port = MetadataPort()
    service = SchoolProfessionalReviewService(persistence=port)
    port.tasks[0]["review_note"] = "must not escape"
    with pytest.raises(BackendError) as caught:
        await service.list_tasks(actor(BackendRole.PSYCHOLOGICAL_SPECIALIST))
    assert caught.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE
    port.page["items"] *= 2
    port.page["total"] = 2
    with pytest.raises(BackendError) as caught:
        await service.list_eligible_enrollments(
            actor(BackendRole.PSYCHOLOGICAL_SPECIALIST), "TASK_synthetic", offset=0, limit=1
        )
    assert caught.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE


@pytest.mark.asyncio
@pytest.mark.parametrize("offset,limit", [(True, 20), (0, True), (-1, 20), (0, 51), (100001, 20)])
async def test_metadata_paging_rejects_invalid_values(offset, limit):
    port = MetadataPort()
    service = SchoolProfessionalReviewService(persistence=port)
    with pytest.raises(BackendError) as caught:
        await service.list_eligible_enrollments(
            actor(BackendRole.PSYCHOLOGICAL_SPECIALIST),
            "TASK_synthetic",
            offset=offset,
            limit=limit,
        )
    assert caught.value.code is ErrorCode.VALIDATION_FAILED
    assert port.calls == []
