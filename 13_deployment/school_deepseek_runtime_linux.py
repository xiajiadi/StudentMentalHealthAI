"""Serve the fixed DeepSeek Runtime plus the authenticated independent-student route."""

from __future__ import annotations

import os

import llm_runtime.api.app as runtime_api
import uvicorn
from school_deepseek_independent_runtime import attach_deepseek_independent_route


def main() -> None:
    app = runtime_api.app
    runtime = app.state.llm_runtime
    attach_deepseek_independent_route(app, runtime)
    port = int(os.environ.get("SMHAI_LLM_PORT", "8160"))
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
