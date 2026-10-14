from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from smhai_backend.adapters.school_post_assessment import SchoolPostAssessmentWorkerManager
from smhai_backend.container import _shared_worker_concurrency_lock, build_container
from smhai_backend.core.config import BackendSettings, ResearchEducationWorkerSettings


def _explicit_managed_research_settings(**overrides):
    values = {
        "_env_file": None,
        "environment": "research",
        "identity_profile": "school_tenant",
        "persistence_mode": "mysql",
        "school_csrf_secret": "a" * 64,
        "school_research_enabled": True,
        "school_research_managed_enabled": True,
        "school_research_runtime_file": "runtime.json",
        "school_research_runtime_sha256": "1" * 64,
        "school_research_base_url": "http://127.0.0.1:57419",
        "school_research_service_file": "service.json",
        "school_research_service_sha256": "2" * 64,
        "school_research_cat_python": "python.exe",
        "school_research_cat_source": "cat-source",
        "school_research_cat_dependencies": "cat-dependencies",
        "school_research_study_use_file": "study-use.json",
        "school_research_study_use_sha256": "3" * 64,
        "school_research_source_rights_verified": True,
        "school_research_latest_study_end": datetime(2027, 6, 30, tzinfo=UTC),
        "research_education_worker": {"enabled": True},
    }
    values.update(overrides)
    return BackendSettings(**values)


def test_research_education_worker_is_explicitly_disabled_by_default():
    legacy = BackendSettings(_env_file=None)
    school_mysql = BackendSettings(
        _env_file=None,
        identity_profile="school_tenant",
        persistence_mode="mysql",
        school_csrf_secret="a" * 64,
    )

    assert legacy.research_education_worker_enabled is False
    assert school_mysql.post_assessment_worker_enabled is True
    assert school_mysql.research_education_worker_enabled is False


def test_research_education_worker_requires_managed_school_mysql_and_pinned_study_use():
    with pytest.raises(ValidationError, match="requires nonproduction managed school research"):
        BackendSettings(
            _env_file=None,
            research_education_worker={"enabled": True},
        )

    with pytest.raises(ValidationError, match="requires nonproduction managed school research"):
        BackendSettings(
            _env_file=None,
            identity_profile="school_tenant",
            persistence_mode="mysql",
            school_csrf_secret="a" * 64,
            research_education_worker={"enabled": True},
        )

    configured = _explicit_managed_research_settings()
    assert configured.research_education_worker_enabled is True


@pytest.mark.parametrize(
    "values",
    [
        {"enabled": "yes"},
        {"enabled": 1},
        {"enabled": True, "unexpected": True},
        {"poll_interval_seconds": True},
        {"poll_interval_seconds": float("nan")},
        {"lease_seconds": "60"},
        {"lease_seconds": True},
        {"max_attempts": 21},
        {"max_attempts": True},
        {"shutdown_drain_seconds": float("inf")},
    ],
)
def test_research_education_worker_rejects_unbounded_or_non_strict_settings(values):
    with pytest.raises(ValidationError):
        ResearchEducationWorkerSettings.model_validate(values)


def test_research_education_worker_cannot_be_enabled_in_production():
    with pytest.raises(ValidationError):
        _explicit_managed_research_settings(environment="production")


def test_disabled_worker_does_not_create_a_manager():
    container = build_container(BackendSettings(_env_file=None))

    assert container.research_education_worker_manager is None


def test_explicit_enable_builds_manager_with_the_legacy_workers_shared_lock(monkeypatch):
    import importlib

    database_module = importlib.import_module("smhai_backend.adapters.database")
    bootstrap_module = importlib.import_module("smhai_backend.domains.school_research.bootstrap")
    research_lifecycle = importlib.import_module("smhai_backend.domains.school_research.lifecycle")
    persistence = type(
        "Persistence",
        (),
        {"identity_profile": "school_tenant", "_started": False},
    )()
    monkeypatch.setattr(database_module, "MySqlBackendAdapter", lambda **_kwargs: persistence)
    for name in (
        "build_school_research_cohorts_service",
        "build_school_research_discovery_service",
        "build_school_research_profiles_service",
        "build_school_research_service",
        "build_school_research_tasks_service",
    ):
        monkeypatch.setattr(bootstrap_module, name, lambda *_args: None)
    monkeypatch.setattr(
        bootstrap_module, "build_school_research_study_policy", lambda _settings: object()
    )
    monkeypatch.setattr(
        research_lifecycle, "build_school_research_process_factory", lambda *_args: None
    )

    container = build_container(_explicit_managed_research_settings())

    assert container.post_assessment_worker_manager is not None
    assert container.research_education_worker_manager is not None
    assert (
        container.research_education_worker_manager.concurrency_lock
        is container.post_assessment_worker_manager.concurrency_lock
    )


def test_container_reuses_the_post_assessment_single_slot_lock():
    manager = SchoolPostAssessmentWorkerManager(
        type("Adapter", (), {"persistence": object()})(),
        BackendSettings(_env_file=None).post_assessment_worker,
    )

    assert _shared_worker_concurrency_lock(manager) is manager.concurrency_lock


class _FakePersistence:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def start(self) -> None:
        self.events.append("persistence.start")

    async def close(self) -> None:
        self.events.append("persistence.close")


class _FakeSafety:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def start(self) -> None:
        self.events.append("safety.start")

    async def close(self) -> None:
        self.events.append("safety.close")


class _FakeManager:
    def __init__(
        self,
        events: list[str],
        name: str,
        *,
        fail_close: bool = False,
    ) -> None:
        self.events = events
        self.name = name
        self.fail_close = fail_close

    async def start(self) -> None:
        self.events.append(f"{self.name}.start")

    async def close(self) -> None:
        self.events.append(f"{self.name}.close")
        if self.fail_close:
            raise RuntimeError("synthetic worker cleanup failure")

    def dependency_status(self) -> dict[str, str]:
        return {"status": "READY", "integration": self.name.upper()}


@pytest.mark.asyncio
async def test_container_starts_and_stops_both_workers_before_database_close():
    events: list[str] = []
    container = build_container(BackendSettings(_env_file=None))
    container.persistence = _FakePersistence(events)
    container.safety = _FakeSafety(events)
    container.post_assessment_worker_manager = _FakeManager(events, "post")
    container.research_education_worker_manager = _FakeManager(events, "research")

    await container.start()
    await container.close()

    assert events == [
        "persistence.start",
        "safety.start",
        "post.start",
        "research.start",
        "research.close",
        "post.close",
        "safety.close",
        "persistence.close",
    ]


@pytest.mark.asyncio
async def test_research_worker_shutdown_failure_keeps_database_open():
    events: list[str] = []
    container = build_container(BackendSettings(_env_file=None))
    container.persistence = _FakePersistence(events)
    container.safety = _FakeSafety(events)
    container.post_assessment_worker_manager = _FakeManager(events, "post")
    container.research_education_worker_manager = _FakeManager(events, "research", fail_close=True)

    with pytest.raises(RuntimeError, match="research education worker shutdown did not complete"):
        await container.close()

    assert "research.close" in events
    assert "post.close" in events
    assert "safety.close" in events
    assert "persistence.close" not in events
