"""Start the accepted Safety Control Plane after loading its CPU guard."""

import uvicorn

from safety_engine.api.app import create_app
from safety_engine.api.factory import build_default_bundle


if __name__ == "__main__":
    bundle = build_default_bundle()
    health = bundle.service.qwen.load()
    if not health.ready:
        raise RuntimeError(f"Qwen3Guard preload failed: {health.detail_code}")
    app = create_app(bundle=bundle)
    uvicorn.run(app, host="127.0.0.1", port=8190, log_level="info")
