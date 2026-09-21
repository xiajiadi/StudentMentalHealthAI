"""Explicit D3-4 orchestration stage ledger.

The ledger is deliberately small and synchronous.  It records the canonical
logical order independently of any particular RAG, D3, Runtime, or Database
implementation.  A worker can therefore use it as a guard around async calls
without moving module ownership into Backend.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from smhai_backend.core.trusted_context import (
    TrustedRequestContext,
    is_trusted_request_context,
)


class OrchestrationStage(StrEnum):
    REQUEST_AUTHENTICATED = "REQUEST_AUTHENTICATED"
    REQUEST_AUTHORIZED = "REQUEST_AUTHORIZED"
    INPUT_SAFETY_EVALUATED = "INPUT_SAFETY_EVALUATED"
    ASSESSMENT_BOUND = "ASSESSMENT_BOUND"
    INTERPRETATION_READY = "INTERPRETATION_READY"
    RETRIEVAL_BOUND = "RETRIEVAL_BOUND"
    ROLE_PROJECTED = "ROLE_PROJECTED"
    PROMPT_ASSEMBLED = "PROMPT_ASSEMBLED"
    GENERATION_BUFFERED = "GENERATION_BUFFERED"
    OUTPUT_SAFETY_EVALUATED = "OUTPUT_SAFETY_EVALUATED"
    PERSISTED = "PERSISTED"


class OrchestrationState(StrEnum):
    ACTIVE = "ACTIVE"
    ABORTED = "ABORTED"
    COMPLETED = "COMPLETED"


class StageLedgerError(RuntimeError):
    """Fail-closed stage transition error."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


class SafetyStopAction(StrEnum):
    CRISIS_ROUTE = "CRISIS_ROUTE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCK = "BLOCK"


_ORDER: tuple[OrchestrationStage, ...] = (
    OrchestrationStage.REQUEST_AUTHENTICATED,
    OrchestrationStage.REQUEST_AUTHORIZED,
    OrchestrationStage.INPUT_SAFETY_EVALUATED,
    OrchestrationStage.ASSESSMENT_BOUND,
    OrchestrationStage.INTERPRETATION_READY,
    OrchestrationStage.RETRIEVAL_BOUND,
    OrchestrationStage.ROLE_PROJECTED,
    OrchestrationStage.PROMPT_ASSEMBLED,
    OrchestrationStage.GENERATION_BUFFERED,
    OrchestrationStage.OUTPUT_SAFETY_EVALUATED,
    OrchestrationStage.PERSISTED,
)
_STOP_ACTIONS = frozenset(item.value for item in SafetyStopAction)


@dataclass(frozen=True, slots=True)
class StageRecord:
    stage: OrchestrationStage
    predecessor: OrchestrationStage | None
    transaction_id: str
    context_id: str
    occurred_at: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    safety_action: str | None = None


@dataclass(frozen=True, slots=True)
class StageLedgerSnapshot:
    transaction_id: str
    context_id: str
    state: OrchestrationState
    current: OrchestrationStage | None
    stages: tuple[OrchestrationStage, ...]
    records: tuple[StageRecord, ...]
    terminal_action: str | None
    terminal_reason: str | None


class StageLedger:
    """One-use, ordered ledger bound to one exact trusted context object."""

    stages: tuple[OrchestrationStage, ...] = _ORDER

    def __init__(self, context: TrustedRequestContext) -> None:
        if not is_trusted_request_context(context):
            raise StageLedgerError("TRUSTED_CONTEXT_REQUIRED", "typed trusted context is required")
        self.context = context
        self.transaction_id = context.transaction_id
        self.context_id = context.context_id
        self.state = OrchestrationState.ACTIVE
        self._records: list[StageRecord] = []
        self.terminal_action: str | None = None
        self.terminal_reason: str | None = None

    @property
    def current(self) -> OrchestrationStage | None:
        return self._records[-1].stage if self._records else None

    @property
    def records(self) -> tuple[StageRecord, ...]:
        return tuple(self._records)

    @property
    def completed(self) -> bool:
        return self.state is OrchestrationState.COMPLETED

    @property
    def aborted(self) -> bool:
        return self.state is OrchestrationState.ABORTED

    def _coerce_stage(self, stage: OrchestrationStage | str) -> OrchestrationStage:
        try:
            return stage if isinstance(stage, OrchestrationStage) else OrchestrationStage(stage)
        except ValueError as exc:
            raise StageLedgerError("STAGE_INVALID", "unknown orchestration stage") from exc

    def _check_context(self, context: TrustedRequestContext) -> None:
        if not is_trusted_request_context(context):
            raise StageLedgerError("TRUSTED_CONTEXT_REQUIRED", "typed trusted context is required")
        if context is not self.context:
            raise StageLedgerError(
                "TRUSTED_CONTEXT_MISMATCH",
                "stage transition must use the exact trusted context object",
            )

    def advance(
        self,
        stage: OrchestrationStage | str,
        *,
        context: TrustedRequestContext | None = None,
        metadata: Mapping[str, Any] | None = None,
        safety_action: str | None = None,
    ) -> StageRecord:
        """Record exactly the next stage and enforce predecessor/context rules."""

        typed_stage = self._coerce_stage(stage)
        self._check_context(context or self.context)
        if self.state is not OrchestrationState.ACTIVE:
            raise StageLedgerError("STAGE_TERMINAL", "orchestration is already terminal")
        expected_index = len(self._records)
        expected = self.stages[expected_index] if expected_index < len(self.stages) else None
        if expected is None:
            raise StageLedgerError("STAGE_DUPLICATE", "all orchestration stages are complete")
        if typed_stage is not expected:
            predecessor = self.current.value if self.current else "NONE"
            raise StageLedgerError(
                "STAGE_OUT_OF_ORDER",
                f"expected {expected.value} after {predecessor}, got {typed_stage.value}",
            )
        normalized_action = None
        if safety_action is not None:
            normalized_action = str(getattr(safety_action, "value", safety_action))
        record = StageRecord(
            stage=typed_stage,
            predecessor=self.current,
            transaction_id=self.transaction_id,
            context_id=self.context_id,
            occurred_at=datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            metadata=dict(metadata or {}),
            safety_action=normalized_action,
        )
        self._records.append(record)
        if normalized_action in _STOP_ACTIONS:
            self.state = OrchestrationState.ABORTED
            self.terminal_action = normalized_action
            self.terminal_reason = "safety stop action"
        elif typed_stage is OrchestrationStage.PERSISTED:
            self.state = OrchestrationState.COMPLETED
        return record

    # ``record`` is intentionally an alias because some orchestration callers
    # describe the operation as recording a stage rather than advancing it.
    record = advance

    def abort(
        self,
        action: SafetyStopAction | str,
        *,
        reason: str,
        context: TrustedRequestContext | None = None,
    ) -> None:
        """Terminate normal work after an authoritative Safety stop."""

        self._check_context(context or self.context)
        if self.state is not OrchestrationState.ACTIVE:
            raise StageLedgerError("STAGE_TERMINAL", "orchestration is already terminal")
        normalized = str(getattr(action, "value", action))
        if normalized not in _STOP_ACTIONS:
            raise StageLedgerError(
                "SAFETY_ACTION_INVALID", "only fail-closed Safety actions terminate work"
            )
        if not self._records or self.current not in {
            OrchestrationStage.INPUT_SAFETY_EVALUATED,
            OrchestrationStage.INTERPRETATION_READY,
            OrchestrationStage.RETRIEVAL_BOUND,
            OrchestrationStage.ROLE_PROJECTED,
            OrchestrationStage.PROMPT_ASSEMBLED,
            OrchestrationStage.GENERATION_BUFFERED,
            OrchestrationStage.OUTPUT_SAFETY_EVALUATED,
        }:
            raise StageLedgerError(
                "SAFETY_STAGE_INVALID",
                "a Safety evaluation must be recorded before a normal path is aborted",
            )
        self.state = OrchestrationState.ABORTED
        self.terminal_action = normalized
        self.terminal_reason = reason

    def require(self, stage: OrchestrationStage | str) -> StageRecord:
        """Return a recorded stage or fail closed."""

        typed_stage = self._coerce_stage(stage)
        for record in self._records:
            if record.stage is typed_stage:
                return record
        raise StageLedgerError("STAGE_PRECONDITION", f"stage {typed_stage.value} has not completed")

    def snapshot(self) -> StageLedgerSnapshot:
        return StageLedgerSnapshot(
            transaction_id=self.transaction_id,
            context_id=self.context_id,
            state=self.state,
            current=self.current,
            stages=tuple(record.stage for record in self._records),
            records=self.records,
            terminal_action=self.terminal_action,
            terminal_reason=self.terminal_reason,
        )


OrchestrationStateMachine = StageLedger

__all__ = [
    "OrchestrationStage",
    "OrchestrationState",
    "OrchestrationStateMachine",
    "SafetyStopAction",
    "StageLedger",
    "StageLedgerError",
    "StageLedgerSnapshot",
    "StageRecord",
]
