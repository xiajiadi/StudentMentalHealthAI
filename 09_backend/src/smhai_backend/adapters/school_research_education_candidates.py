"""Persistence and live authorization for task-bound education candidates."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import func

from smhai_backend.adapters.school_research_feedback import (
    SchoolResearchFeedbackPersistenceAdapter,
    _naive_utc,
    _repo_call,
)
from smhai_backend.core.errors import BackendError, ErrorCode, error
from smhai_backend.domains.research_general_education.schemas import (
    ResearchGeneralEducationCandidatePayload,
)
from smhai_backend.domains.school_research.study_use import ResearchStudyUsePolicy

_POLICY_VERSION = "RESEARCH_GENERAL_EDUCATION_DRAFT_V1"
_PAYLOAD_SCHEMA = "school-research-general-education-candidate.v1"
_BATCH_RESOURCE = "school_research_education_candidate_batch"
_JOB_RESOURCE = "school_research_education_candidate_job"
_CANDIDATE_RESOURCE = "school_research_education_candidate"
_PUBLICATION_STATUS = "not_approved_for_publication_or_operational_use"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _not_found():
    return error(
        ErrorCode.RESOURCE_NOT_FOUND,
        detail="research education candidate was not found",
    )


def _conflict():
    return error(
        ErrorCode.WORKFLOW_CONFLICT,
        detail="research education candidate state changed",
    )


async def _candidate_repo_call(awaitable):
    from database_layer.errors import (
        DatabaseUnavailable,
        EncryptionKeyUnavailable,
        ForeignKeyConflict,
        NotFound,
        OptimisticConcurrencyConflict,
        UniqueConflict,
    )
    from database_layer.school_research_education_candidates import (
        ResearchEducationCandidateError,
    )

    try:
        return await awaitable
    except (OptimisticConcurrencyConflict, UniqueConflict):
        raise _conflict() from None
    except (ForeignKeyConflict, NotFound):
        raise _not_found() from None
    except ResearchEducationCandidateError as exc:
        if exc.code in {"INVALID_INPUT", "INVALID_ENCRYPTED_PAYLOAD", "INVALID_SCOPE"}:
            raise error(
                ErrorCode.VALIDATION_FAILED,
                detail="research education candidate input is invalid",
            ) from None
        raise _conflict() from None
    except (DatabaseUnavailable, EncryptionKeyUnavailable):
        raise error(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            detail="research education candidate storage is unavailable",
            retryable=True,
        ) from None


class SchoolResearchEducationCandidatePersistenceAdapter(SchoolResearchFeedbackPersistenceAdapter):
    """Reuse the established task Scope C checks and exact completed-session scope."""

    def __init__(
        self,
        persistence,
        *,
        enabled: bool,
        school_id: int | None,
        school_study_ref: str | None,
        policy_hash: str | None,
        source_manifest_sha256: str | None,
        source_package_ref: str | None,
        source_study_ref: str | None,
        study_use_policy: ResearchStudyUsePolicy | None,
    ) -> None:
        super().__init__(persistence, study_use_policy=study_use_policy)
        self.enabled = enabled is True
        self.school_id = school_id
        self.school_study_ref = school_study_ref
        self.policy_hash = policy_hash
        self.source_manifest_sha256 = source_manifest_sha256
        self.source_package_ref = source_package_ref
        self.source_study_ref = source_study_ref

    def _require_enabled(self) -> None:
        if (
            not self.enabled
            or type(self.school_id) is not int
            or self.school_id <= 0
            or not isinstance(self.school_study_ref, str)
            or not self.school_study_ref
            or not isinstance(self.source_package_ref, str)
            or not self.source_package_ref
            or not isinstance(self.source_study_ref, str)
            or not self.source_study_ref
            or not isinstance(self.policy_hash, str)
            or _SHA256.fullmatch(self.policy_hash) is None
            or not isinstance(self.source_manifest_sha256, str)
            or _SHA256.fullmatch(self.source_manifest_sha256) is None
            or type(self.study_use_policy) is not ResearchStudyUsePolicy
            or self.study_use_policy.source_rights_verified is not True
            or self.study_use_policy.study_ref != self.school_study_ref
        ):
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="research education candidate policy is unavailable",
                retryable=True,
            )

    async def _active_task(self, uow, actor, task_ref: str, *, at: datetime):
        if actor.school_id != self.school_id:
            raise _not_found()
        _account_id, role_id = await self._require_actor(
            uow, actor, "psychological_specialist", _naive_utc(at)
        )
        task = await self._task(uow, actor, task_ref, lock=True)
        assignment = await self._active_assignment(uow, actor, task, at=_naive_utc(at), lock=True)
        if assignment.specialist_membership_role_id != role_id:
            raise _not_found()
        binding, _profile = await self._require_task_study_scope(uow, actor, task, at)
        if binding.response_origin != "PUBLIC_OBSERVED":
            raise _not_found()
        return task, binding, role_id

    async def school_research_education_candidate_list_tasks(self, actor):
        self._require_enabled()
        now, db_now = self._now()
        m = self._db_models
        async with self._uow() as uow:
            _, role_id = await self._require_actor(uow, actor, "psychological_specialist", db_now)
            if actor.school_id != self.school_id:
                raise _not_found()
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
            items = []
            for task_ref, class_ref, class_name, published_at in rows:
                task, _binding, _role = await self._active_task(uow, actor, task_ref, at=now)
                items.append(
                    {
                        "task_ref": task_ref,
                        "class_ref": class_ref,
                        "class_display_name": class_name,
                        "published_at": published_at or task.published_at,
                    }
                )
            return {"items": items}

    def _candidate_scope(self, scope):
        from database_layer.school_research_education_candidates import (
            ResearchEducationCandidateScope,
        )

        return ResearchEducationCandidateScope(
            research_session_id=scope.research_session_id,
            school_id=scope.school_id,
            task_id=scope.task_id,
            class_id=scope.class_id,
            task_enrollment_id=scope.task_enrollment_id,
            subject_id=scope.subject_id,
            task_binding_id=scope.task_binding_id,
            profile_version_id=scope.profile_version_id,
            profile_ref=scope.profile_ref,
            profile_version_number=scope.profile_version_number,
            profile_sha256=scope.profile_sha256,
            response_origin=scope.response_origin,
        )

    @staticmethod
    def _same_scope(left, right) -> bool:
        names = (
            "research_session_id",
            "school_id",
            "task_id",
            "class_id",
            "task_enrollment_id",
            "subject_id",
            "task_binding_id",
            "profile_version_id",
            "profile_ref",
            "profile_version_number",
            "profile_sha256",
            "response_origin",
        )
        return all(getattr(left, name) == getattr(right, name) for name in names)

    def _require_row_pins(self, row) -> None:
        if (
            row.study_ref != self.school_study_ref
            or row.policy_version != _POLICY_VERSION
            or row.policy_hash != self.policy_hash
            or row.source_manifest_sha256 != self.source_manifest_sha256
            or row.purpose != "RESEARCH_SIMULATION"
            or row.research_only is not True
            or row.psychological_interpretation_allowed is not False
            or row.publication_status != _PUBLICATION_STATUS
            or row.safety_policy_version != "safety-port-unversioned.v1"
            or row.content_revision != 1
            or row.status not in {"HELD", "ADOPTED", "DISCARDED"}
            or row.state_version not in {1, 2}
            or (row.status == "HELD") != (row.state_version == 1)
            or row.scope.response_origin != "PUBLIC_OBSERVED"
            or not isinstance(row.content_sha256, str)
            or _SHA256.fullmatch(row.content_sha256) is None
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research education candidate metadata is unavailable",
            )

    def _payload_from_row(self, row):
        from database_layer.crypto import EncryptedPayload

        from smhai_backend.domains.research_general_education.service import (
            EXPECTED_MODEL_DIGEST_SHA256,
            EXPECTED_MODEL_ID,
            EXPECTED_MODEL_VERSION,
            PROMPT_ID,
            PROMPT_SHA256,
            PROMPT_VERSION,
            SAFETY_POLICY_VERSION,
        )

        if (
            row.payload_schema_version != _PAYLOAD_SCHEMA
            or not row.cipher_format_version
            or not row.key_version
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research education candidate content is unavailable",
            )
        try:
            value = self.protection.decrypt_json(
                EncryptedPayload(
                    ciphertext=row.payload_ciphertext,
                    cipher_format_version=row.cipher_format_version,
                    key_version=row.key_version,
                    payload_schema_version=row.payload_schema_version,
                )
            )
            payload = ResearchGeneralEducationCandidatePayload.from_closed_mapping(value)
        except Exception:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research education candidate content is unavailable",
            ) from None
        provenance = payload.provenance
        if (
            provenance.policy_version != row.policy_version
            or provenance.policy_hash != row.policy_hash
            or provenance.source_manifest_sha256 != row.source_manifest_sha256
            or provenance.source_package_ref != self.source_package_ref
            or provenance.source_study_ref != self.source_study_ref
            or provenance.source_age_scope != "14-17"
            or provenance.safety_policy_version != SAFETY_POLICY_VERSION
            or provenance.retrieval_id != row.retrieval_id
            or provenance.retrieval_bundle_sha256 != row.retrieval_bundle_sha256
            or provenance.prompt_id != row.prompt_ref
            or provenance.prompt_id != PROMPT_ID
            or provenance.prompt_version != row.prompt_version
            or provenance.prompt_version != PROMPT_VERSION
            or provenance.prompt_sha256 != row.prompt_sha256
            or provenance.prompt_sha256 != PROMPT_SHA256
            or provenance.model_id != row.model_ref
            or provenance.model_id != EXPECTED_MODEL_ID
            or provenance.model_version != EXPECTED_MODEL_VERSION
            or provenance.model_digest_sha256 != row.model_digest_sha256
            or provenance.model_digest_sha256 != EXPECTED_MODEL_DIGEST_SHA256
            or provenance.runtime_version != row.runtime_version
            or provenance.runtime_local_only is not True
            or provenance.runtime_attempt_count != 1
            or provenance.runtime_retry_count != 0
            or provenance.runtime_fallback_count != 0
            or provenance.runtime_fallback_attempted is not False
            or provenance.input_safety_action != row.input_safety_action
            or provenance.retrieval_safety_action != row.retrieval_safety_action
            or provenance.output_safety_action != row.output_safety_action
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research education candidate provenance is unavailable",
            )
        card_by_chunk = {card.chunk_id: card for card in payload.source_cards}
        allowed_chunks = set(card_by_chunk)
        if any(
            hashlib.sha256(card.excerpt_text.encode("utf-8")).hexdigest() != card.excerpt_sha256
            or card.consumer_age_min > card.consumer_age_max
            for card in payload.source_cards
        ) or any(
            not set(suggestion.source_chunk_ids).issubset(allowed_chunks)
            for suggestion in payload.content.suggestions
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research education candidate citations are unavailable",
            )
        canonical = json.dumps(
            payload.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if hashlib.sha256(canonical).hexdigest() != row.content_sha256:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research education candidate content is unavailable",
            )
        return payload

    def validate_feedback_candidate_in_uow(self, row, expected_scope):
        """Validate adopted candidate lineage for the caller's already-live exact session scope."""
        self._require_enabled()
        self._require_row_pins(row)
        if (
            row.status != "ADOPTED"
            or row.state_version != 2
            or row.content_revision != 1
            or not self._same_scope(row.scope, expected_scope)
        ):
            raise _conflict()
        payload = self._payload_from_row(row)
        if (
            payload.provenance.policy_hash != self.policy_hash
            or payload.provenance.source_manifest_sha256 != self.source_manifest_sha256
        ):
            raise _conflict()
        return payload

    async def _session_ref(self, uow, actor, task, session_id: int) -> str:
        m = self._db_models
        value = await uow.session.scalar(
            self._select(m.SchoolResearchSession.session_ref).where(
                m.SchoolResearchSession.id == session_id,
                m.SchoolResearchSession.school_id == actor.school_id,
                m.SchoolResearchSession.task_id == task.id,
            )
        )
        if not isinstance(value, str) or not value:
            raise _not_found()
        return value

    async def _require_active_specialist_assignment(self, uow, task, *, at: datetime) -> None:
        m = self._db_models
        assignment_id = await uow.session.scalar(
            self._select(m.SchoolTaskSpecialistAssignment.id)
            .join(
                m.MembershipRole,
                m.MembershipRole.id
                == m.SchoolTaskSpecialistAssignment.specialist_membership_role_id,
            )
            .join(
                m.AccountSchoolMembership,
                m.AccountSchoolMembership.id == m.MembershipRole.membership_id,
            )
            .join(m.Account, m.Account.id == m.AccountSchoolMembership.account_id)
            .where(
                m.SchoolTaskSpecialistAssignment.school_id == task.school_id,
                m.SchoolTaskSpecialistAssignment.task_id == task.id,
                m.SchoolTaskSpecialistAssignment.class_id == task.class_id,
                m.SchoolTaskSpecialistAssignment.status == "ACTIVE",
                m.SchoolTaskSpecialistAssignment.revoked_at.is_(None),
                m.MembershipRole.school_id == task.school_id,
                m.MembershipRole.role_code == "psychological_specialist",
                m.MembershipRole.status == "ACTIVE",
                m.MembershipRole.revoked_at.is_(None),
                m.MembershipRole.valid_from <= _naive_utc(at),
                (m.MembershipRole.valid_until.is_(None))
                | (m.MembershipRole.valid_until >= _naive_utc(at)),
                m.AccountSchoolMembership.school_id == task.school_id,
                m.AccountSchoolMembership.status == "ACTIVE",
                m.AccountSchoolMembership.revoked_at.is_(None),
                m.AccountSchoolMembership.valid_from <= _naive_utc(at),
                (m.AccountSchoolMembership.valid_until.is_(None))
                | (m.AccountSchoolMembership.valid_until >= _naive_utc(at)),
                m.Account.status == self._db_enums.AccountStatus.ACTIVE.value,
            )
            .limit(1)
            .with_for_update()
        )
        if assignment_id is None:
            raise _conflict()

    async def _current_candidate(
        self, uow, actor, task, row, *, at, lock=False, include_payload=False
    ):
        self._require_row_pins(row)
        if row.scope.task_id != task.id or row.scope.school_id != actor.school_id:
            raise _not_found()
        session_ref = await self._session_ref(uow, actor, task, row.scope.research_session_id)
        scope, _metadata, _retention, _profile, _pin = await self._current_scope(
            uow, actor, task, session_ref=session_ref, at=at, lock=lock
        )
        if scope.response_origin != "PUBLIC_OBSERVED" or not self._same_scope(row.scope, scope):
            raise _not_found()
        payload = self._payload_from_row(row) if include_payload else None
        return scope, session_ref, payload

    def _summary(self, row, *, task_ref, session_ref):
        self._require_row_pins(row)
        return {
            "candidate_ref": row.candidate_ref,
            "task_ref": task_ref,
            "session_ref": session_ref,
            "status": row.status,
            "state_version": row.state_version,
            "purpose": row.purpose,
            "research_only": row.research_only,
            "psychological_interpretation_allowed": row.psychological_interpretation_allowed,
            "publication_status": row.publication_status,
            "student_feedback_eligible": False,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    async def school_research_education_candidate_list(
        self, actor, task_ref: str, *, status: str, offset: int, limit: int
    ) -> dict:
        self._require_enabled()
        if (
            status not in {"HELD", "ADOPTED", "DISCARDED"}
            or type(offset) is not int
            or not 0 <= offset <= 100_000
            or type(limit) is not int
            or not 1 <= limit <= 50
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="candidate pagination is invalid")
        now, db_now = self._now()
        m = self._db_models
        async with self._uow() as uow:
            task, _binding, role_id = await self._active_task(uow, actor, task_ref, at=now)
            rows = await uow.research_education_candidates.list_for_task(
                school_id=actor.school_id,
                task_id=task.id,
                status=status,
                limit=limit,
                offset=offset,
            )
            total = int(
                await uow.session.scalar(
                    self._select(func.count()).where(
                        m.SchoolResearchEducationCandidate.school_id == actor.school_id,
                        m.SchoolResearchEducationCandidate.task_id == task.id,
                        m.SchoolResearchEducationCandidate.status == status,
                    )
                )
                or 0
            )
            items = []
            for row in rows:
                _scope, session_ref, _payload = await self._current_candidate(
                    uow, actor, task, row, at=now
                )
                items.append(self._summary(row, task_ref=task_ref, session_ref=session_ref))
            return {
                "items": items,
                "offset": offset,
                "limit": limit,
                "has_more": offset + len(items) < total,
            }

    async def school_research_education_candidate_get(
        self, actor, task_ref: str, candidate_ref: str
    ) -> dict:
        self._require_enabled()
        now, _db_now = self._now()
        async with self._uow() as uow:
            task, _binding, _role_id = await self._active_task(uow, actor, task_ref, at=now)
            row = await uow.research_education_candidates.get_for_task(
                school_id=actor.school_id,
                task_id=task.id,
                candidate_ref=candidate_ref,
            )
            if row is None:
                raise _not_found()
            _scope, session_ref, payload = await self._current_candidate(
                uow, actor, task, row, at=now, include_payload=True
            )
            return {
                **self._summary(row, task_ref=task_ref, session_ref=session_ref),
                "candidate_payload": payload.model_dump(mode="python"),
            }

    async def school_research_education_candidate_resolve(
        self,
        actor,
        task_ref: str,
        candidate_ref: str,
        *,
        expected_state_version: int,
        target: str,
        idempotency,
        trace_id: str,
    ) -> dict:
        self._require_enabled()
        if (
            type(expected_state_version) is not int
            or expected_state_version not in {1, 2}
            or target not in {"ADOPTED", "DISCARDED"}
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="candidate resolution is invalid")
        now, db_now = self._now()
        async with self._uow() as uow:
            actor_account_id, role_id = await self._require_actor(
                uow, actor, "psychological_specialist", db_now
            )
            task, _binding, checked_role_id = await self._active_task(uow, actor, task_ref, at=now)
            if checked_role_id != role_id:
                raise _not_found()
            row = await uow.research_education_candidates.get_for_task(
                school_id=actor.school_id,
                task_id=task.id,
                candidate_ref=candidate_ref,
            )
            if row is None:
                raise _not_found()
            _scope, session_ref, _payload = await self._current_candidate(
                uow, actor, task, row, at=now, lock=True
            )
            claim = await self._school_idempotency_begin(uow, idempotency)
            if claim.replayed:
                if await self._receipt_resource(claim, _CANDIDATE_RESOURCE) != row.candidate_ref:
                    raise _conflict()
                current = await uow.research_education_candidates.get_for_task(
                    school_id=actor.school_id,
                    task_id=task.id,
                    candidate_ref=candidate_ref,
                )
                if (
                    current is None
                    or current.status != target
                    or current.state_version != 2
                    or current.resolved_by_membership_role_id != role_id
                ):
                    raise _conflict()
                return self._summary(current, task_ref=task_ref, session_ref=session_ref)
            updated = await _candidate_repo_call(
                uow.research_education_candidates.resolve(
                    school_id=actor.school_id,
                    task_id=task.id,
                    candidate_ref=candidate_ref,
                    expected_state_version=expected_state_version,
                    target=target,
                    actor_membership_role_id=role_id,
                    trace_id=trace_id,
                    now=now,
                )
            )
            self._require_row_pins(updated)
            await self._audit_research(
                uow,
                actor_account_id=actor_account_id,
                action=f"school_research_education_candidate.{target.lower()}",
                resource_type=_CANDIDATE_RESOURCE,
                resource_ref=updated.candidate_ref,
                trace_id=trace_id,
                state=updated.status,
            )
            await self._school_idempotency_complete(
                uow,
                claim,
                resource_type=_CANDIDATE_RESOURCE,
                result_ref=updated.candidate_ref,
            )
            return self._summary(updated, task_ref=task_ref, session_ref=session_ref)

    async def school_research_education_candidate_queue_batch(
        self,
        actor,
        task_ref: str,
        *,
        limit: int,
        offset: int,
        idempotency,
        trace_id: str,
    ) -> dict:
        """Atomically enqueue a stable page of exact eligible public-observed sessions."""
        self._require_enabled()
        if (
            type(limit) is not int
            or not 1 <= limit <= 100
            or type(offset) is not int
            or not 0 <= offset <= 100_000
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="candidate batch bounds are invalid")
        from database_layer.school_research_education_jobs import (
            GENERAL_EDUCATION_POLICY_VERSION,
        )

        now, db_now = self._now()
        m = self._db_models
        async with self._uow() as uow:
            actor_account_id, role_id = await self._require_actor(
                uow, actor, "psychological_specialist", db_now
            )
            task, binding, checked_role_id = await self._active_task(uow, actor, task_ref, at=now)
            if checked_role_id != role_id:
                raise _not_found()

            grant = m.SubjectAccessGrant
            active_student_grants = (
                self._select(
                    grant.id.label("grant_id"),
                    grant.school_id.label("school_id"),
                    grant.subject_id.label("subject_id"),
                )
                .join(m.Account, m.Account.id == grant.principal_account_id)
                .join(
                    m.AccountSchoolMembership,
                    (m.AccountSchoolMembership.account_id == m.Account.id)
                    & (m.AccountSchoolMembership.school_id == grant.school_id),
                )
                .join(
                    m.MembershipRole,
                    (m.MembershipRole.membership_id == m.AccountSchoolMembership.id)
                    & (m.MembershipRole.school_id == m.AccountSchoolMembership.school_id),
                )
                .where(
                    grant.school_id == actor.school_id,
                    grant.relationship_type == "SELF",
                    grant.status == "ACTIVE",
                    grant.revoked_at.is_(None),
                    grant.valid_from <= db_now,
                    (grant.valid_until.is_(None)) | (grant.valid_until >= db_now),
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
                .subquery()
            )
            session = m.SchoolResearchSession
            enrollment = m.TaskEnrollment
            roster = m.SchoolClassStudent
            school_class = m.SchoolClass
            subject = m.Subject
            eligible_query = (
                self._select(
                    session.id.label("session_id"),
                    session.session_ref.label("session_ref"),
                    session.completed_at.label("completed_at"),
                )
                .join(
                    enrollment,
                    (enrollment.id == session.task_enrollment_id)
                    & (enrollment.task_id == session.task_id)
                    & (enrollment.school_id == session.school_id)
                    & (enrollment.class_id == session.class_id)
                    & (enrollment.subject_id == session.subject_id),
                )
                .join(
                    roster,
                    (roster.id == enrollment.class_student_id)
                    & (roster.school_id == enrollment.school_id)
                    & (roster.class_id == enrollment.class_id)
                    & (roster.subject_id == enrollment.subject_id),
                )
                .join(
                    school_class,
                    (school_class.id == session.class_id)
                    & (school_class.school_id == session.school_id),
                )
                .join(
                    subject,
                    (subject.id == session.subject_id) & (subject.school_id == session.school_id),
                )
                .join(
                    active_student_grants,
                    (active_student_grants.c.school_id == session.school_id)
                    & (active_student_grants.c.subject_id == session.subject_id),
                )
                .where(
                    session.school_id == actor.school_id,
                    session.task_id == task.id,
                    session.class_id == task.class_id,
                    session.task_binding_id == binding.binding_id,
                    session.profile_version_id == binding.profile_version_id,
                    session.profile_ref == binding.profile_ref,
                    session.profile_version_number == binding.profile_version_number,
                    session.profile_sha256 == binding.profile_sha256,
                    session.response_origin == "PUBLIC_OBSERVED",
                    session.status == "COMPLETED",
                    session.completed_at.is_not(None),
                    session.purpose == "RESEARCH_SIMULATION",
                    session.research_only.is_(True),
                    enrollment.status == "ACTIVE",
                    enrollment.revoked_at.is_(None),
                    roster.status == "ACTIVE",
                    roster.revoked_at.is_(None),
                    roster.valid_from <= db_now,
                    (roster.valid_until.is_(None)) | (roster.valid_until >= db_now),
                    school_class.status == "ACTIVE",
                    subject.status == self._db_enums.SubjectStatus.ACTIVE.value,
                    subject.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                )
                .group_by(session.id, session.session_ref, session.completed_at)
                .having(func.count(func.distinct(active_student_grants.c.grant_id)) == 1)
                .order_by(session.completed_at, session.id)
                .offset(offset)
                .limit(limit + 1)
            )
            page = list((await uow.session.execute(eligible_query)).all())
            has_more = len(page) > limit
            page = page[:limit]
            selected = []
            for result in page:
                session_ref = result._mapping["session_ref"]
                scope, metadata, _retention, _profile, _pin = await self._current_scope(
                    uow, actor, task, session_ref=session_ref, at=now, lock=True
                )
                if (
                    scope.response_origin != "PUBLIC_OBSERVED"
                    or metadata.session_id != result._mapping["session_id"]
                ):
                    raise _conflict()
                selected.append((scope, session_ref))

            request_fingerprint = (
                f"{actor.school_id}:{task.id}:{binding.binding_id}:{offset}:{limit}:"
                f"{_POLICY_VERSION}:{self.policy_hash}:{self.source_manifest_sha256}:"
                f"{self.source_package_ref}:{self.source_study_ref}:{self.school_study_ref}:"
                f"{binding.profile_sha256}:"
                + ":".join(str(scope.research_session_id) for scope, _ in selected)
            )
            batch_ref = (
                "REGENBATCH_" + hashlib.sha256(request_fingerprint.encode("ascii")).hexdigest()
            )
            idem_claim = await self._school_idempotency_begin(uow, idempotency)

            existing_session_ids = set()
            if selected:
                existing_session_ids = set(
                    (
                        await uow.session.scalars(
                            self._select(m.SchoolResearchEducationJob.research_session_id).where(
                                m.SchoolResearchEducationJob.school_id == actor.school_id,
                                m.SchoolResearchEducationJob.task_id == task.id,
                                m.SchoolResearchEducationJob.policy_version == _POLICY_VERSION,
                                m.SchoolResearchEducationJob.policy_hash == self.policy_hash,
                                m.SchoolResearchEducationJob.research_session_id.in_(
                                    [scope.research_session_id for scope, _ in selected]
                                ),
                            )
                        )
                    ).all()
                )

            if idem_claim.replayed:
                receipt = await self._receipt_resource(idem_claim, _BATCH_RESOURCE)
                if receipt != batch_ref:
                    raise _conflict()
                rows = (
                    (
                        await uow.session.execute(
                            self._select(
                                m.SchoolResearchEducationJob.research_session_id,
                                m.SchoolResearchEducationJob.job_ref,
                            ).where(
                                m.SchoolResearchEducationJob.school_id == actor.school_id,
                                m.SchoolResearchEducationJob.task_id == task.id,
                                m.SchoolResearchEducationJob.policy_version == _POLICY_VERSION,
                                m.SchoolResearchEducationJob.policy_hash == self.policy_hash,
                                m.SchoolResearchEducationJob.research_session_id.in_(
                                    [scope.research_session_id for scope, _ in selected]
                                ),
                            )
                        )
                    ).all()
                    if selected
                    else []
                )
                replay_refs = {
                    row._mapping["research_session_id"]: row._mapping["job_ref"] for row in rows
                }
                if set(replay_refs) != {scope.research_session_id for scope, _ in selected}:
                    raise _conflict()
                job_refs = [replay_refs[scope.research_session_id] for scope, _ in selected]
            else:
                jobs = []
                for scope, _session_ref in selected:
                    job = await _repo_call(
                        uow.research_education_jobs.enqueue_completed_session(
                            school_id=scope.school_id,
                            research_session_id=scope.research_session_id,
                            task_id=scope.task_id,
                            class_id=scope.class_id,
                            task_enrollment_id=scope.task_enrollment_id,
                            subject_id=scope.subject_id,
                            task_binding_id=scope.task_binding_id,
                            profile_version_id=scope.profile_version_id,
                            profile_ref=scope.profile_ref,
                            profile_version_number=scope.profile_version_number,
                            profile_sha256=scope.profile_sha256,
                            response_origin=scope.response_origin,
                            policy_version=GENERAL_EDUCATION_POLICY_VERSION,
                            policy_hash=self.policy_hash,
                            now=now,
                        )
                    )
                    jobs.append((scope, job))
                job_refs = [job.job_ref for _scope, job in jobs]
                for scope, job in jobs:
                    if scope.research_session_id in existing_session_ids:
                        continue
                    await self._audit_research(
                        uow,
                        actor_account_id=actor_account_id,
                        action="school_research_education_candidate_job.queued",
                        resource_type=_JOB_RESOURCE,
                        resource_ref=job.job_ref,
                        trace_id=trace_id,
                        state=job.status,
                    )
                await self._school_idempotency_complete(
                    uow,
                    idem_claim,
                    resource_type=_BATCH_RESOURCE,
                    result_ref=batch_ref,
                )

            return {
                "batch_ref": batch_ref,
                "job_refs": job_refs,
                "job_count": len(job_refs),
                "offset": offset,
                "limit": limit,
                "next_offset": offset + len(page) if has_more else None,
                "policy_version": _POLICY_VERSION,
                "purpose": "RESEARCH_SIMULATION",
                "research_only": True,
                "publication_status": _PUBLICATION_STATUS,
                "student_feedback_eligible": False,
            }

    def _validate_new_payload(self, payload):
        from smhai_backend.domains.research_general_education.service import (
            EXPECTED_MODEL_DIGEST_SHA256,
            EXPECTED_MODEL_ID,
            EXPECTED_MODEL_VERSION,
            PROMPT_ID,
            PROMPT_SHA256,
            PROMPT_VERSION,
            SAFETY_POLICY_VERSION,
        )

        if type(payload) is not ResearchGeneralEducationCandidatePayload:
            try:
                payload = ResearchGeneralEducationCandidatePayload.from_closed_mapping(payload)
            except Exception:
                raise error(
                    ErrorCode.VALIDATION_FAILED,
                    detail="research education candidate content is invalid",
                ) from None
        provenance = payload.provenance
        if (
            provenance.policy_version != _POLICY_VERSION
            or provenance.policy_hash != self.policy_hash
            or provenance.source_package_ref != self.source_package_ref
            or provenance.source_study_ref != self.source_study_ref
            or provenance.source_manifest_sha256 != self.source_manifest_sha256
            or provenance.source_age_scope != "14-17"
            or provenance.safety_policy_version != SAFETY_POLICY_VERSION
            or provenance.model_id != EXPECTED_MODEL_ID
            or provenance.model_version != EXPECTED_MODEL_VERSION
            or provenance.model_digest_sha256 != EXPECTED_MODEL_DIGEST_SHA256
            or provenance.prompt_id != PROMPT_ID
            or provenance.prompt_version != PROMPT_VERSION
            or provenance.prompt_sha256 != PROMPT_SHA256
            or provenance.runtime_local_only is not True
            or provenance.runtime_attempt_count != 1
            or provenance.runtime_retry_count != 0
            or provenance.runtime_fallback_count != 0
            or provenance.runtime_fallback_attempted is not False
            or any(
                hashlib.sha256(card.excerpt_text.encode("utf-8")).hexdigest() != card.excerpt_sha256
                or card.consumer_age_min > card.consumer_age_max
                for card in payload.source_cards
            )
            or any(
                not set(suggestion.source_chunk_ids).issubset(
                    {card.chunk_id for card in payload.source_cards}
                )
                for suggestion in payload.content.suggestions
            )
        ):
            raise error(
                ErrorCode.FORBIDDEN,
                detail="research education candidate pins are unavailable",
            )
        return payload

    @staticmethod
    def _payload_sha256(payload) -> str:
        body = json.dumps(
            payload.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(body).hexdigest()

    @staticmethod
    def _same_claim_identity(left, right) -> bool:
        names = (
            "id",
            "job_ref",
            "school_id",
            "research_session_id",
            "task_id",
            "class_id",
            "task_enrollment_id",
            "subject_id",
            "task_binding_id",
            "profile_version_id",
            "profile_ref",
            "profile_version_number",
            "profile_sha256",
            "response_origin",
            "policy_version",
            "policy_hash",
            "purpose",
            "research_only",
            "publication_status",
            "status",
            "lease_owner",
            "lease_token",
        )
        return all(getattr(left, name) == getattr(right, name) for name in names)

    async def _live_claim_scope(self, uow, claim, *, now: datetime):
        from database_layer.school_research_education_jobs import (
            GENERAL_EDUCATION_POLICY_VERSION,
            ResearchEducationJobClaim,
        )

        if (
            type(claim) is not ResearchEducationJobClaim
            or claim.policy_version != GENERAL_EDUCATION_POLICY_VERSION
            or claim.policy_hash != self.policy_hash
            or claim.response_origin != "PUBLIC_OBSERVED"
            or claim.school_id != self.school_id
            or claim.status != "LEASED"
            or claim.purpose != "RESEARCH_SIMULATION"
            or claim.research_only is not True
            or claim.publication_status != _PUBLICATION_STATUS
        ):
            raise _conflict()
        m = self._db_models
        task = await uow.session.scalar(
            self._select(m.MeasurementTask)
            .join(m.School, m.School.id == m.MeasurementTask.school_id)
            .where(
                m.MeasurementTask.id == claim.task_id,
                m.MeasurementTask.school_id == claim.school_id,
                m.MeasurementTask.class_id == claim.class_id,
                m.MeasurementTask.status.in_(("PUBLISHED", "CLOSED")),
                m.MeasurementTask.cat_binding_mode == "RESEARCH_PROFILE",
                m.School.status == "ACTIVE",
                m.School.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
            )
            .with_for_update()
        )
        if task is None:
            raise _not_found()
        await self._require_active_specialist_assignment(uow, task, at=now)
        actor_scope = SimpleNamespace(
            school_id=claim.school_id,
            school_ref=await uow.session.scalar(
                self._select(m.School.school_ref).where(m.School.id == claim.school_id)
            ),
        )
        binding, _profile = await self._require_task_study_scope(
            uow, actor_scope, task, now
        )
        if (
            task.id != claim.task_id
            or task.class_id != claim.class_id
            or binding.binding_id != claim.task_binding_id
            or binding.response_origin != "PUBLIC_OBSERVED"
            or binding.profile_version_id != claim.profile_version_id
            or binding.profile_ref != claim.profile_ref
            or binding.profile_version_number != claim.profile_version_number
            or binding.profile_sha256 != claim.profile_sha256
        ):
            raise _conflict()
        session_ref = await self._session_ref(
            uow, actor_scope, task, claim.research_session_id
        )
        scope, _metadata, retention, _profile, _pin = await self._current_scope(
            uow, actor_scope, task, session_ref=session_ref, at=now, lock=True
        )
        if not self._same_scope(scope, claim) or scope.response_origin != "PUBLIC_OBSERVED":
            raise _conflict()

        # Batch enqueue takes task/session locks before inspecting or locking job rows.
        # Keep workers on the same order, then revalidate the exact live lease last.
        persisted = await _repo_call(
            uow.research_education_jobs.require_active_claim(
                school_id=claim.school_id,
                research_session_id=claim.research_session_id,
                job_id=claim.id,
                lease_owner=claim.lease_owner,
                lease_token=claim.lease_token,
                now=now,
            )
        )
        if (
            type(persisted) is not ResearchEducationJobClaim
            or not self._same_claim_identity(persisted, claim)
            or persisted.policy_version != GENERAL_EDUCATION_POLICY_VERSION
            or persisted.policy_hash != self.policy_hash
            or persisted.response_origin != "PUBLIC_OBSERVED"
            or persisted.purpose != "RESEARCH_SIMULATION"
            or persisted.research_only is not True
            or persisted.publication_status != _PUBLICATION_STATUS
            or persisted.status != "LEASED"
            or persisted.lease_owner != claim.lease_owner
            or persisted.lease_token != claim.lease_token
            or not self._same_scope(scope, persisted)
        ):
            raise _conflict()
        return persisted, task, actor_scope, session_ref, scope, retention

    async def authorize_education_claim(self, claim) -> bool:
        """Authorize the exact live research session before any processor/model call."""
        self._require_enabled()
        now, _db_now = self._now()
        try:
            async with self._uow() as uow:
                await self._live_claim_scope(uow, claim, now=now)
            return True
        except BackendError as exc:
            if exc.code in {
                ErrorCode.FORBIDDEN,
                ErrorCode.RESOURCE_NOT_FOUND,
                ErrorCode.WORKFLOW_CONFLICT,
            }:
                return False
            raise

    async def finalize_education_job(
        self, claim, *, status: str, error_code=None
    ) -> str:
        """Write a content-free terminal disposition only for the exact live lease."""
        self._require_enabled()
        from database_layer.school_research_education_jobs import (
            GENERAL_EDUCATION_POLICY_VERSION,
            ResearchEducationJobClaim,
            ResearchEducationJobErrorCode,
        )

        if status not in {"ABSTAINED", "REVIEW_REQUIRED", "CRISIS_ROUTED", "FAILED", "CANCELLED"}:
            raise ValueError("unsupported research education job disposition")
        if error_code is not None and not isinstance(error_code, ResearchEducationJobErrorCode):
            raise ValueError("research education job error code is invalid")
        if (
            type(claim) is not ResearchEducationJobClaim
            or claim.policy_version != GENERAL_EDUCATION_POLICY_VERSION
            or claim.response_origin != "PUBLIC_OBSERVED"
            or claim.school_id != self.school_id
            or claim.status != "LEASED"
            or claim.purpose != "RESEARCH_SIMULATION"
            or claim.research_only is not True
            or claim.publication_status != _PUBLICATION_STATUS
        ):
            raise error(ErrorCode.FORBIDDEN, detail="research education job scope is unavailable")
        now, _db_now = self._now()
        async with self._uow() as uow:
            current = True
            try:
                persisted, _task, _actor_scope, _session_ref, _scope, _retention = (
                    await self._live_claim_scope(uow, claim, now=now)
                )
            except BackendError as exc:
                if exc.code not in {
                    ErrorCode.FORBIDDEN,
                    ErrorCode.RESOURCE_NOT_FOUND,
                    ErrorCode.WORKFLOW_CONFLICT,
                }:
                    raise
                current = False
                persisted = await _repo_call(
                    uow.research_education_jobs.require_active_claim(
                        school_id=claim.school_id,
                        research_session_id=claim.research_session_id,
                        job_id=claim.id,
                        lease_owner=claim.lease_owner,
                        lease_token=claim.lease_token,
                        now=now,
                    )
                )
                if (
                    type(persisted) is not ResearchEducationJobClaim
                    or not self._same_claim_identity(persisted, claim)
                    or persisted.policy_version != GENERAL_EDUCATION_POLICY_VERSION
                    or persisted.response_origin != "PUBLIC_OBSERVED"
                    or persisted.purpose != "RESEARCH_SIMULATION"
                    or persisted.research_only is not True
                    or persisted.publication_status != _PUBLICATION_STATUS
                ):
                    raise _conflict() from None
            disposition = status if current else "CANCELLED"
            await _repo_call(
                uow.research_education_jobs.finish(
                    school_id=persisted.school_id,
                    research_session_id=persisted.research_session_id,
                    job_id=persisted.id,
                    lease_owner=persisted.lease_owner,
                    lease_token=persisted.lease_token,
                    status=disposition,
                    error_code=error_code if current else None,
                    now=now,
                )
            )
            return disposition

    async def store_generated_candidate(self, claim, payload, *, trace_id: str) -> dict:
        """Persist only a fully validated held candidate against its active job lease."""
        self._require_enabled()
        from database_layer.school_research_education_candidates import (
            ResearchEducationCandidateScope,
        )
        from database_layer.school_research_education_jobs import (
            GENERAL_EDUCATION_POLICY_VERSION,
            ResearchEducationJobClaim,
        )

        if type(claim) is not ResearchEducationJobClaim:
            raise error(
                ErrorCode.VALIDATION_FAILED,
                detail="research education job claim is invalid",
            )
        if (
            claim.policy_version != GENERAL_EDUCATION_POLICY_VERSION
            or claim.policy_hash != self.policy_hash
            or claim.response_origin != "PUBLIC_OBSERVED"
            or claim.school_id != self.school_id
            or claim.status != "LEASED"
            or not isinstance(trace_id, str)
            or not trace_id.startswith("TRACE_")
        ):
            raise error(ErrorCode.FORBIDDEN, detail="research education job scope is unavailable")
        payload = self._validate_new_payload(payload)
        now, _db_now = self._now()
        async with self._uow() as uow:
            persisted, _task, _actor_scope, _session_ref, scope, retention = (
                await self._live_claim_scope(uow, claim, now=now)
            )
            if payload.provenance.source_study_ref != self.source_study_ref:
                raise _conflict()
            encrypted = self.protection.encrypt_json(
                payload.model_dump(mode="json"),
                payload_schema_version=_PAYLOAD_SCHEMA,
            )
            candidate_ref = f"REEDUC_{uuid4().hex}"
            row = await _candidate_repo_call(
                uow.research_education_candidates.create_held(
                    claim=persisted,
                    scope=ResearchEducationCandidateScope(
                        research_session_id=scope.research_session_id,
                        school_id=scope.school_id,
                        task_id=scope.task_id,
                        class_id=scope.class_id,
                        task_enrollment_id=scope.task_enrollment_id,
                        subject_id=scope.subject_id,
                        task_binding_id=scope.task_binding_id,
                        profile_version_id=scope.profile_version_id,
                        profile_ref=scope.profile_ref,
                        profile_version_number=scope.profile_version_number,
                        profile_sha256=scope.profile_sha256,
                        response_origin=scope.response_origin,
                    ),
                    candidate_ref=candidate_ref,
                    study_ref=self.school_study_ref,
                    policy_version=_POLICY_VERSION,
                    policy_hash=self.policy_hash,
                    source_manifest_sha256=self.source_manifest_sha256,
                    retrieval_id=payload.provenance.retrieval_id,
                    retrieval_bundle_sha256=payload.provenance.retrieval_bundle_sha256,
                    prompt_ref=payload.provenance.prompt_id,
                    prompt_version=payload.provenance.prompt_version,
                    prompt_sha256=payload.provenance.prompt_sha256,
                    model_ref=payload.provenance.model_id,
                    model_digest_sha256=payload.provenance.model_digest_sha256,
                    runtime_version=payload.provenance.runtime_version,
                    safety_policy_version=payload.provenance.safety_policy_version,
                    input_safety_action=payload.provenance.input_safety_action,
                    retrieval_safety_action=payload.provenance.retrieval_safety_action,
                    output_safety_action=payload.provenance.output_safety_action,
                    content_sha256=self._payload_sha256(payload),
                    payload_ciphertext=encrypted.ciphertext,
                    cipher_format_version=encrypted.cipher_format_version,
                    key_version=encrypted.key_version,
                    payload_schema_version=encrypted.payload_schema_version,
                    trace_id=trace_id,
                    now=now,
                )
            )
            finished = await _repo_call(
                uow.research_education_jobs.finish(
                    school_id=persisted.school_id,
                    research_session_id=persisted.research_session_id,
                    job_id=persisted.id,
                    lease_owner=persisted.lease_owner,
                    lease_token=persisted.lease_token,
                    status="HELD",
                    now=now,
                )
            )
            if (
                finished.status != "HELD"
                or finished.research_session_id != row.scope.research_session_id
                or finished.policy_hash != row.policy_hash
            ):
                raise _conflict()
            await uow.audit.append(
                action="school_research_education_candidate.held",
                resource_type=_CANDIDATE_RESOURCE,
                resource_public_id=row.candidate_ref,
                result=self._db_enums.AuditResult.SUCCESS,
                trace_id=trace_id,
                safe_metadata={"source": _CANDIDATE_RESOURCE, "state": "HELD"},
            )
            return {
                "candidate_ref": row.candidate_ref,
                "status": row.status,
                "state_version": row.state_version,
                "purpose": row.purpose,
                "research_only": row.research_only,
                "psychological_interpretation_allowed": row.psychological_interpretation_allowed,
                "publication_status": row.publication_status,
                "student_feedback_eligible": False,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
