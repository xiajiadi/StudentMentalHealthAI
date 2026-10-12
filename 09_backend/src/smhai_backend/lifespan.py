"""FastAPI lifespan for long-lived clients and process-local stores."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from smhai_backend.container import BackendContainer
from smhai_backend.core.logging import configure_logging


def make_lifespan(container: BackendContainer):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(json_logs=container.settings.observability.json_logs)
        app.state.lifecycle_started = False
        try:
            await container.start()
            app.state.lifecycle_started = True
            yield
        finally:
            await container.close()
            app.state.lifecycle_started = False

    return lifespan
