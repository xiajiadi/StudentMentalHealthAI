from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from database_layer.base import Base
from database_layer.errors import OptimisticConcurrencyConflict, UniqueConflict
from database_layer.models import (
    Account,
    AccountSchoolMembership,
    MembershipRole,
    SafetyDecision,
    School,
    SchoolClass,
    SchoolClassStudent,
    SchoolConversationSafetyCase,
    SchoolConversationSafetyEvent,
    Subject,
    SubjectAccessGrant,
    SupportRun,
    SupportSession,
)
from database_layer.provenance import SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF
from database_layer.school_conversation_safety import (
    SchoolConversationSafetyError,
    SchoolConversationSafetyRepository,
)
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Session

_NOW = datetime(2026, 10, 15, 0, 0, tzinfo=UTC)


class _AsyncSession:
    def __init__(self, session: Session) -> None:
        self.sync = session

    async def scalar(self, statement):
        return self.sync.scalar(statement)

    async def scalars(self, statement):
        return self.sync.scalars(statement)

    async def execute(self, statement):
        return self.sync.execute(statement)

    def add(self, value):
        self.sync.add(value)

    async def flush(self):
        self.sync.flush()

    @asynccontextmanager
    async def begin_nested(self):
        with self.sync.begin_nested():
            yield self


@pytest.fixture
def db(monkeypatch):
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
    def enable_constraints(connection, _record):
        connection.create_collation(
            "ascii_bin", lambda left, right: (left > right) - (left < right)
        )
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = Session(engine)
    _seed(session)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed(session: Session, *, second_class: bool = False) -> None:
    now = _NOW.replace(tzinfo=None)
    session.add(
        School(
            id=1,
            school_ref="conversation-safety-school",
            status="ACTIVE",
            data_origin="SYNTHETIC",
            provenance_ref=SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF,
        )
    )
    for account_id, login in ((1, "safety-student"), (2, "safety-admin"), (3, "safety-specialist")):
        session.add(
            Account(id=account_id, login_name=login, password_hash="synthetic", status="ACTIVE")
        )
    session.flush()
    for membership_id, account_id in ((1, 1), (2, 2), (3, 3)):
        session.add(
            AccountSchoolMembership(
                id=membership_id,
                account_id=account_id,
                school_id=1,
                status="ACTIVE",
                valid_from=now - timedelta(days=1),
            )
        )
    session.flush()
    for role_id, membership_id, role_code in (
        (1, 1, "student"),
        (2, 2, "admin"),
        (3, 3, "psychological_specialist"),
    ):
        session.add(
            MembershipRole(
                id=role_id,
                membership_id=membership_id,
                school_id=1,
                role_code=role_code,
                status="ACTIVE",
                valid_from=now - timedelta(days=1),
            )
        )
    session.add(
        Subject(
            id=1,
            subject_ref="SUBJ_conversation_safety",
            school_id=1,
            status="ACTIVE",
            data_origin="SYNTHETIC",
        )
    )
    session.flush()
    session.add(
        SubjectAccessGrant(
            id=1,
            principal_account_id=1,
            subject_id=1,
            school_id=1,
            relationship_type="SELF",
            status="ACTIVE",
            valid_from=now - timedelta(days=1),
        )
    )
    session.add(
        SchoolClass(
            id=1,
            school_id=1,
            class_ref="class-a",
            created_by_membership_role_id=2,
            status="ACTIVE",
        )
    )
    if second_class:
        session.add(
            SchoolClass(
                id=2,
                school_id=1,
                class_ref="class-b",
                created_by_membership_role_id=2,
                status="ACTIVE",
            )
        )
    session.flush()
    session.add(
        SchoolClassStudent(
            id=1,
            school_id=1,
            class_id=1,
            subject_id=1,
            status="ACTIVE",
            valid_from=now - timedelta(days=1),
        )
    )
    if second_class:
        session.add(
            SchoolClassStudent(
                id=2,
                school_id=1,
                class_id=2,
                subject_id=1,
                status="ACTIVE",
                valid_from=now - timedelta(days=1),
            )
        )
    session.add(
        SupportSession(
            id=1,
            support_ref="CONV_safety_test",
            subject_id=1,
            assessment_session_id=None,
            target_role="student",
            status="ACTIVE",
            started_at=now,
        )
    )
    session.flush()
    session.add(
        SupportRun(
            id=1,
            run_ref="TURN_safety_test",
            support_session_id=1,
            assessment_session_id=None,
            trace_id="TRACE_safety_test",
            status="BLOCKED",
            workflow_action="CRISIS_ROUTE",
            started_at=now,
            completed_at=now,
        )
    )
    session.flush()
    session.add(
        SafetyDecision(
            id=1,
            decision_ref="SAFE_safety_test",
            support_run_id=1,
            action="CRISIS_ROUTE",
            policy_version="test-safety-v1",
            trace_id="TRACE_safety_test",
        )
    )
    session.commit()


def _create(repo: SchoolConversationSafetyRepository):
    return repo.create_from_safety_decision(
        support_session_id=1,
        support_run_id=1,
        safety_decision_id=1,
        school_id=1,
        subject_id=1,
        action="CRISIS_ROUTE",
        reason_codes=("SYNTHETIC_TEST_CODE",),
        safety_review_reference="review_case_test",
        actor_membership_role_id=1,
        trace_id="TRACE_safety_test",
        now=_NOW,
    )


def test_case_creation_is_idempotently_bound_to_source_and_stores_only_metadata(db):
    async def run():
        repo = SchoolConversationSafetyRepository(_AsyncSession(db))
        case = await _create(repo)
        assert case.status == "UNASSIGNED_PENDING"
        assert case.action == "CRISIS_ROUTE"
        assert case.reason_codes == ("SYNTHETIC_TEST_CODE",)
        assert case.class_ref == "class-a"
        assert case.decision_code is None
        assert db.scalar(
            select(SchoolConversationSafetyCase).where(
                SchoolConversationSafetyCase.case_ref == case.case_ref
            )
        )
        event_row = db.scalar(select(SchoolConversationSafetyEvent))
        assert event_row.event_type == "CREATED"
        assert not hasattr(event_row, "message")
        with pytest.raises(UniqueConflict):
            await _create(repo)

    asyncio.run(run())


def test_ambiguous_class_is_durable_unbound_then_admin_must_bind_exact_current_class(db):
    now = _NOW.replace(tzinfo=None)
    db.add(
        SchoolClass(
            id=2,
            school_id=1,
            class_ref="class-b",
            created_by_membership_role_id=2,
            status="ACTIVE",
        )
    )
    db.flush()
    db.add(
        SchoolClassStudent(
            id=2,
            school_id=1,
            class_id=2,
            subject_id=1,
            status="ACTIVE",
            valid_from=now - timedelta(days=1),
        )
    )
    db.commit()

    async def run():
        repo = SchoolConversationSafetyRepository(_AsyncSession(db))
        case = await _create(repo)
        assert case.class_id is None
        assigned = await repo.assign(
            school_id=1,
            case_ref=case.case_ref,
            class_ref="class-b",
            specialist_membership_role_id=3,
            actor_membership_role_id=2,
            expected_version=1,
            trace_id="TRACE_bind_class",
            now=_NOW,
        )
        assert assigned.class_ref == "class-b"
        assert assigned.status == "ASSIGNED"

    asyncio.run(run())


def test_explicit_unresolved_status_never_uses_approved_and_stale_scope_hides_case(db):
    async def run():
        repo = SchoolConversationSafetyRepository(_AsyncSession(db))
        case = await _create(repo)
        assigned = await repo.assign(
            school_id=1,
            case_ref=case.case_ref,
            class_ref="class-a",
            specialist_membership_role_id=3,
            actor_membership_role_id=2,
            expected_version=1,
            trace_id="TRACE_assign",
            now=_NOW,
        )
        assert assigned.status == "ASSIGNED"
        in_review = await repo.transition(
            school_id=1,
            case_ref=case.case_ref,
            specialist_membership_role_id=3,
            expected_version=2,
            to_status="IN_REVIEW",
            decision_code=None,
            trace_id="TRACE_review",
            now=_NOW,
        )
        assert in_review.status == "IN_REVIEW"
        with pytest.raises(SchoolConversationSafetyError):
            await repo.transition(
                school_id=1,
                case_ref=case.case_ref,
                specialist_membership_role_id=3,
                expected_version=3,
                to_status="REVIEWED",
                decision_code=None,
                trace_id="TRACE_decision",
                now=_NOW,
            )
        reviewed = await repo.transition(
            school_id=1,
            case_ref=case.case_ref,
            specialist_membership_role_id=3,
            expected_version=3,
            to_status="REVIEWED",
            decision_code="UNRESOLVED_NEEDS_CONTEXT",
            trace_id="TRACE_decision",
            now=_NOW,
        )
        assert reviewed.status == "REVIEWED"
        assert reviewed.decision_code == "UNRESOLVED_NEEDS_CONTEXT"
        assert "APPROVED" not in {reviewed.status, reviewed.decision_code}
        link = db.get(SchoolClassStudent, 1)
        link.status = "REVOKED"
        link.revoked_at = _NOW.replace(tzinfo=None)
        db.flush()
        assert (
            await repo.get_assigned(
                school_id=1,
                case_ref=case.case_ref,
                specialist_membership_role_id=3,
                now=_NOW,
            )
            is None
        )

    asyncio.run(run())


def test_assigned_list_total_uses_current_assignment_and_roster_scope(db):
    async def run():
        repo = SchoolConversationSafetyRepository(_AsyncSession(db))
        case = await _create(repo)
        await repo.assign(
            school_id=1,
            case_ref=case.case_ref,
            class_ref="class-a",
            specialist_membership_role_id=3,
            actor_membership_role_id=2,
            expected_version=1,
            trace_id="TRACE_assign_list",
            now=_NOW,
        )
        rows = await repo.list_assigned(
            school_id=1,
            specialist_membership_role_id=3,
            limit=1,
            offset=0,
            now=_NOW,
        )
        assert len(rows) == 1
        assert (
            await repo.count_assigned(school_id=1, specialist_membership_role_id=3, now=_NOW) == 1
        )

        link = db.get(SchoolClassStudent, 1)
        link.status = "REVOKED"
        link.revoked_at = _NOW.replace(tzinfo=None)
        db.flush()
        assert (
            await repo.list_assigned(
                school_id=1,
                specialist_membership_role_id=3,
                limit=1,
                offset=0,
                now=_NOW,
            )
            == []
        )
        assert (
            await repo.count_assigned(school_id=1, specialist_membership_role_id=3, now=_NOW) == 0
        )

    asyncio.run(run())


def test_student_status_selects_latest_case_when_session_has_multiple_safety_decisions(db):
    async def run():
        repo = SchoolConversationSafetyRepository(_AsyncSession(db))
        first = await _create(repo)
        db.add(
            SafetyDecision(
                id=2,
                decision_ref="SAFE_safety_test_second",
                support_run_id=1,
                action="CRISIS_ROUTE",
                policy_version="test-safety-v1",
                trace_id="TRACE_safety_test_second",
            )
        )
        db.flush()
        latest = await repo.create_from_safety_decision(
            support_session_id=1,
            support_run_id=1,
            safety_decision_id=2,
            school_id=1,
            subject_id=1,
            action="CRISIS_ROUTE",
            reason_codes=("SYNTHETIC_SECOND_CODE",),
            safety_review_reference=None,
            actor_membership_role_id=1,
            trace_id="TRACE_safety_second",
            now=_NOW,
        )

        current = await repo.get_student_status(school_id=1, subject_id=1, support_session_id=1)
        assert current is not None
        assert current.case_ref == latest.case_ref
        assert current.case_ref != first.case_ref

    asyncio.run(run())


def test_escalation_and_close_transitions_cannot_reopen_or_approve(db):
    async def run():
        repo = SchoolConversationSafetyRepository(_AsyncSession(db))
        case = await _create(repo)
        assigned = await repo.assign(
            school_id=1,
            case_ref=case.case_ref,
            class_ref="class-a",
            specialist_membership_role_id=3,
            actor_membership_role_id=2,
            expected_version=1,
            trace_id="TRACE_assign_graph",
            now=_NOW,
        )
        in_review = await repo.transition(
            school_id=1,
            case_ref=case.case_ref,
            specialist_membership_role_id=3,
            expected_version=assigned.state_version,
            to_status="IN_REVIEW",
            decision_code=None,
            trace_id="TRACE_review_graph",
            now=_NOW,
        )
        escalated = await repo.transition(
            school_id=1,
            case_ref=case.case_ref,
            specialist_membership_role_id=3,
            expected_version=in_review.state_version,
            to_status="ESCALATION_NEEDED",
            decision_code="UNRESOLVED_NEEDS_CONTEXT",
            trace_id="TRACE_escalation_graph",
            now=_NOW,
        )
        closed = await repo.transition(
            school_id=1,
            case_ref=case.case_ref,
            specialist_membership_role_id=3,
            expected_version=escalated.state_version,
            to_status="CLOSED",
            decision_code="UNRESOLVED_NEEDS_CONTEXT",
            trace_id="TRACE_close_graph",
            now=_NOW,
        )
        assert closed.status == "CLOSED"
        with pytest.raises(OptimisticConcurrencyConflict):
            await repo.transition(
                school_id=1,
                case_ref=case.case_ref,
                specialist_membership_role_id=3,
                expected_version=closed.state_version,
                to_status="IN_REVIEW",
                decision_code=None,
                trace_id="TRACE_reopen_graph",
                now=_NOW,
            )
        assert "APPROVED" not in {
            assigned.status,
            in_review.status,
            escalated.status,
            closed.status,
        }

    asyncio.run(run())
