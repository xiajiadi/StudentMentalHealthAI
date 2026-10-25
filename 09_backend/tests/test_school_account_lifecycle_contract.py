from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from smhai_backend.app_factory import create_app
from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.domains.school_account_lifecycle.router import router
from smhai_backend.domains.school_account_lifecycle.schemas import (
    AcceptInvitationRequest,
    RecoveryRequest,
    StaffInvitationRequest,
)


def test_all_lifecycle_paths_are_registered_without_expanding_openapi():
    app = create_app()
    paths = {getattr(route, "path", None) for route in router.routes}
    assert {
        "/school/admin/accounts/summary",
        "/school/admin/staff/invitations",
        "/school/admin/staff/invitations/{invitation_ref}/revoke",
        "/school/admin/staff/invitations/{invitation_ref}/reissue",
        "/auth/staff-invitations/accept",
        "/auth/recovery-requests",
        "/school/admin/recovery-requests",
        "/school/teacher/recovery-requests/{ticket_ref}/verify",
        "/school/admin/recovery-requests/{ticket_ref}/approve",
        "/auth/password/reset/complete",
        "/school/admin/accounts/{user_id}/status",
    } <= paths
    assert "/api/v1/school/admin/accounts/summary" not in app.openapi()["paths"]


def test_invitation_mutations_require_recent_reauthentication_and_csrf():
    sensitive_paths = {
        "/school/admin/staff/invitations",
        "/school/admin/staff/invitations/{invitation_ref}/revoke",
        "/school/admin/staff/invitations/{invitation_ref}/reissue",
    }
    for route in router.routes:
        route_methods = getattr(route, "methods", set())
        if getattr(route, "path", None) not in sensitive_paths or "POST" not in route_methods:
            continue
        dependant = getattr(route, "dependant", None)
        names = {
            dependency.call.__name__
            for dependency in getattr(dependant, "dependencies", [])
            if getattr(getattr(dependency, "call", None), "__name__", None) is not None
        }
        assert "recent_reauthenticated_csrf_protected" in names


def test_invitation_requires_manual_confirmation_and_secret_is_masked():
    invitation = StaffInvitationRequest.model_validate(
        {
            "employee_ref": " STAFF-1 ",
            "display_name": " 教师甲 ",
            "role": "teacher",
            "work_contact": " teacher@example.invalid ",
            "verified": True,
            "class_refs": ["CLASS_A"],
            "delivery_channel": "MANUAL",
        }
    )
    assert invitation.employee_ref == "STAFF-1"
    assert invitation.work_contact == "teacher@example.invalid"
    with pytest.raises(ValidationError):
        StaffInvitationRequest.model_validate(
            {
                "employee_ref": "STAFF-1",
                "display_name": "教师甲",
                "role": "teacher",
                "work_contact": "teacher@example.invalid",
                "verified": False,
                "class_refs": ["CLASS_A"],
                "delivery_channel": "MANUAL",
            }
        )

    request = AcceptInvitationRequest.model_validate(
        {
            "invitation_ref": "INV_SYNTHETIC",
            "credential": "synthetic-only-one-time-token-value",
            "new_password": "SyntheticPassword123!",
            "confirm_password": "SyntheticPassword123!",
        }
    )
    assert isinstance(request.credential, SecretStr)
    assert "synthetic-only-one-time-token-value" not in repr(request)


def test_psychologist_invitation_requires_ascii_employee_reference():
    invitation = StaffInvitationRequest.model_validate(
        {
            "employee_ref": "PSY-001",
            "display_name": "合成心理老师",
            "role": "psychological_specialist",
            "work_contact": "staff@example.invalid",
            "verified": True,
            "class_refs": [],
            "delivery_channel": "MANUAL",
        }
    )
    assert invitation.role == "psychological_specialist"

    with pytest.raises(ValidationError):
        StaffInvitationRequest.model_validate(
            {
                "employee_ref": "心理老师001",
                "display_name": "合成心理老师",
                "role": "psychological_specialist",
                "work_contact": "staff@example.invalid",
                "verified": True,
                "class_refs": [],
                "delivery_channel": "MANUAL",
            }
        )

def test_public_recovery_dto_accepts_only_fixed_reason_codes():
    request = RecoveryRequest(
        school_ref="SCHOOL_SYNTHETIC",
        username="STUDENT_SYNTHETIC",
        class_ref="CLASS_A",
        reason_code="CREDENTIAL_LOST",
    )
    assert request.reason_code == "CREDENTIAL_LOST"
    with pytest.raises(ValidationError):
        RecoveryRequest.model_validate(
            {
                "school_ref": "SCHOOL_SYNTHETIC",
                "username": "STUDENT_SYNTHETIC",
                "class_ref": "CLASS_A",
                "reason_code": "PRIVATE_NOTE_OR_PASSWORD",
            }
        )

    with pytest.raises(ValidationError):
        StaffInvitationRequest.model_validate(
            {
                "employee_ref": "STAFF-2",
                "display_name": "心理老师",
                "role": "psychological_specialist",
                "work_contact": "specialist@example.invalid",
                "verified": True,
                "class_refs": ["CLASS_A"],
                "delivery_channel": "MANUAL",
            }
        )


@pytest.mark.asyncio
async def test_lifecycle_service_rejects_wrong_tenant_or_role_before_persistence():
    app = create_app()
    service = app.state.container.school_account_lifecycle
    actor = Actor(
        user_id="USER_synthetic",
        username="synthetic",
        role=BackendRole.TEACHER,
        subject_id=None,
        scope_profile="legacy_demo",
    )
    with pytest.raises(BackendError) as denied:
        await service.account_summary(actor)
    assert denied.value.code is ErrorCode.FORBIDDEN
