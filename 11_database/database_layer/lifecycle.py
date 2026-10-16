"""Explicit retention and synthetic subject-erasure operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from sqlalchemy import case, delete, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .base import utc_now
from .enums import AuditResult, DataOrigin, SubjectStatus
from .errors import NotFound, PersistenceError
from .models import (
    AssessmentResponse,
    AssessmentResult,
    AssessmentSession,
    ConsentRecord,
    ReviewCase,
    ReviewEvent,
    SafetyDecision,
    SchoolIndependentEducationReview,
    Subject,
    SubjectAccessGrant,
    SupportEvidence,
    SupportMessage,
    SupportRun,
    SupportSession,
)
from .repositories import AuditRepository


@dataclass(frozen=True, slots=True)
class PurgeResult:
    subject_public_id: str
    deleted_rows: dict[str, int]
    audit_event_id: int


class SyntheticLifecycleService:
    """Data-lifecycle service guarded against accidental real-data erasure."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def erase_subject(
        self,
        subject_id: int,
        *,
        synthetic_only: bool = True,
        at: datetime | None = None,
        trace_id: str = "TRACE_database_erasure",
    ) -> PurgeResult:
        subject = await self.session.get(Subject, subject_id)
        if subject is None:
            raise NotFound("subject was not found")
        if synthetic_only and subject.data_origin != DataOrigin.SYNTHETIC.value:
            raise PersistenceError("synthetic erasure service cannot target non-synthetic data")

        erased_at = at or utc_now()
        deleted: dict[str, int] = {}

        case_ids = select(ReviewCase.id).where(ReviewCase.subject_id == subject_id)
        run_ids = (
            select(SupportRun.id)
            .join(SupportSession, SupportRun.support_session_id == SupportSession.id)
            .where(SupportSession.subject_id == subject_id)
        )
        session_ids = select(SupportSession.id).where(SupportSession.subject_id == subject_id)
        assessment_ids = select(AssessmentSession.id).where(
            AssessmentSession.subject_id == subject_id
        )

        deleted["review_events"] = await self._delete(
            delete(ReviewEvent).where(ReviewEvent.review_case_id.in_(case_ids))
        )
        deleted["review_cases"] = await self._delete(
            delete(ReviewCase).where(ReviewCase.subject_id == subject_id)
        )
        deleted["support_evidence"] = await self._delete(
            delete(SupportEvidence).where(SupportEvidence.support_run_id.in_(run_ids))
        )
        deleted["support_messages"] = await self._delete(
            delete(SupportMessage).where(SupportMessage.support_session_id.in_(session_ids))
        )
        deleted["safety_decisions"] = await self._delete(
            delete(SafetyDecision).where(SafetyDecision.support_run_id.in_(run_ids))
        )
        deleted["support_runs"] = await self._delete(
            delete(SupportRun).where(SupportRun.support_session_id.in_(session_ids))
        )
        deleted["support_sessions"] = await self._delete(
            delete(SupportSession).where(SupportSession.subject_id == subject_id)
        )
        deleted["assessment_results"] = await self._delete(
            delete(AssessmentResult).where(
                AssessmentResult.assessment_session_id.in_(assessment_ids)
            )
        )
        deleted["assessment_responses"] = await self._delete(
            delete(AssessmentResponse).where(
                AssessmentResponse.assessment_session_id.in_(assessment_ids)
            )
        )
        deleted["assessment_sessions"] = await self._delete(
            delete(AssessmentSession).where(AssessmentSession.subject_id == subject_id)
        )
        deleted["consent_records"] = await self._delete(
            delete(ConsentRecord).where(ConsentRecord.subject_id == subject_id)
        )
        deleted["subject_access_grants"] = await self._delete(
            delete(SubjectAccessGrant).where(SubjectAccessGrant.subject_id == subject_id)
        )

        subject.status = SubjectStatus.ERASED.value
        subject.subject_ref = f"SUBJ_ERASED_{uuid4().hex}"
        subject.retention_due_at = None
        subject.erased_at = erased_at
        await self.session.flush()

        audit = AuditRepository(self.session)
        event = await audit.append(
            action="SUBJECT_ERASURE_COMPLETED",
            resource_type="subject",
            resource_public_id=subject.public_id,
            result=AuditResult.SUCCESS,
            trace_id=trace_id,
            safe_metadata={"state": "ERASED", "count": sum(deleted.values())},
        )
        return PurgeResult(subject.public_id, deleted, event.id)

    async def purge_due_encrypted_payloads(
        self,
        *,
        before: datetime,
        synthetic_only: bool = True,
        trace_id: str = "TRACE_database_retention",
    ) -> int:
        """Remove ciphertext for due synthetic records without claiming legal policy."""

        if not synthetic_only:
            raise PersistenceError("Round 1 retention routine requires synthetic_only=True")
        total = 0
        for model, field_names in (
            (
                AssessmentResponse,
                (
                    "response_ciphertext",
                    "cipher_format_version",
                    "key_version",
                    "payload_schema_version",
                ),
            ),
            (
                AssessmentResult,
                (
                    "payload_ciphertext",
                    "cipher_format_version",
                    "key_version",
                    "payload_schema_version",
                ),
            ),
            (
                SupportMessage,
                (
                    "payload_ciphertext",
                    "cipher_format_version",
                    "key_version",
                    "payload_schema_version",
                ),
            ),
            (
                SafetyDecision,
                (
                    "detail_ciphertext",
                    "cipher_format_version",
                    "key_version",
                    "payload_schema_version",
                ),
            ),
            (
                ReviewCase,
                (
                    "case_note_ciphertext",
                    "cipher_format_version",
                    "key_version",
                    "payload_schema_version",
                ),
            ),
            (
                ReviewEvent,
                (
                    "note_ciphertext",
                    "cipher_format_version",
                    "key_version",
                    "payload_schema_version",
                ),
            ),
        ):
            due_column = model.retention_due_at
            values = {name: None for name in field_names}
            result = await self.session.execute(
                update(model).where(due_column.is_not(None), due_column <= before).values(**values)
            )
            total += result.rowcount  # type: ignore[reportAttributeAccessIssue]

        # Migration 0024 keeps review rows, state, source/Safety hashes, and
        # append-only events intact at retention time. The candidate ciphertext
        # is NOT NULL and reviewed ciphertext participates in a state CHECK, so
        # replace only existing ciphertext bytes with the empty BLOB instead of
        # nulling columns or mutating workflow metadata. Restrict this new lane
        # to synthetic subjects and skip already-purged rows for repeatability.
        review = SchoolIndependentEducationReview
        synthetic_subject = exists(
            select(1).where(
                Subject.id == review.subject_id,
                Subject.data_origin == DataOrigin.SYNTHETIC.value,
            )
        )
        candidate_ciphertext = review.candidate_payload_ciphertext
        reviewed_ciphertext = review.reviewed_payload_ciphertext
        due = review.retention_due_at.is_not(None) & (review.retention_due_at <= before)
        has_ciphertext = (candidate_ciphertext != b"") | (
            reviewed_ciphertext.is_not(None) & (reviewed_ciphertext != b"")
        )
        result = await self.session.execute(
            update(review)
            .where(due, synthetic_subject, has_ciphertext)
            .values(
                candidate_payload_ciphertext=b"",
                reviewed_payload_ciphertext=case(
                    (reviewed_ciphertext.is_not(None), b""),
                    else_=reviewed_ciphertext,
                ),
            )
        )
        total += result.rowcount  # type: ignore[reportAttributeAccessIssue]
        await self.session.flush()
        audit = AuditRepository(self.session)
        await audit.append(
            action="RETENTION_PAYLOAD_PURGE",
            resource_type="retention_job",
            resource_public_id=None,
            result=AuditResult.SUCCESS,
            trace_id=trace_id,
            safe_metadata={"count": total, "state": "SYNTHETIC_ONLY"},
        )
        return total

    async def _delete(self, statement: object) -> int:
        result = await self.session.execute(statement)  # type: ignore[arg-type]
        return int(result.rowcount or 0)
