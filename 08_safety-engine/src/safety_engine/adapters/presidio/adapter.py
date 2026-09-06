"""Presidio-backed detection and redaction.

Presidio owns entity detection/anonymization here; the Safety Control Plane
only translates its results into internal, PII-safe signals.  The recognizer
extension is deliberately small and documented because Chinese entity recall
requires local evaluation rather than an assumption of parity with English.
"""

from __future__ import annotations

import importlib.metadata
import re
from dataclasses import dataclass
from typing import Any

from safety_engine.adapters.base import AdapterResult
from safety_engine.domain import (
    ComponentHealth,
    ErrorCode,
    SafetyError,
    SafetySignal,
    SeverityHint,
    SignalSource,
    SignalType,
    metadata_for_text,
)


@dataclass(slots=True, frozen=True)
class PIIFinding:
    entity_type: str
    start: int
    end: int
    score: float

    @property
    def span_length(self) -> int:
        return self.end - self.start


class PresidioPrivacyAdapter:
    component = "presidio"

    def __init__(self, *, version: str | None = None) -> None:
        self.version = version or _package_version("presidio-analyzer", "unknown")
        self._analyzer: Any | None = None
        self._anonymizer: Any | None = None
        self._init_error: str | None = None

    def _ensure_engines(self) -> tuple[Any, Any]:
        if self._analyzer is not None and self._anonymizer is not None:
            return self._analyzer, self._anonymizer
        try:
            from presidio_analyzer import (
                AnalyzerEngine,
                Pattern,
                PatternRecognizer,
                RecognizerRegistry,
            )

            try:
                from presidio_analyzer.nlp_engine import NoOpNlpEngine
            except ImportError:
                from presidio_analyzer.nlp_engine.no_op_nlp_engine import NoOpNlpEngine
            from presidio_anonymizer import AnonymizerEngine
            from presidio_anonymizer.entities import OperatorConfig
        except Exception as exc:  # pragma: no cover - depends on optional package
            self._init_error = f"{type(exc).__name__}: {exc}"
            raise SafetyError(
                ErrorCode.PRIVACY_ENGINE_UNAVAILABLE,
                "Presidio is not available",
                details={"component": self.component},
            ) from exc

        try:
            registry = RecognizerRegistry(supported_languages=["en", "zh"])
        except TypeError:
            registry = RecognizerRegistry()
        for language in ("en", "zh"):
            registry.add_recognizer(
                PatternRecognizer(
                    supported_entity="PHONE_NUMBER",
                    name=f"custom_phone_{language}",
                    supported_language=language,
                    patterns=[
                        Pattern(
                            name="international_or_local_phone",
                            regex=(
                                r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)|"
                                r"(?<!\d)(?:\+?\d[\d -]{7,14}\d)(?!\d)"
                            ),
                            score=0.78,
                        )
                    ],
                )
            )
            registry.add_recognizer(
                PatternRecognizer(
                    supported_entity="EMAIL_ADDRESS",
                    name=f"custom_email_{language}",
                    supported_language=language,
                    patterns=[
                        Pattern(
                            name="email",
                            regex=r"(?i)(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])",
                            score=0.92,
                        )
                    ],
                )
            )
            registry.add_recognizer(
                PatternRecognizer(
                    supported_entity="CHINA_ID",
                    name=f"china_id_{language}",
                    supported_language=language,
                    patterns=[
                        Pattern(
                            name="china_resident_id",
                            regex=r"(?<!\d)[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[0-9Xx](?!\d)",
                            score=0.90,
                        )
                    ],
                )
            )
            registry.add_recognizer(
                PatternRecognizer(
                    supported_entity="STUDENT_IDENTIFIER",
                    name=f"synthetic_student_id_{language}",
                    supported_language=language,
                    patterns=[
                        Pattern(
                            name="synthetic_student_identifier",
                            regex=r"(?i)(?<![A-Z0-9])STU[-_ ]?\d{4,12}(?![A-Z0-9])",
                            score=0.86,
                        )
                    ],
                )
            )

        noop_nlp = NoOpNlpEngine(
            models=[
                {"lang_code": "en", "model_name": "no-op"},
                {"lang_code": "zh", "model_name": "no-op"},
            ]
        )
        try:
            analyzer = AnalyzerEngine(
                registry=registry,
                nlp_engine=noop_nlp,
                supported_languages=["en", "zh"],
            )
        except TypeError:
            # Compatibility with older Presidio constructor signatures.
            analyzer = AnalyzerEngine(registry=registry, nlp_engine=noop_nlp)
        self._analyzer = analyzer
        self._anonymizer = (AnonymizerEngine(), OperatorConfig)
        return self._analyzer, self._anonymizer

    def health(self) -> ComponentHealth:
        try:
            self._ensure_engines()
        except SafetyError as exc:
            return ComponentHealth(
                component=self.component,
                available=False,
                ready=False,
                version=self.version,
                detail_code=exc.code.value,
            )
        return ComponentHealth(
            component=self.component,
            available=True,
            ready=True,
            version=self.version,
        )

    def _analyze(self, text: str) -> list[PIIFinding]:
        analyzer, _ = self._ensure_engines()
        language = "zh" if re.search(r"[\u3400-\u9fff]", text) else "en"
        results = analyzer.analyze(text=text, language=language, score_threshold=0.35)
        return sorted(
            [
                PIIFinding(
                    entity_type=str(result.entity_type),
                    start=int(result.start),
                    end=int(result.end),
                    score=float(result.score),
                )
                for result in results
            ],
            key=lambda finding: (finding.start, finding.end, finding.entity_type),
        )

    def detect(self, text: str, *, trace_id: str) -> AdapterResult:
        findings = self._analyze(text)
        signals = [
            SafetySignal(
                source=SignalSource.PRESIDIO,
                signal_type=SignalType.PRIVACY,
                category=finding.entity_type,
                severity_hint=SeverityHint.MODERATE,
                confidence=min(max(finding.score, 0.0), 1.0),
                reason_code="PII_DETECTED",
                component=self.component,
                component_version=self.version,
                trace_id=trace_id,
                metadata={
                    "entity_type": finding.entity_type,
                    "span_length": finding.span_length,
                    "score": round(finding.score, 4),
                },
            )
            for finding in findings
        ]
        return AdapterResult(
            status="PII_FOUND" if findings else "PASSED",
            signals=signals,
            metadata={"finding_count": len(findings)},
        )

    def redact(self, text: str, *, trace_id: str) -> str:
        del trace_id
        findings = self._analyze(text)
        if not findings:
            return text
        anonymizer, operator_config_type = self._ensure_engines()[1]
        analyzer_results = [_as_presidio_result(finding) for finding in findings]
        operators = {"DEFAULT": operator_config_type("replace", {"new_value": "<PII_REDACTED>"})}
        return anonymizer.anonymize(
            text=text, analyzer_results=analyzer_results, operators=operators
        ).text

    def mask(self, text: str, *, trace_id: str) -> str:
        """Compatibility name for callers that use mask rather than redact."""

        return self.redact(text, trace_id=trace_id)

    def anonymize_metadata(self, text: str, *, trace_id: str) -> dict[str, Any]:
        """Return category counts and text digest without returning raw spans."""

        result = self.detect(text, trace_id=trace_id)
        categories: dict[str, int] = {}
        for signal in result.signals:
            categories[signal.category] = categories.get(signal.category, 0) + 1
        return {
            **metadata_for_text(text),
            "finding_count": len(result.signals),
            "category_counts": categories,
        }


def _as_presidio_result(finding: PIIFinding) -> Any:
    """Convert our redaction-safe finding back to Presidio's result object."""

    from presidio_analyzer import RecognizerResult

    return RecognizerResult(
        entity_type=finding.entity_type,
        start=finding.start,
        end=finding.end,
        score=finding.score,
    )


def _package_version(package: str, fallback: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return fallback
