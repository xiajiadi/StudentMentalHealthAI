"""Encrypted, per-candidate consent and release persistence for research chats."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .crypto import FernetDataProtectionProvider
from .models import (
    SchoolIndependentEducationReview,
    SchoolIndependentEducationReviewEvent,
)

_REF = re.compile(r"^EDUREV_[0-9a-f]{32}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_REASONS = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_MAX_ENCRYPTED_PAYLOAD_BYTES = 1_000_000
_CANDIDATE_SCHEMA = "independent-research-education-candidate.v1"
_DRAFT_SCHEMA = "independent-research-education-reviewed-draft.v1"
CONSENT_NOTICE_VERSION = "independent-education-share.v1"
_INITIAL_STATUS = "HELD"
_CANDIDATE_FIELDS = frozenset(
    {"schema_version", "content", "citations", "source_cards", "provenance"}
)
_PROVENANCE_FIELDS = frozenset(
    {
        "purpose",
        "research_only",
        "source_study_ref",
        "source_package_ref",
        "source_manifest_sha256",
        "retrieval_id",
        "retrieval_bundle_sha256",
        "generation_id",
        "prompt_id",
        "prompt_version",
        "prompt_sha256",
        "model_id",
        "logical_model_id",
        "model_version",
        "model_digest_sha256",
        "runtime_version",
        "trace_id",
        "input_safety_action",
        "input_safety_reason_codes",
        "input_safety_requires_human",
        "retrieval_safety_action",
        "retrieval_safety_reason_codes",
        "retrieval_safety_requires_human",
        "output_safety_action",
        "output_safety_reason_codes",
        "output_safety_requires_human",
        "claim_boundary_status",
        "citation_binding_status",
    }
)
_TRANSITIONS = {
    "HELD": frozenset({"SHARED", "WITHDRAWN"}),
    "SHARED": frozenset({"DRAFT", "WITHDRAWN"}),
    "DRAFT": frozenset({"DRAFT", "PUBLISHED", "WITHDRAWN"}),
    "PUBLISHED": frozenset({"REVOKED", "WITHDRAWN"}),
    "REVOKED": frozenset({"WITHDRAWN"}),
    "WITHDRAWN": frozenset(),
}


class IndependentEducationReviewError(ValueError):
    """Closed persistence failure; never includes payload or credential values."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _utc_naive(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise IndependentEducationReviewError("INVALID_TIMESTAMP")
    # DatabaseLayer's trusted business clock already returns naive UTC for
    # MySQL DATETIME(6). Accept it unchanged; normalize aware server clocks.
    if value.tzinfo is None:
        return value
    if value.utcoffset() is None:
        raise IndependentEducationReviewError("INVALID_TIMESTAMP")
    return value.astimezone(UTC).replace(tzinfo=None)


def _canonical_json(value: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(
            dict(value), ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise IndependentEducationReviewError("INVALID_PAYLOAD") from exc


def _validate_provenance(provenance: Mapping[str, object]) -> None:
    if set(provenance) != _PROVENANCE_FIELDS:
        raise IndependentEducationReviewError("INVALID_PROVENANCE")
    required_tokens = (
        "source_study_ref",
        "source_package_ref",
        "retrieval_id",
        "prompt_id",
        "prompt_version",
        "model_id",
        "logical_model_id",
        "model_version",
        "runtime_version",
        "trace_id",
    )
    if any(
        not isinstance(provenance.get(name), str) or _TOKEN.fullmatch(provenance[name]) is None
        for name in required_tokens
    ):
        raise IndependentEducationReviewError("INVALID_PROVENANCE")
    for name in ("source_manifest_sha256", "retrieval_bundle_sha256", "model_digest_sha256"):
        value = provenance.get(name)
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise IndependentEducationReviewError("INVALID_PROVENANCE")
    prompt_sha = provenance.get("prompt_sha256")
    if prompt_sha is not None and (
        not isinstance(prompt_sha, str) or _SHA256.fullmatch(prompt_sha) is None
    ):
        raise IndependentEducationReviewError("INVALID_PROVENANCE")
    if (
        provenance.get("purpose") != "RESEARCH_SIMULATION"
        or provenance.get("research_only") is not True
    ):
        raise IndependentEducationReviewError("INVALID_PROVENANCE")
    if provenance.get("claim_boundary_status") != "ACCEPTED":
        raise IndependentEducationReviewError("INVALID_PROVENANCE")
    if provenance.get("citation_binding_status") != "BOUND":
        raise IndependentEducationReviewError("INVALID_PROVENANCE")
    if any(
        provenance.get(field) is not False
        for field in (
            "input_safety_requires_human",
            "retrieval_safety_requires_human",
            "output_safety_requires_human",
        )
    ):
        raise IndependentEducationReviewError("UNSAFE_CANDIDATE")
    for stage in ("input", "retrieval", "output"):
        action = provenance.get(f"{stage}_safety_action")
        reasons = provenance.get(f"{stage}_safety_reason_codes")
        if action not in {"PROCEED", "PROCEED_WITH_BOUNDARY"}:
            raise IndependentEducationReviewError("UNSAFE_CANDIDATE")
        if (
            not isinstance(reasons, list)
            or not reasons
            or len(reasons) > 16
            or len(set(reasons)) != len(reasons)
            or any(
                not isinstance(item, str) or _REASONS.fullmatch(item) is None for item in reasons
            )
        ):
            raise IndependentEducationReviewError("INVALID_PROVENANCE")


def _validate_publish_safety_receipt(value: object, *, trace_id: str) -> None:
    allowed_fields = {
        "operation",
        "action",
        "reason_codes",
        "requires_human",
        "decision_id",
        "trace_id",
        "checked_material_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != allowed_fields:
        raise IndependentEducationReviewError("PUBLISH_SAFETY_RECEIPT_REQUIRED")
    reasons = value.get("reason_codes")
    decision_id = value.get("decision_id")
    if (
        value.get("operation") != "OUTPUT"
        or value.get("action") not in {"PROCEED", "PROCEED_WITH_BOUNDARY"}
        or value.get("requires_human") is not False
        or value.get("trace_id") != trace_id
        or not isinstance(value.get("checked_material_sha256"), str)
        or _SHA256.fullmatch(value["checked_material_sha256"]) is None
        or not isinstance(reasons, list)
        or not 1 <= len(reasons) <= 16
        or any(not isinstance(item, str) or _REASONS.fullmatch(item) is None for item in reasons)
        or len(set(reasons)) != len(reasons)
        or (
            decision_id is not None
            and (
                not isinstance(decision_id, str)
                or _TOKEN.fullmatch(decision_id) is None
            )
        )
    ):
        raise IndependentEducationReviewError("PUBLISH_SAFETY_RECEIPT_INVALID")


class SchoolIndependentEducationReviewRepository:
    """Caller-owned UOW repository for the isolated review resource."""

    def __init__(self, session: AsyncSession, protection: FernetDataProtectionProvider) -> None:
        self.session = session
        self.protection = protection

    async def create_held(
        self,
        *,
        review_ref: str,
        school_id: int,
        subject_id: int,
        support_session_id: int,
        support_run_id: int,
        candidate_payload: Mapping[str, object],
        provenance: Mapping[str, object],
        actor_membership_role_id: int,
        trace_id: str,
        retention_due_at: datetime | None,
        now: datetime,
    ) -> SchoolIndependentEducationReview:
        if not isinstance(review_ref, str) or _REF.fullmatch(review_ref) is None:
            raise IndependentEducationReviewError("INVALID_REVIEW_REF")
        if (
            set(candidate_payload) != _CANDIDATE_FIELDS
            or candidate_payload.get("schema_version") != _CANDIDATE_SCHEMA
            or not isinstance(candidate_payload.get("provenance"), Mapping)
        ):
            raise IndependentEducationReviewError("INVALID_CANDIDATE_SCHEMA")
        _validate_provenance(provenance)
        serialized = _canonical_json(candidate_payload)
        if len(serialized) > _MAX_ENCRYPTED_PAYLOAD_BYTES:
            raise IndependentEducationReviewError("CANDIDATE_TOO_LARGE")
        protected = self.protection.encrypt_json(
            candidate_payload, payload_schema_version=_CANDIDATE_SCHEMA
        )
        if len(protected.ciphertext) > _MAX_ENCRYPTED_PAYLOAD_BYTES:
            raise IndependentEducationReviewError("CANDIDATE_TOO_LARGE")
        clock = _utc_naive(now)
        record = SchoolIndependentEducationReview(
            review_ref=review_ref,
            school_id=school_id,
            subject_id=subject_id,
            support_session_id=support_session_id,
            support_run_id=support_run_id,
            reviewer_membership_role_id=None,
            status=_INITIAL_STATUS,
            state_version=1,
            purpose="RESEARCH_SIMULATION",
            research_only=True,
            professional_approval=False,
            clinical_approval=False,
            psychometric_approval=False,
            ethics_approval=False,
            school_production_approval=False,
            source_study_ref=provenance["source_study_ref"],
            source_package_ref=provenance["source_package_ref"],
            source_manifest_sha256=provenance["source_manifest_sha256"],
            retrieval_id=provenance["retrieval_id"],
            retrieval_bundle_sha256=provenance["retrieval_bundle_sha256"],
            prompt_id=provenance["prompt_id"],
            prompt_version=provenance["prompt_version"],
            prompt_sha256=provenance["prompt_sha256"],
            model_id=provenance["model_id"],
            logical_model_id=provenance["logical_model_id"],
            model_version=provenance["model_version"],
            model_digest_sha256=provenance["model_digest_sha256"],
            runtime_version=provenance["runtime_version"],
            trace_id=trace_id,
            input_safety_action=provenance["input_safety_action"],
            input_safety_reason_codes=provenance["input_safety_reason_codes"],
            retrieval_safety_action=provenance["retrieval_safety_action"],
            retrieval_safety_reason_codes=provenance["retrieval_safety_reason_codes"],
            output_safety_action=provenance["output_safety_action"],
            output_safety_reason_codes=provenance["output_safety_reason_codes"],
            claim_boundary_status="ACCEPTED",
            citation_binding_status="BOUND",
            candidate_content_sha256=hashlib.sha256(serialized).hexdigest(),
            candidate_payload_ciphertext=protected.ciphertext,
            candidate_cipher_format_version=protected.cipher_format_version,
            candidate_key_version=protected.key_version,
            candidate_payload_schema_version=protected.payload_schema_version,
            content_revision=0,
            reviewed_at=None,
            shared_at=None,
            published_at=None,
            revoked_at=None,
            withdrawn_at=None,
            retention_due_at=retention_due_at,
            created_at=clock,
            updated_at=clock,
        )
        self.session.add(record)
        await self.session.flush()
        self.session.add(
            SchoolIndependentEducationReviewEvent(
                review_id=record.id,
                school_id=school_id,
                actor_membership_role_id=actor_membership_role_id,
                event_type="CREATED",
                from_status=None,
                to_status="HELD",
                state_version=1,
                trace_id=trace_id,
                retention_due_at=retention_due_at,
                created_at=clock,
            )
        )
        await self.session.flush()
        return record

    async def get_for_update(
        self, *, review_ref: str, school_id: int, subject_id: int | None = None
    ) -> SchoolIndependentEducationReview | None:
        statement = select(SchoolIndependentEducationReview).where(
            SchoolIndependentEducationReview.review_ref == review_ref,
            SchoolIndependentEducationReview.school_id == school_id,
        )
        if subject_id is not None:
            statement = statement.where(SchoolIndependentEducationReview.subject_id == subject_id)
        return await self.session.scalar(statement.with_for_update())

    async def get(self, *, review_ref: str, school_id: int, lock: bool = False):
        if not isinstance(review_ref, str) or _REF.fullmatch(review_ref) is None:
            return None
        statement = select(SchoolIndependentEducationReview).where(
            SchoolIndependentEducationReview.review_ref == review_ref,
            SchoolIndependentEducationReview.school_id == school_id,
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def list_for_owner(
        self, *, school_id: int, subject_id: int, session_id: int, offset: int, limit: int
    ) -> tuple[dict[str, object], ...]:
        rows = (
            (
                await self.session.execute(
                    select(
                        SchoolIndependentEducationReview.id,
                        SchoolIndependentEducationReview.review_ref,
                        SchoolIndependentEducationReview.school_id,
                        SchoolIndependentEducationReview.subject_id,
                        SchoolIndependentEducationReview.support_session_id,
                        SchoolIndependentEducationReview.status,
                        SchoolIndependentEducationReview.state_version,
                        SchoolIndependentEducationReview.created_at,
                        SchoolIndependentEducationReview.updated_at,
                        SchoolIndependentEducationReview.reviewer_membership_role_id,
                        SchoolIndependentEducationReview.shared_at,
                        SchoolIndependentEducationReview.published_at,
                    )
                    .where(
                        SchoolIndependentEducationReview.school_id == school_id,
                        SchoolIndependentEducationReview.subject_id == subject_id,
                        SchoolIndependentEducationReview.support_session_id == session_id,
                    )
                    .order_by(
                        SchoolIndependentEducationReview.created_at.desc(),
                        SchoolIndependentEducationReview.id.desc(),
                    )
                    .offset(offset)
                    .limit(limit)
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(row) for row in rows)

    async def count_for_owner(self, *, school_id: int, subject_id: int, session_id: int) -> int:
        count = await self.session.scalar(
            select(func.count(SchoolIndependentEducationReview.id)).where(
                SchoolIndependentEducationReview.school_id == school_id,
                SchoolIndependentEducationReview.subject_id == subject_id,
                SchoolIndependentEducationReview.support_session_id == session_id,
            )
        )
        return int(count or 0)

    async def list_for_reviewer(
        self, *, school_id: int, reviewer_membership_role_id: int, offset: int, limit: int
    ) -> tuple[dict[str, object], ...]:
        rows = (
            (
                await self.session.execute(
                    select(
                        SchoolIndependentEducationReview.id,
                        SchoolIndependentEducationReview.review_ref,
                        SchoolIndependentEducationReview.school_id,
                        SchoolIndependentEducationReview.status,
                        SchoolIndependentEducationReview.state_version,
                        SchoolIndependentEducationReview.created_at,
                        SchoolIndependentEducationReview.updated_at,
                    )
                    .where(
                        SchoolIndependentEducationReview.school_id == school_id,
                        SchoolIndependentEducationReview.reviewer_membership_role_id
                        == reviewer_membership_role_id,
                        SchoolIndependentEducationReview.status.in_(
                            ("SHARED", "DRAFT", "PUBLISHED")
                        ),
                    )
                    .order_by(
                        SchoolIndependentEducationReview.updated_at.desc(),
                        SchoolIndependentEducationReview.id.desc(),
                    )
                    .offset(offset)
                    .limit(limit)
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(row) for row in rows)

    async def count_for_reviewer(self, *, school_id: int, reviewer_membership_role_id: int) -> int:
        count = await self.session.scalar(
            select(func.count(SchoolIndependentEducationReview.id)).where(
                SchoolIndependentEducationReview.school_id == school_id,
                SchoolIndependentEducationReview.reviewer_membership_role_id
                == reviewer_membership_role_id,
                SchoolIndependentEducationReview.status.in_(("SHARED", "DRAFT", "PUBLISHED")),
            )
        )
        return int(count or 0)

    async def get_candidate_payload(
        self, row: SchoolIndependentEducationReview
    ) -> dict[str, object]:
        payload = self.protection.decrypt_json(
            self._encrypted(
                row.candidate_payload_ciphertext,
                row.candidate_cipher_format_version,
                row.candidate_key_version,
                row.candidate_payload_schema_version,
            )
        )
        if (
            not isinstance(payload, Mapping)
            or payload.get("schema_version") != _CANDIDATE_SCHEMA
            or hashlib.sha256(_canonical_json(payload)).hexdigest() != row.candidate_content_sha256
        ):
            raise IndependentEducationReviewError("CANDIDATE_ENVELOPE_INVALID")
        return dict(payload)

    async def get_reviewed_payload(
        self, row: SchoolIndependentEducationReview
    ) -> dict[str, object] | None:
        if row.reviewed_payload_ciphertext is None:
            return None
        payload = self.protection.decrypt_json(
            self._encrypted(
                row.reviewed_payload_ciphertext,
                row.reviewed_cipher_format_version,
                row.reviewed_key_version,
                row.reviewed_payload_schema_version,
            )
        )
        if (
            not isinstance(payload, Mapping)
            or payload.get("schema_version") != _DRAFT_SCHEMA
            or not isinstance(row.reviewed_content_sha256, str)
            or hashlib.sha256(_canonical_json(payload)).hexdigest() != row.reviewed_content_sha256
        ):
            raise IndependentEducationReviewError("REVIEWED_ENVELOPE_INVALID")
        return dict(payload)

    @staticmethod
    def _encrypted(ciphertext, cipher_format_version, key_version, payload_schema_version):
        from .crypto import EncryptedPayload

        if not all(
            isinstance(value, str) and value
            for value in (cipher_format_version, key_version, payload_schema_version)
        ):
            raise IndependentEducationReviewError("CIPHER_ENVELOPE_INVALID")
        return EncryptedPayload(
            ciphertext=ciphertext,
            cipher_format_version=cipher_format_version,
            key_version=key_version,
            payload_schema_version=payload_schema_version,
        )

    async def transition(
        self,
        *,
        row: SchoolIndependentEducationReview,
        expected_version: int,
        to_status: str,
        actor_membership_role_id: int,
        trace_id: str,
        now: datetime,
        reviewer_membership_role_id: int | None = None,
        reviewed_payload: Mapping[str, object] | None = None,
    ) -> SchoolIndependentEducationReview:
        allowed = _TRANSITIONS.get(row.status, frozenset())
        same_status_draft = row.status == "DRAFT" and to_status == "DRAFT"
        if (
            row.state_version != expected_version
            or to_status not in allowed
            and not same_status_draft
        ):
            raise IndependentEducationReviewError("STALE_OR_INVALID_TRANSITION")
        clock = _utc_naive(now)
        from_status = row.status
        next_version = row.state_version + 1
        if to_status == "SHARED":
            if reviewer_membership_role_id is None:
                raise IndependentEducationReviewError("REVIEWER_REQUIRED")
            row.reviewer_membership_role_id = reviewer_membership_role_id
            row.consent_notice_version = CONSENT_NOTICE_VERSION
            row.shared_at = clock
        elif to_status == "DRAFT":
            if reviewer_membership_role_id != row.reviewer_membership_role_id:
                raise IndependentEducationReviewError("REVIEWER_SCOPE_MISMATCH")
            if (
                not isinstance(reviewed_payload, Mapping)
                or reviewed_payload.get("schema_version") != _DRAFT_SCHEMA
            ):
                raise IndependentEducationReviewError("INVALID_REVIEWED_DRAFT")
            serialized = _canonical_json(reviewed_payload)
            if len(serialized) > _MAX_ENCRYPTED_PAYLOAD_BYTES:
                raise IndependentEducationReviewError("REVIEWED_DRAFT_TOO_LARGE")
            protected = self.protection.encrypt_json(
                reviewed_payload, payload_schema_version=_DRAFT_SCHEMA
            )
            if len(protected.ciphertext) > _MAX_ENCRYPTED_PAYLOAD_BYTES:
                raise IndependentEducationReviewError("REVIEWED_DRAFT_TOO_LARGE")
            row.reviewed_content_sha256 = hashlib.sha256(serialized).hexdigest()
            row.reviewed_payload_ciphertext = protected.ciphertext
            row.reviewed_cipher_format_version = protected.cipher_format_version
            row.reviewed_key_version = protected.key_version
            row.reviewed_payload_schema_version = protected.payload_schema_version
            row.content_revision += 1
            row.reviewed_at = clock
        elif to_status == "PUBLISHED":
            if row.reviewed_payload_ciphertext is None or row.content_revision < 1:
                raise IndependentEducationReviewError("REVIEWED_DRAFT_REQUIRED")
            if not isinstance(reviewed_payload, Mapping) or reviewed_payload.get(
                "schema_version"
            ) != _DRAFT_SCHEMA:
                raise IndependentEducationReviewError("PUBLISH_SAFETY_RECEIPT_REQUIRED")
            _validate_publish_safety_receipt(
                reviewed_payload.get("publish_safety_check"), trace_id=trace_id
            )
            serialized = _canonical_json(reviewed_payload)
            if len(serialized) > _MAX_ENCRYPTED_PAYLOAD_BYTES:
                raise IndependentEducationReviewError("REVIEWED_DRAFT_TOO_LARGE")
            protected = self.protection.encrypt_json(
                reviewed_payload, payload_schema_version=_DRAFT_SCHEMA
            )
            if len(protected.ciphertext) > _MAX_ENCRYPTED_PAYLOAD_BYTES:
                raise IndependentEducationReviewError("REVIEWED_DRAFT_TOO_LARGE")
            row.reviewed_content_sha256 = hashlib.sha256(serialized).hexdigest()
            row.reviewed_payload_ciphertext = protected.ciphertext
            row.reviewed_cipher_format_version = protected.cipher_format_version
            row.reviewed_key_version = protected.key_version
            row.reviewed_payload_schema_version = protected.payload_schema_version
            row.published_at = clock
        elif to_status == "REVOKED":
            if row.status != "PUBLISHED":
                raise IndependentEducationReviewError("PUBLISHED_CONTENT_REQUIRED")
            row.revoked_at = clock
        elif to_status == "WITHDRAWN":
            row.withdrawn_at = clock
        row.status = to_status
        row.state_version = next_version
        row.updated_at = clock
        await self.session.flush()
        self.session.add(
            SchoolIndependentEducationReviewEvent(
                review_id=row.id,
                school_id=row.school_id,
                actor_membership_role_id=actor_membership_role_id,
                event_type={
                    "SHARED": "SHARED",
                    "DRAFT": "DRAFT_SAVED",
                    "PUBLISHED": "PUBLISHED",
                    "REVOKED": "REVOKED",
                    "WITHDRAWN": "WITHDRAWN",
                }[to_status],
                from_status=from_status,
                to_status=to_status,
                state_version=next_version,
                trace_id=trace_id,
                retention_due_at=row.retention_due_at,
                created_at=clock,
            )
        )
        await self.session.flush()
        return row
