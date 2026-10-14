from __future__ import annotations

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
