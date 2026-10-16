"""Tenant-scoped persistence for independent student education-support conversations.

This adapter deliberately uses the nullable-assessment support tables directly through
the existing database unit of work. It does not enter the assessment-bound workflow.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from smhai_backend.core.errors import BackendError, ErrorCode, error
from smhai_backend.core.idempotency import fingerprint
from smhai_backend.core.request_context import get_request_context
from smhai_backend.domains.school_conversation_safety.contracts import SafetyCaseSeed

_IDEMPOTENCY_KEY_MAX = 200
_MESSAGE_MAX = 20_000
_PAGE_MAX = 50
_TURN_MAX_AGE = timedelta(seconds=120)
_SAFETY_METADATA_POLICY_VERSION = "safety-port-unversioned.v1"
_TURN_FAILURE_ACTIONS = frozenset(
    {"DEPENDENCY_FAILURE", "INVALID_OUTPUT", "CLAIM_REJECTED", "INTERRUPTED"}
)
_CITATION_COLUMN_LIMITS = {
    "citation_id": 128,
    "source_id": 128,
    "chunk_id": 128,
    "document_id": 128,
    "source_version": 64,
    "source_hash": 128,
    "title": 512,
    "organization": 512,
    "locator": 512,
}
_SAFE_COMPONENT_KEYS = frozenset(
    {
        "abstention_reason_code",
        "attempt_count",
        "claim_boundary_status",
        "claim_boundary_category",
        "claim_boundary_field_kind",
        "dependency_error_code",
        "diagnostic_reason_code",
        "evidence_count",
        "failure_code",
        "generation_id",
        "input_safety_action",
        "model_id",
        "model_version",
        "output_safety_action",
        "prompt_id",
        "prompt_version",
        "retrieval_id",
        "retrieval_safety_action",
        "source_query_transform",
        "source_layers_hit",
        "source_layers_missing",
        "runtime_version",
        "stage",
        "conversation_lane",
        "consumer_age_min",
        "consumer_age_max",
        "consumer_population",
        "engineering_review_status",
        "reviewer_kind",
        "human_curated",
        "professional_approval",
        "ethics_approval",
        "clinical_approval",
        "psychometric_approval",
        "publication_eligible",
        "production_use",
        "package_id",
        "purpose",
        "source_manifest_sha256",
        "source_rights_status",
        "source_review_status",
        "source_policy_expires_at",
        "study_ref",
    }
)
_SAFE_DEPENDENCY_ERROR_CODES = frozenset(
    {
        "dependency_timeout",
        "dependency_unavailable",
        "dependency_invalid_response",
        "UNKNOWN",
    }
)
_SAFE_DIAGNOSTIC_REASON_CODES = frozenset(
    {
        "STANDARD_CLAIM_BOUNDARY_REJECTED",
        "RESEARCH_BIBLIOGRAPHY_GUARD_REJECTED",
        "CITATION_BINDING_REJECTED",
    }
)
_SAFE_CLAIM_BOUNDARY_CATEGORIES = frozenset(
    {"DIAGNOSIS", "CLINICAL", "SEVERITY", "PSYCHOMETRIC_SCORE", "OTHER_ALLOWLISTED"}
)
_SAFE_CLAIM_BOUNDARY_FIELDS = frozenset({"SUMMARY", "OBSERVATION", "SUGGESTION"})
_SAFE_ATOM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,127}$")
_OPAQUE_SUFFIX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,126}$")


def _page(offset: int, limit: int) -> tuple[int, int]:
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise error(ErrorCode.VALIDATION_FAILED, detail="invalid pagination")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= _PAGE_MAX:
        raise error(ErrorCode.VALIDATION_FAILED, detail="invalid pagination")
    return offset, limit


def _safe_id(value: Any, prefix: str) -> str:
    if not isinstance(value, str) or not value.startswith(f"{prefix}_"):
        raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="conversation resource was not found")
    suffix = value[len(prefix) + 1 :]
    if not suffix or len(value) > 128 or not _OPAQUE_SUFFIX.fullmatch(suffix):
        raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="conversation resource was not found")
    return value


def _required_key(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > _IDEMPOTENCY_KEY_MAX:
        raise error(ErrorCode.VALIDATION_FAILED, detail="invalid idempotency key")
    return value.strip()


def _safe_component_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Keep only explicitly safe, bounded identifiers/counters; never accept prose."""
    if value is None or not isinstance(value, Mapping):
        return {}
    result: dict[str, Any] = {}
    for key in _SAFE_COMPONENT_KEYS:
        item = value.get(key)
        if key == "dependency_error_code":
            if type(item) is str and item in _SAFE_DEPENDENCY_ERROR_CODES:
                result[key] = item
            continue
        if key == "diagnostic_reason_code":
            if type(item) is str and item in _SAFE_DIAGNOSTIC_REASON_CODES:
                result[key] = item
            continue
        if key == "claim_boundary_category":
            if type(item) is str and item in _SAFE_CLAIM_BOUNDARY_CATEGORIES:
                result[key] = item
            continue
        if key == "claim_boundary_field_kind":
            if type(item) is str and item in _SAFE_CLAIM_BOUNDARY_FIELDS:
                result[key] = item
            continue
        if isinstance(item, str) and _SAFE_ATOM.fullmatch(item):
            result[key] = item
        elif isinstance(item, int) and not isinstance(item, bool) and 0 <= item <= 1_000_000:
            result[key] = item
    return result


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return normalized.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _plain_mapping(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, Mapping):
        try:
            encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            if len(encoded.encode("utf-8")) > 20_000:
                return None
            return json.loads(encoded)
        except (TypeError, ValueError):
            return None
    return None


def _citation_field(value: Any, field: str, *, required: bool = False) -> str | None:
    """Validate a citation value against its actual ASCII/VARCHAR column limit."""
    if value is None:
        if required:
            raise error(ErrorCode.VALIDATION_FAILED, detail="invalid citation reference")
        return None
    limit = _CITATION_COLUMN_LIMITS[field]
    if not isinstance(value, str) or not value or len(value) > limit:
        raise error(ErrorCode.VALIDATION_FAILED, detail="invalid citation reference")
    if field in {"title", "organization", "locator"}:
        if not value.isprintable():
            raise error(ErrorCode.VALIDATION_FAILED, detail="invalid citation reference")
        return value
    if not value.isascii() or not _SAFE_ATOM.fullmatch(value):
        raise error(ErrorCode.VALIDATION_FAILED, detail="invalid citation reference")
    return value


def _safe_evidence_projection(row: Any) -> dict[str, Any] | None:
    """Return only schema-valid stored citation data; corrupted rows are not exposed."""
    try:
        citation_id = _citation_field(row.citation_id, "citation_id", required=True)
        source_id = _citation_field(row.source_id, "source_id", required=True)
        chunk_id = _citation_field(row.chunk_id, "chunk_id")
        document_id = _citation_field(row.document_id, "document_id")
        source_version = _citation_field(row.source_version, "source_version")
        source_hash = _citation_field(row.source_hash, "source_hash")
        title = _citation_field(row.citation_title, "title")
        organization = _citation_field(row.citation_organization, "organization")
        locator = _citation_field(row.locator, "locator")
        rank = row.rank_order
        if isinstance(rank, bool) or not isinstance(rank, int) or not 1 <= rank <= 1_000_000:
            return None
    except (AttributeError, BackendError, TypeError, ValueError):
        return None
    return {
        "citation_id": citation_id,
        "source_id": source_id,
        "chunk_id": chunk_id,
        "document_id": document_id,
        "title": title,
        "organization": organization,
        "locator": locator,
        "source_version": source_version,
        "source_hash": source_hash,
        "rank": rank,
    }


class SchoolConversationsPersistenceAdapter:
    """Persistence adapter for independent, owner-private student conversations."""

    def __init__(self, persistence: Any, *, target_role: str = "student") -> None:
        if target_role not in {"student", "student_research"}:
            raise ValueError("unsupported conversation storage lane")
        self._persistence = persistence
        self._target_role = target_role

    def __getattr__(self, name: str) -> Any:
        return getattr(self._persistence, name)

    async def _audit(
        self,
        uow: Any,
        *,
        account_id: int,
        action: str,
        resource_type: str,
        resource_ref: str | None,
        trace_id: str,
        count: int = 1,
    ) -> None:
        await uow.audit.append(
            action=action,
            resource_type=resource_type,
            resource_public_id=resource_ref,
            result=self._db_enums.AuditResult.SUCCESS,
            trace_id=trace_id,
            actor_account_id=account_id,
            safe_metadata={"source": "school_conversations", "state": "SUCCESS", "count": count},
        )

    async def _student_subject(self, uow: Any, actor: Any, now: datetime) -> tuple[int, Any]:
        role = getattr(getattr(actor, "role", None), "value", getattr(actor, "role", None))
        if str(role).lower() != "student":
            raise error(ErrorCode.FORBIDDEN, detail="access denied")
        account_id, _role_id = await self._school_actor_role(uow, actor, "student", now)
        if not isinstance(actor.subject_id, str) or not actor.subject_id.startswith("SUBJ_"):
            raise error(ErrorCode.FORBIDDEN, detail="access denied")
        m = self._db_models
        rows = list(
            (
                await uow.session.execute(
                    self._select(m.Subject)
                    .join(
                        m.SubjectAccessGrant,
                        (m.SubjectAccessGrant.subject_id == m.Subject.id)
                        & (m.SubjectAccessGrant.school_id == m.Subject.school_id),
                    )
                    .where(
                        m.Subject.subject_ref == actor.subject_id,
                        m.Subject.school_id == actor.school_id,
                        m.Subject.status == self._db_enums.SubjectStatus.ACTIVE.value,
                        m.Subject.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                        m.SubjectAccessGrant.principal_account_id == account_id,
                        m.SubjectAccessGrant.relationship_type == "SELF",
                        m.SubjectAccessGrant.school_id == actor.school_id,
                        m.SubjectAccessGrant.status == "ACTIVE",
                        m.SubjectAccessGrant.revoked_at.is_(None),
                        m.SubjectAccessGrant.valid_from <= now,
                        (m.SubjectAccessGrant.valid_until.is_(None))
                        | (m.SubjectAccessGrant.valid_until >= now),
                    )
                    .limit(2)
                )
            ).scalars()
        )
        if len(rows) != 1:
            raise error(ErrorCode.FORBIDDEN, detail="access denied")
        return account_id, rows[0]

    async def _owned_session(
        self,
        uow: Any,
        actor: Any,
        subject: Any,
        conversation_id: str,
        *,
        lock: bool,
    ) -> Any:
        m = self._db_models
        statement = (
            self._select(m.SupportSession)
            .join(m.Subject, m.Subject.id == m.SupportSession.subject_id)
            .where(
                m.SupportSession.support_ref == conversation_id,
                m.SupportSession.subject_id == subject.id,
                m.SupportSession.assessment_session_id.is_(None),
                m.SupportSession.target_role == self._target_role,
                m.Subject.id == subject.id,
                m.Subject.school_id == actor.school_id,
                m.Subject.subject_ref == actor.subject_id,
                m.Subject.status == self._db_enums.SubjectStatus.ACTIVE.value,
                m.Subject.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
            )
        )
        if lock:
            statement = statement.with_for_update()
        row = await uow.session.scalar(statement)
        if row is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="conversation was not found")
        return row

    @staticmethod
    def _session_projection(row: Any) -> dict[str, Any]:
        return {
            "conversation_id": row.support_ref,
            "status": str(row.status).lower(),
            "created_at": _timestamp(row.created_at),
            "updated_at": _timestamp(row.updated_at),
        }

    async def _lookup_receipt_resource(
        self,
        uow: Any,
        *,
        receipt: Any,
        resource_type: str,
    ) -> str:
        if (
            receipt is None
            or receipt.result_resource_type != resource_type
            or not isinstance(receipt.result_public_id, str)
        ):
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="idempotency result is unavailable")
        return receipt.result_public_id

    async def create(self, actor: Any, *, idempotency_key: str, trace_id: str) -> dict[str, Any]:
        key = _required_key(idempotency_key)
        now = self._utc_now()
        async with self._uow() as uow:
            account_id, subject = await self._student_subject(uow, actor, now)
            scope = f"{account_id}:student:conversation:create:{actor.school_id}"
            claim = await self._school_idempotency_begin(
                uow,
                (
                    key,
                    fingerprint(
                        {"operation": "conversation.create", "subject": subject.subject_ref}
                    ),
                    scope,
                ),
            )
            if claim.replayed:
                conversation_id = await self._lookup_receipt_resource(
                    uow, receipt=claim.record, resource_type="student_conversation"
                )
                row = await self._owned_session(uow, actor, subject, conversation_id, lock=False)
                await self._audit(
                    uow,
                    account_id=account_id,
                    action="student_conversation.create_replayed",
                    resource_type="student_conversation",
                    resource_ref=conversation_id,
                    trace_id=trace_id,
                )
                return self._session_projection(row)
            conversation_id = f"CONV_{uuid4().hex}"
            row = await uow.support.create_session(
                support_ref=conversation_id,
                subject_id=subject.id,
                target_role=self._target_role,
                assessment_session_id=None,
                trace_id=trace_id,
                retention_due_at=subject.retention_due_at,
            )
            await self._school_idempotency_complete(
                uow, claim, resource_type="student_conversation", result_ref=conversation_id
            )
            await self._audit(
                uow,
                account_id=account_id,
                action="student_conversation.created",
                resource_type="student_conversation",
                resource_ref=conversation_id,
                trace_id=trace_id,
            )
            return self._session_projection(row)

    async def list(self, actor: Any, *, offset: int, limit: int) -> dict[str, Any]:
        offset, limit = _page(offset, limit)
        from sqlalchemy import func

        now = self._utc_now()
        m = self._db_models
        async with self._uow() as uow:
            account_id, subject = await self._student_subject(uow, actor, now)
            base = self._select(m.SupportSession).where(
                m.SupportSession.subject_id == subject.id,
                m.SupportSession.assessment_session_id.is_(None),
                m.SupportSession.target_role == self._target_role,
            )
            total = int(
                await uow.session.scalar(
                    self._select(func.count(m.SupportSession.id)).where(
                        m.SupportSession.subject_id == subject.id,
                        m.SupportSession.assessment_session_id.is_(None),
                        m.SupportSession.target_role == self._target_role,
                    )
                )
                or 0
            )
            rows = list(
                (
                    await uow.session.scalars(
                        base.order_by(
                            m.SupportSession.updated_at.desc(), m.SupportSession.id.desc()
                        )
                        .offset(offset)
                        .limit(limit)
                    )
                ).all()
            )
            await self._audit(
                uow,
                account_id=account_id,
                action="student_conversation.listed",
                resource_type="student_conversation_collection",
                resource_ref=None,
                trace_id=get_request_context().trace_id,
                count=len(rows),
            )
            return {
                "items": [self._session_projection(row) for row in rows],
                "total": total,
                "has_more": offset + len(rows) < total,
            }

    async def detail(
        self, actor: Any, conversation_id: str, *, offset: int, limit: int
    ) -> dict[str, Any]:
        conversation_id = _safe_id(conversation_id, "CONV")
        offset, limit = _page(offset, limit)
        from sqlalchemy import func

        now = self._utc_now()
        m = self._db_models
        async with self._uow() as uow:
            account_id, subject = await self._student_subject(uow, actor, now)
            session = await self._owned_session(uow, actor, subject, conversation_id, lock=True)
            interrupted = await self._expire_abandoned(uow, session, now)
            total = int(
                await uow.session.scalar(
                    self._select(func.count(m.SupportRun.id)).where(
                        m.SupportRun.support_session_id == session.id,
                        m.SupportRun.assessment_session_id.is_(None),
                    )
                )
                or 0
            )
            runs = list(
                (
                    await uow.session.scalars(
                        self._select(m.SupportRun)
                        .where(
                            m.SupportRun.support_session_id == session.id,
                            m.SupportRun.assessment_session_id.is_(None),
                        )
                        .order_by(m.SupportRun.created_at, m.SupportRun.id)
                        .offset(offset)
                        .limit(limit)
                    )
                ).all()
            )
            sequences: set[int] = set()
            turn_by_sequence: dict[int, str] = {}
            for run in runs:
                metadata = (
                    run.component_versions if isinstance(run.component_versions, Mapping) else {}
                )
                for name in ("user_message_sequence", "assistant_message_sequence"):
                    value = metadata.get(name)
                    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                        sequences.add(value)
                        turn_by_sequence[value] = run.run_ref
            messages: list[dict[str, Any]] = []
            action_by_turn = {run.run_ref: run.workflow_action for run in runs}
            if sequences:
                message_rows = list(
                    (
                        await uow.session.scalars(
                            self._select(m.SupportMessage)
                            .where(
                                m.SupportMessage.support_session_id == session.id,
                                m.SupportMessage.sequence_no.in_(sequences),
                            )
                            .order_by(m.SupportMessage.sequence_no)
                        )
                    ).all()
                )
                # Authorization and ownership are established before any ciphertext is opened.
                for row in message_rows:
                    expected_turn = turn_by_sequence.get(int(row.sequence_no))
                    if (
                        self._target_role == "student_research"
                        and row.message_kind == self._db_enums.MessageKind.APPROVED_OUTPUT.value
                        and action_by_turn.get(expected_turn)
                        in {"PROCEED", "PROCEED_WITH_BOUNDARY"}
                    ):
                        # Legacy research answers remain encrypted in storage, but their
                        # old completed projection is no longer a release mechanism.
                        continue
                    payload = self._persistence._decrypt_support_message(row)
                    if (
                        not isinstance(payload, Mapping)
                        or payload.get("schema_version") != "independent-message.v1"
                        or payload.get("turn_id") != expected_turn
                    ):
                        continue
                    if row.message_kind == self._db_enums.MessageKind.USER_INPUT.value:
                        body = payload.get("text")
                        if not isinstance(body, str) or len(body) > _MESSAGE_MAX:
                            continue
                        safe_payload = {"turn_id": expected_turn, "text": body}
                    elif row.message_kind == self._db_enums.MessageKind.APPROVED_OUTPUT.value:
                        body = payload.get("content")
                        if not isinstance(body, Mapping):
                            continue
                        safe_payload = {"turn_id": expected_turn, "content": dict(body)}
                    else:
                        continue
                    messages.append(
                        {
                            "message_id": f"MSG_{row.public_id}",
                            "sequence": int(row.sequence_no),
                            "kind": str(row.message_kind).lower(),
                            "created_at": _timestamp(row.created_at),
                            "payload": safe_payload,
                        }
                    )
            run_ids = [run.id for run in runs]
            evidence_by_run: dict[int, list[dict[str, Any]]] = {run_id: [] for run_id in run_ids}
            if run_ids and self._target_role != "student_research":
                evidence_rows = list(
                    (
                        await uow.session.scalars(
                            self._select(m.SupportEvidence)
                            .where(m.SupportEvidence.support_run_id.in_(run_ids))
                            .order_by(
                                m.SupportEvidence.support_run_id, m.SupportEvidence.rank_order
                            )
                            .limit(limit * 20)
                        )
                    ).all()
                )
                for evidence in evidence_rows:
                    projection = _safe_evidence_projection(evidence)
                    if projection is not None:
                        evidence_by_run[evidence.support_run_id].append(projection)
            turns = []
            for run in runs:
                stored = (
                    run.component_versions if isinstance(run.component_versions, Mapping) else {}
                )
                safe = _safe_component_metadata(stored.get("safe_metadata"))
                turns.append(
                    {
                        "turn_id": run.run_ref,
                        "status": str(run.status).lower(),
                        "action": run.workflow_action,
                        "created_at": _timestamp(run.created_at),
                        "completed_at": _timestamp(run.completed_at),
                        "safe_metadata": safe,
                        "citations": evidence_by_run.get(run.id, []),
                    }
                )
            await self._audit(
                uow,
                account_id=account_id,
                action="student_conversation.detail_read",
                resource_type="student_conversation",
                resource_ref=conversation_id,
                trace_id=get_request_context().trace_id,
                count=len(messages),
            )
            if interrupted:
                await self._audit(
                    uow,
                    account_id=account_id,
                    action="student_conversation.turn_interrupted",
                    resource_type="student_conversation",
                    resource_ref=conversation_id,
                    trace_id=get_request_context().trace_id,
                    count=interrupted,
                )
            return {
                "conversation": self._session_projection(session),
                "messages": messages,
                "turns": turns,
                "offset": offset,
                "limit": limit,
                "total_turns": total,
                "has_more": offset + len(runs) < total,
            }

    async def _expire_abandoned(self, uow: Any, session: Any, now: datetime) -> int:
        m = self._db_models
        requested = list(
            (
                await uow.session.scalars(
                    self._select(m.SupportRun)
                    .where(
                        m.SupportRun.support_session_id == session.id,
                        m.SupportRun.status == self._db_enums.SupportRunStatus.REQUESTED.value,
                        m.SupportRun.assessment_session_id.is_(None),
                    )
                    .order_by(m.SupportRun.created_at)
                    .limit(101)
                    .with_for_update()
                )
            ).all()
        )
        if len(requested) > 100:
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="conversation requires reconciliation")
        interrupted = 0
        for run in requested:
            started = run.started_at or run.created_at
            if started is not None and started > now - _TURN_MAX_AGE:
                continue
            stored = run.component_versions if isinstance(run.component_versions, Mapping) else {}
            safe = _safe_component_metadata(stored.get("safe_metadata"))
            safe["failure_code"] = "TURN_INTERRUPTED"
            stored = {
                "source": "independent_conversation",
                "user_message_sequence": stored.get("user_message_sequence"),
                "safe_metadata": safe,
            }
            run.component_versions = stored
            run.status = self._db_enums.SupportRunStatus.FAILED.value
            run.workflow_action = "INTERRUPTED"
            run.completed_at = now
            interrupted += 1
        if interrupted:
            await uow.session.flush()
        return interrupted

    async def _replay_turn(
        self, uow: Any, session: Any, run: Any, *, replayed: bool
    ) -> dict[str, Any]:
        stored = run.component_versions if isinstance(run.component_versions, Mapping) else {}
        sequence = stored.get("user_message_sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="turn reservation is unavailable")
        status = str(getattr(run.status, "value", run.status)).upper()
        action = getattr(run, "workflow_action", None)
        safe = _safe_component_metadata(stored.get("safe_metadata"))
        result = {
            "turn_id": run.run_ref,
            "status": status.lower(),
            "replayed": replayed,
            "user_message_sequence": sequence,
            "action": action,
            "completed_at": _timestamp(getattr(run, "completed_at", None)),
            "assistant_message_sequence": None,
            "citations": [],
            "safe_metadata": safe,
            "content": None,
        }
        if status == self._db_enums.SupportRunStatus.REQUESTED.value:
            return result
        if (
            status
            not in {
                self._db_enums.SupportRunStatus.COMPLETED.value,
                self._db_enums.SupportRunStatus.BLOCKED.value,
                self._db_enums.SupportRunStatus.FAILED.value,
            }
            or not isinstance(action, str)
            or not action
            or getattr(run, "completed_at", None) is None
        ):
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="turn reservation is unavailable")

        assistant_sequence = stored.get("assistant_message_sequence")
        if assistant_sequence is not None and (
            not isinstance(assistant_sequence, int)
            or isinstance(assistant_sequence, bool)
            or assistant_sequence < 1
            or assistant_sequence == sequence
        ):
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="turn reservation is unavailable")

        has_approved_output = status == self._db_enums.SupportRunStatus.COMPLETED.value or (
            status == self._db_enums.SupportRunStatus.BLOCKED.value and action == "CRISIS_ROUTE"
        )
        if has_approved_output != (assistant_sequence is not None):
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="turn reservation is unavailable")
        if status == self._db_enums.SupportRunStatus.COMPLETED.value and action not in {
            "PROCEED",
            "PROCEED_WITH_BOUNDARY",
            "ABSTAIN",
        }:
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="turn reservation is unavailable")
        if (
            status == self._db_enums.SupportRunStatus.FAILED.value
            and action not in _TURN_FAILURE_ACTIONS
        ):
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="turn reservation is unavailable")
        if (
            status == self._db_enums.SupportRunStatus.BLOCKED.value
            and action
            not in {
                "BLOCK",
                "REVIEW_REQUIRED",
                "CRISIS_ROUTE",
            }
            and not (self._target_role == "student_research" and action == "CONTENT_REVIEW_HELD")
        ):
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="turn reservation is unavailable")

        m = self._db_models
        citations: list[dict[str, Any]] = []
        evidence_rows = list(
            (
                await uow.session.scalars(
                    self._select(m.SupportEvidence)
                    .where(m.SupportEvidence.support_run_id == run.id)
                    .order_by(m.SupportEvidence.rank_order)
                    .limit(20)
                )
            ).all()
        )
        for evidence in evidence_rows:
            projection = _safe_evidence_projection(evidence)
            if projection is not None:
                citations.append(projection)

        if assistant_sequence is not None:
            message_rows = list(
                (
                    await uow.session.scalars(
                        self._select(m.SupportMessage).where(
                            m.SupportMessage.support_session_id == session.id,
                            m.SupportMessage.sequence_no == assistant_sequence,
                        )
                    )
                ).all()
            )
            if len(message_rows) != 1:
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="turn reservation is unavailable")
            message = message_rows[0]
            if (
                message.sequence_no != assistant_sequence
                or message.message_kind != self._db_enums.MessageKind.APPROVED_OUTPUT.value
            ):
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="turn reservation is unavailable")
            if (
                self._target_role == "student_research"
                and status == self._db_enums.SupportRunStatus.COMPLETED.value
                and action in {"PROCEED", "PROCEED_WITH_BOUNDARY"}
            ):
                result["assistant_message_sequence"] = assistant_sequence
                return result
            payload = self._persistence._decrypt_support_message(message)
            if (
                not isinstance(payload, Mapping)
                or payload.get("schema_version") != "independent-message.v1"
                or payload.get("turn_id") != run.run_ref
                or not isinstance(payload.get("content"), Mapping)
            ):
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="turn reservation is unavailable")
            stored_content = payload["content"]
            if action == "CRISIS_ROUTE":
                crisis_text = stored_content.get("text")
                if (
                    set(stored_content) != {"kind", "text"}
                    or stored_content.get("kind") != "approved_safety_response"
                    or not isinstance(crisis_text, str)
                    or not crisis_text.strip()
                    or len(crisis_text) > _MESSAGE_MAX
                ):
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT, detail="turn reservation is unavailable"
                    )
                result["content"] = {"kind": "approved_safety_response", "text": crisis_text}
            else:
                from smhai_backend.domains.support.schemas import GenerationContent

                try:
                    content = GenerationContent.model_validate(stored_content, strict=True)
                except (TypeError, ValueError):
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT, detail="turn reservation is unavailable"
                    ) from None
                result["content"] = content.model_dump(mode="json")

        if status == self._db_enums.SupportRunStatus.FAILED.value and citations:
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="turn reservation is unavailable")
        if (
            status == self._db_enums.SupportRunStatus.BLOCKED.value
            and action != "CRISIS_ROUTE"
            and citations
        ):
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="turn reservation is unavailable")
        if action == "ABSTAIN" and citations:
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="turn reservation is unavailable")
        if action == "CRISIS_ROUTE" and citations:
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="turn reservation is unavailable")
        result["assistant_message_sequence"] = assistant_sequence
        result["citations"] = citations
        return result

    async def reserve_turn(
        self,
        actor: Any,
        conversation_id: str,
        *,
        message: str,
        idempotency_key: str,
        trace_id: str,
    ) -> dict[str, Any]:
        conversation_id = _safe_id(conversation_id, "CONV")
        key = _required_key(idempotency_key)
        if not isinstance(message, str) or not message.strip() or len(message) > _MESSAGE_MAX:
            raise error(ErrorCode.VALIDATION_FAILED, detail="invalid message")
        now = self._utc_now()
        m = self._db_models
        async with self._uow() as uow:
            account_id, subject = await self._student_subject(uow, actor, now)
            session = await self._owned_session(uow, actor, subject, conversation_id, lock=True)
            if session.status not in {
                self._db_enums.SupportStatus.OPEN.value,
                self._db_enums.SupportStatus.ACTIVE.value,
            }:
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="conversation is not active")
            scope = f"{account_id}:student:conversation:turn:{actor.school_id}:{conversation_id}"
            claim = await self._school_idempotency_begin(
                uow,
                (
                    key,
                    fingerprint(
                        {
                            "operation": "conversation.reserve_turn",
                            "conversation_id": conversation_id,
                            "message": message,
                        }
                    ),
                    scope,
                ),
            )
            interrupted = await self._expire_abandoned(uow, session, now)
            if claim.replayed:
                turn_id = await self._lookup_receipt_resource(
                    uow, receipt=claim.record, resource_type="student_conversation_turn"
                )
                run = await uow.session.scalar(
                    self._select(m.SupportRun).where(
                        m.SupportRun.run_ref == turn_id,
                        m.SupportRun.support_session_id == session.id,
                        m.SupportRun.assessment_session_id.is_(None),
                    )
                )
                if run is None:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT, detail="turn reservation is unavailable"
                    )
                if interrupted:
                    await self._audit(
                        uow,
                        account_id=account_id,
                        action="student_conversation.turn_interrupted",
                        resource_type="student_conversation",
                        resource_ref=conversation_id,
                        trace_id=trace_id,
                        count=interrupted,
                    )
                await self._audit(
                    uow,
                    account_id=account_id,
                    action="student_conversation.turn_replayed",
                    resource_type="student_conversation_turn",
                    resource_ref=turn_id,
                    trace_id=trace_id,
                )
                return await self._replay_turn(uow, session, run, replayed=True)
            active = await uow.session.scalar(
                self._select(m.SupportRun)
                .where(
                    m.SupportRun.support_session_id == session.id,
                    m.SupportRun.status == self._db_enums.SupportRunStatus.REQUESTED.value,
                    m.SupportRun.assessment_session_id.is_(None),
                )
                .with_for_update()
            )
            if active is not None:
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT, detail="a conversation turn is in progress"
                )
            from sqlalchemy import func

            maximum = await uow.session.scalar(
                self._select(func.max(m.SupportMessage.sequence_no)).where(
                    m.SupportMessage.support_session_id == session.id
                )
            )
            sequence = int(maximum or 0) + 1
            turn_id = f"TURN_{uuid4().hex}"
            run = await uow.support.create_run(
                run_ref=turn_id,
                support_session_id=session.id,
                trace_id=trace_id,
                status=self._db_enums.SupportRunStatus.REQUESTED,
                workflow_action="REQUESTED",
                assessment_session_id=None,
                component_versions={
                    "source": "independent_conversation",
                    "user_message_sequence": sequence,
                    "safe_metadata": {},
                },
            )
            run.started_at = now
            await uow.support.persist_message(
                support_session_id=session.id,
                sequence_no=sequence,
                message_kind=self._db_enums.MessageKind.USER_INPUT,
                payload={
                    "schema_version": "independent-message.v1",
                    "turn_id": turn_id,
                    "text": message,
                },
                retention_due_at=session.retention_due_at,
            )
            session.status = self._db_enums.SupportStatus.ACTIVE.value
            session.trace_id = trace_id
            await self._school_idempotency_complete(
                uow, claim, resource_type="student_conversation_turn", result_ref=turn_id
            )
            await self._audit(
                uow,
                account_id=account_id,
                action="student_conversation.turn_reserved",
                resource_type="student_conversation_turn",
                resource_ref=turn_id,
                trace_id=trace_id,
            )
            if interrupted:
                await self._audit(
                    uow,
                    account_id=account_id,
                    action="student_conversation.turn_interrupted",
                    resource_type="student_conversation",
                    resource_ref=conversation_id,
                    trace_id=trace_id,
                    count=interrupted,
                )
            return {
                "turn_id": run.run_ref,
                "status": "requested",
                "replayed": False,
                "user_message_sequence": sequence,
            }

    @staticmethod
    def _citation_value(citation: Any, key: str) -> Any:
        if isinstance(citation, Mapping):
            return citation.get(key)
        return getattr(citation, key, None)

    def _persist_evidence(
        self, uow: Any, run: Any, citations: Sequence[Any]
    ) -> list[dict[str, Any]]:
        persisted: list[dict[str, Any]] = []
        if len(citations) > 20:
            raise error(ErrorCode.VALIDATION_FAILED, detail="too many citation references")
        for index, citation in enumerate(citations, start=1):
            citation_id = _citation_field(
                self._citation_value(citation, "citation_id"), "citation_id", required=True
            )
            document_id = _citation_field(
                self._citation_value(citation, "document_id"), "document_id"
            )
            chunk_id = _citation_field(self._citation_value(citation, "chunk_id"), "chunk_id")
            title = self._citation_value(citation, "title") or self._citation_value(
                citation, "source_title"
            )
            organization = self._citation_value(citation, "organization") or self._citation_value(
                citation, "source_organization"
            )
            locator = self._citation_value(citation, "locator") or self._citation_value(
                citation, "source_locator"
            )
            source_version = _citation_field(
                self._citation_value(citation, "source_version"), "source_version"
            )
            source_hash = _citation_field(
                self._citation_value(citation, "source_hash"), "source_hash"
            )
            title = _citation_field(title, "title")
            organization = _citation_field(organization, "organization")
            locator = _citation_field(locator, "locator")
            source_id = document_id or citation_id
            persisted.append(
                {
                    "citation_id": citation_id,
                    "source_id": source_id,
                    "chunk_id": chunk_id,
                    "document_id": document_id,
                    "source_version": source_version,
                    "source_hash": source_hash,
                    "title": title,
                    "organization": organization,
                    "locator": locator,
                    "rank": index,
                }
            )
        return persisted

    async def finish_turn(
        self,
        actor: Any,
        conversation_id: str,
        turn_id: str,
        *,
        status: str,
        action: str,
        approved_content: Any = None,
        citations: Sequence[Any] = (),
        safe_metadata: Mapping[str, Any] | None = None,
        safety_case: SafetyCaseSeed | None = None,
        trace_id: str,
    ) -> dict[str, Any]:
        conversation_id = _safe_id(conversation_id, "CONV")
        turn_id = _safe_id(turn_id, "TURN")
        status = status.upper() if isinstance(status, str) else ""
        action = action.upper() if isinstance(action, str) else ""
        valid_statuses = {"COMPLETED", "BLOCKED", "FAILED"}
        safety_actions = {item.value for item in self._db_enums.SafetyAction}
        if status not in valid_statuses:
            raise error(ErrorCode.VALIDATION_FAILED, detail="invalid terminal turn state")
        content = _plain_mapping(approved_content)
        if status == "COMPLETED":
            if action not in {"PROCEED", "PROCEED_WITH_BOUNDARY", "ABSTAIN"} or content is None:
                raise error(ErrorCode.VALIDATION_FAILED, detail="approved content is required")
            if action == "ABSTAIN" and citations:
                raise error(ErrorCode.VALIDATION_FAILED, detail="abstention cannot cite evidence")
        elif status == "BLOCKED" and action == "CRISIS_ROUTE":
            if content is None or citations:
                raise error(
                    ErrorCode.VALIDATION_FAILED, detail="approved crisis content is required"
                )
        elif status == "BLOCKED":
            if action not in safety_actions or content is not None or citations:
                raise error(
                    ErrorCode.VALIDATION_FAILED, detail="terminal turn has no approved content"
                )
        elif status == "FAILED":
            if action not in _TURN_FAILURE_ACTIONS or content is not None or citations:
                raise error(ErrorCode.VALIDATION_FAILED, detail="failed turn cannot store output")
        elif content is not None or citations:
            # Do not persist unapproved model candidates through a failure/block path.
            raise error(ErrorCode.VALIDATION_FAILED, detail="terminal turn has no approved content")
        if action in {"REVIEW_REQUIRED", "CRISIS_ROUTE"}:
            if (
                status != "BLOCKED"
                or not isinstance(safety_case, SafetyCaseSeed)
                or safety_case.action != action
            ):
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT,
                    detail="safety review metadata is unavailable",
                )
        elif safety_case is not None:
            raise error(ErrorCode.VALIDATION_FAILED, detail="invalid safety review metadata")
        student_role_id: int | None = None
        clean_metadata = _safe_component_metadata(safe_metadata)
        now = self._utc_now()
        m = self._db_models
        async with self._uow() as uow:
            account_id, subject = await self._student_subject(uow, actor, now)
            session = await self._owned_session(uow, actor, subject, conversation_id, lock=True)
            run = await uow.session.scalar(
                self._select(m.SupportRun)
                .where(
                    m.SupportRun.run_ref == turn_id,
                    m.SupportRun.support_session_id == session.id,
                    m.SupportRun.assessment_session_id.is_(None),
                )
                .with_for_update()
            )
            if run is None:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="turn was not found")
            if run.status != self._db_enums.SupportRunStatus.REQUESTED.value:
                if run.status == status and run.workflow_action == action:
                    stored = (
                        run.component_versions
                        if isinstance(run.component_versions, Mapping)
                        else {}
                    )
                    await self._audit(
                        uow,
                        account_id=account_id,
                        action="student_conversation.finish_replayed",
                        resource_type="student_conversation_turn",
                        resource_ref=turn_id,
                        trace_id=trace_id,
                    )
                    return {
                        "turn_id": run.run_ref,
                        "status": str(run.status).lower(),
                        "action": run.workflow_action,
                        "completed_at": _timestamp(run.completed_at),
                        "safe_metadata": _safe_component_metadata(stored.get("safe_metadata")),
                    }
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="turn is already terminal")
            started = run.started_at or run.created_at
            if started is not None and started <= now - _TURN_MAX_AGE:
                component = (
                    run.component_versions if isinstance(run.component_versions, Mapping) else {}
                )
                sequence = component.get("user_message_sequence")
                safe = _safe_component_metadata(component.get("safe_metadata"))
                safe["failure_code"] = "TURN_INTERRUPTED"
                run.status = self._db_enums.SupportRunStatus.FAILED.value
                run.workflow_action = "INTERRUPTED"
                run.completed_at = now
                run.component_versions = {
                    "source": "independent_conversation",
                    "user_message_sequence": sequence,
                    "safe_metadata": safe,
                }
                await self._audit(
                    uow,
                    account_id=account_id,
                    action="student_conversation.turn_interrupted",
                    resource_type="student_conversation_turn",
                    resource_ref=turn_id,
                    trace_id=trace_id,
                )
                return {
                    "turn_id": turn_id,
                    "status": "failed",
                    "action": "INTERRUPTED",
                    "completed_at": _timestamp(now),
                    "user_message_sequence": sequence,
                    "assistant_message_sequence": None,
                    "citations": [],
                    "safe_metadata": safe,
                }
            evidence = self._persist_evidence(uow, run, citations) if citations else []
            component = (
                run.component_versions if isinstance(run.component_versions, Mapping) else {}
            )
            sequence = component.get("user_message_sequence")
            if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="turn reservation is unavailable")
            output_sequence = None
            if content is not None:
                from sqlalchemy import func

                maximum = await uow.session.scalar(
                    self._select(func.max(m.SupportMessage.sequence_no)).where(
                        m.SupportMessage.support_session_id == session.id
                    )
                )
                output_sequence = int(maximum or 0) + 1
                await uow.support.persist_message(
                    support_session_id=session.id,
                    sequence_no=output_sequence,
                    message_kind=self._db_enums.MessageKind.APPROVED_OUTPUT,
                    payload={
                        "schema_version": "independent-message.v1",
                        "turn_id": turn_id,
                        "content": content,
                    },
                    retention_due_at=session.retention_due_at,
                )
            if evidence:
                for citation in evidence:
                    await uow.support.add_evidence(
                        support_run_id=run.id,
                        citation_id=citation["citation_id"],
                        source_id=citation["source_id"],
                        chunk_id=citation["chunk_id"],
                        document_id=citation["document_id"],
                        source_version=citation["source_version"],
                        source_hash=citation["source_hash"],
                        citation_title=citation["title"],
                        citation_organization=citation["organization"],
                        locator=citation["locator"],
                        rank_order=citation["rank"],
                    )
            run.status = getattr(self._db_enums.SupportRunStatus, status).value
            run.workflow_action = action
            run.completed_at = now
            if run.started_at is not None:
                elapsed = (now - run.started_at).total_seconds() * 1000
                run.duration_ms = max(0, min(int(elapsed), 2_147_483_647))
            run.component_versions = {
                "source": "independent_conversation",
                "user_message_sequence": sequence,
                "assistant_message_sequence": output_sequence,
                "safe_metadata": clean_metadata,
            }
            if safety_case is not None:
                _student_account_id, student_role_id = await self._school_actor_role(
                    uow, actor, "student", now
                )
                safety_action = next(
                    item for item in self._db_enums.SafetyAction if item.value == safety_case.action
                )
                decision = await uow.support.create_safety_decision(
                    decision_ref=f"SAFE_{uuid4().hex}",
                    support_run_id=run.id,
                    action=safety_action,
                    policy_version=_SAFETY_METADATA_POLICY_VERSION,
                    guard_model_revision=None,
                    trace_id=trace_id,
                    detail=None,
                    retention_due_at=session.retention_due_at,
                )
                if uow.conversation_safety is None or student_role_id is None:
                    raise error(
                        ErrorCode.DEPENDENCY_UNAVAILABLE,
                        detail="conversation safety persistence is unavailable",
                        retryable=True,
                    )
                await uow.conversation_safety.create_from_safety_decision(
                    support_session_id=session.id,
                    support_run_id=run.id,
                    safety_decision_id=decision.id,
                    school_id=actor.school_id,
                    subject_id=subject.id,
                    action=safety_case.action,
                    reason_codes=safety_case.reason_codes,
                    safety_review_reference=safety_case.review_reference,
                    actor_membership_role_id=student_role_id,
                    trace_id=trace_id,
                    retention_due_at=session.retention_due_at,
                    now=now,
                )
            session.trace_id = trace_id
            await self._audit(
                uow,
                account_id=account_id,
                action=f"student_conversation.turn_{status.lower()}",
                resource_type="student_conversation_turn",
                resource_ref=turn_id,
                trace_id=trace_id,
            )
            return {
                "turn_id": turn_id,
                "status": status.lower(),
                "action": action,
                "completed_at": _timestamp(run.completed_at),
                "user_message_sequence": sequence,
                "assistant_message_sequence": output_sequence,
                "citations": evidence,
                "safe_metadata": clean_metadata,
            }

    async def finish_content_review_hold(
        self,
        actor: Any,
        conversation_id: str,
        turn_id: str,
        *,
        candidate_payload: Mapping[str, Any],
        safe_metadata: Mapping[str, Any] | None,
        trace_id: str,
    ) -> dict[str, Any]:
        """Atomically hold a validated research candidate and block its source turn."""
        if self._target_role != "student_research":
            raise error(ErrorCode.FORBIDDEN, detail="research review hold is unavailable")
        from smhai_backend.domains.independent_education_reviews.schemas import (
            IndependentEducationCandidatePayload,
        )

        try:
            candidate = IndependentEducationCandidatePayload.model_validate(
                candidate_payload, strict=True
            )
        except (TypeError, ValueError):
            raise error(
                ErrorCode.VALIDATION_FAILED,
                detail="research candidate could not be held",
            ) from None
        if candidate.provenance.trace_id != trace_id:
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="research turn binding is unavailable")
        conversation_id = _safe_id(conversation_id, "CONV")
        turn_id = _safe_id(turn_id, "TURN")
        now = self._utc_now()
        clean_metadata = _safe_component_metadata(safe_metadata)
        m = self._db_models
        async with self._uow() as uow:
            account_id, subject = await self._student_subject(uow, actor, now)
            _student_account_id, actor_role_id = await self._school_actor_role(
                uow, actor, "student", now
            )
            session = await self._owned_session(uow, actor, subject, conversation_id, lock=True)
            run = await uow.session.scalar(
                self._select(m.SupportRun)
                .where(
                    m.SupportRun.run_ref == turn_id,
                    m.SupportRun.support_session_id == session.id,
                    m.SupportRun.assessment_session_id.is_(None),
                )
                .with_for_update()
            )
            if run is None or run.trace_id != trace_id:
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="turn was not found")
            if run.status != self._db_enums.SupportRunStatus.REQUESTED.value:
                existing = await uow.session.scalar(
                    self._select(m.SchoolIndependentEducationReview).where(
                        m.SchoolIndependentEducationReview.support_run_id == run.id,
                        m.SchoolIndependentEducationReview.support_session_id == session.id,
                        m.SchoolIndependentEducationReview.subject_id == subject.id,
                        m.SchoolIndependentEducationReview.school_id == actor.school_id,
                    )
                )
                if (
                    run.status == self._db_enums.SupportRunStatus.BLOCKED.value
                    and run.workflow_action == "CONTENT_REVIEW_HELD"
                    and existing is not None
                    and existing.trace_id == trace_id
                    and existing.candidate_content_sha256
                    == hashlib.sha256(
                        json.dumps(
                            candidate.model_dump(mode="json"),
                            ensure_ascii=False,
                            allow_nan=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest()
                ):
                    stored = (
                        run.component_versions
                        if isinstance(run.component_versions, Mapping)
                        else {}
                    )
                    return {
                        "turn_id": turn_id,
                        "status": "blocked",
                        "action": "CONTENT_REVIEW_HELD",
                        "completed_at": _timestamp(run.completed_at),
                        "user_message_sequence": None,
                        "assistant_message_sequence": None,
                        "citations": [],
                        "safe_metadata": _safe_component_metadata(stored.get("safe_metadata")),
                    }
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="turn is already terminal")
            component = (
                run.component_versions if isinstance(run.component_versions, Mapping) else {}
            )
            sequence = component.get("user_message_sequence")
            if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="turn reservation is unavailable")
            started = run.started_at or run.created_at
            if started is not None and started <= now - _TURN_MAX_AGE:
                safe = _safe_component_metadata(component.get("safe_metadata"))
                safe["failure_code"] = "TURN_INTERRUPTED"
                run.status = self._db_enums.SupportRunStatus.FAILED.value
                run.workflow_action = "INTERRUPTED"
                run.completed_at = now
                run.component_versions = {
                    "source": "independent_conversation",
                    "user_message_sequence": sequence,
                    "safe_metadata": safe,
                }
                await self._audit(
                    uow,
                    account_id=account_id,
                    action="student_conversation.turn_interrupted",
                    resource_type="student_conversation_turn",
                    resource_ref=turn_id,
                    trace_id=trace_id,
                )
                return {
                    "turn_id": turn_id,
                    "status": "failed",
                    "action": "INTERRUPTED",
                    "completed_at": _timestamp(now),
                    "user_message_sequence": sequence,
                    "assistant_message_sequence": None,
                    "citations": [],
                    "safe_metadata": safe,
                }
            if (
                candidate.provenance.source_study_ref == ""
                or candidate.provenance.source_package_ref == ""
                or candidate.provenance.source_manifest_sha256 == ""
            ):
                raise error(
                    ErrorCode.WORKFLOW_CONFLICT, detail="research source pins are unavailable"
                )
            if uow.independent_education_reviews is None:
                raise error(
                    ErrorCode.DEPENDENCY_UNAVAILABLE,
                    detail="research education review persistence is unavailable",
                    retryable=True,
                )
            review = await uow.independent_education_reviews.create_held(
                review_ref=f"EDUREV_{uuid4().hex}",
                school_id=actor.school_id,
                subject_id=subject.id,
                support_session_id=session.id,
                support_run_id=run.id,
                candidate_payload=candidate.model_dump(mode="json"),
                provenance=candidate.provenance.model_dump(mode="python"),
                actor_membership_role_id=actor_role_id,
                trace_id=trace_id,
                retention_due_at=session.retention_due_at,
                now=now,
            )
            run.status = self._db_enums.SupportRunStatus.BLOCKED.value
            run.workflow_action = "CONTENT_REVIEW_HELD"
            run.completed_at = now
            run.generation_ref = candidate.provenance.generation_id
            run.retrieval_ref = candidate.provenance.retrieval_id
            if run.started_at is not None:
                elapsed = (now - run.started_at).total_seconds() * 1000
                run.duration_ms = max(0, min(int(elapsed), 2_147_483_647))
            run.component_versions = {
                "source": "independent_conversation",
                "user_message_sequence": sequence,
                "assistant_message_sequence": None,
                "safe_metadata": clean_metadata,
            }
            session.trace_id = trace_id
            await uow.session.flush()
            await self._audit(
                uow,
                account_id=account_id,
                action="student_conversation.content_review_held",
                resource_type="independent_education_review",
                resource_ref=review.review_ref,
                trace_id=trace_id,
            )
            return {
                "turn_id": turn_id,
                "status": "blocked",
                "action": "CONTENT_REVIEW_HELD",
                "completed_at": _timestamp(now),
                "user_message_sequence": sequence,
                "assistant_message_sequence": None,
                "citations": [],
                "safe_metadata": clean_metadata,
            }
