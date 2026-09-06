"""Single-process engineering rate limiter; no production-distributed claim."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping
from time import monotonic

from .errors import ErrorCode, error


class InMemoryRateLimiter:
    def __init__(
        self,
        *,
        max_requests: int | None = None,
        limits: Mapping[str, int] | None = None,
        window_seconds: int,
    ):
        self.max_requests = max_requests
        self.limits = dict(limits or {})
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, bucket: str, identity: str) -> None:
        now = monotonic()
        key = f"{bucket}:{identity}"
        events = self._events[key]
        cutoff = now - self.window_seconds
        while events and events[0] <= cutoff:
            events.popleft()
        max_requests = self.limits.get(bucket, self.max_requests)
        if max_requests is None:
            raise ValueError(f"no rate limit configured for bucket {bucket}")
        if len(events) >= max_requests:
            retry_after = max(1, int(events[0] + self.window_seconds - now + 0.999))
            raise error(
                ErrorCode.RATE_LIMITED,
                detail="request rate limit exceeded",
                retryable=True,
                retry_after=retry_after,
            )
        events.append(now)

    def clear(self) -> None:
        self._events.clear()
