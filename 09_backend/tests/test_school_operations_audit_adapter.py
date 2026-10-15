from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from database_layer import models as db_models
from sqlalchemy import create_engine, event
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Session

from smhai_backend.adapters.school_operations_audit import SchoolOperationsAuditPersistenceAdapter


class Result:
    def all(self):
        return []


class FakeSession:
    def __init__(self) -> None:
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return Result()


class FakePersistence:
    _db_models = db_models
    _db_enums = SimpleNamespace(
        DataOrigin=SimpleNamespace(SYNTHETIC=SimpleNamespace(value="SYNTHETIC"))
    )
    _select = staticmethod(__import__("sqlalchemy").select)

    def __init__(self):
        self.session = FakeSession()

    def _utc_now(self):
        return datetime(2026, 10, 16, tzinfo=UTC)

    @asynccontextmanager
    async def _uow(self):
        yield SimpleNamespace(session=self.session)

    async def _school_actor_role(self, *_args, **_kwargs):
        return (101, 102)


async def test_query_requires_tenant_resource_links_and_excludes_actor_identity():
    persistence = FakePersistence()
    adapter = SchoolOperationsAuditPersistenceAdapter(persistence)
    actor = SimpleNamespace(school_id=17, school_ref="SCHOOL_fixture")
    result = await adapter.school_operations_audit_list(actor, offset=50, limit=25, category=None)
    assert result == {"items": [], "has_more": False}
    sql = str(persistence.session.statement.compile(dialect=mysql.dialect()))
    assert "school_account_provisions.school_id" in sql
    assert "account_school_memberships.school_id" in sql
    assert "school_classes.school_id" in sql
    assert "measurement_tasks.school_id" in sql
    assert "school_account_batches.school_id" in sql
    assert "actor_account_id" not in sql
    assert "trace_id" not in sql
    assert persistence.session.statement._limit_clause.value == 26
    assert persistence.session.statement._offset_clause.value == 50
    for disallowed in (
        "assessment_responses",
        "support_messages",
        "school_research_education_candidates",
        "school_research_education_input_reviews",
        "school_research_education_output_reviews",
    ):
        assert disallowed not in sql


class SqliteSession:
    def __init__(self, session: Session) -> None:
        self.session = session

    async def execute(self, statement):
        return self.session.execute(statement)


class SqlitePersistence(FakePersistence):
    def __init__(self, session: Session) -> None:
        self.session = SqliteSession(session)


@pytest.mark.asyncio
async def test_sql_query_returns_only_events_joined_to_owned_objects():
    engine = create_engine("sqlite:///:memory:")
    event.listen(
        engine,
        "connect",
        lambda connection, _record: connection.create_collation(
            "ascii_bin", lambda left, right: (left > right) - (left < right)
        ),
    )
    selected = ["schools", "school_classes", "audit_events"]
    db_models.Base.metadata.create_all(
        engine, tables=[db_models.Base.metadata.tables[name] for name in selected]
    )
    session = Session(engine)
    school_table = db_models.School.__table__
    class_table = db_models.SchoolClass.__table__
    audit_table = db_models.AuditEvent.__table__
    session.execute(
        school_table.insert(),
        [
            {
                "id": 17,
                "public_id": "school-pub-17",
                "school_ref": "SCHOOL_A",
                "data_origin": "SYNTHETIC",
                "provenance_ref": "SYNTHETIC_REF_SCHOOL_SEED_RECIPE_V1",
            },
            {
                "id": 18,
                "public_id": "school-pub-18",
                "school_ref": "SCHOOL_B",
                "data_origin": "SYNTHETIC",
                "provenance_ref": "SYNTHETIC_REF_SCHOOL_SEED_RECIPE_V1",
            },
        ],
    )
    session.execute(
        class_table.insert(),
        [
            {
                "id": 101,
                "public_id": "class-a",
                "school_id": 17,
                "class_ref": "CLASS_A",
                "created_by_membership_role_id": 1,
            },
            {
                "id": 201,
                "public_id": "class-b",
                "school_id": 18,
                "class_ref": "CLASS_B",
                "created_by_membership_role_id": 2,
            },
        ],
    )
    common = {
        "result": "SUCCESS",
        "trace_id": "TRACE_fixture",
        "created_at": datetime(2026, 10, 16, tzinfo=UTC),
    }
    session.execute(
        audit_table.insert(),
        [
            {
                "id": 1,
                "public_id": "2d6e0c0f-233b-4d62-8f20-d7d0a2f187a3",
                "action": "school_directory.rename_class",
                "resource_type": "school_class",
                "resource_public_id": "class-a",
                **common,
            },
            {
                "id": 2,
                "public_id": "b77e9a73-afbc-4481-adf0-ea33df53e883",
                "action": "school_directory.rename_class",
                "resource_type": "school_class",
                "resource_public_id": "class-b",
                **common,
            },
            {
                "id": 3,
                "public_id": "a4585e22-b5ce-453a-b376-f8c6306b7cc1",
                "action": "professional_review.approved",
                "resource_type": "review_case",
                "resource_public_id": "private-case",
                **common,
            },
        ],
    )
    session.commit()
    persistence = SqlitePersistence(session)
    adapter = SchoolOperationsAuditPersistenceAdapter(persistence)
    result = await adapter.school_operations_audit_list(
        SimpleNamespace(school_id=17, school_ref="SCHOOL_A"),
        offset=0,
        limit=25,
        category="class",
    )
    assert result["has_more"] is False
    assert [item["event_ref"] for item in result["items"]] == [
        "2d6e0c0f-233b-4d62-8f20-d7d0a2f187a3"
    ]
    assert result["items"][0]["created_at"].tzinfo is UTC
    session.close()
    engine.dispose()


@pytest.mark.asyncio
async def test_account_events_require_school_provision_scope():
    engine = create_engine("sqlite:///:memory:")
    event.listen(
        engine,
        "connect",
        lambda connection, _record: connection.create_collation(
            "ascii_bin", lambda left, right: (left > right) - (left < right)
        ),
    )
    selected = ["schools", "accounts", "school_account_provisions", "audit_events"]
    db_models.Base.metadata.create_all(
        engine, tables=[db_models.Base.metadata.tables[name] for name in selected]
    )
    session = Session(engine)
    session.execute(
        db_models.School.__table__.insert(),
        [
            {
                "id": 17,
                "public_id": "school-pub-17",
                "school_ref": "SCHOOL_A",
                "data_origin": "SYNTHETIC",
                "provenance_ref": "SYNTHETIC_REF_SCHOOL_SEED_RECIPE_V1",
            },
            {
                "id": 18,
                "public_id": "school-pub-18",
                "school_ref": "SCHOOL_B",
                "data_origin": "SYNTHETIC",
                "provenance_ref": "SYNTHETIC_REF_SCHOOL_SEED_RECIPE_V1",
            },
        ],
    )
    session.execute(
        db_models.Account.__table__.insert(),
        [
            {
                "id": 301,
                "public_id": "account-a",
                "login_name": "SYNTHETIC_A",
                "password_hash": "fixture-hash",
            },
            {
                "id": 302,
                "public_id": "account-b",
                "login_name": "SYNTHETIC_B",
                "password_hash": "fixture-hash",
            },
        ],
    )
    session.execute(
        db_models.SchoolAccountProvision.__table__.insert(),
        [
            {
                "id": 401,
                "public_id": "provision-a",
                "school_id": 17,
                "batch_id": 501,
                "account_id": 301,
                "membership_id": 601,
                "membership_role_id": 701,
                "row_no": 1,
                "role_code": "student",
                "status": "PENDING_ACTIVATION",
            },
            {
                "id": 402,
                "public_id": "provision-b",
                "school_id": 18,
                "batch_id": 502,
                "account_id": 302,
                "membership_id": 602,
                "membership_role_id": 702,
                "row_no": 1,
                "role_code": "student",
                "status": "PENDING_ACTIVATION",
            },
        ],
    )
    event_common = {
        "result": "SUCCESS",
        "trace_id": "TRACE_fixture",
        "created_at": datetime(2026, 10, 16, tzinfo=UTC),
    }
    session.execute(
        db_models.AuditEvent.__table__.insert(),
        [
            {
                "id": 1,
                "public_id": "a4585e22-b5ce-453a-b376-f8c6306b7cc1",
                "action": "school_directory.activate_account",
                "resource_type": "school_account",
                "resource_public_id": "account-a",
                **event_common,
            },
            {
                "id": 2,
                "public_id": "b77e9a73-afbc-4481-adf0-ea33df53e883",
                "action": "school_directory.activate_account",
                "resource_type": "school_account",
                "resource_public_id": "account-b",
                **event_common,
            },
        ],
    )
    session.commit()
    adapter = SchoolOperationsAuditPersistenceAdapter(SqlitePersistence(session))
    result = await adapter.school_operations_audit_list(
        SimpleNamespace(school_id=17, school_ref="SCHOOL_A"),
        offset=0,
        limit=25,
        category="account",
    )
    assert result["has_more"] is False
    assert [item["event_ref"] for item in result["items"]] == [
        "a4585e22-b5ce-453a-b376-f8c6306b7cc1"
    ]
    assert "account-a" not in str(result)
    session.close()
    engine.dispose()
