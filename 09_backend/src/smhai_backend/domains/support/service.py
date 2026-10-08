"""Safety-first application workflow.

The service owns ordering and publication gates. Specialized algorithms remain
behind CAT, RAG, LLM Runtime, and Safety ports.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from structlog.contextvars import bind_contextvars, clear_contextvars, get_contextvars

from smhai_backend.core.async_utils import maybe_await
from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.logging import logger
from smhai_backend.core.orchestration import OrchestrationStage, StageLedger
from smhai_backend.core.request_context import RequestContext
from smhai_backend.core.support_diagnostics import (
    SupportDiagnosticComponent,
    SupportDiagnosticFailureCode,
    SupportDiagnosticStage,
    SupportWorkflowDiagnostics,
    failure_code_for_exception,
)
from smhai_backend.core.trusted_context import (
    TrustedContextError,
    derive_trusted_request_context,
)
from smhai_backend.domains.assessment.binding import (
    AssessmentBindingError,
    bind_assessment,
)
from smhai_backend.domains.assessment.service import AssessmentService
from smhai_backend.domains.audit import AuditService
from smhai_backend.domains.authorization import NativeAuthorizationProvider
from smhai_backend.domains.models import Actor, BackendRole, ReportRecord, ReviewProjection
from smhai_backend.domains.ports import (
    ConversationRepository,
    ReportRepository,
    ReviewProjectionRepository,
)
from smhai_backend.integrations.d3 import (
    D3CompositionError,
    default_fixture_config,
    retrieval_eligibility_population,
    server_model_reference,
)
from smhai_backend.integrations.d3_chain import (
    D3ChainError,
    compose_d3_chain,
    interpret_d3_chain,
)
from smhai_backend.integrations.evidence import (
    CitationBindingError,
    EligibilityPolicy,
    RetrievalEvidenceBundle,
    build_retrieval_evidence_bundle,
)
from smhai_backend.integrations.llm import CandidateResponse, LLMRuntimeClient
from smhai_backend.integrations.rag import RagClient, RetrievalResult
from smhai_backend.integrations.safety import SafetyAction, SafetyCheckView, SafetyClient

from .schemas import (
    GenerationContent,
    GenerationProjection,
    RetrievalRequest,
    SupportCitation,
    SupportRequest,
    SupportResult,
)

_FORBIDDEN_GENERATED_CLAIMS = re.compile(
    r"(?i)(?<![A-Za-z])(?:theta|se|score|band|severity|clinical|diagnos(?:is|tic)?)(?![A-Za-z])|诊断"
)


class SupportOrchestrator:
    def __init__(
        self,
        *,
        assessments: AssessmentService,
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
        self.d3_call_order: list[str] = []
        self.stage_ledgers: dict[str, Any] = {}
        self._active_workflows: dict[str, str] = {}
        self._workflow_diagnostics: dict[str, SupportWorkflowDiagnostics] = {}
        self._d3_fixtures = default_fixture_config()

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
        subject_id_assertion: str | None = None,
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
                    subject_id_assertion=subject_id_assertion,
                )
        except TimeoutError as exc:
            await self._fail_active_workflow(
                context,
                reason_code="DEPENDENCY_TIMEOUT",
                failure_code=SupportDiagnosticFailureCode.DEPENDENCY_TIMEOUT,
            )
            raise error(
                ErrorCode.DEPENDENCY_TIMEOUT,
                status_code=504,
                detail="support dependency deadline exceeded",
                retryable=True,
            ) from exc
        except Exception as exc:
            await self._fail_active_workflow(
                context,
                reason_code=type(exc).__name__.upper()[:64],
                failure=exc,
            )
            raise
        finally:
            self._active_workflows.pop(context.trace_id, None)
            self._workflow_diagnostics.pop(context.trace_id, None)

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
        subject_id_assertion: str | None,
    ) -> SupportResult:
        record = await self.assessments.get_for_actor(
            actor,
            payload.assessment_id,
            action="support:create",
            request_id=context.request_id,
            trace_id=context.trace_id,
        )
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
        diagnostics = SupportWorkflowDiagnostics(
            last_confirmed_stage=SupportDiagnosticStage.WORKFLOW_REQUESTED
        )
        self._workflow_diagnostics[context.trace_id] = diagnostics

        # The verified session Actor and persisted assessment are authoritative.
        # Request fields are intent/assertions and cannot select D3 policy,
        # retrieval, model, role, relationship, or disclosure authority.
        diagnostics.begin(
            SupportDiagnosticStage.REQUEST_AUTHORIZATION,
            SupportDiagnosticComponent.BACKEND,
        )
        try:
            trusted_context = derive_trusted_request_context(
                actor,
                record,
                request=payload,
                target_role=payload.target_role,
                transaction_id=f"TX_{context.trace_id.removeprefix('TRACE_')}",
                request_id=context.request_id,
                trace_id=context.trace_id,
            )
        except TrustedContextError as exc:
            raise error(ErrorCode.FORBIDDEN, detail="request authorization failed") from exc
        diagnostics.confirm()

        ledger = StageLedger(trusted_context)
        self.stage_ledgers[context.trace_id] = ledger
        ledger.advance(
            OrchestrationStage.REQUEST_AUTHENTICATED,
            metadata={"principal_id": trusted_context.principal_id},
        )
        ledger.advance(
            OrchestrationStage.REQUEST_AUTHORIZED,
            metadata={
                "product_role": trusted_context.product_role.value,
                "subject_id": trusted_context.subject_id,
                "audience_role": trusted_context.audience_role.value,
            },
        )

        safety_context = self._safety_context(
            record.assessment, payload.target_role, message, context
        )

        self.call_order.append("safety_input")
        diagnostics.begin(
            SupportDiagnosticStage.INPUT_SAFETY,
            SupportDiagnosticComponent.INPUT_SAFETY,
        )
        input_check = await self.safety.check_input(safety_context, context)
        pre_action = input_check.decision.action
        ledger.advance(
            OrchestrationStage.INPUT_SAFETY_EVALUATED,
            metadata={"reason_codes": tuple(input_check.decision.reason_codes)},
            safety_action=pre_action,
        )
        diagnostics.confirm()
        if pre_action not in {"PROCEED", "PROCEED_WITH_BOUNDARY"}:
            diagnostics.begin(
                SupportDiagnosticStage.BLOCKED_RESULT_PROJECTION,
                SupportDiagnosticComponent.BACKEND,
            )
            result = await self._blocked_result(
                record=record,
                payload=payload,
                generation_id=generation_id,
                report_id=report_id,
                input_check=input_check,
                output_check=None,
                retrieval=None,
                bundle=None,
                prompt_id="PROMPT_not_run",
                prompt_version="not_run",
                model_id=None,
            )
            diagnostics.confirm()
            diagnostics.begin(
                SupportDiagnosticStage.REPORT_PERSISTENCE,
                SupportDiagnosticComponent.DATABASE,
            )
            await self._store_result(
                result,
                record.subject_id,
                context,
                actor,
                message,
                audit_metadata={"actor_scope": "subject_bound", "synthetic_fixture_only": True},
            )
            diagnostics.confirm()
            return result

        try:
            diagnostics.begin(
                SupportDiagnosticStage.ASSESSMENT_BINDING,
                SupportDiagnosticComponent.ASSESSMENT,
            )
            binding = bind_assessment(
                actor,
                record,
                assessment_id=payload.assessment_id,
                requested_assessment_id=payload.assessment_id,
                subject_id_assertion=subject_id_assertion,
                trusted_context=trusted_context,
                transaction_id=trusted_context.transaction_id,
                request_id=context.request_id,
                trace_id=context.trace_id,
                compatibility_fixtures=self._d3_fixtures.assessment_fixtures,
            )
        except AssessmentBindingError as exc:
            if exc.code == "ASSESSMENT_NOT_FOUND":
                raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="assessment not found") from exc
            if exc.code in {"SUBJECT_SCOPE_DENIED", "TRUSTED_CONTEXT_MISMATCH"}:
                raise error(ErrorCode.FORBIDDEN, detail="assessment access denied") from exc
            raise error(
                ErrorCode.WORKFLOW_CONFLICT,
                detail="assessment is not eligible for this support workflow",
            ) from exc
        ledger.advance(
            OrchestrationStage.ASSESSMENT_BOUND,
            metadata={
                "assessment_id": binding.assessment_id,
                "assessment_hash": binding.assessment_hash,
                "instrument_id": binding.instrument_id,
                "instrument_version": binding.instrument_version,
                "compatibility_fixture_id": binding.compatibility_fixture_id,
                "compatibility_fixture_version": binding.compatibility_fixture_version,
                "compatibility_approval_reference": binding.compatibility_approval_reference,
            },
        )
        diagnostics.confirm()

        try:
            # D3-2 is intentionally completed before any RAG side effect.  The
            # typed result is carried through the same transaction and reused
            # by the later D3-3/D3-1 composition phase.
            diagnostics.begin(
                SupportDiagnosticStage.ASSESSMENT_INTERPRETATION,
                SupportDiagnosticComponent.D3,
            )
            interpretation = interpret_d3_chain(trusted_context, binding, ledger)
            self.d3_call_order.append("d3_2")
            self.call_order.append("d3_2")
            diagnostics.confirm()
        except (D3ChainError, D3CompositionError, ValueError) as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                status_code=502,
                detail="accepted assessment interpretation could not be composed",
            ) from exc

        self.call_order.append("rag")
        diagnostics.begin(
            SupportDiagnosticStage.RAG_RETRIEVAL,
            SupportDiagnosticComponent.RAG,
        )
        retrieval = await self.rag.retrieve(
            assessment=record.assessment,
            target_role=payload.target_role,
            query=message,
            top_k=5,
            trace_id=context.trace_id,
            # A caller supplied retrieval reference is never authoritative for
            # generation.  Always retrieve and bind a fresh result here.
            retrieval_id_hint=None,
            request_id=context.request_id,
        )
        diagnostics.confirm()
        self.call_order.append("safety_retrieval")
        diagnostics.begin(
            SupportDiagnosticStage.RETRIEVAL_SAFETY,
            SupportDiagnosticComponent.RETRIEVAL_SAFETY,
        )
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
        diagnostics.confirm()
        if retrieval_check.decision.action not in {"PROCEED", "PROCEED_WITH_BOUNDARY"}:
            ledger.abort(
                retrieval_check.decision.action,
                reason="retrieval Safety stopped the generation path",
            )
            diagnostics.begin(
                SupportDiagnosticStage.BLOCKED_RESULT_PROJECTION,
                SupportDiagnosticComponent.BACKEND,
            )
            result = await self._blocked_result(
                record=record,
                payload=payload,
                generation_id=generation_id,
                report_id=report_id,
                input_check=input_check,
                output_check=retrieval_check,
                retrieval=retrieval,
                bundle=None,
                prompt_id="PROMPT_not_run",
                prompt_version="not_run",
                model_id=None,
            )
            diagnostics.confirm()
            diagnostics.begin(
                SupportDiagnosticStage.REPORT_PERSISTENCE,
                SupportDiagnosticComponent.DATABASE,
            )
            await self._store_result(
                result,
                record.subject_id,
                context,
                actor,
                message,
                audit_metadata={"actor_scope": "subject_bound", "synthetic_fixture_only": True},
            )
            diagnostics.confirm()
            return result

        risk = record.assessment.get("risk")
        risk_level = risk.get("level") if isinstance(risk, Mapping) else None
        try:
            diagnostics.begin(
                SupportDiagnosticStage.EVIDENCE_BUNDLE,
                SupportDiagnosticComponent.EVIDENCE,
            )
            retrieval_population = retrieval_eligibility_population(
                retrieval, config=self._d3_fixtures
            )
            bundle = build_retrieval_evidence_bundle(
                retrieval,
                transaction_id=trusted_context.transaction_id,
                request_id=trusted_context.request_id,
                trace_id=trusted_context.trace_id,
                policy=EligibilityPolicy(
                    target_population=retrieval_population,
                    target_role=payload.target_role,
                    risk_level=str(risk_level) if isinstance(risk_level, str) else None,
                ),
                # Empty success responses must be retained long enough to
                # classify them as deterministic abstentions. Non-empty
                # evidence continues to use the strict generation gate.
                strict_eligibility=bool(retrieval.chunks),
            )
            diagnostics.confirm()
            if not bundle.items:
                ledger.advance(
                    OrchestrationStage.RETRIEVAL_BOUND,
                    metadata={
                        "retrieval_id": bundle.retrieval_id,
                        "bundle_hash": bundle.bundle_hash,
                        "eligibility_reason_codes": ["NO_ELIGIBLE_EVIDENCE"],
                    },
                    safety_action=retrieval_check.decision.action,
                )
                diagnostics.begin(
                    SupportDiagnosticStage.ABSTENTION_RESULT_PROJECTION,
                    SupportDiagnosticComponent.BACKEND,
                )
                result = await self._abstained_result(
                    record=record,
                    payload=payload,
                    generation_id=generation_id,
                    report_id=report_id,
                    retrieval=retrieval,
                    input_check=input_check,
                    retrieval_check=retrieval_check,
                )
                diagnostics.confirm()
                diagnostics.begin(
                    SupportDiagnosticStage.REPORT_PERSISTENCE,
                    SupportDiagnosticComponent.DATABASE,
                )
                await self._store_result(
                    result,
                    record.subject_id,
                    context,
                    actor,
                    message,
                    audit_metadata={
                        "actor_scope": "subject_bound",
                        "synthetic_fixture_only": True,
                        "abstention_reason_code": "NO_ELIGIBLE_EVIDENCE",
                        "input_safety_action": input_check.decision.action,
                        "retrieval_safety_action": retrieval_check.decision.action,
                    },
                )
                diagnostics.confirm()
                ledger.abstain(reason_code="NO_ELIGIBLE_EVIDENCE")
                return result

            diagnostics.begin(
                SupportDiagnosticStage.EVIDENCE_BUNDLE,
                SupportDiagnosticComponent.EVIDENCE,
            )
            bundle.require_eligible()
            diagnostics.confirm()
            diagnostics.begin(
                SupportDiagnosticStage.D3_COMPOSITION,
                SupportDiagnosticComponent.D3,
            )
            d3_result = compose_d3_chain(
                trusted_context,
                binding,
                ledger,
                bundle,
                generation_id=generation_id,
                retrieval_safety_action=retrieval_check.decision.action,
                interpretation=interpretation,
            )
            # Keep integration observability in the Backend-owned orchestrator;
            # the accepted D3 chain remains a stable typed API.
            self.d3_call_order.extend(("d3_3", "d3_1"))
            diagnostics.confirm()
        except (D3ChainError, D3CompositionError, ValueError) as exc:
            # Never fall back to the legacy raw prompt or Runtime path when a
            # trusted D3 seam or evidence policy refuses the request.
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                status_code=502,
                detail="accepted generation policy could not compose this request",
            ) from exc

        diagnostics.begin(
            SupportDiagnosticStage.PROMPT_VALIDATION,
            SupportDiagnosticComponent.BACKEND,
        )
        rendered_text = getattr(d3_result.rendered_prompt, "rendered_text", None)
        if not isinstance(rendered_text, str) or not rendered_text:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                status_code=502,
                detail="accepted prompt engine returned an invalid prompt",
            )
        diagnostics.confirm()
        try:
            diagnostics.begin(
                SupportDiagnosticStage.MODEL_POLICY,
                SupportDiagnosticComponent.BACKEND,
            )
            server_model_id, server_provider_class = server_model_reference(
                str(getattr(self.llm, "label", "CONTRACT_FAKE"))
            )
        except D3CompositionError as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                status_code=502,
                detail="model policy is unavailable",
            ) from exc
        diagnostics.confirm()

        diagnostics.begin(
            SupportDiagnosticStage.LLM_RUNTIME,
            SupportDiagnosticComponent.LLM_RUNTIME,
        )
        candidate = await self.llm.generate(
            prompt=rendered_text,
            model_id=server_model_id,
            provider_class=server_provider_class,
            trace_id=context.trace_id,
            request_id=context.request_id,
            generation_id=generation_id,
            assessment_id=payload.assessment_id,
            subject_id=trusted_context.subject_id,
            target_role=payload.target_role,
            language=payload.language,
            safety_mode="standard",
            retrieval_id=bundle.retrieval_id,
            chunk_ids=bundle.chunk_ids,
            prompt_id=d3_result.template.prompt_id,
            prompt_version=d3_result.template.prompt_version,
            metadata={"synthetic_fixture": True, "bundle_hash": bundle.bundle_hash},
        )
        diagnostics.confirm()
        if not self.call_order or self.call_order[-1] != "llm":
            self.call_order.append("llm")
        self.call_order.append("safety_output")
        candidate_for_safety = candidate.text
        if "SYNTHETIC_UNSAFE_OUTPUT" in message:
            candidate_for_safety += "\nSYNTHETIC_UNSAFE_OUTPUT"
        ledger.advance(
            OrchestrationStage.GENERATION_BUFFERED,
            metadata={
                "runtime_label": candidate.label,
                "model_id": candidate.model_id,
                "model_version": candidate.model_version,
                "runtime_version": candidate.runtime_version,
            },
        )
        diagnostics.begin(
            SupportDiagnosticStage.OUTPUT_SAFETY,
            SupportDiagnosticComponent.OUTPUT_SAFETY,
        )
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
        ledger.advance(
            OrchestrationStage.OUTPUT_SAFETY_EVALUATED,
            metadata={"reason_codes": tuple(output_check.decision.reason_codes)},
            safety_action=output_check.decision.action,
        )
        diagnostics.confirm()
        if output_check.decision.action not in {"PROCEED", "PROCEED_WITH_BOUNDARY"}:
            diagnostics.begin(
                SupportDiagnosticStage.BLOCKED_RESULT_PROJECTION,
                SupportDiagnosticComponent.BACKEND,
            )
            result = await self._blocked_result(
                record=record,
                payload=payload,
                generation_id=generation_id,
                report_id=report_id,
                input_check=input_check,
                output_check=output_check,
                retrieval=retrieval,
                bundle=bundle,
                prompt_id=d3_result.template.prompt_id,
                prompt_version=d3_result.template.prompt_version,
                model_id=candidate.model_id,
                candidate=candidate,
            )
            diagnostics.confirm()
            diagnostics.begin(
                SupportDiagnosticStage.REPORT_PERSISTENCE,
                SupportDiagnosticComponent.DATABASE,
            )
            await self._store_result(
                result,
                record.subject_id,
                context,
                actor,
                message,
                audit_metadata={
                    "actor_scope": "subject_bound",
                    "synthetic_fixture_only": True,
                    "bundle_hash": bundle.bundle_hash,
                    "evidence_ids": [item.evidence_id for item in bundle.items],
                },
            )
            diagnostics.confirm()
            return result

        diagnostics.begin(
            SupportDiagnosticStage.CONTENT_VALIDATION,
            SupportDiagnosticComponent.BACKEND,
        )
        try:
            content = GenerationContent.model_validate(json.loads(candidate.text))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                status_code=502,
                detail="LLM Runtime returned invalid structured content",
            ) from exc
        diagnostics.confirm()
        diagnostics.begin(
            SupportDiagnosticStage.CLAIM_BOUNDARY,
            SupportDiagnosticComponent.BACKEND,
        )
        if _contains_forbidden_generated_claim(content):
            ledger.abort(
                "BLOCK",
                reason="generated content crossed the Backend psychological-claim boundary",
            )
            try:
                _log_generation_boundary_rejection(
                    request_id=context.request_id,
                    trace_id=context.trace_id,
                    generation_id=generation_id,
                    candidate_text=candidate.text,
                    output_safety_action=output_check.decision.action,
                    content=content,
                )
            except Exception:
                # Diagnostic failure must never turn a rejected candidate into
                # a published result or replace the established 502 response.
                pass
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                status_code=502,
                detail="LLM Runtime returned content outside the approved generation boundary",
            )
        diagnostics.confirm()
        diagnostics.begin(
            SupportDiagnosticStage.CITATION_BINDING,
            SupportDiagnosticComponent.EVIDENCE,
        )
        try:
            citations = self._citations_from_bundle(bundle, content)
        except CitationBindingError as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                status_code=502,
                detail="LLM Runtime returned an unbound citation",
            ) from exc
        diagnostics.confirm()
        generation = self._generated_result(
            assessment_id=payload.assessment_id,
            generation_id=generation_id,
            target_role=payload.target_role,
            retrieval=retrieval,
            content=content,
            input_check=input_check,
            output_check=output_check,
            prompt_id=d3_result.template.prompt_id,
            prompt_version=d3_result.template.prompt_version,
            candidate=candidate,
        )
        candidate_source = (
            "CONTROLLED_SYNTHETIC" if candidate.label == "CONTRACT_FAKE" else "MODEL_EXECUTED"
        )
        generation_projection = _candidate_generation(
            generation,
            generation_status="EXECUTED",
            candidate_source=candidate_source,
        )
        report = ReportRecord(
            report_id=report_id,
            assessment_id=payload.assessment_id,
            subject_id=record.subject_id,
            generation_id=generation_id,
            status="generated",
            generation=generation_projection.model_dump(mode="json"),
            safety_action=output_check.decision.action,
            citations=[item.model_dump(mode="json") for item in citations],
            candidate_source=candidate_source,
        )
        diagnostics.begin(
            SupportDiagnosticStage.REPORT_PERSISTENCE,
            SupportDiagnosticComponent.DATABASE,
        )
        await maybe_await(
            self.conversations.save_metadata(
                request_id=context.request_id,
                trace_id=context.trace_id,
                metadata={
                    "support_request": True,
                    "message_length": len(message),
                    "message_digest": _digest(message),
                    "generation_id": generation_id,
                    "report_id": report_id,
                },
            )
        )
        await self.audit.record(
            event="SUPPORT_REQUESTED",
            actor=actor,
            request_id=context.request_id,
            trace_id=context.trace_id,
            outcome="generated",
            metadata={
                "transaction_id": trusted_context.transaction_id,
                "context_id": trusted_context.context_id,
                "principal_id": trusted_context.principal_id,
                "subject_id": trusted_context.subject_id,
                "stage": ledger.current.value if ledger.current else None,
                "assessment_id": payload.assessment_id,
                "generation_id": generation_id,
                "report_id": report_id,
                "input_safety_action": input_check.decision.action,
                "safety_action": output_check.decision.action,
                "citation_count": len(citations),
                "retrieval_id": bundle.retrieval_id,
                "chunk_ids": list(bundle.chunk_ids),
                "bundle_hash": bundle.bundle_hash,
                "evidence_ids": [item.evidence_id for item in bundle.items],
                "actor_scope": "subject_bound",
                "synthetic_fixture_only": True,
                "content_population_mapping_id": d3_result.content_population_mapping.mapping_id,
                "content_population_mapping_version": (
                    d3_result.content_population_mapping.mapping_version
                ),
                "content_population": d3_result.content_population_mapping.target_population,
                "d3_2_policy_id": d3_result.assessment_policy.policy_id,
                "d3_2_policy_version": d3_result.assessment_policy.policy_version,
                "d3_2_policy_hash": d3_result.assessment_policy.policy_hash,
                "d3_3_policy_id": d3_result.role_policy.policy_id,
                "d3_3_policy_version": d3_result.role_policy.policy_version,
                "d3_3_policy_hash": d3_result.role_policy.policy_hash,
                "d3_1_prompt_id": d3_result.template.prompt_id,
                "d3_1_prompt_version": d3_result.template.prompt_version,
                "d3_1_prompt_hash": d3_result.template.content_hash,
                "runtime_label": candidate.label,
                "runtime_model_id": candidate.model_id,
                "runtime_model_version": candidate.model_version,
                "runtime_version": candidate.runtime_version,
                "output_safety_action": output_check.decision.action,
            },
        )
        result = SupportResult(
            status="generated",
            safety_action=output_check.decision.action,
            normal_generation=True,
            generation=generation_projection,
            report_id=report_id,
            content=content,
            citations=citations,
            trace_id=context.trace_id,
            integration_labels=dict(self.integration_labels),
        )
        await maybe_await(self.conversations.complete_workflow(result))
        try:
            await maybe_await(self.reports.save(report))
        except Exception:
            await self._discard_report(report_id)
            raise
        ledger.advance(
            OrchestrationStage.PERSISTED,
            metadata={
                "report_id": report_id,
                "generation_id": generation_id,
                "bundle_hash": bundle.bundle_hash,
            },
        )
        diagnostics.confirm()
        return result

    async def retrieve(
        self, actor: Actor, payload: RetrievalRequest, *, context: RequestContext
    ) -> RetrievalResult:
        record = await self.assessments.get_for_actor(
            actor,
            payload.assessment_id,
            action="retrieval:create",
            request_id=context.request_id,
            trace_id=context.trace_id,
        )
        try:
            trusted_context = derive_trusted_request_context(
                actor,
                record,
                request=payload,
                target_role=payload.target_role,
                transaction_id=f"TX_{context.trace_id.removeprefix('TRACE_')}",
                request_id=context.request_id,
                trace_id=context.trace_id,
            )
        except TrustedContextError as exc:
            raise error(ErrorCode.FORBIDDEN, detail="request authorization failed") from exc

        ledger = StageLedger(trusted_context)
        self.stage_ledgers[context.trace_id] = ledger
        ledger.advance(OrchestrationStage.REQUEST_AUTHENTICATED)
        ledger.advance(OrchestrationStage.REQUEST_AUTHORIZED)
        safety_context = self._safety_context(
            record.assessment, payload.target_role, payload.query, context
        )
        self.call_order.append("safety_input")
        input_check = await self.safety.check_input(safety_context, context)
        action = input_check.decision.action
        ledger.advance(OrchestrationStage.INPUT_SAFETY_EVALUATED, safety_action=action)
        if action not in {"PROCEED", "PROCEED_WITH_BOUNDARY"}:
            raise error(ErrorCode.FORBIDDEN, detail="retrieval request was stopped by Safety")
        try:
            binding = bind_assessment(
                actor,
                record,
                assessment_id=payload.assessment_id,
                requested_assessment_id=payload.assessment_id,
                trusted_context=trusted_context,
                transaction_id=trusted_context.transaction_id,
                request_id=context.request_id,
                trace_id=context.trace_id,
                compatibility_fixtures=self._d3_fixtures.assessment_fixtures,
            )
        except AssessmentBindingError as exc:
            raise error(
                ErrorCode.WORKFLOW_CONFLICT,
                detail="assessment is not eligible for retrieval",
            ) from exc
        ledger.advance(OrchestrationStage.ASSESSMENT_BOUND)
        self.call_order.append("rag")
        retrieval = await self.rag.retrieve(
            assessment=record.assessment,
            target_role=payload.target_role,
            query=payload.query,
            top_k=payload.top_k,
            trace_id=context.trace_id,
            request_id=context.request_id,
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
            raise error(ErrorCode.FORBIDDEN, detail="retrieval response was stopped by Safety")
        risk = record.assessment.get("risk")
        risk_level = risk.get("level") if isinstance(risk, Mapping) else None
        retrieval_population = retrieval_eligibility_population(retrieval, config=self._d3_fixtures)
        try:
            build_retrieval_evidence_bundle(
                retrieval,
                transaction_id=trusted_context.transaction_id,
                request_id=trusted_context.request_id,
                trace_id=trusted_context.trace_id,
                policy=EligibilityPolicy(
                    target_population=retrieval_population,
                    target_role=payload.target_role,
                    risk_level=str(risk_level) if isinstance(risk_level, str) else None,
                ),
            )
        except ValueError as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                status_code=502,
                detail="retrieval evidence is not eligible",
            ) from exc
        # The projection is intentionally detached from generation authority:
        # generation obtains its own same-transaction retrieval bundle.
        del binding, ledger
        return retrieval

    async def _discard_report(self, report_id: str) -> None:
        """Remove a partially written report when publication fails."""

        delete = getattr(self.reports, "delete", None)
        if not callable(delete):
            return
        try:
            await maybe_await(delete(report_id))
        except Exception:
            # Preserve the publication failure.  Current durable adapters use
            # a transaction/no-op report port; the in-memory adapter supports
            # best-effort cleanup for a save implementation that fails after
            # inserting.
            return

    async def _fail_active_workflow(
        self,
        context: RequestContext,
        *,
        reason_code: str,
        failure: BaseException | None = None,
        failure_code: SupportDiagnosticFailureCode | None = None,
    ) -> None:
        report_id = self._active_workflows.get(context.trace_id)
        if not report_id:
            return
        fail = getattr(self.conversations, "fail_workflow", None)
        if fail is None:
            return
        try:
            diagnostics = self._workflow_diagnostics.get(context.trace_id)
            safe_diagnostics = (
                diagnostics.failure_metadata(
                    failure_code or failure_code_for_exception(failure)
                )
                if diagnostics is not None
                else SupportWorkflowDiagnostics().failure_metadata(
                    failure_code or failure_code_for_exception(failure)
                )
            )
            await maybe_await(
                fail(
                    report_id,
                    reason_code=reason_code,
                    trace_id=context.trace_id,
                    stage_diagnostics=safe_diagnostics,
                )
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
        record = await self.assessments.get_for_actor(
            actor,
            assessment_id,
            action="safety:check",
            request_id=context.request_id,
            trace_id=context.trace_id,
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
        if actor.role is BackendRole.ADMIN:
            # Admins receive only the coarse report envelope.  Keep this
            # projection in the service as well as the HTTP adapter so another
            # Backend caller cannot bypass the route-level redaction.
            return ReportRecord(
                report_id=report.report_id,
                assessment_id=report.assessment_id,
                subject_id=report.subject_id,
                generation_id=report.generation_id,
                status=report.status,
                generation={},
                review_id=report.review_id,
                review_status=report.review_status,
                safety_action=report.safety_action,
                citations=[],
                candidate_source=report.candidate_source,
            )
        return report

    async def reports_for_actor(
        self,
        actor: Actor,
        *,
        assessment_id: str | None = None,
        limit: int = 100,
    ) -> list[ReportRecord]:
        """Return only reports whose subjects are already in the actor's scope."""

        subject_ids = (
            {actor.subject_id}
            if actor.role is BackendRole.STUDENT and actor.subject_id is not None
            else set(actor.accessible_subject_ids)
        )
        authorized_subject_ids = {
            subject_id
            for subject_id in subject_ids
            if self.authorization.can(
                actor,
                "report:read",
                resource={"subject_id": subject_id, "owner_user_id": actor.user_id},
            )
        }
        if not authorized_subject_ids:
            return []
        return await maybe_await(
            self.reports.list_for_subjects(
                authorized_subject_ids,
                assessment_id=assessment_id,
                limit=limit,
            )
        )

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
        self.authorization.require(
            actor,
            "report:read",
            resource={"subject_id": report.subject_id, "owner_user_id": actor.user_id},
        )
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
            metadata={
                "report_id": report_id,
                "review_id": projection.review_id,
                "subject_id": report.subject_id,
                "actor_scope": "assigned_subjects",
            },
        )
        return projection

    async def pending_reviews(self, actor: Actor) -> list[ReviewProjection]:
        self.authorization.require(actor, "review:list")
        pending = await maybe_await(self.reviews.list_pending())
        return [
            projection
            for projection in pending
            if projection.subject_id in actor.accessible_subject_ids
        ]

    async def review_detail(self, actor: Actor, review_id: str) -> ReviewProjection:
        self.authorization.require(actor, "review:read")
        projection = await maybe_await(self.reviews.get(review_id))
        if projection is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="review not found")
        self.authorization.require(
            actor,
            "report:read",
            resource={"subject_id": projection.subject_id, "owner_user_id": actor.user_id},
        )
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
        bundle: RetrievalEvidenceBundle | None,
        prompt_id: str,
        prompt_version: str,
        model_id: str | None,
        candidate: CandidateResponse | None = None,
    ) -> SupportResult:
        check = output_check or input_check
        action = check.decision.action
        review_reference = check.review_reference
        if check.decision.requires_human and review_reference is None:
            review_reference = f"REVIEW_{uuid4().hex}"
        candidate_source = "CONTROLLED_SYNTHETIC" if candidate is not None else "NOT_RUN"
        generation_model_id = candidate.model_id if candidate is not None else None
        generation_model_version = candidate.model_version if candidate is not None else None
        generation_runtime_version = candidate.runtime_version if candidate is not None else None
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
            model_id=generation_model_id,
            model_version=generation_model_version,
            runtime_version=generation_runtime_version,
        )
        generation_projection = _candidate_generation(
            generation,
            generation_status="EXECUTED" if candidate is not None else "NOT_RUN",
            candidate_source=candidate_source,
        )
        # Raw retrieval is never a citation authority.  A blocked path may
        # retain citations only when the same eligible evidence bundle already
        # crossed the trusted boundary; retrieval Safety stops therefore have
        # an empty citation set.
        citations = self._citations_from_evidence_bundle(bundle) if bundle else []
        report = ReportRecord(
            report_id=report_id,
            assessment_id=payload.assessment_id,
            subject_id=record.subject_id,
            generation_id=generation_id,
            status="needs_review" if check.decision.requires_human else "safety_blocked",
            generation=generation_projection.model_dump(mode="json"),
            review_id=review_reference,
            review_status="pending" if check.decision.requires_human else "not_required",
            safety_action=action,
            citations=[item.model_dump(mode="json") for item in citations],
            candidate_source=candidate_source,
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
            generation=generation_projection,
            report_id=report_id,
            content=None,
            citations=citations,
            review_reference=review_reference,
            crisis_response=crisis_response,
            trace_id=input_check.trace_id,
            integration_labels=dict(self.integration_labels),
        )

    async def _abstained_result(
        self,
        *,
        record,
        payload: SupportRequest,
        generation_id: str,
        report_id: str,
        retrieval: RetrievalResult,
        input_check: SafetyCheckView,
        retrieval_check: SafetyCheckView,
    ) -> SupportResult:
        """Persist a valid zero-evidence transaction without model execution."""

        generation = {
            "schema_version": "generation.v1",
            "generation_id": generation_id,
            "status": "requested",
            "target_role": payload.target_role,
            "content": None,
            "safety": {
                "precheck": _safety_status(input_check.decision.action),
                "postcheck": _safety_status(retrieval_check.decision.action),
                "reason_codes": ["NO_ELIGIBLE_EVIDENCE"],
                "human_review_required": False,
            },
            "provenance": {
                "assessment_id": payload.assessment_id,
                "retrieval_id": retrieval.retrieval_id,
                "prompt_id": "PROMPT_not_run",
                "prompt_version": "not_run",
                "model_id": None,
                "model_version": None,
                "runtime_version": None,
            },
            "review": {
                "status": "not_required",
                "reviewer_id": None,
                "reviewed_at": None,
            },
            "created_at": _timestamp(),
        }
        generation_projection = _candidate_generation(
            generation,
            generation_status="NOT_RUN",
            candidate_source="NOT_RUN",
        )
        report = ReportRecord(
            report_id=report_id,
            assessment_id=payload.assessment_id,
            subject_id=record.subject_id,
            generation_id=generation_id,
            status="abstained",
            generation=generation_projection.model_dump(mode="json"),
            review_status="not_required",
            safety_action=retrieval_check.decision.action,
            citations=[],
            candidate_source="NOT_RUN",
        )
        await maybe_await(self.reports.save(report))
        return SupportResult(
            status="abstained",
            safety_action=retrieval_check.decision.action,
            normal_generation=False,
            generation=generation_projection,
            report_id=report_id,
            content=None,
            citations=[],
            review_reference=None,
            crisis_response=None,
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
        audit_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        generation = result.generation.model_dump(mode="json")
        await maybe_await(self.conversations.complete_workflow(result))
        await maybe_await(
            self.conversations.save_metadata(
                request_id=context.request_id,
                trace_id=context.trace_id,
                metadata={
                    "support_request": True,
                    "message_length": len(message),
                    "message_digest": _digest(message),
                    "generation_id": generation["generation_id"],
                    "report_id": result.report_id,
                    "safety_action": result.safety_action,
                    "normal_generation": result.normal_generation,
                    "support_status": result.status,
                    "actor_scope": "subject_bound",
                    "synthetic_fixture_only": True,
                    **dict(audit_metadata or {}),
                },
            )
        )
        await self.audit.record(
            event="SUPPORT_REQUESTED",
            actor=actor,
            request_id=context.request_id,
            trace_id=context.trace_id,
            outcome=result.safety_action,
            metadata={
                "assessment_id": generation.get("provenance", {}).get("assessment_id"),
                "generation_id": generation["generation_id"],
                "report_id": result.report_id,
                "review_reference": result.review_reference,
                "support_status": result.status,
                "actor_scope": "subject_bound",
                "synthetic_fixture_only": True,
                **dict(audit_metadata or {}),
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
    def _citations_from_evidence_bundle(
        bundle: RetrievalEvidenceBundle,
    ) -> list[SupportCitation]:
        """Expose only display references already bound to the same bundle."""

        bundle.require_eligible()
        return [
            SupportCitation(
                citation_id=item.citation_id,
                chunk_id=item.chunk_id,
                document_id=item.document_id,
                title=str(item.citation.get("title"))
                if item.citation.get("title") is not None
                else None,
                organization=str(item.citation.get("organization"))
                if item.citation.get("organization") is not None
                else None,
                locator=item.locator,
                rank=index,
                source_version=item.schema_version,
                source_hash=item.content_hash,
            )
            for index, item in enumerate(bundle.items, start=1)
        ]

    @staticmethod
    def _citations_from_bundle(
        bundle: RetrievalEvidenceBundle, content: GenerationContent
    ) -> list[SupportCitation]:
        """Validate and resolve candidate citations from the same bundle."""

        source_ids = list(
            dict.fromkeys(
                source_id
                for suggestion in content.suggestions
                for source_id in suggestion.source_chunk_ids
            )
        )
        references = [bundle.reference_for(source_id) for source_id in source_ids]
        evidence = bundle.validate_citations(references)
        return [
            SupportCitation(
                citation_id=item.citation_id,
                chunk_id=item.chunk_id,
                document_id=item.document_id,
                title=str(item.citation.get("title"))
                if item.citation.get("title") is not None
                else None,
                organization=str(item.citation.get("organization"))
                if item.citation.get("organization") is not None
                else None,
                locator=item.locator,
                rank=index,
                source_version=item.schema_version,
                source_hash=item.content_hash,
            )
            for index, item in enumerate(evidence, start=1)
        ]

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
        model_id: str | None,
        model_version: str | None = None,
        runtime_version: str | None = None,
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
                "model_version": model_version,
                "runtime_version": runtime_version,
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


def _citations_from_retrieval(retrieval: RetrievalResult | None) -> list[SupportCitation]:
    if retrieval is None:
        return []
    citations: list[SupportCitation] = []
    for rank, chunk in enumerate(retrieval.chunks, start=1):
        digest = _digest(f"{chunk.document_id}|{chunk.chunk_id}|{chunk.content_hash}")[:24]
        citations.append(
            SupportCitation(
                citation_id=f"CITE_{digest}",
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                title=chunk.citation.title,
                organization=chunk.citation.organization,
                locator=chunk.citation.locator,
                rank=rank,
                source_version=chunk.schema_version,
                source_hash=chunk.content_hash,
            )
        )
    return citations


def _candidate_generation(
    generation: dict[str, Any],
    *,
    generation_status: str,
    candidate_source: str,
) -> GenerationProjection:
    """Add candidate-only execution metadata without mutating frozen v1 data."""

    value = dict(generation)
    provenance = dict(value.get("provenance", {}))
    if generation_status == "NOT_RUN":
        provenance["model_id"] = None
        provenance["model_version"] = None
        provenance["runtime_version"] = None
    provenance["generation_status"] = generation_status
    provenance["candidate_source"] = candidate_source
    value["provenance"] = provenance
    return GenerationProjection.model_validate(value)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _contains_forbidden_generated_claim(content: GenerationContent) -> bool:
    """Reject obvious measurement/clinical claims before publication.

    D3-3 already constrains the prompt-facing projection.  This small output
    invariant covers a compromised or overly literal Runtime candidate even
    when a synthetic Safety adapter returns ``PROCEED``.  The disclaimer is
    intentionally excluded because the frozen fixture explicitly states that
    the content is not diagnosis or treatment advice.
    """

    values = [content.summary, *content.observations]
    values.extend(suggestion.text for suggestion in content.suggestions)
    return any(_FORBIDDEN_GENERATED_CLAIMS.search(value) for value in values)


def _log_generation_boundary_rejection(
    *,
    request_id: str,
    trace_id: str,
    generation_id: str,
    candidate_text: str,
    output_safety_action: str,
    content: GenerationContent,
) -> None:
    """Emit only fixed, non-content metadata for a rejected candidate.

    The selected field is the first match in schema order (summary, then
    observations, then suggestions); ``field_index`` is zero-based, including
    summary's single index 0. ``match_count`` counts matches in that field.
    """

    field_kind, field_index, category, match_count = _first_boundary_match(content)
    request_context = get_contextvars()
    clear_contextvars()
    try:
        logger().warning(
            "support_generation_boundary_rejected",
            request_id=request_id,
            trace_id=trace_id,
            generation_id=generation_id,
            candidate_sha256=_digest(candidate_text),
            parse_status="PARSED",
            output_safety_action=str(output_safety_action),
            boundary_check_code="FORBIDDEN_GENERATED_CLAIM",
            field_kind=field_kind,
            field_index=field_index,
            matched_category=category,
            match_count=match_count,
            workflow_disposition="FAILED_CLOSED_NO_REPORT",
        )
    finally:
        clear_contextvars()
        bind_contextvars(**request_context)


def _first_boundary_match(
    content: GenerationContent,
) -> tuple[str, int, str, int]:
    fields = [
        ("SUMMARY", 0, content.summary),
        *(('OBSERVATION', index, value) for index, value in enumerate(content.observations)),
        *(
            ("SUGGESTION", index, suggestion.text)
            for index, suggestion in enumerate(content.suggestions)
        ),
    ]
    for field_kind, field_index, value in fields:
        matches = list(_FORBIDDEN_GENERATED_CLAIMS.finditer(value))
        if matches:
            return (
                field_kind,
                field_index,
                _boundary_match_category(matches[0].group(0)),
                len(matches),
            )
    raise ValueError("rejected generation has no boundary match")


def _boundary_match_category(match: str) -> str:
    normalized = match.casefold()
    if normalized == "诊断" or normalized.startswith("diagnos"):
        return "DIAGNOSIS"
    if normalized == "clinical":
        return "CLINICAL"
    if normalized == "severity":
        return "SEVERITY"
    if normalized in {"theta", "se", "score", "band"}:
        return "PSYCHOMETRIC_SCORE"
    return "OTHER_ALLOWLISTED"


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _digest(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()
