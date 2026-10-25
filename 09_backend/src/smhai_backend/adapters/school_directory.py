"""SQLAlchemy operations for the school-local directory, composed over the shared adapter."""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Any
from uuid import uuid4

from smhai_backend.core.errors import ErrorCode, error


def _database_public_id(value: str, prefix: str) -> str:
    if not value.startswith(f"{prefix}_"):
        raise ValueError(f"unsupported {prefix} reference")
    return value.removeprefix(f"{prefix}_")


class SchoolDirectoryImportRejected(Exception):
    def __init__(self, errors: list[dict[str, object]]) -> None:
        self.errors = errors
        super().__init__("school directory import preflight rejected")


class SchoolDirectoryPersistenceAdapter:
    """Keep directory queries/mutations separate while reusing the tenant guard and UOW."""

    def __init__(self, persistence: Any) -> None:
        self._persistence = persistence

    def __getattr__(self, name: str) -> Any:
        return getattr(self._persistence, name)

    async def _school_directory_audit(
        self,
        uow,
        *,
        actor_account_id: int | None,
        action: str,
        resource_type: str,
        resource_public_id: str | None,
        trace_id: str,
        count: int = 1,
    ) -> None:
        await uow.audit.append(
            action=action,
            resource_type=resource_type,
            resource_public_id=resource_public_id,
            result=self._db_enums.AuditResult.SUCCESS,
            trace_id=trace_id,
            actor_account_id=actor_account_id,
            safe_metadata={"source": "school_directory", "state": "SUCCESS", "count": count},
        )

    async def school_directory_get(self, actor: Any) -> dict[str, Any]:
        """Return only operational directory metadata for the persisted school admin."""

        from sqlalchemy import func

        m = self._db_models
        now = self._utc_now()
        async with self._uow() as uow:
            await self._school_actor_role(uow, actor, "admin", now)
            school = await uow.session.scalar(
                self._select(m.School).where(
                    m.School.id == actor.school_id,
                    m.School.school_ref == actor.school_ref,
                    m.School.status == "ACTIVE",
                    m.School.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                )
            )
            if school is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="school was not found")
            students = (
                self._select(func.count(m.SchoolClassStudent.id))
                .where(
                    m.SchoolClassStudent.class_id == m.SchoolClass.id,
                    m.SchoolClassStudent.school_id == actor.school_id,
                    m.SchoolClassStudent.status == "ACTIVE",
                    m.SchoolClassStudent.revoked_at.is_(None),
                    m.SchoolClassStudent.valid_from <= now,
                    (m.SchoolClassStudent.valid_until.is_(None))
                    | (m.SchoolClassStudent.valid_until >= now),
                )
                .scalar_subquery()
            )
            teachers = (
                self._select(func.count(m.SchoolClassTeacher.id))
                .where(
                    m.SchoolClassTeacher.class_id == m.SchoolClass.id,
                    m.SchoolClassTeacher.school_id == actor.school_id,
                    m.SchoolClassTeacher.status == "ACTIVE",
                    m.SchoolClassTeacher.revoked_at.is_(None),
                    m.SchoolClassTeacher.valid_from <= now,
                    (m.SchoolClassTeacher.valid_until.is_(None))
                    | (m.SchoolClassTeacher.valid_until >= now),
                )
                .scalar_subquery()
            )
            class_rows = (
                await uow.session.execute(
                    self._select(
                        m.SchoolClass.class_ref,
                        m.SchoolClass.display_name,
                        m.SchoolClass.status,
                        students,
                        teachers,
                    )
                    .where(m.SchoolClass.school_id == actor.school_id)
                    .order_by(m.SchoolClass.class_ref)
                )
            ).all()
            member_rows = (
                await uow.session.execute(
                    self._select(
                        m.Account.public_id,
                        m.AccountSchoolMembership.display_name,
                        m.MembershipRole.role_code,
                        m.Account.status,
                        m.SchoolAccountProvision.status,
                    )
                    .join(
                        m.AccountSchoolMembership,
                        m.AccountSchoolMembership.account_id == m.Account.id,
                    )
                    .join(
                        m.MembershipRole,
                        m.MembershipRole.membership_id == m.AccountSchoolMembership.id,
                    )
                    .outerjoin(
                        m.SchoolAccountProvision,
                        (m.SchoolAccountProvision.account_id == m.Account.id)
                        & (m.SchoolAccountProvision.school_id == actor.school_id),
                    )
                    .where(
                        m.AccountSchoolMembership.school_id == actor.school_id,
                        m.AccountSchoolMembership.status == "ACTIVE",
                        m.AccountSchoolMembership.revoked_at.is_(None),
                        m.AccountSchoolMembership.valid_from <= now,
                        (m.AccountSchoolMembership.valid_until.is_(None))
                        | (m.AccountSchoolMembership.valid_until >= now),
                        m.MembershipRole.school_id == actor.school_id,
                        m.MembershipRole.role_code.in_(("student", "teacher")),
                        m.MembershipRole.status == "ACTIVE",
                        m.MembershipRole.revoked_at.is_(None),
                        m.MembershipRole.valid_from <= now,
                        (m.MembershipRole.valid_until.is_(None))
                        | (m.MembershipRole.valid_until >= now),
                    )
                    .order_by(m.MembershipRole.role_code, m.Account.public_id)
                )
            ).all()
            class_refs_by_member: dict[str, set[str]] = {}
            provisioned_student_classes = (
                await uow.session.execute(
                    self._select(m.Account.public_id, m.SchoolClass.class_ref)
                    .join(
                        m.SchoolAccountProvision,
                        m.SchoolAccountProvision.account_id == m.Account.id,
                    )
                    .join(
                        m.SchoolAccountBatch,
                        m.SchoolAccountBatch.id == m.SchoolAccountProvision.batch_id,
                    )
                    .join(m.SchoolClass, m.SchoolClass.id == m.SchoolAccountBatch.class_id)
                    .where(
                        m.SchoolAccountProvision.school_id == actor.school_id,
                        m.SchoolAccountProvision.role_code == "student",
                        m.SchoolAccountProvision.status.in_(
                            ("PENDING_ACTIVATION", "ACTIVE")
                        ),
                        m.SchoolClass.school_id == actor.school_id,
                        m.SchoolClass.status == "ACTIVE",
                    )
                    .order_by(m.Account.public_id, m.SchoolClass.class_ref)
                )
            ).all()
            assigned_student_classes = (
                await uow.session.execute(
                    self._select(m.Account.public_id, m.SchoolClass.class_ref)
                    .join(
                        m.AccountSchoolMembership,
                        m.AccountSchoolMembership.account_id == m.Account.id,
                    )
                    .join(
                        m.MembershipRole,
                        m.MembershipRole.membership_id == m.AccountSchoolMembership.id,
                    )
                    .join(
                        m.SubjectAccessGrant,
                        (m.SubjectAccessGrant.principal_account_id == m.Account.id)
                        & (m.SubjectAccessGrant.school_id == actor.school_id)
                        & (m.SubjectAccessGrant.relationship_type == "SELF"),
                    )
                    .join(
                        m.SchoolClassStudent,
                        m.SchoolClassStudent.subject_id == m.SubjectAccessGrant.subject_id,
                    )
                    .join(m.SchoolClass, m.SchoolClass.id == m.SchoolClassStudent.class_id)
                    .where(
                        m.AccountSchoolMembership.school_id == actor.school_id,
                        m.AccountSchoolMembership.status == "ACTIVE",
                        m.AccountSchoolMembership.revoked_at.is_(None),
                        m.AccountSchoolMembership.valid_from <= now,
                        (m.AccountSchoolMembership.valid_until.is_(None))
                        | (m.AccountSchoolMembership.valid_until >= now),
                        m.MembershipRole.school_id == actor.school_id,
                        m.MembershipRole.role_code == "student",
                        m.MembershipRole.status == "ACTIVE",
                        m.MembershipRole.revoked_at.is_(None),
                        m.MembershipRole.valid_from <= now,
                        (m.MembershipRole.valid_until.is_(None))
                        | (m.MembershipRole.valid_until >= now),
                        m.SubjectAccessGrant.status == "ACTIVE",
                        m.SubjectAccessGrant.revoked_at.is_(None),
                        m.SubjectAccessGrant.valid_from <= now,
                        (m.SubjectAccessGrant.valid_until.is_(None))
                        | (m.SubjectAccessGrant.valid_until >= now),
                        m.SchoolClassStudent.school_id == actor.school_id,
                        m.SchoolClassStudent.status == "ACTIVE",
                        m.SchoolClassStudent.revoked_at.is_(None),
                        m.SchoolClassStudent.valid_from <= now,
                        (m.SchoolClassStudent.valid_until.is_(None))
                        | (m.SchoolClassStudent.valid_until >= now),
                        m.SchoolClass.school_id == actor.school_id,
                        m.SchoolClass.status == "ACTIVE",
                    )
                    .order_by(m.Account.public_id, m.SchoolClass.class_ref)
                )
            ).all()
            assigned_teacher_classes = (
                await uow.session.execute(
                    self._select(m.Account.public_id, m.SchoolClass.class_ref)
                    .join(
                        m.AccountSchoolMembership,
                        m.AccountSchoolMembership.account_id == m.Account.id,
                    )
                    .join(
                        m.MembershipRole,
                        m.MembershipRole.membership_id == m.AccountSchoolMembership.id,
                    )
                    .join(
                        m.SchoolClassTeacher,
                        m.SchoolClassTeacher.membership_role_id == m.MembershipRole.id,
                    )
                    .join(m.SchoolClass, m.SchoolClass.id == m.SchoolClassTeacher.class_id)
                    .where(
                        m.AccountSchoolMembership.school_id == actor.school_id,
                        m.AccountSchoolMembership.status == "ACTIVE",
                        m.AccountSchoolMembership.revoked_at.is_(None),
                        m.AccountSchoolMembership.valid_from <= now,
                        (m.AccountSchoolMembership.valid_until.is_(None))
                        | (m.AccountSchoolMembership.valid_until >= now),
                        m.MembershipRole.school_id == actor.school_id,
                        m.MembershipRole.role_code == "teacher",
                        m.MembershipRole.status == "ACTIVE",
                        m.MembershipRole.revoked_at.is_(None),
                        m.MembershipRole.valid_from <= now,
                        (m.MembershipRole.valid_until.is_(None))
                        | (m.MembershipRole.valid_until >= now),
                        m.SchoolClassTeacher.school_id == actor.school_id,
                        m.SchoolClassTeacher.status == "ACTIVE",
                        m.SchoolClassTeacher.revoked_at.is_(None),
                        m.SchoolClassTeacher.valid_from <= now,
                        (m.SchoolClassTeacher.valid_until.is_(None))
                        | (m.SchoolClassTeacher.valid_until >= now),
                        m.SchoolClass.school_id == actor.school_id,
                        m.SchoolClass.status == "ACTIVE",
                    )
                    .order_by(m.Account.public_id, m.SchoolClass.class_ref)
                )
            ).all()
            for public_id, class_ref in (
                *provisioned_student_classes,
                *assigned_student_classes,
                *assigned_teacher_classes,
            ):
                class_refs_by_member.setdefault(public_id, set()).add(class_ref)
            return {
                "school": {"school_ref": school.school_ref, "display_name": school.display_name},
                "classes": [
                    {
                        "class_ref": row[0],
                        "display_name": row[1],
                        "status": row[2],
                        "active_student_count": int(row[3]),
                        "active_teacher_count": int(row[4]),
                    }
                    for row in class_rows
                ],
                "members": [
                    {
                        "user_id": f"USER_{row[0]}",
                        "display_name": row[1],
                        "role": row[2],
                        "account_status": row[3],
                        "provisioning_status": row[4],
                        "class_refs": sorted(class_refs_by_member.get(row[0], set())),
                    }
                    for row in member_rows
                ],
            }

    async def school_directory_set_school_name(
        self, actor: Any, display_name: str, *, trace_id: str
    ) -> dict[str, Any]:
        now = self._utc_now()
        m = self._db_models
        async with self._uow() as uow:
            account_id, _role_id = await self._school_actor_role(uow, actor, "admin", now)
            school = await uow.session.scalar(
                self._select(m.School)
                .where(
                    m.School.id == actor.school_id,
                    m.School.school_ref == actor.school_ref,
                    m.School.status == "ACTIVE",
                    m.School.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                )
                .with_for_update()
            )
            if school is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="school was not found")
            school.display_name = display_name
            await self._school_directory_audit(
                uow,
                actor_account_id=account_id,
                action="school_directory.rename_school",
                resource_type="school",
                resource_public_id=school.school_ref,
                trace_id=trace_id,
            )
            return {"school_ref": school.school_ref, "display_name": school.display_name}

    async def school_directory_set_class_name(
        self, actor: Any, class_ref: str, display_name: str, *, trace_id: str
    ) -> dict[str, Any]:
        now = self._utc_now()
        m = self._db_models
        async with self._uow() as uow:
            account_id, _role_id = await self._school_actor_role(uow, actor, "admin", now)
            school_class = await uow.session.scalar(
                self._select(m.SchoolClass)
                .where(
                    m.SchoolClass.school_id == actor.school_id,
                    m.SchoolClass.class_ref == class_ref,
                )
                .with_for_update()
            )
            if school_class is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="class was not found")
            school_class.display_name = display_name
            await self._school_directory_audit(
                uow,
                actor_account_id=account_id,
                action="school_directory.rename_class",
                resource_type="school_class",
                resource_public_id=school_class.public_id,
                trace_id=trace_id,
            )
            return {"class_ref": school_class.class_ref, "display_name": school_class.display_name}

    async def school_directory_set_member_name(
        self, actor: Any, user_ref: str, display_name: str, *, trace_id: str
    ) -> dict[str, Any]:
        try:
            public_id = _database_public_id(user_ref, "USER")
        except ValueError:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="member was not found") from None
        now = self._utc_now()
        m = self._db_models
        async with self._uow() as uow:
            actor_account_id, _role_id = await self._school_actor_role(uow, actor, "admin", now)
            membership = await uow.session.scalar(
                self._select(m.AccountSchoolMembership)
                .join(m.Account, m.Account.id == m.AccountSchoolMembership.account_id)
                .join(
                    m.MembershipRole,
                    m.MembershipRole.membership_id == m.AccountSchoolMembership.id,
                )
                .where(
                    m.Account.public_id == public_id,
                    m.AccountSchoolMembership.school_id == actor.school_id,
                    m.AccountSchoolMembership.status == "ACTIVE",
                    m.AccountSchoolMembership.revoked_at.is_(None),
                    m.AccountSchoolMembership.valid_from <= now,
                    (m.AccountSchoolMembership.valid_until.is_(None))
                    | (m.AccountSchoolMembership.valid_until >= now),
                    m.MembershipRole.school_id == actor.school_id,
                    m.MembershipRole.role_code.in_(("student", "teacher")),
                    m.MembershipRole.status == "ACTIVE",
                    m.MembershipRole.revoked_at.is_(None),
                    m.MembershipRole.valid_from <= now,
                    (m.MembershipRole.valid_until.is_(None))
                    | (m.MembershipRole.valid_until >= now),
                )
                .distinct()
                .with_for_update()
            )
            if membership is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="member was not found")
            membership.display_name = display_name
            await self._school_directory_audit(
                uow,
                actor_account_id=actor_account_id,
                action="school_directory.rename_member",
                resource_type="school_membership",
                resource_public_id=membership.public_id,
                trace_id=trace_id,
            )
            return {"user_id": user_ref, "display_name": membership.display_name}

    async def _school_directory_preflight_errors(
        self, uow, actor: Any, class_ref: str | None, rows, *, lock_class: bool
    ) -> list[dict[str, object]]:
        from sqlalchemy import func

        m = self._db_models
        errors: list[dict[str, object]] = []
        if class_ref is not None:
            class_query = self._select(m.SchoolClass.id).where(
                m.SchoolClass.school_id == actor.school_id,
                m.SchoolClass.class_ref == class_ref,
                m.SchoolClass.status == "ACTIVE",
            )
            if lock_class:
                class_query = class_query.with_for_update()
            class_id = await uow.session.scalar(class_query)
            if class_id is None:
                errors.extend({"row_no": row.row_no, "code": "CLASS_UNAVAILABLE"} for row in rows)
        names = [row.login_name.casefold() for row in rows]
        found = set(
            (
                await uow.session.scalars(
                    self._select(func.lower(m.Account.login_name)).where(
                        func.lower(m.Account.login_name).in_(names)
                    )
                )
            ).all()
        )
        for row in rows:
            if row.login_name.casefold() in found:
                errors.append({"row_no": row.row_no, "code": "LOGIN_UNAVAILABLE"})
        return errors

    async def school_directory_preview_accounts(
        self, actor: Any, class_ref: str | None, rows
    ) -> dict[str, Any]:
        now = self._utc_now()
        async with self._uow() as uow:
            await self._school_actor_role(uow, actor, "admin", now)
            errors = await self._school_directory_preflight_errors(
                uow, actor, class_ref, rows, lock_class=False
            )
            return {"valid": not errors, "row_count": len(rows), "errors": errors}

    async def _school_directory_batch_result(self, uow, actor: Any, batch_ref: str):
        m = self._db_models
        batch = await uow.session.scalar(
            self._select(m.SchoolAccountBatch).where(
                m.SchoolAccountBatch.batch_ref == batch_ref,
                m.SchoolAccountBatch.school_id == actor.school_id,
            )
        )
        if batch is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="account batch was not found")
        rows = (
            await uow.session.execute(
                self._select(
                    m.SchoolAccountProvision.row_no,
                    m.Account.public_id,
                    m.AccountSchoolMembership.display_name,
                    m.SchoolAccountProvision.role_code,
                    m.SchoolAccountProvision.status,
                )
                .join(m.Account, m.Account.id == m.SchoolAccountProvision.account_id)
                .join(
                    m.AccountSchoolMembership,
                    m.AccountSchoolMembership.id == m.SchoolAccountProvision.membership_id,
                )
                .where(
                    m.SchoolAccountProvision.batch_id == batch.id,
                    m.SchoolAccountProvision.school_id == actor.school_id,
                )
                .order_by(m.SchoolAccountProvision.row_no)
            )
        ).all()
        return {
            "batch_ref": batch.batch_ref,
            "created_count": len(rows),
            "accounts": [
                {
                    "row_no": row[0],
                    "user_id": f"USER_{row[1]}",
                    "display_name": row[2],
                    "role": row[3],
                    "status": row[4],
                }
                for row in rows
            ],
        }

    async def school_directory_get_batch(self, actor: Any, batch_ref: str) -> dict[str, Any]:
        now = self._utc_now()
        async with self._uow() as uow:
            await self._school_actor_role(uow, actor, "admin", now)
            return await self._school_directory_batch_result(uow, actor, batch_ref)

    async def school_directory_import_accounts(
        self, actor: Any, class_ref: str | None, rows, *, idempotency, trace_id: str
    ) -> dict[str, Any]:
        from pwdlib import PasswordHash

        m = self._db_models
        e = self._db_enums
        at = self._utc_now()
        try:
            async with self._uow() as uow:
                actor_account_id, admin_role_id = await self._school_actor_role(
                    uow, actor, "admin", at
                )
                claim = await self._school_idempotency_begin(uow, idempotency)
                if claim.replayed:
                    if (
                        claim.record.result_resource_type != "school_account_batch"
                        or claim.record.result_public_id is None
                    ):
                        raise error(
                            ErrorCode.WORKFLOW_CONFLICT,
                            detail="idempotency result is unavailable",
                        )
                    return await self._school_directory_batch_result(
                        uow, actor, claim.record.result_public_id
                    )

                errors = await self._school_directory_preflight_errors(
                    uow, actor, class_ref, rows, lock_class=True
                )
                if errors:
                    raise SchoolDirectoryImportRejected(errors)

                class_id = None
                if class_ref is not None:
                    class_id = await uow.session.scalar(
                        self._select(m.SchoolClass.id)
                        .where(
                            m.SchoolClass.school_id == actor.school_id,
                            m.SchoolClass.class_ref == class_ref,
                            m.SchoolClass.status == "ACTIVE",
                        )
                        .with_for_update()
                    )
                    if class_id is None:
                        raise SchoolDirectoryImportRejected(
                            [{"row_no": row.row_no, "code": "CLASS_UNAVAILABLE"} for row in rows]
                        )

                batch_ref = f"BATCH_{uuid4().hex}"
                batch = m.SchoolAccountBatch(
                    batch_ref=batch_ref,
                    school_id=actor.school_id,
                    created_by_membership_role_id=admin_role_id,
                    class_id=int(class_id) if class_id is not None else None,
                    row_count=len(rows),
                )
                uow.session.add(batch)
                await uow.session.flush()
                hasher = PasswordHash.recommended()
                for row in rows:
                    unusable_password = secrets.token_urlsafe(48)
                    account = m.Account(
                        login_name=row.login_name,
                        password_hash=hasher.hash(unusable_password),
                        status=e.AccountStatus.SUSPENDED.value,
                    )
                    uow.session.add(account)
                    await uow.session.flush()
                    membership = m.AccountSchoolMembership(
                        account_id=account.id,
                        school_id=actor.school_id,
                        display_name=row.display_name,
                        status="ACTIVE",
                        valid_from=at,
                    )
                    uow.session.add(membership)
                    await uow.session.flush()
                    membership_role = await uow.memberships.add_role(
                        membership_id=membership.id,
                        school_id=actor.school_id,
                        role_code=row.role,
                        valid_from=at,
                        status="ACTIVE",
                    )
                    if row.role == "student":
                        subject = await uow.subjects.create(
                            subject_ref=f"SUBJ_{uuid4().hex}",
                            school_id=actor.school_id,
                            data_origin=e.DataOrigin.SYNTHETIC,
                        )
                        uow.session.add(
                            m.SubjectAccessGrant(
                                principal_account_id=account.id,
                                subject_id=subject.id,
                                school_id=actor.school_id,
                                relationship_type=e.RelationshipType.SELF.value,
                                status=e.GrantStatus.ACTIVE.value,
                                valid_from=at,
                            )
                        )
                    uow.session.add(
                        m.SchoolAccountProvision(
                            school_id=actor.school_id,
                            batch_id=batch.id,
                            account_id=account.id,
                            membership_id=membership.id,
                            membership_role_id=membership_role.id,
                            row_no=row.row_no,
                            role_code=row.role,
                            status="PENDING_ACTIVATION",
                            activated_at=None,
                        )
                    )
                await uow.session.flush()
                await self._school_idempotency_complete(
                    uow, claim, resource_type="school_account_batch", result_ref=batch.batch_ref
                )
                await self._school_directory_audit(
                    uow,
                    actor_account_id=actor_account_id,
                    action="school_directory.import_accounts",
                    resource_type="school_account_batch",
                    resource_public_id=batch.batch_ref,
                    trace_id=trace_id,
                    count=len(rows),
                )
                return await self._school_directory_batch_result(uow, actor, batch.batch_ref)
        except SchoolDirectoryImportRejected as rejected:
            return {"valid": False, "row_count": len(rows), "errors": rejected.errors}
        except self._integrity_error as exc:
            raise error(
                ErrorCode.WORKFLOW_CONFLICT,
                detail="account import conflicted with another update",
            ) from exc

    async def _school_roster_preflight_errors(
        self, uow, actor: Any, rows, *, lock_classes: bool
    ) -> tuple[list[dict[str, object]], dict[str, Any]]:
        from sqlalchemy import func

        m = self._db_models
        class_refs = sorted({row.class_ref for row in rows})
        class_query = self._select(m.SchoolClass).where(
            m.SchoolClass.school_id == actor.school_id,
            m.SchoolClass.class_ref.in_(class_refs),
            m.SchoolClass.status == "ACTIVE",
        ).order_by(m.SchoolClass.class_ref)
        if lock_classes:
            class_query = class_query.with_for_update()
        classes = list((await uow.session.scalars(class_query)).all())
        classes_by_ref = {school_class.class_ref: school_class for school_class in classes}
        errors: list[dict[str, object]] = []
        login_names: list[str] = []
        for row in rows:
            school_class = classes_by_ref.get(row.class_ref)
            if school_class is None:
                errors.append({"row_no": row.row_no, "code": "CLASS_UNAVAILABLE"})
            elif (
                row.grade_level is not None
                and school_class.grade_level is not None
                and row.grade_level.casefold() != school_class.grade_level.casefold()
            ):
                errors.append({"row_no": row.row_no, "code": "GRADE_LEVEL_MISMATCH"})
            login_names.append(self._roster_login_name(actor.school_ref, row.student_number))

        if login_names:
            found = set(
                (
                    await uow.session.scalars(
                        self._select(func.lower(m.Account.login_name)).where(
                            func.lower(m.Account.login_name).in_(
                                [name.casefold() for name in login_names]
                            )
                        )
                    )
                ).all()
            )
            for row in rows:
                login_name = self._roster_login_name(actor.school_ref, row.student_number)
                if login_name.casefold() in found:
                    errors.append(
                        {"row_no": row.row_no, "code": "STUDENT_NUMBER_UNAVAILABLE"}
                    )
        return errors, classes_by_ref

    @staticmethod
    def _roster_login_name(school_ref: str, student_number: str) -> str:
        from smhai_backend.domains.school_directory.service import roster_login_name

        return roster_login_name(school_ref, student_number)

    async def school_roster_import_preview(
        self, actor: Any, rows, *, source_sha256: str | None = None
    ) -> dict[str, Any]:
        del source_sha256  # A preview is read-only and the digest is not a validation input.
        now = self._utc_now()
        async with self._uow() as uow:
            await self._school_actor_role(uow, actor, "admin", now)
            errors, _classes = await self._school_roster_preflight_errors(
                uow, actor, rows, lock_classes=False
            )
            return {"valid": not errors, "row_count": len(rows), "errors": errors}

    async def _school_roster_import_result(self, uow, actor: Any, run_ref: str):
        m = self._db_models
        run = await uow.session.scalar(
            self._select(m.SchoolRosterImportRun).where(
                m.SchoolRosterImportRun.run_ref == run_ref,
                m.SchoolRosterImportRun.school_id == actor.school_id,
            )
        )
        if run is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="roster import was not found")
        batch_links = (
            await uow.session.execute(
                self._select(
                    m.SchoolRosterImportRunBatch.batch_id,
                    m.SchoolAccountBatch.batch_ref,
                )
                .join(
                    m.SchoolAccountBatch,
                    m.SchoolAccountBatch.id == m.SchoolRosterImportRunBatch.batch_id,
                )
                .where(
                    m.SchoolRosterImportRunBatch.run_id == run.id,
                    m.SchoolRosterImportRunBatch.school_id == actor.school_id,
                )
                .order_by(m.SchoolAccountBatch.batch_ref)
            )
        ).all()
        batch_ids = [record[0] for record in batch_links]
        records = (
            await uow.session.execute(
                self._select(
                    m.SchoolAccountProvision.row_no,
                    m.Account.public_id,
                    m.AccountSchoolMembership.display_name,
                    m.SchoolClass.class_ref,
                    m.SchoolAccountProvision.status,
                )
                .join(m.Account, m.Account.id == m.SchoolAccountProvision.account_id)
                .join(
                    m.AccountSchoolMembership,
                    m.AccountSchoolMembership.id == m.SchoolAccountProvision.membership_id,
                )
                .join(
                    m.SchoolAccountBatch,
                    m.SchoolAccountBatch.id == m.SchoolAccountProvision.batch_id,
                )
                .join(m.SchoolClass, m.SchoolClass.id == m.SchoolAccountBatch.class_id)
                .where(
                    m.SchoolAccountProvision.school_id == actor.school_id,
                    m.SchoolAccountBatch.id.in_(batch_ids),
                )
                .order_by(m.SchoolAccountProvision.row_no)
            )
        ).all()
        return {
            "run_ref": run.run_ref,
            "row_count": run.row_count,
            "created_count": run.created_count,
            "status": run.status,
            "child_batch_refs": [record[1] for record in batch_links],
            "summary": dict(run.summary),
            "accounts": [
                {
                    "row_no": record[0],
                    "user_id": f"USER_{record[1]}",
                    "display_name": record[2],
                    "class_ref": record[3],
                    "status": record[4],
                }
                for record in records
            ],
        }

    async def school_roster_import_get(self, actor: Any, run_ref: str) -> dict[str, Any]:
        now = self._utc_now()
        async with self._uow() as uow:
            await self._school_actor_role(uow, actor, "admin", now)
            return await self._school_roster_import_result(uow, actor, run_ref)

    async def school_roster_import(
        self,
        actor: Any,
        rows,
        *,
        source_sha256: str | None,
        idempotency,
        trace_id: str,
    ) -> dict[str, Any]:
        from pwdlib import PasswordHash

        m = self._db_models
        e = self._db_enums
        at = self._utc_now()
        try:
            async with self._uow() as uow:
                actor_account_id, admin_role_id = await self._school_actor_role(
                    uow, actor, "admin", at
                )
                claim = await self._school_idempotency_begin(uow, idempotency)
                if claim.replayed:
                    if (
                        claim.record.result_resource_type != "school_roster_import_run"
                        or claim.record.result_public_id is None
                    ):
                        raise error(
                            ErrorCode.WORKFLOW_CONFLICT,
                            detail="roster import result is unavailable",
                        )
                    return await self._school_roster_import_result(
                        uow, actor, claim.record.result_public_id
                    )

                errors, classes_by_ref = await self._school_roster_preflight_errors(
                    uow, actor, rows, lock_classes=True
                )
                if errors:
                    raise SchoolDirectoryImportRejected(errors)

                from collections import defaultdict

                grouped: dict[str, list[Any]] = defaultdict(list)
                for row in rows:
                    grouped[row.class_ref].append(row)

                run_ref = f"ROSTER_{uuid4().hex}"
                child_batches: list[tuple[Any, list[Any], str]] = []
                for class_ref in sorted(grouped):
                    school_class = classes_by_ref[class_ref]
                    class_rows = grouped[class_ref]
                    for offset in range(0, len(class_rows), 100):
                        batch_rows = class_rows[offset : offset + 100]
                        batch_ref = f"BATCH_{uuid4().hex}"
                        batch = m.SchoolAccountBatch(
                            batch_ref=batch_ref,
                            school_id=actor.school_id,
                            created_by_membership_role_id=admin_role_id,
                            class_id=school_class.id,
                            row_count=len(batch_rows),
                        )
                        uow.session.add(batch)
                        await uow.session.flush()
                        child_batches.append((batch, batch_rows, class_ref))

                hasher = PasswordHash.recommended()
                for batch, batch_rows, _class_ref in child_batches:
                    for row in batch_rows:
                        account = m.Account(
                            login_name=self._roster_login_name(
                                actor.school_ref, row.student_number
                            ),
                            password_hash=hasher.hash(secrets.token_urlsafe(48)),
                            status=e.AccountStatus.SUSPENDED.value,
                        )
                        uow.session.add(account)
                        await uow.session.flush()
                        membership = m.AccountSchoolMembership(
                            account_id=account.id,
                            school_id=actor.school_id,
                            display_name=row.display_name,
                            status="ACTIVE",
                            valid_from=at,
                        )
                        uow.session.add(membership)
                        await uow.session.flush()
                        membership_role = await uow.memberships.add_role(
                            membership_id=membership.id,
                            school_id=actor.school_id,
                            role_code="student",
                            valid_from=at,
                            status="ACTIVE",
                        )
                        subject = await uow.subjects.create(
                            subject_ref=f"SUBJ_{uuid4().hex}",
                            school_id=actor.school_id,
                            data_origin=e.DataOrigin.SYNTHETIC,
                        )
                        uow.session.add(
                            m.SubjectAccessGrant(
                                principal_account_id=account.id,
                                subject_id=subject.id,
                                school_id=actor.school_id,
                                relationship_type=e.RelationshipType.SELF.value,
                                status=e.GrantStatus.ACTIVE.value,
                                valid_from=at,
                            )
                        )
                        uow.session.add(
                            m.SchoolAccountProvision(
                                school_id=actor.school_id,
                                batch_id=batch.id,
                                account_id=account.id,
                                membership_id=membership.id,
                                membership_role_id=membership_role.id,
                                row_no=row.row_no,
                                role_code="student",
                                status="PENDING_ACTIVATION",
                                activated_at=None,
                            )
                        )
                await uow.session.flush()

                summary = {
                    "class_count": len(grouped),
                    "batch_count": len(child_batches),
                    "student_count": len(rows),
                }
                run = m.SchoolRosterImportRun(
                    run_ref=run_ref,
                    school_id=actor.school_id,
                    created_by_membership_role_id=admin_role_id,
                    idempotency_key_hash=hashlib.sha256(
                        idempotency[0].encode("utf-8")
                    ).digest(),
                    request_fingerprint=bytes.fromhex(idempotency[1]),
                    source_sha256=bytes.fromhex(source_sha256) if source_sha256 else None,
                    row_count=len(rows),
                    created_count=len(rows),
                    status="COMPLETED",
                    summary=summary,
                    trace_id=trace_id,
                )
                uow.session.add(run)
                await uow.session.flush()
                for batch, batch_rows, class_ref in child_batches:
                    uow.session.add(
                        m.SchoolRosterImportRunBatch(
                            run_id=run.id,
                            school_id=actor.school_id,
                            batch_id=batch.id,
                            class_id=classes_by_ref[class_ref].id,
                            row_count=len(batch_rows),
                        )
                    )
                await uow.session.flush()
                await self._school_idempotency_complete(
                    uow,
                    claim,
                    resource_type="school_roster_import_run",
                    result_ref=run_ref,
                )
                await self._school_directory_audit(
                    uow,
                    actor_account_id=actor_account_id,
                    action="school_directory.import_roster",
                    resource_type="school_roster_import_run",
                    resource_public_id=run_ref,
                    trace_id=trace_id,
                    count=len(rows),
                )
                return await self._school_roster_import_result(uow, actor, run_ref)
        except SchoolDirectoryImportRejected as rejected:
            return {"valid": False, "row_count": len(rows), "errors": rejected.errors}
        except self._integrity_error as exc:
            raise error(
                ErrorCode.WORKFLOW_CONFLICT,
                detail="roster import conflicted with another update",
            ) from exc

    async def _revoke_account_sessions(
        self, uow, account_id: int, at, *, reason: str = "INITIAL_CREDENTIAL_COMPLETED"
    ) -> None:
        m = self._db_models
        sessions = list(
            (
                await uow.session.scalars(
                    self._select(m.AuthSession)
                    .where(
                        m.AuthSession.account_id == account_id,
                        m.AuthSession.revoked_at.is_(None),
                    )
                    .order_by(m.AuthSession.id)
                    .with_for_update()
                )
            ).all()
        )
        for session in sessions:
            session.revoked_at = at
            session.revocation_reason = reason

    @staticmethod
    def _initial_credential_conflict():
        return error(
            ErrorCode.WORKFLOW_CONFLICT,
            detail="one or more accounts cannot receive an initial credential",
        )

    async def school_directory_issue_initial_credentials(
        self,
        actor: Any,
        user_refs: list[str],
        *,
        ttl_seconds: int,
        trace_id: str,
    ) -> dict[str, Any]:
        m = self._db_models
        e = self._db_enums
        at = self._utc_now()
        if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) or ttl_seconds <= 0:
            raise error(ErrorCode.VALIDATION_FAILED, detail="credential expiry is invalid")
        try:
            public_ids = [_database_public_id(ref, "USER") for ref in user_refs]
        except (TypeError, ValueError):
            raise self._initial_credential_conflict() from None
        if not user_refs or len(user_refs) > 200 or len(set(public_ids)) != len(public_ids):
            raise error(ErrorCode.VALIDATION_FAILED, detail="invalid credential targets")

        async with self._uow() as uow:
            actor_account_id, admin_role_id = await self._school_actor_role(
                uow, actor, "admin", at
            )
            accounts = list(
                (
                    await uow.session.scalars(
                        self._select(m.Account)
                        .where(m.Account.public_id.in_(public_ids))
                        .order_by(m.Account.id)
                        .with_for_update()
                    )
                ).all()
            )
            accounts_by_public_id = {account.public_id: account for account in accounts}
            if set(accounts_by_public_id) != set(public_ids):
                raise self._initial_credential_conflict()
            account_ids = [account.id for account in accounts]

            provisions = list(
                (
                    await uow.session.scalars(
                        self._select(m.SchoolAccountProvision)
                        .where(
                            m.SchoolAccountProvision.school_id == actor.school_id,
                            m.SchoolAccountProvision.account_id.in_(account_ids),
                        )
                        .order_by(m.SchoolAccountProvision.account_id)
                        .with_for_update()
                    )
                ).all()
            )
            provision_by_account = {provision.account_id: provision for provision in provisions}
            if set(provision_by_account) != set(account_ids):
                raise self._initial_credential_conflict()

            memberships = list(
                (
                    await uow.session.scalars(
                        self._select(m.AccountSchoolMembership)
                        .where(m.AccountSchoolMembership.account_id.in_(account_ids))
                        .order_by(
                            m.AccountSchoolMembership.account_id,
                            m.AccountSchoolMembership.school_id,
                        )
                        .with_for_update()
                    )
                ).all()
            )
            roles = list(
                (
                    await uow.session.scalars(
                        self._select(m.MembershipRole)
                        .where(
                            m.MembershipRole.membership_id.in_(
                                [membership.id for membership in memberships]
                            )
                        )
                        .order_by(m.MembershipRole.membership_id, m.MembershipRole.id)
                        .with_for_update()
                    )
                ).all()
            )
            memberships_by_account: dict[int, list[Any]] = {}
            roles_by_membership: dict[int, list[Any]] = {}
            for membership in memberships:
                memberships_by_account.setdefault(membership.account_id, []).append(membership)
            for role in roles:
                roles_by_membership.setdefault(role.membership_id, []).append(role)

            batches = list(
                (
                    await uow.session.scalars(
                        self._select(m.SchoolAccountBatch)
                        .where(
                            m.SchoolAccountBatch.id.in_(
                                [provision.batch_id for provision in provisions]
                            ),
                            m.SchoolAccountBatch.school_id == actor.school_id,
                        )
                        .order_by(m.SchoolAccountBatch.id)
                        .with_for_update()
                    )
                ).all()
            )
            batches_by_id = {batch.id: batch for batch in batches}
            school_data_origin = await uow.session.scalar(
                self._select(m.School.data_origin).where(m.School.id == actor.school_id)
            )
            is_synthetic_school = school_data_origin == e.DataOrigin.SYNTHETIC.value
            prior_initial_credentials = set(
                (
                    await uow.session.scalars(
                        self._select(m.SchoolAccountCredential.account_id)
                        .where(
                            m.SchoolAccountCredential.school_id == actor.school_id,
                            m.SchoolAccountCredential.account_id.in_(account_ids),
                            m.SchoolAccountCredential.purpose == "INITIAL_ACTIVATION",
                        )
                        .with_for_update()
                    )
                ).all()
            )
            class_ids = sorted({batch.class_id for batch in batches if batch.class_id is not None})
            school_classes = list(
                (
                    await uow.session.scalars(
                        self._select(m.SchoolClass)
                        .where(
                            m.SchoolClass.id.in_(class_ids),
                            m.SchoolClass.school_id == actor.school_id,
                            m.SchoolClass.status == "ACTIVE",
                        )
                        .order_by(m.SchoolClass.id)
                        .with_for_update()
                    )
                ).all()
            ) if class_ids else []
            classes_by_id = {school_class.id: school_class for school_class in school_classes}

            ordered_accounts = [accounts_by_public_id[public_id] for public_id in public_ids]
            result_rows: list[dict[str, Any]] = []
            for account in ordered_accounts:
                provision = provision_by_account[account.id]
                account_memberships = memberships_by_account.get(account.id, [])
                if (
                    len(account_memberships) != 1
                    or account_memberships[0].id != provision.membership_id
                    or account_memberships[0].school_id != actor.school_id
                    or account_memberships[0].status != "ACTIVE"
                    or account_memberships[0].revoked_at is not None
                    or account_memberships[0].valid_from > at
                    or (
                        account_memberships[0].valid_until is not None
                        and account_memberships[0].valid_until < at
                    )
                ):
                    raise self._initial_credential_conflict()
                membership = account_memberships[0]
                membership_roles = roles_by_membership.get(membership.id, [])
                role = next(
                    (
                        row
                        for row in membership_roles
                        if row.id == provision.membership_role_id
                        and row.school_id == actor.school_id
                        and row.role_code == provision.role_code
                        and row.status == "ACTIVE"
                        and row.revoked_at is None
                        and row.valid_from <= at
                        and (row.valid_until is None or row.valid_until >= at)
                    ),
                    None,
                )
                if (
                    role is None
                    or len(membership_roles) != 1
                    or provision.role_code not in {"student", "teacher"}
                ):
                    raise self._initial_credential_conflict()
                batch = batches_by_id.get(provision.batch_id)
                if batch is None:
                    raise self._initial_credential_conflict()
                school_class = (
                    classes_by_id.get(batch.class_id) if batch.class_id is not None else None
                )
                if batch.class_id is not None and school_class is None:
                    raise self._initial_credential_conflict()

                pending = (
                    provision.status == "PENDING_ACTIVATION"
                    and account.status == e.AccountStatus.SUSPENDED.value
                    and not account.must_change_password
                )
                reissue = (
                    provision.status == "ACTIVE"
                    and account.status == e.AccountStatus.ACTIVE.value
                    and account.must_change_password
                )
                synthetic_uninitialized = (
                    is_synthetic_school
                    and provision.status == "ACTIVE"
                    and account.status == e.AccountStatus.ACTIVE.value
                    and not account.must_change_password
                    and account.id not in prior_initial_credentials
                )
                if account.password_changed_at is not None or not (
                    pending or reissue or synthetic_uninitialized
                ):
                    raise self._initial_credential_conflict()
                result_rows.append(
                    {
                        "account": account,
                        "provision": provision,
                        "membership": membership,
                        "role": role,
                        "batch": batch,
                        "school_class": school_class,
                        "pending": pending,
                    }
                )

            expires_at = at + timedelta(seconds=ttl_seconds)
            response_credentials: list[dict[str, Any]] = []
            for row in result_rows:
                account = row["account"]
                provision = row["provision"]
                membership = row["membership"]
                role = row["role"]
                batch = row["batch"]
                school_class = row["school_class"]
                if row["pending"]:
                    account.status = e.AccountStatus.ACTIVE.value
                    account.must_change_password = True
                    provision.status = "ACTIVE"
                    provision.activated_at = at
                    if school_class is not None:
                        if provision.role_code == "student":
                            subject_ids = list(
                                (
                                    await uow.session.scalars(
                                        self._select(m.Subject.id)
                                        .join(
                                            m.SubjectAccessGrant,
                                            m.SubjectAccessGrant.subject_id == m.Subject.id,
                                        )
                                        .where(
                                            m.SubjectAccessGrant.principal_account_id == account.id,
                                            m.SubjectAccessGrant.school_id == actor.school_id,
                                            m.SubjectAccessGrant.relationship_type
                                            == e.RelationshipType.SELF.value,
                                m.SubjectAccessGrant.status
                                == e.GrantStatus.ACTIVE.value,
                                            m.SubjectAccessGrant.revoked_at.is_(None),
                                            m.SubjectAccessGrant.valid_from <= at,
                                            (m.SubjectAccessGrant.valid_until.is_(None))
                                            | (m.SubjectAccessGrant.valid_until >= at),
                                            m.Subject.school_id == actor.school_id,
                                            m.Subject.status == e.SubjectStatus.ACTIVE.value,
                                            m.Subject.data_origin == e.DataOrigin.SYNTHETIC.value,
                                        )
                                        .with_for_update()
                                    )
                                ).all()
                            )
                            if len(subject_ids) != 1:
                                raise self._initial_credential_conflict()
                            await uow.school_operations.add_student_subject_to_class(
                                school_id=actor.school_id,
                                class_id=school_class.id,
                                subject_id=int(subject_ids[0]),
                                admin_membership_role_id=admin_role_id,
                                at=at,
                            )
                        else:
                            await uow.school_operations.add_teacher_role_to_class(
                                school_id=actor.school_id,
                                class_id=school_class.id,
                                teacher_membership_role_id=role.id,
                                admin_membership_role_id=admin_role_id,
                                at=at,
                            )
                else:
                    # Reissued and recovered synthetic accounts must establish
                    # a fresh password before they can authenticate again.
                    account.must_change_password = True

                old_credentials = list(
                    (
                        await uow.session.scalars(
                            self._select(m.SchoolAccountCredential)
                            .where(
                                m.SchoolAccountCredential.account_id == account.id,
                                m.SchoolAccountCredential.school_id == actor.school_id,
                                m.SchoolAccountCredential.purpose == "INITIAL_ACTIVATION",
                                m.SchoolAccountCredential.status == "ISSUED",
                            )
                            .order_by(m.SchoolAccountCredential.id)
                            .with_for_update()
                        )
                    ).all()
                )
                for old in old_credentials:
                    old.status = "REVOKED"
                    old.revoked_at = at

                raw_credential = secrets.token_urlsafe(32)
                credential_ref = f"CRED_{uuid4().hex}"
                credential = m.SchoolAccountCredential(
                    credential_ref=credential_ref,
                    account_id=account.id,
                    school_id=actor.school_id,
                    issued_by_membership_role_id=admin_role_id,
                    purpose="INITIAL_ACTIVATION",
                    resource_ref=provision.public_id,
                    token_hash=hashlib.sha256(raw_credential.encode("utf-8")).digest(),
                    status="ISSUED",
                    delivery_channel="MANUAL",
                    expires_at=expires_at,
                    consumed_at=None,
                    revoked_at=None,
                    trace_id=trace_id,
                )
                uow.session.add(credential)
                await uow.session.flush()
                await self._revoke_account_sessions(
                    uow, account.id, at, reason="INITIAL_CREDENTIAL_ISSUED"
                )
                await self._school_directory_audit(
                    uow,
                    actor_account_id=actor_account_id,
                    action="school_directory.issue_initial_credential",
                    resource_type="school_account_credential",
                    resource_public_id=credential.public_id,
                    trace_id=trace_id,
                    count=1,
                )
                response_credentials.append(
                    {
                        "user_id": f"USER_{account.public_id}",
                        "login_name": account.login_name,
                        "display_name": membership.display_name,
                        "class_ref": school_class.class_ref if school_class is not None else None,
                        "credential": raw_credential,
                        "expires_at": expires_at,
                    }
                )
            await uow.session.flush()
            return {
                "credentials": response_credentials,
                "delivery_status": "MANUAL_HANDOFF_REQUIRED",
            }

    async def school_directory_complete_initial_credential(
        self,
        *,
        username: str,
        school_ref: str,
        token_hash: bytes,
        new_password: str,
        trace_id: str,
    ) -> dict[str, str]:
        from pwdlib import PasswordHash
        from sqlalchemy import func

        from smhai_backend.core.errors import ErrorCode

        invalid = error(
            ErrorCode.AUTH_INVALID_CREDENTIALS,
            detail="initial credential is invalid or expired",
        )
        if (
            not isinstance(username, str)
            or not username.strip()
            or not isinstance(school_ref, str)
            or not school_ref.strip()
            or not isinstance(token_hash, bytes)
            or len(token_hash) != 32
        ):
            raise invalid
        m = self._db_models
        e = self._db_enums
        at = self._utc_now()
        normalized_username = username.strip().casefold()
        async with self._uow() as uow:
            identity = await uow.session.execute(
                self._select(m.Account.id, m.School.id)
                .join(
                    m.AccountSchoolMembership,
                    m.AccountSchoolMembership.account_id == m.Account.id,
                )
                .join(m.School, m.School.id == m.AccountSchoolMembership.school_id)
                .where(
                    func.lower(m.Account.login_name) == normalized_username,
                    m.School.school_ref == school_ref.strip(),
                    m.School.status == "ACTIVE",
                    m.School.data_origin == e.DataOrigin.SYNTHETIC.value,
                    m.AccountSchoolMembership.status == "ACTIVE",
                    m.AccountSchoolMembership.revoked_at.is_(None),
                    m.AccountSchoolMembership.valid_from <= at,
                    (m.AccountSchoolMembership.valid_until.is_(None))
                    | (m.AccountSchoolMembership.valid_until >= at),
                )
                .limit(1)
            )
            identity_row = identity.first()
            if identity_row is None:
                raise invalid
            account_id, school_id = identity_row
            account = await uow.session.scalar(
                self._select(m.Account)
                .where(m.Account.id == account_id)
                .with_for_update()
            )
            if (
                account is None
                or account.status != e.AccountStatus.ACTIVE.value
                or not account.must_change_password
                or account.password_changed_at is not None
            ):
                raise invalid

            memberships = list(
                (
                    await uow.session.scalars(
                        self._select(m.AccountSchoolMembership)
                        .where(
                            m.AccountSchoolMembership.account_id == account.id,
                            m.AccountSchoolMembership.school_id == school_id,
                        )
                        .order_by(m.AccountSchoolMembership.id)
                        .with_for_update()
                    )
                ).all()
            )
            if len(memberships) != 1:
                raise invalid
            membership = memberships[0]
            if (
                membership.status != "ACTIVE"
                or membership.revoked_at is not None
                or membership.valid_from > at
                or (membership.valid_until is not None and membership.valid_until < at)
            ):
                raise invalid
            provisions = list(
                (
                    await uow.session.scalars(
                        self._select(m.SchoolAccountProvision)
                        .where(
                            m.SchoolAccountProvision.account_id == account.id,
                            m.SchoolAccountProvision.school_id == school_id,
                        )
                        .with_for_update()
                    )
                ).all()
            )
            if len(provisions) != 1:
                raise invalid
            provision = provisions[0]
            if (
                provision.status != "ACTIVE"
                or provision.membership_id != membership.id
                or provision.role_code not in {"student", "teacher"}
            ):
                raise invalid
            membership_roles = list(
                (
                    await uow.session.scalars(
                        self._select(m.MembershipRole)
                        .where(m.MembershipRole.membership_id == membership.id)
                        .order_by(m.MembershipRole.id)
                        .with_for_update()
                    )
                ).all()
            )
            role = next(
                (
                    item
                    for item in membership_roles
                    if item.id == provision.membership_role_id
                    and item.school_id == school_id
                    and item.role_code == provision.role_code
                    and item.status == "ACTIVE"
                    and item.revoked_at is None
                    and item.valid_from <= at
                    and (item.valid_until is None or item.valid_until >= at)
                ),
                None,
            )
            if role is None or len(membership_roles) != 1:
                raise invalid

            credential = await uow.session.scalar(
                self._select(m.SchoolAccountCredential)
                .where(
                    m.SchoolAccountCredential.account_id == account.id,
                    m.SchoolAccountCredential.school_id == school_id,
                    m.SchoolAccountCredential.token_hash == token_hash,
                    m.SchoolAccountCredential.purpose == "INITIAL_ACTIVATION",
                )
                .with_for_update()
            )
            if (
                credential is None
                or credential.status != "ISSUED"
                or credential.revoked_at is not None
                or credential.consumed_at is not None
                or credential.expires_at <= at
            ):
                raise invalid

            account.password_hash = PasswordHash.recommended().hash(new_password)
            account.status = e.AccountStatus.ACTIVE.value
            account.must_change_password = False
            account.password_changed_at = at
            account.failed_login_count = 0
            account.locked_until = None
            credential.status = "CONSUMED"
            credential.consumed_at = at
            await self._revoke_account_sessions(uow, account.id, at)
            await uow.session.flush()
            await self._school_directory_audit(
                uow,
                actor_account_id=None,
                action="school_directory.complete_initial_credential",
                resource_type="school_account_credential",
                resource_public_id=credential.public_id,
                trace_id=trace_id,
                count=1,
            )
            return {"status": "PASSWORD_SET"}

    async def school_directory_activate_account(
        self, actor: Any, user_ref: str, new_password: str, *, trace_id: str
    ) -> dict[str, Any]:
        del actor, user_ref, new_password, trace_id
        raise error(
            ErrorCode.WORKFLOW_CONFLICT,
            detail="initial credentials must be issued before the account can set its password",
        )
