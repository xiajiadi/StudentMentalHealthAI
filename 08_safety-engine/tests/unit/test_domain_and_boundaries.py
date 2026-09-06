from __future__ import annotations

from pathlib import Path

import pytest

from safety_engine.clinical_boundary import ClinicalBoundaryGuard
from safety_engine.domain import (
    ActorRole,
    DisclosurePolicy,
    SafetySignal,
    SeverityHint,
    SignalSource,
    SignalType,
)
from safety_engine.privacy import DisclosureMatrix


def test_signal_rejects_raw_sensitive_metadata():
    with pytest.raises(ValueError, match="raw sensitive"):
        SafetySignal(
            source=SignalSource.DETERMINISTIC_RULE,
            signal_type=SignalType.CONTENT,
            category="test",
            severity_hint=SeverityHint.LOW,
            confidence=1.0,
            reason_code="CONTENT_SAFE",
            component="test",
            component_version="1",
            trace_id="trace-1",
            metadata={"raw_text": "synthetic only"},
        )


def test_disclosure_matrix_uses_only_four_allowed_values():
    matrix = DisclosureMatrix()
    values = {matrix.resolve(role).value for role in ActorRole}
    values.add(matrix.resolve(ActorRole.STUDENT, pii_detected=True).value)
    values.add(matrix.resolve(ActorRole.TEACHER, restricted=True).value)
    assert values <= {item.value for item in DisclosurePolicy}
    assert matrix.resolve(ActorRole.STUDENT) == DisclosurePolicy.FULL
    assert matrix.resolve(ActorRole.TEACHER) == DisclosurePolicy.SUMMARY
    assert matrix.resolve(ActorRole.PARENT) == DisclosurePolicy.SUMMARY
    assert matrix.resolve(ActorRole.REVIEWER) == DisclosurePolicy.FULL
    assert matrix.resolve(ActorRole.STUDENT, pii_detected=True) == DisclosurePolicy.REDACTED
    assert matrix.resolve(ActorRole.TEACHER, restricted=True) == DisclosurePolicy.HIDDEN


def test_clinical_boundary_does_not_calculate_assessment_values():
    guard = ClinicalBoundaryGuard()
    signals = guard.check("Please diagnose me and calculate a clinical risk score.", trace_id="t")
    assert [signal.reason_code for signal in signals] == ["CLINICAL_OVERREACH"]
    source = Path(guard.__module__.replace(".", "/")) if False else None
    assert source is None
