from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from database_layer.base import utc_now
from database_layer.enums import DataOrigin, ReviewPriority, ReviewStatus, SafetyAction
from database_layer.errors import OptimisticConcurrencyConflict
from database_layer.models import Account, AssessmentResponse, IdempotencyRecord, ReviewCase
from database_layer.repositories import (
    AccountRepository,
    AssessmentRepository,
    IdempotencyStore,
    ReviewRepository,
    SubjectRepository,
)
from sqlalchemy import select, text

pytestmark = pytest.mark.mysql


REQUIRED_TABLES = {
    "accounts",
    "roles",
    "account_roles",
    "subjects",
    "subject_access_grants",
    "consent_records",
    "auth_sessions",
    "assessment_sessions",
    "assessment_responses",
    "assessment_results",
    "support_sessions",
    "support_messages",
    "support_runs",
    "support_evidence",
    "safety_decisions",
    "review_cases",
    "review_events",
    "idempotency_records",
    "audit_events",
}


async def test_mysql_runtime_and_schema(mysql_engine) -> None:
    async with mysql_engine.connect() as connection:
        runtime = (
            (
                await connection.execute(
                    text(
                        "SELECT VERSION() AS version, @@version_comment AS edition, "
                        "@@character_set_database AS charset_name, "
                        "@@collation_database AS collation_name, "
                        "@@time_zone AS time_zone, @@sql_mode AS sql_mode"
                    )
                )
            )
            .mappings()
            .one()
        )
        assert str(runtime["version"]).startswith("8.4.")
        assert "Community" in str(runtime["edition"])
        assert runtime["charset_name"] == "utf8mb4"
        assert runtime["collation_name"] == "utf8mb4_0900_ai_ci"
        assert runtime["time_zone"] == "+00:00"
        assert "STRICT" in str(runtime["sql_mode"])

        tables = {
            row[0]
            for row in (
                await connection.execute(
                    text(
                        "SELECT TABLE_NAME FROM information_schema.TABLES "
                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'"
                    )
                )
            ).all()
        }
        assert REQUIRED_TABLES.issubset(tables)
        engines = {
            row[0]: row[1]
            for row in (
                await connection.execute(
                    text(
                        "SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES "
                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN "
                        "('accounts','subjects','assessment_responses','audit_events')"
                    )
                )
            ).all()
        }
        assert set(engines.values()) == {"InnoDB"}


async def test_migration_version_table_is_at_head(mysql_engine) -> None:
    async with mysql_engine.connect() as connection:
        revision = (
            await connection.execute(text("SELECT version_num FROM database_alembic_version"))
        ).scalar_one()
    assert revision == "20260905_0001"


async def test_encrypted_assessment_response_is_not_plaintext(session_factory, protection) -> None:
    suffix = uuid4().hex
    async with session_factory.begin() as session:
        subject = await SubjectRepository(session).create(
            subject_ref=f"SUBJ_mysql_test_{suffix}", data_origin=DataOrigin.SYNTHETIC
        )
        assessment = await AssessmentRepository(session, protection).create_session(
            assessment_ref=f"ASSESS_mysql_test_{suffix}",
            subject_id=subject.id,
            instrument_id="synthetic",
            instrument_version="0.1.0",
            item_bank_version="synthetic-0.1.0",
            config_version="synthetic-0.1.0",
            trace_id=f"TRACE_mysql_test_{suffix}",
        )
        phrase = f"synthetic-sensitive-{suffix}"
        response = await AssessmentRepository(session, protection).append_response(
            assessment_session_id=assessment.id,
            sequence_no=1,
            item_ref=f"ITEM_mysql_test_{suffix}",
            response_payload={"answer": phrase},
            trace_id=f"TRACE_mysql_test_{suffix}",
        )
        raw = await session.scalar(
            select(AssessmentResponse.response_ciphertext).where(
                AssessmentResponse.id == response.id
            )
        )
        assert raw is not None
        assert phrase.encode("utf-8") not in raw
        await session.delete(response)
        await session.delete(assessment)
        await session.delete(subject)


async def test_transaction_rollback_leaves_no_account(session_factory) -> None:
    suffix = uuid4().hex
    async with session_factory() as session:
        await session.begin()
        account = await AccountRepository(session).create(
            login_name=f"rollback_{suffix}", password_hash="synthetic-hash"
        )
        account_id = account.id
        await session.rollback()
        assert await session.get(Account, account_id) is None


async def test_review_version_prevents_stale_update(session_factory, protection) -> None:
    suffix = uuid4().hex
    async with session_factory.begin() as session:
        subject = await SubjectRepository(session).create(
            subject_ref=f"SUBJ_review_test_{suffix}", data_origin=DataOrigin.SYNTHETIC
        )
        # The safety FK is created with a small direct fixture in the same
        # transaction by the test helper below.
        account = await AccountRepository(session).create(
            login_name=f"reviewer_{suffix}", password_hash="synthetic-hash"
        )
        assessment = await AssessmentRepository(session, protection).create_session(
            assessment_ref=f"ASSESS_review_test_{suffix}",
            subject_id=subject.id,
            instrument_id="synthetic",
            instrument_version="0.1.0",
            item_bank_version=None,
            config_version=None,
            trace_id=f"TRACE_review_test_{suffix}",
        )
        from database_layer.repositories import SupportRepository

        support = await SupportRepository(session, protection).create_session(
            support_ref=f"SUPPORT_review_test_{suffix}",
            subject_id=subject.id,
            target_role="reviewer",
            assessment_session_id=assessment.id,
            trace_id=f"TRACE_review_test_{suffix}",
            retention_due_at=None,
        )
        run = await SupportRepository(session, protection).create_run(
            run_ref=f"GEN_review_test_{suffix}",
            support_session_id=support.id,
            trace_id=f"TRACE_review_test_{suffix}",
        )
        decision = await SupportRepository(session, protection).create_safety_decision(
            decision_ref=f"SAFE_review_test_{suffix}",
            support_run_id=run.id,
            action=SafetyAction.REVIEW_REQUIRED,
            policy_version="synthetic-0.1.0",
            guard_model_revision=None,
            trace_id=f"TRACE_review_test_{suffix}",
            detail=None,
            retention_due_at=None,
        )
        review = await ReviewRepository(session, protection).create_case(
            review_ref=f"REVIEW_test_{suffix}",
            subject_id=subject.id,
            safety_decision_id=decision.id,
            priority=ReviewPriority.NORMAL,
            case_note=None,
            retention_due_at=None,
        )
        review_id = review.id
        subject_id = subject.id
        account_id = account.id

    async with session_factory() as first, session_factory() as second:
        async with first.begin():
            first_case = await first.get(ReviewCase, review_id)
            assert first_case is not None
            first_case.version = 2
        async with second.begin():
            second_case = await second.get(ReviewCase, review_id)
            assert second_case is not None
            with pytest.raises(OptimisticConcurrencyConflict):
                await ReviewRepository(second, protection).update_case(
                    review_case_id=review_id,
                    expected_version=1,
                    status=ReviewStatus.IN_REVIEW,
                )

    # The test database is named and dedicated; remove only this synthetic graph.
    async with session_factory.begin() as cleanup:
        from database_layer.lifecycle import SyntheticLifecycleService

        await SyntheticLifecycleService(cleanup).erase_subject(subject_id)
        account = await cleanup.get(Account, account_id)
        if account:
            await cleanup.delete(account)


async def test_idempotency_concurrent_claim_has_one_authoritative_effect(session_factory) -> None:
    scope = f"generation:{uuid4().hex}"
    key = f"idem-{uuid4().hex}"
    expires_at = utc_now() + timedelta(minutes=5)

    async def claim_one() -> tuple[int, bool]:
        async with session_factory() as session:
            await session.begin()
            record, created = await IdempotencyStore(session).claim(
                scope=scope,
                key=key,
                request_bytes=b"synthetic-request",
                expires_at=expires_at,
            )
            await session.commit()
            return record.id, created

    results = await asyncio.gather(claim_one(), claim_one())
    assert sum(created for _, created in results) == 1
    assert len({record_id for record_id, _ in results}) == 1

    async with session_factory.begin() as cleanup:
        record = await cleanup.get(IdempotencyRecord, results[0][0])
        if record:
            await cleanup.delete(record)
