"""Deterministic engineering boundary checks.

These rules prevent the safety service from presenting an engineering control
decision as a diagnosis.  They do not calculate clinical scores, theta,
standard error, or thresholds.
"""

from __future__ import annotations

import re

from safety_engine.domain import SafetySignal, SeverityHint, SignalSource, SignalType


class ClinicalBoundaryGuard:
    component = "clinical_boundary"
    version = "1.0"

    _patterns = (
        re.compile(r"\b(?:diagnose|diagnosis|clinical\s+diagnosis|medical\s+diagnosis)\b", re.I),
        re.compile(
            r"\b(?:you\s+have|you\s+are)\s+(?:depression|anxiety|adhd|ptsd|bipolar)\b", re.I
        ),
        re.compile(
            r"(?:临床诊断|确诊|你患有|你就是)(?:.{0,12})(?:抑郁|焦虑|多动|创伤|双相)?", re.I
        ),
        re.compile(r"\b(?:clinical|suicide)\s+(?:risk\s+)?(?:score|threshold)\b", re.I),
        re.compile(
            r"\b(?:theta|standard\s+error|psychometric\s+threshold|cut\s*[- ]?score)\b", re.I
        ),
    )

    def check(self, text: str, *, trace_id: str) -> list[SafetySignal]:
        if not any(pattern.search(text) for pattern in self._patterns):
            return []
        return [
            SafetySignal(
                source=SignalSource.DETERMINISTIC_RULE,
                signal_type=SignalType.CLINICAL_BOUNDARY,
                category="clinical_boundary",
                severity_hint=SeverityHint.HIGH,
                confidence=1.0,
                reason_code="CLINICAL_OVERREACH",
                component=self.component,
                component_version=self.version,
                trace_id=trace_id,
                metadata={"rule_set": self.version},
            )
        ]
