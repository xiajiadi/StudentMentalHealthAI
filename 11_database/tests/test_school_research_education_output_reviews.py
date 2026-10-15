from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import io
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from database_layer.base import Base
from database_layer.errors import OptimisticConcurrencyConflict
from database_layer.models import (
    SchoolResearchEducationCandidate,
    SchoolResearchEducationCandidateEvent,
    SchoolResearchEducationInputReview,
    SchoolResearchEducationOutputReview,
    SchoolResearchEducationOutputReviewEvent,
    SchoolResearchEducationJob,
)
from database_layer.school_research_education_candidates import (
    ResearchEducationCandidateScope,
    SchoolResearchEducationCandidateRepository,
)
from database_layer.school_research_education_input_reviews import (
    SchoolResearchEducationInputReviewRepository,
)
from database_layer.school_research_education_jobs import (
    GENERAL_EDUCATION_POLICY_VERSION,
    ResearchEducationJobErrorCode,
    SchoolResearchEducationJobRepository,
)
from database_layer.school_research_education_output_reviews import (
    CANDIDATE_PAYLOAD_SCHEMA_VERSION,
    OUTPUT_REVIEW_PAYLOAD_SCHEMA_VERSION,
    ResearchEducationOutputReviewError,
    ResearchEducationOutputReviewEvidence,
    ResearchEducationOutputReviewScope,
    ResearchEducationOutputReviewStatus as ReviewStatus,
    SchoolResearchEducationOutputReviewRepository,
)
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from test_school_research_education_candidates import _claim as _round0_claim
from test_school_research_education_candidates import _scope as _candidate_scope
from test_school_research_education_input_reviews import (
    _authorize,
    _claim as _claim_for_input_review,
    _create as _create_input_review,
    _evidence as _input_evidence,
    _finish_review_required,
    _scope as _input_scope,
)
from test_school_research_education_jobs import _AsyncSessionAdapter, _seed

_NOW = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
_POLICY_HASH = "a" * 64
_MANIFEST_HASH = "b" * 64
_CANDIDATE_HASH = "c" * 64
_RETRIEVAL_HASH = "d" * 64
_PROMPT_HASH = "e" * 64
_MODEL_HASH = "f" * 64


class _OutputReviewAsyncSessionAdapter(_AsyncSessionAdapter):
    async def execute(self, statement):
        return self.sync.execute(statement)


@pytest.fixture
def session(monkeypatch):
    medium_blob_cls = type(mysql.MEDIUMBLOB())
    big_int_cls = type(mysql.BIGINT(unsigned=True))
    medium_blob_dispatch = medium_blob_cls._compiler_dispatch
    big_int_dispatch = big_int_cls._compiler_dispatch

    def compile_blob(self, visitor, **kwargs):
        return "BLOB" if visitor.dialect.name == "sqlite" else medium_blob_dispatch(self, visitor, **kwargs)

    def compile_bigint(self, visitor, **kwargs):
        return "INTEGER" if visitor.dialect.name == "sqlite" else big_int_dispatch(self, visitor, **kwargs)

    monkeypatch.setattr(medium_blob_cls, "_compiler_dispatch", compile_blob)
    monkeypatch.setattr(big_int_cls, "_compiler_dispatch", compile_bigint)
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def setup_sqlite(connection, _record):
        connection.create_collation("ascii_bin", lambda left, right: (left > right) - (left < right))
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    db = Session(engine)
    _seed(db)
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _trace(job_ref: str, attempt: int = 1) -> str:
    token = hashlib.sha256(f"{job_ref}:{attempt}".encode("ascii")).hexdigest()[:32]
    return f"TRACE_{token}"


def _output_scope(claim):
    return ResearchEducationOutputReviewScope(**{
        field: getattr(claim, field)
        for field in ResearchEducationCandidateScope.__dataclass_fields__
    })


def _evidence(claim, *, input_review=None, **changes):
    trace = _trace(claim.job_ref, claim.attempt_count)
    values = dict(
        safety_decision_id="DEC_output_synthetic_001",
        safety_review_ref="REVIEW_output_synthetic_001",
        safety_trace_id=trace,
        safety_operation="OUTPUT",
        safety_action="REVIEW_REQUIRED",
        safety_reason_codes=("CONTENT_CONTROVERSIAL",),
        safety_requires_human=True,
        input_safety_action=("REVIEW_REQUIRED" if input_review is not None else "PROCEED"),
        retrieval_safety_action="PROCEED_WITH_BOUNDARY",
        canonical_input_sha256=(
            input_review.canonical_input_sha256 if input_review is not None else None
        ),
        policy_version=GENERAL_EDUCATION_POLICY_VERSION,
        policy_hash=claim.policy_hash,
        source_package_ref=(
            input_review.source_package_ref if input_review is not None else "student-r3-source-package"
        ),
        source_study_ref=(
            input_review.source_study_ref if input_review is not None else "school-general-education-r3"
        ),
        source_manifest_sha256=(
            input_review.source_manifest_sha256 if input_review is not None else _MANIFEST_HASH
        ),
        retrieval_id="RETR_general_001",
        retrieval_bundle_sha256=_RETRIEVAL_HASH,
        prompt_id=(
            input_review.prompt_id if input_review is not None else "PROMPT_research_general_education"
        ),
        prompt_version=(input_review.prompt_version if input_review is not None else "1.4.0"),
        prompt_sha256=(input_review.prompt_sha256 if input_review is not None else _PROMPT_HASH),
        model_ref="MODEL_pinned_local_7b",
        model_digest_sha256=_MODEL_HASH,
        runtime_version="ollama-pinned-v1",
        safety_policy_version="research-safety-v1",
        candidate_content_sha256=None,
        candidate_payload_schema_version=None,
        expires_at=_NOW + timedelta(hours=12),
        trace_id=trace,
    )
    values.update(changes)
    return ResearchEducationOutputReviewEvidence(**values)


def _repo(session):
    return SchoolResearchEducationOutputReviewRepository(
        _OutputReviewAsyncSessionAdapter(session)
    )


def _create_output_review(session, claim, *, evidence=None, now=_NOW):
    return asyncio.run(
        _repo(session).create_pending(
            claim=claim,
            scope=_output_scope(claim),
            evidence=evidence or _evidence(claim),
            content_sha256="1" * 64,
            payload_ciphertext=b"encrypted-output-review-envelope",
            cipher_format_version="fernet.v1",
            key_version="school-key-v1",
            payload_schema_version=OUTPUT_REVIEW_PAYLOAD_SCHEMA_VERSION,
            now=now,
        )
    )


def _finish_review_job(session, claim, now):
    return asyncio.run(
        SchoolResearchEducationJobRepository(_OutputReviewAsyncSessionAdapter(session)).finish(
            school_id=claim.school_id,
            research_session_id=claim.research_session_id,
            job_id=claim.id,
            lease_owner=claim.lease_owner,
            lease_token=claim.lease_token,
            status="REVIEW_REQUIRED",
            error_code=ResearchEducationJobErrorCode.SAFETY_BLOCKED,
            now=now,
        )
    )


def _create_candidate_from_output_review(session, claim, review, *, actor_id=1, now=_NOW):
    return asyncio.run(
        SchoolResearchEducationCandidateRepository(
            _OutputReviewAsyncSessionAdapter(session)
        ).create_held_from_output_review(
            scope=_candidate_scope(claim),
            output_review_ref=review.output_review_ref,
            candidate_ref=f"RGECAND_{claim.job_ref[4:]}",
            content_sha256=_CANDIDATE_HASH,
            payload_ciphertext=b"encrypted-reviewed-candidate",
            cipher_format_version="fernet.v1",
            key_version="school-key-v1",
            payload_schema_version=CANDIDATE_PAYLOAD_SCHEMA_VERSION,
            actor_membership_role_id=actor_id,
            trace_id="TRACE_candidate_resolve_001",
            now=now,
        )
    )


def test_output_review_schema_is_scoped_encrypted_and_only_accepts_consumed_lineage():
    review = SchoolResearchEducationOutputReview.__table__
    events = SchoolResearchEducationOutputReviewEvent.__table__
    candidate = SchoolResearchEducationCandidate.__table__
    assert review.c.payload_ciphertext.type.python_type is bytes
    assert review.c.payload_ciphertext.type.__class__ is mysql.MEDIUMBLOB
    assert review.c.status.server_default.arg == ReviewStatus.PENDING.value
    assert review.c.generation_round.nullable is False
    assert review.c.input_review_id.nullable is True
    assert review.c.candidate_content_sha256.nullable is True
    assert review.c.candidate_payload_schema_version.nullable is True
    assert review.c.safety_action.default is None
    assert review.c.safety_operation.default is None
    assert events.c.trace_id.nullable is False
    assert not any(name.endswith("ciphertext") for name in events.columns.keys())
    assert candidate.c.output_review_id.nullable is True
    assert candidate.c.output_review_state.nullable is True
    assert {
        (tuple(element.parent.name for element in constraint.elements), constraint.referred_table.name)
        for constraint in candidate.foreign_key_constraints
    } >= {
        (("output_review_id", "output_review_state", "job_id", "generation_round", "research_session_id", "school_id"),
         "school_research_education_output_reviews")
    }
    assert all(
        len(constraint.name or "") <= 64
        for table in (review, events)
        for constraint in (*table.constraints, *table.indexes)
    )


def test_pending_output_review_requires_exact_stop_scope_expiry_and_replay(session):
    claim = _round0_claim(session)
    repository = _repo(session)
    scope = _output_scope(claim)
    evidence = _evidence(claim)
    first = asyncio.run(repository.create_pending(
        claim=claim,
        scope=scope,
        evidence=evidence,
        content_sha256="1" * 64,
        payload_ciphertext=b"encrypted-output-review-envelope",
        cipher_format_version="fernet.v1",
        key_version="school-key-v1",
        now=_NOW,
    ))
    second = asyncio.run(repository.create_pending(
        claim=claim,
        scope=scope,
        evidence=evidence,
        content_sha256="1" * 64,
        payload_ciphertext=b"another-ciphertext-for-same-plaintext-hash",
        cipher_format_version="fernet.v1",
        key_version="school-key-v1",
        now=_NOW,
    ))
    assert first.id == second.id
    assert first.status == "PENDING"
    assert first.candidate_content_sha256 is None
    assert first.candidate_payload_schema_version is None
    assert first.payload_ciphertext == b"encrypted-output-review-envelope"
    assert first.payload_schema_version == OUTPUT_REVIEW_PAYLOAD_SCHEMA_VERSION
    with pytest.raises((ResearchEducationOutputReviewError, OptimisticConcurrencyConflict)):
        asyncio.run(repository.create_pending(
            claim=claim,
            scope=replace(scope, school_id=999),
            evidence=evidence,
            content_sha256="1" * 64,
            payload_ciphertext=b"encrypted",
            cipher_format_version="fernet.v1",
            key_version="school-key-v1",
            now=_NOW,
        ))
    with pytest.raises(ResearchEducationOutputReviewError):
        _create_output_review(
            session,
            claim,
            evidence=replace(evidence, expires_at=_NOW + timedelta(hours=25)),
        )
    with pytest.raises(ResearchEducationOutputReviewError):
        _create_output_review(session, claim, evidence=replace(evidence, safety_reason_codes=("CRISIS",)))
    with pytest.raises(ResearchEducationOutputReviewError):
        _create_output_review(
            session,
            claim,
            evidence=replace(
                evidence,
                candidate_content_sha256=_CANDIDATE_HASH,
                candidate_payload_schema_version=CANDIDATE_PAYLOAD_SCHEMA_VERSION,
            ),
        )
    with pytest.raises(ResearchEducationOutputReviewError):
        asyncio.run(repository.create_pending(
            claim=claim,
            scope=scope,
            evidence=evidence,
            content_sha256="1" * 64,
            payload_ciphertext=b"x" * 1_000_001,
            cipher_format_version="fernet.v1",
            key_version="school-key-v1",
            now=_NOW,
        ))

    _finish_review_job(session, claim, _NOW + timedelta(seconds=30))
    summary = asyncio.run(
        repository.list_for_task(school_id=claim.school_id, task_id=claim.task_id)
    )
    assert len(summary) == 1
    assert summary[0].output_review_ref == first.output_review_ref
    assert not hasattr(summary[0], "payload_ciphertext")
    exact_scope = asyncio.run(repository.find_scope_for_task(
        school_id=claim.school_id,
        task_id=claim.task_id,
        output_review_ref=first.output_review_ref,
    ))
    assert exact_scope == scope
    assert asyncio.run(repository.get_for_task(
        scope=scope, output_review_ref=first.output_review_ref
    )).payload_ciphertext == first.payload_ciphertext
    assert asyncio.run(repository.get_for_task(
        scope=replace(scope, task_id=999), output_review_ref=first.output_review_ref
    )) is None


def test_round0_output_review_candidate_consumes_one_receipt_and_keeps_job_terminal(session):
    claim = _round0_claim(session)
    review = _create_output_review(session, claim)
    _finish_review_job(session, claim, _NOW + timedelta(seconds=30))
    candidate = _create_candidate_from_output_review(
        session, claim, review, now=_NOW + timedelta(minutes=1)
    )
    session.expire_all()
    persisted_review = session.scalar(
        select(SchoolResearchEducationOutputReview).where(
            SchoolResearchEducationOutputReview.id == review.id
        )
    )
    job = session.scalar(
        select(SchoolResearchEducationJob).where(SchoolResearchEducationJob.id == claim.id)
    )
    events = session.scalars(
        select(SchoolResearchEducationOutputReviewEvent).where(
            SchoolResearchEducationOutputReviewEvent.output_review_id == review.id
        )
    ).all()
    assert candidate.status == "HELD"
    assert candidate.output_safety_action == "REVIEW_REQUIRED"
    assert candidate.output_review_id == review.id
    assert candidate.output_review_state == "CONSUMED"
    assert candidate.trace_id == "TRACE_candidate_resolve_001"
    assert candidate.trace_id != persisted_review.trace_id
    assert candidate.input_review_id is None
    assert persisted_review.status == "CONSUMED"
    assert persisted_review.candidate_content_sha256 == _CANDIDATE_HASH
    assert persisted_review.candidate_payload_schema_version == CANDIDATE_PAYLOAD_SCHEMA_VERSION
    assert persisted_review.state_version == 2
    assert job.status == "REVIEW_REQUIRED" and job.last_error_code == "SAFETY_BLOCKED"
    assert len(events) == 2
    assert [event.event_type for event in events] == ["PENDING", "CONSUMED"]
    assert session.scalar(select(SchoolResearchEducationCandidateEvent).where(
        SchoolResearchEducationCandidateEvent.candidate_id == candidate.id
    )) is not None

    with pytest.raises(OptimisticConcurrencyConflict):
        asyncio.run(_repo(session).resolve(
            scope=_output_scope(claim),
            output_review_ref=review.output_review_ref,
            expected_state_version=1,
            status="REJECTED",
            actor_membership_role_id=1,
            trace_id="TRACE_reject_again",
            now=_NOW + timedelta(minutes=2),
        ))


def test_round1_terminal_candidate_atomically_consumes_authorized_input_review(session):
    claim0 = _claim_for_input_review(session)
    input_review = _create_input_review(session, claim0)
    _finish_review_job(session, claim0, _NOW + timedelta(seconds=30))
    authorized, _continuation = _authorize(session, claim0, input_review)
    jobs = SchoolResearchEducationJobRepository(_OutputReviewAsyncSessionAdapter(session))
    claim1 = asyncio.run(jobs.claim_next(
        school_id=claim0.school_id,
        lease_owner="output-review-round1-worker",
        policy_version=GENERAL_EDUCATION_POLICY_VERSION,
        generation_round=1,
        max_attempts=1,
        now=_NOW + timedelta(minutes=2),
    ))[0]
    evidence = _evidence(claim1, input_review=input_review)
    output_review = _create_output_review(
        session,
        claim1,
        evidence=evidence,
        now=_NOW + timedelta(minutes=2),
    )
    _finish_review_job(session, claim1, _NOW + timedelta(minutes=2, seconds=30))

    with pytest.raises(IntegrityError):
        _create_candidate_from_output_review(
            session,
            claim1,
            output_review,
            actor_id=999_999,
            now=_NOW + timedelta(minutes=2, seconds=40),
        )
    session.expire_all()
    assert session.scalar(select(SchoolResearchEducationOutputReview).where(
        SchoolResearchEducationOutputReview.id == output_review.id
    )).status == "PENDING"
    assert session.scalar(select(SchoolResearchEducationInputReview).where(
        SchoolResearchEducationInputReview.id == authorized.id
    )).status == "CONTINUATION_AUTHORIZED"
    assert session.scalar(select(SchoolResearchEducationCandidate).where(
        SchoolResearchEducationCandidate.job_id == claim1.id
    )) is None

    candidate = _create_candidate_from_output_review(
        session,
        claim1,
        output_review,
        now=_NOW + timedelta(minutes=2, seconds=45),
    )
    session.expire_all()
    input_persisted = session.scalar(select(SchoolResearchEducationInputReview).where(
        SchoolResearchEducationInputReview.id == authorized.id
    ))
    output_persisted = session.scalar(select(SchoolResearchEducationOutputReview).where(
        SchoolResearchEducationOutputReview.id == output_review.id
    ))
    job = session.scalar(select(SchoolResearchEducationJob).where(
        SchoolResearchEducationJob.id == claim1.id
    ))
    assert candidate.generation_round == 1
    assert candidate.input_review_id == authorized.id
    assert candidate.input_review_state == "CONSUMED"
    assert candidate.output_review_id == output_review.id
    assert input_persisted.status == "CONSUMED" and input_persisted.state_version == 3
    assert output_persisted.status == "CONSUMED" and output_persisted.state_version == 2
    assert job.status == "REVIEW_REQUIRED" and job.last_error_code == "SAFETY_BLOCKED"


def test_output_review_resolve_is_expiry_and_state_version_guarded(session):
    claim = _round0_claim(session)
    review = _create_output_review(session, claim)
    _finish_review_job(session, claim, _NOW + timedelta(seconds=30))
    repository = _repo(session)
    with pytest.raises(OptimisticConcurrencyConflict):
        asyncio.run(repository.resolve(
            scope=_output_scope(claim),
            output_review_ref=review.output_review_ref,
            expected_state_version=2,
            status="REJECTED",
            actor_membership_role_id=1,
            trace_id="TRACE_bad_version",
            now=_NOW + timedelta(minutes=1),
        ))
    resolved = asyncio.run(repository.resolve(
        scope=_output_scope(claim),
        output_review_ref=review.output_review_ref,
        expected_state_version=1,
        status="REJECTED",
        actor_membership_role_id=1,
        trace_id="TRACE_reject_001",
        now=_NOW + timedelta(minutes=1),
    ))
    assert resolved.status == "REJECTED" and resolved.state_version == 2
    with pytest.raises(OptimisticConcurrencyConflict):
        asyncio.run(repository.resolve(
            scope=_output_scope(claim),
            output_review_ref=review.output_review_ref,
            expected_state_version=1,
            status="REVOKED",
            actor_membership_role_id=1,
            trace_id="TRACE_revoke_001",
            now=_NOW + timedelta(minutes=2),
        ))


def test_0023_migration_names_match_models_and_downgrade_refuses_rows(monkeypatch):
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20261016_0023_research_education_output_reviews.py"
    )
    spec = importlib.util.spec_from_file_location("education_output_reviews_0023", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "20261016_0023"
    assert migration.down_revision == "20261015_0022"

    legacy_name = "ck_school_research_education_candidates_safety_actions_allowed"
    legacy_output = io.StringIO()
    legacy_context = MigrationContext.configure(
        dialect=mysql.dialect(),
        opts={"as_sql": True, "output_buffer": legacy_output, "target_metadata": Base.metadata},
    )
    with Operations.context(legacy_context):
        Operations(legacy_context).create_check_constraint(
            legacy_name, "school_research_education_candidates", "1=1"
        )
    legacy_sql = legacy_output.getvalue()
    old_name_match = re.search(r"ADD CONSTRAINT ([A-Za-z0-9_]+) CHECK", legacy_sql)
    assert old_name_match is not None
    old_name = old_name_match.group(1)
    assert old_name != legacy_name

    output = io.StringIO()
    context = MigrationContext.configure(
        dialect=mysql.dialect(),
        opts={"as_sql": True, "output_buffer": output, "target_metadata": Base.metadata},
    )
    with Operations.context(context):
        migration.upgrade()
    sql = output.getvalue()
    assert f"DROP CHECK {old_name}" in sql
    assert f"ADD CONSTRAINT {legacy_name} CHECK" in sql
    candidate_check = next(
        constraint
        for constraint in SchoolResearchEducationCandidate.__table__.constraints
        if constraint.name == legacy_name and hasattr(constraint, "sqltext")
    )
    migration_check = re.findall(
        rf"ALTER TABLE `?school_research_education_candidates`? "
        rf"ADD CONSTRAINT `?{re.escape(legacy_name)}`? CHECK \((.*?)\);",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert len(migration_check) == 1
    def normalize_check(value):
        return re.sub(r"\s+", "", value).casefold()

    assert normalize_check(migration_check[0]) == normalize_check(str(candidate_check.sqltext))
    names = set(re.findall(r"CONSTRAINT\s+`?([A-Za-z0-9_]+)`?", sql))
    names.update(re.findall(r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+`?([A-Za-z0-9_]+)`?", sql))
    assert names and all(len(name) <= 64 for name in names)
    model_sql = "".join(
        str(CreateTable(table).compile(dialect=mysql.dialect()))
        for table in (
            SchoolResearchEducationOutputReview.__table__,
            SchoolResearchEducationOutputReviewEvent.__table__,
        )
    ) + str(CreateTable(SchoolResearchEducationCandidate.__table__).compile(dialect=mysql.dialect()))
    model_names = set(re.findall(r"CONSTRAINT\s+`?([A-Za-z0-9_]+)`?", model_sql))
    new_model_names = {
        name for name in model_names
        if "output_review" in name or name == "ck_school_research_education_candidates_safety_actions_allowed"
    }
    assert new_model_names <= names
    assert "CREATE TABLE school_research_education_output_reviews" in sql
    assert "CREATE TABLE school_research_education_output_review_events" in sql
    assert "payload_ciphertext MEDIUMBLOB NOT NULL" in sql
    assert "raw_output" not in sql and "candidate_body" not in sql

    downgrade_output = io.StringIO()
    downgrade_context = MigrationContext.configure(
        dialect=mysql.dialect(),
        opts={
            "as_sql": True,
            "output_buffer": downgrade_output,
            "target_metadata": Base.metadata,
        },
    )
    real_operations = Operations(downgrade_context)

    class _NoRows:
        def first(self):
            return None

    class _NoRowsBind:
        def execute(self, _statement):
            return _NoRows()

    class _OperationsWithEmptyBind:
        def __getattr__(self, name):
            if name == "get_bind":
                return lambda: _NoRowsBind()
            return getattr(real_operations, name)

    with Operations.context(downgrade_context):
        monkeypatch.setattr(migration, "op", _OperationsWithEmptyBind())
        migration.downgrade()
    downgrade_sql = downgrade_output.getvalue()
    assert f"DROP CHECK {legacy_name}" in downgrade_sql
    assert f"ADD CONSTRAINT {old_name} CHECK" in downgrade_sql
    monkeypatch.undo()

    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE school_research_education_candidates "
                "(id INTEGER, output_review_id INTEGER)"
            )
            connection.exec_driver_sql(
                "CREATE TABLE school_research_education_output_review_events (id INTEGER)"
            )
            connection.exec_driver_sql(
                "CREATE TABLE school_research_education_output_reviews (id INTEGER)"
            )
            connection.exec_driver_sql(
                "INSERT INTO school_research_education_output_reviews (id) VALUES (1)"
            )
            context = MigrationContext.configure(connection)
            with (
                Operations.context(context),
                pytest.raises(RuntimeError, match="refusing downgrade"),
            ):
                migration.downgrade()
            assert connection.exec_driver_sql(
                "SELECT COUNT(*) FROM school_research_education_output_reviews"
            ).scalar_one() == 1
    finally:
        engine.dispose()
