"""Independent checks for untrusted retrieved chunks.

NeMo Guardrails 0.24.x IORails exposes input/output checks, not a retrieval
surface.  This adapter is therefore an explicit PARTIAL integration: it checks
privacy, prompt-injection-like text, and source eligibility without implementing
RAG or silently claiming a NeMo retrieval rail.
"""

from __future__ import annotations

import re
from typing import Any

from safety_engine.adapters.base import AdapterResult
from safety_engine.adapters.presidio import PresidioPrivacyAdapter
from safety_engine.domain import (
    ErrorCode,
    SafetyError,
    SafetySignal,
    SeverityHint,
    SignalSource,
    SignalType,
)


class RetrievalSafetyAdapter:
    component = "retrieval_safety"
    version = "1.0"
    integration_status = "PARTIAL"

    _injection_patterns = (
        re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions", re.I),
        re.compile(r"(?:system|developer)\s+message\s*[:：]", re.I),
        re.compile(r"do\s+not\s+follow\s+the\s+application", re.I),
        re.compile(r"绕过(?:安全|系统)规则|忽略之前的指令", re.I),
    )

    def __init__(self, privacy: PresidioPrivacyAdapter) -> None:
        self.privacy = privacy

    def check_retrieval(
        self,
        chunks: list[dict[str, Any]],
        *,
        trace_id: str,
    ) -> AdapterResult:
        signals: list[SafetySignal] = []
        ineligible_count = 0
        for index, chunk in enumerate(chunks):
            content = chunk.get("content") if isinstance(chunk, dict) else None
            metadata = chunk.get("metadata", {}) if isinstance(chunk, dict) else {}
            if not isinstance(content, str) or not isinstance(metadata, dict):
                raise SafetyError(
                    ErrorCode.RETRIEVAL_SAFETY_CHECK_FAILED,
                    "retrieval chunk shape is invalid",
                    details={"chunk_index": index},
                )
            review_status = str(metadata.get("review_status", "")).lower()
            rights_status = str(metadata.get("rights_status", "")).lower()
            if review_status != "approved" or rights_status != "verified":
                ineligible_count += 1
                signals.append(
                    SafetySignal(
                        source=SignalSource.DETERMINISTIC_RULE,
                        signal_type=SignalType.RETRIEVAL,
                        category="source_eligibility",
                        severity_hint=SeverityHint.HIGH,
                        confidence=1.0,
                        reason_code="RETRIEVAL_SOURCE_INELIGIBLE",
                        component=self.component,
                        component_version=self.version,
                        trace_id=trace_id,
                        metadata={
                            "chunk_index": index,
                            "review_status": review_status or "MISSING",
                            "rights_status": rights_status or "MISSING",
                        },
                    )
                )
            privacy_result = self.privacy.detect(content, trace_id=trace_id)
            signals.extend(privacy_result.signals)
            if any(pattern.search(content) for pattern in self._injection_patterns):
                signals.append(
                    SafetySignal(
                        source=SignalSource.DETERMINISTIC_RULE,
                        signal_type=SignalType.INJECTION,
                        category="retrieved_instruction",
                        severity_hint=SeverityHint.HIGH,
                        confidence=1.0,
                        reason_code="PROMPT_INJECTION",
                        component=self.component,
                        component_version=self.version,
                        trace_id=trace_id,
                        metadata={"chunk_index": index},
                    )
                )
        return AdapterResult(
            status="BLOCKED" if signals else "PASSED",
            signals=signals,
            metadata={
                "chunk_count": len(chunks),
                "ineligible_count": ineligible_count,
                "integration_status": self.integration_status,
            },
        )
