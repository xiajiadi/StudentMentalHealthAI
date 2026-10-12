from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "11_database"))
sys.path.insert(0, str(REPO / "09_backend" / "src"))
database_site_packages = REPO / "11_database" / ".venv" / "Lib" / "site-packages"
if database_site_packages.is_dir():
    sys.path.append(str(database_site_packages))
import school_cat_start_revocation_qa as qa
from database_layer.models import SchoolClassStudent, SubjectAccessGrant
from smhai_backend.adapters.database import MySqlBackendAdapter
from smhai_backend.adapters.school_cat_assets import SchoolCatAssetsPersistenceAdapter


def test_safe_output_contains_only_fixed_stages_and_allowlisted_error_class():
    result = qa._safe_result(
        status="PASS",
        stage="complete",
        checks={**dict.fromkeys(qa.STAGES, "PASS"), "assessment_id": "private"},
        error_class="private exception detail",
    )

    assert result["status"] == "PASS"
    assert set(result["checks"]) == set(qa.STAGES)
    assert result["error_class"] == "OtherError"
    assert "private" not in repr(result)


def test_safe_output_never_marks_partial_checks_as_pass():
    result = qa._safe_result(
        status="PASS", stage="complete", checks={qa.STAGES[0]: "PASS"}
    )

    assert result["status"] == "FAIL"
    assert all(
        value == "FAIL"
        for key, value in result["checks"].items()
        if key != qa.STAGES[0]
    )


@pytest.mark.asyncio
async def test_start_lock_serializes_revoke_after_start_and_releases_both_operations():
    lock_acquired, release_lock, revoke_entered = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )
    order: list[str] = []

    async def start():
        lock_acquired.set()
        await release_lock.wait()
        order.append("start_committed")
        return {"assessment": "synthetic"}

    async def revoke():
        revoke_entered.set()
        await release_lock.wait()
        order.append("revoke_committed")
        return {"status": "REVOKED"}

    start_result, revoke_result = await qa._run_start_then_revoke(
        start,
        revoke,
        lock_acquired=lock_acquired,
        release_lock=release_lock,
        revoke_entered=revoke_entered,
        blocked_window_seconds=0.02,
    )

    assert start_result == {"assessment": "synthetic"}
    assert revoke_result == {"status": "REVOKED"}
    assert order == ["start_committed", "revoke_committed"]
    assert release_lock.is_set()


@pytest.mark.asyncio
async def test_early_revoke_completion_fails_and_still_releases_cancelled_start():
    lock_acquired, release_lock, revoke_entered = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )
    start_cancelled = asyncio.Event()

    async def start():
        lock_acquired.set()
        try:
            await release_lock.wait()
        except asyncio.CancelledError:
            start_cancelled.set()
            raise

    async def revoke():
        revoke_entered.set()

    with pytest.raises(qa.QaFailure):
        await qa._run_start_then_revoke(
            start,
            revoke,
            lock_acquired=lock_acquired,
            release_lock=release_lock,
            revoke_entered=revoke_entered,
            blocked_window_seconds=0.1,
        )

    assert release_lock.is_set()
    assert start_cancelled.is_set()


def test_session_reference_projection_requires_exact_assessment_ref():
    snapshot = {
        "assessment_sessions": (
            ("id", "assessment_ref"),
            ((17, "ASSESS_SYNTHETIC_QA"),),
        )
    }

    assert qa._session_id_from_snapshot(snapshot, "ASSESS_SYNTHETIC_QA") == 17
    assert qa._session_id_from_snapshot(snapshot, "ASSESS_OTHER") is None


def test_real_backend_adapter_and_current_roster_linkage_columns_import():
    assert hasattr(SchoolClassStudent, "subject_id")
    assert not hasattr(SchoolClassStudent, "student_account_id")
    assert hasattr(SubjectAccessGrant, "principal_account_id")
    source = __import__("inspect").getsource(
        MySqlBackendAdapter.school_prepare_task_session
    )
    assert "m.SubjectAccessGrant" in source
    assert "principal_account_id" in source


def test_activation_list_uses_real_admin_http_endpoint_and_not_mysql_adapter_method():
    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "data": {
                    "engineering_only": True,
                    "psychological_interpretation_allowed": False,
                    "items": [
                        {"activation_ref": f"CACT_{'a' * 36}", "status": "ACTIVE"}
                    ],
                }
            }

    class Client:
        def __init__(self):
            self.request = None

        def get(self, path, *, params):
            self.request = (path, params)
            return Response()

    client = Client()
    assert qa._eligible_activation_ref_from_client(client) == f"CACT_{'a' * 36}"
    assert client.request == (
        "/api/v1/school/cat-assets/activations",
        {"limit": 100, "skip": 0},
    )
    assert hasattr(
        SchoolCatAssetsPersistenceAdapter, "school_cat_assets_list_activations"
    )
    assert not hasattr(MySqlBackendAdapter, "school_cat_assets_list_activations")
    native_source = __import__("inspect").getsource(qa._run_native)
    assert "_eligible_activation_ref_from_client(admin_client)" in native_source
    assert "persistence.school_cat_assets_list_activations" not in native_source


@pytest.mark.asyncio
async def test_guard_wrapper_pauses_only_after_original_scope_lock_returns_and_restores():
    class Adapter:
        async def _lock_school_assessment_write_scope(
            self, _uow, _actor, _account, enrollment, *, at
        ):
            return enrollment, "task", at

    adapter = Adapter()
    acquired, release = asyncio.Event(), asyncio.Event()
    restore = qa._guard_instance_after_lock(
        adapter, acquired=acquired, release=release, timeout=1
    )
    operation = asyncio.create_task(
        adapter._lock_school_assessment_write_scope(
            "uow", "actor", 1, "enrollment", at="now"
        )
    )
    await asyncio.wait_for(acquired.wait(), timeout=1)
    assert not operation.done()
    release.set()
    assert await operation == ("enrollment", "task", "now")
    restore()
    assert await adapter._lock_school_assessment_write_scope(
        "uow", "actor", 1, "enrollment", at="now"
    ) == ("enrollment", "task", "now")
