"""Explicit reference-data and synthetic-fixture seed helpers."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .base import utc_now
from .enums import (
    AccountStatus,
    AuditResult,
    DataOrigin,
    MessageKind,
    ReviewPriority,
    SafetyAction,
)
from .models import Role
from .repositories import AccountRepository, AuditRepository, SubjectRepository

REFERENCE_ROLE_CODES = (
    "student",
    "teacher",
    "parent",
    "reviewer",
    "psychological_specialist",
    "admin",
)


async def seed_reference_roles(session: AsyncSession) -> int:
    """Insert stable role vocabulary idempotently; never inserts demo people."""

    inserted = 0
    for role_code in REFERENCE_ROLE_CODES:
        existing = await session.scalar(select(Role).where(Role.role_code == role_code))
        if existing is None:
            session.add(Role(role_code=role_code, status="ACTIVE"))
            inserted += 1
    await session.flush()
    return inserted


async def seed_synthetic_case(
    session: AsyncSession,
    *,
    protection,
    trace_id: str = "TRACE_synthetic_database_round1",
) -> dict[str, str | int]:
    """Build a fully linked, clearly synthetic persistence fixture.

    This helper is for isolated test/dev databases only.  It does not run
    automatically at application import or migration time.
    """

    from .repositories import AssessmentRepository, ReviewRepository, SupportRepository

    account = await AccountRepository(session).create(
        login_name=f"synthetic-reviewer-{uuid4().hex[:12]}",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$synthetic-fixture-only",
        status=AccountStatus.ACTIVE,
    )
    subject = await SubjectRepository(session).create(
        subject_ref=f"SUBJ_synthetic_{uuid4().hex}",
        school_id=None,
        data_origin=DataOrigin.SYNTHETIC,
        retention_due_at=utc_now() + timedelta(days=1),
    )
    assessment = await AssessmentRepository(session, protection).create_session(
        assessment_ref=f"ASSESS_synthetic_{uuid4().hex}",
        subject_id=subject.id,
        instrument_id="synthetic-instrument",
        instrument_version="0.1.0",
        item_bank_version="synthetic-item-bank-0.1.0",
        config_version="synthetic-config-0.1.0",
        trace_id=trace_id,
    )
    assessment.status = "IN_PROGRESS"
    await AssessmentRepository(session, protection).append_response(
        assessment_session_id=assessment.id,
        sequence_no=1,
        item_ref="ITEM_synthetic_001",
        response_payload={"answer": 3, "source": "synthetic_fixture"},
        trace_id=trace_id,
    )
    await AssessmentRepository(session, protection).save_result(
        assessment_session_id=assessment.id,
        result_payload={"schema_version": "assessment.v1", "source": "synthetic_fixture"},
        completed_at=utc_now(),
        retention_due_at=utc_now() + timedelta(days=1),
    )
    support = await SupportRepository(session, protection).create_session(
        support_ref=f"SUPPORT_synthetic_{uuid4().hex}",
        subject_id=subject.id,
        target_role="teacher",
        assessment_session_id=assessment.id,
        trace_id=trace_id,
        retention_due_at=utc_now() + timedelta(days=1),
    )
    support_repo = SupportRepository(session, protection)
    await support_repo.persist_message(
        support_session_id=support.id,
        sequence_no=1,
        message_kind=MessageKind.USER_INPUT,
        payload={"text": "synthetic user input"},
        retention_due_at=utc_now() + timedelta(days=1),
    )
    run = await support_repo.create_run(
        run_ref=f"GEN_synthetic_{uuid4().hex}",
        support_session_id=support.id,
        assessment_session_id=assessment.id,
        trace_id=trace_id,
        workflow_action="REVIEW_REQUIRED",
        component_versions={"fixture": "0.1.0"},
    )
    decision = await support_repo.create_safety_decision(
        decision_ref=f"SAFE_synthetic_{uuid4().hex}",
        support_run_id=run.id,
        action=SafetyAction.REVIEW_REQUIRED,
        policy_version="synthetic-safety-0.1.0",
        guard_model_revision="synthetic-guard-0.1.0",
        trace_id=trace_id,
        detail={"reason_code": "SYNTHETIC_REVIEW_FIXTURE"},
        retention_due_at=utc_now() + timedelta(days=1),
    )
    await support_repo.persist_message(
        support_session_id=support.id,
        sequence_no=2,
        message_kind=MessageKind.APPROVED_OUTPUT,
        payload={"text": "synthetic approved output"},
        safety_decision_id=decision.id,
        retention_due_at=utc_now() + timedelta(days=1),
    )
    review = await ReviewRepository(session, protection).create_case(
        review_ref=f"REVIEW_synthetic_{uuid4().hex}",
        subject_id=subject.id,
        safety_decision_id=decision.id,
        priority=ReviewPriority.NORMAL,
        case_note={"note": "synthetic review note"},
        retention_due_at=utc_now() + timedelta(days=1),
    )
    await AuditRepository(session).append(
        action="SYNTHETIC_FIXTURE_CREATED",
        resource_type="review_case",
        resource_public_id=review.public_id,
        result=AuditResult.SUCCESS,
        trace_id=trace_id,
        actor_account_id=account.id,
        safe_metadata={"state": "SYNTHETIC", "source": "database_round1_fixture"},
    )
    return {
        "account_id": account.id,
        "subject_id": subject.id,
        "assessment_id": assessment.id,
        "support_session_id": support.id,
        "support_run_id": run.id,
        "safety_decision_id": decision.id,
        "review_case_id": review.id,
    }
