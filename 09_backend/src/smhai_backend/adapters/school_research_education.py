"""Persistence and live-scope adapters for research education jobs.

The authorization query selects metadata columns only. It does not load the
encrypted CAT snapshot, profile payload, or binding config. A current trusted
study-use policy is required before a session can be terminally abstained.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from smhai_backend.domains.school_research.study_use import (
    ResearchStudyProfilePin,
    ResearchStudyUsePolicy,
)
from smhai_backend.domains.school_research_education.service import (
    RESEARCH_EDUCATION_POLICY_VERSION,
    ResearchEducationAuthorizationUnavailable,
    ResearchEducationWorker,
)

_LOGGER = logging.getLogger(__name__)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PUBLICATION_NOT_APPROVED = "not_approved_for_publication_or_operational_use"


@dataclass(slots=True)
class _WorkerHealth:
    status: str
    failure_code: str | None = None


class SchoolResearchEducationPersistenceAdapter:
    """Expose synthetic school pollers and create fresh per-school auth gates."""

    def __init__(self, persistence: Any, *, study_use_policy: ResearchStudyUsePolicy | None):
        self.persistence = persistence
        self.study_use_policy = study_use_policy

    async def active_school_ids(self) -> list[int]:
        persistence = self.persistence
        if getattr(persistence, "identity_profile", None) != "school_tenant" or not getattr(
            persistence, "_started", False
        ):
            raise RuntimeError("research education persistence is not ready")
        m = persistence._db_models
        async with persistence._uow() as uow:
            result = await uow.session.scalars(
                persistence._select(m.School.id)
                .where(
                    m.School.status == "ACTIVE",
                    m.School.data_origin == "SYNTHETIC",
                )
                .order_by(m.School.id)
            )
            return [int(value) for value in result.all()]

    def authorization_for_school(self, school_id: int) -> SchoolResearchEducationLiveAuthorization:
        return SchoolResearchEducationLiveAuthorization(
            self.persistence,
            school_id=school_id,
            study_use_policy=self.study_use_policy,
        )


class SchoolResearchEducationLiveAuthorization:
    """Atomically recheck current metadata and finish under the live lease."""

    def __init__(
        self,
        persistence: Any,
        *,
        school_id: int,
        study_use_policy: ResearchStudyUsePolicy | None,
    ) -> None:
        if type(school_id) is not int or school_id <= 0:
            raise ValueError("school_id must be positive")
        self.persistence = persistence
        self.school_id = school_id
        self.study_use_policy = study_use_policy

    async def finalize_no_policy(self, claim: Any, *, now: datetime) -> str:
        """Freshly reauthorize and finish without starting any generation path."""
        if not _valid_claim(claim, self.school_id) or not _aware_utc(now):
            raise ResearchEducationAuthorizationUnavailable()
        persistence = self.persistence
        if getattr(persistence, "identity_profile", None) != "school_tenant" or not getattr(
            persistence, "_started", False
        ):
            raise ResearchEducationAuthorizationUnavailable()
        policy = self.study_use_policy
        if type(policy) is not ResearchStudyUsePolicy or policy.source_rights_verified is not True:
            raise ResearchEducationAuthorizationUnavailable()

        try:
            async with persistence._uow() as uow:
                current = await self._scope_is_current(uow, claim, now=now, policy=policy)
                from database_layer.school_research_education_jobs import (
                    ResearchEducationJobErrorCode,
                )

                await uow.research_education_jobs.finish(
                    school_id=claim.school_id,
                    research_session_id=claim.research_session_id,
                    job_id=claim.id,
                    lease_owner=claim.lease_owner,
                    lease_token=claim.lease_token,
                    status="ABSTAINED" if current else "CANCELLED",
                    error_code=(
                        ResearchEducationJobErrorCode.POLICY_UNAVAILABLE if current else None
                    ),
                    now=now,
                )
                return "ABSTAINED" if current else "CANCELLED"
        except ResearchEducationAuthorizationUnavailable:
            raise
        except Exception:
            # Roll back current-scope reads and never leak SQL/row/driver text.
            raise ResearchEducationAuthorizationUnavailable() from None

    async def _scope_is_current(
        self,
        uow: Any,
        claim: Any,
        *,
        now: datetime,
        policy: ResearchStudyUsePolicy,
    ) -> bool:
        owner = self.persistence
        m = owner._db_models
        session = m.SchoolResearchSession
        task = m.MeasurementTask
        school_class = m.SchoolClass
        enrollment = m.TaskEnrollment
        roster = m.SchoolClassStudent
        subject = m.Subject
        school = m.School
        binding = m.SchoolResearchTaskBinding
        profile = m.SchoolResearchProfileVersion
        grant = m.SubjectAccessGrant
        membership = m.AccountSchoolMembership
        membership_role = m.MembershipRole
        account = m.Account
        role = m.Role
        cohort = m.SchoolResearchCohort

        # Deliberately select individual non-sensitive columns. Selecting ORM
        # rows here would also load encrypted snapshots and payloads.
        columns = (
            session.id.label("session_id"),
            session.school_id.label("session_school_id"),
            session.task_id.label("session_task_id"),
            session.class_id.label("session_class_id"),
            session.task_enrollment_id.label("session_enrollment_id"),
            session.subject_id.label("session_subject_id"),
            session.task_binding_id.label("session_binding_id"),
            session.profile_version_id.label("session_profile_version_id"),
            session.profile_ref.label("session_profile_ref"),
            session.profile_version_number.label("session_profile_version_number"),
            session.profile_sha256.label("session_profile_sha256"),
            session.response_origin.label("session_response_origin"),
            session.status.label("session_status"),
            session.completed_at.label("session_completed_at"),
            session.purpose.label("session_purpose"),
            session.research_only.label("session_research_only"),
            task.id.label("task_id"),
            task.school_id.label("task_school_id"),
            task.class_id.label("task_class_id"),
            task.status.label("task_status"),
            task.cat_binding_mode.label("task_mode"),
            task.opens_at.label("task_opens_at"),
            task.due_at.label("task_due_at"),
            school.id.label("school_id"),
            school.status.label("school_status"),
            school.data_origin.label("school_data_origin"),
            school_class.id.label("class_id"),
            school_class.school_id.label("class_school_id"),
            school_class.status.label("class_status"),
            enrollment.id.label("enrollment_id"),
            enrollment.school_id.label("enrollment_school_id"),
            enrollment.task_id.label("enrollment_task_id"),
            enrollment.class_id.label("enrollment_class_id"),
            enrollment.class_student_id.label("enrollment_roster_id"),
            enrollment.subject_id.label("enrollment_subject_id"),
            enrollment.status.label("enrollment_status"),
            enrollment.revoked_at.label("enrollment_revoked_at"),
            roster.id.label("roster_id"),
            roster.school_id.label("roster_school_id"),
            roster.class_id.label("roster_class_id"),
            roster.subject_id.label("roster_subject_id"),
            roster.status.label("roster_status"),
            roster.valid_from.label("roster_valid_from"),
            roster.valid_until.label("roster_valid_until"),
            roster.revoked_at.label("roster_revoked_at"),
            subject.id.label("subject_id"),
            subject.school_id.label("subject_school_id"),
            subject.status.label("subject_status"),
            subject.data_origin.label("subject_data_origin"),
            grant.id.label("grant_id"),
            grant.principal_account_id.label("principal_account_id"),
            grant.relationship_type.label("grant_relationship"),
            grant.status.label("grant_status"),
            grant.valid_from.label("grant_valid_from"),
            grant.valid_until.label("grant_valid_until"),
            grant.revoked_at.label("grant_revoked_at"),
            membership.id.label("membership_id"),
            membership.school_id.label("membership_school_id"),
            membership.account_id.label("membership_account_id"),
            membership.status.label("membership_status"),
            membership.valid_from.label("membership_valid_from"),
            membership.valid_until.label("membership_valid_until"),
            membership.revoked_at.label("membership_revoked_at"),
            membership_role.id.label("membership_role_id"),
            membership_role.school_id.label("membership_role_school_id"),
            membership_role.membership_id.label("membership_role_membership_id"),
            membership_role.role_code.label("membership_role_code"),
            membership_role.status.label("membership_role_status"),
            membership_role.valid_from.label("membership_role_valid_from"),
            membership_role.valid_until.label("membership_role_valid_until"),
            membership_role.revoked_at.label("membership_role_revoked_at"),
            role.status.label("global_role_status"),
            account.status.label("account_status"),
            binding.id.label("binding_id"),
            binding.school_id.label("binding_school_id"),
            binding.task_id.label("binding_task_id"),
            binding.class_id.label("binding_class_id"),
            binding.profile_version_id.label("binding_profile_version_id"),
            binding.profile_ref.label("binding_profile_ref"),
            binding.profile_version_number.label("binding_profile_version_number"),
            binding.profile_sha256.label("binding_profile_sha256"),
            binding.response_origin.label("binding_response_origin"),
            binding.status.label("binding_status"),
            binding.revoked_at.label("binding_revoked_at"),
            binding.purpose.label("binding_purpose"),
            binding.research_only.label("binding_research_only"),
            binding.cohort_id.label("binding_cohort_id"),
            profile.id.label("profile_version_id"),
            profile.school_id.label("profile_school_id"),
            profile.profile_ref.label("profile_ref"),
            profile.version_number.label("profile_version_number"),
            profile.profile_sha256.label("profile_sha256"),
            profile.parameter_origin.label("profile_parameter_origin"),
            profile.rights_status.label("profile_rights_status"),
            profile.execution_status.label("profile_execution_status"),
            profile.research_only.label("profile_research_only"),
            profile.human_curated.label("profile_human_curated"),
            profile.psychological_interpretation_allowed.label("profile_interpretation_allowed"),
            profile.publication_status.label("profile_publication_status"),
            profile.simulation_enabled_at.label("profile_simulation_enabled_at"),
            profile.rights_revoked_at.label("profile_rights_revoked_at"),
            profile.disabled_at.label("profile_disabled_at"),
            profile.fit_sha256.label("profile_fit_sha256"),
            profile.calibration_sha256.label("profile_calibration_sha256"),
            profile.manifest_sha256.label("profile_manifest_sha256"),
            profile.published_parameter_crosswalk_sha256.label("profile_crosswalk_sha256"),
            cohort.id.label("cohort_id"),
            cohort.school_id.label("cohort_school_id"),
            cohort.study_ref.label("cohort_study_ref"),
            cohort.status.label("cohort_status"),
            cohort.purpose.label("cohort_purpose"),
            cohort.research_only.label("cohort_research_only"),
        )
        statement = (
            owner._select(*columns)
            .select_from(session)
            .join(
                task,
                (task.id == session.task_id)
                & (task.school_id == session.school_id)
                & (task.class_id == session.class_id),
            )
            .join(school, school.id == session.school_id)
            .join(
                school_class,
                (school_class.id == session.class_id)
                & (school_class.school_id == session.school_id),
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
                subject,
                (subject.id == session.subject_id) & (subject.school_id == session.school_id),
            )
            .join(
                binding,
                (binding.id == session.task_binding_id)
                & (binding.school_id == session.school_id)
                & (binding.task_id == session.task_id)
                & (binding.class_id == session.class_id)
                & (binding.profile_version_id == session.profile_version_id)
                & (binding.profile_ref == session.profile_ref)
                & (binding.profile_version_number == session.profile_version_number)
                & (binding.profile_sha256 == session.profile_sha256)
                & (binding.response_origin == session.response_origin),
            )
            .join(
                profile,
                (profile.id == binding.profile_version_id)
                & (profile.school_id == binding.school_id)
                & (profile.profile_ref == binding.profile_ref)
                & (profile.version_number == binding.profile_version_number)
                & (profile.profile_sha256 == binding.profile_sha256),
            )
            .join(
                grant,
                (grant.subject_id == subject.id)
                & (grant.school_id == subject.school_id)
                & (grant.relationship_type == "SELF"),
            )
            .join(
                membership,
                (membership.account_id == grant.principal_account_id)
                & (membership.school_id == grant.school_id),
            )
            .join(
                membership_role,
                (membership_role.membership_id == membership.id)
                & (membership_role.school_id == membership.school_id)
                & (membership_role.role_code == "student"),
            )
            .join(role, role.role_code == membership_role.role_code)
            .join(account, account.id == membership.account_id)
            .outerjoin(
                cohort,
                (cohort.id == binding.cohort_id) & (cohort.school_id == binding.school_id),
            )
            .where(
                session.id == claim.research_session_id,
                session.school_id == claim.school_id,
                session.task_id == claim.task_id,
                session.class_id == claim.class_id,
                session.task_enrollment_id == claim.task_enrollment_id,
                session.subject_id == claim.subject_id,
                session.task_binding_id == claim.task_binding_id,
                session.profile_version_id == claim.profile_version_id,
                session.profile_ref == claim.profile_ref,
                session.profile_version_number == claim.profile_version_number,
                session.profile_sha256 == claim.profile_sha256,
                session.response_origin == claim.response_origin,
                session.status == "COMPLETED",
                session.completed_at.is_not(None),
                session.purpose == "RESEARCH_SIMULATION",
                session.research_only.is_(True),
                task.status == "PUBLISHED",
                task.cat_binding_mode == "RESEARCH_PROFILE",
                task.opens_at <= _naive_utc(now),
                school.status == "ACTIVE",
                school.data_origin == "SYNTHETIC",
                school_class.status == "ACTIVE",
                enrollment.status == "ACTIVE",
                enrollment.revoked_at.is_(None),
                roster.status == "ACTIVE",
                roster.revoked_at.is_(None),
                roster.valid_from <= _naive_utc(now),
                (roster.valid_until.is_(None)) | (roster.valid_until >= _naive_utc(now)),
                subject.status == "ACTIVE",
                subject.data_origin == "SYNTHETIC",
                grant.status == "ACTIVE",
                grant.revoked_at.is_(None),
                grant.valid_from <= _naive_utc(now),
                (grant.valid_until.is_(None)) | (grant.valid_until >= _naive_utc(now)),
                membership.status == "ACTIVE",
                membership.revoked_at.is_(None),
                membership.valid_from <= _naive_utc(now),
                (membership.valid_until.is_(None)) | (membership.valid_until >= _naive_utc(now)),
                membership_role.status == "ACTIVE",
                membership_role.revoked_at.is_(None),
                membership_role.valid_from <= _naive_utc(now),
                (membership_role.valid_until.is_(None))
                | (membership_role.valid_until >= _naive_utc(now)),
                role.status == "ACTIVE",
                account.status == "ACTIVE",
                binding.status == "ACTIVE",
                binding.revoked_at.is_(None),
                binding.purpose == "RESEARCH_SIMULATION",
                binding.research_only.is_(True),
                profile.rights_status == "VERIFIED",
                profile.execution_status == "SIMULATION_ENABLED",
                profile.rights_revoked_at.is_(None),
                profile.disabled_at.is_(None),
                profile.simulation_enabled_at.is_not(None),
                profile.research_only.is_(True),
                profile.human_curated.is_(False),
                profile.psychological_interpretation_allowed.is_(False),
                profile.publication_status == _PUBLICATION_NOT_APPROVED,
                profile.parameter_origin == "PUBLISHED_ROUNDED_REFERENCE",
                profile.fit_sha256.is_(None),
                profile.calibration_sha256.is_(None),
                profile.published_parameter_crosswalk_sha256.is_not(None),
                binding.response_origin == "PUBLIC_OBSERVED",
            )
            .limit(2)
            .execution_options(populate_existing=True)
        )
        result = await uow.session.execute(statement)
        rows = result.all()
        if len(rows) != 1:
            return False
        row = rows[0]._mapping
        if not _mapping_matches_claim(row, claim, policy, now):
            return False

        if row["binding_cohort_id"] is not None:
            if (
                row["cohort_id"] != row["binding_cohort_id"]
                or row["cohort_school_id"] != claim.school_id
                or row["cohort_status"] != "SEALED"
                or row["cohort_purpose"] != "RESEARCH_SIMULATION"
                or row["cohort_research_only"] is not True
                or row["cohort_study_ref"] != policy.study_ref
            ):
                return False
        return True


class SchoolResearchEducationWorkerManager:
    """Manage per-school research pollers under a caller-shared lock."""

    def __init__(
        self,
        persistence_adapter: SchoolResearchEducationPersistenceAdapter,
        *,
        settings: Any,
        concurrency_lock: asyncio.Lock,
    ) -> None:
        if not isinstance(concurrency_lock, asyncio.Lock):
            raise TypeError("a shared asyncio.Lock is required")
        self.persistence_adapter = persistence_adapter
        self.persistence = persistence_adapter.persistence
        self.study_use_policy = persistence_adapter.study_use_policy
        self.settings = settings
        self.concurrency_lock = concurrency_lock
        self.workers: dict[int, ResearchEducationWorker] = {}
        self.health: dict[int, _WorkerHealth] = {}
        self._started = False
        self._closing = False
        self._closed = False

    async def start(self) -> None:
        if self._closing or self._closed:
            raise RuntimeError("research education worker manager cannot be restarted")
        if self._started:
            return
        if (
            getattr(self.persistence, "identity_profile", None) != "school_tenant"
            or not getattr(self.persistence, "_started", False)
            or type(self.study_use_policy) is not ResearchStudyUsePolicy
            or self.study_use_policy.source_rights_verified is not True
        ):
            raise RuntimeError("research education worker requires pinned study-use policy")

        school_ids = await self.persistence_adapter.active_school_ids()
        try:
            for school_id in school_ids:
                worker = ResearchEducationWorker(
                    school_id=school_id,
                    unit_of_work_factory=self.persistence._uow,
                    authorization=self.persistence_adapter.authorization_for_school(school_id),
                    concurrency_lock=self.concurrency_lock,
                    worker_id=f"research-education-{school_id}",
                    poll_interval_seconds=self.settings.poll_interval_seconds,
                    lease_seconds=self.settings.lease_seconds,
                    max_attempts=self.settings.max_attempts,
                    clock=lambda: self.persistence._utc_now().replace(tzinfo=UTC),
                )
                self.workers[school_id] = worker
                self.health[school_id] = _WorkerHealth("RUNNING")
                task = worker.start()
                task.add_done_callback(lambda done, sid=school_id: self._worker_finished(sid, done))
        except Exception:
            await self.close()
            raise
        self._started = True

    def _worker_finished(self, school_id: int, task: asyncio.Task[Any]) -> None:
        if task.cancelled():
            if self._closing:
                self.health[school_id] = _WorkerHealth("STOPPED")
                return
            failure = "UNEXPECTED_WORKER_STOP"
        else:
            exception = task.exception()
            if exception is None:
                self.health[school_id] = _WorkerHealth(
                    "STOPPED" if self._closing else "UNAVAILABLE",
                    None if self._closing else "UNEXPECTED_WORKER_STOP",
                )
                return
            failure = "UNEXPECTED_WORKER_FAILURE"
        self.health[school_id] = _WorkerHealth("UNAVAILABLE", failure)
        _LOGGER.error(
            "school research education worker stopped",
            extra={"school_id": school_id, "failure_code": failure},
        )

    def dependency_status(self) -> dict[str, str]:
        if not self._started:
            return {"status": "STARTING", "integration": "RESEARCH_OUTBOX"}
        failed = any(item.status == "UNAVAILABLE" for item in self.health.values())
        return {
            "status": "UNAVAILABLE" if failed else "READY",
            "integration": "RESEARCH_OUTBOX",
        }

    async def close(self) -> None:
        if self._closed:
            return
        self._closing = True
        tasks = [asyncio.create_task(worker.stop(drain=True)) for worker in self.workers.values()]
        if tasks:
            drain = float(getattr(self.settings, "shutdown_drain_seconds", 10.0))
            _done, pending = await asyncio.wait(tasks, timeout=drain)
            if pending:
                for worker in self.workers.values():
                    task = worker._run_task
                    if task is not None and not task.done():
                        task.cancel()
                _done, pending = await asyncio.wait(pending, timeout=2.0)
                for task in pending:
                    task.cancel()
                if pending:
                    raise RuntimeError("research education workers did not stop")
            for task in tasks:
                if task.done() and not task.cancelled():
                    task.exception()
        for school_id in self.workers:
            if self.health[school_id].status == "RUNNING":
                self.health[school_id] = _WorkerHealth("STOPPED")
        self._started = False
        self._closed = True


def _valid_claim(claim: Any, school_id: int) -> bool:
    return (
        getattr(claim, "school_id", None) == school_id
        and type(getattr(claim, "research_session_id", None)) is int
        and type(getattr(claim, "task_id", None)) is int
        and type(getattr(claim, "class_id", None)) is int
        and type(getattr(claim, "task_enrollment_id", None)) is int
        and type(getattr(claim, "subject_id", None)) is int
        and type(getattr(claim, "task_binding_id", None)) is int
        and type(getattr(claim, "profile_version_id", None)) is int
        and getattr(claim, "policy_version", None) == RESEARCH_EDUCATION_POLICY_VERSION
        and getattr(claim, "policy_hash", None) is None
        and getattr(claim, "lease_owner", None)
        and getattr(claim, "lease_token", None)
    )


def _mapping_matches_claim(
    row: Any, claim: Any, policy: ResearchStudyUsePolicy, now: datetime
) -> bool:
    if any(
        row.get(row_name) != getattr(claim, claim_name)
        for row_name, claim_name in (
            ("session_id", "research_session_id"),
            ("session_school_id", "school_id"),
            ("session_task_id", "task_id"),
            ("session_class_id", "class_id"),
            ("session_enrollment_id", "task_enrollment_id"),
            ("session_subject_id", "subject_id"),
            ("session_binding_id", "task_binding_id"),
            ("session_profile_version_id", "profile_version_id"),
            ("session_profile_ref", "profile_ref"),
            ("session_profile_version_number", "profile_version_number"),
            ("session_profile_sha256", "profile_sha256"),
            ("session_response_origin", "response_origin"),
        )
    ):
        return False
    if (
        row["task_id"] != claim.task_id
        or row["task_school_id"] != claim.school_id
        or row["task_class_id"] != claim.class_id
        or row["school_id"] != claim.school_id
        or row["class_id"] != claim.class_id
        or row["enrollment_id"] != claim.task_enrollment_id
        or row["enrollment_school_id"] != claim.school_id
        or row["enrollment_task_id"] != claim.task_id
        or row["enrollment_class_id"] != claim.class_id
        or row["enrollment_subject_id"] != claim.subject_id
        or row["roster_id"] != row["enrollment_roster_id"]
        or row["roster_school_id"] != claim.school_id
        or row["roster_class_id"] != claim.class_id
        or row["roster_subject_id"] != claim.subject_id
        or row["subject_id"] != claim.subject_id
        or row["subject_school_id"] != claim.school_id
        or row["binding_id"] != claim.task_binding_id
        or row["binding_school_id"] != claim.school_id
        or row["binding_task_id"] != claim.task_id
        or row["binding_class_id"] != claim.class_id
        or row["binding_profile_version_id"] != claim.profile_version_id
        or row["binding_profile_ref"] != claim.profile_ref
        or row["binding_profile_version_number"] != claim.profile_version_number
        or row["binding_profile_sha256"] != claim.profile_sha256
        or row["binding_response_origin"] != claim.response_origin
        or row["profile_version_id"] != claim.profile_version_id
        or row["profile_school_id"] != claim.school_id
        or row["profile_ref"] != claim.profile_ref
        or row["profile_version_number"] != claim.profile_version_number
        or row["profile_sha256"] != claim.profile_sha256
        or row["task_status"] != "PUBLISHED"
        or row["task_mode"] != "RESEARCH_PROFILE"
        or row["school_status"] != "ACTIVE"
        or row["school_data_origin"] != "SYNTHETIC"
        or row["class_status"] != "ACTIVE"
        or row["enrollment_status"] != "ACTIVE"
        or row["enrollment_revoked_at"] is not None
        or row["roster_status"] != "ACTIVE"
        or row["roster_revoked_at"] is not None
        or row["roster_valid_from"] > _naive_utc(now)
        or (row["roster_valid_until"] is not None and row["roster_valid_until"] < _naive_utc(now))
        or row["subject_status"] != "ACTIVE"
        or row["subject_data_origin"] != "SYNTHETIC"
        or row["grant_relationship"] != "SELF"
        or row["grant_status"] != "ACTIVE"
        or row["grant_revoked_at"] is not None
        or row["grant_valid_from"] > _naive_utc(now)
        or (row["grant_valid_until"] is not None and row["grant_valid_until"] < _naive_utc(now))
        or row["membership_school_id"] != claim.school_id
        or row["membership_account_id"] != row["principal_account_id"]
        or row["membership_status"] != "ACTIVE"
        or row["membership_revoked_at"] is not None
        or row["membership_valid_from"] > _naive_utc(now)
        or (
            row["membership_valid_until"] is not None
            and row["membership_valid_until"] < _naive_utc(now)
        )
        or row["membership_role_school_id"] != claim.school_id
        or row["membership_role_membership_id"] != row["membership_id"]
        or row["membership_role_code"] != "student"
        or row["membership_role_status"] != "ACTIVE"
        or row["membership_role_revoked_at"] is not None
        or row["membership_role_valid_from"] > _naive_utc(now)
        or (
            row["membership_role_valid_until"] is not None
            and row["membership_role_valid_until"] < _naive_utc(now)
        )
        or row["global_role_status"] != "ACTIVE"
        or row["account_status"] != "ACTIVE"
        or row["binding_status"] != "ACTIVE"
        or row["binding_revoked_at"] is not None
        or row["binding_purpose"] != "RESEARCH_SIMULATION"
        or row["binding_research_only"] is not True
        or row["profile_rights_status"] != "VERIFIED"
        or row["profile_execution_status"] != "SIMULATION_ENABLED"
        or row["profile_rights_revoked_at"] is not None
        or row["profile_disabled_at"] is not None
        or row["profile_simulation_enabled_at"] is None
        or row["profile_research_only"] is not True
        or row["profile_human_curated"] is not False
        or row["profile_interpretation_allowed"] is not False
        or row["profile_publication_status"] != _PUBLICATION_NOT_APPROVED
        or row["profile_parameter_origin"] != "PUBLISHED_ROUNDED_REFERENCE"
        or row["profile_fit_sha256"] is not None
        or row["profile_calibration_sha256"] is not None
        or type(row["profile_manifest_sha256"]) is not str
        or _SHA256.fullmatch(row["profile_manifest_sha256"]) is None
        or type(row["profile_crosswalk_sha256"]) is not str
        or _SHA256.fullmatch(row["profile_crosswalk_sha256"]) is None
        or row["session_status"] != "COMPLETED"
        or row["session_completed_at"] is None
        or row["session_purpose"] != "RESEARCH_SIMULATION"
        or row["session_research_only"] is not True
        or row["session_response_origin"] != "PUBLIC_OBSERVED"
        or row["binding_response_origin"] != "PUBLIC_OBSERVED"
        or row["task_opens_at"] > _naive_utc(now)
    ):
        return False
    if not _SHA256.fullmatch(claim.profile_sha256):
        return False
    try:
        policy_window = {}
        if row["task_due_at"] is not None:
            policy_window = {
                "task_opens_at": _aware_utc_value(row["task_opens_at"]),
                "task_due_at": _aware_utc_value(row["task_due_at"]),
            }
        pin = policy.require_scope(
            school_id=claim.school_id,
            profile_ref=claim.profile_ref,
            profile_sha256=claim.profile_sha256,
            manifest_sha256=row["profile_manifest_sha256"],
            at=now,
        )
        # Processing may happen after the measurement deadline. Keep today's
        # study permission current, and validate measurement timing separately.
        completed_at = _aware_utc_value(row["session_completed_at"])
        if completed_at > now:
            return False
        policy.require_scope(
            school_id=claim.school_id,
            profile_ref=claim.profile_ref,
            profile_sha256=claim.profile_sha256,
            manifest_sha256=row["profile_manifest_sha256"],
            at=completed_at,
            **policy_window,
        )
    except Exception:
        return False
    return (
        type(pin) is ResearchStudyProfilePin
        and pin.profile_ref == claim.profile_ref
        and pin.profile_sha256 == claim.profile_sha256
        and pin.manifest_sha256 == row["profile_manifest_sha256"]
        and pin.published_crosswalk_sha256 == row["profile_crosswalk_sha256"]
    )


def _aware_utc(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() == UTC.utcoffset(value)
    )


def _aware_utc_value(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _naive_utc(value: datetime) -> datetime:
    return _aware_utc_value(value).replace(tzinfo=None)
