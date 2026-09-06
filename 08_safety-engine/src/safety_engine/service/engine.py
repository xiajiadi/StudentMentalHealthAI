"""Safety Control Plane service orchestration."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from safety_engine.adapters.base import AdapterResult
from safety_engine.adapters.nemo import NemoIORailsAdapter
from safety_engine.adapters.presidio import PresidioPrivacyAdapter
from safety_engine.adapters.qwen_guard import Qwen3GuardProvider
from safety_engine.clinical_boundary import ClinicalBoundaryGuard
from safety_engine.crisis import CrisisTemplateRepository
from safety_engine.domain import (
    Action,
    ComponentHealth,
    ErrorCode,
    SafetyContext,
    SafetyDecision,
    SafetySignal,
    SeverityHint,
    SignalSource,
    SignalType,
)
from safety_engine.domain.errors import error_code_from_exception
from safety_engine.policy import PolicyClient
from safety_engine.privacy import DisclosureMatrix
from safety_engine.retrieval import RetrievalSafetyAdapter
from safety_engine.review import HumanReviewService
from safety_engine.tracing import TraceBuilder

from .result import SafetyCheckResult
from .rules import assessment_signal, deterministic_content_signals, synthetic_crisis_signal


@dataclass(slots=True)
class SafetyEngineConfig:
    service_version: str = "0.1.0"
    policy_version: str = "1.0.0"
    policy_revision: str = "unknown"
    required_components: tuple[str, ...] = ("opa", "presidio", "nemo_guardrails", "qwen3guard")


class SafetyService:
    """Independent service boundary; no dependency on the normal LLM runtime."""

    component = "safety_control_plane"

    def __init__(
        self,
        *,
        privacy: PresidioPrivacyAdapter,
        nemo: NemoIORailsAdapter,
        qwen: Qwen3GuardProvider,
        policy: PolicyClient,
        review: HumanReviewService,
        crisis_templates: CrisisTemplateRepository,
        config: SafetyEngineConfig | None = None,
        clinical_boundary: ClinicalBoundaryGuard | None = None,
        disclosure: DisclosureMatrix | None = None,
    ) -> None:
        self.privacy = privacy
        self.nemo = nemo
        self.qwen = qwen
        self.policy = policy
        self.review = review
        self.crisis_templates = crisis_templates
        self.config = config or SafetyEngineConfig(
            policy_revision=getattr(policy, "policy_revision", "unknown")
        )
        self.clinical_boundary = clinical_boundary or ClinicalBoundaryGuard()
        self.disclosure = disclosure or DisclosureMatrix()
        self.retrieval = RetrievalSafetyAdapter(privacy)

    async def precheck(self, context: SafetyContext) -> SafetyCheckResult:
        trace = TraceBuilder(
            trace_id=context.trace_id, request_id=context.request_id, operation="INPUT"
        )
        signals: list[SafetySignal] = []
        text = context.current_user_message
        for index, item in enumerate(context.assessment_signals):
            signals.append(assessment_signal(item, trace_id=context.trace_id, index=index))

        crisis_signal = synthetic_crisis_signal(
            text, context.conversation_metadata, trace_id=context.trace_id
        )
        if crisis_signal:
            signals.append(crisis_signal)

        safe_text, privacy_result = self._privacy_stage(text, context, trace)
        signals.extend(privacy_result.signals)
        signals.extend(deterministic_content_signals(safe_text, trace_id=context.trace_id))
        signals.extend(self.clinical_boundary.check(safe_text, trace_id=context.trace_id))

        # The explicit synthetic crisis route is deterministic.  Guard models
        # are not needed to produce a crisis template and no normal LLM exists
        # in this service, so normal generation is provably bypassed.
        if crisis_signal is None:
            safe_text = await self._nemo_stage(safe_text, context, trace, signals, route="input")
            await self._qwen_input_stage(safe_text, context, trace, signals)

        return self._decide(
            context=context,
            operation="INPUT",
            text=safe_text,
            signals=signals,
            trace=trace,
        )

    async def postcheck(self, context: SafetyContext, candidate_text: str) -> SafetyCheckResult:
        trace = TraceBuilder(
            trace_id=context.trace_id, request_id=context.request_id, operation="OUTPUT"
        )
        signals: list[SafetySignal] = []
        safe_text, privacy_result = self._privacy_stage(candidate_text, context, trace)
        signals.extend(privacy_result.signals)
        signals.extend(deterministic_content_signals(safe_text, trace_id=context.trace_id))
        signals.extend(self.clinical_boundary.check(safe_text, trace_id=context.trace_id))
        safe_text = await self._nemo_stage(safe_text, context, trace, signals, route="output")
        await self._qwen_response_stage(
            context.current_user_message, safe_text, context, trace, signals
        )
        return self._decide(
            context=context,
            operation="OUTPUT",
            text=safe_text,
            signals=signals,
            trace=trace,
        )

    async def check_retrieval(
        self, context: SafetyContext, chunks: list[dict[str, Any]]
    ) -> SafetyCheckResult:
        trace = TraceBuilder(
            trace_id=context.trace_id, request_id=context.request_id, operation="RETRIEVAL"
        )
        started = time.perf_counter()
        try:
            retrieval_result = self.retrieval.check_retrieval(chunks, trace_id=context.trace_id)
        except Exception as exc:
            retrieval_result = AdapterResult(status="FAILED")
            error_code = error_code_from_exception(
                exc, ErrorCode.RETRIEVAL_SAFETY_CHECK_FAILED
            ).value
            signal = self._component_failure_signal(
                component="retrieval_safety",
                version=self.retrieval.version,
                trace_id=context.trace_id,
                error_code=error_code,
            )
            retrieval_result.signals.append(signal)
        signals = list(retrieval_result.signals)
        trace.record(
            stage="retrieval_safety",
            component=self.retrieval.component,
            outcome=retrieval_result.status,
            started_at=started,
            signal_ids=[signal.signal_id for signal in retrieval_result.signals],
            metadata={
                "chunk_count": len(chunks),
                "integration_status": self.retrieval.integration_status,
            },
        )
        result = self._decide(
            context=context,
            operation="RETRIEVAL",
            text=None,
            signals=signals,
            trace=trace,
        )
        result.retrieval_findings = retrieval_result.metadata
        return result

    def health(self) -> dict[str, ComponentHealth]:
        adapters = {
            "opa": self.policy,
            "presidio": self.privacy,
            "nemo_guardrails": self.nemo,
            "qwen3guard": self.qwen,
            "human_review": self.review,
        }
        return {
            name: self._safe_component_health(name, adapter) for name, adapter in adapters.items()
        }

    def _privacy_stage(
        self, text: str, context: SafetyContext, trace: TraceBuilder
    ) -> tuple[str, AdapterResult]:
        started = time.perf_counter()
        try:
            result = self.privacy.detect(text, trace_id=context.trace_id)
            safe_text = (
                self.privacy.redact(text, trace_id=context.trace_id) if result.signals else text
            )
            outcome = result.status
        except Exception as exc:
            error_code = error_code_from_exception(exc, ErrorCode.PRIVACY_ENGINE_UNAVAILABLE).value
            result = AdapterResult(
                status="FAILED",
                signals=[
                    self._component_failure_signal(
                        component="presidio",
                        version=getattr(self.privacy, "version", "unknown"),
                        trace_id=context.trace_id,
                        error_code=error_code,
                    )
                ],
            )
            safe_text = ""
            outcome = "FAILED"
        trace.record(
            stage="privacy",
            component="presidio",
            outcome=outcome,
            started_at=started,
            signal_ids=[signal.signal_id for signal in result.signals],
            metadata={"finding_count": len(result.signals)},
        )
        return safe_text, result

    async def _nemo_stage(
        self,
        text: str,
        context: SafetyContext,
        trace: TraceBuilder,
        signals: list[SafetySignal],
        *,
        route: str,
    ) -> str:
        started = time.perf_counter()
        try:
            result = (
                await self.nemo.check_input(text, trace_id=context.trace_id)
                if route == "input"
                else await self.nemo.check_output(text, trace_id=context.trace_id)
            )
            signals.extend(result.signals)
            outcome = result.status
            transformed = result.transformed_text or text
        except Exception as exc:
            error_code = error_code_from_exception(exc, ErrorCode.GUARDRAIL_CHECK_FAILED).value
            failure = self._component_failure_signal(
                component="nemo_guardrails",
                version=getattr(self.nemo, "version", "unknown"),
                trace_id=context.trace_id,
                error_code=error_code,
            )
            signals.append(failure)
            outcome = "FAILED"
            transformed = text
        trace.record(
            stage=f"nemo_{route}",
            component="nemo_guardrails",
            outcome=outcome,
            started_at=started,
            signal_ids=[
                signal.signal_id for signal in signals if signal.component == "nemo_guardrails"
            ],
            metadata={"rail_type": route},
        )
        return transformed

    async def _qwen_input_stage(
        self, text: str, context: SafetyContext, trace: TraceBuilder, signals: list[SafetySignal]
    ) -> None:
        started = time.perf_counter()
        try:
            result = await self.qwen.classify_input(text, trace_id=context.trace_id)
            signals.extend(result.signals)
            outcome = result.status
            metadata = {
                "label": result.metadata.get("label"),
                "inference_latency_ms": round(
                    float(result.metadata.get("inference_latency_ms", 0)), 3
                ),
            }
        except Exception as exc:
            error_code = error_code_from_exception(exc, ErrorCode.GUARD_MODEL_UNAVAILABLE).value
            signals.append(
                self._component_failure_signal(
                    component="qwen3guard",
                    version=getattr(self.qwen, "version", "unknown"),
                    trace_id=context.trace_id,
                    error_code=error_code,
                )
            )
            outcome = "FAILED"
            metadata = {}
        trace.record(
            stage="qwen_input",
            component="qwen3guard",
            outcome=outcome,
            started_at=started,
            signal_ids=[signal.signal_id for signal in signals if signal.component == "qwen3guard"],
            metadata=metadata,
        )

    async def _qwen_response_stage(
        self,
        user_message: str,
        candidate: str,
        context: SafetyContext,
        trace: TraceBuilder,
        signals: list[SafetySignal],
    ) -> None:
        started = time.perf_counter()
        try:
            result = await self.qwen.classify_response(
                user_message, candidate, trace_id=context.trace_id
            )
            signals.extend(result.signals)
            outcome = result.status
            metadata = {
                "label": result.metadata.get("label"),
                "inference_latency_ms": round(
                    float(result.metadata.get("inference_latency_ms", 0)), 3
                ),
            }
        except Exception as exc:
            error_code = error_code_from_exception(exc, ErrorCode.GUARD_MODEL_UNAVAILABLE).value
            signals.append(
                self._component_failure_signal(
                    component="qwen3guard",
                    version=getattr(self.qwen, "version", "unknown"),
                    trace_id=context.trace_id,
                    error_code=error_code,
                )
            )
            outcome = "FAILED"
            metadata = {}
        trace.record(
            stage="qwen_response",
            component="qwen3guard",
            outcome=outcome,
            started_at=started,
            signal_ids=[signal.signal_id for signal in signals if signal.component == "qwen3guard"],
            metadata=metadata,
        )

    def _decide(
        self,
        *,
        context: SafetyContext,
        operation: str,
        text: str | None,
        signals: list[SafetySignal],
        trace: TraceBuilder,
    ) -> SafetyCheckResult:
        health = self.health()
        required_components = (
            ("opa", "presidio") if operation == "RETRIEVAL" else self.config.required_components
        )
        for component in required_components:
            health_item = health.get(component)
            if health_item is None or not health_item.ready:
                if not any(
                    signal.source == SignalSource.SYSTEM_HEALTH
                    and signal.metadata.get("component") == component
                    for signal in signals
                ):
                    signals.append(
                        self._component_failure_signal(
                            component=component,
                            version=(health_item.version or "unknown")
                            if health_item
                            else "unknown",
                            trace_id=context.trace_id,
                            error_code=(
                                health_item.detail_code
                                if health_item
                                else ErrorCode.COMPONENT_UNAVAILABLE.value
                            )
                            or ErrorCode.COMPONENT_UNAVAILABLE.value,
                        )
                    )
        policy_input = {
            "operation": operation,
            "actor_role": context.actor_role.value,
            "component_health": {
                name: bool(health_item.ready) for name, health_item in health.items()
            },
            "signals": [signal.model_dump(mode="json") for signal in signals],
        }
        policy_decision_id: str | None = None
        policy_started = time.perf_counter()
        try:
            policy_result = self.policy.evaluate(policy_input)
            action = Action(policy_result["action"])
            raw_policy_decision_id = policy_result.get("decision_id")
            if raw_policy_decision_id:
                policy_decision_id = str(raw_policy_decision_id)
            policy_reasons = [str(reason) for reason in policy_result.get("reason_codes", [])]
            requires_human = bool(
                policy_result.get(
                    "requires_human", action in {Action.REVIEW_REQUIRED, Action.CRISIS_ROUTE}
                )
            )
            trace.record(
                stage="policy",
                component="opa",
                outcome=action.value,
                started_at=policy_started,
                metadata={"policy_version": self.config.policy_version},
            )
        except Exception as exc:
            error_code = error_code_from_exception(exc, ErrorCode.POLICY_EVALUATION_FAILED)
            failure_signal = self._component_failure_signal(
                component="opa",
                version=getattr(self.policy, "version", "unknown"),
                trace_id=context.trace_id,
                error_code=error_code.value,
            )
            signals.append(failure_signal)
            action = Action.BLOCK
            policy_reasons = [error_code.value]
            requires_human = True
            trace.record(
                stage="policy",
                component="opa",
                outcome="FAIL_CLOSED",
                started_at=policy_started,
                signal_ids=[failure_signal.signal_id],
                metadata={"error_code": error_code.value},
            )

        reason_codes = _unique(policy_reasons + [signal.reason_code for signal in signals])
        crisis = any(signal.reason_code == "EXPLICIT_CRISIS_SIGNAL" for signal in signals)
        pii = any(signal.reason_code == "PII_DETECTED" for signal in signals)
        restricted = any(signal.reason_code == "DISCLOSURE_RESTRICTED" for signal in signals)
        disclosure = self.disclosure.resolve(
            context.actor_role,
            pii_detected=pii,
            restricted=restricted,
            crisis=crisis,
        )
        decision = SafetyDecision(
            action=action,
            reason_codes=reason_codes or [ErrorCode.SAFETY_SERVICE_UNAVAILABLE.value],
            source_signal_ids=[signal.signal_id for signal in signals],
            requires_human=requires_human,
            disclosure_policy=disclosure,
            policy_version=self.config.policy_version,
            policy_revision=self.config.policy_revision,
            safety_service_version=self.config.service_version,
            trace_id=context.trace_id,
        )
        review_case = None
        crisis_response = None
        if action == Action.CRISIS_ROUTE:
            try:
                template = self.crisis_templates.get(
                    language=str(context.generation_metadata.get("language", "zh-CN")),
                    target_role=context.actor_role,
                )
                crisis_response = template.content
                decision.crisis_template_id = template.template_id
            except Exception as exc:
                error_code = error_code_from_exception(
                    exc, ErrorCode.CRISIS_TEMPLATE_UNAVAILABLE
                ).value
                decision.action = Action.BLOCK
                decision.requires_human = True
                decision.reason_codes = _unique(decision.reason_codes + [error_code])
                action = decision.action
        if decision.requires_human or decision.action == Action.CRISIS_ROUTE:
            try:
                review_case = self.review.create(
                    decision_id=decision.decision_id,
                    trace_id=context.trace_id,
                    reason_codes=decision.reason_codes,
                    actor_role=context.actor_role,
                    disclosure_policy=decision.disclosure_policy,
                )
                decision.review_case_id = review_case.review_case_id
            except Exception as exc:
                error_code = error_code_from_exception(exc, ErrorCode.REVIEW_QUEUE_FAILED).value
                decision.action = Action.BLOCK
                decision.requires_human = True
                decision.reason_codes = _unique(decision.reason_codes + [error_code])
                action = decision.action

        final_trace = trace.finish(
            action=decision.action,
            signal_count=len(signals),
            signal_ids=[signal.signal_id for signal in signals],
            component_versions={name: item.version or "unknown" for name, item in health.items()},
            policy_version=self.config.policy_version,
            policy_decision_id=policy_decision_id,
            review_case_id=decision.review_case_id,
            crisis_template_id=decision.crisis_template_id,
        )
        visible_text = (
            text if decision.action in {Action.PROCEED, Action.PROCEED_WITH_BOUNDARY} else None
        )
        return SafetyCheckResult(
            operation=operation,  # type: ignore[arg-type]
            decision=decision,
            trace=final_trace,
            signals=signals,
            sanitized_text=visible_text,
            crisis_response=crisis_response if decision.action == Action.CRISIS_ROUTE else None,
            review_case=review_case,
            normal_llm_invoked=False,
        )

    @staticmethod
    def _component_failure_signal(
        *, component: str, version: str, trace_id: str, error_code: str
    ) -> SafetySignal:
        return SafetySignal(
            source=SignalSource.SYSTEM_HEALTH,
            signal_type=SignalType.COMPONENT_HEALTH,
            category=component,
            severity_hint=SeverityHint.CRITICAL,
            confidence=1.0,
            reason_code="COMPONENT_UNAVAILABLE",
            component=component,
            component_version=version,
            trace_id=trace_id,
            metadata={"component": component, "error_code": error_code},
        )

    @staticmethod
    def _safe_component_health(name: str, adapter: Any) -> ComponentHealth:
        try:
            result = adapter.health()
            if not isinstance(result, ComponentHealth):
                raise TypeError("adapter health returned an invalid result")
            return result
        except Exception as exc:
            error_code = error_code_from_exception(exc, ErrorCode.COMPONENT_UNAVAILABLE)
            try:
                version = str(getattr(adapter, "version", "unknown") or "unknown")
            except Exception:
                version = "unknown"
            return ComponentHealth(
                component=name,
                available=False,
                ready=False,
                version=version,
                detail_code=error_code.value,
            )


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
