"""School-scoped research CAT persistence over the caller's transaction.

This repository does not perform actor authorization or verify snapshot
signatures. Backend callers must resolve the active SELF grant, account and
roster scope, then verify the signed snapshot with their trusted authenticator.
Only the immutable encrypted research envelope is persisted here.
Account rows have no synthetic-origin field in the current schema; Backend must
prove the actor from authenticated account/SELF-grant and synthetic seed scope.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .base import utc_now
from .crypto import EncryptedPayload, FernetDataProtectionProvider
from .errors import EncryptionFailure, EncryptionKeyUnavailable
from .models import (
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

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_STOP_REASON = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,63}$")
_PROFILE_ENVELOPE_SCHEMA = "school-research-profile-envelope.v1"
_CONFIG_ENVELOPE_SCHEMA = "school-research-config-envelope.v1"
_SESSION_ENVELOPE_SCHEMA = "school-research-session-envelope.v1"
_PROFILE_PAYLOAD_SCHEMA = "research-profile-envelope.v1"
_CONFIG_PAYLOAD_SCHEMA = "research-cat-config-envelope.v1"
_SESSION_PAYLOAD_SCHEMA = "research-cat-session-envelope.v1"
_RESEARCH_PURPOSE = "RESEARCH_SIMULATION"
_RESEARCH_PUBLICATION_STATUS = "not_approved_for_publication_or_operational_use"
_PROFILE_SCHEMA_V1 = "psynova.research-profile.v1"
_PROFILE_SCHEMA_V2 = "psynova.research-profile.v2"
_PROFILE_SCHEMA_V3 = "psynova.research-profile.v3"
_SNAPSHOT_SCHEMA = "psynova.research-cat-snapshot.v1"
_PROMIS_V3_PROFILE_ID = "promis-pediatric-anxiety-8-item-subset-20261014-r1"
_PROMIS_V3_PROFILE_SHA256 = "a2720adf10496f495efe21262de0e1890650847a84aff770aa025e9da825acf3"
_PROMIS_V3_MANIFEST_SHA256 = "984d395c29c26c1ce728d97790abf99d583ef47518ee6e058e067c8e8c15f524"
_PROMIS_V3_CROSSWALK_SHA256 = "2176b6cbf7498d8ef912f2902a22c31cb7b229ac82d988d54567cfe615c9066c"
_PROMIS_V3_RAW_DIMENSION = (
    "Pediatric anxiety item-response research dimension; no psychological interpretation"
)
_PROMIS_V3_STORAGE_DIMENSION = "PROMIS_PEDIATRIC_ANXIETY_RESEARCH"
_PROMIS_V3_SOURCE_POPULATION_SCOPE = "PROMIS_US_GENPOP_CHILD_SELF_REPORT_8_17"
_PROMIS_V3_RAW_PUBLICATION_STATUS = "not_approved"
_LOCAL_RESEARCH_FIT = "LOCAL_RESEARCH_FIT"
_PUBLISHED_ROUNDED_REFERENCE = "PUBLISHED_ROUNDED_REFERENCE"
_PROMIS_V3_ROOT_FIELDS = frozenset(
    {
        "schema",
        "profile_id",
        "profile_type",
        "instrument_id",
        "instrument_family",
        "dimension",
        "research_only",
        "publication_status",
        "human_curated",
        "psychological_interpretation_allowed",
        "loader_compatibility",
        "response_scale",
        "model",
        "scoring",
        "candidate_cat_config",
        "items",
        "source_data",
        "rights",
        "provenance",
        "not_approved_for",
    }
)
_PROMIS_V3_MODEL_FIELDS = frozenset(
    {
        "family",
        "parameter_origin",
        "parameter_version",
        "parameter_metric",
        "precision",
        "version_compatibility",
    }
)


class ResearchCatRepositoryErrorCode(StrEnum):
    INVALID_INPUT = "RESEARCH_INVALID_INPUT"
    PROFILE_NOT_FOUND = "RESEARCH_PROFILE_NOT_FOUND"
    PROFILE_HASH_MISMATCH = "RESEARCH_PROFILE_HASH_MISMATCH"
    PROFILE_NOT_ELIGIBLE = "RESEARCH_PROFILE_NOT_ELIGIBLE"
    PROFILE_RIGHTS_REVOKED = "RESEARCH_PROFILE_RIGHTS_REVOKED"
    TASK_NOT_FOUND = "RESEARCH_TASK_NOT_FOUND"
    TASK_MODE_MISMATCH = "RESEARCH_TASK_MODE_MISMATCH"
    SCOPE_MISMATCH = "RESEARCH_SCOPE_MISMATCH"
    SYNTHETIC_SCOPE_REQUIRED = "RESEARCH_SYNTHETIC_SCOPE_REQUIRED"
    BINDING_NOT_FOUND = "RESEARCH_BINDING_NOT_FOUND"
    BINDING_NOT_ACTIVE = "RESEARCH_BINDING_NOT_ACTIVE"
    CONFIG_HASH_MISMATCH = "RESEARCH_CONFIG_HASH_MISMATCH"
    SESSION_NOT_FOUND = "RESEARCH_SESSION_NOT_FOUND"
    SESSION_DISABLED = "RESEARCH_SESSION_DISABLED"
    SNAPSHOT_INVALID = "RESEARCH_SNAPSHOT_INVALID"
    SESSION_CONFLICT = "RESEARCH_SESSION_CONFLICT"
    CONCURRENCY_CONFLICT = "RESEARCH_CONCURRENCY_CONFLICT"
    PERSISTENCE_CONFLICT = "RESEARCH_PERSISTENCE_CONFLICT"
    CRYPTO_FAILURE = "RESEARCH_CRYPTO_FAILURE"


class ResearchCatRepositoryError(Exception):
    """Stable, content-free persistence failure."""

    def __init__(self, code: ResearchCatRepositoryErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class ResearchProfileLike(Protocol):
    """Validated CAT profile fields required by the storage boundary."""

    profile_id: str
    profile_type: str
    instrument_id: str
    dimension: str
    file_sha256: str
    manifest_sha256: str | None
    raw_profile_bytes: bytes
    research_only: bool
    publication_status: str
    psychological_interpretation_allowed: bool
    human_curated: bool


@dataclass(frozen=True, slots=True)
class ResearchProfileMetadata:
    profile_version_id: int
    school_id: int
    profile_ref: str
    version_number: int
    instrument_id: str
    dimension: str
    source_population_scope: str
    profile_sha256: str
    manifest_sha256: str
    fit_sha256: str | None
    calibration_sha256: str | None
    parameter_origin: str
    published_parameter_crosswalk_sha256: str | None
    rights_status: str
    execution_status: str
    research_only: bool
    human_curated: bool
    psychological_interpretation_allowed: bool
    publication_status: str
    created_at: datetime
    simulation_enabled_at: datetime | None
    rights_revoked_at: datetime | None
    disabled_at: datetime | None


@dataclass(frozen=True, slots=True, repr=False)
class ResearchProfilePayload:
    """Backend-only content load; do not use as a history or teacher DTO."""

    metadata: ResearchProfileMetadata
    raw_profile_bytes: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class _ProfileStorageProjection:
    profile_ref: str
    instrument_id: str
    dimension: str
    fit_sha256: str | None
    calibration_sha256: str | None
    parameter_origin: str
    published_parameter_crosswalk_sha256: str | None


@dataclass(frozen=True, slots=True)
class ResearchTaskBindingMetadata:
    binding_id: int
    school_id: int
    task_id: int
    class_id: int
    profile_version_id: int
    profile_ref: str
    profile_version_number: int
    profile_sha256: str
    response_origin: str
    status: str
    config_version: str
    config_sha256: str
    research_only: bool
    created_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True, repr=False)
class ResearchTaskBindingExecution:
    metadata: ResearchTaskBindingMetadata
    config_json: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ResearchSessionMetadata:
    session_id: int
    session_ref: str
    school_id: int
    task_id: int
    class_id: int
    task_enrollment_id: int
    subject_id: int
    task_binding_id: int
    profile_version_id: int
    profile_ref: str
    profile_version_number: int
    profile_sha256: str
    response_origin: str
    config_version: str
    config_sha256: str
    status: str
    state_version: int
    items_answered: int
    stop_reason: str | None
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True, repr=False)
class ResearchSessionForResume:
    """Backend-only signed snapshot payload; callers must verify its signature."""

    metadata: ResearchSessionMetadata
    signed_snapshot_json: str = field(repr=False)


def map_cat_status_to_storage(value: object) -> str:
    """Map the in-memory CAT states to the strict persistence enum."""

    if type(value) is not str:
        _raise(
            ResearchCatRepositoryErrorCode.SNAPSHOT_INVALID,
            "research CAT state must be a known string status",
        )
    if value == "ACTIVE":
        return "IN_PROGRESS"
    if value == "COMPLETED":
        return "COMPLETED"
    if value in {"INCOMPLETE", "FAILED"}:
        return "FAILED"
    raise ResearchCatRepositoryError(
        ResearchCatRepositoryErrorCode.SNAPSHOT_INVALID,
        "research CAT state has no persistence status mapping",
    )


class SchoolResearchCatRepository:
    """Repository using profile → task → binding → enrollment → roster/subject → session locks.

    The caller owns the transaction and actor authorization. This ordering
    keeps start, resume, save, and binding setup from taking shared row locks
    in opposite directions.
    """

    def __init__(
        self,
        session: AsyncSession,
        protection: FernetDataProtectionProvider,
    ) -> None:
        self.session = session
        self.protection = protection

    async def create_profile_version(
        self,
        *,
        school_id: int,
        version_number: int,
        source_population_scope: str,
        profile: ResearchProfileLike,
        expected_profile_sha256: str,
        expected_manifest_sha256: str,
        rights_status: str,
        execution_status: str,
        creator_membership_role_id: int,
    ) -> ResearchProfileMetadata:
        """Store exact profile bytes after checking independent registry hashes.

        Expected digests must come from a trusted server-side registry, never
        from hashing the untrusted profile document at the call site.
        """
        _positive_int(school_id, "school_id")
        _positive_int(version_number, "version_number")
        _positive_int(creator_membership_role_id, "creator_membership_role_id")
        _require_sha256(expected_profile_sha256, "expected_profile_sha256")
        _require_sha256(expected_manifest_sha256, "expected_manifest_sha256")
        source_population_scope = _require_token(
            source_population_scope, "source_population_scope", 64
        )
        rights_status, execution_status = _profile_states(rights_status, execution_status)
        projection = _validate_profile_input(
            profile,
            expected_profile_sha256,
            expected_manifest_sha256,
        )
        if (
            projection.parameter_origin == _PUBLISHED_ROUNDED_REFERENCE
            and source_population_scope != _PROMIS_V3_SOURCE_POPULATION_SCOPE
        ):
            _raise(
                ResearchCatRepositoryErrorCode.INVALID_INPUT,
                "PROMIS v3 source population projection is fixed to the pinned profile",
            )
        if rights_status == "REVOKED" and execution_status != "DISABLED":
            _raise(
                ResearchCatRepositoryErrorCode.PROFILE_NOT_ELIGIBLE,
                "revoked profile rights require disabled execution",
            )
        if execution_status == "SIMULATION_ENABLED" and rights_status != "VERIFIED":
            _raise(
                ResearchCatRepositoryErrorCode.PROFILE_NOT_ELIGIBLE,
                "simulation requires verified profile rights",
            )

        await self._require_synthetic_school(school_id)
        await self._require_active_membership_role(creator_membership_role_id, school_id)
        existing = await self._one(
            SchoolResearchProfileVersion,
            SchoolResearchProfileVersion.school_id == school_id,
            SchoolResearchProfileVersion.profile_ref == projection.profile_ref,
            SchoolResearchProfileVersion.version_number == version_number,
            lock=True,
        )
        if existing is not None:
            _raise(
                ResearchCatRepositoryErrorCode.PERSISTENCE_CONFLICT,
                "research profile version already exists",
            )

        envelope = {
            "schema": _PROFILE_ENVELOPE_SCHEMA,
            "profile_sha256": expected_profile_sha256,
            "profile_id": projection.profile_ref,
            "profile_schema": _profile_document_schema(profile.raw_profile_bytes),
            "raw_profile_utf8_b64": base64.b64encode(profile.raw_profile_bytes).decode("ascii"),
        }
        protected = self._encrypt(envelope, _PROFILE_PAYLOAD_SCHEMA)
        enabled_at = utc_now() if execution_status == "SIMULATION_ENABLED" else None
        revoked_at = utc_now() if rights_status == "REVOKED" else None
        disabled_at = utc_now() if execution_status == "DISABLED" else None
        row = SchoolResearchProfileVersion(
            school_id=school_id,
            profile_ref=projection.profile_ref,
            version_number=version_number,
            instrument_id=projection.instrument_id,
            dimension=projection.dimension,
            source_population_scope=source_population_scope,
            profile_sha256=expected_profile_sha256,
            manifest_sha256=expected_manifest_sha256,
            fit_sha256=projection.fit_sha256,
            calibration_sha256=projection.calibration_sha256,
            parameter_origin=projection.parameter_origin,
            published_parameter_crosswalk_sha256=(
                projection.published_parameter_crosswalk_sha256
            ),
            rights_status=rights_status,
            execution_status=execution_status,
            purpose=_RESEARCH_PURPOSE,
            research_only=True,
            human_curated=False,
            psychological_interpretation_allowed=False,
            publication_status=_RESEARCH_PUBLICATION_STATUS,
            payload_ciphertext=protected.ciphertext,
            cipher_format_version=protected.cipher_format_version,
            key_version=protected.key_version,
            payload_schema_version=protected.payload_schema_version,
            created_by_membership_role_id=creator_membership_role_id,
            status_changed_by_membership_role_id=creator_membership_role_id,
            simulation_enabled_at=enabled_at,
            rights_revoked_at=revoked_at,
            disabled_at=disabled_at,
        )
        await self._insert(row, "research profile version already exists")
        return _profile_metadata(row)

    async def get_profile_metadata(
        self,
        *,
        school_id: int,
        profile_ref: str,
        version_number: int,
    ) -> ResearchProfileMetadata:
        row = await self._one(
            SchoolResearchProfileVersion,
            SchoolResearchProfileVersion.school_id == school_id,
            SchoolResearchProfileVersion.profile_ref
            == _require_token(profile_ref, "profile_ref", 128),
            SchoolResearchProfileVersion.version_number
            == _positive_int(version_number, "version_number"),
        )
        if row is None:
            _raise(
                ResearchCatRepositoryErrorCode.PROFILE_NOT_FOUND,
                "research profile version was not found",
            )
        return _profile_metadata(row)

    async def load_profile_version(
        self,
        *,
        school_id: int,
        profile_ref: str,
        version_number: int,
        expected_profile_sha256: str,
        expected_manifest_sha256: str,
    ) -> ResearchProfilePayload:
        _require_sha256(expected_profile_sha256, "expected_profile_sha256")
        _require_sha256(expected_manifest_sha256, "expected_manifest_sha256")
        row = await self._one(
            SchoolResearchProfileVersion,
            SchoolResearchProfileVersion.school_id == _positive_int(school_id, "school_id"),
            SchoolResearchProfileVersion.profile_ref
            == _require_token(profile_ref, "profile_ref", 128),
            SchoolResearchProfileVersion.version_number
            == _positive_int(version_number, "version_number"),
        )
        if row is None:
            _raise(
                ResearchCatRepositoryErrorCode.PROFILE_NOT_FOUND,
                "research profile version was not found",
            )
        if (
            row.profile_sha256 != expected_profile_sha256
            or row.manifest_sha256 != expected_manifest_sha256
        ):
            _raise(
                ResearchCatRepositoryErrorCode.PROFILE_HASH_MISMATCH,
                "stored profile does not match the independently supplied registry hashes",
            )
        payload = self._decrypt(
            row.payload_ciphertext,
            row.key_version,
            row.cipher_format_version,
            row.payload_schema_version,
        )
        raw = _decode_profile_envelope(
            payload,
            expected_profile_sha256=expected_profile_sha256,
            expected_profile_ref=row.profile_ref,
        )
        _verify_profile_row_metadata(raw, row)
        return ResearchProfilePayload(_profile_metadata(row), raw)

    async def change_profile_eligibility(
        self,
        *,
        school_id: int,
        profile_ref: str,
        version_number: int,
        expected_profile_sha256: str,
        status_actor_membership_role_id: int,
        rights_status: str | None = None,
        execution_status: str | None = None,
    ) -> ResearchProfileMetadata:
        _require_sha256(expected_profile_sha256, "expected_profile_sha256")
        _positive_int(status_actor_membership_role_id, "status_actor_membership_role_id")
        await self._require_synthetic_school(school_id)
        await self._require_active_membership_role(status_actor_membership_role_id, school_id)
        row = await self._one(
            SchoolResearchProfileVersion,
            SchoolResearchProfileVersion.school_id == _positive_int(school_id, "school_id"),
            SchoolResearchProfileVersion.profile_ref
            == _require_token(profile_ref, "profile_ref", 128),
            SchoolResearchProfileVersion.version_number
            == _positive_int(version_number, "version_number"),
            lock=True,
        )
        if row is None:
            _raise(
                ResearchCatRepositoryErrorCode.PROFILE_NOT_FOUND,
                "research profile version was not found",
            )
        if row.profile_sha256 != expected_profile_sha256:
            _raise(
                ResearchCatRepositoryErrorCode.PROFILE_HASH_MISMATCH,
                "research profile version hash differs from the trusted registry",
            )
        next_rights = rights_status or row.rights_status
        next_execution = execution_status or row.execution_status
        next_rights, next_execution = _profile_states(next_rights, next_execution)
        if row.rights_status == "REVOKED" and next_rights != "REVOKED":
            _raise(
                ResearchCatRepositoryErrorCode.PROFILE_NOT_ELIGIBLE,
                "revoked profile rights cannot be restored on the same immutable version",
            )
        if next_rights == "REVOKED":
            next_execution = "DISABLED"
        if next_execution == "SIMULATION_ENABLED" and next_rights != "VERIFIED":
            _raise(
                ResearchCatRepositoryErrorCode.PROFILE_NOT_ELIGIBLE,
                "simulation requires verified profile rights",
            )
        now = utc_now()
        row.rights_status = next_rights
        row.execution_status = next_execution
        row.status_changed_by_membership_role_id = status_actor_membership_role_id
        if next_execution == "SIMULATION_ENABLED" and row.simulation_enabled_at is None:
            row.simulation_enabled_at = now
        if next_rights == "REVOKED":
            row.rights_revoked_at = row.rights_revoked_at or now
            row.disabled_at = row.disabled_at or now
        elif next_execution == "DISABLED":
            row.disabled_at = row.disabled_at or now
        await self.session.flush()
        return _profile_metadata(row)

    async def create_task_binding(
        self,
        *,
        school_id: int,
        task_id: int,
        class_id: int,
        profile_version_id: int,
        profile_ref: str,
        profile_version_number: int,
        expected_profile_sha256: str,
        response_origin: str,
        config_version: str,
        config_payload: Mapping[str, object],
        expected_config_sha256: str,
        creator_membership_role_id: int,
    ) -> ResearchTaskBindingMetadata:
        _require_sha256(expected_profile_sha256, "expected_profile_sha256")
        _require_sha256(expected_config_sha256, "expected_config_sha256")
        school_id = _positive_int(school_id, "school_id")
        task_id = _positive_int(task_id, "task_id")
        class_id = _positive_int(class_id, "class_id")
        profile_version_id = _positive_int(profile_version_id, "profile_version_id")
        profile_version_number = _positive_int(profile_version_number, "profile_version_number")
        creator_membership_role_id = _positive_int(
            creator_membership_role_id, "creator_membership_role_id"
        )
        profile_ref = _require_token(profile_ref, "profile_ref", 128)
        response_origin = _require_choice(
            response_origin, {"PUBLIC_OBSERVED", "MODEL_GENERATED"}, "response_origin"
        )
        config_version = _require_token(config_version, "config_version", 64)
        config_json = _canonical_json(config_payload)
        config_sha256 = hashlib.sha256(config_json.encode("utf-8")).hexdigest()
        if config_sha256 != expected_config_sha256:
            _raise(
                ResearchCatRepositoryErrorCode.CONFIG_HASH_MISMATCH,
                "CAT config differs from the independently supplied config hash",
            )
        await self._require_synthetic_school(school_id)
        await self._require_active_membership_role(creator_membership_role_id, school_id)
        profile = await self._one(
            SchoolResearchProfileVersion,
            SchoolResearchProfileVersion.id == profile_version_id,
            SchoolResearchProfileVersion.school_id == school_id,
            SchoolResearchProfileVersion.profile_ref == profile_ref,
            SchoolResearchProfileVersion.version_number == profile_version_number,
            SchoolResearchProfileVersion.profile_sha256 == expected_profile_sha256,
            lock=True,
        )
        if profile is None:
            _raise(
                ResearchCatRepositoryErrorCode.PROFILE_NOT_FOUND,
                "exact profile version is not present in this school scope",
            )
        _require_profile_enabled(profile)
        task = await self._one(
            MeasurementTask,
            MeasurementTask.id == task_id,
            MeasurementTask.school_id == school_id,
            MeasurementTask.class_id == class_id,
            lock=True,
        )
        if (
            task is None
            or task.status != "PUBLISHED"
            or task.school_id != school_id
            or task.class_id != class_id
        ):
            _raise(
                ResearchCatRepositoryErrorCode.TASK_NOT_FOUND,
                "published research task was not found in this school scope",
            )
        if task.cat_binding_mode != "RESEARCH_PROFILE":
            _raise(
                ResearchCatRepositoryErrorCode.TASK_MODE_MISMATCH,
                "task is not explicitly bound to the research CAT lane",
            )
        await self._require_active_class(school_id, class_id)
        existing = await self._one(
            SchoolResearchTaskBinding,
            SchoolResearchTaskBinding.task_id == task_id,
            lock=True,
        )
        if existing is not None:
            _raise(
                ResearchCatRepositoryErrorCode.PERSISTENCE_CONFLICT,
                "research task already has an immutable profile binding",
            )
        protected = self._encrypt(
            {
                "schema": _CONFIG_ENVELOPE_SCHEMA,
                "config_sha256": expected_config_sha256,
                "config_json": config_json,
            },
            _CONFIG_PAYLOAD_SCHEMA,
        )
        row = SchoolResearchTaskBinding(
            school_id=school_id,
            task_id=task_id,
            class_id=class_id,
            profile_version_id=profile_version_id,
            profile_ref=profile_ref,
            profile_version_number=profile_version_number,
            profile_sha256=expected_profile_sha256,
            response_origin=response_origin,
            status="ACTIVE",
            purpose=_RESEARCH_PURPOSE,
            research_only=True,
            config_version=config_version,
            config_sha256=expected_config_sha256,
            config_ciphertext=protected.ciphertext,
            cipher_format_version=protected.cipher_format_version,
            key_version=protected.key_version,
            payload_schema_version=protected.payload_schema_version,
            created_by_membership_role_id=creator_membership_role_id,
        )
        await self._insert(row, "research task binding already exists")
        return _binding_metadata(row)

    async def get_task_binding_metadata(
        self, *, school_id: int, task_id: int
    ) -> ResearchTaskBindingMetadata:
        row = await self._one(
            SchoolResearchTaskBinding,
            SchoolResearchTaskBinding.school_id == _positive_int(school_id, "school_id"),
            SchoolResearchTaskBinding.task_id == _positive_int(task_id, "task_id"),
        )
        if row is None:
            _raise(
                ResearchCatRepositoryErrorCode.BINDING_NOT_FOUND,
                "research task binding was not found",
            )
        return _binding_metadata(row)

    async def load_active_task_binding(
        self,
        *,
        school_id: int,
        task_id: int,
        expected_profile_sha256: str,
        expected_config_sha256: str,
    ) -> ResearchTaskBindingExecution:
        _require_sha256(expected_profile_sha256, "expected_profile_sha256")
        _require_sha256(expected_config_sha256, "expected_config_sha256")
        binding = await self._one(
            SchoolResearchTaskBinding,
            SchoolResearchTaskBinding.school_id == _positive_int(school_id, "school_id"),
            SchoolResearchTaskBinding.task_id == _positive_int(task_id, "task_id"),
        )
        if binding is None:
            _raise(
                ResearchCatRepositoryErrorCode.BINDING_NOT_FOUND,
                "research task binding was not found",
            )
        profile = await self._binding_profile(binding, lock=True)
        task = await self._one(
            MeasurementTask,
            MeasurementTask.id == binding.task_id,
            MeasurementTask.school_id == binding.school_id,
            MeasurementTask.class_id == binding.class_id,
            MeasurementTask.status == "PUBLISHED",
            MeasurementTask.cat_binding_mode == "RESEARCH_PROFILE",
            lock=True,
        )
        if (
            task is None
            or task.status != "PUBLISHED"
            or task.cat_binding_mode != "RESEARCH_PROFILE"
            or task.school_id != binding.school_id
            or task.class_id != binding.class_id
        ):
            _raise(
                ResearchCatRepositoryErrorCode.TASK_MODE_MISMATCH,
                "active research binding no longer matches a published research task",
            )
        binding = await self._lock_binding(binding)
        await self._require_synthetic_school(binding.school_id)
        await self._require_active_class(binding.school_id, binding.class_id)
        self._require_binding_enabled(binding, profile)
        if (
            binding.profile_sha256 != expected_profile_sha256
            or binding.config_sha256 != expected_config_sha256
        ):
            _raise(
                ResearchCatRepositoryErrorCode.PROFILE_HASH_MISMATCH,
                "binding profile or config hash differs from the trusted registry",
            )
        payload = self._decrypt(
            binding.config_ciphertext,
            binding.key_version,
            binding.cipher_format_version,
            binding.payload_schema_version,
        )
        config_json = _decode_config_envelope(payload, expected_config_sha256)
        return ResearchTaskBindingExecution(_binding_metadata(binding), config_json)

    async def revoke_task_binding(
        self,
        *,
        school_id: int,
        task_id: int,
        revoker_membership_role_id: int,
    ) -> ResearchTaskBindingMetadata:
        await self._require_synthetic_school(_positive_int(school_id, "school_id"))
        await self._require_active_membership_role(
            _positive_int(revoker_membership_role_id, "revoker_membership_role_id"),
            _positive_int(school_id, "school_id"),
        )
        row = await self._one(
            SchoolResearchTaskBinding,
            SchoolResearchTaskBinding.school_id == school_id,
            SchoolResearchTaskBinding.task_id == task_id,
            lock=True,
        )
        if row is None:
            _raise(
                ResearchCatRepositoryErrorCode.BINDING_NOT_FOUND,
                "research task binding was not found",
            )
        row.status = "REVOKED"
        row.revoked_at = row.revoked_at or utc_now()
        row.revoked_by_membership_role_id = revoker_membership_role_id
        await self.session.flush()
        return _binding_metadata(row)

    async def create_or_load_session(
        self,
        *,
        school_id: int,
        task_id: int,
        task_enrollment_id: int,
        subject_id: int,
        session_ref: str,
        expected_profile_sha256: str,
        expected_config_sha256: str,
        signed_snapshot: Mapping[str, object],
        trace_id: str | None = None,
        retention_due_at: datetime | None = None,
    ) -> ResearchSessionForResume:
        _require_sha256(expected_profile_sha256, "expected_profile_sha256")
        _require_sha256(expected_config_sha256, "expected_config_sha256")
        school_id = _positive_int(school_id, "school_id")
        task_id = _positive_int(task_id, "task_id")
        enrollment_id = _positive_int(task_enrollment_id, "task_enrollment_id")
        subject_id = _positive_int(subject_id, "subject_id")
        session_ref = _require_token(session_ref, "session_ref", 128)
        await self._require_synthetic_school(school_id)
        binding = await self._one(
            SchoolResearchTaskBinding,
            SchoolResearchTaskBinding.school_id == school_id,
            SchoolResearchTaskBinding.task_id == task_id,
        )
        if binding is None:
            _raise(
                ResearchCatRepositoryErrorCode.BINDING_NOT_FOUND,
                "research task profile binding is missing",
            )
        profile = await self._binding_profile(binding, lock=True)
        task = await self._one(
            MeasurementTask,
            MeasurementTask.id == task_id,
            MeasurementTask.school_id == school_id,
            MeasurementTask.class_id == binding.class_id,
            MeasurementTask.status == "PUBLISHED",
            MeasurementTask.cat_binding_mode == "RESEARCH_PROFILE",
            lock=True,
        )
        if (
            task is None
            or task.id != task_id
            or task.school_id != school_id
            or task.class_id != binding.class_id
            or task.status != "PUBLISHED"
            or task.cat_binding_mode != "RESEARCH_PROFILE"
        ):
            _raise(
                ResearchCatRepositoryErrorCode.TASK_MODE_MISMATCH,
                "published research CAT task is unavailable in this scope",
            )
        binding = await self._lock_binding(binding)
        self._require_binding_enabled(binding, profile)
        enrollment, task, class_student, subject = await self._require_session_scope(
            school_id=school_id,
            task_id=task_id,
            task_enrollment_id=enrollment_id,
            subject_id=subject_id,
            lock_task=False,
        )
        if enrollment.class_id != binding.class_id:
            _raise(
                ResearchCatRepositoryErrorCode.SCOPE_MISMATCH,
                "task enrollment does not match its research binding class",
            )
        self._require_synthetic_subject(subject, school_id)
        if (
            binding.profile_sha256 != expected_profile_sha256
            or binding.config_sha256 != expected_config_sha256
        ):
            _raise(
                ResearchCatRepositoryErrorCode.PROFILE_HASH_MISMATCH,
                "research task binding differs from the supplied profile/config registry",
            )
        snapshot_fields = _validate_signed_snapshot(
            signed_snapshot,
            session_ref=session_ref,
            profile_ref=binding.profile_ref,
            profile_sha256=binding.profile_sha256,
            config_version=binding.config_version,
            config_sha256=binding.config_sha256,
            require_active=True,
        )
        existing = await self._one(
            SchoolResearchSession,
            SchoolResearchSession.task_enrollment_id == enrollment_id,
        )
        if existing is not None:
            if not _same_session_scope(
                existing, enrollment, binding, subject
            ) or not _same_session_request(
                existing,
                session_ref=session_ref,
                config_version=binding.config_version,
                config_sha256=binding.config_sha256,
            ):
                _raise(
                    ResearchCatRepositoryErrorCode.SESSION_CONFLICT,
                    "enrollment already owns a different research CAT session",
                )
            return await self._resume_dto(existing)

        protected = self._encrypt(
            {"schema": _SESSION_ENVELOPE_SCHEMA, "signed_snapshot": dict(signed_snapshot)},
            _SESSION_PAYLOAD_SCHEMA,
        )
        now = utc_now()
        row = SchoolResearchSession(
            session_ref=session_ref,
            school_id=school_id,
            task_id=task_id,
            class_id=enrollment.class_id,
            task_enrollment_id=enrollment_id,
            subject_id=subject_id,
            task_binding_id=binding.id,
            profile_version_id=profile.id,
            profile_ref=profile.profile_ref,
            profile_version_number=profile.version_number,
            profile_sha256=profile.profile_sha256,
            response_origin=binding.response_origin,
            config_version=binding.config_version,
            config_sha256=binding.config_sha256,
            purpose=_RESEARCH_PURPOSE,
            research_only=True,
            status="IN_PROGRESS",
            state_version=1,
            items_answered=len(snapshot_fields["answers"]),
            stop_reason=None,
            snapshot_ciphertext=protected.ciphertext,
            snapshot_sha256=snapshot_fields["payload_sha256"],
            cipher_format_version=protected.cipher_format_version,
            key_version=protected.key_version,
            payload_schema_version=protected.payload_schema_version,
            started_at=now,
            trace_id=_optional_token(trace_id, "trace_id", 128),
            retention_due_at=retention_due_at,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
        except IntegrityError as exc:
            winner = await self._one(
                SchoolResearchSession,
                SchoolResearchSession.task_enrollment_id == enrollment_id,
            )
            if (
                winner is not None
                and _same_session_scope(winner, enrollment, binding, subject)
                and _same_session_request(
                    winner,
                    session_ref=session_ref,
                    config_version=binding.config_version,
                    config_sha256=binding.config_sha256,
                )
            ):
                return await self._resume_dto(winner)
            raise ResearchCatRepositoryError(
                ResearchCatRepositoryErrorCode.PERSISTENCE_CONFLICT,
                "research session could not be created in the requested scope",
            ) from exc
        return await self._resume_dto(row)

    async def load_session_for_resume(
        self,
        *,
        school_id: int,
        session_ref: str,
        expected_profile_sha256: str,
        expected_config_sha256: str,
    ) -> ResearchSessionForResume:
        _require_sha256(expected_profile_sha256, "expected_profile_sha256")
        _require_sha256(expected_config_sha256, "expected_config_sha256")
        row = await self._one(
            SchoolResearchSession,
            SchoolResearchSession.school_id == _positive_int(school_id, "school_id"),
            SchoolResearchSession.session_ref == _require_token(session_ref, "session_ref", 128),
        )
        if row is None:
            _raise(
                ResearchCatRepositoryErrorCode.SESSION_NOT_FOUND,
                "research session was not found in this school scope",
            )
        return await self._resume_dto(
            row,
            expected_profile_sha256=expected_profile_sha256,
            expected_config_sha256=expected_config_sha256,
        )

    async def save_session_snapshot(
        self,
        *,
        school_id: int,
        session_ref: str,
        expected_state_version: int,
        expected_profile_sha256: str,
        expected_config_sha256: str,
        signed_snapshot: Mapping[str, object],
    ) -> ResearchSessionMetadata:
        _positive_int(expected_state_version, "expected_state_version")
        _require_sha256(expected_profile_sha256, "expected_profile_sha256")
        _require_sha256(expected_config_sha256, "expected_config_sha256")
        row = await self._one(
            SchoolResearchSession,
            SchoolResearchSession.school_id == _positive_int(school_id, "school_id"),
            SchoolResearchSession.session_ref == _require_token(session_ref, "session_ref", 128),
        )
        if row is None:
            _raise(
                ResearchCatRepositoryErrorCode.SESSION_NOT_FOUND,
                "research session was not found in this school scope",
            )
        binding, profile = await self._session_binding_and_profile(row)
        self._require_binding_enabled(binding, profile)
        row = await self._lock_session(row)
        if row.status != "IN_PROGRESS":
            _raise(
                ResearchCatRepositoryErrorCode.SESSION_DISABLED,
                "terminal research session cannot accept a new snapshot",
            )
        if row.state_version != expected_state_version:
            _raise(
                ResearchCatRepositoryErrorCode.CONCURRENCY_CONFLICT,
                "research session state version has changed",
            )
        if (
            row.profile_sha256 != expected_profile_sha256
            or row.config_sha256 != expected_config_sha256
            or binding.config_sha256 != expected_config_sha256
        ):
            _raise(
                ResearchCatRepositoryErrorCode.PROFILE_HASH_MISMATCH,
                "session hashes differ from the trusted registry",
            )
        fields = _validate_signed_snapshot(
            signed_snapshot,
            session_ref=row.session_ref,
            profile_ref=row.profile_ref,
            profile_sha256=row.profile_sha256,
            config_version=row.config_version,
            config_sha256=row.config_sha256,
            require_active=False,
        )
        current_payload = self._decrypt(
            row.snapshot_ciphertext,
            row.key_version,
            row.cipher_format_version,
            row.payload_schema_version,
        )
        current_snapshot = _decode_session_envelope(
            current_payload,
            expected_session_ref=row.session_ref,
            expected_profile_ref=row.profile_ref,
            expected_profile_sha256=row.profile_sha256,
            expected_config_version=row.config_version,
            expected_config_sha256=row.config_sha256,
            expected_payload_sha256=row.snapshot_sha256,
            expected_items_answered=row.items_answered,
            require_active=True,
        )
        old_answers = current_snapshot["payload"]["answers"]
        new_answers = fields["answers"]
        if (
            len(new_answers) < len(old_answers)
            or new_answers[: len(old_answers)] != old_answers
            or len(new_answers) > len(old_answers) + 1
        ):
            _raise(
                ResearchCatRepositoryErrorCode.SNAPSHOT_INVALID,
                "saved CAT snapshot must preserve prior answers and add at most one response",
            )
        storage_status = map_cat_status_to_storage(fields["status"])
        if storage_status == "ABANDONED":
            _raise(
                ResearchCatRepositoryErrorCode.SNAPSHOT_INVALID,
                "CAT snapshot cannot set abandoned storage status",
            )
        protected = self._encrypt(
            {"schema": _SESSION_ENVELOPE_SCHEMA, "signed_snapshot": dict(signed_snapshot)},
            _SESSION_PAYLOAD_SCHEMA,
        )
        completed_at = utc_now() if storage_status == "COMPLETED" else None
        result = await self.session.execute(
            update(SchoolResearchSession)
            .where(
                SchoolResearchSession.id == row.id,
                SchoolResearchSession.school_id == row.school_id,
                SchoolResearchSession.state_version == expected_state_version,
                SchoolResearchSession.status == "IN_PROGRESS",
            )
            .values(
                snapshot_ciphertext=protected.ciphertext,
                snapshot_sha256=fields["payload_sha256"],
                cipher_format_version=protected.cipher_format_version,
                key_version=protected.key_version,
                payload_schema_version=protected.payload_schema_version,
                state_version=expected_state_version + 1,
                items_answered=len(fields["answers"]),
                status=storage_status,
                stop_reason=fields["stop_reason"],
                completed_at=completed_at,
                updated_at=utc_now(),
            )
            .execution_options(synchronize_session=False)
        )
        if getattr(result, "rowcount", None) != 1:
            _raise(
                ResearchCatRepositoryErrorCode.CONCURRENCY_CONFLICT,
                "research session snapshot compare-and-swap failed",
            )
        row.snapshot_ciphertext = protected.ciphertext
        row.snapshot_sha256 = fields["payload_sha256"]
        row.cipher_format_version = protected.cipher_format_version
        row.key_version = protected.key_version
        row.payload_schema_version = protected.payload_schema_version
        row.state_version = expected_state_version + 1
        row.items_answered = len(fields["answers"])
        row.status = storage_status
        row.stop_reason = fields["stop_reason"]
        row.completed_at = completed_at
        row.updated_at = utc_now()
        return _session_metadata(row)

    async def abandon_session(
        self,
        *,
        school_id: int,
        session_ref: str,
        expected_state_version: int,
        reason: str,
    ) -> ResearchSessionMetadata:
        _positive_int(expected_state_version, "expected_state_version")
        reason = _require_stop_reason(reason)
        row = await self._one(
            SchoolResearchSession,
            SchoolResearchSession.school_id == _positive_int(school_id, "school_id"),
            SchoolResearchSession.session_ref == _require_token(session_ref, "session_ref", 128),
            lock=True,
        )
        if row is None:
            _raise(
                ResearchCatRepositoryErrorCode.SESSION_NOT_FOUND,
                "research session was not found in this school scope",
            )
        if row.status != "IN_PROGRESS" or row.state_version != expected_state_version:
            _raise(
                ResearchCatRepositoryErrorCode.CONCURRENCY_CONFLICT,
                "research session is terminal or has changed",
            )
        result = await self.session.execute(
            update(SchoolResearchSession)
            .where(
                SchoolResearchSession.id == row.id,
                SchoolResearchSession.school_id == row.school_id,
                SchoolResearchSession.state_version == expected_state_version,
                SchoolResearchSession.status == "IN_PROGRESS",
            )
            .values(
                status="ABANDONED",
                stop_reason=reason,
                state_version=expected_state_version + 1,
                updated_at=utc_now(),
            )
            .execution_options(synchronize_session=False)
        )
        if getattr(result, "rowcount", None) != 1:
            _raise(
                ResearchCatRepositoryErrorCode.CONCURRENCY_CONFLICT,
                "research session abandon compare-and-swap failed",
            )
        row.status = "ABANDONED"
        row.stop_reason = reason
        row.state_version = expected_state_version + 1
        row.updated_at = utc_now()
        return _session_metadata(row)

    async def get_session_l1_metadata(
        self, *, school_id: int, session_ref: str
    ) -> ResearchSessionMetadata:
        """Return lifecycle metadata only; never return the encrypted snapshot."""

        row = await self._one(
            SchoolResearchSession,
            SchoolResearchSession.school_id == _positive_int(school_id, "school_id"),
            SchoolResearchSession.session_ref == _require_token(session_ref, "session_ref", 128),
        )
        if row is None:
            _raise(
                ResearchCatRepositoryErrorCode.SESSION_NOT_FOUND,
                "research session was not found in this school scope",
            )
        return _session_metadata(row)

    async def _resume_dto(
        self,
        row: SchoolResearchSession,
        *,
        expected_profile_sha256: str | None = None,
        expected_config_sha256: str | None = None,
    ) -> ResearchSessionForResume:
        if row.status != "IN_PROGRESS":
            _raise(
                ResearchCatRepositoryErrorCode.SESSION_DISABLED,
                "only an in-progress research session can be resumed",
            )
        binding, profile = await self._session_binding_and_profile(row)
        self._require_binding_enabled(binding, profile)
        row = await self._lock_session(row)
        if row.status != "IN_PROGRESS":
            _raise(
                ResearchCatRepositoryErrorCode.SESSION_DISABLED,
                "only an in-progress research session can be resumed",
            )
        if expected_profile_sha256 is not None and (expected_profile_sha256 != row.profile_sha256):
            _raise(
                ResearchCatRepositoryErrorCode.PROFILE_HASH_MISMATCH,
                "session profile hash differs from the trusted registry",
            )
        if expected_config_sha256 is not None and (expected_config_sha256 != row.config_sha256):
            _raise(
                ResearchCatRepositoryErrorCode.CONFIG_HASH_MISMATCH,
                "session config hash differs from the trusted registry",
            )
        payload = self._decrypt(
            row.snapshot_ciphertext,
            row.key_version,
            row.cipher_format_version,
            row.payload_schema_version,
        )
        signed_snapshot = _decode_session_envelope(
            payload,
            expected_session_ref=row.session_ref,
            expected_profile_ref=row.profile_ref,
            expected_profile_sha256=row.profile_sha256,
            expected_config_version=row.config_version,
            expected_config_sha256=row.config_sha256,
            expected_payload_sha256=row.snapshot_sha256,
            expected_items_answered=row.items_answered,
            require_active=True,
        )
        return ResearchSessionForResume(_session_metadata(row), _canonical_json(signed_snapshot))

    async def _lock_session(self, session: SchoolResearchSession) -> SchoolResearchSession:
        """Lock the session only after profile, task, binding, and enrollment."""

        row = await self._one(
            SchoolResearchSession,
            SchoolResearchSession.id == session.id,
            SchoolResearchSession.school_id == session.school_id,
            lock=True,
        )
        if row is None:
            _raise(
                ResearchCatRepositoryErrorCode.SESSION_NOT_FOUND,
                "research session disappeared while its scope was being locked",
            )
        immutable_scope = (
            "session_ref",
            "school_id",
            "task_id",
            "class_id",
            "task_enrollment_id",
            "subject_id",
            "task_binding_id",
            "profile_version_id",
            "profile_ref",
            "profile_version_number",
            "profile_sha256",
            "response_origin",
            "config_version",
            "config_sha256",
        )
        if any(getattr(row, name) != getattr(session, name) for name in immutable_scope):
            _raise(
                ResearchCatRepositoryErrorCode.SCOPE_MISMATCH,
                "research session scope changed while its locks were acquired",
            )
        return row

    async def _session_binding_and_profile(
        self, row: SchoolResearchSession
    ) -> tuple[SchoolResearchTaskBinding, SchoolResearchProfileVersion]:
        binding = await self._one(
            SchoolResearchTaskBinding,
            SchoolResearchTaskBinding.id == row.task_binding_id,
            SchoolResearchTaskBinding.school_id == row.school_id,
            SchoolResearchTaskBinding.task_id == row.task_id,
            SchoolResearchTaskBinding.class_id == row.class_id,
            SchoolResearchTaskBinding.profile_version_id == row.profile_version_id,
            SchoolResearchTaskBinding.profile_ref == row.profile_ref,
            SchoolResearchTaskBinding.profile_version_number == row.profile_version_number,
            SchoolResearchTaskBinding.profile_sha256 == row.profile_sha256,
            SchoolResearchTaskBinding.response_origin == row.response_origin,
        )
        if binding is None:
            _raise(
                ResearchCatRepositoryErrorCode.BINDING_NOT_FOUND,
                "research session binding scope is unavailable",
            )
        profile = await self._binding_profile(binding, lock=True)
        task = await self._one(
            MeasurementTask,
            MeasurementTask.id == row.task_id,
            MeasurementTask.school_id == row.school_id,
            MeasurementTask.class_id == row.class_id,
            MeasurementTask.status == "PUBLISHED",
            MeasurementTask.cat_binding_mode == "RESEARCH_PROFILE",
            lock=True,
        )
        if (
            task is None
            or task.id != row.task_id
            or task.school_id != row.school_id
            or task.class_id != row.class_id
            or task.status != "PUBLISHED"
            or task.cat_binding_mode != "RESEARCH_PROFILE"
        ):
            _raise(
                ResearchCatRepositoryErrorCode.TASK_MODE_MISMATCH,
                "published research CAT task is unavailable in this session scope",
            )
        binding = await self._lock_binding(binding)
        enrollment, _task, _class_student, subject = await self._require_session_scope(
            school_id=row.school_id,
            task_id=row.task_id,
            task_enrollment_id=row.task_enrollment_id,
            subject_id=row.subject_id,
            lock_task=False,
        )
        if (
            binding.config_version != row.config_version
            or binding.config_sha256 != row.config_sha256
            or not _same_session_scope(row, enrollment, binding, subject)
        ):
            _raise(
                ResearchCatRepositoryErrorCode.SCOPE_MISMATCH,
                "research session no longer matches its frozen binding scope",
            )
        return binding, profile

    async def _binding_profile(
        self, binding: SchoolResearchTaskBinding, *, lock: bool
    ) -> SchoolResearchProfileVersion:
        profile = await self._one(
            SchoolResearchProfileVersion,
            SchoolResearchProfileVersion.id == binding.profile_version_id,
            SchoolResearchProfileVersion.school_id == binding.school_id,
            SchoolResearchProfileVersion.profile_ref == binding.profile_ref,
            SchoolResearchProfileVersion.version_number == binding.profile_version_number,
            SchoolResearchProfileVersion.profile_sha256 == binding.profile_sha256,
            lock=lock,
        )
        if profile is None:
            _raise(
                ResearchCatRepositoryErrorCode.PROFILE_NOT_FOUND,
                "exact profile version for this binding is missing",
            )
        return profile

    async def _lock_binding(self, binding: SchoolResearchTaskBinding) -> SchoolResearchTaskBinding:
        """Lock a binding only after its profile and task locks are held."""

        row = await self._one(
            SchoolResearchTaskBinding,
            SchoolResearchTaskBinding.id == binding.id,
            SchoolResearchTaskBinding.school_id == binding.school_id,
            SchoolResearchTaskBinding.task_id == binding.task_id,
            SchoolResearchTaskBinding.class_id == binding.class_id,
            SchoolResearchTaskBinding.profile_version_id == binding.profile_version_id,
            SchoolResearchTaskBinding.profile_ref == binding.profile_ref,
            SchoolResearchTaskBinding.profile_version_number == binding.profile_version_number,
            SchoolResearchTaskBinding.profile_sha256 == binding.profile_sha256,
            SchoolResearchTaskBinding.response_origin == binding.response_origin,
            SchoolResearchTaskBinding.config_version == binding.config_version,
            SchoolResearchTaskBinding.config_sha256 == binding.config_sha256,
            lock=True,
        )
        if row is None:
            _raise(
                ResearchCatRepositoryErrorCode.BINDING_NOT_ACTIVE,
                "research task binding changed while its scope was being locked",
            )
        return row

    def _require_binding_enabled(
        self,
        binding: SchoolResearchTaskBinding,
        profile: SchoolResearchProfileVersion,
    ) -> None:
        if binding.status != "ACTIVE":
            _raise(
                ResearchCatRepositoryErrorCode.BINDING_NOT_ACTIVE,
                "revoked research task binding cannot be used",
            )
        _require_profile_enabled(profile)

    async def _require_session_scope(
        self,
        *,
        school_id: int,
        task_id: int,
        task_enrollment_id: int,
        subject_id: int,
        lock_task: bool = True,
    ) -> tuple[TaskEnrollment, MeasurementTask, SchoolClassStudent, Subject]:
        task = await self._one(
            MeasurementTask,
            MeasurementTask.id == task_id,
            MeasurementTask.school_id == school_id,
            MeasurementTask.cat_binding_mode == "RESEARCH_PROFILE",
            MeasurementTask.status == "PUBLISHED",
            lock=lock_task,
        )
        if (
            task is None
            or task.id != task_id
            or task.school_id != school_id
            or task.status != "PUBLISHED"
            or task.cat_binding_mode != "RESEARCH_PROFILE"
        ):
            _raise(
                ResearchCatRepositoryErrorCode.TASK_MODE_MISMATCH,
                "published research CAT task is unavailable in this scope",
            )
        enrollment = await self._one(
            TaskEnrollment,
            TaskEnrollment.id == task_enrollment_id,
            TaskEnrollment.task_id == task_id,
            TaskEnrollment.school_id == school_id,
            TaskEnrollment.subject_id == subject_id,
            TaskEnrollment.class_id == task.class_id,
            TaskEnrollment.status == "ACTIVE",
            lock=True,
        )
        if (
            enrollment is None
            or enrollment.id != task_enrollment_id
            or enrollment.task_id != task_id
            or enrollment.school_id != school_id
            or enrollment.subject_id != subject_id
            or enrollment.class_id != task.class_id
            or enrollment.status != "ACTIVE"
        ):
            _raise(
                ResearchCatRepositoryErrorCode.SCOPE_MISMATCH,
                "active task enrollment does not match the requested school and subject",
            )
        class_student = await self._one(
            SchoolClassStudent,
            SchoolClassStudent.id == enrollment.class_student_id,
            SchoolClassStudent.subject_id == subject_id,
            SchoolClassStudent.class_id == enrollment.class_id,
            SchoolClassStudent.school_id == school_id,
            SchoolClassStudent.status == "ACTIVE",
            lock=True,
        )
        if (
            class_student is None
            or class_student.id != enrollment.class_student_id
            or class_student.subject_id != subject_id
            or class_student.class_id != enrollment.class_id
            or class_student.school_id != school_id
            or class_student.status != "ACTIVE"
        ):
            _raise(
                ResearchCatRepositoryErrorCode.SCOPE_MISMATCH,
                "active class roster row does not match the enrollment subject",
            )
        await self._require_active_class(school_id, enrollment.class_id)
        await self._require_synthetic_school(school_id)
        subject = await self._one(
            Subject,
            Subject.id == subject_id,
            Subject.school_id == school_id,
            Subject.status == "ACTIVE",
            Subject.data_origin == "SYNTHETIC",
            lock=True,
        )
        if subject is None:
            _raise(
                ResearchCatRepositoryErrorCode.SYNTHETIC_SCOPE_REQUIRED,
                "research sessions require an active synthetic subject in a synthetic school",
            )
        self._require_synthetic_subject(subject, school_id)
        return enrollment, task, class_student, subject

    async def _require_synthetic_school(self, school_id: int) -> School:
        row = await self._one(
            School,
            School.id == _positive_int(school_id, "school_id"),
            School.status == "ACTIVE",
            School.data_origin == "SYNTHETIC",
        )
        if (
            row is None
            or row.id != school_id
            or row.status != "ACTIVE"
            or row.data_origin != "SYNTHETIC"
        ):
            _raise(
                ResearchCatRepositoryErrorCode.SYNTHETIC_SCOPE_REQUIRED,
                "research CAT requires an active synthetic school",
            )
        return row

    def _require_synthetic_subject(self, subject: Subject, school_id: int) -> None:
        if (
            subject.school_id != school_id
            or subject.status != "ACTIVE"
            or subject.data_origin != "SYNTHETIC"
        ):
            _raise(
                ResearchCatRepositoryErrorCode.SYNTHETIC_SCOPE_REQUIRED,
                "research session requires an active synthetic subject in this school",
            )

    async def _require_active_class(self, school_id: int, class_id: int) -> SchoolClass:
        row = await self._one(
            SchoolClass,
            SchoolClass.id == class_id,
            SchoolClass.school_id == school_id,
            SchoolClass.status == "ACTIVE",
        )
        if (
            row is None
            or row.id != class_id
            or row.school_id != school_id
            or row.status != "ACTIVE"
        ):
            _raise(
                ResearchCatRepositoryErrorCode.SCOPE_MISMATCH,
                "active class was not found in the synthetic school scope",
            )
        return row

    async def _require_active_membership_role(
        self, membership_role_id: int, school_id: int
    ) -> MembershipRole:
        row = await self._one(
            MembershipRole,
            MembershipRole.id == membership_role_id,
            MembershipRole.school_id == school_id,
            MembershipRole.status == "ACTIVE",
        )
        if (
            row is None
            or row.id != membership_role_id
            or row.school_id != school_id
            or row.status != "ACTIVE"
        ):
            _raise(
                ResearchCatRepositoryErrorCode.SCOPE_MISMATCH,
                "active operator membership is unavailable in this school scope",
            )
        return row

    async def _one(self, model, *conditions, lock: bool = False):
        statement = select(model).where(*conditions)
        if lock:
            statement = statement.with_for_update()
        result = await self.session.scalars(statement)
        return result.one_or_none()

    async def _insert(self, row, conflict_message: str) -> None:
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
        except IntegrityError as exc:
            raise ResearchCatRepositoryError(
                ResearchCatRepositoryErrorCode.PERSISTENCE_CONFLICT, conflict_message
            ) from exc

    def _encrypt(
        self, payload: Mapping[str, object], payload_schema_version: str
    ) -> EncryptedPayload:
        try:
            return self.protection.encrypt_json(
                payload, payload_schema_version=payload_schema_version
            )
        except (EncryptionFailure, EncryptionKeyUnavailable) as exc:
            raise ResearchCatRepositoryError(
                ResearchCatRepositoryErrorCode.CRYPTO_FAILURE,
                "research payload encryption failed",
            ) from exc

    def _decrypt(
        self,
        ciphertext: bytes,
        key_version: str,
        cipher_format_version: str,
        payload_schema_version: str,
    ) -> dict[str, object]:
        try:
            return self.protection.decrypt_json(
                EncryptedPayload(
                    ciphertext=ciphertext,
                    key_version=key_version,
                    cipher_format_version=cipher_format_version,
                    payload_schema_version=payload_schema_version,
                )
            )
        except (EncryptionFailure, EncryptionKeyUnavailable) as exc:
            raise ResearchCatRepositoryError(
                ResearchCatRepositoryErrorCode.CRYPTO_FAILURE,
                "research payload decryption failed",
            ) from exc


def _same_session_scope(row, enrollment, binding, subject) -> bool:
    return (
        row.school_id == enrollment.school_id == binding.school_id == subject.school_id
        and row.task_id == enrollment.task_id == binding.task_id
        and row.class_id == enrollment.class_id == binding.class_id
        and row.task_enrollment_id == enrollment.id
        and row.subject_id == enrollment.subject_id == subject.id
        and row.task_binding_id == binding.id
        and row.profile_version_id == binding.profile_version_id
        and row.profile_ref == binding.profile_ref
        and row.profile_version_number == binding.profile_version_number
        and row.profile_sha256 == binding.profile_sha256
        and row.response_origin == binding.response_origin
    )


def _same_session_request(
    row,
    *,
    session_ref: str,
    config_version: str,
    config_sha256: str,
) -> bool:
    return (
        row.session_ref == session_ref
        and row.config_version == config_version
        and row.config_sha256 == config_sha256
    )


def _profile_metadata(row: SchoolResearchProfileVersion) -> ResearchProfileMetadata:
    return ResearchProfileMetadata(
        profile_version_id=row.id,
        school_id=row.school_id,
        profile_ref=row.profile_ref,
        version_number=row.version_number,
        instrument_id=row.instrument_id,
        dimension=row.dimension,
        source_population_scope=row.source_population_scope,
        profile_sha256=row.profile_sha256,
        manifest_sha256=row.manifest_sha256,
        fit_sha256=row.fit_sha256,
        calibration_sha256=row.calibration_sha256,
        parameter_origin=row.parameter_origin,
        published_parameter_crosswalk_sha256=row.published_parameter_crosswalk_sha256,
        rights_status=row.rights_status,
        execution_status=row.execution_status,
        research_only=row.research_only,
        human_curated=row.human_curated,
        psychological_interpretation_allowed=row.psychological_interpretation_allowed,
        publication_status=row.publication_status,
        created_at=row.created_at,
        simulation_enabled_at=row.simulation_enabled_at,
        rights_revoked_at=row.rights_revoked_at,
        disabled_at=row.disabled_at,
    )


def _binding_metadata(row: SchoolResearchTaskBinding) -> ResearchTaskBindingMetadata:
    return ResearchTaskBindingMetadata(
        binding_id=row.id,
        school_id=row.school_id,
        task_id=row.task_id,
        class_id=row.class_id,
        profile_version_id=row.profile_version_id,
        profile_ref=row.profile_ref,
        profile_version_number=row.profile_version_number,
        profile_sha256=row.profile_sha256,
        response_origin=row.response_origin,
        status=row.status,
        config_version=row.config_version,
        config_sha256=row.config_sha256,
        research_only=row.research_only,
        created_at=row.created_at,
        revoked_at=row.revoked_at,
    )


def _session_metadata(row: SchoolResearchSession) -> ResearchSessionMetadata:
    return ResearchSessionMetadata(
        session_id=row.id,
        session_ref=row.session_ref,
        school_id=row.school_id,
        task_id=row.task_id,
        class_id=row.class_id,
        task_enrollment_id=row.task_enrollment_id,
        subject_id=row.subject_id,
        task_binding_id=row.task_binding_id,
        profile_version_id=row.profile_version_id,
        profile_ref=row.profile_ref,
        profile_version_number=row.profile_version_number,
        profile_sha256=row.profile_sha256,
        response_origin=row.response_origin,
        config_version=row.config_version,
        config_sha256=row.config_sha256,
        status=row.status,
        state_version=row.state_version,
        items_answered=row.items_answered,
        stop_reason=row.stop_reason,
        started_at=row.started_at,
        completed_at=row.completed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _validate_profile_input(
    profile: ResearchProfileLike,
    expected_profile_sha256: str,
    expected_manifest_sha256: str,
) -> _ProfileStorageProjection:
    try:
        raw = profile.raw_profile_bytes
        file_sha = profile.file_sha256
        profile_id = profile.profile_id
        instrument_id = profile.instrument_id
        dimension = profile.dimension
        manifest_sha256 = getattr(profile, "manifest_sha256", None)
        flags = (
            profile.research_only,
            profile.human_curated,
            profile.psychological_interpretation_allowed,
            profile.publication_status,
            profile.profile_type,
        )
    except AttributeError as exc:
        _raise(
            ResearchCatRepositoryErrorCode.INVALID_INPUT,
            "validated research profile is missing required immutable fields",
            cause=exc,
        )
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != expected_profile_sha256:
        _raise(
            ResearchCatRepositoryErrorCode.PROFILE_HASH_MISMATCH,
            "research profile bytes differ from the independently supplied trusted hash",
        )
    if type(file_sha) is not str or file_sha != expected_profile_sha256:
        _raise(
            ResearchCatRepositoryErrorCode.PROFILE_HASH_MISMATCH,
            "research profile object hash differs from its original source bytes",
        )
    _require_sha256(expected_manifest_sha256, "expected_manifest_sha256")
    profile_id = _require_token(profile_id, "profile_id", 128)
    document = _parse_json_object(raw)
    schema = document.get("schema")
    if schema == _PROFILE_SCHEMA_V3:
        projection = _promis_v3_storage_projection(
            document,
            profile_ref=profile_id,
            expected_profile_sha256=expected_profile_sha256,
            expected_manifest_sha256=expected_manifest_sha256,
        )
        if (
            type(instrument_id) is not str
            or instrument_id != document.get("instrument_id")
            or dimension != _PROMIS_V3_RAW_DIMENSION
            or flags[0] is not True
            or flags[1] is not False
            or flags[2] is not False
            or flags[3] != _PROMIS_V3_RAW_PUBLICATION_STATUS
            or flags[4] != "CAT_RESEARCH_PROFILE_CANDIDATE"
            or manifest_sha256 != expected_manifest_sha256
        ):
            _raise(
                ResearchCatRepositoryErrorCode.INVALID_INPUT,
                "validated PROMIS v3 object differs from its pinned source projection",
            )
        return projection

    if schema not in {_PROFILE_SCHEMA_V1, _PROFILE_SCHEMA_V2}:
        _raise(
            ResearchCatRepositoryErrorCode.INVALID_INPUT,
            "research profile schema is unsupported by this persistence slice",
        )
    if (
        type(instrument_id) is not str
        or not instrument_id
        or type(dimension) is not str
        or not dimension
        or flags[0] is not True
        or flags[1] is not False
        or flags[2] is not False
        or flags[3] != _RESEARCH_PUBLICATION_STATUS
        or flags[4] != "CAT_RESEARCH_PROFILE_CANDIDATE"
    ):
        _raise(
            ResearchCatRepositoryErrorCode.PROFILE_HASH_MISMATCH,
            "research profile object differs from its expected hash or locked research flags",
        )
    if (
        document.get("profile_id") != profile_id
        or document.get("instrument_id") != instrument_id
        or document.get("dimension") != dimension
        or document.get("research_only") is not True
        or document.get("publication_status") != _RESEARCH_PUBLICATION_STATUS
        or document.get("psychological_interpretation_allowed") is not False
        or document.get("human_curated", False) is not False
    ):
        _raise(
            ResearchCatRepositoryErrorCode.INVALID_INPUT,
            "raw profile bytes do not match locked research-only object metadata",
        )
    model = document.get("model")
    if not isinstance(model, dict):
        _raise(
            ResearchCatRepositoryErrorCode.INVALID_INPUT,
            "research profile model metadata is missing",
        )
    fit_sha = model.get("fit_sha256")
    calibration_sha = model.get("calibration_sha256")
    _require_sha256(fit_sha, "model.fit_sha256")
    _require_sha256(calibration_sha, "model.calibration_sha256")
    _require_ascii_text(instrument_id, "instrument_id", 128)
    _require_ascii_text(dimension, "dimension", 64)
    return _ProfileStorageProjection(
        profile_ref=profile_id,
        instrument_id=instrument_id,
        dimension=dimension,
        fit_sha256=fit_sha,
        calibration_sha256=calibration_sha,
        parameter_origin=_LOCAL_RESEARCH_FIT,
        published_parameter_crosswalk_sha256=None,
    )


def _promis_v3_storage_projection(
    document: Mapping[str, object],
    *,
    profile_ref: str,
    expected_profile_sha256: str,
    expected_manifest_sha256: str,
) -> _ProfileStorageProjection:
    """Map the one pinned PROMIS v3 source to safe DB metadata without rewriting it."""

    if (
        expected_profile_sha256 != _PROMIS_V3_PROFILE_SHA256
        or expected_manifest_sha256 != _PROMIS_V3_MANIFEST_SHA256
        or profile_ref != _PROMIS_V3_PROFILE_ID
        or set(document) != _PROMIS_V3_ROOT_FIELDS
        or document.get("schema") != _PROFILE_SCHEMA_V3
        or document.get("profile_id") != _PROMIS_V3_PROFILE_ID
        or document.get("profile_type") != "research_only_candidate"
        or document.get("instrument_id") != "PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET"
        or document.get("instrument_family") != "PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET"
        or document.get("dimension") != _PROMIS_V3_RAW_DIMENSION
        or type(document.get("research_only")) is not bool
        or document.get("research_only") is not True
        or document.get("publication_status") != _PROMIS_V3_RAW_PUBLICATION_STATUS
        or type(document.get("human_curated")) is not bool
        or document.get("human_curated") is not False
        or type(document.get("psychological_interpretation_allowed")) is not bool
        or document.get("psychological_interpretation_allowed") is not False
    ):
        _raise(
            ResearchCatRepositoryErrorCode.PROFILE_HASH_MISMATCH,
            "PROMIS v3 source identity or locked research flags differ from the pinned profile",
        )
    model = document.get("model")
    provenance = document.get("provenance")
    if (
        not isinstance(model, Mapping)
        or set(model) != _PROMIS_V3_MODEL_FIELDS
        or model.get("parameter_origin") != "published item bank parameters; no refit"
        or "fit_sha256" in model
        or "calibration_sha256" in model
        or not isinstance(provenance, Mapping)
    ):
        _raise(
            ResearchCatRepositoryErrorCode.PROFILE_HASH_MISMATCH,
            "PROMIS v3 must retain published rounded parameters without local fit hashes",
        )
    crosswalk_sha256 = provenance.get("parameter_crosswalk_sha256")
    if (
        type(crosswalk_sha256) is not str
        or not _SHA256.fullmatch(crosswalk_sha256)
        or crosswalk_sha256 != _PROMIS_V3_CROSSWALK_SHA256
    ):
        _raise(
            ResearchCatRepositoryErrorCode.PROFILE_HASH_MISMATCH,
            "PROMIS v3 published-parameter crosswalk differs from its pinned provenance",
        )
    return _ProfileStorageProjection(
        profile_ref=_PROMIS_V3_PROFILE_ID,
        instrument_id="PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET",
        dimension=_PROMIS_V3_STORAGE_DIMENSION,
        fit_sha256=None,
        calibration_sha256=None,
        parameter_origin=_PUBLISHED_ROUNDED_REFERENCE,
        published_parameter_crosswalk_sha256=crosswalk_sha256,
    )


def _decode_profile_envelope(
    payload: Mapping[str, object],
    *,
    expected_profile_sha256: str,
    expected_profile_ref: str,
) -> bytes:
    if (
        set(payload)
        != {
            "schema",
            "profile_sha256",
            "profile_id",
            "profile_schema",
            "raw_profile_utf8_b64",
        }
        or payload.get("schema") != _PROFILE_ENVELOPE_SCHEMA
    ):
        _raise(
            ResearchCatRepositoryErrorCode.CRYPTO_FAILURE,
            "encrypted profile envelope schema is invalid",
        )
    if (
        payload.get("profile_sha256") != expected_profile_sha256
        or payload.get("profile_id") != expected_profile_ref
    ):
        _raise(
            ResearchCatRepositoryErrorCode.PROFILE_HASH_MISMATCH,
            "encrypted profile envelope metadata differs from trusted storage metadata",
        )
    encoded = payload.get("raw_profile_utf8_b64")
    if not isinstance(encoded, str):
        _raise(
            ResearchCatRepositoryErrorCode.CRYPTO_FAILURE,
            "encrypted profile envelope has no source bytes",
        )
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        _raise(
            ResearchCatRepositoryErrorCode.CRYPTO_FAILURE,
            "encrypted profile source bytes are malformed",
            cause=exc,
        )
    actual = hashlib.sha256(raw).hexdigest()
    document = _parse_json_object(raw)
    if (
        actual != expected_profile_sha256
        or document.get("profile_id") != expected_profile_ref
        or document.get("schema") != payload.get("profile_schema")
    ):
        _raise(
            ResearchCatRepositoryErrorCode.PROFILE_HASH_MISMATCH,
            "decrypted original profile bytes fail their independently supplied hash",
        )
    return raw


def _verify_profile_row_metadata(
    raw_profile_bytes: bytes, row: SchoolResearchProfileVersion
) -> None:
    document = _parse_json_object(raw_profile_bytes)
    if document.get("schema") == _PROFILE_SCHEMA_V3:
        projection = _promis_v3_storage_projection(
            document,
            profile_ref=row.profile_ref,
            expected_profile_sha256=row.profile_sha256,
            expected_manifest_sha256=row.manifest_sha256,
        )
        if (
            row.profile_sha256 != _PROMIS_V3_PROFILE_SHA256
            or row.manifest_sha256 != _PROMIS_V3_MANIFEST_SHA256
            or row.instrument_id != projection.instrument_id
            or row.dimension != projection.dimension
            or row.fit_sha256 is not None
            or row.calibration_sha256 is not None
            or row.parameter_origin != projection.parameter_origin
            or row.published_parameter_crosswalk_sha256
            != projection.published_parameter_crosswalk_sha256
            or row.publication_status != _RESEARCH_PUBLICATION_STATUS
            or row.research_only is not True
            or row.human_curated is not False
            or row.psychological_interpretation_allowed is not False
        ):
            _raise(
                ResearchCatRepositoryErrorCode.PROFILE_HASH_MISMATCH,
                "decrypted PROMIS v3 source differs from its safe immutable row projection",
            )
        return

    model = document.get("model")
    if not isinstance(model, dict):
        _raise(
            ResearchCatRepositoryErrorCode.PROFILE_HASH_MISMATCH,
            "decrypted profile model metadata is unavailable",
        )
    if (
        document.get("instrument_id") != row.instrument_id
        or document.get("dimension") != row.dimension
        or model.get("fit_sha256") != row.fit_sha256
        or model.get("calibration_sha256") != row.calibration_sha256
        or row.parameter_origin != _LOCAL_RESEARCH_FIT
        or row.published_parameter_crosswalk_sha256 is not None
        or document.get("research_only") is not True
        or document.get("publication_status") != _RESEARCH_PUBLICATION_STATUS
        or document.get("psychological_interpretation_allowed") is not False
        or ("human_curated" in document and document.get("human_curated") is not False)
    ):
        _raise(
            ResearchCatRepositoryErrorCode.PROFILE_HASH_MISMATCH,
            "decrypted original profile metadata differs from its immutable row projection",
        )


def _decode_config_envelope(payload: Mapping[str, object], expected_config_sha256: str) -> str:
    if (
        set(payload) != {"schema", "config_sha256", "config_json"}
        or payload.get("schema") != _CONFIG_ENVELOPE_SCHEMA
    ):
        _raise(
            ResearchCatRepositoryErrorCode.CRYPTO_FAILURE,
            "encrypted CAT config envelope schema is invalid",
        )
    config_json = payload.get("config_json")
    if (
        not isinstance(config_json, str)
        or hashlib.sha256(config_json.encode("utf-8")).hexdigest() != expected_config_sha256
        or payload.get("config_sha256") != expected_config_sha256
    ):
        _raise(
            ResearchCatRepositoryErrorCode.CONFIG_HASH_MISMATCH,
            "decrypted CAT config does not match its independent registry hash",
        )
    try:
        parsed = json.loads(config_json, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ResearchCatRepositoryError) as exc:
        _raise(
            ResearchCatRepositoryErrorCode.CRYPTO_FAILURE,
            "decrypted CAT config is invalid JSON",
            cause=exc,
        )
    if not isinstance(parsed, dict) or _canonical_json(parsed) != config_json:
        _raise(
            ResearchCatRepositoryErrorCode.CRYPTO_FAILURE,
            "decrypted CAT config is not canonical JSON",
        )
    return config_json


def _validate_signed_snapshot(
    signed_snapshot: Mapping[str, object],
    *,
    session_ref: str,
    profile_ref: str,
    profile_sha256: str,
    config_version: str,
    config_sha256: str,
    require_active: bool,
) -> dict[str, object]:
    if not isinstance(signed_snapshot, Mapping) or set(signed_snapshot) != {
        "payload",
        "payload_sha256",
        "signature",
    }:
        _raise(
            ResearchCatRepositoryErrorCode.SNAPSHOT_INVALID,
            "backend must provide the complete signed CAT snapshot envelope",
        )
    payload = signed_snapshot.get("payload")
    signature = signed_snapshot.get("signature")
    digest = signed_snapshot.get("payload_sha256")
    if (
        not isinstance(payload, Mapping)
        or type(signature) is not str
        or not signature.isascii()
        or not signature.isprintable()
        or not (1 <= len(signature) <= 4096)
        or type(digest) is not str
        or not _SHA256.fullmatch(digest)
    ):
        _raise(
            ResearchCatRepositoryErrorCode.SNAPSHOT_INVALID,
            "backend signed CAT snapshot envelope is malformed",
        )
    payload_json = _canonical_json(payload)
    actual_digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    if actual_digest != digest:
        _raise(
            ResearchCatRepositoryErrorCode.SNAPSHOT_INVALID,
            "signed CAT snapshot digest does not match its payload",
        )
    required = {
        "schema",
        "session_id",
        "profile_id",
        "profile_sha256",
        "config_version",
        "config_sha256",
        "step",
        "status",
        "stop_reason",
        "pending_item_id",
        "answers",
    }
    if set(payload) != required or payload.get("schema") != _SNAPSHOT_SCHEMA:
        _raise(
            ResearchCatRepositoryErrorCode.SNAPSHOT_INVALID,
            "research CAT snapshot payload fields are invalid",
        )
    if (
        payload.get("session_id") != session_ref
        or payload.get("profile_id") != profile_ref
        or payload.get("profile_sha256") != profile_sha256
        or payload.get("config_version") != config_version
        or payload.get("config_sha256") != config_sha256
        or type(payload.get("step")) is not int
        or type(payload.get("answers")) is not list
        or payload.get("step") != len(payload.get("answers"))
    ):
        _raise(
            ResearchCatRepositoryErrorCode.SNAPSHOT_INVALID,
            "research CAT snapshot scope or answer count differs from its binding",
        )
    status = payload.get("status")
    if type(status) is not str or status not in {
        "ACTIVE",
        "COMPLETED",
        "INCOMPLETE",
        "FAILED",
    }:
        _raise(
            ResearchCatRepositoryErrorCode.SNAPSHOT_INVALID,
            "research CAT snapshot has an unsupported lifecycle status",
        )
    if require_active and status != "ACTIVE":
        _raise(
            ResearchCatRepositoryErrorCode.SNAPSHOT_INVALID,
            "new research CAT sessions require an active initial snapshot",
        )
    stop_reason = payload.get("stop_reason")
    if stop_reason is not None:
        _require_stop_reason(stop_reason)
    answers = payload.get("answers")
    if any(
        not isinstance(answer, Mapping)
        or set(answer) != {"item_id", "raw_value"}
        or not isinstance(answer.get("item_id"), str)
        or isinstance(answer.get("raw_value"), bool)
        or not isinstance(answer.get("raw_value"), int)
        for answer in answers
    ):
        _raise(
            ResearchCatRepositoryErrorCode.SNAPSHOT_INVALID,
            "signed research CAT answers do not match the strict ordinal event schema",
        )
    return {
        "payload": dict(payload),
        "payload_sha256": digest,
        "signature": signature,
        "status": status,
        "stop_reason": stop_reason,
        "answers": answers,
    }


def _decode_session_envelope(
    payload: Mapping[str, object],
    *,
    expected_session_ref: str,
    expected_profile_ref: str,
    expected_profile_sha256: str,
    expected_config_version: str,
    expected_config_sha256: str,
    expected_payload_sha256: str,
    expected_items_answered: int,
    require_active: bool,
) -> Mapping[str, object]:
    if (
        set(payload) != {"schema", "signed_snapshot"}
        or payload.get("schema") != _SESSION_ENVELOPE_SCHEMA
    ):
        _raise(
            ResearchCatRepositoryErrorCode.CRYPTO_FAILURE,
            "encrypted research session envelope schema is invalid",
        )
    snapshot = payload.get("signed_snapshot")
    fields = _validate_signed_snapshot(
        snapshot,
        session_ref=expected_session_ref,
        profile_ref=expected_profile_ref,
        profile_sha256=expected_profile_sha256,
        config_version=expected_config_version,
        config_sha256=expected_config_sha256,
        require_active=require_active,
    )
    if (
        fields["payload_sha256"] != expected_payload_sha256
        or len(fields["answers"]) != expected_items_answered
    ):
        _raise(
            ResearchCatRepositoryErrorCode.SNAPSHOT_INVALID,
            "encrypted research snapshot does not match its lifecycle projection",
        )
    return snapshot


def _require_profile_enabled(profile: SchoolResearchProfileVersion) -> None:
    if profile.rights_status == "REVOKED":
        _raise(
            ResearchCatRepositoryErrorCode.PROFILE_RIGHTS_REVOKED,
            "revoked research profile rights prevent further use",
        )
    if (
        profile.rights_status != "VERIFIED"
        or profile.execution_status != "SIMULATION_ENABLED"
        or profile.research_only is not True
        or profile.human_curated is not False
        or profile.psychological_interpretation_allowed is not False
        or profile.publication_status != _RESEARCH_PUBLICATION_STATUS
    ):
        _raise(
            ResearchCatRepositoryErrorCode.PROFILE_NOT_ELIGIBLE,
            "research profile is not eligible for isolated simulation",
        )


def _profile_states(rights_status: str, execution_status: str) -> tuple[str, str]:
    return (
        _require_choice(rights_status, {"PENDING", "VERIFIED", "REVOKED"}, "rights_status"),
        _require_choice(
            execution_status,
            {"CANDIDATE_RESEARCH_ONLY", "SIMULATION_ENABLED", "DISABLED"},
            "execution_status",
        ),
    )


def _parse_json_object(raw: bytes) -> dict[str, object]:
    try:
        result = json.loads(
            raw.decode("utf-8-sig"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ResearchCatRepositoryError) as exc:
        _raise(
            ResearchCatRepositoryErrorCode.INVALID_INPUT,
            "profile source bytes are not strict UTF-8 JSON",
            cause=exc,
        )
    if not isinstance(result, dict):
        _raise(
            ResearchCatRepositoryErrorCode.INVALID_INPUT,
            "research profile root must be a JSON object",
        )
    return result


def _profile_document_schema(raw: bytes) -> str:
    document = _parse_json_object(raw)
    schema = document.get("schema")
    if schema not in {_PROFILE_SCHEMA_V1, _PROFILE_SCHEMA_V2, _PROFILE_SCHEMA_V3}:
        _raise(
            ResearchCatRepositoryErrorCode.INVALID_INPUT,
            "research profile schema is unsupported",
        )
    return schema


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ResearchCatRepositoryError(
                ResearchCatRepositoryErrorCode.INVALID_INPUT,
                "JSON object contains duplicate keys",
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ResearchCatRepositoryError(
        ResearchCatRepositoryErrorCode.INVALID_INPUT,
        "JSON contains a non-finite numeric constant",
    )


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        _raise(
            ResearchCatRepositoryErrorCode.INVALID_INPUT,
            "research persistence envelope is not canonical JSON",
            cause=exc,
        )


def _require_sha256(value: object, name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _raise(
            ResearchCatRepositoryErrorCode.INVALID_INPUT,
            f"{name} must be a lowercase SHA-256",
        )
    return value


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        _raise(
            ResearchCatRepositoryErrorCode.INVALID_INPUT,
            f"{name} must be a positive integer",
        )
    return value


def _require_token(value: object, name: str, limit: int) -> str:
    if (
        type(value) is not str
        or not value.isascii()
        or len(value) > limit
        or _TOKEN.fullmatch(value) is None
    ):
        _raise(
            ResearchCatRepositoryErrorCode.INVALID_INPUT,
            f"{name} must be a bounded ASCII reference",
        )
    return value


def _require_ascii_text(value: object, name: str, limit: int) -> str:
    if type(value) is not str or not value or not value.isascii() or len(value) > limit:
        _raise(
            ResearchCatRepositoryErrorCode.INVALID_INPUT,
            f"{name} must be bounded ASCII text for its database column",
        )
    return value


def _optional_token(value: object, name: str, limit: int) -> str | None:
    return None if value is None else _require_token(value, name, limit)


def _require_stop_reason(value: object) -> str:
    if type(value) is not str or not value.isascii() or _STOP_REASON.fullmatch(value) is None:
        _raise(
            ResearchCatRepositoryErrorCode.INVALID_INPUT,
            "stop reason must be a bounded content-free code",
        )
    return value


def _require_choice(value: object, choices: set[str], name: str) -> str:
    if type(value) is not str or value not in choices:
        _raise(
            ResearchCatRepositoryErrorCode.INVALID_INPUT,
            f"{name} is outside its fixed research status set",
        )
    return value


def _raise(
    code: ResearchCatRepositoryErrorCode,
    message: str,
    *,
    cause: BaseException | None = None,
) -> None:
    error = ResearchCatRepositoryError(code, message)
    if cause is None:
        raise error
    raise error from cause
