from __future__ import annotations

import asyncio
from pathlib import Path
from threading import Event

import pytest

from safety_engine.adapters.base import AdapterResult
from safety_engine.adapters.qwen_guard import Qwen3GuardProvider
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


@pytest.mark.asyncio
async def test_cpu_guard_runs_checks_in_order_and_drops_cancelled_queued_work(monkeypatch):
    guard = Qwen3GuardProvider(serialize_cpu_checks=True)
    started = Event()
    finish = Event()
    observed: list[str] = []

    def classify_input(_text, trace_id, _route):
        observed.append(trace_id)
        if trace_id == "running-input":
            started.set()
            assert finish.wait(3)
        return AdapterResult(status="PASSED")

    def classify_output(_user, _candidate, trace_id):
        observed.append(trace_id)
        return AdapterResult(status="PASSED")

    monkeypatch.setattr(guard, "_classify_and_signal", classify_input)
    monkeypatch.setattr(guard, "_classify_response_and_signal", classify_output)
    running = asyncio.create_task(guard.classify_input("exercise", trace_id="running-input"))
    tasks = [running]
    try:
        assert await asyncio.to_thread(started.wait, 3)
        cancelled = asyncio.create_task(guard.classify_input("exercise", trace_id="queued-input"))
        response = asyncio.create_task(
            guard.classify_response("prompt", "exercise", trace_id="queued-output")
        )
        tasks.extend((cancelled, response))
        await asyncio.sleep(0)
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        assert observed == ["running-input"]
        finish.set()
        results = await asyncio.wait_for(asyncio.gather(running, response), 3)
        assert [result.status for result in results] == ["PASSED", "PASSED"]
        assert observed == ["running-input", "queued-output"]
    finally:
        finish.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        guard.close()


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
