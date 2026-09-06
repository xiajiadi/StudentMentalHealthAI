"""Small compatibility helper for sync test adapters and async real adapters."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable


async def maybe_await[T](value: T | Awaitable[T]) -> T:
    """Await a real adapter result while keeping memory adapters lightweight."""

    if inspect.isawaitable(value):
        return await value
    return value
