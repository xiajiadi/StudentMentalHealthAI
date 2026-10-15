from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from smhai_backend.domains.school_research_general_education_generation import (
    manager as manager_module,
)
from smhai_backend.domains.school_research_general_education_generation.manager import (
    ResearchGeneralEducationWorkerManager,
)

_POLICY_HASH = "a" * 64
_MANIFEST_HASH = "b" * 64


class _Query:
    def where(self, *_conditions):
        return self


class _Column:
    def __eq__(self, _other):
        return True


class _ScalarResult:
    def all(self):
        return [17]


class _Session:
    async def scalars(self, _query):
        return _ScalarResult()


class _UnitOfWork:
    def __init__(self):
        self.session = _Session()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


class _Persistence:
    identity_profile = "school_tenant"
    _started = True
    _db_models = SimpleNamespace(
        School=SimpleNamespace(id=_Column(), status=_Column(), data_origin=_Column())
    )

    def __init__(self):
        self.select_count = 0

    def _select(self, _column):
        return _Query()

    def _uow(self):
        self.select_count += 1
        return _UnitOfWork()

    def _utc_now(self):
        return datetime.now(UTC).replace(tzinfo=None)


class _FakeWorker:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self._task = None
        self._stopped = asyncio.Event()
        self.instances.append(self)

    def start(self):
        async def run():
            await self._stopped.wait()

        self._task = asyncio.create_task(run())
        return self._task

    async def stop(self, *, drain=True):
        self._stopped.set()
        if self._task is not None:
            await self._task


def _settings(**overrides):
    values = {
        "enabled": True,
        "school_id": 17,
        "school_study_ref": "school-study",
        "source_study_ref": "source-study",
        "source_manifest_sha256": _MANIFEST_HASH,
        "policy_hash": _POLICY_HASH,
        "input_review_continuation_enabled": False,
        "poll_interval_seconds": 1.0,
        "lease_seconds": 300,
        "shutdown_drain_seconds": 1.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _dependencies(persistence=None):
    persistence = persistence or _Persistence()
    policy = SimpleNamespace(
        school_id=17,
        study_ref="school-study",
        source_rights_verified=True,
    )
    adapter = SimpleNamespace(
        study_use_policy=policy,
        enabled=True,
        school_id=17,
        policy_hash=_POLICY_HASH,
        source_package_ref="R3_package",
        source_study_ref="source-study",
        source_manifest_sha256=_MANIFEST_HASH,
        input_review_continuation_enabled=False,
    )
    pins = SimpleNamespace(
        policy_hash=_POLICY_HASH,
        source_package_ref="R3_package",
        source_study_ref="source-study",
        source_manifest_sha256=_MANIFEST_HASH,
    )
    generation_service = SimpleNamespace(policy_pins=pins)
    return persistence, adapter, generation_service


@pytest.mark.asyncio
async def test_manager_starts_one_worker_for_exact_school_and_drains(monkeypatch):
    _FakeWorker.instances.clear()
    monkeypatch.setattr(manager_module, "ResearchGeneralEducationWorker", _FakeWorker)
    persistence, adapter, generation_service = _dependencies()
    lock = asyncio.Lock()
    manager = ResearchGeneralEducationWorkerManager(
        persistence=persistence,
        persistence_adapter=adapter,
        generation_service=generation_service,
        settings=_settings(),
        concurrency_lock=lock,
        source_valid_through=datetime.now(UTC) + timedelta(days=1),
    )

    assert manager.dependency_status() == {
        "status": "STARTING",
        "integration": "RESEARCH_GENERAL_EDUCATION_DRAFT_OUTBOX",
    }
    await manager.start()

    assert len(_FakeWorker.instances) == 1
    worker = _FakeWorker.instances[0]
    assert worker.kwargs["school_id"] == 17
    assert worker.kwargs["policy_hash"] == _POLICY_HASH
    assert worker.kwargs["concurrency_lock"] is lock
    assert worker.kwargs["input_review_continuation_enabled"] is False
    assert manager.health == {17: "RUNNING"}
    assert manager.dependency_status()["status"] == "READY"

    await manager.close()

    assert worker._task.done()
    assert manager._closed is True


@pytest.mark.asyncio
async def test_manager_only_enables_reviewed_claims_when_setting_and_adapter_allow_it(monkeypatch):
    _FakeWorker.instances.clear()
    monkeypatch.setattr(manager_module, "ResearchGeneralEducationWorker", _FakeWorker)
    persistence, adapter, generation_service = _dependencies()
    adapter.input_review_continuation_enabled = True
    manager = ResearchGeneralEducationWorkerManager(
        persistence=persistence,
        persistence_adapter=adapter,
        generation_service=generation_service,
        settings=_settings(input_review_continuation_enabled=True),
        concurrency_lock=asyncio.Lock(),
        source_valid_through=datetime.now(UTC) + timedelta(days=1),
    )

    await manager.start()

    assert len(_FakeWorker.instances) == 1
    assert _FakeWorker.instances[0].kwargs["input_review_continuation_enabled"] is True
    await manager.close()


@pytest.mark.asyncio
async def test_manager_refuses_continuation_setting_without_adapter_opt_in(monkeypatch):
    _FakeWorker.instances.clear()
    monkeypatch.setattr(manager_module, "ResearchGeneralEducationWorker", _FakeWorker)
    persistence, adapter, generation_service = _dependencies()
    manager = ResearchGeneralEducationWorkerManager(
        persistence=persistence,
        persistence_adapter=adapter,
        generation_service=generation_service,
        settings=_settings(input_review_continuation_enabled=True),
        concurrency_lock=asyncio.Lock(),
        source_valid_through=datetime.now(UTC) + timedelta(days=1),
    )

    with pytest.raises(RuntimeError, match="continuation adapter is not enabled"):
        await manager.start()

    assert persistence.select_count == 0
    assert _FakeWorker.instances == []


@pytest.mark.asyncio
async def test_expired_source_marks_unavailable_without_query_or_worker(monkeypatch):
    _FakeWorker.instances.clear()
    monkeypatch.setattr(manager_module, "ResearchGeneralEducationWorker", _FakeWorker)
    persistence, adapter, generation_service = _dependencies()
    manager = ResearchGeneralEducationWorkerManager(
        persistence=persistence,
        persistence_adapter=adapter,
        generation_service=generation_service,
        settings=_settings(),
        concurrency_lock=asyncio.Lock(),
        source_valid_through=datetime.now(UTC) - timedelta(seconds=1),
    )

    await manager.start()

    assert persistence.select_count == 0
    assert manager.workers == {}
    assert manager.health == {17: "UNAVAILABLE"}
    assert manager.dependency_status()["status"] == "UNAVAILABLE"
    assert _FakeWorker.instances == []
    await manager.close()
