"""Lifecycle manager for the explicitly configured held-draft worker."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from .worker import ResearchGeneralEducationWorker

_LOGGER = logging.getLogger(__name__)


class ResearchGeneralEducationWorkerManager:
    """Run one bounded poller for the configured synthetic school only."""

    def __init__(
        self,
        *,
        persistence: Any,
        persistence_adapter: Any,
        generation_service: Any,
        settings: Any,
        concurrency_lock: asyncio.Lock,
        source_valid_through: datetime,
    ) -> None:
        if not isinstance(concurrency_lock, asyncio.Lock):
            raise TypeError("a shared worker concurrency lock is required")
        if (
            not isinstance(source_valid_through, datetime)
            or source_valid_through.tzinfo is None
            or source_valid_through.utcoffset() is None
        ):
            raise ValueError("a timezone-aware source expiry is required")
        self.persistence = persistence
        self.persistence_adapter = persistence_adapter
        self.generation_service = generation_service
        self.settings = settings
        self.concurrency_lock = concurrency_lock
        self.source_valid_through = source_valid_through.astimezone(UTC)
        self.workers: dict[int, ResearchGeneralEducationWorker] = {}
        self.health: dict[int, str] = {}
        self._started = False
        self._closing = False
        self._closed = False

    async def start(self) -> None:
        if self._closing or self._closed:
            raise RuntimeError("general-education worker manager cannot restart")
        if self._started:
            return
        if (
            getattr(self.persistence, "identity_profile", None) != "school_tenant"
            or not getattr(self.persistence, "_started", False)
            or getattr(self.settings, "enabled", False) is not True
        ):
            raise RuntimeError(
                "general-education worker requires enabled school research persistence"
            )
        school_id = getattr(self.settings, "school_id", None)
        if type(school_id) is not int or school_id <= 0:
            raise RuntimeError("general-education worker requires a pinned school")
        if self._now() > self.source_valid_through:
            self.health[school_id] = "UNAVAILABLE"
            self._started = True
            return
        policy = getattr(self.persistence_adapter, "study_use_policy", None)
        generation_pins = getattr(self.generation_service, "policy_pins", None)
        if (
            getattr(policy, "school_id", None) != school_id
            or getattr(policy, "study_ref", None)
            != getattr(self.settings, "school_study_ref", None)
            or getattr(policy, "source_rights_verified", None) is not True
            or getattr(self.persistence_adapter, "enabled", False) is not True
            or getattr(self.persistence_adapter, "school_id", None) != school_id
            or getattr(self.persistence_adapter, "policy_hash", None)
            != getattr(self.settings, "policy_hash", None)
            or getattr(generation_pins, "policy_hash", None)
            != getattr(self.settings, "policy_hash", None)
            or getattr(generation_pins, "source_study_ref", None)
            != getattr(self.settings, "source_study_ref", None)
            or getattr(generation_pins, "source_manifest_sha256", None)
            != getattr(self.settings, "source_manifest_sha256", None)
            or getattr(generation_pins, "source_package_ref", None)
            != getattr(self.persistence_adapter, "source_package_ref", None)
            or getattr(generation_pins, "source_study_ref", None)
            != getattr(self.persistence_adapter, "source_study_ref", None)
            or getattr(generation_pins, "source_manifest_sha256", None)
            != getattr(self.persistence_adapter, "source_manifest_sha256", None)
        ):
            raise RuntimeError("general-education worker pins or source expiry are unavailable")

        models = self.persistence._db_models
        async with self.persistence._uow() as uow:
            active_school_ids = list(
                (
                    await uow.session.scalars(
                        self.persistence._select(models.School.id).where(
                            models.School.id == school_id,
                            models.School.status == "ACTIVE",
                            models.School.data_origin == "SYNTHETIC",
                        )
                    )
                ).all()
            )
        if active_school_ids != [school_id]:
            raise RuntimeError("general-education study school is unavailable")

        try:
            worker = ResearchGeneralEducationWorker(
                school_id=school_id,
                policy_hash=self.settings.policy_hash,
                persistence=self.persistence,
                persistence_adapter=self.persistence_adapter,
                generation_service=self.generation_service,
                concurrency_lock=self.concurrency_lock,
                worker_id=f"general-education-{school_id}",
                poll_interval_seconds=self.settings.poll_interval_seconds,
                lease_seconds=self.settings.lease_seconds,
                clock=lambda: self.persistence._utc_now().replace(tzinfo=UTC),
            )
            self.workers[school_id] = worker
            self.health[school_id] = "RUNNING"
            worker.start().add_done_callback(
                lambda task, sid=school_id: self._finished(sid, task)
            )
        except Exception:
            await self.close()
            raise
        self._started = True

    def _finished(self, school_id: int, task: asyncio.Task[Any]) -> None:
        if self._closing and task.cancelled():
            self.health[school_id] = "STOPPED"
            return
        try:
            failed = task.cancelled() or task.exception() is not None
        except asyncio.CancelledError:
            failed = not self._closing
        self.health[school_id] = "UNAVAILABLE" if failed or not self._closing else "STOPPED"
        if failed:
            _LOGGER.error(
                "general-education worker stopped",
                extra={"school_id": school_id, "failure_code": "UNEXPECTED_WORKER_STOP"},
            )

    def dependency_status(self) -> dict[str, str]:
        if not self._started:
            return {
                "status": "STARTING",
                "integration": "RESEARCH_GENERAL_EDUCATION_DRAFT_OUTBOX",
            }
        failed = any(status == "UNAVAILABLE" for status in self.health.values())
        return {
            "status": "UNAVAILABLE" if failed else "READY",
            "integration": "RESEARCH_GENERAL_EDUCATION_DRAFT_OUTBOX",
        }

    async def close(self) -> None:
        if self._closed:
            return
        self._closing = True
        stops = [
            asyncio.create_task(worker.stop(drain=True))
            for worker in self.workers.values()
        ]
        if stops:
            drain_seconds = float(self.settings.shutdown_drain_seconds)
            _done, pending = await asyncio.wait(stops, timeout=drain_seconds)
            if pending:
                for worker in self.workers.values():
                    if worker._task is not None and not worker._task.done():
                        worker._task.cancel()
                _done, pending = await asyncio.wait(pending, timeout=2.0)
                if pending:
                    raise RuntimeError("general-education worker did not stop")
        for school_id, state in self.health.items():
            if state == "RUNNING":
                self.health[school_id] = "STOPPED"
        self._started = False
        self._closed = True

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)


__all__ = ["ResearchGeneralEducationWorkerManager"]
