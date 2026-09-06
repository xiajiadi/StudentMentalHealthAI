"""CAT session state machine and trace orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Any

from ..providers.base import CATProvider, ItemSelection, ProviderSession, StopDecision
from .config import CATConfig
from .enums import ResponseStatus, SessionStatus, StopReason
from .errors import SessionStateError, SessionStoppedError
from .item import ResponseValue
from .item_bank import ItemBank
from .result import AbilityEstimate, CATResult
from .trace import CATTraceRecord


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp used by trace and result records."""

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def elapsed_seconds(started_at: str, completed_at: str) -> int | None:
    """Calculate a non-negative whole-second duration from two ISO timestamps."""

    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        return max(0, int((end - start).total_seconds()))
    except ValueError:
        return None


@dataclass
class Session:
    """A provider-independent CAT session with explicit lifecycle guards."""

    assessment_id: str
    subject_id: str
    item_bank: ItemBank
    config: CATConfig
    dimension: str
    status: SessionStatus = SessionStatus.CREATED
    provider_session: ProviderSession | None = None
    started_at: str | None = None
    completed_at: str | None = None
    traces: list[CATTraceRecord] = field(default_factory=list)
    _selected: ItemSelection | None = field(default=None, repr=False)
    _last_stop_decision: StopDecision | None = field(default=None, repr=False)
    _result: CATResult | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Validate identifiers and the selected dimension at construction time."""

        if not re.fullmatch(r"ASSESS_[A-Za-z0-9][A-Za-z0-9_.-]*", self.assessment_id):
            raise SessionStateError("assessment_id must use the ASSESS_ prefix")
        if not re.fullmatch(r"SUBJ_[A-Za-z0-9][A-Za-z0-9_.-]*", self.subject_id):
            raise SessionStateError("subject_id must use the SUBJ_ prefix")
        if self.dimension not in self.item_bank.dimensions:
            raise SessionStateError(f"unknown session dimension: {self.dimension}")

    @classmethod
    def create(
        cls,
        assessment_id: str,
        subject_id: str,
        item_bank: ItemBank,
        config: CATConfig,
        dimension: str | None = None,
    ) -> "Session":
        """Create a new session without initializing a provider."""

        selected_dimension = dimension or item_bank.dimensions[0]
        return cls(assessment_id, subject_id, item_bank, config, selected_dimension)

    @property
    def selected_item_id(self) -> str | None:
        """Return the presented item awaiting a response, if any."""

        return self._selected.item_id if self._selected else None

    @property
    def last_stop_decision(self) -> StopDecision | None:
        """Return the most recent stopping evaluation."""

        return self._last_stop_decision

    @property
    def result(self) -> CATResult | None:
        """Return the completed result, if the session is complete."""

        return self._result

    def initialize(self, provider: CATProvider) -> None:
        """Initialize the provider exactly once and enter `INITIALIZED`."""

        if self.status is not SessionStatus.CREATED:
            raise SessionStateError(f"cannot initialize session from {self.status.value}")
        self.item_bank.assert_runtime_ready()
        self.provider_session = provider.start_session(
            session_id=self.assessment_id,
            item_bank=self.item_bank,
            config=self.config,
        )
        self.started_at = utc_now()
        self.status = SessionStatus.INITIALIZED

    def select_next_item(self, provider: CATProvider) -> ItemSelection:
        """Select and present the next item, respecting stop and pending guards."""

        self._require_provider()
        if self.status not in {SessionStatus.INITIALIZED, SessionStatus.IN_PROGRESS}:
            raise SessionStateError(f"cannot select an item from {self.status.value}")
        if self._selected is not None:
            raise SessionStateError("a selected item is already awaiting a response")
        self._last_stop_decision = provider.should_stop(self.provider_session)  # type: ignore[arg-type]
        if self._last_stop_decision.should_stop:
            raise SessionStoppedError(self._last_stop_decision.reason.value)
        selection = provider.select_next_item(self.provider_session)  # type: ignore[arg-type]
        self._selected = selection
        self.status = SessionStatus.IN_PROGRESS
        return selection

    def submit_response(self, provider: CATProvider, response: ResponseValue) -> CATTraceRecord:
        """Score and submit one response for the currently presented item."""

        self._require_active_response()
        assert self._selected is not None
        assert self.provider_session is not None
        item = self.item_bank.item_by_id(self._selected.item_id)
        score = item.score_response(response)
        theta_before = provider.estimate_ability(self.provider_session)
        se_before = provider.get_uncertainty(self.provider_session)
        update = provider.submit_response(self.provider_session, item.item_id, score)
        record = self._make_trace(
            response_status=ResponseStatus.ANSWERED,
            response=response,
            theta_before=theta_before,
            theta_after=update.theta,
            se_before=se_before,
            se_after=update.se,
        )
        self.traces.append(record)
        self._selected = None
        self._last_stop_decision = provider.should_stop(self.provider_session)
        return record

    def record_missing(self, provider: CATProvider, status: ResponseStatus) -> CATTraceRecord:
        """Record a supported non-answer without assigning a category score."""

        self._require_active_response()
        if status is ResponseStatus.ANSWERED:
            raise SessionStateError("answered responses must use submit_response")
        assert self._selected is not None
        assert self.provider_session is not None
        theta_before = provider.estimate_ability(self.provider_session)
        se_before = provider.get_uncertainty(self.provider_session)
        update = provider.record_non_answer(self.provider_session, self._selected.item_id, status)
        record = self._make_trace(
            response_status=status,
            response=None,
            theta_before=theta_before,
            theta_after=update.theta,
            se_before=se_before,
            se_after=update.se,
        )
        self.traces.append(record)
        self._selected = None
        self._last_stop_decision = provider.should_stop(self.provider_session)
        return record

    def complete(self, provider: CATProvider, manual: bool = False) -> CATResult:
        """Complete only after a configured stop or an explicit manual termination."""

        self._require_provider()
        if self.status is not SessionStatus.IN_PROGRESS:
            raise SessionStateError(f"cannot complete session from {self.status.value}")
        if self._selected is not None:
            raise SessionStateError("cannot complete while an item is awaiting a response")
        assert self.provider_session is not None
        decision = provider.should_stop(self.provider_session)
        if not decision.should_stop and not manual:
            raise SessionStateError("configured stopping criteria have not been reached")
        if manual:
            decision = StopDecision(True, StopReason.MANUAL_TERMINATION)
        snapshot = provider.get_result(self.provider_session, decision)
        self.completed_at = utc_now()
        self.status = SessionStatus.COMPLETED
        self._last_stop_decision = decision
        self._result = CATResult(
            assessment_id=self.assessment_id,
            subject_id=self.subject_id,
            instrument_id=self.item_bank.instrument_id,
            instrument_version=self.item_bank.version,
            population_scope=self.item_bank.target_population,
            dimension=self.dimension,
            estimate=AbilityEstimate(snapshot.theta, snapshot.se, snapshot.items_answered),
            items_administered=snapshot.items_administered,
            provider_version=self.provider_session.provider_version,
            item_bank_id=self.item_bank.item_bank_id,
            item_bank_version=self.item_bank.version,
            config_version=self.config.config_version,
            status="completed",
            started_at=self.started_at or self.completed_at,
            completed_at=self.completed_at,
            duration_seconds=elapsed_seconds(self.started_at or self.completed_at, self.completed_at),
            stopping_reason=decision.reason,
            traces=tuple(self.traces),
        )
        self._result.validate()
        return self._result

    def pause(self) -> None:
        """Move an active session to the reserved paused state."""

        if self.status not in {SessionStatus.INITIALIZED, SessionStatus.IN_PROGRESS}:
            raise SessionStateError(f"cannot pause session from {self.status.value}")
        if self._selected is not None:
            raise SessionStateError("cannot pause while an item is awaiting a response")
        self.status = SessionStatus.PAUSED

    def resume(self) -> None:
        """Resume a paused session without changing provider versions."""

        if self.status is not SessionStatus.PAUSED:
            raise SessionStateError(f"cannot resume session from {self.status.value}")
        self.status = SessionStatus.IN_PROGRESS

    def cancel(self) -> None:
        """Move an initialized or active session to the reserved cancelled state."""

        if self.status not in {SessionStatus.INITIALIZED, SessionStatus.IN_PROGRESS, SessionStatus.PAUSED}:
            raise SessionStateError(f"cannot cancel session from {self.status.value}")
        self.status = SessionStatus.CANCELLED

    def mark_error(self) -> None:
        """Move a non-terminal session to the reserved error state."""

        if self.status in {SessionStatus.COMPLETED, SessionStatus.CANCELLED}:
            raise SessionStateError(f"cannot mark {self.status.value} session as ERROR")
        self.status = SessionStatus.ERROR

    def _make_trace(
        self,
        response_status: ResponseStatus,
        response: ResponseValue | None,
        theta_before: float,
        theta_after: float,
        se_before: float,
        se_after: float,
    ) -> CATTraceRecord:
        """Create a trace from the selected item and provider metadata."""

        assert self._selected is not None
        assert self.provider_session is not None
        return CATTraceRecord(
            sequence_number=len(self.traces) + 1,
            item_id=self._selected.item_id,
            response_status=response_status,
            response=response,
            theta_before=float(theta_before),
            theta_after=float(theta_after),
            se_before=float(se_before),
            se_after=float(se_after),
            selection_criterion=self._selected.criterion,
            selection_score=self._selected.score,
            timestamp=utc_now(),
            provider_version=self.provider_session.provider_version,
            item_bank_version=self.item_bank.version,
            config_version=self.config.config_version,
        )

    def _require_provider(self) -> None:
        if self.provider_session is None:
            raise SessionStateError("session has not been initialized")

    def _require_active_response(self) -> None:
        if self.status is not SessionStatus.IN_PROGRESS:
            raise SessionStateError(f"cannot record a response from {self.status.value}")
        if self._selected is None:
            raise SessionStateError("no item is awaiting a response")

