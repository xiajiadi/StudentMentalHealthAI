"""Latency-aware trace builder that only accepts safe metadata."""

from __future__ import annotations

import time
from typing import Literal

from safety_engine.domain import Action, SafetyTrace, TraceEvent


class TraceBuilder:
    def __init__(
        self,
        *,
        trace_id: str,
        request_id: str,
        operation: Literal["INPUT", "OUTPUT", "RETRIEVAL"],
    ) -> None:
        self.trace_id = trace_id
        self.request_id = request_id
        self.operation: Literal["INPUT", "OUTPUT", "RETRIEVAL"] = operation
        self.events: list[TraceEvent] = []

    def record(
        self,
        *,
        stage: str,
        component: str,
        outcome: str,
        started_at: float,
        signal_ids: list[str] | None = None,
        metadata: dict | None = None,
    ) -> None:
        self.events.append(
            TraceEvent(
                stage=stage,
                component=component,
                outcome=outcome,
                latency_ms=max(0.0, (time.perf_counter() - started_at) * 1000),
                signal_ids=signal_ids or [],
                metadata=metadata or {},
            )
        )

    def finish(
        self,
        *,
        action: Action,
        signal_count: int,
        signal_ids: list[str] | None = None,
        component_versions: dict[str, str] | None = None,
        policy_version: str | None = None,
        policy_decision_id: str | None = None,
        review_case_id: str | None = None,
        crisis_template_id: str | None = None,
    ) -> SafetyTrace:
        latencies = {event.stage: event.latency_ms for event in self.events}
        failure = any(event.outcome in {"FAILED", "FAIL_CLOSED"} for event in self.events)
        return SafetyTrace(
            trace_id=self.trace_id,
            request_id=self.request_id,
            operation=self.operation,
            events=self.events,
            final_action=action,
            action=action,
            signal_count=signal_count,
            signals=signal_ids or [],
            component_versions=component_versions or {},
            policy_version=policy_version,
            policy_decision_id=policy_decision_id,
            review_case_id=review_case_id,
            crisis_template_id=crisis_template_id,
            latencies=latencies,
            failure=failure,
            degraded=failure or action != Action.PROCEED,
        )
