from __future__ import annotations

import asyncio
import importlib.util
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from database_layer.base import Base
from database_layer.errors import ForeignKeyConflict, OptimisticConcurrencyConflict, UniqueConflict
from database_layer.models import (
    Account,
    AccountSchoolMembership,
    MeasurementTask,
    MembershipRole,
    School,
    SchoolClass,
    SchoolClassStudent,
    SchoolResearchEducationJob,
    SchoolResearchProfileVersion,
    SchoolResearchSession,
    SchoolResearchTaskBinding,
    Subject,
    TaskEnrollment,
)
from database_layer.provenance import SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF
from database_layer.school_research_education_jobs import (
    STAFF_PROGRAMME_POLICY_VERSION,
    ResearchEducationJobClaim,
    ResearchEducationJobErrorCode,
    SchoolResearchEducationJobRepository,
)
from sqlalchemy import create_engine, event, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

_NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
_PROFILE_SHA = "a" * 64
_MANIFEST_SHA = "b" * 64


class _AsyncSessionAdapter:
    def __init__(self, session: Session) -> None:
        self.sync = session

    async def scalar(self, statement):
        return self.sync.scalar(statement)

    async def scalars(self, statement):
        return self.sync.scalars(statement)

    def add(self, instance):
        self.sync.add(instance)

    async def flush(self):
        self.sync.flush()

    @asynccontextmanager
    async def begin_nested(self):
        with self.sync.begin_nested():
            yield self


@pytest.fixture
def session(monkeypatch):
    medium_blob_cls = type(mysql.MEDIUMBLOB())
    big_int_cls = type(mysql.BIGINT(unsigned=True))
    medium_blob_dispatch = medium_blob_cls._compiler_dispatch
    big_int_dispatch = big_int_cls._compiler_dispatch

    def compile_sqlite_blob(self, visitor, **kw):
        return (
            "BLOB"
            if visitor.dialect.name == "sqlite"
            else medium_blob_dispatch(self, visitor, **kw)
        )

    def compile_sqlite_bigint(self, visitor, **kw):
        return (
            "INTEGER" if visitor.dialect.name == "sqlite" else big_int_dispatch(self, visitor, **kw)
        )

    monkeypatch.setattr(medium_blob_cls, "_compiler_dispatch", compile_sqlite_blob)
    monkeypatch.setattr(big_int_cls, "_compiler_dispatch", compile_sqlite_bigint)
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_constraints(connection, _record):
        connection.create_collation("ascii_bin", lambda a, b: (a > b) - (a < b))
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    db = Session(engine)
    _seed(db)
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _seed(db: Session) -> None:
    at = _NOW.replace(tzinfo=None)
    db.add(
        School(
            id=1,
            school_ref="research-outbox-school",
            display_name="Synthetic",
            status="ACTIVE",
            data_origin="SYNTHETIC",
            provenance_ref=SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF,
        )
    )
    db.add(
        Account(
            id=1,
            login_name="research-outbox-student",
            password_hash="synthetic-hash",
            status="ACTIVE",
        )
    )
    db.flush()
    db.add(
        AccountSchoolMembership(
            id=1,
            account_id=1,
            school_id=1,
            display_name="Synthetic",
            status="ACTIVE",
            valid_from=at - timedelta(days=1),
        )
    )
    db.flush()
    db.add(
        MembershipRole(
            id=1,
            membership_id=1,
            school_id=1,
            role_code="admin",
            status="ACTIVE",
            valid_from=at - timedelta(days=1),
        )
    )
    db.flush()
    db.add(
        SchoolClass(
            id=1,
            school_id=1,
            class_ref="research-outbox-class",
            display_name="Synthetic",
            created_by_membership_role_id=1,
            status="ACTIVE",
        )
    )
    db.add(
        Subject(
            id=1,
            subject_ref="research-outbox-subject",
            school_id=1,
            status="ACTIVE",
            data_origin="SYNTHETIC",
        )
    )
    db.flush()
    db.add(
        SchoolClassStudent(
            id=1,
            school_id=1,
            class_id=1,
            subject_id=1,
            status="ACTIVE",
            valid_from=at - timedelta(days=1),
        )
    )
    db.flush()
    db.add(
        SchoolResearchProfileVersion(
            id=1,
            school_id=1,
            profile_ref="research-profile",
            version_number=3,
            instrument_id="synthetic-profile",
            dimension="SYNTHETIC",
            source_population_scope="SYNTHETIC",
            profile_sha256=_PROFILE_SHA,
            manifest_sha256=_MANIFEST_SHA,
            fit_sha256="c" * 64,
            calibration_sha256="d" * 64,
            rights_status="VERIFIED",
            execution_status="SIMULATION_ENABLED",
            purpose="RESEARCH_SIMULATION",
            research_only=True,
            human_curated=False,
            psychological_interpretation_allowed=False,
            publication_status="not_approved_for_publication_or_operational_use",
            payload_ciphertext=b"synthetic-ciphertext",
            cipher_format_version="fernet.v1",
            key_version="synthetic-key",
            payload_schema_version="research-profile.v1",
            created_by_membership_role_id=1,
            status_changed_by_membership_role_id=1,
            simulation_enabled_at=at - timedelta(days=1),
            parameter_origin="LOCAL_RESEARCH_FIT",
            published_parameter_crosswalk_sha256=None,
        )
    )
    db.add(
        MeasurementTask(
            id=1,
            school_id=1,
            class_id=1,
            task_ref="research-task",
            created_by_membership_role_id=1,
            instrument_id="synthetic-profile",
            instrument_version="3",
            item_bank_version=None,
            config_version="cfg-v1",
            opens_at=at - timedelta(days=1),
            due_at=None,
            published_at=at - timedelta(days=1),
            status="PUBLISHED",
            cat_binding_mode="RESEARCH_PROFILE",
        )
    )
    db.flush()
    db.add(
        SchoolResearchTaskBinding(
            id=1,
            school_id=1,
            task_id=1,
            class_id=1,
            profile_version_id=1,
            profile_ref="research-profile",
            profile_version_number=3,
            profile_sha256=_PROFILE_SHA,
            response_origin="PUBLIC_OBSERVED",
            status="ACTIVE",
            purpose="RESEARCH_SIMULATION",
            research_only=True,
            config_version="cfg-v1",
            config_sha256="e" * 64,
            config_ciphertext=b"synthetic-ciphertext",
            cipher_format_version="fernet.v1",
            key_version="synthetic-key",
            payload_schema_version="research-binding.v1",
            created_by_membership_role_id=1,
            revoked_by_membership_role_id=None,
            revoked_at=None,
            corpus_sha256=None,
            case_count=None,
            cohort_id=None,
        )
    )
    db.add(
        TaskEnrollment(
            id=1,
            school_id=1,
            task_id=1,
            class_id=1,
            class_student_id=1,
            subject_id=1,
            status="ACTIVE",
            revoked_at=None,
        )
    )
    db.flush()
    db.add(
        SchoolResearchSession(
            id=1,
            session_ref="research-session",
            school_id=1,
            task_id=1,
            class_id=1,
            task_enrollment_id=1,
            subject_id=1,
            task_binding_id=1,
            profile_version_id=1,
            profile_ref="research-profile",
            profile_version_number=3,
            profile_sha256=_PROFILE_SHA,
            response_origin="PUBLIC_OBSERVED",
            config_version="cfg-v1",
            config_sha256="e" * 64,
            purpose="RESEARCH_SIMULATION",
            research_only=True,
            status="COMPLETED",
            state_version=9,
            items_answered=8,
            stop_reason="SYNTHETIC_TEST",
            snapshot_ciphertext=b"do-not-read-this",
            snapshot_sha256="f" * 64,
            cipher_format_version="fernet.v1",
            key_version="synthetic-key",
            payload_schema_version="research-session.v1",
            started_at=at - timedelta(hours=1),
            completed_at=at - timedelta(minutes=1),
            trace_id="synthetic-trace",
            retention_due_at=None,
        )
    )
    db.flush()
    db.commit()


def _repo(db):
    return SchoolResearchEducationJobRepository(cast(AsyncSession, _AsyncSessionAdapter(db)))


def _enqueue(repo, **overrides):
    values = dict(
        school_id=1,
        research_session_id=1,
        task_id=1,
        class_id=1,
        task_enrollment_id=1,
        subject_id=1,
        task_binding_id=1,
        profile_version_id=1,
        profile_ref="research-profile",
        profile_version_number=3,
        profile_sha256=_PROFILE_SHA,
        response_origin="PUBLIC_OBSERVED",
        now=_NOW,
    )
    values.update(overrides)
    return asyncio.run(repo.enqueue_completed_session(**values))


def test_completed_session_outbox_is_idempotent_and_contains_no_content(session):
    repo = _repo(session)
    first = _enqueue(repo, policy_version=STAFF_PROGRAMME_POLICY_VERSION, policy_hash="9" * 64)
    again = _enqueue(repo, policy_version=STAFF_PROGRAMME_POLICY_VERSION, policy_hash="9" * 64)
    assert first.id == again.id
    assert first.status == "QUEUED"
    assert first.purpose == "RESEARCH_SIMULATION"
    assert first.research_only is True
    assert first.publication_status == "not_approved_for_publication_or_operational_use"
    assert "do-not-read-this" not in repr(first)
    assert _PROFILE_SHA not in repr(first)
    claim = asyncio.run(
        repo.claim_next(
            school_id=1,
            lease_owner="staff-programme-worker",
            policy_version=STAFF_PROGRAMME_POLICY_VERSION,
            now=_NOW,
        )
    )[0]
    assert claim.purpose == "RESEARCH_SIMULATION"
    assert claim.research_only is True
    assert claim.publication_status == "not_approved_for_publication_or_operational_use"
    assert set(SchoolResearchEducationJob.__table__.columns.keys()).isdisjoint(
        {
            "answers",
            "raw_response",
            "snapshot_ciphertext",
            "score",
            "case_index",
            "assessment_session_id",
        }
    )
    assert (
        session.scalar(
            select(SchoolResearchEducationJob).where(SchoolResearchEducationJob.id == first.id)
        ).publication_status
        == "not_approved_for_publication_or_operational_use"
    )


def test_require_active_claim_returns_persisted_full_scope_and_rejects_stale_or_cross_school(
    session,
):
    repo = _repo(session)
    queued = _enqueue(
        repo,
        policy_version=STAFF_PROGRAMME_POLICY_VERSION,
        policy_hash="9" * 64,
    )
    original = asyncio.run(
        repo.claim_next(
            school_id=1,
            lease_owner="staff-programme-worker",
            policy_version=STAFF_PROGRAMME_POLICY_VERSION,
            now=_NOW,
        )
    )[0]

    persisted = asyncio.run(
        repo.require_active_claim(
            school_id=original.school_id,
            research_session_id=original.research_session_id,
            job_id=original.id,
            lease_owner=original.lease_owner,
            lease_token=original.lease_token,
            now=_NOW,
        )
    )

    assert type(persisted) is ResearchEducationJobClaim
    assert persisted.id == queued.id
    assert persisted.task_id == 1
    assert persisted.class_id == 1
    assert persisted.task_enrollment_id == 1
    assert persisted.subject_id == 1
    assert persisted.task_binding_id == 1
    assert persisted.profile_version_id == 1
    assert persisted.profile_ref == "research-profile"
    assert persisted.profile_version_number == 3
    assert persisted.profile_sha256 == _PROFILE_SHA
    assert persisted.response_origin == "PUBLIC_OBSERVED"
    assert persisted.policy_hash == "9" * 64
    assert persisted.lease_owner == original.lease_owner
    assert persisted.lease_token == original.lease_token
    assert persisted.status == "LEASED"
    assert _PROFILE_SHA not in repr(persisted)
    assert persisted.lease_token not in repr(persisted)

    with pytest.raises(OptimisticConcurrencyConflict):
        asyncio.run(
            repo.require_active_claim(
                school_id=2,
                research_session_id=original.research_session_id,
                job_id=original.id,
                lease_owner=original.lease_owner,
                lease_token=original.lease_token,
                now=_NOW,
            )
        )
    with pytest.raises(OptimisticConcurrencyConflict):
        asyncio.run(
            repo.require_active_claim(
                school_id=original.school_id,
                research_session_id=original.research_session_id,
                job_id=original.id,
                lease_owner=original.lease_owner,
                lease_token=original.lease_token,
                now=_NOW + timedelta(seconds=61),
            )
        )


def test_enqueue_requires_completed_exact_scope_and_fixed_policy(session):
    repo = _repo(session)
    with pytest.raises(ForeignKeyConflict):
        _enqueue(repo, subject_id=999)
    with pytest.raises(ValueError):
        _enqueue(repo, policy_version="ALLOW_PERSONALIZED_RESEARCH_POLICY")
    row = session.get(SchoolResearchSession, 1)
    row.status = "IN_PROGRESS"
    row.completed_at = None
    session.commit()
    with pytest.raises(OptimisticConcurrencyConflict):
        _enqueue(repo)


def test_database_composite_fk_rejects_cross_school_scope(session):
    bad = SchoolResearchEducationJob(
        job_ref="REJ_cross_school_scope_test",
        research_session_id=1,
        school_id=2,
        task_id=1,
        class_id=1,
        task_enrollment_id=1,
        subject_id=1,
        task_binding_id=1,
        profile_version_id=1,
        profile_ref="research-profile",
        profile_version_number=3,
        profile_sha256=_PROFILE_SHA,
        response_origin="MODEL_GENERATED",
        policy_version="NO_RESEARCH_PERSONALIZED_POLICY_V1",
    )
    session.add(bad)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_enqueue_rejects_naive_timestamp(session):
    with pytest.raises(ValueError):
        _enqueue(_repo(session), now=datetime(2026, 10, 14, 9, 0))


def test_outer_rollback_removes_enqueue(session):
    repo = _repo(session)
    session.begin()
    session.get(SchoolResearchSession, 1).trace_id = "synthetic-outer-transaction"
    session.flush()
    _enqueue(repo)
    session.rollback()
    assert session.scalar(select(SchoolResearchEducationJob.id)) is None


def test_lease_owner_token_expiry_retry_and_attempt_limit(session):
    repo = _repo(session)
    queued = _enqueue(repo)
    claim = asyncio.run(
        repo.claim_next(
            school_id=1, lease_owner="worker-a", lease_seconds=5, max_attempts=2, now=_NOW
        )
    )[0]
    assert claim.id == queued.id
    assert claim.lease_token not in repr(claim)
    assert _PROFILE_SHA not in repr(claim)
    with pytest.raises(OptimisticConcurrencyConflict):
        asyncio.run(
            repo.finish(
                school_id=1,
                research_session_id=1,
                job_id=claim.id,
                lease_owner="worker-b",
                lease_token=claim.lease_token,
                now=_NOW + timedelta(seconds=1),
            )
        )
    with pytest.raises(OptimisticConcurrencyConflict):
        asyncio.run(
            repo.finish(
                school_id=1,
                research_session_id=1,
                job_id=claim.id,
                lease_owner="worker-a",
                lease_token="lease_wrong-token",
                now=_NOW + timedelta(seconds=1),
            )
        )
    retry = asyncio.run(
        repo.retry(
            school_id=1,
            research_session_id=1,
            job_id=claim.id,
            lease_owner="worker-a",
            lease_token=claim.lease_token,
            error_code=ResearchEducationJobErrorCode.UPSTREAM_TIMEOUT,
            max_attempts=2,
            base_delay_seconds=1,
            now=_NOW + timedelta(seconds=1),
        )
    )
    assert retry.status == "RETRY"
    second = asyncio.run(
        repo.claim_next(
            school_id=1,
            lease_owner="worker-b",
            lease_seconds=5,
            max_attempts=2,
            now=_NOW + timedelta(seconds=5),
        )
    )[0]
    assert second.attempt_count == 2
    with pytest.raises(OptimisticConcurrencyConflict):
        asyncio.run(
            repo.finish(
                school_id=1,
                research_session_id=1,
                job_id=second.id,
                lease_owner="worker-b",
                lease_token=second.lease_token,
                now=_NOW + timedelta(seconds=11),
            )
        )
    recovered = asyncio.run(
        repo.claim_next(
            school_id=1,
            lease_owner="worker-c",
            max_attempts=2,
            now=_NOW + timedelta(seconds=11),
        )
    )
    assert recovered == []
    final = session.get(SchoolResearchEducationJob, queued.id)
    assert final.status == "FAILED"
    assert final.last_error_code == ResearchEducationJobErrorCode.LEASE_EXPIRED_MAX_ATTEMPTS.value


def test_invalid_dependency_response_can_finish_as_review_required(session):
    repo = _repo(session)
    queued = _enqueue(
        repo,
        policy_version=STAFF_PROGRAMME_POLICY_VERSION,
        policy_hash="9" * 64,
    )
    claim = asyncio.run(
        repo.claim_next(
            school_id=1,
            lease_owner="staff-worker",
            limit=1,
            lease_seconds=30,
            max_attempts=5,
            policy_version=STAFF_PROGRAMME_POLICY_VERSION,
            now=_NOW,
        )
    )[0]

    finished = asyncio.run(
        repo.finish(
            school_id=1,
            research_session_id=1,
            job_id=queued.id,
            lease_owner=claim.lease_owner,
            lease_token=claim.lease_token,
            status="REVIEW_REQUIRED",
            error_code=ResearchEducationJobErrorCode.DEPENDENCY_INVALID_RESPONSE,
            now=_NOW + timedelta(seconds=1),
        )
    )

    assert finished.status == "REVIEW_REQUIRED"
    assert (
        finished.last_error_code
        == ResearchEducationJobErrorCode.DEPENDENCY_INVALID_RESPONSE.value
    )
    assert finished.lease_expires_at is None
    persisted = session.get(SchoolResearchEducationJob, queued.id)
    assert persisted.lease_owner is None
    assert persisted.lease_token is None


def test_fixed_internal_worker_stage_code_persists_without_schema_change(session):
    repo = _repo(session)
    queued = _enqueue(
        repo,
        policy_version=STAFF_PROGRAMME_POLICY_VERSION,
        policy_hash="9" * 64,
    )
    claim = asyncio.run(
        repo.claim_next(
            school_id=1,
            lease_owner="staff-worker",
            policy_version=STAFF_PROGRAMME_POLICY_VERSION,
            now=_NOW,
        )
    )[0]

    reviewed = asyncio.run(
        repo.finish(
            school_id=1,
            research_session_id=1,
            job_id=queued.id,
            lease_owner=claim.lease_owner,
            lease_token=claim.lease_token,
            status="REVIEW_REQUIRED",
            error_code=ResearchEducationJobErrorCode.INTERNAL_FAILURE_CANDIDATE_PROJECTION,
            now=_NOW,
        )
    )

    assert reviewed.status == "REVIEW_REQUIRED"
    assert reviewed.last_error_code == "INTERNAL_FAILURE_CANDIDATE_PROJECTION"
    assert session.get(SchoolResearchEducationJob, queued.id).last_error_code == (
        "INTERNAL_FAILURE_CANDIDATE_PROJECTION"
    )


def test_replay_scope_and_error_codes_are_closed(session):
    repo = _repo(session)
    _enqueue(repo, policy_hash="a" * 64)
    with pytest.raises(UniqueConflict):
        _enqueue(repo, policy_hash="b" * 64)
    with pytest.raises(ValueError):
        _enqueue(repo, profile_sha256="not-a-digest")
    with pytest.raises(ValueError):
        asyncio.run(
            repo.finish(
                school_id=1,
                research_session_id=1,
                job_id=1,
                lease_owner="x",
                lease_token="y",
                status="APPROVED_FOR_PUBLICATION",
                error_code=None,
                now=_NOW,
            )
        )
    assert (
        re.search(
            r"snapshot|answer|assessment_session",
            " ".join(SchoolResearchEducationJob.__table__.columns.keys()),
        )
        is None
    )


def test_no_policy_worker_cannot_claim_staff_programme_job(session):
    repo = _repo(session)
    staff_job = _enqueue(
        repo,
        policy_version=STAFF_PROGRAMME_POLICY_VERSION,
        policy_hash="9" * 64,
    )
    assert _enqueue(
        repo,
        policy_version=STAFF_PROGRAMME_POLICY_VERSION,
        policy_hash="9" * 64,
    ).id == staff_job.id
    with pytest.raises(UniqueConflict):
        _enqueue(
            repo,
            policy_version=STAFF_PROGRAMME_POLICY_VERSION,
            policy_hash="8" * 64,
        )
    with pytest.raises(ValueError):
        _enqueue(
            repo,
            policy_version=STAFF_PROGRAMME_POLICY_VERSION,
            policy_hash="9" * 64,
            response_origin="MODEL_GENERATED",
        )
    old_lane = asyncio.run(
        repo.claim_next(school_id=1, lease_owner="old-no-policy-worker", now=_NOW)
    )
    assert old_lane == []

    staff_lane = asyncio.run(
        repo.claim_next(
            school_id=1,
            lease_owner="staff-programme-worker",
            policy_version=STAFF_PROGRAMME_POLICY_VERSION,
            now=_NOW,
        )
    )
    assert len(staff_lane) == 1
    assert staff_lane[0].id == staff_job.id
    assert staff_lane[0].policy_version == STAFF_PROGRAMME_POLICY_VERSION
    assert staff_lane[0].policy_hash == "9" * 64

    with pytest.raises(ValueError):
        _enqueue(repo, policy_version=STAFF_PROGRAMME_POLICY_VERSION)


def test_0016_migration_has_exact_model_columns_and_composite_session_fk(monkeypatch):
    medium_blob_cls = type(mysql.MEDIUMBLOB())
    big_int_cls = type(mysql.BIGINT(unsigned=True))
    medium_blob_dispatch = medium_blob_cls._compiler_dispatch
    big_int_dispatch = big_int_cls._compiler_dispatch

    def compile_sqlite_blob(self, visitor, **kw):
        return (
            "BLOB"
            if visitor.dialect.name == "sqlite"
            else medium_blob_dispatch(self, visitor, **kw)
        )

    def compile_sqlite_bigint(self, visitor, **kw):
        return (
            "INTEGER" if visitor.dialect.name == "sqlite" else big_int_dispatch(self, visitor, **kw)
        )

    monkeypatch.setattr(medium_blob_cls, "_compiler_dispatch", compile_sqlite_blob)
    monkeypatch.setattr(big_int_cls, "_compiler_dispatch", compile_sqlite_bigint)
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def register_ascii_collation(connection, _record):
        connection.create_collation("ascii_bin", lambda a, b: (a > b) - (a < b))

    path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20261014_0016_research_education_jobs.py"
    )
    spec = importlib.util.spec_from_file_location("research_education_jobs_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
    inspector = sa_inspect(engine)
    assert [
        column["name"] for column in inspector.get_columns("school_research_education_jobs")
    ] == list(SchoolResearchEducationJob.__table__.columns.keys())
    foreign_key = next(
        fk
        for fk in inspector.get_foreign_keys("school_research_education_jobs")
        if fk["name"] == "fk_school_research_education_jobs_session_exact_scope"
    )
    assert foreign_key["constrained_columns"] == [
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
    ]
    assert foreign_key["referred_columns"] == [
        "id",
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
    ]
    engine.dispose()
