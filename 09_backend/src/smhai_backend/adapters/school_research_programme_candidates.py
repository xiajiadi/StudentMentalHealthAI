"""Encrypted persistence and authorization for staff-only programme candidates."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import uuid4

from smhai_backend.adapters.school_research_feedback import (
    SchoolResearchFeedbackPersistenceAdapter,
    _repo_call,
)
from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.school_research.study_use import ResearchStudyUsePolicy
from smhai_backend.domains.school_research_programme_candidates.schemas import (
    GeneratedProgrammeCandidate,
    ProgrammeCandidateContent,
)

RESEARCH_STAFF_PROGRAMME_POLICY_VERSION = "RESEARCH_STAFF_PROGRAMME_POLICY_V1"
_RESOURCE = "school_research_programme_candidate"
_CONTENT_SCHEMA = "school_research_programme_candidate.v1"
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
        self.expected_model_ref = expected_model_ref
        self.expected_model_digest_sha256 = expected_model_digest_sha256
        self.expected_prompt_ref = expected_prompt_ref
        self.expected_prompt_version = expected_prompt_version
        self.enabled = enabled is True

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
            if not isinstance(value, dict) or set(value) != {
                "candidate_ref", "programme_ref", "content_revision", "content"
            }:
                raise ValueError
            if (
                value["candidate_ref"] != row.candidate_ref
                or value["programme_ref"] != row.programme_ref
                or value["content_revision"] != 1
            ):
                raise ValueError
            content = ProgrammeCandidateContent.model_validate(value["content"], strict=True)
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
        self._require_enabled()
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
            task, binding, _profile, pin = await self._policy_binding_pin(
                uow, school_id=scope.school_id, task_id=scope.task_id, at=now
            )
            if (
                task.class_id != scope.class_id
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
