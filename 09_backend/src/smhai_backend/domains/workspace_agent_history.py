"""Persist a bounded workspace transcript without provider prompts or attachment contents."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import closing
from time import time
from uuid import uuid4

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.idempotency import fingerprint
from smhai_backend.domains.models import Actor

from .workspace_agent_cat_store import WorkspaceCatStore

_RETENTION_SECONDS = 7 * 24 * 60 * 60
_LEASE_SECONDS = 210
_MAX_EVENTS = 160
_MAX_CONCURRENT_RUNS = 12


def workspace_owner(actor: Actor) -> str:
    return fingerprint(
        {
            "actor": actor.user_id,
            "school": actor.school_id,
            "school_ref": actor.school_ref,
            "role": actor.role.value,
        }
    )


class WorkspaceHistory:
    def __init__(self, path: str) -> None:
        self.path = path
        self.cat = WorkspaceCatStore(path)
        self.running: dict[tuple[str, str], asyncio.Task[None]] = {}
        with closing(self.connect()) as db, db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS workspace_history (
                    owner TEXT PRIMARY KEY, updated REAL NOT NULL, run TEXT,
                    events TEXT NOT NULL
                )"""
            )

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=2)

    def read(
        self, owner: str, since: str | None = None
    ) -> tuple[list[dict] | None, str | None, str]:
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT events, run, updated FROM workspace_history WHERE owner=?",
                (owner,),
            ).fetchone()
        now = time()
        if row is None or row[2] < now - _RETENTION_SECONDS:
            return (None if since == "empty" else []), None, "empty"
        active_run = row[1] if row[2] >= now - _LEASE_SECONDS else None
        revision = f"{row[2]:.9f}-{active_run or 'idle'}"
        if since == revision:
            return None, active_run, revision
        events = json.loads(row[0])
        if row[1] and active_run is None:
            events.append({"type": "end", "status": "interrupted", "run_id": row[1]})
        return events, active_run, revision

    def acquire(
        self, owner: str, *, replaces: str | None = None, start: dict | None = None
    ) -> tuple[str, list[dict]]:
        if len(self.running) >= _MAX_CONCURRENT_RUNS:
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="workspace is busy",
                retryable=True,
            )
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            now = time()
            db.execute(
                "DELETE FROM workspace_history WHERE updated < ?",
                (now - _RETENTION_SECONDS,),
            )
            row = db.execute(
                "SELECT events, run, updated FROM workspace_history WHERE owner=?", (owner,)
            ).fetchone()
            if row is not None and row[1] and row[2] >= now - _LEASE_SECONDS:
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="a workspace run is active")
            events = json.loads(row[0]) if row else []
            if row and row[1]:
                events.append({"type": "end", "status": "interrupted", "run_id": row[1]})
            if replaces is not None and (not events or events[-1]["run_id"] != replaces):
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="workspace run changed")
            run_id = uuid4().hex
            stored = events if start is None else [*events, {**start, "run_id": run_id}]
            db.execute(
                """INSERT INTO workspace_history VALUES (?, ?, ?, ?)
                   ON CONFLICT(owner) DO UPDATE SET updated=excluded.updated, run=excluded.run,
                   events=excluded.events""",
                (owner, now, run_id, json.dumps(stored[-_MAX_EVENTS:], ensure_ascii=False)),
            )
        return run_id, events

    def allows_confirmation(
        self, owner: str, run_id: str | None, *, token: str | None = None
    ) -> bool:
        events, active, _ = self.read(owner)
        events = events or []
        if run_id is None and token is not None:
            # Tokens issued before run binding may still be open in another tab.
            run_id = next((
                event["run_id"] for event in events
                if event["type"] == "tool_result" and event["view"].get("token") == token
            ), None)
        if run_id is None:
            return True
        if any(
            event["type"] == "start" and event.get("replaces_run_id") == run_id
            for event in events
        ):
            return False
        if active == run_id:
            task = self.running.get((owner, run_id))
            return task is not None and not task.cancelling()
        return any(
            event["run_id"] == run_id and event["type"] == "end" and event["status"] == "completed"
            for event in events
        )

    def append(self, owner: str, run_id: str, event: dict) -> None:
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT events FROM workspace_history WHERE owner=? AND run=?", (owner, run_id)
            ).fetchone()
            if row is None:
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="workspace run changed")
            events = [*json.loads(row[0]), {**event, "run_id": run_id}][-_MAX_EVENTS:]
            db.execute(
                "UPDATE workspace_history SET updated=?, run=?, events=? WHERE owner=?",
                (
                    time(),
                    None if event["type"] == "end" else run_id,
                    json.dumps(events, ensure_ascii=False),
                    owner,
                ),
            )

    def reset(self, owner: str) -> None:
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT run, updated FROM workspace_history WHERE owner=?", (owner,)
            ).fetchone()
            if row and row[0] and row[1] >= time() - _LEASE_SECONDS:
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="a workspace run is active")
            db.execute("DELETE FROM workspace_history WHERE owner=?", (owner,))

    async def stop_runs(self) -> None:
        tasks = tuple(self.running.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
