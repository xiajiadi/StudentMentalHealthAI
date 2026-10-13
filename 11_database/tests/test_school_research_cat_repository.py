from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from database_layer.crypto import (
    EncryptedPayload,
    FernetDataProtectionProvider,
    MappingKeyProvider,
)
from database_layer.models import (
    MeasurementTask,
    MembershipRole,
    School,
    SchoolClass,
    SchoolClassStudent,
    SchoolResearchProfileVersion,
    SchoolResearchSession,
    SchoolResearchTaskBinding,
    Subject,
    TaskEnrollment,
)
from database_layer.school_research_cat import (
    ResearchCatRepositoryError,
    ResearchCatRepositoryErrorCode,
    ResearchProfileMetadata,
    ResearchProfilePayload,
    ResearchSessionForResume,
    SchoolResearchCatRepository,
    map_cat_status_to_storage,
)
from database_layer.unit_of_work import SqlAlchemyUnitOfWork

_RAW_PROFILE = json.dumps(
    {
        "schema": "psynova.research-profile.v2",
        "profile_id": "research-profile-fixture-v1",
        "profile_type": "CAT_RESEARCH_PROFILE_CANDIDATE",
        "instrument_id": "SYNTHETIC_TEST_PROFILE",
        "dimension": "Synthetic research fixture dimension",
        "research_only": True,
        "publication_status": "not_approved_for_publication_or_operational_use",
        "psychological_interpretation_allowed": False,
        "model": {
            "fit_sha256": "a" * 64,
            "calibration_sha256": "b" * 64,
        },
    },
    ensure_ascii=False,
    separators=(",", ":"),
).encode("utf-8")
_PROFILE_SHA = hashlib.sha256(_RAW_PROFILE).hexdigest()
_MANIFEST_SHA = "c" * 64
_PROMIS_PROFILE_PATH = Path(
    r"D:\Dev\datasets\psynova-public-research\research-profiles\promis-pediatric-anxiety-8-item-subset-20261014-r1\profile.json"
)
_PROMIS_PROFILE_SHA = "a2720adf10496f495efe21262de0e1890650847a84aff770aa025e9da825acf3"
_PROMIS_MANIFEST_SHA = "984d395c29c26c1ce728d97790abf99d583ef47518ee6e058e067c8e8c15f524"
_PROMIS_CROSSWALK_SHA = "2176b6cbf7498d8ef912f2902a22c31cb7b229ac82d988d54567cfe615c9066c"
_PROMIS_RAW_DIMENSION = (
    "Pediatric anxiety item-response research dimension; no psychological interpretation"
)
_PROMIS_STORAGE_DIMENSION = "PROMIS_PEDIATRIC_ANXIETY_RESEARCH"
_CONFIG = {"model": "GRM", "estimator": "EAP", "min_items": 1, "max_items": 1}
_CONFIG_JSON = json.dumps(_CONFIG, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
_CONFIG_SHA = hashlib.sha256(_CONFIG_JSON.encode("utf-8")).hexdigest()


class _ScalarResult:
    def __init__(self, rows):
        self.rows = rows

    def one_or_none(self):
        assert len(self.rows) <= 1
        return self.rows[0] if self.rows else None


class _ExecuteResult:
    rowcount = 1


class _FakeSession:
    def __init__(self):
        now = datetime(2026, 10, 14, tzinfo=UTC).replace(tzinfo=None)
        self.rows = {
            School: [SimpleNamespace(id=3, status="ACTIVE", data_origin="SYNTHETIC")],
            MembershipRole: [SimpleNamespace(id=7, school_id=3, status="ACTIVE")],
            SchoolClass: [SimpleNamespace(id=11, school_id=3, status="ACTIVE")],
            MeasurementTask: [
                SimpleNamespace(
                    id=13,
                    school_id=3,
                    class_id=11,
                    status="PUBLISHED",
                    cat_binding_mode="RESEARCH_PROFILE",
                )
            ],
            TaskEnrollment: [
                SimpleNamespace(
                    id=17,
                    school_id=3,
                    task_id=13,
                    class_id=11,
                    class_student_id=19,
                    subject_id=23,
                    status="ACTIVE",
                )
            ],
            SchoolClassStudent: [
                SimpleNamespace(
                    id=19,
                    school_id=3,
                    class_id=11,
                    subject_id=23,
                    status="ACTIVE",
                )
            ],
            Subject: [
                SimpleNamespace(
                    id=23,
                    school_id=3,
                    status="ACTIVE",
                    data_origin="SYNTHETIC",
                )
            ],
            SchoolResearchProfileVersion: [],
            SchoolResearchTaskBinding: [],
            SchoolResearchSession: [],
        }
        self.added = []
        self._next_id = 100
        self._now = now
        self.executed = []
        self.locked_models = []
        self.held_lock_rows = set()
        self.commits = 0
        self.rollbacks = 0

    async def scalars(self, statement):
        model = statement.column_descriptions[0]["entity"]
        rows = self.rows.get(model, [])
        if statement._for_update_arg is not None:
            for row in rows:
                identity = (model, getattr(row, "id", id(row)))
                if identity not in self.held_lock_rows:
                    self.held_lock_rows.add(identity)
                    self.locked_models.append(model)
        return _ScalarResult(rows)

    def reset_lock_tracking(self):
        self.locked_models.clear()
        self.held_lock_rows.clear()

    async def execute(self, statement):
        self.executed.append(statement)
        return _ExecuteResult()

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        while self.added:
            row = self.added.pop(0)
            row.id = self._next_id
            self._next_id += 1
            row.public_id = f"synthetic-public-{row.id}"
            row.created_at = self._now
            row.updated_at = self._now
            self.rows.setdefault(type(row), []).append(row)

    @asynccontextmanager
    async def begin_nested(self):
        yield self

    async def begin(self):
        return None

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def close(self):
        return None


def _profile():
    return SimpleNamespace(
        profile_id="research-profile-fixture-v1",
        profile_type="CAT_RESEARCH_PROFILE_CANDIDATE",
        instrument_id="SYNTHETIC_TEST_PROFILE",
        dimension="Synthetic research fixture dimension",
        file_sha256=_PROFILE_SHA,
        manifest_sha256=None,
        raw_profile_bytes=_RAW_PROFILE,
        research_only=True,
        publication_status="not_approved_for_publication_or_operational_use",
        psychological_interpretation_allowed=False,
        human_curated=False,
    )


def _promis_profile():
    if not _PROMIS_PROFILE_PATH.is_file():
        pytest.skip("pinned public PROMIS v3 profile is not present in this environment")
    raw = _PROMIS_PROFILE_PATH.read_bytes()
    manifest_raw = _PROMIS_PROFILE_PATH.with_name("manifest.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == _PROMIS_PROFILE_SHA
    assert hashlib.sha256(manifest_raw).hexdigest() == _PROMIS_MANIFEST_SHA
    document = json.loads(raw.decode("utf-8"))
    return SimpleNamespace(
        profile_id=document["profile_id"],
        profile_type="CAT_RESEARCH_PROFILE_CANDIDATE",
        instrument_id=document["instrument_id"],
        dimension=_PROMIS_RAW_DIMENSION,
        file_sha256=_PROMIS_PROFILE_SHA,
        manifest_sha256=_PROMIS_MANIFEST_SHA,
        raw_profile_bytes=raw,
        research_only=True,
        publication_status="not_approved",
        psychological_interpretation_allowed=False,
        human_curated=False,
    )


def _repo(session=None):
    session = session or _FakeSession()
    keys = MappingKeyProvider({"test-v1": Fernet.generate_key()}, "test-v1")
    protection = FernetDataProtectionProvider(keys)
    return SchoolResearchCatRepository(session, protection), session, protection


def _assert_research_lock_order(session):
    ranks = {
        SchoolResearchProfileVersion: 0,
        MeasurementTask: 1,
        SchoolResearchTaskBinding: 2,
        TaskEnrollment: 3,
        SchoolClassStudent: 4,
        Subject: 5,
        SchoolResearchSession: 6,
    }
    observed = [ranks[model] for model in session.locked_models]
    assert observed == sorted(observed), [model.__name__ for model in session.locked_models]


def _snapshot(session_ref="research-session-fixture-v1", *, status="ACTIVE", answers=()):
    payload = {
        "schema": "psynova.research-cat-snapshot.v1",
        "session_id": session_ref,
        "profile_id": "research-profile-fixture-v1",
        "profile_sha256": _PROFILE_SHA,
        "config_version": "config-fixture-v1",
        "config_sha256": _CONFIG_SHA,
        "step": len(answers),
        "status": status,
        "stop_reason": None if status == "ACTIVE" else "max_items_reached",
        "pending_item_id": None,
        "answers": list(answers),
    }
    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()
    return {
        "payload": payload,
        "payload_sha256": hashlib.sha256(encoded).hexdigest(),
        "signature": "unit-test-signature",
    }


async def _install_research_records(repo, session):
    profile_meta = await repo.create_profile_version(
        school_id=3,
        version_number=1,
        source_population_scope="SYNTHETIC_FIXTURE",
        profile=_profile(),
        expected_profile_sha256=_PROFILE_SHA,
        expected_manifest_sha256=_MANIFEST_SHA,
        rights_status="VERIFIED",
        execution_status="SIMULATION_ENABLED",
        creator_membership_role_id=7,
    )
    profile_row = session.rows[SchoolResearchProfileVersion][0]
    binding_meta = await repo.create_task_binding(
        school_id=3,
        task_id=13,
        class_id=11,
        profile_version_id=profile_meta.profile_version_id,
        profile_ref=profile_meta.profile_ref,
        profile_version_number=1,
        expected_profile_sha256=_PROFILE_SHA,
        response_origin="MODEL_GENERATED",
        config_version="config-fixture-v1",
        config_payload=_CONFIG,
        expected_config_sha256=_CONFIG_SHA,
        creator_membership_role_id=7,
    )
    return profile_meta, profile_row, binding_meta


@pytest.mark.asyncio
async def test_profile_bytes_are_independently_hash_checked_and_encrypted_verbatim():
    repo, session, protection = _repo()
    metadata = await repo.create_profile_version(
        school_id=3,
        version_number=1,
        source_population_scope="SYNTHETIC_FIXTURE",
        profile=_profile(),
        expected_profile_sha256=_PROFILE_SHA,
        expected_manifest_sha256=_MANIFEST_SHA,
        rights_status="VERIFIED",
        execution_status="SIMULATION_ENABLED",
        creator_membership_role_id=7,
    )

    row = session.rows[SchoolResearchProfileVersion][0]
    clear = protection.decrypt_json(
        EncryptedPayload(
            ciphertext=row.payload_ciphertext,
            key_version=row.key_version,
            cipher_format_version=row.cipher_format_version,
            payload_schema_version=row.payload_schema_version,
        )
    )
    assert base64_decode(clear["raw_profile_utf8_b64"]) == _RAW_PROFILE
    loaded = await repo.load_profile_version(
        school_id=3,
        profile_ref="research-profile-fixture-v1",
        version_number=1,
        expected_profile_sha256=_PROFILE_SHA,
        expected_manifest_sha256=_MANIFEST_SHA,
    )
    assert isinstance(metadata, ResearchProfileMetadata)
    assert isinstance(loaded, ResearchProfilePayload)
    assert loaded.raw_profile_bytes == _RAW_PROFILE
    assert metadata.parameter_origin == "LOCAL_RESEARCH_FIT"
    assert metadata.fit_sha256 == "a" * 64
    assert metadata.calibration_sha256 == "b" * 64
    assert metadata.published_parameter_crosswalk_sha256 is None
    assert session.commits == session.rollbacks == 0

    with pytest.raises(ResearchCatRepositoryError) as caught:
        await repo.create_profile_version(
            school_id=3,
            version_number=2,
            source_population_scope="SYNTHETIC_FIXTURE",
            profile=_profile(),
            expected_profile_sha256="d" * 64,
            expected_manifest_sha256=_MANIFEST_SHA,
            rights_status="VERIFIED",
            execution_status="SIMULATION_ENABLED",
            creator_membership_role_id=7,
        )
    assert caught.value.code is ResearchCatRepositoryErrorCode.PROFILE_HASH_MISMATCH


@pytest.mark.asyncio
async def test_profile_load_rejects_tampered_database_fit_projection():
    repo, session, _protection = _repo()
    await repo.create_profile_version(
        school_id=3,
        version_number=1,
        source_population_scope="SYNTHETIC_FIXTURE",
        profile=_profile(),
        expected_profile_sha256=_PROFILE_SHA,
        expected_manifest_sha256=_MANIFEST_SHA,
        rights_status="VERIFIED",
        execution_status="SIMULATION_ENABLED",
        creator_membership_role_id=7,
    )
    session.rows[SchoolResearchProfileVersion][0].fit_sha256 = "d" * 64
    with pytest.raises(ResearchCatRepositoryError) as caught:
        await repo.load_profile_version(
            school_id=3,
            profile_ref="research-profile-fixture-v1",
            version_number=1,
            expected_profile_sha256=_PROFILE_SHA,
            expected_manifest_sha256=_MANIFEST_SHA,
        )
    assert caught.value.code is ResearchCatRepositoryErrorCode.PROFILE_HASH_MISMATCH


@pytest.mark.asyncio
async def test_profile_creation_rejects_raw_human_curated_true():
    repo, session, _protection = _repo()
    document = json.loads(_RAW_PROFILE)
    document["human_curated"] = True
    raw = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    profile = _profile()
    profile.raw_profile_bytes = raw
    profile.file_sha256 = hashlib.sha256(raw).hexdigest()

    with pytest.raises(ResearchCatRepositoryError) as caught:
        await repo.create_profile_version(
            school_id=3,
            version_number=1,
            source_population_scope="SYNTHETIC_FIXTURE",
            profile=profile,
            expected_profile_sha256=profile.file_sha256,
            expected_manifest_sha256=_MANIFEST_SHA,
            rights_status="VERIFIED",
            execution_status="SIMULATION_ENABLED",
            creator_membership_role_id=7,
        )
    assert caught.value.code is ResearchCatRepositoryErrorCode.INVALID_INPUT
    assert session.rows[SchoolResearchProfileVersion] == []


@pytest.mark.asyncio
async def test_pinned_promis_v3_maps_only_negative_safe_metadata_and_preserves_raw_bytes():
    repo, session, protection = _repo()
    profile = _promis_profile()
    metadata = await repo.create_profile_version(
        school_id=3,
        version_number=1,
        source_population_scope="PROMIS_US_GENPOP_CHILD_SELF_REPORT_8_17",
        profile=profile,
        expected_profile_sha256=_PROMIS_PROFILE_SHA,
        expected_manifest_sha256=_PROMIS_MANIFEST_SHA,
        rights_status="PENDING",
        execution_status="CANDIDATE_RESEARCH_ONLY",
        creator_membership_role_id=7,
    )

    row = session.rows[SchoolResearchProfileVersion][0]
    assert metadata.profile_ref == "promis-pediatric-anxiety-8-item-subset-20261014-r1"
    assert metadata.instrument_id == "PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET"
    assert metadata.dimension == _PROMIS_STORAGE_DIMENSION
    assert metadata.publication_status == "not_approved_for_publication_or_operational_use"
    assert metadata.parameter_origin == "PUBLISHED_ROUNDED_REFERENCE"
    assert metadata.fit_sha256 is None
    assert metadata.calibration_sha256 is None
    assert metadata.published_parameter_crosswalk_sha256 == _PROMIS_CROSSWALK_SHA
    assert metadata.execution_status == "CANDIDATE_RESEARCH_ONLY"
    assert row.dimension == _PROMIS_STORAGE_DIMENSION

    envelope = protection.decrypt_json(
        EncryptedPayload(
            ciphertext=row.payload_ciphertext,
            key_version=row.key_version,
            cipher_format_version=row.cipher_format_version,
            payload_schema_version=row.payload_schema_version,
        )
    )
    assert base64_decode(envelope["raw_profile_utf8_b64"]) == profile.raw_profile_bytes

    loaded = await repo.load_profile_version(
        school_id=3,
        profile_ref=profile.profile_id,
        version_number=1,
        expected_profile_sha256=_PROMIS_PROFILE_SHA,
        expected_manifest_sha256=_PROMIS_MANIFEST_SHA,
    )
    assert loaded.raw_profile_bytes == profile.raw_profile_bytes
    assert loaded.metadata == metadata


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("publication_status", "approved"),
        ("human_curated", True),
        ("psychological_interpretation_allowed", True),
        ("profile_type", "research_only_candidate"),
    ],
)
async def test_pinned_promis_v3_rejects_contradictory_validated_object_flags(field, bad_value):
    repo, session, _protection = _repo()
    profile = _promis_profile()
    setattr(profile, field, bad_value)

    with pytest.raises(ResearchCatRepositoryError) as caught:
        await repo.create_profile_version(
            school_id=3,
            version_number=1,
            source_population_scope="PROMIS_US_GENPOP_CHILD_SELF_REPORT_8_17",
            profile=profile,
            expected_profile_sha256=_PROMIS_PROFILE_SHA,
            expected_manifest_sha256=_PROMIS_MANIFEST_SHA,
            rights_status="PENDING",
            execution_status="CANDIDATE_RESEARCH_ONLY",
            creator_membership_role_id=7,
        )
    assert caught.value.code is ResearchCatRepositoryErrorCode.INVALID_INPUT
    assert session.rows[SchoolResearchProfileVersion] == []


@pytest.mark.asyncio
async def test_pinned_promis_v3_requires_independent_expected_manifest_pin():
    repo, session, _protection = _repo()
    profile = _promis_profile()

    with pytest.raises(ResearchCatRepositoryError) as caught:
        await repo.create_profile_version(
            school_id=3,
            version_number=1,
            source_population_scope="PROMIS_US_GENPOP_CHILD_SELF_REPORT_8_17",
            profile=profile,
            expected_profile_sha256=_PROMIS_PROFILE_SHA,
            expected_manifest_sha256="f" * 64,
            rights_status="PENDING",
            execution_status="CANDIDATE_RESEARCH_ONLY",
            creator_membership_role_id=7,
        )
    assert caught.value.code is ResearchCatRepositoryErrorCode.PROFILE_HASH_MISMATCH
    assert session.rows[SchoolResearchProfileVersion] == []


@pytest.mark.asyncio
async def test_pinned_promis_v3_rejects_unrelated_population_projection():
    repo, session, _protection = _repo()
    profile = _promis_profile()

    with pytest.raises(ResearchCatRepositoryError) as caught:
        await repo.create_profile_version(
            school_id=3,
            version_number=1,
            source_population_scope="CN_HIGH_SCHOOL_NORM",
            profile=profile,
            expected_profile_sha256=_PROMIS_PROFILE_SHA,
            expected_manifest_sha256=_PROMIS_MANIFEST_SHA,
            rights_status="PENDING",
            execution_status="CANDIDATE_RESEARCH_ONLY",
            creator_membership_role_id=7,
        )
    assert caught.value.code is ResearchCatRepositoryErrorCode.INVALID_INPUT
    assert session.rows[SchoolResearchProfileVersion] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.__setitem__("publication_status", "approved"),
        lambda d: d.__setitem__("human_curated", True),
        lambda d: d["model"].__setitem__("fit_sha256", "a" * 64),
        lambda d: d["model"].__setitem__("calibration_sha256", "b" * 64),
        lambda d: d["provenance"].__setitem__("parameter_crosswalk_sha256", "c" * 64),
        lambda d: d.__setitem__("instrument_family", "UNRELATED_FAMILY"),
    ],
)
async def test_pinned_promis_v3_rejects_mutated_raw_profile_even_with_recomputed_hash(mutation):
    repo, session, _protection = _repo()
    profile = _promis_profile()
    document = json.loads(profile.raw_profile_bytes)
    mutation(document)
    profile.raw_profile_bytes = json.dumps(
        document, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    profile.file_sha256 = hashlib.sha256(profile.raw_profile_bytes).hexdigest()

    with pytest.raises(ResearchCatRepositoryError) as caught:
        await repo.create_profile_version(
            school_id=3,
            version_number=1,
            source_population_scope="PROMIS_US_GENPOP_CHILD_SELF_REPORT_8_17",
            profile=profile,
            expected_profile_sha256=profile.file_sha256,
            expected_manifest_sha256=_PROMIS_MANIFEST_SHA,
            rights_status="PENDING",
            execution_status="CANDIDATE_RESEARCH_ONLY",
            creator_membership_role_id=7,
        )
    assert caught.value.code is ResearchCatRepositoryErrorCode.PROFILE_HASH_MISMATCH
    assert session.rows[SchoolResearchProfileVersion] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("parameter_origin", "LOCAL_RESEARCH_FIT"),
        ("published_parameter_crosswalk_sha256", "c" * 64),
        ("dimension", "PROMIS_OTHER_DIMENSION"),
        ("publication_status", "approved"),
    ],
)
async def test_promis_v3_profile_load_rejects_tampered_row_provenance(field, bad_value):
    repo, session, _protection = _repo()
    profile = _promis_profile()
    await repo.create_profile_version(
        school_id=3,
        version_number=1,
        source_population_scope="PROMIS_US_GENPOP_CHILD_SELF_REPORT_8_17",
        profile=profile,
        expected_profile_sha256=_PROMIS_PROFILE_SHA,
        expected_manifest_sha256=_PROMIS_MANIFEST_SHA,
        rights_status="PENDING",
        execution_status="CANDIDATE_RESEARCH_ONLY",
        creator_membership_role_id=7,
    )
    setattr(session.rows[SchoolResearchProfileVersion][0], field, bad_value)

    with pytest.raises(ResearchCatRepositoryError) as caught:
        await repo.load_profile_version(
            school_id=3,
            profile_ref=profile.profile_id,
            version_number=1,
            expected_profile_sha256=_PROMIS_PROFILE_SHA,
            expected_manifest_sha256=_PROMIS_MANIFEST_SHA,
        )
    assert caught.value.code is ResearchCatRepositoryErrorCode.PROFILE_HASH_MISMATCH


@pytest.mark.asyncio
async def test_binding_and_session_are_exact_scoped_encrypted_and_cas_saved():
    repo, session, _protection = _repo()
    _profile_meta, profile_row, binding_meta = await _install_research_records(repo, session)
    _assert_research_lock_order(session)
    session.reset_lock_tracking()
    execution = await repo.load_active_task_binding(
        school_id=3,
        task_id=13,
        expected_profile_sha256=_PROFILE_SHA,
        expected_config_sha256=_CONFIG_SHA,
    )
    assert execution.metadata == binding_meta
    assert execution.config_json == _CONFIG_JSON
    _assert_research_lock_order(session)
    session.reset_lock_tracking()

    initial = _snapshot()
    resume = await repo.create_or_load_session(
        school_id=3,
        task_id=13,
        task_enrollment_id=17,
        subject_id=23,
        session_ref="research-session-fixture-v1",
        expected_profile_sha256=_PROFILE_SHA,
        expected_config_sha256=_CONFIG_SHA,
        signed_snapshot=initial,
    )
    assert isinstance(resume, ResearchSessionForResume)
    assert resume.metadata.status == "IN_PROGRESS"
    assert resume.metadata.state_version == 1
    assert "answers" not in resume.metadata.__dataclass_fields__
    assert json.loads(resume.signed_snapshot_json)["payload"]["answers"] == []
    _assert_research_lock_order(session)
    session.reset_lock_tracking()

    next_snapshot = _snapshot(answers=({"item_id": "fixture-item-1", "raw_value": 2},))
    saved = await repo.save_session_snapshot(
        school_id=3,
        session_ref="research-session-fixture-v1",
        expected_state_version=1,
        expected_profile_sha256=_PROFILE_SHA,
        expected_config_sha256=_CONFIG_SHA,
        signed_snapshot=next_snapshot,
    )
    assert saved.status == "IN_PROGRESS"
    assert saved.state_version == 2 and saved.items_answered == 1
    assert session.rows[SchoolResearchSession][0].snapshot_ciphertext
    assert profile_row.payload_ciphertext
    _assert_research_lock_order(session)
    session.reset_lock_tracking()
    resumed = await repo.load_session_for_resume(
        school_id=3,
        session_ref="research-session-fixture-v1",
        expected_profile_sha256=_PROFILE_SHA,
        expected_config_sha256=_CONFIG_SHA,
    )
    assert json.loads(resumed.signed_snapshot_json)["payload"]["answers"] == [
        {"item_id": "fixture-item-1", "raw_value": 2}
    ]
    _assert_research_lock_order(session)
    session.reset_lock_tracking()

    with pytest.raises(ResearchCatRepositoryError) as caught:
        await repo.save_session_snapshot(
            school_id=3,
            session_ref="research-session-fixture-v1",
            expected_state_version=1,
            expected_profile_sha256=_PROFILE_SHA,
            expected_config_sha256=_CONFIG_SHA,
            signed_snapshot=next_snapshot,
        )
    assert caught.value.code is ResearchCatRepositoryErrorCode.CONCURRENCY_CONFLICT

    rewritten_history = _snapshot(answers=({"item_id": "fixture-item-1", "raw_value": 3},))
    with pytest.raises(ResearchCatRepositoryError) as caught:
        await repo.save_session_snapshot(
            school_id=3,
            session_ref="research-session-fixture-v1",
            expected_state_version=2,
            expected_profile_sha256=_PROFILE_SHA,
            expected_config_sha256=_CONFIG_SHA,
            signed_snapshot=rewritten_history,
        )
    assert caught.value.code is ResearchCatRepositoryErrorCode.SNAPSHOT_INVALID

    # History path is lifecycle-only even though the stored snapshot has answers.
    metadata = await repo.get_session_l1_metadata(
        school_id=3, session_ref="research-session-fixture-v1"
    )
    assert metadata.items_answered == 1
    assert not hasattr(metadata, "snapshot_ciphertext")


@pytest.mark.asyncio
async def test_revoked_or_disabled_research_binding_fails_resume_and_does_not_leak_snapshot():
    repo, session, _protection = _repo()
    await _install_research_records(repo, session)
    await repo.create_or_load_session(
        school_id=3,
        task_id=13,
        task_enrollment_id=17,
        subject_id=23,
        session_ref="research-session-fixture-v1",
        expected_profile_sha256=_PROFILE_SHA,
        expected_config_sha256=_CONFIG_SHA,
        signed_snapshot=_snapshot(),
    )
    session.rows[SchoolResearchTaskBinding][0].status = "REVOKED"
    session.rows[SchoolResearchTaskBinding][0].revoked_at = datetime.now(UTC).replace(tzinfo=None)

    with pytest.raises(ResearchCatRepositoryError) as caught:
        await repo.load_session_for_resume(
            school_id=3,
            session_ref="research-session-fixture-v1",
            expected_profile_sha256=_PROFILE_SHA,
            expected_config_sha256=_CONFIG_SHA,
        )
    assert caught.value.code is ResearchCatRepositoryErrorCode.BINDING_NOT_ACTIVE
    history = await repo.get_session_l1_metadata(
        school_id=3, session_ref="research-session-fixture-v1"
    )
    assert history.items_answered == 0
    assert not hasattr(history, "signed_snapshot_json")


@pytest.mark.asyncio
async def test_research_session_rejects_non_synthetic_subject_origin():
    repo, session, _protection = _repo()
    await _install_research_records(repo, session)
    session.rows[Subject][0].data_origin = "PRODUCTION_PENDING"
    with pytest.raises(ResearchCatRepositoryError) as caught:
        await repo.create_or_load_session(
            school_id=3,
            task_id=13,
            task_enrollment_id=17,
            subject_id=23,
            session_ref="research-session-fixture-v1",
            expected_profile_sha256=_PROFILE_SHA,
            expected_config_sha256=_CONFIG_SHA,
            signed_snapshot=_snapshot(),
        )
    assert caught.value.code is ResearchCatRepositoryErrorCode.SYNTHETIC_SCOPE_REQUIRED
    assert session.rows[SchoolResearchSession] == []


@pytest.mark.asyncio
async def test_signed_snapshot_unhashable_status_returns_stable_repository_error():
    repo, _session, _protection = _repo()
    await _install_research_records(repo, _session)
    snapshot = _snapshot(status=[])

    with pytest.raises(ResearchCatRepositoryError) as caught:
        await repo.create_or_load_session(
            school_id=3,
            task_id=13,
            task_enrollment_id=17,
            subject_id=23,
            session_ref="research-session-fixture-v1",
            expected_profile_sha256=_PROFILE_SHA,
            expected_config_sha256=_CONFIG_SHA,
            signed_snapshot=snapshot,
        )
    assert caught.value.code is ResearchCatRepositoryErrorCode.SNAPSHOT_INVALID


@pytest.mark.asyncio
async def test_revoked_profile_rights_block_resume_but_l1_history_remains_available():
    repo, session, _protection = _repo()
    await _install_research_records(repo, session)
    await repo.create_or_load_session(
        school_id=3,
        task_id=13,
        task_enrollment_id=17,
        subject_id=23,
        session_ref="research-session-fixture-v1",
        expected_profile_sha256=_PROFILE_SHA,
        expected_config_sha256=_CONFIG_SHA,
        signed_snapshot=_snapshot(),
    )
    profile = session.rows[SchoolResearchProfileVersion][0]
    profile.rights_status = "REVOKED"
    profile.execution_status = "DISABLED"

    with pytest.raises(ResearchCatRepositoryError) as caught:
        await repo.load_session_for_resume(
            school_id=3,
            session_ref="research-session-fixture-v1",
            expected_profile_sha256=_PROFILE_SHA,
            expected_config_sha256=_CONFIG_SHA,
        )
    assert caught.value.code is ResearchCatRepositoryErrorCode.PROFILE_RIGHTS_REVOKED
    assert (
        await repo.get_session_l1_metadata(school_id=3, session_ref="research-session-fixture-v1")
    ).items_answered == 0


@pytest.mark.asyncio
async def test_profile_eligibility_and_binding_revocation_take_only_their_ordered_lock():
    repo, session, _protection = _repo()
    profile_meta, _profile_row, _binding_meta = await _install_research_records(repo, session)
    session.reset_lock_tracking()

    disabled = await repo.change_profile_eligibility(
        school_id=3,
        profile_ref=profile_meta.profile_ref,
        version_number=profile_meta.version_number,
        expected_profile_sha256=_PROFILE_SHA,
        status_actor_membership_role_id=7,
        rights_status="REVOKED",
    )
    assert disabled.rights_status == "REVOKED"
    assert disabled.execution_status == "DISABLED"
    _assert_research_lock_order(session)
    assert session.locked_models == [SchoolResearchProfileVersion]

    session.reset_lock_tracking()
    revoked = await repo.revoke_task_binding(
        school_id=3,
        task_id=13,
        revoker_membership_role_id=7,
    )
    assert revoked.status == "REVOKED"
    _assert_research_lock_order(session)
    assert session.locked_models == [SchoolResearchTaskBinding]


def test_status_mapping_is_explicit_and_unknown_states_fail_closed():
    assert map_cat_status_to_storage("ACTIVE") == "IN_PROGRESS"
    assert map_cat_status_to_storage("COMPLETED") == "COMPLETED"
    assert map_cat_status_to_storage("INCOMPLETE") == "FAILED"
    assert map_cat_status_to_storage("FAILED") == "FAILED"
    with pytest.raises(ResearchCatRepositoryError) as caught:
        map_cat_status_to_storage("ABANDONED")
    assert caught.value.code is ResearchCatRepositoryErrorCode.SNAPSHOT_INVALID
    with pytest.raises(ResearchCatRepositoryError) as caught:
        map_cat_status_to_storage([])
    assert caught.value.code is ResearchCatRepositoryErrorCode.SNAPSHOT_INVALID


def base64_decode(value: str) -> bytes:
    import base64

    return base64.b64decode(value, validate=True)


@pytest.mark.asyncio
async def test_unit_of_work_wires_repository_without_owning_a_second_transaction():
    session = _FakeSession()
    protection = FernetDataProtectionProvider(
        MappingKeyProvider({"test-v1": Fernet.generate_key()}, "test-v1")
    )

    def factory():
        return session

    uow = SqlAlchemyUnitOfWork(factory, protection)
    async with uow as active:
        assert active.research_cat is not None
        assert active.research_cat.session is session
        assert active.research_cat.protection is protection
    assert session.commits == 1
    assert session.rollbacks == 0
