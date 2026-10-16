"""Per-resource student consent and assigned-specialist education review adapter."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.independent_education_reviews.schemas import (
    IndependentEducationCandidatePayload,
    IndependentEducationCandidateProjection,
    IndependentEducationDraftPayload,
    IndependentEducationPublishSafetyCheck,
    publish_material_sha256,
)
from smhai_backend.domains.research_general_education.schemas import (
    ResearchGeneralEducationSourceCard,
)

from .school_conversations import SchoolConversationsPersistenceAdapter

_REVIEW_REF = re.compile(r"^EDUREV_[0-9a-f]{32}$")
_REVIEWER_REF = re.compile(r"^ROLE_[0-9a-f-]{36}$")
_PAGE_MAX = 50


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return normalized.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class SchoolIndependentEducationReviewsPersistenceAdapter:
    """Scope every operation to one SELF-owned conversation or one assigned role."""

    def __init__(
        self,
        persistence: Any,
        *,
        expected_school_id: int,
        source_study_ref: str,
        source_package_ref: str,
        source_manifest_sha256: str,
        prompt_id: str,
        prompt_version: str,
        valid_through: datetime,
        source_cards: Mapping[str, ResearchGeneralEducationSourceCard],
    ) -> None:
        if (
            type(expected_school_id) is not int
            or expected_school_id <= 0
            or not source_study_ref
            or not source_package_ref
            or not re.fullmatch(r"[0-9a-f]{64}", source_manifest_sha256)
            or not prompt_id.startswith("PROMPT_")
            or not prompt_version
            or valid_through.tzinfo is None
            or valid_through.utcoffset() is None
        ):
            raise ValueError("independent education review server pins are invalid")
        cards: dict[str, ResearchGeneralEducationSourceCard] = {}
        for chunk_id, value in source_cards.items():
            card = (
                value
                if isinstance(value, ResearchGeneralEducationSourceCard)
                else ResearchGeneralEducationSourceCard.model_validate(value, strict=True)
            )
            if (
                chunk_id != card.chunk_id
                or card.chunk_id in cards
                or (card.consumer_age_min, card.consumer_age_max) != (14, 17)
            ):
                raise ValueError("independent education source cards are invalid")
            cards[chunk_id] = card
        self._persistence = persistence
        self._conversations = SchoolConversationsPersistenceAdapter(
            persistence, target_role="student_research"
        )
        self.expected_school_id = expected_school_id
        self.source_study_ref = source_study_ref
        self.source_package_ref = source_package_ref
        self.source_manifest_sha256 = source_manifest_sha256
        self.prompt_id = prompt_id
        self.prompt_version = prompt_version
        self.valid_through = valid_through.astimezone(UTC)
        self.source_cards = cards

    def _require_page(self, offset: int, limit: int) -> tuple[int, int]:
        if (
            type(offset) is not int
            or not 0 <= offset <= 100_000
            or type(limit) is not int
            or not 1 <= limit <= _PAGE_MAX
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="pagination is invalid")
        return offset, limit

    def _require_source_current(self, row=None) -> None:
        now = self._conversations._utc_now()
        current_utc = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
        if current_utc > self.valid_through or not self.source_cards:
            raise error(
                ErrorCode.WORKFLOW_CONFLICT, detail="research source is no longer available"
            )
        if row is not None and (
            row.school_id != self.expected_school_id
            or row.source_study_ref != self.source_study_ref
            or row.source_package_ref != self.source_package_ref
            or row.source_manifest_sha256 != self.source_manifest_sha256
            or row.prompt_id != self.prompt_id
            or row.prompt_version != self.prompt_version
        ):
            raise error(
                ErrorCode.WORKFLOW_CONFLICT, detail="research source binding is unavailable"
            )

    def _candidate(self, row, payload_value: object) -> IndependentEducationCandidatePayload:
        try:
            payload = IndependentEducationCandidatePayload.model_validate(
                payload_value, strict=True
            )
        except (TypeError, ValueError):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="independent education review is unavailable",
            ) from None
        provenance = payload.provenance
        if (
            provenance.source_study_ref != row.source_study_ref
            or provenance.source_package_ref != row.source_package_ref
            or provenance.source_manifest_sha256 != row.source_manifest_sha256
            or provenance.retrieval_id != row.retrieval_id
            or provenance.retrieval_bundle_sha256 != row.retrieval_bundle_sha256
            or provenance.prompt_id != row.prompt_id
            or provenance.prompt_version != row.prompt_version
            or provenance.prompt_sha256 != row.prompt_sha256
            or provenance.model_id != row.model_id
            or provenance.logical_model_id != row.logical_model_id
            or provenance.model_version != row.model_version
            or provenance.model_digest_sha256 != row.model_digest_sha256
            or provenance.runtime_version != row.runtime_version
            or provenance.trace_id != row.trace_id
            or provenance.input_safety_action != row.input_safety_action
            or provenance.input_safety_reason_codes != row.input_safety_reason_codes
            or provenance.retrieval_safety_action != row.retrieval_safety_action
            or provenance.retrieval_safety_reason_codes != row.retrieval_safety_reason_codes
            or provenance.output_safety_action != row.output_safety_action
            or provenance.output_safety_reason_codes != row.output_safety_reason_codes
            or row.purpose != "RESEARCH_SIMULATION"
            or row.research_only is not True
            or row.professional_approval is not False
            or row.clinical_approval is not False
            or row.psychometric_approval is not False
            or row.ethics_approval is not False
            or row.school_production_approval is not False
            or row.claim_boundary_status != "ACCEPTED"
            or row.citation_binding_status != "BOUND"
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="independent education review provenance is unavailable",
            )
        for card in payload.source_cards:
            current = self.source_cards.get(card.chunk_id)
            if current is None or current.model_dump(mode="python") != card.model_dump(
                mode="python"
            ):
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT,
                    detail="research source material is no longer current",
                )
        if any(citation.chunk_id not in self.source_cards for citation in payload.citations):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="independent education citations are unavailable",
            )
        return payload

    @staticmethod
    def _candidate_projection(
        candidate: IndependentEducationCandidatePayload,
    ) -> IndependentEducationCandidateProjection:
        provenance = candidate.provenance.model_dump(mode="python")
        for internal_key in (
            "generation_id",
            "input_safety_requires_human",
            "retrieval_safety_requires_human",
            "output_safety_requires_human",
        ):
            provenance.pop(internal_key, None)
        return IndependentEducationCandidateProjection.model_validate(
            {
                "schema_version": candidate.schema_version,
                "content": candidate.content.model_dump(mode="python"),
                "citations": [item.model_dump(mode="python") for item in candidate.citations],
                "source_cards": [item.model_dump(mode="python") for item in candidate.source_cards],
                "provenance": provenance,
            },
            strict=True,
        )

    @staticmethod
    def _review_ref(value: str) -> str:
        if type(value) is not str or _REVIEW_REF.fullmatch(value) is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="review was not found")
        return value

    @staticmethod
    def _reviewer_ref(value: str) -> str:
        if type(value) is not str or _REVIEWER_REF.fullmatch(value) is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="reviewer is unavailable")
        return value

    async def _student_scope(self, uow, actor, conversation_id: str, now: datetime):
        if actor.school_id != self.expected_school_id:
            raise error(ErrorCode.FORBIDDEN, detail="access denied")
        account_id, subject = await self._conversations._student_subject(uow, actor, now)
        role_account_id, role_id = await self._conversations._school_actor_role(
            uow, actor, "student", now
        )
        if role_account_id != account_id:
            raise error(ErrorCode.FORBIDDEN, detail="access denied")
        session = await self._conversations._owned_session(
            uow, actor, subject, conversation_id, lock=False
        )
        self._require_source_current()
        return account_id, role_id, subject, session

    async def _reviewer_scope(self, uow, actor, now: datetime) -> tuple[int, int]:
        if actor.school_id != self.expected_school_id:
            raise error(ErrorCode.FORBIDDEN, detail="access denied")
        return await self._conversations._school_actor_role(
            uow, actor, "psychological_specialist", now
        )

    async def _find_reviewer_role(self, uow, reviewer_ref: str, now: datetime):
        reviewer_ref = self._reviewer_ref(reviewer_ref)
        m = self._conversations._db_models
        public_id = reviewer_ref.removeprefix("ROLE_")
        rows = list(
            (
                await uow.session.execute(
                    select(m.MembershipRole, m.AccountSchoolMembership)
                    .join(
                        m.AccountSchoolMembership,
                        (m.AccountSchoolMembership.id == m.MembershipRole.membership_id)
                        & (m.AccountSchoolMembership.school_id == m.MembershipRole.school_id),
                    )
                    .join(m.Account, m.Account.id == m.AccountSchoolMembership.account_id)
                    .join(m.School, m.School.id == m.AccountSchoolMembership.school_id)
                    .where(
                        m.MembershipRole.public_id == public_id,
                        m.MembershipRole.school_id == self.expected_school_id,
                        m.MembershipRole.role_code == "psychological_specialist",
                        m.MembershipRole.status == "ACTIVE",
                        m.MembershipRole.revoked_at.is_(None),
                        m.MembershipRole.valid_from <= now,
                        (m.MembershipRole.valid_until.is_(None))
                        | (m.MembershipRole.valid_until >= now),
                        m.AccountSchoolMembership.status == "ACTIVE",
                        m.AccountSchoolMembership.revoked_at.is_(None),
                        m.AccountSchoolMembership.valid_from <= now,
                        (m.AccountSchoolMembership.valid_until.is_(None))
                        | (m.AccountSchoolMembership.valid_until >= now),
                        m.Account.status
                        == self._conversations._db_enums.AccountStatus.ACTIVE.value,
                        m.School.status == "ACTIVE",
                        m.School.data_origin
                        == self._conversations._db_enums.DataOrigin.SYNTHETIC.value,
                    )
                    .limit(2)
                    .with_for_update()
                )
            ).all()
        )
        if len(rows) != 1:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="reviewer is unavailable")
        role, membership = rows[0]
        return role, membership

    async def _locked_student_review(
        self, uow, actor, conversation_id: str, review_ref: str, now: datetime
    ):
        account_id, actor_role_id, subject, session = await self._student_scope(
            uow, actor, conversation_id, now
        )
        if uow.independent_education_reviews is None:
            raise error(ErrorCode.DEPENDENCY_UNAVAILABLE, detail="education review is unavailable")
        row = await uow.independent_education_reviews.get_for_update(
            review_ref=review_ref,
            school_id=actor.school_id,
            subject_id=subject.id,
        )
        if row is None or row.support_session_id != session.id:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="review was not found")
        self._require_source_current(row)
        return account_id, actor_role_id, subject, session, row

    async def _locked_staff_review(
        self, uow, actor, review_ref: str, now: datetime, *, allow_revoked: bool = False
    ):
        account_id, role_id = await self._reviewer_scope(uow, actor, now)
        if uow.independent_education_reviews is None:
            raise error(ErrorCode.DEPENDENCY_UNAVAILABLE, detail="education review is unavailable")
        row = await uow.independent_education_reviews.get_for_update(
            review_ref=review_ref, school_id=actor.school_id
        )
        if (
            row is None
            or row.reviewer_membership_role_id != role_id
            or row.status
            not in ({"SHARED", "DRAFT", "PUBLISHED", "REVOKED"} if allow_revoked else {
                "SHARED",
                "DRAFT",
                "PUBLISHED",
            })
        ):
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="review was not found")
        await self._require_current_owner_self(uow, row, now)
        self._require_source_current(row)
        return account_id, role_id, row

    async def _require_current_owner_self(self, uow, row, now: datetime) -> None:
        m = self._conversations._db_models
        enums = self._conversations._db_enums
        result = await uow.session.execute(
            select(m.SubjectAccessGrant.id)
            .join(
                m.Subject,
                (m.Subject.id == m.SubjectAccessGrant.subject_id)
                & (m.Subject.school_id == m.SubjectAccessGrant.school_id),
            )
            .join(m.Account, m.Account.id == m.SubjectAccessGrant.principal_account_id)
            .join(
                m.AccountSchoolMembership,
                (m.AccountSchoolMembership.account_id == m.SubjectAccessGrant.principal_account_id)
                & (m.AccountSchoolMembership.school_id == m.SubjectAccessGrant.school_id),
            )
            .join(
                m.MembershipRole,
                (m.MembershipRole.membership_id == m.AccountSchoolMembership.id)
                & (m.MembershipRole.school_id == m.AccountSchoolMembership.school_id),
            )
            .where(
                m.SubjectAccessGrant.subject_id == row.subject_id,
                m.SubjectAccessGrant.school_id == row.school_id,
                m.SubjectAccessGrant.relationship_type == "SELF",
                m.SubjectAccessGrant.status == "ACTIVE",
                m.SubjectAccessGrant.revoked_at.is_(None),
                m.SubjectAccessGrant.valid_from <= now,
                (m.SubjectAccessGrant.valid_until.is_(None))
                | (m.SubjectAccessGrant.valid_until >= now),
                m.Subject.status == enums.SubjectStatus.ACTIVE.value,
                m.Subject.data_origin == enums.DataOrigin.SYNTHETIC.value,
                m.Account.status == enums.AccountStatus.ACTIVE.value,
                m.AccountSchoolMembership.status == "ACTIVE",
                m.AccountSchoolMembership.revoked_at.is_(None),
                m.AccountSchoolMembership.valid_from <= now,
                (m.AccountSchoolMembership.valid_until.is_(None))
                | (m.AccountSchoolMembership.valid_until >= now),
                m.MembershipRole.role_code == "student",
                m.MembershipRole.status == "ACTIVE",
                m.MembershipRole.revoked_at.is_(None),
                m.MembershipRole.valid_from <= now,
                (m.MembershipRole.valid_until.is_(None))
                | (m.MembershipRole.valid_until >= now),
            )
            .limit(2)
            .with_for_update()
        )
        if len(result.all()) != 1:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="review was not found")

    def _student_summary(self, row, *, published_content=None, reviewer_public_id=None):
        return {
            "review_ref": row.review_ref,
            "status": row.status,
            "state_version": row.state_version,
            "created_at": _timestamp(row.created_at),
            "updated_at": _timestamp(row.updated_at),
            "reviewer_ref": f"ROLE_{reviewer_public_id}" if reviewer_public_id else None,
            "published_content": published_content,
        }

    @staticmethod
    def _published_content(draft: IndependentEducationDraftPayload, row) -> dict[str, Any]:
        return {
            "title": draft.title,
            "body": draft.body,
            "citations": [item.model_dump(mode="json") for item in draft.citations],
            "source_cards": [item.model_dump(mode="json") for item in draft.source_cards],
            "published_at": _timestamp(row.published_at),
        }

    async def _public_reviewer_id(self, uow, row) -> str | None:
        if row.reviewer_membership_role_id is None:
            return None
        m = self._conversations._db_models
        result = await uow.session.execute(
            select(m.MembershipRole.public_id)
            .join(
                m.AccountSchoolMembership,
                (m.AccountSchoolMembership.id == m.MembershipRole.membership_id)
                & (m.AccountSchoolMembership.school_id == m.MembershipRole.school_id),
            )
            .join(m.Account, m.Account.id == m.AccountSchoolMembership.account_id)
            .where(
                m.MembershipRole.id == row.reviewer_membership_role_id,
                m.MembershipRole.school_id == row.school_id,
                m.MembershipRole.role_code == "psychological_specialist",
                m.MembershipRole.status == "ACTIVE",
                m.MembershipRole.revoked_at.is_(None),
                m.MembershipRole.valid_from <= self._conversations._utc_now(),
                (m.MembershipRole.valid_until.is_(None))
                | (m.MembershipRole.valid_until >= self._conversations._utc_now()),
                m.AccountSchoolMembership.status == "ACTIVE",
                m.AccountSchoolMembership.revoked_at.is_(None),
                m.AccountSchoolMembership.valid_from <= self._conversations._utc_now(),
                (m.AccountSchoolMembership.valid_until.is_(None))
                | (m.AccountSchoolMembership.valid_until >= self._conversations._utc_now()),
                m.Account.status == self._conversations._db_enums.AccountStatus.ACTIVE.value,
            )
        )
        value = result.scalar_one_or_none()
        return str(value) if value else None

    async def student_list(self, actor, conversation_id: str, *, offset: int, limit: int):
        offset, limit = self._require_page(offset, limit)
        now = self._conversations._utc_now()
        async with self._conversations._uow() as uow:
            _account_id, _role_id, subject, session = await self._student_scope(
                uow, actor, conversation_id, now
            )
            repo = uow.independent_education_reviews
            rows = await repo.list_for_owner(
                school_id=actor.school_id,
                subject_id=subject.id,
                session_id=session.id,
                offset=offset,
                limit=limit,
            )
            total = await repo.count_for_owner(
                school_id=actor.school_id,
                subject_id=subject.id,
                session_id=session.id,
            )
            items = []
            for projection in rows:
                row = await repo.get(review_ref=projection["review_ref"], school_id=actor.school_id)
                if row is None:
                    raise error(
                        ErrorCode.DEPENDENCY_INVALID_RESPONSE, detail="review is unavailable"
                    )
                await self._require_current_owner_self(uow, row, now)
                self._require_source_current(row)
                published = None
                if row.status == "PUBLISHED":
                    published = await self._published_for_student(uow, row)
                items.append(
                    self._student_summary(
                        row,
                        published_content=published,
                        reviewer_public_id=await self._public_reviewer_id(uow, row),
                    )
                )
            return {
                "items": items,
                "offset": offset,
                "limit": limit,
                "total": total,
                "has_more": offset + len(items) < total,
            }

    async def student_reviewers(self, actor, conversation_id: str, *, offset: int, limit: int):
        offset, limit = self._require_page(offset, limit)
        now = self._conversations._utc_now()
        async with self._conversations._uow() as uow:
            _account_id, _role_id, _subject, _session = await self._student_scope(
                uow, actor, conversation_id, now
            )
            m = self._conversations._db_models
            query = (
                select(m.MembershipRole.public_id, m.AccountSchoolMembership.display_name)
                .join(
                    m.AccountSchoolMembership,
                    (m.AccountSchoolMembership.id == m.MembershipRole.membership_id)
                    & (m.AccountSchoolMembership.school_id == m.MembershipRole.school_id),
                )
                .join(m.Account, m.Account.id == m.AccountSchoolMembership.account_id)
                .join(m.School, m.School.id == m.AccountSchoolMembership.school_id)
                .where(
                    m.MembershipRole.school_id == actor.school_id,
                    m.MembershipRole.role_code == "psychological_specialist",
                    m.MembershipRole.status == "ACTIVE",
                    m.MembershipRole.revoked_at.is_(None),
                    m.MembershipRole.valid_from <= now,
                    (m.MembershipRole.valid_until.is_(None))
                    | (m.MembershipRole.valid_until >= now),
                    m.AccountSchoolMembership.status == "ACTIVE",
                    m.AccountSchoolMembership.revoked_at.is_(None),
                    m.AccountSchoolMembership.valid_from <= now,
                    (m.AccountSchoolMembership.valid_until.is_(None))
                    | (m.AccountSchoolMembership.valid_until >= now),
                    m.Account.status == self._conversations._db_enums.AccountStatus.ACTIVE.value,
                    m.School.status == "ACTIVE",
                    m.School.data_origin
                    == self._conversations._db_enums.DataOrigin.SYNTHETIC.value,
                )
            )
            total = int(
                await uow.session.scalar(
                    select(func.count()).select_from(query.order_by(None).subquery())
                )
                or 0
            )
            rows = (
                await uow.session.execute(
                    query.order_by(m.AccountSchoolMembership.display_name, m.MembershipRole.id)
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
            return {
                "items": [
                    {
                        "reviewer_ref": f"ROLE_{public_id}",
                        "display_name": display_name or "心理老师",
                    }
                    for public_id, display_name in rows
                ],
                "offset": offset,
                "limit": limit,
                "total": total,
                "has_more": offset + len(rows) < total,
            }

    async def _write_claim(
        self, uow, account_id: int, operation: str, review_ref: str, idempotency
    ):
        if (
            not isinstance(idempotency, tuple)
            or len(idempotency) != 2
            or not isinstance(idempotency[0], str)
            or not isinstance(idempotency[1], str)
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="idempotency key is required")
        key, request_hash = idempotency
        scope = (
            f"{account_id}:independent-education-review:{operation}:"
            f"{self.expected_school_id}:{review_ref}"
        )
        return await self._persistence._school_idempotency_begin(uow, (key, request_hash, scope))

    async def _complete_write(self, uow, claim, review_ref: str) -> None:
        if not claim.replayed:
            await self._persistence._school_idempotency_complete(
                uow,
                claim,
                resource_type="independent_education_review",
                result_ref=review_ref,
            )

    async def _load_student_review(
        self, uow, actor, conversation_id: str, review_ref: str, now: datetime
    ):
        account_id, role_id, subject, session, row = await self._locked_student_review(
            uow, actor, conversation_id, review_ref, now
        )
        candidate = self._candidate(
            row, await uow.independent_education_reviews.get_candidate_payload(row)
        )
        return account_id, role_id, subject, session, row, candidate

    async def share(
        self,
        actor,
        conversation_id: str,
        review_ref: str,
        *,
        expected_version: int,
        reviewer_ref: str,
        consent: bool,
        idempotency,
        trace_id: str,
    ):
        review_ref = self._review_ref(review_ref)
        if consent is not True:
            raise error(ErrorCode.VALIDATION_FAILED, detail="explicit sharing consent is required")
        now = self._conversations._utc_now()
        async with self._conversations._uow() as uow:
            (
                account_id,
                actor_role_id,
                _subject,
                _session,
                row,
                _candidate,
            ) = await self._load_student_review(uow, actor, conversation_id, review_ref, now)
            claim = await self._write_claim(uow, account_id, "share", review_ref, idempotency)
            if claim.replayed:
                published = await self._published_for_student(uow, row)
                return self._student_summary(
                    row,
                    published_content=published,
                    reviewer_public_id=await self._public_reviewer_id(uow, row),
                )
            role, _membership = await self._find_reviewer_role(uow, reviewer_ref, now)
            updated = await uow.independent_education_reviews.transition(
                row=row,
                expected_version=expected_version,
                to_status="SHARED",
                actor_membership_role_id=actor_role_id,
                reviewer_membership_role_id=role.id,
                trace_id=trace_id,
                now=now,
            )
            await self._complete_write(uow, claim, review_ref)
            await self._conversations._audit(
                uow,
                account_id=account_id,
                action="independent_education_review.shared",
                resource_type="independent_education_review",
                resource_ref=review_ref,
                trace_id=trace_id,
            )
            return self._student_summary(
                updated,
                reviewer_public_id=role.public_id,
            )

    async def withdraw(
        self,
        actor,
        conversation_id: str,
        review_ref: str,
        *,
        expected_version: int,
        idempotency,
        trace_id: str,
    ):
        review_ref = self._review_ref(review_ref)
        now = self._conversations._utc_now()
        async with self._conversations._uow() as uow:
            (
                account_id,
                actor_role_id,
                _subject,
                _session,
                row,
                _candidate,
            ) = await self._load_student_review(uow, actor, conversation_id, review_ref, now)
            claim = await self._write_claim(uow, account_id, "withdraw", review_ref, idempotency)
            if claim.replayed:
                published = await self._published_for_student(uow, row)
                return self._student_summary(
                    row,
                    published_content=published,
                    reviewer_public_id=await self._public_reviewer_id(uow, row),
                )
            updated = await uow.independent_education_reviews.transition(
                row=row,
                expected_version=expected_version,
                to_status="WITHDRAWN",
                actor_membership_role_id=actor_role_id,
                trace_id=trace_id,
                now=now,
            )
            await self._complete_write(uow, claim, review_ref)
            await self._conversations._audit(
                uow,
                account_id=account_id,
                action="independent_education_review.withdrawn",
                resource_type="independent_education_review",
                resource_ref=review_ref,
                trace_id=trace_id,
            )
            return self._student_summary(
                updated,
                reviewer_public_id=await self._public_reviewer_id(uow, updated),
            )

    async def _published_for_student(self, uow, row):
        if row.status != "PUBLISHED":
            return None
        if await self._public_reviewer_id(uow, row) is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="review was not found")
        repo = uow.independent_education_reviews
        candidate = self._candidate(row, await repo.get_candidate_payload(row))
        payload = await repo.get_reviewed_payload(row)
        try:
            draft = IndependentEducationDraftPayload.model_validate(payload, strict=True)
        except (TypeError, ValueError):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE, detail="review is unavailable"
            ) from None
        if (
            draft.candidate_content_sha256 != row.candidate_content_sha256
            or draft.source_manifest_sha256 != row.source_manifest_sha256
            or [item.model_dump(mode="python") for item in draft.citations]
            != [item.model_dump(mode="python") for item in candidate.citations]
            or [item.model_dump(mode="python") for item in draft.source_cards]
            != [item.model_dump(mode="python") for item in candidate.source_cards]
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE, detail="review is unavailable"
            )
        return self._published_content(draft, row)

    async def _published_for_staff(self, uow, row):
        """Return only a decryptable published draft still bound to its candidate."""
        if row.status != "PUBLISHED":
            return None
        repo = uow.independent_education_reviews
        candidate = self._candidate(row, await repo.get_candidate_payload(row))
        payload = await repo.get_reviewed_payload(row)
        try:
            draft = IndependentEducationDraftPayload.model_validate(payload, strict=True)
        except (TypeError, ValueError):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE, detail="review is unavailable"
            ) from None
        if (
            draft.candidate_content_sha256 != row.candidate_content_sha256
            or draft.source_manifest_sha256 != row.source_manifest_sha256
            or [item.model_dump(mode="python") for item in draft.citations]
            != [item.model_dump(mode="python") for item in candidate.citations]
            or [item.model_dump(mode="python") for item in draft.source_cards]
            != [item.model_dump(mode="python") for item in candidate.source_cards]
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE, detail="review is unavailable"
            )
        return self._published_content(draft, row)

    async def staff_list(self, actor, *, offset: int, limit: int):
        offset, limit = self._require_page(offset, limit)
        now = self._conversations._utc_now()
        async with self._conversations._uow() as uow:
            account_id, role_id = await self._reviewer_scope(uow, actor, now)
            repo = uow.independent_education_reviews
            rows = await repo.list_for_reviewer(
                school_id=actor.school_id,
                reviewer_membership_role_id=role_id,
                offset=offset,
                limit=limit,
            )
            total = await repo.count_for_reviewer(
                school_id=actor.school_id,
                reviewer_membership_role_id=role_id,
            )
            items = []
            for projection in rows:
                row = await repo.get(review_ref=projection["review_ref"], school_id=actor.school_id)
                if row is None:
                    raise error(
                        ErrorCode.DEPENDENCY_INVALID_RESPONSE, detail="review is unavailable"
                    )
                await self._require_current_owner_self(uow, row, now)
                self._require_source_current(row)
                items.append(
                    {
                        "review_ref": row.review_ref,
                        "status": row.status,
                        "state_version": row.state_version,
                        "created_at": _timestamp(row.created_at),
                        "updated_at": _timestamp(row.updated_at),
                    }
                )
            return {
                "items": items,
                "offset": offset,
                "limit": limit,
                "total": total,
                "has_more": offset + len(items) < total,
            }

    async def staff_detail(self, actor, review_ref: str):
        review_ref = self._review_ref(review_ref)
        now = self._conversations._utc_now()
        async with self._conversations._uow() as uow:
            _account_id, _role_id, row = await self._locked_staff_review(
                uow, actor, review_ref, now
            )
            repo = uow.independent_education_reviews
            candidate = self._candidate(row, await repo.get_candidate_payload(row))
            reviewed = await repo.get_reviewed_payload(row)
            draft = None
            if reviewed is not None:
                try:
                    draft_model = IndependentEducationDraftPayload.model_validate(
                        reviewed, strict=True
                    )
                except (TypeError, ValueError):
                    raise error(
                        ErrorCode.DEPENDENCY_INVALID_RESPONSE, detail="review is unavailable"
                    ) from None
                if (
                    draft_model.candidate_content_sha256 != row.candidate_content_sha256
                    or draft_model.source_manifest_sha256 != row.source_manifest_sha256
                    or [item.model_dump(mode="python") for item in draft_model.citations]
                    != [item.model_dump(mode="python") for item in candidate.citations]
                    or [item.model_dump(mode="python") for item in draft_model.source_cards]
                    != [item.model_dump(mode="python") for item in candidate.source_cards]
                ):
                    raise error(
                        ErrorCode.DEPENDENCY_INVALID_RESPONSE, detail="review is unavailable"
                    )
                draft = {
                    "title": draft_model.title,
                    "body": draft_model.body,
                    "content_revision": row.content_revision,
                    "citations": [item.model_dump(mode="json") for item in draft_model.citations],
                    "source_cards": [
                        item.model_dump(mode="json") for item in draft_model.source_cards
                    ],
                    "updated_at": _timestamp(row.reviewed_at),
                }
            return {
                "review_ref": row.review_ref,
                "status": row.status,
                "state_version": row.state_version,
                "created_at": _timestamp(row.created_at),
                "updated_at": _timestamp(row.updated_at),
                "shared_at": _timestamp(row.shared_at),
                "candidate": self._candidate_projection(candidate).model_dump(mode="json"),
                "reviewed_draft": draft,
            }

    async def save_draft(
        self,
        actor,
        review_ref: str,
        *,
        expected_version: int,
        title: str,
        body: str,
        idempotency,
        trace_id: str,
    ):
        review_ref = self._review_ref(review_ref)
        now = self._conversations._utc_now()
        async with self._conversations._uow() as uow:
            account_id, role_id, row = await self._locked_staff_review(uow, actor, review_ref, now)
            claim = await self._write_claim(uow, account_id, "draft", review_ref, idempotency)
            if claim.replayed:
                return {
                    "review_ref": row.review_ref,
                    "status": row.status,
                    "state_version": row.state_version,
                    "created_at": _timestamp(row.created_at),
                    "updated_at": _timestamp(row.updated_at),
                    "reviewer_ref": None,
                    "published_content": await self._published_for_staff(uow, row),
                }
            candidate = self._candidate(
                row, await uow.independent_education_reviews.get_candidate_payload(row)
            )
            draft = IndependentEducationDraftPayload(
                schema_version="independent-research-education-reviewed-draft.v1",
                title=title,
                body=body,
                citations=candidate.citations,
                source_cards=candidate.source_cards,
                candidate_content_sha256=row.candidate_content_sha256,
                source_manifest_sha256=row.source_manifest_sha256,
            )
            updated = await uow.independent_education_reviews.transition(
                row=row,
                expected_version=expected_version,
                to_status="DRAFT",
                actor_membership_role_id=role_id,
                reviewer_membership_role_id=role_id,
                trace_id=trace_id,
                now=now,
                reviewed_payload=draft.model_dump(mode="json"),
            )
            await self._complete_write(uow, claim, review_ref)
            await self._conversations._audit(
                uow,
                account_id=account_id,
                action="independent_education_review.draft_saved",
                resource_type="independent_education_review",
                resource_ref=review_ref,
                trace_id=trace_id,
            )
            return {
                "review_ref": updated.review_ref,
                "status": updated.status,
                "state_version": updated.state_version,
                "created_at": _timestamp(updated.created_at),
                "updated_at": _timestamp(updated.updated_at),
                "reviewer_ref": None,
                "published_content": None,
            }

    async def publish(
        self,
        actor,
        review_ref: str,
        *,
        expected_version: int,
        safety_material_sha256: str | None = None,
        publish_safety_check: Mapping[str, object] | None = None,
        idempotency,
        trace_id: str,
    ):
        review_ref = self._review_ref(review_ref)
        now = self._conversations._utc_now()
        async with self._conversations._uow() as uow:
            account_id, role_id, row = await self._locked_staff_review(uow, actor, review_ref, now)
            claim = await self._write_claim(uow, account_id, "publish", review_ref, idempotency)
            if claim.replayed:
                published = await self._published_for_staff(uow, row)
                return {
                    "review_ref": row.review_ref,
                    "status": row.status,
                    "state_version": row.state_version,
                    "created_at": _timestamp(row.created_at),
                    "updated_at": _timestamp(row.updated_at),
                    "reviewer_ref": None,
                    "published_content": published,
                }
            candidate = self._candidate(
                row, await uow.independent_education_reviews.get_candidate_payload(row)
            )
            draft_value = await uow.independent_education_reviews.get_reviewed_payload(row)
            try:
                draft = IndependentEducationDraftPayload.model_validate(draft_value, strict=True)
            except (TypeError, ValueError):
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT, detail="a reviewed draft is required"
                ) from None
            if (
                draft.candidate_content_sha256 != row.candidate_content_sha256
                or draft.source_manifest_sha256 != row.source_manifest_sha256
                or [item.model_dump(mode="python") for item in draft.citations]
                != [item.model_dump(mode="python") for item in candidate.citations]
                or [item.model_dump(mode="python") for item in draft.source_cards]
                != [item.model_dump(mode="python") for item in candidate.source_cards]
            ):
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT, detail="reviewed source binding is unavailable"
                )
            public_candidate = self._candidate_projection(candidate).model_dump(mode="json")
            public_draft = {
                "title": draft.title,
                "body": draft.body,
                "content_revision": row.content_revision,
                "citations": [item.model_dump(mode="json") for item in draft.citations],
                "source_cards": [
                    item.model_dump(mode="json") for item in draft.source_cards
                ],
                "updated_at": _timestamp(row.reviewed_at),
            }
            current_material_sha256 = publish_material_sha256(public_candidate, public_draft)
            if safety_material_sha256 != current_material_sha256:
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT,
                    detail="reviewed content changed during Output Safety check",
                )
            try:
                safety_receipt = IndependentEducationPublishSafetyCheck.model_validate(
                    publish_safety_check, strict=True
                )
            except (TypeError, ValueError):
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT,
                    detail="reviewed Output Safety receipt is unavailable",
                ) from None
            if (
                safety_receipt.trace_id != trace_id
                or safety_receipt.checked_material_sha256 != current_material_sha256
                or safety_receipt.requires_human is not False
            ):
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT,
                    detail="reviewed Output Safety receipt is unavailable",
                )
            payload_for_publish = draft.model_dump(mode="json")
            payload_for_publish["publish_safety_check"] = safety_receipt.model_dump(mode="json")
            updated = await uow.independent_education_reviews.transition(
                row=row,
                expected_version=expected_version,
                to_status="PUBLISHED",
                actor_membership_role_id=role_id,
                reviewer_membership_role_id=role_id,
                trace_id=trace_id,
                now=now,
                reviewed_payload=payload_for_publish,
            )
            await self._complete_write(uow, claim, review_ref)
            await self._conversations._audit(
                uow,
                account_id=account_id,
                action="independent_education_review.published",
                resource_type="independent_education_review",
                resource_ref=review_ref,
                trace_id=trace_id,
            )
            published = self._published_content(draft, updated)
            return {
                "review_ref": updated.review_ref,
                "status": updated.status,
                "state_version": updated.state_version,
                "created_at": _timestamp(updated.created_at),
                "updated_at": _timestamp(updated.updated_at),
                "reviewer_ref": None,
                "published_content": published,
            }

    async def revoke(
        self, actor, review_ref: str, *, expected_version: int, idempotency, trace_id: str
    ):
        review_ref = self._review_ref(review_ref)
        now = self._conversations._utc_now()
        async with self._conversations._uow() as uow:
            account_id, role_id, row = await self._locked_staff_review(
                uow, actor, review_ref, now, allow_revoked=True
            )
            claim = await self._write_claim(uow, account_id, "revoke", review_ref, idempotency)
            if claim.replayed:
                return {
                    "review_ref": row.review_ref,
                    "status": row.status,
                    "state_version": row.state_version,
                    "created_at": _timestamp(row.created_at),
                    "updated_at": _timestamp(row.updated_at),
                    "reviewer_ref": None,
                    "published_content": None,
                }
            updated = await uow.independent_education_reviews.transition(
                row=row,
                expected_version=expected_version,
                to_status="REVOKED",
                actor_membership_role_id=role_id,
                reviewer_membership_role_id=role_id,
                trace_id=trace_id,
                now=now,
            )
            await self._complete_write(uow, claim, review_ref)
            await self._conversations._audit(
                uow,
                account_id=account_id,
                action="independent_education_review.revoked",
                resource_type="independent_education_review",
                resource_ref=review_ref,
                trace_id=trace_id,
            )
            return {
                "review_ref": updated.review_ref,
                "status": updated.status,
                "state_version": updated.state_version,
                "created_at": _timestamp(updated.created_at),
                "updated_at": _timestamp(updated.updated_at),
                "reviewer_ref": None,
                "published_content": None,
            }
