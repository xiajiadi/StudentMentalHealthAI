"""School-isolated document store and lexical retrieval for the public demo."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

import httpx

from smhai_backend.core.errors import ErrorCode, error

MAX_UPLOAD = 50 * 1024 * 1024
MAX_DOCUMENTS = 32
_TERMS = re.compile(r"[\u3400-\u9fff]+|[^\W_]+", re.UNICODE)
_LAYERS = {
    "policy": ("政策", "制度", "规范", "实施框架", "权益", "policy", "guideline", "framework", "implementation"),
    "intervention": ("干预", "活动", "训练", "练习", "预防", "intervention", "training", "programme", "exercise", "prevention"),
    "theory": ("理论", "研究", "机制", "模型", "综述", "theory", "research", "review", "model"),
}
_FIELDS = "ref, title, layer, imported_at, chunk_count"


def library_path(school_ref: str) -> Path:
    directory = os.environ.get("SMHAI_DEMO_LIBRARY_DIRECTORY")
    if not directory or not Path(directory).is_dir():
        raise error(ErrorCode.DEPENDENCY_UNAVAILABLE, detail="school library storage is not configured")
    name = hashlib.sha256(school_ref.encode("ascii")).hexdigest()
    return Path(directory) / f"{name}.sqlite"


def _extract(content: BinaryIO, suffix: str) -> str:
    worker = Path(__file__).with_name("library_extract.py")
    args = [sys.executable, "-I", str(worker), suffix]
    if suffix == ".pdf" and (wheel := os.environ.get("SMHAI_DEMO_LIBRARY_PDF_WHEEL")):
        args.append(wheel)
    try:
        content.seek(0)
        response = subprocess.run(args, stdin=content, capture_output=True, timeout=30, check=False)
    except subprocess.TimeoutExpired:
        raise error(ErrorCode.VALIDATION_FAILED, detail="document processing time limit reached") from None
    if response.returncode == 3:
        raise error(ErrorCode.DEPENDENCY_UNAVAILABLE, detail="PDF processing is unavailable")
    if response.returncode != 0:
        raise error(ErrorCode.VALIDATION_FAILED, detail="could not read document text")
    return response.stdout.decode("utf-8")


def _layer(title: str, text: str) -> str:
    head = title.casefold()
    body = text[:8000].casefold()
    scores = {
        layer: sum(4 * (word in head) + min(body.count(word), 3) for word in words)
        for layer, words in _LAYERS.items()
    }
    chosen = max(scores, key=scores.__getitem__)
    return chosen if scores[chosen] else "theory"


def _words(text: str) -> list[str]:
    tokens = []
    for value in _TERMS.findall(text.casefold()):
        if "\u3400" <= value[0] <= "\u9fff" and len(value) > 1:
            tokens.extend(value[i:i + 2] for i in range(len(value) - 1))
        else:
            tokens.append(value)
    return tokens


def _open(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=4)
    db.row_factory = sqlite3.Row
    return db


def _find_import(db: sqlite3.Connection, fingerprint: str) -> dict | None:
    existing = db.execute(
        f"SELECT {_FIELDS} FROM documents WHERE digest = ?", (fingerprint,)
    ).fetchone()
    if existing is None:
        return None
    if existing["chunk_count"] == 0:
        raise error(ErrorCode.WORKFLOW_CONFLICT, detail="document has been withdrawn")
    return dict(existing)


def _require_capacity(db: sqlite3.Connection) -> None:
    if db.execute("SELECT count(*) FROM documents WHERE chunk_count > 0").fetchone()[0] >= MAX_DOCUMENTS:
        raise error(ErrorCode.VALIDATION_FAILED, detail="school library capacity reached")


def add_document(path: Path, filename: str, content: BinaryIO, reviewer_ref: str) -> tuple[dict, bool]:
    filename = filename.strip()
    suffix = Path(filename).suffix.lower()
    if not 1 <= len(filename) <= 160 or re.search(r"[/\\\x00-\x1f\x7f]", filename):
        raise error(ErrorCode.VALIDATION_FAILED, detail="invalid document name")
    if suffix not in {".pdf", ".docx", ".txt", ".md"} or not 0 < content.seek(0, 2) <= MAX_UPLOAD:
        raise error(ErrorCode.VALIDATION_FAILED, detail="unsupported or oversized document")
    content.seek(0)
    fingerprint = hashlib.file_digest(content, "sha256").hexdigest()
    with closing(_open(path)) as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS documents (
                ref TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
                layer TEXT NOT NULL, imported_at TEXT NOT NULL, chunk_count INTEGER NOT NULL,
                uploader_ref TEXT NOT NULL
            )"""
        )
        db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(ref UNINDEXED, ordinal UNINDEXED, text UNINDEXED, terms)")
        existing = _find_import(db, fingerprint)
        if existing is not None:
            return existing, False
        _require_capacity(db)

    title = Path(filename).stem
    text = _extract(content, suffix)
    chunks = [text[start:start + 880].strip() for start in range(0, len(text), 780)]
    chunks = [chunk for chunk in chunks if chunk]
    document = (
        "LIB_" + uuid4().hex, title, _layer(title, text), datetime.now(UTC).isoformat(),
        len(chunks), reviewer_ref, fingerprint,
    )
    with closing(_open(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        existing = _find_import(db, fingerprint)
        if existing is not None:
            return existing, False
        _require_capacity(db)
        db.execute(
            "INSERT INTO documents (ref,title,layer,imported_at,chunk_count,uploader_ref,digest) VALUES (?,?,?,?,?,?,?)",
            document,
        )
        db.executemany(
            "INSERT INTO chunks (ref,ordinal,text,terms) VALUES (?,?,?,?)",
            ((document[0], index, chunk, " ".join(_words(chunk))) for index, chunk in enumerate(chunks, 1)),
        )
        row = db.execute(f"SELECT {_FIELDS} FROM documents WHERE ref = ?", (document[0],)).fetchone()
        return dict(row), True


def list_documents(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with closing(_open(path)) as db:
        return [
            dict(row) for row in db.execute(
                f"SELECT {_FIELDS} FROM documents WHERE chunk_count > 0 ORDER BY imported_at DESC"
            )
        ]


def withdraw_document(path: Path, ref: str, reviewer_ref: str) -> None:
    if not path.is_file():
        raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="document was not found")
    with closing(_open(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        document = db.execute("SELECT chunk_count FROM documents WHERE ref = ?", (ref,)).fetchone()
        if document is None:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="document was not found")
        if document["chunk_count"] == 0:
            return
        db.execute(
            """CREATE TABLE IF NOT EXISTS document_withdrawals (
                ref TEXT PRIMARY KEY, withdrawn_at TEXT NOT NULL, withdrawn_by TEXT NOT NULL
            )"""
        )
        db.execute(
            "INSERT INTO document_withdrawals (ref, withdrawn_at, withdrawn_by) VALUES (?, ?, ?)",
            (ref, datetime.now(UTC).isoformat(), reviewer_ref),
        )
        db.execute("DELETE FROM chunks WHERE ref = ?", (ref,))
        db.execute("UPDATE documents SET chunk_count = 0 WHERE ref = ?", (ref,))


async def retrieve(school_ref: str, query: str) -> list[dict]:
    key_file = os.environ.get("SMHAI_DEMO_LIBRARY_RAG_KEY")
    if not key_file:
        raise error(ErrorCode.DEPENDENCY_UNAVAILABLE, detail="school library retrieval is not configured")
    try:
        key = Path(key_file).read_bytes()
        if len(key) != 32:
            raise ValueError()
        body = json.dumps({"school_ref": school_ref, "query": query}, ensure_ascii=False).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(key, timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        async with httpx.AsyncClient(timeout=6, trust_env=False) as client:
            response = await client.post(
                "http://127.0.0.1:8170/internal/rag/school-library/retrieval",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-PsyNova-Library-Time": timestamp,
                    "X-PsyNova-Library-Signature": signature,
                },
            )
            response.raise_for_status()
            matches = response.json()["items"]
        if not isinstance(matches, list):
            raise ValueError()
        return matches
    except (OSError, ValueError, KeyError, httpx.HTTPError):
        raise error(ErrorCode.DEPENDENCY_UNAVAILABLE, detail="school library retrieval unavailable", retryable=True) from None
