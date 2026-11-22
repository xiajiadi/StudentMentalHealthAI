"""School-session gateway for the independent synthetic CAT Platform."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

import httpx
from database_layer.provenance import is_public_demo_school_ref
from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.auth.dependencies import CsrfActor, CurrentActor
from smhai_backend.domains.models import Actor, BackendRole

router = APIRouter(prefix="/workbench")
_ID = r"[a-f0-9]{32}"
_READ = re.compile(
    rf"(?:capabilities|banks(?:/{_ID}(?:/curves|/export)?)?|designs(?:/{_ID})?"
    rf"|sessions(?:/{_ID}(?:/provenance)?)?|experiments(?:/{_ID}(?:/export)?)?)\Z"
)
_WRITE = re.compile(
    rf"(?:banks(?:/demo|/import-csv|/{_ID}/(?:fork|publish))?|designs(?:/{_ID}/publish)?"
    rf"|sessions(?:/{_ID}/(?:answers|pause|resume))?|experiments(?:/{_ID}/retry)?)\Z"
)
_MAX_BODY = 2_000_000


def _configuration(request: Request, actor: Actor) -> tuple[Path, Path]:
    if (
        request.app.state.container.settings.public_demo.site_key is None
        or actor.role is not BackendRole.PSYCHOLOGICAL_SPECIALIST
        or actor.scope_profile != "school_tenant"
        or type(actor.school_id) is not int
        or actor.school_id <= 0
        or not actor.school_ref
        or not is_public_demo_school_ref(actor.school_ref)
    ):
        raise error(ErrorCode.FORBIDDEN, detail="access denied")
    state = os.environ.get("SMHAI_DEMO_CAT_STATE")
    socket = os.environ.get("SMHAI_DEMO_CAT_SOCKET")
    if not state or not socket or not (Path(state) / "cat.sqlite3").is_file() or not Path(socket).is_socket():
        raise error(ErrorCode.DEPENDENCY_UNAVAILABLE, detail="CAT workbench is not configured")
    return Path(state), Path(socket)


def _secret(state: Path) -> bytes:
    path = state / "bridge.key"
    if not path.exists():
        with NamedTemporaryFile(dir=state, delete=False) as file:
            candidate = Path(file.name)
            try:
                file.write(secrets.token_bytes(32))
                file.flush()
                os.fsync(file.fileno())
                try:
                    os.link(candidate, path)
                except FileExistsError:
                    pass
            finally:
                candidate.unlink()
    value = path.read_bytes()
    if len(value) != 32:
        raise ValueError("invalid CAT bridge key")
    return value


def _tenant_token(state: Path, actor: Actor) -> str:
    key = _secret(state)
    scope = f"{actor.school_ref}:{actor.school_id}"
    project = hmac.new(key, f"project:{scope}".encode(), hashlib.sha256).hexdigest()[:32]
    principal = hmac.new(key, f"actor:{scope}:{actor.user_id}".encode(), hashlib.sha256).hexdigest()[:32]
    token = hmac.new(key, f"token:{principal}".encode(), hashlib.sha256).hexdigest()
    fingerprint = hashlib.sha256(token.encode()).hexdigest()
    with closing(sqlite3.connect(state / "cat.sqlite3", timeout=4)) as db, db:
        if db.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise ValueError("unsupported CAT storage schema")
        if db.execute("SELECT 1 FROM tokens WHERE digest = ? AND project_id = ?", (fingerprint, project)).fetchone():
            return token
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT OR IGNORE INTO projects (id, name) VALUES (?, ?)", (project, "PsyNova 合成学校"))
        db.execute(
            """INSERT OR IGNORE INTO tokens
               (id, digest, principal, role, project_id, name, created_at)
               VALUES (?, ?, ?, 'researcher', ?, ?, ?)""",
            (principal, fingerprint, principal, project, "PsyNova 学校会话", datetime.now(UTC).isoformat()),
        )
    return token


async def _forward(request: Request, actor: Actor, path: str, body: bytes | None = None):
    state, socket = _configuration(request, actor)
    allowed = _WRITE if request.method == "POST" else _READ
    if not allowed.fullmatch(path):
        raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="unknown CAT workbench route")
    expected = (
        {"item_id"} if path.endswith("/curves")
        else {"format"} if path.startswith("experiments/") and path.endswith("/export")
        else set()
    )
    if set(request.query_params) - expected or len(request.query_params.multi_items()) != len(request.query_params):
        raise error(ErrorCode.VALIDATION_FAILED, detail="invalid CAT query")
    try:
        token = await run_in_threadpool(_tenant_token, state, actor)
        transport = httpx.AsyncHTTPTransport(uds=str(socket))
        async with httpx.AsyncClient(transport=transport, timeout=15, trust_env=False) as client:
            upstream = await client.request(
                request.method,
                f"http://cat-platform/api/v1/{path}",
                content=body,
                params=dict(request.query_params),
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
    except (httpx.HTTPError, OSError, sqlite3.Error, ValueError):
        raise error(ErrorCode.DEPENDENCY_UNAVAILABLE, detail="CAT workbench unavailable", retryable=True) from None
    headers = {"Cache-Control": "no-store"}
    if "content-disposition" in upstream.headers:
        headers["Content-Disposition"] = upstream.headers["content-disposition"]
    return Response(
        content=upstream.content, status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json"), headers=headers,
    )


@router.get("/{path:path}", include_in_schema=False)
async def read_workbench(request: Request, actor: CurrentActor, path: str):
    return await _forward(request, actor, path)


@router.post("/{path:path}", include_in_schema=False)
async def write_workbench(request: Request, actor: CsrfActor, path: str):
    _configuration(request, actor)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > _MAX_BODY:
            raise error(ErrorCode.VALIDATION_FAILED, detail="CAT request is too large")
        body.extend(chunk)
    return await _forward(request, actor, path, bytes(body) or None)
