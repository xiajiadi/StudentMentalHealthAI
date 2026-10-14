"""Transactional research-only review and educational feedback persistence."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import uuid4

from smhai_backend.adapters.school_professional_reviews import (
    SchoolProfessionalReviewPersistenceAdapter,
    _public_id,
)
from smhai_backend.core.errors import BackendError, ErrorCode, error
from smhai_backend.core.request_context import get_request_context
from smhai_backend.domains.school_research.study_use import (
    ResearchStudyProfilePin,
    ResearchStudyUseError,
    ResearchStudyUsePolicy,
)

_CASE_NOTE_SCHEMA = "school_research_review_note.v1"
_FEEDBACK_CONTENT_SCHEMA = "school_research_feedback_content.v1"
_CASE_RESOURCE = "school_research_review_case"
_FEEDBACK_RESOURCE = "school_research_feedback"
_PUBLICATION_NOT_APPROVED = "not_approved_for_publication_or_operational_use"
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,126}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _not_found():
    return error(ErrorCode.RESOURCE_NOT_FOUND, detail="research feedback was not found")


def _workflow_conflict():
    return error(ErrorCode.WORKFLOW_CONFLICT, detail="research feedback state changed")


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _naive_utc(value: datetime) -> datetime:
    return _aware_utc(value).replace(tzinfo=None)


async def _repo_call(awaitable):
    """Translate expected persistence conflicts without exposing database details."""
    from database_layer.errors import (
        DatabaseUnavailable,
        EncryptionKeyUnavailable,
        ForeignKeyConflict,
        NotFound,
        OptimisticConcurrencyConflict,
        UniqueConflict,
    )
    from database_layer.school_research_review_feedback import ResearchReviewFeedbackError

    try:
        return await awaitable
    except (OptimisticConcurrencyConflict, UniqueConflict, ResearchReviewFeedbackError):
        raise _workflow_conflict() from None
    except (ForeignKeyConflict, NotFound):
        raise _not_found() from None
    except (DatabaseUnavailable, EncryptionKeyUnavailable):
        raise error(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            detail="research feedback storage is unavailable",
            retryable=True,
        ) from None


class SchoolResearchFeedbackPersistenceAdapter(SchoolProfessionalReviewPersistenceAdapter):
    """Reuse school role/assignment/idempotency primitives with research-only refs."""

    def __init__(
        self,
        persistence,
        *,
        study_use_policy: ResearchStudyUsePolicy | None = None,
    ):
        super().__init__(persistence)
        self.study_use_policy = study_use_policy

    def _now(self) -> tuple[datetime, datetime]:
        value = self._utc_now()
        aware = _aware_utc(value)
        return aware, aware.replace(tzinfo=None)

    def _policy_pin(self, *, profile, binding, task, at: datetime) -> ResearchStudyProfilePin:
        policy = self.study_use_policy
        if (
            type(policy) is not ResearchStudyUsePolicy
            or policy.source_rights_verified is not True
            or profile.school_id != binding.school_id
            or profile.profile_ref != binding.profile_ref
            or profile.profile_version_id != binding.profile_version_id
            or profile.version_number != binding.profile_version_number
            or profile.profile_sha256 != binding.profile_sha256
            or binding.task_id != task.id
            or binding.class_id != task.class_id
            or binding.status != "ACTIVE"
            or binding.revoked_at is not None
            or binding.research_only is not True
            or profile.rights_status != "VERIFIED"
            or profile.execution_status != "SIMULATION_ENABLED"
            or profile.rights_revoked_at is not None
            or profile.research_only is not True
            or profile.human_curated is not False
            or profile.psychological_interpretation_allowed is not False
            or profile.publication_status != _PUBLICATION_NOT_APPROVED
            or not isinstance(profile.manifest_sha256, str)
            or _SHA256.fullmatch(profile.manifest_sha256) is None
        ):
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="research study scope is unavailable")
        opens_at = task.opens_at
        due_at = task.due_at
        if (opens_at is None) != (due_at is None):
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="research task window is invalid")
        if opens_at is not None and due_at is not None:
            opens = _aware_utc(opens_at)
            due = _aware_utc(due_at)
            if opens > due or opens < policy.starts_at or due > policy.ends_at:
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="research task window is invalid")
        try:
            pin = policy.require_scope(
                school_id=profile.school_id,
                profile_ref=profile.profile_ref,
                profile_sha256=profile.profile_sha256,
                manifest_sha256=profile.manifest_sha256,
                at=at,
            )
        except ResearchStudyUseError:
            raise error(ErrorCode.FORBIDDEN, detail="research study use is unavailable") from None
        except BackendError:
            raise
        except Exception:
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="research study policy is unavailable",
            ) from None
        if (
            type(pin) is not ResearchStudyProfilePin
            or pin.profile_ref != profile.profile_ref
            or pin.profile_sha256 != profile.profile_sha256
            or pin.manifest_sha256 != profile.manifest_sha256
            or pin.published_crosswalk_sha256 != profile.published_parameter_crosswalk_sha256
        ):
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="research study pin changed")
        if binding.cohort_id is not None:
            study_ref = getattr(policy, "study_ref", None)
            if not isinstance(study_ref, str) or not study_ref:
                raise error(
                    ErrorCode.DEPENDENCY_UNAVAILABLE,
                    detail="research study pin is unavailable",
                )
            return pin
        return pin

    async def _require_cohort_study_scope(self, uow, actor, binding) -> None:
        if binding.cohort_id is None:
            return
        study_ref = getattr(self.study_use_policy, "study_ref", None)
        if not isinstance(study_ref, str) or not study_ref:
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="research study pin is unavailable",
            )
        cohort_study_ref = await uow.session.scalar(
            self._select(self._db_models.SchoolResearchCohort.study_ref).where(
                self._db_models.SchoolResearchCohort.id == binding.cohort_id,
                self._db_models.SchoolResearchCohort.school_id == actor.school_id,
            )
        )
        if cohort_study_ref != study_ref:
            raise error(ErrorCode.FORBIDDEN, detail="research study scope is unavailable")

    async def _require_task_study_scope(self, uow, actor, task, at: datetime):
        binding = await uow.research_cat.get_task_binding_metadata(
            school_id=actor.school_id, task_id=task.id
        )
        profile = await uow.research_cat.get_profile_metadata(
            school_id=actor.school_id,
            profile_ref=binding.profile_ref,
            version_number=binding.profile_version_number,
        )
        self._policy_pin(profile=profile, binding=binding, task=task, at=at)
        await self._require_cohort_study_scope(uow, actor, binding)
        return binding, profile

    async def _current_scope(
        self,
        uow,
        actor,
        task,
        *,
        session_ref: str,
        at: datetime,
        student_account_id: int | None = None,
        lock: bool = False,
    ):
        """Resolve exact completed session scope without loading its CAT snapshot."""
        from database_layer.school_research_review_feedback import ResearchSessionScope

        m = self._db_models
        metadata = await uow.research_cat.get_session_l1_metadata(
            school_id=actor.school_id, session_ref=session_ref
        )
        if (
            metadata.school_id != actor.school_id
            or metadata.task_id != task.id
            or metadata.status != "COMPLETED"
            or metadata.completed_at is None
            or metadata.items_answered < 1
        ):
            raise _not_found()
        if task.cat_binding_mode != "RESEARCH_PROFILE":
            raise _not_found()

        query = (
            self._select(
                m.SchoolResearchSession.id,
                m.SchoolResearchSession.school_id,
                m.SchoolResearchSession.task_id,
                m.SchoolResearchSession.class_id,
                m.SchoolResearchSession.task_enrollment_id,
                m.SchoolResearchSession.subject_id,
                m.SchoolResearchSession.task_binding_id,
                m.SchoolResearchSession.profile_version_id,
                m.SchoolResearchSession.profile_ref,
                m.SchoolResearchSession.profile_version_number,
                m.SchoolResearchSession.profile_sha256,
                m.SchoolResearchSession.response_origin,
                m.SchoolResearchSession.purpose,
                m.SchoolResearchSession.research_only,
                m.TaskEnrollment.class_student_id,
                m.Subject.retention_due_at,
            )
            .join(
                m.TaskEnrollment,
                (m.TaskEnrollment.id == m.SchoolResearchSession.task_enrollment_id)
                & (m.TaskEnrollment.task_id == m.SchoolResearchSession.task_id)
                & (m.TaskEnrollment.school_id == m.SchoolResearchSession.school_id)
                & (m.TaskEnrollment.class_id == m.SchoolResearchSession.class_id)
                & (m.TaskEnrollment.class_id == m.SchoolResearchSession.class_id)
                & (m.TaskEnrollment.subject_id == m.SchoolResearchSession.subject_id),
            )
            .join(
                m.SchoolClassStudent,
                (m.SchoolClassStudent.id == m.TaskEnrollment.class_student_id)
                & (m.SchoolClassStudent.school_id == m.TaskEnrollment.school_id)
                & (m.SchoolClassStudent.class_id == m.TaskEnrollment.class_id)
                & (m.SchoolClassStudent.subject_id == m.TaskEnrollment.subject_id),
            )
            .join(
                m.SchoolClass,
                (m.SchoolClass.id == m.SchoolResearchSession.class_id)
                & (m.SchoolClass.school_id == m.SchoolResearchSession.school_id),
            )
            .join(
                m.Subject,
                (m.Subject.id == m.SchoolResearchSession.subject_id)
                & (m.Subject.school_id == m.SchoolResearchSession.school_id),
            )
            .where(
                m.SchoolResearchSession.id == metadata.session_id,
                m.SchoolResearchSession.session_ref == session_ref,
                m.SchoolResearchSession.school_id == actor.school_id,
                m.SchoolResearchSession.task_id == task.id,
                m.SchoolResearchSession.status == "COMPLETED",
                m.SchoolResearchSession.completed_at.is_not(None),
                m.SchoolResearchSession.purpose == "RESEARCH_SIMULATION",
                m.SchoolResearchSession.research_only.is_(True),
                m.TaskEnrollment.status == "ACTIVE",
                m.TaskEnrollment.revoked_at.is_(None),
                m.SchoolClassStudent.status == "ACTIVE",
                m.SchoolClassStudent.revoked_at.is_(None),
                m.SchoolClassStudent.valid_from <= _naive_utc(at),
                (m.SchoolClassStudent.valid_until.is_(None))
                | (m.SchoolClassStudent.valid_until >= _naive_utc(at)),
                m.SchoolClass.status == "ACTIVE",
                m.Subject.status == self._db_enums.SubjectStatus.ACTIVE.value,
                m.Subject.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
            )
        )
        if lock:
            query = query.with_for_update()
        row = (await uow.session.execute(query.limit(2))).first()
        if row is None:
            raise _not_found()
        values = row._mapping
        if (
            values["school_id"] != metadata.school_id
            or values["task_id"] != metadata.task_id
            or values["class_id"] != metadata.class_id
            or values["task_enrollment_id"] != metadata.task_enrollment_id
            or values["subject_id"] != metadata.subject_id
            or values["task_binding_id"] != metadata.task_binding_id
            or values["profile_version_id"] != metadata.profile_version_id
            or values["profile_ref"] != metadata.profile_ref
            or values["profile_version_number"] != metadata.profile_version_number
            or values["profile_sha256"] != metadata.profile_sha256
            or values["response_origin"] != metadata.response_origin
        ):
            raise _not_found()

        grants = await uow.session.scalars(
            self._select(m.SubjectAccessGrant.id)
            .join(m.Account, m.Account.id == m.SubjectAccessGrant.principal_account_id)
            .join(
                m.AccountSchoolMembership,
                (m.AccountSchoolMembership.account_id == m.Account.id)
                & (m.AccountSchoolMembership.school_id == m.SubjectAccessGrant.school_id),
            )
            .join(
                m.MembershipRole,
                (m.MembershipRole.membership_id == m.AccountSchoolMembership.id)
                & (m.MembershipRole.school_id == m.AccountSchoolMembership.school_id),
            )
            .where(
                m.SubjectAccessGrant.school_id == actor.school_id,
                m.SubjectAccessGrant.subject_id == metadata.subject_id,
                m.SubjectAccessGrant.relationship_type == "SELF",
                m.SubjectAccessGrant.status == "ACTIVE",
                m.SubjectAccessGrant.revoked_at.is_(None),
                m.SubjectAccessGrant.valid_from <= _naive_utc(at),
                (m.SubjectAccessGrant.valid_until.is_(None))
                | (m.SubjectAccessGrant.valid_until >= _naive_utc(at)),
                m.Account.status == self._db_enums.AccountStatus.ACTIVE.value,
                m.AccountSchoolMembership.status == "ACTIVE",
                m.AccountSchoolMembership.revoked_at.is_(None),
                m.AccountSchoolMembership.valid_from <= _naive_utc(at),
                (m.AccountSchoolMembership.valid_until.is_(None))
                | (m.AccountSchoolMembership.valid_until >= _naive_utc(at)),
                m.MembershipRole.role_code == "student",
                m.MembershipRole.status == "ACTIVE",
                m.MembershipRole.revoked_at.is_(None),
                m.MembershipRole.valid_from <= _naive_utc(at),
                (m.MembershipRole.valid_until.is_(None))
                | (m.MembershipRole.valid_until >= _naive_utc(at)),
                *(
                    (m.SubjectAccessGrant.principal_account_id == student_account_id,)
                    if student_account_id is not None
                    else ()
                ),
            )
            .distinct()
        )
        grant_ids = grants.all()
        if len(grant_ids) != 1:
            raise _not_found()

        binding = await uow.research_cat.get_task_binding_metadata(
            school_id=actor.school_id, task_id=task.id
        )
        profile = await uow.research_cat.get_profile_metadata(
            school_id=actor.school_id,
            profile_ref=metadata.profile_ref,
            version_number=metadata.profile_version_number,
        )
        pin = self._policy_pin(profile=profile, binding=binding, task=task, at=at)
        await self._require_cohort_study_scope(uow, actor, binding)
        scope = ResearchSessionScope(
            research_session_id=metadata.session_id,
            school_id=metadata.school_id,
            task_id=metadata.task_id,
            class_id=metadata.class_id,
            task_enrollment_id=metadata.task_enrollment_id,
            subject_id=metadata.subject_id,
            task_binding_id=metadata.task_binding_id,
            profile_version_id=metadata.profile_version_id,
            profile_ref=metadata.profile_ref,
            profile_version_number=metadata.profile_version_number,
            profile_sha256=metadata.profile_sha256,
            response_origin=metadata.response_origin,
        )
        return scope, metadata, values["retention_due_at"], profile, pin

    def _review_note(self, dto) -> str | None:
        if dto.case_note_ciphertext is None:
            return None
        if (
            not dto.case_note_cipher_format_version
            or not dto.case_note_key_version
            or dto.case_note_payload_schema_version != _CASE_NOTE_SCHEMA
        ):
            raise error(ErrorCode.DEPENDENCY_INVALID_RESPONSE, detail="review note is unavailable")
        from database_layer.crypto import EncryptedPayload

        try:
            value = self.protection.decrypt_json(
                EncryptedPayload(
                    ciphertext=dto.case_note_ciphertext,
                    key_version=dto.case_note_key_version,
                    cipher_format_version=dto.case_note_cipher_format_version,
                    payload_schema_version=dto.case_note_payload_schema_version,
                )
            )
        except Exception:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="review note is unavailable",
            ) from None
        if (
            not isinstance(value, dict)
            or set(value) != {"note", "review_ref"}
            or value["review_ref"] != dto.review_ref
            or not isinstance(value["note"], str)
            or len(value["note"]) > 4000
        ):
            raise error(ErrorCode.DEPENDENCY_INVALID_RESPONSE, detail="review note is unavailable")
        return value["note"]

    def _feedback_content(self, dto) -> tuple[str, str]:
        if (
            not dto.cipher_format_version
            or not dto.key_version
            or dto.payload_schema_version != _FEEDBACK_CONTENT_SCHEMA
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="feedback content is unavailable",
            )
        from database_layer.crypto import EncryptedPayload

        try:
            value = self.protection.decrypt_json(
                EncryptedPayload(
                    ciphertext=dto.payload_ciphertext,
                    key_version=dto.key_version,
                    cipher_format_version=dto.cipher_format_version,
                    payload_schema_version=dto.payload_schema_version,
                )
            )
        except Exception:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="feedback content is unavailable",
            ) from None
        if (
            not isinstance(value, dict)
            or set(value) != {"feedback_ref", "content_revision", "title", "body"}
            or value["feedback_ref"] != dto.feedback_ref
            or value["content_revision"] != dto.content_revision
            or not isinstance(value["title"], str)
            or not 1 <= len(value["title"]) <= 120
            or not isinstance(value["body"], str)
            or not 1 <= len(value["body"]) <= 4000
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE, detail="feedback content is unavailable"
            )
        return value["title"], value["body"]

    def _case_projection(self, case, *, task_ref: str, session_ref: str):
        if (
            case.purpose != "RESEARCH_SIMULATION"
            or case.research_only is not True
            or case.publication_status != _PUBLICATION_NOT_APPROVED
        ):
            raise error(ErrorCode.DEPENDENCY_INVALID_RESPONSE, detail="review case is unavailable")
        return {
            "case_ref": case.review_ref,
            "task_ref": task_ref,
            "session_ref": session_ref,
            "status": case.status,
            "version": case.version,
            "created_at": case.created_at,
            "updated_at": case.updated_at,
            "review_note": self._review_note(case),
        }

    def _feedback_projection(self, record, *, case_ref: str, session_ref: str, student: bool):
        if (
            record.feedback_kind != "GENERAL_EDUCATIONAL_SUPPORT"
            or record.purpose != "RESEARCH_SIMULATION"
            or record.research_only is not True
            or record.psychological_interpretation_allowed is not False
            or record.publication_status != _PUBLICATION_NOT_APPROVED
            or (student and record.status != "PUBLISHED")
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research feedback is unavailable",
            )
        title, body = self._feedback_content(record)
        common = {
            "feedback_ref": record.feedback_ref,
            "session_ref": session_ref,
            "feedback_kind": record.feedback_kind,
            "purpose": record.purpose,
            "research_only": record.research_only,
            "psychological_interpretation_allowed": record.psychological_interpretation_allowed,
            "publication_status": record.publication_status,
            "content_revision": record.content_revision,
            "state_version": record.state_version,
            "status": record.status,
            "title": title,
            "body": body,
            "created_at": record.created_at,
            "published_at": record.published_at,
        }
        if student:
            return common
        return {
            **common,
            "case_ref": case_ref,
            "case_version": record.case_version,
            "revoked_at": record.revoked_at,
        }

    async def school_research_feedback_list_tasks(self, actor):
        now, db_now = self._now()
        m = self._db_models
        async with self._uow() as uow:
            _, role_id = await self._require_actor(uow, actor, "psychological_specialist", db_now)
            rows = (
                await uow.session.execute(
                    self._select(
                        m.MeasurementTask.task_ref,
                        m.SchoolClass.class_ref,
                        m.SchoolClass.display_name,
                        m.MeasurementTask.published_at,
                    )
                    .join(
                        m.SchoolTaskSpecialistAssignment,
                        (m.SchoolTaskSpecialistAssignment.task_id == m.MeasurementTask.id)
                        & (
                            m.SchoolTaskSpecialistAssignment.school_id
                            == m.MeasurementTask.school_id
                        )
                        & (m.SchoolTaskSpecialistAssignment.class_id == m.MeasurementTask.class_id),
                    )
                    .join(
                        m.SchoolClass,
                        (m.SchoolClass.id == m.MeasurementTask.class_id)
                        & (m.SchoolClass.school_id == m.MeasurementTask.school_id),
                    )
                    .where(
                        m.MeasurementTask.school_id == actor.school_id,
                        m.MeasurementTask.status.in_(("PUBLISHED", "CLOSED")),
                        m.MeasurementTask.cat_binding_mode == "RESEARCH_PROFILE",
                        m.SchoolTaskSpecialistAssignment.specialist_membership_role_id == role_id,
                        m.SchoolTaskSpecialistAssignment.status == "ACTIVE",
                        m.SchoolTaskSpecialistAssignment.revoked_at.is_(None),
                        m.SchoolClass.status == "ACTIVE",
                    )
                    .order_by(m.MeasurementTask.published_at, m.MeasurementTask.task_ref)
                )
            ).all()
            eligible = []
            for task_ref, class_ref, class_name, published_at in rows:
                task = await self._task(uow, actor, task_ref, lock=False)
                await self._require_task_study_scope(uow, actor, task, now)
                eligible.append(
                    {
                        "task_ref": task_ref,
                        "class_ref": class_ref,
                        "class_display_name": class_name,
                        "published_at": published_at,
                    }
                )
            return eligible

    async def school_research_feedback_list_eligible_sessions(
        self, actor, task_ref, *, offset, limit
    ):
        from sqlalchemy import func

        now, db_now = self._now()
        m = self._db_models
        async with self._uow() as uow:
            _, role_id = await self._require_actor(uow, actor, "psychological_specialist", db_now)
            task = await self._task(uow, actor, task_ref, lock=False)
            await self._active_assignment(uow, actor, task, at=db_now, lock=False)
            base = (
                self._select(
                    m.SchoolResearchSession.session_ref,
                    m.SchoolResearchSession.items_answered,
                    m.SchoolResearchSession.completed_at,
                )
                .join(
                    m.TaskEnrollment,
                    (m.TaskEnrollment.id == m.SchoolResearchSession.task_enrollment_id)
                    & (m.TaskEnrollment.task_id == m.SchoolResearchSession.task_id)
                    & (m.TaskEnrollment.school_id == m.SchoolResearchSession.school_id)
                    & (m.TaskEnrollment.class_id == m.SchoolResearchSession.class_id)
                    & (m.TaskEnrollment.subject_id == m.SchoolResearchSession.subject_id),
                )
                .join(
                    m.SchoolClassStudent,
                    (m.SchoolClassStudent.id == m.TaskEnrollment.class_student_id)
                    & (m.SchoolClassStudent.school_id == m.TaskEnrollment.school_id)
                    & (m.SchoolClassStudent.class_id == m.TaskEnrollment.class_id)
                    & (m.SchoolClassStudent.subject_id == m.TaskEnrollment.subject_id),
                )
                .join(
                    m.SchoolClass,
                    (m.SchoolClass.id == m.SchoolResearchSession.class_id)
                    & (m.SchoolClass.school_id == m.SchoolResearchSession.school_id),
                )
                .join(
                    m.Subject,
                    (m.Subject.id == m.SchoolResearchSession.subject_id)
                    & (m.Subject.school_id == m.SchoolResearchSession.school_id),
                )
                .join(
                    m.SubjectAccessGrant,
                    (m.SubjectAccessGrant.subject_id == m.Subject.id)
                    & (m.SubjectAccessGrant.school_id == m.Subject.school_id),
                )
                .join(
                    m.Account,
                    m.Account.id == m.SubjectAccessGrant.principal_account_id,
                )
                .join(
                    m.AccountSchoolMembership,
                    (m.AccountSchoolMembership.account_id == m.Account.id)
                    & (m.AccountSchoolMembership.school_id == m.SubjectAccessGrant.school_id),
                )
                .join(
                    m.MembershipRole,
                    (m.MembershipRole.membership_id == m.AccountSchoolMembership.id)
                    & (m.MembershipRole.school_id == m.AccountSchoolMembership.school_id),
                )
                .where(
                    m.SchoolResearchSession.school_id == actor.school_id,
                    m.SchoolResearchSession.task_id == task.id,
                    m.SchoolResearchSession.class_id == task.class_id,
                    m.SchoolResearchSession.status == "COMPLETED",
                    m.SchoolResearchSession.purpose == "RESEARCH_SIMULATION",
                    m.SchoolResearchSession.research_only.is_(True),
                    m.TaskEnrollment.status == "ACTIVE",
                    m.TaskEnrollment.revoked_at.is_(None),
                    m.SchoolClassStudent.status == "ACTIVE",
                    m.SchoolClassStudent.revoked_at.is_(None),
                    m.SchoolClassStudent.valid_from <= db_now,
                    (m.SchoolClassStudent.valid_until.is_(None))
                    | (m.SchoolClassStudent.valid_until >= db_now),
                    m.SchoolClass.status == "ACTIVE",
                    m.Subject.status == self._db_enums.SubjectStatus.ACTIVE.value,
                    m.Subject.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                    m.SubjectAccessGrant.relationship_type == "SELF",
                    m.SubjectAccessGrant.status == "ACTIVE",
                    m.SubjectAccessGrant.revoked_at.is_(None),
                    m.SubjectAccessGrant.valid_from <= db_now,
                    (m.SubjectAccessGrant.valid_until.is_(None))
                    | (m.SubjectAccessGrant.valid_until >= db_now),
                    m.Account.status == self._db_enums.AccountStatus.ACTIVE.value,
                    m.AccountSchoolMembership.status == "ACTIVE",
                    m.AccountSchoolMembership.revoked_at.is_(None),
                    m.AccountSchoolMembership.valid_from <= db_now,
                    (m.AccountSchoolMembership.valid_until.is_(None))
                    | (m.AccountSchoolMembership.valid_until >= db_now),
                    m.MembershipRole.role_code == "student",
                    m.MembershipRole.status == "ACTIVE",
                    m.MembershipRole.revoked_at.is_(None),
                    m.MembershipRole.valid_from <= db_now,
                    (m.MembershipRole.valid_until.is_(None))
                    | (m.MembershipRole.valid_until >= db_now),
                )
                .distinct()
            )
            total = int(
                await uow.session.scalar(
                    self._select(func.count()).select_from(base.order_by(None).subquery())
                )
                or 0
            )
            rows = (
                await uow.session.execute(
                    base.order_by(
                        m.SchoolResearchSession.completed_at,
                        m.SchoolResearchSession.session_ref,
                    )
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
            items = []
            for session_ref, items_answered, completed_at in rows:
                scope, metadata, _retention, _profile, _pin = await self._current_scope(
                    uow, actor, task, session_ref=session_ref, at=now
                )
                existing = await uow.research_reviews.get_case(
                    school_id=actor.school_id,
                    research_session_id=scope.research_session_id,
                )
                items.append(
                    {
                        "session_ref": session_ref,
                        "task_ref": task_ref,
                        "status": "COMPLETED",
                        "items_answered": items_answered,
                        "completed_at": completed_at,
                        "case_ref": existing.review_ref if existing else None,
                    }
                )
            return {"items": items, "total": total}

    async def school_research_feedback_list_cases(self, actor, task_ref, *, status, offset, limit):
        from sqlalchemy import func

        now, db_now = self._now()
        m = self._db_models
        async with self._uow() as uow:
            _, role_id = await self._require_actor(uow, actor, "psychological_specialist", db_now)
            task = await self._task(uow, actor, task_ref, lock=False)
            await self._active_assignment(uow, actor, task, at=db_now, lock=False)
            await self._require_task_study_scope(uow, actor, task, now)
            case_model = m.SchoolResearchReviewCase
            session_model = m.SchoolResearchSession
            base = (
                self._select(
                    case_model.id,
                    case_model.review_ref,
                    session_model.session_ref,
                    case_model.created_at,
                )
                .join(
                    session_model,
                    (session_model.id == case_model.research_session_id)
                    & (session_model.school_id == case_model.school_id)
                    & (session_model.task_id == case_model.task_id)
                    & (session_model.class_id == case_model.class_id)
                    & (session_model.task_enrollment_id == case_model.task_enrollment_id)
                    & (session_model.subject_id == case_model.subject_id)
                    & (session_model.task_binding_id == case_model.task_binding_id)
                    & (session_model.profile_version_id == case_model.profile_version_id)
                    & (session_model.profile_ref == case_model.profile_ref)
                    & (
                        session_model.profile_version_number
                        == case_model.profile_version_number
                    )
                    & (session_model.profile_sha256 == case_model.profile_sha256)
                    & (session_model.response_origin == case_model.response_origin),
                )
                .join(
                    m.TaskEnrollment,
                    (m.TaskEnrollment.id == case_model.task_enrollment_id)
                    & (m.TaskEnrollment.task_id == case_model.task_id)
                    & (m.TaskEnrollment.school_id == case_model.school_id)
                    & (m.TaskEnrollment.class_id == case_model.class_id)
                    & (m.TaskEnrollment.subject_id == case_model.subject_id),
                )
                .join(
                    m.SchoolClassStudent,
                    (m.SchoolClassStudent.id == m.TaskEnrollment.class_student_id)
                    & (m.SchoolClassStudent.school_id == m.TaskEnrollment.school_id)
                    & (m.SchoolClassStudent.class_id == m.TaskEnrollment.class_id)
                    & (m.SchoolClassStudent.subject_id == m.TaskEnrollment.subject_id),
                )
                .join(
                    m.SchoolClass,
                    (m.SchoolClass.id == case_model.class_id)
                    & (m.SchoolClass.school_id == case_model.school_id),
                )
                .join(
                    m.Subject,
                    (m.Subject.id == case_model.subject_id)
                    & (m.Subject.school_id == case_model.school_id),
                )
                .join(
                    m.SubjectAccessGrant,
                    (m.SubjectAccessGrant.subject_id == m.Subject.id)
                    & (m.SubjectAccessGrant.school_id == m.Subject.school_id),
                )
                .join(
                    m.Account,
                    m.Account.id == m.SubjectAccessGrant.principal_account_id,
                )
                .join(
                    m.AccountSchoolMembership,
                    (m.AccountSchoolMembership.account_id == m.Account.id)
                    & (m.AccountSchoolMembership.school_id == m.SubjectAccessGrant.school_id),
                )
                .join(
                    m.MembershipRole,
                    (m.MembershipRole.membership_id == m.AccountSchoolMembership.id)
                    & (m.MembershipRole.school_id == m.AccountSchoolMembership.school_id),
                )
                .where(
                    case_model.school_id == actor.school_id,
                    case_model.task_id == task.id,
                    case_model.specialist_membership_role_id == role_id,
                    session_model.status == "COMPLETED",
                    session_model.purpose == "RESEARCH_SIMULATION",
                    session_model.research_only.is_(True),
                    m.TaskEnrollment.status == "ACTIVE",
                    m.TaskEnrollment.revoked_at.is_(None),
                    m.SchoolClassStudent.status == "ACTIVE",
                    m.SchoolClassStudent.revoked_at.is_(None),
                    m.SchoolClassStudent.valid_from <= db_now,
                    (m.SchoolClassStudent.valid_until.is_(None))
                    | (m.SchoolClassStudent.valid_until >= db_now),
                    m.SchoolClass.status == "ACTIVE",
                    m.Subject.status == self._db_enums.SubjectStatus.ACTIVE.value,
                    m.Subject.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                    m.SubjectAccessGrant.relationship_type == "SELF",
                    m.SubjectAccessGrant.status == "ACTIVE",
                    m.SubjectAccessGrant.revoked_at.is_(None),
                    m.SubjectAccessGrant.valid_from <= db_now,
                    (m.SubjectAccessGrant.valid_until.is_(None))
                    | (m.SubjectAccessGrant.valid_until >= db_now),
                    m.Account.status == self._db_enums.AccountStatus.ACTIVE.value,
                    m.AccountSchoolMembership.status == "ACTIVE",
                    m.AccountSchoolMembership.revoked_at.is_(None),
                    m.AccountSchoolMembership.valid_from <= db_now,
                    (m.AccountSchoolMembership.valid_until.is_(None))
                    | (m.AccountSchoolMembership.valid_until >= db_now),
                    m.MembershipRole.role_code == "student",
                    m.MembershipRole.status == "ACTIVE",
                    m.MembershipRole.revoked_at.is_(None),
                    m.MembershipRole.valid_from <= db_now,
                    (m.MembershipRole.valid_until.is_(None))
                    | (m.MembershipRole.valid_until >= db_now),
                )
            )
            if status is not None:
                base = base.where(case_model.status == status)
            base = base.distinct()
            total = int(
                await uow.session.scalar(
                    self._select(func.count()).select_from(base.order_by(None).subquery())
                )
                or 0
            )
            visible_rows = (
                await uow.session.execute(
                    base.order_by(case_model.created_at, case_model.id)
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
            items = []
            for _case_id, case_ref, session_ref, _created_at in visible_rows:
                scope, _metadata, _retention, _profile, _pin = await self._current_scope(
                    uow, actor, task, session_ref=session_ref, at=now
                )
                dto = await uow.research_reviews.get_case(
                    school_id=actor.school_id,
                    research_session_id=scope.research_session_id,
                )
                if dto is None or dto.review_ref != case_ref or dto.scope != scope:
                    raise _not_found()
                items.append(self._case_projection(dto, task_ref=task_ref, session_ref=session_ref))
            return {"items": items, "total": total}

    async def school_research_feedback_get_case(self, actor, task_ref, case_ref):
        now, db_now = self._now()
        m = self._db_models
        async with self._uow() as uow:
            _, role_id = await self._require_actor(uow, actor, "psychological_specialist", db_now)
            task = await self._task(uow, actor, task_ref, lock=False)
            await self._active_assignment(uow, actor, task, at=db_now, lock=False)
            ref = _public_id(case_ref, "SRV")
            row = await uow.session.scalar(
                self._select(m.SchoolResearchReviewCase).where(
                    m.SchoolResearchReviewCase.review_ref == f"SRV_{ref}",
                    m.SchoolResearchReviewCase.school_id == actor.school_id,
                    m.SchoolResearchReviewCase.task_id == task.id,
                    m.SchoolResearchReviewCase.specialist_membership_role_id == role_id,
                )
            )
            if row is None:
                raise _not_found()
            session_ref = await uow.session.scalar(
                self._select(m.SchoolResearchSession.session_ref).where(
                    m.SchoolResearchSession.id == row.research_session_id,
                    m.SchoolResearchSession.school_id == actor.school_id,
                )
            )
            scope, _metadata, _retention, _profile, _pin = await self._current_scope(
                uow, actor, task, session_ref=session_ref, at=now
            )
            dto = await uow.research_reviews.get_case(
                school_id=actor.school_id,
                research_session_id=scope.research_session_id,
            )
            if dto is None or dto.review_ref != row.review_ref:
                raise _not_found()
            return self._case_projection(dto, task_ref=task_ref, session_ref=session_ref)

    async def school_research_feedback_create_case(
        self, actor, task_ref, session_ref, *, idempotency, trace_id
    ):
        now, db_now = self._now()
        async with self._uow() as uow:
            actor_account_id, role_id = await self._require_actor(
                uow, actor, "psychological_specialist", db_now
            )
            task = await self._task(uow, actor, task_ref, lock=True)
            await self._active_assignment(uow, actor, task, at=db_now, lock=True)
            scope, metadata, retention, _profile, _pin = await self._current_scope(
                uow, actor, task, session_ref=session_ref, at=now, lock=True
            )
            claim = await self._school_idempotency_begin(uow, idempotency)
            if claim.replayed:
                ref = await self._receipt_resource(claim, _CASE_RESOURCE)
                existing = await uow.research_reviews.get_case(
                    school_id=actor.school_id,
                    research_session_id=scope.research_session_id,
                )
                if (
                    existing is None
                    or existing.review_ref != ref
                    or existing.specialist_membership_role_id != role_id
                ):
                    raise _workflow_conflict()
                return self._case_projection(existing, task_ref=task_ref, session_ref=session_ref)
            if await uow.research_reviews.get_case(
                school_id=actor.school_id,
                research_session_id=scope.research_session_id,
            ):
                raise _workflow_conflict()
            row = await _repo_call(
                uow.research_reviews.create_case(
                    scope=scope,
                    specialist_membership_role_id=role_id,
                    actor_membership_role_id=role_id,
                    trace_id=trace_id,
                    retention_due_at=retention,
                    now=now,
                )
            )
            await self._audit_research(
                uow,
                actor_account_id=actor_account_id,
                action="school_research_review.case_created",
                resource_type=_CASE_RESOURCE,
                resource_ref=row.review_ref,
                trace_id=trace_id,
                state=row.status,
            )
            await self._school_idempotency_complete(
                uow, claim, resource_type=_CASE_RESOURCE, result_ref=row.review_ref
            )
            return self._case_projection(row, task_ref=task_ref, session_ref=session_ref)

    async def school_research_feedback_transition_case(
        self,
        actor,
        task_ref,
        case_ref,
        *,
        expected_version,
        status,
        note,
        idempotency,
        trace_id,
    ):
        now, db_now = self._now()
        m = self._db_models
        async with self._uow() as uow:
            actor_account_id, role_id = await self._require_actor(
                uow, actor, "psychological_specialist", db_now
            )
            task = await self._task(uow, actor, task_ref, lock=True)
            await self._active_assignment(uow, actor, task, at=db_now, lock=True)
            row = await self._review_model(uow, actor, task, role_id, case_ref, lock=True)
            session_ref = await uow.session.scalar(
                self._select(m.SchoolResearchSession.session_ref).where(
                    m.SchoolResearchSession.id == row.research_session_id,
                    m.SchoolResearchSession.school_id == actor.school_id,
                )
            )
            scope, _metadata, _retention, _profile, _pin = await self._current_scope(
                uow, actor, task, session_ref=session_ref, at=now, lock=True
            )
            claim = await self._school_idempotency_begin(uow, idempotency)
            if claim.replayed:
                if await self._receipt_resource(claim, _CASE_RESOURCE) != row.review_ref:
                    raise _workflow_conflict()
                current = await uow.research_reviews.get_case(
                    school_id=actor.school_id,
                    research_session_id=scope.research_session_id,
                )
                if current is None:
                    raise _not_found()
                return self._case_projection(current, task_ref=task_ref, session_ref=session_ref)
            protected = self.protection.encrypt_json(
                {"note": note, "review_ref": row.review_ref},
                payload_schema_version=_CASE_NOTE_SCHEMA,
            )
            updated = await _repo_call(
                uow.research_reviews.transition_case(
                    school_id=actor.school_id,
                    research_session_id=scope.research_session_id,
                    expected_version=expected_version,
                    to_status=status,
                    actor_membership_role_id=role_id,
                    case_note_ciphertext=protected.ciphertext,
                    case_note_cipher_format_version=protected.cipher_format_version,
                    case_note_key_version=protected.key_version,
                    case_note_payload_schema_version=protected.payload_schema_version,
                    trace_id=trace_id,
                    now=now,
                )
            )
            await self._audit_research(
                uow,
                actor_account_id=actor_account_id,
                action="school_research_review.case_transition",
                resource_type=_CASE_RESOURCE,
                resource_ref=updated.review_ref,
                trace_id=trace_id,
                state=updated.status,
            )
            await self._school_idempotency_complete(
                uow, claim, resource_type=_CASE_RESOURCE, result_ref=updated.review_ref
            )
            return self._case_projection(updated, task_ref=task_ref, session_ref=session_ref)

    async def school_research_feedback_create_draft(
        self,
        actor,
        case_ref,
        *,
        expected_case_version,
        title,
        body,
        idempotency,
        trace_id,
    ):
        from sqlalchemy import func

        now, db_now = self._now()
        m = self._db_models
        async with self._uow() as uow:
            actor_account_id, role_id = await self._require_actor(
                uow, actor, "psychological_specialist", db_now
            )
            row = await self._review_model_by_ref(uow, actor, role_id, case_ref, lock=False)
            task = await self._task_by_id(uow, actor, row.task_id, lock=True)
            await self._active_assignment(uow, actor, task, at=db_now, lock=True)
            locked_row = await self._review_model_by_ref(
                uow, actor, role_id, case_ref, lock=True
            )
            if locked_row.id != row.id:
                raise _not_found()
            row = locked_row
            session_ref = await uow.session.scalar(
                self._select(m.SchoolResearchSession.session_ref).where(
                    m.SchoolResearchSession.id == row.research_session_id,
                    m.SchoolResearchSession.school_id == actor.school_id,
                )
            )
            scope, _metadata, retention, _profile, _pin = await self._current_scope(
                uow, actor, task, session_ref=session_ref, at=now, lock=True
            )
            claim = await self._school_idempotency_begin(uow, idempotency)
            if claim.replayed:
                ref = await self._receipt_resource(claim, _FEEDBACK_RESOURCE)
                existing = await self._feedback_model_by_ref(uow, actor, ref, lock=False)
                if (
                    existing is None
                    or existing.review_case_id != row.id
                    or existing.created_by_membership_role_id != role_id
                ):
                    raise _workflow_conflict()
                dto = await uow.research_feedback.get_feedback(
                    school_id=actor.school_id, feedback_id=existing.id
                )
                if dto is None:
                    raise _not_found()
                return self._feedback_projection(
                    dto, case_ref=row.review_ref, session_ref=session_ref, student=False
                )
            if row.status != "APPROVED" or row.version != expected_case_version:
                raise _workflow_conflict()
            latest_revision = int(
                await uow.session.scalar(
                    self._select(func.max(m.SchoolResearchFeedbackRecord.content_revision)).where(
                        m.SchoolResearchFeedbackRecord.review_case_id == row.id
                    )
                )
                or 0
            )
            ref = f"RFEED_{uuid4().hex}"
            next_revision = latest_revision + 1
            protected = self.protection.encrypt_json(
                {
                    "feedback_ref": ref,
                    "content_revision": next_revision,
                    "title": title,
                    "body": body,
                },
                payload_schema_version=_FEEDBACK_CONTENT_SCHEMA,
            )
            dto = await _repo_call(
                uow.research_feedback.create_draft(
                    school_id=actor.school_id,
                    research_session_id=scope.research_session_id,
                    expected_case_version=expected_case_version,
                    feedback_ref=ref,
                    content_revision=next_revision,
                    payload_ciphertext=protected.ciphertext,
                    cipher_format_version=protected.cipher_format_version,
                    key_version=protected.key_version,
                    payload_schema_version=protected.payload_schema_version,
                    actor_membership_role_id=role_id,
                    trace_id=trace_id,
                    retention_due_at=retention,
                    now=now,
                )
            )
            await self._audit_research(
                uow,
                actor_account_id=actor_account_id,
                action="school_research_feedback.draft_created",
                resource_type=_FEEDBACK_RESOURCE,
                resource_ref=dto.feedback_ref,
                trace_id=trace_id,
                state=dto.status,
            )
            await self._school_idempotency_complete(
                uow, claim, resource_type=_FEEDBACK_RESOURCE, result_ref=dto.feedback_ref
            )
            return self._feedback_projection(
                dto, case_ref=row.review_ref, session_ref=session_ref, student=False
            )

    async def school_research_feedback_list_for_case(self, actor, case_ref, *, offset, limit):
        from sqlalchemy import func

        now, db_now = self._now()
        m = self._db_models
        async with self._uow() as uow:
            _, role_id = await self._require_actor(uow, actor, "psychological_specialist", db_now)
            row = await self._review_model_by_ref(uow, actor, role_id, case_ref, lock=False)
            task = await self._task_by_id(uow, actor, row.task_id, lock=False)
            await self._active_assignment(uow, actor, task, at=db_now, lock=False)
            session_ref = await uow.session.scalar(
                self._select(m.SchoolResearchSession.session_ref).where(
                    m.SchoolResearchSession.id == row.research_session_id,
                    m.SchoolResearchSession.school_id == actor.school_id,
                )
            )
            scope, _metadata, _retention, _profile, _pin = await self._current_scope(
                uow, actor, task, session_ref=session_ref, at=now
            )
            count = int(
                await uow.session.scalar(
                    self._select(func.count()).where(
                        m.SchoolResearchFeedbackRecord.school_id == actor.school_id,
                        m.SchoolResearchFeedbackRecord.review_case_id == row.id,
                    )
                )
                or 0
            )
            values = await uow.research_feedback.list_feedback(
                school_id=actor.school_id,
                research_session_id=scope.research_session_id,
                limit=limit,
                offset=offset,
            )
            items = []
            for record in values:
                if record.review_case_id != row.id:
                    raise error(
                        ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                        detail="research feedback data is unavailable",
                    )
                items.append(
                    self._feedback_projection(
                        record, case_ref=row.review_ref, session_ref=session_ref, student=False
                    )
                )
            return {"items": items, "total": count}

    async def school_research_feedback_publish(
        self,
        actor,
        feedback_ref,
        *,
        expected_state_version,
        expected_case_version,
        idempotency,
        trace_id,
    ):
        return await self._transition_feedback(
            actor,
            feedback_ref,
            expected_state_version=expected_state_version,
            expected_case_version=expected_case_version,
            idempotency=idempotency,
            trace_id=trace_id,
            publish=True,
        )

    async def school_research_feedback_revoke(
        self,
        actor,
        feedback_ref,
        *,
        expected_state_version,
        idempotency,
        trace_id,
    ):
        return await self._transition_feedback(
            actor,
            feedback_ref,
            expected_state_version=expected_state_version,
            expected_case_version=None,
            idempotency=idempotency,
            trace_id=trace_id,
            publish=False,
        )

    async def _transition_feedback(
        self,
        actor,
        feedback_ref,
        *,
        expected_state_version,
        expected_case_version,
        idempotency,
        trace_id,
        publish,
    ):
        now, db_now = self._now()
        m = self._db_models
        async with self._uow() as uow:
            actor_account_id, role_id = await self._require_actor(
                uow, actor, "psychological_specialist", db_now
            )
            record = await self._feedback_model_by_ref(uow, actor, feedback_ref, lock=False)
            if record is None or record.created_by_membership_role_id != role_id:
                raise _not_found()
            case = await uow.session.scalar(
                self._select(m.SchoolResearchReviewCase).where(
                    m.SchoolResearchReviewCase.id == record.review_case_id,
                    m.SchoolResearchReviewCase.school_id == actor.school_id,
                )
            )
            if case is None or case.specialist_membership_role_id != role_id:
                raise _not_found()
            task = await self._task_by_id(uow, actor, case.task_id, lock=True)
            await self._active_assignment(uow, actor, task, at=db_now, lock=True)
            locked_record = await self._feedback_model_by_ref(
                uow, actor, feedback_ref, lock=True
            )
            if (
                locked_record.id != record.id
                or locked_record.review_case_id != case.id
                or locked_record.created_by_membership_role_id != role_id
            ):
                raise _not_found()
            record = locked_record
            session_ref = await uow.session.scalar(
                self._select(m.SchoolResearchSession.session_ref).where(
                    m.SchoolResearchSession.id == record.research_session_id,
                    m.SchoolResearchSession.school_id == actor.school_id,
                )
            )
            scope, _metadata, _retention, _profile, _pin = await self._current_scope(
                uow, actor, task, session_ref=session_ref, at=now, lock=True
            )
            claim = await self._school_idempotency_begin(uow, idempotency)
            target_resource = "PUBLISHED" if publish else "REVOKED"
            if claim.replayed:
                ref = await self._receipt_resource(claim, _FEEDBACK_RESOURCE)
                if ref != record.feedback_ref:
                    raise _workflow_conflict()
                current = await uow.research_feedback.get_feedback(
                    school_id=actor.school_id, feedback_id=record.id
                )
                if current is None or current.status != target_resource:
                    raise _workflow_conflict()
                return self._feedback_projection(
                    current, case_ref=case.review_ref, session_ref=session_ref, student=False
                )
            if publish:
                dto = await _repo_call(
                    uow.research_feedback.publish(
                        school_id=actor.school_id,
                        feedback_id=record.id,
                        expected_state_version=expected_state_version,
                        expected_case_version=expected_case_version,
                        actor_membership_role_id=role_id,
                        trace_id=trace_id,
                        now=now,
                    )
                )
            else:
                dto = await _repo_call(
                    uow.research_feedback.revoke(
                        school_id=actor.school_id,
                        feedback_id=record.id,
                        expected_state_version=expected_state_version,
                        actor_membership_role_id=role_id,
                        trace_id=trace_id,
                        now=now,
                    )
                )
            await self._audit_research(
                uow,
                actor_account_id=actor_account_id,
                action="school_research_feedback.published"
                if publish
                else "school_research_feedback.revoked",
                resource_type=_FEEDBACK_RESOURCE,
                resource_ref=dto.feedback_ref,
                trace_id=trace_id,
                state=dto.status,
            )
            await self._school_idempotency_complete(
                uow, claim, resource_type=_FEEDBACK_RESOURCE, result_ref=dto.feedback_ref
            )
            return self._feedback_projection(
                dto, case_ref=case.review_ref, session_ref=session_ref, student=False
            )

    async def school_research_feedback_list_student(self, actor, *, offset, limit):
        from sqlalchemy import func

        now, db_now = self._now()
        m = self._db_models
        async with self._uow() as uow:
            account_id, _ = await self._require_actor(uow, actor, "student", db_now)
            base = self._student_candidate_query(actor, account_id, now)
            total = int(
                await uow.session.scalar(
                    self._select(func.count()).select_from(base.order_by(None).subquery())
                )
                or 0
            )
            feedback_refs = (
                await uow.session.scalars(
                    base.order_by(
                        m.SchoolResearchFeedbackRecord.created_at.desc(),
                        m.SchoolResearchFeedbackRecord.feedback_ref.asc(),
                    )
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
            items = []
            for ref in feedback_refs:
                item = await self._student_read(uow, actor, account_id, ref, now)
                items.append(item)
            return {"items": items, "total": total}

    async def school_research_feedback_read_student(self, actor, feedback_ref):
        now, db_now = self._now()
        async with self._uow() as uow:
            account_id, role_id = await self._require_actor(uow, actor, "student", db_now)
            result = await self._student_read(uow, actor, account_id, feedback_ref, now)
            await uow.audit.append(
                action="school_research_feedback.student_read",
                resource_type=_FEEDBACK_RESOURCE,
                resource_public_id=feedback_ref,
                result=self._db_enums.AuditResult.SUCCESS,
                trace_id=get_request_context().trace_id,
                actor_account_id=account_id,
                safe_metadata={"source": "school_research_feedback", "state": "PUBLISHED"},
            )
            return result

    def _student_candidate_query(self, actor, account_id, now):
        m = self._db_models
        return (
            self._select(
                m.SchoolResearchFeedbackRecord.feedback_ref,
                m.SchoolResearchFeedbackRecord.created_at,
            )
            .join(
                m.SchoolResearchReviewCase,
                m.SchoolResearchReviewCase.id == m.SchoolResearchFeedbackRecord.review_case_id,
            )
            .join(
                m.SchoolResearchSession,
                (m.SchoolResearchSession.id == m.SchoolResearchFeedbackRecord.research_session_id)
                & (m.SchoolResearchSession.school_id == m.SchoolResearchFeedbackRecord.school_id)
                & (m.SchoolResearchSession.task_id == m.SchoolResearchFeedbackRecord.task_id)
                & (m.SchoolResearchSession.class_id == m.SchoolResearchFeedbackRecord.class_id)
                & (
                    m.SchoolResearchSession.task_enrollment_id
                    == m.SchoolResearchFeedbackRecord.task_enrollment_id
                )
                & (m.SchoolResearchSession.subject_id == m.SchoolResearchFeedbackRecord.subject_id)
                & (
                    m.SchoolResearchSession.task_binding_id
                    == m.SchoolResearchFeedbackRecord.task_binding_id
                )
                & (
                    m.SchoolResearchSession.profile_version_id
                    == m.SchoolResearchFeedbackRecord.profile_version_id
                )
                & (
                    m.SchoolResearchSession.profile_ref
                    == m.SchoolResearchFeedbackRecord.profile_ref
                )
                & (
                    m.SchoolResearchSession.profile_version_number
                    == m.SchoolResearchFeedbackRecord.profile_version_number
                )
                & (
                    m.SchoolResearchSession.profile_sha256
                    == m.SchoolResearchFeedbackRecord.profile_sha256
                )
                & (
                    m.SchoolResearchSession.response_origin
                    == m.SchoolResearchFeedbackRecord.response_origin
                ),
            )
            .join(
                m.TaskEnrollment,
                (m.TaskEnrollment.id == m.SchoolResearchFeedbackRecord.task_enrollment_id)
                & (m.TaskEnrollment.task_id == m.SchoolResearchFeedbackRecord.task_id)
                & (m.TaskEnrollment.school_id == m.SchoolResearchFeedbackRecord.school_id)
                & (m.TaskEnrollment.class_id == m.SchoolResearchFeedbackRecord.class_id)
                & (m.TaskEnrollment.subject_id == m.SchoolResearchFeedbackRecord.subject_id),
            )
            .join(
                m.SchoolClassStudent,
                (m.SchoolClassStudent.id == m.TaskEnrollment.class_student_id)
                & (m.SchoolClassStudent.school_id == m.TaskEnrollment.school_id)
                & (m.SchoolClassStudent.class_id == m.TaskEnrollment.class_id)
                & (m.SchoolClassStudent.subject_id == m.TaskEnrollment.subject_id),
            )
            .join(
                m.SchoolClass,
                (m.SchoolClass.id == m.SchoolResearchFeedbackRecord.class_id)
                & (m.SchoolClass.school_id == m.SchoolResearchFeedbackRecord.school_id),
            )
            .join(
                m.MeasurementTask,
                (m.MeasurementTask.id == m.SchoolResearchFeedbackRecord.task_id)
                & (m.MeasurementTask.school_id == m.SchoolResearchFeedbackRecord.school_id)
                & (m.MeasurementTask.class_id == m.SchoolResearchFeedbackRecord.class_id),
            )
            .join(
                m.Subject,
                (m.Subject.id == m.SchoolResearchFeedbackRecord.subject_id)
                & (m.Subject.school_id == m.SchoolResearchFeedbackRecord.school_id),
            )
            .join(
                m.SubjectAccessGrant,
                (m.SubjectAccessGrant.subject_id == m.Subject.id)
                & (m.SubjectAccessGrant.school_id == m.Subject.school_id),
            )
            .join(
                m.Account,
                m.Account.id == m.SubjectAccessGrant.principal_account_id,
            )
            .join(
                m.AccountSchoolMembership,
                (m.AccountSchoolMembership.account_id == m.Account.id)
                & (m.AccountSchoolMembership.school_id == m.SubjectAccessGrant.school_id),
            )
            .join(
                m.MembershipRole,
                (m.MembershipRole.membership_id == m.AccountSchoolMembership.id)
                & (m.MembershipRole.school_id == m.AccountSchoolMembership.school_id),
            )
            .where(
                m.SchoolResearchFeedbackRecord.school_id == actor.school_id,
                m.SchoolResearchFeedbackRecord.status == "PUBLISHED",
                m.SchoolResearchFeedbackRecord.publication_status == _PUBLICATION_NOT_APPROVED,
                m.SchoolResearchReviewCase.status == "APPROVED",
                m.SchoolResearchReviewCase.version == m.SchoolResearchFeedbackRecord.case_version,
                m.SchoolResearchSession.status == "COMPLETED",
                m.SchoolResearchSession.purpose == "RESEARCH_SIMULATION",
                m.SchoolResearchSession.research_only.is_(True),
                m.TaskEnrollment.status == "ACTIVE",
                m.TaskEnrollment.revoked_at.is_(None),
                m.SchoolClassStudent.status == "ACTIVE",
                m.SchoolClassStudent.revoked_at.is_(None),
                m.SchoolClassStudent.valid_from <= _naive_utc(now),
                (m.SchoolClassStudent.valid_until.is_(None))
                | (m.SchoolClassStudent.valid_until >= _naive_utc(now)),
                m.SchoolClass.status == "ACTIVE",
                m.MeasurementTask.status.in_(("PUBLISHED", "CLOSED")),
                m.MeasurementTask.cat_binding_mode == "RESEARCH_PROFILE",
                m.Subject.status == self._db_enums.SubjectStatus.ACTIVE.value,
                m.Subject.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                m.Account.status == self._db_enums.AccountStatus.ACTIVE.value,
                m.AccountSchoolMembership.status == "ACTIVE",
                m.AccountSchoolMembership.revoked_at.is_(None),
                m.AccountSchoolMembership.valid_from <= _naive_utc(now),
                (m.AccountSchoolMembership.valid_until.is_(None))
                | (m.AccountSchoolMembership.valid_until >= _naive_utc(now)),
                m.MembershipRole.role_code == "student",
                m.MembershipRole.status == "ACTIVE",
                m.MembershipRole.revoked_at.is_(None),
                m.MembershipRole.valid_from <= _naive_utc(now),
                (m.MembershipRole.valid_until.is_(None))
                | (m.MembershipRole.valid_until >= _naive_utc(now)),
                m.SubjectAccessGrant.school_id == actor.school_id,
                m.SubjectAccessGrant.principal_account_id == account_id,
                m.SubjectAccessGrant.relationship_type == "SELF",
                m.SubjectAccessGrant.status == "ACTIVE",
                m.SubjectAccessGrant.revoked_at.is_(None),
                m.SubjectAccessGrant.valid_from <= _naive_utc(now),
                (m.SubjectAccessGrant.valid_until.is_(None))
                | (m.SubjectAccessGrant.valid_until >= _naive_utc(now)),
            )
            .distinct()
        )

    async def _student_read(self, uow, actor, account_id, feedback_ref, now):
        record = await self._feedback_model_by_ref(uow, actor, feedback_ref, lock=False)
        if record is None:
            raise _not_found()
        candidate = await uow.session.scalar(
            self._student_candidate_query(actor, account_id, now).where(
                self._db_models.SchoolResearchFeedbackRecord.feedback_ref == feedback_ref
            )
        )
        if candidate is None:
            raise _not_found()
        session_ref = await uow.session.scalar(
            self._select(self._db_models.SchoolResearchSession.session_ref).where(
                self._db_models.SchoolResearchSession.id == record.research_session_id,
                self._db_models.SchoolResearchSession.school_id == actor.school_id,
            )
        )
        scope, _metadata, _retention, _profile, _pin = await self._current_scope(
            uow,
            actor,
            await self._task_by_id(uow, actor, record.task_id, lock=False),
            session_ref=session_ref,
            at=now,
            student_account_id=account_id,
        )
        dto = await uow.research_feedback.get_feedback(
            school_id=actor.school_id, feedback_id=record.id
        )
        if dto is None or dto.scope != scope or dto.status != "PUBLISHED":
            raise _not_found()
        case = await uow.research_reviews.get_case(
            school_id=actor.school_id, research_session_id=scope.research_session_id
        )
        if (
            case is None
            or case.id != record.review_case_id
            or case.status != "APPROVED"
            or case.version != record.case_version
        ):
            raise _not_found()
        return self._feedback_projection(
            dto, case_ref=case.review_ref, session_ref=session_ref, student=True
        )

    async def _review_model(self, uow, actor, task, role_id, case_ref, *, lock):
        m = self._db_models
        if (
            not isinstance(case_ref, str)
            or len(case_ref) > 128
            or not _SAFE_REF.fullmatch(case_ref)
        ):
            raise _not_found()
        stmt = self._select(m.SchoolResearchReviewCase).where(
            m.SchoolResearchReviewCase.review_ref == case_ref,
            m.SchoolResearchReviewCase.school_id == actor.school_id,
            m.SchoolResearchReviewCase.task_id == task.id,
            m.SchoolResearchReviewCase.specialist_membership_role_id == role_id,
        )
        if lock:
            stmt = stmt.with_for_update()
        row = await uow.session.scalar(stmt)
        if row is None:
            raise _not_found()
        return row

    async def _review_model_by_ref(self, uow, actor, role_id, case_ref, *, lock):
        m = self._db_models
        if (
            not isinstance(case_ref, str)
            or len(case_ref) > 128
            or not _SAFE_REF.fullmatch(case_ref)
        ):
            raise _not_found()
        stmt = self._select(m.SchoolResearchReviewCase).where(
            m.SchoolResearchReviewCase.review_ref == case_ref,
            m.SchoolResearchReviewCase.school_id == actor.school_id,
            m.SchoolResearchReviewCase.specialist_membership_role_id == role_id,
        )
        if lock:
            stmt = stmt.with_for_update()
        row = await uow.session.scalar(stmt)
        if row is None:
            raise _not_found()
        return row

    async def _feedback_model_by_ref(self, uow, actor, feedback_ref, *, lock):
        m = self._db_models
        if (
            not isinstance(feedback_ref, str)
            or len(feedback_ref) > 128
            or not _SAFE_REF.fullmatch(feedback_ref)
        ):
            raise _not_found()
        stmt = self._select(m.SchoolResearchFeedbackRecord).where(
            m.SchoolResearchFeedbackRecord.feedback_ref == feedback_ref,
            m.SchoolResearchFeedbackRecord.school_id == actor.school_id,
        )
        if lock:
            stmt = stmt.with_for_update()
        row = await uow.session.scalar(stmt)
        if row is None:
            raise _not_found()
        return row

    async def _task_by_id(self, uow, actor, task_id, *, lock):
        m = self._db_models
        stmt = (
            self._select(m.MeasurementTask)
            .join(m.School, m.School.id == m.MeasurementTask.school_id)
            .where(
                m.MeasurementTask.id == task_id,
                m.MeasurementTask.school_id == actor.school_id,
                m.School.school_ref == actor.school_ref,
                m.School.status == "ACTIVE",
                m.School.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                m.MeasurementTask.status.in_(("PUBLISHED", "CLOSED")),
                m.MeasurementTask.cat_binding_mode == "RESEARCH_PROFILE",
            )
        )
        if lock:
            stmt = stmt.with_for_update()
        task = await uow.session.scalar(stmt)
        if task is None:
            raise _not_found()
        return task

    async def _feedback_by_id(self, uow, actor, feedback_id):
        return await uow.research_feedback.get_feedback(
            school_id=actor.school_id, feedback_id=feedback_id
        )

    async def _audit_research(
        self, uow, *, actor_account_id, action, resource_type, resource_ref, trace_id, state
    ):
        await uow.audit.append(
            action=action,
            resource_type=resource_type,
            resource_public_id=resource_ref,
            result=self._db_enums.AuditResult.SUCCESS,
            trace_id=trace_id,
            actor_account_id=actor_account_id,
            safe_metadata={"source": "school_research_feedback", "state": state},
        )
