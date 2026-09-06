from __future__ import annotations

from pathlib import Path

import pytest

from safety_engine.adapters.base import AdapterResult
from safety_engine.crisis import CrisisTemplateRepository
from safety_engine.domain import (
    ComponentHealth,
    ErrorCode,
    SafetyContext,
    SafetyError,
    SafetySignal,
    SeverityHint,
    SignalSource,
    SignalType,
)
from safety_engine.review import HumanReviewService, InMemoryReviewRepository
from safety_engine.service import SafetyEngineConfig, SafetyService


class FakePrivacy:
    component = "presidio"
    version = "fake"

    def __init__(self, *, pii: bool = False, unavailable: bool = False) -> None:
        self.pii = pii
        self.unavailable = unavailable

    def health(self) -> ComponentHealth:
        return ComponentHealth(
            component=self.component,
            available=not self.unavailable,
            ready=not self.unavailable,
            version=self.version,
            detail_code=ErrorCode.PRIVACY_ENGINE_UNAVAILABLE.value if self.unavailable else None,
        )

    def detect(self, text: str, *, trace_id: str) -> AdapterResult:
        if self.unavailable:
            raise SafetyError(ErrorCode.PRIVACY_ENGINE_UNAVAILABLE, "fake privacy down")
        if not self.pii:
            return AdapterResult(status="PASSED")
        return AdapterResult(
            status="PII_FOUND",
            signals=[
                SafetySignal(
                    source=SignalSource.PRESIDIO,
                    signal_type=SignalType.PRIVACY,
                    category="PHONE_NUMBER",
                    severity_hint=SeverityHint.MODERATE,
                    confidence=1.0,
                    reason_code="PII_DETECTED",
                    component=self.component,
                    component_version=self.version,
                    trace_id=trace_id,
                    metadata={"entity_type": "PHONE_NUMBER", "span_length": 11},
                )
            ],
        )

    def redact(self, text: str, *, trace_id: str) -> str:
        return "<PII_REDACTED>" if self.pii else text


class FakeNemo:
    component = "nemo_guardrails"
    version = "fake"

    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable = unavailable

    def health(self) -> ComponentHealth:
        return ComponentHealth(
            component=self.component,
            available=not self.unavailable,
            ready=not self.unavailable,
            version=self.version,
        )

    async def check_input(self, text: str, *, trace_id: str) -> AdapterResult:
        if self.unavailable:
            raise SafetyError(ErrorCode.GUARDRAIL_CHECK_FAILED, "fake NeMo down")
        return AdapterResult(status="PASSED")

    async def check_output(self, text: str, *, trace_id: str) -> AdapterResult:
        return await self.check_input(text, trace_id=trace_id)


class FakeQwen:
    component = "qwen3guard"
    version = "fake"

    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable = unavailable
        self.input_calls = 0
        self.response_calls = 0

    def health(self) -> ComponentHealth:
        return ComponentHealth(
            component=self.component,
            available=not self.unavailable,
            ready=not self.unavailable,
            version=self.version,
        )

    async def classify_input(self, text: str, *, trace_id: str) -> AdapterResult:
        self.input_calls += 1
        if self.unavailable:
            raise SafetyError(ErrorCode.GUARD_MODEL_UNAVAILABLE, "fake Qwen down")
        return AdapterResult(status="PASSED")

    async def classify_response(
        self, user_message: str, candidate: str, *, trace_id: str
    ) -> AdapterResult:
        self.response_calls += 1
        if self.unavailable:
            raise SafetyError(ErrorCode.GUARD_MODEL_UNAVAILABLE, "fake Qwen down")
        return AdapterResult(status="PASSED")


class FakePolicy:
    component = "opa"
    version = "fake"
    policy_revision = "fake-revision"

    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable = unavailable

    def health(self) -> ComponentHealth:
        return ComponentHealth(
            component=self.component,
            available=not self.unavailable,
            ready=not self.unavailable,
            version=self.version,
        )

    def evaluate(self, policy_input: dict) -> dict:
        if self.unavailable:
            raise SafetyError(ErrorCode.POLICY_ENGINE_UNAVAILABLE, "fake OPA down")
        codes = {signal["reason_code"] for signal in policy_input["signals"]}
        if "EXPLICIT_CRISIS_SIGNAL" in codes:
            return {
                "action": "CRISIS_ROUTE",
                "reason_codes": ["EXPLICIT_CRISIS_SIGNAL"],
                "requires_human": True,
            }
        if not all(
            policy_input["component_health"].get(name, False)
            for name in ("presidio", "nemo_guardrails", "qwen3guard")
        ):
            return {
                "action": "REVIEW_REQUIRED",
                "reason_codes": ["COMPONENT_UNAVAILABLE"],
                "requires_human": True,
            }
        if "PROMPT_INJECTION" in codes or "JAILBREAK" in codes:
            return {
                "action": "BLOCK",
                "reason_codes": ["PROMPT_INJECTION"],
                "requires_human": False,
            }
        if "CLINICAL_OVERREACH" in codes:
            return {
                "action": "REVIEW_REQUIRED",
                "reason_codes": ["CLINICAL_OVERREACH"],
                "requires_human": True,
            }
        if "PII_DETECTED" in codes:
            return {
                "action": "PROCEED_WITH_BOUNDARY",
                "reason_codes": ["PII_DETECTED"],
                "requires_human": False,
            }
        return {
            "action": "PROCEED",
            "reason_codes": ["NO_BLOCKING_SIGNAL"],
            "requires_human": False,
        }


@pytest.fixture
def module_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def context() -> SafetyContext:
    return SafetyContext(
        trace_id="trace-test-001",
        request_id="request-test-001",
        actor_role="STUDENT",
        age_group="ADOLESCENT",
        current_user_message="I want help organizing my study plan.",
    )


@pytest.fixture
def make_service(module_root: Path):
    def _make(*, privacy=None, nemo=None, qwen=None, policy=None) -> tuple[SafetyService, FakeQwen]:
        qwen = qwen or FakeQwen()
        service = SafetyService(
            privacy=privacy or FakePrivacy(),
            nemo=nemo or FakeNemo(),
            qwen=qwen,
            policy=policy or FakePolicy(),
            review=HumanReviewService(InMemoryReviewRepository()),
            crisis_templates=CrisisTemplateRepository(module_root / "templates" / "crisis"),
            config=SafetyEngineConfig(policy_revision="fake-revision"),
        )
        return service, qwen

    return _make
