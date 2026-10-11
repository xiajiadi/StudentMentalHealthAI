from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from database_layer.base import utc_now
from database_layer.enums import DataOrigin, ReviewPriority, ReviewStatus, SafetyAction
from database_layer.errors import OptimisticConcurrencyConflict
from database_layer.models import (
    Account,
    AssessmentResponse,
    IdempotencyRecord,
    ReviewCase,
    SubjectAccessGrant,
)
from database_layer.repositories import (
    SYNTHETIC_SCHOOL_PROVENANCE_REF,
    AccountRepository,
    AssessmentRepository,
    AuthSessionStore,
    IdempotencyStore,
    ReviewRepository,
    SchoolMembershipRepository,
    SubjectRepository,
)
from sqlalchemy import select, text

pytestmark = pytest.mark.mysql


REQUIRED_TABLES = {
    "accounts",
    "roles",
    "account_roles",
    "schools",
    "account_school_memberships",
    "membership_roles",
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
    assert revision == "20261011_0004"


async def test_encrypted_assessment_response_is_not_plaintext(session_factory, protection) -> None:
    suffix = uuid4().hex
    async with session_factory.begin() as session:
        subject = await SubjectRepository(session).create(
            subject_ref=f"SUBJ_mysql_test_{suffix}",
            school_id=None,
            data_origin=DataOrigin.SYNTHETIC,
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
            subject_ref=f"SUBJ_review_test_{suffix}",
            school_id=None,
            data_origin=DataOrigin.SYNTHETIC,
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


async def test_school_contexts_grants_and_sessions_are_same_school_and_fail_closed(
    session_factory,
) -> None:
    from database_layer.base import utc_now

    suffix = uuid4().hex
    now = utc_now()
    async with session_factory.begin() as session:
        accounts = AccountRepository(session)
        teacher = await accounts.create(
            login_name=f"teacher_{suffix}", password_hash="synthetic-hash"
        )
        other = await accounts.create(
            login_name=f"other_{suffix}", password_hash="synthetic-hash"
        )
        memberships = SchoolMembershipRepository(session)
        provenance_ref = SYNTHETIC_SCHOOL_PROVENANCE_REF
        school_a = await memberships.create_school(
            school_ref=f"SCHOOL_A_{suffix}",
            data_origin=DataOrigin.SYNTHETIC,
            provenance_ref=provenance_ref,
        )
        school_b = await memberships.create_school(
            school_ref=f"SCHOOL_B_{suffix}",
            data_origin=DataOrigin.SYNTHETIC,
            provenance_ref=provenance_ref,
        )
        membership_a = await memberships.create_membership(
            account_id=teacher.id, school_id=school_a.id, valid_from=now
        )
        membership_b = await memberships.create_membership(
            account_id=teacher.id, school_id=school_b.id, valid_from=now
        )
        inactive_membership = await memberships.create_membership(
            account_id=other.id, school_id=school_a.id, valid_from=now, status="INACTIVE"
        )
        role_a = await memberships.add_role(
            membership_id=membership_a.id,
            school_id=school_a.id,
            role_code="teacher",
            valid_from=now,
        )
        role_b = await memberships.add_role(
            membership_id=membership_b.id,
            school_id=school_b.id,
            role_code="teacher",
            valid_from=now,
        )
        inactive_role = await memberships.add_role(
            membership_id=inactive_membership.id,
            school_id=school_a.id,
            role_code="teacher",
            valid_from=now,
        )
        subject_a = await SubjectRepository(session).create(
            subject_ref=f"SUBJ_A_{suffix}", school_id=school_a.id
        )
        subject_b = await SubjectRepository(session).create(
            subject_ref=f"SUBJ_B_{suffix}", school_id=school_b.id
        )
        legacy_subject = await SubjectRepository(session).create(
            subject_ref=f"SUBJ_LEGACY_{suffix}", school_id=None
        )

        grant_a = await memberships.grant_subject_in_school(
            principal_account_id=teacher.id,
            subject_id=subject_a.id,
            school_id=school_a.id,
            role_code="teacher",
            valid_from=now,
        )
        with pytest.raises(ValueError, match="principal has no active matching school role"):
            await memberships.grant_subject_in_school(
                principal_account_id=other.id,
                subject_id=subject_b.id,
                school_id=school_b.id,
                role_code="teacher",
                valid_from=now,
            )
        with pytest.raises(ValueError, match="not active in the requested school"):
            await memberships.grant_subject_in_school(
                principal_account_id=teacher.id,
                subject_id=subject_b.id,
                school_id=school_a.id,
                role_code="teacher",
                valid_from=now,
            )
        grant_b = await memberships.grant_subject_in_school(
            principal_account_id=teacher.id,
            subject_id=subject_b.id,
            school_id=school_b.id,
            role_code="teacher",
            valid_from=now,
        )
        with pytest.raises(ValueError, match="role cannot receive a school subject grant"):
            await memberships.grant_subject_in_school(
                principal_account_id=teacher.id,
                subject_id=subject_a.id,
                school_id=school_a.id,
                role_code="reviewer",
                valid_from=now,
            )

        school_a_contexts = await memberships.active_contexts(account_id=teacher.id, at=now)
        assert {(row[1], row[2]) for row in school_a_contexts} == {
            ("teacher", school_a.id),
            ("teacher", school_b.id),
        }
        assert await memberships.active_contexts(account_id=other.id, at=now) == []
        assert await memberships.context_for_account(
            account_id=other.id, context_id=role_a.id, at=now
        ) is None
        assert await memberships.authorized_subject_refs(
            account_id=teacher.id,
            school_id=school_a.id,
            role_code="teacher",
            at=now,
        ) == frozenset({subject_a.subject_ref})
        assert await memberships.authorized_subject_refs(
            account_id=teacher.id,
            school_id=school_b.id,
            role_code="teacher",
            at=now,
        ) == frozenset({subject_b.subject_ref})

        role_a.revoked_at = now
        assert await memberships.context_for_account(
            account_id=teacher.id, context_id=role_a.id, at=now
        ) is None
        assert {
            row[0]
            for row in await memberships.active_contexts(account_id=teacher.id, at=now)
        } == {role_b.id}
        grant_a.revoked_at = now
        assert await memberships.authorized_subject_refs(
            account_id=teacher.id,
            school_id=school_a.id,
            role_code="teacher",
            at=now,
        ) == frozenset()
        membership_b.revoked_at = now
        assert await memberships.context_for_account(
            account_id=teacher.id, context_id=role_b.id, at=now
        ) is None
        assert await memberships.authorized_subject_refs(
            account_id=teacher.id,
            school_id=school_b.id,
            role_code="teacher",
            at=now,
        ) == frozenset()

        # Internal REVIEW_ASSIGNMENT remains NULL-scoped, but the school
        # context resolver cannot consume it as a school grant.
        legacy_reviewer = await accounts.create(
            login_name=f"reviewer_{suffix}", password_hash="synthetic-hash"
        )
        legacy_grant = SubjectAccessGrant(
                principal_account_id=legacy_reviewer.id,
                subject_id=legacy_subject.id,
                school_id=None,
                relationship_type="REVIEW_ASSIGNMENT",
                status="ACTIVE",
                valid_from=now,
            )
        session.add(legacy_grant)
        await session.flush()
        assert await memberships.authorized_subject_refs(
            account_id=legacy_reviewer.id,
            school_id=school_a.id,
            role_code="teacher",
            at=now,
        ) == frozenset()

        sessions = AuthSessionStore(session)
        raw_token = f"session-{suffix}"
        auth_session = await sessions.create(
            account_id=teacher.id,
            raw_session_token=raw_token,
            raw_csrf_token=f"csrf-{suffix}",
            idle_expires_at=now + timedelta(minutes=10),
            absolute_expires_at=now + timedelta(hours=1),
            active_school_id=school_a.id,
            active_membership_role_id=role_a.id,
        )
        persisted = await sessions.find_by_token(raw_token)
        assert persisted is not None
        assert persisted.active_school_id == school_a.id
        assert persisted.active_membership_role_id == role_a.id
        switched = await sessions.set_active_context(
            raw_token, school_id=school_b.id, membership_role_id=role_b.id
        )
        assert switched is not None
        assert switched.active_school_id == school_b.id
        assert switched.active_membership_role_id == role_b.id

        await session.delete(auth_session)
        await session.delete(grant_a)
        await session.delete(grant_b)
        await session.delete(legacy_grant)
        await session.flush()

        await session.delete(inactive_role)
        await session.delete(role_b)
        await session.delete(role_a)
        await session.flush()

        await session.delete(inactive_membership)
        await session.delete(membership_b)
        await session.delete(membership_a)
        await session.flush()

        await session.delete(legacy_subject)
        await session.delete(subject_b)
        await session.delete(subject_a)
        await session.flush()

        await session.delete(legacy_reviewer)
        await session.delete(teacher)
        await session.delete(other)
        await session.flush()

        await session.delete(school_a)
        await session.delete(school_b)
        await session.flush()
