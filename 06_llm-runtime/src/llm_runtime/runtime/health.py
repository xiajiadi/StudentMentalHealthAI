"""Runtime lifecycle state and health primitives."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..errors import LLMRuntimeError, RuntimeErrorCode


class RuntimeState(StrEnum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    STOPPING = "STOPPING"


_ALLOWED_TRANSITIONS: dict[RuntimeState, frozenset[RuntimeState]] = {
    RuntimeState.STOPPED: frozenset({RuntimeState.STARTING}),
    RuntimeState.STARTING: frozenset(
        {
            RuntimeState.READY,
            RuntimeState.DEGRADED,
            RuntimeState.FAILED,
            RuntimeState.STOPPING,
        }
    ),
    RuntimeState.READY: frozenset(
        {RuntimeState.DEGRADED, RuntimeState.STOPPING, RuntimeState.FAILED}
    ),
    RuntimeState.DEGRADED: frozenset(
        {RuntimeState.READY, RuntimeState.STOPPING, RuntimeState.FAILED}
    ),
    RuntimeState.FAILED: frozenset(
        {RuntimeState.STARTING, RuntimeState.STOPPING, RuntimeState.STOPPED}
    ),
    RuntimeState.STOPPING: frozenset({RuntimeState.STOPPED, RuntimeState.FAILED}),
}


class RuntimeStateMachine:
    """Small explicit state machine used by startup/shutdown and health checks."""

    def __init__(self, initial: RuntimeState = RuntimeState.STOPPED) -> None:
        self._state = initial

    @property
    def state(self) -> RuntimeState:
        return self._state

    def transition(self, target: RuntimeState) -> RuntimeState:
        if target is self._state:
            return self._state
        if target not in _ALLOWED_TRANSITIONS[self._state]:
            raise LLMRuntimeError(
                RuntimeErrorCode.CONFIGURATION_ERROR,
                f"Invalid runtime state transition: {self._state.value} -> {target.value}.",
                details={"from": self._state.value, "to": target.value},
            )
        self._state = target
        return self._state


@dataclass
class RuntimeHealth:
    """Serializable aggregate health snapshot without prompt or output data."""

    state: RuntimeState
    runtime_version: str
    cloud_fallback: bool
    providers: Mapping[str, Any] = field(default_factory=dict)
    models: Mapping[str, Any] = field(default_factory=dict)
    processes: Mapping[str, Any] = field(default_factory=dict)
    last_error: Mapping[str, Any] | None = None

    @property
    def liveness(self) -> str:
        return "pass" if self.state is not RuntimeState.FAILED else "fail"

    @property
    def readiness(self) -> str:
        return "pass" if self.state in {RuntimeState.READY, RuntimeState.DEGRADED} else "fail"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.state.value,
            "state": self.state.value,
            "liveness": self.liveness,
            "readiness": self.readiness,
            "runtime_version": self.runtime_version,
            "cloud_fallback": self.cloud_fallback,
            "providers": dict(self.providers),
            "models": dict(self.models),
            "processes": dict(self.processes),
            "last_error": dict(self.last_error) if self.last_error else None,
        }
