"""Process restart checks for the durable workspace conversation store."""

import subprocess
import sys

import pytest

from smhai_backend.app_factory import create_app
from smhai_backend.core.config import BackendSettings
from smhai_backend.core.errors import BackendError
from smhai_backend.domains.workspace_agent_history import WorkspaceHistory


def run_worker(path, script):
    return subprocess.run(
        [sys.executable, "-c", script, str(path)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


async def test_backend_start_recovers_a_worker_that_exited_without_cleanup(tmp_path):
    path = tmp_path / "workspace.sqlite3"
    child = run_worker(
        path,
        """
import os
import sys
from smhai_backend.domains.workspace_agent_history import WorkspaceHistory

history = WorkspaceHistory(sys.argv[1])
with history.worker():
    completed, _ = history.acquire("completed-owner")
    history.append("completed-owner", completed, {"type": "end", "status": "completed"})
    run, _ = history.acquire("interrupted-owner")
    history.append("interrupted-owner", run, {"type": "user", "text": "Check a synthetic class"})
    os._exit(19)
""",
    )
    assert child.returncode == 19, child.stderr
    settings = BackendSettings(environment="test", workspace_agent_store=str(path))
    app = create_app(settings=settings)
    history = app.state.workspace_history
    _events, run, revision = history.read("interrupted-owner")
    assert run is not None
    completed, _, completed_revision = history.read("completed-owner")

    async with app.router.lifespan_context(app):
        assert app.state.lifecycle_started
        recovered, active, _ = history.read("interrupted-owner", revision)
        assert active is None
        interrupted = {"type": "end", "status": "interrupted", "run_id": run}
        assert recovered == [
            {"type": "user", "text": "Check a synthetic class", "run_id": run},
            interrupted,
        ]
        assert history.read("completed-owner") == (completed, None, completed_revision)
        assert history.allows_confirmation("completed-owner", completed[-1]["run_id"])
        assert not history.allows_confirmation("interrupted-owner", run)
        retry, prior = history.acquire("interrupted-owner", replaces=run)
        assert retry != run and prior == recovered
        with pytest.raises(BackendError, match="workflow_conflict"):
            history.append("interrupted-owner", run, {"type": "answer", "text": "stale"})
        history.append("interrupted-owner", retry, {"type": "end", "status": "completed"})

    with WorkspaceHistory(str(path)).worker():
        stored, active, _ = history.read("interrupted-owner")
        assert active is None
        assert stored.count(interrupted) == 1
        assert stored[-1] == {"type": "end", "status": "completed", "run_id": retry}


def test_second_process_cannot_recover_a_live_worker(tmp_path):
    path = tmp_path / "shared.sqlite3"
    history = WorkspaceHistory(str(path))
    with history.worker():
        run, _ = history.acquire("active-owner")
        child = run_worker(
            path,
            """
import sys
from smhai_backend.domains.workspace_agent_history import WorkspaceHistory

with WorkspaceHistory(sys.argv[1]).worker():
    raise AssertionError("Two processes may not own the same history")
""",
        )
        assert child.returncode != 0
        assert "workspace history already has a running worker" in child.stderr
        _events, active, _ = history.read("active-owner")
        assert active == run
        history.append("active-owner", run, {"type": "end", "status": "completed"})
