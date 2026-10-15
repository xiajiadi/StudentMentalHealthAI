"""Encrypted persistence and authorization for staff-only programme candidates."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import and_, or_

from smhai_backend.adapters.school_research_feedback import (
    SchoolResearchFeedbackPersistenceAdapter,
    _repo_call,
)
from smhai_backend.core.errors import BackendError, ErrorCode, error
from smhai_backend.domains.research_programme_generation.schemas import (
    CLAIM_BOUNDARY_VERSION,
)
from smhai_backend.domains.research_programme_generation.schemas import (
    STUDY_REF as SOURCE_STUDY_REF,
)
from smhai_backend.domains.school_research.study_use import ResearchStudyUsePolicy
from smhai_backend.domains.school_research_programme_candidates.schemas import (
    GeneratedProgrammeCandidate,
    ProgrammeCandidateContent,
)
from smhai_backend.integrations.research_programme import PROMPT_VERSION

RESEARCH_STAFF_PROGRAMME_POLICY_VERSION = "RESEARCH_STAFF_PROGRAMME_POLICY_V1"
_RESOURCE = "school_research_programme_candidate"
_JOB_RESOURCE = "school_research_programme_generation_job"
_BATCH_JOB_RESOURCE = "school_research_programme_generation_batch"
_CONTENT_SCHEMA = "school_research_programme_candidate.v2"
_LEGACY_CONTENT_SCHEMA = "school_research_programme_candidate.v1"
_PUBLICATION_STATUS = "not_approved_for_publication_or_operational_use"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _not_found():
    return error(ErrorCode.RESOURCE_NOT_FOUND, detail="research programme candidate was not found")


def _conflict():
    return error(ErrorCode.WORKFLOW_CONFLICT, detail="research programme candidate state changed")


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _naive_utc(value: datetime) -> datetime:
    return _aware_utc(value).replace(tzinfo=None)


def _finished_job_matches_candidate_scope(
    finished_job, generated: GeneratedProgrammeCandidate
) -> bool:
    scope = generated.task_scope
    return all(
        (
            finished_job.school_id == scope.school_id,
            finished_job.task_id == scope.task_id,
            finished_job.class_id == scope.class_id,
            finished_job.task_binding_id == scope.task_binding_id,
            finished_job.profile_version_id == scope.profile_version_id,
            finished_job.profile_ref == scope.profile_ref,
            finished_job.profile_version_number == scope.profile_version_number,
            finished_job.profile_sha256 == scope.profile_sha256,
            finished_job.response_origin == scope.response_origin,
            finished_job.policy_version == generated.job.policy_version,
            finished_job.policy_hash == generated.processor_policy_sha256,
        )
    )


def _job_lease_matches_persisted_claim(job, claim) -> bool:
    return all(
        (
            claim.id == job.job_id,
            claim.school_id == job.school_id,
            claim.research_session_id == job.research_session_id,
            claim.lease_owner == job.lease_owner,
            claim.lease_token == job.lease_token,
            claim.policy_version == job.policy_version,
            claim.policy_hash == job.policy_hash,
        )
    )


def _task_scope_matches_persisted_claim(scope, claim) -> bool:
    return all(
        (
            scope.school_id == claim.school_id,
            scope.task_id == claim.task_id,
            scope.class_id == claim.class_id,
            scope.task_binding_id == claim.task_binding_id,
            scope.profile_version_id == claim.profile_version_id,
            scope.profile_ref == claim.profile_ref,
            scope.profile_version_number == claim.profile_version_number,
            scope.profile_sha256 == claim.profile_sha256,
            scope.response_origin == claim.response_origin,
        )
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
    from database_layer.school_research_programme_candidates import (
        ResearchProgrammeCandidateError,
    )

    try:
        return await awaitable
    except (OptimisticConcurrencyConflict, UniqueConflict):
        raise _conflict() from None
    except (ForeignKeyConflict, NotFound):
        raise _not_found() from None
    except ResearchProgrammeCandidateError as exc:
        if exc.code in {"INVALID_INPUT", "INVALID_ENCRYPTED_PAYLOAD", "INVALID_SCOPE"}:
            raise error(
                ErrorCode.VALIDATION_FAILED,
                detail="research programme candidate input is invalid",
            ) from None
        raise _conflict() from None
    except (DatabaseUnavailable, EncryptionKeyUnavailable):
        raise error(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            detail="research programme candidate storage is unavailable",
            retryable=True,
        ) from None


class SchoolResearchProgrammeCandidatePersistenceAdapter(SchoolResearchFeedbackPersistenceAdapter):
    """Reuse task-specialist auth and study-policy checks without student scope."""

    def __init__(
        self,
        persistence,
        *,
        study_use_policy: ResearchStudyUsePolicy | None,
        study_use_policy_sha256: str | None,
        enabled: bool,
        expected_source_manifest_sha256: str | None = None,
        expected_processor_policy_sha256: str | None = None,
        expected_model_ref: str | None = None,
        expected_model_digest_sha256: str | None = None,
        expected_prompt_ref: str | None = None,
        expected_prompt_version: str | None = None,
    ) -> None:
        super().__init__(persistence, study_use_policy=study_use_policy)
        if (
            expected_source_manifest_sha256 is not None
            and (
                not isinstance(expected_source_manifest_sha256, str)
                or _SHA256.fullmatch(expected_source_manifest_sha256) is None
            )
        ):
            raise ValueError("trusted research source manifest pin is invalid")
        generation_pins = (
            expected_model_ref,
            expected_model_digest_sha256,
            expected_prompt_ref,
            expected_prompt_version,
        )
        if any(value is not None for value in generation_pins) and not all(
            isinstance(value, str) and value for value in generation_pins
        ):
            raise ValueError("trusted research generation pins must be provided together")
        if (
            expected_model_digest_sha256 is not None
            and _SHA256.fullmatch(expected_model_digest_sha256) is None
        ):
            raise ValueError("trusted research model digest pin is invalid")
        self.study_use_policy_sha256 = study_use_policy_sha256
        self.expected_source_manifest_sha256 = expected_source_manifest_sha256
        if (
            expected_processor_policy_sha256 is not None
            and _SHA256.fullmatch(expected_processor_policy_sha256) is None
        ):
            raise ValueError("trusted research processor policy pin is invalid")
        self.expected_processor_policy_sha256 = expected_processor_policy_sha256
        self.expected_model_ref = expected_model_ref
        self.expected_model_digest_sha256 = expected_model_digest_sha256
        self.expected_prompt_ref = expected_prompt_ref
        self.expected_prompt_version = expected_prompt_version
        self.enabled = enabled is True
        self.generation_enabled = False

    def configure_generation(self, *, enabled: bool, processor_policy_sha256: str | None) -> None:
        if type(enabled) is not bool:
            raise TypeError("research programme generation enablement must be boolean")
        if enabled and (
            processor_policy_sha256 is None
            or processor_policy_sha256 != self.expected_processor_policy_sha256
        ):
            raise ValueError("research programme processor policy pin is unavailable")
        self.generation_enabled = enabled

    def _require_enabled(self) -> None:
        if (
            not self.enabled
            or type(self.study_use_policy) is not ResearchStudyUsePolicy
            or self.study_use_policy.source_rights_verified is not True
            or not isinstance(self.study_use_policy_sha256, str)
            or len(self.study_use_policy_sha256) != 64
            or any(char not in "0123456789abcdef" for char in self.study_use_policy_sha256)
        ):
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="research programme candidate policy is unavailable",
                retryable=True,
            )

    def _summary(self, row):
        if (
            row.purpose != "RESEARCH_SIMULATION"
            or row.research_only is not True
            or row.psychological_interpretation_allowed is not False
            or row.publication_status != _PUBLICATION_STATUS
            or row.output_boundary != "STAFF_REFERENCE_ONLY"
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research programme candidate is unavailable",
            )
        return {
            "candidate_ref": row.candidate_ref,
            "programme_ref": row.programme_ref,
            "status": row.status,
            "state_version": row.state_version,
            "student_feedback_eligible": False,
            "output_boundary": row.output_boundary,
            "created_at": row.created_at,
        }

    def _require_source_manifest_pin(self, actual_sha256: str) -> None:
        expected = self.expected_source_manifest_sha256
        if expected is None:
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="research programme source manifest pin is unavailable",
                retryable=True,
            )
        if not isinstance(actual_sha256, str) or _SHA256.fullmatch(actual_sha256) is None:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research programme source manifest is invalid",
            )
        if actual_sha256 != expected:
            raise _conflict()

    def _require_generation_pins(self, generated: GeneratedProgrammeCandidate) -> None:
        if (
            generated.source_study_ref != SOURCE_STUDY_REF
            or generated.claim_boundary_version != CLAIM_BOUNDARY_VERSION
        ):
            raise error(
                ErrorCode.FORBIDDEN,
                detail="research programme study references are unavailable",
            )
        if any(
            value is None
            for value in (
                self.expected_model_ref,
                self.expected_model_digest_sha256,
                self.expected_prompt_ref,
                self.expected_prompt_version,
            )
        ):
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="research programme generation pins are unavailable",
                retryable=True,
            )
        if (
            generated.model_ref != self.expected_model_ref
            or generated.model_digest_sha256 != self.expected_model_digest_sha256
            or generated.prompt_ref != self.expected_prompt_ref
            or generated.prompt_version != self.expected_prompt_version
        ):
            raise error(
                ErrorCode.FORBIDDEN,
                detail="research programme generation pins are unavailable",
            )
        if generated.processor_policy_sha256 != self.expected_processor_policy_sha256:
            raise error(
                ErrorCode.FORBIDDEN,
                detail="research programme processor policy pin is unavailable",
            )

    def _require_generation_enabled(self) -> None:
        self._require_enabled()
        if (
            self.generation_enabled is not True
            or self.expected_processor_policy_sha256 is None
            or any(
                value is None
                for value in (
                    self.expected_source_manifest_sha256,
                    self.expected_model_ref,
                    self.expected_model_digest_sha256,
                    self.expected_prompt_ref,
                    self.expected_prompt_version,
                )
            )
        ):
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="research programme generation policy is unavailable",
                retryable=True,
            )

    async def _policy_binding_pin(
        self, *, uow, school_id: int, task_id: int, at: datetime, task=None
    ):
        self._require_enabled()
        from database_layer.models import MeasurementTask, School, SchoolResearchCohort

        if task is None:
            task = await uow.session.scalar(
                self._select(MeasurementTask)
                .join(School, School.id == MeasurementTask.school_id)
                .where(
                    MeasurementTask.id == task_id,
                    MeasurementTask.school_id == school_id,
                    MeasurementTask.status.in_(("PUBLISHED", "CLOSED")),
                    MeasurementTask.cat_binding_mode == "RESEARCH_PROFILE",
                    School.status == "ACTIVE",
                    School.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                )
                .with_for_update()
            )
        if task is None:
            raise _not_found()
        binding = await uow.research_cat.get_task_binding_metadata(
            school_id=school_id, task_id=task_id
        )
        profile = await uow.research_cat.get_profile_metadata(
            school_id=school_id,
            profile_ref=binding.profile_ref,
            version_number=binding.profile_version_number,
        )
        pin = self._policy_pin(profile=profile, binding=binding, task=task, at=at)
        policy = self.study_use_policy
        if binding.cohort_id is not None:
            cohort_study_ref = await uow.session.scalar(
                self._select(SchoolResearchCohort.study_ref).where(
                    SchoolResearchCohort.id == binding.cohort_id,
                    SchoolResearchCohort.school_id == school_id,
                )
            )
            if cohort_study_ref != policy.study_ref:
                raise error(ErrorCode.FORBIDDEN, detail="research study scope is unavailable")
        return task, binding, profile, pin

    def _require_candidate_current(self, row, *, binding, pin):
        self._require_source_manifest_pin(row.source_manifest_sha256)
        scope = row.scope
        if (
            row.study_ref != self.study_use_policy.study_ref
            or row.study_policy_sha256 != self.study_use_policy_sha256
            or scope.school_id != binding.school_id
            or scope.task_id != binding.task_id
            or scope.class_id != binding.class_id
            or scope.task_binding_id != binding.binding_id
            or scope.profile_version_id != binding.profile_version_id
            or scope.profile_ref != binding.profile_ref
            or scope.profile_version_number != binding.profile_version_number
            or scope.profile_sha256 != binding.profile_sha256
            or scope.response_origin != binding.response_origin
            or pin.profile_ref != scope.profile_ref
            or pin.profile_sha256 != scope.profile_sha256
        ):
            raise _conflict()

    async def _active_task_for_actor(
        self, uow, actor, task_ref: str, *, role_id: int, at: datetime
    ):
        task = await self._task(uow, actor, task_ref, lock=True)
        assignment = await self._active_assignment(uow, actor, task, at=at, lock=True)
        if assignment.specialist_membership_role_id != role_id:
            raise _not_found()
        _, binding, profile, pin = await self._policy_binding_pin(
            uow=uow, school_id=actor.school_id, task_id=task.id, at=at, task=task
        )
        return task, binding, profile, pin

    def _decrypt_content(self, row) -> dict:
        from database_layer.crypto import EncryptedPayload

        try:
            value = self.protection.decrypt_json(
                EncryptedPayload(
                    ciphertext=row.payload_ciphertext,
                    cipher_format_version=row.cipher_format_version,
                    key_version=row.key_version,
                    payload_schema_version=row.payload_schema_version,
                )
            )
            base_fields = {"candidate_ref", "programme_ref", "content_revision", "content"}
            fields = set(value) if isinstance(value, dict) else set()
            if fields != base_fields and fields != base_fields | {"source_study_ref"}:
                raise ValueError
            if (
                value["candidate_ref"] != row.candidate_ref
                or value["programme_ref"] != row.programme_ref
                or value["content_revision"] != 1
                or (
                    "source_study_ref" in value
                    and value["source_study_ref"] != SOURCE_STUDY_REF
                )
                or (
                    "source_study_ref" not in value
                    and row.study_ref != SOURCE_STUDY_REF
                )
            ):
                raise ValueError
            content_value = value["content"]
            if not isinstance(content_value, dict):
                raise ValueError
            origin_fields = {"content_origin", "generation_mode"}
            supplied_origin_fields = origin_fields.intersection(content_value)
            if supplied_origin_fields and supplied_origin_fields != origin_fields:
                raise ValueError
            has_origin_fields = supplied_origin_fields == origin_fields
            if row.payload_schema_version == _CONTENT_SCHEMA:
                if row.prompt_version != PROMPT_VERSION or not has_origin_fields:
                    raise ValueError
            elif row.payload_schema_version == _LEGACY_CONTENT_SCHEMA:
                if row.prompt_version == PROMPT_VERSION or has_origin_fields:
                    raise ValueError
            else:
                raise ValueError
            if not has_origin_fields:
                content_value = {
                    **content_value,
                    "content_origin": "LEGACY_MODEL_TEXT",
                    "generation_mode": "LEGACY_MODEL_AUTHORED_PASSAGES",
                }
            content = ProgrammeCandidateContent.model_validate(content_value, strict=True)
            if has_origin_fields and (
                content.content_origin != "VERIFIED_SOURCE_METADATA"
                or content.generation_mode != "MODEL_SOURCE_SELECTION"
            ):
                raise ValueError
            if content.programme_ref != row.programme_ref:
                raise ValueError
            return content.model_dump(mode="python")
        except Exception:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research programme candidate content is unavailable",
            ) from None

    def _detail(self, row):
        self._require_source_manifest_pin(row.source_manifest_sha256)
        return {
            **self._summary(row),
            "purpose": row.purpose,
            "research_only": row.research_only,
            "psychological_interpretation_allowed": row.psychological_interpretation_allowed,
            "publication_status": row.publication_status,
            "output_boundary": row.output_boundary,
            "content": self._decrypt_content(row),
        }

    async def store_generated_candidate(self, generated: GeneratedProgrammeCandidate) -> dict:
        """Internal processor write; claims the worker lease and stores no student payload."""
        self._require_generation_enabled()
        if type(generated) is not GeneratedProgrammeCandidate:
            raise error(ErrorCode.VALIDATION_FAILED, detail="generated candidate is invalid")
        self._require_source_manifest_pin(generated.source_manifest_sha256)
        self._require_generation_pins(generated)
        job = generated.job
        scope = generated.task_scope
        if (
            job.policy_version != RESEARCH_STAFF_PROGRAMME_POLICY_VERSION
            or job.policy_hash != generated.processor_policy_sha256
            or job.school_id != scope.school_id
        ):
            raise error(
                ErrorCode.FORBIDDEN,
                detail="research programme generation scope is unavailable",
            )
        now = _aware_utc(self._utc_now())
        async with self._uow() as uow:
            from database_layer.school_research_education_jobs import (
                ResearchEducationJobClaim,
            )

            persisted_claim = await _repo_call(
                uow.research_education_jobs.require_active_claim(
                    school_id=job.school_id,
                    research_session_id=job.research_session_id,
                    job_id=job.job_id,
                    lease_owner=job.lease_owner,
                    lease_token=job.lease_token,
                    now=now,
                )
            )
            if (
                type(persisted_claim) is not ResearchEducationJobClaim
                or not _job_lease_matches_persisted_claim(job, persisted_claim)
                or persisted_claim.policy_hash != generated.processor_policy_sha256
            ):
                raise _conflict()
            task, binding, _profile, pin = await self._live_generation_scope(
                uow, persisted_claim, at=now
            )
            if (
                not _task_scope_matches_persisted_claim(scope, persisted_claim)
                or task.id != scope.task_id
                or task.class_id != scope.class_id
                or binding.binding_id != scope.task_binding_id
                or binding.profile_version_id != scope.profile_version_id
                or binding.profile_ref != scope.profile_ref
                or binding.profile_version_number != scope.profile_version_number
                or binding.profile_sha256 != scope.profile_sha256
                or binding.response_origin != scope.response_origin
                or generated.study_ref != self.study_use_policy.study_ref
                or generated.study_policy_sha256 != self.study_use_policy_sha256
                or generated.processor_policy_sha256 != job.policy_hash
                or pin.profile_ref != scope.profile_ref
                or pin.profile_sha256 != scope.profile_sha256
            ):
                raise _conflict()
            row_scope = self._candidate_scope(scope)
            candidate_ref = f"RPCAND_{uuid4().hex}"
            encrypted = self.protection.encrypt_json(
                {
                    "candidate_ref": candidate_ref,
                    "programme_ref": generated.programme_ref,
                    "source_study_ref": generated.source_study_ref,
                    "content_revision": 1,
                    "content": generated.content.model_dump(mode="json"),
                },
                payload_schema_version=_CONTENT_SCHEMA,
            )
            dto = await _candidate_repo_call(uow.research_programme_candidates.create_held(
                scope=row_scope,
                candidate_ref=candidate_ref,
                study_ref=generated.study_ref,
                study_policy_sha256=generated.study_policy_sha256,
                processor_policy_sha256=generated.processor_policy_sha256,
                programme_ref=generated.programme_ref,
                source_manifest_sha256=generated.source_manifest_sha256,
                source_set_sha256=generated.source_set_sha256,
                retrieval_id=generated.retrieval_id,
                retrieval_bundle_sha256=generated.retrieval_bundle_sha256,
                chunk_set_sha256=generated.chunk_set_sha256,
                prompt_ref=generated.prompt_ref,
                prompt_version=generated.prompt_version,
                prompt_sha256=generated.prompt_sha256,
                model_ref=generated.model_ref,
                model_digest_sha256=generated.model_digest_sha256,
                runtime_version=generated.runtime_version,
                safety_policy_version=generated.safety_policy_version,
                input_safety_action=generated.input_safety_action,
                retrieval_safety_action=generated.retrieval_safety_action,
                output_safety_action=generated.output_safety_action,
                claim_boundary_version=generated.claim_boundary_version,
                claim_boundary_status=generated.claim_boundary_status,
                payload_ciphertext=encrypted.ciphertext,
                cipher_format_version=encrypted.cipher_format_version,
                key_version=encrypted.key_version,
                payload_schema_version=encrypted.payload_schema_version,
                now=now,
            ))
            finished_job = await _repo_call(
                uow.research_education_jobs.finish(
                    school_id=job.school_id,
                    research_session_id=job.research_session_id,
                    job_id=job.job_id,
                    lease_owner=job.lease_owner,
                    lease_token=job.lease_token,
                    status="HELD",
                    now=now,
                )
            )
            if not _finished_job_matches_candidate_scope(finished_job, generated):
                raise _conflict()
            await uow.audit.append(
                action="school_research_programme_candidate.generated",
                resource_type=_RESOURCE,
                resource_public_id=dto.candidate_ref,
                result=self._db_enums.AuditResult.SUCCESS,
                trace_id=generated.trace_id,
                safe_metadata={"source": _RESOURCE, "state": "HELD"},
            )
            return self._summary(dto)

    async def school_research_programme_generation_queue(
        self, actor, task_ref: str, *, idempotency, trace_id: str
    ) -> dict:
        """Queue one server-selected completed PUBLIC_OBSERVED session."""
        self._require_generation_enabled()
        from database_layer.school_research_education_jobs import (
            STAFF_PROGRAMME_POLICY_VERSION,
        )

        now, db_now = self._now()
        async with self._uow() as uow:
            actor_account_id, role_id = await self._require_actor(
                uow, actor, "psychological_specialist", db_now
            )
            task, binding, _profile, _pin = await self._active_task_for_actor(
                uow, actor, task_ref, role_id=role_id, at=now
            )
            idem_claim = await self._school_idempotency_begin(uow, idempotency)
            m = self._db_models
            session_ref = await uow.session.scalar(
                self._select(m.SchoolResearchSession.session_ref)
                .where(
                    m.SchoolResearchSession.school_id == actor.school_id,
                    m.SchoolResearchSession.task_id == task.id,
                    m.SchoolResearchSession.class_id == task.class_id,
                    m.SchoolResearchSession.task_binding_id == binding.binding_id,
                    m.SchoolResearchSession.profile_version_id == binding.profile_version_id,
                    m.SchoolResearchSession.profile_ref == binding.profile_ref,
                    m.SchoolResearchSession.profile_version_number
                    == binding.profile_version_number,
                    m.SchoolResearchSession.profile_sha256 == binding.profile_sha256,
                    m.SchoolResearchSession.response_origin == "PUBLIC_OBSERVED",
                    m.SchoolResearchSession.status == "COMPLETED",
                    m.SchoolResearchSession.completed_at.is_not(None),
                    m.SchoolResearchSession.purpose == "RESEARCH_SIMULATION",
                    m.SchoolResearchSession.research_only.is_(True),
                )
                .order_by(m.SchoolResearchSession.completed_at, m.SchoolResearchSession.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if session_ref is None:
                raise _not_found()
            scope, _metadata, _retention, _profile, _pin = await self._current_scope(
                uow, actor, task, session_ref=session_ref, at=now, lock=True
            )
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
                    policy_version=STAFF_PROGRAMME_POLICY_VERSION,
                    policy_hash=self.expected_processor_policy_sha256,
                    now=now,
                )
            )
            if idem_claim.replayed:
                receipt = await self._receipt_resource(idem_claim, _JOB_RESOURCE)
                if receipt != job.job_ref:
                    raise _conflict()
            else:
                await self._audit_research(
                    uow,
                    actor_account_id=actor_account_id,
                    action="school_research_programme_generation.queued",
                    resource_type=_JOB_RESOURCE,
                    resource_ref=job.job_ref,
                    trace_id=trace_id,
                    state=job.status,
                )
                await self._school_idempotency_complete(
                    uow,
                    idem_claim,
                    resource_type=_JOB_RESOURCE,
                    result_ref=job.job_ref,
                )
            return {
                "job_ref": job.job_ref,
                "status": job.status,
                "policy_version": job.policy_version,
                "purpose": job.purpose,
                "research_only": job.research_only,
                "publication_status": job.publication_status,
                "student_feedback_eligible": False,
            }

    async def school_research_programme_generation_queue_batch(
        self,
        actor,
        task_ref: str,
        *,
        limit: int,
        after_job_ref: str | None,
        idempotency,
        trace_id: str,
    ) -> dict:
        """Atomically queue a bounded page of individually authorized sessions."""
        self._require_generation_enabled()
        from database_layer.school_research_education_jobs import (
            STAFF_PROGRAMME_POLICY_VERSION,
        )

        if type(limit) is not int or not 1 <= limit <= 100:
            raise error(ErrorCode.VALIDATION_FAILED, detail="batch limit is invalid")
        if after_job_ref is not None and (
            type(after_job_ref) is not str
            or re.fullmatch(r"REJ_[0-9a-f]{64}", after_job_ref) is None
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="batch cursor is invalid")

        now, db_now = self._now()
        async with self._uow() as uow:
            actor_account_id, role_id = await self._require_actor(
                uow, actor, "psychological_specialist", db_now
            )
            task, binding, _profile, _pin = await self._active_task_for_actor(
                uow, actor, task_ref, role_id=role_id, at=now
            )
            idem_claim = await self._school_idempotency_begin(uow, idempotency)
            m = self._db_models
            session = m.SchoolResearchSession
            cursor_marker = None
            if after_job_ref is not None:
                cursor_query = (
                    self._select(
                        session.session_ref.label("session_ref"),
                        session.completed_at.label("completed_at"),
                        session.id.label("session_id"),
                    )
                    .join(
                        m.SchoolResearchEducationJob,
                        (m.SchoolResearchEducationJob.research_session_id == session.id)
                        & (m.SchoolResearchEducationJob.school_id == session.school_id),
                    )
                    .where(
                        m.SchoolResearchEducationJob.job_ref == after_job_ref,
                        m.SchoolResearchEducationJob.school_id == actor.school_id,
                        m.SchoolResearchEducationJob.task_id == task.id,
                        m.SchoolResearchEducationJob.class_id == task.class_id,
                        m.SchoolResearchEducationJob.task_binding_id == binding.binding_id,
                        m.SchoolResearchEducationJob.profile_version_id
                        == binding.profile_version_id,
                        m.SchoolResearchEducationJob.profile_ref == binding.profile_ref,
                        m.SchoolResearchEducationJob.profile_version_number
                        == binding.profile_version_number,
                        m.SchoolResearchEducationJob.profile_sha256 == binding.profile_sha256,
                        m.SchoolResearchEducationJob.response_origin == "PUBLIC_OBSERVED",
                        m.SchoolResearchEducationJob.job_kind == "EDUCATION_SUPPORT",
                        m.SchoolResearchEducationJob.policy_version
                        == STAFF_PROGRAMME_POLICY_VERSION,
                        m.SchoolResearchEducationJob.policy_hash
                        == self.expected_processor_policy_sha256,
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
                    )
                    .with_for_update()
                )
                cursor_result = await uow.session.execute(cursor_query)
                cursor_row = cursor_result.first()
                if cursor_row is None:
                    raise _not_found()
                cursor_mapping = cursor_row._mapping
                cursor_ref = cursor_mapping["session_ref"]
                cursor_marker = (
                    cursor_mapping["completed_at"],
                    cursor_mapping["session_id"],
                )
                await self._current_scope(
                    uow, actor, task, session_ref=cursor_ref, at=now, lock=True
                )

            selection = self._select(
                session.session_ref.label("session_ref"),
                session.completed_at.label("completed_at"),
                session.id.label("session_id"),
            ).where(
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
            )
            if cursor_marker is not None:
                selection = selection.where(
                    or_(
                        session.completed_at > cursor_marker[0],
                        and_(
                            session.completed_at == cursor_marker[0],
                            session.id > cursor_marker[1],
                        ),
                    )
                )
            selected = await uow.session.execute(
                selection.order_by(session.completed_at, session.id)
                .limit(limit)
                .with_for_update()
            )
            rows = selected.all()

            jobs = []
            for row in rows:
                session_ref = row._mapping["session_ref"]
                scope, _metadata, _retention, _profile, _pin = await self._current_scope(
                    uow, actor, task, session_ref=session_ref, at=now, lock=True
                )
                jobs.append(
                    await _repo_call(
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
                            policy_version=STAFF_PROGRAMME_POLICY_VERSION,
                            policy_hash=self.expected_processor_policy_sha256,
                            now=now,
                        )
                    )
                )

            job_refs = [job.job_ref for job in jobs]
            next_cursor = job_refs[-1] if len(job_refs) == limit else None
            request_fingerprint = (
                f"{actor.school_id}:{task.id}:{binding.binding_id}:{limit}:"
                f"{after_job_ref or 'FIRST'}:{self.expected_processor_policy_sha256}:"
                + ":".join(job_refs)
            )
            batch_ref = "REJBATCH_" + hashlib.sha256(
                request_fingerprint.encode("ascii")
            ).hexdigest()
            if idem_claim.replayed:
                receipt = await self._receipt_resource(idem_claim, _BATCH_JOB_RESOURCE)
                if receipt != batch_ref:
                    # The idempotency row stores one batch digest, not membership data.
                    # Fail closed if the same page no longer resolves identically.
                    raise _conflict()
            else:
                for job in jobs:
                    await self._audit_research(
                        uow,
                        actor_account_id=actor_account_id,
                        action="school_research_programme_generation.queued",
                        resource_type=_JOB_RESOURCE,
                        resource_ref=job.job_ref,
                        trace_id=trace_id,
                        state=job.status,
                    )
                await self._school_idempotency_complete(
                    uow,
                    idem_claim,
                    resource_type=_BATCH_JOB_RESOURCE,
                    result_ref=batch_ref,
                )

            return {
                "batch_ref": batch_ref,
                "job_refs": job_refs,
                "job_count": len(job_refs),
                "next_cursor": next_cursor,
                "policy_version": STAFF_PROGRAMME_POLICY_VERSION,
                "purpose": "RESEARCH_SIMULATION",
                "research_only": True,
                "publication_status": _PUBLICATION_STATUS,
                "student_feedback_eligible": False,
            }

    async def authorize_programme_claim(self, claim) -> bool:
        self._require_generation_enabled()
        now, _db_now = self._now()
        try:
            async with self._uow() as uow:
                await self._live_generation_scope(uow, claim, at=now)
            return True
        except BackendError as exc:
            if exc.code in {
                ErrorCode.FORBIDDEN,
                ErrorCode.RESOURCE_NOT_FOUND,
                ErrorCode.WORKFLOW_CONFLICT,
            }:
                return False
            raise

    async def finalize_programme_job(self, claim, *, status: str, error_code=None) -> str:
        self._require_generation_enabled()
        from database_layer.school_research_education_jobs import (
            ResearchEducationJobErrorCode,
        )

        now, _db_now = self._now()
        if status not in {"ABSTAINED", "REVIEW_REQUIRED", "CRISIS_ROUTED", "FAILED"}:
            raise ValueError("unsupported staff programme disposition")
        if error_code is not None and not isinstance(error_code, ResearchEducationJobErrorCode):
            raise ValueError("staff programme disposition code is invalid")
        async with self._uow() as uow:
            current = True
            try:
                await self._live_generation_scope(uow, claim, at=now)
            except BackendError as exc:
                if exc.code not in {
                    ErrorCode.FORBIDDEN,
                    ErrorCode.RESOURCE_NOT_FOUND,
                    ErrorCode.WORKFLOW_CONFLICT,
                }:
                    raise
                current = False
            await _repo_call(
                uow.research_education_jobs.finish(
                    school_id=claim.school_id,
                    research_session_id=claim.research_session_id,
                    job_id=claim.id,
                    lease_owner=claim.lease_owner,
                    lease_token=claim.lease_token,
                    status=status if current else "CANCELLED",
                    error_code=error_code if current else None,
                    now=now,
                )
            )
            return status if current else "CANCELLED"

    async def retry_programme_job(self, claim, *, error_code) -> None:
        self._require_generation_enabled()
        await _repo_call(
            self._repo_retry(
                claim,
                error_code=error_code,
            )
        )

    async def _repo_retry(self, claim, *, error_code):
        from database_layer.school_research_education_jobs import (
            ResearchEducationJobErrorCode,
        )

        if not isinstance(error_code, ResearchEducationJobErrorCode):
            raise ValueError("staff programme retry code is invalid")
        now, _db_now = self._now()
        async with self._uow() as uow:
            return await uow.research_education_jobs.retry(
                school_id=claim.school_id,
                research_session_id=claim.research_session_id,
                job_id=claim.id,
                lease_owner=claim.lease_owner,
                lease_token=claim.lease_token,
                error_code=error_code,
                now=now,
            )

    async def _live_generation_scope(self, uow, claim, *, at):
        from types import SimpleNamespace

        from database_layer.school_research_education_jobs import (
            STAFF_PROGRAMME_POLICY_VERSION,
        )

        if (
            claim.policy_version != STAFF_PROGRAMME_POLICY_VERSION
            or claim.policy_hash != self.expected_processor_policy_sha256
            or claim.response_origin != "PUBLIC_OBSERVED"
            or claim.school_id <= 0
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
                m.SchoolTaskSpecialistAssignment.school_id == claim.school_id,
                m.SchoolTaskSpecialistAssignment.task_id == claim.task_id,
                m.SchoolTaskSpecialistAssignment.class_id == claim.class_id,
                m.SchoolTaskSpecialistAssignment.status == "ACTIVE",
                m.SchoolTaskSpecialistAssignment.revoked_at.is_(None),
                m.MembershipRole.school_id == claim.school_id,
                m.MembershipRole.role_code == "psychological_specialist",
                m.MembershipRole.status == "ACTIVE",
                m.MembershipRole.revoked_at.is_(None),
                m.MembershipRole.valid_from <= _naive_utc(at),
                (m.MembershipRole.valid_until.is_(None))
                | (m.MembershipRole.valid_until >= _naive_utc(at)),
                m.AccountSchoolMembership.school_id == claim.school_id,
                m.AccountSchoolMembership.status == "ACTIVE",
                m.AccountSchoolMembership.revoked_at.is_(None),
                m.AccountSchoolMembership.valid_from <= _naive_utc(at),
                (m.AccountSchoolMembership.valid_until.is_(None))
                | (m.AccountSchoolMembership.valid_until >= _naive_utc(at)),
                m.Account.status == self._db_enums.AccountStatus.ACTIVE.value,
            )
            .limit(1)
        )
        if assignment_id is None:
            raise _not_found()
        _task, binding, profile, pin = await self._policy_binding_pin(
            uow=uow,
            school_id=claim.school_id,
            task_id=claim.task_id,
            at=at,
            task=task,
        )
        session_ref = await uow.session.scalar(
            self._select(m.SchoolResearchSession.session_ref).where(
                m.SchoolResearchSession.id == claim.research_session_id,
                m.SchoolResearchSession.school_id == claim.school_id,
                m.SchoolResearchSession.task_id == claim.task_id,
                m.SchoolResearchSession.class_id == claim.class_id,
                m.SchoolResearchSession.task_enrollment_id == claim.task_enrollment_id,
                m.SchoolResearchSession.subject_id == claim.subject_id,
                m.SchoolResearchSession.task_binding_id == claim.task_binding_id,
                m.SchoolResearchSession.profile_version_id == claim.profile_version_id,
                m.SchoolResearchSession.profile_ref == claim.profile_ref,
                m.SchoolResearchSession.profile_version_number == claim.profile_version_number,
                m.SchoolResearchSession.profile_sha256 == claim.profile_sha256,
                m.SchoolResearchSession.response_origin == claim.response_origin,
                m.SchoolResearchSession.status == "COMPLETED",
                m.SchoolResearchSession.completed_at.is_not(None),
                m.SchoolResearchSession.purpose == "RESEARCH_SIMULATION",
                m.SchoolResearchSession.research_only.is_(True),
            )
            .limit(1)
        )
        if session_ref is None:
            raise _not_found()
        task_actor = SimpleNamespace(school_id=claim.school_id)
        scope, metadata, _retention, _profile, fresh_pin = await self._current_scope(
            uow, task_actor, task, session_ref=session_ref, at=at, lock=False
        )
        if (
            metadata.response_origin != "PUBLIC_OBSERVED"
            or metadata.completed_at is None
            or _aware_utc(metadata.completed_at) > _aware_utc(at)
            or fresh_pin != pin
            or scope.research_session_id != claim.research_session_id
            or scope.school_id != claim.school_id
            or scope.task_id != claim.task_id
            or scope.class_id != claim.class_id
            or scope.task_enrollment_id != claim.task_enrollment_id
            or scope.subject_id != claim.subject_id
            or scope.task_binding_id != claim.task_binding_id
            or scope.profile_version_id != claim.profile_version_id
            or scope.profile_ref != claim.profile_ref
            or scope.profile_version_number != claim.profile_version_number
            or scope.profile_sha256 != claim.profile_sha256
            or scope.response_origin != claim.response_origin
        ):
            raise _conflict()
        return task, binding, profile, pin

    @staticmethod
    def _candidate_scope(scope):
        from database_layer.school_research_programme_candidates import (
            ResearchProgrammeCandidateScope,
        )

        return ResearchProgrammeCandidateScope(
            school_id=scope.school_id,
            task_id=scope.task_id,
            class_id=scope.class_id,
            task_binding_id=scope.task_binding_id,
            profile_version_id=scope.profile_version_id,
            profile_ref=scope.profile_ref,
            profile_version_number=scope.profile_version_number,
            profile_sha256=scope.profile_sha256,
            response_origin=scope.response_origin,
        )

    async def school_research_programme_candidate_list(
        self, actor, task_ref: str, *, offset: int, limit: int
    ) -> list[dict]:
        self._require_enabled()
        now, db_now = self._now()
        async with self._uow() as uow:
            _, role_id = await self._require_actor(uow, actor, "psychological_specialist", db_now)
            task, binding, _profile, pin = await self._active_task_for_actor(
                uow, actor, task_ref, role_id=role_id, at=now
            )
            rows = await uow.research_programme_candidates.list_for_task(
                school_id=actor.school_id,
                task_id=task.id,
                status="HELD",
                limit=limit,
                offset=offset,
            )
            for row in rows:
                self._require_candidate_current(row, binding=binding, pin=pin)
            return [self._summary(row) for row in rows]

    async def school_research_programme_candidate_get(
        self, actor, task_ref: str, candidate_ref: str
    ) -> dict:
        self._require_enabled()
        now, db_now = self._now()
        async with self._uow() as uow:
            _, role_id = await self._require_actor(uow, actor, "psychological_specialist", db_now)
            task, binding, _profile, pin = await self._active_task_for_actor(
                uow, actor, task_ref, role_id=role_id, at=now
            )
            row = await uow.research_programme_candidates.get(
                school_id=actor.school_id,
                task_id=task.id,
                candidate_ref=candidate_ref,
            )
            if row is None:
                raise _not_found()
            self._require_candidate_current(row, binding=binding, pin=pin)
            return self._detail(row)

    async def school_research_programme_candidate_adopt(
        self,
        actor,
        task_ref: str,
        candidate_ref: str,
        *,
        expected_state_version: int,
        idempotency,
        trace_id: str,
    ) -> dict:
        return await self._resolve_candidate(
            actor,
            task_ref,
            candidate_ref,
            expected_state_version=expected_state_version,
            target="ADOPTED",
            idempotency=idempotency,
            trace_id=trace_id,
        )

    async def school_research_programme_candidate_discard(
        self,
        actor,
        task_ref: str,
        candidate_ref: str,
        *,
        expected_state_version: int,
        idempotency,
        trace_id: str,
    ) -> dict:
        return await self._resolve_candidate(
            actor,
            task_ref,
            candidate_ref,
            expected_state_version=expected_state_version,
            target="DISCARDED",
            idempotency=idempotency,
            trace_id=trace_id,
        )

    async def _resolve_candidate(
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
        now, db_now = self._now()
        async with self._uow() as uow:
            actor_account_id, role_id = await self._require_actor(
                uow, actor, "psychological_specialist", db_now
            )
            task, binding, _profile, pin = await self._active_task_for_actor(
                uow, actor, task_ref, role_id=role_id, at=now
            )
            row = await uow.research_programme_candidates.get(
                school_id=actor.school_id,
                task_id=task.id,
                candidate_ref=candidate_ref,
                lock=True,
            )
            if row is None:
                raise _not_found()
            self._require_candidate_current(row, binding=binding, pin=pin)
            claim = await self._school_idempotency_begin(uow, idempotency)
            if claim.replayed:
                ref = await self._receipt_resource(claim, _RESOURCE)
                if ref != candidate_ref or row.status != target:
                    raise _conflict()
                return self._summary(row)
            if row.status != "HELD" or row.state_version != expected_state_version:
                raise _conflict()
            dto = await _candidate_repo_call(
                uow.research_programme_candidates.resolve(
                    school_id=actor.school_id,
                    task_id=task.id,
                    candidate_ref=candidate_ref,
                    expected_state_version=expected_state_version,
                    target=target,
                    actor_membership_role_id=role_id,
                    now=now,
                )
            )
            action = (
                "school_research_programme_candidate.adopted"
                if target == "ADOPTED"
                else "school_research_programme_candidate.discarded"
            )
            await self._audit_research(
                uow,
                actor_account_id=actor_account_id,
                action=action,
                resource_type=_RESOURCE,
                resource_ref=dto.candidate_ref,
                trace_id=trace_id,
                state=target,
            )
            await self._school_idempotency_complete(
                uow, claim, resource_type=_RESOURCE, result_ref=dto.candidate_ref
            )
            return self._summary(dto)
