"""Task-bound persistence projections for stopped research education inputs."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.request_context import valid_correlation_id

_POLICY_VERSION = "RESEARCH_GENERAL_EDUCATION_DRAFT_V1"
_INPUT_REVIEW_RESOURCE = "school_research_education_input_review"
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SAFETY_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _not_found():
    return error(
        ErrorCode.RESOURCE_NOT_FOUND,
        detail="research education input review was not found",
    )


def _conflict():
    return error(
        ErrorCode.WORKFLOW_CONFLICT,
        detail="research education input review state changed",
    )


async def _input_review_repo_call(awaitable):
    """Translate only known repository failures to closed API errors."""
    from database_layer.errors import (
        DatabaseUnavailable,
        EncryptionKeyUnavailable,
        ForeignKeyConflict,
        NotFound,
        OptimisticConcurrencyConflict,
        UniqueConflict,
    )
    from database_layer.school_research_education_input_reviews import (
        ResearchEducationInputReviewError,
    )

    try:
        return await awaitable
    except (OptimisticConcurrencyConflict, UniqueConflict):
        raise _conflict() from None
    except (ForeignKeyConflict, NotFound):
        raise _not_found() from None
    except ResearchEducationInputReviewError as exc:
        if exc.code in {"INVALID_PAGINATION", "INVALID_INPUT", "INVALID_SCOPE"}:
            raise error(
                ErrorCode.VALIDATION_FAILED,
                detail="research education input review request is invalid",
            ) from None
        raise _conflict() from None
    except (DatabaseUnavailable, EncryptionKeyUnavailable):
        raise error(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            detail="research education input review storage is unavailable",
            retryable=True,
        ) from None


class ResearchEducationInputReviewPersistenceMixin:
    """Reusable routes over current assigned Scope C and research-session facts."""

    def _input_review_ref(self, value: str, field: str) -> str:
        if type(value) is not str or _SAFE_REF.fullmatch(value) is None:
            raise error(ErrorCode.VALIDATION_FAILED, detail=f"{field} is invalid")
        return value

    def _input_review_pins(self, row) -> None:
        from database_layer.school_research_education_input_reviews import (
            ResearchEducationInputReviewDTO,
            ResearchEducationInputReviewScope,
        )

        from smhai_backend.domains.research_general_education.prompt import (
            PROMPT_ID,
            PROMPT_SHA256,
            PROMPT_VERSION,
        )
        from smhai_backend.domains.research_general_education.service import (
            ResearchGeneralEducationPolicyPins,
            canonical_input_context_sha256,
        )

        if (
            type(row) is not ResearchEducationInputReviewDTO
            or type(row.scope) is not ResearchEducationInputReviewScope
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research education input review metadata is unavailable",
            )
        if (
            row.policy_version != _POLICY_VERSION
            or row.policy_hash != self.policy_hash
            or row.source_package_ref != self.source_package_ref
            or row.source_study_ref != self.source_study_ref
            or row.source_manifest_sha256 != self.source_manifest_sha256
            or row.prompt_id != PROMPT_ID
            or row.prompt_version != PROMPT_VERSION
            or row.prompt_sha256 != PROMPT_SHA256
        ):
            raise _conflict()
        if (
            not isinstance(row.job_ref, str)
            or re.fullmatch(r"^REJ_[0-9a-f]{64}$", row.job_ref) is None
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research education input review metadata is unavailable",
            )
        expected_trace = "TRACE_" + hashlib.sha256(
            f"{row.job_ref}:1".encode("ascii")
        ).hexdigest()[:32]
        if (
            not isinstance(row.canonical_input_sha256, str)
            or _SHA256.fullmatch(row.canonical_input_sha256) is None
            or not isinstance(row.policy_hash, str)
            or _SHA256.fullmatch(row.policy_hash) is None
            or not isinstance(row.source_manifest_sha256, str)
            or _SHA256.fullmatch(row.source_manifest_sha256) is None
            or row.safety_operation != "INPUT"
            or row.safety_action != "REVIEW_REQUIRED"
            or row.safety_reason_code != "CONTENT_CONTROVERSIAL"
            or row.safety_requires_human is not True
            or not isinstance(row.decision_id, str)
            or _SAFETY_REF.fullmatch(row.decision_id) is None
            or not isinstance(row.safety_review_ref, str)
            or _SAFETY_REF.fullmatch(row.safety_review_ref) is None
            or not isinstance(row.safety_trace_id, str)
            or not row.safety_trace_id
            or valid_correlation_id(row.safety_trace_id, "TRACE") != row.safety_trace_id
            or row.safety_trace_id != row.trace_id
            or row.trace_id != expected_trace
            or not isinstance(row.status, str)
            or row.status not in {"PENDING", "REJECTED", "REVOKED"}
            or type(row.state_version) is not int
            or (row.status == "PENDING") != (row.state_version == 1)
            or (row.status in {"REJECTED", "REVOKED"}) != (row.state_version == 2)
            or not isinstance(row.expires_at, datetime)
            or not isinstance(row.created_at, datetime)
            or not isinstance(row.updated_at, datetime)
            or not isinstance(row.input_review_ref, str)
            or not isinstance(row.job_ref, str)
            or not isinstance(row.trace_id, str)
            or _SAFE_REF.fullmatch(row.input_review_ref) is None
            or valid_correlation_id(row.trace_id, "TRACE") != row.trace_id
            or row.expires_at.tzinfo is None
            or row.created_at.tzinfo is None
            or row.updated_at.tzinfo is None
            or row.expires_at <= row.created_at
            or row.expires_at > row.created_at + timedelta(hours=24)
            or row.updated_at < row.created_at
            or (
                row.status == "PENDING"
                and (row.resolved_at is not None or row.resolved_by_membership_role_id is not None)
            )
            or (
                row.status in {"REJECTED", "REVOKED"}
                and (
                    not isinstance(row.resolved_at, datetime)
                    or row.resolved_at.tzinfo is None
                    or type(row.resolved_by_membership_role_id) is not int
                    or row.resolved_by_membership_role_id <= 0
                )
            )
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research education input review metadata is unavailable",
            )
        try:
            expected_digest = canonical_input_context_sha256(
                policy_pins=ResearchGeneralEducationPolicyPins(
                    policy_hash=row.policy_hash,
                    source_package_ref=row.source_package_ref,
                    source_study_ref=row.source_study_ref,
                    source_manifest_sha256=row.source_manifest_sha256,
                )
            )
        except (TypeError, ValueError):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research education input review metadata is unavailable",
            ) from None
        if row.canonical_input_sha256 != expected_digest:
            raise _conflict()

    async def _current_input_review(self, uow, actor, task, row, *, at, lock=False):
        m = self._db_models
        self._input_review_pins(row)
        scope = row.scope
        if (
            scope.school_id != actor.school_id
            or scope.task_id != task.id
            or scope.response_origin != "PUBLIC_OBSERVED"
        ):
            raise _not_found()
        session_ref = await self._session_ref(
            uow, actor, task, scope.research_session_id
        )
        current_scope, _metadata, _retention, _profile, _pin = await self._current_scope(
            uow,
            actor,
            task,
            session_ref=session_ref,
            at=at,
            lock=lock,
        )
        if (
            current_scope.response_origin != "PUBLIC_OBSERVED"
            or not self._same_scope(scope, current_scope)
        ):
            raise _conflict()

        statement = self._select(
            m.SchoolResearchEducationJob.job_ref,
            m.SchoolResearchEducationJob.research_session_id,
            m.SchoolResearchEducationJob.school_id,
            m.SchoolResearchEducationJob.task_id,
            m.SchoolResearchEducationJob.attempt_count,
            m.SchoolResearchEducationJob.class_id,
            m.SchoolResearchEducationJob.task_enrollment_id,
            m.SchoolResearchEducationJob.subject_id,
            m.SchoolResearchEducationJob.task_binding_id,
            m.SchoolResearchEducationJob.profile_version_id,
            m.SchoolResearchEducationJob.profile_ref,
            m.SchoolResearchEducationJob.profile_version_number,
            m.SchoolResearchEducationJob.profile_sha256,
            m.SchoolResearchEducationJob.response_origin,
            m.SchoolResearchEducationJob.status,
            m.SchoolResearchEducationJob.last_error_code,
            m.SchoolResearchEducationJob.policy_version,
            m.SchoolResearchEducationJob.policy_hash,
            m.SchoolResearchEducationJob.purpose,
            m.SchoolResearchEducationJob.research_only,
            m.SchoolResearchEducationJob.publication_status,
        ).where(
            m.SchoolResearchEducationJob.id == row.job_id,
            m.SchoolResearchEducationJob.job_ref == row.job_ref,
            m.SchoolResearchEducationJob.research_session_id == scope.research_session_id,
            m.SchoolResearchEducationJob.school_id == scope.school_id,
            m.SchoolResearchEducationJob.task_id == scope.task_id,
        )
        if lock:
            statement = statement.with_for_update()
        job = (await uow.session.execute(statement)).first()
        if job is None:
            raise _not_found()
        expected_job = (
            row.job_ref,
            scope.research_session_id,
            scope.school_id,
            scope.task_id,
            1,
            scope.class_id,
            scope.task_enrollment_id,
            scope.subject_id,
            scope.task_binding_id,
            scope.profile_version_id,
            scope.profile_ref,
            scope.profile_version_number,
            scope.profile_sha256,
            scope.response_origin,
            "REVIEW_REQUIRED",
            "SAFETY_BLOCKED",
            _POLICY_VERSION,
            self.policy_hash,
            "RESEARCH_SIMULATION",
            True,
            "not_approved_for_publication_or_operational_use",
        )
        if tuple(job) != expected_job:
            raise _conflict()
        return current_scope, session_ref

    @staticmethod
    def _input_review_summary(row, *, task_ref: str, session_ref: str) -> dict:
        return {
            "input_review_ref": row.input_review_ref,
            "job_ref": row.job_ref,
            "task_ref": task_ref,
            "session_ref": session_ref,
            "status": row.status,
            "state_version": row.state_version,
            "expires_at": row.expires_at,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "reason_codes": [row.safety_reason_code],
            "purpose": "RESEARCH_SIMULATION",
            "research_only": True,
            "continuation_enabled": False,
        }

    def _input_review_detail(self, row, *, task_ref: str, session_ref: str) -> dict:
        from smhai_backend.domains.research_general_education.prompt import (
            FIXED_GENERAL_EDUCATION_REQUEST,
        )

        return {
            **self._input_review_summary(row, task_ref=task_ref, session_ref=session_ref),
            "fixed_request": FIXED_GENERAL_EDUCATION_REQUEST,
            "canonical_input_sha256": row.canonical_input_sha256,
            "policy_version": row.policy_version,
            "policy_hash": row.policy_hash,
            "source_package_ref": row.source_package_ref,
            "source_study_ref": row.source_study_ref,
            "source_manifest_sha256": row.source_manifest_sha256,
            "prompt_id": row.prompt_id,
            "prompt_version": row.prompt_version,
            "prompt_sha256": row.prompt_sha256,
        }

    async def school_research_education_input_review_list(
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
            raise error(ErrorCode.VALIDATION_FAILED, detail="input review pagination is invalid")
        now, _db_now = self._now()
        async with self._uow() as uow:
            task, _binding, _role_id = await self._active_task(
                uow, actor, task_ref, at=now
            )
            rows = await _input_review_repo_call(
                uow.research_education_input_reviews.list_for_task(
                    school_id=actor.school_id,
                    task_id=task.id,
                    offset=offset,
                    limit=limit + 1,
                )
            )
            if type(rows) is not list or len(rows) > limit + 1:
                raise error(
                    ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                    detail="research education input review metadata is unavailable",
                )
            projections = []
            for row in rows:
                _scope, session_ref = await self._current_input_review(
                    uow, actor, task, row, at=now
                )
                projections.append(
                    self._input_review_summary(row, task_ref=task_ref, session_ref=session_ref)
                )
            return {
                "items": projections[:limit],
                "offset": offset,
                "limit": limit,
                "has_more": len(rows) > limit,
            }

    async def school_research_education_input_review_get(
        self, actor, task_ref: str, input_review_ref: str
    ) -> dict:
        self._require_enabled()
        task_ref = self._input_review_ref(task_ref, "task_ref")
        input_review_ref = self._input_review_ref(input_review_ref, "input_review_ref")
        now, _db_now = self._now()
        async with self._uow() as uow:
            task, _binding, _role_id = await self._active_task(
                uow, actor, task_ref, at=now
            )
            row = await _input_review_repo_call(
                uow.research_education_input_reviews.get_for_task(
                    school_id=actor.school_id,
                    task_id=task.id,
                    input_review_ref=input_review_ref,
                )
            )
            if row is None:
                raise _not_found()
            _scope, session_ref = await self._current_input_review(
                uow, actor, task, row, at=now
            )
            return self._input_review_detail(row, task_ref=task_ref, session_ref=session_ref)

    async def school_research_education_input_review_resolve(
        self,
        actor,
        task_ref: str,
        input_review_ref: str,
        *,
        expected_state_version: int,
        target: str,
        idempotency,
        trace_id: str,
    ) -> dict:
        self._require_enabled()
        task_ref = self._input_review_ref(task_ref, "task_ref")
        input_review_ref = self._input_review_ref(input_review_ref, "input_review_ref")
        if (
            type(expected_state_version) is not int
            or expected_state_version < 1
            or expected_state_version > 2_147_483_647
            or type(target) is not str
            or target not in {"REJECTED", "REVOKED"}
            or valid_correlation_id(trace_id, "TRACE") != trace_id
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="input review resolution is invalid")
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
            row = await _input_review_repo_call(
                uow.research_education_input_reviews.get_for_task(
                    school_id=actor.school_id,
                    task_id=task.id,
                    input_review_ref=input_review_ref,
                )
            )
            if row is None:
                raise _not_found()
            _scope, session_ref = await self._current_input_review(
                uow, actor, task, row, at=now, lock=True
            )
            if row.expires_at <= now:
                raise _conflict()

            claim = await self._school_idempotency_begin(uow, idempotency)
            if claim.replayed:
                receipt_ref = await self._receipt_resource(claim, _INPUT_REVIEW_RESOURCE)
                if receipt_ref != row.input_review_ref:
                    raise _conflict()
                current = await _input_review_repo_call(
                    uow.research_education_input_reviews.get_for_task(
                        school_id=actor.school_id,
                        task_id=task.id,
                        input_review_ref=input_review_ref,
                    )
                )
                if current is None:
                    raise _not_found()
                _scope, session_ref = await self._current_input_review(
                    uow, actor, task, current, at=now, lock=True
                )
                if (
                    current.status != target
                    or current.state_version != expected_state_version + 1
                    or current.resolved_by_membership_role_id != role_id
                    or current.expires_at <= now
                ):
                    raise _conflict()
                return self._input_review_summary(
                    current, task_ref=task_ref, session_ref=session_ref
                )

            repository = uow.research_education_input_reviews
            resolver = repository.reject if target == "REJECTED" else repository.revoke
            updated = await _input_review_repo_call(
                resolver(
                    input_review_ref=input_review_ref,
                    scope=row.scope,
                    expected_state_version=expected_state_version,
                    actor_membership_role_id=role_id,
                    trace_id=trace_id,
                    now=now,
                )
            )
            self._input_review_pins(updated)
            if (
                updated.status != target
                or updated.state_version != expected_state_version + 1
                or updated.resolved_by_membership_role_id != role_id
            ):
                raise error(
                    ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                    detail="research education input review metadata is unavailable",
                )
            await self._audit_research(
                uow,
                actor_account_id=actor_account_id,
                action=f"school_research_education_input_review.{target.lower()}",
                resource_type=_INPUT_REVIEW_RESOURCE,
                resource_ref=updated.input_review_ref,
                trace_id=trace_id,
                state=updated.status,
            )
            await self._school_idempotency_complete(
                uow,
                claim,
                resource_type=_INPUT_REVIEW_RESOURCE,
                result_ref=updated.input_review_ref,
            )
            return self._input_review_summary(
                updated, task_ref=task_ref, session_ref=session_ref
            )
