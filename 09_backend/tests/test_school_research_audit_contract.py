"""Bridge research audit metadata to the real shared audit repository."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_DATABASE_ROOT = _REPOSITORY_ROOT / "11_database"
for _database_path in (
    _DATABASE_ROOT / ".venv" / "Lib" / "site-packages",
    _DATABASE_ROOT,
):
    if _database_path.is_dir() and str(_database_path) not in sys.path:
        sys.path.insert(0, str(_database_path))

from database_layer.enums import AuditResult  # noqa: E402
from database_layer.models import AuditEvent  # noqa: E402
from database_layer.repositories import _SAFE_AUDIT_KEYS, AuditRepository  # noqa: E402

from smhai_backend.adapters.school_research_profiles import (  # noqa: E402
    _simulation_audit_metadata,
)
from smhai_backend.adapters.school_research_tasks import _audit as audit_research_task  # noqa: E402

POLICY_SHA = "a" * 64


class _NoDatabaseRecordingSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flush_count = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flush_count += 1


@pytest.mark.asyncio
async def test_profile_and_task_adapter_metadata_pass_through_real_audit_repository() -> None:
    session = _NoDatabaseRecordingSession()
    audit = AuditRepository(session)  # exercise the production whitelist and append path

    await audit.append(
        action="school_research_profiles.enable_simulation",
        resource_type="school_research_profile_version",
        resource_public_id="promis-pediatric-anxiety-8-item-subset-20261014-r1",
        result=AuditResult.SUCCESS,
        trace_id="TRACE_synthetic_audit_bridge_profile",
        actor_account_id=11,
        safe_metadata=_simulation_audit_metadata(POLICY_SHA),
    )
    await audit_research_task(
        SimpleNamespace(audit=audit),
        actor_account_id=11,
        task_ref="TASK_synthetic_replay_audit_bridge",
        trace_id="TRACE_synthetic_audit_bridge_task",
        action="school_research_tasks.task.published",
        success_result=AuditResult.SUCCESS,
        study_use_policy_sha256=POLICY_SHA,
    )

    assert len(session.added) == 2
    profile_event, task_event = session.added
    assert isinstance(profile_event, AuditEvent)
    assert isinstance(task_event, AuditEvent)
    assert profile_event.safe_metadata == {
        "schema_version": "psynova.research-study-use.v1",
        "component_version": POLICY_SHA,
        "reason_code": "ISOLATED_HISTORICAL_REPLAY",
        "source": "school_research_profiles",
        "state": "SIMULATION_ENABLED",
    }
    assert task_event.safe_metadata == {
        "schema_version": "psynova.research-study-use.v1",
        "component_version": POLICY_SHA,
        "reason_code": "ISOLATED_HISTORICAL_REPLAY",
        "source": "school_research_tasks",
        "state": "PUBLISHED",
    }
    assert all(set(event.safe_metadata) <= _SAFE_AUDIT_KEYS for event in session.added)
    assert session.flush_count == 2
