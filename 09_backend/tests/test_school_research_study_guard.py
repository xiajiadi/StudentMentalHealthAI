import importlib
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from smhai_backend.adapters.school_research import (
    SchoolResearchPersistenceAdapter,
)
from smhai_backend.core.errors import BackendError, ErrorCode

sys.path.insert(0, str(Path(__file__).resolve().parent))
persistence = importlib.import_module("test_school_research_persistence_adapter")


NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
IDEMPOTENCY = ("key-1", "a" * 64, "b" * 64)


def _adapter_with_policy(*, policy=None, claims=None, metadata=None):
    repo = persistence._Repo(metadata=metadata)
    owner = persistence._Owner(repo, claims=claims)
    adapter, client, factory_calls = persistence._adapter(owner)
    if policy is not None:
        adapter._study_use_policy = policy
    return adapter, owner, repo, client, factory_calls


def _assert_policy_denied(exc_info):
    assert exc_info.value.code is ErrorCode.FORBIDDEN
    assert "policy" in exc_info.value.detail
    for digest in ("a" * 64, "b" * 64, "c" * 64):
        assert digest not in exc_info.value.detail


@pytest.mark.asyncio
async def test_missing_policy_fails_closed_before_client_factory_or_profile_decrypt(
    monkeypatch,
):
    persistence._install_scope(monkeypatch)
    repo = persistence._Repo()
    owner = persistence._Owner(repo)
    factory_calls = []
    adapter = SchoolResearchPersistenceAdapter(
        owner,
        client_for_binding=lambda binding: factory_calls.append(binding),
    )
    with pytest.raises(BackendError) as exc_info:
        await adapter.prepare_start(
            persistence._actor(), "task-ref", at=NOW, idempotency=IDEMPOTENCY
        )

    assert exc_info.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE
    assert not factory_calls
    assert not repo.load_calls
    assert not repo.create_calls


@pytest.mark.asyncio
async def test_policy_receives_utc_times_and_start_replay_is_denied_before_replay_or_client(
    monkeypatch,
):
    persistence._install_scope(monkeypatch)
    policy = persistence._TrustedStudyPolicy(error_code="scope_denied")
    adapter, _owner, repo, _client, factory_calls = _adapter_with_policy(
        policy=policy, claims=[persistence._claim(replayed=True)]
    )
    naive_now = NOW.replace(tzinfo=None)

    with pytest.raises(BackendError) as exc_info:
        await adapter.prepare_start(
            persistence._actor(), "task-ref", at=naive_now, idempotency=IDEMPOTENCY
        )

    _assert_policy_denied(exc_info)
    assert policy.calls[0]["at"] == NOW
    assert not factory_calls
    assert not repo.load_calls and not repo.create_calls


@pytest.mark.asyncio
async def test_expired_policy_denies_answer_and_resume_before_snapshot_decrypt_or_client(
    monkeypatch,
):
    persistence._install_scope(monkeypatch)
    policy = persistence._TrustedStudyPolicy(error_code="scope_denied")
    adapter, _owner, repo, _client, factory_calls = _adapter_with_policy(policy=policy)

    with pytest.raises(BackendError) as answer_error:
        await adapter.prepare_answer(
            persistence._actor(),
            "session-ref",
            expected_state_version=1,
            at=NOW,
            idempotency=IDEMPOTENCY,
        )
    _assert_policy_denied(answer_error)
    assert not repo.load_calls and not factory_calls

    with pytest.raises(BackendError) as resume_error:
        await adapter.prepare_resume(persistence._actor(), "session-ref", at=NOW)
    _assert_policy_denied(resume_error)
    assert not repo.load_calls and not factory_calls


@pytest.mark.asyncio
async def test_commit_start_rechecks_policy_before_snapshot_conversion_or_write(monkeypatch):
    persistence._install_scope(monkeypatch)
    policy = persistence._TrustedStudyPolicy()
    adapter, _owner, repo, client, factory_calls = _adapter_with_policy(policy=policy)
    plan = await adapter.prepare_start(
        persistence._actor(), "task-ref", at=NOW, idempotency=IDEMPOTENCY
    )
    assert type(plan) is persistence.ResearchStartPlan

    adapter._study_use_policy = persistence._TrustedStudyPolicy(error_code="scope_denied")
    with pytest.raises(BackendError) as exc_info:
        await adapter.commit_start(
            persistence._actor(),
            plan,
            persistence._state(),
            at=NOW,
            trace_id="trace-safe",
            idempotency=IDEMPOTENCY,
        )

    _assert_policy_denied(exc_info)
    assert len(factory_calls) == 1  # Only prepare-start built a client.
    assert not client.calls
    assert not repo.create_calls


@pytest.mark.asyncio
async def test_commit_answer_rechecks_policy_before_new_snapshot_or_save(monkeypatch):
    persistence._install_scope(monkeypatch)
    adapter, _owner, repo, client, _factory_calls = _adapter_with_policy(
        policy=persistence._TrustedStudyPolicy()
    )
    plan = await adapter.prepare_answer(
        persistence._actor(),
        "session-ref",
        expected_state_version=1,
        at=NOW,
        idempotency=IDEMPOTENCY,
    )
    assert type(plan) is persistence.ResearchAnswerPlan
    assert repo.load_calls

    adapter._study_use_policy = persistence._TrustedStudyPolicy(error_code="scope_denied")
    with pytest.raises(BackendError) as exc_info:
        await adapter.commit_answer(
            persistence._actor(),
            plan,
            persistence._state(items_answered=1, status="COMPLETED"),
            at=NOW,
            idempotency=IDEMPOTENCY,
        )

    _assert_policy_denied(exc_info)
    assert not client.calls
    assert not repo.save_calls


@pytest.mark.asyncio
async def test_database_manifest_or_crosswalk_mismatch_denies_before_resume_decrypt(
    monkeypatch,
):
    persistence._install_scope(monkeypatch)
    adapter, _owner, repo, _client, factory_calls = _adapter_with_policy(
        policy=persistence._TrustedStudyPolicy()
    )
    repo.profile_metadata.published_parameter_crosswalk_sha256 = "d" * 64

    with pytest.raises(BackendError) as exc_info:
        await adapter.prepare_resume(persistence._actor(), "session-ref", at=NOW)

    assert exc_info.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert not repo.load_calls
    assert not factory_calls
