"""SQLAlchemy operations for the school-local directory, composed over the shared adapter."""

from __future__ import annotations

import secrets
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
        actor_account_id: int,
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
                self._select(m.School).where(
                    m.School.id == actor.school_id,
                    m.School.school_ref == actor.school_ref,
                    m.School.status == "ACTIVE",
                    m.School.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                ).with_for_update()
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
                errors.extend(
                    {"row_no": row.row_no, "code": "CLASS_UNAVAILABLE"} for row in rows
                )
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
                    if claim.record.result_public_id is None:
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
                            [
                                {"row_no": row.row_no, "code": "CLASS_UNAVAILABLE"}
                                for row in rows
                            ]
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

    async def school_directory_activate_account(
        self, actor: Any, user_ref: str, new_password: str, *, trace_id: str
    ) -> dict[str, Any]:
        from pwdlib import PasswordHash

        try:
            public_id = _database_public_id(user_ref, "USER")
        except ValueError:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="account was not found") from None
        at = self._utc_now()
        m = self._db_models
        async with self._uow() as uow:
            actor_account_id, admin_role_id = await self._school_actor_role(uow, actor, "admin", at)
            account = await uow.session.scalar(
                self._select(m.Account)
                .where(m.Account.public_id == public_id)
                .with_for_update()
            )
            if account is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="account was not found")
            provision = await uow.session.scalar(
                self._select(m.SchoolAccountProvision)
                .where(
                    m.SchoolAccountProvision.account_id == account.id,
                    m.SchoolAccountProvision.school_id == actor.school_id,
                )
                .with_for_update()
            )
            if provision is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="pending account was not found")
            if (
                provision.status != "PENDING_ACTIVATION"
                or account.status != self._db_enums.AccountStatus.SUSPENDED.value
            ):
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="account cannot be activated")
            memberships = list(
                (
                    await uow.session.scalars(
                        self._select(m.AccountSchoolMembership)
                        .where(m.AccountSchoolMembership.account_id == account.id)
                        .with_for_update()
                    )
                ).all()
            )
            if (
                len(memberships) != 1
                or memberships[0].id != provision.membership_id
                or memberships[0].school_id != actor.school_id
                or memberships[0].status != "ACTIVE"
                or memberships[0].revoked_at is not None
                or memberships[0].valid_from > at
                or (memberships[0].valid_until is not None and memberships[0].valid_until < at)
            ):
                raise error(ErrorCode.FORBIDDEN, detail="account activation scope is invalid")
            membership_role = await uow.session.scalar(
                self._select(m.MembershipRole)
                .where(
                    m.MembershipRole.id == provision.membership_role_id,
                    m.MembershipRole.membership_id == provision.membership_id,
                    m.MembershipRole.school_id == actor.school_id,
                    m.MembershipRole.role_code == provision.role_code,
                    m.MembershipRole.status == "ACTIVE",
                    m.MembershipRole.revoked_at.is_(None),
                    m.MembershipRole.valid_from <= at,
                    (m.MembershipRole.valid_until.is_(None))
                    | (m.MembershipRole.valid_until >= at),
                )
                .with_for_update()
            )
            if membership_role is None or provision.role_code not in {"student", "teacher"}:
                raise error(ErrorCode.FORBIDDEN, detail="account activation scope is invalid")
            batch = await uow.session.scalar(
                self._select(m.SchoolAccountBatch)
                .where(
                    m.SchoolAccountBatch.id == provision.batch_id,
                    m.SchoolAccountBatch.school_id == actor.school_id,
                )
                .with_for_update()
            )
            if batch is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="account batch was not found")
            school_class = None
            if batch.class_id is not None:
                school_class = await uow.session.scalar(
                    self._select(m.SchoolClass)
                    .where(
                        m.SchoolClass.id == batch.class_id,
                        m.SchoolClass.school_id == actor.school_id,
                        m.SchoolClass.status == "ACTIVE",
                    )
                    .with_for_update()
                )
                if school_class is None:
                    raise error(ErrorCode.WORKFLOW_CONFLICT, detail="account class is unavailable")

            account.password_hash = PasswordHash.recommended().hash(new_password)
            account.status = self._db_enums.AccountStatus.ACTIVE.value
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
                                    == self._db_enums.RelationshipType.SELF.value,
                                    m.SubjectAccessGrant.status == "ACTIVE",
                                    m.SubjectAccessGrant.revoked_at.is_(None),
                                    m.SubjectAccessGrant.valid_from <= at,
                                    (m.SubjectAccessGrant.valid_until.is_(None))
                                    | (m.SubjectAccessGrant.valid_until >= at),
                                    m.Subject.school_id == actor.school_id,
                                    m.Subject.status == self._db_enums.SubjectStatus.ACTIVE.value,
                                    m.Subject.data_origin
                                    == self._db_enums.DataOrigin.SYNTHETIC.value,
                                )
                                .with_for_update()
                            )
                        ).all()
                    )
                    if len(subject_ids) != 1:
                        raise error(ErrorCode.FORBIDDEN, detail="student subject scope is invalid")
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
                        teacher_membership_role_id=membership_role.id,
                        admin_membership_role_id=admin_role_id,
                        at=at,
                    )
            await uow.session.flush()
            await self._school_directory_audit(
                uow,
                actor_account_id=actor_account_id,
                action="school_directory.activate_account",
                resource_type="school_account",
                resource_public_id=account.public_id,
                trace_id=trace_id,
            )
            return {"user_id": user_ref, "status": "ACTIVE"}

