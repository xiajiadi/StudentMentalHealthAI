from __future__ import annotations

import asyncio
import importlib.util
import io
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from database_layer.base import Base
from database_layer.errors import ForeignKeyConflict, OptimisticConcurrencyConflict
from database_layer.models import SchoolResearchProgrammeCandidate
from database_layer.school_research_programme_candidates import (
    ResearchProgrammeCandidateError,
    ResearchProgrammeCandidateScope,
    SchoolResearchProgrammeCandidateRepository,
)
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from test_school_research_education_jobs import _seed

_NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
_HASH = "a" * 64


class _AsyncSessionAdapter:
    def __init__(self, session: Session) -> None:
        self.sync = session

    async def scalar(self, statement):
        return self.sync.scalar(statement)

    async def scalars(self, statement):
        return self.sync.scalars(statement)

    def add(self, row):
        self.sync.add(row)

    async def flush(self):
        self.sync.flush()

    def begin_nested(self):
        return _AsyncNested(self.sync)


class _AsyncNested:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        self.context = self.session.begin_nested()
        self.context.__enter__()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return self.context.__exit__(exc_type, exc, tb)


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


def _scope(**changes):
    values = {
        "school_id": 1,
        "task_id": 1,
        "class_id": 1,
        "task_binding_id": 1,
        "profile_version_id": 1,
        "profile_ref": "research-profile",
        "profile_version_number": 3,
        "profile_sha256": "a" * 64,
        "response_origin": "MODEL_GENERATED",
    }
    values.update(changes)
    return ResearchProgrammeCandidateScope(**values)


def _candidate_kwargs(**changes):
    scope = changes.pop("scope", None)
    values = {
        "scope": scope or _scope(),
        "candidate_ref": "RPCANDIDATE_001",
        "study_ref": "study-r1",
        "study_policy_sha256": "b" * 64,
        "processor_policy_sha256": "a" * 64,
        "programme_ref": "staff-programme-r1",
        "source_manifest_sha256": "c" * 64,
        "source_set_sha256": "d" * 64,
        "retrieval_id": "RETR_research_programme_001",
        "retrieval_bundle_sha256": "e" * 64,
        "chunk_set_sha256": "f" * 64,
        "prompt_ref": "PROMPT_research_programme",
        "prompt_version": "1",
        "prompt_sha256": "1" * 64,
        "model_ref": "qwen-local-7b-pinned",
        "model_digest_sha256": "2" * 64,
        "runtime_version": "local-runtime-v1",
        "safety_policy_version": "research-safety-v1",
        "input_safety_action": "PROCEED",
        "retrieval_safety_action": "PROCEED_WITH_BOUNDARY",
        "output_safety_action": "PROCEED",
        "claim_boundary_version": "claim-boundary-v1",
        "claim_boundary_status": "ACCEPTED",
        "payload_ciphertext": b"synthetic-encrypted-candidate",
        "cipher_format_version": "fernet.v1",
        "key_version": "school-key-v1",
        "payload_schema_version": "school_research_programme_candidate.v1",
        "now": _NOW,
    }
    values.update(changes)
    return values


def test_candidate_schema_is_task_scoped_encrypted_and_nonpublishable():
    table = SchoolResearchProgrammeCandidate.__table__
    assert "payload_ciphertext" in table.columns
    assert not any(
        name in table.columns
        for name in ("student_id", "subject_id", "research_session_id", "answer", "score")
    )
    assert table.c.status.server_default.arg == "HELD"
    assert (
        table.c.publication_status.server_default.arg
        == "not_approved_for_publication_or_operational_use"
    )
    assert len(Base.metadata.tables) == 55
    pin_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if constraint.name == "school_research_programme_candidate_pin_unique"
    }
    assert pin_columns == {
        (
            "school_id",
            "task_id",
            "task_binding_id",
            "study_ref",
            "study_policy_sha256",
            "processor_policy_sha256",
            "programme_ref",
            "source_manifest_sha256",
            "prompt_ref",
            "prompt_version",
            "prompt_sha256",
            "model_ref",
            "model_digest_sha256",
            "runtime_version",
            "safety_policy_version",
            "claim_boundary_version",
        )
    }
    mysql_sql = str(CreateTable(table).compile(dialect=mysql.dialect()))
    assert "payload_ciphertext MEDIUMBLOB NOT NULL" in mysql_sql
    assert "student_id" not in mysql_sql and "assessment_result" not in mysql_sql


def test_held_candidate_replay_resolution_and_fixed_metadata(session):
    async def run():
        repository = SchoolResearchProgrammeCandidateRepository(_AsyncSessionAdapter(session))
        first = await repository.create_held(**_candidate_kwargs())
        replay = await repository.create_held(
            **_candidate_kwargs(
                candidate_ref="RPCANDIDATE_002",
                source_set_sha256="9" * 64,
                retrieval_id="RETR_research_programme_retry_2",
                retrieval_bundle_sha256="8" * 64,
                chunk_set_sha256="7" * 64,
            )
        )
        assert first.id == replay.id
        assert replay.retrieval_id == first.retrieval_id
        assert first.status == "HELD" and first.state_version == 1
        assert first.purpose == "RESEARCH_SIMULATION"
        assert first.research_only is True
        assert first.psychological_interpretation_allowed is False
        assert first.publication_status == "not_approved_for_publication_or_operational_use"
        assert first.output_boundary == "STAFF_REFERENCE_ONLY"
        assert first.processor_policy_sha256 == "a" * 64
        assert "synthetic-encrypted-candidate" not in repr(first)
        rows = await repository.list_for_task(school_id=1, task_id=1)
        assert [item.candidate_ref for item in rows] == ["RPCANDIDATE_001"]
        adopted = await repository.resolve(
            school_id=1,
            task_id=1,
            candidate_ref=first.candidate_ref,
            expected_state_version=1,
            target="ADOPTED",
            actor_membership_role_id=1,
            now=_NOW,
        )
        assert adopted.status == "ADOPTED" and adopted.state_version == 2
        with pytest.raises(OptimisticConcurrencyConflict):
            await repository.resolve(
                school_id=1,
                task_id=1,
                candidate_ref=first.candidate_ref,
                expected_state_version=1,
                target="DISCARDED",
                actor_membership_role_id=1,
                now=_NOW,
            )

    asyncio.run(run())


def test_candidate_ingest_rejects_bad_safety_and_foreign_binding(session):
    async def run():
        repository = SchoolResearchProgrammeCandidateRepository(_AsyncSessionAdapter(session))
        bad_safety = _candidate_kwargs()
        bad_safety["input_safety_action"] = "REVIEW_REQUIRED"
        with pytest.raises(ResearchProgrammeCandidateError) as exc:
            await repository.create_held(**bad_safety)
        assert exc.value.code == "INVALID_SAFETY_DISPOSITION"
        bad_hash = _candidate_kwargs(processor_policy_sha256="z" * 64)
        with pytest.raises(ResearchProgrammeCandidateError) as exc:
            await repository.create_held(**bad_hash)
        assert exc.value.code == "INVALID_INPUT"
        with pytest.raises(ForeignKeyConflict):
            await repository.create_held(
                **_candidate_kwargs(scope=_scope(profile_sha256="9" * 64))
            )

    asyncio.run(run())


def test_0018_migration_matches_model_scope_and_column_order():
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20261014_0018_research_programme_candidates.py"
    )
    spec = importlib.util.spec_from_file_location(
        "research_programme_candidates_0018", migration_path
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "20261014_0018"
    assert migration.down_revision == "20261014_0017"
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

    medium_blob_cls._compiler_dispatch = compile_blob
    big_int_cls._compiler_dispatch = compile_bigint
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def setup_sqlite(connection, _record):
        connection.create_collation(
            "ascii_bin", lambda left, right: (left > right) - (left < right)
        )
        connection.execute("PRAGMA foreign_keys=ON")

    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            Base.metadata.create_all(
                connection,
                tables=[
                    table
                    for table in Base.metadata.sorted_tables
                    if table.name != "school_research_programme_candidates"
                ],
            )
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                migration.upgrade()
            inspector = inspect(connection)
            table_name = "school_research_programme_candidates"
            actual = inspector.get_columns(table_name)
            expected_table = Base.metadata.tables[table_name]
            expected = expected_table.columns
            assert [column["name"] for column in actual] == list(expected.keys())
            actual_uniques = {
                (constraint["name"], tuple(constraint["column_names"]))
                for constraint in inspector.get_unique_constraints(table_name)
            }
            expected_uniques = {
                (constraint.name, tuple(column.name for column in constraint.columns))
                for constraint in expected_table.constraints
                if constraint.__class__.__name__ == "UniqueConstraint"
            }
            assert actual_uniques == expected_uniques
            actual_fks = {
                (tuple(item["constrained_columns"]), tuple(item["referred_columns"]))
                for item in inspector.get_foreign_keys(table_name)
            }
            expected_fks = {
                (
                    tuple(element.parent.name for element in constraint.elements),
                    tuple(element.column.name for element in constraint.elements),
                )
                for constraint in expected_table.foreign_key_constraints
            }
            assert actual_fks == expected_fks
    finally:
        medium_blob_cls._compiler_dispatch = medium_blob_dispatch
        big_int_cls._compiler_dispatch = big_int_dispatch
        engine.dispose()


def test_0018_rendered_mysql_check_names_match_model_and_fit_identifier_limit():
    table = SchoolResearchProgrammeCandidate.__table__
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20261014_0018_research_programme_candidates.py"
    )
    spec = importlib.util.spec_from_file_location(
        "research_programme_candidates_0018_names", migration_path
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    buffer = io.StringIO()
    context = MigrationContext.configure(
        dialect=mysql.dialect(),
        opts={"as_sql": True, "output_buffer": buffer},
    )
    with Operations.context(context):
        migration.upgrade()

    model_ddl = str(CreateTable(table).compile(dialect=mysql.dialect()))
    migration_ddl = buffer.getvalue()
    check_names = {
        "ck_school_research_programme_candidates_output_staff_only",
        "ck_school_research_programme_candidates_resolution_state",
    }
    name_pattern = re.compile(r"CONSTRAINT\s+`?([A-Za-z0-9_]+)`?")
    model_names = set(name_pattern.findall(model_ddl))
    migration_names = set(name_pattern.findall(migration_ddl))
    assert check_names <= model_names
    assert check_names <= migration_names
    assert all(len(name) <= 64 for name in check_names)
