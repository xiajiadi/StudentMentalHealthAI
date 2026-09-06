"""Development entry point."""

from __future__ import annotations

import uvicorn

from .app_factory import create_app
from .core.config import BackendSettings

app = create_app()


def main() -> None:
    settings = BackendSettings()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
