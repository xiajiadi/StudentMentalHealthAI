# ruff: noqa: E402

from __future__ import annotations

import hashlib
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "11_database" / ".venv" / "Lib" / "site-packages"))
sys.path.insert(0, str(REPO / "05_rag-engine" / "src"))

from smhai_backend.container import build_container
from smhai_backend.core.config import BackendSettings
from smhai_backend.core.request_context import RequestContext

_SOURCE_STUDY_REF = "school-noncommercial-rag-research-2027-06"
_SCHOOL_STUDY_REF = "HUNNU_PROMIS_HISTORICAL_REPLAY_2026_R1"
_MANIFEST_SHA256 = "ac9cc1641faa565ff7a18866be1c2dbf8aaf16aff7155ea80c38bfd979429a9b"
_MANIFEST_PATH = r"D:\Dev\datasets\student-research\manifest.json"


def _settings():
    return BackendSettings(
        _env_file=None,
        environment="research",
        identity_profile="school_tenant",
        persistence_mode="mysql",
        school_csrf_secret="c" * 64,
        school_research_enabled=True,
        school_research_runtime_file=r"D:\research\runtime.json",
        school_research_runtime_sha256="d" * 64,
        school_research_base_url="http://127.0.0.1:8182",
        school_research_managed_enabled=True,
        school_research_service_file=r"D:\research\service.json",
        school_research_service_sha256="e" * 64,
        school_research_cat_python=r"D:\Dev\pythons\python.exe",
        school_research_cat_source=r"D:\cat\src",
        school_research_cat_dependencies=r"D:\cat\deps",
        school_research_study_use_file=r"D:\research\study-use.json",
        school_research_study_use_sha256="b" * 64,
        school_research_source_rights_verified=True,
        school_research_latest_study_end=datetime(2027, 6, 30, 15, 59, 59, tzinfo=UTC),
        school_research_student_conversation={
            "enabled": True,
            "school_id": 17,
            "study_ref": _SOURCE_STUDY_REF,
            "manifest_file": _MANIFEST_PATH,
            "manifest_sha256": _MANIFEST_SHA256,
            "safety_base_url": "http://127.0.0.1:8191",
        },
        safety={"mode": "http", "base_url": "http://127.0.0.1:8190"},
        llm={"mode": "http", "base_url": "http://127.0.0.1:8160"},
        research_programme_runtime={
            "mode": "http",
            "base_url": "http://127.0.0.1:8161",
            "timeout": {"read": 65.0},
        },
        research_general_education_draft={
            "enabled": True,
            "school_id": 17,
            "school_study_ref": _SCHOOL_STUDY_REF,
            "policy_hash": "c" * 64,
            "source_study_ref": _SOURCE_STUDY_REF,
            "source_manifest_sha256": _MANIFEST_SHA256,
            "source_manifest_file": _MANIFEST_PATH,
        },
    )


class _Persistence:
    identity_profile = "school_tenant"
    _started = False

    async def close(self):
        return None


def _pinned_package(valid_through: datetime):
    text = "Synthetic public source excerpt with its original limitation."
    source = SimpleNamespace(
        source_id="SRC_SYNTHETIC_1",
        title="Synthetic public source",
        canonical_url="https://example.org/source",
        publisher="Synthetic publisher",
        source_language="en",
        license="CC BY 4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        attribution="Synthetic publisher, CC BY 4.0",
        rights_status="VERIFIED_WITH_CONDITIONS",
        student_retrieval_eligible=True,
    )
    record = SimpleNamespace(
        record_id="REC_SYNTHETIC_1",
        source_id=source.source_id,
        locator="Section 1",
        text=text,
        excerpt_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        source_population_scope="Original source population",
        student_retrieval_eligible=True,
    )
    return SimpleNamespace(
        package_id="R3_SYNTHETIC_PACKAGE",
        study_ref=_SOURCE_STUDY_REF,
        manifest_sha256=_MANIFEST_SHA256,
        valid_through=valid_through,
        sources=(source,),
        records=(record,),
    )


def _patch_container_dependencies(monkeypatch, *, package):
    import importlib

    database_module = importlib.import_module("smhai_backend.adapters.database")
    bootstrap_module = importlib.import_module("smhai_backend.domains.school_research.bootstrap")
    lifecycle_module = importlib.import_module("smhai_backend.domains.school_research.lifecycle")
    student_module = importlib.import_module("rag_engine.research.student_education")

    persistence = _Persistence()
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
        bootstrap_module,
        "build_school_research_study_policy",
        lambda _settings: SimpleNamespace(
            school_id=17,
            study_ref=_SCHOOL_STUDY_REF,
            source_rights_verified=True,
        ),
    )
    monkeypatch.setattr(
        lifecycle_module, "build_school_research_process_factory", lambda *_args: None
    )
    monkeypatch.setattr(
        student_module,
        "load_school_student_package",
        lambda *_args, **_kwargs: package,
    )

    class FakeRetriever:
        def __init__(self, loaded_package):
            self.package = loaded_package

        def retrieve(self, *_args, **_kwargs):
            raise AssertionError("container wiring test must not retrieve or generate")

    monkeypatch.setattr(student_module, "SchoolStudentEducationRetriever", FakeRetriever)
    return persistence


@pytest.mark.asyncio
async def test_enabled_container_wires_held_worker_candidate_feedback_and_private_runtime(
    monkeypatch,
):
    package = _pinned_package(datetime.now(UTC) + timedelta(days=10))
    persistence = _patch_container_dependencies(monkeypatch, package=package)
    container = build_container(_settings())

    try:
        manager = container.research_general_education_worker_manager
        candidate_adapter = container.school_research_education_candidates.persistence
        assert manager is not None
        assert manager.persistence is persistence
        assert manager.persistence_adapter is candidate_adapter
        assert candidate_adapter.enabled is True
        assert candidate_adapter.source_package_ref == package.package_id
        assert candidate_adapter.source_study_ref == package.study_ref
        assert candidate_adapter.source_manifest_sha256 == _MANIFEST_SHA256
        assert manager.generation_service.retriever is not None
        assert manager.generation_service.safety is container.school_research_student_safety
        assert (
            manager.generation_service.runtime
            is container.research_general_education_runtime_client
        )
        assert manager.generation_service.policy_pins.source_package_ref == package.package_id
        feedback_adapter = container.school_research_feedback.persistence
        assert (
            feedback_adapter.education_candidate_validator.__self__ is candidate_adapter
        )
        assert container.post_assessment_worker_manager is not None
        assert (
            manager.concurrency_lock
            is container.post_assessment_worker_manager.concurrency_lock
        )
        assert container.school_research_student_conversations is not None
        assert (
            container.research_general_education_runtime_client
            is not container.research_programme_runtime_client
        )
    finally:
        await container.close()


@pytest.mark.asyncio
async def test_expired_r3_package_does_not_create_a_worker_or_runtime_client(monkeypatch):
    package = _pinned_package(datetime.now(UTC) - timedelta(seconds=1))
    _patch_container_dependencies(monkeypatch, package=package)
    container = build_container(_settings())

    try:
        assert container.research_general_education_worker_manager is None
        assert container.research_general_education_runtime_client is None
        assert container.school_research_education_candidates is None

        async def healthy(*_args, **_kwargs):
            return {"status": "READY"}

        monkeypatch.setattr(type(container.cat), "health", healthy)
        monkeypatch.setattr(type(container.rag), "health", healthy)
        monkeypatch.setattr(type(container.llm), "health", healthy)
        monkeypatch.setattr(type(container.safety), "health", healthy)
        matrix = await container.dependency_matrix(RequestContext("REQ_test", "TRACE_test"))
        assert matrix["research_general_education_draft_worker"] == {
            "status": "UNAVAILABLE",
            "integration": "RESEARCH_GENERAL_EDUCATION_DRAFT_OUTBOX",
        }
    finally:
        await container.close()


class _LifecyclePersistence:
    async def start(self):
        self.events.append("persistence.start")

    async def close(self):
        self.events.append("persistence.close")

    def __init__(self, events):
        self.events = events


class _LifecycleSafety:
    def __init__(self, events):
        self.events = events

    async def start(self):
        self.events.append("safety.start")

    async def close(self):
        self.events.append("safety.close")


class _LifecycleManager:
    def __init__(self, events, *, fail_start=False, fail_close=False):
        self.events = events
        self.fail_start = fail_start
        self.fail_close = fail_close

    async def start(self):
        self.events.append("draft_worker.start")
        if self.fail_start:
            raise RuntimeError("synthetic worker startup failure")

    async def close(self):
        self.events.append("draft_worker.close")
        if self.fail_close:
            raise RuntimeError("synthetic worker cleanup failure")

    def dependency_status(self):
        return {"status": "READY", "integration": "RESEARCH_GENERAL_EDUCATION_DRAFT_OUTBOX"}


class _LifecycleClient:
    def __init__(self, events):
        self.events = events

    async def close(self):
        self.events.append("draft_runtime.close")


@pytest.mark.asyncio
async def test_container_lifecycle_drains_worker_closes_client_then_database():
    events = []
    container = build_container(BackendSettings(_env_file=None))
    container.persistence = _LifecyclePersistence(events)
    container.safety = _LifecycleSafety(events)
    container.research_general_education_worker_manager = _LifecycleManager(events)
    container.research_general_education_runtime_client = _LifecycleClient(events)

    await container.start()
    await container.close()

    assert events == [
        "persistence.start",
        "safety.start",
        "draft_worker.start",
        "draft_worker.close",
        "safety.close",
        "draft_runtime.close",
        "persistence.close",
    ]


@pytest.mark.asyncio
async def test_startup_failure_cleans_worker_client_and_keeps_database_if_worker_stuck():
    events = []
    container = build_container(BackendSettings(_env_file=None))
    container.persistence = _LifecyclePersistence(events)
    container.safety = _LifecycleSafety(events)
    container.research_general_education_worker_manager = _LifecycleManager(
        events, fail_start=True, fail_close=True
    )
    container.research_general_education_runtime_client = _LifecycleClient(events)

    with pytest.raises(RuntimeError, match="synthetic worker startup failure"):
        await container.start()

    assert "draft_worker.close" in events
    assert "draft_runtime.close" in events
    assert "persistence.close" not in events
