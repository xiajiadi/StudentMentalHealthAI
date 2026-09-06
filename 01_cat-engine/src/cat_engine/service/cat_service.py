"""Small orchestration facade for the domain Session and a CATProvider."""

from __future__ import annotations

from typing import Any

from ..domain.config import CATConfig
from ..domain.enums import ResponseStatus
from ..domain.item import ResponseValue
from ..domain.item_bank import ItemBank
from ..domain.result import CATResult, RiskSnapshot
from ..domain.session import Session
from ..domain.trace import CATTraceRecord
from ..providers.base import CATProvider, ItemSelection
from .assessment_mapper import AssessmentMapper


class CATService:
    """Keep controllers independent of provider-specific implementation details."""

    def __init__(self, provider: CATProvider, mapper: AssessmentMapper | None = None) -> None:
        self.provider = provider
        self.mapper = mapper or AssessmentMapper()

    def create_session(
        self,
        assessment_id: str,
        subject_id: str,
        item_bank: ItemBank,
        config: CATConfig,
        dimension: str | None = None,
    ) -> Session:
        """Create and initialize a session through the provider interface."""

        session = Session.create(assessment_id, subject_id, item_bank, config, dimension)
        session.initialize(self.provider)
        return session

    def next_item(self, session: Session) -> ItemSelection:
        """Select the next item without exposing third-party engine types."""

        return session.select_next_item(self.provider)

    def submit_response(self, session: Session, response: ResponseValue) -> CATTraceRecord:
        """Record an answered response and its estimate transition."""

        return session.submit_response(self.provider, response)

    def record_missing(self, session: Session, status: ResponseStatus) -> CATTraceRecord:
        """Record a skipped, timed-out, invalid, or not-presented item."""

        return session.record_missing(self.provider, status)

    def complete(self, session: Session, manual: bool = False) -> CATResult:
        """Complete a session after stopping or explicit manual termination."""

        return session.complete(self.provider, manual=manual)

    def assessment(self, result: CATResult, risk: RiskSnapshot) -> dict[str, Any]:
        """Map a completed result to the frozen assessment.v1 object."""

        return self.mapper.map(result, risk)

