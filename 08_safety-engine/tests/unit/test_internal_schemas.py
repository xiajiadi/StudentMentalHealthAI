from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from safety_engine.domain import (
    Action,
    ActorRole,
    DisclosurePolicy,
    HumanReviewCase,
    SafetyContext,
    SafetyDecision,
    SafetySignal,
    SafetyTrace,
    SeverityHint,
    SignalSource,
    SignalType,
)


def test_internal_json_schemas_validate_runtime_models():
    root = Path(__file__).resolve().parents[2]
    context = SafetyContext(
        trace_id="schema-trace-001",
        request_id="schema-request-001",
        actor_role=ActorRole.STUDENT,
        age_group="ADOLESCENT",
        current_user_message="Synthetic schema fixture.",
    )
    signal = SafetySignal(
        source=SignalSource.DETERMINISTIC_RULE,
        signal_type=SignalType.CONTENT,
        category="schema_fixture",
        severity_hint=SeverityHint.LOW,
        confidence=1.0,
        reason_code="CONTENT_SAFE",
        component="test",
        component_version="1.0",
        trace_id=context.trace_id,
    )
    decision = SafetyDecision(
        action=Action.PROCEED,
        reason_codes=["NO_BLOCKING_SIGNAL"],
        source_signal_ids=[signal.signal_id],
        requires_human=False,
        disclosure_policy=DisclosurePolicy.FULL,
        policy_version="1.0.0",
        policy_revision="schema-fixture",
        safety_service_version="0.1.0",
        trace_id=context.trace_id,
    )
    trace = SafetyTrace(
        trace_id=context.trace_id,
        request_id=context.request_id,
        operation="INPUT",
        final_action=Action.PROCEED,
        action=Action.PROCEED,
        signals=[signal.signal_id],
        component_versions={"test": "1.0"},
        policy_version="1.0.0",
        latencies={"policy": 0.1},
    )
    review = HumanReviewCase(
        decision_id=decision.decision_id,
        trace_id=context.trace_id,
        reason_codes=["CLINICAL_OVERREACH"],
        actor_role=ActorRole.STUDENT,
        disclosure_policy=DisclosurePolicy.FULL,
    )
    instances = {
        "safety_context.v1.schema.json": context.model_dump(mode="json"),
        "safety_signal.v1.schema.json": signal.model_dump(mode="json"),
        "safety_decision.v1.schema.json": decision.model_dump(mode="json"),
        "safety_trace.v1.schema.json": trace.model_dump(mode="json"),
        "human_review_case.v1.schema.json": review.model_dump(mode="json"),
    }
    for schema_name, instance in instances.items():
        schema = json.loads((root / "contracts" / "internal" / schema_name).read_text())
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(instance),
            key=lambda error: list(error.path),
        )
        assert not errors, f"{schema_name}: {[error.message for error in errors]}"
