"""Safety-first application workflow.

The service owns ordering and publication gates. Specialized algorithms remain
behind CAT, RAG, LLM Runtime, and Safety ports.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from smhai_backend.core.async_utils import maybe_await
from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.request_context import RequestContext
from smhai_backend.domains.audit import AuditService
from smhai_backend.domains.authorization import NativeAuthorizationProvider
from smhai_backend.domains.models import Actor, ReportRecord, ReviewProjection
from smhai_backend.domains.ports import (
    AssessmentRepository,
    ConversationRepository,
    ReportRepository,
    ReviewProjectionRepository,
)
from smhai_backend.integrations.llm import CandidateResponse, LLMRuntimeClient
from smhai_backend.integrations.rag import RagClient, RetrievalResult
from smhai_backend.integrations.safety import SafetyAction, SafetyCheckView, SafetyClient

from .schemas import GenerationContent, RetrievalRequest, SupportRequest, SupportResult


class SupportOrchestrator:
    def __init__(
        self,
        *,
        assessments: AssessmentRepository,
        conversations: ConversationRepository,
        reports: ReportRepository,
        reviews: ReviewProjectionRepository,
        authorization: NativeAuthorizationProvider,
        audit: AuditService,
        safety: SafetyClient,
        rag: RagClient,
        llm: LLMRuntimeClient,
        deadline_seconds: float,
        integration_labels: dict[str, str],
    ) -> None:
        self.assessments = assessments
        self.conversations = conversations
        self.reports = reports
        self.reviews = reviews
        self.authorization = authorization
        self.audit = audit
        self.safety = safety
        self.rag = rag
        self.llm = llm
        self.deadline_seconds = deadline_seconds
        self.integration_labels = dict(integration_labels)
        self.call_order: list[str] = []
        self._active_workflows: dict[str, str] = {}

    async def create(
        self,
        actor: Actor,
        payload: SupportRequest,
        *,
        context: RequestContext,
        generation_id: str | None = None,
        retrieval_id_hint: str | None = None,
        prompt_id: str = "PROMPT_backend_support_v1",
        prompt_version: str = "1.0",
        model_id: str = "MODEL_backend_fake",
        provider_class: str = "mock",
        message_override: str | None = None,
    ) -> SupportResult:
        try:
            async with asyncio.timeout(self.deadline_seconds):
                return await self._create(
                    actor,
                    payload,
                    context=context,
                    generation_id=generation_id,
                    retrieval_id_hint=retrieval_id_hint,
                    prompt_id=prompt_id,
                    prompt_version=prompt_version,
                    model_id=model_id,
                    provider_class=provider_class,
                    message_override=message_override,
                )
        except TimeoutError as exc:
            await self._fail_active_workflow(context, reason_code="DEPENDENCY_TIMEOUT")
            raise error(
                ErrorCode.DEPENDENCY_TIMEOUT,
                status_code=504,
                detail="support dependency deadline exceeded",
                retryable=True,
            ) from exc
        except Exception as exc:
            await self._fail_active_workflow(
                context, reason_code=type(exc).__name__.upper()[:64]
            )
            raise
        finally:
            self._active_workflows.pop(context.trace_id, None)

    async def _create(
        self,
        actor: Actor,
        payload: SupportRequest,
        *,
        context: RequestContext,
        generation_id: str | None,
        retrieval_id_hint: str | None,
        prompt_id: str,
        prompt_version: str,
        model_id: str,
        provider_class: str,
        message_override: str | None,
    ) -> SupportResult:
        record = await maybe_await(self.assessments.get(payload.assessment_id))
        if record is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="assessment not found")
        self.authorization.require(
            actor,
            "support:create",
            resource={"subject_id": record.subject_id, "owner_user_id": actor.user_id},
        )
        if actor.role.value == "STUDENT" and payload.target_role != "student":
            raise error(ErrorCode.FORBIDDEN, detail="access denied")
        if record.assessment.get("status") != "completed":
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="assessment must be completed first")

        generation_id = generation_id or f"GEN_{uuid4().hex}"
        report_id = f"REPORT_{uuid4().hex}"
        message = message_override if message_override is not None else payload.message
        await maybe_await(
            self.conversations.begin_workflow(
                report_id=report_id,
                assessment_id=payload.assessment_id,
                subject_id=record.subject_id,
                target_role=payload.target_role,
                message=message,
                generation_id=generation_id,
                trace_id=context.trace_id,
                request_id=context.request_id,
            )
        )
        self._active_workflows[context.trace_id] = report_id
        safety_context = self._safety_context(
            record.assessment, payload.target_role, message, context
        )

        self.call_order.append("safety_input")
        input_check = await self.safety.check_input(safety_context, context)
        pre_action = input_check.decision.action
        if pre_action not in {"PROCEED", "PROCEED_WITH_BOUNDARY"}:
            result = await self._blocked_result(
                record=record,
                payload=payload,
                generation_id=generation_id,
                report_id=report_id,
                input_check=input_check,
                output_check=None,
                retrieval=None,
                prompt_id=prompt_id,
                prompt_version=prompt_version,
                model_id=model_id,
            )
            await self._store_result(result, record.subject_id, context, actor, message)
            return result

        self.call_order.append("rag")
        retrieval = await self.rag.retrieve(
            assessment=record.assessment,
            target_role=payload.target_role,
            query=message,
            top_k=5,
            trace_id=context.trace_id,
            retrieval_id_hint=retrieval_id_hint,
        )
        self.call_order.append("safety_retrieval")
        retrieval_check = await self.safety.check_retrieval(
            {
                **safety_context,
                "retrieval_metadata": {
                    "retrieval_id": retrieval.retrieval_id,
                    "chunk_count": len(retrieval.chunks),
                },
            },
            [chunk.model_dump(mode="json") for chunk in retrieval.chunks],
            context,
        )
        if retrieval_check.decision.action not in {"PROCEED", "PROCEED_WITH_BOUNDARY"}:
            result = await self._blocked_result(
                record=record,
                payload=payload,
                generation_id=generation_id,
                report_id=report_id,
                input_check=input_check,
                output_check=retrieval_check,
                retrieval=retrieval,
                prompt_id=prompt_id,
                prompt_version=prompt_version,
                model_id=model_id,
            )
            await self._store_result(result, record.subject_id, context, actor, message)
            return result

        prompt = self._build_prompt(payload, message, retrieval)
        self.call_order.append("llm")
        candidate = await self.llm.generate(
            prompt=prompt,
            model_id=model_id,
            provider_class=provider_class,
            trace_id=context.trace_id,
            request_id=context.request_id,
            generation_id=generation_id,
            assessment_id=payload.assessment_id,
            subject_id=record.subject_id,
            target_role=payload.target_role,
            language=payload.language,
            safety_mode="standard",
            retrieval_id=retrieval.retrieval_id,
            chunk_ids=tuple(chunk.chunk_id for chunk in retrieval.chunks),
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            metadata={"synthetic_fixture": True},
        )
        self.call_order.append("safety_output")
        candidate_for_safety = candidate.text
        if "SYNTHETIC_UNSAFE_OUTPUT" in message:
            candidate_for_safety += "\nSYNTHETIC_UNSAFE_OUTPUT"
        output_check = await self.safety.check_output(
            {
                **safety_context,
                "current_user_message": "",
                "generation_metadata": {
                    "candidate_length": len(candidate.text),
                    "candidate_digest": _digest(candidate.text),
                },
            },
            candidate_for_safety,
            context,
        )
        if output_check.decision.action not in {"PROCEED", "PROCEED_WITH_BOUNDARY"}:
            result = await self._blocked_result(
                record=record,
                payload=payload,
                generation_id=generation_id,
                report_id=report_id,
                input_check=input_check,
                output_check=output_check,
                retrieval=retrieval,
                prompt_id=prompt_id,
                prompt_version=prompt_version,
                model_id=model_id,
                candidate=candidate,
            )
            await self._store_result(result, record.subject_id, context, actor, message)
            return result

        try:
            content = GenerationContent.model_validate(json.loads(candidate.text))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                status_code=502,
                detail="LLM Runtime returned invalid structured content",
            ) from exc
        generation = self._generated_result(
            assessment_id=payload.assessment_id,
            generation_id=generation_id,
            target_role=payload.target_role,
            retrieval=retrieval,
            content=content,
            input_check=input_check,
            output_check=output_check,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            candidate=candidate,
        )
        report = ReportRecord(
            report_id=report_id,
            assessment_id=payload.assessment_id,
            subject_id=record.subject_id,
            generation_id=generation_id,
            status="generated",
            generation=generation,
            safety_action=output_check.decision.action,
        )
        await maybe_await(self.reports.save(report))
        await maybe_await(self.conversations.save_metadata(
            request_id=context.request_id,
            trace_id=context.trace_id,
            metadata={
                "support_request": True,
                "message_length": len(message),
                "message_digest": _digest(message),
                "generation_id": generation_id,
                "report_id": report_id,
            },
        ))
        await self.audit.record(
            event="SUPPORT_REQUESTED",
            actor=actor,
            request_id=context.request_id,
            trace_id=context.trace_id,
            outcome="generated",
            metadata={
                "assessment_id": payload.assessment_id,
                "generation_id": generation_id,
                "report_id": report_id,
                "safety_action": output_check.decision.action,
                "citation_count": len(retrieval.chunks),
            },
        )
        result = SupportResult(
            status="generated",
            safety_action=output_check.decision.action,
            normal_generation=True,
            generation=generation,
            report_id=report_id,
            content=content,
            citations=[chunk.citation for chunk in retrieval.chunks],
            trace_id=context.trace_id,
            integration_labels=dict(self.integration_labels),
        )
        await maybe_await(self.conversations.complete_workflow(result))
        return result

    async def retrieve(
        self, actor: Actor, payload: RetrievalRequest, *, context: RequestContext
    ) -> RetrievalResult:
        record = await maybe_await(self.assessments.get(payload.assessment_id))
        if record is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="assessment not found")
        self.authorization.require(
            actor,
            "retrieval:create",
            resource={"subject_id": record.subject_id, "owner_user_id": actor.user_id},
        )
        return await self.rag.retrieve(
            assessment=record.assessment,
            target_role=payload.target_role,
            query=payload.query,
            top_k=payload.top_k,
            trace_id=context.trace_id,
            request_id=context.request_id,
        )

    async def _fail_active_workflow(
        self, context: RequestContext, *, reason_code: str
    ) -> None:
        report_id = self._active_workflows.get(context.trace_id)
        if not report_id:
            return
        fail = getattr(self.conversations, "fail_workflow", None)
        if fail is None:
            return
        try:
            await maybe_await(
                fail(report_id, reason_code=reason_code, trace_id=context.trace_id)
            )
        except Exception:
            # Preserve the original dependency/application error.  The
            # database adapter records this transition independently when it
            # can complete its short failure transaction.
            return

    async def safety_check(
        self,
        actor: Actor,
        assessment_id: str,
        candidate_text: str | None,
        *,
        context: RequestContext,
    ) -> SafetyCheckView:
        record = await maybe_await(self.assessments.get(assessment_id))
        if record is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="assessment not found")
        self.authorization.require(
            actor,
            "safety:check",
            resource={"subject_id": record.subject_id, "owner_user_id": actor.user_id},
        )
        payload = self._safety_context(record.assessment, "student", "", context)
        if candidate_text:
            return await self.safety.check_output(payload, candidate_text, context)
        return await self.safety.check_input(payload, context)

    async def report_for_actor(self, actor: Actor, report_id: str) -> ReportRecord:
        report = await maybe_await(self.reports.get(report_id))
        if report is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="report not found")
        self.authorization.require(
            actor,
            "report:read",
            resource={"subject_id": report.subject_id, "owner_user_id": actor.user_id},
        )
        return report

    async def review(
        self,
        actor: Actor,
        report_id: str,
        decision: str,
        *,
        context: RequestContext,
    ) -> ReviewProjection:
        self.authorization.require(actor, "review:action")
        report = await maybe_await(self.reports.get(report_id))
        if report is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="report not found")
        if not report.review_id:
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="report does not require review")
        projection = await maybe_await(self.reviews.get(report.review_id))
        if projection is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="review not found")
        if projection.status not in {"pending", "in_review"}:
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="review is already closed")
        if projection.safety_review_case_id:
            await self.safety.finalize_review(
                projection.safety_review_case_id, request_context=context
            )
        projection.status = "approved" if decision == "approved" else "rejected"
        projection.updated_at = _timestamp()
        await maybe_await(self.reviews.save(projection))
        report.review_status = projection.status
        report.status = projection.status
        await maybe_await(self.reports.save(report))
        await self.audit.record(
            event="REVIEW_ACTIONED",
            actor=actor,
            request_id=context.request_id,
            trace_id=context.trace_id,
            outcome=projection.status,
            metadata={"report_id": report_id, "review_id": projection.review_id},
        )
        return projection

    async def pending_reviews(self, actor: Actor) -> list[ReviewProjection]:
        self.authorization.require(actor, "review:list")
        return await maybe_await(self.reviews.list_pending())

    async def review_detail(self, actor: Actor, review_id: str) -> ReviewProjection:
        self.authorization.require(actor, "review:read")
        projection = await maybe_await(self.reviews.get(review_id))
        if projection is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="review not found")
        return projection

    async def _blocked_result(
        self,
        *,
        record,
        payload: SupportRequest,
        generation_id: str,
        report_id: str,
        input_check: SafetyCheckView,
        output_check: SafetyCheckView | None,
        retrieval: RetrievalResult | None,
        prompt_id: str,
        prompt_version: str,
        model_id: str,
        candidate: CandidateResponse | None = None,
    ) -> SupportResult:
        check = output_check or input_check
        action = check.decision.action
        review_reference = check.review_reference
        if check.decision.requires_human and review_reference is None:
            review_reference = f"REVIEW_{uuid4().hex}"
        generation = self._blocked_generation(
            assessment_id=payload.assessment_id,
            generation_id=generation_id,
            target_role=payload.target_role,
            action=action,
            reason_codes=_unique(
                [*input_check.decision.reason_codes, *check.decision.reason_codes]
            ),
            retrieval_id=retrieval.retrieval_id if retrieval else "RETR_not_run",
            chunk_ids=[chunk.chunk_id for chunk in retrieval.chunks]
            if retrieval
            else ["CHUNK_not_run"],
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            model_id=model_id,
        )
        report = ReportRecord(
            report_id=report_id,
            assessment_id=payload.assessment_id,
            subject_id=record.subject_id,
            generation_id=generation_id,
            status="needs_review" if check.decision.requires_human else "safety_blocked",
            generation=generation,
            review_id=review_reference,
            review_status="pending" if check.decision.requires_human else "not_required",
            safety_action=action,
        )
        await maybe_await(self.reports.save(report))
        if check.decision.requires_human and review_reference:
            projection = ReviewProjection(
                review_id=review_reference,
                report_id=report_id,
                assessment_id=payload.assessment_id,
                subject_id=record.subject_id,
                generation_id=generation_id,
                status="pending",
                reason_codes=_unique(
                    [*input_check.decision.reason_codes, *check.decision.reason_codes]
                ),
                safety_action=action,
                safety_review_case_id=check.review_reference,
            )
            await maybe_await(self.reviews.save(projection))
        crisis_response = check.crisis_response if action == "CRISIS_ROUTE" else None
        return SupportResult(
            status=report.status,
            safety_action=action,
            normal_generation=False,
            generation=generation,
            report_id=report_id,
            content=None,
            citations=[chunk.citation for chunk in retrieval.chunks] if retrieval else [],
            review_reference=review_reference,
            crisis_response=crisis_response,
            trace_id=input_check.trace_id,
            integration_labels=dict(self.integration_labels),
        )

    async def _store_result(
        self,
        result: SupportResult,
        subject_id: str,
        context: RequestContext,
        actor: Actor,
        message: str,
    ) -> None:
        await maybe_await(self.conversations.complete_workflow(result))
        await maybe_await(self.conversations.save_metadata(
            request_id=context.request_id,
            trace_id=context.trace_id,
            metadata={
                "support_request": True,
                "message_length": len(message),
                "message_digest": _digest(message),
                "generation_id": result.generation["generation_id"],
                "report_id": result.report_id,
                "safety_action": result.safety_action,
                "normal_generation": result.normal_generation,
            },
        ))
        await self.audit.record(
            event="SUPPORT_REQUESTED",
            actor=actor,
            request_id=context.request_id,
            trace_id=context.trace_id,
            outcome=result.safety_action,
            metadata={
                "assessment_id": result.generation.get("provenance", {}).get("assessment_id"),
                "generation_id": result.generation["generation_id"],
                "report_id": result.report_id,
                "review_reference": result.review_reference,
            },
        )

    @staticmethod
    def _safety_context(
        assessment: Mapping[str, Any],
        target_role: str,
        message: str,
        context: RequestContext,
    ) -> dict[str, Any]:
        role_map = {
            "student": "STUDENT",
            "teacher": "TEACHER",
            "parent": "PARENT",
            "admin": "SYSTEM",
        }
        risk = assessment.get("risk", {})
        return {
            "trace_id": context.trace_id,
            "request_id": context.request_id,
            "actor_role": role_map[target_role],
            "age_group": "UNKNOWN",
            "assessment_signals": [
                {
                    "source": "ASSESSMENT",
                    "risk_level": risk.get("level", "unknown"),
                    "need_human_review": bool(risk.get("need_human_review", False)),
                }
            ],
            "current_user_message": message,
            "conversation_metadata": {
                "synthetic_fixture": True,
                "explicit_crisis_signal": "SYNTHETIC_CRISIS_SIGNAL" in message,
            },
            "retrieval_metadata": {},
            "generation_metadata": {},
            "component_health": {},
        }

    @staticmethod
    def _build_prompt(payload: SupportRequest, message: str, retrieval: RetrievalResult) -> str:
        chunk_ids = ",".join(chunk.chunk_id for chunk in retrieval.chunks)
        return (
            "Return JSON only, matching the requested generation schema. "
            "Do not diagnose, assign clinical risk, or invent citations. "
            "education_support; target_role="
            f"{payload.target_role}; message={message}; source_chunk_ids={chunk_ids}"
        )

    @staticmethod
    def _generated_result(
        *,
        assessment_id: str,
        generation_id: str,
        target_role: str,
        retrieval: RetrievalResult,
        content: GenerationContent,
        input_check: SafetyCheckView,
        output_check: SafetyCheckView,
        prompt_id: str,
        prompt_version: str,
        candidate: CandidateResponse,
    ) -> dict[str, Any]:
        reason_codes = _unique(
            [*input_check.decision.reason_codes, *output_check.decision.reason_codes]
        )
        result = {
            "schema_version": "generation.v1",
            "generation_id": generation_id,
            "status": "generated",
            "target_role": target_role,
            "content": content.model_dump(mode="json"),
            "safety": {
                "precheck": _safety_status(input_check.decision.action),
                "postcheck": _safety_status(output_check.decision.action),
                "reason_codes": reason_codes,
                "human_review_required": False,
            },
            "provenance": {
                "assessment_id": assessment_id,
                "retrieval_id": retrieval.retrieval_id,
                "prompt_id": prompt_id,
                "prompt_version": prompt_version,
                "model_id": candidate.model_id,
                "model_version": candidate.model_version,
                "runtime_version": candidate.runtime_version,
            },
            "review": {"status": "not_required", "reviewer_id": None, "reviewed_at": None},
            "created_at": _timestamp(),
        }
        from smhai_backend.integrations.contracts import validate_frozen

        validate_frozen("generation.v1.schema.json", result)
        return result

    @staticmethod
    def _blocked_generation(
        *,
        assessment_id: str,
        generation_id: str,
        target_role: str,
        action: SafetyAction,
        reason_codes: list[str],
        retrieval_id: str,
        chunk_ids: list[str],
        prompt_id: str,
        prompt_version: str,
        model_id: str,
    ) -> dict[str, Any]:
        result = {
            "schema_version": "generation.v1",
            "generation_id": generation_id,
            "status": "needs_review" if action == "REVIEW_REQUIRED" else "safety_blocked",
            "target_role": target_role,
            "content": None,
            "safety": {
                "precheck": _safety_status(action),
                "postcheck": _safety_status(action),
                "reason_codes": _unique(reason_codes),
                "human_review_required": action in {"BLOCK", "REVIEW_REQUIRED", "CRISIS_ROUTE"},
            },
            "provenance": {
                "assessment_id": assessment_id,
                "retrieval_id": retrieval_id,
                "prompt_id": prompt_id,
                "prompt_version": prompt_version,
                "model_id": model_id,
                "model_version": "not_used",
                "runtime_version": "not_used",
            },
            "review": {
                "status": "pending"
                if action in {"BLOCK", "REVIEW_REQUIRED", "CRISIS_ROUTE"}
                else "not_required",
                "reviewer_id": None,
                "reviewed_at": None,
            },
            "created_at": _timestamp(),
        }
        return result


def _safety_status(action: SafetyAction) -> str:
    if action in {"PROCEED", "PROCEED_WITH_BOUNDARY"}:
        return "warn" if action == "PROCEED_WITH_BOUNDARY" else "passed"
    if action == "REVIEW_REQUIRED":
        return "needs_review"
    return "blocked"


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _digest(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()
