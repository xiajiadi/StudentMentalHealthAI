"""Persist a bounded workspace transcript without provider prompts or attachment contents."""

from __future__ import annotations

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
        with closing(self.connect()) as db, db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS workspace_history (
                    owner TEXT PRIMARY KEY, updated REAL NOT NULL, run TEXT,
                    events TEXT NOT NULL
                )"""
            )

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=2)

    def read(self, owner: str) -> tuple[list[dict], bool]:
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT events, run, updated FROM workspace_history WHERE owner=?",
                (owner,),
            ).fetchone()
        if row is None or row[2] < time() - _RETENTION_SECONDS:
            return [], False
        events = json.loads(row[0])
        active = bool(row[1] and row[2] >= time() - _LEASE_SECONDS)
        if row[1] and not active:
            events.append({"type": "end", "status": "interrupted", "run_id": row[1]})
        return events, active

    def acquire(self, owner: str) -> tuple[str, list[dict]]:
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
            run_id = uuid4().hex
            db.execute(
                """INSERT INTO workspace_history VALUES (?, ?, ?, ?)
                   ON CONFLICT(owner) DO UPDATE SET updated=excluded.updated, run=excluded.run,
                   events=excluded.events""",
                (owner, now, run_id, json.dumps(events, ensure_ascii=False)),
            )
        return run_id, events

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
