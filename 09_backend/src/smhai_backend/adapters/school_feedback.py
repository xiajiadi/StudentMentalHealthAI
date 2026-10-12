"""Encrypted task feedback with current authorization and atomic publication.

Feedback content is separate from professional case notes and measurement data.
This adapter performs no inference or network requests inside its transactions.
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import uuid4

from smhai_backend.adapters.school_professional_reviews import (
    SchoolProfessionalReviewPersistenceAdapter,
    _positive_version,
    _public_id,
    _role_value,
)
from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.request_context import get_request_context
from smhai_backend.domains.support.service import _FORBIDDEN_GENERATED_CLAIMS

_SCHEMA = "school_feedback_content.v1"
_RESOURCE = "school_feedback"


def _missing():
    return error(ErrorCode.RESOURCE_NOT_FOUND, detail="feedback was not found")


class SchoolFeedbackPersistenceAdapter(SchoolProfessionalReviewPersistenceAdapter):
    """Reuse tenant/UOW machinery, with separate feedback scope and records."""

    async def _actor(self, uow, actor, role, now):
        if (
            self.identity_profile != "school_tenant"
            or actor.scope_profile != "school_tenant"
            or _role_value(actor) != role
            or actor.school_id is None
            or not actor.school_ref
        ):
            raise error(ErrorCode.FORBIDDEN, detail="access denied")
        return await self._school_actor_role(uow, actor, role, now, lock=True)

    async def _candidate_case(self, uow, actor, case_ref):
        m = self._db_models
        case_id = _public_id(case_ref, "PCR")
        row = await uow.session.scalar(
            self._select(m.SchoolProfessionalReviewCase).where(
                m.SchoolProfessionalReviewCase.review_ref == case_id,
                m.SchoolProfessionalReviewCase.school_id == actor.school_id,
            )
        )
        if row is None:
            raise _missing()
        return row

    async def _scope(self, uow, actor, case, now, *, student_account_id=None):
        """Lock roster -> enrollment -> class -> task -> subject -> SELF -> case.

        Completion feedback remains readable after a task's due date or closure.
        Explicit roster/enrollment/task/identity revocations still deny access.
        """
        m = self._db_models
        enrollment = await uow.session.scalar(
            self._select(m.TaskEnrollment).where(
                m.TaskEnrollment.id == case.task_enrollment_id,
                m.TaskEnrollment.school_id == actor.school_id,
                m.TaskEnrollment.task_id == case.task_id,
                m.TaskEnrollment.subject_id == case.subject_id,
                m.TaskEnrollment.class_id == case.class_id,
            )
        )
        if enrollment is None:
            raise _missing()
        roster = await uow.session.scalar(
            self._select(m.SchoolClassStudent)
            .where(
                m.SchoolClassStudent.id == enrollment.class_student_id,
                m.SchoolClassStudent.school_id == actor.school_id,
                m.SchoolClassStudent.class_id == case.class_id,
                m.SchoolClassStudent.subject_id == case.subject_id,
                m.SchoolClassStudent.status == "ACTIVE",
                m.SchoolClassStudent.revoked_at.is_(None),
                m.SchoolClassStudent.valid_from <= now,
                (m.SchoolClassStudent.valid_until.is_(None))
                | (m.SchoolClassStudent.valid_until >= now),
            )
            .with_for_update()
        )
        if roster is None:
            raise _missing()
        enrollment = await uow.session.scalar(
            self._select(m.TaskEnrollment)
            .where(
                m.TaskEnrollment.id == enrollment.id,
                m.TaskEnrollment.class_student_id == roster.id,
                m.TaskEnrollment.school_id == actor.school_id,
                m.TaskEnrollment.task_id == case.task_id,
                m.TaskEnrollment.class_id == case.class_id,
                m.TaskEnrollment.subject_id == case.subject_id,
                m.TaskEnrollment.status == "ACTIVE",
                m.TaskEnrollment.revoked_at.is_(None),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        school_class = await uow.session.scalar(
            self._select(m.SchoolClass)
            .where(
                m.SchoolClass.id == case.class_id,
                m.SchoolClass.school_id == actor.school_id,
                m.SchoolClass.status == "ACTIVE",
            )
            .with_for_update()
        )
        task = await uow.session.scalar(
            self._select(m.MeasurementTask)
            .where(
                m.MeasurementTask.id == case.task_id,
                m.MeasurementTask.school_id == actor.school_id,
                m.MeasurementTask.class_id == case.class_id,
                m.MeasurementTask.status.in_(("PUBLISHED", "CLOSED")),
            )
            .with_for_update()
        )
        subject = await uow.session.scalar(
            self._select(m.Subject)
            .where(
                m.Subject.id == case.subject_id,
                m.Subject.school_id == actor.school_id,
                m.Subject.status == self._db_enums.SubjectStatus.ACTIVE.value,
                m.Subject.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
            )
            .with_for_update()
        )
        if any(value is None for value in (enrollment, school_class, task, subject)):
            raise _missing()
        if student_account_id is not None:
            grants = list(
                (
                    await uow.session.scalars(
                        self._select(m.SubjectAccessGrant)
                        .where(
                            m.SubjectAccessGrant.subject_id == case.subject_id,
                            m.SubjectAccessGrant.school_id == actor.school_id,
                            m.SubjectAccessGrant.principal_account_id == student_account_id,
                            m.SubjectAccessGrant.relationship_type == "SELF",
                            m.SubjectAccessGrant.status == "ACTIVE",
                            m.SubjectAccessGrant.revoked_at.is_(None),
                            m.SubjectAccessGrant.valid_from <= now,
                            (m.SubjectAccessGrant.valid_until.is_(None))
                            | (m.SubjectAccessGrant.valid_until >= now),
                        )
                        .with_for_update()
                        .limit(2)
                    )
                ).all()
            )
            if len(grants) != 1:
                raise _missing()
        else:
            await self._active_assignment(uow, actor, task, at=now, lock=True)
        # Reload candidate rows after the locking reads. An ORM identity-map
        # snapshot acquired before a revocation must not become authorization.
        current = await uow.session.scalar(
            self._select(m.SchoolProfessionalReviewCase)
            .where(
                m.SchoolProfessionalReviewCase.id == case.id,
                m.SchoolProfessionalReviewCase.school_id == actor.school_id,
                m.SchoolProfessionalReviewCase.task_id == task.id,
                m.SchoolProfessionalReviewCase.class_id == school_class.id,
                m.SchoolProfessionalReviewCase.task_enrollment_id == enrollment.id,
                m.SchoolProfessionalReviewCase.subject_id == subject.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if current is None:
            raise _missing()
        assessment = await uow.session.scalar(
            self._select(m.AssessmentSession)
            .where(
                m.AssessmentSession.id == current.assessment_session_id,
                m.AssessmentSession.task_enrollment_id == enrollment.id,
                m.AssessmentSession.subject_id == subject.id,
                m.AssessmentSession.status == self._db_enums.AssessmentStatus.COMPLETED.value,
            )
            .with_for_update()
        )
        if assessment is None:
            raise _missing()
        return current, assessment

    async def _feedback(self, uow, actor, feedback_ref, *, case=None):
        _public_id(feedback_ref, "FEED")
        m = self._db_models
        statement = self._select(m.SchoolFeedbackRecord).where(
            m.SchoolFeedbackRecord.feedback_ref == feedback_ref,
            m.SchoolFeedbackRecord.school_id == actor.school_id,
        )
        if case is not None:
            statement = statement.where(m.SchoolFeedbackRecord.review_case_id == case.id)
        row = await uow.session.scalar(
            statement.with_for_update().execution_options(populate_existing=True)
        )
        if row is None:
            raise _missing()
        if case is not None and (
            row.task_id != case.task_id
            or row.class_id != case.class_id
            or row.task_enrollment_id != case.task_enrollment_id
            or row.subject_id != case.subject_id
            or row.assessment_session_id != case.assessment_session_id
        ):
            raise _missing()
        return row

    def _content(self, row):
        from database_layer.crypto import EncryptedPayload

        if (
            row.synthetic_only is not True
            or row.level != "L3"
            or row.payload_schema_version != _SCHEMA
            or row.cipher_format_version != self.protection.cipher_format_version
            or not isinstance(row.payload_ciphertext, bytes)
            or not row.key_version
        ):
            raise error(ErrorCode.DEPENDENCY_INVALID_RESPONSE, detail="feedback is unavailable")
        content = self.protection.decrypt_json(
            EncryptedPayload(
                ciphertext=row.payload_ciphertext,
                cipher_format_version=row.cipher_format_version,
                key_version=row.key_version,
                payload_schema_version=row.payload_schema_version,
            )
        )
        if (
            not isinstance(content, Mapping)
            or set(content) != {"feedback_ref", "content_revision", "title", "body"}
            or content["feedback_ref"] != row.feedback_ref
            or type(content["content_revision"]) is not int
            or content["content_revision"] != row.content_revision
            or not isinstance(content["title"], str)
            or not content["title"].strip()
            or not 1 <= len(content["title"]) <= 120
            or not isinstance(content["body"], str)
            or not content["body"].strip()
            or not 1 <= len(content["body"]) <= 2000
            or _FORBIDDEN_GENERATED_CLAIMS.search(content["title"])
            or _FORBIDDEN_GENERATED_CLAIMS.search(content["body"])
        ):
            raise error(ErrorCode.DEPENDENCY_INVALID_RESPONSE, detail="feedback is unavailable")
        return content

    def _projection(self, row, case, assessment, *, student=False):
        if student and (
            row.status != "PUBLISHED" or row.published_at is None or row.revoked_at is not None
        ):
            raise _missing()
        content = self._content(row)
        result = {
            "feedback_ref": row.feedback_ref,
            "assessment_ref": assessment.assessment_ref,
            "level": "L3",
            "synthetic_only": True,
            "content_revision": row.content_revision,
            "state_version": row.state_version,
            "status": row.status,
            "title": content["title"],
            "body": content["body"],
            "created_at": row.created_at,
            "published_at": row.published_at,
        }
        if not student:
            result.update(
                case_ref=f"PCR_{case.review_ref}",
                case_version=row.case_version,
                revoked_at=row.revoked_at,
            )
        return result

    async def _append(self, uow, row, account_id, role_id, action, previous, trace_id, now):
        event = self._db_models.SchoolFeedbackEvent(
            feedback_id=row.id,
            school_id=row.school_id,
            review_case_id=row.review_case_id,
            content_revision=row.content_revision,
            actor_membership_role_id=role_id,
            event_type=action,
            from_status=previous,
            to_status=row.status,
            state_version=row.state_version,
            trace_id=trace_id,
            created_at=now,
        )
        uow.session.add(event)
        await uow.session.flush()
        await uow.audit.append(
            action=f"school_feedback.{action.lower()}",
            resource_type=_RESOURCE,
            resource_public_id=row.feedback_ref,
            result=self._db_enums.AuditResult.SUCCESS,
            trace_id=trace_id,
            actor_account_id=account_id,
            safe_metadata={
                "source": "school_feedback",
                "state": row.status,
                "count": 1,
            },
        )

    async def _replay_projection(self, uow, row, case, assessment, action, version):
        """Restore the original action result, without changing current visibility."""
        m = self._db_models
        events = list(
            (
                await uow.session.scalars(
                    self._select(m.SchoolFeedbackEvent)
                    .where(
                        m.SchoolFeedbackEvent.feedback_id == row.id,
                        m.SchoolFeedbackEvent.school_id == row.school_id,
                        m.SchoolFeedbackEvent.review_case_id == row.review_case_id,
                        m.SchoolFeedbackEvent.content_revision == row.content_revision,
                        m.SchoolFeedbackEvent.state_version == version,
                        m.SchoolFeedbackEvent.event_type == action,
                    )
                    .limit(2)
                )
            ).all()
        )
        status = {"CREATED": "DRAFT", "PUBLISHED": "PUBLISHED", "REVOKED": "REVOKED"}[action]
        if len(events) != 1 or events[0].to_status != status or row.state_version < version:
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="idempotency result is unavailable")
        projected = self._projection(row, case, assessment)
        projected.update(
            status=status,
            state_version=version,
            published_at=None if action == "CREATED" else row.published_at,
            revoked_at=events[0].created_at if action == "REVOKED" else None,
        )
        return projected

    async def school_feedback_create(
        self, actor, case_ref, *, expected_case_version, title, body, idempotency, trace_id
    ):
        from sqlalchemy import func

        from smhai_backend.domains.school_feedback.schemas import FeedbackDraftRequest

        request = FeedbackDraftRequest(
            expected_case_version=expected_case_version, title=title, body=body
        )
        if _FORBIDDEN_GENERATED_CLAIMS.search(request.title) or _FORBIDDEN_GENERATED_CLAIMS.search(
            request.body
        ):
            raise error(
                ErrorCode.VALIDATION_FAILED,
                detail="synthetic feedback exceeds the supported content scope",
            )
        now = self._utc_now()
        m = self._db_models
        async with self._uow() as uow:
            account_id, role_id = await self._actor(uow, actor, "psychological_specialist", now)
            candidate = await self._candidate_case(uow, actor, case_ref)
            case, assessment = await self._scope(uow, actor, candidate, now)
            claim = await self._school_idempotency_begin(uow, idempotency)
            if claim.replayed:
                ref = await self._receipt_resource(claim, _RESOURCE)
                row = await self._feedback(uow, actor, ref, case=case)
                return await self._replay_projection(uow, row, case, assessment, "CREATED", 1)
            if case.version != request.expected_case_version:
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="review version changed")
            latest = await uow.session.scalar(
                self._select(func.max(m.SchoolFeedbackRecord.content_revision)).where(
                    m.SchoolFeedbackRecord.review_case_id == case.id
                )
            )
            revision = (latest or 0) + 1
            _positive_version(revision)
            ref = f"FEED_{uuid4().hex}"
            encrypted = self.protection.encrypt_json(
                {
                    "feedback_ref": ref,
                    "content_revision": revision,
                    "title": request.title,
                    "body": request.body,
                },
                payload_schema_version=_SCHEMA,
            )
            row = m.SchoolFeedbackRecord(
                feedback_ref=ref,
                review_case_id=case.id,
                school_id=case.school_id,
                task_id=case.task_id,
                class_id=case.class_id,
                task_enrollment_id=case.task_enrollment_id,
                subject_id=case.subject_id,
                assessment_session_id=case.assessment_session_id,
                content_revision=revision,
                state_version=1,
                case_version=case.version,
                status="DRAFT",
                level="L3",
                synthetic_only=True,
                payload_ciphertext=encrypted.ciphertext,
                cipher_format_version=encrypted.cipher_format_version,
                key_version=encrypted.key_version,
                payload_schema_version=encrypted.payload_schema_version,
                retention_due_at=case.retention_due_at,
                created_at=now,
                updated_at=now,
            )
            uow.session.add(row)
            await uow.session.flush()
            await self._append(uow, row, account_id, role_id, "CREATED", None, trace_id, now)
            await self._school_idempotency_complete(
                uow, claim, resource_type=_RESOURCE, result_ref=ref
            )
            return self._projection(row, case, assessment)

    async def _transition(
        self,
        actor,
        feedback_ref,
        *,
        expected_case_version,
        expected_state_version,
        idempotency,
        trace_id,
        publish,
    ):
        expected_case_version = _positive_version(expected_case_version)
        expected_state_version = _positive_version(expected_state_version)
        _public_id(feedback_ref, "FEED")
        now = self._utc_now()
        m = self._db_models
        async with self._uow() as uow:
            account_id, role_id = await self._actor(uow, actor, "psychological_specialist", now)
            # Candidate lookup is nonlocking; acquire the shared scope lock order
            # before locking a feedback revision or idempotency receipt.
            candidate = await uow.session.scalar(
                self._select(m.SchoolProfessionalReviewCase)
                .join(
                    m.SchoolFeedbackRecord,
                    m.SchoolFeedbackRecord.review_case_id == m.SchoolProfessionalReviewCase.id,
                )
                .where(
                    m.SchoolFeedbackRecord.feedback_ref == feedback_ref,
                    m.SchoolFeedbackRecord.school_id == actor.school_id,
                    m.SchoolProfessionalReviewCase.school_id == actor.school_id,
                )
            )
            if candidate is None:
                raise _missing()
            case, assessment = await self._scope(uow, actor, candidate, now)
            row = await self._feedback(uow, actor, feedback_ref, case=case)
            claim = await self._school_idempotency_begin(uow, idempotency)
            if claim.replayed:
                if await self._receipt_resource(claim, _RESOURCE) != feedback_ref:
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT, detail="idempotency result is unavailable"
                    )
                return await self._replay_projection(
                    uow,
                    row,
                    case,
                    assessment,
                    "PUBLISHED" if publish else "REVOKED",
                    expected_state_version + 1,
                )
            if case.version != expected_case_version or row.state_version != expected_state_version:
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="feedback version changed")
            if publish:
                if (
                    row.status != "DRAFT"
                    or case.status != "APPROVED"
                    or row.case_version != case.version
                ):
                    raise error(
                        ErrorCode.WORKFLOW_CONFLICT, detail="feedback is not ready for publication"
                    )
                self._content(row)
                row.status = "PUBLISHED"
                row.published_at = now
                action = "PUBLISHED"
                previous = "DRAFT"
            else:
                if row.status != "PUBLISHED":
                    raise error(ErrorCode.WORKFLOW_CONFLICT, detail="feedback cannot be revoked")
                row.status = "REVOKED"
                row.revoked_at = now
                action = "REVOKED"
                previous = "PUBLISHED"
            row.state_version += 1
            _positive_version(row.state_version)
            row.updated_at = now
            await uow.session.flush()
            await self._append(uow, row, account_id, role_id, action, previous, trace_id, now)
            await self._school_idempotency_complete(
                uow, claim, resource_type=_RESOURCE, result_ref=feedback_ref
            )
            return self._projection(row, case, assessment)

    async def school_feedback_publish(self, actor, feedback_ref, **kwargs):
        return await self._transition(actor, feedback_ref, publish=True, **kwargs)

    async def school_feedback_revoke(self, actor, feedback_ref, **kwargs):
        return await self._transition(actor, feedback_ref, publish=False, **kwargs)

    async def school_feedback_list_cases(self, actor, case_ref, *, offset=0, limit=50):
        from sqlalchemy import func

        m = self._db_models
        now = self._utc_now()
        async with self._uow() as uow:
            await self._actor(uow, actor, "psychological_specialist", now)
            candidate = await self._candidate_case(uow, actor, case_ref)
            case, assessment = await self._scope(uow, actor, candidate, now)
            base = self._select(m.SchoolFeedbackRecord).where(
                m.SchoolFeedbackRecord.review_case_id == case.id,
                m.SchoolFeedbackRecord.school_id == actor.school_id,
            )
            total = int(
                await uow.session.scalar(self._select(func.count()).select_from(base.subquery()))
                or 0
            )
            rows = list(
                (
                    await uow.session.scalars(
                        base.order_by(m.SchoolFeedbackRecord.content_revision.desc())
                        .offset(offset)
                        .limit(limit)
                    )
                ).all()
            )
            return {
                "items": [self._projection(row, case, assessment) for row in rows],
                "total": total,
            }

    def _student_candidates(self, actor, account_id, now):
        """Return only refs whose scope and SELF grant are currently visible."""
        m = self._db_models
        return (
            self._select(m.SchoolFeedbackRecord.feedback_ref)
            .join(
                m.SchoolProfessionalReviewCase,
                m.SchoolProfessionalReviewCase.id == m.SchoolFeedbackRecord.review_case_id,
            )
            .join(
                m.TaskEnrollment, m.TaskEnrollment.id == m.SchoolFeedbackRecord.task_enrollment_id
            )
            .join(
                m.SchoolClassStudent, m.SchoolClassStudent.id == m.TaskEnrollment.class_student_id
            )
            .join(m.SchoolClass, m.SchoolClass.id == m.SchoolFeedbackRecord.class_id)
            .join(m.MeasurementTask, m.MeasurementTask.id == m.SchoolFeedbackRecord.task_id)
            .join(m.Subject, m.Subject.id == m.SchoolFeedbackRecord.subject_id)
            .join(m.SubjectAccessGrant, m.SubjectAccessGrant.subject_id == m.Subject.id)
            .join(
                m.AssessmentSession,
                m.AssessmentSession.id == m.SchoolFeedbackRecord.assessment_session_id,
            )
            .where(
                m.SchoolFeedbackRecord.school_id == actor.school_id,
                m.SchoolFeedbackRecord.status == "PUBLISHED",
                m.SchoolFeedbackRecord.revoked_at.is_(None),
                m.SchoolFeedbackRecord.published_at.is_not(None),
                m.TaskEnrollment.status == "ACTIVE",
                m.TaskEnrollment.revoked_at.is_(None),
                m.SchoolClassStudent.status == "ACTIVE",
                m.SchoolClassStudent.revoked_at.is_(None),
                m.SchoolClassStudent.valid_from <= now,
                (m.SchoolClassStudent.valid_until.is_(None))
                | (m.SchoolClassStudent.valid_until >= now),
                m.SchoolClass.status == "ACTIVE",
                m.MeasurementTask.status.in_(("PUBLISHED", "CLOSED")),
                m.Subject.status == self._db_enums.SubjectStatus.ACTIVE.value,
                m.Subject.data_origin == self._db_enums.DataOrigin.SYNTHETIC.value,
                m.SubjectAccessGrant.school_id == actor.school_id,
                m.SubjectAccessGrant.principal_account_id == account_id,
                m.SubjectAccessGrant.relationship_type == "SELF",
                m.SubjectAccessGrant.status == "ACTIVE",
                m.SubjectAccessGrant.revoked_at.is_(None),
                m.SubjectAccessGrant.valid_from <= now,
                (m.SubjectAccessGrant.valid_until.is_(None))
                | (m.SubjectAccessGrant.valid_until >= now),
                m.AssessmentSession.status == self._db_enums.AssessmentStatus.COMPLETED.value,
            )
            .distinct()
        )

    async def _student_read(self, uow, actor, account_id, feedback_ref, now):
        m = self._db_models
        _public_id(feedback_ref, "FEED")
        candidate = await uow.session.scalar(
            self._select(m.SchoolProfessionalReviewCase)
            .join(
                m.SchoolFeedbackRecord,
                m.SchoolFeedbackRecord.review_case_id == m.SchoolProfessionalReviewCase.id,
            )
            .where(
                m.SchoolFeedbackRecord.feedback_ref == feedback_ref,
                m.SchoolFeedbackRecord.school_id == actor.school_id,
                m.SchoolProfessionalReviewCase.school_id == actor.school_id,
            )
        )
        if candidate is None:
            raise _missing()
        case, assessment = await self._scope(
            uow, actor, candidate, now, student_account_id=account_id
        )
        row = await self._feedback(uow, actor, feedback_ref, case=case)
        return self._projection(row, case, assessment, student=True)

    async def school_feedback_list_student(self, actor, *, offset=0, limit=50):
        from sqlalchemy import func

        m = self._db_models
        now = self._utc_now()
        async with self._uow() as uow:
            account_id, _ = await self._actor(uow, actor, "student", now)
            base = self._student_candidates(actor, account_id, now)
            total = int(
                await uow.session.scalar(self._select(func.count()).select_from(base.subquery()))
                or 0
            )
            refs = list(
                (
                    await uow.session.scalars(
                        base.order_by(m.SchoolFeedbackRecord.feedback_ref.desc())
                        .offset(offset)
                        .limit(limit)
                    )
                ).all()
            )
            items = [await self._student_read(uow, actor, account_id, ref, now) for ref in refs]
            return {"items": items, "total": total}

    async def school_feedback_read_student(self, actor, feedback_ref):
        now = self._utc_now()
        async with self._uow() as uow:
            account_id, _ = await self._actor(uow, actor, "student", now)
            result = await self._student_read(uow, actor, account_id, feedback_ref, now)
            await uow.audit.append(
                action="school_feedback.student_read",
                resource_type=_RESOURCE,
                resource_public_id=feedback_ref,
                result=self._db_enums.AuditResult.SUCCESS,
                trace_id=get_request_context().trace_id,
                actor_account_id=account_id,
                safe_metadata={"source": "school_feedback", "state": "PUBLISHED", "count": 1},
            )
            return result
