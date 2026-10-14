from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from smhai_backend.adapters.school_research_education import (
    SchoolResearchEducationLiveAuthorization,
)
from smhai_backend.domains.school_research.study_use import (
    ResearchStudyProfilePin,
    ResearchStudyUsePolicy,
)
from smhai_backend.domains.school_research_education.service import (
    RESEARCH_EDUCATION_POLICY_VERSION,
    ResearchEducationAuthorizationUnavailable,
    ResearchEducationWorker,
    ResearchEducationWorkerResult,
)

NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
PROFILE_SHA = "a" * 64
MANIFEST_SHA = "b" * 64
CROSSWALK_SHA = "c" * 64


class _Claim:
    id = 901
    job_ref = "REJ_fixture"
    school_id = 11
    research_session_id = 71
    task_id = 21
    class_id = 31
    task_enrollment_id = 51
    subject_id = 61
    task_binding_id = 81
    profile_version_id = 91
    profile_ref = "profile-promis-v3"
    profile_version_number = 3
    profile_sha256 = PROFILE_SHA
    response_origin = "PUBLIC_OBSERVED"
    policy_version = RESEARCH_EDUCATION_POLICY_VERSION
    policy_hash = None
    status = "LEASED"
    attempt_count = 1
    lease_owner = "research-worker-11"
    lease_token = "lease-test-token"


class _Repository:
    def __init__(self, claim=None, *, fail_finish=False, fail_retry=False):
        self.claims = [] if claim is None else [claim]
        self.calls = []
        self.fail_finish = fail_finish
        self.fail_retry = fail_retry

    async def claim_next(self, **kwargs):
        self.calls.append(("claim", kwargs))
        found, self.claims = self.claims[:1], self.claims[1:]
        return found

    async def finish(self, **kwargs):
        self.calls.append(("finish", kwargs))
        if self.fail_finish:
            from database_layer.errors import OptimisticConcurrencyConflict

            raise OptimisticConcurrencyConflict("stale")
        return SimpleNamespace(status=kwargs["status"])

    async def retry(self, **kwargs):
        self.calls.append(("retry", kwargs))
        if self.fail_retry:
            from database_layer.errors import OptimisticConcurrencyConflict

            raise OptimisticConcurrencyConflict("stale")
        return SimpleNamespace(status="RETRY")


class _Uow:
    def __init__(self, repository, state):
        self.research_education_jobs = repository
        self.state = state
        self.session = None

    async def __aenter__(self):
        self.state["active"] += 1
        return self

    async def __aexit__(self, exc_type, _exc, _tb):
        self.state["active"] -= 1
        self.state["last_exit"] = "rollback" if exc_type else "commit"


def _worker(repository, authorization, *, shared_lock=None):
    state = {"active": 0}
    return (
        ResearchEducationWorker(
            school_id=11,
            unit_of_work_factory=lambda: _Uow(repository, state),
            authorization=authorization,
            concurrency_lock=shared_lock,
            worker_id="research-worker-11",
            clock=lambda: NOW,
        ),
        state,
    )


@pytest.mark.asyncio
async def test_default_policy_abstains_in_same_short_uow_without_processor_or_content():
    claim = _Claim()
    repository = _Repository(claim)
    state = {"active": 0}

    class _Authorization:
        async def finalize_no_policy(self, actual_claim, *, now):
            assert state["active"] == 0
            assert actual_claim is claim
            assert now == NOW
            return "ABSTAINED"

    worker, _ = _worker(repository, _Authorization())
    assert "processor" not in inspect.signature(ResearchEducationWorker).parameters
    assert await worker.run_once() is ResearchEducationWorkerResult.ABSTAINED
    assert [kind for kind, _ in repository.calls] == ["claim"]
    assert repository.calls[0][1]["max_attempts"] == 5


@pytest.mark.asyncio
async def test_live_scope_revocation_cancels_without_opening_any_content_path():
    claim = _Claim()
    repository = _Repository(claim)

    class _Authorization:
        async def finalize_no_policy(self, actual_claim, *, now):
            return "CANCELLED"

    worker, _ = _worker(repository, _Authorization())
    assert await worker.run_once() is ResearchEducationWorkerResult.CANCELLED
    # Cancellation is performed by the live adapter in the same UOW as its
    # current-scope check. The worker has no RAG/LLM or snapshot API.
    assert not any(hasattr(worker, name) for name in ("processor", "rag", "llm", "snapshot"))


@pytest.mark.asyncio
async def test_stale_lease_is_not_retried_or_reported_as_applied():
    claim = _Claim()
    repository = _Repository(claim, fail_retry=True)

    class _Authorization:
        async def finalize_no_policy(self, actual_claim, *, now):
            raise ResearchEducationAuthorizationUnavailable()

    worker, _ = _worker(repository, _Authorization())
    result = await worker.run_once()
    assert result is ResearchEducationWorkerResult.STALE_LEASE
    assert [kind for kind, _ in repository.calls] == ["claim", "retry"]


@pytest.mark.asyncio
async def test_authorization_failure_uses_allowlisted_bounded_retry_and_rolls_back():
    claim = _Claim()
    repository = _Repository(claim)

    class _Authorization:
        async def finalize_no_policy(self, _claim, *, now):
            raise ResearchEducationAuthorizationUnavailable()

    worker, state = _worker(repository, _Authorization())
    assert await worker.run_once() is ResearchEducationWorkerResult.RETRY
    assert [kind for kind, _ in repository.calls] == ["claim", "retry"]
    assert repository.calls[-1][1]["error_code"].value == "INTERNAL_FAILURE"
    assert repository.calls[-1][1]["max_attempts"] == 5
    assert state["active"] == 0


def _trusted_policy() -> ResearchStudyUsePolicy:
    return ResearchStudyUsePolicy(
        study_ref="study-alpha",
        school_id=11,
        institution="Synthetic School",
        use_scope="ISOLATED_HISTORICAL_REPLAY",
        noncommercial=True,
        historical_replay_only=True,
        english_unchanged=True,
        starts_at=NOW - timedelta(days=3),
        ends_at=NOW + timedelta(days=3),
        profiles=(
            ResearchStudyProfilePin("profile-promis-v3", PROFILE_SHA, MANIFEST_SHA, CROSSWALK_SHA),
        ),
        rights_basis="Operator recorded public-source research-use basis.",
        rights_source_urls=("https://example.org/research-rights",),
        recorded_by="operator-fixture",
        recorded_at=NOW - timedelta(days=1),
        operator_declaration="Synthetic fixture for tests.",
        source_rights_verified=True,
    )


def _valid_mapping(claim):
    now = NOW.replace(tzinfo=None)
    return {
        "session_id": claim.research_session_id,
        "session_school_id": claim.school_id,
        "session_task_id": claim.task_id,
        "session_class_id": claim.class_id,
        "session_enrollment_id": claim.task_enrollment_id,
        "session_subject_id": claim.subject_id,
        "session_binding_id": claim.task_binding_id,
        "session_profile_version_id": claim.profile_version_id,
        "session_profile_ref": claim.profile_ref,
        "session_profile_version_number": claim.profile_version_number,
        "session_profile_sha256": claim.profile_sha256,
        "session_response_origin": claim.response_origin,
        "session_status": "COMPLETED",
        "session_completed_at": now,
        "session_purpose": "RESEARCH_SIMULATION",
        "session_research_only": True,
        "task_id": claim.task_id,
        "task_school_id": claim.school_id,
        "task_class_id": claim.class_id,
        "task_status": "PUBLISHED",
        "task_mode": "RESEARCH_PROFILE",
        "task_opens_at": (NOW - timedelta(hours=1)).replace(tzinfo=None),
        "task_due_at": (NOW + timedelta(hours=1)).replace(tzinfo=None),
        "school_id": claim.school_id,
        "school_status": "ACTIVE",
        "school_data_origin": "SYNTHETIC",
        "class_id": claim.class_id,
        "class_school_id": claim.school_id,
        "class_status": "ACTIVE",
        "enrollment_id": claim.task_enrollment_id,
        "enrollment_school_id": claim.school_id,
        "enrollment_task_id": claim.task_id,
        "enrollment_class_id": claim.class_id,
        "enrollment_roster_id": 41,
        "enrollment_subject_id": claim.subject_id,
        "enrollment_status": "ACTIVE",
        "enrollment_revoked_at": None,
        "roster_id": 41,
        "roster_school_id": claim.school_id,
        "roster_class_id": claim.class_id,
        "roster_subject_id": claim.subject_id,
        "roster_status": "ACTIVE",
        "roster_valid_from": (NOW - timedelta(days=1)).replace(tzinfo=None),
        "roster_valid_until": None,
        "roster_revoked_at": None,
        "subject_id": claim.subject_id,
        "subject_school_id": claim.school_id,
        "subject_status": "ACTIVE",
        "subject_data_origin": "SYNTHETIC",
        "grant_id": 1,
        "principal_account_id": 101,
        "grant_relationship": "SELF",
        "grant_status": "ACTIVE",
        "grant_valid_from": (NOW - timedelta(days=1)).replace(tzinfo=None),
        "grant_valid_until": None,
        "grant_revoked_at": None,
        "membership_id": 201,
        "membership_school_id": claim.school_id,
        "membership_account_id": 101,
        "membership_status": "ACTIVE",
        "membership_valid_from": (NOW - timedelta(days=1)).replace(tzinfo=None),
        "membership_valid_until": None,
        "membership_revoked_at": None,
        "membership_role_id": 301,
        "membership_role_school_id": claim.school_id,
        "membership_role_membership_id": 201,
        "membership_role_code": "student",
        "membership_role_status": "ACTIVE",
        "membership_role_valid_from": (NOW - timedelta(days=1)).replace(tzinfo=None),
        "membership_role_valid_until": None,
        "membership_role_revoked_at": None,
        "global_role_status": "ACTIVE",
        "account_status": "ACTIVE",
        "binding_id": claim.task_binding_id,
        "binding_school_id": claim.school_id,
        "binding_task_id": claim.task_id,
        "binding_class_id": claim.class_id,
        "binding_profile_version_id": claim.profile_version_id,
        "binding_profile_ref": claim.profile_ref,
        "binding_profile_version_number": claim.profile_version_number,
        "binding_profile_sha256": claim.profile_sha256,
        "binding_response_origin": claim.response_origin,
        "binding_status": "ACTIVE",
        "binding_revoked_at": None,
        "binding_purpose": "RESEARCH_SIMULATION",
        "binding_research_only": True,
        "binding_cohort_id": None,
        "profile_version_id": claim.profile_version_id,
        "profile_school_id": claim.school_id,
        "profile_ref": claim.profile_ref,
        "profile_version_number": claim.profile_version_number,
        "profile_sha256": PROFILE_SHA,
        "profile_parameter_origin": "PUBLISHED_ROUNDED_REFERENCE",
        "profile_rights_status": "VERIFIED",
        "profile_execution_status": "SIMULATION_ENABLED",
        "profile_research_only": True,
        "profile_human_curated": False,
        "profile_interpretation_allowed": False,
        "profile_publication_status": "not_approved_for_publication_or_operational_use",
        "profile_simulation_enabled_at": (NOW - timedelta(days=1)).replace(tzinfo=None),
        "profile_rights_revoked_at": None,
        "profile_disabled_at": None,
        "profile_fit_sha256": None,
        "profile_calibration_sha256": None,
        "profile_manifest_sha256": MANIFEST_SHA,
        "profile_crosswalk_sha256": CROSSWALK_SHA,
        "cohort_id": None,
        "cohort_school_id": None,
        "cohort_study_ref": None,
        "cohort_status": None,
        "cohort_purpose": None,
        "cohort_research_only": None,
    }


class _Row:
    def __init__(self, mapping):
        self._mapping = mapping


class _Result:
    def __init__(self, mappings):
        self.rows = [_Row(item) for item in mappings]

    def all(self):
        return self.rows


class _Session:
    def __init__(self, mappings):
        self.mappings = mappings
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _Result(self.mappings)


class _AuthUow:
    def __init__(self, session, repository, state):
        self.session = session
        self.research_education_jobs = repository
        self.state = state

    async def __aenter__(self):
        self.state["active"] += 1
        return self

    async def __aexit__(self, exc_type, _exc, _tb):
        self.state["active"] -= 1
        self.state["exit"] = "rollback" if exc_type else "commit"


@pytest.mark.asyncio
@pytest.mark.parametrize("after_deadline", [False, True])
async def test_live_authorization_reads_only_metadata_and_finishes_in_same_uow(after_deadline):
    from database_layer import models
    from sqlalchemy import select

    claim = _Claim()
    row = _valid_mapping(claim)
    if after_deadline:
        row["task_due_at"] = (NOW - timedelta(seconds=1)).replace(tzinfo=None)
        row["session_completed_at"] = (NOW - timedelta(seconds=2)).replace(tzinfo=None)
    state = {"active": 0}
    repo = _Repository()
    session = _Session([row])
    uow = _AuthUow(session, repo, state)

    class _Context:
        async def __aenter__(self):
            return await uow.__aenter__()

        async def __aexit__(self, *args):
            return await uow.__aexit__(*args)

    class _Persistence:
        identity_profile = "school_tenant"
        _started = True
        _db_models = models
        _select = staticmethod(select)

        def _uow(self):
            return _Context()

    adapter = SchoolResearchEducationLiveAuthorization(
        _Persistence(), school_id=claim.school_id, study_use_policy=_trusted_policy()
    )
    assert await adapter.finalize_no_policy(claim, now=NOW) == "ABSTAINED"
    assert state["active"] == 0
    assert state["exit"] == "commit"
    assert repo.calls[0][0] == "finish"
    assert repo.calls[0][1]["status"] == "ABSTAINED"
    assert repo.calls[0][1]["error_code"].value == "POLICY_UNAVAILABLE"
    sql = str(session.statement).lower()
    for forbidden in (
        "snapshot_ciphertext",
        "payload_ciphertext",
        "config_ciphertext",
        "case_index",
    ):
        assert forbidden not in sql


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("grant_status", "REVOKED"),
        ("roster_status", "REVOKED"),
        ("enrollment_status", "REVOKED"),
        ("task_status", "CANCELLED"),
        ("profile_rights_status", "REVOKED"),
        ("profile_execution_status", "DISABLED"),
        ("session_status", "IN_PROGRESS"),
    ],
)
async def test_live_authorization_cancels_on_revocation_or_stale_scope(field, value):
    from database_layer import models
    from sqlalchemy import select

    claim = _Claim()
    row = _valid_mapping(claim)
    row[field] = value
    state = {"active": 0}
    repo = _Repository()
    session = _Session([row])
    uow = _AuthUow(session, repo, state)

    class _Persistence:
        identity_profile = "school_tenant"
        _started = True
        _db_models = models
        _select = staticmethod(select)

        def _uow(self):
            return _Context()

    class _Context:
        async def __aenter__(self):
            return await uow.__aenter__()

        async def __aexit__(self, *args):
            return await uow.__aexit__(*args)

    adapter = SchoolResearchEducationLiveAuthorization(
        _Persistence(), school_id=claim.school_id, study_use_policy=_trusted_policy()
    )
    assert await adapter.finalize_no_policy(claim, now=NOW) == "CANCELLED"
    assert repo.calls[0][1]["status"] == "CANCELLED"
    assert repo.calls[0][1]["error_code"] is None


@pytest.mark.asyncio
async def test_live_authorization_rejects_duplicate_self_rows_and_study_pin_mismatch():
    from database_layer import models
    from sqlalchemy import select

    claim = _Claim()
    state = {"active": 0}
    repository = _Repository()
    session = _Session([_valid_mapping(claim), _valid_mapping(claim)])
    uow = _AuthUow(session, repository, state)

    class _Persistence:
        identity_profile = "school_tenant"
        _started = True
        _db_models = models
        _select = staticmethod(select)

        def _uow(self):
            return _Context()

    class _Context:
        async def __aenter__(self):
            return await uow.__aenter__()

        async def __aexit__(self, *args):
            return await uow.__aexit__(*args)

    adapter = SchoolResearchEducationLiveAuthorization(
        _Persistence(), school_id=claim.school_id, study_use_policy=_trusted_policy()
    )
    assert await adapter.finalize_no_policy(claim, now=NOW) == "CANCELLED"
    assert repository.calls[-1][1]["status"] == "CANCELLED"
