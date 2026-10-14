from types import SimpleNamespace

import pytest

from smhai_backend.container import build_container
from smhai_backend.core.config import BackendSettings


class Persistence:
    def __init__(self, events):
        self.events = events

    async def start(self):
        self.events.append("database_start")

    async def close(self):
        self.events.append("database_close")


class Process:
    def __init__(self, events, *, fail_start=False, fail_close=False):
        self.events = events
        self.fail_start = fail_start
        self.fail_close = fail_close
        self.status = "STOPPED"

    async def start(self):
        self.events.append("research_start")
        if self.fail_start:
            raise RuntimeError("bounded_test_failure")
        self.status = "READY"

    async def close(self):
        self.events.append("research_close")
        if self.fail_close:
            raise RuntimeError("bounded_test_failure")
        self.status = "STOPPED"

    async def health(self):
        return SimpleNamespace(status=self.status)


def configured_container(monkeypatch, *, fail_start=False, fail_close=False):
    events = []
    container = build_container(BackendSettings(_env_file=None))
    container.persistence = Persistence(events)
    process = Process(events, fail_start=fail_start, fail_close=fail_close)

    def factory():
        events.append("research_construct")
        return process

    async def safety_start():
        events.append("safety_start")

    async def close_clients():
        events.append("clients_close")
        return False

    container.school_research_process_factory = factory
    container.safety = SimpleNamespace(start=safety_start)
    monkeypatch.setattr(type(container), "_close_clients", lambda self: close_clients())
    return container, process, events


@pytest.mark.asyncio
async def test_research_child_constructed_after_database_and_stopped_before_database(monkeypatch):
    container, process, events = configured_container(monkeypatch)
    assert not await container.research_process_ready()
    await container.start()
    assert events == ["database_start", "research_construct", "research_start", "safety_start"]
    assert await container.research_process_ready()
    await container.close()
    assert events[-3:] == ["research_close", "clients_close", "database_close"]
    assert process.status == "STOPPED"


@pytest.mark.asyncio
async def test_research_start_failure_cleans_owned_process_and_database(monkeypatch):
    container, _process, events = configured_container(monkeypatch, fail_start=True)
    with pytest.raises(RuntimeError, match="bounded_test_failure"):
        await container.start()
    assert events[-3:] == ["research_close", "clients_close", "database_close"]
    assert "safety_start" not in events


@pytest.mark.asyncio
async def test_unconfirmed_child_shutdown_preserves_database_runtime(monkeypatch):
    container, _process, events = configured_container(monkeypatch, fail_close=True)
    await container.start()
    with pytest.raises(RuntimeError, match="research CAT process shutdown did not complete"):
        await container.close()
    assert "database_close" not in events


@pytest.mark.asyncio
async def test_dead_managed_child_is_not_ready(monkeypatch):
    container, process, _events = configured_container(monkeypatch)
    await container.start()
    process.status = "UNAVAILABLE"
    assert not await container.research_process_ready()
    await container.close()


@pytest.mark.asyncio
async def test_default_container_has_no_managed_research_dependency():
    container = build_container(BackendSettings(_env_file=None))
    assert container.school_research_process_factory is None
    assert container.school_research_process is None
    assert await container.research_process_ready()


@pytest.mark.asyncio
async def test_ready_route_tracks_required_managed_child(client, app):
    container = app.state.container
    process = Process([])
    container.school_research_process_factory = lambda: process
    container.school_research_process = process
    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "starting"
    assert response.json()["data"]["core"]["research_cat"] == "UNAVAILABLE"
    process.status = "READY"
    response = await client.get("/health/ready")
    assert response.json()["data"]["status"] == "ready"
    assert response.json()["data"]["core"]["research_cat"] == "READY"


def test_managed_process_cannot_enable_without_research_configuration():
    with pytest.raises(ValueError, match="managed research CAT requires explicit"):
        BackendSettings(_env_file=None, school_research_managed_enabled=True)
