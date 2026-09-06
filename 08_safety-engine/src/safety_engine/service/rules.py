"""Small deterministic rules that supplement model-backed checks."""

from __future__ import annotations

import re

from safety_engine.domain import SafetySignal, SeverityHint, SignalSource, SignalType

INJECTION_PATTERNS = (
    ("PROMPT_INJECTION", re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions", re.I)),
    ("PROMPT_INJECTION", re.compile(r"(?:system|developer)\s+message\s*[:：]", re.I)),
    ("PROMPT_INJECTION", re.compile(r"do\s+not\s+follow\s+(?:the\s+)?application", re.I)),
    ("JAILBREAK", re.compile(r"\b(?:DAN|jailbreak|bypass\s+safety|no\s+rules)\b", re.I)),
    ("PROMPT_INJECTION", re.compile(r"忽略之前的指令|绕过(?:安全|系统)规则", re.I)),
)


def deterministic_content_signals(text: str, *, trace_id: str) -> list[SafetySignal]:
    signals: list[SafetySignal] = []
    seen: set[str] = set()
    for reason_code, pattern in INJECTION_PATTERNS:
        if reason_code in seen:
            continue
        if pattern.search(text):
            seen.add(reason_code)
            signals.append(
                SafetySignal(
                    source=SignalSource.DETERMINISTIC_RULE,
                    signal_type=SignalType.INJECTION,
                    category="instruction_integrity",
                    severity_hint=SeverityHint.HIGH,
                    confidence=1.0,
                    reason_code=reason_code,
                    component="deterministic_rules",
                    component_version="1.0",
                    trace_id=trace_id,
                    metadata={"rule_set": "input_output_injection_v1"},
                )
            )
    return signals


def synthetic_crisis_signal(
    text: str,
    metadata: dict,
    *,
    trace_id: str,
) -> SafetySignal | None:
    """Recognize only an explicitly marked synthetic Round 1 fixture."""

    if metadata.get("synthetic_fixture") is not True:
        return None
    allowed = {"synthetic_crisis_signal", "这是合成危机测试信号"}
    explicit = metadata.get("explicit_crisis_signal") is True
    phrase = text.strip().casefold() in allowed
    if not (explicit or phrase):
        return None
    return SafetySignal(
        source=SignalSource.DETERMINISTIC_RULE,
        signal_type=SignalType.CRISIS,
        category="synthetic_fixture_crisis_route",
        severity_hint=SeverityHint.CRITICAL,
        confidence=1.0,
        reason_code="EXPLICIT_CRISIS_SIGNAL",
        component="deterministic_rules",
        component_version="1.0",
        trace_id=trace_id,
        metadata={"synthetic_fixture": True, "template_route": "deterministic"},
    )


def assessment_signal(item: dict, *, trace_id: str, index: int) -> SafetySignal:
    """Pass through an upstream assessment observation without recalculation."""

    category = str(item.get("category") or item.get("type") or "upstream_assessment")
    value = item.get("value")
    if value is None:
        value = item.get("risk")
    safe_value = str(value)[:80] if value is not None else "present"
    source_id = str(item.get("signal_id") or f"assessment-{index + 1}")
    return SafetySignal(
        signal_id=source_id,
        source=SignalSource.ASSESSMENT,
        signal_type=SignalType.ASSESSMENT,
        category=category,
        severity_hint=SeverityHint.UNKNOWN,
        confidence=None,
        reason_code="ASSESSMENT_SIGNAL_RECEIVED",
        component="assessment_input",
        component_version="root-contract-v0.1.0",
        trace_id=trace_id,
        metadata={"upstream_signal_id": source_id, "value_label": safe_value},
    )
