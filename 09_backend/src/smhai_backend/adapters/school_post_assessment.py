"""MySQL-backed lifecycle and authorization ports for the outbox worker."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC
from typing import Any, Protocol

from smhai_backend.core.config import PostAssessmentWorkerSettings
from smhai_backend.domains.post_assessment.service import (
    PostAssessmentAuthorizationFailure,
    PostAssessmentAuthorizationScope,
    PostAssessmentPersistenceFailure,
    PostAssessmentWorker,
    database_persistence_error_mapper,
)

_LOGGER = logging.getLogger(__name__)


class SchoolPostAssessmentManagerAdapter(Protocol):
    persistence: Any

    async def active_school_ids(self) -> list[int]: ...

    def authorization_for_school(self, school_id: int) -> Any: ...


class SchoolPostAssessmentPersistenceAdapter:
    """Read only school inventory and exact student authorization for jobs."""

    def __init__(self, persistence: Any) -> None:
        self.persistence = persistence

    async def active_school_ids(self) -> list[int]:
        persistence = self.persistence
        if (
            getattr(persistence, "identity_profile", None) != "school_tenant"
            or not getattr(persistence, "_started", False)
        ):
            raise RuntimeError("school post-assessment persistence is not ready")
        m = persistence._db_models
        async with persistence._uow() as uow:
            rows = await uow.session.scalars(
                persistence._select(m.School.id)
                .where(
                    m.School.status == "ACTIVE",
                    m.School.data_origin == persistence._db_enums.DataOrigin.SYNTHETIC.value,
                )
                .order_by(m.School.id)
            )
            return [int(school_id) for school_id in rows.all()]

    def authorization_for_school(self, school_id: int) -> SchoolPostAssessmentAuthorization:
        return SchoolPostAssessmentAuthorization(self.persistence, school_id=school_id)


class SchoolPostAssessmentAuthorization:
    """Recheck one assessment's full school/student scope without reading payloads."""

    def __init__(self, persistence: Any, *, school_id: int) -> None:
        self.persistence = persistence
        self.school_id = school_id

    async def is_authorized(self, scope: PostAssessmentAuthorizationScope) -> bool:
        if (
            self.persistence.identity_profile != "school_tenant"
            or not self.persistence._started
            or type(scope.school_id) is not int
            or scope.school_id != self.school_id
            or any(
                type(value) is not int or value <= 0
                for value in (
                    scope.task_id,
                    scope.class_id,
                    scope.class_student_id,
                    scope.task_enrollment_id,
                    scope.subject_id,
                    scope.assessment_session_id,
                )
            )
        ):
            return False

        persistence = self.persistence
        m = persistence._db_models
        now = persistence._utc_now()
        async with persistence._uow() as uow:
            # Fetch only the assessment reference and its exact relational scope.
            # AssessmentResponse and AssessmentResult are never selected.
            assessment_ref = await uow.session.scalar(
                persistence._select(m.AssessmentSession.assessment_ref)
                .join(
                    m.TaskEnrollment,
                    (m.TaskEnrollment.id == m.AssessmentSession.task_enrollment_id)
                    & (m.TaskEnrollment.subject_id == m.AssessmentSession.subject_id),
                )
                .where(
                    m.AssessmentSession.id == scope.assessment_session_id,
                    m.AssessmentSession.status == "COMPLETED",
                    m.AssessmentSession.completed_at.is_not(None),
                    m.AssessmentSession.task_enrollment_id == scope.task_enrollment_id,
                    m.AssessmentSession.subject_id == scope.subject_id,
                    m.TaskEnrollment.id == scope.task_enrollment_id,
                    m.TaskEnrollment.school_id == scope.school_id,
                    m.TaskEnrollment.task_id == scope.task_id,
                    m.TaskEnrollment.class_id == scope.class_id,
                    m.TaskEnrollment.class_student_id == scope.class_student_id,
                    m.TaskEnrollment.subject_id == scope.subject_id,
                    m.TaskEnrollment.status == "ACTIVE",
                    m.TaskEnrollment.revoked_at.is_(None),
                )
                .limit(1)
            )
            if not assessment_ref:
                return False

            # Resolve the current SELF principal, then reuse the DB-layer
            # completed-work predicate. It checks current account/membership/
            # roster authorization and validates the task window at completion.
            account_ids = await uow.session.scalars(
                persistence._select(m.SubjectAccessGrant.principal_account_id)
                .where(
                    m.SubjectAccessGrant.school_id == scope.school_id,
                    m.SubjectAccessGrant.subject_id == scope.subject_id,
                    m.SubjectAccessGrant.relationship_type == "SELF",
                    m.SubjectAccessGrant.status == "ACTIVE",
                    m.SubjectAccessGrant.revoked_at.is_(None),
                    m.SubjectAccessGrant.valid_from <= now,
                    (m.SubjectAccessGrant.valid_until.is_(None))
                    | (m.SubjectAccessGrant.valid_until >= now),
                )
                .distinct()
                .limit(2)
            )
            principals = [int(account_id) for account_id in account_ids.all()]
            if len(principals) != 1:
                return False

            enrollment = await uow.school_operations.completed_enrollment_for_post_assessment(
                assessment_ref=assessment_ref,
                student_account_id=principals[0],
                at=now,
            )
            return bool(
                enrollment is not None
                and enrollment.id == scope.task_enrollment_id
                and enrollment.school_id == scope.school_id
                and enrollment.task_id == scope.task_id
                and enrollment.class_id == scope.class_id
                and enrollment.class_student_id == scope.class_student_id
                and enrollment.subject_id == scope.subject_id
            )


@dataclass(slots=True)
class _WorkerHealth:
    status: str
    failure_code: str | None = None


class SchoolPostAssessmentWorkerManager:
    """Start per-school pollers with shared single concurrency and bounded drain."""

    def __init__(
        self,
        persistence_adapter: SchoolPostAssessmentManagerAdapter,
        settings: PostAssessmentWorkerSettings,
    ) -> None:
        self.persistence_adapter = persistence_adapter
        self.persistence = persistence_adapter.persistence
        self.settings = settings
        self.workers: dict[int, PostAssessmentWorker] = {}
        self.health: dict[int, _WorkerHealth] = {}
        self._global_lock = asyncio.Lock()
        self._started = False
        self._closing = False
        self._closed = False

    @property
    def concurrency_lock(self) -> asyncio.Lock:
        """Expose the shared single-slot lock for other local worker lanes."""
        return self._global_lock

    async def start(self) -> None:
        if self._closing or self._closed:
            raise RuntimeError("school post-assessment worker manager cannot be restarted")
        if self._started:
            return
        if (
            self.persistence.identity_profile != "school_tenant"
            or not self.persistence._started
        ):
            raise RuntimeError("school post-assessment worker requires a ready MySQL adapter")

        # Missing database classes/enums are fatal here; no string-code fallback.
        persistence_errors = database_persistence_error_mapper()
        school_ids = await self.persistence_adapter.active_school_ids()
        for school_id in school_ids:
            worker = PostAssessmentWorker(
                school_id=school_id,
                unit_of_work_factory=self.persistence._uow,
                authorization=self.persistence_adapter.authorization_for_school(school_id),
                persistence_errors=persistence_errors,
                worker_id=f"post-assessment-{school_id}",
                policy_version=self.settings.policy_version,
                poll_interval_seconds=self.settings.poll_interval_seconds,
                lease_seconds=self.settings.lease_seconds,
                heartbeat_interval_seconds=self.settings.heartbeat_interval_seconds,
                max_attempts=self.settings.max_attempts,
                clock=lambda: self._aware_now(),
                concurrency_lock=self._global_lock,
            )
            self.workers[school_id] = worker
            self.health[school_id] = _WorkerHealth("RUNNING")
            task = worker.start()
            task.add_done_callback(
                lambda completed, sid=school_id: self._worker_finished(sid, completed)
            )
        self._started = True

    def _aware_now(self):
        # Database ``utc_now`` deliberately returns naive UTC for DATETIME(6).
        return self.persistence._utc_now().replace(tzinfo=UTC)

    def _worker_finished(self, school_id: int, task: asyncio.Task) -> None:
        if task.cancelled():
            if self._closing:
                self.health[school_id] = _WorkerHealth("STOPPED")
                return
            failure_code = "UNEXPECTED_WORKER_STOP"
            self.health[school_id] = _WorkerHealth("UNAVAILABLE", failure_code)
            _LOGGER.error(
                "school post-assessment worker stopped",
                extra={"school_id": school_id, "failure_code": failure_code},
            )
            return
        exception = task.exception()
        if exception is None:
            self.health[school_id] = _WorkerHealth(
                "STOPPED" if self._closing else "UNAVAILABLE",
                None if self._closing else "UNEXPECTED_WORKER_STOP",
            )
            return
        if isinstance(exception, PostAssessmentAuthorizationFailure):
            failure_code = "AUTHORIZATION_FAILURE"
        elif isinstance(exception, PostAssessmentPersistenceFailure):
            failure_code = f"PERSISTENCE_{exception.stage.value}"
        else:
            failure_code = "UNEXPECTED_WORKER_FAILURE"
        self.health[school_id] = _WorkerHealth("UNAVAILABLE", failure_code)
        _LOGGER.error(
            "school post-assessment worker stopped",
            extra={"school_id": school_id, "failure_code": failure_code},
        )

    def dependency_status(self) -> dict[str, str]:
        if not self._started:
            return {"status": "STARTING", "integration": "LOCAL_OUTBOX"}
        failed = any(value.status == "UNAVAILABLE" for value in self.health.values())
        return {
            "status": "UNAVAILABLE" if failed else "READY",
            "integration": "LOCAL_OUTBOX",
        }

    async def close(self) -> None:
        if self._closed:
            return
        if not self.workers:
            self._closing = True
            self._started = False
            self._closed = True
            return
        self._closing = True
        stop_owners = {
            asyncio.create_task(worker.stop(drain=True)): school_id
            for school_id, worker in self.workers.items()
        }
        _done, pending = await asyncio.wait(
            set(stop_owners), timeout=self.settings.shutdown_drain_seconds
        )
        if pending:
            _LOGGER.warning(
                "school post-assessment drain expired; cancelling workers",
                extra={"pending_workers": len(pending)},
            )
            for worker in self.workers.values():
                task = worker._run_task
                if task is not None and not task.done():
                    task.cancel()
            _done, still_pending = await asyncio.wait(pending, timeout=2.0)
            for task in still_pending:
                task.cancel()
            if still_pending:
                _LOGGER.error(
                    "school post-assessment workers did not stop after cancellation",
                    extra={"pending_workers": len(still_pending)},
                )
                for task in still_pending:
                    self.health[stop_owners[task]] = _WorkerHealth(
                        "UNAVAILABLE", "SHUTDOWN_CANCEL_UNCONFIRMED"
                    )
                # Do not let BackendContainer proceed to close the DB while a
                # poller may still be inside a UoW. Raising keeps shutdown
                # fail-closed; lease expiry remains the recovery mechanism.
                raise RuntimeError("school post-assessment workers did not stop")
        for task in stop_owners:
            if task.done() and not task.cancelled():
                try:
                    task.result()
                except PostAssessmentPersistenceFailure as exc:
                    _LOGGER.error(
                        "school post-assessment shutdown persistence failure",
                        extra={"failure_code": f"PERSISTENCE_{exc.stage.value}"},
                    )
                except Exception:
                    _LOGGER.error(
                        "school post-assessment shutdown failed",
                        extra={"failure_code": "SHUTDOWN_FAILURE"},
                    )
        for school_id in self.workers:
            if self.health[school_id].status == "RUNNING":
                self.health[school_id] = _WorkerHealth("STOPPED")
        self._started = False
        self._closed = True
