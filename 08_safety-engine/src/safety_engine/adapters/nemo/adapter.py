"""NeMo Guardrails 0.24.x adapter.

Only the public IORails surface is used.  The adapter never owns or invokes a
project-wide LLM and never exposes NeMo types beyond this module.
"""

from __future__ import annotations

import importlib.metadata
import inspect
from pathlib import Path
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
)


class NemoIORailsAdapter:
    component = "nemo_guardrails"

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path)
        self.version = _package_version("nemoguardrails", "unknown")
        self._rails: Any | None = None
        self._init_error: str | None = None

    def _ensure_rails(self) -> Any:
        if self._rails is not None:
            return self._rails
        try:
            from nemoguardrails import RailsConfig
            from nemoguardrails.guardrails.iorails import IORails
        except Exception as exc:  # pragma: no cover - optional runtime dependency
            self._init_error = f"{type(exc).__name__}: {exc}"
            raise SafetyError(
                ErrorCode.GUARDRAIL_CHECK_FAILED,
                "NeMo Guardrails IORails is not available",
                details={"component": self.component},
            ) from exc
        if not self.config_path.exists():
            raise SafetyError(
                ErrorCode.GUARDRAIL_CHECK_FAILED,
                "NeMo Guardrails configuration is missing",
                details={"path": str(self.config_path)},
            )
        try:
            config = RailsConfig.from_path(str(self.config_path))
            self._rails = IORails(config)
        except Exception as exc:
            self._init_error = f"{type(exc).__name__}: {exc}"
            raise SafetyError(
                ErrorCode.GUARDRAIL_CHECK_FAILED,
                "NeMo Guardrails configuration failed to load",
                details={"component": self.component},
            ) from exc
        return self._rails

    def health(self) -> ComponentHealth:
        try:
            self._ensure_rails()
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

    async def _check(self, text: str, *, trace_id: str, rail_type: str) -> AdapterResult:
        rails = self._ensure_rails()
        from nemoguardrails.rails.llm.options import RailType

        try:
            result = rails.check_async(
                [{"role": "user", "content": text}],
                rail_types=[RailType.INPUT if rail_type == "input" else RailType.OUTPUT],
            )
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            raise SafetyError(
                ErrorCode.GUARDRAIL_CHECK_FAILED,
                f"NeMo {rail_type} rail execution failed",
                details={"component": self.component, "rail_type": rail_type},
            ) from exc

        status = _result_status(result)
        transformed = _result_text(result)
        detections = _safe_detection_count(result)
        if status == "BLOCKED":
            signal_type = SignalType.INJECTION if rail_type == "input" else SignalType.CONTENT
            signal = SafetySignal(
                source=SignalSource.NEMO,
                signal_type=signal_type,
                category=f"{rail_type}_rail",
                severity_hint=SeverityHint.HIGH,
                confidence=None,
                reason_code="CONTENT_UNSAFE"
                if signal_type == SignalType.CONTENT
                else "PROMPT_INJECTION",
                component=self.component,
                component_version=self.version,
                trace_id=trace_id,
                metadata={
                    "rail_type": rail_type,
                    "rail_status": status,
                    "detection_count": detections,
                },
            )
            return AdapterResult(status=status, signals=[signal], transformed_text=None)
        if status == "MODIFIED":
            signal = SafetySignal(
                source=SignalSource.NEMO,
                signal_type=SignalType.CONTENT,
                category=f"{rail_type}_rail",
                severity_hint=SeverityHint.MODERATE,
                confidence=None,
                reason_code="CONTENT_TRANSFORMED",
                component=self.component,
                component_version=self.version,
                trace_id=trace_id,
                metadata={
                    "rail_type": rail_type,
                    "rail_status": status,
                    "detection_count": detections,
                },
            )
            return AdapterResult(status=status, signals=[signal], transformed_text=transformed)
        if status != "PASSED":
            raise SafetyError(
                ErrorCode.GUARDRAIL_CHECK_FAILED,
                "NeMo returned an unrecognized rail status",
                details={"status": status, "rail_type": rail_type},
            )
        return AdapterResult(
            status=status,
            signals=[],
            transformed_text=transformed if transformed and transformed != text else None,
        )

    async def check_input(self, text: str, *, trace_id: str) -> AdapterResult:
        return await self._check(text, trace_id=trace_id, rail_type="input")

    async def check_output(self, text: str, *, trace_id: str) -> AdapterResult:
        return await self._check(text, trace_id=trace_id, rail_type="output")


def _result_status(result: Any) -> str:
    value = getattr(result, "status", None)
    if value is None and isinstance(result, dict):
        value = result.get("status") or result.get("outcome")
    value = getattr(value, "value", value)
    normalized = str(value or "").upper()
    if normalized in {"PASS", "PASSED", "ALLOW", "ALLOWED"}:
        return "PASSED"
    if normalized in {"MODIFIED", "TRANSFORM", "TRANSFORMED"}:
        return "MODIFIED"
    if normalized in {"BLOCK", "BLOCKED", "DENY", "DENIED"}:
        return "BLOCKED"
    return normalized or "UNKNOWN"


def _result_text(result: Any) -> str | None:
    value = getattr(result, "content", None)
    if value is None and isinstance(result, dict):
        value = result.get("content") or result.get("output")
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and isinstance(value.get("content"), str):
        return value["content"]
    return None


def _safe_detection_count(result: Any) -> int:
    metadata = getattr(result, "metadata", None)
    if metadata is None and isinstance(result, dict):
        metadata = result.get("metadata")
    if not isinstance(metadata, dict):
        return 0
    detections = metadata.get("detections")
    return len(detections) if isinstance(detections, list) else 0


def _package_version(package: str, fallback: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return fallback
