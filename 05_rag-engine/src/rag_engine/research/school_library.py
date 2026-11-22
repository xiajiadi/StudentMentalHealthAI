"""Authenticated retrieval from the school-isolated library index."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

router = APIRouter()
_SCHOOL = re.compile(r"PUBLICDEMO_[a-f0-9]{64}\Z")
_TERMS = re.compile(r"[\u3400-\u9fff]+|[^\W_]+", re.UNICODE)


def _search(path: Path, query: str) -> list[dict]:
    terms = []
    for value in _TERMS.findall(query.casefold()):
        if "\u3400" <= value[0] <= "\u9fff" and len(value) > 1:
            terms.extend(value[i:i + 2] for i in range(len(value) - 1))
        else:
            terms.append(value)
    words = tuple(dict.fromkeys(terms))[:40]
    if not words or not path.exists():
        return []
    expression = " OR ".join(f'"{word}"' for word in words)
    connection = sqlite3.connect(f"file:{quote(str(path), safe='/')}?mode=ro", uri=True, timeout=4)
    with closing(connection) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(
            """SELECT d.ref, d.title, d.layer, c.ordinal, c.text
               FROM chunks c JOIN documents d ON d.ref = c.ref
               WHERE chunks MATCH ? ORDER BY bm25(chunks) LIMIT 12""",
            (expression,),
        )]


@router.post("/internal/rag/school-library/retrieval", include_in_schema=False)
async def retrieve_school_library(request: Request):
    directory = os.environ.get("SMHAI_RAG_SCHOOL_LIBRARY_DIRECTORY")
    key_file = os.environ.get("SMHAI_RAG_SCHOOL_LIBRARY_KEY")
    if not directory or not key_file:
        raise HTTPException(503, detail="school library unavailable")
    timestamp = request.headers.get("x-psynova-library-time", "")
    signature = request.headers.get("x-psynova-library-signature", "")
    if not re.fullmatch(r"[0-9]{10}", timestamp) or abs(int(timestamp) - time.time()) > 30:
        raise HTTPException(403, detail="access denied")
    if not re.fullmatch(r"[0-9a-f]{64}", signature):
        raise HTTPException(403, detail="access denied")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 1024:
            raise HTTPException(422, detail="invalid query")
        body.extend(chunk)
    try:
        key = Path(key_file).read_bytes()
        if len(key) != 32:
            raise ValueError()
    except (OSError, ValueError):
        raise HTTPException(503, detail="school library unavailable") from None
    expected = hmac.new(key, timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(403, detail="access denied")
    try:
        payload = json.loads(body)
        school, query = payload["school_ref"], payload["query"]
        if (
            set(payload) != {"school_ref", "query"}
            or not _SCHOOL.fullmatch(school)
            or not isinstance(query, str)
            or not 1 <= len(query) <= 160
        ):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise HTTPException(422, detail="invalid query") from None
    path = Path(directory) / (hashlib.sha256(school.encode("ascii")).hexdigest() + ".sqlite")
    try:
        matches = await run_in_threadpool(_search, path, query)
    except (OSError, sqlite3.Error):
        raise HTTPException(503, detail="school library retrieval unavailable") from None
    return {"items": matches}
