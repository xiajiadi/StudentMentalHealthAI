"""Small helper for stable idempotent write semantics."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from fastapi import Request

from smhai_backend.core.async_utils import maybe_await
from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.models import IdempotencyRecord
from smhai_backend.domains.ports import IdempotencyStore


def request_key(request: Request) -> str | None:
    value = request.headers.get("Idempotency-Key")
    if not value:
        return None
    value = value.strip()
    if not value or len(value) > 200:
        raise error(ErrorCode.VALIDATION_FAILED, detail="invalid idempotency key")
    return value


def fingerprint(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def prior_result(
    store: IdempotencyStore, *, scope: str, key: str, request_fingerprint: str
) -> dict[str, Any] | None:
    record = store.get(scope, key)
    if record is None:
        return None
    if record.fingerprint != request_fingerprint:
        raise error(
            ErrorCode.WORKFLOW_CONFLICT,
            detail="idempotency key was already used for another request",
        )
    return dict(record.body)


def remember_result(
    store: IdempotencyStore,
    *,
    scope: str,
    key: str | None,
    request_fingerprint: str,
    status_code: int,
    body: dict[str, Any],
) -> None:
    if key is not None:
        store.put(
            scope,
            key,
            IdempotencyRecord(
                fingerprint=request_fingerprint,
                status_code=status_code,
                body=dict(body),
                created_at=time.time(),
            ),
        )


async def prior_result_async(
    store: IdempotencyStore, *, scope: str, key: str, request_fingerprint: str
) -> dict[str, Any] | None:
    record = await maybe_await(store.get(scope, key))
    if record is None:
        claim = getattr(store, "claim", None)
        if claim is not None:
            claimed = await maybe_await(claim(scope, key, request_fingerprint))
            if claimed:
                return None
            record = await maybe_await(store.get(scope, key))
            if record is None:
                return None
        if record is None:
            return None
    if record.fingerprint != request_fingerprint:
        raise error(
            ErrorCode.WORKFLOW_CONFLICT,
            detail="idempotency key was already used for another request",
        )
    if not record.body:
        raise error(
            ErrorCode.WORKFLOW_CONFLICT,
            detail="idempotency result is durable; retrieve the referenced resource",
        )
    return dict(record.body)


async def remember_result_async(
    store: IdempotencyStore,
    *,
    scope: str,
    key: str | None,
    request_fingerprint: str,
    status_code: int,
    body: dict[str, Any],
) -> None:
    if key is not None:
        await maybe_await(
            store.put(
                scope,
                key,
                IdempotencyRecord(
                    fingerprint=request_fingerprint,
                    status_code=status_code,
                    body=dict(body),
                    created_at=time.time(),
                ),
            )
        )
