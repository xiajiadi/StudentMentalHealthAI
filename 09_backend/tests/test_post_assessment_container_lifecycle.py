from __future__ import annotations

from typing import Any

import pytest

from smhai_backend.container import build_container
from smhai_backend.core.config import BackendSettings


class _FakePersistence:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def start(self) -> None:
        self.events.append("persistence.start")

    async def close(self) -> None:
        self.events.append("persistence.close")


class _FakeSafety:
    def __init__(self, events: list[str], *, fail_start: bool = False) -> None:
        self.events = events
        self.fail_start = fail_start

    async def start(self) -> None:
        self.events.append("safety.start")
        if self.fail_start:
            raise RuntimeError("synthetic safety startup failure")

    async def close(self) -> None:
        self.events.append("safety.close")


class _FakeWorkerManager:
    def __init__(
        self,
        events: list[str],
        *,
        fail_start: bool = False,
        fail_close: bool = False,
    ) -> None:
        self.events = events
        self.fail_start = fail_start
        self.fail_close = fail_close

    async def start(self) -> None:
        assert "safety.start" in self.events
        self.events.append("worker.start")
        if self.fail_start:
            raise RuntimeError("synthetic worker startup failure")

    async def close(self) -> None:
        self.events.append("worker.close")
        if self.fail_close:
            raise RuntimeError("synthetic worker shutdown failure")


def _container(
    events: list[str],
    *,
    safety_fails: bool = False,
    worker_fails_start: bool = False,
    worker_fails_close: bool = False,
):
    container: Any = build_container(BackendSettings(_env_file=None))
    container.persistence = _FakePersistence(events)
    container.safety = _FakeSafety(events, fail_start=safety_fails)
    container.post_assessment_worker_manager = _FakeWorkerManager(
        events,
        fail_start=worker_fails_start,
        fail_close=worker_fails_close,
    )
    return container


@pytest.mark.asyncio
async def test_container_starts_safety_before_worker_and_stops_worker_before_persistence():
    events: list[str] = []
    container = _container(events)

    await container.start()
    await container.close()

    assert events == [
        "persistence.start",
        "safety.start",
        "worker.start",
        "worker.close",
        "safety.close",
        "persistence.close",
    ]


@pytest.mark.asyncio
async def test_safety_start_failure_closes_worker_clients_and_persistence():
    events: list[str] = []
    container = _container(events, safety_fails=True)

    with pytest.raises(RuntimeError, match="synthetic safety startup failure"):
        await container.start()

    assert events == [
        "persistence.start",
        "safety.start",
        "worker.close",
        "safety.close",
        "persistence.close",
    ]


@pytest.mark.asyncio
async def test_worker_start_failure_closes_initialized_safety_and_persistence():
    events: list[str] = []
    container = _container(events, worker_fails_start=True)

    with pytest.raises(RuntimeError, match="synthetic worker startup failure"):
        await container.start()

    assert events == [
        "persistence.start",
        "safety.start",
        "worker.start",
        "worker.close",
        "safety.close",
        "persistence.close",
    ]


@pytest.mark.asyncio
async def test_worker_shutdown_failure_releases_clients_but_does_not_close_database():
    events: list[str] = []
    container = _container(events, worker_fails_close=True)

    with pytest.raises(RuntimeError, match="worker shutdown did not complete"):
        await container.close()

    assert events == ["worker.close", "safety.close"]
