"""Review repositories; no notification or student-content persistence."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import RLock
from typing import Protocol

from safety_engine.domain import HumanReviewCase, ReviewAuditEvent


class ReviewRepository(Protocol):
    def save(self, case: HumanReviewCase) -> HumanReviewCase: ...

    def get(self, review_case_id: str) -> HumanReviewCase | None: ...

    def save_event(self, event: ReviewAuditEvent) -> ReviewAuditEvent: ...

    def list_events(self, review_case_id: str) -> list[ReviewAuditEvent]: ...


class InMemoryReviewRepository:
    def __init__(self) -> None:
        self._cases: dict[str, HumanReviewCase] = {}
        self._events: dict[str, list[ReviewAuditEvent]] = {}
        self._lock = RLock()

    def save(self, case: HumanReviewCase) -> HumanReviewCase:
        with self._lock:
            self._cases[case.review_case_id] = case
            return case

    def get(self, review_case_id: str) -> HumanReviewCase | None:
        with self._lock:
            return self._cases.get(review_case_id)

    def save_event(self, event: ReviewAuditEvent) -> ReviewAuditEvent:
        with self._lock:
            self._events.setdefault(event.review_case_id, []).append(event)
            return event

    def list_events(self, review_case_id: str) -> list[ReviewAuditEvent]:
        with self._lock:
            return list(self._events.get(review_case_id, []))


class SQLiteReviewRepository:
    """Optional local SQLite persistence for synthetic review metadata only."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS review_cases (
                    review_case_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_events (
                    event_id TEXT PRIMARY KEY,
                    review_case_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    def save(self, case: HumanReviewCase) -> HumanReviewCase:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO review_cases(review_case_id, payload) VALUES (?, ?)",
                (case.review_case_id, case.model_dump_json()),
            )
        return case

    def get(self, review_case_id: str) -> HumanReviewCase | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM review_cases WHERE review_case_id = ?", (review_case_id,)
            ).fetchone()
        return HumanReviewCase.model_validate_json(row[0]) if row else None

    def save_event(self, event: ReviewAuditEvent) -> ReviewAuditEvent:
        with self._connect() as connection:
            connection.execute(
                (
                    "INSERT OR REPLACE INTO review_events(event_id, review_case_id, payload) "
                    "VALUES (?, ?, ?)"
                ),
                (event.event_id, event.review_case_id, event.model_dump_json()),
            )
        return event

    def list_events(self, review_case_id: str) -> list[ReviewAuditEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM review_events WHERE review_case_id = ? ORDER BY event_id",
                (review_case_id,),
            ).fetchall()
        return [ReviewAuditEvent.model_validate_json(row[0]) for row in rows]
