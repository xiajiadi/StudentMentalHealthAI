"""Domain-specific persistence adapters.

Repositories add, flush and query only.  Commit/rollback is owned by
``SqlAlchemyUnitOfWork``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, case, distinct, func, select, update
from sqlalchemy.engine import Row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .crypto import EncryptedPayload, FernetDataProtectionProvider
from .enums import (
    AccountStatus,
    AssessmentStatus,
    AuditResult,
    ConsentStatus,
    DataOrigin,
    IdempotencyState,
    MessageKind,
    ReviewEventType,
    ReviewPriority,
    ReviewStatus,
    SafetyAction,
    SupportRunStatus,
    SupportStatus,
)
from .errors import NotFound, OptimisticConcurrencyConflict, UniqueConflict
from .models import (
    Account,
    AccountRole,
    AccountSchoolMembership,
    AssessmentResponse,
    AssessmentResult,
    AssessmentSession,
    AuditEvent,
    AuthSession,
    ConsentRecord,
    IdempotencyRecord,
    MeasurementTask,
    MembershipRole,
    ReviewCase,
    ReviewEvent,
    SafetyDecision,
    School,
    SchoolClass,
    SchoolClassStudent,
    SchoolClassTeacher,
    SchoolResearchSession,
    Subject,
    SubjectAccessGrant,
    SupportEvidence,
    SupportMessage,
    SupportRun,
    SupportSession,
    TaskEnrollment,
)
from .provenance import (
    SYNTHETIC_SCHOOL_TEST_PROVENANCE_REF,
    is_registered_school_provenance_ref,
)

SYNTHETIC_SCHOOL_PROVENANCE_REF = SYNTHETIC_SCHOOL_TEST_PROVENANCE_REF


def _hash_opaque_token(token: str) -> bytes:
    if not token:
        raise ValueError("opaque token must not be empty")
    return hashlib.sha256(token.encode("utf-8")).digest()


def _hash_request(request_bytes: bytes) -> bytes:
    return hashlib.sha256(request_bytes).digest()


def _map_integrity_error(exc: IntegrityError) -> UniqueConflict:
    del exc
    return UniqueConflict("persistence uniqueness constraint was violated")


class AccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        login_name: str,
        password_hash: str,
        status: AccountStatus = AccountStatus.ACTIVE,
    ) -> Account:
        account = Account(login_name=login_name, password_hash=password_hash, status=status.value)
        self.session.add(account)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise _map_integrity_error(exc) from exc
        return account

    async def get_by_login_name(self, login_name: str) -> Account | None:
        result = await self.session.execute(select(Account).where(Account.login_name == login_name))
        return result.scalar_one_or_none()


class SubjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        subject_ref: str,
        school_id: int | None,
        data_origin: DataOrigin = DataOrigin.SYNTHETIC,
        retention_due_at: datetime | None = None,
    ) -> Subject:
        subject = Subject(
            subject_ref=subject_ref,
            school_id=school_id,
            data_origin=data_origin.value,
            retention_due_at=retention_due_at,
        )
        self.session.add(subject)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise _map_integrity_error(exc) from exc
        return subject

    async def get_by_ref(self, subject_ref: str) -> Subject | None:
        result = await self.session.execute(
            select(Subject).where(Subject.subject_ref == subject_ref)
        )
        return result.scalar_one_or_none()

    async def for_school(self, *, school_id: int) -> list[Subject]:
        result = await self.session.scalars(
            select(Subject).where(Subject.school_id == school_id)
        )
        return list(result.all())


class SchoolMembershipRepository:
    """Persistence helpers for explicitly provisioned school contexts."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_school(
        self,
        *,
        school_ref: str,
        data_origin: DataOrigin,
        provenance_ref: str,
    ) -> School:
        if data_origin != DataOrigin.SYNTHETIC:
            raise ValueError("school creation requires SYNTHETIC data origin")
        if not is_registered_school_provenance_ref(provenance_ref):
            raise ValueError("school provenance_ref must be an opaque synthetic reference token")
        school = School(
            school_ref=school_ref,
            status="ACTIVE",
            data_origin=DataOrigin.SYNTHETIC.value,
            provenance_ref=provenance_ref,
        )
        self.session.add(school)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise _map_integrity_error(exc) from exc
        return school

    async def get_school_by_ref(self, school_ref: str) -> School | None:
        result = await self.session.execute(select(School).where(School.school_ref == school_ref))
        return result.scalar_one_or_none()

    async def schools_with_provenance(self, *, provenance_ref: str) -> list[School]:
        result = await self.session.scalars(
            select(School).where(School.provenance_ref == provenance_ref)
        )
        return list(result.all())

    async def memberships_for_account(
        self, *, account_id: int
    ) -> list[AccountSchoolMembership]:
        result = await self.session.scalars(
            select(AccountSchoolMembership).where(
                AccountSchoolMembership.account_id == account_id
            )
        )
        return list(result.all())

    async def memberships_for_school(self, *, school_id: int) -> list[AccountSchoolMembership]:
        result = await self.session.scalars(
            select(AccountSchoolMembership).where(
                AccountSchoolMembership.school_id == school_id
            )
        )
        return list(result.all())

    async def roles_for_membership(self, *, membership_id: int) -> list[MembershipRole]:
        result = await self.session.scalars(
            select(MembershipRole).where(MembershipRole.membership_id == membership_id)
        )
        return list(result.all())

    async def grants_for_account(self, *, account_id: int) -> list[SubjectAccessGrant]:
        result = await self.session.scalars(
            select(SubjectAccessGrant).where(
                SubjectAccessGrant.principal_account_id == account_id
            )
        )
        return list(result.all())

    async def grants_for_subjects(self, *, subject_ids: list[int]) -> list[SubjectAccessGrant]:
        if not subject_ids:
            return []
        result = await self.session.scalars(
            select(SubjectAccessGrant).where(SubjectAccessGrant.subject_id.in_(subject_ids))
        )
        return list(result.all())

    async def platform_roles_for_account(self, *, account_id: int) -> list[AccountRole]:
        result = await self.session.scalars(
            select(AccountRole).where(AccountRole.account_id == account_id)
        )
        return list(result.all())

    async def create_membership(
        self,
        *,
        account_id: int,
        school_id: int,
        valid_from: datetime,
        status: str = "ACTIVE",
        valid_until: datetime | None = None,
    ) -> AccountSchoolMembership:
        membership = AccountSchoolMembership(
            account_id=account_id,
            school_id=school_id,
            valid_from=valid_from,
            valid_until=valid_until,
            status=status,
        )
        self.session.add(membership)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise _map_integrity_error(exc) from exc
        return membership

    async def add_role(
        self,
        *,
        membership_id: int,
        school_id: int,
        role_code: str,
        valid_from: datetime,
        status: str = "ACTIVE",
        valid_until: datetime | None = None,
    ) -> MembershipRole:
        if role_code not in {"student", "teacher", "psychological_specialist", "admin"}:
            raise ValueError("role is not available in a school context")
        role = MembershipRole(
            membership_id=membership_id,
            school_id=school_id,
            role_code=role_code,
            valid_from=valid_from,
            valid_until=valid_until,
            status=status,
        )
        self.session.add(role)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise _map_integrity_error(exc) from exc
        return role

    async def active_contexts(
        self, *, account_id: int, at: datetime
    ) -> list[Row[tuple[int, str, int, str]]]:
        statement = (
            select(MembershipRole.id, MembershipRole.role_code, School.id, School.school_ref)
            .join(
                AccountSchoolMembership,
                MembershipRole.membership_id == AccountSchoolMembership.id,
            )
            .join(School, School.id == AccountSchoolMembership.school_id)
            .join(Account, Account.id == AccountSchoolMembership.account_id)
            .where(
                Account.id == account_id,
                Account.status == AccountStatus.ACTIVE.value,
                School.status == "ACTIVE",
                AccountSchoolMembership.status == "ACTIVE",
                AccountSchoolMembership.revoked_at.is_(None),
                AccountSchoolMembership.valid_from <= at,
                (AccountSchoolMembership.valid_until.is_(None))
                | (AccountSchoolMembership.valid_until >= at),
                MembershipRole.status == "ACTIVE",
                MembershipRole.revoked_at.is_(None),
                MembershipRole.valid_from <= at,
                (MembershipRole.valid_until.is_(None)) | (MembershipRole.valid_until >= at),
            )
            .order_by(School.school_ref, MembershipRole.role_code, MembershipRole.id)
        )
        result = await self.session.execute(statement)
        return list(result.all())

    async def context_for_account(
        self, *, account_id: int, context_id: int, at: datetime
    ) -> tuple[int, int, str] | None:
        statement = (
            select(MembershipRole.id, School.id, MembershipRole.role_code)
            .join(
                AccountSchoolMembership,
                MembershipRole.membership_id == AccountSchoolMembership.id,
            )
            .join(School, School.id == AccountSchoolMembership.school_id)
            .join(Account, Account.id == AccountSchoolMembership.account_id)
            .where(
                MembershipRole.id == context_id,
                Account.id == account_id,
                Account.status == AccountStatus.ACTIVE.value,
                School.status == "ACTIVE",
                AccountSchoolMembership.status == "ACTIVE",
                AccountSchoolMembership.revoked_at.is_(None),
                AccountSchoolMembership.valid_from <= at,
                (AccountSchoolMembership.valid_until.is_(None))
                | (AccountSchoolMembership.valid_until >= at),
                MembershipRole.status == "ACTIVE",
                MembershipRole.revoked_at.is_(None),
                MembershipRole.valid_from <= at,
                (MembershipRole.valid_until.is_(None)) | (MembershipRole.valid_until >= at),
            )
        )
        row = (await self.session.execute(statement)).one_or_none()
        if row is None:
            return None
        return (row[0], row[1], row[2])

    async def authorized_subject_refs(
        self, *, account_id: int, school_id: int, role_code: str, at: datetime
    ) -> frozenset[str]:
        relationship_type = {
            "student": "SELF",
            "teacher": "TEACHER_OF",
        }.get(role_code)
        if relationship_type is None:
            return frozenset()
        statement = (
            select(Subject.subject_ref)
            .join(SubjectAccessGrant, SubjectAccessGrant.subject_id == Subject.id)
            .join(
                AccountSchoolMembership,
                (AccountSchoolMembership.account_id == SubjectAccessGrant.principal_account_id)
                & (AccountSchoolMembership.school_id == SubjectAccessGrant.school_id),
            )
            .join(
                MembershipRole,
                MembershipRole.membership_id == AccountSchoolMembership.id,
            )
            .join(Account, Account.id == AccountSchoolMembership.account_id)
            .join(School, School.id == AccountSchoolMembership.school_id)
            .where(
                AccountSchoolMembership.account_id == account_id,
                AccountSchoolMembership.school_id == school_id,
                AccountSchoolMembership.status == "ACTIVE",
                AccountSchoolMembership.revoked_at.is_(None),
                AccountSchoolMembership.valid_from <= at,
                (AccountSchoolMembership.valid_until.is_(None))
                | (AccountSchoolMembership.valid_until >= at),
                Account.status == AccountStatus.ACTIVE.value,
                School.status == "ACTIVE",
                MembershipRole.role_code == role_code,
                MembershipRole.status == "ACTIVE",
                MembershipRole.revoked_at.is_(None),
                MembershipRole.valid_from <= at,
                (MembershipRole.valid_until.is_(None)) | (MembershipRole.valid_until >= at),
                SubjectAccessGrant.school_id == school_id,
                Subject.school_id == school_id,
                Subject.status == "ACTIVE",
                SubjectAccessGrant.relationship_type == relationship_type,
                SubjectAccessGrant.status == "ACTIVE",
                SubjectAccessGrant.revoked_at.is_(None),
                SubjectAccessGrant.valid_from <= at,
                (SubjectAccessGrant.valid_until.is_(None)) | (SubjectAccessGrant.valid_until >= at),
            )
            .distinct()
        )
        return frozenset((await self.session.scalars(statement)).all())

    async def grant_subject_in_school(
        self,
        *,
        principal_account_id: int,
        subject_id: int,
        school_id: int,
        role_code: str,
        valid_from: datetime,
        valid_until: datetime | None = None,
    ) -> SubjectAccessGrant:
        relationship_type = {"student": "SELF", "teacher": "TEACHER_OF"}.get(role_code)
        if relationship_type is None:
            raise ValueError("role cannot receive a school subject grant")
        contexts = await self.active_contexts(account_id=principal_account_id, at=valid_from)
        if not any(row[1] == role_code and row[2] == school_id for row in contexts):
            raise ValueError("principal has no active matching school role")
        subject = await self.session.scalar(
            select(Subject).where(
                Subject.id == subject_id,
                Subject.school_id == school_id,
                Subject.status == "ACTIVE",
            )
        )
        if subject is None:
            raise ValueError("subject is not active in the requested school")
        grant = SubjectAccessGrant(
            principal_account_id=principal_account_id,
            subject_id=subject_id,
            school_id=school_id,
            relationship_type=relationship_type,
            status="ACTIVE",
            valid_from=valid_from,
            valid_until=valid_until,
        )
        self.session.add(grant)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise _map_integrity_error(exc) from exc
        return grant


@dataclass(frozen=True, slots=True)
class PublishedTaskSnapshot:
    """Persistence result without student or assessment identifiers."""

    task: MeasurementTask
    enrollment_count: int


@dataclass(frozen=True, slots=True)
class TaskProgressCounts:
    """Task-only aggregate; deliberately contains no person/resource IDs."""

    published_enrollment_count: int
    active_enrollment_count: int
    revoked_enrollment_count: int
    not_started_count: int
    created_count: int
    in_progress_count: int
    completed_count: int
    abandoned_count: int
    invalid_count: int


class SchoolOperationsRepository:
    """Persistence primitives for same-school classes and task snapshots.

    This repository validates persisted relationship types and tenant links. It
    does not replace request-level Backend authorization; commit and rollback
    remain owned by the caller's ``SqlAlchemyUnitOfWork``.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_class(
        self,
        *,
        school_id: int,
        class_ref: str,
        admin_membership_role_id: int,
        at: datetime,
    ) -> SchoolClass:
        await self._require_active_role(
            admin_membership_role_id,
            school_id=school_id,
            role_code="admin",
            at=at,
        )
        record = SchoolClass(
            school_id=school_id,
            class_ref=class_ref,
            created_by_membership_role_id=admin_membership_role_id,
            status="ACTIVE",
        )
        self.session.add(record)
        await self._flush_unique()
        return record

    async def add_student_subject_to_class(
        self,
        *,
        school_id: int,
        class_id: int,
        subject_id: int,
        admin_membership_role_id: int,
        at: datetime,
        valid_until: datetime | None = None,
    ) -> SchoolClassStudent:
        await self._require_active_role(
            admin_membership_role_id,
            school_id=school_id,
            role_code="admin",
            at=at,
        )
        await self._require_active_class(class_id, school_id=school_id)
        await self._require_active_student_subject(
            subject_id,
            school_id=school_id,
            at=at,
        )
        if valid_until is not None and valid_until < at:
            raise ValueError("class student link validity is invalid")
        existing = await self.session.scalar(
            select(SchoolClassStudent).where(
                SchoolClassStudent.school_id == school_id,
                SchoolClassStudent.class_id == class_id,
                SchoolClassStudent.subject_id == subject_id,
            )
        )
        if existing is not None:
            if (
                existing.status != "ACTIVE"
                or existing.revoked_at is not None
                or existing.valid_from > at
                or (existing.valid_until is not None and existing.valid_until < at)
            ):
                existing.status = "ACTIVE"
                existing.valid_from = at
                existing.valid_until = valid_until
                existing.revoked_at = None
                await self._flush_unique()
            return existing
        record = SchoolClassStudent(
            school_id=school_id,
            class_id=class_id,
            subject_id=subject_id,
            status="ACTIVE",
            valid_from=at,
            valid_until=valid_until,
        )
        self.session.add(record)
        await self._flush_unique()
        return record

    async def add_teacher_role_to_class(
        self,
        *,
        school_id: int,
        class_id: int,
        teacher_membership_role_id: int,
        admin_membership_role_id: int,
        at: datetime,
        valid_until: datetime | None = None,
    ) -> SchoolClassTeacher:
        await self._require_active_role(
            admin_membership_role_id,
            school_id=school_id,
            role_code="admin",
            at=at,
        )
        await self._require_active_class(class_id, school_id=school_id)
        await self._require_active_role(
            teacher_membership_role_id,
            school_id=school_id,
            role_code="teacher",
            at=at,
        )
        if valid_until is not None and valid_until < at:
            raise ValueError("class teacher link validity is invalid")
        existing = await self.session.scalar(
            select(SchoolClassTeacher).where(
                SchoolClassTeacher.school_id == school_id,
                SchoolClassTeacher.class_id == class_id,
                SchoolClassTeacher.membership_role_id == teacher_membership_role_id,
            )
        )
        if existing is not None:
            if (
                existing.status != "ACTIVE"
                or existing.revoked_at is not None
                or existing.valid_from > at
                or (existing.valid_until is not None and existing.valid_until < at)
            ):
                existing.status = "ACTIVE"
                existing.valid_from = at
                existing.valid_until = valid_until
                existing.revoked_at = None
                await self._flush_unique()
            return existing
        record = SchoolClassTeacher(
            school_id=school_id,
            class_id=class_id,
            membership_role_id=teacher_membership_role_id,
            status="ACTIVE",
            valid_from=at,
            valid_until=valid_until,
        )
        self.session.add(record)
        await self._flush_unique()
        return record

    async def revoke_class_student_link(
        self,
        *,
        link_id: int,
        school_id: int,
        admin_membership_role_id: int,
        at: datetime,
    ) -> SchoolClassStudent:
        await self._require_active_role(
            admin_membership_role_id,
            school_id=school_id,
            role_code="admin",
            at=at,
        )
        link = await self.session.get(SchoolClassStudent, link_id)
        if link is None or link.school_id != school_id:
            raise NotFound("class student link was not found")
        if link.status != "REVOKED":
            link.status = "REVOKED"
            link.revoked_at = at
            await self.session.execute(
                update(TaskEnrollment)
                .where(
                    TaskEnrollment.class_student_id == link.id,
                    TaskEnrollment.school_id == school_id,
                    TaskEnrollment.status == "ACTIVE",
                )
                .values(status="REVOKED", revoked_at=at)
            )
            await self.session.flush()
        return link

    async def revoke_class_teacher_link(
        self,
        *,
        link_id: int,
        school_id: int,
        admin_membership_role_id: int,
        at: datetime,
    ) -> SchoolClassTeacher:
        await self._require_active_role(
            admin_membership_role_id,
            school_id=school_id,
            role_code="admin",
            at=at,
        )
        link = await self.session.get(SchoolClassTeacher, link_id)
        if link is None or link.school_id != school_id:
            raise NotFound("class teacher link was not found")
        if link.status != "REVOKED":
            link.status = "REVOKED"
            link.revoked_at = at
            await self.session.flush()
        return link

    async def publish_task_with_snapshot(
        self,
        *,
        school_id: int,
        class_id: int,
        task_ref: str,
        admin_membership_role_id: int,
        instrument_id: str,
        instrument_version: str,
        item_bank_version: str | None,
        config_version: str | None,
        opens_at: datetime,
        due_at: datetime | None,
        published_at: datetime,
    ) -> PublishedTaskSnapshot:
        """Create a published task and snapshot active class students atomically.

        The nested transaction is a savepoint inside the caller's UOW. An
        invalid roster link or any flush conflict removes both the task and
        every enrollment created by this operation.
        """

        if due_at is not None and due_at < opens_at:
            raise ValueError("measurement task window is invalid")
        try:
            async with self.session.begin_nested():
                await self._require_active_role(
                    admin_membership_role_id,
                    school_id=school_id,
                    role_code="admin",
                    at=published_at,
                )
                await self._require_active_class(class_id, school_id=school_id)
                task = MeasurementTask(
                    school_id=school_id,
                    class_id=class_id,
                    task_ref=task_ref,
                    created_by_membership_role_id=admin_membership_role_id,
                    instrument_id=instrument_id,
                    instrument_version=instrument_version,
                    item_bank_version=item_bank_version,
                    config_version=config_version,
                    opens_at=opens_at,
                    due_at=due_at,
                    published_at=published_at,
                    status="PUBLISHED",
                )
                self.session.add(task)
                await self.session.flush()

                links = list(
                    (
                        await self.session.scalars(
                            select(SchoolClassStudent).where(
                                SchoolClassStudent.school_id == school_id,
                                SchoolClassStudent.class_id == class_id,
                                SchoolClassStudent.status == "ACTIVE",
                                SchoolClassStudent.revoked_at.is_(None),
                                SchoolClassStudent.valid_from <= published_at,
                                (SchoolClassStudent.valid_until.is_(None))
                                | (SchoolClassStudent.valid_until >= published_at),
                            )
                        )
                    ).all()
                )
                for link in links:
                    await self._require_active_student_subject(
                        link.subject_id,
                        school_id=school_id,
                        at=published_at,
                    )
                    self.session.add(
                        TaskEnrollment(
                            school_id=school_id,
                            task_id=task.id,
                            class_id=class_id,
                            class_student_id=link.id,
                            subject_id=link.subject_id,
                            status="ACTIVE",
                        )
                    )
                    await self.session.flush()
                return PublishedTaskSnapshot(task=task, enrollment_count=len(links))
        except IntegrityError as exc:
            raise _map_integrity_error(exc) from exc

    async def revoke_enrollment(
        self,
        *,
        enrollment_id: int,
        school_id: int,
        admin_membership_role_id: int,
        at: datetime,
    ) -> TaskEnrollment:
        await self._require_active_role(
            admin_membership_role_id,
            school_id=school_id,
            role_code="admin",
            at=at,
        )
        enrollment = await self.session.get(TaskEnrollment, enrollment_id)
        if enrollment is None or enrollment.school_id != school_id:
            raise NotFound("task enrollment was not found")
        if enrollment.status != "REVOKED":
            enrollment.status = "REVOKED"
            enrollment.revoked_at = at
            await self.session.flush()
        return enrollment

    async def link_assessment_session(
        self,
        *,
        enrollment_id: int,
        assessment_session_id: int,
        school_id: int,
        student_account_id: int,
        at: datetime,
    ) -> AssessmentSession:
        enrollment = await self._require_active_enrollment(
            enrollment_id=enrollment_id,
            school_id=school_id,
            student_account_id=student_account_id,
            at=at,
        )
        assessment = await self.session.get(AssessmentSession, assessment_session_id)
        if assessment is None:
            raise NotFound("assessment session was not found")
        if assessment.subject_id != enrollment.subject_id:
            raise ValueError("assessment subject does not match task enrollment")
        if assessment.task_enrollment_id == enrollment.id:
            return assessment
        if assessment.task_enrollment_id is not None:
            raise UniqueConflict("assessment session is already linked to another task enrollment")
        raise ValueError("unbound assessment sessions cannot be linked to a task enrollment")

    async def create_task_assessment_session(
        self,
        *,
        enrollment_id: int,
        assessment_ref: str,
        school_id: int,
        student_account_id: int,
        at: datetime,
        trace_id: str | None = None,
    ) -> AssessmentSession:
        """Create or recover the one task-bound session for a current enrollment.

        All task-derived fields come from persisted task/enrollment records.
        The savepoint makes uniqueness races recoverable without leaving the
        caller-owned unit of work in a failed state.
        """

        enrollment = await self._require_active_enrollment(
            enrollment_id=enrollment_id,
            school_id=school_id,
            student_account_id=student_account_id,
            at=at,
        )
        existing = await self._linked_session_for_enrollment(enrollment.id, enrollment.subject_id)
        if existing is not None:
            return existing

        task = await self.session.get(MeasurementTask, enrollment.task_id)
        if (
            task is None
            or task.school_id != enrollment.school_id
            or task.class_id != enrollment.class_id
            or task.status != "PUBLISHED"
            or task.opens_at > at
            or (task.due_at is not None and task.due_at < at)
        ):
            raise NotFound("open measurement task was not found")

        candidate = AssessmentSession(
            assessment_ref=assessment_ref,
            subject_id=enrollment.subject_id,
            task_enrollment_id=enrollment.id,
            instrument_id=task.instrument_id,
            instrument_version=task.instrument_version,
            item_bank_version=task.item_bank_version,
            config_version=task.config_version,
            trace_id=trace_id,
            status=AssessmentStatus.CREATED.value,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(candidate)
                await self.session.flush()
            return candidate
        except IntegrityError as exc:
            # A concurrent start may have won the unique enrollment constraint.
            # Locking read observes the committed winner even under REPEATABLE READ.
            existing = await self._linked_session_for_enrollment(
                enrollment.id, enrollment.subject_id, current_read=True
            )
            if existing is not None:
                return existing
            raise _map_integrity_error(exc) from exc

    async def linked_assessment_session(
        self,
        *,
        enrollment_id: int,
        school_id: int,
        student_account_id: int,
        at: datetime,
    ) -> AssessmentSession | None:
        """Return the existing session for a current enrollment, if present."""

        enrollment = await self._require_active_enrollment(
            enrollment_id=enrollment_id,
            school_id=school_id,
            student_account_id=student_account_id,
            at=at,
        )
        return await self.session.scalar(
            select(AssessmentSession).where(
                AssessmentSession.task_enrollment_id == enrollment.id,
                AssessmentSession.subject_id == enrollment.subject_id,
            )
        )

    async def active_enrollment_for_assessment(
        self,
        *,
        assessment_ref: str,
        student_account_id: int,
        at: datetime,
    ) -> TaskEnrollment | None:
        return await self.session.scalar(
            self._active_enrollment_statement(
                student_account_id=student_account_id,
                at=at,
                assessment_ref=assessment_ref,
            )
        )

    async def completed_enrollment_for_post_assessment(
        self,
        *,
        assessment_ref: str,
        student_account_id: int,
        at: datetime,
    ) -> TaskEnrollment | None:
        """Reauthorize completed work using its completion time, not task read window."""
        return await self.session.scalar(
            self._active_enrollment_statement(
                student_account_id=student_account_id,
                at=at,
                assessment_ref=assessment_ref,
                completed_assessment=True,
            )
        )

    async def _require_active_enrollment(
        self,
        *,
        enrollment_id: int,
        school_id: int,
        student_account_id: int,
        at: datetime,
    ) -> TaskEnrollment:
        enrollment = await self.session.scalar(
            self._active_enrollment_statement(
                student_account_id=student_account_id,
                at=at,
                enrollment_id=enrollment_id,
            )
        )
        if enrollment is None or enrollment.school_id != school_id:
            raise NotFound("active task enrollment was not found")
        return enrollment

    def _active_enrollment_statement(
        self,
        *,
        student_account_id: int,
        at: datetime,
        enrollment_id: int | None = None,
        assessment_ref: str | None = None,
        completed_assessment: bool = False,
    ):
        statement = (
            select(TaskEnrollment)
            .select_from(TaskEnrollment)
            .join(
                SchoolClassStudent,
                (SchoolClassStudent.id == TaskEnrollment.class_student_id)
                & (SchoolClassStudent.subject_id == TaskEnrollment.subject_id)
                & (SchoolClassStudent.class_id == TaskEnrollment.class_id)
                & (SchoolClassStudent.school_id == TaskEnrollment.school_id),
            )
            .join(
                SchoolClass,
                (SchoolClass.id == TaskEnrollment.class_id)
                & (SchoolClass.school_id == TaskEnrollment.school_id),
            )
            .join(
                MeasurementTask,
                (MeasurementTask.id == TaskEnrollment.task_id)
                & (MeasurementTask.school_id == TaskEnrollment.school_id)
                & (MeasurementTask.class_id == TaskEnrollment.class_id),
            )
            .join(Subject, (Subject.id == TaskEnrollment.subject_id))
            .join(
                SubjectAccessGrant,
                (SubjectAccessGrant.subject_id == TaskEnrollment.subject_id)
                & (SubjectAccessGrant.school_id == TaskEnrollment.school_id),
            )
            .join(
                AccountSchoolMembership,
                (AccountSchoolMembership.account_id == SubjectAccessGrant.principal_account_id)
                & (AccountSchoolMembership.school_id == TaskEnrollment.school_id),
            )
            .join(
                MembershipRole,
                MembershipRole.membership_id == AccountSchoolMembership.id,
            )
            .join(Account, Account.id == AccountSchoolMembership.account_id)
            .join(School, School.id == TaskEnrollment.school_id)
            .where(
                TaskEnrollment.status == "ACTIVE",
                TaskEnrollment.revoked_at.is_(None),
                MeasurementTask.status == "PUBLISHED",
                SchoolClassStudent.status == "ACTIVE",
                SchoolClassStudent.revoked_at.is_(None),
                SchoolClassStudent.valid_from <= at,
                (SchoolClassStudent.valid_until.is_(None))
                | (SchoolClassStudent.valid_until >= at),
                SchoolClass.status == "ACTIVE",
                Subject.status == "ACTIVE",
                Subject.data_origin == DataOrigin.SYNTHETIC.value,
                Subject.school_id == TaskEnrollment.school_id,
                SubjectAccessGrant.principal_account_id == student_account_id,
                SubjectAccessGrant.relationship_type == "SELF",
                SubjectAccessGrant.status == "ACTIVE",
                SubjectAccessGrant.revoked_at.is_(None),
                SubjectAccessGrant.valid_from <= at,
                (SubjectAccessGrant.valid_until.is_(None))
                | (SubjectAccessGrant.valid_until >= at),
                Account.status == AccountStatus.ACTIVE.value,
                AccountSchoolMembership.status == "ACTIVE",
                AccountSchoolMembership.revoked_at.is_(None),
                AccountSchoolMembership.valid_from <= at,
                (AccountSchoolMembership.valid_until.is_(None))
                | (AccountSchoolMembership.valid_until >= at),
                MembershipRole.school_id == TaskEnrollment.school_id,
                MembershipRole.role_code == "student",
                MembershipRole.status == "ACTIVE",
                MembershipRole.revoked_at.is_(None),
                MembershipRole.valid_from <= at,
                (MembershipRole.valid_until.is_(None)) | (MembershipRole.valid_until >= at),
                School.status == "ACTIVE",
                School.data_origin == DataOrigin.SYNTHETIC.value,
            )
        )
        if enrollment_id is not None:
            statement = statement.where(TaskEnrollment.id == enrollment_id)
        if assessment_ref is not None:
            statement = statement.join(
                AssessmentSession,
                (AssessmentSession.task_enrollment_id == TaskEnrollment.id)
                & (AssessmentSession.subject_id == TaskEnrollment.subject_id),
            ).where(AssessmentSession.assessment_ref == assessment_ref)
        if completed_assessment:
            if assessment_ref is None:
                raise ValueError("completed assessment scope requires an assessment reference")
            statement = statement.where(
                AssessmentSession.status == "COMPLETED",
                AssessmentSession.completed_at.is_not(None),
                AssessmentSession.completed_at <= at,
                MeasurementTask.opens_at <= AssessmentSession.completed_at,
                (MeasurementTask.due_at.is_(None))
                | (AssessmentSession.completed_at <= MeasurementTask.due_at),
            )
        else:
            statement = statement.where(
                MeasurementTask.opens_at <= at,
                (MeasurementTask.due_at.is_(None)) | (MeasurementTask.due_at >= at),
            )
        return statement.distinct()

    async def _linked_session_for_enrollment(
        self, enrollment_id: int, subject_id: int, *, current_read: bool = False
    ) -> AssessmentSession | None:
        statement = select(AssessmentSession).where(
            AssessmentSession.task_enrollment_id == enrollment_id,
            AssessmentSession.subject_id == subject_id,
        )
        if current_read:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def task_progress_counts(
        self, *, task_id: int, school_id: int
    ) -> TaskProgressCounts:
        active = TaskEnrollment.status == "ACTIVE"
        research_task = MeasurementTask.cat_binding_mode == "RESEARCH_PROFILE"
        normal_task = MeasurementTask.cat_binding_mode != "RESEARCH_PROFILE"
        session_missing = case(
            (research_task, SchoolResearchSession.id.is_(None)),
            else_=AssessmentSession.id.is_(None),
        )
        statement = (
            select(
                func.count(TaskEnrollment.id).label("published_enrollment_count"),
                func.sum(case((active, 1), else_=0)).label("active_enrollment_count"),
                func.sum(case((TaskEnrollment.status == "REVOKED", 1), else_=0)).label(
                    "revoked_enrollment_count"
                ),
                func.sum(
                    case(
                        (and_(active, session_missing), 1),
                        else_=0,
                    )
                ).label("not_started_count"),
                *(
                    func.sum(
                        case(
                            (
                                and_(
                                    active,
                                    case(
                                        (
                                            research_task,
                                            (
                                                SchoolResearchSession.status
                                                == research_status
                                                if research_status is not None
                                                else False
                                            ),
                                        ),
                                        else_=and_(
                                            AssessmentSession.status == status,
                                            AssessmentSession.cat_binding_mode
                                            == MeasurementTask.cat_binding_mode,
                                        ),
                                    ),
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ).label(label)
                    for status, label, research_status in (
                        ("CREATED", "created_count", None),
                        ("IN_PROGRESS", "in_progress_count", "IN_PROGRESS"),
                        ("COMPLETED", "completed_count", "COMPLETED"),
                        ("ABANDONED", "abandoned_count", "ABANDONED"),
                        ("INVALID", "invalid_count", "FAILED"),
                    )
                ),
            )
            .select_from(MeasurementTask)
            .outerjoin(
                TaskEnrollment,
                (TaskEnrollment.task_id == MeasurementTask.id)
                & (TaskEnrollment.school_id == MeasurementTask.school_id),
            )
            .outerjoin(
                AssessmentSession,
                normal_task
                & (AssessmentSession.task_enrollment_id == TaskEnrollment.id)
                & (AssessmentSession.subject_id == TaskEnrollment.subject_id)
                & (
                    AssessmentSession.cat_binding_mode
                    == MeasurementTask.cat_binding_mode
                ),
            )
            .outerjoin(
                SchoolResearchSession,
                research_task
                & (SchoolResearchSession.task_enrollment_id == TaskEnrollment.id)
                & (SchoolResearchSession.subject_id == TaskEnrollment.subject_id)
                & (SchoolResearchSession.task_id == MeasurementTask.id)
                & (SchoolResearchSession.school_id == MeasurementTask.school_id)
                & (SchoolResearchSession.class_id == MeasurementTask.class_id),
            )
            .where(MeasurementTask.id == task_id, MeasurementTask.school_id == school_id)
            .group_by(MeasurementTask.id)
        )
        row = (await self.session.execute(statement)).one_or_none()
        if row is None:
            raise NotFound("measurement task was not found")
        return TaskProgressCounts(*(int(value or 0) for value in row))

    async def _require_active_role(
        self,
        membership_role_id: int,
        *,
        school_id: int,
        role_code: str,
        at: datetime,
    ) -> MembershipRole:
        statement = (
            select(MembershipRole)
            .join(
                AccountSchoolMembership,
                MembershipRole.membership_id == AccountSchoolMembership.id,
            )
            .join(Account, Account.id == AccountSchoolMembership.account_id)
            .join(School, School.id == AccountSchoolMembership.school_id)
            .where(
                MembershipRole.id == membership_role_id,
                MembershipRole.school_id == school_id,
                MembershipRole.role_code == role_code,
                MembershipRole.status == "ACTIVE",
                MembershipRole.revoked_at.is_(None),
                MembershipRole.valid_from <= at,
                (MembershipRole.valid_until.is_(None)) | (MembershipRole.valid_until >= at),
                AccountSchoolMembership.school_id == school_id,
                AccountSchoolMembership.status == "ACTIVE",
                AccountSchoolMembership.revoked_at.is_(None),
                AccountSchoolMembership.valid_from <= at,
                (AccountSchoolMembership.valid_until.is_(None))
                | (AccountSchoolMembership.valid_until >= at),
                Account.status == AccountStatus.ACTIVE.value,
                School.status == "ACTIVE",
                School.data_origin == DataOrigin.SYNTHETIC.value,
            )
        )
        record = await self.session.scalar(statement)
        if (
            record is None
            or record.role_code != role_code
            or record.school_id != school_id
            or record.status != "ACTIVE"
            or record.revoked_at is not None
        ):
            raise ValueError(f"an active same-school {role_code} role is required")
        return record

    async def _require_active_class(self, class_id: int, *, school_id: int) -> SchoolClass:
        statement = (
            select(SchoolClass)
            .join(School, School.id == SchoolClass.school_id)
            .where(
                SchoolClass.id == class_id,
                SchoolClass.school_id == school_id,
                SchoolClass.status == "ACTIVE",
                School.status == "ACTIVE",
                School.data_origin == DataOrigin.SYNTHETIC.value,
            )
        )
        record = await self.session.scalar(statement)
        if record is None:
            raise NotFound("active school class was not found")
        return record

    async def _require_active_student_subject(
        self,
        subject_id: int,
        *,
        school_id: int,
        at: datetime,
        principal_account_id: int | None = None,
    ) -> None:
        statement = (
            select(func.count(distinct(SubjectAccessGrant.principal_account_id)))
            .select_from(SubjectAccessGrant)
            .join(
                AccountSchoolMembership,
                (AccountSchoolMembership.account_id == SubjectAccessGrant.principal_account_id)
                & (AccountSchoolMembership.school_id == SubjectAccessGrant.school_id),
            )
            .join(
                MembershipRole,
                MembershipRole.membership_id == AccountSchoolMembership.id,
            )
            .join(Account, Account.id == AccountSchoolMembership.account_id)
            .join(School, School.id == AccountSchoolMembership.school_id)
            .join(Subject, Subject.id == SubjectAccessGrant.subject_id)
            .where(
                SubjectAccessGrant.subject_id == subject_id,
                SubjectAccessGrant.school_id == school_id,
                SubjectAccessGrant.relationship_type == "SELF",
                SubjectAccessGrant.status == "ACTIVE",
                SubjectAccessGrant.revoked_at.is_(None),
                SubjectAccessGrant.valid_from <= at,
                (SubjectAccessGrant.valid_until.is_(None))
                | (SubjectAccessGrant.valid_until >= at),
                AccountSchoolMembership.school_id == school_id,
                AccountSchoolMembership.status == "ACTIVE",
                AccountSchoolMembership.revoked_at.is_(None),
                AccountSchoolMembership.valid_from <= at,
                (AccountSchoolMembership.valid_until.is_(None))
                | (AccountSchoolMembership.valid_until >= at),
                MembershipRole.role_code == "student",
                MembershipRole.status == "ACTIVE",
                MembershipRole.revoked_at.is_(None),
                MembershipRole.valid_from <= at,
                (MembershipRole.valid_until.is_(None)) | (MembershipRole.valid_until >= at),
                MembershipRole.school_id == school_id,
                Account.status == AccountStatus.ACTIVE.value,
                School.status == "ACTIVE",
                School.data_origin == DataOrigin.SYNTHETIC.value,
                Subject.school_id == school_id,
                Subject.status == "ACTIVE",
                Subject.data_origin == DataOrigin.SYNTHETIC.value,
            )
        )
        if principal_account_id is not None:
            statement = statement.where(
                SubjectAccessGrant.principal_account_id == principal_account_id
            )
        principal_count = int(await self.session.scalar(statement) or 0)
        if principal_count != 1:
            raise ValueError("subject requires one active same-school student SELF grant")

    async def _flush_unique(self) -> None:
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise _map_integrity_error(exc) from exc


class ConsentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        subject_id: int,
        consent_type: str,
        policy_version: str,
        scope_identifier: str,
        status: ConsentStatus,
        granted_at: datetime,
        granted_by_account_id: int | None = None,
        granted_by_relationship: str | None = None,
        withdrawn_at: datetime | None = None,
        trace_id: str | None = None,
        retention_due_at: datetime | None = None,
    ) -> ConsentRecord:
        record = ConsentRecord(
            subject_id=subject_id,
            consent_type=consent_type,
            policy_version=policy_version,
            scope_identifier=scope_identifier,
            granted_by_account_id=granted_by_account_id,
            granted_by_relationship=granted_by_relationship,
            granted_at=granted_at,
            withdrawn_at=withdrawn_at,
            status=status.value,
            trace_id=trace_id,
            retention_due_at=retention_due_at,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def history(self, subject_id: int, consent_type: str) -> list[ConsentRecord]:
        result = await self.session.execute(
            select(ConsentRecord)
            .where(
                ConsentRecord.subject_id == subject_id,
                ConsentRecord.consent_type == consent_type,
            )
            .order_by(ConsentRecord.created_at, ConsentRecord.id)
        )
        return list(result.scalars())


class AuthSessionStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        account_id: int,
        raw_session_token: str,
        idle_expires_at: datetime,
        absolute_expires_at: datetime,
        raw_csrf_token: str | None = None,
        user_agent: str | None = None,
        active_school_id: int | None = None,
        active_membership_role_id: int | None = None,
    ) -> AuthSession:
        record = AuthSession(
            account_id=account_id,
            session_token_hash=_hash_opaque_token(raw_session_token),
            csrf_token_hash=_hash_opaque_token(raw_csrf_token) if raw_csrf_token else None,
            user_agent_hash=_hash_opaque_token(user_agent) if user_agent else None,
            active_school_id=active_school_id,
            active_membership_role_id=active_membership_role_id,
            idle_expires_at=idle_expires_at,
            absolute_expires_at=absolute_expires_at,
        )
        self.session.add(record)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise _map_integrity_error(exc) from exc
        return record

    async def set_active_context(
        self,
        raw_session_token: str,
        *,
        school_id: int,
        membership_role_id: int,
    ) -> AuthSession | None:
        record = await self.find_by_token(raw_session_token)
        if record is None:
            return None
        record.active_school_id = school_id
        record.active_membership_role_id = membership_role_id
        await self.session.flush()
        return record

    async def find_by_token(self, raw_session_token: str) -> AuthSession | None:
        token_hash = _hash_opaque_token(raw_session_token)
        result = await self.session.execute(
            select(AuthSession).where(
                AuthSession.session_token_hash == token_hash,
                AuthSession.revoked_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def revoke(self, raw_session_token: str, *, reason: str, at: datetime) -> None:
        record = await self.find_by_token(raw_session_token)
        if record is not None:
            record.revoked_at = at
            record.revocation_reason = reason
            await self.session.flush()


class AssessmentRepository:
    def __init__(self, session: AsyncSession, protection: FernetDataProtectionProvider) -> None:
        self.session = session
        self.protection = protection

    async def create_session(
        self,
        *,
        assessment_ref: str,
        subject_id: int,
        instrument_id: str,
        instrument_version: str,
        item_bank_version: str | None,
        config_version: str | None,
        trace_id: str | None,
    ) -> AssessmentSession:
        record = AssessmentSession(
            assessment_ref=assessment_ref,
            subject_id=subject_id,
            instrument_id=instrument_id,
            instrument_version=instrument_version,
            item_bank_version=item_bank_version,
            config_version=config_version,
            trace_id=trace_id,
            status=AssessmentStatus.CREATED.value,
        )
        self.session.add(record)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise _map_integrity_error(exc) from exc
        return record

    async def append_response(
        self,
        *,
        assessment_session_id: int,
        sequence_no: int,
        item_ref: str,
        response_payload: Mapping[str, object],
        trace_id: str | None,
        payload_schema_version: str = "assessment-response.v1",
        retention_due_at: datetime | None = None,
    ) -> AssessmentResponse:
        protected = self.protection.encrypt_json(
            response_payload, payload_schema_version=payload_schema_version
        )
        record = AssessmentResponse(
            assessment_session_id=assessment_session_id,
            sequence_no=sequence_no,
            item_ref=item_ref,
            response_ciphertext=protected.ciphertext,
            cipher_format_version=protected.cipher_format_version,
            key_version=protected.key_version,
            payload_schema_version=protected.payload_schema_version,
            trace_id=trace_id,
            retention_due_at=retention_due_at,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def save_result(
        self,
        *,
        assessment_session_id: int,
        result_payload: Mapping[str, object],
        completed_at: datetime | None,
        retention_due_at: datetime | None,
        payload_schema_version: str = "assessment-result.v1",
    ) -> AssessmentResult:
        protected = self.protection.encrypt_json(
            result_payload, payload_schema_version=payload_schema_version
        )
        record = AssessmentResult(
            assessment_session_id=assessment_session_id,
            payload_ciphertext=protected.ciphertext,
            cipher_format_version=protected.cipher_format_version,
            key_version=protected.key_version,
            payload_schema_version=protected.payload_schema_version,
            completed_at=completed_at,
            retention_due_at=retention_due_at,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_session(self, assessment_ref: str) -> AssessmentSession:
        result = await self.session.execute(
            select(AssessmentSession).where(AssessmentSession.assessment_ref == assessment_ref)
        )
        record = result.scalar_one_or_none()
        if record is None:
            raise NotFound("assessment session was not found")
        return record


class SupportRepository:
    def __init__(self, session: AsyncSession, protection: FernetDataProtectionProvider) -> None:
        self.session = session
        self.protection = protection

    async def create_session(
        self,
        *,
        support_ref: str,
        subject_id: int,
        target_role: str,
        assessment_session_id: int | None,
        trace_id: str | None,
        retention_due_at: datetime | None,
    ) -> SupportSession:
        record = SupportSession(
            support_ref=support_ref,
            subject_id=subject_id,
            target_role=target_role,
            assessment_session_id=assessment_session_id,
            trace_id=trace_id,
            retention_due_at=retention_due_at,
            status=SupportStatus.OPEN.value,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def create_run(
        self,
        *,
        run_ref: str,
        support_session_id: int,
        trace_id: str,
        status: SupportRunStatus = SupportRunStatus.REQUESTED,
        workflow_action: str | None = None,
        assessment_session_id: int | None = None,
        generation_ref: str | None = None,
        retrieval_ref: str | None = None,
        component_versions: Mapping[str, object] | None = None,
    ) -> SupportRun:
        record = SupportRun(
            run_ref=run_ref,
            support_session_id=support_session_id,
            assessment_session_id=assessment_session_id,
            generation_ref=generation_ref,
            retrieval_ref=retrieval_ref,
            trace_id=trace_id,
            status=status.value,
            workflow_action=workflow_action,
            component_versions=dict(component_versions) if component_versions else None,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def persist_message(
        self,
        *,
        support_session_id: int,
        sequence_no: int,
        message_kind: MessageKind,
        payload: Mapping[str, object],
        safety_decision_id: int | None = None,
        retention_due_at: datetime | None = None,
    ) -> SupportMessage:
        if message_kind not in {MessageKind.USER_INPUT, MessageKind.APPROVED_OUTPUT}:
            raise ValueError("only user input or safety-approved output may be persisted")
        protected = self.protection.encrypt_json(
            payload, payload_schema_version="support-message.v1"
        )
        record = SupportMessage(
            support_session_id=support_session_id,
            sequence_no=sequence_no,
            message_kind=message_kind.value,
            payload_ciphertext=protected.ciphertext,
            cipher_format_version=protected.cipher_format_version,
            key_version=protected.key_version,
            payload_schema_version=protected.payload_schema_version,
            safety_decision_id=safety_decision_id,
            retention_due_at=retention_due_at,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def add_evidence(
        self,
        *,
        support_run_id: int,
        citation_id: str,
        source_id: str,
        chunk_id: str | None = None,
        document_id: str | None = None,
        source_version: str | None = None,
        source_hash: str | None = None,
        citation_title: str | None = None,
        citation_organization: str | None = None,
        locator: str | None = None,
        rank_order: int = 0,
    ) -> SupportEvidence:
        record = SupportEvidence(
            support_run_id=support_run_id,
            citation_id=citation_id,
            source_id=source_id,
            chunk_id=chunk_id,
            document_id=document_id,
            source_version=source_version,
            source_hash=source_hash,
            citation_title=citation_title,
            citation_organization=citation_organization,
            locator=locator,
            rank_order=rank_order,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def create_safety_decision(
        self,
        *,
        decision_ref: str,
        support_run_id: int,
        action: SafetyAction,
        policy_version: str,
        guard_model_revision: str | None,
        trace_id: str,
        detail: Mapping[str, object] | None,
        retention_due_at: datetime | None,
    ) -> SafetyDecision:
        protected: EncryptedPayload | None = None
        if detail is not None:
            protected = self.protection.encrypt_json(
                detail, payload_schema_version="safety-detail.v1"
            )
        record = SafetyDecision(
            decision_ref=decision_ref,
            support_run_id=support_run_id,
            action=action.value,
            policy_version=policy_version,
            guard_model_revision=guard_model_revision,
            trace_id=trace_id,
            detail_ciphertext=protected.ciphertext if protected else None,
            cipher_format_version=protected.cipher_format_version if protected else None,
            key_version=protected.key_version if protected else None,
            payload_schema_version=protected.payload_schema_version if protected else None,
            retention_due_at=retention_due_at,
        )
        self.session.add(record)
        await self.session.flush()
        return record


class ReviewRepository:
    def __init__(self, session: AsyncSession, protection: FernetDataProtectionProvider) -> None:
        self.session = session
        self.protection = protection

    async def create_case(
        self,
        *,
        review_ref: str,
        subject_id: int,
        safety_decision_id: int,
        priority: ReviewPriority,
        case_note: Mapping[str, object] | None,
        retention_due_at: datetime | None,
    ) -> ReviewCase:
        protected = (
            self.protection.encrypt_json(case_note, payload_schema_version="review-note.v1")
            if case_note is not None
            else None
        )
        record = ReviewCase(
            review_ref=review_ref,
            subject_id=subject_id,
            safety_decision_id=safety_decision_id,
            priority=priority.value,
            status=ReviewStatus.OPEN.value,
            case_note_ciphertext=protected.ciphertext if protected else None,
            cipher_format_version=protected.cipher_format_version if protected else None,
            key_version=protected.key_version if protected else None,
            payload_schema_version=protected.payload_schema_version if protected else None,
            retention_due_at=retention_due_at,
        )
        self.session.add(record)
        await self.session.flush()
        await self.add_event(
            review_case_id=record.id,
            event_type=ReviewEventType.CREATED,
            actor_account_id=None,
            to_status=ReviewStatus.OPEN.value,
            note=None,
            trace_id=None,
            retention_due_at=retention_due_at,
        )
        return record

    async def update_case(
        self,
        *,
        review_case_id: int,
        expected_version: int,
        status: ReviewStatus,
        assigned_account_id: int | None = None,
        closed_at: datetime | None = None,
    ) -> ReviewCase:
        values: dict[str, Any] = {
            "status": status.value,
            "assigned_account_id": assigned_account_id,
            "closed_at": closed_at,
            "version": expected_version + 1,
        }
        result = await self.session.execute(
            update(ReviewCase)
            .where(ReviewCase.id == review_case_id, ReviewCase.version == expected_version)
            .values(**values)
        )
        if result.rowcount != 1:  # type: ignore[reportAttributeAccessIssue]
            raise OptimisticConcurrencyConflict("review case version is stale")
        await self.session.flush()
        refreshed = await self.session.get(ReviewCase, review_case_id)
        if refreshed is None:
            raise NotFound("review case was not found")
        return refreshed

    async def add_event(
        self,
        *,
        review_case_id: int,
        event_type: ReviewEventType,
        actor_account_id: int | None,
        to_status: str | None,
        note: Mapping[str, object] | None,
        trace_id: str | None,
        retention_due_at: datetime | None,
    ) -> ReviewEvent:
        protected = (
            self.protection.encrypt_json(note, payload_schema_version="review-event-note.v1")
            if note is not None
            else None
        )
        record = ReviewEvent(
            review_case_id=review_case_id,
            event_type=event_type.value,
            actor_account_id=actor_account_id,
            to_status=to_status,
            note_ciphertext=protected.ciphertext if protected else None,
            cipher_format_version=protected.cipher_format_version if protected else None,
            key_version=protected.key_version if protected else None,
            payload_schema_version=protected.payload_schema_version if protected else None,
            trace_id=trace_id,
            retention_due_at=retention_due_at,
        )
        self.session.add(record)
        await self.session.flush()
        return record


class IdempotencyStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def claim(
        self,
        *,
        scope: str,
        key: str,
        request_bytes: bytes,
        expires_at: datetime,
    ) -> tuple[IdempotencyRecord, bool]:
        record = IdempotencyRecord(
            scope=scope,
            key_hash=_hash_opaque_token(key),
            request_hash=_hash_request(request_bytes),
            state=IdempotencyState.IN_PROGRESS.value,
            expires_at=expires_at,
        )
        created = True
        try:
            async with self.session.begin_nested():
                self.session.add(record)
                await self.session.flush()
        except IntegrityError:
            created = False
        if created:
            return record, True
        result = await self.session.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.scope == scope,
                IdempotencyRecord.key_hash == _hash_opaque_token(key),
            )
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            raise UniqueConflict("idempotency record was concurrently removed")
        if existing.request_hash != _hash_request(request_bytes):
            raise UniqueConflict("idempotency key was reused for a different request")
        return existing, False

    async def complete(
        self,
        record_id: int,
        *,
        result_resource_type: str,
        result_public_id: str,
    ) -> None:
        record = await self.session.get(IdempotencyRecord, record_id)
        if record is None:
            raise NotFound("idempotency record was not found")
        record.state = IdempotencyState.COMPLETED.value
        record.result_resource_type = result_resource_type
        record.result_public_id = result_public_id
        await self.session.flush()


_SAFE_AUDIT_KEYS = frozenset(
    {"schema_version", "component_version", "reason_code", "count", "source", "state"}
)


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(
        self,
        *,
        action: str,
        resource_type: str,
        resource_public_id: str | None,
        result: AuditResult,
        trace_id: str,
        actor_account_id: int | None = None,
        safe_metadata: Mapping[str, object] | None = None,
    ) -> AuditEvent:
        metadata = dict(safe_metadata or {})
        unknown = set(metadata) - _SAFE_AUDIT_KEYS
        if unknown:
            raise ValueError("audit metadata contains a non-whitelisted field")
        record = AuditEvent(
            action=action,
            resource_type=resource_type,
            resource_public_id=resource_public_id,
            result=result.value,
            trace_id=trace_id,
            actor_account_id=actor_account_id,
            safe_metadata=metadata,
        )
        self.session.add(record)
        await self.session.flush()
        return record


# Names aligned with the future Backend port vocabulary without importing its
# unfinished module.  Structural compatibility is documented separately.
SqlAlchemyUserRepository = AccountRepository
SqlAlchemySessionStore = AuthSessionStore
SqlAlchemyAssessmentRepository = AssessmentRepository
SqlAlchemyConversationRepository = SupportRepository
SqlAlchemyReviewRepository = ReviewRepository
SqlAlchemyAuditRepository = AuditRepository
SqlAlchemyIdempotencyStore = IdempotencyStore


__all__ = [
    "AccountRepository",
    "AssessmentRepository",
    "AuditRepository",
    "AuthSessionStore",
    "ConsentRepository",
    "IdempotencyStore",
    "ReviewRepository",
    "SchoolMembershipRepository",
    "SqlAlchemyAssessmentRepository",
    "SqlAlchemyAuditRepository",
    "SqlAlchemyConversationRepository",
    "SqlAlchemyIdempotencyStore",
    "SqlAlchemyReviewRepository",
    "SqlAlchemySessionStore",
    "SqlAlchemyUserRepository",
    "SubjectRepository",
    "SupportRepository",
]
