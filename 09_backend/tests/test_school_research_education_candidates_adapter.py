from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from smhai_backend.adapters.school_research_education_candidates import (
    SchoolResearchEducationCandidatePersistenceAdapter,
)
from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.domains.models import BackendRole
from smhai_backend.domains.research_general_education.service import SAFETY_POLICY_VERSION

from .test_school_research_education_candidates_service import (
    actor,
    candidate_payload,
)

_POLICY_HASH = "1" * 64
_SOURCE_MANIFEST = "2" * 64


def adapter(**changes):
    values = {
        "enabled": True,
        "school_id": 17,
        "school_study_ref": "SCHOOL_STUDY_SYNTHETIC",
        "policy_hash": _POLICY_HASH,
        "source_manifest_sha256": _SOURCE_MANIFEST,
        "source_package_ref": "R3_PACKAGE_SYNTHETIC",
        "source_study_ref": "R3_STUDY_SYNTHETIC",
        "study_use_policy": None,
    }
    values.update(changes)
    return SchoolResearchEducationCandidatePersistenceAdapter(None, **values)


def _row(payload, **changes):
    provenance = payload.provenance
    adapter_for_hash = adapter()
    values = dict(
        study_ref="SCHOOL_STUDY_SYNTHETIC",
        policy_version="RESEARCH_GENERAL_EDUCATION_DRAFT_V1",
        policy_hash=provenance.policy_hash,
        source_manifest_sha256=provenance.source_manifest_sha256,
        purpose="RESEARCH_SIMULATION",
        research_only=True,
        psychological_interpretation_allowed=False,
        publication_status="not_approved_for_publication_or_operational_use",
        safety_policy_version=SAFETY_POLICY_VERSION,
        content_revision=1,
        status="HELD",
        state_version=1,
        content_sha256=adapter_for_hash._payload_sha256(payload),
        scope=SimpleNamespace(response_origin="PUBLIC_OBSERVED"),
        payload_schema_version="school-research-general-education-candidate.v1",
        cipher_format_version="enc.v1",
        key_version="key-v1",
        payload_ciphertext=b"ciphertext",
        retrieval_id=provenance.retrieval_id,
        retrieval_bundle_sha256=provenance.retrieval_bundle_sha256,
        prompt_ref=provenance.prompt_id,
        prompt_version=provenance.prompt_version,
        prompt_sha256=provenance.prompt_sha256,
        model_ref=provenance.model_id,
        model_digest_sha256=provenance.model_digest_sha256,
        runtime_version=provenance.runtime_version,
        input_safety_action=provenance.input_safety_action,
        retrieval_safety_action=provenance.retrieval_safety_action,
        output_safety_action=provenance.output_safety_action,
    )
    values.update(changes)
    return SimpleNamespace(**values)


def test_disabled_or_unpinned_candidate_policy_fails_closed():
    with pytest.raises(BackendError) as raised:
        adapter(enabled=False)._require_enabled()
    assert raised.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE

    with pytest.raises(BackendError) as raised:
        adapter(policy_hash=None)._require_enabled()
    assert raised.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE


async def test_wrong_school_is_hidden_before_scope_resolution():
    configured = adapter()
    with pytest.raises(BackendError) as raised:
        await configured._active_task(
            object(),
            replace(actor(BackendRole.PSYCHOLOGICAL_SPECIALIST), school_id=18),
            "TASK_demo",
            at=datetime.now(UTC),
        )
    assert raised.value.code is ErrorCode.RESOURCE_NOT_FOUND


@pytest.mark.parametrize("response_origin", ["PUBLIC_OBSERVED", "MODEL_GENERATED"])
async def test_active_task_rechecks_current_assigned_specialist_and_observed_binding(
    response_origin,
):
    configured = adapter()
    task = SimpleNamespace(id=23, class_id=5)
    binding = SimpleNamespace(response_origin=response_origin)
    assignment = SimpleNamespace(specialist_membership_role_id=7)

    async def require_actor(_uow, _actor, _role, _at):
        return 101, 7

    async def get_task(_uow, _actor, _task_ref, *, lock):
        assert lock is True
        return task

    async def active_assignment(_uow, _actor, _task, *, at, lock):
        assert lock is True
        return assignment

    async def task_scope(_uow, _actor, _task, _at):
        return binding, object()

    configured._require_actor = require_actor
    configured._task = get_task
    configured._active_assignment = active_assignment
    configured._require_task_study_scope = task_scope

    if response_origin == "MODEL_GENERATED":
        with pytest.raises(BackendError) as raised:
            await configured._active_task(
                object(),
                actor(BackendRole.PSYCHOLOGICAL_SPECIALIST),
                "TASK_demo",
                at=datetime.now(UTC),
            )
        assert raised.value.code is ErrorCode.RESOURCE_NOT_FOUND
    else:
        result = await configured._active_task(
            object(), actor(BackendRole.PSYCHOLOGICAL_SPECIALIST), "TASK_demo", at=datetime.now(UTC)
        )
        assert result == (task, binding, 7)


async def test_revoked_specialist_assignment_fails_closed():
    configured = adapter()
    task = SimpleNamespace(id=23, class_id=5)

    async def require_actor(_uow, _actor, _role, _at):
        return 101, 7

    async def get_task(_uow, _actor, _task_ref, *, lock):
        return task

    async def revoked_assignment(_uow, _actor, _task, *, at, lock):
        raise BackendError(ErrorCode.RESOURCE_NOT_FOUND)

    configured._require_actor = require_actor
    configured._task = get_task
    configured._active_assignment = revoked_assignment

    with pytest.raises(BackendError) as raised:
        await configured._active_task(
            object(), actor(BackendRole.PSYCHOLOGICAL_SPECIALIST), "TASK_demo", at=datetime.now(UTC)
        )
    assert raised.value.code is ErrorCode.RESOURCE_NOT_FOUND


async def test_generation_job_list_is_current_task_scoped_and_content_free(monkeypatch):
    from database_layer import models
    from sqlalchemy import select

    configured = adapter()
    monkeypatch.setattr(configured, "_require_enabled", lambda: None)
    configured._db_models = models
    monkeypatch.setattr(configured, "_select", select, raising=False)
    now = datetime(2026, 10, 15, tzinfo=UTC)
    monkeypatch.setattr(configured, "_now", lambda: (now, now))
    task = SimpleNamespace(id=23, class_id=31)
    binding = SimpleNamespace(
        binding_id=61,
        profile_version_id=71,
        profile_ref="PROMIS_SYNTHETIC",
        profile_version_number=3,
        profile_sha256="4" * 64,
    )

    async def active_task(_uow, _actor, _task_ref, *, at):
        assert at == now
        return task, binding, 7

    monkeypatch.setattr(configured, "_active_task", active_task)

    class Rows:
        def __init__(self, rows):
            self.rows = rows

        def all(self):
            return self.rows

    class Session:
        def __init__(self):
            self.statements = []

        async def scalar(self, statement):
            self.statements.append(statement)
            return 1

        async def execute(self, statement):
            self.statements.append(statement)
            if len(self.statements) == 2:
                return Rows([
                    SimpleNamespace(
                        _mapping={
                            "job_ref": "REJ_" + "a" * 64,
                            "status": "HELD",
                            "attempt_count": 1,
                            "last_error_code": None,
                            "created_at": now,
                            "updated_at": now,
                        }
                    )
                ])
            return Rows([("HELD", 1)])

    class UnitOfWork:
        def __init__(self):
            self.session = Session()
            self.entered = self.exited = 0

        async def __aenter__(self):
            self.entered += 1
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            self.exited += 1
            return False

    uow = UnitOfWork()
    monkeypatch.setattr(configured, "_uow", lambda: uow, raising=False)

    result = await configured.school_research_education_candidate_generation_job_list(
        actor(BackendRole.PSYCHOLOGICAL_SPECIALIST), "TASK_demo", offset=0, limit=20
    )

    assert result["total"] == 1
    assert result["status_counts"]["HELD"] == 1
    assert result["items"] == [
        {
            "job_ref": "REJ_" + "a" * 64,
            "status": "HELD",
            "attempt_count": 1,
            "last_error_code": None,
            "created_at": now,
            "updated_at": now,
        }
    ]
    assert uow.entered == uow.exited == 1
    assert len(uow.session.statements) == 3
    parameters = [
        set(statement.compile().params.values()) for statement in uow.session.statements
    ]
    assert all(_POLICY_HASH in values for values in parameters)
    assert all("RESEARCH_GENERAL_EDUCATION_DRAFT_V1" in values for values in parameters)
    assert all(task.id in values for values in parameters)
    assert all(binding.binding_id in values for values in parameters)
    selected = " ".join(str(column) for column in uow.session.statements[1].selected_columns)
    assert all(name in selected for name in ("job_ref", "status", "attempt_count", "created_at"))
    assert all(
        name not in selected
        for name in ("subject_id", "lease_owner", "lease_token", "payload")
    )


def test_new_payload_must_match_server_policy_source_and_model_pins():
    configured = adapter()
    payload = candidate_payload()
    assert configured._validate_new_payload(payload) is payload

    unpinned = payload.model_dump(mode="json")
    unpinned["provenance"]["source_manifest_sha256"] = "9" * 64
    with pytest.raises(BackendError) as raised:
        configured._validate_new_payload(unpinned)
    assert raised.value.code is ErrorCode.FORBIDDEN

    altered_excerpt = payload.model_dump(mode="json")
    altered_excerpt["source_cards"][0]["excerpt_text"] += " modified"
    with pytest.raises(BackendError) as raised:
        configured._validate_new_payload(altered_excerpt)
    assert raised.value.code is ErrorCode.FORBIDDEN


def test_candidate_readback_checks_row_payload_provenance_and_content_hash():
    configured = adapter()
    payload = candidate_payload()
    configured.protection = SimpleNamespace(
        decrypt_json=lambda _encrypted: payload.model_dump(mode="python")
    )

    result = configured._payload_from_row(_row(payload))
    assert result.provenance.model_digest_sha256 == payload.provenance.model_digest_sha256
    assert result.source_cards[0].excerpt_text == payload.source_cards[0].excerpt_text

    tampered = _row(payload, model_ref="other-model")
    with pytest.raises(BackendError) as raised:
        configured._payload_from_row(tampered)
    assert raised.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE

    with pytest.raises(BackendError) as raised:
        configured._payload_from_row(_row(payload, content_sha256="0" * 64))
    assert raised.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE


async def test_worker_live_claim_locks_task_scope_before_job_lease():
    from database_layer import models
    from database_layer.school_research_education_jobs import ResearchEducationJobClaim
    from sqlalchemy import select

    claim = ResearchEducationJobClaim(
        id=91,
        job_ref="REDJOB_synthetic",
        school_id=17,
        research_session_id=11,
        task_id=23,
        class_id=31,
        task_enrollment_id=41,
        subject_id=51,
        task_binding_id=61,
        profile_version_id=71,
        profile_ref="PROMIS_SYNTHETIC",
        profile_version_number=3,
        profile_sha256="1" * 64,
        response_origin="PUBLIC_OBSERVED",
        policy_version="RESEARCH_GENERAL_EDUCATION_DRAFT_V1",
        policy_hash=_POLICY_HASH,
        purpose="RESEARCH_SIMULATION",
        research_only=True,
        publication_status="not_approved_for_publication_or_operational_use",
        status="LEASED",
        attempt_count=1,
        next_attempt_at=None,
        lease_expires_at=datetime(2026, 10, 15, 12, tzinfo=UTC),
        last_error_code=None,
        created_at=datetime(2026, 10, 15, 11, tzinfo=UTC),
        updated_at=datetime(2026, 10, 15, 11, tzinfo=UTC),
        lease_owner="worker-synthetic",
        lease_token="token-synthetic",
    )
    scope = SimpleNamespace(
        research_session_id=11,
        school_id=17,
        task_id=23,
        class_id=31,
        task_enrollment_id=41,
        subject_id=51,
        task_binding_id=61,
        profile_version_id=71,
        profile_ref="PROMIS_SYNTHETIC",
        profile_version_number=3,
        profile_sha256="1" * 64,
        response_origin="PUBLIC_OBSERVED",
    )
    events = []

    class Session:
        def __init__(self):
            self.scalar_calls = 0

        async def scalar(self, _statement):
            self.scalar_calls += 1
            if self.scalar_calls == 1:
                events.append("task_lock")
                return SimpleNamespace(id=23, class_id=31)
            return "SCHOOL_synthetic"

    class JobRepository:
        async def require_active_claim(self, **kwargs):
            assert kwargs["job_id"] == claim.id
            events.append("job_lease_lock")
            return claim

    configured = adapter()
    configured._db_models = models
    configured._db_enums = SimpleNamespace(
        DataOrigin=SimpleNamespace(SYNTHETIC=SimpleNamespace(value="SYNTHETIC"))
    )
    configured._select = select

    async def require_assignment(_uow, _task, *, at):
        events.append("assignment_lock")

    async def require_profile_scope(_uow, _actor, _task, _now):
        events.append("profile_scope")
        return (
            SimpleNamespace(
                binding_id=61,
                response_origin="PUBLIC_OBSERVED",
                profile_version_id=71,
                profile_ref="PROMIS_SYNTHETIC",
                profile_version_number=3,
                profile_sha256="1" * 64,
            ),
            None,
        )

    async def session_ref(_uow, _actor, _task, session_id):
        assert session_id == claim.research_session_id
        events.append("session_ref")
        return "RSESS_synthetic"

    async def current_scope(_uow, _actor, _task, **kwargs):
        assert kwargs["lock"] is True
        events.append("session_scope_lock")
        return scope, None, None, None, None

    configured._require_active_specialist_assignment = require_assignment
    configured._require_task_study_scope = require_profile_scope
    configured._session_ref = session_ref
    configured._current_scope = current_scope
    uow = SimpleNamespace(
        session=Session(),
        research_education_jobs=JobRepository(),
    )

    result = await configured._live_claim_scope(
        uow, claim, now=datetime(2026, 10, 15, 11, 30, tzinfo=UTC)
    )

    assert result[0] is claim
    assert events == [
        "task_lock",
        "assignment_lock",
        "profile_scope",
        "session_ref",
        "session_scope_lock",
        "job_lease_lock",
    ]


async def test_claim_with_wrong_policy_hash_is_denied_and_only_cancelled():
    from database_layer.school_research_education_jobs import ResearchEducationJobClaim

    claim = ResearchEducationJobClaim(
        id=91,
        job_ref="REDJOB_synthetic",
        school_id=17,
        research_session_id=11,
        task_id=23,
        class_id=31,
        task_enrollment_id=41,
        subject_id=51,
        task_binding_id=61,
        profile_version_id=71,
        profile_ref="PROMIS_SYNTHETIC",
        profile_version_number=3,
        profile_sha256="1" * 64,
        response_origin="PUBLIC_OBSERVED",
        policy_version="RESEARCH_GENERAL_EDUCATION_DRAFT_V1",
        policy_hash="9" * 64,
        purpose="RESEARCH_SIMULATION",
        research_only=True,
        publication_status="not_approved_for_publication_or_operational_use",
        status="LEASED",
        attempt_count=1,
        next_attempt_at=None,
        lease_expires_at=datetime(2026, 10, 15, 12, tzinfo=UTC),
        last_error_code=None,
        created_at=datetime(2026, 10, 15, 11, tzinfo=UTC),
        updated_at=datetime(2026, 10, 15, 11, tzinfo=UTC),
        lease_owner="worker-synthetic",
        lease_token="token-synthetic",
    )
    finished = []

    class JobRepository:
        async def require_active_claim(self, **kwargs):
            assert kwargs["job_id"] == claim.id
            return claim

        async def finish(self, **kwargs):
            finished.append(kwargs)

    class UnitOfWork:
        research_education_jobs = JobRepository()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    configured = adapter()
    configured._require_enabled = lambda: None
    configured._utc_now = lambda: datetime(2026, 10, 15, 11, 30, tzinfo=UTC)
    configured._uow = UnitOfWork
    disposition = await configured.finalize_education_job(
        claim, status="REVIEW_REQUIRED"
    )

    assert disposition == "CANCELLED"
    assert len(finished) == 1
    assert finished[0]["status"] == "CANCELLED"
    assert finished[0]["error_code"] is None
