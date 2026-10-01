"""Fixed Safety service entrypoint with offline Qwen3Guard preload."""

from __future__ import annotations

from typing import Any, Callable


SAFETY_HOST = "127.0.0.1"
SAFETY_PORT = 8190


def start_safety_service(
    *,
    build_bundle: Callable[[], Any] | None = None,
    create_app: Callable[..., Any] | None = None,
    run_server: Callable[..., Any] | None = None,
) -> None:
    """Preload the frozen local guard model, then serve the unchanged Safety app."""

    if build_bundle is None or create_app is None or run_server is None:
        from safety_engine.api.app import create_app as app_factory
        from safety_engine.api.factory import build_default_bundle
        import uvicorn

        build_bundle = build_default_bundle
        create_app = app_factory
        run_server = uvicorn.run

    bundle = build_bundle()
    try:
        health = bundle.service.qwen.load()
    except Exception:
        raise RuntimeError("fixed offline Qwen3Guard preload failed") from None
    if getattr(health, "ready", False) is not True:
        raise RuntimeError("fixed offline Qwen3Guard preload failed")

    application = create_app(bundle=bundle)
    run_server(application, host=SAFETY_HOST, port=SAFETY_PORT, log_level="info")


if __name__ == "__main__":
    start_safety_service()
