"""SQL operations for scoped school account invitations and recovery tickets."""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Any
from uuid import uuid4

from pwdlib import PasswordHash

from smhai_backend.adapters.school_directory import SchoolDirectoryPersistenceAdapter
from smhai_backend.core.errors import ErrorCode, error

STAFF_RECOVERY_RESOURCE_PREFIX = "STAFF_RECOVERY_"


class SchoolAccountLifecyclePersistenceAdapter:
    """Separate lifecycle transactions from the general directory adapter."""

    @staticmethod
    def _generic_credential_error():
        return error(
            ErrorCode.AUTH_INVALID_CREDENTIALS,
            detail="credential is invalid or expired",
        )

    def __init__(self, persistence: Any) -> None:
        self._directory = SchoolDirectoryPersistenceAdapter(persistence)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._directory, name)

    async def _audit(
        self,
        uow: Any,
        *,
        actor_account_id: int | None,
        action: str,
        resource_type: str,
        resource_ref: str | None,
        trace_id: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        await uow.audit.append(
            action=action,
            resource_type=resource_type,
            resource_public_id=resource_ref,
            result=self._db_enums.AuditResult.SUCCESS,
            trace_id=trace_id,
            actor_account_id=actor_account_id,
            safe_metadata={
                "source": "school_account_lifecycle",
                "state": "SUCCESS",
                **(metadata or {}),
            },
        )

    async def _revoke_sessions(self, uow: Any, account_id: int, now: Any, reason: str) -> None:
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
            session.revoked_at = now
            session.revocation_reason = reason

    @staticmethod
    def _token() -> tuple[str, bytes]:
        value = secrets.token_urlsafe(32)
        return value, hashlib.sha256(value.encode("utf-8")).digest()

    @staticmethod
    def _login_name(school_ref: str, employee_ref: str) -> str:
        school_hash = hashlib.sha256(school_ref.casefold().encode("utf-8")).hexdigest()[:12]
        employee_hash = hashlib.sha256(employee_ref.casefold().encode("utf-8")).hexdigest()[:32]
        return f"STAFF_{school_hash}_{employee_hash}"

    @staticmethod
    def _public_id(ref: str, prefix: str) -> str:
        marker = f"{prefix}_"
        if not isinstance(ref, str) or not ref.startswith(marker):
            raise ValueError
        return ref.removeprefix(marker)

    async def account_summary(self, actor: Any) -> dict[str, int]:
        from sqlalchemy import func, or_

        m = self._db_models
        now = self._utc_now()
        async with self._uow() as uow:
            await self._school_actor_role(uow, actor, "admin", now)
            total = await uow.session.scalar(
                self._select(func.count(func.distinct(m.Account.id)))
                .join(
                    m.AccountSchoolMembership, m.AccountSchoolMembership.account_id == m.Account.id
                )
                .where(m.AccountSchoolMembership.school_id == actor.school_id)
            )
            active = await uow.session.scalar(
                self._select(func.count(func.distinct(m.Account.id)))
                .join(
                    m.AccountSchoolMembership, m.AccountSchoolMembership.account_id == m.Account.id
                )
                .where(
                    m.AccountSchoolMembership.school_id == actor.school_id,
                    m.Account.status == self._db_enums.AccountStatus.ACTIVE.value,
                    m.Account.must_change_password.is_(False),
                    or_(m.Account.locked_until.is_(None), m.Account.locked_until <= now),
                )
            )
            pending = await uow.session.scalar(
                self._select(func.count(func.distinct(m.Account.id)))
                .join(
                    m.AccountSchoolMembership,
                    m.AccountSchoolMembership.account_id == m.Account.id,
                )
                .outerjoin(
                    m.SchoolAccountProvision,
                    (m.SchoolAccountProvision.account_id == m.Account.id)
                    & (m.SchoolAccountProvision.school_id == actor.school_id),
                )
                .where(
                    m.AccountSchoolMembership.school_id == actor.school_id,
                    or_(
                        m.Account.must_change_password.is_(True),
                        m.SchoolAccountProvision.status == "PENDING_ACTIVATION",
                    ),
                )
            )
            suspended = await uow.session.scalar(
                self._select(func.count(func.distinct(m.Account.id)))
                .join(
                    m.AccountSchoolMembership, m.AccountSchoolMembership.account_id == m.Account.id
                )
                .where(
                    m.AccountSchoolMembership.school_id == actor.school_id,
                    or_(
                        m.Account.status.in_(
                            (
                                self._db_enums.AccountStatus.SUSPENDED.value,
                                self._db_enums.AccountStatus.DISABLED.value,
                            )
                        ),
                        m.Account.locked_until > now,
                    ),
                )
            )
            classes = await uow.session.scalar(
                self._select(func.count(m.SchoolClass.id)).where(
                    m.SchoolClass.school_id == actor.school_id,
                    m.SchoolClass.status == "ACTIVE",
                )
            )
            invitations_issued = await uow.session.scalar(
                self._select(func.count(m.SchoolStaffInvitation.id)).where(
                    m.SchoolStaffInvitation.school_id == actor.school_id,
                    m.SchoolStaffInvitation.status == "ISSUED",
                    m.SchoolStaffInvitation.expires_at > now,
                )
            )
            invitations_accepted = await uow.session.scalar(
                self._select(func.count(m.SchoolStaffInvitation.id)).where(
                    m.SchoolStaffInvitation.school_id == actor.school_id,
                    m.SchoolStaffInvitation.status == "ACCEPTED",
                )
            )
            invitations_expired = await uow.session.scalar(
                self._select(func.count(m.SchoolStaffInvitation.id)).where(
                    m.SchoolStaffInvitation.school_id == actor.school_id,
                    or_(
                        m.SchoolStaffInvitation.status == "EXPIRED",
                        (
                            (m.SchoolStaffInvitation.status == "ISSUED")
                            & (m.SchoolStaffInvitation.expires_at <= now)
                        ),
                    ),
                )
            )
            invitations_revoked = await uow.session.scalar(
                self._select(func.count(m.SchoolStaffInvitation.id)).where(
                    m.SchoolStaffInvitation.school_id == actor.school_id,
                    m.SchoolStaffInvitation.status == "REVOKED",
                )
            )
            recovery_queue_count = await uow.session.scalar(
                self._select(func.count(m.SchoolPasswordRecoveryTicket.id)).where(
                    m.SchoolPasswordRecoveryTicket.school_id == actor.school_id,
                    m.SchoolPasswordRecoveryTicket.status.in_(
                        ("REQUESTED", "TEACHER_VERIFIED", "APPROVED")
                    ),
                )
            )
            return {
                "total_accounts": int(total or 0),
                "active_accounts": int(active or 0),
                "pending_activation": int(pending or 0),
                "suspended_accounts": int(suspended or 0),
                "classes": int(classes or 0),
                "invitations_issued": int(invitations_issued or 0),
                "invitations_accepted": int(invitations_accepted or 0),
                "invitations_expired": int(invitations_expired or 0),
                "invitations_revoked": int(invitations_revoked or 0),
                "recovery_queue_count": int(recovery_queue_count or 0),
            }

    async def create_staff_invitation(
        self,
        actor: Any,
        payload: Any,
        *,
        ttl_seconds: int,
        trace_id: str,
    ) -> dict[str, Any]:
        m = self._db_models
        e = self._db_enums
        now = self._utc_now()
        if not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            raise error(ErrorCode.VALIDATION_FAILED, detail="invitation expiry is invalid")
        login_name = self._login_name(actor.school_ref, payload.employee_ref)
        expires_at = now + timedelta(seconds=ttl_seconds)
        raw_token, token_hash = self._token()
        invitation_ref = f"INV_{uuid4().hex}"
        if (payload.role == "teacher" and not payload.class_refs) or (
            payload.role == "psychological_specialist" and payload.class_refs
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="class scope is invalid for this role")

        async with self._uow() as uow:
            actor_id, issuer_role_id = await self._school_actor_role(
                uow, actor, "admin", now, lock=True
            )
            duplicate = await uow.session.scalar(
                self._select(m.SchoolStaffInvitation.id).where(
                    m.SchoolStaffInvitation.school_id == actor.school_id,
                    m.SchoolStaffInvitation.employee_ref == payload.employee_ref,
                )
            )
            existing_account = await uow.session.scalar(
                self._select(m.Account.id).where(m.Account.login_name == login_name)
            )
            if duplicate is not None or existing_account is not None:
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT,
                    detail="staff invitation conflicts with an existing account",
                )
            classes = (
                list(
                    (
                        await uow.session.scalars(
                            self._select(m.SchoolClass)
                            .where(
                                m.SchoolClass.school_id == actor.school_id,
                                m.SchoolClass.class_ref.in_(payload.class_refs),
                                m.SchoolClass.status == "ACTIVE",
                            )
                            .order_by(m.SchoolClass.id)
                            .with_for_update()
                        )
                    ).all()
                )
                if payload.class_refs
                else []
            )
            if {item.class_ref for item in classes} != set(payload.class_refs):
                raise error(
                    ErrorCode.RESOURCE_NOT_FOUND, detail="one or more classes were not found"
                )

            protected_contact = uow.protection.encrypt_json(
                {"contact": payload.work_contact},
                payload_schema_version="school-staff-contact.v1",
            )
            account = m.Account(
                login_name=login_name,
                password_hash=PasswordHash.recommended().hash(secrets.token_urlsafe(48)),
                status=e.AccountStatus.SUSPENDED.value,
                must_change_password=True,
            )
            uow.session.add(account)
            await uow.session.flush()
            membership = m.AccountSchoolMembership(
                account_id=account.id,
                school_id=actor.school_id,
                display_name=payload.display_name,
                status="INACTIVE",
                valid_from=now,
            )
            uow.session.add(membership)
            await uow.session.flush()
            role = m.MembershipRole(
                membership_id=membership.id,
                school_id=actor.school_id,
                role_code=payload.role,
                status="INACTIVE",
                valid_from=now,
            )
            uow.session.add(role)
            await uow.session.flush()
            invitation = m.SchoolStaffInvitation(
                invitation_ref=invitation_ref,
                school_id=actor.school_id,
                account_id=account.id,
                membership_id=membership.id,
                membership_role_id=role.id,
                issued_by_membership_role_id=issuer_role_id,
                role_code=payload.role,
                employee_ref=payload.employee_ref,
                status="ISSUED",
                delivery_channel="MANUAL",
                work_contact_ciphertext=protected_contact.ciphertext,
                work_contact_cipher_format_version=protected_contact.cipher_format_version,
                work_contact_key_version=protected_contact.key_version,
                work_contact_payload_schema_version=protected_contact.payload_schema_version,
                work_contact_verified_at=now,
                expires_at=expires_at,
                trace_id=trace_id,
            )
            uow.session.add(invitation)
            await uow.session.flush()
            for school_class in classes:
                uow.session.add(
                    m.SchoolStaffInvitationClass(
                        invitation_id=invitation.id,
                        school_id=actor.school_id,
                        class_id=school_class.id,
                    )
                )
            uow.session.add(
                m.SchoolAccountCredential(
                    credential_ref=f"CRED_{uuid4().hex}",
                    account_id=account.id,
                    school_id=actor.school_id,
                    issued_by_membership_role_id=issuer_role_id,
                    purpose="STAFF_INVITATION",
                    resource_ref=invitation.public_id,
                    token_hash=token_hash,
                    status="ISSUED",
                    delivery_channel="MANUAL",
                    expires_at=expires_at,
                    trace_id=trace_id,
                )
            )
            await uow.session.flush()
            await self._audit(
                uow,
                actor_account_id=actor_id,
                action="school_account_lifecycle.staff_invitation.issue",
                resource_type="school_staff_invitation",
                resource_ref=invitation.public_id,
                trace_id=trace_id,
                metadata={"count": len(classes)},
            )
            return {
                "invitation_ref": invitation_ref,
                "status": "ISSUED",
                "delivery_channel": "MANUAL_HANDOFF_REQUIRED",
                "user_id": f"USER_{account.public_id}",
                "login_name": login_name,
                "credential": raw_token,
                "expires_at": expires_at,
            }

    async def import_school_staff_roster(
        self,
        actor: Any,
        rows: list[Any],
        *,
        ttl_seconds: int,
        trace_id: str,
    ) -> dict[str, Any]:
        """Create synthetic staff invitations and one-time first-login credentials."""

        m = self._db_models
        e = self._db_enums
        now = self._utc_now()
        if not isinstance(ttl_seconds, int) or ttl_seconds <= 0 or not 1 <= len(rows) <= 200:
            raise error(ErrorCode.VALIDATION_FAILED, detail="staff import size is invalid")

        row_refs = [row.employee_ref.casefold() for row in rows]
        if len(set(row_refs)) != len(row_refs):
            raise error(ErrorCode.VALIDATION_FAILED, detail="employee references must be unique")

        async with self._uow() as uow:
            actor_id, issuer_role_id = await self._school_actor_role(
                uow, actor, "admin", now, lock=True
            )
            school = await uow.session.scalar(
                self._select(m.School)
                .where(
                    m.School.id == actor.school_id,
                    m.School.school_ref == actor.school_ref,
                    m.School.status == "ACTIVE",
                    m.School.data_origin == e.DataOrigin.SYNTHETIC.value,
                )
                .with_for_update()
            )
            if school is None:
                raise error(ErrorCode.FORBIDDEN, detail="synthetic staff import is unavailable")

            existing_refs = set(
                (
                    await uow.session.scalars(
                        self._select(m.SchoolStaffInvitation.employee_ref).where(
                            m.SchoolStaffInvitation.school_id == actor.school_id,
                            m.SchoolStaffInvitation.employee_ref.in_(
                                [row.employee_ref for row in rows]
                            ),
                        )
                    )
                ).all()
            )
            login_names = [self._login_name(actor.school_ref, row.employee_ref) for row in rows]
            existing_logins = set(
                (
                    await uow.session.scalars(
                        self._select(m.Account.login_name).where(
                            m.Account.login_name.in_(login_names)
                        )
                    )
                ).all()
            )
            if existing_refs or existing_logins:
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT,
                    detail="one or more staff accounts already exist",
                )

            requested_classes = sorted(
                {class_ref for row in rows for class_ref in row.class_refs}
            )
            classes = (
                list(
                    (
                        await uow.session.scalars(
                            self._select(m.SchoolClass)
                            .where(
                                m.SchoolClass.school_id == actor.school_id,
                                m.SchoolClass.class_ref.in_(requested_classes),
                                m.SchoolClass.status == "ACTIVE",
                            )
                            .order_by(m.SchoolClass.id)
                            .with_for_update()
                        )
                    ).all()
                )
                if requested_classes
                else []
            )
            classes_by_ref = {item.class_ref: item for item in classes}
            if set(classes_by_ref) != set(requested_classes):
                raise error(
                    ErrorCode.RESOURCE_NOT_FOUND,
                    detail="one or more classes were not found",
                )

            expires_at = now + timedelta(seconds=ttl_seconds)
            hasher = PasswordHash.recommended()
            output: list[dict[str, Any]] = []
            for row in rows:
                login_name = self._login_name(actor.school_ref, row.employee_ref)
                invitation_ref = f"INV_{uuid4().hex}"
                raw_token, token_hash = self._token()
                account = m.Account(
                    login_name=login_name,
                    password_hash=hasher.hash(secrets.token_urlsafe(48)),
                    status=e.AccountStatus.SUSPENDED.value,
                    must_change_password=True,
                )
                uow.session.add(account)
                await uow.session.flush()
                membership = m.AccountSchoolMembership(
                    account_id=account.id,
                    school_id=actor.school_id,
                    display_name=row.display_name,
                    status="INACTIVE",
                    valid_from=now,
                )
                uow.session.add(membership)
                await uow.session.flush()
                role = m.MembershipRole(
                    membership_id=membership.id,
                    school_id=actor.school_id,
                    role_code=row.role,
                    status="INACTIVE",
                    valid_from=now,
                )
                uow.session.add(role)
                await uow.session.flush()

                contact = uow.protection.encrypt_json(
                    {"contact": f"{row.employee_ref}@example.invalid"},
                    payload_schema_version="school-staff-contact.v1",
                )
                invitation = m.SchoolStaffInvitation(
                    invitation_ref=invitation_ref,
                    school_id=actor.school_id,
                    account_id=account.id,
                    membership_id=membership.id,
                    membership_role_id=role.id,
                    issued_by_membership_role_id=issuer_role_id,
                    role_code=row.role,
                    employee_ref=row.employee_ref,
                    status="ISSUED",
                    delivery_channel="MANUAL",
                    work_contact_ciphertext=contact.ciphertext,
                    work_contact_cipher_format_version=contact.cipher_format_version,
                    work_contact_key_version=contact.key_version,
                    work_contact_payload_schema_version=contact.payload_schema_version,
                    work_contact_verified_at=now,
                    expires_at=expires_at,
                    trace_id=trace_id,
                )
                uow.session.add(invitation)
                await uow.session.flush()
                class_refs: list[str] = []
                for class_ref in row.class_refs:
                    uow.session.add(
                        m.SchoolStaffInvitationClass(
                            invitation_id=invitation.id,
                            school_id=actor.school_id,
                            class_id=classes_by_ref[class_ref].id,
                        )
                    )
                    class_refs.append(class_ref)
                uow.session.add(
                    m.SchoolAccountCredential(
                        credential_ref=f"CRED_{uuid4().hex}",
                        account_id=account.id,
                        school_id=actor.school_id,
                        issued_by_membership_role_id=issuer_role_id,
                        purpose="STAFF_INVITATION",
                        resource_ref=invitation.public_id,
                        token_hash=token_hash,
                        status="ISSUED",
                        delivery_channel="MANUAL",
                        expires_at=expires_at,
                        trace_id=trace_id,
                    )
                )
                await uow.session.flush()
                await self._audit(
                    uow,
                    actor_account_id=actor_id,
                    action="school_account_lifecycle.staff_roster_import.issue",
                    resource_type="school_staff_invitation",
                    resource_ref=invitation.public_id,
                    trace_id=trace_id,
                    metadata={"count": 1},
                )
                output.append(
                    {
                        "invitation_ref": invitation_ref,
                        "user_id": f"USER_{account.public_id}",
                        "login_name": login_name,
                        "display_name": row.display_name,
                        "role": row.role,
                        "class_refs": class_refs,
                        "credential": raw_token,
                        "expires_at": expires_at,
                    }
                )
            await uow.session.flush()
            return {
                "created_count": len(output),
                "credentials": output,
                "delivery_status": "MANUAL_HANDOFF_REQUIRED",
            }

    async def list_staff_invitations(self, actor: Any) -> list[dict[str, Any]]:
        m = self._db_models
        now = self._utc_now()
        async with self._uow() as uow:
            await self._school_actor_role(uow, actor, "admin", now)
            rows = (
                await uow.session.execute(
                    self._select(
                        m.SchoolStaffInvitation.id,
                        m.SchoolStaffInvitation.public_id,
                        m.SchoolStaffInvitation.invitation_ref,
                        m.SchoolStaffInvitation.employee_ref,
                        m.SchoolStaffInvitation.role_code,
                        m.SchoolStaffInvitation.status,
                        m.SchoolStaffInvitation.delivery_channel,
                        m.SchoolStaffInvitation.created_at,
                        m.SchoolStaffInvitation.expires_at,
                        m.Account.public_id,
                        m.Account.login_name,
                        m.AccountSchoolMembership.display_name,
                    )
                    .join(m.Account, m.Account.id == m.SchoolStaffInvitation.account_id)
                    .join(
                        m.AccountSchoolMembership,
                        (m.AccountSchoolMembership.id == m.SchoolStaffInvitation.membership_id)
                        & (
                            m.AccountSchoolMembership.school_id == m.SchoolStaffInvitation.school_id
                        ),
                    )
                    .where(m.SchoolStaffInvitation.school_id == actor.school_id)
                    .order_by(m.SchoolStaffInvitation.created_at.desc())
                    .limit(500)
                )
            ).all()
            invitation_ids = [row[0] for row in rows]
            class_refs_by_invitation: dict[int, list[str]] = {
                invitation_id: [] for invitation_id in invitation_ids
            }
            if invitation_ids:
                class_rows = (
                    await uow.session.execute(
                        self._select(
                            m.SchoolStaffInvitationClass.invitation_id,
                            m.SchoolClass.class_ref,
                        )
                        .join(
                            m.SchoolClass,
                            (m.SchoolClass.id == m.SchoolStaffInvitationClass.class_id)
                            & (m.SchoolClass.school_id == m.SchoolStaffInvitationClass.school_id),
                        )
                        .where(
                            m.SchoolStaffInvitationClass.school_id == actor.school_id,
                            m.SchoolStaffInvitationClass.invitation_id.in_(invitation_ids),
                        )
                        .order_by(
                            m.SchoolStaffInvitationClass.invitation_id,
                            m.SchoolClass.class_ref,
                        )
                    )
                ).all()
                for invitation_id, class_ref in class_rows:
                    class_refs_by_invitation[int(invitation_id)].append(class_ref)
            grouped: dict[str, dict[str, Any]] = {}
            for row in rows:
                status = row[5]
                if status == "ISSUED" and row[8] <= now:
                    status = "EXPIRED"
                grouped[row[2]] = {
                    "invitation_ref": row[2],
                    "user_id": f"USER_{row[9]}",
                    "login_name": row[10],
                    "display_name": row[11],
                    "employee_ref": row[3],
                    "role": row[4],
                    "status": status,
                    "delivery_channel": row[6],
                    "class_refs": class_refs_by_invitation[int(row[0])],
                    "created_at": row[7],
                    "expires_at": row[8],
                }
            return list(grouped.values())

    async def revoke_staff_invitation(
        self,
        actor: Any,
        invitation_ref: str,
        *,
        reason_code: str,
        trace_id: str,
    ) -> dict[str, str]:
        m = self._db_models
        now = self._utc_now()
        async with self._uow() as uow:
            actor_id, _role_id = await self._school_actor_role(uow, actor, "admin", now, lock=True)
            invitation = await uow.session.scalar(
                self._select(m.SchoolStaffInvitation)
                .where(
                    m.SchoolStaffInvitation.invitation_ref == invitation_ref,
                    m.SchoolStaffInvitation.school_id == actor.school_id,
                )
                .with_for_update()
            )
            if invitation is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="invitation was not found")
            if invitation.status not in {"ISSUED", "EXPIRED"}:
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="invitation cannot be revoked")
            credentials = list(
                (
                    await uow.session.scalars(
                        self._select(m.SchoolAccountCredential)
                        .where(
                            m.SchoolAccountCredential.account_id == invitation.account_id,
                            m.SchoolAccountCredential.school_id == actor.school_id,
                            m.SchoolAccountCredential.resource_ref == invitation.public_id,
                            m.SchoolAccountCredential.purpose == "STAFF_INVITATION",
                            m.SchoolAccountCredential.status == "ISSUED",
                        )
                        .order_by(m.SchoolAccountCredential.id)
                        .with_for_update()
                    )
                ).all()
            )
            for credential in credentials:
                credential.status = "REVOKED"
                credential.revoked_at = now
            invitation.status = "REVOKED"
            invitation.revoked_at = now
            await uow.session.flush()
            await self._audit(
                uow,
                actor_account_id=actor_id,
                action="school_account_lifecycle.staff_invitation.revoke",
                resource_type="school_staff_invitation",
                resource_ref=invitation.public_id,
                trace_id=trace_id,
                metadata={"reason_code": reason_code, "count": len(credentials)},
            )
            return {"status": "REVOKED"}

    async def reissue_staff_invitation(
        self,
        actor: Any,
        invitation_ref: str,
        *,
        reason_code: str,
        ttl_seconds: int,
        trace_id: str,
    ) -> dict[str, Any]:
        m = self._db_models
        e = self._db_enums
        now = self._utc_now()
        expires_at = now + timedelta(seconds=ttl_seconds)
        raw_token, token_hash = self._token()
        async with self._uow() as uow:
            actor_id, issuer_role_id = await self._school_actor_role(
                uow, actor, "admin", now, lock=True
            )
            invitation = await uow.session.scalar(
                self._select(m.SchoolStaffInvitation)
                .where(
                    m.SchoolStaffInvitation.invitation_ref == invitation_ref,
                    m.SchoolStaffInvitation.school_id == actor.school_id,
                )
                .with_for_update()
            )
            if invitation is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="invitation was not found")
            if invitation.status == "ACCEPTED":
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT, detail="accepted invitation cannot be reissued"
                )
            account = await uow.session.scalar(
                self._select(m.Account)
                .where(m.Account.id == invitation.account_id)
                .with_for_update()
            )
            membership = await uow.session.scalar(
                self._select(m.AccountSchoolMembership)
                .where(
                    m.AccountSchoolMembership.id == invitation.membership_id,
                    m.AccountSchoolMembership.account_id == invitation.account_id,
                    m.AccountSchoolMembership.school_id == actor.school_id,
                )
                .with_for_update()
            )
            role = await uow.session.scalar(
                self._select(m.MembershipRole)
                .where(
                    m.MembershipRole.id == invitation.membership_role_id,
                    m.MembershipRole.membership_id == invitation.membership_id,
                    m.MembershipRole.school_id == actor.school_id,
                )
                .with_for_update()
            )
            if (
                account is None
                or account.status != e.AccountStatus.SUSPENDED.value
                or not account.must_change_password
                or membership is None
                or membership.status != "INACTIVE"
                or role is None
                or role.status != "INACTIVE"
            ):
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="invitation cannot be reissued")
            old_credentials = list(
                (
                    await uow.session.scalars(
                        self._select(m.SchoolAccountCredential)
                        .where(
                            m.SchoolAccountCredential.account_id == account.id,
                            m.SchoolAccountCredential.school_id == actor.school_id,
                            m.SchoolAccountCredential.resource_ref == invitation.public_id,
                            m.SchoolAccountCredential.purpose == "STAFF_INVITATION",
                            m.SchoolAccountCredential.status == "ISSUED",
                        )
                        .order_by(m.SchoolAccountCredential.id)
                        .with_for_update()
                    )
                ).all()
            )
            for old in old_credentials:
                old.status = "REVOKED"
                old.revoked_at = now
            credential = m.SchoolAccountCredential(
                credential_ref=f"CRED_{uuid4().hex}",
                account_id=account.id,
                school_id=actor.school_id,
                issued_by_membership_role_id=issuer_role_id,
                purpose="STAFF_INVITATION",
                resource_ref=invitation.public_id,
                token_hash=token_hash,
                status="ISSUED",
                delivery_channel="MANUAL",
                expires_at=expires_at,
                trace_id=trace_id,
            )
            uow.session.add(credential)
            invitation.status = "ISSUED"
            invitation.revoked_at = None
            invitation.expires_at = expires_at
            await uow.session.flush()
            await self._audit(
                uow,
                actor_account_id=actor_id,
                action="school_account_lifecycle.staff_invitation.reissue",
                resource_type="school_staff_invitation",
                resource_ref=invitation.public_id,
                trace_id=trace_id,
                metadata={
                    "reason_code": reason_code,
                    "count": len(old_credentials),
                },
            )
            return {
                "invitation_ref": invitation.invitation_ref,
                "status": "ISSUED",
                "delivery_channel": "MANUAL_HANDOFF_REQUIRED",
                "user_id": f"USER_{account.public_id}",
                "login_name": account.login_name,
                "credential": raw_token,
                "expires_at": expires_at,
            }

    async def issue_staff_recovery_credential(
        self,
        actor: Any,
        user_ref: str,
        *,
        reason_code: str,
        verification_method: str,
        ttl_seconds: int,
        trace_id: str,
    ) -> dict[str, Any]:
        m = self._db_models
        e = self._db_enums
        now = self._utc_now()
        if (
            not isinstance(ttl_seconds, int)
            or ttl_seconds <= 0
            or verification_method not in {"IN_PERSON", "VERIFIED_WORK_CONTACT"}
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="recovery verification is invalid")
        try:
            public_id = self._public_id(user_ref, "USER")
        except ValueError:
            raise error(
                ErrorCode.RESOURCE_NOT_FOUND, detail="staff account was not found"
            ) from None

        raw_token, token_hash = self._token()
        expires_at = now + timedelta(seconds=ttl_seconds)
        async with self._uow() as uow:
            actor_id, issuer_role_id = await self._school_actor_role(
                uow, actor, "admin", now, lock=True
            )
            target = (
                await uow.session.execute(
                    self._select(m.Account, m.AccountSchoolMembership)
                    .join(
                        m.AccountSchoolMembership,
                        m.AccountSchoolMembership.account_id == m.Account.id,
                    )
                    .where(
                        m.Account.public_id == public_id,
                        m.Account.status == e.AccountStatus.ACTIVE.value,
                        m.AccountSchoolMembership.school_id == actor.school_id,
                        m.AccountSchoolMembership.status == "ACTIVE",
                        m.AccountSchoolMembership.revoked_at.is_(None),
                        m.AccountSchoolMembership.valid_from <= now,
                        (m.AccountSchoolMembership.valid_until.is_(None))
                        | (m.AccountSchoolMembership.valid_until >= now),
                    )
                    .with_for_update()
                )
            ).first()
            if target is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="staff account was not found")
            account, membership = target
            role_codes = set(
                (
                    await uow.session.scalars(
                        self._select(m.MembershipRole.role_code).where(
                            m.MembershipRole.membership_id == membership.id,
                            m.MembershipRole.school_id == actor.school_id,
                            m.MembershipRole.status == "ACTIVE",
                            m.MembershipRole.revoked_at.is_(None),
                            m.MembershipRole.valid_from <= now,
                            (m.MembershipRole.valid_until.is_(None))
                            | (m.MembershipRole.valid_until >= now),
                        )
                    )
                ).all()
            )
            staff_roles = {"teacher", "psychological_specialist"}
            if not role_codes.intersection(staff_roles) or role_codes.intersection(
                {"admin", "student"}
            ):
                raise error(ErrorCode.FORBIDDEN, detail="access denied")
            if "psychological_specialist" in role_codes and verification_method != "IN_PERSON":
                raise error(
                    ErrorCode.VALIDATION_FAILED,
                    detail="psychological specialist recovery requires in-person verification",
                )
            verified_invitation = await uow.session.scalar(
                self._select(m.SchoolStaffInvitation.id)
                .where(
                    m.SchoolStaffInvitation.account_id == account.id,
                    m.SchoolStaffInvitation.school_id == actor.school_id,
                    m.SchoolStaffInvitation.status == "ACCEPTED",
                    m.SchoolStaffInvitation.work_contact_verified_at.is_not(None),
                )
                .limit(1)
            )
            if verified_invitation is None:
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT,
                    detail="verified staff invitation is required for recovery",
                )

            outstanding = list(
                (
                    await uow.session.scalars(
                        self._select(m.SchoolAccountCredential)
                        .where(
                            m.SchoolAccountCredential.account_id == account.id,
                            m.SchoolAccountCredential.school_id == actor.school_id,
                            m.SchoolAccountCredential.status == "ISSUED",
                        )
                        .order_by(m.SchoolAccountCredential.id)
                        .with_for_update()
                    )
                ).all()
            )
            for credential in outstanding:
                credential.status = "REVOKED"
                credential.revoked_at = now
            account.must_change_password = True
            await self._revoke_sessions(uow, account.id, now, "STAFF_PASSWORD_RESET_ISSUED")
            credential_ref = f"CRED_{uuid4().hex}"
            uow.session.add(
                m.SchoolAccountCredential(
                    credential_ref=credential_ref,
                    account_id=account.id,
                    school_id=actor.school_id,
                    issued_by_membership_role_id=issuer_role_id,
                    purpose="PASSWORD_RESET",
                    resource_ref=f"{STAFF_RECOVERY_RESOURCE_PREFIX}{account.public_id}",
                    token_hash=token_hash,
                    status="ISSUED",
                    delivery_channel="MANUAL",
                    expires_at=expires_at,
                    trace_id=trace_id,
                )
            )
            await uow.session.flush()
            await self._audit(
                uow,
                actor_account_id=actor_id,
                action=(
                    f"school_account_lifecycle.staff_recovery.issue.{verification_method.lower()}"
                ),
                resource_type="account",
                resource_ref=account.public_id,
                trace_id=trace_id,
                metadata={"reason_code": reason_code},
            )
            return {
                "user_id": f"USER_{account.public_id}",
                "login_name": account.login_name,
                "status": "ISSUED",
                "delivery_channel": "MANUAL_HANDOFF_REQUIRED",
                "credential": raw_token,
                "expires_at": expires_at,
            }

    async def accept_staff_invitation(
        self,
        *,
        invitation_ref: str,
        token_hash: bytes,
        new_password: str,
        trace_id: str,
    ) -> dict[str, str]:
        m = self._db_models
        e = self._db_enums
        now = self._utc_now()
        async with self._uow() as uow:
            invitation = await uow.session.scalar(
                self._select(m.SchoolStaffInvitation)
                .where(m.SchoolStaffInvitation.invitation_ref == invitation_ref)
                .with_for_update()
            )
            if invitation is None:
                raise self._generic_credential_error()
            if invitation.status == "ISSUED" and invitation.expires_at <= now:
                raise self._generic_credential_error()
            account = await uow.session.scalar(
                self._select(m.Account)
                .where(m.Account.id == invitation.account_id)
                .with_for_update()
            )
            credential = await uow.session.scalar(
                self._select(m.SchoolAccountCredential)
                .where(
                    m.SchoolAccountCredential.account_id == invitation.account_id,
                    m.SchoolAccountCredential.school_id == invitation.school_id,
                    m.SchoolAccountCredential.resource_ref == invitation.public_id,
                    m.SchoolAccountCredential.purpose == "STAFF_INVITATION",
                    m.SchoolAccountCredential.token_hash == token_hash,
                    m.SchoolAccountCredential.status == "ISSUED",
                    m.SchoolAccountCredential.expires_at > now,
                )
                .with_for_update()
            )
            if (
                invitation.status != "ISSUED"
                or credential is None
                or account is None
                or account.status != e.AccountStatus.SUSPENDED.value
            ):
                raise self._generic_credential_error()
            membership = await uow.session.scalar(
                self._select(m.AccountSchoolMembership)
                .where(
                    m.AccountSchoolMembership.id == invitation.membership_id,
                    m.AccountSchoolMembership.account_id == account.id,
                    m.AccountSchoolMembership.school_id == invitation.school_id,
                    m.AccountSchoolMembership.status == "INACTIVE",
                )
                .with_for_update()
            )
            role = await uow.session.scalar(
                self._select(m.MembershipRole)
                .where(
                    m.MembershipRole.id == invitation.membership_role_id,
                    m.MembershipRole.membership_id == invitation.membership_id,
                    m.MembershipRole.school_id == invitation.school_id,
                    m.MembershipRole.role_code == invitation.role_code,
                    m.MembershipRole.status == "INACTIVE",
                )
                .with_for_update()
            )
            if membership is None or role is None:
                raise self._generic_credential_error()
            account.password_hash = PasswordHash.recommended().hash(new_password)
            account.status = e.AccountStatus.ACTIVE.value
            account.must_change_password = False
            account.password_changed_at = now
            account.failed_login_count = 0
            account.locked_until = None
            membership.status = "ACTIVE"
            membership.valid_from = now
            role.status = "ACTIVE"
            role.valid_from = now
            invitation.status = "ACCEPTED"
            invitation.accepted_at = now
            credential.status = "CONSUMED"
            credential.consumed_at = now

            # Generic teacher class access is restricted to the explicitly
            # approved invitation classes. Specialist roles receive no
            # teacher-of subject grants from role assignment alone.
            if invitation.role_code == "teacher":
                links = list(
                    (
                        await uow.session.scalars(
                            self._select(m.SchoolStaffInvitationClass)
                            .where(
                                m.SchoolStaffInvitationClass.invitation_id == invitation.id,
                                m.SchoolStaffInvitationClass.school_id == invitation.school_id,
                            )
                            .order_by(m.SchoolStaffInvitationClass.class_id)
                            .with_for_update()
                        )
                    ).all()
                )
                for link in links:
                    uow.session.add(
                        m.SchoolClassTeacher(
                            school_id=invitation.school_id,
                            class_id=link.class_id,
                            membership_role_id=role.id,
                            status="ACTIVE",
                            valid_from=now,
                        )
                    )
            await self._revoke_sessions(uow, account.id, now, "STAFF_INVITATION_ACCEPTED")
            await uow.session.flush()
            await self._audit(
                uow,
                actor_account_id=None,
                action="school_account_lifecycle.staff_invitation.accept",
                resource_type="school_staff_invitation",
                resource_ref=invitation.public_id,
                trace_id=trace_id,
            )
            return {"status": "ACCEPTED"}

    async def create_recovery_request(
        self,
        *,
        school_ref: str,
        username: str,
        class_ref: str,
        reason_code: str,
        trace_id: str,
    ) -> dict[str, str]:
        """Create a ticket only for an exact student/class match; response stays generic."""
        from sqlalchemy import func

        m = self._db_models
        now = self._utc_now()
        async with self._uow() as uow:
            target = await uow.session.execute(
                self._select(
                    m.Account.id,
                    m.School.id,
                    m.SchoolClass.id,
                    m.AccountSchoolMembership.display_name,
                )
                .join(
                    m.AccountSchoolMembership, m.AccountSchoolMembership.account_id == m.Account.id
                )
                .join(m.School, m.School.id == m.AccountSchoolMembership.school_id)
                .join(
                    m.MembershipRole, m.MembershipRole.membership_id == m.AccountSchoolMembership.id
                )
                .join(m.SchoolClass, m.SchoolClass.class_ref == class_ref)
                .join(
                    m.SubjectAccessGrant,
                    (m.SubjectAccessGrant.principal_account_id == m.Account.id)
                    & (m.SubjectAccessGrant.school_id == m.School.id)
                    & (m.SubjectAccessGrant.relationship_type == "SELF"),
                )
                .join(
                    m.SchoolClassStudent,
                    m.SchoolClassStudent.subject_id == m.SubjectAccessGrant.subject_id,
                )
                .where(
                    func.lower(m.Account.login_name) == username.strip().casefold(),
                    m.School.school_ref == school_ref.strip(),
                    m.School.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                    m.School.status == "ACTIVE",
                    m.AccountSchoolMembership.school_id == m.School.id,
                    m.AccountSchoolMembership.status == "ACTIVE",
                    m.AccountSchoolMembership.revoked_at.is_(None),
                    m.AccountSchoolMembership.valid_from <= now,
                    (m.AccountSchoolMembership.valid_until.is_(None))
                    | (m.AccountSchoolMembership.valid_until >= now),
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
                    m.SchoolClass.school_id == m.School.id,
                    m.SchoolClass.status == "ACTIVE",
                    m.SchoolClassStudent.class_id == m.SchoolClass.id,
                    m.SchoolClassStudent.school_id == m.School.id,
                    m.SchoolClassStudent.status == "ACTIVE",
                    m.SchoolClassStudent.revoked_at.is_(None),
                    m.SchoolClassStudent.valid_from <= now,
                    (m.SchoolClassStudent.valid_until.is_(None))
                    | (m.SchoolClassStudent.valid_until >= now),
                )
                .limit(1)
            )
            row = target.first()
            if row is not None:
                account_id, school_id, class_id, _display_name = row
                active_ticket = await uow.session.scalar(
                    self._select(m.SchoolPasswordRecoveryTicket.id)
                    .where(
                        m.SchoolPasswordRecoveryTicket.account_id == account_id,
                        m.SchoolPasswordRecoveryTicket.school_id == school_id,
                        m.SchoolPasswordRecoveryTicket.status.in_(
                            ("REQUESTED", "TEACHER_VERIFIED", "APPROVED")
                        ),
                    )
                    .limit(1)
                )
                if active_ticket is None:
                    ticket_ref = f"RESET_{uuid4().hex}"
                    ticket = m.SchoolPasswordRecoveryTicket(
                        ticket_ref=ticket_ref,
                        school_id=school_id,
                        account_id=account_id,
                        class_id=class_id,
                        reason_code=reason_code,
                        status="REQUESTED",
                        trace_id=trace_id,
                    )
                    uow.session.add(ticket)
                    await uow.session.flush()
                    await self._audit(
                        uow,
                        actor_account_id=None,
                        action="school_account_lifecycle.recovery.request",
                        resource_type="school_password_recovery_ticket",
                        resource_ref=ticket.public_id,
                        trace_id=trace_id,
                        metadata={"reason_code": reason_code},
                    )
            return {"status": "REQUEST_RECEIVED"}

    async def list_recovery_requests(self, actor: Any) -> list[dict[str, Any]]:
        m = self._db_models
        now = self._utc_now()
        async with self._uow() as uow:
            await self._school_actor_role(uow, actor, "admin", now)
            rows = (
                await uow.session.execute(
                    self._select(
                        m.SchoolPasswordRecoveryTicket.ticket_ref,
                        m.Account.public_id,
                        m.Account.login_name,
                        m.AccountSchoolMembership.display_name,
                        m.SchoolClass.class_ref,
                        m.SchoolPasswordRecoveryTicket.status,
                        m.SchoolPasswordRecoveryTicket.created_at,
                    )
                    .join(m.Account, m.Account.id == m.SchoolPasswordRecoveryTicket.account_id)
                    .join(
                        m.AccountSchoolMembership,
                        (m.AccountSchoolMembership.account_id == m.Account.id)
                        & (
                            m.AccountSchoolMembership.school_id
                            == m.SchoolPasswordRecoveryTicket.school_id
                        ),
                    )
                    .join(
                        m.SchoolClass, m.SchoolClass.id == m.SchoolPasswordRecoveryTicket.class_id
                    )
                    .where(m.SchoolPasswordRecoveryTicket.school_id == actor.school_id)
                    .order_by(m.SchoolPasswordRecoveryTicket.created_at.desc())
                    .limit(200)
                )
            ).all()
            return [
                {
                    "ticket_ref": row[0],
                    "user_id": f"USER_{row[1]}",
                    "username": row[2],
                    "display_name": row[3],
                    "class_ref": row[4],
                    "role": "student",
                    "status": row[5],
                    "created_at": row[6],
                }
                for row in rows
            ]

    async def verify_recovery_request(
        self,
        actor: Any,
        ticket_ref: str,
        *,
        reason_code: str,
        trace_id: str,
    ) -> dict[str, str]:
        m = self._db_models
        now = self._utc_now()
        async with self._uow() as uow:
            actor_id, role_id = await self._school_actor_role(uow, actor, "teacher", now, lock=True)
            ticket = await uow.session.scalar(
                self._select(m.SchoolPasswordRecoveryTicket)
                .where(
                    m.SchoolPasswordRecoveryTicket.ticket_ref == ticket_ref,
                    m.SchoolPasswordRecoveryTicket.school_id == actor.school_id,
                )
                .with_for_update()
            )
            if ticket is None or ticket.status != "REQUESTED":
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT, detail="recovery request cannot be verified"
                )
            assigned = await uow.session.scalar(
                self._select(m.SchoolClassTeacher.id)
                .join(
                    m.MembershipRole, m.MembershipRole.id == m.SchoolClassTeacher.membership_role_id
                )
                .join(
                    m.AccountSchoolMembership,
                    m.AccountSchoolMembership.id == m.MembershipRole.membership_id,
                )
                .where(
                    m.AccountSchoolMembership.account_id == actor_id,
                    m.MembershipRole.id == role_id,
                    m.SchoolClassTeacher.class_id == ticket.class_id,
                    m.SchoolClassTeacher.school_id == actor.school_id,
                    m.SchoolClassTeacher.status == "ACTIVE",
                    m.SchoolClassTeacher.revoked_at.is_(None),
                    m.SchoolClassTeacher.valid_from <= now,
                    (m.SchoolClassTeacher.valid_until.is_(None))
                    | (m.SchoolClassTeacher.valid_until >= now),
                    m.MembershipRole.status == "ACTIVE",
                    m.MembershipRole.revoked_at.is_(None),
                    m.MembershipRole.valid_from <= now,
                    (m.MembershipRole.valid_until.is_(None))
                    | (m.MembershipRole.valid_until >= now),
                    m.AccountSchoolMembership.status == "ACTIVE",
                    m.AccountSchoolMembership.revoked_at.is_(None),
                    m.AccountSchoolMembership.valid_from <= now,
                    (m.AccountSchoolMembership.valid_until.is_(None))
                    | (m.AccountSchoolMembership.valid_until >= now),
                )
                .limit(1)
            )
            if assigned is None:
                raise error(ErrorCode.FORBIDDEN, detail="access denied")
            ticket.status = "TEACHER_VERIFIED"
            ticket.verified_by_membership_role_id = role_id
            ticket.verified_at = now
            await uow.session.flush()
            await self._audit(
                uow,
                actor_account_id=actor_id,
                action="school_account_lifecycle.recovery.verify",
                resource_type="school_password_recovery_ticket",
                resource_ref=ticket.public_id,
                trace_id=trace_id,
                metadata={"reason_code": reason_code},
            )
            return {"status": "TEACHER_VERIFIED"}

    async def approve_recovery_request(
        self,
        actor: Any,
        ticket_ref: str,
        *,
        reason_code: str,
        ttl_seconds: int,
        trace_id: str,
    ) -> dict[str, Any]:
        m = self._db_models
        now = self._utc_now()
        raw_token, token_hash = self._token()
        expires_at = now + timedelta(seconds=ttl_seconds)
        async with self._uow() as uow:
            actor_id, admin_role_id = await self._school_actor_role(
                uow, actor, "admin", now, lock=True
            )
            ticket = await uow.session.scalar(
                self._select(m.SchoolPasswordRecoveryTicket)
                .where(
                    m.SchoolPasswordRecoveryTicket.ticket_ref == ticket_ref,
                    m.SchoolPasswordRecoveryTicket.school_id == actor.school_id,
                )
                .with_for_update()
            )
            if (
                ticket is None
                or ticket.status != "TEACHER_VERIFIED"
                or ticket.verified_at is None
                or ticket.verified_by_membership_role_id is None
            ):
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT, detail="recovery request cannot be approved"
                )
            account = await uow.session.scalar(
                self._select(m.Account).where(m.Account.id == ticket.account_id).with_for_update()
            )
            if account is None or account.status != self._db_enums.AccountStatus.ACTIVE.value:
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT, detail="recovery request cannot be approved"
                )
            previous = list(
                (
                    await uow.session.scalars(
                        self._select(m.SchoolAccountCredential)
                        .where(
                            m.SchoolAccountCredential.account_id == account.id,
                            m.SchoolAccountCredential.school_id == actor.school_id,
                            m.SchoolAccountCredential.status == "ISSUED",
                        )
                        .with_for_update()
                    )
                ).all()
            )
            for old in previous:
                old.status = "REVOKED"
                old.revoked_at = now
            credential_ref = f"CRED_{uuid4().hex}"
            uow.session.add(
                m.SchoolAccountCredential(
                    credential_ref=credential_ref,
                    account_id=account.id,
                    school_id=actor.school_id,
                    issued_by_membership_role_id=admin_role_id,
                    purpose="PASSWORD_RESET",
                    resource_ref=ticket.public_id,
                    token_hash=token_hash,
                    status="ISSUED",
                    delivery_channel="MANUAL",
                    expires_at=expires_at,
                    trace_id=trace_id,
                )
            )
            ticket.status = "APPROVED"
            ticket.approved_by_membership_role_id = admin_role_id
            ticket.approved_at = now
            ticket.expires_at = expires_at
            ticket.credential_ref = credential_ref
            account.must_change_password = True
            await self._revoke_sessions(uow, account.id, now, "PASSWORD_RESET_APPROVED")
            await uow.session.flush()
            await self._audit(
                uow,
                actor_account_id=actor_id,
                action="school_account_lifecycle.recovery.approve",
                resource_type="school_password_recovery_ticket",
                resource_ref=ticket.public_id,
                trace_id=trace_id,
                metadata={"reason_code": reason_code},
            )
            return {"credential": raw_token, "expires_at": expires_at, "status": "APPROVED"}

    async def complete_password_reset(
        self,
        *,
        school_ref: str,
        username: str,
        token_hash: bytes,
        new_password: str,
        trace_id: str,
    ) -> dict[str, str]:
        from sqlalchemy import func

        m = self._db_models
        e = self._db_enums
        now = self._utc_now()
        async with self._uow() as uow:
            account = await uow.session.scalar(
                self._select(m.Account)
                .join(
                    m.AccountSchoolMembership, m.AccountSchoolMembership.account_id == m.Account.id
                )
                .join(m.School, m.School.id == m.AccountSchoolMembership.school_id)
                .where(
                    func.lower(m.Account.login_name) == username.strip().casefold(),
                    m.School.school_ref == school_ref.strip(),
                    m.School.data_origin == e.DataOrigin.SYNTHETIC.value,
                    m.AccountSchoolMembership.status == "ACTIVE",
                    m.AccountSchoolMembership.revoked_at.is_(None),
                    m.Account.status == e.AccountStatus.ACTIVE.value,
                )
                .with_for_update()
            )
            if account is None:
                raise self._generic_credential_error()
            credential = await uow.session.scalar(
                self._select(m.SchoolAccountCredential)
                .join(m.School, m.School.id == m.SchoolAccountCredential.school_id)
                .where(
                    m.SchoolAccountCredential.account_id == account.id,
                    m.School.school_ref == school_ref.strip(),
                    m.SchoolAccountCredential.token_hash == token_hash,
                    m.SchoolAccountCredential.purpose == "PASSWORD_RESET",
                    m.SchoolAccountCredential.status == "ISSUED",
                    m.SchoolAccountCredential.expires_at > now,
                )
                .with_for_update()
            )
            if credential is None:
                raise self._generic_credential_error()
            ticket = await uow.session.scalar(
                self._select(m.SchoolPasswordRecoveryTicket)
                .where(
                    m.SchoolPasswordRecoveryTicket.credential_ref == credential.credential_ref,
                    m.SchoolPasswordRecoveryTicket.status == "APPROVED",
                    m.SchoolPasswordRecoveryTicket.expires_at > now,
                )
                .with_for_update()
            )
            staff_recovery_ref = f"{STAFF_RECOVERY_RESOURCE_PREFIX}{account.public_id}"
            is_staff_recovery = credential.resource_ref == staff_recovery_ref
            if not account.must_change_password:
                raise self._generic_credential_error()
            if ticket is None and is_staff_recovery:
                staff_role_codes = set(
                    (
                        await uow.session.scalars(
                            self._select(m.MembershipRole.role_code)
                            .join(
                                m.AccountSchoolMembership,
                                m.AccountSchoolMembership.id == m.MembershipRole.membership_id,
                            )
                            .where(
                                m.AccountSchoolMembership.account_id == account.id,
                                m.AccountSchoolMembership.school_id == credential.school_id,
                                m.AccountSchoolMembership.status == "ACTIVE",
                                m.AccountSchoolMembership.revoked_at.is_(None),
                                m.AccountSchoolMembership.valid_from <= now,
                                (m.AccountSchoolMembership.valid_until.is_(None))
                                | (m.AccountSchoolMembership.valid_until >= now),
                                m.MembershipRole.school_id == credential.school_id,
                                m.MembershipRole.status == "ACTIVE",
                                m.MembershipRole.revoked_at.is_(None),
                                m.MembershipRole.valid_from <= now,
                                (m.MembershipRole.valid_until.is_(None))
                                | (m.MembershipRole.valid_until >= now),
                            )
                        )
                    ).all()
                )
                verified_invitation = await uow.session.scalar(
                    self._select(m.SchoolStaffInvitation.id)
                    .where(
                        m.SchoolStaffInvitation.account_id == account.id,
                        m.SchoolStaffInvitation.school_id == credential.school_id,
                        m.SchoolStaffInvitation.status == "ACCEPTED",
                        m.SchoolStaffInvitation.work_contact_verified_at.is_not(None),
                    )
                    .limit(1)
                )
                if (
                    not staff_role_codes.intersection({"teacher", "psychological_specialist"})
                    or staff_role_codes.intersection({"admin", "student"})
                    or verified_invitation is None
                ):
                    raise self._generic_credential_error()
            elif (
                ticket is None
                or ticket.status != "APPROVED"
                or ticket.expires_at is None
                or ticket.expires_at <= now
            ):
                raise self._generic_credential_error()
            account.password_hash = PasswordHash.recommended().hash(new_password)
            account.must_change_password = False
            account.password_changed_at = now
            account.failed_login_count = 0
            account.locked_until = None
            credential.status = "CONSUMED"
            credential.consumed_at = now
            if ticket is not None:
                ticket.status = "COMPLETED"
                ticket.completed_at = now
            others = list(
                (
                    await uow.session.scalars(
                        self._select(m.SchoolAccountCredential)
                        .where(
                            m.SchoolAccountCredential.account_id == account.id,
                            m.SchoolAccountCredential.status == "ISSUED",
                            m.SchoolAccountCredential.id != credential.id,
                        )
                        .with_for_update()
                    )
                ).all()
            )
            for other in others:
                other.status = "REVOKED"
                other.revoked_at = now
            await self._revoke_sessions(uow, account.id, now, "PASSWORD_RESET_COMPLETED")
            await uow.session.flush()
            if is_staff_recovery:
                audit_action = "school_account_lifecycle.staff_recovery.complete"
                audit_resource_type = "account"
                audit_resource_ref = account.public_id
            elif ticket is not None:
                audit_action = "school_account_lifecycle.password_reset.complete"
                audit_resource_type = "school_password_recovery_ticket"
                audit_resource_ref = ticket.public_id
            else:
                raise self._generic_credential_error()
            await self._audit(
                uow,
                actor_account_id=None,
                action=audit_action,
                resource_type=audit_resource_type,
                resource_ref=audit_resource_ref,
                trace_id=trace_id,
                metadata={},
            )
            return {"status": "PASSWORD_RESET"}

    async def set_account_status(
        self,
        actor: Any,
        user_ref: str,
        *,
        status: str,
        reason_code: str,
        trace_id: str,
    ) -> dict[str, str]:
        m = self._db_models
        e = self._db_enums
        now = self._utc_now()
        try:
            public_id = self._public_id(user_ref, "USER")
        except ValueError:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="account was not found") from None
        async with self._uow() as uow:
            actor_id, _role_id = await self._school_actor_role(uow, actor, "admin", now, lock=True)
            account = await uow.session.scalar(
                self._select(m.Account).where(m.Account.public_id == public_id).with_for_update()
            )
            if account is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="account was not found")
            memberships = list(
                (
                    await uow.session.scalars(
                        self._select(m.AccountSchoolMembership)
                        .where(m.AccountSchoolMembership.account_id == account.id)
                        .order_by(m.AccountSchoolMembership.school_id)
                        .with_for_update()
                    )
                ).all()
            )
            target_memberships = [item for item in memberships if item.school_id == actor.school_id]
            if len(target_memberships) != 1 or len(memberships) != 1:
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT,
                    detail="account status cannot be changed while linked to another school",
                )
            membership = target_memberships[0]
            if membership.revoked_at is not None or membership.status == "REVOKED":
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="account status cannot be changed")
            roles = list(
                (
                    await uow.session.scalars(
                        self._select(m.MembershipRole)
                        .where(m.MembershipRole.membership_id == membership.id)
                        .with_for_update()
                    )
                ).all()
            )
            if not any(role.status == "ACTIVE" and role.role_code == "admin" for role in roles):
                target_is_admin = False
            else:
                target_is_admin = True
            if status == "DISABLED" and target_is_admin:
                from sqlalchemy import func, or_

                active_admins = await uow.session.scalar(
                    self._select(func.count(func.distinct(m.Account.id)))
                    .join(
                        m.AccountSchoolMembership,
                        m.AccountSchoolMembership.account_id == m.Account.id,
                    )
                    .join(
                        m.MembershipRole,
                        m.MembershipRole.membership_id == m.AccountSchoolMembership.id,
                    )
                    .where(
                        m.AccountSchoolMembership.school_id == actor.school_id,
                        m.AccountSchoolMembership.status == "ACTIVE",
                        m.AccountSchoolMembership.revoked_at.is_(None),
                        m.AccountSchoolMembership.valid_from <= now,
                        (m.AccountSchoolMembership.valid_until.is_(None))
                        | (m.AccountSchoolMembership.valid_until >= now),
                        m.Account.status == e.AccountStatus.ACTIVE.value,
                        m.Account.must_change_password.is_(False),
                        or_(m.Account.locked_until.is_(None), m.Account.locked_until <= now),
                        m.MembershipRole.role_code == "admin",
                        m.MembershipRole.status == "ACTIVE",
                        m.MembershipRole.revoked_at.is_(None),
                        m.MembershipRole.valid_from <= now,
                        (m.MembershipRole.valid_until.is_(None))
                        | (m.MembershipRole.valid_until >= now),
                    )
                )
                if int(active_admins or 0) <= 1:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT,
                        detail="at least one active school administrator is required",
                    )
            account.status = (
                e.AccountStatus.DISABLED.value
                if status == "DISABLED"
                else e.AccountStatus.ACTIVE.value
            )
            membership.status = "ACTIVE"
            if status == "DISABLED":
                await self._revoke_sessions(uow, account.id, now, "ACCOUNT_DISABLED")
                credentials = list(
                    (
                        await uow.session.scalars(
                            self._select(m.SchoolAccountCredential)
                            .where(
                                m.SchoolAccountCredential.account_id == account.id,
                                m.SchoolAccountCredential.school_id == actor.school_id,
                                m.SchoolAccountCredential.status == "ISSUED",
                            )
                            .order_by(m.SchoolAccountCredential.id)
                            .with_for_update()
                        )
                    ).all()
                )
                for credential in credentials:
                    credential.status = "REVOKED"
                    credential.revoked_at = now
                open_tickets = list(
                    (
                        await uow.session.scalars(
                            self._select(m.SchoolPasswordRecoveryTicket)
                            .where(
                                m.SchoolPasswordRecoveryTicket.account_id == account.id,
                                m.SchoolPasswordRecoveryTicket.school_id == actor.school_id,
                                m.SchoolPasswordRecoveryTicket.status.in_(
                                    ("REQUESTED", "TEACHER_VERIFIED", "APPROVED")
                                ),
                            )
                            .order_by(m.SchoolPasswordRecoveryTicket.id)
                            .with_for_update()
                        )
                    ).all()
                )
                for ticket in open_tickets:
                    ticket.status = "EXPIRED"
                    ticket.expires_at = now
            await uow.session.flush()
            await self._audit(
                uow,
                actor_account_id=actor_id,
                action=f"school_account_lifecycle.account.{status.lower()}",
                resource_type="account",
                resource_ref=account.public_id,
                trace_id=trace_id,
                metadata={"reason_code": reason_code},
            )
            return {"status": status}
