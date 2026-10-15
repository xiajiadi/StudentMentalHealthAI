from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import io
import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from database_layer.base import Base
from database_layer.errors import OptimisticConcurrencyConflict, UniqueConflict
from database_layer.models import (
    SchoolResearchEducationCandidate,
    SchoolResearchEducationCandidateEvent,
    SchoolResearchFeedbackRecord,
)
from database_layer.school_research_education_candidates import (
    ResearchEducationCandidateError,
    ResearchEducationCandidateScope,
    SchoolResearchEducationCandidateRepository,
    _required_utc_aware,
    _utc_aware,
)
from database_layer.school_research_education_input_reviews import (
    SchoolResearchEducationInputReviewRepository,
)
from database_layer.school_research_education_jobs import (
    GENERAL_EDUCATION_POLICY_VERSION,
    SchoolResearchEducationJobRepository,
)
from database_layer.unit_of_work import SqlAlchemyUnitOfWork
from sqlalchemy import (
    CheckConstraint,
    Column,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    event,
    select,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from test_school_research_education_input_reviews import (
    _authorize,
    _finish_review_required,
)
from test_school_research_education_input_reviews import (
    _create as _create_input_review,
)
from test_school_research_education_input_reviews import (
    _scope as _input_review_scope,
)
from test_school_research_education_jobs import _AsyncSessionAdapter, _seed

_NOW = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
_POLICY_HASH = "a" * 64
_MANIFEST_HASH = "b" * 64


class _CandidateAsyncSessionAdapter(_AsyncSessionAdapter):
    async def execute(self, statement):
        return self.sync.execute(statement)


@pytest.fixture
def session(monkeypatch):
    medium_blob_cls = type(mysql.MEDIUMBLOB())
    big_int_cls = type(mysql.BIGINT(unsigned=True))
    medium_blob_dispatch = medium_blob_cls._compiler_dispatch
    big_int_dispatch = big_int_cls._compiler_dispatch

    def compile_blob(self, visitor, **kw):
        if visitor.dialect.name == "sqlite":
            return "BLOB"
        return medium_blob_dispatch(self, visitor, **kw)

    def compile_bigint(self, visitor, **kw):
        if visitor.dialect.name == "sqlite":
            return "INTEGER"
        return big_int_dispatch(self, visitor, **kw)

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
    return ResearchEducationCandidateScope(
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


def _candidate_values(claim):
    trace_id = "TRACE_general_001"
    if claim.generation_round == 1:
        token = hashlib.sha256(
            f"{claim.job_ref}:{claim.attempt_count}".encode("ascii")
        ).hexdigest()[:32]
        trace_id = f"TRACE_{token}"
    return {
        "claim": claim,
        "scope": _scope(claim),
        "candidate_ref": "RGECAND_" + claim.job_ref[4:],
        "study_ref": "school-general-education-r3",
        "policy_version": GENERAL_EDUCATION_POLICY_VERSION,
        "policy_hash": _POLICY_HASH,
        "source_manifest_sha256": _MANIFEST_HASH,
        "retrieval_id": "RETR_general_001",
        "retrieval_bundle_sha256": "c" * 64,
        "prompt_ref": "PROMPT_general_education",
        "prompt_version": "1.0.0",
        "prompt_sha256": "d" * 64,
        "model_ref": "MODEL_pinned_local_7b",
        "model_digest_sha256": "e" * 64,
        "runtime_version": "ollama-pinned-v1",
        "safety_policy_version": "research-safety-v1",
        "input_safety_action": "PROCEED",
        "retrieval_safety_action": "PROCEED_WITH_BOUNDARY",
        "output_safety_action": "PROCEED",
        "content_sha256": "f" * 64,
        "payload_ciphertext": b"synthetic-encrypted-general-education-candidate",
        "cipher_format_version": "fernet.v1",
        "key_version": "school-key-v1",
        "payload_schema_version": "school_research_education_candidate.v1",
        "trace_id": trace_id,
        "now": _NOW,
    }


def _claim(session):
    jobs = SchoolResearchEducationJobRepository(_CandidateAsyncSessionAdapter(session))
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
    claims = asyncio.run(
        jobs.claim_next(
            school_id=1,
            lease_owner="general-education-worker",
            policy_version=GENERAL_EDUCATION_POLICY_VERSION,
            now=_NOW,
        )
    )
    assert len(claims) == 1
    return claims[0]


def test_candidate_schema_is_exact_session_job_bound_and_ciphertext_only():
    candidate = SchoolResearchEducationCandidate.__table__
    event_table = SchoolResearchEducationCandidateEvent.__table__
    assert "payload_ciphertext" in candidate.columns
    assert candidate.c.status.server_default.arg == "HELD"
    assert candidate.c.content_revision.default.arg == 1
    assert not {
        "answer", "score", "snapshot_ciphertext", "candidate_body", "candidate_text"
    }.intersection(candidate.columns.keys())
    assert candidate.c.payload_ciphertext.type.python_type is bytes
    assert candidate.c.generation_round.default.arg == 0
    assert candidate.c.generation_round.nullable is False
    assert candidate.c.input_review_id.nullable is True
    assert candidate.c.input_review_state.nullable is True
    assert event_table.c["candidate_id"].nullable is False
    assert not any(name.endswith("ciphertext") for name in event_table.columns.keys())

    foreign_keys = {
        (tuple(element.parent.name for element in constraint.elements),
         constraint.referred_table.name,
         tuple(element.column.name for element in constraint.elements))
        for constraint in candidate.foreign_key_constraints
    }
    assert (
        ("job_id", "research_session_id", "school_id"),
        "school_research_education_jobs",
        ("id", "research_session_id", "school_id"),
    ) in foreign_keys
    assert (
        ("job_id", "generation_round", "research_session_id", "school_id"),
        "school_research_education_jobs",
        ("id", "generation_round", "research_session_id", "school_id"),
    ) in foreign_keys
    assert (
        ("job_id", "input_review_id", "research_session_id", "school_id"),
        "school_research_education_jobs",
        ("id", "input_review_id", "research_session_id", "school_id"),
    ) in foreign_keys
    assert (
        ("input_review_id", "input_review_state", "research_session_id", "school_id"),
        "school_research_education_input_reviews",
        ("id", "status", "research_session_id", "school_id"),
    ) in foreign_keys
    assert set(
        element.parent.name
        for constraint in candidate.foreign_key_constraints
        if constraint.referred_table.name == "school_research_sessions"
        for element in constraint.elements
    ) == {
        "research_session_id", "school_id", "task_id", "class_id", "task_enrollment_id",
        "subject_id", "task_binding_id", "profile_version_id", "profile_ref",
        "profile_version_number", "profile_sha256", "response_origin",
    }
    feedback = SchoolResearchFeedbackRecord.__table__
    assert feedback.c.source_candidate_id.nullable is True
    assert feedback.c.source_candidate_revision.nullable is True
    mysql_sql = str(CreateTable(candidate).compile(dialect=mysql.dialect()))
    assert "payload_ciphertext MEDIUMBLOB NOT NULL" in mysql_sql
    assert "snapshot_ciphertext" not in mysql_sql and "answer" not in mysql_sql
    assert candidate.c.input_review_state.type.length == 24


def test_candidate_round_safety_check_rejects_partial_review_and_keeps_normal_round0():
    candidate = SchoolResearchEducationCandidate.__table__
    check = next(
        constraint
        for constraint in candidate.constraints
        if isinstance(constraint, CheckConstraint)
        and constraint.name.endswith("safety_actions_allowed")
    )
    guard = Table(
        "candidate_review_round_guard",
        MetaData(),
        Column("generation_round", Integer, nullable=False),
        Column("input_review_id", Integer, nullable=True),
        Column("input_review_state", String(24), nullable=True),
        Column("output_review_id", Integer, nullable=True),
        Column("output_review_state", String(16), nullable=True),
        Column("input_safety_action", String(32), nullable=False),
        Column("retrieval_safety_action", String(32), nullable=False),
        Column("output_safety_action", String(32), nullable=False),
        CheckConstraint(str(check.sqltext), name="round_review_actions_match"),
    )
    engine = create_engine("sqlite://")
    guard.metadata.create_all(engine)
    try:
        with engine.begin() as connection:
            connection.execute(
                guard.insert().values(
                    generation_round=0,
                    input_review_id=None,
                    input_review_state=None,
                    input_safety_action="PROCEED",
                    retrieval_safety_action="PROCEED",
                    output_safety_action="PROCEED_WITH_BOUNDARY",
                )
            )
            connection.execute(
                guard.insert().values(
                    generation_round=0,
                    input_review_id=None,
                    input_review_state=None,
                    output_review_id=11,
                    output_review_state="CONSUMED",
                    input_safety_action="PROCEED",
                    retrieval_safety_action="PROCEED",
                    output_safety_action="REVIEW_REQUIRED",
                )
            )
            connection.execute(
                guard.insert().values(
                    generation_round=1,
                    input_review_id=7,
                    input_review_state="CONSUMED",
                    input_safety_action="REVIEW_REQUIRED",
                    retrieval_safety_action="PROCEED",
                    output_safety_action="PROCEED",
                )
            )
        for values in (
            {"generation_round": 0, "input_review_id": None, "input_review_state": "CONSUMED",
             "input_safety_action": "PROCEED"},
            {"generation_round": 1, "input_review_id": 7, "input_review_state": None,
             "input_safety_action": "REVIEW_REQUIRED"},
            {"generation_round": 1, "input_review_id": None, "input_review_state": None,
             "input_safety_action": "REVIEW_REQUIRED"},
            {"generation_round": 0, "input_review_id": None, "input_review_state": None,
             "input_safety_action": "REVIEW_REQUIRED"},
            {"generation_round": 0, "input_review_id": None, "input_review_state": None,
             "output_review_id": None, "output_review_state": None,
             "input_safety_action": "PROCEED", "output_safety_action": "REVIEW_REQUIRED"},
            {"generation_round": 0, "input_review_id": None, "input_review_state": None,
             "output_review_id": 11, "output_review_state": None,
             "input_safety_action": "PROCEED", "output_safety_action": "REVIEW_REQUIRED"},
            {"generation_round": 0, "input_review_id": None, "input_review_state": None,
             "output_review_id": 11, "output_review_state": "CONSUMED",
             "input_safety_action": "PROCEED", "output_safety_action": "PROCEED"},
        ):
            with pytest.raises(IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        guard.insert().values(
                            {
                                "input_review_state": None,
                                "input_review_id": None,
                                "input_safety_action": "PROCEED",
                                "retrieval_safety_action": "PROCEED",
                                "output_safety_action": "PROCEED",
                                **values,
                            }
                        )
                    )
    finally:
        engine.dispose()


def test_feedback_candidate_pair_check_preserves_legacy_nulls_and_rejects_partial_pairs():
    feedback = SchoolResearchFeedbackRecord.__table__
    pair_constraint = next(
        constraint
        for constraint in feedback.constraints
        if isinstance(constraint, CheckConstraint)
        and "source_candidate_id IS NULL" in str(constraint.sqltext)
    )
    metadata = MetaData()
    guard = Table(
        "feedback_candidate_pair_guard",
        metadata,
        Column("source_candidate_id", Integer, nullable=True),
        Column("source_candidate_revision", Integer, nullable=True),
        CheckConstraint(str(pair_constraint.sqltext), name="candidate_pair_matches"),
    )
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    try:
        with engine.begin() as connection:
            connection.execute(
                guard.insert().values(
                    source_candidate_id=None, source_candidate_revision=None
                )
            )
            connection.execute(
                guard.insert().values(
                    source_candidate_id=17, source_candidate_revision=1
                )
            )
        for values in (
            {"source_candidate_id": 17, "source_candidate_revision": None},
            {"source_candidate_id": None, "source_candidate_revision": 1},
            {"source_candidate_id": 17, "source_candidate_revision": 2},
        ):
            with pytest.raises(IntegrityError):
                with engine.begin() as connection:
                    connection.execute(guard.insert().values(**values))
    finally:
        engine.dispose()


def test_candidate_datetime_projection_normalizes_naive_aware_and_nullable_values():
    naive = datetime(2026, 10, 16, 12, 34, 56, 789123)
    aware = naive.replace(tzinfo=UTC)

    assert _utc_aware(naive) == aware
    assert _utc_aware(aware) == aware
    assert _utc_aware(None) is None
    assert _required_utc_aware(naive) == aware
    assert _required_utc_aware(aware) == aware
    with pytest.raises(ResearchEducationCandidateError, match="PERSISTED_TIMESTAMP_INVALID"):
        _required_utc_aware(None)


def test_held_candidate_replay_resolve_and_append_only_events(session):
    claim = _claim(session)
    repository = SchoolResearchEducationCandidateRepository(
        _CandidateAsyncSessionAdapter(session)
    )
    values = _candidate_values(claim)

    first = asyncio.run(repository.create_held(**values))
    replay = asyncio.run(repository.create_held(**values))

    assert first.id == replay.id
    assert first.candidate_ref == replay.candidate_ref
    assert first.status == "HELD" and first.state_version == 1
    assert first.content_revision == 1
    assert first.generation_round == 0
    assert first.input_review_id is None and first.input_review_state is None
    assert first.created_at.tzinfo is UTC and first.updated_at.tzinfo is UTC
    assert first.resolved_at is None
    assert first.source_manifest_sha256 == _MANIFEST_HASH
    assert first.purpose == "RESEARCH_SIMULATION"
    assert first.research_only is True
    assert first.psychological_interpretation_allowed is False
    assert first.publication_status == "not_approved_for_publication_or_operational_use"
    assert b"synthetic-encrypted-general-education-candidate" not in repr(first).encode()

    listed = asyncio.run(repository.list_for_task(school_id=1, task_id=1))
    fetched = asyncio.run(
        repository.get_for_task(
            school_id=1, task_id=1, candidate_ref=first.candidate_ref
        )
    )
    assert [item.id for item in listed] == [first.id]
    assert fetched is not None and fetched.id == first.id

    adopted = asyncio.run(
        repository.resolve(
            school_id=1,
            task_id=1,
            candidate_ref=first.candidate_ref,
            expected_state_version=1,
            target="ADOPTED",
            actor_membership_role_id=1,
            trace_id="TRACE_review_001",
            now=_NOW,
        )
    )
    assert adopted.status == "ADOPTED" and adopted.state_version == 2
    assert adopted.trace_id == first.trace_id
    events = session.scalars(
        select(SchoolResearchEducationCandidateEvent).order_by(
            SchoolResearchEducationCandidateEvent.state_version
        )
    ).all()
    assert [(event.event_type, event.state_version) for event in events] == [
        ("HELD", 1), ("ADOPTED", 2)
    ]
    assert events[0].actor_membership_role_id is None
    assert events[1].actor_membership_role_id == 1

    with pytest.raises(OptimisticConcurrencyConflict):
        asyncio.run(
            repository.resolve(
                school_id=1,
                task_id=1,
                candidate_ref=first.candidate_ref,
                expected_state_version=1,
                target="DISCARDED",
                actor_membership_role_id=1,
                trace_id="TRACE_review_002",
                now=_NOW,
            )
        )


def test_candidate_replay_with_different_content_or_scope_fails_closed(session):
    claim = _claim(session)
    repository = SchoolResearchEducationCandidateRepository(
        _CandidateAsyncSessionAdapter(session)
    )
    values = _candidate_values(claim)
    asyncio.run(repository.create_held(**values))

    changed_payload = dict(values, content_sha256="0" * 64)
    with pytest.raises(UniqueConflict):
        asyncio.run(repository.create_held(**changed_payload))

    wrong_scope = replace(_scope(claim), task_id=999)
    with pytest.raises(ResearchEducationCandidateError):
        asyncio.run(repository.create_held(**dict(values, scope=wrong_scope)))

    with pytest.raises(ResearchEducationCandidateError):
        asyncio.run(repository.create_held(**dict(values, output_safety_action="REVIEW_REQUIRED")))


def test_reviewed_candidate_requires_and_persists_consumed_round1_sidecar(session):
    claim0 = _claim(session)
    pending = _create_input_review(session, claim0)
    _finish_review_required(session, claim0)
    authorized, continuation = _authorize(session, claim0, pending)
    jobs = SchoolResearchEducationJobRepository(_CandidateAsyncSessionAdapter(session))
    claim1 = asyncio.run(
        jobs.claim_next(
            school_id=claim0.school_id,
            lease_owner="continuation-worker",
            policy_version=GENERAL_EDUCATION_POLICY_VERSION,
            generation_round=1,
            max_attempts=1,
            now=_NOW.replace(minute=2),
        )
    )[0]
    input_reviews = SchoolResearchEducationInputReviewRepository(
        _CandidateAsyncSessionAdapter(session)
    )
    evidence = pending
    consumed = asyncio.run(
        input_reviews.consume_for_candidate(
            claim=claim1,
            scope=_input_review_scope(claim0),
            grant_policy_version="RESEARCH_INPUT_REVIEW_ONCE_V1",
            grant_policy_hash="e" * 64,
            source_package_ref=evidence.source_package_ref,
            source_study_ref=evidence.source_study_ref,
            source_manifest_sha256=evidence.source_manifest_sha256,
            prompt_id=evidence.prompt_id,
            prompt_version=evidence.prompt_version,
            prompt_sha256=evidence.prompt_sha256,
            canonical_input_sha256=evidence.canonical_input_sha256,
            trace_id="TRACE_candidate_consume_001",
            now=_NOW.replace(minute=2),
        )
    )
    values = _candidate_values(claim1)
    values.update(
        input_safety_action="REVIEW_REQUIRED",
        input_review=consumed,
        source_manifest_sha256=consumed.source_manifest_sha256,
        prompt_ref=consumed.prompt_id,
        prompt_version=consumed.prompt_version,
        prompt_sha256=consumed.prompt_sha256,
        now=_NOW.replace(minute=2),
    )
    repository = SchoolResearchEducationCandidateRepository(
        _CandidateAsyncSessionAdapter(session)
    )
    with pytest.raises(ResearchEducationCandidateError, match="INPUT_REVIEW_TRACE_INVALID"):
        asyncio.run(repository.create_held(**dict(values, trace_id="TRACE_unbound")))
    candidate = asyncio.run(repository.create_held(**values))
    assert candidate.generation_round == 1
    assert candidate.input_review_id == consumed.id
    assert candidate.input_review_state == "CONSUMED"
    assert candidate.input_safety_action == "REVIEW_REQUIRED"
    assert candidate.created_at == consumed.consumed_at
    assert candidate.updated_at == candidate.created_at
    assert candidate.created_at.tzinfo is UTC

    stored_candidate = session.get(SchoolResearchEducationCandidate, candidate.id)
    assert stored_candidate is not None
    valid_trace = stored_candidate.trace_id
    stored_candidate.trace_id = "TRACE_unbound"
    session.flush()
    with pytest.raises(
        ResearchEducationCandidateError,
        match="CANDIDATE_CONTINUATION_LINEAGE_INVALID",
    ):
        asyncio.run(
            repository.get_for_task(
                school_id=claim1.school_id,
                task_id=claim1.task_id,
                candidate_ref=candidate.candidate_ref,
            )
        )
    stored_candidate.trace_id = valid_trace
    session.flush()

    finalized = asyncio.run(
        jobs.finish(
            school_id=claim1.school_id,
            research_session_id=claim1.research_session_id,
            job_id=claim1.id,
            lease_owner=claim1.lease_owner,
            lease_token=claim1.lease_token,
            status="HELD",
            now=_NOW.replace(minute=2),
        )
    )
    assert finalized.status == "HELD" and finalized.generation_round == 1
    assert continuation.id == claim1.id and authorized.id == consumed.id
    listed = asyncio.run(repository.list_for_task(school_id=1, task_id=1))
    fetched = asyncio.run(
        repository.get_for_task(
            school_id=1, task_id=1, candidate_ref=candidate.candidate_ref
        )
    )
    assert [row.input_review_id for row in listed] == [consumed.id]
    assert fetched is not None and fetched.input_review_state == "CONSUMED"


def test_candidate_repository_never_selects_cat_snapshot(session):
    claim = _claim(session)
    statements: list[str] = []

    @event.listens_for(session.bind, "before_cursor_execute")
    def remember_sql(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lower())

    repository = SchoolResearchEducationCandidateRepository(
        _CandidateAsyncSessionAdapter(session)
    )
    asyncio.run(repository.create_held(**_candidate_values(claim)))
    assert statements
    assert all("snapshot_ciphertext" not in statement for statement in statements)


def test_unit_of_work_exposes_education_candidate_repository():
    class _Session:
        async def begin(self):
            return None

        async def commit(self):
            return None

        async def rollback(self):
            return None

        async def close(self):
            return None

    async def run():
        unit = SqlAlchemyUnitOfWork(lambda: _Session(), object())
        await unit.__aenter__()
        assert isinstance(
            unit.research_education_candidates,
            SchoolResearchEducationCandidateRepository,
        )
        await unit.__aexit__(None, None, None)

    asyncio.run(run())


def test_0020_migration_links_candidate_and_feedback_lineage(monkeypatch):
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20261015_0020_school_research_education_candidates.py"
    )
    spec = importlib.util.spec_from_file_location("education_candidates_0020", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "20261015_0020"
    assert migration.down_revision == "20261015_0019"
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect=mysql.dialect(),
        opts={"as_sql": True, "output_buffer": output},
    )
    with Operations.context(context):
        migration.upgrade()

    sql = output.getvalue()
    constraint_names = re.findall(r"CONSTRAINT\s+`?([A-Za-z0-9_]+)`?", sql)
    assert constraint_names
    assert all(len(name) <= 64 for name in constraint_names)
    event_ddl = str(
        CreateTable(SchoolResearchEducationCandidateEvent.__table__).compile(
            dialect=mysql.dialect()
        )
    )
    event_model_names = set(
        re.findall(r"CONSTRAINT\s+`?([A-Za-z0-9_]+)`?", event_ddl)
    )
    assert event_model_names <= set(constraint_names)
    for required in (
        "school_research_education_job_id_session_school_unique",
        "CREATE TABLE school_research_education_candidates",
        "CREATE TABLE school_research_education_candidate_events",
        "payload_ciphertext MEDIUMBLOB NOT NULL",
        "source_candidate_id BIGINT UNSIGNED",
        "source_candidate_revision INTEGER",
        "fk_school_research_feedback_source_candidate_exact_scope",
    ):
        assert required in sql
    assert "snapshot_ciphertext" not in sql

    feedback_constraints = SchoolResearchFeedbackRecord.__table__.foreign_key_constraints
    assert any(
        constraint.name == "fk_school_research_feedback_source_candidate_exact_scope"
        and tuple(element.parent.name for element in constraint.elements)
        == ("source_candidate_id", "research_session_id", "school_id")
        for constraint in feedback_constraints
    )
