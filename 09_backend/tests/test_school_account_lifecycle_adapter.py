from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
for _database_path in (
    _REPOSITORY_ROOT / "11_database" / ".venv" / "Lib" / "site-packages",
    _REPOSITORY_ROOT / "11_database",
):
    if _database_path.is_dir() and str(_database_path) not in sys.path:
        sys.path.insert(0, str(_database_path))

from cryptography.fernet import Fernet  # noqa: E402
from database_layer import enums as db_enums  # noqa: E402
from database_layer import models as db_models  # noqa: E402
from database_layer.crypto import FernetDataProtectionProvider, MappingKeyProvider  # noqa: E402
from database_layer.repositories import _SAFE_AUDIT_KEYS  # noqa: E402

from smhai_backend.adapters.school_account_lifecycle import (  # noqa: E402
    SchoolAccountLifecyclePersistenceAdapter,
)
from smhai_backend.core.errors import BackendError, ErrorCode  # noqa: E402
from smhai_backend.domains.school_account_lifecycle.schemas import (  # noqa: E402
    StaffInvitationRequest,
)

pytest_plugins = ["tests.test_school_roster_import"]


class _AuditSink:
    def __init__(self):
        self.events = []

    async def append(self, **event):
        assert set(event.get("safe_metadata", {})) <= _SAFE_AUDIT_KEYS
        self.events.append(event)


class _ProtectedTransaction:
    def __init__(self, base, protection, audit):
        self.base = base
        self.protection = protection
        self.audit = audit

    async def __aenter__(self):
        await self.base.__aenter__()
        self.session = self.base.session
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return await self.base.__aexit__(exc_type, exc, traceback)


@pytest.fixture
def lifecycle_scope(roster_scope):
    from sqlalchemy import event

    required = (
        "school_staff_invitations",
        "school_staff_invitation_classes",
        "school_password_recovery_tickets",
    )
    db_models.Base.metadata.create_all(
        roster_scope.engine,
        tables=[db_models.Base.metadata.tables[name] for name in required],
    )
    event.listen(
        roster_scope.engine,
        "connect",
        lambda connection, _record: connection.create_collation(
            "ascii_bin", lambda left, right: (left > right) - (left < right)
        ),
    )
    owner = roster_scope.adapter._persistence
    base_uow = owner._uow
    key = Fernet.generate_key()
    protection = FernetDataProtectionProvider(MappingKeyProvider({"test": key}, "test"))
    audit = _AuditSink()
    owner._uow = lambda: _ProtectedTransaction(base_uow(), protection, audit)
    adapter = SchoolAccountLifecyclePersistenceAdapter(owner)
    return SimpleNamespace(
        adapter=adapter, session=roster_scope.session, actor=roster_scope.actor, audit=audit
    )


@pytest.mark.asyncio
async def test_staff_invitation_is_encrypted_one_time_and_activates_only_on_acceptance(
    lifecycle_scope,
):
    scope = lifecycle_scope
    payload = StaffInvitationRequest.model_validate(
        {
            "employee_ref": "TEACHER-001",
            "display_name": "合成教师",
            "role": "teacher",
            "work_contact": "teacher@example.invalid",
            "verified": True,
            "class_refs": ["CLASS_A"],
            "delivery_channel": "MANUAL",
        }
    )

    issued = await scope.adapter.create_staff_invitation(
        scope.actor,
        payload,
        ttl_seconds=86_400,
        trace_id="trace-invitation-test",
    )
    assert issued["delivery_channel"] == "MANUAL_HANDOFF_REQUIRED"
    assert issued["login_name"].startswith("STAFF_")
    assert issued["user_id"].startswith("USER_")
    credential = scope.session.query(db_models.SchoolAccountCredential).one()
    assert credential.token_hash == hashlib.sha256(issued["credential"].encode()).digest()
    assert issued["credential"].encode() not in credential.token_hash

    account = (
        scope.session.query(db_models.Account).filter_by(login_name=issued["login_name"]).one()
    )
    membership = (
        scope.session.query(db_models.AccountSchoolMembership)
        .filter_by(account_id=account.id, school_id=101)
        .one()
    )
    role = (
        scope.session.query(db_models.MembershipRole).filter_by(membership_id=membership.id).one()
    )
    invitation = scope.session.query(db_models.SchoolStaffInvitation).one()
    assert account.status == db_enums.AccountStatus.SUSPENDED.value
    assert membership.status == "INACTIVE"
    assert role.status == "INACTIVE"
    assert invitation.work_contact_ciphertext != b"teacher@example.invalid"
    assert b"teacher@example.invalid" not in invitation.work_contact_ciphertext
    assert invitation.work_contact_payload_schema_version == "school-staff-contact.v1"
    assert invitation.work_contact_key_version
    assert invitation.work_contact_cipher_format_version
    assert not any("teacher@example.invalid" in repr(event) for event in scope.audit.events)

    accepted = await scope.adapter.accept_staff_invitation(
        invitation_ref=issued["invitation_ref"],
        token_hash=hashlib.sha256(issued["credential"].encode()).digest(),
        new_password="SyntheticTeacherPassword123!",
        trace_id="trace-invitation-accept",
    )
    assert accepted == {"status": "ACCEPTED"}
    scope.session.refresh(account)
    scope.session.refresh(membership)
    scope.session.refresh(role)
    scope.session.refresh(invitation)
    scope.session.refresh(credential)
    assert account.status == db_enums.AccountStatus.ACTIVE.value
    assert account.must_change_password is False
    assert membership.status == "ACTIVE"
    assert role.status == "ACTIVE"
    assert invitation.status == "ACCEPTED"
    assert credential.status == "CONSUMED"
    assert (
        scope.session.query(db_models.SchoolClassTeacher)
        .filter_by(membership_role_id=role.id, class_id=401, school_id=101)
        .count()
        == 1
    )

    with pytest.raises(BackendError) as replay:
        await scope.adapter.accept_staff_invitation(
            invitation_ref=issued["invitation_ref"],
            token_hash=hashlib.sha256(issued["credential"].encode()).digest(),
            new_password="SyntheticTeacherPassword456!",
            trace_id="trace-invitation-replay",
        )
    assert replay.value.code is ErrorCode.AUTH_INVALID_CREDENTIALS


@pytest.mark.asyncio
async def test_summary_is_school_scoped_and_has_no_personal_or_secret_fields(lifecycle_scope):
    summary = await lifecycle_scope.adapter.account_summary(lifecycle_scope.actor)
    assert summary == {
        "total_accounts": 1,
        "active_accounts": 1,
        "pending_activation": 0,
        "suspended_accounts": 0,
        "classes": 2,
        "invitations_issued": 0,
        "invitations_accepted": 0,
        "invitations_expired": 0,
        "invitations_revoked": 0,
        "recovery_queue_count": 0,
    }


@pytest.mark.asyncio
async def test_status_flow_cannot_disable_the_only_active_school_admin(lifecycle_scope):
    with pytest.raises(BackendError) as denied:
        await lifecycle_scope.adapter.set_account_status(
            lifecycle_scope.actor,
            "USER_admin-public-a",
            status="DISABLED",
            reason_code="ROLE_CHANGE",
            trace_id="trace-admin-last-account",
        )
    assert denied.value.code is ErrorCode.WORKFLOW_CONFLICT
    admin = lifecycle_scope.session.query(db_models.Account).filter_by(id=201).one()
    assert admin.status == db_enums.AccountStatus.ACTIVE.value


@pytest.mark.asyncio
async def test_invitation_reissue_revokes_old_token_and_reuses_same_account(lifecycle_scope):
    scope = lifecycle_scope
    payload = StaffInvitationRequest.model_validate(
        {
            "employee_ref": "TEACHER-REISSUE",
            "display_name": "重签教师",
            "role": "teacher",
            "work_contact": "reissue@example.invalid",
            "verified": True,
            "class_refs": ["CLASS_A"],
            "delivery_channel": "MANUAL",
        }
    )
    first = await scope.adapter.create_staff_invitation(
        scope.actor, payload, ttl_seconds=86_400, trace_id="trace-invite-first"
    )
    listed = await scope.adapter.list_staff_invitations(scope.actor)
    assert len(listed) == 1
    assert listed[0]["status"] == "ISSUED"
    assert listed[0]["class_refs"] == ["CLASS_A"]
    summary = await scope.adapter.account_summary(scope.actor)
    assert summary["invitations_issued"] == 1
    assert summary["recovery_queue_count"] == 0
    reissued = await scope.adapter.reissue_staff_invitation(
        scope.actor,
        first["invitation_ref"],
        reason_code="CREDENTIAL_LOST",
        ttl_seconds=86_400,
        trace_id="trace-invite-reissue",
    )
    assert reissued["invitation_ref"] == first["invitation_ref"]
    assert reissued["user_id"] == first["user_id"]
    assert reissued["credential"] != first["credential"]
    assert (
        scope.session.query(db_models.Account).filter_by(login_name=first["login_name"]).count()
        == 1
    )
    credentials = (
        scope.session.query(db_models.SchoolAccountCredential)
        .filter_by(
            account_id=scope.session.query(db_models.Account)
            .filter_by(login_name=first["login_name"])
            .one()
            .id
        )
        .order_by(db_models.SchoolAccountCredential.id)
        .all()
    )
    assert [item.status for item in credentials] == ["REVOKED", "ISSUED"]

    with pytest.raises(BackendError) as stale_token:
        await scope.adapter.accept_staff_invitation(
            invitation_ref=first["invitation_ref"],
            token_hash=hashlib.sha256(first["credential"].encode()).digest(),
            new_password="SyntheticTeacherPassword123!",
            trace_id="trace-invite-old-token",
        )
    assert stale_token.value.code is ErrorCode.AUTH_INVALID_CREDENTIALS

    accepted = await scope.adapter.accept_staff_invitation(
        invitation_ref=reissued["invitation_ref"],
        token_hash=hashlib.sha256(reissued["credential"].encode()).digest(),
        new_password="SyntheticTeacherPassword456!",
        trace_id="trace-invite-new-token",
    )
    assert accepted == {"status": "ACCEPTED"}
    invitation = scope.session.query(db_models.SchoolStaffInvitation).one()
    assert invitation.status == "ACCEPTED"


@pytest.mark.asyncio
async def test_invitation_revoke_hides_other_school_objects_and_invalidates_token(lifecycle_scope):
    scope = lifecycle_scope
    now = datetime(2026, 10, 24, 9, 30)
    scope.session.add_all(
        [
            db_models.School(
                id=102,
                public_id="school-public-b",
                school_ref="SCHOOL_B",
                display_name="Synthetic School B",
                status="ACTIVE",
                data_origin="SYNTHETIC",
                provenance_ref="SYNTHETIC_REF_AUTH_TENANT_FIXTURE_V1",
            ),
            db_models.Account(
                id=220,
                public_id="admin-public-b",
                login_name="synthetic-admin-b",
                password_hash="test-admin-hash",
                status="ACTIVE",
            ),
            db_models.AccountSchoolMembership(
                id=320,
                public_id="membership-admin-b",
                account_id=220,
                school_id=102,
                status="ACTIVE",
                valid_from=now - timedelta(days=1),
            ),
            db_models.MembershipRole(
                id=321,
                public_id="role-admin-b",
                membership_id=320,
                school_id=102,
                role_code="admin",
                status="ACTIVE",
                valid_from=now - timedelta(days=1),
            ),
            db_models.SchoolClass(
                id=420,
                public_id="class-b-school-two-public",
                school_id=102,
                class_ref="CLASS_B",
                display_name="B班",
                created_by_membership_role_id=321,
                status="ACTIVE",
            ),
        ]
    )
    scope.session.commit()
    from smhai_backend.domains.models import Actor, BackendRole, SchoolRoleContext

    school_b_admin = Actor(
        user_id="USER_admin-public-b",
        username="synthetic-admin-b",
        role=BackendRole.ADMIN,
        subject_id=None,
        scope_profile="school_tenant",
        school_id=102,
        school_ref="SCHOOL_B",
        school_contexts=(
            SchoolRoleContext(
                context_id="321",
                role=BackendRole.ADMIN,
                school_id=102,
                school_ref="SCHOOL_B",
            ),
        ),
    )
    issued = await scope.adapter.create_staff_invitation(
        school_b_admin,
        StaffInvitationRequest.model_validate(
            {
                "employee_ref": "TEACHER-B-1",
                "display_name": "B校教师",
                "role": "teacher",
                "work_contact": "teacher-b@example.invalid",
                "verified": True,
                "class_refs": ["CLASS_B"],
                "delivery_channel": "MANUAL",
            }
        ),
        ttl_seconds=86_400,
        trace_id="trace-school-b-invite",
    )
    with pytest.raises(BackendError) as cross_school:
        await scope.adapter.revoke_staff_invitation(
            scope.actor,
            issued["invitation_ref"],
            reason_code="CANCELLED",
            trace_id="trace-school-a-cross-revoke",
        )
    assert cross_school.value.code is ErrorCode.RESOURCE_NOT_FOUND
    b_invitation = scope.session.query(db_models.SchoolStaffInvitation).one()
    assert await scope.adapter.list_staff_invitations(scope.actor) == []
    b_list = await scope.adapter.list_staff_invitations(school_b_admin)
    assert len(b_list) == 1 and b_list[0]["status"] == "ISSUED"

    revoked = await scope.adapter.revoke_staff_invitation(
        school_b_admin,
        issued["invitation_ref"],
        reason_code="CANCELLED",
        trace_id="trace-school-b-revoke",
    )
    assert revoked == {"status": "REVOKED"}
    scope.session.refresh(b_invitation)
    assert b_invitation.status == "REVOKED"
    b_list = await scope.adapter.list_staff_invitations(school_b_admin)
    assert b_list[0]["status"] == "REVOKED"
    credential = scope.session.query(db_models.SchoolAccountCredential).one()
    assert credential.status == "REVOKED"
    with pytest.raises(BackendError) as revoked_token:
        await scope.adapter.accept_staff_invitation(
            invitation_ref=issued["invitation_ref"],
            token_hash=hashlib.sha256(issued["credential"].encode()).digest(),
            new_password="SyntheticTeacherPassword123!",
            trace_id="trace-revoked-token",
        )
    assert revoked_token.value.code is ErrorCode.AUTH_INVALID_CREDENTIALS


@pytest.mark.asyncio
async def test_recovery_flow_requires_teacher_assignment_and_consumes_reset_token(
    lifecycle_scope,
):
    scope = lifecycle_scope
    now = datetime(2026, 10, 24, 9, 30)
    scope.session.add_all(
        [
            db_models.Account(
                id=204,
                public_id="student-public-b",
                login_name="synthetic-student-b",
                password_hash="old-test-hash",
                status="ACTIVE",
            ),
            db_models.AccountSchoolMembership(
                id=314,
                public_id="membership-student-b",
                account_id=204,
                school_id=101,
                display_name="合成学生乙",
                status="ACTIVE",
                valid_from=now - timedelta(days=1),
            ),
            db_models.MembershipRole(
                id=315,
                public_id="role-student-b",
                membership_id=314,
                school_id=101,
                role_code="student",
                status="ACTIVE",
                valid_from=now - timedelta(days=1),
            ),
            db_models.Subject(
                id=504,
                public_id="subject-student-b",
                subject_ref="SUBJ_student_b",
                school_id=101,
                status="ACTIVE",
                data_origin="SYNTHETIC",
            ),
            db_models.SubjectAccessGrant(
                id=514,
                public_id="grant-self-student-b",
                principal_account_id=204,
                subject_id=504,
                school_id=101,
                relationship_type="SELF",
                status="ACTIVE",
                valid_from=now - timedelta(days=1),
            ),
            db_models.SchoolClassStudent(
                id=524,
                public_id="class-student-b",
                school_id=101,
                class_id=401,
                subject_id=504,
                status="ACTIVE",
                valid_from=now - timedelta(days=1),
            ),
            db_models.Account(
                id=205,
                public_id="teacher-public-c",
                login_name="synthetic-teacher-c",
                password_hash="test-teacher-hash",
                status="ACTIVE",
            ),
            db_models.AccountSchoolMembership(
                id=325,
                public_id="membership-teacher-c",
                account_id=205,
                school_id=101,
                display_name="合成教师丙",
                status="ACTIVE",
                valid_from=now - timedelta(days=1),
            ),
            db_models.MembershipRole(
                id=326,
                public_id="role-teacher-c",
                membership_id=325,
                school_id=101,
                role_code="teacher",
                status="ACTIVE",
                valid_from=now - timedelta(days=1),
            ),
            db_models.SchoolClassTeacher(
                id=327,
                public_id="class-teacher-c",
                school_id=101,
                class_id=401,
                membership_role_id=326,
                status="ACTIVE",
                valid_from=now - timedelta(days=1),
            ),
            db_models.Account(
                id=206,
                public_id="teacher-public-d",
                login_name="synthetic-teacher-d",
                password_hash="test-teacher-hash",
                status="ACTIVE",
            ),
            db_models.AccountSchoolMembership(
                id=335,
                public_id="membership-teacher-d",
                account_id=206,
                school_id=101,
                display_name="合成教师丁",
                status="ACTIVE",
                valid_from=now - timedelta(days=1),
            ),
            db_models.MembershipRole(
                id=336,
                public_id="role-teacher-d",
                membership_id=335,
                school_id=101,
                role_code="teacher",
                status="ACTIVE",
                valid_from=now - timedelta(days=1),
            ),
            db_models.SchoolClassTeacher(
                id=337,
                public_id="class-teacher-d",
                school_id=101,
                class_id=402,
                membership_role_id=336,
                status="ACTIVE",
                valid_from=now - timedelta(days=1),
            ),
        ]
    )
    scope.session.commit()

    submitted = await scope.adapter.create_recovery_request(
        school_ref="SCHOOL_A",
        username="synthetic-student-b",
        class_ref="CLASS_A",
        reason_code="CREDENTIAL_LOST",
        trace_id="trace-recovery-request",
    )
    assert submitted == {"status": "REQUEST_RECEIVED"}
    queue = await scope.adapter.list_recovery_requests(scope.actor)
    assert len(queue) == 1
    ticket_ref = queue[0]["ticket_ref"]

    from smhai_backend.domains.models import Actor, BackendRole, SchoolRoleContext

    out_of_scope_teacher = Actor(
        user_id="USER_teacher-public-d",
        username="synthetic-teacher-d",
        role=BackendRole.TEACHER,
        subject_id=None,
        scope_profile="school_tenant",
        school_id=101,
        school_ref="SCHOOL_A",
        school_contexts=(
            SchoolRoleContext(
                context_id="336",
                role=BackendRole.TEACHER,
                school_id=101,
                school_ref="SCHOOL_A",
            ),
        ),
    )
    with pytest.raises(BackendError) as cross_class:
        await scope.adapter.verify_recovery_request(
            out_of_scope_teacher,
            ticket_ref,
            reason_code="SCHOOL_ID_CONFIRMED",
            trace_id="trace-recovery-cross-class",
        )
    assert cross_class.value.code is ErrorCode.FORBIDDEN

    teacher_actor = Actor(
        user_id="USER_teacher-public-c",
        username="synthetic-teacher-c",
        role=BackendRole.TEACHER,
        subject_id=None,
        scope_profile="school_tenant",
        school_id=101,
        school_ref="SCHOOL_A",
        school_contexts=(
            SchoolRoleContext(
                context_id="326",
                role=BackendRole.TEACHER,
                school_id=101,
                school_ref="SCHOOL_A",
            ),
        ),
    )
    verified = await scope.adapter.verify_recovery_request(
        teacher_actor,
        ticket_ref,
        reason_code="SCHOOL_ID_CONFIRMED",
        trace_id="trace-recovery-verify",
    )
    assert verified == {"status": "TEACHER_VERIFIED"}
    issued = await scope.adapter.approve_recovery_request(
        scope.actor,
        ticket_ref,
        reason_code="ADMIN_APPROVED",
        ttl_seconds=900,
        trace_id="trace-recovery-approve",
    )
    reset = await scope.adapter.complete_password_reset(
        school_ref="SCHOOL_A",
        username="synthetic-student-b",
        token_hash=hashlib.sha256(issued["credential"].encode()).digest(),
        new_password="NewStudentPassword123!",
        trace_id="trace-recovery-complete",
    )
    assert reset == {"status": "PASSWORD_RESET"}
    student = scope.session.query(db_models.Account).filter_by(id=204).one()
    ticket = scope.session.query(db_models.SchoolPasswordRecoveryTicket).one()
    assert student.must_change_password is False
    assert student.password_changed_at is not None
    assert ticket.status == "COMPLETED"
    with pytest.raises(BackendError) as replay:
        await scope.adapter.complete_password_reset(
            school_ref="SCHOOL_A",
            username="synthetic-student-b",
            token_hash=hashlib.sha256(issued["credential"].encode()).digest(),
            new_password="NewStudentPassword456!",
            trace_id="trace-recovery-replay",
        )
    assert replay.value.code is ErrorCode.AUTH_INVALID_CREDENTIALS


@pytest.mark.parametrize(
    ("role", "class_refs"),
    [("teacher", ["CLASS_A"]), ("psychological_specialist", [])],
)
@pytest.mark.asyncio
async def test_staff_recovery_credential_is_one_time_and_requires_an_accepted_verified_invitation(
    lifecycle_scope, role, class_refs
):
    scope = lifecycle_scope
    payload = StaffInvitationRequest.model_validate(
        {
            "employee_ref": f"STAFF-RESET-{role}",
            "display_name": "合成教职工",
            "role": role,
            "work_contact": "staff-reset@example.invalid",
            "verified": True,
            "class_refs": class_refs,
            "delivery_channel": "MANUAL",
        }
    )
    invitation = await scope.adapter.create_staff_invitation(
        scope.actor,
        payload,
        ttl_seconds=86_400,
        trace_id="trace-staff-reset-invite",
    )
    await scope.adapter.accept_staff_invitation(
        invitation_ref=invitation["invitation_ref"],
        token_hash=hashlib.sha256(invitation["credential"].encode()).digest(),
        new_password="SyntheticStaffPassword123!",
        trace_id="trace-staff-reset-accept",
    )
    account = (
        scope.session.query(db_models.Account).filter_by(login_name=invitation["login_name"]).one()
    )
    original_hash = account.password_hash

    if role == "psychological_specialist":
        with pytest.raises(BackendError) as insufficient_verification:
            await scope.adapter.issue_staff_recovery_credential(
                scope.actor,
                invitation["user_id"],
                reason_code="CREDENTIAL_LOST",
                verification_method="VERIFIED_WORK_CONTACT",
                ttl_seconds=900,
                trace_id="trace-staff-reset-insufficient-verification",
            )
        assert insufficient_verification.value.code is ErrorCode.VALIDATION_FAILED

    reset = await scope.adapter.issue_staff_recovery_credential(
        scope.actor,
        invitation["user_id"],
        reason_code="CREDENTIAL_LOST",
        verification_method="IN_PERSON",
        ttl_seconds=900,
        trace_id="trace-staff-reset-issue",
    )

    assert reset["status"] == "ISSUED"
    assert reset["delivery_channel"] == "MANUAL_HANDOFF_REQUIRED"
    assert reset["credential"] != invitation["credential"]
    scope.session.refresh(account)
    assert account.must_change_password is True
    assert account.password_hash == original_hash
    recovery_credential = (
        scope.session.query(db_models.SchoolAccountCredential)
        .filter_by(account_id=account.id, purpose="PASSWORD_RESET", status="ISSUED")
        .one()
    )
    assert recovery_credential.resource_ref == f"STAFF_RECOVERY_{account.public_id}"
    assert recovery_credential.token_hash == hashlib.sha256(reset["credential"].encode()).digest()
    assert reset["credential"].encode() not in recovery_credential.token_hash
    assert not any(reset["credential"] in repr(event) for event in scope.audit.events)

    completed = await scope.adapter.complete_password_reset(
        school_ref="SCHOOL_A",
        username=invitation["login_name"],
        token_hash=hashlib.sha256(reset["credential"].encode()).digest(),
        new_password="SyntheticStaffPassword456!",
        trace_id="trace-staff-reset-complete",
    )
    assert completed == {"status": "PASSWORD_RESET"}
    scope.session.refresh(account)
    scope.session.refresh(recovery_credential)
    assert account.must_change_password is False
    assert account.password_hash != original_hash
    assert recovery_credential.status == "CONSUMED"

    with pytest.raises(BackendError) as replay:
        await scope.adapter.complete_password_reset(
            school_ref="SCHOOL_A",
            username=invitation["login_name"],
            token_hash=hashlib.sha256(reset["credential"].encode()).digest(),
            new_password="SyntheticStaffPassword789!",
            trace_id="trace-staff-reset-replay",
        )
    assert replay.value.code is ErrorCode.AUTH_INVALID_CREDENTIALS
