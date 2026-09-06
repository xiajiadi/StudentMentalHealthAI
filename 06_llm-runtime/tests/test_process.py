from __future__ import annotations

import sys

from llm_runtime.runtime.process import ManagedProcess


def test_managed_process_starts_and_stops_cleanly(tmp_path):
    manager = ManagedProcess(
        command=[sys.executable, "-c", "import time; time.sleep(30)"],
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
    )

    pid = manager.start()
    assert pid > 0
    assert manager.is_running()
    assert manager.stop(timeout_seconds=2) is True
    assert not manager.is_running()

