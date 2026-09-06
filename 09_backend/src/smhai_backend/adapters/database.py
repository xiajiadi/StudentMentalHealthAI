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
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pwdlib import PasswordHash

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.models import (
    AssessmentRecord,
    AuditEvent,
    BackendRole,
    IdempotencyRecord,
    ReportRecord,
    ReviewProjection,
    SessionRecord,
    SyntheticUser,
)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _as_datetime(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo else parsed


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

    def __init__(self, *, repository_root: Path | None = None) -> None:
        try:
            from database_layer import (
                DatabaseSettings,
                DevLocalKeyProvider,
                FernetDataProtectionProvider,
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
        protection = FernetDataProtectionProvider(
            DevLocalKeyProvider.from_env(repository_root=root)
        )
        self.engine = create_engine(self.settings)
        self.session_factory = create_session_factory(self.engine)
        self.protection = protection
        self._started = False
        self._idempotency_bodies: dict[tuple[str, str], dict[str, Any]] = {}
        self._metadata_records: list[dict[str, Any]] = []
        self._audit_cache: list[AuditEvent] = []
        self._csrf_secret = b"smhai-round1-synthetic-csrf-secret"

        self._seed_reference_roles = seed_reference_roles

    def _uow(self) -> Any:
        return self._uow_type(self.session_factory, self.protection)

    async def start(self) -> None:
        await self._ensure_synthetic_fixtures()
        self._started = True

    async def close(self) -> None:
        if self._started:
            await self.engine.dispose()
            self._started = False

    # ------------------------------------------------------------------
    # Synthetic identity and authorization projection
    # ------------------------------------------------------------------

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
            subjects: dict[str, Any] = {}
            for _, _, _, subject_ref in fixtures:
                if subject_ref is None:
                    continue
                subject = await uow.subjects.get_by_ref(subject_ref)
                if subject is None:
                    subject = await uow.subjects.create(
                        subject_ref=subject_ref,
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
        role_code = next(
            (
                candidate
                for candidate in ("student", "teacher", "reviewer", "parent", "admin")
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
        )

    async def create(self, user_id: str, ttl_seconds: int) -> SessionRecord:
        raw_token = secrets.token_urlsafe(32)
        csrf_token = self._csrf_token(raw_token)
        now = self._utc_now()
        async with self._uow() as uow:
            account = await self._account_for_user(uow, user_id)
            if account is None:
                raise error(ErrorCode.AUTH_SESSION_EXPIRED, detail="authentication is required")
            await uow.auth_sessions.create(
                account_id=account.id,
                raw_session_token=raw_token,
                raw_csrf_token=csrf_token,
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
        m = self._db_models
        async with self._uow() as uow:
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
                    or None,
                )
            db_record.status = self._status_upper(str(record.assessment.get("status", "created")))
            timestamps = record.assessment.get("timestamps", {})
            db_record.started_at = (
                _as_datetime(timestamps.get("started_at")) or db_record.started_at
            )
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
                    trace_id=None,
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

    async def get_assessment(self, assessment_id: str) -> AssessmentRecord | None:
        m = self._db_models
        async with self._uow() as uow:
            try:
                db_record = await uow.assessments.get_session(assessment_id)
            except self._db_not_found:
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
                responses=responses,
                cat_provider_version=str(provenance.get("cat_engine_version") or "") or None,
                cat_item_bank_version=str(
                    provenance.get("item_bank_version") or db_record.item_bank_version or ""
                )
                or None,
                cat_config_version=db_record.config_version,
                answered_count=len(responses),
                administered_count=len(responses),
            )

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
            generation = result.generation if isinstance(result.generation, dict) else {}
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
                        source_version="knowledge.v1",
                        source_hash=None,
                        locator=str(citation.locator),
                        rank_order=rank,
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

    async def fail_workflow(self, report_id: str, *, reason_code: str, trace_id: str) -> None:
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
            )

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
                "model_id": "MODEL_not_used",
                "model_version": "not_used",
                "runtime_version": "not_used",
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
