from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx

from harness.controlled_product_eval import process_lifecycle
from harness.controlled_product_eval.process_lifecycle import ProcessSpec, ProcessSupervisor


def test_service_readiness_uses_fixed_profile_request_timeout(tmp_path, monkeypatch):
    observed = {}

    class ReadyResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"status": "READY"}

    class AsyncClient:
        def __init__(self, *, timeout, **_kwargs):
            observed["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url):
            return ReadyResponse()

    monkeypatch.setattr(process_lifecycle.httpx, "AsyncClient", AsyncClient)
    spec = ProcessSpec(
        name="d4-runtime",
        executable=Path("D:/fixed/runtime/python.exe"),
        arguments=("-m", "llm_runtime.api.app"),
        cwd=tmp_path,
        environment={},
        readiness_url="http://127.0.0.1:8160/health/ready",
        readiness_kind="service",
        log_path=tmp_path / "runtime.log",
        readiness_request_timeout_seconds=15.0,
        environment_allowlist=frozenset(),
    )
    owned = SimpleNamespace(spec=spec, process=SimpleNamespace(poll=lambda: None), readiness_verified=False)

    asyncio.run(ProcessSupervisor(startup_timeout_seconds=1)._wait_ready(owned))

    assert owned.readiness_verified is True
    assert isinstance(observed["timeout"], httpx.Timeout)
    assert observed["timeout"].read == 15.0
