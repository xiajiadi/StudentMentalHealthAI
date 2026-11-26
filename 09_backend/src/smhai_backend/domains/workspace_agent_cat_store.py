"""Bounded, private CAT attachments and school-scoped workspace handoffs."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from time import time
from uuid import uuid4

from smhai_backend.core.errors import ErrorCode, error

_ATTACHMENT_LIFETIME = 24 * 3600
_PREVIEW_LIFETIME = 7 * 24 * 3600


class WorkspaceCatStore:
    def __init__(self, path: str):
        self.path = path
        with closing(self.connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS workspace_cat_attachment (
                    ref TEXT PRIMARY KEY, owner TEXT NOT NULL, created REAL NOT NULL,
                    document TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS workspace_cat_attachment_owner
                    ON workspace_cat_attachment(owner, created);
                CREATE TABLE IF NOT EXISTS workspace_cat_draft (
                    ref TEXT PRIMARY KEY, owner TEXT NOT NULL, school TEXT NOT NULL,
                    created REAL NOT NULL, state TEXT NOT NULL, data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS workspace_cat_draft_school
                    ON workspace_cat_draft(school, state, created);
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=2)
        db.execute("PRAGMA secure_delete=ON")
        return db

    def upload(self, owner: str, document: dict) -> str:
        ref = uuid4().hex
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            self._prune(db)
            # Keep a small number of still-pending attachments per workspace.
            count = db.execute(
                "SELECT COUNT(*) FROM workspace_cat_attachment WHERE owner=?", (owner,)
            ).fetchone()[0]
            if count >= 6:
                raise error(ErrorCode.WORKFLOW_CONFLICT, detail="CAT attachment limit reached")
            db.execute(
                "INSERT INTO workspace_cat_attachment VALUES (?,?,?,?)",
                (ref, owner, time(), json.dumps(document, ensure_ascii=False, allow_nan=False)),
            )
        return ref

    @staticmethod
    def _prune(db):
        db.execute(
            "DELETE FROM workspace_cat_attachment WHERE created<?",
            (time() - _ATTACHMENT_LIFETIME,),
        )
        db.execute(
            """DELETE FROM workspace_cat_draft
               WHERE state='PREVIEW' AND created<?""",
            (time() - _PREVIEW_LIFETIME,),
        )

    def attachment(self, owner: str, ref: str | None) -> tuple[str, dict]:
        with closing(self.connect()) as db:
            row = db.execute(
                """SELECT ref, document FROM workspace_cat_attachment
                   WHERE owner=? AND created>? AND (? IS NULL OR ref=?)
                   ORDER BY created DESC LIMIT 1""",
                (owner, time() - _ATTACHMENT_LIFETIME, ref, ref),
            ).fetchone()
        if row is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="CAT attachment missing or expired")
        return row[0], json.loads(row[1])

    def create_draft(self, ref: str, owner: str, school: str, preview: dict):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            self._prune(db)
            db.execute(
                """INSERT OR IGNORE INTO workspace_cat_draft VALUES (?,?,?,?,?,?)""",
                (ref, owner, school, time(), "PREVIEW", json.dumps(preview)),
            )
        return self.draft(owner, ref)

    def draft(self, owner: str, ref: str) -> tuple[str, dict]:
        with closing(self.connect()) as db:
            row = db.execute(
                """SELECT state, data FROM workspace_cat_draft WHERE owner=? AND ref=?
                   AND (state!='PREVIEW' OR created>?)""",
                (owner, ref, time() - _PREVIEW_LIFETIME),
            ).fetchone()
        if row is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="CAT draft unavailable")
        return row[0], json.loads(row[1])

    def advance(self, owner: str, ref: str, previous: str, state: str, data: dict):
        with closing(self.connect()) as db, db:
            db.execute(
                """UPDATE workspace_cat_draft SET state=?, data=? WHERE ref=? AND owner=?
                   AND state=?""",
                (state, json.dumps(data), ref, owner, previous),
            )
        return self.draft(owner, ref)

    def handoffs(self, school: str, ref: str | None = None):
        with closing(self.connect()) as db:
            rows = db.execute(
                """SELECT ref, data FROM workspace_cat_draft WHERE school=?
                   AND (state='APPROVED' OR (? IS NOT NULL AND state='PUBLISHED'))
                   AND (? IS NULL OR ref=?) ORDER BY created DESC LIMIT 20""",
                (school, ref, ref, ref),
            ).fetchall()
        return [(key, json.loads(data)) for key, data in rows]

    def mark_published(self, school: str, ref: str, task_ref: str):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT data FROM workspace_cat_draft
                   WHERE school=? AND ref=? AND state='APPROVED'""",
                (school, ref),
            ).fetchone()
            if row:
                data = json.loads(row[0])
                data["published_task_ref"] = task_ref
                db.execute(
                    "UPDATE workspace_cat_draft SET state='PUBLISHED', data=? WHERE ref=?",
                    (json.dumps(data), ref),
                )

    def published_handoff_refs(self, school: str, refs: set[str]) -> set[str]:
        if not refs:
            return set()
        with closing(self.connect()) as db:
            rows = db.execute(
                """SELECT ref FROM workspace_cat_draft WHERE school=? AND state='PUBLISHED'
                   AND ref IN (SELECT value FROM json_each(?))""",
                (school, json.dumps(sorted(refs))),
            ).fetchall()
        return {row[0] for row in rows}

    def specialist_drafts(self, owner: str):
        with closing(self.connect()) as db:
            rows = db.execute(
                """SELECT ref, state, data FROM workspace_cat_draft WHERE owner=?
                   AND (state!='PREVIEW' OR created>?) ORDER BY created DESC LIMIT 10""",
                (owner, time() - _PREVIEW_LIFETIME),
            ).fetchall()
        return [(ref, state, json.loads(data)) for ref, state, data in rows]
