from __future__ import annotations

import asyncio
import importlib.util
import io
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from database_layer.base import Base
from database_layer.errors import ForeignKeyConflict, OptimisticConcurrencyConflict, UniqueConflict
from database_layer.models import (
    SchoolResearchEducationInputReview,
    SchoolResearchEducationInputReviewEvent,
    SchoolResearchEducationJob,
)
from database_layer.school_research_education_input_reviews import (
    ResearchEducationInputReviewError,
    ResearchEducationInputReviewEvidence,
    ResearchEducationInputReviewScope,
    SchoolResearchEducationInputReviewRepository,
)
from database_layer.school_research_education_jobs import (
    GENERAL_EDUCATION_POLICY_VERSION,
    SchoolResearchEducationJobRepository,
)
from database_layer.unit_of_work import SqlAlchemyUnitOfWork
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects import mysql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from test_school_research_education_jobs import _AsyncSessionAdapter, _seed

_NOW = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
_POLICY_HASH = "a" * 64


class _InputReviewAsyncSessionAdapter(_AsyncSessionAdapter):
    async def execute(self, statement):
        return self.sync.execute(statement)


@pytest.fixture
def session(monkeypatch):
    medium_blob_cls = type(mysql.MEDIUMBLOB())
    big_int_cls = type(mysql.BIGINT(unsigned=True))
    medium_blob_dispatch = medium_blob_cls._compiler_dispatch
    big_int_dispatch = big_int_cls._compiler_dispatch

    def compile_blob(self, visitor, **kwargs):
        return (
            "BLOB"
            if visitor.dialect.name == "sqlite"
            else medium_blob_dispatch(self, visitor, **kwargs)
        )

    def compile_bigint(self, visitor, **kwargs):
        return (
            "INTEGER"
            if visitor.dialect.name == "sqlite"
            else big_int_dispatch(self, visitor, **kwargs)
        )

    monkeypatch.setattr(medium_blob_cls, "_compiler_dispatch", compile_blob)
    monkeypatch.setattr(big_int_cls, "_compiler_dispatch", compile_bigint)
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def setup_sqlite(connection, _record):
        connection.create_collation(
            "ascii_bin", lambda left, right: (left > right) - (left < right)
        )
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    db = Session(engine)
    _seed(db)
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _scope(claim):
    return ResearchEducationInputReviewScope(
        research_session_id=claim.research_session_id,
        school_id=claim.school_id,
        task_id=claim.task_id,
        class_id=claim.class_id,
        task_enrollment_id=claim.task_enrollment_id,
        subject_id=claim.subject_id,
        task_binding_id=claim.task_binding_id,
        profile_version_id=claim.profile_version_id,
        profile_ref=claim.profile_ref,
        profile_version_number=claim.profile_version_number,
        profile_sha256=claim.profile_sha256,
        response_origin=claim.response_origin,
    )


def _claim(session):
    jobs = SchoolResearchEducationJobRepository(
        cast(AsyncSession, _InputReviewAsyncSessionAdapter(session))
    )
    asyncio.run(
        jobs.enqueue_completed_session(
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
            profile_sha256="a" * 64,
            response_origin="PUBLIC_OBSERVED",
            policy_version=GENERAL_EDUCATION_POLICY_VERSION,
            policy_hash=_POLICY_HASH,
            now=_NOW,
        )
    )
    return asyncio.run(
        jobs.claim_next(
            school_id=1,
            lease_owner="research-worker",
            policy_version=GENERAL_EDUCATION_POLICY_VERSION,
            now=_NOW,
        )
    )[0]


def _evidence(**changes):
    values = dict(
        decision_id="DEC_synthetic_001",
        safety_review_ref="REVIEW_synthetic_001",
        safety_trace_id="TRACE_safety_input_001",
        safety_operation="INPUT",
        safety_action="REVIEW_REQUIRED",
        reason_codes=("CONTENT_CONTROVERSIAL",),
        requires_human=True,
        canonical_input_sha256="b" * 64,
        policy_version=GENERAL_EDUCATION_POLICY_VERSION,
        policy_hash=_POLICY_HASH,
        source_package_ref="student-r3-source-package",
        source_study_ref="school-noncommercial-rag-research-2027-06",
        source_manifest_sha256="c" * 64,
        prompt_id="PROMPT_research_general_education",
        prompt_version="1.4.0",
        prompt_sha256="d" * 64,
        expires_at=_NOW + timedelta(hours=24),
        trace_id="TRACE_worker_input_001",
    )
    values.update(changes)
    return ResearchEducationInputReviewEvidence(**values)


def _repo(session):
    return SchoolResearchEducationInputReviewRepository(
        cast(AsyncSession, _InputReviewAsyncSessionAdapter(session))
    )


def _create(session, claim, evidence=None):
    return asyncio.run(
        _repo(session).create_pending(
            claim=claim,
            scope=_scope(claim),
            evidence=evidence or _evidence(),
            now=_NOW,
        )
    )


def _finish_review_required(session, claim):
    jobs = SchoolResearchEducationJobRepository(
        cast(AsyncSession, _InputReviewAsyncSessionAdapter(session))
    )
    return asyncio.run(
        jobs.finish(
            school_id=claim.school_id,
            research_session_id=claim.research_session_id,
            job_id=claim.id,
            lease_owner=claim.lease_owner,
            lease_token=claim.lease_token,
            status="REVIEW_REQUIRED",
            now=_NOW + timedelta(seconds=30),
        )
    )


def _authorize(session, claim, pending):
    return asyncio.run(
        _repo(session).authorize_and_enqueue_continuation(
            input_review_ref=pending.input_review_ref,
            scope=_scope(claim),
            expected_state_version=1,
            actor_membership_role_id=1,
            grant_policy_version="RESEARCH_INPUT_REVIEW_ONCE_V1",
            grant_policy_hash="e" * 64,
            trace_id="TRACE_authorize_001",
            now=_NOW + timedelta(minutes=1),
        )
    )


def test_input_review_schema_is_job_and_session_bound_content_free_and_mysql_safe():
    review = SchoolResearchEducationInputReview.__table__
    event_table = SchoolResearchEducationInputReviewEvent.__table__
    assert len(review.columns) == 47
    assert "job_id" in review.columns
    assert "canonical_input_sha256" in review.columns
    assert "raw_input" not in review.columns and "input_text" not in review.columns
    assert "snapshot_ciphertext" not in review.columns and "answer" not in review.columns
    assert review.c.status.type.length == 24
    assert review.c.original_job_generation_round.default.arg == 0
    assert review.c.grant_policy_version.nullable is True
    assert review.c.grant_policy_hash.nullable is True
    assert review.c.authorized_by_membership_role_id.nullable is True
    assert review.c.consumed_at.nullable is True
    assert event_table.c.event_type.type.length == 24
    assert event_table.c.from_status.type.length == 24
    assert event_table.c.to_status.type.length == 24
    assert any(
        constraint.name == "fk_school_research_education_input_review_session_exact_scope"
        and len(constraint.elements) == 12
        for constraint in review.foreign_key_constraints
    )
    assert any(
        constraint.name == "fk_school_research_education_input_review_job_round_scope"
        and tuple(element.parent.name for element in constraint.elements)
        == ("job_id", "original_job_generation_round", "research_session_id", "school_id")
        for constraint in review.foreign_key_constraints
    )
    assert any(
        constraint.name == "school_research_education_input_review_job_unique"
        and tuple(column.name for column in constraint.columns) == ("job_id",)
        for constraint in review.constraints
    )
    assert "actor_membership_role_id" in event_table.columns
    names = re.findall(
        r"CONSTRAINT\s+`?([A-Za-z0-9_]+)`?",
        str(CreateTable(review).compile(dialect=mysql.dialect()))
        + str(CreateTable(event_table).compile(dialect=mysql.dialect())),
    )
    assert names and all(len(name) <= 64 for name in names)


def test_create_pending_requires_live_claim_and_is_idempotent_without_rewriting(session):
    claim = _claim(session)
    first = _create(session, claim)
    again = _create(session, claim)
    assert first.input_review_ref.startswith("REIR_")
    assert first.job_ref == claim.job_ref
    assert first.status == "PENDING" and first.state_version == 1
    assert first.decision_id == "DEC_synthetic_001"
    assert first.safety_review_ref == "REVIEW_synthetic_001"
    assert first.safety_trace_id == "TRACE_safety_input_001"
    assert first.safety_reason_code == "CONTENT_CONTROVERSIAL"
    assert first.expires_at == _NOW + timedelta(hours=24)
    assert first.input_review_ref == again.input_review_ref
    assert "synthetic_input_text" not in repr(first)
    rows = session.scalars(select(SchoolResearchEducationInputReviewEvent)).all()
    assert [(row.event_type, row.state_version) for row in rows] == [("PENDING", 1)]

    changed = _evidence(canonical_input_sha256="e" * 64)
    with pytest.raises(UniqueConflict):
        _create(session, claim, changed)
    persisted = session.scalar(select(SchoolResearchEducationInputReview))
    assert persisted.canonical_input_sha256 == "b" * 64


@pytest.mark.parametrize(
    "changes",
    [
        {"safety_action": "BLOCK"},
        {"safety_operation": "RETRIEVAL"},
        {"reason_codes": ("CONTENT_CONTROVERSIAL", "OTHER")},
        {"reason_codes": ()},
        {"requires_human": False},
        {"expires_at": _NOW + timedelta(hours=24, seconds=1)},
        {"source_manifest_sha256": "bad"},
    ],
)
def test_create_pending_rejects_ineligible_or_unpinned_safety_receipts(session, changes):
    claim = _claim(session)
    with pytest.raises(ResearchEducationInputReviewError):
        _create(session, claim, _evidence(**changes))
    assert session.scalar(select(SchoolResearchEducationInputReview)) is None
    assert session.scalar(select(SchoolResearchEducationInputReviewEvent)) is None


def test_no_retroactive_creation_after_job_terminal_and_stale_lease_rejected(session):
    claim = _claim(session)
    jobs = SchoolResearchEducationJobRepository(cast(object, _AsyncSessionAdapter(session)))
    asyncio.run(
        jobs.finish(
            school_id=1,
            research_session_id=claim.research_session_id,
            job_id=claim.id,
            lease_owner=claim.lease_owner,
            lease_token=claim.lease_token,
            status="REVIEW_REQUIRED",
            now=_NOW + timedelta(seconds=30),
        )
    )
    with pytest.raises(OptimisticConcurrencyConflict):
        _create(session, claim)


def test_read_reject_and_revoke_are_scoped_versioned_and_audited(session):
    claim = _claim(session)
    repo = _repo(session)
    pending = _create(session, claim)
    assert (
        asyncio.run(
            repo.get_for_task(school_id=1, task_id=1, input_review_ref=pending.input_review_ref)
        )
        == pending
    )
    assert asyncio.run(repo.list_for_task(school_id=1, task_id=1)) == [pending]

    rejected = asyncio.run(
        repo.reject(
            input_review_ref=pending.input_review_ref,
            scope=_scope(claim),
            expected_state_version=1,
            actor_membership_role_id=1,
            trace_id="TRACE_reject_001",
            now=_NOW + timedelta(minutes=1),
        )
    )
    assert rejected.status == "REJECTED" and rejected.state_version == 2
    assert rejected.resolved_by_membership_role_id == 1
    events = session.scalars(
        select(SchoolResearchEducationInputReviewEvent).order_by(
            SchoolResearchEducationInputReviewEvent.state_version
        )
    ).all()
    assert [
        (row.event_type, row.from_status, row.to_status, row.state_version) for row in events
    ] == [
        ("PENDING", None, "PENDING", 1),
        ("REJECTED", "PENDING", "REJECTED", 2),
    ]
    with pytest.raises(OptimisticConcurrencyConflict):
        asyncio.run(
            repo.revoke(
                input_review_ref=pending.input_review_ref,
                scope=_scope(claim),
                expected_state_version=1,
                actor_membership_role_id=1,
                trace_id="TRACE_revoke_stale_001",
                now=_NOW + timedelta(minutes=2),
            )
        )

    assert (
        asyncio.run(
            repo.get_for_task(school_id=1, task_id=99, input_review_ref=pending.input_review_ref)
        )
        is None
    )
    wrong_scope = ResearchEducationInputReviewScope(
        **{
            **{name: getattr(_scope(claim), name) for name in _scope(claim).__dataclass_fields__},
            "task_id": 99,
        }
    )
    with pytest.raises(ForeignKeyConflict):
        asyncio.run(
            repo.reject(
                input_review_ref=pending.input_review_ref,
                scope=wrong_scope,
                expected_state_version=1,
                actor_membership_role_id=1,
                trace_id="TRACE_wrong_scope_001",
                now=_NOW + timedelta(minutes=2),
            )
        )


def test_expired_review_cannot_be_disposed_and_uow_exposes_repository(session):
    claim = _claim(session)
    pending = _create(session, claim)
    with pytest.raises(OptimisticConcurrencyConflict):
        asyncio.run(
            _repo(session).reject(
                input_review_ref=pending.input_review_ref,
                scope=_scope(claim),
                expected_state_version=1,
                actor_membership_role_id=1,
                trace_id="TRACE_expired_review_001",
                now=_NOW + timedelta(hours=24, seconds=1),
            )
        )

    class _Session:
        async def begin(self):
            return None

        async def commit(self):
            return None

        async def rollback(self):
            return None

        async def close(self):
            return None

    async def check_uow():
        unit = SqlAlchemyUnitOfWork(lambda: _Session(), object())
        await unit.__aenter__()
        assert isinstance(
            unit.research_education_input_reviews,
            SchoolResearchEducationInputReviewRepository,
        )
        await unit.__aexit__(None, None, None)

    asyncio.run(check_uow())


def test_authorize_enqueues_one_round1_and_round0_replay_stays_unchanged(session):
    claim = _claim(session)
    pending = _create(session, claim)
    _finish_review_required(session, claim)

    authorized, continuation = _authorize(session, claim, pending)
    assert authorized.status == "CONTINUATION_AUTHORIZED"
    assert authorized.state_version == 2
    assert authorized.authorized_by_membership_role_id == 1
    assert authorized.grant_policy_version == "RESEARCH_INPUT_REVIEW_ONCE_V1"
    assert continuation.generation_round == 1
    assert continuation.input_review_id == authorized.id
    assert continuation.status == "QUEUED" and continuation.attempt_count == 0

    original = session.get(SchoolResearchEducationJob, claim.id)
    assert original is not None
    assert original.status == "REVIEW_REQUIRED"
    assert original.generation_round == 0 and original.input_review_id is None
    assert session.scalar(
        select(SchoolResearchEducationJob).where(
            SchoolResearchEducationJob.input_review_id == authorized.id
        )
    ).id == continuation.id

    jobs = SchoolResearchEducationJobRepository(
        cast(AsyncSession, _InputReviewAsyncSessionAdapter(session))
    )
    replay = asyncio.run(
        jobs.enqueue_completed_session(
            school_id=claim.school_id,
            research_session_id=claim.research_session_id,
            task_id=claim.task_id,
            class_id=claim.class_id,
            task_enrollment_id=claim.task_enrollment_id,
            subject_id=claim.subject_id,
            task_binding_id=claim.task_binding_id,
            profile_version_id=claim.profile_version_id,
            profile_ref=claim.profile_ref,
            profile_version_number=claim.profile_version_number,
            profile_sha256=claim.profile_sha256,
            response_origin=claim.response_origin,
            policy_version=claim.policy_version,
            policy_hash=claim.policy_hash,
            now=_NOW + timedelta(minutes=1),
        )
    )
    assert replay.id == claim.id and replay.generation_round == 0
    assert replay.input_review_id is None

    assert asyncio.run(
        jobs.claim_next(
            school_id=1,
            lease_owner="normal-worker",
            policy_version=GENERAL_EDUCATION_POLICY_VERSION,
            now=_NOW + timedelta(minutes=2),
        )
    ) == []
    claimed = asyncio.run(
        jobs.claim_next(
            school_id=1,
            lease_owner="continuation-worker",
            policy_version=GENERAL_EDUCATION_POLICY_VERSION,
            generation_round=1,
            max_attempts=1,
            now=_NOW + timedelta(minutes=2),
        )
    )
    assert len(claimed) == 1 and claimed[0].id == continuation.id
    assert claimed[0].generation_round == 1
    assert asyncio.run(
        jobs.claim_next(
            school_id=1,
            lease_owner="continuation-worker-2",
            policy_version=GENERAL_EDUCATION_POLICY_VERSION,
            generation_round=1,
            max_attempts=1,
            now=_NOW + timedelta(minutes=3),
        )
    ) == []


def test_dispatch_recheck_and_consume_require_current_review_pins(session):
    claim0 = _claim(session)
    pending = _create(session, claim0)
    _finish_review_required(session, claim0)
    authorized, continuation = _authorize(session, claim0, pending)
    jobs = SchoolResearchEducationJobRepository(
        cast(AsyncSession, _InputReviewAsyncSessionAdapter(session))
    )
    claim1 = asyncio.run(
        jobs.claim_next(
            school_id=1,
            lease_owner="continuation-worker",
            policy_version=GENERAL_EDUCATION_POLICY_VERSION,
            generation_round=1,
            max_attempts=1,
            now=_NOW + timedelta(minutes=2),
        )
    )[0]
    repo = _repo(session)
    pins = dict(
        claim=claim1,
        scope=_scope(claim1),
        grant_policy_version="RESEARCH_INPUT_REVIEW_ONCE_V1",
        grant_policy_hash="e" * 64,
        source_package_ref="student-r3-source-package",
        source_study_ref="school-noncommercial-rag-research-2027-06",
        source_manifest_sha256="c" * 64,
        prompt_id="PROMPT_research_general_education",
        prompt_version="1.4.0",
        prompt_sha256="d" * 64,
        canonical_input_sha256="b" * 64,
        now=_NOW + timedelta(minutes=2),
    )
    authorized_capability = asyncio.run(repo.require_authorized_continuation(**pins))
    assert authorized_capability.id == authorized.id
    assert authorized_capability.status == "CONTINUATION_AUTHORIZED"

    with pytest.raises(ResearchEducationInputReviewError):
        asyncio.run(
            repo.consume_for_candidate(
                **dict(
                    pins,
                    prompt_sha256="f" * 64,
                    trace_id="TRACE_consume_001",
                )
            )
        )
    assert (
        session.get(SchoolResearchEducationInputReview, authorized.id).status
        == "CONTINUATION_AUTHORIZED"
    )

    consumed = asyncio.run(
        repo.consume_for_candidate(
            **pins,
            trace_id="TRACE_consume_001",
        )
    )
    assert consumed.status == "CONSUMED" and consumed.state_version == 3
    assert consumed.consumed_at == _NOW + timedelta(minutes=2)
    event_rows = session.scalars(
        select(SchoolResearchEducationInputReviewEvent).order_by(
            SchoolResearchEducationInputReviewEvent.state_version
        )
    ).all()
    assert [(item.event_type, item.state_version) for item in event_rows] == [
        ("PENDING", 1),
        ("CONTINUATION_AUTHORIZED", 2),
        ("CONSUMED", 3),
    ]
    assert event_rows[-1].actor_membership_role_id is None
    assert continuation.input_review_id == consumed.id


def test_revoke_authorized_grant_cancels_continuation_job(session):
    claim0 = _claim(session)
    pending = _create(session, claim0)
    _finish_review_required(session, claim0)
    authorized, continuation = _authorize(session, claim0, pending)

    revoked = asyncio.run(
        _repo(session).revoke(
            input_review_ref=pending.input_review_ref,
            scope=_scope(claim0),
            expected_state_version=2,
            actor_membership_role_id=1,
            trace_id="TRACE_revoke_authorized_001",
            now=_NOW + timedelta(minutes=2),
        )
    )
    assert revoked.status == "REVOKED" and revoked.state_version == 3
    assert revoked.authorized_by_membership_role_id == 1
    assert session.get(SchoolResearchEducationJob, continuation.id).status == "CANCELLED"
    assert asyncio.run(
        SchoolResearchEducationJobRepository(
            cast(AsyncSession, _InputReviewAsyncSessionAdapter(session))
        ).claim_next(
            school_id=1,
            lease_owner="continuation-worker",
            policy_version=GENERAL_EDUCATION_POLICY_VERSION,
            generation_round=1,
            max_attempts=1,
            now=_NOW + timedelta(minutes=3),
        )
    ) == []
    assert authorized.id == revoked.id


def test_0021_migration_is_additive_has_short_names_and_refuses_data_downgrade():
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20261015_0021_school_research_education_input_reviews.py"
    )
    spec = importlib.util.spec_from_file_location("education_input_reviews_0021", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "20261015_0021"
    assert migration.down_revision == "20261015_0020"
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect=mysql.dialect(),
        opts={"as_sql": True, "output_buffer": output},
    )
    with Operations.context(context):
        migration.upgrade()
    sql = output.getvalue()
    names = re.findall(r"CONSTRAINT\s+`?([A-Za-z0-9_]+)`?", sql)
    assert names and all(len(name) <= 64 for name in names)
    model_names = set(
        re.findall(
            r"CONSTRAINT\s+`?([A-Za-z0-9_]+)`?",
            str(
                CreateTable(SchoolResearchEducationInputReview.__table__).compile(
                    dialect=mysql.dialect()
                )
            )
            + str(
                CreateTable(SchoolResearchEducationInputReviewEvent.__table__).compile(
                    dialect=mysql.dialect()
                )
            ),
        )
    )
    model_names -= {
        "school_research_education_input_review_status_scope_unique",
        "fk_school_research_education_input_review_authorizer_school",
        "fk_school_research_education_input_review_job_round_scope",
    }
    model_names = {name for name in model_names if "original_job" not in name}
    assert model_names <= set(names)
    assert "CREATE TABLE school_research_education_input_reviews" in sql
    assert "CREATE TABLE school_research_education_input_review_events" in sql
    assert "snapshot_ciphertext" not in sql and "input_text" not in sql
    assert "DATE_ADD" not in sql

    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE school_research_education_input_reviews (id INTEGER)"
            )
            connection.exec_driver_sql(
                "CREATE TABLE school_research_education_input_review_events (id INTEGER)"
            )
            connection.exec_driver_sql(
                "INSERT INTO school_research_education_input_reviews (id) VALUES (1)"
            )
            context = MigrationContext.configure(connection)
            with (
                Operations.context(context),
                pytest.raises(RuntimeError, match="refusing downgrade"),
            ):
                migration.downgrade()
            assert (
                connection.exec_driver_sql(
                    "SELECT COUNT(*) FROM school_research_education_input_reviews"
                ).scalar_one()
                == 1
            )
    finally:
        engine.dispose()


def test_0022_migration_adds_round_lineage_and_refuses_round1_downgrade():
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20261015_0022_research_education_input_review_continuation.py"
    )
    spec = importlib.util.spec_from_file_location("education_continuation_0022", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "20261015_0022"
    assert migration.down_revision == "20261015_0021"

    output = io.StringIO()
    context = MigrationContext.configure(
        dialect=mysql.dialect(),
        opts={"as_sql": True, "output_buffer": output},
    )
    with Operations.context(context):
        migration.upgrade()
    sql = output.getvalue()
    assert "generation_round" in sql
    assert "input_review_id" in sql
    assert "CONTINUATION_AUTHORIZED" in sql
    assert "CONSUMED" in sql
    assert "fk_school_research_education_candidate_consumed_review" in sql
    names = re.findall(r"CONSTRAINT\s+`?([A-Za-z0-9_]+)`?", sql)
    assert names and all(len(name) <= 64 for name in names)

    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE school_research_education_jobs "
                "(generation_round INTEGER, input_review_id INTEGER)"
            )
            connection.exec_driver_sql(
                "INSERT INTO school_research_education_jobs VALUES (1, 9)"
            )
            context = MigrationContext.configure(connection)
            with (
                Operations.context(context),
                pytest.raises(RuntimeError, match="jobs has continuation data"),
            ):
                migration.downgrade()
            assert connection.exec_driver_sql(
                "SELECT generation_round, input_review_id "
                "FROM school_research_education_jobs"
            ).one() == (1, 9)
    finally:
        engine.dispose()
