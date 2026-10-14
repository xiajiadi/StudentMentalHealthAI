"""Thin in-process adapter from Backend ports to the existing Database layer.

The adapter deliberately owns no domain policy.  It translates Backend's
opaque ``USER_*``/``ASSESS_*``/``REPORT_*`` references to the Database layer's
public identifiers and keeps every unit of work short-lived.  In particular,
the support workflow creates a durable REQUESTED run before external calls and
finishes it in a separate transaction after the Safety decision.

The Database package is imported lazily so the isolated Backend/fake test mode
does not need to install database-only dependencies.  Real integration runs
put ``11_database`` and its isolated environment on ``PYTHONPATH``.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pwdlib import PasswordHash

from smhai_backend.core.config import school_csrf_secret_bytes
from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.support_diagnostics import sanitize_support_stage_diagnostics
from smhai_backend.domains.models import (
    AssessmentRecord,
    AuditEvent,
    BackendRole,
    IdempotencyRecord,
    ReportRecord,
    ReviewProjection,
    SchoolRoleContext,
    SessionRecord,
    SyntheticUser,
)

REQUIRED_DATABASE_REVISION = "20261011_0005"
REQUIRED_SCHOOL_TENANT_DATABASE_REVISION = "20261014_0016"
_SCHOOL_CAT_BANK_DOCUMENT_SCHEMA = "school_cat_bank_document.v1"
_SCHOOL_CAT_CONFIG_DOCUMENT_SCHEMA = "school_cat_config_document.v1"
_SCHOOL_POST_ASSESSMENT_POLICY_VERSION = "NO_PERSONALIZED_POLICY_V1"
_LEGACY_CSRF_SECRET = b"smhai-round1-synthetic-csrf-secret"


@dataclass(frozen=True, slots=True)
class SchoolIdempotencyClaim:
    record: Any
    replayed: bool


def _create_data_protection_provider(identity_profile: str, repository_root: Path) -> Any:
    if identity_profile not in {"legacy_demo", "school_tenant"}:
        raise RuntimeError("unsupported database identity profile")

    from database_layer import (
        DevLocalKeyProvider,
        FernetDataProtectionProvider,
        WindowsDpapiKeyProvider,
    )

    if identity_profile == "school_tenant":
        return FernetDataProtectionProvider(
            WindowsDpapiKeyProvider.from_env(repository_root=repository_root)
        )

    return FernetDataProtectionProvider(
        DevLocalKeyProvider.from_env(repository_root=repository_root)
    )


def _csrf_secret_for_profile(identity_profile: str, school_csrf_secret: str | None) -> bytes:
    if identity_profile == "legacy_demo":
        return _LEGACY_CSRF_SECRET
    if identity_profile == "school_tenant":
        return school_csrf_secret_bytes(school_csrf_secret)
    raise RuntimeError("unsupported database identity profile")


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _as_datetime(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo else parsed


def _database_utc_datetime(value: datetime | None) -> datetime | None:
    """Attach UTC semantics to timezone-naive UTC database timestamps."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _as_timestamp(value: datetime | None) -> float:
    if value is None:
        return 0.0
    return value.replace(tzinfo=UTC).timestamp()


def _hash_token(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def _backend_user_id(public_id: str) -> str:
    return f"USER_{public_id}"


def _database_public_id(value: str, prefix: str) -> str:
    if not value.startswith(f"{prefix}_"):
        raise ValueError(f"unsupported {prefix} reference")
    return value.removeprefix(f"{prefix}_")


class MySqlBackendAdapter:
    """Concrete implementation of all Backend persistence ports.

    One instance is shared by the container, but every method opens its own
    ``SqlAlchemyUnitOfWork``.  No method awaits CAT, RAG, LLM Runtime, Safety,
    or any other external dependency while a unit of work is active.
    """

    label = "MYSQL"

    def __init__(
        self,
        *,
        repository_root: Path | None = None,
        identity_profile: str = "legacy_demo",
        school_csrf_secret: str | None = None,
    ) -> None:
        csrf_secret_bytes = _csrf_secret_for_profile(identity_profile, school_csrf_secret)
        try:
            from database_layer import (
                DatabaseSettings,
                SqlAlchemyUnitOfWork,
                create_engine,
                create_session_factory,
            )
            from database_layer import enums as db_enums
            from database_layer import models as db_models
            from database_layer.base import utc_now
            from database_layer.errors import NotFound as DatabaseNotFound
            from database_layer.seed import seed_reference_roles
        except ImportError as exc:  # pragma: no cover - exercised by setup probes
            raise RuntimeError(
                "Database layer dependencies are unavailable; configure the isolated "
                "database runtime"
            ) from exc

        from sqlalchemy import select
        from sqlalchemy.exc import IntegrityError

        self._select = select
        self._integrity_error = IntegrityError
        self._db_enums = db_enums
        self._db_models = db_models
        self._db_not_found = DatabaseNotFound
        self._utc_now = utc_now
        self._uow_type = SqlAlchemyUnitOfWork
        self.settings = DatabaseSettings.from_env()
        root = (repository_root or Path(__file__).resolve().parents[4]).resolve()
        protection = _create_data_protection_provider(identity_profile, root)
        self.engine = create_engine(self.settings)
        self.session_factory = create_session_factory(self.engine)
        self.protection = protection
        self._started = False
        self.identity_profile = identity_profile
        self._idempotency_bodies: dict[tuple[str, str], dict[str, Any]] = {}
        self._metadata_records: list[dict[str, Any]] = []
        self._audit_cache: list[AuditEvent] = []
        self._csrf_secret = csrf_secret_bytes

        self._seed_reference_roles = seed_reference_roles

    def _uow(self) -> Any:
        return self._uow_type(self.session_factory, self.protection)

    @staticmethod
    def _decrypt_school_cat_document(uow: Any, row: Any, schema_version: str) -> dict[str, Any]:
        from database_layer.crypto import EncryptedPayload

        if (
            not isinstance(row.payload_ciphertext, bytes)
            or not row.key_version
            or row.cipher_format_version != uow.protection.cipher_format_version
            or row.payload_schema_version != schema_version
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="saved CAT version is unavailable",
            )
        try:
            value = uow.protection.decrypt_json(
                EncryptedPayload(
                    ciphertext=row.payload_ciphertext,
                    key_version=row.key_version,
                    cipher_format_version=row.cipher_format_version,
                    payload_schema_version=row.payload_schema_version,
                )
            )
        except Exception as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="saved CAT version is unavailable",
            ) from exc
        if not isinstance(value, dict):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="saved CAT version is unavailable",
            )
        return value

    @staticmethod
    def _school_cat_instrument_version(bank_document: Mapping[str, Any]) -> Any:
        metadata = bank_document.get("metadata")
        if metadata is None:
            return bank_document.get("version")
        if not isinstance(metadata, Mapping):
            return None
        return metadata.get("instrument_version", bank_document.get("version"))

    async def _task_cat_binding_fields(self, uow: Any, actor: Any, task: Any) -> dict[str, Any]:
        m = self._db_models
        mode = task.cat_binding_mode
        if mode == "FIXTURE":
            from smhai_backend.domains.assessment.binding import D3_IDENTITY

            if (
                task.instrument_id != D3_IDENTITY.instrument_id
                or task.instrument_version != D3_IDENTITY.instrument_version
                or task.item_bank_version is not None
                or task.config_version is not None
            ):
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT,
                    detail="fixture task CAT metadata is unsupported",
                )
            unexpected = await uow.session.scalar(
                self._select(m.SchoolCatTaskBinding).where(
                    m.SchoolCatTaskBinding.school_id == actor.school_id,
                    m.SchoolCatTaskBinding.task_id == task.id,
                )
            )
            if unexpected is not None:
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="task CAT binding is inconsistent")
            return {"activation_ref": None, "plan_name": None, "plan_version_number": None}
        if mode != "SAVED_VERSION":
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="task CAT binding mode is invalid")
        binding = await uow.session.scalar(
            self._select(m.SchoolCatTaskBinding).where(
                m.SchoolCatTaskBinding.school_id == actor.school_id,
                m.SchoolCatTaskBinding.task_id == task.id,
            )
        )
        if binding is None:
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="saved task CAT binding is unavailable")
        activation = await uow.session.scalar(
            self._select(m.SchoolCatActivation).where(
                m.SchoolCatActivation.id == binding.activation_id,
                m.SchoolCatActivation.school_id == actor.school_id,
                m.SchoolCatActivation.plan_version_id == binding.plan_version_id,
            )
        )
        plan_version = await uow.session.scalar(
            self._select(m.SchoolCatPlanVersion).where(
                m.SchoolCatPlanVersion.id == binding.plan_version_id,
                m.SchoolCatPlanVersion.school_id == actor.school_id,
            )
        )
        if activation is None or plan_version is None:
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="saved task CAT binding is unavailable")
        plan = await uow.session.scalar(
            self._select(m.SchoolCatPlan).where(
                m.SchoolCatPlan.id == plan_version.plan_id,
                m.SchoolCatPlan.school_id == actor.school_id,
            )
        )
        if plan is None:
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="saved task CAT plan is unavailable")
        if (
            task.instrument_id == ""
            or task.instrument_version == ""
            or task.item_bank_version is None
            or task.config_version is None
        ):
            raise error(
                ErrorCode.WORKFLOW_CONFLICT,
                detail="saved task CAT metadata is unavailable",
            )
        return {
            "activation_ref": f"CACT_{activation.public_id}",
            "plan_name": plan.display_name,
            "plan_version_number": int(plan_version.version_number),
        }

    async def _school_task_assessment_binding(
        self,
        uow: Any,
        actor: Any,
        task: Any,
        enrollment: Any,
        session: Any,
        *,
        at: datetime,
        lock_bindings: bool = False,
    ) -> dict[str, Any]:
        m = self._db_models
        mode = task.cat_binding_mode
        require_active = session.status == "CREATED"
        if session.cat_binding_mode != mode:
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="task CAT binding mode changed")
        task_binding_statement = self._select(m.SchoolCatTaskBinding).where(
            m.SchoolCatTaskBinding.school_id == actor.school_id,
            m.SchoolCatTaskBinding.task_id == task.id,
        )
        session_binding_statement = self._select(m.SchoolCatSessionBinding).where(
            m.SchoolCatSessionBinding.school_id == actor.school_id,
            m.SchoolCatSessionBinding.assessment_session_id == session.id,
        )
        if lock_bindings:
            task_binding_statement = task_binding_statement.with_for_update()
            session_binding_statement = session_binding_statement.with_for_update()
        task_binding = await uow.session.scalar(task_binding_statement)
        session_binding = await uow.session.scalar(session_binding_statement)
        if mode == "FIXTURE":
            from smhai_backend.domains.assessment.binding import D3_IDENTITY

            if (
                task.instrument_id != D3_IDENTITY.instrument_id
                or task.instrument_version != D3_IDENTITY.instrument_version
                or task.item_bank_version is not None
                or task.config_version is not None
                or task_binding is not None
                or session_binding is not None
            ):
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT,
                    detail="fixture CAT binding is inconsistent",
                )
            return {
                "task_enrollment_id": int(enrollment.id),
                "cat_binding_mode": "FIXTURE",
                "saved_binding": None,
                "saved_bank_document": None,
                "saved_config_document": None,
            }
        if mode != "SAVED_VERSION" or task_binding is None or session_binding is None:
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="saved CAT binding is unavailable")
        if (
            task_binding.school_id != actor.school_id
            or task_binding.task_id != task.id
            or session_binding.task_id != task.id
            or session_binding.task_enrollment_id != enrollment.id
            or session_binding.subject_id != session.subject_id
            or session_binding.task_binding_id != task_binding.id
            or session_binding.activation_id != task_binding.activation_id
            or session_binding.plan_version_id != task_binding.plan_version_id
        ):
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="saved CAT binding is inconsistent")
        activation_statement = self._select(m.SchoolCatActivation).where(
                m.SchoolCatActivation.id == session_binding.activation_id,
                m.SchoolCatActivation.school_id == actor.school_id,
                m.SchoolCatActivation.plan_version_id == session_binding.plan_version_id,
            )
        if require_active:
            activation_statement = activation_statement.with_for_update()
        activation = await uow.session.scalar(activation_statement)
        plan_version = await uow.session.scalar(
            self._select(m.SchoolCatPlanVersion).where(
                m.SchoolCatPlanVersion.id == session_binding.plan_version_id,
                m.SchoolCatPlanVersion.school_id == actor.school_id,
            )
        )
        if activation is None or plan_version is None:
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="saved CAT version is unavailable")
        plan_statement = self._select(m.SchoolCatPlan).where(
                m.SchoolCatPlan.id == plan_version.plan_id,
                m.SchoolCatPlan.school_id == actor.school_id,
            )
        if require_active:
            plan_statement = plan_statement.with_for_update()
        plan = await uow.session.scalar(plan_statement)
        bank_version = await uow.session.scalar(
            self._select(m.SchoolCatItemBankVersion).where(
                m.SchoolCatItemBankVersion.id == plan_version.bank_version_id,
                m.SchoolCatItemBankVersion.school_id == actor.school_id,
            )
        )
        bank_statement = self._select(m.SchoolCatItemBank).where(
                m.SchoolCatItemBank.id == bank_version.bank_id,
                m.SchoolCatItemBank.school_id == actor.school_id,
            ) if bank_version is not None else None
        if require_active and bank_statement is not None:
            bank_statement = bank_statement.with_for_update()
        bank = await uow.session.scalar(bank_statement) if bank_statement is not None else None
        if plan is None or bank_version is None or bank is None:
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="saved CAT version is unavailable")
        if require_active and (
            activation.status != "ACTIVE" or plan.status != "ACTIVE" or bank.status != "ACTIVE"
        ):
            raise error(
                ErrorCode.WORKFLOW_CONFLICT,
                detail="saved CAT activation is no longer eligible for a new assessment",
            )
        binding_ref = f"CSBIND_{session_binding.public_id}"
        saved_binding = {
            "binding_ref": binding_ref,
            "activation_ref": f"CACT_{activation.public_id}",
            "plan_version_ref": f"CPVER_{plan_version.public_id}",
            "bank_version_ref": f"CBVER_{bank_version.public_id}",
        }
        bank_document = config_document = None
        if session.status in {"CREATED", "IN_PROGRESS"}:
            bank_document = self._decrypt_school_cat_document(
                uow, bank_version, _SCHOOL_CAT_BANK_DOCUMENT_SCHEMA
            )
            config_document = self._decrypt_school_cat_document(
                uow, plan_version, _SCHOOL_CAT_CONFIG_DOCUMENT_SCHEMA
            )
            if (
                bank_document.get("instrument_id") != task.instrument_id
                or self._school_cat_instrument_version(bank_document)
                != task.instrument_version
                or task.item_bank_version != bank_document.get("version")
                or task.config_version != config_document.get("config_version")
            ):
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="saved CAT task identity changed")
        return {
            "task_enrollment_id": int(enrollment.id),
            "cat_binding_mode": "SAVED_VERSION",
            "saved_binding": saved_binding,
            "saved_bank_document": bank_document,
            "saved_config_document": config_document,
        }

    async def _lock_school_assessment_write_scope(
        self,
        uow: Any,
        actor: Any,
        account_id: int,
        enrollment: Any,
        *,
        at: datetime,
    ) -> tuple[Any, Any, Any]:
        """Lock the current task authorization rows before a student write."""
        m = self._db_models
        # Keep this order aligned with revoke_class_student_link: it locks the
        # roster row before updating all active enrollments for that link.
        roster = await uow.session.scalar(
            self._select(m.SchoolClassStudent)
            .where(
                m.SchoolClassStudent.id == enrollment.class_student_id,
                m.SchoolClassStudent.school_id == actor.school_id,
                m.SchoolClassStudent.class_id == enrollment.class_id,
                m.SchoolClassStudent.subject_id == enrollment.subject_id,
                m.SchoolClassStudent.status == "ACTIVE",
                m.SchoolClassStudent.revoked_at.is_(None),
                m.SchoolClassStudent.valid_from <= at,
                (m.SchoolClassStudent.valid_until.is_(None))
                | (m.SchoolClassStudent.valid_until >= at),
            )
            .with_for_update()
        )
        if roster is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="assessment access is unavailable")
        enrollment = await uow.session.scalar(
            self._select(m.TaskEnrollment)
            .where(
                m.TaskEnrollment.id == enrollment.id,
                m.TaskEnrollment.school_id == actor.school_id,
                m.TaskEnrollment.class_student_id == roster.id,
                m.TaskEnrollment.status == "ACTIVE",
            )
            .with_for_update()
        )
        if enrollment is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="assessment access is unavailable")
        school_class = await uow.session.scalar(
            self._select(m.SchoolClass)
            .where(
                m.SchoolClass.id == enrollment.class_id,
                m.SchoolClass.school_id == actor.school_id,
                m.SchoolClass.status == "ACTIVE",
            )
            .with_for_update()
        )
        task = await uow.session.scalar(
            self._select(m.MeasurementTask)
            .where(
                m.MeasurementTask.id == enrollment.task_id,
                m.MeasurementTask.school_id == actor.school_id,
                m.MeasurementTask.class_id == enrollment.class_id,
                m.MeasurementTask.status == "PUBLISHED",
                m.MeasurementTask.opens_at <= at,
                (m.MeasurementTask.due_at.is_(None)) | (m.MeasurementTask.due_at >= at),
            )
            .with_for_update()
        )
        subject = await uow.session.scalar(
            self._select(m.Subject)
            .where(
                m.Subject.id == enrollment.subject_id,
                m.Subject.school_id == actor.school_id,
                m.Subject.status == self._db_enums.SubjectStatus.ACTIVE.value,
                m.Subject.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
            )
            .with_for_update()
        )
        access_grant = await uow.session.scalar(
            self._select(m.SubjectAccessGrant)
            .where(
                m.SubjectAccessGrant.subject_id == enrollment.subject_id,
                m.SubjectAccessGrant.school_id == actor.school_id,
                m.SubjectAccessGrant.principal_account_id == account_id,
                m.SubjectAccessGrant.relationship_type == "SELF",
                m.SubjectAccessGrant.status == "ACTIVE",
                m.SubjectAccessGrant.revoked_at.is_(None),
                m.SubjectAccessGrant.valid_from <= at,
                (m.SubjectAccessGrant.valid_until.is_(None))
                | (m.SubjectAccessGrant.valid_until >= at),
            )
            .with_for_update()
        )
        if any(value is None for value in (roster, school_class, task, subject, access_grant)):
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="assessment access is unavailable")
        return enrollment, task, subject

    def _optional_identity_specs(self) -> tuple[tuple[str, str], ...]:
        if self.identity_profile != "legacy_demo":
            return ()
        return (
            ("admin", "SMHAI_M0_ADMIN"),
            ("psychological_specialist", "SMHAI_M0_SPECIALIST"),
        )

    async def start(self) -> None:
        try:
            await self._require_database_revision()
            await self._ensure_synthetic_fixtures()
        except Exception:
            try:
                await self.engine.dispose()
            except Exception:
                pass
            raise
        self._started = True

    async def close(self) -> None:
        if self._started:
            await self.engine.dispose()
            self._started = False

    # ------------------------------------------------------------------
    # Synthetic identity and authorization projection
    # ------------------------------------------------------------------

    async def _require_database_revision(self) -> None:
        """Fail fast unless this isolated runtime schema is at the reviewed head."""

        try:
            async with self.engine.connect() as connection:
                result = await connection.exec_driver_sql(
                    "SELECT version_num FROM database_alembic_version"
                )
                revisions = list(result.scalars().all())
        except Exception:
            required_revision = (
                REQUIRED_SCHOOL_TENANT_DATABASE_REVISION
                if self.identity_profile == "school_tenant"
                else REQUIRED_DATABASE_REVISION
            )
            raise RuntimeError(
                "Database schema revision is missing or unsupported; this runtime does not "
                "perform migrations. Provision an isolated synthetic workspace at revision "
                f"{required_revision}."
            ) from None
        required_revision = (
            REQUIRED_SCHOOL_TENANT_DATABASE_REVISION
            if self.identity_profile == "school_tenant"
            else REQUIRED_DATABASE_REVISION
        )
        if revisions != [required_revision]:
            raise RuntimeError(
                "Database schema revision is missing or unsupported; this runtime does not "
                "perform migrations. Provision an isolated synthetic workspace at revision "
                f"{required_revision}."
            )

    def _school_actor_ref(self, actor: Any) -> str:
        if (
            self.identity_profile != "school_tenant"
            or actor.scope_profile != "school_tenant"
            or actor.school_id is None
            or actor.school_ref is None
        ):
            raise error(ErrorCode.FORBIDDEN, detail="access denied")
        try:
            return _database_public_id(actor.user_id, "USER")
        except ValueError:
            raise error(ErrorCode.FORBIDDEN, detail="access denied") from None

    async def _school_idempotency_begin(self, uow, idempotency):
        if idempotency is None:
            raise error(ErrorCode.VALIDATION_FAILED, detail="Idempotency-Key is required")
        key, request_fingerprint, scope = idempotency
        m = self._db_models
        key_hash = _hash_token(key)
        now = self._utc_now()
        row = await uow.session.scalar(
            self._select(m.IdempotencyRecord)
            .where(
                m.IdempotencyRecord.scope == scope,
                m.IdempotencyRecord.key_hash == key_hash,
            )
            .with_for_update()
        )
        request_hash = bytes.fromhex(request_fingerprint)
        if row is not None and row.expires_at > now:
            if row.request_hash != request_hash:
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT,
                    detail="idempotency key was already used for another request",
                )
            if row.state == self._db_enums.IdempotencyState.COMPLETED.value:
                return SchoolIdempotencyClaim(record=row, replayed=True)
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="idempotency request is in progress")
        if row is None:
            row = m.IdempotencyRecord(
                scope=scope,
                key_hash=key_hash,
                request_hash=request_hash,
                state=self._db_enums.IdempotencyState.IN_PROGRESS.value,
                expires_at=now + timedelta(hours=24),
            )
            uow.session.add(row)
        else:
            row.request_hash = request_hash
            row.state = self._db_enums.IdempotencyState.IN_PROGRESS.value
            row.result_resource_type = None
            row.result_public_id = None
            row.expires_at = now + timedelta(hours=24)
        try:
            await uow.session.flush()
        except self._integrity_error as exc:
            raise error(
                ErrorCode.WORKFLOW_CONFLICT,
                detail="idempotency request is already in progress",
            ) from exc
        return SchoolIdempotencyClaim(record=row, replayed=False)

    async def _school_idempotency_complete(
        self, uow, claim: SchoolIdempotencyClaim, *, resource_type: str, result_ref: str
    ) -> None:
        if claim.replayed or claim.record is None:
            raise RuntimeError("only a newly claimed school write can complete its receipt")
        row = claim.record
        if row.state != self._db_enums.IdempotencyState.IN_PROGRESS.value:
            raise RuntimeError("school idempotency receipt is not in progress")
        row.state = self._db_enums.IdempotencyState.COMPLETED.value
        row.result_resource_type = resource_type
        row.result_public_id = result_ref
        await uow.session.flush()

    async def _school_actor_role(
        self, uow, actor: Any, role_code: str, at: datetime, *, lock: bool = False
    ) -> tuple[int, int]:
        """Resolve account and active role from the server actor and persisted membership."""
        m = self._db_models
        public_id = self._school_actor_ref(actor)
        statement = (
            self._select(m.Account.id, m.MembershipRole.id)
            .join(m.AccountSchoolMembership, m.AccountSchoolMembership.account_id == m.Account.id)
            .join(m.MembershipRole, m.MembershipRole.membership_id == m.AccountSchoolMembership.id)
            .join(m.School, m.School.id == m.AccountSchoolMembership.school_id)
            .where(
                m.Account.public_id == public_id,
                m.Account.status == self._db_enums.AccountStatus.ACTIVE.value,
                m.AccountSchoolMembership.school_id == actor.school_id,
                m.AccountSchoolMembership.status == "ACTIVE",
                m.AccountSchoolMembership.revoked_at.is_(None),
                m.AccountSchoolMembership.valid_from <= at,
                (m.AccountSchoolMembership.valid_until.is_(None))
                | (m.AccountSchoolMembership.valid_until >= at),
                m.MembershipRole.school_id == actor.school_id,
                m.MembershipRole.role_code == role_code,
                m.MembershipRole.status == "ACTIVE",
                m.MembershipRole.revoked_at.is_(None),
                m.MembershipRole.valid_from <= at,
                (m.MembershipRole.valid_until.is_(None)) | (m.MembershipRole.valid_until >= at),
                m.School.school_ref == actor.school_ref,
                m.School.status == "ACTIVE",
                m.School.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
            )
            .limit(2)
        )
        if lock:
            statement = statement.with_for_update()
        rows = list((await uow.session.execute(statement)).all())
        if len(rows) != 1:
            raise error(ErrorCode.FORBIDDEN, detail="access denied")
        contexts = [
            context
            for context in actor.school_contexts
            if context.role.value.lower() == role_code
            and context.school_id == actor.school_id
            and context.school_ref == actor.school_ref
        ]
        if len(contexts) != 1 or str(rows[0][1]) != contexts[0].context_id:
            raise error(ErrorCode.FORBIDDEN, detail="access denied")
        return int(rows[0][0]), int(rows[0][1])

    async def school_list_classes(self, actor: Any) -> list[dict[str, Any]]:
        from sqlalchemy import func

        m = self._db_models
        now = self._utc_now()
        _account_id, _role_id = None, None
        async with self._uow() as uow:
            _account_id, _role_id = await self._school_actor_role(uow, actor, "admin", now)
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
            rows = (
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
            return [
                dict(
                    class_ref=row[0],
                    display_name=row[1],
                    status=row[2],
                    active_student_count=int(row[3]),
                    active_teacher_count=int(row[4]),
                )
                for row in rows
            ]

    async def school_create_class(
        self, actor: Any, class_ref: str, *, at: datetime, idempotency=None
    ) -> dict[str, Any]:
        async with self._uow() as uow:
            account_id, role_id = await self._school_actor_role(uow, actor, "admin", at)
            claim = await self._school_idempotency_begin(uow, idempotency)
            if claim.replayed:
                existing = await uow.session.scalar(
                    self._select(self._db_models.SchoolClass).where(
                        self._db_models.SchoolClass.school_id == actor.school_id,
                        self._db_models.SchoolClass.class_ref == class_ref,
                    )
                )
                if existing is None:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT, detail="idempotency result is unavailable"
                    )
                return {
                    "class_ref": existing.class_ref,
                    "status": existing.status,
                    "active_student_count": 0,
                    "active_teacher_count": 0,
                }
            row = await uow.school_operations.create_class(
                school_id=actor.school_id,
                class_ref=class_ref,
                admin_membership_role_id=role_id,
                at=at,
            )
            await self._school_idempotency_complete(
                uow, claim, resource_type="school_class", result_ref=row.public_id
            )
            return {
                "class_ref": row.class_ref,
                "status": row.status,
                "active_student_count": 0,
                "active_teacher_count": 0,
            }

    async def school_list_members(
        self, actor: Any, role_code: str, *, at: datetime
    ) -> list[dict[str, Any]]:
        m = self._db_models
        async with self._uow() as uow:
            await self._school_actor_role(uow, actor, "admin", at)
            statement = (
                self._select(m.Account.public_id, m.AccountSchoolMembership.display_name)
                .join(
                    m.AccountSchoolMembership, m.AccountSchoolMembership.account_id == m.Account.id
                )
                .join(
                    m.MembershipRole, m.MembershipRole.membership_id == m.AccountSchoolMembership.id
                )
                .join(m.School, m.School.id == m.AccountSchoolMembership.school_id)
                .where(
                    m.Account.status == self._db_enums.AccountStatus.ACTIVE.value,
                    m.AccountSchoolMembership.school_id == actor.school_id,
                    m.AccountSchoolMembership.status == "ACTIVE",
                    m.AccountSchoolMembership.revoked_at.is_(None),
                    m.AccountSchoolMembership.valid_from <= at,
                    (m.AccountSchoolMembership.valid_until.is_(None))
                    | (m.AccountSchoolMembership.valid_until >= at),
                    m.MembershipRole.school_id == actor.school_id,
                    m.MembershipRole.role_code == role_code,
                    m.MembershipRole.status == "ACTIVE",
                    m.MembershipRole.revoked_at.is_(None),
                    m.MembershipRole.valid_from <= at,
                    (m.MembershipRole.valid_until.is_(None)) | (m.MembershipRole.valid_until >= at),
                    m.School.school_ref == actor.school_ref,
                    m.School.status == "ACTIVE",
                    m.School.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                )
            )
            if role_code == "teacher":
                refs = (await uow.session.execute(statement.order_by(m.Account.public_id))).all()
                return [
                    {
                        "user_id": f"USER_{row[0]}",
                        "role": role_code,
                        "subject_id": None,
                        "display_name": row[1],
                    }
                    for row in refs
                ]
            statement = (
                statement.add_columns(m.Subject.subject_ref)
                .join(
                    m.SubjectAccessGrant,
                    (m.SubjectAccessGrant.principal_account_id == m.Account.id)
                    & (m.SubjectAccessGrant.school_id == actor.school_id),
                )
                .join(m.Subject, m.Subject.id == m.SubjectAccessGrant.subject_id)
                .where(
                    m.SubjectAccessGrant.relationship_type == "SELF",
                    m.SubjectAccessGrant.status == "ACTIVE",
                    m.SubjectAccessGrant.revoked_at.is_(None),
                    m.SubjectAccessGrant.valid_from <= at,
                    (m.SubjectAccessGrant.valid_until.is_(None))
                    | (m.SubjectAccessGrant.valid_until >= at),
                    m.Subject.school_id == actor.school_id,
                    m.Subject.status == self._db_enums.SubjectStatus.ACTIVE.value,
                    m.Subject.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                )
                .distinct()
                .order_by(m.Account.public_id, m.Subject.subject_ref)
            )
            rows = (await uow.session.execute(statement)).all()
            return [
                {
                    "user_id": f"USER_{row[0]}",
                    "role": role_code,
                    "subject_id": row[2],
                    "display_name": row[1],
                }
                for row in rows
            ]

    async def school_assign_student(
        self, actor: Any, class_ref: str, student_user_ref: str, *, at: datetime, idempotency=None
    ) -> dict[str, Any]:
        m = self._db_models
        try:
            student_public_id = _database_public_id(student_user_ref, "USER")
        except ValueError:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="student was not found") from None
        async with self._uow() as uow:
            _account_id, role_id = await self._school_actor_role(uow, actor, "admin", at)
            claim = await self._school_idempotency_begin(uow, idempotency)
            receipt = claim.record
            if claim.replayed:
                link = await uow.session.scalar(
                    self._select(m.SchoolClassStudent).where(
                        m.SchoolClassStudent.public_id == receipt.result_public_id,
                        m.SchoolClassStudent.school_id == actor.school_id,
                    )
                )
                if link is None:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT, detail="idempotency result is unavailable"
                    )
                return {
                    "class_ref": class_ref,
                    "student_user_id": student_user_ref,
                    "status": link.status,
                }
            school_class = await uow.session.scalar(
                self._select(m.SchoolClass).where(
                    m.SchoolClass.school_id == actor.school_id, m.SchoolClass.class_ref == class_ref
                )
            )
            student = await uow.session.scalar(
                self._select(m.Account).where(
                    m.Account.public_id == student_public_id,
                    m.Account.status == self._db_enums.AccountStatus.ACTIVE.value,
                )
            )
            subject_ids = []
            if student is not None:
                subject_ids = list(
                    (
                        await uow.session.scalars(
                            self._select(m.Subject.id)
                            .join(
                                m.SubjectAccessGrant,
                                m.SubjectAccessGrant.subject_id == m.Subject.id,
                            )
                            .join(
                                m.AccountSchoolMembership,
                                (
                                    m.AccountSchoolMembership.account_id
                                    == m.SubjectAccessGrant.principal_account_id
                                )
                                & (
                                    m.AccountSchoolMembership.school_id
                                    == m.SubjectAccessGrant.school_id
                                ),
                            )
                            .join(
                                m.MembershipRole,
                                m.MembershipRole.membership_id == m.AccountSchoolMembership.id,
                            )
                            .where(
                                m.SubjectAccessGrant.principal_account_id == student.id,
                                m.SubjectAccessGrant.school_id == actor.school_id,
                                m.SubjectAccessGrant.relationship_type == "SELF",
                                m.SubjectAccessGrant.status == "ACTIVE",
                                m.SubjectAccessGrant.revoked_at.is_(None),
                                m.SubjectAccessGrant.valid_from <= at,
                                (m.SubjectAccessGrant.valid_until.is_(None))
                                | (m.SubjectAccessGrant.valid_until >= at),
                                m.AccountSchoolMembership.status == "ACTIVE",
                                m.AccountSchoolMembership.revoked_at.is_(None),
                                m.AccountSchoolMembership.valid_from <= at,
                                (m.AccountSchoolMembership.valid_until.is_(None))
                                | (m.AccountSchoolMembership.valid_until >= at),
                                m.MembershipRole.school_id == actor.school_id,
                                m.MembershipRole.role_code == "student",
                                m.MembershipRole.status == "ACTIVE",
                                m.MembershipRole.revoked_at.is_(None),
                                m.MembershipRole.valid_from <= at,
                                (m.MembershipRole.valid_until.is_(None))
                                | (m.MembershipRole.valid_until >= at),
                                m.Subject.school_id == actor.school_id,
                                m.Subject.status == self._db_enums.SubjectStatus.ACTIVE.value,
                                m.Subject.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                            )
                        )
                    ).all()
                )
            if school_class is None or len(subject_ids) != 1:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="class or student was not found")
            link = await uow.school_operations.add_student_subject_to_class(
                school_id=actor.school_id,
                class_id=school_class.id,
                subject_id=int(subject_ids[0]),
                admin_membership_role_id=role_id,
                at=at,
            )
            await self._school_idempotency_complete(
                uow, claim, resource_type="class_student", result_ref=link.public_id
            )
            return {
                "class_ref": class_ref,
                "student_user_id": student_user_ref,
                "status": link.status,
            }

    async def school_assign_teacher(
        self, actor: Any, class_ref: str, teacher_user_ref: str, *, at: datetime, idempotency=None
    ) -> dict[str, Any]:
        m = self._db_models
        try:
            public_id = _database_public_id(teacher_user_ref, "USER")
        except ValueError:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="teacher was not found") from None
        async with self._uow() as uow:
            _account_id, admin_role_id = await self._school_actor_role(uow, actor, "admin", at)
            claim = await self._school_idempotency_begin(uow, idempotency)
            receipt = claim.record
            if claim.replayed:
                link = await uow.session.scalar(
                    self._select(m.SchoolClassTeacher).where(
                        m.SchoolClassTeacher.public_id == receipt.result_public_id,
                        m.SchoolClassTeacher.school_id == actor.school_id,
                    )
                )
                if link is None:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT, detail="idempotency result is unavailable"
                    )
                return {
                    "class_ref": class_ref,
                    "teacher_user_id": teacher_user_ref,
                    "status": link.status,
                }
            teacher = await uow.session.scalar(
                self._select(m.Account).where(
                    m.Account.public_id == public_id,
                    m.Account.status == self._db_enums.AccountStatus.ACTIVE.value,
                )
            )
            school_class = await uow.session.scalar(
                self._select(m.SchoolClass).where(
                    m.SchoolClass.school_id == actor.school_id, m.SchoolClass.class_ref == class_ref
                )
            )
            if teacher is None or school_class is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="class or teacher was not found")
            teacher_roles = (
                await uow.session.scalars(
                    self._select(m.MembershipRole.id)
                    .join(
                        m.AccountSchoolMembership,
                        m.MembershipRole.membership_id == m.AccountSchoolMembership.id,
                    )
                    .where(
                        m.AccountSchoolMembership.account_id == teacher.id,
                        m.AccountSchoolMembership.school_id == actor.school_id,
                        m.AccountSchoolMembership.status == "ACTIVE",
                        m.MembershipRole.school_id == actor.school_id,
                        m.MembershipRole.role_code == "teacher",
                        m.MembershipRole.status == "ACTIVE",
                        m.MembershipRole.revoked_at.is_(None),
                        m.MembershipRole.valid_from <= at,
                        (m.MembershipRole.valid_until.is_(None))
                        | (m.MembershipRole.valid_until >= at),
                    )
                )
            ).all()
            if len(teacher_roles) != 1:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="teacher was not found")
            link = await uow.school_operations.add_teacher_role_to_class(
                school_id=actor.school_id,
                class_id=school_class.id,
                teacher_membership_role_id=int(teacher_roles[0]),
                admin_membership_role_id=admin_role_id,
                at=at,
            )
            await self._school_idempotency_complete(
                uow, claim, resource_type="class_teacher", result_ref=link.public_id
            )
            return {
                "class_ref": class_ref,
                "teacher_user_id": teacher_user_ref,
                "status": link.status,
            }

    async def school_publish_task(
        self,
        actor: Any,
        class_ref: str,
        task_ref: str,
        *,
        opens_at: datetime,
        due_at: datetime | None,
        activation_ref: str | None = None,
        at: datetime,
        idempotency=None,
    ) -> dict[str, Any]:
        m = self._db_models
        async with self._uow() as uow:
            account_id, role_id = await self._school_actor_role(uow, actor, "admin", at)
            claim = await self._school_idempotency_begin(uow, idempotency)
            if claim.replayed:
                task = await uow.session.scalar(
                    self._select(m.MeasurementTask).where(
                        m.MeasurementTask.school_id == actor.school_id,
                        m.MeasurementTask.task_ref == task_ref,
                    )
                )
                if task is None:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT, detail="idempotency result is unavailable"
                    )
                counts = await uow.school_operations.task_progress_counts(
                    task_id=task.id, school_id=actor.school_id
                )
                from dataclasses import asdict
                cat_binding = await self._task_cat_binding_fields(uow, actor, task)

                return {
                    "task_ref": task.task_ref,
                    "class_ref": class_ref,
                    "status": task.status,
                    "opens_at": task.opens_at,
                    "due_at": task.due_at,
                    "published_at": task.published_at,
                    **asdict(counts),
                    "instrument_id": task.instrument_id,
                    "instrument_version": task.instrument_version,
                    **cat_binding,
                }
            school_class = await uow.session.scalar(
                self._select(m.SchoolClass).where(
                    m.SchoolClass.school_id == actor.school_id, m.SchoolClass.class_ref == class_ref
                )
            )
            if school_class is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="class was not found")
            if activation_ref is None:
                from smhai_backend.domains.assessment.binding import D3_IDENTITY

                cat_binding_mode = "FIXTURE"
                instrument_id = D3_IDENTITY.instrument_id
                instrument_version = D3_IDENTITY.instrument_version
                item_bank_version = None
                config_version = None
                activation = plan_version = None
            else:
                try:
                    activation_public_id = _database_public_id(activation_ref, "CACT")
                except ValueError:
                    raise error(
                        ErrorCode.RESOURCE_NOT_FOUND,
                        detail="CAT activation was not found",
                    ) from None
                activation = await uow.session.scalar(
                    self._select(m.SchoolCatActivation)
                    .where(
                        m.SchoolCatActivation.public_id == activation_public_id,
                        m.SchoolCatActivation.school_id == actor.school_id,
                    )
                    .with_for_update()
                )
                if activation is None:
                    raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="CAT activation was not found")
                if activation.status != "ACTIVE":
                    raise error(ErrorCode.WORKFLOW_CONFLICT, detail="CAT activation is revoked")
                plan_version = await uow.session.scalar(
                    self._select(m.SchoolCatPlanVersion).where(
                        m.SchoolCatPlanVersion.id == activation.plan_version_id,
                        m.SchoolCatPlanVersion.school_id == actor.school_id,
                    )
                )
                if plan_version is None:
                    raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="CAT activation was not found")
                plan = await uow.session.scalar(
                    self._select(m.SchoolCatPlan)
                    .where(
                        m.SchoolCatPlan.id == plan_version.plan_id,
                        m.SchoolCatPlan.school_id == actor.school_id,
                    )
                    .with_for_update()
                )
                bank_version = await uow.session.scalar(
                    self._select(m.SchoolCatItemBankVersion).where(
                        m.SchoolCatItemBankVersion.id == plan_version.bank_version_id,
                        m.SchoolCatItemBankVersion.school_id == actor.school_id,
                    )
                )
                bank = await uow.session.scalar(
                    self._select(m.SchoolCatItemBank)
                    .where(
                        m.SchoolCatItemBank.id == bank_version.bank_id,
                        m.SchoolCatItemBank.school_id == actor.school_id,
                    )
                    .with_for_update()
                ) if bank_version is not None else None
                if plan is None or bank_version is None or bank is None:
                    raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="CAT activation was not found")
                if plan.status != "ACTIVE" or bank.status != "ACTIVE":
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT,
                        detail="saved CAT assets are no longer eligible for a task",
                    )
                bank_document = self._decrypt_school_cat_document(
                    uow, bank_version, _SCHOOL_CAT_BANK_DOCUMENT_SCHEMA
                )
                config_document = self._decrypt_school_cat_document(
                    uow, plan_version, _SCHOOL_CAT_CONFIG_DOCUMENT_SCHEMA
                )
                instrument_id = bank_document.get("instrument_id")
                instrument_version = self._school_cat_instrument_version(bank_document)
                item_bank_version = bank_document.get("version")
                config_version = config_document.get("config_version")
                if not all(
                    isinstance(value, str) and value and value.isascii()
                    for value in (
                        instrument_id,
                        instrument_version,
                        item_bank_version,
                        config_version,
                    )
                ):
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT,
                        detail="saved CAT identity is unavailable",
                    )
                cat_binding_mode = "SAVED_VERSION"

            snapshot = await uow.school_operations.publish_task_with_snapshot(
                school_id=actor.school_id,
                class_id=school_class.id,
                task_ref=task_ref,
                admin_membership_role_id=role_id,
                instrument_id=instrument_id,
                instrument_version=instrument_version,
                item_bank_version=item_bank_version,
                config_version=config_version,
                opens_at=opens_at,
                due_at=due_at,
                published_at=at,
            )
            task = snapshot.task
            task.cat_binding_mode = cat_binding_mode
            if activation is not None and plan_version is not None:
                uow.session.add(
                    m.SchoolCatTaskBinding(
                        school_id=actor.school_id,
                        task_id=task.id,
                        activation_id=activation.id,
                        plan_version_id=plan_version.id,
                    )
                )
                await uow.session.flush()
            await self._school_idempotency_complete(
                uow, claim, resource_type="measurement_task", result_ref=task.public_id
            )
            from smhai_backend.core.request_context import get_request_context

            await uow.audit.append(
                action="school_tasks.task.published",
                resource_type="measurement_task",
                resource_public_id=task.task_ref,
                result=self._db_enums.AuditResult.SUCCESS,
                trace_id=get_request_context().trace_id,
                actor_account_id=account_id,
                safe_metadata={"source": "backend", "state": "PUBLISHED"},
            )
            cat_binding = await self._task_cat_binding_fields(uow, actor, task)
            return {
                "task_ref": task.task_ref,
                "class_ref": class_ref,
                "status": task.status,
                "opens_at": task.opens_at,
                "due_at": task.due_at,
                "published_at": task.published_at,
                "published_enrollment_count": snapshot.enrollment_count,
                "active_enrollment_count": snapshot.enrollment_count,
                "revoked_enrollment_count": 0,
                "instrument_id": task.instrument_id,
                "instrument_version": task.instrument_version,
                **cat_binding,
            }

    async def school_list_class_tasks(
        self, actor: Any, class_ref: str, *, at: datetime
    ) -> list[dict[str, Any]]:
        from dataclasses import asdict

        m = self._db_models
        async with self._uow() as uow:
            await self._school_actor_role(uow, actor, "admin", at)
            school_class = await uow.session.scalar(
                self._select(m.SchoolClass).where(
                    m.SchoolClass.school_id == actor.school_id,
                    m.SchoolClass.class_ref == class_ref,
                )
            )
            if school_class is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="class was not found")
            tasks = (
                await uow.session.scalars(
                    self._select(m.MeasurementTask)
                    .where(
                        m.MeasurementTask.school_id == actor.school_id,
                        m.MeasurementTask.class_id == school_class.id,
                        m.MeasurementTask.cat_binding_mode.in_(("FIXTURE", "SAVED_VERSION")),
                    )
                    .order_by(m.MeasurementTask.published_at.desc())
                )
            ).all()
            output = []
            for task in tasks:
                counts = await uow.school_operations.task_progress_counts(
                    task_id=task.id, school_id=actor.school_id
                )
                output.append(
                    {
                        "task_ref": task.task_ref,
                        "class_ref": class_ref,
                        "status": task.status,
                        "opens_at": task.opens_at,
                        "due_at": task.due_at,
                        "published_at": task.published_at,
                        "instrument_id": task.instrument_id,
                        "instrument_version": task.instrument_version,
                        **await self._task_cat_binding_fields(uow, actor, task),
                        **asdict(counts),
                    }
                )
            return output

    async def school_list_student_tasks(self, actor: Any, *, at: datetime) -> list[dict[str, Any]]:
        m = self._db_models
        async with self._uow() as uow:
            account_id, _role_id = await self._school_actor_role(uow, actor, "student", at)
            statement = (
                self._select(
                    m.MeasurementTask.task_ref,
                    m.SchoolClass.class_ref,
                    m.MeasurementTask.status,
                    m.MeasurementTask.opens_at,
                    m.MeasurementTask.due_at,
                    m.AssessmentSession.assessment_ref,
                    m.AssessmentSession.status,
                )
                .select_from(m.TaskEnrollment)
                .join(
                    m.SchoolClassStudent,
                    (m.SchoolClassStudent.id == m.TaskEnrollment.class_student_id)
                    & (m.SchoolClassStudent.subject_id == m.TaskEnrollment.subject_id)
                    & (m.SchoolClassStudent.class_id == m.TaskEnrollment.class_id)
                    & (m.SchoolClassStudent.school_id == m.TaskEnrollment.school_id),
                )
                .join(
                    m.SchoolClass,
                    (m.SchoolClass.id == m.TaskEnrollment.class_id)
                    & (m.SchoolClass.school_id == m.TaskEnrollment.school_id),
                )
                .join(
                    m.MeasurementTask,
                    (m.MeasurementTask.id == m.TaskEnrollment.task_id)
                    & (m.MeasurementTask.school_id == m.TaskEnrollment.school_id)
                    & (m.MeasurementTask.class_id == m.TaskEnrollment.class_id),
                )
                .join(m.Subject, m.Subject.id == m.TaskEnrollment.subject_id)
                .join(
                    m.SubjectAccessGrant,
                    (m.SubjectAccessGrant.subject_id == m.TaskEnrollment.subject_id)
                    & (m.SubjectAccessGrant.school_id == m.TaskEnrollment.school_id),
                )
                .join(
                    m.AccountSchoolMembership,
                    (
                        m.AccountSchoolMembership.account_id
                        == m.SubjectAccessGrant.principal_account_id
                    )
                    & (m.AccountSchoolMembership.school_id == m.TaskEnrollment.school_id),
                )
                .join(
                    m.MembershipRole, m.MembershipRole.membership_id == m.AccountSchoolMembership.id
                )
                .join(m.Account, m.Account.id == m.AccountSchoolMembership.account_id)
                .join(m.School, m.School.id == m.TaskEnrollment.school_id)
                .outerjoin(
                    m.AssessmentSession,
                    (m.AssessmentSession.task_enrollment_id == m.TaskEnrollment.id)
                    & (m.AssessmentSession.subject_id == m.TaskEnrollment.subject_id),
                )
            )
            statement = (
                statement.where(
                    m.TaskEnrollment.school_id == actor.school_id,
                    m.TaskEnrollment.status == "ACTIVE",
                    m.MeasurementTask.cat_binding_mode.in_(("FIXTURE", "SAVED_VERSION")),
                    m.SchoolClassStudent.status == "ACTIVE",
                    m.SchoolClassStudent.revoked_at.is_(None),
                    m.SchoolClassStudent.valid_from <= at,
                    (m.SchoolClassStudent.valid_until.is_(None))
                    | (m.SchoolClassStudent.valid_until >= at),
                    m.SchoolClass.status == "ACTIVE",
                    m.MeasurementTask.status == "PUBLISHED",
                    m.MeasurementTask.opens_at <= at,
                    (m.MeasurementTask.due_at.is_(None)) | (m.MeasurementTask.due_at >= at),
                    m.Subject.status == self._db_enums.SubjectStatus.ACTIVE.value,
                    m.Subject.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                    m.Subject.school_id == actor.school_id,
                    m.SubjectAccessGrant.principal_account_id == account_id,
                    m.SubjectAccessGrant.relationship_type == "SELF",
                    m.SubjectAccessGrant.status == "ACTIVE",
                    m.SubjectAccessGrant.revoked_at.is_(None),
                    m.SubjectAccessGrant.valid_from <= at,
                    (m.SubjectAccessGrant.valid_until.is_(None))
                    | (m.SubjectAccessGrant.valid_until >= at),
                    m.AccountSchoolMembership.status == "ACTIVE",
                    m.AccountSchoolMembership.revoked_at.is_(None),
                    m.AccountSchoolMembership.valid_from <= at,
                    (m.AccountSchoolMembership.valid_until.is_(None))
                    | (m.AccountSchoolMembership.valid_until >= at),
                    m.MembershipRole.school_id == actor.school_id,
                    m.MembershipRole.role_code == "student",
                    m.MembershipRole.status == "ACTIVE",
                    m.MembershipRole.revoked_at.is_(None),
                    m.MembershipRole.valid_from <= at,
                    (m.MembershipRole.valid_until.is_(None)) | (m.MembershipRole.valid_until >= at),
                    m.Account.status == self._db_enums.AccountStatus.ACTIVE.value,
                    m.School.school_ref == actor.school_ref,
                    m.School.status == "ACTIVE",
                    m.School.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                )
                .distinct()
                .order_by(m.MeasurementTask.opens_at, m.MeasurementTask.task_ref)
            )
            rows = (await uow.session.execute(statement)).all()
            return [
                dict(
                    task_ref=row[0],
                    class_ref=row[1],
                    status=row[2],
                    opens_at=row[3],
                    due_at=row[4],
                    assessment_id=row[5],
                    assessment_status=row[6],
                )
                for row in rows
            ]

    async def school_list_student_task_history(
        self, actor: Any, *, at: datetime
    ) -> list[dict[str, Any]]:
        """Return own task lifecycle metadata without loading assessment payloads."""
        if (
            actor.scope_profile != "school_tenant"
            or actor.role is not BackendRole.STUDENT
            or actor.school_id is None
            or actor.school_ref is None
        ):
            return []
        m = self._db_models
        async with self._uow() as uow:
            account_id, role_id = await self._school_actor_role(uow, actor, "student", at)
            statement = (
                self._select(
                    m.MeasurementTask.task_ref,
                    m.SchoolClass.class_ref,
                    m.MeasurementTask.status,
                    m.TaskEnrollment.status,
                    m.AssessmentSession.status,
                    m.AssessmentSession.started_at,
                    m.AssessmentSession.completed_at,
                )
                .select_from(m.TaskEnrollment)
                .join(
                    m.MeasurementTask,
                    (m.MeasurementTask.id == m.TaskEnrollment.task_id)
                    & (m.MeasurementTask.school_id == m.TaskEnrollment.school_id)
                    & (m.MeasurementTask.class_id == m.TaskEnrollment.class_id),
                )
                .join(
                    m.SchoolClass,
                    (m.SchoolClass.id == m.TaskEnrollment.class_id)
                    & (m.SchoolClass.school_id == m.TaskEnrollment.school_id),
                )
                .join(
                    m.SchoolClassStudent,
                    (m.SchoolClassStudent.id == m.TaskEnrollment.class_student_id)
                    & (m.SchoolClassStudent.subject_id == m.TaskEnrollment.subject_id)
                    & (m.SchoolClassStudent.class_id == m.TaskEnrollment.class_id)
                    & (m.SchoolClassStudent.school_id == m.TaskEnrollment.school_id),
                )
                .join(
                    m.Subject,
                    (m.Subject.id == m.TaskEnrollment.subject_id)
                    & (m.Subject.school_id == m.TaskEnrollment.school_id),
                )
                .join(
                    m.SubjectAccessGrant,
                    (m.SubjectAccessGrant.subject_id == m.Subject.id)
                    & (m.SubjectAccessGrant.school_id == m.TaskEnrollment.school_id),
                )
                .join(
                    m.AccountSchoolMembership,
                    (
                        m.AccountSchoolMembership.account_id
                        == m.SubjectAccessGrant.principal_account_id
                    )
                    & (m.AccountSchoolMembership.school_id == m.TaskEnrollment.school_id),
                )
                .join(
                    m.MembershipRole,
                    m.MembershipRole.membership_id == m.AccountSchoolMembership.id,
                )
                .join(m.Account, m.Account.id == m.AccountSchoolMembership.account_id)
                .join(m.School, m.School.id == m.TaskEnrollment.school_id)
                .outerjoin(
                    m.AssessmentSession,
                    (m.AssessmentSession.task_enrollment_id == m.TaskEnrollment.id)
                    & (m.AssessmentSession.subject_id == m.TaskEnrollment.subject_id),
                )
                .where(
                    m.TaskEnrollment.school_id == actor.school_id,
                    m.SchoolClassStudent.subject_id == m.TaskEnrollment.subject_id,
                    m.Subject.status == self._db_enums.SubjectStatus.ACTIVE.value,
                    m.Subject.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                    m.SubjectAccessGrant.principal_account_id == account_id,
                    m.SubjectAccessGrant.relationship_type == "SELF",
                    m.SubjectAccessGrant.status == "ACTIVE",
                    m.SubjectAccessGrant.revoked_at.is_(None),
                    m.SubjectAccessGrant.valid_from <= at,
                    (m.SubjectAccessGrant.valid_until.is_(None))
                    | (m.SubjectAccessGrant.valid_until >= at),
                    m.AccountSchoolMembership.status == "ACTIVE",
                    m.AccountSchoolMembership.revoked_at.is_(None),
                    m.AccountSchoolMembership.valid_from <= at,
                    (m.AccountSchoolMembership.valid_until.is_(None))
                    | (m.AccountSchoolMembership.valid_until >= at),
                    m.MembershipRole.id == role_id,
                    m.MembershipRole.school_id == actor.school_id,
                    m.MembershipRole.role_code == "student",
                    m.MembershipRole.status == "ACTIVE",
                    m.MembershipRole.revoked_at.is_(None),
                    m.MembershipRole.valid_from <= at,
                    (m.MembershipRole.valid_until.is_(None)) | (m.MembershipRole.valid_until >= at),
                    m.Account.status == self._db_enums.AccountStatus.ACTIVE.value,
                    m.School.school_ref == actor.school_ref,
                    m.School.status == "ACTIVE",
                    m.School.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                )
                .order_by(m.MeasurementTask.published_at.desc(), m.MeasurementTask.task_ref)
            )
            rows = (await uow.session.execute(statement)).all()
            return [
                {
                    "task_ref": row[0],
                    "class_ref": row[1],
                    "task_status": row[2],
                    "enrollment_status": row[3],
                    "assessment_status": row[4],
                    "started_at": row[5],
                    "completed_at": row[6],
                }
                for row in rows
            ]

    async def school_prepare_task_session(
        self,
        actor: Any,
        task_ref: str,
        assessment_ref: str,
        *,
        at: datetime,
        trace_id: str,
        idempotency=None,
    ) -> dict[str, Any]:
        m = self._db_models
        account_id, _role_id = None, None
        async with self._uow() as uow:
            account_id, _role_id = await self._school_actor_role(
                uow, actor, "student", at, lock=True
            )
            claim = await self._school_idempotency_begin(uow, idempotency)
            receipt = claim.record
            if claim.replayed:
                if (
                    receipt.result_resource_type != "assessment_session"
                    or not receipt.result_public_id
                ):
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT,
                        detail="idempotency result is unavailable",
                    )
                assessment_ref = receipt.result_public_id
            enrollment = await uow.session.scalar(
                self._select(m.TaskEnrollment)
                .join(
                    m.MeasurementTask,
                    (m.MeasurementTask.id == m.TaskEnrollment.task_id)
                    & (m.MeasurementTask.school_id == m.TaskEnrollment.school_id)
                    & (m.MeasurementTask.class_id == m.TaskEnrollment.class_id),
                )
                .join(
                    m.SchoolClassStudent,
                    (m.SchoolClassStudent.id == m.TaskEnrollment.class_student_id)
                    & (m.SchoolClassStudent.school_id == m.TaskEnrollment.school_id)
                    & (m.SchoolClassStudent.class_id == m.TaskEnrollment.class_id)
                    & (m.SchoolClassStudent.subject_id == m.TaskEnrollment.subject_id),
                )
                .join(
                    m.SubjectAccessGrant,
                    (m.SubjectAccessGrant.subject_id == m.TaskEnrollment.subject_id)
                    & (m.SubjectAccessGrant.school_id == m.TaskEnrollment.school_id),
                )
                .where(
                    m.TaskEnrollment.school_id == actor.school_id,
                    m.TaskEnrollment.status == "ACTIVE",
                    m.MeasurementTask.task_ref == task_ref,
                    # A research start locks its research task before the
                    # ordinary roster/enrollment write path. Exclude it here
                    # so the ordinary path cannot invert those lock orders.
                    m.MeasurementTask.cat_binding_mode.in_(("FIXTURE", "SAVED_VERSION")),
                    m.SubjectAccessGrant.principal_account_id == account_id,
                    m.SubjectAccessGrant.relationship_type == "SELF",
                )
            )
            if enrollment is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="open assigned task was not found")
            enrollment, task, _subject = await self._lock_school_assessment_write_scope(
                uow, actor, account_id, enrollment, at=at
            )
            if task.cat_binding_mode not in {"FIXTURE", "SAVED_VERSION"}:
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT,
                    detail="task requires a different CAT session workflow",
                )
            existing_session = await uow.session.scalar(
                self._select(m.AssessmentSession).where(
                    m.AssessmentSession.task_enrollment_id == enrollment.id,
                    m.AssessmentSession.subject_id == enrollment.subject_id,
                ).with_for_update()
            )
            session = await uow.school_operations.create_task_assessment_session(
                enrollment_id=enrollment.id,
                assessment_ref=assessment_ref,
                school_id=actor.school_id,
                student_account_id=account_id,
                at=at,
                trace_id=trace_id,
            )
            if existing_session is None:
                session.cat_binding_mode = task.cat_binding_mode
            elif session.cat_binding_mode != task.cat_binding_mode:
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="task CAT binding mode changed")
            session_binding = await uow.session.scalar(
                self._select(m.SchoolCatSessionBinding).where(
                    m.SchoolCatSessionBinding.assessment_session_id == session.id,
                    m.SchoolCatSessionBinding.school_id == actor.school_id,
                ).with_for_update()
            )
            if task.cat_binding_mode == "SAVED_VERSION" and session_binding is None:
                if existing_session is not None:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT,
                        detail="saved CAT session binding is unavailable",
                    )
                task_binding = await uow.session.scalar(
                    self._select(m.SchoolCatTaskBinding).where(
                        m.SchoolCatTaskBinding.task_id == task.id,
                        m.SchoolCatTaskBinding.school_id == actor.school_id,
                    )
                )
                if task_binding is None:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT,
                        detail="saved task CAT binding is unavailable",
                    )
                candidate_binding = m.SchoolCatSessionBinding(
                    school_id=actor.school_id,
                    assessment_session_id=session.id,
                    task_enrollment_id=enrollment.id,
                    subject_id=enrollment.subject_id,
                    task_id=task.id,
                    task_binding_id=task_binding.id,
                    activation_id=task_binding.activation_id,
                    plan_version_id=task_binding.plan_version_id,
                )
                try:
                    async with uow.session.begin_nested():
                        uow.session.add(candidate_binding)
                        await uow.session.flush()
                    session_binding = candidate_binding
                except self._integrity_error:
                    session_binding = await uow.session.scalar(
                        self._select(m.SchoolCatSessionBinding)
                        .where(
                            m.SchoolCatSessionBinding.assessment_session_id == session.id,
                            m.SchoolCatSessionBinding.school_id == actor.school_id,
                        )
                        .with_for_update()
                    )
                    if (
                        session_binding is None
                        or session_binding.task_enrollment_id != enrollment.id
                        or session_binding.subject_id != enrollment.subject_id
                        or session_binding.task_binding_id != task_binding.id
                    ):
                        raise error(
                            ErrorCode.WORKFLOW_CONFLICT,
                            detail="saved CAT session binding is unavailable",
                        ) from None
            binding_context = await self._school_task_assessment_binding(
                uow, actor, task, enrollment, session, at=at
            )
            if claim.replayed:
                if session.assessment_ref != assessment_ref:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT,
                        detail="idempotency result does not match the task session",
                    )
            else:
                await self._school_idempotency_complete(
                    uow,
                    claim,
                    resource_type="assessment_session",
                    result_ref=session.assessment_ref,
                )
            subject = await uow.session.get(m.Subject, session.subject_id)
            if subject is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="assigned task was not found")
            result = {
                "assessment_id": session.assessment_ref,
                "subject_id": subject.subject_ref,
                "instrument_id": session.instrument_id,
                "instrument_version": session.instrument_version,
                "item_bank_version": session.item_bank_version,
                "config_version": session.config_version,
                "started_at": session.started_at or at,
                "task_ref": task.task_ref,
                "session_status": session.status,
                "cat_binding_mode": binding_context["cat_binding_mode"],
            }
            if (
                not claim.replayed
                and existing_session is None
                and getattr(session, "trace_id", None) == trace_id
            ):
                await uow.audit.append(
                    action="school_tasks.assessment_session.prepared",
                    resource_type="assessment_session",
                    resource_public_id=session.assessment_ref,
                    result=self._db_enums.AuditResult.SUCCESS,
                    trace_id=trace_id,
                    actor_account_id=account_id,
                    safe_metadata={"source": "backend", "state": "CREATED"},
                )
            return result

    async def school_revoke_enrollment(
        self, actor: Any, task_ref: str, enrollment_ref: str, *, at: datetime, idempotency=None
    ) -> dict[str, str]:
        m = self._db_models
        try:
            enrollment_public_id = _database_public_id(enrollment_ref, "ENROLL")
        except ValueError:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="enrollment was not found") from None
        async with self._uow() as uow:
            _account_id, role_id = await self._school_actor_role(uow, actor, "admin", at)
            claim = await self._school_idempotency_begin(uow, idempotency)
            receipt = claim.record
            if claim.replayed:
                enrollment = await uow.session.scalar(
                    self._select(m.TaskEnrollment).where(
                        m.TaskEnrollment.public_id == receipt.result_public_id,
                        m.TaskEnrollment.school_id == actor.school_id,
                    )
                )
                if enrollment is None:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT, detail="idempotency result is unavailable"
                    )
                return {"enrollment_ref": enrollment_ref, "status": enrollment.status}
            enrollment = await uow.session.scalar(
                self._select(m.TaskEnrollment)
                .join(m.MeasurementTask, m.MeasurementTask.id == m.TaskEnrollment.task_id)
                .where(
                    m.TaskEnrollment.public_id == enrollment_public_id,
                    m.TaskEnrollment.school_id == actor.school_id,
                    m.MeasurementTask.task_ref == task_ref,
                )
            )
            if enrollment is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="enrollment was not found")
            enrollment = await uow.school_operations.revoke_enrollment(
                enrollment_id=enrollment.id,
                school_id=actor.school_id,
                admin_membership_role_id=role_id,
                at=at,
            )
            await self._school_idempotency_complete(
                uow, claim, resource_type="task_enrollment", result_ref=enrollment.public_id
            )
            return {"enrollment_ref": enrollment_ref, "status": enrollment.status}

    async def school_list_task_enrollments(
        self, actor: Any, task_ref: str, *, at: datetime
    ) -> list[dict[str, str]]:
        m = self._db_models
        async with self._uow() as uow:
            _account_id, _role_id = await self._school_actor_role(uow, actor, "admin", at)
            task = await uow.session.scalar(
                self._select(m.MeasurementTask).where(
                    m.MeasurementTask.school_id == actor.school_id,
                    m.MeasurementTask.task_ref == task_ref,
                )
            )
            if task is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="task was not found")
            rows = (
                await uow.session.execute(
                    self._select(m.TaskEnrollment.public_id, m.TaskEnrollment.status)
                    .where(
                        m.TaskEnrollment.task_id == task.id,
                        m.TaskEnrollment.school_id == actor.school_id,
                    )
                    .order_by(m.TaskEnrollment.created_at, m.TaskEnrollment.public_id)
                )
            ).all()
            return [{"enrollment_ref": f"ENROLL_{row[0]}", "status": row[1]} for row in rows]

    async def school_teacher_progress(
        self, actor: Any, class_ref: str | None = None
    ) -> list[dict[str, Any]]:
        m = self._db_models
        now = self._utc_now()
        async with self._uow() as uow:
            account_id, role_id = await self._school_actor_role(uow, actor, "teacher", now)
            classes_statement = (
                self._select(m.SchoolClass.class_ref)
                .join(m.SchoolClassTeacher, m.SchoolClassTeacher.class_id == m.SchoolClass.id)
                .where(
                    m.SchoolClass.status == "ACTIVE",
                    m.SchoolClassTeacher.school_id == actor.school_id,
                    m.SchoolClassTeacher.membership_role_id == role_id,
                    m.SchoolClassTeacher.status == "ACTIVE",
                    m.SchoolClassTeacher.revoked_at.is_(None),
                    m.SchoolClassTeacher.valid_from <= now,
                    (m.SchoolClassTeacher.valid_until.is_(None))
                    | (m.SchoolClassTeacher.valid_until >= now),
                )
            )
            if class_ref is not None:
                classes_statement = classes_statement.where(m.SchoolClass.class_ref == class_ref)
            class_refs = sorted(set((await uow.session.scalars(classes_statement)).all()))
            if class_ref is not None and not class_refs:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="class was not found")
            output = []
            from dataclasses import asdict

            for current_class_ref in class_refs:
                tasks = (
                    await uow.session.scalars(
                        self._select(m.MeasurementTask)
                        .join(m.SchoolClass, m.SchoolClass.id == m.MeasurementTask.class_id)
                        .where(
                            m.MeasurementTask.school_id == actor.school_id,
                            m.SchoolClass.class_ref == current_class_ref,
                        )
                        .order_by(m.MeasurementTask.published_at.desc())
                    )
                ).all()
                for task in tasks:
                    counts = await uow.school_operations.task_progress_counts(
                        task_id=task.id, school_id=actor.school_id
                    )
                    output.append(
                        {
                            "class_ref": current_class_ref,
                            "task_ref": task.task_ref,
                            "task_status": task.status,
                            "opens_at": task.opens_at,
                            "due_at": task.due_at,
                            **asdict(counts),
                        }
                    )
            return output

    async def _ensure_synthetic_fixtures(self) -> None:
        """Create only clearly-labelled local identities when absent."""

        m = self._db_models
        e = self._db_enums
        fixtures = (
            ("student_a", "synthetic-student-a", "student", "SUBJ_demo_a"),
            ("student_b", "synthetic-student-b", "student", "SUBJ_demo_b"),
            ("teacher", "synthetic-teacher", "teacher", None),
            ("reviewer", "synthetic-reviewer", "reviewer", None),
        )
        if self.identity_profile == "school_tenant":
            fixtures = ()
        optional_identity_specs = self._optional_identity_specs()
        optional_fixtures: list[tuple[str, str, str, str | None]] = []
        for role_code, env_prefix in optional_identity_specs:
            username = os.environ.get(f"{env_prefix}_USERNAME")
            password = os.environ.get(f"{env_prefix}_PASSWORD")
            if (username is None) != (password is None):
                raise RuntimeError(f"Incomplete local demo identity configuration: {env_prefix}.")
            if username is None or password is None:
                continue
            if not username.strip() or len(username) > 128 or not password or len(password) > 256:
                raise RuntimeError(f"Invalid local demo identity configuration: {env_prefix}.")
            optional_fixtures.append((username.strip(), password, role_code, None))

        fixtures = (*fixtures, *optional_fixtures)
        fixture_usernames = [fixture[0].casefold() for fixture in fixtures]
        if len(fixture_usernames) != len(set(fixture_usernames)):
            raise RuntimeError("Duplicate local synthetic identity configuration.")

        hasher = PasswordHash.recommended()
        async with self._uow() as uow:
            assert uow.session is not None
            await self._seed_reference_roles(uow.session)
            role_rows = {
                row.role_code: row
                for row in (
                    await uow.session.scalars(self._select(m.Role).where(m.Role.status == "ACTIVE"))
                ).all()
            }
            configured_roles = {fixture[2] for fixture in optional_fixtures}
            if any(role_code not in role_rows for role_code in configured_roles):
                raise RuntimeError(
                    "A configured local demo identity references an unavailable role."
                )
            subjects: dict[str, Any] = {}
            for _, _, _, subject_ref in fixtures:
                if subject_ref is None:
                    continue
                subject = await uow.subjects.get_by_ref(subject_ref)
                if subject is None:
                    subject = await uow.subjects.create(
                        subject_ref=subject_ref,
                        school_id=None,
                        data_origin=e.DataOrigin.SYNTHETIC,
                    )
                subjects[subject_ref] = subject

            for username, password, role_code, self_subject_ref in fixtures:
                account = await uow.accounts.get_by_login_name(username)
                if account is None:
                    account = await uow.accounts.create(
                        login_name=username,
                        password_hash=hasher.hash(password),
                        status=e.AccountStatus.ACTIVE,
                    )
                role = role_rows.get(role_code)
                if role is None:
                    continue
                account_role = await uow.session.scalar(
                    self._select(m.AccountRole).where(
                        m.AccountRole.account_id == account.id,
                        m.AccountRole.role_id == role.id,
                    )
                )
                if account_role is None:
                    uow.session.add(
                        m.AccountRole(
                            account_id=account.id,
                            role_id=role.id,
                            status=e.GrantStatus.ACTIVE.value,
                        )
                    )
                if self_subject_ref is not None:
                    subject = subjects[self_subject_ref]
                    grant = await uow.session.scalar(
                        self._select(m.SubjectAccessGrant).where(
                            m.SubjectAccessGrant.principal_account_id == account.id,
                            m.SubjectAccessGrant.subject_id == subject.id,
                        )
                    )
                    if grant is None:
                        uow.session.add(
                            m.SubjectAccessGrant(
                                principal_account_id=account.id,
                                subject_id=subject.id,
                                school_id=None,
                                relationship_type=e.RelationshipType.SELF.value,
                                status=e.GrantStatus.ACTIVE.value,
                                valid_from=self._utc_now(),
                            )
                        )
                elif role_code in {"teacher", "reviewer"}:
                    for subject in subjects.values():
                        relationship = (
                            e.RelationshipType.TEACHER_OF
                            if role_code == "teacher"
                            else e.RelationshipType.REVIEW_ASSIGNMENT
                        )
                        grant = await uow.session.scalar(
                            self._select(m.SubjectAccessGrant).where(
                                m.SubjectAccessGrant.principal_account_id == account.id,
                                m.SubjectAccessGrant.subject_id == subject.id,
                            )
                        )
                        if grant is None:
                            uow.session.add(
                                m.SubjectAccessGrant(
                                    principal_account_id=account.id,
                                    subject_id=subject.id,
                                    school_id=None,
                                    relationship_type=relationship.value,
                                    status=e.GrantStatus.ACTIVE.value,
                                    valid_from=self._utc_now(),
                                )
                            )
            await uow.session.flush()

    async def _user_from_account(self, uow, account) -> SyntheticUser | None:
        m = self._db_models
        e = self._db_enums
        if account.status != e.AccountStatus.ACTIVE.value:
            return None
        roles = list(
            (
                await uow.session.scalars(
                    self._select(m.Role.role_code)
                    .join(m.AccountRole, m.AccountRole.role_id == m.Role.id)
                    .where(
                        m.AccountRole.account_id == account.id,
                        m.AccountRole.status == e.GrantStatus.ACTIVE.value,
                        m.Role.status == "ACTIVE",
                    )
                )
            ).all()
        )
        if self.identity_profile == "school_tenant":
            now = self._utc_now()
            contexts = []
            active_contexts = await uow.memberships.active_contexts(
                account_id=account.id,
                at=now,
            )
            for context_id, role_code, school_id, school_ref in active_contexts:
                accessible = await uow.memberships.authorized_subject_refs(
                    account_id=account.id,
                    school_id=school_id,
                    role_code=role_code,
                    at=now,
                )
                contexts.append(
                    SchoolRoleContext(
                        context_id=str(context_id),
                        role=BackendRole(role_code.upper()),
                        school_id=school_id,
                        school_ref=school_ref,
                        accessible_subject_ids=accessible,
                    )
                )
            if contexts:
                first = contexts[0]
                return SyntheticUser(
                    user_id=_backend_user_id(account.public_id),
                    username=account.login_name,
                    role=first.role,
                    subject_id=None,
                    password_hash=account.password_hash,
                    accessible_subject_ids=frozenset(),
                    scope_profile="school_tenant",
                    school_contexts=tuple(contexts),
                    default_context_id=None,
                )
            # REVIEWER is internal and never enters the school selector. The
            # school_tenant profile does not resolve NULL-scoped legacy grants.
            if BackendRole.REVIEWER.value.lower() in roles:
                return SyntheticUser(
                    user_id=_backend_user_id(account.public_id),
                    username=account.login_name,
                    role=BackendRole.REVIEWER,
                    subject_id=None,
                    password_hash=account.password_hash,
                    accessible_subject_ids=frozenset(),
                    scope_profile="internal",
                )
            return None

        role_code = next(
            (
                candidate
                for candidate in (
                    "student",
                    "teacher",
                    "reviewer",
                    "psychological_specialist",
                    "parent",
                    "admin",
                )
                if candidate in roles
            ),
            None,
        )
        if role_code is None:
            return None
        accessible = frozenset(
            (
                await uow.session.scalars(
                    self._select(m.Subject.subject_ref)
                    .join(
                        m.SubjectAccessGrant,
                        m.SubjectAccessGrant.subject_id == m.Subject.id,
                    )
                    .where(
                        m.SubjectAccessGrant.principal_account_id == account.id,
                        m.SubjectAccessGrant.school_id.is_(None),
                        m.Subject.school_id.is_(None),
                        m.SubjectAccessGrant.status == e.GrantStatus.ACTIVE.value,
                        m.Subject.status == e.SubjectStatus.ACTIVE.value,
                    )
                )
            ).all()
        )
        subject_id = None
        if role_code == "student" and accessible:
            subject_id = next(iter(accessible))
        return SyntheticUser(
            user_id=_backend_user_id(account.public_id),
            username=account.login_name,
            role=BackendRole(role_code.upper()),
            subject_id=subject_id,
            password_hash=account.password_hash,
            accessible_subject_ids=accessible,
            scope_profile="legacy_demo",
        )

    async def get_by_username(self, username: str) -> SyntheticUser | None:
        async with self._uow() as uow:
            account = await uow.accounts.get_by_login_name(username)
            return await self._user_from_account(uow, account) if account else None

    async def _get_user(self, user_id: str) -> SyntheticUser | None:
        try:
            public_id = _database_public_id(user_id, "USER")
        except ValueError:
            return None
        async with self._uow() as uow:
            account = await uow.session.scalar(
                self._select(self._db_models.Account).where(
                    self._db_models.Account.public_id == public_id
                )
            )
            return await self._user_from_account(uow, account) if account else None

    async def _account_for_user(self, uow, user_id: str):
        try:
            public_id = _database_public_id(user_id, "USER")
        except ValueError:
            return None
        return await uow.session.scalar(
            self._select(self._db_models.Account).where(
                self._db_models.Account.public_id == public_id
            )
        )

    # ------------------------------------------------------------------
    # Opaque session store
    # ------------------------------------------------------------------

    def _csrf_token(self, raw_session_token: str) -> str:
        return hmac.new(
            self._csrf_secret,
            raw_session_token.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _session_record(self, raw_token: str, record) -> SessionRecord:
        return SessionRecord(
            session_id=raw_token,
            user_id=_backend_user_id(record.account.public_id)
            if getattr(record, "account", None) is not None
            else "",
            csrf_token=self._csrf_token(raw_token),
            created_at=_as_timestamp(record.created_at),
            expires_at=_as_timestamp(record.idle_expires_at),
            last_seen_at=_as_timestamp(record.last_seen_at),
            active_context_id=(
                str(record.active_membership_role_id)
                if record.active_membership_role_id is not None
                else None
            ),
        )

    async def create(
        self,
        user_id: str,
        ttl_seconds: int,
        *,
        active_context_id: str | None = None,
    ) -> SessionRecord:
        raw_token = secrets.token_urlsafe(32)
        csrf_token = self._csrf_token(raw_token)
        now = self._utc_now()
        async with self._uow() as uow:
            account = await self._account_for_user(uow, user_id)
            if account is None:
                raise error(ErrorCode.AUTH_SESSION_EXPIRED, detail="authentication is required")
            active_school_id = None
            active_role_id = None
            if active_context_id is not None:
                try:
                    context_id = int(active_context_id)
                except ValueError:
                    raise error(ErrorCode.FORBIDDEN, detail="access denied") from None
                resolved = await uow.memberships.context_for_account(
                    account_id=account.id, context_id=context_id, at=now
                )
                if resolved is None:
                    raise error(ErrorCode.FORBIDDEN, detail="access denied")
                active_role_id, active_school_id, _role_code = resolved
            await uow.auth_sessions.create(
                account_id=account.id,
                raw_session_token=raw_token,
                raw_csrf_token=csrf_token,
                active_school_id=active_school_id,
                active_membership_role_id=active_role_id,
                idle_expires_at=now + timedelta(seconds=ttl_seconds),
                absolute_expires_at=now + timedelta(seconds=max(ttl_seconds * 8, 3600)),
            )
        return SessionRecord(
            session_id=raw_token,
            user_id=user_id,
            csrf_token=csrf_token,
            created_at=now.replace(tzinfo=UTC).timestamp(),
            expires_at=(now + timedelta(seconds=ttl_seconds)).replace(tzinfo=UTC).timestamp(),
            last_seen_at=now.replace(tzinfo=UTC).timestamp(),
            active_context_id=active_context_id,
        )

    async def _get_session(self, session_id: str) -> SessionRecord | None:
        async with self._uow() as uow:
            record = await uow.auth_sessions.find_by_token(session_id)
            if record is None:
                return None
            now = self._utc_now()
            if record.idle_expires_at <= now or record.absolute_expires_at <= now:
                record.revoked_at = now
                record.revocation_reason = "expired"
                await uow.session.flush()
                return None
            account = await uow.session.get(self._db_models.Account, record.account_id)
            if account is None:
                return None
            record.account = account
            return self._session_record(session_id, record)

    async def touch(self, session_id: str, ttl_seconds: int) -> SessionRecord | None:
        async with self._uow() as uow:
            record = await uow.auth_sessions.find_by_token(session_id)
            if record is None:
                return None
            now = self._utc_now()
            if record.idle_expires_at <= now or record.absolute_expires_at <= now:
                record.revoked_at = now
                record.revocation_reason = "expired"
                return None
            record.last_seen_at = now
            record.idle_expires_at = min(
                now + timedelta(seconds=ttl_seconds), record.absolute_expires_at
            )
            account = await uow.session.get(self._db_models.Account, record.account_id)
            if account is None:
                return None
            record.account = account
            return self._session_record(session_id, record)

    async def rotate(self, session_id: str, user_id: str, ttl_seconds: int) -> SessionRecord:
        await self.revoke(session_id)
        return await self.create(user_id, ttl_seconds)

    async def set_active_context(self, session_id: str, context_id: str) -> SessionRecord | None:
        try:
            parsed_context_id = int(context_id)
        except ValueError:
            return None
        now = self._utc_now()
        async with self._uow() as uow:
            record = await uow.auth_sessions.find_by_token(session_id)
            if record is None:
                return None
            if record.idle_expires_at <= now or record.absolute_expires_at <= now:
                return None
            resolved = await uow.memberships.context_for_account(
                account_id=record.account_id, context_id=parsed_context_id, at=now
            )
            if resolved is None:
                raise error(ErrorCode.FORBIDDEN, detail="access denied")
            role_id, school_id, _role_code = resolved
            updated = await uow.auth_sessions.set_active_context(
                session_id, school_id=school_id, membership_role_id=role_id
            )
            if updated is None:
                return None
            account = await uow.session.get(self._db_models.Account, record.account_id)
            if account is None:
                return None
            updated.account = account
            return self._session_record(session_id, updated)

    async def revoke(self, session_id: str, reason: str = "logout") -> None:
        async with self._uow() as uow:
            await uow.auth_sessions.revoke(session_id, reason=reason, at=self._utc_now())

    async def is_revoked(self, session_id: str) -> bool:
        async with self._uow() as uow:
            record = await uow.session.scalar(
                self._select(self._db_models.AuthSession).where(
                    self._db_models.AuthSession.session_token_hash == _hash_token(session_id)
                )
            )
            if record is None:
                return False
            now = self._utc_now()
            return bool(
                record.revoked_at is not None
                or record.idle_expires_at <= now
                or record.absolute_expires_at <= now
            )

    # ------------------------------------------------------------------
    # Assessment persistence
    # ------------------------------------------------------------------

    def _status_upper(self, value: str) -> str:
        return {
            "created": "CREATED",
            "in_progress": "IN_PROGRESS",
            "completed": "COMPLETED",
            "abandoned": "ABANDONED",
            "invalid": "INVALID",
        }.get(value, value.upper())

    async def _save_assessment(self, record: AssessmentRecord) -> None:
        async with self._uow() as uow:
            await self._save_assessment_in_uow(uow, record)

    async def _save_assessment_in_uow(
        self,
        uow: Any,
        record: AssessmentRecord,
        *,
        db_record: Any | None = None,
        trace_id: str | None = None,
    ) -> None:
        m = self._db_models
        if db_record is None:
            try:
                db_record = await uow.assessments.get_session(record.assessment_id)
            except self._db_not_found:
                subject = await uow.subjects.get_by_ref(record.subject_id)
                if subject is None:
                    raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="subject not found") from None
                instrument = record.assessment.get("instrument", {})
                db_record = await uow.assessments.create_session(
                    assessment_ref=record.assessment_id,
                    subject_id=subject.id,
                    instrument_id=str(instrument.get("instrument_id", "instrument.synthetic")),
                    instrument_version=str(instrument.get("version", "1.0")),
                    item_bank_version=record.cat_item_bank_version,
                    config_version=record.cat_config_version,
                    trace_id=str(record.assessment.get("timestamps", {}).get("trace_id") or "")
                    or trace_id,
                )
        db_record.status = self._status_upper(str(record.assessment.get("status", "created")))
        timestamps = record.assessment.get("timestamps", {})
        db_record.started_at = _as_datetime(timestamps.get("started_at")) or db_record.started_at
        db_record.completed_at = _as_datetime(timestamps.get("completed_at"))
        existing_responses = list(
            (
                await uow.session.scalars(
                    self._select(m.AssessmentResponse)
                    .where(m.AssessmentResponse.assessment_session_id == db_record.id)
                    .order_by(m.AssessmentResponse.sequence_no)
                )
            ).all()
        )
        existing_items = {item.item_ref for item in existing_responses}
        next_sequence = len(existing_responses) + 1
        for item_id, value in record.responses.items():
            if item_id in existing_items:
                continue
            await uow.assessments.append_response(
                assessment_session_id=db_record.id,
                sequence_no=next_sequence,
                item_ref=item_id,
                response_payload={"item_id": item_id, "value": value},
                trace_id=trace_id,
            )
            next_sequence += 1
        if db_record.status == "COMPLETED":
            protected = self.protection.encrypt_json(
                record.assessment, payload_schema_version="assessment-result.v1"
            )
            result_row = await uow.session.scalar(
                self._select(m.AssessmentResult).where(
                    m.AssessmentResult.assessment_session_id == db_record.id
                )
            )
            if result_row is None:
                result_row = m.AssessmentResult(
                    assessment_session_id=db_record.id,
                    schema_version="assessment.v1",
                )
                uow.session.add(result_row)
            result_row.payload_ciphertext = protected.ciphertext
            result_row.cipher_format_version = protected.cipher_format_version
            result_row.key_version = protected.key_version
            result_row.payload_schema_version = protected.payload_schema_version
            result_row.completed_at = db_record.completed_at or self._utc_now()
        await uow.session.flush()

    async def school_save_assessment_for_actor(
        self,
        actor: Any,
        record: AssessmentRecord,
        *,
        at: datetime,
        trace_id: str,
    ) -> None:
        """Reauthorize and persist a task assessment under the same row locks."""
        if (
            self.identity_profile != "school_tenant"
            or actor.scope_profile != "school_tenant"
            or actor.role is not BackendRole.STUDENT
            or actor.school_id is None
            or actor.school_ref is None
            or record.task_enrollment_id is None
        ):
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="assessment access is unavailable")
        m = self._db_models
        async with self._uow() as uow:
            account_id, _role_id = await self._school_actor_role(
                uow, actor, "student", at, lock=True
            )
            enrollment = await uow.school_operations.active_enrollment_for_assessment(
                assessment_ref=record.assessment_id,
                student_account_id=account_id,
                at=at,
            )
            if (
                enrollment is None
                or enrollment.id != record.task_enrollment_id
                or enrollment.school_id != actor.school_id
                or enrollment.subject_id is None
            ):
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="assessment access is unavailable")
            enrollment, task, subject = await self._lock_school_assessment_write_scope(
                uow, actor, account_id, enrollment, at=at
            )
            if subject.subject_ref != record.subject_id:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="assessment access is unavailable")
            try:
                db_record = await uow.assessments.get_session(record.assessment_id)
            except self._db_not_found:
                raise error(
                    ErrorCode.RESOURCE_NOT_FOUND,
                    detail="assessment session is unavailable",
                ) from None
            db_record = await uow.session.scalar(
                self._select(m.AssessmentSession)
                .where(
                    m.AssessmentSession.id == db_record.id,
                    m.AssessmentSession.assessment_ref == record.assessment_id,
                    m.AssessmentSession.subject_id == enrollment.subject_id,
                    m.AssessmentSession.task_enrollment_id == enrollment.id,
                )
                .with_for_update()
            )
            if db_record is None or db_record.status not in {"CREATED", "IN_PROGRESS"}:
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="assessment is no longer writable")
            binding_context = await self._school_task_assessment_binding(
                uow,
                actor,
                task,
                enrollment,
                db_record,
                at=at,
                lock_bindings=True,
            )
            instrument = record.assessment.get("instrument", {})
            saved_version_changed = binding_context["cat_binding_mode"] == "SAVED_VERSION" and (
                record.cat_item_bank_version != task.item_bank_version
                or record.cat_config_version != task.config_version
            )
            if (
                record.cat_binding_mode != binding_context["cat_binding_mode"]
                or record.saved_binding != binding_context["saved_binding"]
                or record.saved_bank_document != binding_context["saved_bank_document"]
                or record.saved_config_document != binding_context["saved_config_document"]
                or instrument.get("instrument_id") != task.instrument_id
                or instrument.get("version") != task.instrument_version
                or saved_version_changed
            ):
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="assessment CAT binding changed")
            next_status = self._status_upper(str(record.assessment.get("status", "created")))
            if next_status not in {"IN_PROGRESS", "COMPLETED"}:
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="assessment status is not writable")
            previous_status = db_record.status
            await self._save_assessment_in_uow(
                uow,
                record,
                db_record=db_record,
                trace_id=trace_id,
            )
            if (
                previous_status in {"CREATED", "IN_PROGRESS"}
                and next_status == "COMPLETED"
            ):
                if uow.post_assessment_jobs is None:
                    raise RuntimeError("post-assessment job repository is unavailable")
                await uow.post_assessment_jobs.enqueue(
                    school_id=enrollment.school_id,
                    task_id=task.id,
                    class_id=enrollment.class_id,
                    class_student_id=enrollment.class_student_id,
                    task_enrollment_id=enrollment.id,
                    subject_id=enrollment.subject_id,
                    assessment_session_id=db_record.id,
                    policy_version=_SCHOOL_POST_ASSESSMENT_POLICY_VERSION,
                )

    async def get_assessment(
        self, assessment_id: str, *, actor: Any = None, at: datetime | None = None
    ) -> AssessmentRecord | None:
        if actor is not None and (
            self.identity_profile != "school_tenant"
            or actor.scope_profile != "school_tenant"
            or actor.role is not BackendRole.STUDENT
            or actor.school_id is None
            or actor.school_ref is None
        ):
            return None
        m = self._db_models
        async with self._uow() as uow:
            task_enrollment = None
            try:
                db_record = await uow.assessments.get_session(assessment_id)
            except self._db_not_found:
                return None
            binding_context = {
                "task_enrollment_id": db_record.task_enrollment_id,
                "cat_binding_mode": db_record.cat_binding_mode,
                "saved_binding": None,
                "saved_bank_document": None,
                "saved_config_document": None,
            }
            if actor is not None and actor.scope_profile == "school_tenant":
                at = at or self._utc_now()
                account_id, _role_id = await self._school_actor_role(uow, actor, "student", at)
                if db_record.task_enrollment_id is not None:
                    task_enrollment = await uow.school_operations.active_enrollment_for_assessment(
                        assessment_ref=assessment_id,
                        student_account_id=account_id,
                        at=at,
                    )
                    if task_enrollment is None or task_enrollment.school_id != actor.school_id:
                        return None
                    task = await uow.session.get(m.MeasurementTask, task_enrollment.task_id)
                    if task is None or task.school_id != actor.school_id:
                        return None
                    binding_context = await self._school_task_assessment_binding(
                        uow,
                        actor,
                        task,
                        task_enrollment,
                        db_record,
                        at=at,
                    )
                elif db_record.cat_binding_mode == "SAVED_VERSION":
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT,
                        detail="saved CAT session has no task binding",
                    )
                else:
                    own_subject = await uow.session.scalar(
                        self._select(m.Subject.id)
                        .join(
                            m.SubjectAccessGrant,
                            (m.SubjectAccessGrant.subject_id == m.Subject.id)
                            & (m.SubjectAccessGrant.school_id == actor.school_id),
                        )
                        .join(
                            m.AccountSchoolMembership,
                            (
                                m.AccountSchoolMembership.account_id
                                == m.SubjectAccessGrant.principal_account_id
                            )
                            & (m.AccountSchoolMembership.school_id == actor.school_id),
                        )
                        .join(
                            m.MembershipRole,
                            m.MembershipRole.membership_id == m.AccountSchoolMembership.id,
                        )
                        .where(
                            m.Subject.id == db_record.subject_id,
                            m.Subject.school_id == actor.school_id,
                            m.Subject.status == self._db_enums.SubjectStatus.ACTIVE.value,
                            m.Subject.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                            m.SubjectAccessGrant.principal_account_id == account_id,
                            m.SubjectAccessGrant.relationship_type == "SELF",
                            m.SubjectAccessGrant.status == "ACTIVE",
                            m.SubjectAccessGrant.revoked_at.is_(None),
                            m.SubjectAccessGrant.valid_from <= at,
                            (m.SubjectAccessGrant.valid_until.is_(None))
                            | (m.SubjectAccessGrant.valid_until >= at),
                            m.AccountSchoolMembership.status == "ACTIVE",
                            m.AccountSchoolMembership.revoked_at.is_(None),
                            m.AccountSchoolMembership.valid_from <= at,
                            (m.AccountSchoolMembership.valid_until.is_(None))
                            | (m.AccountSchoolMembership.valid_until >= at),
                            m.MembershipRole.school_id == actor.school_id,
                            m.MembershipRole.role_code == "student",
                            m.MembershipRole.status == "ACTIVE",
                            m.MembershipRole.revoked_at.is_(None),
                            m.MembershipRole.valid_from <= at,
                            (m.MembershipRole.valid_until.is_(None))
                            | (m.MembershipRole.valid_until >= at),
                        )
                    )
                    if own_subject is None:
                        return None
            subject = await uow.session.get(m.Subject, db_record.subject_id)
            if subject is None:
                return None
            result_row = await uow.session.scalar(
                self._select(m.AssessmentResult).where(
                    m.AssessmentResult.assessment_session_id == db_record.id
                )
            )
            assessment = self._decrypt_result(result_row) if result_row else None
            response_rows = list(
                (
                    await uow.session.scalars(
                        self._select(m.AssessmentResponse)
                        .where(m.AssessmentResponse.assessment_session_id == db_record.id)
                        .order_by(m.AssessmentResponse.sequence_no)
                    )
                ).all()
            )
            responses: dict[str, Any] = {}
            for row in response_rows:
                payload = self._decrypt_response(row)
                if payload is not None:
                    responses[row.item_ref] = payload.get("value", payload.get("answer"))
            if not isinstance(assessment, dict):
                assessment = self._assessment_skeleton(
                    db_record, subject.subject_ref, len(responses)
                )
            provenance = assessment.get("provenance", {})
            if not isinstance(provenance, Mapping):
                provenance = {}
            return AssessmentRecord(
                assessment_id=assessment_id,
                subject_id=subject.subject_ref,
                assessment=assessment,
                data_origin=str(getattr(subject.data_origin, "value", subject.data_origin)),
                responses=responses,
                cat_provider_version=str(provenance.get("cat_engine_version") or "") or None,
                cat_item_bank_version=str(
                    provenance.get("item_bank_version") or db_record.item_bank_version or ""
                )
                or None,
                cat_config_version=db_record.config_version,
                answered_count=len(responses),
                administered_count=len(responses),
                task_enrollment_id=binding_context["task_enrollment_id"],
                cat_binding_mode=binding_context["cat_binding_mode"],
                saved_binding=binding_context["saved_binding"],
                saved_bank_document=binding_context["saved_bank_document"],
                saved_config_document=binding_context["saved_config_document"],
            )

    async def school_get_assessment_for_actor(
        self, actor: Any, assessment_id: str, *, at: datetime
    ) -> AssessmentRecord | None:
        if (
            self.identity_profile != "school_tenant"
            or actor.scope_profile != "school_tenant"
            or actor.role is not BackendRole.STUDENT
            or actor.school_id is None
            or actor.school_ref is None
        ):
            return None
        return await self.get_assessment(assessment_id, actor=actor, at=at)

    async def list_assessments_for_subjects(
        self,
        subject_ids: set[str],
        *,
        limit: int | None = None,
        skip: int = 0,
        status: str | None = None,
    ) -> list[AssessmentRecord]:
        if not subject_ids:
            return []
        m = self._db_models
        async with self._uow() as uow:
            statement = (
                self._select(m.AssessmentSession.assessment_ref)
                .join(m.Subject, m.Subject.id == m.AssessmentSession.subject_id)
                .where(m.Subject.subject_ref.in_(subject_ids))
                .order_by(
                    m.AssessmentSession.started_at.desc(),
                    m.AssessmentSession.assessment_ref.desc(),
                )
            )
            if status is not None:
                statement = statement.where(m.AssessmentSession.status == status.upper())
            if skip:
                statement = statement.offset(skip)
            if limit is not None:
                statement = statement.limit(limit)
            refs = list((await uow.session.scalars(statement)).all())
        records: list[AssessmentRecord] = []
        for assessment_id in refs:
            record = await self.get_assessment(assessment_id)
            if record is not None:
                records.append(record)
        return records

    def _school_assessment_scope_statement(
        self,
        actor: Any,
        subject_refs: set[str],
        *,
        now: datetime,
        account_id: int,
        role_id: int,
        status: str | None,
        limit: int | None,
        skip: int,
        metadata_only: bool,
    ):
        """Build the shared, pre-pagination school student authorization query."""
        m = self._db_models
        from sqlalchemy import and_, or_

        if metadata_only:
            from sqlalchemy import func

            response_count = (
                self._select(func.count(m.AssessmentResponse.id))
                .where(
                    m.AssessmentResponse.assessment_session_id == m.AssessmentSession.id
                )
                .scalar_subquery()
            )
            selected = (
                m.AssessmentSession.assessment_ref,
                m.AssessmentSession.status,
                response_count,
                m.AssessmentSession.started_at,
                m.AssessmentSession.completed_at,
            )
        else:
            selected = (
                m.AssessmentSession.assessment_ref,
                m.AssessmentSession.started_at,
            )

        statement = (
            self._select(*selected)
            .join(m.Subject, m.Subject.id == m.AssessmentSession.subject_id)
            .outerjoin(
                m.TaskEnrollment,
                (m.TaskEnrollment.id == m.AssessmentSession.task_enrollment_id)
                & (m.TaskEnrollment.subject_id == m.AssessmentSession.subject_id),
            )
            .outerjoin(
                m.SchoolClassStudent,
                (m.SchoolClassStudent.id == m.TaskEnrollment.class_student_id)
                & (m.SchoolClassStudent.subject_id == m.TaskEnrollment.subject_id)
                & (m.SchoolClassStudent.class_id == m.TaskEnrollment.class_id)
                & (m.SchoolClassStudent.school_id == m.TaskEnrollment.school_id),
            )
            .outerjoin(
                m.SchoolClass,
                (m.SchoolClass.id == m.TaskEnrollment.class_id)
                & (m.SchoolClass.school_id == m.TaskEnrollment.school_id),
            )
            .outerjoin(
                m.MeasurementTask,
                (m.MeasurementTask.id == m.TaskEnrollment.task_id)
                & (m.MeasurementTask.school_id == m.TaskEnrollment.school_id)
                & (m.MeasurementTask.class_id == m.TaskEnrollment.class_id),
            )
            .join(
                m.SubjectAccessGrant,
                (m.SubjectAccessGrant.subject_id == m.Subject.id)
                & (m.SubjectAccessGrant.school_id == actor.school_id),
            )
            .join(
                m.AccountSchoolMembership,
                (m.AccountSchoolMembership.account_id
                 == m.SubjectAccessGrant.principal_account_id)
                & (m.AccountSchoolMembership.school_id == actor.school_id),
            )
            .join(
                m.MembershipRole,
                m.MembershipRole.membership_id == m.AccountSchoolMembership.id,
            )
            .where(
                m.Subject.subject_ref.in_(subject_refs),
                m.Subject.school_id == actor.school_id,
                m.Subject.status == self._db_enums.SubjectStatus.ACTIVE.value,
                m.Subject.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                m.SubjectAccessGrant.principal_account_id == account_id,
                m.SubjectAccessGrant.relationship_type == "SELF",
                m.SubjectAccessGrant.status == "ACTIVE",
                m.SubjectAccessGrant.revoked_at.is_(None),
                m.SubjectAccessGrant.valid_from <= now,
                (m.SubjectAccessGrant.valid_until.is_(None))
                | (m.SubjectAccessGrant.valid_until >= now),
                m.AccountSchoolMembership.status == "ACTIVE",
                m.AccountSchoolMembership.revoked_at.is_(None),
                m.AccountSchoolMembership.valid_from <= now,
                (m.AccountSchoolMembership.valid_until.is_(None))
                | (m.AccountSchoolMembership.valid_until >= now),
                m.MembershipRole.id == role_id,
                m.MembershipRole.school_id == actor.school_id,
                m.MembershipRole.role_code == "student",
                m.MembershipRole.status == "ACTIVE",
                m.MembershipRole.revoked_at.is_(None),
                m.MembershipRole.valid_from <= now,
                (m.MembershipRole.valid_until.is_(None))
                | (m.MembershipRole.valid_until >= now),
                or_(
                    and_(
                        m.AssessmentSession.task_enrollment_id.is_(None),
                        m.TaskEnrollment.id.is_(None),
                    ),
                    and_(
                        m.AssessmentSession.task_enrollment_id.is_not(None),
                        m.TaskEnrollment.status == "ACTIVE",
                        m.SchoolClassStudent.status == "ACTIVE",
                        m.SchoolClassStudent.revoked_at.is_(None),
                        m.SchoolClassStudent.valid_from <= now,
                        (m.SchoolClassStudent.valid_until.is_(None))
                        | (m.SchoolClassStudent.valid_until >= now),
                        m.SchoolClass.status == "ACTIVE",
                        m.MeasurementTask.status == "PUBLISHED",
                        m.MeasurementTask.opens_at <= now,
                        (m.MeasurementTask.due_at.is_(None))
                        | (m.MeasurementTask.due_at >= now),
                        m.TaskEnrollment.school_id == actor.school_id,
                        m.Subject.school_id == actor.school_id,
                    ),
                ),
            )
            .distinct()
            .order_by(
                m.AssessmentSession.started_at.desc(),
                m.AssessmentSession.assessment_ref.desc(),
            )
        )
        if status is not None:
            statement = statement.where(m.AssessmentSession.status == status.upper())
        if skip:
            statement = statement.offset(skip)
        if limit is not None:
            statement = statement.limit(limit)
        return statement

    async def school_list_assessment_metadata_for_actor(
        self,
        actor: Any,
        subject_refs: set[str],
        *,
        limit: int,
        skip: int,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return authorized lifecycle metadata without loading encrypted payloads."""
        if (
            self.identity_profile != "school_tenant"
            or actor.scope_profile != "school_tenant"
            or actor.role is not BackendRole.STUDENT
            or actor.school_id is None
            or actor.school_ref is None
            or not subject_refs
        ):
            return []
        async with self._uow() as uow:
            now = self._utc_now()
            account_id, role_id = await self._school_actor_role(uow, actor, "student", now)
            statement = self._school_assessment_scope_statement(
                actor,
                subject_refs,
                now=now,
                account_id=account_id,
                role_id=role_id,
                status=status,
                limit=limit,
                skip=skip,
                metadata_only=True,
            )
            rows = list((await uow.session.execute(statement)).all())
        return [
            {
                "assessment_id": row[0],
                "status": str(row[1]).lower(),
                "items_answered": int(row[2]),
                "started_at": _database_utc_datetime(row[3]),
                "completed_at": _database_utc_datetime(row[4]),
            }
            for row in rows
        ]

    async def school_list_assessments_for_actor(
        self,
        actor: Any,
        subject_refs: set[str],
        *,
        limit: int | None = None,
        skip: int = 0,
        status: str | None = None,
    ) -> list[AssessmentRecord]:
        """List records in the current student's authorized assessment scope.

        Membership, SELF grant, and task lifecycle/window predicates are
        applied before pagination. Each row is rechecked in the same UOW as
        decryption to close the revocation race.
        """
        if (
            actor.scope_profile != "school_tenant"
            or actor.role is not BackendRole.STUDENT
            or actor.school_id is None
            or actor.school_ref is None
            or not subject_refs
        ):
            return []
        async with self._uow() as uow:
            now = self._utc_now()
            account_id, role_id = await self._school_actor_role(uow, actor, "student", now)
            statement = self._school_assessment_scope_statement(
                actor,
                subject_refs,
                now=now,
                account_id=account_id,
                role_id=role_id,
                status=status,
                limit=limit,
                skip=skip,
                metadata_only=False,
            )
            refs = list((await uow.session.scalars(statement)).all())
        records = []
        for assessment_ref in refs:
            record = await self.get_assessment(assessment_ref, actor=actor, at=self._utc_now())
            if record is not None:
                records.append(record)
        return records

    def _decrypt_result(self, row) -> dict[str, Any] | None:
        if row is None or row.payload_ciphertext is None:
            return None
        from database_layer.crypto import EncryptedPayload

        value = self.protection.decrypt_json(
            EncryptedPayload(
                ciphertext=row.payload_ciphertext,
                key_version=row.key_version or "",
                cipher_format_version=row.cipher_format_version or "",
                payload_schema_version=row.payload_schema_version or "",
            )
        )
        return value if isinstance(value, dict) else None

    def _decrypt_response(self, row) -> dict[str, Any] | None:
        if row.response_ciphertext is None:
            return None
        from database_layer.crypto import EncryptedPayload

        value = self.protection.decrypt_json(
            EncryptedPayload(
                ciphertext=row.response_ciphertext,
                key_version=row.key_version or "",
                cipher_format_version=row.cipher_format_version or "",
                payload_schema_version=row.payload_schema_version or "",
            )
        )
        return value if isinstance(value, dict) else None

    @staticmethod
    def _assessment_skeleton(db_record, subject_ref: str, response_count: int) -> dict[str, Any]:
        status = str(db_record.status).lower()
        return {
            "schema_version": "assessment.v1",
            "assessment_id": db_record.assessment_ref,
            "subject_id": subject_ref,
            "instrument": {
                "instrument_id": db_record.instrument_id,
                "version": db_record.instrument_version,
            },
            "population_scope": "synthetic_demo",
            "status": status,
            "dimensions": {
                "wellbeing": {
                    "theta": None,
                    "se": None,
                    "score": None,
                    "band": "unknown",
                    "interpretation_status": "insufficient_data",
                    "items_answered": response_count,
                }
            },
            "risk": {
                "level": "normal",
                "need_human_review": False,
                "reason_codes": ["PERSISTED_SYNTHETIC_FIXTURE"],
                "ruleset_id": "RULESET_persisted_synthetic_fixture",
            },
            "response_summary": {"items_answered": response_count, "duration_seconds": None},
            "provenance": {
                "source_adapter": "backend-mysql-rehydration",
                "adapter_version": "1.0",
                "cat_engine_version": "not_available",
                "item_bank_version": db_record.item_bank_version or "not_available",
            },
            "timestamps": {
                "started_at": db_record.started_at.isoformat() + "Z"
                if db_record.started_at
                else None,
                "completed_at": db_record.completed_at.isoformat() + "Z"
                if db_record.completed_at
                else None,
            },
        }

    # ------------------------------------------------------------------
    # Support workflow: TX-A / TX-B / failure transition
    # ------------------------------------------------------------------

    async def begin_workflow(
        self,
        *,
        report_id: str,
        assessment_id: str,
        subject_id: str,
        target_role: str,
        message: str,
        generation_id: str,
        trace_id: str,
        request_id: str,
    ) -> None:
        m = self._db_models
        async with self._uow() as uow:
            run = await uow.session.scalar(
                self._select(m.SupportRun).where(m.SupportRun.run_ref == report_id)
            )
            if run is not None:
                return
            subject = await uow.subjects.get_by_ref(subject_id)
            assessment = await uow.assessments.get_session(assessment_id)
            if subject is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="subject not found")
            support = await uow.support.create_session(
                support_ref=f"SUPPORT_{report_id}",
                subject_id=subject.id,
                target_role=target_role,
                assessment_session_id=assessment.id,
                trace_id=trace_id,
                retention_due_at=None,
            )
            await uow.support.create_run(
                run_ref=report_id,
                support_session_id=support.id,
                assessment_session_id=assessment.id,
                generation_ref=generation_id,
                trace_id=trace_id,
                status=self._db_enums.SupportRunStatus.REQUESTED,
                workflow_action="REQUESTED",
                component_versions={"persistence": "MYSQL", "state": "REQUESTED"},
            )
            await uow.support.persist_message(
                support_session_id=support.id,
                sequence_no=1,
                message_kind=self._db_enums.MessageKind.USER_INPUT,
                payload={
                    "text": message,
                    "request_id": request_id,
                    "synthetic_fixture_only": True,
                },
            )

    async def complete_workflow(self, result: Any) -> None:
        m = self._db_models
        e = self._db_enums
        async with self._uow() as uow:
            run = await uow.session.scalar(
                self._select(m.SupportRun).where(m.SupportRun.run_ref == result.report_id)
            )
            if run is None:
                return
            action = e.SafetyAction(result.safety_action)
            decision = await uow.session.scalar(
                self._select(m.SafetyDecision)
                .where(m.SafetyDecision.support_run_id == run.id)
                .order_by(m.SafetyDecision.created_at.desc())
            )
            generation = (
                result.generation.model_dump(mode="json")
                if hasattr(result.generation, "model_dump")
                else result.generation
                if isinstance(result.generation, dict)
                else {}
            )
            detail = {
                "generation": generation,
                "reason_codes": list(generation.get("safety", {}).get("reason_codes", [])),
                "candidate_persisted": False,
                "synthetic_fixture_only": True,
            }
            if decision is None:
                decision = await uow.support.create_safety_decision(
                    decision_ref=f"SAFE_{result.report_id}",
                    support_run_id=run.id,
                    action=action,
                    policy_version="safety-engine.v1",
                    guard_model_revision="Qwen3Guard-round1",
                    trace_id=str(result.trace_id),
                    detail=detail,
                    retention_due_at=None,
                )
            run.status = (
                e.SupportRunStatus.COMPLETED.value
                if result.normal_generation
                else e.SupportRunStatus.BLOCKED.value
            )
            run.workflow_action = action.value
            run.generation_ref = str(generation.get("generation_id") or run.generation_ref or "")
            run.retrieval_ref = str(
                generation.get("provenance", {}).get("retrieval_id") or run.retrieval_ref or ""
            )
            run.component_versions = {
                "persistence": "MYSQL",
                "safety_action": action.value,
                "candidate_persisted": False,
            }
            run.completed_at = self._utc_now()
            if result.normal_generation and result.content is not None:
                existing = await uow.session.scalar(
                    self._select(m.SupportMessage).where(
                        m.SupportMessage.support_session_id == run.support_session_id,
                        m.SupportMessage.message_kind == e.MessageKind.APPROVED_OUTPUT.value,
                    )
                )
                if existing is None:
                    await uow.support.persist_message(
                        support_session_id=run.support_session_id,
                        sequence_no=2,
                        message_kind=e.MessageKind.APPROVED_OUTPUT,
                        payload={"generation": generation},
                        safety_decision_id=decision.id,
                    )
            for rank, citation in enumerate(result.citations, start=1):
                citation_id, source_id = self._citation_ids(citation)
                existing = await uow.session.scalar(
                    self._select(m.SupportEvidence).where(
                        m.SupportEvidence.support_run_id == run.id,
                        m.SupportEvidence.citation_id == citation_id,
                    )
                )
                if existing is None:
                    await uow.support.add_evidence(
                        support_run_id=run.id,
                        citation_id=citation_id,
                        source_id=source_id,
                        chunk_id=getattr(citation, "chunk_id", None),
                        document_id=getattr(citation, "document_id", None),
                        source_version=getattr(citation, "source_version", None) or "knowledge.v1",
                        source_hash=getattr(citation, "source_hash", None),
                        citation_title=getattr(citation, "title", None),
                        citation_organization=getattr(citation, "organization", None),
                        locator=getattr(citation, "locator", None),
                        rank_order=getattr(citation, "rank", None) or rank,
                    )
            if result.review_reference:
                existing_case = await uow.session.scalar(
                    self._select(m.ReviewCase).where(
                        m.ReviewCase.review_ref == result.review_reference
                    )
                )
                if existing_case is None:
                    priority = (
                        e.ReviewPriority.URGENT
                        if action == e.SafetyAction.CRISIS_ROUTE
                        else e.ReviewPriority.HIGH
                    )
                    await uow.reviews.create_case(
                        review_ref=result.review_reference,
                        subject_id=(
                            await uow.session.get(m.SupportSession, run.support_session_id)
                        ).subject_id,
                        safety_decision_id=decision.id,
                        priority=priority,
                        case_note={
                            "reason_codes": detail["reason_codes"],
                            "report_id": result.report_id,
                            "synthetic_fixture_only": True,
                        },
                        retention_due_at=None,
                    )

    async def fail_workflow(
        self,
        report_id: str,
        *,
        reason_code: str,
        trace_id: str,
        stage_diagnostics: dict[str, Any] | None = None,
    ) -> None:
        async with self._uow() as uow:
            run = await uow.session.scalar(
                self._select(self._db_models.SupportRun).where(
                    self._db_models.SupportRun.run_ref == report_id
                )
            )
            if run is not None:
                run.status = self._db_enums.SupportRunStatus.FAILED.value
                run.workflow_action = "FAILED"
                run.component_versions = {
                    "persistence": "MYSQL",
                    "reason_code": reason_code,
                    "candidate_persisted": False,
                    **sanitize_support_stage_diagnostics(stage_diagnostics),
                }
                run.trace_id = trace_id
                run.completed_at = self._utc_now()

    async def save_metadata(
        self, *, request_id: str, trace_id: str, metadata: dict[str, Any]
    ) -> None:
        # The user message and workflow state are persisted by begin/complete.
        # Keep this non-sensitive projection only for in-process diagnostics.
        self._metadata_records.append(
            {"request_id": request_id, "trace_id": trace_id, "metadata": dict(metadata)}
        )

    @staticmethod
    def _citation_ids(citation) -> tuple[str, str]:
        explicit_citation_id = getattr(citation, "citation_id", None)
        explicit_source_id = getattr(citation, "document_id", None)
        if explicit_citation_id:
            return str(explicit_citation_id), str(explicit_source_id or explicit_citation_id)
        value = f"{citation.title}|{citation.organization}|{citation.locator}"
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
        return f"CITE_{digest}", f"SRC_{digest}"

    async def _save_report(self, report: ReportRecord) -> None:
        # ``complete_workflow`` is invoked by SupportOrchestrator after the
        # report projection has been safety-approved or blocked.  Keeping the
        # projection write here as a no-op prevents a second persistence path
        # from bypassing the workflow state machine.
        return None

    async def _get_report(self, report_id: str) -> ReportRecord | None:
        m = self._db_models
        async with self._uow() as uow:
            run = await uow.session.scalar(
                self._select(m.SupportRun).where(m.SupportRun.run_ref == report_id)
            )
            if run is None:
                return None
            assessment = await uow.session.get(m.AssessmentSession, run.assessment_session_id)
            support = await uow.session.get(m.SupportSession, run.support_session_id)
            if assessment is None or support is None:
                return None
            decision = await uow.session.scalar(
                self._select(m.SafetyDecision)
                .where(m.SafetyDecision.support_run_id == run.id)
                .order_by(m.SafetyDecision.created_at.desc())
            )
            case = None
            if decision is not None:
                case = await uow.session.scalar(
                    self._select(m.ReviewCase)
                    .where(m.ReviewCase.safety_decision_id == decision.id)
                    .order_by(m.ReviewCase.created_at.desc())
                )
            approved = await uow.session.scalar(
                self._select(m.SupportMessage).where(
                    m.SupportMessage.support_session_id == support.id,
                    m.SupportMessage.message_kind == "APPROVED_OUTPUT",
                )
            )
            generation: dict[str, Any] | None = None
            if approved is not None:
                payload = self._decrypt_support_message(approved)
                if isinstance(payload, dict) and isinstance(payload.get("generation"), dict):
                    generation = payload["generation"]
            if generation is None and decision is not None:
                detail = self._decrypt_safety_detail(decision)
                if isinstance(detail, dict) and isinstance(detail.get("generation"), dict):
                    generation = detail["generation"]
            generation = generation or self._fallback_blocked_generation(run, assessment, decision)
            evidence_rows = list(
                (
                    await uow.session.scalars(
                        self._select(m.SupportEvidence)
                        .where(m.SupportEvidence.support_run_id == run.id)
                        .order_by(m.SupportEvidence.rank_order, m.SupportEvidence.id)
                    )
                ).all()
            )
            citations = [
                {
                    "citation_id": row.citation_id,
                    "chunk_id": row.chunk_id,
                    "document_id": row.document_id,
                    "title": row.citation_title,
                    "organization": row.citation_organization,
                    "locator": row.locator,
                    "rank": row.rank_order,
                    "source_version": row.source_version,
                    "source_hash": row.source_hash,
                }
                for row in evidence_rows
            ]
            review_status = "not_required"
            review_id = case.review_ref if case else None
            if case is not None:
                review_status = {
                    "OPEN": "pending",
                    "ASSIGNED": "in_review",
                    "IN_REVIEW": "in_review",
                    "APPROVED": "approved",
                    "REJECTED": "rejected",
                    "CLOSED": "closed",
                }.get(case.status, str(case.status).lower())
            status = "generated" if run.status == "COMPLETED" else "safety_blocked"
            if review_status not in {"not_required", "pending", "in_review"}:
                status = review_status
            elif review_status in {"pending", "in_review"}:
                status = "needs_review"
            return ReportRecord(
                report_id=report_id,
                assessment_id=assessment.assessment_ref,
                subject_id=support.subject_id
                and await self._subject_ref(uow, support.subject_id)
                or "",
                generation_id=str(generation.get("generation_id") or run.generation_ref or ""),
                status=status,
                generation=generation,
                review_id=review_id,
                review_status=review_status,
                safety_action=str(
                    run.workflow_action or (decision.action if decision else "BLOCK")
                ),
                citations=citations,
                candidate_source=str(
                    generation.get("provenance", {}).get("candidate_source")
                    or (
                        "NOT_RUN"
                        if generation.get("provenance", {}).get("model_id") is None
                        else "MODEL_EXECUTED"
                    )
                ),
            )

    async def list_for_subjects(
        self,
        subject_ids: set[str],
        assessment_id: str | None = None,
        limit: int = 100,
    ) -> list[ReportRecord]:
        if not subject_ids:
            return []
        m = self._db_models
        limit = max(1, min(limit, 100))
        async with self._uow() as uow:
            statement = (
                self._select(
                    m.SupportRun.run_ref,
                    m.SupportRun.completed_at,
                    m.SupportRun.created_at,
                )
                .join(
                    m.AssessmentSession,
                    m.AssessmentSession.id == m.SupportRun.assessment_session_id,
                )
                .join(m.Subject, m.Subject.id == m.AssessmentSession.subject_id)
                .where(m.Subject.subject_ref.in_(subject_ids))
            )
            if assessment_id is not None:
                statement = statement.where(m.AssessmentSession.assessment_ref == assessment_id)
            rows = list(
                (
                    await uow.session.execute(
                        statement.order_by(m.SupportRun.created_at.desc()).limit(limit)
                    )
                ).all()
            )

        records: list[ReportRecord] = []
        for report_id, completed_at, created_at in rows:
            record = await self._get_report(report_id)
            if record is None:
                continue
            timestamp = completed_at or created_at
            if isinstance(timestamp, datetime):
                if timestamp.tzinfo:
                    timestamp = timestamp.astimezone(UTC)
                else:
                    timestamp = timestamp.replace(tzinfo=UTC)
                timestamp = timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")
            record.generation["created_at"] = str(timestamp)
            records.append(record)
        return records

    async def _subject_ref(self, uow, subject_id: int) -> str:
        subject = await uow.session.get(self._db_models.Subject, subject_id)
        return subject.subject_ref if subject else ""

    def _decrypt_support_message(self, row) -> dict[str, Any] | None:
        if row.payload_ciphertext is None:
            return None
        from database_layer.crypto import EncryptedPayload

        return self.protection.decrypt_json(
            EncryptedPayload(
                ciphertext=row.payload_ciphertext,
                key_version=row.key_version or "",
                cipher_format_version=row.cipher_format_version or "",
                payload_schema_version=row.payload_schema_version or "",
            )
        )

    def _decrypt_safety_detail(self, row) -> dict[str, Any] | None:
        if row.detail_ciphertext is None:
            return None
        from database_layer.crypto import EncryptedPayload

        return self.protection.decrypt_json(
            EncryptedPayload(
                ciphertext=row.detail_ciphertext,
                key_version=row.key_version or "",
                cipher_format_version=row.cipher_format_version or "",
                payload_schema_version=row.payload_schema_version or "",
            )
        )

    @staticmethod
    def _fallback_blocked_generation(run, assessment, decision) -> dict[str, Any]:
        action = str(run.workflow_action or (decision.action if decision else "BLOCK"))
        return {
            "schema_version": "generation.v1",
            "generation_id": run.generation_ref or "GEN_persisted",
            "status": "needs_review"
            if action in {"REVIEW_REQUIRED", "CRISIS_ROUTE"}
            else "safety_blocked",
            "target_role": "student",
            "content": None,
            "safety": {
                "precheck": "blocked",
                "postcheck": "blocked",
                "reason_codes": ["PERSISTED_WORKFLOW"],
                "human_review_required": action in {"BLOCK", "REVIEW_REQUIRED", "CRISIS_ROUTE"},
            },
            "provenance": {
                "assessment_id": assessment.assessment_ref,
                "retrieval_id": run.retrieval_ref or "RETR_not_run",
                "prompt_id": "PROMPT_persisted",
                "prompt_version": "1.0",
                "model_id": None,
                "model_version": None,
                "runtime_version": None,
            },
            "review": {
                "status": "pending"
                if action in {"BLOCK", "REVIEW_REQUIRED", "CRISIS_ROUTE"}
                else "not_required",
                "reviewer_id": None,
                "reviewed_at": None,
            },
            "created_at": run.created_at.isoformat() + "Z",
        }

    # ------------------------------------------------------------------
    # Review projection and audit
    # ------------------------------------------------------------------

    async def _review_projection(self, uow, case) -> ReviewProjection | None:
        m = self._db_models
        decision = await uow.session.get(m.SafetyDecision, case.safety_decision_id)
        if decision is None:
            return None
        run = await uow.session.get(m.SupportRun, decision.support_run_id)
        if run is None:
            return None
        assessment = await uow.session.get(m.AssessmentSession, run.assessment_session_id)
        detail = self._decrypt_safety_detail(decision) or {}
        reason_codes = detail.get("reason_codes", [])
        return ReviewProjection(
            review_id=case.review_ref,
            report_id=run.run_ref,
            assessment_id=assessment.assessment_ref if assessment else "",
            subject_id=await self._subject_ref(uow, case.subject_id),
            generation_id=run.generation_ref or "",
            status={
                "OPEN": "pending",
                "ASSIGNED": "in_review",
                "IN_REVIEW": "in_review",
                "APPROVED": "approved",
                "REJECTED": "rejected",
                "CLOSED": "closed",
            }.get(case.status, str(case.status).lower()),
            reason_codes=[str(item) for item in reason_codes]
            if isinstance(reason_codes, list)
            else [],
            safety_action=decision.action,
            safety_review_case_id=case.review_ref,
            created_at=case.created_at.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z"),
            updated_at=case.updated_at.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z"),
        )

    async def get_review_projection(self, review_id: str) -> ReviewProjection | None:
        async with self._uow() as uow:
            case = await uow.session.scalar(
                self._select(self._db_models.ReviewCase).where(
                    self._db_models.ReviewCase.review_ref == review_id
                )
            )
            return await self._review_projection(uow, case) if case else None

    async def list_pending(self) -> list[ReviewProjection]:
        async with self._uow() as uow:
            cases = list(
                (
                    await uow.session.scalars(
                        self._select(self._db_models.ReviewCase).where(
                            self._db_models.ReviewCase.status.in_(("OPEN", "ASSIGNED", "IN_REVIEW"))
                        )
                    )
                ).all()
            )
            values = []
            for case in cases:
                projection = await self._review_projection(uow, case)
                if projection is not None:
                    values.append(projection)
            return values

    async def save_review(self, projection: ReviewProjection) -> None:
        e = self._db_enums
        status_map = {
            "pending": e.ReviewStatus.OPEN,
            "in_review": e.ReviewStatus.IN_REVIEW,
            "approved": e.ReviewStatus.APPROVED,
            "rejected": e.ReviewStatus.REJECTED,
            "closed": e.ReviewStatus.CLOSED,
        }
        async with self._uow() as uow:
            case = await uow.session.scalar(
                self._select(self._db_models.ReviewCase).where(
                    self._db_models.ReviewCase.review_ref == projection.review_id
                )
            )
            if case is None:
                return
            status = status_map.get(projection.status)
            if status is None or case.status == status.value:
                return
            await uow.reviews.update_case(
                review_case_id=case.id,
                expected_version=case.version,
                status=status,
                closed_at=self._utc_now()
                if status
                in {e.ReviewStatus.APPROVED, e.ReviewStatus.REJECTED, e.ReviewStatus.CLOSED}
                else None,
            )
            await uow.reviews.add_event(
                review_case_id=case.id,
                event_type=e.ReviewEventType.DECISION_RECORDED,
                actor_account_id=None,
                to_status=status.value,
                note={"synthetic_fixture_only": True},
                trace_id=None,
                retention_due_at=None,
            )

    async def append(self, event: AuditEvent) -> None:
        outcome = {
            "accepted": self._db_enums.AuditResult.SUCCESS,
            "generated": self._db_enums.AuditResult.SUCCESS,
            "approved": self._db_enums.AuditResult.SUCCESS,
            "denied": self._db_enums.AuditResult.DENIED,
        }.get(event.outcome, self._db_enums.AuditResult.FAILURE)
        safe_metadata: dict[str, object] = {
            "source": "backend",
            "state": event.outcome,
        }
        if event.metadata.get("synthetic_fixture_only") is True:
            safe_metadata["source"] = "synthetic_fixture"
        count = event.metadata.get("citation_count")
        if isinstance(count, int):
            safe_metadata["count"] = count
        actor_account_id = None
        if event.actor_id:
            try:
                public_id = _database_public_id(event.actor_id, "USER")
                actor_account_id = await self._account_id_by_public_id(public_id)
            except ValueError:
                actor_account_id = None
        async with self._uow() as uow:
            await uow.audit.append(
                action=event.event,
                resource_type="backend_workflow",
                resource_public_id=None,
                result=outcome,
                trace_id=event.trace_id,
                actor_account_id=actor_account_id,
                safe_metadata=safe_metadata,
            )
        self._audit_cache.append(event)

    async def _account_id_by_public_id(self, public_id: str) -> int | None:
        async with self._uow() as uow:
            account = await uow.session.scalar(
                self._select(self._db_models.Account).where(
                    self._db_models.Account.public_id == public_id
                )
            )
            return account.id if account else None

    async def list(self) -> list[AuditEvent]:
        return list(self._audit_cache)

    # ------------------------------------------------------------------
    # Durable idempotency claim/result reference
    # ------------------------------------------------------------------

    async def _get_idempotency(self, scope: str, key: str) -> IdempotencyRecord | None:
        async with self._uow() as uow:
            row = await uow.session.scalar(
                self._select(self._db_models.IdempotencyRecord).where(
                    self._db_models.IdempotencyRecord.scope == scope,
                    self._db_models.IdempotencyRecord.key_hash == _hash_token(key),
                )
            )
            if row is None or row.expires_at <= self._utc_now():
                return None
            return IdempotencyRecord(
                fingerprint=row.request_hash.hex(),
                status_code=200,
                body=dict(self._idempotency_bodies.get((scope, key), {})),
                created_at=_as_timestamp(row.created_at),
            )

    async def claim(self, scope: str, key: str, request_fingerprint: str) -> bool:
        """Atomically reserve a write before any external dependency call."""

        m = self._db_models
        request_hash = bytes.fromhex(request_fingerprint)
        expires_at = self._utc_now() + timedelta(hours=24)
        async with self._uow() as uow:
            row = await uow.session.scalar(
                self._select(m.IdempotencyRecord).where(
                    m.IdempotencyRecord.scope == scope,
                    m.IdempotencyRecord.key_hash == _hash_token(key),
                )
            )
            if row is not None and row.expires_at > self._utc_now():
                if row.request_hash != request_hash:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT,
                        detail="idempotency key was already used for another request",
                    )
                if row.state != self._db_enums.IdempotencyState.COMPLETED.value:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT,
                        detail="idempotency request is already in progress",
                    )
                return False
            if row is None:
                row = m.IdempotencyRecord(
                    scope=scope,
                    key_hash=_hash_token(key),
                    request_hash=request_hash,
                    state=self._db_enums.IdempotencyState.IN_PROGRESS.value,
                    expires_at=expires_at,
                )
                uow.session.add(row)
            else:
                row.request_hash = request_hash
                row.state = self._db_enums.IdempotencyState.IN_PROGRESS.value
                row.result_resource_type = None
                row.result_public_id = None
                row.expires_at = expires_at
            try:
                await uow.session.flush()
            except self._integrity_error as exc:
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT,
                    detail="idempotency request is already in progress",
                ) from exc
            return True

    async def put(self, scope: str, key: str, record: IdempotencyRecord) -> None:  # type: ignore[override]
        m = self._db_models
        fingerprint_bytes = bytes.fromhex(record.fingerprint)
        result_id = (
            (
                record.body.get("data", {}).get("report_id")
                if isinstance(record.body.get("data"), Mapping)
                else None
            )
            or record.body.get("report_id")
            or record.body.get("assessment_id")
        )
        resource_type = (
            "report"
            if isinstance(result_id, str) and result_id.startswith("REPORT_")
            else "assessment"
        )
        async with self._uow() as uow:
            row = await uow.session.scalar(
                self._select(m.IdempotencyRecord).where(
                    m.IdempotencyRecord.scope == scope,
                    m.IdempotencyRecord.key_hash == _hash_token(key),
                )
            )
            if row is None:
                row = m.IdempotencyRecord(
                    scope=scope,
                    key_hash=_hash_token(key),
                    request_hash=fingerprint_bytes,
                    state=self._db_enums.IdempotencyState.COMPLETED.value,
                    result_resource_type=resource_type,
                    result_public_id=str(result_id) if result_id else None,
                    expires_at=self._utc_now() + timedelta(hours=24),
                )
                uow.session.add(row)
            else:
                if row.request_hash != fingerprint_bytes:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT,
                        detail="idempotency key was already used for another request",
                    )
                row.state = self._db_enums.IdempotencyState.COMPLETED.value
                row.result_resource_type = resource_type
                row.result_public_id = str(result_id) if result_id else None
            await uow.session.flush()
        self._idempotency_bodies[(scope, key)] = dict(record.body)

    async def get(self, *args):
        """Dispatch the shared port method without coupling the ports."""

        if len(args) == 2:
            return await self._get_idempotency(args[0], args[1])
        if len(args) != 1:
            raise TypeError("database adapter get expects one or two arguments")
        value = args[0]
        if isinstance(value, str) and value.startswith("USER_"):
            return await self._get_user(value)
        if isinstance(value, str) and value.startswith("ASSESS_"):
            return await self.get_assessment(value)
        if isinstance(value, str) and value.startswith("REPORT_"):
            return await self._get_report(value)
        if isinstance(value, str) and value.startswith("REVIEW_"):
            return await self.get_review_projection(value)
        return await self._get_session(value)

    async def save(self, value) -> None:
        if isinstance(value, AssessmentRecord):
            await self._save_assessment(value)
            return
        if isinstance(value, ReportRecord):
            await self._save_report(value)
            return
        if isinstance(value, ReviewProjection):
            await self.save_review(value)
            return
        raise TypeError(f"unsupported database persistence value: {type(value)!r}")


__all__ = ["MySqlBackendAdapter"]
