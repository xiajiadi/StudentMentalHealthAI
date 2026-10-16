"""Persistence and live authorization for task-bound education candidates."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import func

from smhai_backend.adapters.school_research_education_input_reviews import (
    ResearchEducationInputReviewPersistenceMixin,
    _input_review_repo_call,
)
from smhai_backend.adapters.school_research_feedback import (
    SchoolResearchFeedbackPersistenceAdapter,
    _aware_utc,
    _naive_utc,
    _repo_call,
)
from smhai_backend.core.errors import BackendError, ErrorCode, error
from smhai_backend.core.request_context import valid_correlation_id
from smhai_backend.domains.research_general_education.schemas import (
    ResearchGeneralEducationCandidatePayload,
    ResearchGeneralEducationOutputReviewPayload,
    ResearchGeneralEducationOutputSafetyDiagnostic,
    ResearchGeneralEducationSourceCard,
)
from smhai_backend.domains.school_research.study_use import ResearchStudyUsePolicy

_POLICY_VERSION = "RESEARCH_GENERAL_EDUCATION_DRAFT_V1"
_PAYLOAD_SCHEMA = "school-research-general-education-candidate.v1"
_BATCH_RESOURCE = "school_research_education_candidate_batch"
_JOB_RESOURCE = "school_research_education_candidate_job"
_JOB_AUDIT_RESOURCE = "school_research_education_job"
_CANDIDATE_RESOURCE = "school_research_education_candidate"
_OUTPUT_REVIEW_RESOURCE = "school_research_education_output_review"
_PUBLICATION_STATUS = "not_approved_for_publication_or_operational_use"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_OUTCOME_REASON_TOKEN = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
_SERVICE_OUTCOME_REASON_CODES = frozenset(
    {
        "AWAITING_SOURCE_LIMIT_AND_CONTENT_REVIEW",
        "INPUT_REVIEW_AUTHORIZATION_INVALID",
        "INPUT_SAFETY_INVALID",
        "INPUT_SAFETY_STOP",
        "INPUT_SAFETY_UNAVAILABLE",
        "OUTPUT_SAFETY_INVALID",
        "OUTPUT_SAFETY_STOP",
        "OUTPUT_SAFETY_UNAVAILABLE",
        "RESEARCH_BIBLIOGRAPHY_REJECTED",
        "RESEARCH_CANDIDATE_BINDING_INVALID",
        "RESEARCH_CITATION_BINDING_REJECTED",
        "RESEARCH_CLAIM_BOUNDARY_REJECTED",
        "RESEARCH_CONTENT_EMPTY",
        "RESEARCH_CONTENT_INVALID",
        "RESEARCH_CONTENT_SIZE_EXCEEDED",
        "RESEARCH_EVIDENCE_INELIGIBLE",
        "RESEARCH_EVIDENCE_INVALID",
        "RESEARCH_RETRIEVAL_UNAVAILABLE",
        "RESEARCH_RUNTIME_FAILED",
        "RESEARCH_RUNTIME_RESPONSE_INVALID",
        "RESEARCH_ZERO_BOUND_CITATIONS",
        "RETRIEVAL_SAFETY_INVALID",
        "RETRIEVAL_SAFETY_STOP",
        "RETRIEVAL_SAFETY_UNAVAILABLE",
        "RUNTIME_EVIDENCE_BUDGET_EXCEEDED",
        "SOURCE_CARD_BINDING_INVALID",
        "SOURCE_CARD_UNAVAILABLE",
        "WORKER_GENERATION_FAILURE_V1",
        "ZERO_EVIDENCE",
    }
)


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


async def _output_review_repo_call(awaitable):
    """Translate expected output-review storage failures without echoing data."""
    from database_layer.errors import (
        DatabaseUnavailable,
        EncryptionKeyUnavailable,
        ForeignKeyConflict,
        NotFound,
        OptimisticConcurrencyConflict,
        UniqueConflict,
    )
    from database_layer.school_research_education_output_reviews import (
        ResearchEducationOutputReviewError,
    )

    try:
        return await awaitable
    except (OptimisticConcurrencyConflict, UniqueConflict, ResearchEducationOutputReviewError):
        raise _conflict() from None
    except (ForeignKeyConflict, NotFound):
        raise _not_found() from None
    except (DatabaseUnavailable, EncryptionKeyUnavailable):
        raise error(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            detail="research education output review storage is unavailable",
            retryable=True,
        ) from None


def _canonical_mapping_sha256(value: dict[str, object]) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class SchoolResearchEducationCandidatePersistenceAdapter(
    ResearchEducationInputReviewPersistenceMixin, SchoolResearchFeedbackPersistenceAdapter
):
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
        input_review_continuation_enabled: bool = False,
        source_cards=None,
        source_valid_through: datetime | None = None,
    ) -> None:
        super().__init__(persistence, study_use_policy=study_use_policy)
        self.enabled = enabled is True
        self.school_id = school_id
        self.school_study_ref = school_study_ref
        self.policy_hash = policy_hash
        self.source_manifest_sha256 = source_manifest_sha256
        self.source_package_ref = source_package_ref
        self.source_study_ref = source_study_ref
        self.input_review_continuation_enabled = input_review_continuation_enabled is True
        self.source_cards = dict(source_cards or {})
        self.source_valid_through = source_valid_through

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
            or (
                self.source_valid_through is not None
                and _aware_utc(self.source_valid_through) < datetime.now(UTC)
            )
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
        output_review_id = getattr(row, "output_review_id", None)
        output_review_state = getattr(row, "output_review_state", None)
        output_review_linked = (
            type(output_review_id) is int
            and output_review_id > 0
            and output_review_state == "CONSUMED"
        )
        safe_output_action = row.output_safety_action in {
            "PROCEED",
            "PROCEED_WITH_BOUNDARY",
        }
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
            or type(row.generation_round) is not int
            or row.generation_round not in {0, 1}
            or (row.generation_round == 0 and (
                row.input_review_id is not None or row.input_review_state is not None
                or row.input_safety_action not in {"PROCEED", "PROCEED_WITH_BOUNDARY"}
            ))
            or (row.generation_round == 1 and (
                type(row.input_review_id) is not int or row.input_review_id <= 0
                or row.input_review_state != "CONSUMED"
                or row.input_safety_action != "REVIEW_REQUIRED"
            ))
            or row.retrieval_safety_action not in {"PROCEED", "PROCEED_WITH_BOUNDARY"}
            or not (
                (safe_output_action and output_review_id is None and output_review_state is None)
                or (row.output_safety_action == "REVIEW_REQUIRED" and output_review_linked)
            )
            or (output_review_id is None) != (output_review_state is None)
            or not isinstance(row.content_sha256, str)
            or _SHA256.fullmatch(row.content_sha256) is None
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research education candidate metadata is unavailable",
            )

    async def verify_candidate_input_lineage_in_uow(self, uow, row):
        """Verify immutable review lineage independently of the frozen v1 payload."""
        self._require_row_pins(row)
        m = self._db_models
        job = await uow.session.scalar(
            self._select(m.SchoolResearchEducationJob).where(
                m.SchoolResearchEducationJob.id == row.job_id,
                m.SchoolResearchEducationJob.school_id == row.scope.school_id,
                m.SchoolResearchEducationJob.research_session_id == row.scope.research_session_id,
            )
        )
        output_review_id = getattr(row, "output_review_id", None)
        output_review_linked = output_review_id is not None
        expected_job_status = "REVIEW_REQUIRED" if output_review_linked else "HELD"
        if (
            job is None
            or job.generation_round != row.generation_round
            or job.input_review_id != row.input_review_id
            or job.status != expected_job_status
            or job.attempt_count != 1
            or job.policy_hash != row.policy_hash
            or job.policy_version != row.policy_version
            or not self._same_scope(row.scope, job)
            or (
                output_review_linked
                and (
                    job.last_error_code != "SAFETY_BLOCKED"
                    or job.lease_owner is not None
                    or job.lease_token is not None
                )
            )
        ):
            raise _conflict()
        output_review_lineage = None
        if output_review_linked:
            from database_layer.school_research_education_output_reviews import (
                ResearchEducationOutputReviewScope,
            )

            m = self._db_models
            output_review_ref = await uow.session.scalar(
                self._select(m.SchoolResearchEducationOutputReview.output_review_ref).where(
                    m.SchoolResearchEducationOutputReview.id == output_review_id,
                    m.SchoolResearchEducationOutputReview.school_id == row.scope.school_id,
                    m.SchoolResearchEducationOutputReview.task_id == row.scope.task_id,
                )
            )
            if not isinstance(output_review_ref, str):
                raise _conflict()
            output_scope = ResearchEducationOutputReviewScope(
                **{
                    name: getattr(row.scope, name)
                    for name in ResearchEducationOutputReviewScope.__dataclass_fields__
                }
            )
            output_review = await _output_review_repo_call(
                uow.research_education_output_reviews.get_for_task(
                    scope=output_scope,
                    output_review_ref=output_review_ref,
                )
            )
            if output_review is None or output_review.output_review_ref != output_review_ref:
                raise _conflict()
            self._require_output_review_pins(output_review)
            if (
                output_review.id != output_review_id
                or output_review.job_id != job.id
                or output_review.status != "CONSUMED"
                or output_review.state_version != 2
                or output_review.consumed_at != row.created_at
                or output_review.candidate_content_sha256 != row.content_sha256
                or output_review.candidate_payload_schema_version != _PAYLOAD_SCHEMA
                or getattr(row, "output_review_state", None) != "CONSUMED"
                or output_review.safety_action != "REVIEW_REQUIRED"
                or output_review.safety_reason_code != "CONTENT_CONTROVERSIAL"
                or not self._same_scope(output_review.scope, row.scope)
            ):
                raise _conflict()
            output_review_lineage = {
                "output_review_ref": output_review.output_review_ref,
                "status": output_review.status,
                "state_version": output_review.state_version,
                "reason_code": output_review.safety_reason_code,
            }
        if row.generation_round == 0:
            return {
                "generation_round": 0,
                "input_review": None,
                "output_review": output_review_lineage,
            }
        expected_trace = "TRACE_" + hashlib.sha256(
            f"{job.job_ref}:{job.attempt_count}".encode("ascii")
        ).hexdigest()[:32]
        if output_review_linked:
            try:
                safe_trace = valid_correlation_id(row.trace_id, "TRACE")
            except (TypeError, ValueError):
                raise _conflict() from None
            if safe_trace != row.trace_id:
                raise _conflict()
        elif row.trace_id != expected_trace:
            raise _conflict()
        ref = await uow.session.scalar(
            self._select(m.SchoolResearchEducationInputReview.input_review_ref).where(
                m.SchoolResearchEducationInputReview.id == row.input_review_id,
                m.SchoolResearchEducationInputReview.school_id == row.scope.school_id,
                m.SchoolResearchEducationInputReview.task_id == row.scope.task_id,
            )
        )
        if ref is None:
            raise _conflict()
        review = await _input_review_repo_call(
            uow.research_education_input_reviews.get_for_task(
                school_id=row.scope.school_id, task_id=row.scope.task_id,
                input_review_ref=ref,
            )
        )
        if review is None or review.input_review_ref != ref:
            raise _conflict()
        self._input_review_pins(review)
        if (
            review.status != "CONSUMED" or review.state_version != 3
            or not self._same_scope(row.scope, review.scope)
            or row.created_at is None or review.consumed_at != row.created_at
        ):
            raise _conflict()
        original = await uow.session.scalar(
            self._select(m.SchoolResearchEducationJob).where(
                m.SchoolResearchEducationJob.id == review.job_id,
                m.SchoolResearchEducationJob.school_id == row.scope.school_id,
                m.SchoolResearchEducationJob.research_session_id == row.scope.research_session_id,
            )
        )
        if (
            original is None or original.job_ref != review.job_ref
            or original.generation_round != 0 or original.input_review_id is not None
            or original.status != "REVIEW_REQUIRED" or original.attempt_count != 1
            or original.last_error_code != "SAFETY_BLOCKED"
            or original.policy_hash != review.policy_hash
            or not self._same_scope(review.scope, original)
        ):
            raise _conflict()
        return {
            "generation_round": 1,
            "input_review": {
                "input_review_ref": review.input_review_ref,
                "status": review.status,
                "state_version": review.state_version,
            },
            "output_review": output_review_lineage,
        }

    def _payload_from_row(self, row):
        from database_layer.crypto import EncryptedPayload

        from smhai_backend.domains.research_general_education.prompt import (
            get_prompt_definition,
        )
        from smhai_backend.domains.research_general_education.service import (
            EXPECTED_MODEL_DIGEST_SHA256,
            EXPECTED_MODEL_ID,
            EXPECTED_MODEL_VERSION,
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
        registered_prompt = get_prompt_definition(
            row.prompt_ref, row.prompt_version, row.prompt_sha256
        )
        if (
            registered_prompt is None
            or provenance.prompt_id != registered_prompt.prompt_id
            or provenance.prompt_version != registered_prompt.version
            or provenance.prompt_sha256 != registered_prompt.sha256
            or provenance.policy_version != row.policy_version
            or provenance.policy_hash != row.policy_hash
            or provenance.source_manifest_sha256 != row.source_manifest_sha256
            or provenance.source_package_ref != self.source_package_ref
            or provenance.source_study_ref != self.source_study_ref
            or provenance.source_age_scope != "14-17"
            or provenance.safety_policy_version != SAFETY_POLICY_VERSION
            or provenance.retrieval_id != row.retrieval_id
            or provenance.retrieval_bundle_sha256 != row.retrieval_bundle_sha256
            or provenance.prompt_id != row.prompt_ref
            or provenance.prompt_version != row.prompt_version
            or provenance.prompt_sha256 != row.prompt_sha256
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

    async def _require_active_specialist_assignment(
        self, uow, task, *, at: datetime, membership_role_id: int | None = None
    ) -> None:
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
                *(
                    [m.MembershipRole.id == membership_role_id]
                    if membership_role_id is not None else []
                ),
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
        review_lineage = await self.verify_candidate_input_lineage_in_uow(uow, row)
        payload = self._payload_from_row(row) if include_payload else None
        return scope, session_ref, payload, review_lineage

    def _output_review_summary(self, row, *, task_ref, session_ref):
        return {
            "output_review_ref": row.output_review_ref,
            "job_ref": row.job_ref,
            "task_ref": task_ref,
            "session_ref": session_ref,
            "generation_round": row.generation_round,
            "status": row.status,
            "state_version": row.state_version,
            "expires_at": row.expires_at,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "safety_action": row.safety_action,
            "reason_codes": [row.safety_reason_code],
            "requires_human": row.safety_requires_human,
            "purpose": "RESEARCH_SIMULATION",
            "research_only": True,
            "publication_status": _PUBLICATION_STATUS,
            "student_feedback_eligible": False,
        }

    def _output_review_detail_payload(self, payload):
        from smhai_backend.domains.research_general_education.retrieval_trace import (
            project_r3_retrieval_trace,
        )
        from smhai_backend.domains.research_general_education.service import (
            _source_cards_match_bundle,
        )
        from smhai_backend.integrations.evidence import (
            EligibilityPolicy,
            build_retrieval_evidence_bundle,
        )
        from smhai_backend.integrations.rag import KnowledgeChunk, RetrievalResult

        snapshot = payload.retrieval_snapshot
        retrieval = RetrievalResult(
            retrieval_id=snapshot.retrieval_id,
            chunks=tuple(
                KnowledgeChunk.model_validate(item, strict=True) for item in snapshot.chunks
            ),
            label=snapshot.label,
            trace=project_r3_retrieval_trace(snapshot.trace),
        )
        bundle = build_retrieval_evidence_bundle(
            retrieval,
            transaction_id=payload.provenance.generation_id,
            request_id=payload.request_id,
            trace_id=payload.safety_trace_id,
            policy=EligibilityPolicy(
                target_population="secondary_school_student",
                target_role="student",
                risk_level=None,
                required_review_status="pending",
                required_rights_status="verified",
            ),
            strict_eligibility=True,
        )
        bundle.require_eligible()
        cards = [self.source_cards.get(chunk_id) for chunk_id in bundle.chunk_ids]
        if (
            bundle.bundle_hash != payload.provenance.retrieval_bundle_sha256
            or any(type(card) is not ResearchGeneralEducationSourceCard for card in cards)
            or not _source_cards_match_bundle(
                bundle, {card.chunk_id: card for card in cards if card is not None}
            )
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research education output review sources are unavailable",
            )
        return {
            "schema_version": "school-research-general-education-output-review.v1",
            "content": payload.content.model_dump(mode="python"),
            "source_cards": [card.model_dump(mode="python") for card in cards],
            "citations": [],
            "citation_binding_status": "NOT_EVALUATED_AT_OUTPUT_STOP",
            "provenance": payload.provenance.model_dump(mode="python"),
        }

    def _candidate_payload_from_output_review(self, payload):
        from smhai_backend.domains.conversations.service import (
            _contains_unsupported_bibliography,
        )
        from smhai_backend.domains.research_general_education.schemas import (
            ResearchGeneralEducationCandidatePayload,
            ResearchGeneralEducationProvenance,
        )
        from smhai_backend.domains.research_general_education.service import (
            ResearchGeneralEducationRuntimeSource,
            _contains_forbidden_generated_claim,
            _content_well_formed,
            _within_runtime_evidence_budget,
            canonical_candidate_payload_sha256,
        )
        from smhai_backend.domains.support.service import SupportOrchestrator
        from smhai_backend.integrations.evidence import (
            EligibilityPolicy,
            build_retrieval_evidence_bundle,
        )
        from smhai_backend.integrations.rag import KnowledgeChunk, RetrievalResult

        snapshot = payload.retrieval_snapshot
        retrieval = RetrievalResult(
            retrieval_id=snapshot.retrieval_id,
            chunks=tuple(
                KnowledgeChunk.model_validate(item, strict=True) for item in snapshot.chunks
            ),
            label=snapshot.label,
            trace=dict(snapshot.trace),
        )
        bundle = build_retrieval_evidence_bundle(
            retrieval,
            transaction_id=payload.provenance.generation_id,
            request_id=payload.request_id,
            trace_id=payload.safety_trace_id,
            policy=EligibilityPolicy(
                target_population="secondary_school_student",
                target_role="student",
                risk_level=None,
                required_review_status="pending",
                required_rights_status="verified",
            ),
            strict_eligibility=True,
        )
        bundle.require_eligible()
        content = payload.content
        if (
            not _content_well_formed(content)
            or _contains_forbidden_generated_claim(content)
            or _contains_unsupported_bibliography(
                content,
                bundle,
                original_disclaimer="本草稿仅用于一般教育信息研究复核，不构成诊断或个体建议。",
            )
            or not _within_runtime_evidence_budget(
                tuple(
                    ResearchGeneralEducationRuntimeSource(
                        chunk_id=item.chunk_id,
                        text=item.text or "",
                        title=str(item.citation.get("title") or ""),
                        organization=str(item.citation.get("organization") or ""),
                        locator=item.locator or "",
                    )
                    for item in bundle.items
                )
            )
            or any(
                not set(suggestion.source_chunk_ids).issubset(set(bundle.chunk_ids))
                for suggestion in content.suggestions
            )
        ):
            raise _conflict()
        try:
            citations = SupportOrchestrator._citations_from_bundle(bundle, content)
        except Exception:
            raise _conflict() from None
        if (
            not citations
            or any(citation.chunk_id is None for citation in citations)
            or len({citation.chunk_id for citation in citations}) != len(citations)
        ):
            raise _conflict()
        cited_ids = [citation.chunk_id for citation in citations]
        source_cards = [self.source_cards.get(chunk_id) for chunk_id in cited_ids]
        from smhai_backend.domains.research_general_education.service import (
            _source_cards_match_bundle,
        )

        if (
            any(type(card) is not ResearchGeneralEducationSourceCard for card in source_cards)
            or not set(cited_ids).issubset(set(bundle.chunk_ids))
            or not _source_cards_match_bundle(bundle, self.source_cards)
        ):
            raise _conflict()
        provenance = payload.provenance
        candidate_provenance = ResearchGeneralEducationProvenance(
            policy_version=provenance.policy_version,
            policy_hash=provenance.policy_hash,
            safety_policy_version=provenance.safety_policy_version,
            source_package_ref=provenance.source_package_ref,
            source_study_ref=provenance.source_study_ref,
            source_manifest_sha256=provenance.source_manifest_sha256,
            source_age_scope=provenance.source_age_scope,
            retrieval_id=provenance.retrieval_id,
            retrieval_bundle_sha256=provenance.retrieval_bundle_sha256,
            cited_chunk_ids=cited_ids,
            generation_id=provenance.generation_id,
            prompt_id=provenance.prompt_id,
            prompt_version=provenance.prompt_version,
            prompt_sha256=provenance.prompt_sha256,
            model_id=provenance.model_id,
            model_version=provenance.model_version,
            model_digest_sha256=provenance.model_digest_sha256,
            runtime_version=provenance.runtime_version,
            runtime_attempt_count=provenance.runtime_attempt_count,
            runtime_retry_count=provenance.runtime_retry_count,
            runtime_fallback_count=provenance.runtime_fallback_count,
            runtime_fallback_attempted=provenance.runtime_fallback_attempted,
            runtime_local_only=provenance.runtime_local_only,
            input_safety_action=provenance.input_safety_action,
            input_safety_reason_codes=provenance.input_safety_reason_codes,
            retrieval_safety_action=provenance.retrieval_safety_action,
            retrieval_safety_reason_codes=provenance.retrieval_safety_reason_codes,
            output_safety_action=provenance.output_safety_action,
            output_safety_reason_codes=list(provenance.output_safety_reason_codes),
        )
        result = ResearchGeneralEducationCandidatePayload.from_closed_mapping(
            {
                "schema_version": "school-research-general-education-candidate.v1",
                "content": content.model_dump(mode="python"),
                "citations": [citation.model_dump(mode="python") for citation in citations],
                "source_cards": [card.model_dump(mode="python") for card in source_cards],
                "provenance": candidate_provenance.model_dump(mode="python"),
            }
        )
        if len(json.dumps(content.model_dump(mode="json"), ensure_ascii=False)) > 12_000:
            raise _conflict()
        return result, canonical_candidate_payload_sha256(result)

    async def school_research_education_output_review_list(
        self, actor, task_ref: str, *, offset: int, limit: int
    ) -> dict:
        self._require_enabled()
        task_ref = self._input_review_ref(task_ref, "task_ref")
        if (
            type(offset) is not int
            or not 0 <= offset <= 100_000
            or type(limit) is not int
            or not 1 <= limit <= 20
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="output review pagination is invalid")
        now, _db_now = self._now()
        async with self._uow() as uow:
            task, _binding, _role_id = await self._active_task(
                uow, actor, task_ref, at=now
            )
            rows = await _output_review_repo_call(
                uow.research_education_output_reviews.list_for_task(
                    school_id=actor.school_id,
                    task_id=task.id,
                    offset=offset,
                    limit=limit + 1,
                )
            )
            if not isinstance(rows, (tuple, list)) or len(rows) > limit + 1:
                raise error(
                    ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                    detail="research education output review metadata is unavailable",
                )
            items = []
            for row in rows:
                _scope, session_ref, _payload = await self._current_output_review(
                    uow, actor, task, row, at=now
                )
                items.append(
                    self._output_review_summary(row, task_ref=task_ref, session_ref=session_ref)
                )
            return {
                "items": items[:limit],
                "offset": offset,
                "limit": limit,
                "has_more": len(items) > limit,
            }

    async def school_research_education_output_review_get(
        self, actor, task_ref: str, output_review_ref: str
    ) -> dict:
        self._require_enabled()
        task_ref = self._input_review_ref(task_ref, "task_ref")
        output_review_ref = self._input_review_ref(output_review_ref, "output_review_ref")
        now, _db_now = self._now()
        async with self._uow() as uow:
            task, _binding, _role_id = await self._active_task(
                uow, actor, task_ref, at=now
            )
            from database_layer.school_research_education_output_reviews import (
                ResearchEducationOutputReviewScope,
            )

            scope = await _output_review_repo_call(
                uow.research_education_output_reviews.find_scope_for_task(
                    school_id=actor.school_id,
                    task_id=task.id,
                    output_review_ref=output_review_ref,
                )
            )
            if scope is None:
                raise _not_found()
            if type(scope) is not ResearchEducationOutputReviewScope:
                raise error(
                    ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                    detail="research education output review scope is unavailable",
                )
            task_scope, _metadata, _retention, _profile, _pin = await self._current_scope(
                uow,
                actor,
                task,
                session_ref=await self._session_ref(
                    uow, actor, task, scope.research_session_id
                ),
                at=now,
            )
            if not self._same_scope(scope, task_scope):
                raise _not_found()
            row = await _output_review_repo_call(
                uow.research_education_output_reviews.get_for_task(
                    scope=scope, output_review_ref=output_review_ref
                )
            )
            if row is None:
                raise _not_found()
            _current, session_ref, payload = await self._current_output_review(
                uow, actor, task, row, at=now, include_payload=True
            )
            return {
                **self._output_review_summary(row, task_ref=task_ref, session_ref=session_ref),
                "review_payload": self._output_review_detail_payload(payload),
            }

    async def school_research_education_output_review_resolve(
        self,
        actor,
        task_ref: str,
        output_review_ref: str,
        *,
        expected_state_version: int,
        target: str,
        idempotency,
        trace_id: str,
    ) -> dict:
        self._require_enabled()
        task_ref = self._input_review_ref(task_ref, "task_ref")
        output_review_ref = self._input_review_ref(output_review_ref, "output_review_ref")
        if (
            type(expected_state_version) is not int
            or expected_state_version != 1
            or target not in {"REJECTED", "REVOKED", "CREATE_HELD_CANDIDATE"}
            or valid_correlation_id(trace_id, "TRACE") != trace_id
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="output review resolution is invalid")
        from database_layer.school_research_education_output_reviews import (
            ResearchEducationOutputReviewScope,
        )

        now, db_now = self._now()
        async with self._uow() as uow:
            actor_account_id, role_id = await self._require_actor(
                uow, actor, "psychological_specialist", db_now
            )
            task, _binding, checked_role_id = await self._active_task(
                uow, actor, task_ref, at=now
            )
            if checked_role_id != role_id:
                raise _not_found()
            scope = await _output_review_repo_call(
                uow.research_education_output_reviews.find_scope_for_task(
                    school_id=actor.school_id,
                    task_id=task.id,
                    output_review_ref=output_review_ref,
                )
            )
            if type(scope) is not ResearchEducationOutputReviewScope:
                raise _not_found()
            session_ref = await self._session_ref(
                uow, actor, task, scope.research_session_id
            )
            live_scope, _metadata, _retention, _profile, _pin = await self._current_scope(
                uow, actor, task, session_ref=session_ref, at=now, lock=True
            )
            if not self._same_scope(scope, live_scope):
                raise _not_found()
            row = await _output_review_repo_call(
                uow.research_education_output_reviews.get_for_task(
                    scope=scope, output_review_ref=output_review_ref
                )
            )
            if row is None:
                raise _not_found()
            _scope, session_ref, review_payload = await self._current_output_review(
                uow,
                actor,
                task,
                row,
                at=now,
                lock=True,
                include_payload=target == "CREATE_HELD_CANDIDATE",
            )
            claim = await self._school_idempotency_begin(uow, idempotency)
            if claim.replayed:
                if (
                    await self._receipt_resource(claim, _OUTPUT_REVIEW_RESOURCE)
                    != row.output_review_ref
                ):
                    raise _conflict()
                current = await _output_review_repo_call(
                    uow.research_education_output_reviews.get_for_task(
                        scope=scope, output_review_ref=output_review_ref
                    )
                )
                if current is None:
                    raise _not_found()
                expected_status = {
                    "REJECTED": "REJECTED",
                    "REVOKED": "REVOKED",
                    "CREATE_HELD_CANDIDATE": "CONSUMED",
                }[target]
                if (
                    current.status != expected_status
                    or current.state_version != 2
                    or current.resolved_by_membership_role_id != role_id
                ):
                    raise _conflict()
                candidate = None
                if target == "CREATE_HELD_CANDIDATE":
                    candidate = await self._candidate_for_output_review(
                        uow,
                        actor,
                        task,
                        current,
                        trace_id=trace_id,
                        at=now,
                    )
                return {
                    "output_review": self._output_review_summary(
                        current, task_ref=task_ref, session_ref=session_ref
                    ),
                    "candidate": candidate,
                }

            if (
                row.status != "PENDING"
                or row.state_version != expected_state_version
                or row.expires_at <= now
                or (
                    row.retention_due_at is not None
                    and _aware_utc(row.retention_due_at) <= now
                )
            ):
                raise _conflict()
            if target in {"REJECTED", "REVOKED"}:
                updated = await _output_review_repo_call(
                    uow.research_education_output_reviews.resolve(
                        scope=scope,
                        output_review_ref=output_review_ref,
                        expected_state_version=expected_state_version,
                        status=target,
                        actor_membership_role_id=role_id,
                        trace_id=trace_id,
                        now=now,
                    )
                )
                self._require_output_review_pins(updated)
                await self._audit_research(
                    uow,
                    actor_account_id=actor_account_id,
                    action=f"school_research_education_output_review.{target.lower()}",
                    resource_type=_OUTPUT_REVIEW_RESOURCE,
                    resource_ref=updated.output_review_ref,
                    trace_id=trace_id,
                    state=updated.status,
                )
                await self._school_idempotency_complete(
                    uow,
                    claim,
                    resource_type=_OUTPUT_REVIEW_RESOURCE,
                    result_ref=updated.output_review_ref,
                )
                return {
                    "output_review": self._output_review_summary(
                        updated, task_ref=task_ref, session_ref=session_ref
                    ),
                    "candidate": None,
                }

            await self._require_current_output_review_input_grant(
                uow, task, row, at=now
            )
            candidate_payload, candidate_sha = self._candidate_payload_from_output_review(
                review_payload
            )
            from database_layer.school_research_education_candidates import (
                ResearchEducationCandidateScope,
            )

            candidate_scope = ResearchEducationCandidateScope(
                **{
                    name: getattr(scope, name)
                    for name in ResearchEducationCandidateScope.__dataclass_fields__
                }
            )
            encrypted = self.protection.encrypt_json(
                candidate_payload.model_dump(mode="json"),
                payload_schema_version=_PAYLOAD_SCHEMA,
            )
            if len(encrypted.ciphertext) > 1_000_000:
                raise _conflict()
            candidate_ref = f"REEDUC_{uuid4().hex}"
            candidate = await _candidate_repo_call(
                uow.research_education_candidates.create_held_from_output_review(
                    scope=candidate_scope,
                    school_study_ref=self.school_study_ref,
                    output_review_ref=output_review_ref,
                    candidate_ref=candidate_ref,
                    content_sha256=candidate_sha,
                    payload_ciphertext=encrypted.ciphertext,
                    cipher_format_version=encrypted.cipher_format_version,
                    key_version=encrypted.key_version,
                    payload_schema_version=encrypted.payload_schema_version,
                    actor_membership_role_id=role_id,
                    trace_id=trace_id,
                    now=now,
                )
            )
            updated = await _output_review_repo_call(
                uow.research_education_output_reviews.get_for_task(
                    scope=scope, output_review_ref=output_review_ref
                )
            )
            if (
                updated is None
                or updated.status != "CONSUMED"
                or updated.state_version != 2
                or updated.consumed_at != candidate.created_at
                or candidate.status != "HELD"
                or candidate.created_at != now
            ):
                raise _conflict()
            self._require_row_pins(candidate)
            await self._audit_research(
                uow,
                actor_account_id=actor_account_id,
                action="school_research_education_output_review.create_held_candidate",
                resource_type=_OUTPUT_REVIEW_RESOURCE,
                resource_ref=output_review_ref,
                trace_id=trace_id,
                state="CONSUMED",
            )
            await self._school_idempotency_complete(
                uow,
                claim,
                resource_type=_OUTPUT_REVIEW_RESOURCE,
                result_ref=output_review_ref,
            )
            candidate_summary = self._summary(
                candidate, task_ref=task_ref, session_ref=session_ref
            )
            return {
                "output_review": self._output_review_summary(
                    updated, task_ref=task_ref, session_ref=session_ref
                ),
                "candidate": candidate_summary,
            }

    async def _candidate_for_output_review(
        self, uow, actor, task, review, *, trace_id, at
    ):
        m = self._db_models
        candidate_ref = await uow.session.scalar(
            self._select(m.SchoolResearchEducationCandidate.candidate_ref).where(
                m.SchoolResearchEducationCandidate.school_id == actor.school_id,
                m.SchoolResearchEducationCandidate.task_id == task.id,
                m.SchoolResearchEducationCandidate.output_review_id == review.id,
                m.SchoolResearchEducationCandidate.output_review_state == "CONSUMED",
            )
        )
        if not isinstance(candidate_ref, str):
            raise _conflict()
        row = await uow.research_education_candidates.get_for_task(
            school_id=actor.school_id,
            task_id=task.id,
            candidate_ref=candidate_ref,
        )
        if row is None:
            raise _not_found()
        _scope, session_ref, _payload, _review_lineage = await self._current_candidate(
            uow, actor, task, row, at=at
        )
        return self._summary(row, task_ref=task.task_ref, session_ref=session_ref)

    async def school_research_education_candidate_generation_job_list(
        self, actor, task_ref: str, *, offset: int, limit: int
    ) -> dict:
        """List only content-free jobs inside the caller's current assigned task scope."""
        self._require_enabled()
        from database_layer.school_research_education_jobs import (
            GENERAL_EDUCATION_POLICY_VERSION,
            ResearchEducationJobErrorCode,
        )

        if (
            type(offset) is not int
            or not 0 <= offset <= 100_000
            or type(limit) is not int
            or not 1 <= limit <= 50
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="pagination is invalid")

        statuses = (
            "QUEUED",
            "LEASED",
            "RETRY",
            "HELD",
            "ABSTAINED",
            "REVIEW_REQUIRED",
            "CRISIS_ROUTED",
            "FAILED",
            "CANCELLED",
        )
        now, _db_now = self._now()
        m = self._db_models
        job = m.SchoolResearchEducationJob
        session = m.SchoolResearchSession
        async with self._uow() as uow:
            task, binding, _role_id = await self._active_task(
                uow, actor, task_ref, at=now
            )
            scoped_jobs = (
                self._select(job.id.label("job_id"))
                .select_from(job)
                .join(
                    session,
                    (session.id == job.research_session_id)
                    & (session.school_id == job.school_id),
                )
                .where(
                    job.school_id == actor.school_id,
                    job.task_id == task.id,
                    job.class_id == task.class_id,
                    job.task_binding_id == binding.binding_id,
                    job.profile_version_id == binding.profile_version_id,
                    job.profile_ref == binding.profile_ref,
                    job.profile_version_number == binding.profile_version_number,
                    job.profile_sha256 == binding.profile_sha256,
                    job.response_origin == "PUBLIC_OBSERVED",
                    job.job_kind == "EDUCATION_SUPPORT",
                    job.policy_version == GENERAL_EDUCATION_POLICY_VERSION,
                    job.policy_hash == self.policy_hash,
                    job.purpose == "RESEARCH_SIMULATION",
                    job.research_only.is_(True),
                    job.publication_status == _PUBLICATION_STATUS,
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
                    session.items_answered >= 1,
                    session.purpose == "RESEARCH_SIMULATION",
                    session.research_only.is_(True),
                )
                .subquery()
            )
            total = int(
                await uow.session.scalar(
                    self._select(func.count()).select_from(scoped_jobs)
                )
                or 0
            )
            page_result = await uow.session.execute(
                self._select(
                    job.id.label("job_id"),
                    job.job_ref.label("job_ref"),
                    job.status.label("status"),
                    job.attempt_count.label("attempt_count"),
                    job.last_error_code.label("last_error_code"),
                    job.created_at.label("created_at"),
                    job.updated_at.label("updated_at"),
                    job.generation_round.label("generation_round"),
                    m.SchoolResearchEducationInputReview.input_review_ref.label("input_review_ref"),
                )
                .join(scoped_jobs, scoped_jobs.c.job_id == job.id)
                .outerjoin(
                    m.SchoolResearchEducationInputReview,
                    (m.SchoolResearchEducationInputReview.id == job.input_review_id)
                    & (m.SchoolResearchEducationInputReview.school_id == job.school_id)
                    & (
                        m.SchoolResearchEducationInputReview.research_session_id
                        == job.research_session_id
                    ),
                )
                .order_by(job.id)
                .offset(offset)
                .limit(limit)
            )
            status_result = await uow.session.execute(
                self._select(job.status, func.count())
                .join(scoped_jobs, scoped_jobs.c.job_id == job.id)
                .group_by(job.status)
            )
            status_counts = {status: 0 for status in statuses}
            for status, count in status_result.all():
                if status not in status_counts:
                    raise error(
                        ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                        detail="research generation job data is unavailable",
                    )
                status_counts[status] = int(count)
            if sum(status_counts.values()) != total:
                raise error(
                    ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                    detail="research generation job data is unavailable",
                )

            allowed_error_codes = {item.value for item in ResearchEducationJobErrorCode}
            items = []
            for row in page_result.all():
                values = row._mapping
                last_error_code = values["last_error_code"]
                if (
                    values["status"] not in status_counts
                    or type(values["attempt_count"]) is not int
                    or not 0 <= values["attempt_count"] <= 1
                    or type(values["generation_round"]) is not int
                    or values["generation_round"] not in {0, 1}
                    or (values["generation_round"] == 0) != (values["input_review_ref"] is None)
                    or (
                        last_error_code is not None
                        and last_error_code not in allowed_error_codes
                    )
                ):
                    raise error(
                        ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                        detail="research generation job data is unavailable",
                    )
                items.append(
                    {
                        "job_ref": values["job_ref"],
                        "status": values["status"],
                        "attempt_count": values["attempt_count"],
                        "last_error_code": last_error_code,
                        "created_at": values["created_at"],
                        "updated_at": values["updated_at"],
                        "generation_round": values["generation_round"],
                        "input_review_ref": values["input_review_ref"],
                    }
                )

            return {
                "items": items,
                "offset": offset,
                "limit": limit,
                "total": total,
                "has_more": offset + len(items) < total,
                "status_counts": status_counts,
                "policy_version": GENERAL_EDUCATION_POLICY_VERSION,
                "purpose": "RESEARCH_SIMULATION",
                "research_only": True,
                "publication_status": _PUBLICATION_STATUS,
                "student_feedback_eligible": False,
            }

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
                _scope, session_ref, _payload, _review_lineage = await self._current_candidate(
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
            _scope, session_ref, payload, review_lineage = await self._current_candidate(
                uow, actor, task, row, at=now, include_payload=True
            )
            return {
                **self._summary(row, task_ref=task_ref, session_ref=session_ref),
                "candidate_payload": payload.model_dump(mode="python"),
                "review_lineage": review_lineage,
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
            _scope, session_ref, _payload, _review_lineage = await self._current_candidate(
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
            "generation_round",
            "input_review_id",
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
        self,
        claim,
        *,
        status: str,
        error_code=None,
        input_review=None,
        reason_code=None,
        private_output_safety_failure=None,
        boundary_diagnostic=None,
        output_safety_diagnostic=None,
        output_review_payload=None,
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
            if input_review is not None and current:
                if (
                    disposition != "REVIEW_REQUIRED"
                    or error_code is not ResearchEducationJobErrorCode.SAFETY_BLOCKED
                    or persisted.generation_round != 0
                    or persisted.input_review_id is not None
                ):
                    raise _conflict()
                expected_token = hashlib.sha256(
                    f"{persisted.job_ref}:{persisted.attempt_count}".encode("ascii")
                ).hexdigest()[:32]
                evidence = self._input_review_evidence(
                    input_review, now=now, retention_due_at=_retention
                )
                if input_review.trace_id != f"TRACE_{expected_token}":
                    raise _conflict()
                from database_layer.school_research_education_input_reviews import (
                    ResearchEducationInputReviewScope,
                )

                await _input_review_repo_call(
                    uow.research_education_input_reviews.create_pending(
                        claim=persisted,
                        scope=ResearchEducationInputReviewScope(
                            **{
                                name: getattr(_scope, name)
                                for name in ResearchEducationInputReviewScope.__dataclass_fields__
                            }
                        ),
                        evidence=evidence,
                        now=now,
                    )
                )
            output_safety_for_review = self._safe_output_safety_diagnostic(
                output_safety_diagnostic,
                status=disposition,
                error_code=error_code if current else None,
                reason_code=reason_code,
                scope_current=current,
            )
            review_payload = None
            review_capture = None
            eligible_output_review = (
                current
                and output_safety_for_review is not None
                and output_safety_for_review.action == "REVIEW_REQUIRED"
                and output_safety_for_review.reason_codes == ("CONTENT_CONTROVERSIAL",)
                and output_safety_for_review.requires_human is True
            )
            if eligible_output_review:
                capture_code = "PAYLOAD_UNAVAILABLE"
                if type(output_review_payload) is ResearchGeneralEducationOutputReviewPayload:
                    capture_code = "PAYLOAD_REBIND_FAILED"
                    try:
                        review_payload = self._validated_output_review_payload(
                            output_review_payload,
                            job_ref=persisted.job_ref,
                            attempt_count=persisted.attempt_count,
                            generation_round=persisted.generation_round,
                        )
                    except Exception:
                        review_payload = None
                if review_payload is not None:
                    capture_code = "RETENTION_WINDOW_INVALID"
                    try:
                        expires_at = min(
                            now + timedelta(hours=24),
                            _aware_utc(self.study_use_policy.ends_at),
                        )
                        if _retention is not None:
                            expires_at = min(expires_at, _aware_utc(_retention))
                        if expires_at > now:
                            from database_layer.school_research_education_output_reviews import (
                                OUTPUT_REVIEW_PAYLOAD_SCHEMA_VERSION,
                                ResearchEducationOutputReviewEvidence,
                                ResearchEducationOutputReviewScope,
                            )

                            provenance = review_payload.provenance
                            evidence = ResearchEducationOutputReviewEvidence(
                                safety_decision_id=review_payload.safety_decision_id,
                                safety_review_ref=review_payload.safety_review_ref,
                                safety_trace_id=review_payload.safety_trace_id,
                                safety_operation="OUTPUT",
                                safety_action="REVIEW_REQUIRED",
                                safety_reason_codes=("CONTENT_CONTROVERSIAL",),
                                safety_requires_human=True,
                                input_safety_action=provenance.input_safety_action,
                                retrieval_safety_action=provenance.retrieval_safety_action,
                                canonical_input_sha256=review_payload.canonical_input_sha256,
                                policy_version=provenance.policy_version,
                                policy_hash=provenance.policy_hash,
                                source_package_ref=provenance.source_package_ref,
                                source_study_ref=provenance.source_study_ref,
                                source_manifest_sha256=provenance.source_manifest_sha256,
                                retrieval_id=provenance.retrieval_id,
                                retrieval_bundle_sha256=provenance.retrieval_bundle_sha256,
                                prompt_id=provenance.prompt_id,
                                prompt_version=provenance.prompt_version,
                                prompt_sha256=provenance.prompt_sha256,
                                model_ref=provenance.model_id,
                                model_digest_sha256=provenance.model_digest_sha256,
                                runtime_version=provenance.runtime_version,
                                safety_policy_version=provenance.safety_policy_version,
                                candidate_content_sha256=None,
                                candidate_payload_schema_version=None,
                                expires_at=expires_at,
                                trace_id=review_payload.safety_trace_id,
                            )
                            serialized_review = review_payload.model_dump(mode="json")
                            capture_code = "ENCRYPTION_FAILED"
                            encrypted_review = self.protection.encrypt_json(
                                serialized_review,
                                payload_schema_version=OUTPUT_REVIEW_PAYLOAD_SCHEMA_VERSION,
                            )
                            capture_code = "PAYLOAD_TOO_LARGE"
                            if len(encrypted_review.ciphertext) <= 1_000_000:
                                scope_values = {
                                    name: getattr(_scope, name)
                                    for name in (
                                        ResearchEducationOutputReviewScope.__dataclass_fields__
                                    )
                                }
                                capture_code = "PERSISTENCE_FAILED"
                                try:
                                    async with uow.session.begin_nested():
                                        await _output_review_repo_call(
                                            uow.research_education_output_reviews.create_pending(
                                                claim=persisted,
                                                scope=ResearchEducationOutputReviewScope(**scope_values),
                                                evidence=evidence,
                                                content_sha256=_canonical_mapping_sha256(
                                                    serialized_review
                                                ),
                                                payload_ciphertext=encrypted_review.ciphertext,
                                                cipher_format_version=(
                                                    encrypted_review.cipher_format_version
                                                ),
                                                key_version=encrypted_review.key_version,
                                                payload_schema_version=(
                                                    encrypted_review.payload_schema_version
                                                ),
                                                now=now,
                                            )
                                        )
                                except Exception:
                                    pass
                                else:
                                    review_capture = ("SAVED", "OUTPUT_REVIEW_SAVED")
                        else:
                            capture_code = "RETENTION_WINDOW_INVALID"
                    except Exception:
                        # Capture is optional; retain only its closed outcome below.
                        pass
                if review_capture is None:
                    review_capture = ("NOT_SAVED", capture_code)
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
            safe_reason_code = self._safe_job_outcome_reason(
                reason_code, scope_current=current
            )
            if safe_reason_code is not None:
                token = hashlib.sha256(
                    f"{persisted.job_ref}:{persisted.attempt_count}".encode("ascii")
                ).hexdigest()[:32]
                from database_layer.enums import AuditResult

                await uow.audit.append(
                    action="school_research_education_job.terminal",
                    resource_type=_JOB_AUDIT_RESOURCE,
                    resource_public_id=persisted.job_ref,
                    result=(AuditResult.DENIED if not current else AuditResult.FAILURE),
                    trace_id=f"TRACE_{token}",
                    safe_metadata={
                        "source": _POLICY_VERSION,
                        "state": disposition,
                        "reason_code": safe_reason_code,
                    },
                )
            output_failure = self._safe_private_output_safety_failure(
                private_output_safety_failure,
                status=disposition,
                error_code=error_code if current else None,
                reason_code=reason_code,
                scope_current=current,
            )
            if output_failure is not None:
                token = hashlib.sha256(
                    f"{persisted.job_ref}:{persisted.attempt_count}".encode("ascii")
                ).hexdigest()[:32]
                from database_layer.enums import AuditResult

                await uow.audit.append(
                    action="school_research_education_job.output_safety_dependency",
                    resource_type=_JOB_AUDIT_RESOURCE,
                    resource_public_id=persisted.job_ref,
                    result=AuditResult.FAILURE,
                    trace_id=f"TRACE_{token}",
                    safe_metadata={
                        "source": _POLICY_VERSION,
                        "state": "FAILED",
                        "reason_code": f"OUTPUT_SAFETY_{output_failure}",
                    },
                )
            boundary_metadata = self._safe_claim_boundary_metadata(
                boundary_diagnostic,
                status=disposition,
                error_code=error_code if current else None,
                reason_code=reason_code,
                scope_current=current,
            )
            if boundary_metadata is not None:
                token = hashlib.sha256(
                    f"{persisted.job_ref}:{persisted.attempt_count}".encode("ascii")
                ).hexdigest()[:32]
                from database_layer.enums import AuditResult

                await uow.audit.append(
                    action="school_research_education_job.claim_boundary",
                    resource_type=_JOB_AUDIT_RESOURCE,
                    resource_public_id=persisted.job_ref,
                    result=AuditResult.FAILURE,
                    trace_id=f"TRACE_{token}",
                    safe_metadata=boundary_metadata,
                )
            output_safety = self._safe_output_safety_diagnostic(
                output_safety_diagnostic,
                status=disposition,
                error_code=error_code if current else None,
                reason_code=reason_code,
                scope_current=current,
            )
            if output_safety is not None:
                token = hashlib.sha256(
                    f"{persisted.job_ref}:{persisted.attempt_count}".encode("ascii")
                ).hexdigest()[:32]
                from database_layer.enums import AuditResult

                for safety_reason_code in output_safety.reason_codes:
                    await uow.audit.append(
                        action="school_research_education_job.output_safety",
                        resource_type=_JOB_AUDIT_RESOURCE,
                        resource_public_id=persisted.job_ref,
                        result=AuditResult.FAILURE,
                        trace_id=f"TRACE_{token}",
                        safe_metadata={
                            "schema_version": "research-output-safety-diagnostic.v1",
                            "source": _POLICY_VERSION,
                            "state": output_safety.action,
                            "reason_code": safety_reason_code,
                            # For this versioned event, count encodes requires_human as 0/1.
                            "count": int(output_safety.requires_human),
                        },
                    )
            if review_capture is not None:
                token = hashlib.sha256(
                    f"{persisted.job_ref}:{persisted.attempt_count}".encode("ascii")
                ).hexdigest()[:32]
                from database_layer.enums import AuditResult

                capture_state, capture_code = review_capture
                await uow.audit.append(
                    action="school_research_education_job.output_review_capture",
                    resource_type=_JOB_AUDIT_RESOURCE,
                    resource_public_id=persisted.job_ref,
                    result=(
                        AuditResult.SUCCESS if capture_state == "SAVED" else AuditResult.FAILURE
                    ),
                    trace_id=f"TRACE_{token}",
                    safe_metadata={
                        "schema_version": "research-output-review-capture.v1",
                        "source": _POLICY_VERSION,
                        "state": capture_state,
                        "reason_code": capture_code,
                    },
                )
            return disposition

    @staticmethod
    def _safe_job_outcome_reason(reason_code, *, scope_current: bool) -> str | None:
        if not scope_current:
            return "SCOPE_REVOKED"
        if (
            type(reason_code) is not str
            or _SAFE_OUTCOME_REASON_TOKEN.fullmatch(reason_code) is None
        ):
            return None
        if reason_code in _SERVICE_OUTCOME_REASON_CODES:
            return reason_code
        return "UNCLASSIFIED_OUTCOME"

    @staticmethod
    def _safe_private_output_safety_failure(
        diagnostic, *, status, error_code, reason_code, scope_current
    ) -> str | None:
        from database_layer.school_research_education_jobs import (
            ResearchEducationJobErrorCode,
        )

        if (
            not scope_current
            or status != "FAILED"
            or error_code is not ResearchEducationJobErrorCode.UPSTREAM_TRANSIENT
            or reason_code != "OUTPUT_SAFETY_UNAVAILABLE"
        ):
            return None
        if type(diagnostic) is not str or diagnostic not in {
            "TIMEOUT",
            "TRANSPORT",
            "UPSTREAM_HTTP",
            "INVALID_RESPONSE",
            "OTHER",
        }:
            return None
        return diagnostic

    @staticmethod
    def _safe_claim_boundary_metadata(
        diagnostic, *, status, error_code, reason_code, scope_current
    ) -> dict[str, object] | None:
        from database_layer.school_research_education_jobs import (
            ResearchEducationJobErrorCode,
        )

        if (
            not scope_current
            or status != "ABSTAINED"
            or error_code is not ResearchEducationJobErrorCode.GENERATION_FAILED
            or reason_code != "RESEARCH_CLAIM_BOUNDARY_REJECTED"
        ):
            return None
        from smhai_backend.domains.research_general_education.schemas import (
            ResearchGeneralEducationBoundaryDiagnostic,
        )

        if type(diagnostic) is not ResearchGeneralEducationBoundaryDiagnostic:
            return None
        allowed_fields = {"SUMMARY", "OBSERVATION", "SUGGESTION"}
        allowed_categories = {
            "DIAGNOSIS",
            "CLINICAL",
            "SEVERITY",
            "PSYCHOMETRIC_SCORE",
            "OTHER_ALLOWLISTED",
        }
        if (
            type(diagnostic.field_kind) is not str
            or diagnostic.field_kind not in allowed_fields
            or type(diagnostic.field_index) is not int
            or not 0 <= diagnostic.field_index <= 12_000
            or type(diagnostic.category) is not str
            or diagnostic.category not in allowed_categories
            or type(diagnostic.match_count) is not int
            or not 1 <= diagnostic.match_count <= 12_000
        ):
            return None
        return {
            "source": _POLICY_VERSION,
            "state": diagnostic.field_kind,
            "reason_code": diagnostic.category,
            "count": diagnostic.match_count,
        }

    @staticmethod
    def _safe_output_safety_diagnostic(
        diagnostic, *, status, error_code, reason_code, scope_current
    ) -> ResearchGeneralEducationOutputSafetyDiagnostic | None:
        from database_layer.school_research_education_jobs import (
            ResearchEducationJobErrorCode,
        )

        if (
            not scope_current
            or status not in {"ABSTAINED", "REVIEW_REQUIRED", "CRISIS_ROUTED"}
            or error_code is not ResearchEducationJobErrorCode.SAFETY_BLOCKED
            or reason_code != "OUTPUT_SAFETY_STOP"
            or type(diagnostic) is not ResearchGeneralEducationOutputSafetyDiagnostic
        ):
            return None
        try:
            validated = ResearchGeneralEducationOutputSafetyDiagnostic.model_validate(
                diagnostic.model_dump(mode="python"), strict=True
            )
        except (TypeError, ValueError):
            return None
        if validated.stopped_status != status:
            return None
        return validated

    def _validated_output_review_payload(
        self, value, *, job_ref: str, attempt_count: int, generation_round: int
    ):
        """Fail closed unless the encrypted envelope reproduces the pinned R3 evidence."""
        from smhai_backend.domains.research_general_education.prompt import (
            get_prompt_definition,
        )
        from smhai_backend.domains.research_general_education.retrieval_trace import (
            project_r3_retrieval_trace,
        )
        from smhai_backend.domains.research_general_education.service import (
            EXPECTED_MODEL_DIGEST_SHA256,
            EXPECTED_MODEL_ID,
            EXPECTED_MODEL_VERSION,
            ResearchGeneralEducationPolicyPins,
            _source_cards_match_bundle,
            _valid_retrieval,
        )
        from smhai_backend.integrations.evidence import (
            EligibilityPolicy,
            build_retrieval_evidence_bundle,
        )
        from smhai_backend.integrations.rag import KnowledgeChunk, RetrievalResult

        if type(value) is not ResearchGeneralEducationOutputReviewPayload:
            raise _conflict()
        provenance = value.provenance
        registered_prompt = get_prompt_definition(
            provenance.prompt_id, provenance.prompt_version, provenance.prompt_sha256
        )
        if (
            registered_prompt is None
            or provenance.policy_version != _POLICY_VERSION
            or provenance.policy_hash != self.policy_hash
            or provenance.safety_policy_version != "safety-port-unversioned.v1"
            or provenance.source_package_ref != self.source_package_ref
            or provenance.source_study_ref != self.source_study_ref
            or provenance.source_manifest_sha256 != self.source_manifest_sha256
            or provenance.prompt_id != registered_prompt.prompt_id
            or provenance.prompt_version != registered_prompt.version
            or provenance.prompt_sha256 != registered_prompt.sha256
            or provenance.model_id != EXPECTED_MODEL_ID
            or provenance.model_version != EXPECTED_MODEL_VERSION
            or provenance.model_digest_sha256 != EXPECTED_MODEL_DIGEST_SHA256
            or provenance.output_safety_action != "REVIEW_REQUIRED"
            or provenance.output_safety_reason_codes != ("CONTENT_CONTROVERSIAL",)
            or provenance.output_safety_requires_human is not True
            or value.canonical_input_sha256 is not None
            and generation_round == 0
            or value.canonical_input_sha256 is None
            and generation_round == 1
        ):
            raise _conflict()
        trace_token = hashlib.sha256(
            f"{job_ref}:{attempt_count}".encode("ascii")
        ).hexdigest()[:32]
        if (
            value.safety_trace_id != f"TRACE_{trace_token}"
            or value.request_id != f"REQ_{trace_token}"
        ):
            raise _conflict()
        snapshot = value.retrieval_snapshot
        if (
            snapshot.retrieval_id != provenance.retrieval_id
            or len(json.dumps(value.model_dump(mode="json"), ensure_ascii=False)) > 262_144
        ):
            raise _conflict()
        try:
            trace = project_r3_retrieval_trace(snapshot.trace)
            chunks = tuple(
                KnowledgeChunk.model_validate(item, strict=True) for item in snapshot.chunks
            )
            retrieval = RetrievalResult(
                retrieval_id=snapshot.retrieval_id,
                chunks=chunks,
                label=snapshot.label,
                trace=trace,
            )
            pins = ResearchGeneralEducationPolicyPins(
                policy_hash=self.policy_hash,
                source_package_ref=self.source_package_ref,
                source_study_ref=self.source_study_ref,
                source_manifest_sha256=self.source_manifest_sha256,
            )
            if not _valid_retrieval(retrieval, pins, provenance.retrieval_id):
                raise ValueError("retrieval snapshot is not current")
            bundle = build_retrieval_evidence_bundle(
                retrieval,
                transaction_id=provenance.generation_id,
                request_id=value.request_id,
                trace_id=value.safety_trace_id,
                policy=EligibilityPolicy(
                    target_population="secondary_school_student",
                    target_role="student",
                    risk_level=None,
                    required_review_status="pending",
                    required_rights_status="verified",
                ),
                strict_eligibility=True,
            )
            bundle.require_eligible()
        except Exception:
            raise _conflict() from None
        cards = {chunk_id: self.source_cards.get(chunk_id) for chunk_id in bundle.chunk_ids}
        if (
            bundle.bundle_hash != provenance.retrieval_bundle_sha256
            or not bundle.items
            or any(type(card) is not ResearchGeneralEducationSourceCard for card in cards.values())
            or not _source_cards_match_bundle(bundle, cards)
        ):
            raise _conflict()
        return value

    def _require_output_review_pins(self, row) -> None:
        from smhai_backend.domains.research_general_education.prompt import (
            get_prompt_definition,
        )
        from smhai_backend.domains.research_general_education.service import (
            EXPECTED_MODEL_DIGEST_SHA256,
            EXPECTED_MODEL_ID,
        )

        expected_token = hashlib.sha256(
            f"{row.job_ref}:1".encode("ascii")
        ).hexdigest()[:32]
        prompt = get_prompt_definition(row.prompt_id, row.prompt_version, row.prompt_sha256)
        valid_state = (row.status == "PENDING" and row.state_version == 1) or (
            row.status in {"REJECTED", "REVOKED", "CONSUMED"}
            and row.state_version == 2
        )
        if (
            not valid_state
            or row.safety_operation != "OUTPUT"
            or row.safety_action != "REVIEW_REQUIRED"
            or row.safety_reason_code != "CONTENT_CONTROVERSIAL"
            or row.safety_requires_human is not True
            or row.safety_trace_id != f"TRACE_{expected_token}"
            or row.trace_id != f"TRACE_{expected_token}"
            or row.policy_version != _POLICY_VERSION
            or row.policy_hash != self.policy_hash
            or row.source_package_ref != self.source_package_ref
            or row.source_study_ref != self.source_study_ref
            or row.source_manifest_sha256 != self.source_manifest_sha256
            or row.safety_policy_version != "safety-port-unversioned.v1"
            or prompt is None
            or row.model_ref != EXPECTED_MODEL_ID
            or row.model_digest_sha256 != EXPECTED_MODEL_DIGEST_SHA256
            or row.runtime_version is None
            or not isinstance(row.content_sha256, str)
            or _SHA256.fullmatch(row.content_sha256) is None
            or row.generation_round not in {0, 1}
            or (row.generation_round == 0 and row.canonical_input_sha256 is not None)
            or (row.generation_round == 1 and _SHA256.fullmatch(
                row.canonical_input_sha256 or ""
            ) is None)
            or (row.status == "CONSUMED")
            != (
                isinstance(row.candidate_content_sha256, str)
                and _SHA256.fullmatch(row.candidate_content_sha256) is not None
            )
            or (row.status == "CONSUMED")
            != (row.candidate_payload_schema_version == _PAYLOAD_SCHEMA)
            or (
                row.status != "CONSUMED"
                and (
                    row.candidate_content_sha256 is not None
                    or row.candidate_payload_schema_version is not None
                )
            )
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research education output review metadata is unavailable",
            )

    def _output_review_payload_from_row(self, row):
        from database_layer.crypto import EncryptedPayload
        from database_layer.school_research_education_output_reviews import (
            OUTPUT_REVIEW_PAYLOAD_SCHEMA_VERSION,
        )

        from smhai_backend.domains.research_general_education.schemas import (
            ResearchGeneralEducationOutputReviewPayload,
        )
        from smhai_backend.domains.research_general_education.service import (
            EXPECTED_MODEL_VERSION,
        )

        if (
            row.payload_schema_version != OUTPUT_REVIEW_PAYLOAD_SCHEMA_VERSION
            or not row.cipher_format_version
            or not row.key_version
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research education output review content is unavailable",
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
            expected = set(ResearchGeneralEducationOutputReviewPayload.model_fields)
            if set(value) != expected:
                raise ValueError("encrypted output review fields are not closed")
            from smhai_backend.domains.support.schemas import GenerationContent

            validated_value = dict(value)
            validated_value["content"] = GenerationContent.model_validate(
                value["content"], strict=True
            ).model_dump(mode="python")
            validated_provenance = dict(value["provenance"])
            validated_provenance["output_safety_reason_codes"] = tuple(
                validated_provenance["output_safety_reason_codes"]
            )
            validated_value["provenance"] = validated_provenance
            payload = ResearchGeneralEducationOutputReviewPayload.model_validate(
                validated_value, strict=True
            )
            self._validated_output_review_payload(
                payload,
                job_ref=row.job_ref,
                attempt_count=1,
                generation_round=row.generation_round,
            )
        except Exception:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research education output review content is unavailable",
            ) from None
        if (
            payload.provenance.policy_hash != row.policy_hash
            or payload.provenance.source_manifest_sha256 != row.source_manifest_sha256
            or payload.provenance.retrieval_id != row.retrieval_id
            or payload.provenance.retrieval_bundle_sha256 != row.retrieval_bundle_sha256
            or payload.provenance.prompt_id != row.prompt_id
            or payload.provenance.prompt_version != row.prompt_version
            or payload.provenance.prompt_sha256 != row.prompt_sha256
            or payload.provenance.model_id != row.model_ref
            or payload.provenance.model_version != EXPECTED_MODEL_VERSION
            or payload.provenance.model_digest_sha256 != row.model_digest_sha256
            or payload.provenance.runtime_version != row.runtime_version
            or payload.provenance.input_safety_action != row.input_safety_action
            or payload.provenance.retrieval_safety_action != row.retrieval_safety_action
            or payload.safety_decision_id != row.safety_decision_id
            or payload.safety_review_ref != row.safety_review_ref
            or payload.safety_trace_id != row.safety_trace_id
            or _canonical_mapping_sha256(payload.model_dump(mode="json"))
            != row.content_sha256
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research education output review provenance is unavailable",
            )
        return payload

    async def _current_output_review(
        self, uow, actor, task, row, *, at, lock=False, include_payload=False
    ):
        self._require_output_review_pins(row)
        if row.scope.task_id != task.id or row.scope.school_id != actor.school_id:
            raise _not_found()
        session_ref = await self._session_ref(
            uow, actor, task, row.scope.research_session_id
        )
        scope, _metadata, _retention, _profile, _pin = await self._current_scope(
            uow, actor, task, session_ref=session_ref, at=at, lock=lock
        )
        if scope.response_origin != "PUBLIC_OBSERVED" or not self._same_scope(
            row.scope, scope
        ):
            raise _not_found()
        job = await uow.session.scalar(
            self._select(self._db_models.SchoolResearchEducationJob).where(
                self._db_models.SchoolResearchEducationJob.id == row.job_id,
                self._db_models.SchoolResearchEducationJob.school_id == row.scope.school_id,
                self._db_models.SchoolResearchEducationJob.research_session_id
                == row.scope.research_session_id,
            )
        )
        if (
            job is None
            or job.job_ref != row.job_ref
            or job.generation_round != row.generation_round
            or job.status != "REVIEW_REQUIRED"
            or job.last_error_code != "SAFETY_BLOCKED"
            or job.attempt_count != 1
            or job.lease_owner is not None
            or job.lease_token is not None
            or job.input_review_id != row.input_review_id
            or job.policy_hash != row.policy_hash
            or not self._same_scope(row.scope, job)
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research education output review source is unavailable",
            )
        if include_payload and (
            _aware_utc(row.expires_at) <= _aware_utc(at)
            or (
                row.retention_due_at is not None
                and _aware_utc(row.retention_due_at) <= _aware_utc(at)
            )
        ):
            raise _conflict()
        payload = self._output_review_payload_from_row(row) if include_payload else None
        return scope, session_ref, payload

    async def _require_current_output_review_input_grant(self, uow, task, output_review, *, at):
        """Require round-1 candidate creation to use the current server-owned grant pin."""
        if output_review.generation_round == 0:
            return
        if output_review.generation_round != 1 or output_review.input_review_id is None:
            raise _conflict()

        from smhai_backend.domains.research_general_education.input_review_policy import (
            INPUT_REVIEW_CONTINUATION_POLICY_SHA256,
            INPUT_REVIEW_CONTINUATION_POLICY_VERSION,
        )

        m = self._db_models
        input_review_ref = await uow.session.scalar(
            self._select(m.SchoolResearchEducationInputReview.input_review_ref)
            .where(
                m.SchoolResearchEducationInputReview.id == output_review.input_review_id,
                m.SchoolResearchEducationInputReview.school_id == output_review.scope.school_id,
                m.SchoolResearchEducationInputReview.task_id == task.id,
                m.SchoolResearchEducationInputReview.research_session_id
                == output_review.scope.research_session_id,
            )
            .with_for_update()
        )
        if not isinstance(input_review_ref, str):
            raise _conflict()
        input_review = await _input_review_repo_call(
            uow.research_education_input_reviews.get_for_task(
                school_id=output_review.scope.school_id,
                task_id=task.id,
                input_review_ref=input_review_ref,
            )
        )
        self._input_review_pins(input_review)
        if (
            input_review.id != output_review.input_review_id
            or input_review.status != "CONTINUATION_AUTHORIZED"
            or input_review.state_version != 2
            or input_review.expires_at <= at
            or (
                input_review.retention_due_at is not None
                and _aware_utc(input_review.retention_due_at) <= _aware_utc(at)
            )
            or input_review.grant_policy_version != INPUT_REVIEW_CONTINUATION_POLICY_VERSION
            or input_review.grant_policy_hash != INPUT_REVIEW_CONTINUATION_POLICY_SHA256
            or input_review.policy_version != output_review.policy_version
            or input_review.policy_hash != output_review.policy_hash
            or input_review.source_package_ref != output_review.source_package_ref
            or input_review.source_study_ref != output_review.source_study_ref
            or input_review.source_manifest_sha256 != output_review.source_manifest_sha256
            or input_review.prompt_id != output_review.prompt_id
            or input_review.prompt_version != output_review.prompt_version
            or input_review.prompt_sha256 != output_review.prompt_sha256
            or input_review.canonical_input_sha256 != output_review.canonical_input_sha256
            or not self._same_scope(input_review.scope, output_review.scope)
        ):
            raise _conflict()
        await self._require_active_specialist_assignment(
            uow,
            task,
            at=at,
            membership_role_id=input_review.authorized_by_membership_role_id,
        )
        await self._current_input_review(
            uow,
            SimpleNamespace(school_id=output_review.scope.school_id),
            task,
            input_review,
            at=at,
            lock=True,
        )

    def _input_review_evidence(self, receipt, *, now, retention_due_at=None):
        """Rebind the actual stopped-input receipt to this server's trusted pins."""
        from database_layer.school_research_education_input_reviews import (
            ResearchEducationInputReviewEvidence,
        )

        from smhai_backend.domains.research_general_education.prompt import (
            PROMPT_ID,
            PROMPT_SHA256,
            PROMPT_VERSION,
        )
        from smhai_backend.domains.research_general_education.schemas import (
            ResearchGeneralEducationInputReviewReceipt,
        )
        from smhai_backend.domains.research_general_education.service import (
            ResearchGeneralEducationPolicyPins,
            canonical_input_context_sha256,
        )

        pins = ResearchGeneralEducationPolicyPins(
            policy_hash=self.policy_hash,
            source_package_ref=self.source_package_ref,
            source_study_ref=self.source_study_ref,
            source_manifest_sha256=self.source_manifest_sha256,
        )
        if (
            type(receipt) is not ResearchGeneralEducationInputReviewReceipt
            or receipt.policy_version != _POLICY_VERSION
            or receipt.policy_hash != self.policy_hash
            or receipt.source_package_ref != self.source_package_ref
            or receipt.source_study_ref != self.source_study_ref
            or receipt.source_manifest_sha256 != self.source_manifest_sha256
            or receipt.prompt_id != PROMPT_ID
            or receipt.prompt_version != PROMPT_VERSION
            or receipt.prompt_sha256 != PROMPT_SHA256
            or receipt.canonical_input_sha256
            != canonical_input_context_sha256(policy_pins=pins)
        ):
            raise _conflict()
        expires_at = now + timedelta(hours=24)
        if retention_due_at is not None:
            expires_at = min(expires_at, _aware_utc(retention_due_at))
        if expires_at <= now:
            raise _conflict()
        return ResearchEducationInputReviewEvidence(
            decision_id=receipt.decision_id,
            safety_review_ref=receipt.review_ref,
            safety_trace_id=receipt.trace_id,
            safety_operation=receipt.operation,
            safety_action=receipt.action,
            reason_codes=tuple(receipt.reason_codes),
            requires_human=receipt.requires_human,
            canonical_input_sha256=receipt.canonical_input_sha256,
            policy_version=receipt.policy_version,
            policy_hash=receipt.policy_hash,
            source_package_ref=receipt.source_package_ref,
            source_study_ref=receipt.source_study_ref,
            source_manifest_sha256=receipt.source_manifest_sha256,
            prompt_id=receipt.prompt_id,
            prompt_version=receipt.prompt_version,
            prompt_sha256=receipt.prompt_sha256,
            trace_id=receipt.trace_id,
            expires_at=expires_at,
        )

    async def store_generated_candidate(
        self, claim, payload, *, trace_id: str, input_review=None
    ) -> dict:
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
            consumed_review = None
            if persisted.generation_round == 1:
                authorization, review = await self._continuation_authorization(
                    uow, persisted, _task, now=now
                )
                if input_review != authorization or trace_id != authorization.continuation_trace_id:
                    raise _conflict()
                if payload.provenance.input_safety_action != "REVIEW_REQUIRED":
                    raise _conflict()
                from smhai_backend.domains.research_general_education.input_review_policy import (
                    INPUT_REVIEW_CONTINUATION_POLICY_SHA256,
                    INPUT_REVIEW_CONTINUATION_POLICY_VERSION,
                )
                consumed_review = await _input_review_repo_call(
                    uow.research_education_input_reviews.consume_for_candidate(
                        claim=persisted,
                        scope=review.scope,
                        grant_policy_version=INPUT_REVIEW_CONTINUATION_POLICY_VERSION,
                        grant_policy_hash=INPUT_REVIEW_CONTINUATION_POLICY_SHA256,
                        source_package_ref=review.source_package_ref,
                        source_study_ref=review.source_study_ref,
                        source_manifest_sha256=review.source_manifest_sha256,
                        prompt_id=review.prompt_id, prompt_version=review.prompt_version,
                        prompt_sha256=review.prompt_sha256,
                        canonical_input_sha256=review.canonical_input_sha256,
                        trace_id=trace_id, now=now,
                    )
                )
                if consumed_review.id != review.id or consumed_review.status != "CONSUMED":
                    raise _conflict()
            elif (
                persisted.generation_round != 0 or persisted.input_review_id is not None
                or input_review is not None
                or payload.provenance.input_safety_action
                not in {"PROCEED", "PROCEED_WITH_BOUNDARY"}
            ):
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
                    input_review=consumed_review,
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
