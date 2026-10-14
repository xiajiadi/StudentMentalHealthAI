from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smhai_backend.adapters.school_research import (
    ResearchAnswerPlan,
    ResearchSessionPersistenceResult,
    ResearchStartPlan,
    SchoolResearchPersistenceAdapter,
)
from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.domains.models import Actor, BackendRole, SchoolRoleContext
from smhai_backend.domains.school_research import authorization
from smhai_backend.domains.school_research.client import ResearchCATSnapshotForPersistence
from smhai_backend.domains.school_research.study_use import (
    ResearchStudyProfilePin,
    ResearchStudyUseError,
)

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
IDEMPOTENCY = ("key-1", "a" * 64, "b" * 64)


class _Query:
    def __init__(self, model=None):
        self.model = model

    def where(self, *_conditions):
        return self

    def limit(self, _count):
        return self


class _Column:
    def __eq__(self, _other):
        return self


class _SessionRow:
    school_id = _Column()
    task_id = _Column()
    task_enrollment_id = _Column()


class _RepositoryConcurrencyConflict(Exception):
    code = "RESEARCH_CONCURRENCY_CONFLICT"


class _MeasurementTask:
    id = _Column()
    school_id = _Column()
    task_ref = "task_ref_column"


class _Session:
    def __init__(self, existing=None):
        self.existing = existing
        self.queries = 0

    async def scalar(self, query):
        self.queries += 1
        if query.model == "task_ref_column":
            return "task-ref"
        return self.existing


class _Uow:
    def __init__(self, repo, *, existing=None, events):
        self.session = _Session(existing)
        self.research_cat = repo
        self._events = events

    async def __aenter__(self):
        self._events.append("enter")
        return self

    async def __aexit__(self, exc_type, _exc, _tb):
        self._events.append("rollback" if exc_type else "commit")
        return False


class _EducationJobs:
    def __init__(self, transaction_order):
        self.calls = []
        self.transaction_order = transaction_order
        self.failure = None

    async def enqueue_completed_session(self, **kwargs):
        self.calls.append(kwargs)
        self.transaction_order.append("enqueue")
        if self.failure is not None:
            raise self.failure


def _binding():
    return SimpleNamespace(
        binding_id=91,
        school_id=10,
        task_id=20,
        class_id=30,
        profile_version_id=40,
        profile_ref="profile-v1",
        profile_version_number=1,
        profile_sha256="c" * 64,
        response_origin="PUBLIC_OBSERVED",
        status="ACTIVE",
        config_version="config-v1",
        config_sha256="d" * 64,
        research_only=True,
        created_at=NOW,
        revoked_at=None,
    )


def _candidate(*, task_ref="task-ref", enrollment_id=50, account_id=60):
    return authorization.ResearchStudentScope(
        account_id=account_id,
        membership_role_id=70,
        school_id=10,
        school_ref="school-ref",
        task_id=20,
        task_ref=task_ref,
        class_id=30,
        class_ref="class-ref",
        task_enrollment_id=enrollment_id,
        task_enrollment_ref="enrollment-ref",
        subject_id=80,
        subject_ref="subject-ref",
    )


def _locked(candidate=None, binding=None):
    candidate = candidate or _candidate()
    return SimpleNamespace(
        school_id=candidate.school_id,
        task_id=candidate.task_id,
        class_id=candidate.class_id,
        task_enrollment_id=candidate.task_enrollment_id,
        subject_id=candidate.subject_id,
        principal_account_id=candidate.account_id,
        task_ref=candidate.task_ref,
        class_ref=candidate.class_ref,
        enrollment_ref=candidate.task_enrollment_ref,
        subject_ref=candidate.subject_ref,
        binding=SimpleNamespace(metadata=binding or _binding(), config_json="must-not-escape"),
    )


def _metadata(
    *, session_ref="session-ref", state_version=1, items_answered=0, status="IN_PROGRESS"
):
    binding = _binding()
    return SimpleNamespace(
        session_id=101,
        session_ref=session_ref,
        school_id=10,
        task_id=20,
        class_id=30,
        task_enrollment_id=50,
        subject_id=80,
        task_binding_id=binding.binding_id,
        profile_version_id=binding.profile_version_id,
        profile_ref=binding.profile_ref,
        profile_version_number=binding.profile_version_number,
        profile_sha256=binding.profile_sha256,
        response_origin=binding.response_origin,
        config_version=binding.config_version,
        config_sha256=binding.config_sha256,
        status=status,
        state_version=state_version,
        items_answered=items_answered,
        stop_reason="max_items_reached" if status == "COMPLETED" else None,
        started_at=NOW,
        completed_at=NOW if status == "COMPLETED" else None,
        created_at=NOW,
        updated_at=NOW,
    )


def _state(*, session_ref="session-ref", items_answered=0, status="ACTIVE"):
    return SimpleNamespace(
        binding_ref="private-binding-ref",
        session_ref=session_ref,
        profile_id="profile-v1",
        profile_sha256="c" * 64,
        config_sha256="d" * 64,
        config_version="config-v1",
        research_only=True,
        human_curated=False,
        publication_status="not_approved",
        psychological_interpretation_allowed=False,
        status=status,
        items_answered=items_answered,
        question=object() if status == "ACTIVE" else None,
        completion=object() if status == "COMPLETED" else None,
    )


class _Client:
    def __init__(self, *, bad_wrapper=False):
        self.calls = []
        self.bad_wrapper = bad_wrapper

    def snapshot_for_persistence(self, state):
        self.calls.append(state)
        if self.bad_wrapper:
            return {"payload": "not-a-trusted-wrapper"}
        return ResearchCATSnapshotForPersistence(
            b'{"payload":{"schema":"test"},"payload_sha256":"'
            + b"e" * 64
            + b'","signature":"'
            + b"f" * 64
            + b'"}'
        )


class _Repo:
    def __init__(self, *, metadata=None, loaded=None, saved=None, binding=None):
        self.metadata = metadata or _metadata()
        self.binding = binding or _binding()
        self.profile_metadata = SimpleNamespace(
            school_id=10,
            profile_ref=self.binding.profile_ref,
            profile_version_id=self.binding.profile_version_id,
            version_number=self.binding.profile_version_number,
            profile_sha256=self.binding.profile_sha256,
            manifest_sha256="a" * 64,
            parameter_origin="PUBLISHED_ROUNDED_REFERENCE",
            published_parameter_crosswalk_sha256="b" * 64,
            fit_sha256=None,
            calibration_sha256=None,
            rights_status="VERIFIED",
            execution_status="SIMULATION_ENABLED",
            rights_revoked_at=None,
            disabled_at=None,
            simulation_enabled_at=NOW,
            research_only=True,
            human_curated=False,
            psychological_interpretation_allowed=False,
            publication_status="not_approved_for_publication_or_operational_use",
        )
        self.loaded = loaded or SimpleNamespace(
            metadata=self.metadata,
            signed_snapshot_json='{"payload":{"answers":[]},"signature":"opaque"}',
        )
        self.saved = saved or SimpleNamespace(
            **{
                **vars(self.metadata),
                "state_version": self.metadata.state_version + 1,
                "items_answered": self.metadata.items_answered + 1,
                "status": "COMPLETED",
            }
        )
        self.guard_calls = []
        self.operations = []
        self.create_calls = []
        self.load_calls = []
        self.save_calls = []
        self.create_or_load_session = AsyncMock(side_effect=self._create)
        self.load_session_for_resume = AsyncMock(side_effect=self._load)
        self.get_session_l1_metadata = AsyncMock(side_effect=self._get)
        self.save_session_snapshot = AsyncMock(side_effect=self._save)

    async def lock_student_task_scope(self, **kwargs):
        self.guard_calls.append(kwargs)
        self.operations.append("scope-lock")
        kwargs["require_study_scope"](self.profile_metadata, self.binding)
        await kwargs["require_observed_scope"](self.profile_metadata, self.binding)
        return _locked(
            _candidate(
                task_ref="task-ref",
                enrollment_id=kwargs["task_enrollment_id"],
                account_id=kwargs["principal_account_id"],
            ),
            binding=self.binding,
        )

    async def require_public_observed_case_assignment(self, **kwargs):
        assert kwargs["binding"] is self.binding
        assert kwargs["profile"] is self.profile_metadata
        if kwargs["task_enrollment_id"] != 50 or kwargs["subject_id"] != 80:
            raise authorization.ResearchScopeResolutionError()
        assert kwargs["expected_profile_sha256"] == "c" * 64
        assert kwargs["expected_corpus_sha256"] == "1" * 64
        self.operations.append("observed-assignment-check")
        return SimpleNamespace(case_index=0)

    async def _create(self, **kwargs):
        self.create_calls.append(kwargs)
        return SimpleNamespace(metadata=self.metadata, signed_snapshot_json="private")

    async def _load(self, **kwargs):
        self.load_calls.append(kwargs)
        self.operations.append("snapshot-decrypt")
        return self.loaded

    async def _get(self, **kwargs):
        if kwargs["session_ref"] != self.metadata.session_ref:
            raise RuntimeError("no such fake session")
        return self.metadata

    async def _save(self, **kwargs):
        self.save_calls.append(kwargs)
        return self.saved


class _Owner:
    def __init__(self, repo, *, claims=None, existing_rows=None):
        self.repo = repo
        self.claims = list(claims or [])
        self.existing_rows = list(existing_rows or [])
        self.events = []
        self.completed = []
        self.role_calls = []
        self.factory_events = []
        self.transaction_order = []
        self.research_education_jobs = _EducationJobs(self.transaction_order)
        self._db_models = SimpleNamespace(
            SchoolResearchSession=_SessionRow,
            MeasurementTask=_MeasurementTask,
        )
        self._db_enums = object()
        self._select = lambda model: _Query(model)

    def _uow(self):
        existing = self.existing_rows.pop(0) if self.existing_rows else None
        uow = _Uow(self.repo, existing=existing, events=self.events)
        uow.research_education_jobs = self.research_education_jobs
        return uow

    async def _school_idempotency_begin(self, _uow, _idempotency):
        self.repo.operations.append("idempotency-begin")
        if self.claims:
            return self.claims.pop(0)
        return _claim()

    async def _school_idempotency_complete(self, _uow, claim, *, resource_type, result_ref):
        self.completed.append((claim, resource_type, result_ref))
        self.transaction_order.append("idempotency_complete")

    async def _school_actor_role(self, _uow, actor, role_code, at, *, lock=False):
        self.role_calls.append((actor, role_code, at, lock))
        return (60, 70)


class _TrustedStudyPolicy:
    source_rights_verified = True

    def __init__(self, *, error_code=None):
        self.error_code = error_code
        self.calls = []

    def require_scope(self, **kwargs):
        self.calls.append(kwargs)
        if self.error_code:
            raise ResearchStudyUseError(self.error_code)
        return ResearchStudyProfilePin(
            profile_ref="profile-v1",
            profile_sha256="c" * 64,
            manifest_sha256="a" * 64,
            published_crosswalk_sha256="b" * 64,
        )


def _claim(*, replayed=False, result_ref="session-ref", resource_type="research_session"):
    return SimpleNamespace(
        record=SimpleNamespace(
            state="COMPLETED" if replayed else "IN_PROGRESS",
            result_resource_type=resource_type if replayed else None,
            result_public_id=result_ref if replayed else None,
        ),
        replayed=replayed,
    )


def _install_scope(monkeypatch, candidate=None):
    candidate = candidate or _candidate()

    async def resolve(**kwargs):
        await kwargs["resolve_student_role"](kwargs["actor"], kwargs["at"])
        return candidate

    monkeypatch.setattr(
        "smhai_backend.adapters.school_research.resolve_research_student_scope",
        resolve,
    )


def _adapter(owner, client=None):
    client = client or _Client()
    factory_calls = []
    owner.factory_events.clear()

    def factory(binding):
        factory_calls.append(binding)
        owner.factory_events.append(tuple(owner.events))
        return client

    return (
        SchoolResearchPersistenceAdapter(
            owner,
            client_for_binding=factory,
            study_use_policy=_TrustedStudyPolicy(),
            observed_corpus_for_binding=lambda binding: SimpleNamespace(
                profile_sha256="c" * 64,
                response_csv_sha256="1" * 64,
                matches=lambda index, item, value: index == 0 and item == "item-1" and value == 1,
            ),
        ),
        client,
        factory_calls,
    )


def _actor():
    return Actor(
        user_id="USER_SYNTHETIC",
        username="student",
        role=BackendRole.STUDENT,
        subject_id=None,
        scope_profile="school_tenant",
        school_id=10,
        school_ref="school-ref",
        school_contexts=(
            SchoolRoleContext(
                context_id="role-ref",
                role=BackendRole.STUDENT,
                school_id=10,
                school_ref="school-ref",
            ),
        ),
    )


@pytest.mark.asyncio
async def test_prepare_start_rolls_back_tentative_receipt_and_returns_private_plan(monkeypatch):
    _install_scope(monkeypatch)
    repo = _Repo()
    owner = _Owner(repo)
    adapter, _client, _factory_calls = _adapter(owner)

    result = await adapter.prepare_start(_actor(), "task-ref", at=NOW, idempotency=IDEMPOTENCY)

    assert type(result) is ResearchStartPlan
    assert owner.events == ["enter", "rollback"]
    assert repo.operations == ["scope-lock", "observed-assignment-check", "idempotency-begin"]
    assert owner.role_calls[0][1:] == ("student", owner.role_calls[0][2], True)
    assert [
        {
            key: value
            for key, value in call.items()
            if key not in {"require_study_scope", "require_observed_scope"}
        }
        for call in repo.guard_calls
    ] == [
        {
            "school_id": 10,
            "task_id": 20,
            "task_enrollment_id": 50,
            "subject_id": 80,
            "principal_account_id": 60,
            "at": NOW,
        }
    ]
    assert callable(repo.guard_calls[0]["require_study_scope"])
    assert callable(repo.guard_calls[0]["require_observed_scope"])
    assert "must-not-escape" not in repr(result)
    assert owner.factory_events == [("enter", "rollback")]


@pytest.mark.asyncio
async def test_prepare_start_replay_reauthorizes_and_returns_metadata_without_client(monkeypatch):
    _install_scope(monkeypatch)
    repo = _Repo()
    owner = _Owner(repo, claims=[_claim(replayed=True)])
    adapter, _client, factory_calls = _adapter(owner)

    result = await adapter.prepare_start(_actor(), "task-ref", at=NOW, idempotency=IDEMPOTENCY)

    assert isinstance(result, ResearchSessionPersistenceResult)
    assert result.persisted and result.replayed and not result.state_accepted
    assert result.metadata.session_ref == "session-ref"
    assert result.metadata.task_ref == "task-ref"
    assert not factory_calls
    assert not owner.factory_events
    assert not repo.load_calls
    assert owner.events == ["enter", "commit"]


@pytest.mark.asyncio
async def test_commit_start_persists_authenticated_state_and_completes_same_receipt(monkeypatch):
    _install_scope(monkeypatch)
    repo = _Repo(metadata=_metadata())
    owner = _Owner(repo)
    adapter, client, factory_calls = _adapter(owner)
    plan = await adapter.prepare_start(_actor(), "task-ref", at=NOW, idempotency=IDEMPOTENCY)
    assert type(plan) is ResearchStartPlan

    result = await adapter.commit_start(
        _actor(), plan, _state(), at=NOW, trace_id="trace-1", idempotency=IDEMPOTENCY
    )

    assert result.persisted and not result.replayed and result.state_accepted
    assert repo.create_or_load_session.await_count == 1
    assert repo.create_calls[0]["signed_snapshot"]["signature"] == "f" * 64
    assert repo.create_calls[0]["session_ref"] == "session-ref"
    assert client.calls and factory_calls[0].profile_sha256 == "c" * 64
    assert owner.completed[0][1:] == ("research_session", "session-ref")
    assert owner.events == ["enter", "rollback", "enter", "commit"]


@pytest.mark.asyncio
async def test_concurrent_start_winner_returns_stored_metadata_not_discarded_state(monkeypatch):
    _install_scope(monkeypatch)
    repo = _Repo(metadata=_metadata(session_ref="winner-session"))
    owner = _Owner(repo)
    adapter, client, _factory_calls = _adapter(owner)
    plan = await adapter.prepare_start(_actor(), "task-ref", at=NOW, idempotency=IDEMPOTENCY)
    assert type(plan) is ResearchStartPlan
    owner.existing_rows.append(SimpleNamespace(session_ref="winner-session"))

    result = await adapter.commit_start(
        _actor(),
        plan,
        _state(session_ref="discarded-session"),
        at=NOW,
        trace_id="trace-1",
        idempotency=IDEMPOTENCY,
    )

    assert result.metadata.session_ref == "winner-session"
    assert result.persisted and not result.replayed and not result.state_accepted
    assert not client.calls
    assert not repo.create_calls
    assert owner.completed[0][2] == "winner-session"


@pytest.mark.asyncio
async def test_prepare_answer_loads_only_after_scope_guard_and_checks_cas_version(monkeypatch):
    _install_scope(monkeypatch)
    repo = _Repo(metadata=_metadata(state_version=4, items_answered=3))
    owner = _Owner(repo)
    adapter, _client, _factory_calls = _adapter(owner)

    plan = await adapter.prepare_answer(
        _actor(),
        "session-ref",
        expected_state_version=4,
        item_id="item-1",
        raw_value=1,
        at=NOW,
        idempotency=IDEMPOTENCY,
    )
    assert type(plan) is ResearchAnswerPlan

    assert type(plan) is ResearchAnswerPlan
    assert plan.expected_state_version == 4 and plan.items_answered == 3
    assert repo.guard_calls and repo.load_calls
    assert owner.events == ["enter", "rollback"]
    assert owner.factory_events == [("enter", "rollback")]
    assert "opaque" not in repr(plan)


@pytest.mark.asyncio
async def test_completed_answer_replay_returns_l1_without_decrypt_or_resume(monkeypatch):
    _install_scope(monkeypatch)
    repo = _Repo(metadata=_metadata(state_version=5, items_answered=4, status="COMPLETED"))
    owner = _Owner(repo, claims=[_claim(replayed=True)])
    adapter, _client, factory_calls = _adapter(owner)

    result = await adapter.prepare_answer(
        _actor(),
        "session-ref",
        expected_state_version=5,
        item_id="item-1",
        raw_value=1,
        at=NOW,
        idempotency=IDEMPOTENCY,
    )

    assert isinstance(result, ResearchSessionPersistenceResult)
    assert result.replayed and result.persisted and not result.state_accepted
    assert result.metadata.status == "COMPLETED"
    assert not repo.load_calls
    assert not factory_calls


@pytest.mark.asyncio
async def test_commit_answer_uses_expected_state_version_cas_and_one_receipt(monkeypatch):
    _install_scope(monkeypatch)
    repo = _Repo(metadata=_metadata(state_version=4, items_answered=3))
    owner = _Owner(repo)
    adapter, client, _factory_calls = _adapter(owner)
    plan = await adapter.prepare_answer(
        _actor(),
        "session-ref",
        expected_state_version=4,
        item_id="item-1",
        raw_value=1,
        at=NOW,
        idempotency=IDEMPOTENCY,
    )
    assert type(plan) is ResearchAnswerPlan
    updated = _state(items_answered=4, status="COMPLETED")

    result = await adapter.commit_answer(_actor(), plan, updated, at=NOW, idempotency=IDEMPOTENCY)

    assert result.persisted and result.state_accepted and not result.replayed
    assert repo.save_calls[0]["expected_state_version"] == 4
    assert repo.save_calls[0]["signed_snapshot"]["signature"] == "f" * 64
    assert owner.research_education_jobs.calls == [
        {
            "school_id": 10,
            "research_session_id": 101,
            "task_id": 20,
            "class_id": 30,
            "task_enrollment_id": 50,
            "subject_id": 80,
            "task_binding_id": 91,
            "profile_version_id": 40,
            "profile_ref": "profile-v1",
            "profile_version_number": 1,
            "profile_sha256": "c" * 64,
            "response_origin": "PUBLIC_OBSERVED",
            "policy_version": "NO_RESEARCH_PERSONALIZED_POLICY_V1",
            "policy_hash": None,
            "now": NOW,
        }
    ]
    assert owner.transaction_order == ["enqueue", "idempotency_complete"]
    assert owner.completed[0][1:] == ("research_session", "session-ref")
    assert client.calls == [updated]


@pytest.mark.asyncio
async def test_commit_answer_intermediate_snapshot_does_not_enqueue_education_job(monkeypatch):
    _install_scope(monkeypatch)
    repo = _Repo(metadata=_metadata(state_version=4, items_answered=3))
    repo.saved = _metadata(state_version=5, items_answered=4, status="IN_PROGRESS")
    owner = _Owner(repo)
    adapter, _client, _factory_calls = _adapter(owner)
    plan = await adapter.prepare_answer(
        _actor(),
        "session-ref",
        expected_state_version=4,
        item_id="item-1",
        raw_value=1,
        at=NOW,
        idempotency=IDEMPOTENCY,
    )

    result = await adapter.commit_answer(
        _actor(), plan, _state(items_answered=4, status="ACTIVE"), at=NOW, idempotency=IDEMPOTENCY
    )

    assert result.metadata.status == "IN_PROGRESS"
    assert not owner.research_education_jobs.calls
    assert owner.transaction_order == ["idempotency_complete"]


@pytest.mark.asyncio
async def test_commit_answer_outbox_failure_rolls_back_completed_snapshot(monkeypatch):
    _install_scope(monkeypatch)
    repo = _Repo(metadata=_metadata(state_version=4, items_answered=3))
    owner = _Owner(repo)
    owner.research_education_jobs.failure = RuntimeError("private outbox detail")
    adapter, _client, _factory_calls = _adapter(owner)
    plan = await adapter.prepare_answer(
        _actor(),
        "session-ref",
        expected_state_version=4,
        item_id="item-1",
        raw_value=1,
        at=NOW,
        idempotency=IDEMPOTENCY,
    )

    with pytest.raises(BackendError) as exc_info:
        await adapter.commit_answer(
            _actor(),
            plan,
            _state(items_answered=4, status="COMPLETED"),
            at=NOW,
            idempotency=IDEMPOTENCY,
        )

    assert exc_info.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE
    assert "private outbox detail" not in exc_info.value.detail
    assert len(owner.research_education_jobs.calls) == 1
    assert not owner.completed
    assert owner.events[-1] == "rollback"
    assert owner.transaction_order == ["enqueue"]


@pytest.mark.asyncio
async def test_commit_answer_missing_outbox_fails_closed_and_rolls_back(monkeypatch):
    _install_scope(monkeypatch)
    repo = _Repo(metadata=_metadata(state_version=4, items_answered=3))
    owner = _Owner(repo)
    owner.research_education_jobs = None
    adapter, _client, _factory_calls = _adapter(owner)
    plan = await adapter.prepare_answer(
        _actor(),
        "session-ref",
        expected_state_version=4,
        item_id="item-1",
        raw_value=1,
        at=NOW,
        idempotency=IDEMPOTENCY,
    )

    with pytest.raises(BackendError) as exc_info:
        await adapter.commit_answer(
            _actor(),
            plan,
            _state(items_answered=4, status="COMPLETED"),
            at=NOW,
            idempotency=IDEMPOTENCY,
        )

    assert exc_info.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE
    assert not owner.completed
    assert owner.events[-1] == "rollback"


@pytest.mark.asyncio
async def test_commit_answer_race_replay_reauthorizes_but_does_not_verify_or_save_state(
    monkeypatch,
):
    _install_scope(monkeypatch)
    repo = _Repo(metadata=_metadata(state_version=4, items_answered=3))
    owner = _Owner(repo, claims=[_claim(), _claim(replayed=True)])
    adapter, client, _factory_calls = _adapter(owner)
    plan = await adapter.prepare_answer(
        _actor(),
        "session-ref",
        expected_state_version=4,
        item_id="item-1",
        raw_value=1,
        at=NOW,
        idempotency=IDEMPOTENCY,
    )
    assert type(plan) is ResearchAnswerPlan
    repo.metadata = _metadata(state_version=5, items_answered=4)

    result = await adapter.commit_answer(
        _actor(), plan, _state(items_answered=4), at=NOW, idempotency=IDEMPOTENCY
    )

    assert result.persisted and result.replayed and not result.state_accepted
    assert result.metadata.state_version == 5
    assert not client.calls
    assert not repo.save_calls
    assert not owner.research_education_jobs.calls
    assert repo.guard_calls


@pytest.mark.asyncio
async def test_repository_cas_failure_rolls_back_receipt_and_maps_stable_conflict(monkeypatch):
    _install_scope(monkeypatch)
    repo = _Repo(metadata=_metadata(state_version=4, items_answered=3))
    owner = _Owner(repo)
    adapter, _client, _factory_calls = _adapter(owner)
    plan = await adapter.prepare_answer(
        _actor(),
        "session-ref",
        expected_state_version=4,
        item_id="item-1",
        raw_value=1,
        at=NOW,
        idempotency=IDEMPOTENCY,
    )
    assert type(plan) is ResearchAnswerPlan
    repo.save_session_snapshot.side_effect = _RepositoryConcurrencyConflict(
        "hidden database details"
    )

    with pytest.raises(BackendError) as exc_info:
        await adapter.commit_answer(
            _actor(), plan, _state(items_answered=4), at=NOW, idempotency=IDEMPOTENCY
        )

    assert exc_info.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert "hidden database details" not in exc_info.value.detail
    assert not owner.completed
    assert owner.events[-1] == "rollback"


@pytest.mark.asyncio
async def test_prepare_answer_rejects_stale_expected_state_version_before_decrypt(monkeypatch):
    _install_scope(monkeypatch)
    repo = _Repo(metadata=_metadata(state_version=4, items_answered=3))
    owner = _Owner(repo)
    adapter, _client, _factory_calls = _adapter(owner)

    with pytest.raises(BackendError) as exc_info:
        await adapter.prepare_answer(
            _actor(),
            "session-ref",
            expected_state_version=3,
            item_id="item-1",
            raw_value=1,
            at=NOW,
            idempotency=IDEMPOTENCY,
        )

    assert exc_info.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert not repo.load_calls
    assert owner.events == ["enter", "rollback"]


@pytest.mark.asyncio
async def test_self_revocation_fails_closed_before_session_decryption(monkeypatch):
    async def revoked(**_kwargs):
        raise authorization.ResearchScopeResolutionError("research_scope_unavailable")

    monkeypatch.setattr(
        "smhai_backend.adapters.school_research.resolve_research_student_scope", revoked
    )
    repo = _Repo(metadata=_metadata())
    owner = _Owner(repo)
    adapter, _client, _factory_calls = _adapter(owner)

    with pytest.raises(BackendError) as exc_info:
        await adapter.prepare_answer(
            _actor(),
            "session-ref",
            expected_state_version=1,
            item_id="item-1",
            raw_value=1,
            at=NOW,
            idempotency=IDEMPOTENCY,
        )

    assert exc_info.value.code is ErrorCode.RESOURCE_NOT_FOUND
    assert not repo.guard_calls
    assert not repo.load_calls
    assert owner.events == ["enter", "rollback"]


@pytest.mark.asyncio
async def test_wrong_snapshot_wrapper_rolls_back_without_receipt_or_repository_write(
    monkeypatch,
):
    _install_scope(monkeypatch)
    repo = _Repo()
    owner = _Owner(repo)
    adapter, client, _factory_calls = _adapter(owner, _Client(bad_wrapper=True))
    plan = await adapter.prepare_start(_actor(), "task-ref", at=NOW, idempotency=IDEMPOTENCY)
    assert type(plan) is ResearchStartPlan

    with pytest.raises(BackendError) as exc_info:
        await adapter.commit_start(
            _actor(), plan, _state(), at=NOW, trace_id="trace-1", idempotency=IDEMPOTENCY
        )

    assert exc_info.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE
    assert not repo.create_calls
    assert not owner.completed
    assert client.calls
    assert owner.events[-1] == "rollback"


@pytest.mark.asyncio
async def test_scope_change_between_prepare_and_commit_rejects_candidate_state(monkeypatch):
    _install_scope(monkeypatch)
    repo = _Repo()
    owner = _Owner(repo)
    adapter, client, _factory_calls = _adapter(owner)
    plan = await adapter.prepare_start(_actor(), "task-ref", at=NOW, idempotency=IDEMPOTENCY)
    assert type(plan) is ResearchStartPlan

    changed = _candidate(enrollment_id=51)
    _install_scope(monkeypatch, changed)
    with pytest.raises(BackendError) as exc_info:
        await adapter.commit_start(
            _actor(), plan, _state(), at=NOW, trace_id="trace-1", idempotency=IDEMPOTENCY
        )

    assert exc_info.value.code is ErrorCode.RESOURCE_NOT_FOUND
    assert not client.calls
    assert not repo.create_calls
    assert owner.events[-1] == "rollback"


@pytest.mark.asyncio
async def test_binding_pin_change_between_prepare_and_commit_rejects_old_client(monkeypatch):
    _install_scope(monkeypatch)
    repo = _Repo()
    owner = _Owner(repo)
    adapter, client, _factory_calls = _adapter(owner)
    plan = await adapter.prepare_start(_actor(), "task-ref", at=NOW, idempotency=IDEMPOTENCY)
    assert type(plan) is ResearchStartPlan
    repo.binding = SimpleNamespace(
        **{
            **vars(_binding()),
            "config_version": "config-v2",
            "config_sha256": "e" * 64,
        }
    )

    with pytest.raises(BackendError) as exc_info:
        await adapter.commit_start(
            _actor(), plan, _state(), at=NOW, trace_id="trace-1", idempotency=IDEMPOTENCY
        )

    assert exc_info.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert not client.calls
    assert not repo.create_calls
    assert owner.events[-1] == "rollback"


@pytest.mark.asyncio
async def test_client_factory_failure_is_private_and_leaves_no_claim(monkeypatch):
    _install_scope(monkeypatch)
    repo = _Repo()
    owner = _Owner(repo)

    def fail_factory(_binding):
        raise RuntimeError("untrusted-credential-detail")

    adapter = SchoolResearchPersistenceAdapter(
        owner,
        client_for_binding=fail_factory,
        study_use_policy=_TrustedStudyPolicy(),
    )
    with pytest.raises(BackendError) as exc_info:
        await adapter.prepare_start(_actor(), "task-ref", at=NOW, idempotency=IDEMPOTENCY)

    assert exc_info.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE
    assert "untrusted-credential-detail" not in exc_info.value.detail
    assert owner.events == ["enter", "rollback"]


@pytest.mark.asyncio
async def test_prepare_resume_rechecks_scope_before_decrypt_and_builds_client_after_uow(
    monkeypatch,
):
    _install_scope(monkeypatch)
    repo = _Repo(metadata=_metadata(state_version=4, items_answered=3))
    owner = _Owner(repo)
    adapter, _client, _factory_calls = _adapter(owner)

    plan = await adapter.prepare_resume(_actor(), "session-ref", at=NOW)

    assert plan.session_ref == "session-ref"
    assert plan.state_version == 4
    assert plan.items_answered == 3
    assert repo.operations == ["scope-lock", "observed-assignment-check", "snapshot-decrypt"]
    assert owner.events == ["enter", "commit"]
    assert owner.factory_events == [("enter", "commit")]
    assert not owner.completed


@pytest.mark.asyncio
async def test_prepare_resume_rejects_terminal_session_without_decrypt_or_client(monkeypatch):
    _install_scope(monkeypatch)
    repo = _Repo(metadata=_metadata(status="COMPLETED"))
    owner = _Owner(repo)
    adapter, _client, _factory_calls = _adapter(owner)

    with pytest.raises(BackendError) as exc_info:
        await adapter.prepare_resume(_actor(), "session-ref", at=NOW)

    assert exc_info.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert repo.guard_calls
    assert not repo.load_calls
    assert not owner.factory_events
    assert owner.events == ["enter", "rollback"]


@pytest.mark.asyncio
async def test_observed_mismatch_denies_before_decrypt_or_client(monkeypatch):
    _install_scope(monkeypatch)
    repo = _Repo()
    owner = _Owner(repo)
    adapter, _client, factory_calls = _adapter(owner)
    with pytest.raises(BackendError) as failure:
        await adapter.prepare_answer(
            _actor(),
            "session-ref",
            expected_state_version=1,
            item_id="item-1",
            raw_value=5,
            at=NOW,
            idempotency=IDEMPOTENCY,
        )
    assert failure.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert not repo.load_calls and not factory_calls
    assert not repo.save_calls and not owner.completed
    assert owner.events == ["enter", "rollback"]


@pytest.mark.asyncio
async def test_unconfigured_observed_guard_denies_before_any_decrypt(monkeypatch):
    _install_scope(monkeypatch)
    repo = _Repo()
    owner = _Owner(repo)
    client = _Client()
    adapter = SchoolResearchPersistenceAdapter(
        owner,
        client_for_binding=lambda binding: client,
        study_use_policy=_TrustedStudyPolicy(),
    )
    with pytest.raises(BackendError) as failure:
        await adapter.prepare_start(_actor(), "task-ref", at=NOW, idempotency=IDEMPOTENCY)
    assert failure.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE
    assert not repo.load_calls and not repo.create_calls and not repo.save_calls
    assert "observed-assignment-check" not in repo.operations
    assert not client.calls


@pytest.mark.asyncio
async def test_cohort_guard_forwards_current_trusted_study_before_loading_state(monkeypatch):
    _install_scope(monkeypatch)
    repo = _Repo()
    repo.binding.cohort_id = 701
    owner = _Owner(repo)
    adapter, _client, factory_calls = _adapter(owner)
    adapter._study_use_policy.study_ref = "STUDY_current_replay"
    original = repo.require_public_observed_case_assignment

    async def require_study(**kwargs):
        assert kwargs["expected_study_ref"] == "STUDY_current_replay"
        assert not repo.load_calls and not factory_calls
        return await original(**kwargs)

    repo.require_public_observed_case_assignment = require_study
    await adapter.prepare_answer(
        _actor(), "session-ref", expected_state_version=1,
        item_id="item-1", raw_value=1, at=NOW, idempotency=IDEMPOTENCY,
    )
    assert len(repo.load_calls) == 1
    assert len(factory_calls) == 1


@pytest.mark.asyncio
async def test_cohort_without_current_study_identifier_never_decrypts_or_builds_client(monkeypatch):
    _install_scope(monkeypatch)
    repo = _Repo()
    repo.binding.cohort_id = 701
    owner = _Owner(repo)
    adapter, _client, factory_calls = _adapter(owner)
    with pytest.raises(BackendError) as caught:
        await adapter.prepare_answer(
            _actor(), "session-ref", expected_state_version=1,
            item_id="item-1", raw_value=1, at=NOW, idempotency=IDEMPOTENCY,
        )
    assert caught.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE
    assert not repo.load_calls and not factory_calls
    assert "observed-assignment-check" not in repo.operations
    assert owner.events == ["enter", "rollback"]
