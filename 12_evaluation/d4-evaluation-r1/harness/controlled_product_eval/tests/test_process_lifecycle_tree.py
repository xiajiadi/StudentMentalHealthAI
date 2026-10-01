from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from harness.controlled_product_eval.process_lifecycle import (
    ProcessSpec,
    ProcessSupervisor,
)


def _free_loopback_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object lifecycle contract")
@pytest.mark.asyncio
async def test_job_cleanup_owns_venv_launcher_descendants_without_stopping_sibling(
    tmp_path: Path,
) -> None:
    port = _free_loopback_port()
    listener = (
        "from http.server import BaseHTTPRequestHandler, HTTPServer; "
        "H=type('H',(BaseHTTPRequestHandler,),{"
        "'do_GET':lambda self:(self.send_response(200),"
        "self.send_header('Content-Type','application/json'),self.end_headers(),"
        "self.wfile.write(b'{\\\"status\\\":\\\"READY\\\"}')),"
        "'log_message':lambda *a:None}); "
        f"HTTPServer(('127.0.0.1',{port}),H).serve_forever()"
    )
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{listener!r}]); "
        "time.sleep(120)"
    )
    sibling = subprocess.Popen(
        [sys.executable, "-c", "import time;time.sleep(120)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
    )
    manager = ProcessSupervisor(startup_timeout_seconds=10, shutdown_timeout_seconds=1)
    spec = ProcessSpec(
        name="test-venv-tree",
        executable=Path(sys.executable).resolve(),
        arguments=("-c", parent),
        cwd=tmp_path.resolve(),
        environment={},
        readiness_url=f"http://127.0.0.1:{port}/health/ready",
        readiness_kind="service",
        log_path=tmp_path / "tree.stdout.log",
        stderr_log_path=tmp_path / "tree.stderr.log",
        environment_allowlist=frozenset(),
    )
    try:
        identities = await manager.start([spec])
        identity = identities[0]
        process_tree_pids = identity["process_tree_pids"]
        assert identity["job_active_process_count"] >= 2
        assert identity["pid"] in process_tree_pids
        assert len(process_tree_pids) >= 2

        cleanup = await manager.close()

        assert cleanup["cleanup_verified"] is True
        stopped = cleanup["services"][0]
        assert stopped["job_active_process_count_after_stop"] == 0
        assert stopped["remaining_process_tree_pids"] == []
        assert stopped["endpoint_down"] is True
        assert stopped["shutdown_method"] in {
            "CTRL_BREAK_EVENT",
            "JOB_OBJECT_TERMINATE_FALLBACK",
        }
        assert sibling.poll() is None
    finally:
        if not manager._closed:
            await manager.close()
        if sibling.poll() is None:
            sibling.terminate()
            sibling.wait(timeout=5)
