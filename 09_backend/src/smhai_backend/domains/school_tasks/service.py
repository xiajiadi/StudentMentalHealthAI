"""Authorization-aware orchestration for school classes and task snapshots."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.models import Actor, BackendRole


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def task_ref_for_idempotency(actor: Actor, class_ref: str, key: str) -> str:
    stable_source = (
        f"{actor.user_id}:{actor.school_id}:{actor.school_ref}:{actor.role.value}:{class_ref}:{key}"
    )
    return f"TASK_{hashlib.sha256(stable_source.encode()).hexdigest()[:32]}"


class SchoolTaskService:
    def __init__(self, *, persistence, assessments, cat) -> None:
        self.persistence = persistence
        self.assessments = assessments
        self.cat = cat

    @staticmethod
    def _require(actor: Actor, role: BackendRole) -> None:
        if actor.scope_profile != "school_tenant" or actor.role is not role:
            raise error(ErrorCode.FORBIDDEN, detail="access denied")

    async def list_classes(self, actor: Actor):
        self._require(actor, BackendRole.ADMIN)
        return await self.persistence.school_list_classes(actor)

    async def list_members(self, actor: Actor, role: str):
        self._require(actor, BackendRole.ADMIN)
        if role not in {"student", "teacher"}:
            raise error(ErrorCode.VALIDATION_FAILED, detail="unsupported school member role")
        return await self.persistence.school_list_members(actor, role, at=utc_now())

    async def create_class(self, actor: Actor, class_ref: str, *, idempotency):
        self._require(actor, BackendRole.ADMIN)
        return await self.persistence.school_create_class(
            actor, class_ref, at=utc_now(), idempotency=idempotency
        )

    async def assign_student(
        self, actor: Actor, class_ref: str, student_user_id: str, *, idempotency
    ):
        self._require(actor, BackendRole.ADMIN)
        return await self.persistence.school_assign_student(
            actor, class_ref, student_user_id, at=utc_now(), idempotency=idempotency
        )

    async def assign_teacher(
        self, actor: Actor, class_ref: str, teacher_user_id: str, *, idempotency
    ):
        self._require(actor, BackendRole.ADMIN)
        return await self.persistence.school_assign_teacher(
            actor, class_ref, teacher_user_id, at=utc_now(), idempotency=idempotency
        )

    async def publish_task(self, actor: Actor, class_ref: str, *, opens_at, due_at, idempotency):
        self._require(actor, BackendRole.ADMIN)
        now = utc_now()
        opens = _naive_utc(opens_at)
        due = _naive_utc(due_at) if due_at is not None else None
        if due is not None and due < opens:
            raise error(ErrorCode.VALIDATION_FAILED, detail="task window is invalid")
        key, _fingerprint, _scope = idempotency
        return await self.persistence.school_publish_task(
            actor,
            class_ref,
            task_ref_for_idempotency(actor, class_ref, key),
            opens_at=opens,
            due_at=due,
            at=now,
            idempotency=idempotency,
        )

    async def list_class_tasks(self, actor: Actor, class_ref: str):
        self._require(actor, BackendRole.ADMIN)
        return await self.persistence.school_list_class_tasks(actor, class_ref, at=utc_now())

    async def list_student_tasks(self, actor: Actor):
        self._require(actor, BackendRole.STUDENT)
        return await self.persistence.school_list_student_tasks(actor, at=utc_now())

    async def list_student_task_history(self, actor: Actor):
        self._require(actor, BackendRole.STUDENT)
        return await self.persistence.school_list_student_task_history(actor, at=utc_now())

    async def list_student_assessments(
        self, actor: Actor, *, limit: int, skip: int, status: str | None
    ):
        self._require(actor, BackendRole.STUDENT)
        subject_refs = set(actor.accessible_subject_ids)
        if actor.subject_id:
            subject_refs.add(actor.subject_id)
        return await self.persistence.school_list_assessment_metadata_for_actor(
            actor, subject_refs, limit=limit, skip=skip, status=status
        )

    async def start_task(
        self, actor: Actor, task_ref: str, *, request_id: str, trace_id: str, idempotency
    ):
        self._require(actor, BackendRole.STUDENT)
        if getattr(self.cat, "label", None) != "REAL_HTTP":
            raise error(ErrorCode.DEPENDENCY_UNAVAILABLE, detail="CAT service is unavailable")
        prepared = await self.persistence.school_prepare_task_session(
            actor,
            task_ref,
            f"ASSESS_{uuid4().hex}",
            at=utc_now(),
            trace_id=trace_id,
            idempotency=idempotency,
        )
        record = await self.assessments.state_for_actor(
            actor,
            prepared["assessment_id"],
            action="assessment:read",
            request_id=request_id,
            trace_id=trace_id,
        )
        return {
            "task_ref": task_ref,
            "assessment_id": record.assessment_id,
            "subject_id": record.subject_id,
            "status": record.assessment["status"],
            "selected_item_id": record.selected_item_id,
            "current_item": record.current_item,
            "answered_count": record.answered_count,
            "administered_count": record.administered_count,
            "can_complete": record.can_complete,
            "max_items": record.max_items,
        }

    async def teacher_progress(self, actor: Actor, class_ref: str | None = None):
        self._require(actor, BackendRole.TEACHER)
        return await self.persistence.school_teacher_progress(actor, class_ref)

    async def revoke_enrollment(
        self, actor: Actor, task_ref: str, enrollment_ref: str, *, idempotency
    ):
        self._require(actor, BackendRole.ADMIN)
        return await self.persistence.school_revoke_enrollment(
            actor, task_ref, enrollment_ref, at=utc_now(), idempotency=idempotency
        )

    async def list_enrollments(self, actor: Actor, task_ref: str):
        self._require(actor, BackendRole.ADMIN)
        return await self.persistence.school_list_task_enrollments(actor, task_ref, at=utc_now())


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise error(ErrorCode.VALIDATION_FAILED, detail="timestamps must include a timezone")
    return value.astimezone(UTC).replace(tzinfo=None)
