from __future__ import annotations

import asyncio
import importlib.util
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from database_layer.base import Base
from database_layer.errors import ForeignKeyConflict, OptimisticConcurrencyConflict
from database_layer.models import (
    SchoolResearchFeedbackEvent,
    SchoolResearchFeedbackRecord,
    SchoolResearchReviewCase,
    SchoolResearchReviewEvent,
    SchoolTaskSpecialistAssignment,
)
from database_layer.school_research_review_feedback import (
    ResearchReviewFeedbackError,
    ResearchSessionScope,
    SchoolResearchFeedbackRepository,
    SchoolResearchReviewRepository,
)
from database_layer.unit_of_work import SqlAlchemyUnitOfWork
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Session

from test_school_research_education_jobs import _seed

_NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
_TABLES = (
    "school_research_review_cases",
    "school_research_review_events",
    "school_research_feedback_records",
    "school_research_feedback_events",
)
_SCOPE_FIELDS = (
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
)


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

    def compile_blob(self, visitor, **kw):
        return (
            "BLOB"
            if visitor.dialect.name == "sqlite"
            else medium_blob_dispatch(self, visitor, **kw)
        )

    def compile_bigint(self, visitor, **kw):
        return (
            "INTEGER" if visitor.dialect.name == "sqlite" else big_int_dispatch(self, visitor, **kw)
        )

    monkeypatch.setattr(medium_blob_cls, "_compiler_dispatch", compile_blob)
    monkeypatch.setattr(big_int_cls, "_compiler_dispatch", compile_bigint)
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_constraints(connection, _record):
        connection.create_collation("ascii_bin", lambda a, b: (a > b) - (a < b))
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    db = Session(engine)
    _seed(db)
    db.add(
        SchoolTaskSpecialistAssignment(
            school_id=1,
            task_id=1,
            class_id=1,
            specialist_membership_role_id=1,
            assigned_by_membership_role_id=1,
            status="ACTIVE",
            revoked_at=None,
        )
    )
    db.commit()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _scope() -> ResearchSessionScope:
    return ResearchSessionScope(
        research_session_id=1,
        school_id=1,
        task_id=1,
        class_id=1,
        task_enrollment_id=1,
        subject_id=1,
        task_binding_id=1,
        profile_version_id=1,
        profile_ref="research-profile",
        profile_version_number=3,
        profile_sha256="a" * 64,
        response_origin="MODEL_GENERATED",
    )


def test_models_have_exact_research_session_scope_and_metadata_only_events():
    for model in (SchoolResearchReviewCase, SchoolResearchReviewEvent):
        assert (
            tuple(column.name for column in model.__table__.columns if column.name in _SCOPE_FIELDS)
            == _SCOPE_FIELDS
        )
    for model in (SchoolResearchFeedbackRecord, SchoolResearchFeedbackEvent):
        assert (
            tuple(column.name for column in model.__table__.columns if column.name in _SCOPE_FIELDS)
            == _SCOPE_FIELDS
        )
    assert "case_note_ciphertext" not in SchoolResearchReviewEvent.__table__.columns
    assert "payload_ciphertext" not in SchoolResearchFeedbackEvent.__table__.columns
    assert "psychological_interpretation_allowed" in SchoolResearchFeedbackRecord.__table__.columns
    assert len(Base.metadata.tables) == 54


def test_unit_of_work_exposes_new_repositories():
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
        uow = SqlAlchemyUnitOfWork(lambda: _Session(), object())
        await uow.__aenter__()
        assert isinstance(uow.research_reviews, SchoolResearchReviewRepository)
        assert isinstance(uow.research_feedback, SchoolResearchFeedbackRepository)
        await uow.__aexit__(None, None, None)

    asyncio.run(run())


def test_case_feedback_cas_encrypted_payload_and_revoke_events(session):
    async def run():
        wrapped = _AsyncSessionAdapter(session)
        reviews = SchoolResearchReviewRepository(wrapped)
        feedback = SchoolResearchFeedbackRepository(wrapped)

        case = await reviews.create_case(
            scope=_scope(),
            specialist_membership_role_id=1,
            case_note_ciphertext=b"encrypted-note",
            case_note_cipher_format_version="fernet.v1",
            case_note_key_version="research-key-v1",
            case_note_payload_schema_version="research-note.v1",
            actor_membership_role_id=1,
            now=_NOW,
        )
        assert case.status == "OPEN" and case.version == 1
        assert case.purpose == "RESEARCH_SIMULATION" and case.research_only is True
        assert case.publication_status == "not_approved_for_publication_or_operational_use"
        assert "encrypted-note" not in repr(case)

        with pytest.raises(OptimisticConcurrencyConflict):
            await reviews.transition_case(
                school_id=1,
                research_session_id=1,
                expected_version=1,
                to_status="APPROVED",
                actor_membership_role_id=1,
                now=_NOW,
            )
        case = await reviews.transition_case(
            school_id=1,
            research_session_id=1,
            expected_version=1,
            to_status="IN_REVIEW",
            actor_membership_role_id=1,
            now=_NOW,
        )
        case = await reviews.transition_case(
            school_id=1,
            research_session_id=1,
            expected_version=2,
            to_status="APPROVED",
            actor_membership_role_id=1,
            now=_NOW,
        )

        draft = await feedback.create_draft(
            school_id=1,
            research_session_id=1,
            expected_case_version=case.version,
            feedback_ref="research-feedback-1",
            content_revision=1,
            payload_ciphertext=b"encrypted-education-feedback",
            cipher_format_version="fernet.v1",
            key_version="research-key-v1",
            payload_schema_version="research-feedback.v1",
            actor_membership_role_id=1,
            now=_NOW,
        )
        assert draft.status == "DRAFT" and draft.case_version == case.version
        assert draft.feedback_kind == "GENERAL_EDUCATIONAL_SUPPORT"
        assert draft.psychological_interpretation_allowed is False
        assert draft.publication_status == "not_approved_for_publication_or_operational_use"
        assert "encrypted-education-feedback" not in repr(draft)

        published = await feedback.publish(
            school_id=1,
            feedback_id=draft.id,
            expected_state_version=1,
            expected_case_version=case.version,
            actor_membership_role_id=1,
            now=_NOW,
        )
        assert published.status == "PUBLISHED" and published.state_version == 2
        revoked = await feedback.revoke(
            school_id=1,
            feedback_id=draft.id,
            expected_state_version=2,
            actor_membership_role_id=1,
            now=_NOW,
        )
        assert revoked.status == "REVOKED" and revoked.state_version == 3
        second_draft = await feedback.create_draft(
            school_id=1,
            research_session_id=1,
            expected_case_version=case.version,
            feedback_ref="research-feedback-2",
            content_revision=2,
            payload_ciphertext=b"another-encrypted-feedback",
            cipher_format_version="fernet.v1",
            key_version="research-key-v1",
            payload_schema_version="research-feedback.v1",
            actor_membership_role_id=1,
            now=_NOW,
        )
        draft_revoked = await feedback.revoke(
            school_id=1,
            feedback_id=second_draft.id,
            expected_state_version=1,
            actor_membership_role_id=1,
            now=_NOW,
        )
        assert draft_revoked.status == "REVOKED" and draft_revoked.published_at is None
        assert draft_revoked.published_by_membership_role_id is None
        review_events = await reviews.list_events(school_id=1, research_session_id=1)
        feedback_events = await feedback.list_events(school_id=1, feedback_id=draft.id)
        assert [item.to_status for item in review_events] == ["OPEN", "IN_REVIEW", "APPROVED"]
        assert [item.to_status for item in feedback_events] == ["DRAFT", "PUBLISHED", "REVOKED"]
        assert not hasattr(feedback_events[0], "payload_ciphertext")
        migration_path = (
            Path(__file__).parents[1]
            / "migrations"
            / "versions"
            / "20261014_0017_research_review_feedback.py"
        )
        spec = importlib.util.spec_from_file_location(
            "research_review_feedback_downgrade", migration_path
        )
        assert spec is not None and spec.loader is not None
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        context = MigrationContext.configure(session.connection())
        with Operations.context(context), pytest.raises(RuntimeError, match="downgrade refused"):
            migration.downgrade()

    asyncio.run(run())


def test_repository_rejects_scope_mismatch_missing_cipher_metadata_and_inactive_assignment(session):
    async def run():
        wrapped = _AsyncSessionAdapter(session)
        reviews = SchoolResearchReviewRepository(wrapped)
        wrong_scope = replace(_scope(), profile_sha256="b" * 64)
        with pytest.raises(ForeignKeyConflict):
            await reviews.create_case(
                scope=wrong_scope,
                specialist_membership_role_id=1,
                actor_membership_role_id=1,
                now=_NOW,
            )
        with pytest.raises(ResearchReviewFeedbackError):
            await reviews.create_case(
                scope=replace(_scope(), response_origin=[]),
                specialist_membership_role_id=1,
                actor_membership_role_id=1,
                now=_NOW,
            )
        with pytest.raises(ResearchReviewFeedbackError):
            await reviews.list_cases(
                school_id=1,
                task_id=1,
                specialist_membership_role_id=1,
                status=[],
            )
        with pytest.raises(ResearchReviewFeedbackError):
            await reviews.create_case(
                scope=_scope(),
                specialist_membership_role_id=1,
                case_note_ciphertext=b"cipher",
                actor_membership_role_id=1,
                now=_NOW,
            )
        with pytest.raises(ResearchReviewFeedbackError):
            await reviews.create_case(
                scope=_scope(),
                specialist_membership_role_id=1,
                actor_membership_role_id=2,
                now=_NOW,
            )
        session.query(SchoolTaskSpecialistAssignment).filter_by(task_id=1).update(
            {"status": "REVOKED", "revoked_at": _NOW.replace(tzinfo=None)}
        )
        session.flush()
        with pytest.raises(ForeignKeyConflict):
            await reviews.create_case(
                scope=_scope(),
                specialist_membership_role_id=1,
                actor_membership_role_id=1,
                now=_NOW,
            )

    asyncio.run(run())


def test_0017_migration_revision_and_model_column_order_match():
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20261014_0017_research_review_feedback.py"
    )
    spec = importlib.util.spec_from_file_location("research_review_feedback_0017", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "20261014_0017"
    assert migration.down_revision == "20261014_0016"
    assert tuple(migration._RESEARCH_SCOPE) == _SCOPE_FIELDS
    assert _TABLES == tuple(
        name
        for name in (
            "school_research_review_cases",
            "school_research_review_events",
            "school_research_feedback_records",
            "school_research_feedback_events",
        )
    )

    medium_blob_cls = type(mysql.MEDIUMBLOB())
    big_int_cls = type(mysql.BIGINT(unsigned=True))
    medium_blob_dispatch = medium_blob_cls._compiler_dispatch
    big_int_dispatch = big_int_cls._compiler_dispatch

    def compile_blob(self, visitor, **kw):
        return (
            "BLOB"
            if visitor.dialect.name == "sqlite"
            else medium_blob_dispatch(self, visitor, **kw)
        )

    def compile_bigint(self, visitor, **kw):
        return (
            "INTEGER" if visitor.dialect.name == "sqlite" else big_int_dispatch(self, visitor, **kw)
        )

    medium_blob_cls._compiler_dispatch = compile_blob
    big_int_cls._compiler_dispatch = compile_bigint
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def register_ascii_collation(connection, _record):
        connection.create_collation("ascii_bin", lambda a, b: (a > b) - (a < b))

    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            Base.metadata.create_all(
                connection,
                tables=[
                    table for table in Base.metadata.sorted_tables if table.name not in _TABLES
                ],
            )
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                migration.upgrade()
            inspector = inspect(connection)
            for table_name in _TABLES:
                assert inspector.get_columns(table_name)
                actual_columns = inspector.get_columns(table_name)
                model_columns = Base.metadata.tables[table_name].columns
                assert [item["name"] for item in actual_columns] == list(model_columns.keys())
                for actual, expected in zip(actual_columns, model_columns.values(), strict=True):
                    assert actual["nullable"] is expected.nullable
                    actual_type = actual["type"].compile(dialect=connection.dialect)
                    expected_type = expected.type.compile(dialect=connection.dialect)
                    assert actual_type == expected_type.split(" COLLATE", maxsplit=1)[0]
                    if " COLLATE" in expected_type:
                        table_sql = connection.exec_driver_sql(
                            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                            (table_name,),
                        ).scalar_one()
                        assert 'COLLATE "ascii_bin"' in table_sql
                actual_fks = {
                    (tuple(item["constrained_columns"]), tuple(item["referred_columns"]))
                    for item in inspector.get_foreign_keys(table_name)
                }
                expected_fks = {
                    (
                        tuple(element.parent.name for element in fk.elements),
                        tuple(element.column.name for element in fk.elements),
                    )
                    for fk in Base.metadata.tables[table_name].foreign_key_constraints
                }
                assert actual_fks == expected_fks
                actual_uniques = {
                    (item["name"], tuple(item["column_names"]))
                    for item in inspector.get_unique_constraints(table_name)
                }
                expected_uniques = {
                    (constraint.name, tuple(column.name for column in constraint.columns))
                    for constraint in Base.metadata.tables[table_name].constraints
                    if constraint.__class__.__name__ == "UniqueConstraint"
                }
                assert actual_uniques == expected_uniques
                actual_checks = {
                    item["name"] for item in inspector.get_check_constraints(table_name)
                }
                expected_checks = {
                    constraint.name
                    for constraint in Base.metadata.tables[table_name].constraints
                    if constraint.__class__.__name__ == "CheckConstraint"
                }
                assert actual_checks == expected_checks
                actual_indexes = {
                    (item["name"], tuple(item["column_names"]))
                    for item in inspector.get_indexes(table_name)
                }
                expected_indexes = {
                    (index.name, tuple(column.name for column in index.columns))
                    for index in Base.metadata.tables[table_name].indexes
                }
                assert actual_indexes == expected_indexes
    finally:
        medium_blob_cls._compiler_dispatch = medium_blob_dispatch
        big_int_cls._compiler_dispatch = big_int_dispatch
        engine.dispose()
