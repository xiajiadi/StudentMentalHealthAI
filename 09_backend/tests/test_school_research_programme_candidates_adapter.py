from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from smhai_backend.adapters.school_research_programme_candidates import (
    SchoolResearchProgrammeCandidatePersistenceAdapter,
)
from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.domains.research_programme_generation.schemas import STUDY_REF
from smhai_backend.domains.school_research_programme_candidates.schemas import (
    GeneratedProgrammeCandidate,
)

from .test_school_research_feedback_adapter import _policy
from .test_school_research_programme_candidates_service import (
    _MODEL_DIGEST,
    _MODEL_REF,
    _PROMPT_REF,
    _PROMPT_VERSION,
    _generated_candidate_input,
)

_TRUSTED_SOURCE_MANIFEST_SHA256 = "f8af1a33487f175b02400fbfcf5f655cd93b40c7a5a35e0582dc363b11401a45"


def _adapter(*, expected_source_manifest_sha256=None):
    return SchoolResearchProgrammeCandidatePersistenceAdapter(
        None,
        study_use_policy=None,
        study_use_policy_sha256=None,
        enabled=True,
        expected_source_manifest_sha256=expected_source_manifest_sha256,
        expected_processor_policy_sha256="3" * 64,
        expected_model_ref=_MODEL_REF,
        expected_model_digest_sha256=_MODEL_DIGEST,
        expected_prompt_ref=_PROMPT_REF,
        expected_prompt_version=_PROMPT_VERSION,
    )


def test_candidate_detail_fails_closed_when_source_manifest_pin_is_missing():
    adapter = _adapter()

    with pytest.raises(BackendError) as raised:
        adapter._detail(
            SimpleNamespace(source_manifest_sha256=_TRUSTED_SOURCE_MANIFEST_SHA256)
        )

    assert raised.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE


def test_candidate_detail_rejects_source_manifest_mismatch_before_decrypting():
    adapter = _adapter(
        expected_source_manifest_sha256=_TRUSTED_SOURCE_MANIFEST_SHA256
    )

    with pytest.raises(BackendError) as raised:
        adapter._detail(SimpleNamespace(source_manifest_sha256="0" * 64))

    assert raised.value.code is ErrorCode.WORKFLOW_CONFLICT


def _candidate_content_payload(*, origin_fields=False):
    content = {
        "programme_ref": "staff-programme-r1",
        "title": "Source catalogue",
        "body": "Publisher: Source title [CHUNK_SOURCE]",
        "citations": [
            {
                "citation_id": "S1",
                "source_title": "Source title",
                "source_organization": "Publisher",
                "source_url": "https://example.org/source",
                "source_locator": "Section 1",
            }
        ],
    }
    if origin_fields:
        content.update(
            {
                "content_origin": "VERIFIED_SOURCE_METADATA",
                "generation_mode": "MODEL_SOURCE_SELECTION",
            }
        )
    return {
        "candidate_ref": "RPCAND_synthetic_1",
        "programme_ref": "staff-programme-r1",
        "content_revision": 1,
        "content": content,
    }


def _decrypt_row(*, prompt_version, payload_schema_version):
    return SimpleNamespace(
        candidate_ref="RPCAND_synthetic_1",
        programme_ref="staff-programme-r1",
        study_ref=STUDY_REF,
        prompt_version=prompt_version,
        payload_ciphertext=b"ciphertext",
        cipher_format_version="enc.v1",
        key_version="key-v1",
        payload_schema_version=payload_schema_version,
    )


def test_candidate_detail_labels_old_encrypted_passages_as_legacy_model_text():
    adapter = _adapter()
    adapter.protection = SimpleNamespace(
        decrypt_json=lambda _payload: _candidate_content_payload(origin_fields=False)
    )

    result = adapter._decrypt_content(
        _decrypt_row(
            prompt_version="1.1.1",
            payload_schema_version="school_research_programme_candidate.v1",
        )
    )

    assert result["content_origin"] == "LEGACY_MODEL_TEXT"
    assert result["generation_mode"] == "LEGACY_MODEL_AUTHORED_PASSAGES"


def test_candidate_detail_requires_explicit_origin_for_v120_ciphertext():
    adapter = _adapter()
    adapter.protection = SimpleNamespace(
        decrypt_json=lambda _payload: _candidate_content_payload(origin_fields=False)
    )

    with pytest.raises(BackendError) as raised:
        adapter._decrypt_content(
            _decrypt_row(
                prompt_version="1.2.0",
                payload_schema_version="school_research_programme_candidate.v2",
            )
        )

    assert raised.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE


async def test_candidate_store_requires_a_configured_source_manifest_pin():
    adapter = SchoolResearchProgrammeCandidatePersistenceAdapter(
        None,
        study_use_policy=_policy(),
        study_use_policy_sha256="a" * 64,
        enabled=True,
        expected_processor_policy_sha256="3" * 64,
        expected_model_ref=_MODEL_REF,
        expected_model_digest_sha256=_MODEL_DIGEST,
        expected_prompt_ref=_PROMPT_REF,
        expected_prompt_version=_PROMPT_VERSION,
    )
    generated = GeneratedProgrammeCandidate.model_validate(
        _generated_candidate_input(), strict=True
    )
    adapter.configure_generation(enabled=True, processor_policy_sha256="3" * 64)

    with pytest.raises(BackendError) as raised:
        await adapter.store_generated_candidate(generated)

    assert raised.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE


async def test_candidate_store_rejects_a_different_source_manifest_pin():
    adapter = SchoolResearchProgrammeCandidatePersistenceAdapter(
        None,
        study_use_policy=_policy(),
        study_use_policy_sha256="a" * 64,
        enabled=True,
        expected_source_manifest_sha256=_TRUSTED_SOURCE_MANIFEST_SHA256,
        expected_processor_policy_sha256="3" * 64,
        expected_model_ref=_MODEL_REF,
        expected_model_digest_sha256=_MODEL_DIGEST,
        expected_prompt_ref=_PROMPT_REF,
        expected_prompt_version=_PROMPT_VERSION,
    )
    generated = GeneratedProgrammeCandidate.model_validate(
        _generated_candidate_input(), strict=True
    )
    adapter.configure_generation(enabled=True, processor_policy_sha256="3" * 64)

    with pytest.raises(BackendError) as raised:
        await adapter.store_generated_candidate(generated)

    assert raised.value.code is ErrorCode.WORKFLOW_CONFLICT


async def test_candidate_store_resolves_actual_orm_lease_before_live_scope(monkeypatch):
    from dataclasses import dataclass
    from datetime import UTC, datetime, timedelta

    from database_layer import enums
    from database_layer.base import Base
    from database_layer.crypto import EncryptedPayload
    from database_layer.models import SchoolResearchEducationJob
    from database_layer.school_research_education_jobs import (
        STAFF_PROGRAMME_POLICY_VERSION,
        ResearchEducationJobClaim,
        SchoolResearchEducationJobRepository,
    )
    from sqlalchemy import create_engine, event
    from sqlalchemy.dialects import mysql
    from sqlalchemy.orm import Session

    from smhai_backend.adapters.school_research_programme_candidates import (
        _job_lease_matches_persisted_claim,
        _task_scope_matches_persisted_claim,
    )

    medium_blob_cls = type(mysql.MEDIUMBLOB())
    big_int_cls = type(mysql.BIGINT(unsigned=True))
    medium_blob_dispatch = medium_blob_cls._compiler_dispatch
    big_int_dispatch = big_int_cls._compiler_dispatch
    monkeypatch.setattr(
        medium_blob_cls,
        "_compiler_dispatch",
        lambda self, visitor, **kw: (
            "BLOB"
            if visitor.dialect.name == "sqlite"
            else medium_blob_dispatch(self, visitor, **kw)
        ),
    )
    monkeypatch.setattr(
        big_int_cls,
        "_compiler_dispatch",
        lambda self, visitor, **kw: (
            "INTEGER"
            if visitor.dialect.name == "sqlite"
            else big_int_dispatch(self, visitor, **kw)
        ),
    )
    engine = create_engine("sqlite://")
    event.listen(
        engine,
        "connect",
        lambda connection, _record: connection.create_collation(
            "ascii_bin", lambda left, right: (left > right) - (left < right)
        ),
    )
    Base.metadata.create_all(engine, tables=[SchoolResearchEducationJob.__table__])
    database = Session(engine)
    now = datetime.now(UTC)
    lease_owner = "programme-worker"
    lease_token = "lease_token"
    profile_sha256 = "1" * 64
    policy_sha256 = "3" * 64

    row = SchoolResearchEducationJob(
        id=1,
        public_id="job-public-1",
        job_ref="REJ_synthetic_candidate_store_1",
        research_session_id=2,
        school_id=17,
        task_id=21,
        class_id=31,
        task_enrollment_id=41,
        subject_id=51,
        task_binding_id=61,
        profile_version_id=91,
        profile_ref="PROMIS_SYNTHETIC",
        profile_version_number=3,
        profile_sha256=profile_sha256,
        response_origin="PUBLIC_OBSERVED",
        job_kind="EDUCATION_SUPPORT",
        purpose="RESEARCH_SIMULATION",
        research_only=True,
        publication_status="not_approved_for_publication_or_operational_use",
        policy_version=STAFF_PROGRAMME_POLICY_VERSION,
        policy_hash=policy_sha256,
        status="LEASED",
        attempt_count=1,
        next_attempt_at=None,
        lease_owner=lease_owner,
        lease_expires_at=(now + timedelta(minutes=30)).replace(tzinfo=None),
        lease_token=lease_token,
        last_error_code=None,
        created_at=now.replace(tzinfo=None),
        updated_at=now.replace(tzinfo=None),
    )
    database.add(row)
    database.commit()

    class _AsyncSession:
        def __init__(self, sync_session):
            self.sync_session = sync_session

        async def scalar(self, statement):
            return self.sync_session.scalar(statement)

        async def scalars(self, statement):
            return self.sync_session.scalars(statement)

        async def flush(self):
            self.sync_session.flush()

    @dataclass(frozen=True)
    class _Task:
        id: int
        class_id: int

    @dataclass(frozen=True)
    class _Binding:
        binding_id: int
        profile_version_id: int
        profile_ref: str
        profile_version_number: int
        profile_sha256: str
        response_origin: str

    @dataclass(frozen=True)
    class _Pin:
        profile_ref: str
        profile_sha256: str

    @dataclass(frozen=True)
    class _CandidateSummary:
        candidate_ref: str
        programme_ref: str
        status: str
        state_version: int
        student_feedback_eligible: bool
        output_boundary: str
        created_at: datetime
        purpose: str
        research_only: bool
        psychological_interpretation_allowed: bool
        publication_status: str

    class _CandidateRepository:
        def __init__(self):
            self.created = []

        async def create_held(self, **values):
            self.created.append(values)
            return _CandidateSummary(
                candidate_ref=values["candidate_ref"],
                programme_ref=values["programme_ref"],
                status="HELD",
                state_version=1,
                student_feedback_eligible=False,
                output_boundary="STAFF_REFERENCE_ONLY",
                created_at=values["now"],
                purpose="RESEARCH_SIMULATION",
                research_only=True,
                psychological_interpretation_allowed=False,
                publication_status="not_approved_for_publication_or_operational_use",
            )

    class _Audit:
        async def append(self, **_values):
            return None

    class _Uow:
        def __init__(self):
            self.session = _AsyncSession(database)
            self.research_education_jobs = SchoolResearchEducationJobRepository(self.session)
            self.research_programme_candidates = _CandidateRepository()
            self.audit = _Audit()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, _exc, _tb):
            if exc_type is None:
                database.commit()
            else:
                database.rollback()
            return False

    adapter = SchoolResearchProgrammeCandidatePersistenceAdapter(
        None,
        study_use_policy=_policy(),
        study_use_policy_sha256="a" * 64,
        enabled=True,
        expected_source_manifest_sha256="c" * 64,
        expected_processor_policy_sha256=policy_sha256,
        expected_model_ref=_MODEL_REF,
        expected_model_digest_sha256=_MODEL_DIGEST,
        expected_prompt_ref=_PROMPT_REF,
        expected_prompt_version=_PROMPT_VERSION,
    )
    adapter.configure_generation(enabled=True, processor_policy_sha256=policy_sha256)
    adapter._db_enums = enums
    adapter._utc_now = lambda: now
    uow = _Uow()
    adapter._uow = lambda: uow
    live_claims = []
    profile_pin = _Pin("PROMIS_SYNTHETIC", profile_sha256)

    async def live_generation_scope(_uow, claim, *, at):
        assert type(claim) is ResearchEducationJobClaim
        assert at == now
        live_claims.append(claim)
        return _Task(21, 31), _Binding(61, 91, "PROMIS_SYNTHETIC", 3, profile_sha256,
                                       "PUBLIC_OBSERVED"), object(), profile_pin

    adapter._live_generation_scope = live_generation_scope
    source = _generated_candidate_input()
    source["job"].update(school_id=17, research_session_id=2, lease_owner=lease_owner,
                         lease_token=lease_token, policy_hash=policy_sha256)
    source["task_scope"].update(school_id=17, task_id=21, class_id=31, task_binding_id=61,
                               profile_version_id=91, profile_ref="PROMIS_SYNTHETIC",
                               profile_sha256=profile_sha256)
    source["study_ref"] = _policy().study_ref
    source["study_policy_sha256"] = "a" * 64
    generated = GeneratedProgrammeCandidate.model_validate(source, strict=True)

    class _Protection:
        def encrypt_json(self, _value, *, payload_schema_version):
            return EncryptedPayload(
                ciphertext=b"synthetic-ciphertext",
                key_version="key-v1",
                cipher_format_version="enc.v1",
                payload_schema_version=payload_schema_version,
            )

    adapter.protection = _Protection()
    try:
        result = await adapter.store_generated_candidate(generated)
        assert result["status"] == "HELD"
        assert result["student_feedback_eligible"] is False
        assert len(live_claims) == 1
        claim = live_claims[0]
        assert claim.task_id == 21
        assert claim.class_id == 31
        assert claim.task_enrollment_id == 41
        assert claim.subject_id == 51
        assert claim.task_binding_id == 61
        assert claim.profile_version_id == 91
        assert claim.profile_ref == "PROMIS_SYNTHETIC"
        assert claim.profile_version_number == 3
        assert claim.profile_sha256 == profile_sha256
        assert claim.response_origin == "PUBLIC_OBSERVED"
        assert _job_lease_matches_persisted_claim(generated.job, claim)
        assert _task_scope_matches_persisted_claim(generated.task_scope, claim)
        persisted = database.get(SchoolResearchEducationJob, 1)
        assert persisted.status == "HELD"
        assert persisted.lease_owner is None
        assert persisted.lease_token is None
    finally:
        database.close()
        engine.dispose()


@pytest.mark.parametrize(
    ("after_job_ref", "replayed", "membership_changed", "cursor_rejected", "scope_failure"),
    [
        (None, False, False, False, False),
        ("REJ_" + "b" * 64, False, False, False, False),
        (None, True, False, False, False),
        (None, True, True, False, False),
        ("REJ_" + "b" * 64, False, False, True, False),
        (None, False, False, False, True),
    ],
)
async def test_batch_queue_selects_and_authorizes_each_session_in_one_unit_of_work(
    monkeypatch,
    after_job_ref,
    replayed,
    membership_changed,
    cursor_rejected,
    scope_failure,
):
    from datetime import UTC, datetime

    from sqlalchemy import select
    from database_layer import models
    from smhai_backend.domains.models import BackendRole
    from .test_school_research_programme_candidates_service import actor

    adapter = _adapter(expected_source_manifest_sha256="c" * 64)
    adapter.study_use_policy = _policy()
    adapter.study_use_policy_sha256 = "a" * 64
    adapter.configure_generation(enabled=True, processor_policy_sha256="3" * 64)
    adapter._db_models = models
    monkeypatch.setattr(adapter, "_select", select, raising=False)
    now = datetime(2026, 10, 15, tzinfo=UTC)
    monkeypatch.setattr(adapter, "_now", lambda: (now, now))

    rows = [
        SimpleNamespace(
            _mapping={
                "session_ref": f"RSESS_synthetic_{index}",
                "completed_at": now,
                "session_id": index,
            }
        )
        for index in (1, 2, 3)
    ]

    class _Result:
        def __init__(self, result_rows, *, reject_cursor=False):
            self.result_rows = result_rows
            self.reject_cursor = reject_cursor

        def all(self):
            return self.result_rows

        def first(self):
            return None if self.reject_cursor else self.result_rows[0] if self.result_rows else None

    class _Session:
        def __init__(self):
            self.calls = 0

        async def execute(self, _statement):
            self.calls += 1
            if after_job_ref is not None and self.calls == 1:
                params = set(_statement.compile().params.values())
                assert {
                    17,
                    29,
                    31,
                    37,
                    41,
                    "PROMIS_SYNTHETIC",
                    "a" * 64,
                    "PUBLIC_OBSERVED",
                    "EDUCATION_SUPPORT",
                    "RESEARCH_STAFF_PROGRAMME_POLICY_V1",
                    "3" * 64,
                } <= params
                return _Result(rows[:1], reject_cursor=cursor_rejected)
            return _Result(rows[1:3] if after_job_ref is not None else rows[:2])

    class _Jobs:
        def __init__(self):
            self.calls = []

        async def enqueue_completed_session(self, **values):
            self.calls.append(values)
            job_number = len(self.calls) + (2 if membership_changed else 0)
            return SimpleNamespace(
                job_ref=f"REJ_{job_number:064x}", status="QUEUED"
            )

    class _Uow:
        def __init__(self):
            self.session = _Session()
            self.research_education_jobs = _Jobs()
            self.entered = 0
            self.committed = False
            self.rolled_back = False

        async def __aenter__(self):
            self.entered += 1
            return self

        async def __aexit__(self, exc_type, _exc, _tb):
            self.committed = exc_type is None
            self.rolled_back = exc_type is not None
            return False

    uow = _Uow()
    monkeypatch.setattr(adapter, "_uow", lambda: uow, raising=False)
    monkeypatch.setattr(
        adapter,
        "_require_actor",
        lambda *args, **kwargs: _async((17, 23)),
        raising=False,
    )
    task = SimpleNamespace(id=29, class_id=31)
    binding = SimpleNamespace(
        binding_id=37,
        profile_version_id=41,
        profile_ref="PROMIS_SYNTHETIC",
        profile_version_number=1,
        profile_sha256="a" * 64,
    )
    monkeypatch.setattr(
        adapter,
        "_active_task_for_actor",
        lambda *args, **kwargs: _async((task, binding, None, None)),
        raising=False,
    )
    authorized = []
    def session_scope(session_id):
        return SimpleNamespace(
            school_id=17,
            research_session_id=session_id,
            task_id=29,
            class_id=31,
            task_enrollment_id=43,
            subject_id=47,
            task_binding_id=37,
            profile_version_id=41,
            profile_ref="PROMIS_SYNTHETIC",
            profile_version_number=1,
            profile_sha256="a" * 64,
            response_origin="PUBLIC_OBSERVED",
        )

    async def current_scope(_uow, _actor, _task, *, session_ref, at, lock):
        assert at == now
        assert lock is True
        authorized.append(session_ref)
        if scope_failure and session_ref == "RSESS_synthetic_2":
            raise BackendError(ErrorCode.FORBIDDEN, detail="access denied")
        session_id = int(session_ref.rsplit("_", 1)[1])
        return session_scope(session_id), None, None, None, None

    monkeypatch.setattr(adapter, "_current_scope", current_scope, raising=False)
    monkeypatch.setattr(
        adapter,
        "_school_idempotency_begin",
        lambda *_args: _async(SimpleNamespace(replayed=replayed)),
        raising=False,
    )
    completed = []

    async def complete(_uow, _claim, **values):
        completed.append(values)

    monkeypatch.setattr(adapter, "_school_idempotency_complete", complete, raising=False)
    audits = []

    async def audit(_uow, **values):
        audits.append(values)

    monkeypatch.setattr(adapter, "_audit_research", audit, raising=False)
    request_fingerprint = (
        f"17:29:37:2:{after_job_ref or 'FIRST'}:{'3' * 64}:"
        f"REJ_{1:064x}:REJ_{2:064x}"
    )
    expected_batch_ref = "REJBATCH_" + hashlib.sha256(
        request_fingerprint.encode("ascii")
    ).hexdigest()
    monkeypatch.setattr(
        adapter,
        "_receipt_resource",
        lambda *_args: _async(expected_batch_ref),
        raising=False,
    )

    queue = adapter.school_research_programme_generation_queue_batch
    if cursor_rejected or scope_failure or membership_changed:
        with pytest.raises(BackendError) as raised:
            await queue(
                actor(BackendRole.PSYCHOLOGICAL_SPECIALIST),
                "TASK_synthetic",
                limit=2,
                after_job_ref=after_job_ref,
                idempotency=("batch-key", "request-hash", "scope-hash"),
                trace_id="TRACE_batch",
            )
        assert raised.value.code is (
            ErrorCode.RESOURCE_NOT_FOUND
            if cursor_rejected
            else ErrorCode.FORBIDDEN
            if scope_failure
            else ErrorCode.WORKFLOW_CONFLICT
        )
        assert uow.entered == 1 and not uow.committed and uow.rolled_back
        assert len(completed) == 0 and len(audits) == 0
        if cursor_rejected:
            assert len(uow.research_education_jobs.calls) == 0
        elif scope_failure:
            assert len(uow.research_education_jobs.calls) == 1
        else:
            assert len(uow.research_education_jobs.calls) == 2
        return

    result = await queue(
        actor(BackendRole.PSYCHOLOGICAL_SPECIALIST),
        "TASK_synthetic",
        limit=2,
        after_job_ref=after_job_ref,
        idempotency=("batch-key", "request-hash", "scope-hash"),
        trace_id="TRACE_batch",
    )
    assert result["job_count"] == 2
    assert result["job_refs"] == [f"REJ_{1:064x}", f"REJ_{2:064x}"]
    assert result["next_cursor"] == result["job_refs"][-1]
    assert result["student_feedback_eligible"] is False
    assert uow.entered == 1 and uow.committed and not uow.rolled_back
    expected_authorized = ["RSESS_synthetic_1", "RSESS_synthetic_2"]
    if after_job_ref is not None:
        expected_authorized = [
            "RSESS_synthetic_1",
            "RSESS_synthetic_2",
            "RSESS_synthetic_3",
        ]
    assert authorized == expected_authorized
    assert len(uow.research_education_jobs.calls) == 2
    assert all(
        call["policy_version"] == "RESEARCH_STAFF_PROGRAMME_POLICY_V1"
        and call["policy_hash"] == "3" * 64
        and call["response_origin"] == "PUBLIC_OBSERVED"
        for call in uow.research_education_jobs.calls
    )
    assert result["batch_ref"] == expected_batch_ref
    assert len(audits) == (0 if replayed else 2)
    assert len(completed) == (0 if replayed else 1)
    if not replayed:
        assert completed[0]["resource_type"] == "school_research_programme_generation_batch"


def _async(value):
    async def resolve(*_args, **_kwargs):
        return value

    return resolve()


async def test_generation_job_list_uses_one_uow_and_exact_staff_research_scope(monkeypatch):
    from datetime import UTC, datetime

    from sqlalchemy import select
    from database_layer import enums
    from database_layer import models
    from smhai_backend.domains.models import BackendRole
    from .test_school_research_programme_candidates_service import actor

    adapter = _adapter(expected_source_manifest_sha256="c" * 64)
    adapter.study_use_policy = _policy()
    adapter.study_use_policy_sha256 = "a" * 64
    adapter.configure_generation(enabled=True, processor_policy_sha256="3" * 64)
    adapter._db_models = models
    adapter._db_enums = enums
    monkeypatch.setattr(adapter, "_select", select, raising=False)
    now = datetime(2026, 10, 15, tzinfo=UTC)
    monkeypatch.setattr(adapter, "_now", lambda: (now, now))

    task = SimpleNamespace(id=29, class_id=31)
    binding = SimpleNamespace(
        binding_id=37,
        cohort_id=43,
        profile_version_id=41,
        profile_ref="PROMIS_SYNTHETIC",
        profile_version_number=1,
        profile_sha256="a" * 64,
        response_origin="PUBLIC_OBSERVED",
    )

    class _Rows:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _Session:
        def __init__(self):
            self.statements = []

        async def scalar(self, statement):
            self.statements.append(statement)
            return 3

        async def execute(self, statement):
            self.statements.append(statement)
            if len(self.statements) == 2:
                return _Rows([
                    SimpleNamespace(
                        _mapping={
                            "job_ref": "REJ_" + "b" * 64,
                            "status": "RETRY",
                            "attempt_count": 2,
                            "updated_at": now,
                            "last_error_code": "UPSTREAM_TIMEOUT",
                        }
                    )
                ])
            return _Rows([("RETRY", 1), ("QUEUED", 2)])

    class _Uow:
        def __init__(self):
            self.session = _Session()
            self.entered = 0
            self.exited = 0

        async def __aenter__(self):
            self.entered += 1
            return self

        async def __aexit__(self, exc_type, _exc, _tb):
            self.exited += 1
            return False

    uow = _Uow()
    monkeypatch.setattr(adapter, "_uow", lambda: uow, raising=False)

    async def require_actor(_uow, _actor, _role, _at):
        return 13, 23

    async def active_task(_uow, _actor, _task_ref, *, role_id, at):
        assert role_id == 23 and at == now
        return task, binding, SimpleNamespace(), SimpleNamespace()

    monkeypatch.setattr(adapter, "_require_actor", require_actor)
    monkeypatch.setattr(adapter, "_active_task_for_actor", active_task)

    result = await adapter.school_research_programme_generation_job_list(
        actor(BackendRole.PSYCHOLOGICAL_SPECIALIST), "TASK_demo", offset=0, limit=25
    )

    assert result["total"] == 3
    assert result["status_counts"]["RETRY"] == 1
    assert result["status_counts"]["QUEUED"] == 2
    assert result["items"] == [
        {
            "job_ref": "REJ_" + "b" * 64,
            "status": "RETRY",
            "attempt_count": 2,
            "updated_at": now,
            "last_error_code": "UPSTREAM_TIMEOUT",
        }
    ]
    assert set(result["items"][0]) == {
        "job_ref", "status", "attempt_count", "updated_at", "last_error_code"
    }
    assert result["student_feedback_eligible"] is False
    assert uow.entered == uow.exited == 1
    assert len(uow.session.statements) == 3
    parameter_sets = [set(statement.compile().params.values()) for statement in uow.session.statements]
    assert all("RESEARCH_STAFF_PROGRAMME_POLICY_V1" in values for values in parameter_sets)
    assert all("RESEARCH_SIMULATION" in values for values in parameter_sets)
    assert all("PUBLIC_OBSERVED" in values for values in parameter_sets)
    assert all(adapter.study_use_policy.study_ref in values for values in parameter_sets)
    selected = {str(column) for column in uow.session.statements[1].selected_columns}
    assert all(name in " ".join(selected) for name in ("job_ref", "status", "attempt_count", "updated_at"))
    assert "subject_id" not in " ".join(selected)
    assert "session_ref" not in " ".join(selected)
