"""Human review workflow with strict transitions and synthetic identities."""

from __future__ import annotations

from safety_engine.domain import (
    ActorRole,
    DisclosurePolicy,
    ErrorCode,
    HumanReviewCase,
    ReviewAuditEvent,
    ReviewStatus,
    SafetyError,
)
from safety_engine.domain.models import utc_now

from .repository import ReviewRepository

TRANSITIONS: dict[ReviewStatus, frozenset[ReviewStatus]] = {
    ReviewStatus.PENDING: frozenset({ReviewStatus.ASSIGNED, ReviewStatus.ESCALATED}),
    ReviewStatus.ASSIGNED: frozenset({ReviewStatus.IN_REVIEW, ReviewStatus.ESCALATED}),
    ReviewStatus.IN_REVIEW: frozenset(
        {ReviewStatus.APPROVED, ReviewStatus.REJECTED, ReviewStatus.ESCALATED}
    ),
    ReviewStatus.APPROVED: frozenset({ReviewStatus.CLOSED}),
    ReviewStatus.REJECTED: frozenset({ReviewStatus.CLOSED}),
    ReviewStatus.ESCALATED: frozenset({ReviewStatus.IN_REVIEW, ReviewStatus.CLOSED}),
    ReviewStatus.CLOSED: frozenset(),
}


class HumanReviewService:
    component = "human_review"
    version = "1.0"

    def __init__(self, repository: ReviewRepository) -> None:
        self.repository = repository

    def health(self):
        from safety_engine.domain import ComponentHealth

        return ComponentHealth(
            component=self.component, available=True, ready=True, version=self.version
        )

    def create(
        self,
        *,
        decision_id: str,
        trace_id: str,
        reason_codes: list[str],
        actor_role: ActorRole,
        disclosure_policy: DisclosurePolicy,
    ) -> HumanReviewCase:
        case = HumanReviewCase(
            decision_id=decision_id,
            trace_id=trace_id,
            reason_codes=reason_codes,
            priority=("CRITICAL" if "EXPLICIT_CRISIS_SIGNAL" in reason_codes else "HIGH"),
            actor_role=actor_role,
            disclosure_policy=disclosure_policy,
        )
        try:
            return self.repository.save(case)
        except Exception as exc:
            raise SafetyError(
                ErrorCode.REVIEW_QUEUE_FAILED,
                "human review case could not be persisted",
            ) from exc

    def transition(
        self,
        review_case_id: str,
        to_status: ReviewStatus,
        *,
        actor_id: str,
    ) -> HumanReviewCase:
        case = self.repository.get(review_case_id)
        if case is None:
            raise SafetyError(
                ErrorCode.REVIEW_QUEUE_FAILED, "review case was not found", retryable=False
            )
        if not actor_id.startswith("synthetic-reviewer-") and actor_id != "synthetic-system":
            raise SafetyError(
                ErrorCode.REVIEW_QUEUE_FAILED,
                "Round 1 review actor must be synthetic",
                retryable=False,
            )
        if to_status not in TRANSITIONS[case.status]:
            raise SafetyError(
                ErrorCode.REVIEW_QUEUE_FAILED,
                f"invalid review transition {case.status.value}->{to_status.value}",
                retryable=False,
            )
        old_status = case.status
        case.status = to_status
        case.updated_at = utc_now()
        case.reviewer_id = actor_id
        if to_status == ReviewStatus.ASSIGNED:
            case.assigned_reviewer_id = actor_id
            case.assigned_role = ActorRole.REVIEWER
        if to_status in {ReviewStatus.APPROVED, ReviewStatus.REJECTED}:
            case.decision = to_status.value
        event = ReviewAuditEvent(
            review_case_id=case.review_case_id,
            from_status=old_status,
            to_status=to_status,
            actor_id=actor_id,
        )
        case.audit_event_ids.append(event.event_id)
        self.repository.save_event(event)
        self.repository.save(case)
        return case

    def workflow(
        self, review_case_id: str, *, reviewer_id: str = "synthetic-reviewer-001"
    ) -> HumanReviewCase:
        self.transition(review_case_id, ReviewStatus.ASSIGNED, actor_id=reviewer_id)
        self.transition(review_case_id, ReviewStatus.IN_REVIEW, actor_id=reviewer_id)
        self.transition(review_case_id, ReviewStatus.APPROVED, actor_id=reviewer_id)
        return self.transition(review_case_id, ReviewStatus.CLOSED, actor_id=reviewer_id)
