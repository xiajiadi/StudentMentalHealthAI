"""Atomic, school-scoped publication of research-profile task bindings.

This adapter only creates a PUBLIC_OBSERVED replay task after a separately
injected trusted study policy authorizes the exact study window.  It never
changes a profile's rights or execution eligibility.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from smhai_backend.core.errors import BackendError, ErrorCode, error
from smhai_backend.core.request_context import get_request_context
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.domains.school_research.catalog import (
    ResearchBindingSelection,
    ResearchProfileSelection,
    SchoolResearchCatalog,
    SchoolResearchCatalogError,
)
from smhai_backend.domains.school_research.observed_corpus import ObservedResponseCorpus
from smhai_backend.domains.school_research.study_use import (
    ResearchStudyProfilePin,
    ResearchStudyUseError,
    ResearchStudyUsePolicy,
)

_RESOURCE_TYPE = "measurement_task"
_PUBLICATION_NOT_APPROVED = "not_approved_for_publication_or_operational_use"
_RESEARCH_MODE = "RESEARCH_PROFILE"
_RESPONSE_ORIGIN = "PUBLIC_OBSERVED"
_TASK_REF = re.compile(r"TASK_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}\Z")
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PROFILE_NOT_FOUND = "RESEARCH_PROFILE_NOT_FOUND"
_BINDING_NOT_FOUND = "RESEARCH_BINDING_NOT_FOUND"
_CONFLICT_CODES = frozenset(
    {
        "RESEARCH_PROFILE_NOT_ELIGIBLE",
        "RESEARCH_PROFILE_RIGHTS_REVOKED",
        "RESEARCH_PROFILE_HASH_MISMATCH",
        "RESEARCH_CONFIG_HASH_MISMATCH",
        "RESEARCH_TASK_MODE_MISMATCH",
        "RESEARCH_TASK_NOT_FOUND",
        "RESEARCH_PERSISTENCE_CONFLICT",
        "RESEARCH_BINDING_NOT_FOUND",
        "RESEARCH_CASE_ASSIGNMENT_INVALID",
        "RESEARCH_CORPUS_PIN_UNAVAILABLE",
        "RESEARCH_CASE_ASSIGNMENT_NOT_FOUND",
    }
)
_POLICY_DENIAL_CODES = frozenset(
    {"scope_denied", "task_window_invalid", "task_window_outside_policy"}
)
_CATALOG_PROFILE_LIMIT = 100


@dataclass(frozen=True, slots=True)
class ResearchTaskPublicationView:
    """Safe publication receipt; no database IDs, hashes, or CAT config."""

    task_ref: str
    class_ref: str
    binding_ref: str
    profile_ref: str
    profile_version_number: int
    source_population_scope: str
    instrument_id: str
    instrument_version: str
    status: str
    opens_at: datetime
    due_at: datetime
    published_at: datetime
    published_enrollment_count: int
    response_origin: str
    research_only: bool
    publication_status: str


@dataclass(frozen=True, slots=True)
class ResearchTaskBindingOptionView:
    """Safe admin selector; profile/config bytes and hashes are never projected."""

    binding_ref: str
    profile_ref: str
    profile_version_number: int
    source_population_scope: str
    instrument_id: str
    instrument_version: str
    research_only: bool
    publication_status: str


class SchoolResearchTasksPersistenceAdapter:
    """Create task, roster snapshot, CAT binding, receipt, and audit atomically."""

    def __init__(
        self,
        owner: Any,
        catalog: SchoolResearchCatalog,
        *,
        study_use_policy: ResearchStudyUsePolicy | None = None,
        study_use_policy_sha256: str | None = None,
    ) -> None:
        if not callable(getattr(owner, "_uow", None)):
            raise TypeError("owner must provide database units of work")
        if type(catalog) is not SchoolResearchCatalog:
            raise TypeError("catalog must be an immutable SchoolResearchCatalog")
        if study_use_policy is not None and not callable(
            getattr(study_use_policy, "require_scope", None)
        ):
            raise TypeError("study-use policy must provide require_scope")
        if study_use_policy is None:
            if study_use_policy_sha256 is not None:
                raise TypeError("study policy hash requires a configured policy")
        elif type(study_use_policy_sha256) is not str or not _SHA256.fullmatch(
            study_use_policy_sha256
        ):
            raise TypeError("study-use policy SHA-256 is required")
        self._owner = owner
        self._catalog = catalog
        # Missing trusted study configuration is a deny-all state.
        self._study_use_policy = study_use_policy
        self._study_use_policy_sha256 = study_use_policy_sha256

    async def list_catalog_options(
        self, actor: Actor, *, at: datetime
    ) -> tuple[ResearchTaskBindingOptionView, ...]:
        """List only the pinned, currently usable binding/profile-version pairs."""

        _require_admin_actor(actor)
        _validate_at(at)
        database_at = _database_utc(at)
        try:
            async with self._owner._uow() as uow:
                actor_account_id, _role_id = await self._owner._school_actor_role(
                    uow, actor, "admin", database_at
                )
                # Authenticate the persisted admin before reading any selector
                # or exposing whether a binding exists in the trusted catalog.
                if actor.school_id != self._catalog.school_id:
                    raise _not_found()
                policy = self._require_catalog_policy(at=at)
                configured_bindings = tuple(
                    self._catalog.select_binding(
                        public_binding.binding_ref, school_id=actor.school_id
                    )
                    for public_binding in self._catalog.public_bindings
                    if public_binding.school_id == actor.school_id
                    and public_binding.research_only is True
                    and public_binding.publication_status == _PUBLICATION_NOT_APPROVED
                )
                bindings = tuple(
                    binding for binding in configured_bindings
                    if binding.observed_source_verified is True
                )
                if not bindings:
                    await _audit_catalog_list(
                        uow,
                        actor_account_id=actor_account_id,
                        count=0,
                        success_result=self._owner._db_enums.AuditResult.SUCCESS,
                    )
                    return ()

                profile_refs = tuple(
                    sorted({item.public.profile_ref for item in bindings})
                )
                profile_model = self._owner._db_models.SchoolResearchProfileVersion
                statement = (
                    self._owner._select(
                        profile_model.id,
                        profile_model.school_id,
                        profile_model.profile_ref,
                        profile_model.version_number,
                        profile_model.instrument_id,
                        profile_model.source_population_scope,
                        profile_model.profile_sha256,
                        profile_model.manifest_sha256,
                        profile_model.fit_sha256,
                        profile_model.calibration_sha256,
                        profile_model.parameter_origin,
                        profile_model.published_parameter_crosswalk_sha256,
                        profile_model.research_only,
                        profile_model.human_curated,
                        profile_model.psychological_interpretation_allowed,
                        profile_model.publication_status,
                        profile_model.rights_status,
                        profile_model.execution_status,
                        profile_model.rights_revoked_at,
                        profile_model.disabled_at,
                        profile_model.simulation_enabled_at,
                    )
                    .where(
                        profile_model.school_id == actor.school_id,
                        profile_model.profile_ref.in_(profile_refs),
                        profile_model.rights_status == "VERIFIED",
                        profile_model.execution_status == "SIMULATION_ENABLED",
                        profile_model.rights_revoked_at.is_(None),
                        profile_model.disabled_at.is_(None),
                        profile_model.simulation_enabled_at.is_not(None),
                        profile_model.research_only.is_(True),
                        profile_model.human_curated.is_(False),
                        profile_model.psychological_interpretation_allowed.is_(False),
                        profile_model.publication_status == _PUBLICATION_NOT_APPROVED,
                        profile_model.purpose == "RESEARCH_SIMULATION",
                    )
                    .order_by(profile_model.profile_ref, profile_model.version_number)
                    .limit(_CATALOG_PROFILE_LIMIT + 1)
                )
                rows = list((await uow.session.execute(statement)).all())
                if len(rows) > _CATALOG_PROFILE_LIMIT:
                    raise _dependency_error()

                profile_selections = {
                    profile_ref: self._catalog.select_profile(
                        profile_ref, school_id=actor.school_id
                    )
                    for profile_ref in profile_refs
                }
                options: list[ResearchTaskBindingOptionView] = []
                for row in rows:
                    metadata = _catalog_profile_metadata(row)
                    profile = profile_selections[metadata.profile_ref]
                    _require_profile_eligible(metadata, profile, metadata.version_number)
                    self._require_current_catalog_profile_policy(
                        policy, actor=actor, profile=profile, metadata=metadata, at=at
                    )
                    for binding in bindings:
                        if binding.public.profile_ref != metadata.profile_ref:
                            continue
                        _require_catalog_binding(profile, binding)
                        options.append(
                            ResearchTaskBindingOptionView(
                                binding_ref=binding.public.binding_ref,
                                profile_ref=metadata.profile_ref,
                                profile_version_number=metadata.version_number,
                                source_population_scope=metadata.source_population_scope,
                                instrument_id=metadata.instrument_id,
                                instrument_version=f"research-v{metadata.version_number}",
                                research_only=True,
                                publication_status=_PUBLICATION_NOT_APPROVED,
                            )
                        )
                options.sort(
                    key=lambda item: (
                        item.profile_ref,
                        item.profile_version_number,
                        item.binding_ref,
                    )
                )
                await _audit_catalog_list(
                    uow,
                    actor_account_id=actor_account_id,
                    count=len(options),
                    success_result=self._owner._db_enums.AuditResult.SUCCESS,
                )
                return tuple(options)
        except BackendError:
            raise
        except ResearchStudyUseError as exc:
            if exc.code in _POLICY_DENIAL_CODES:
                raise _policy_denied() from None
            if exc.code == "profile_pin_mismatch":
                raise _conflict() from None
            raise _policy_unavailable() from None
        except SchoolResearchCatalogError:
            raise _not_found() from None
        except Exception:
            raise _dependency_error() from None

    def _require_catalog_policy(self, *, at: datetime) -> ResearchStudyUsePolicy:
        policy = self._study_use_policy
        if (
            type(policy) is not ResearchStudyUsePolicy
            or type(self._study_use_policy_sha256) is not str
            or _SHA256.fullmatch(self._study_use_policy_sha256) is None
            or policy.school_id != self._catalog.school_id
            or policy.source_rights_verified is not True
            or policy.use_scope != "ISOLATED_HISTORICAL_REPLAY"
            or policy.noncommercial is not True
            or policy.historical_replay_only is not True
            or policy.english_unchanged is not True
            or policy.clinical_approval is not False
            or policy.ethics_approval is not False
            or policy.psychometric_approval is not False
        ):
            raise _policy_unavailable()
        instant = _aware_utc(at)
        if not policy.starts_at <= instant <= policy.ends_at:
            raise _policy_denied()
        return policy

    def _require_current_catalog_profile_policy(
        self,
        policy: ResearchStudyUsePolicy,
        *,
        actor: Actor,
        profile: ResearchProfileSelection,
        metadata: Any,
        at: datetime,
    ) -> None:
        pin = policy.require_scope(
            school_id=actor.school_id,
            profile_ref=profile.public.profile_ref,
            profile_sha256=profile.repository.expected_profile_sha256,
            manifest_sha256=profile.repository.expected_manifest_sha256,
            at=_aware_utc(at),
        )
        if (
            type(pin) is not ResearchStudyProfilePin
            or pin.profile_ref != metadata.profile_ref
            or pin.profile_sha256 != metadata.profile_sha256
            or pin.manifest_sha256 != metadata.manifest_sha256
            or pin.published_crosswalk_sha256 != metadata.published_parameter_crosswalk_sha256
        ):
            raise _policy_denied()

    async def publish_task(
        self,
        actor: Actor,
        *,
        class_ref: str,
        task_ref: str,
        binding_ref: str,
        profile_version_number: int,
        opens_at: datetime,
        due_at: datetime,
        at: datetime,
        idempotency: tuple[str, str, str],
    ) -> ResearchTaskPublicationView:
        _require_admin_actor(actor)
        _validate_refs(class_ref, task_ref, binding_ref)
        _validate_version(profile_version_number)
        _validate_time_window(opens_at, due_at)
        _validate_at(at)
        database_at = _database_utc(at)
        opens = _database_utc(opens_at)
        due = _database_utc(due_at)
        _validate_idempotency(idempotency)

        try:
            async with self._owner._uow() as uow:
                account_id, role_id = await self._owner._school_actor_role(
                    uow, actor, "admin", database_at
                )

                # The trusted server catalog is consulted only after persisted
                # admin authorization has succeeded.
                if actor.school_id != self._catalog.school_id:
                    raise _not_found()
                try:
                    binding = self._catalog.select_binding(binding_ref, school_id=actor.school_id)
                    profile = self._catalog.select_profile(
                        binding.public.profile_ref, school_id=actor.school_id
                    )
                except SchoolResearchCatalogError:
                    raise _not_found() from None
                _require_catalog_binding(profile, binding)
                await self._require_trusted_study_window(
                    actor=actor,
                    profile=profile,
                    opens_at=opens_at,
                    due_at=due_at,
                    at=at,
                )

                claim = await self._owner._school_idempotency_begin(uow, idempotency)
                if claim.replayed:
                    return await self._replay(
                        uow,
                        actor=actor,
                        claim=claim,
                        class_ref=class_ref,
                        task_ref=task_ref,
                        profile=profile,
                        binding=binding,
                        profile_version_number=profile_version_number,
                        opens_at=opens,
                        due_at=due,
                        at=database_at,
                    )

                m = self._owner._db_models
                school_class = await uow.session.scalar(
                    self._owner._select(m.SchoolClass).where(
                        m.SchoolClass.school_id == actor.school_id,
                        m.SchoolClass.class_ref == class_ref,
                    )
                )
                if school_class is None:
                    raise _not_found()
                existing_task = await uow.session.scalar(
                    self._owner._select(m.MeasurementTask).where(
                        m.MeasurementTask.school_id == actor.school_id,
                        m.MeasurementTask.task_ref == task_ref,
                    )
                )
                if existing_task is not None:
                    raise _conflict()

                metadata = await _get_profile_metadata(
                    uow,
                    school_id=actor.school_id,
                    profile=profile,
                    version_number=profile_version_number,
                )
                _require_profile_eligible(metadata, profile, profile_version_number)

                # No client-supplied response origin or measurement metadata is
                # accepted. This lane is explicitly a public-observed replay.
                instrument_id = profile.public.instrument_id
                instrument_version = f"research-v{profile_version_number}"
                snapshot = await uow.school_operations.publish_task_with_snapshot(
                    school_id=actor.school_id,
                    class_id=school_class.id,
                    task_ref=task_ref,
                    admin_membership_role_id=role_id,
                    instrument_id=instrument_id,
                    instrument_version=instrument_version,
                    item_bank_version=None,
                    config_version=binding.public.config_version,
                    opens_at=opens,
                    due_at=due,
                    published_at=database_at,
                )
                task = snapshot.task
                task.cat_binding_mode = _RESEARCH_MODE
                await uow.session.flush()
                case_index_plan = _server_case_index_plan(
                    school_id=actor.school_id,
                    task_id=task.id,
                    profile_sha256=profile.repository.expected_profile_sha256,
                    corpus_sha256=binding.observed_corpus_sha256,
                    enrollment_count=snapshot.enrollment_count,
                )

                created_binding = await uow.research_cat.create_task_binding(
                    school_id=actor.school_id,
                    task_id=task.id,
                    class_id=school_class.id,
                    profile_version_id=metadata.profile_version_id,
                    profile_ref=profile.public.profile_ref,
                    profile_version_number=profile_version_number,
                    expected_profile_sha256=profile.repository.expected_profile_sha256,
                    response_origin=_RESPONSE_ORIGIN,
                    config_version=binding.public.config_version,
                    config_payload=binding.cat_config_copy(),
                    expected_config_sha256=binding.config_sha256,
                    creator_membership_role_id=role_id,
                    corpus_sha256=binding.observed_corpus_sha256,
                    case_count=binding.observed_corpus_row_count,
                )
                _require_created_binding(
                    created_binding,
                    school_id=actor.school_id,
                    task_id=task.id,
                    class_id=school_class.id,
                    profile=profile,
                    binding=binding,
                    profile_version_id=metadata.profile_version_id,
                    profile_version_number=profile_version_number,
                )
                assignments = await uow.research_cat.create_public_observed_case_assignments(
                    school_id=actor.school_id,
                    task_id=task.id,
                    class_id=school_class.id,
                    task_binding_id=created_binding.binding_id,
                    expected_profile_sha256=profile.repository.expected_profile_sha256,
                    expected_corpus_sha256=binding.observed_corpus_sha256,
                    creator_membership_role_id=role_id,
                    case_index_plan=case_index_plan,
                )
                _require_created_assignments(
                    assignments,
                    expected_count=snapshot.enrollment_count,
                    school_id=actor.school_id,
                    task_id=task.id,
                    class_id=school_class.id,
                    binding_id=created_binding.binding_id,
                    profile_version_id=metadata.profile_version_id,
                    profile_version_number=profile_version_number,
                    profile=profile,
                    binding=binding,
                    case_index_plan=case_index_plan,
                )

                await self._owner._school_idempotency_complete(
                    uow,
                    claim,
                    resource_type=_RESOURCE_TYPE,
                    result_ref=task.public_id,
                )
                await _audit(
                    uow,
                    actor_account_id=account_id,
                    task_ref=task.task_ref,
                    trace_id=get_request_context().trace_id,
                    action="school_research_tasks.task.published",
                    success_result=self._owner._db_enums.AuditResult.SUCCESS,
                    study_use_policy_sha256=self._study_use_policy_sha256,
                )
                return _view(
                    task=task,
                    class_ref=class_ref,
                    binding_ref=binding_ref,
                    profile=profile,
                    profile_version_number=profile_version_number,
                    enrollment_count=snapshot.enrollment_count,
                    response_origin=_RESPONSE_ORIGIN,
                )
        except BackendError:
            raise
        except SchoolResearchCatalogError:
            raise _not_found() from None
        except Exception as exc:
            code = _exception_code(exc)
            if code in {_PROFILE_NOT_FOUND, _BINDING_NOT_FOUND}:
                raise _not_found() from None
            if code in _CONFLICT_CODES:
                raise _conflict() from None
            raise _dependency_error() from None

    async def _require_trusted_study_window(
        self,
        *,
        actor: Actor,
        profile: ResearchProfileSelection,
        opens_at: datetime,
        due_at: datetime,
        at: datetime,
    ) -> None:
        policy = self._study_use_policy
        if policy is None:
            raise _policy_denied()
        try:
            pin = policy.require_scope(
                school_id=actor.school_id,
                profile_ref=profile.public.profile_ref,
                profile_sha256=profile.repository.expected_profile_sha256,
                manifest_sha256=profile.repository.expected_manifest_sha256,
                at=_aware_utc(at),
                task_opens_at=_aware_utc(opens_at),
                task_due_at=_aware_utc(due_at),
            )
        except ResearchStudyUseError as exc:
            if exc.code in _POLICY_DENIAL_CODES:
                raise _policy_denied() from None
            if exc.code == "profile_pin_mismatch":
                raise _conflict() from None
            raise _policy_unavailable() from None
        except Exception:
            raise _policy_unavailable() from None
        if (
            getattr(pin, "profile_ref", None) != profile.public.profile_ref
            or getattr(pin, "profile_sha256", None) != profile.repository.expected_profile_sha256
            or getattr(pin, "manifest_sha256", None) != profile.repository.expected_manifest_sha256
            or getattr(pin, "published_crosswalk_sha256", None) != _parameter_pins(profile)[2]
        ):
            raise _policy_denied()

    async def _replay(
        self,
        uow: Any,
        *,
        actor: Actor,
        claim: Any,
        class_ref: str,
        task_ref: str,
        profile: ResearchProfileSelection,
        binding: ResearchBindingSelection,
        profile_version_number: int,
        opens_at: datetime,
        due_at: datetime,
        at: datetime,
    ) -> ResearchTaskPublicationView:
        record = getattr(claim, "record", None)
        if (
            record is None
            or getattr(record, "result_resource_type", None) != _RESOURCE_TYPE
            or type(getattr(record, "result_public_id", None)) is not str
        ):
            raise _conflict()
        m = self._owner._db_models
        task = await uow.session.scalar(
            self._owner._select(m.MeasurementTask).where(
                m.MeasurementTask.school_id == actor.school_id,
                m.MeasurementTask.public_id == record.result_public_id,
                m.MeasurementTask.task_ref == task_ref,
                m.MeasurementTask.class_id
                == self._owner._select(m.SchoolClass.id)
                .where(
                    m.SchoolClass.school_id == actor.school_id,
                    m.SchoolClass.class_ref == class_ref,
                )
                .scalar_subquery(),
            )
        )
        if (
            task is None
            or task.cat_binding_mode != _RESEARCH_MODE
            or task.status != "PUBLISHED"
            or task.opens_at != opens_at
            or task.due_at != due_at
        ):
            raise _conflict()
        metadata = await _get_profile_metadata(
            uow,
            school_id=actor.school_id,
            profile=profile,
            version_number=profile_version_number,
        )
        _require_profile_eligible(metadata, profile, profile_version_number)
        persisted_binding = await uow.research_cat.get_task_binding_metadata(
            school_id=actor.school_id, task_id=task.id
        )
        _require_created_binding(
            persisted_binding,
            school_id=actor.school_id,
            task_id=task.id,
            class_id=task.class_id,
            profile=profile,
            binding=binding,
            profile_version_id=metadata.profile_version_id,
            profile_version_number=profile_version_number,
        )
        await uow.research_cat.require_public_observed_task_assignments(
            school_id=actor.school_id,
            task_id=task.id,
            class_id=task.class_id,
            task_binding_id=persisted_binding.binding_id,
            expected_profile_sha256=profile.repository.expected_profile_sha256,
            expected_corpus_sha256=binding.observed_corpus_sha256,
        )
        _require_task_identity(task, profile, profile_version_number, binding)
        await self._require_trusted_study_window(
            actor=actor,
            profile=profile,
            opens_at=_aware_utc(opens_at),
            due_at=_aware_utc(due_at),
            at=_aware_utc(at),
        )
        return _view(
            task=task,
            class_ref=class_ref,
            binding_ref=binding.public.binding_ref,
            profile=profile,
            profile_version_number=profile_version_number,
            enrollment_count=await _published_enrollment_count(uow, task),
            response_origin=persisted_binding.response_origin,
        )


async def _get_profile_metadata(
    uow: Any,
    *,
    school_id: int,
    profile: ResearchProfileSelection,
    version_number: int,
) -> Any:
    try:
        return await uow.research_cat.get_profile_metadata(
            school_id=school_id,
            profile_ref=profile.public.profile_ref,
            version_number=version_number,
        )
    except Exception as exc:
        if _exception_code(exc) == _PROFILE_NOT_FOUND:
            raise _not_found() from None
        raise


def _require_profile_eligible(
    metadata: Any, profile: ResearchProfileSelection, version_number: int
) -> None:
    repository = profile.repository
    public = profile.public
    fit_sha256, calibration_sha256, crosswalk_sha256 = _parameter_pins(profile)
    if (
        type(getattr(metadata, "school_id", None)) is not int
        or metadata.school_id != public.school_id
        or getattr(metadata, "profile_ref", None) != public.profile_ref
        or type(getattr(metadata, "version_number", None)) is not int
        or metadata.version_number != version_number
        or getattr(metadata, "instrument_id", None) != public.instrument_id
        or getattr(metadata, "source_population_scope", None) != repository.source_population_scope
        or getattr(metadata, "profile_sha256", None) != repository.expected_profile_sha256
        or getattr(metadata, "manifest_sha256", None) != repository.expected_manifest_sha256
        or getattr(metadata, "parameter_origin", None) != public.parameter_origin
        or getattr(metadata, "fit_sha256", None) != fit_sha256
        or getattr(metadata, "calibration_sha256", None) != calibration_sha256
        or getattr(metadata, "published_parameter_crosswalk_sha256", None) != crosswalk_sha256
        or getattr(metadata, "research_only", None) is not True
        or getattr(metadata, "human_curated", None) is not False
        or getattr(metadata, "psychological_interpretation_allowed", None) is not False
        or getattr(metadata, "publication_status", None) != _PUBLICATION_NOT_APPROVED
        or getattr(metadata, "rights_status", None) != "VERIFIED"
        or getattr(metadata, "execution_status", None) != "SIMULATION_ENABLED"
        or getattr(metadata, "rights_revoked_at", None) is not None
        or getattr(metadata, "disabled_at", None) is not None
        or getattr(metadata, "simulation_enabled_at", None) is None
    ):
        raise _conflict()


def _catalog_profile_metadata(row: Any) -> Any:
    fields = (
        "profile_version_id",
        "school_id",
        "profile_ref",
        "version_number",
        "instrument_id",
        "source_population_scope",
        "profile_sha256",
        "manifest_sha256",
        "fit_sha256",
        "calibration_sha256",
        "parameter_origin",
        "published_parameter_crosswalk_sha256",
        "research_only",
        "human_curated",
        "psychological_interpretation_allowed",
        "publication_status",
        "rights_status",
        "execution_status",
        "rights_revoked_at",
        "disabled_at",
        "simulation_enabled_at",
    )
    try:
        values = tuple(row)
        if len(values) != len(fields):
            raise ValueError
        metadata = SimpleNamespace(**dict(zip(fields, values, strict=True)))
        if (
            type(metadata.profile_version_id) is not int
            or type(metadata.school_id) is not int
            or type(metadata.version_number) is not int
            or metadata.version_number < 1
            or type(metadata.source_population_scope) is not str
            or not 1 <= len(metadata.source_population_scope) <= 64
        ):
            raise ValueError
        return metadata
    except Exception:
        raise _dependency_error() from None


async def _audit_catalog_list(
    uow: Any,
    *,
    actor_account_id: int,
    count: int,
    success_result: Any,
) -> None:
    await uow.audit.append(
        action="school_research_tasks.catalog.list",
        resource_type=_RESOURCE_TYPE,
        resource_public_id=None,
        result=success_result,
        trace_id=get_request_context().trace_id,
        actor_account_id=actor_account_id,
        safe_metadata={
            "source": "school_research_tasks",
            "state": "READ",
            "count": count,
        },
    )


def _parameter_pins(
    profile: ResearchProfileSelection,
) -> tuple[str | None, str | None, str | None]:
    try:
        document = json.loads(profile.trusted_profile.raw_profile_bytes)
        model = document["model"]
        if profile.public.parameter_origin == "PUBLISHED_ROUNDED_REFERENCE":
            if "fit_sha256" in model or "calibration_sha256" in model:
                raise ValueError
            provenance = document["provenance"]
            crosswalk = provenance["parameter_crosswalk_sha256"]
            if type(crosswalk) is not str or not re.fullmatch(r"[0-9a-f]{64}", crosswalk):
                raise ValueError
            return None, None, crosswalk
        fit = model["fit_sha256"]
        calibration = model["calibration_sha256"]
        if any(
            type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value)
            for value in (fit, calibration)
        ):
            raise ValueError
        if "parameter_crosswalk_sha256" in document.get("provenance", {}):
            raise ValueError
        return fit, calibration, None
    except Exception:
        raise _conflict() from None


def _require_catalog_binding(
    profile: ResearchProfileSelection, binding: ResearchBindingSelection
) -> None:
    corpus = binding.observed_corpus
    if (
        binding.public.profile_ref != profile.public.profile_ref
        or binding.public.school_id != profile.public.school_id
        or binding.public.research_only is not True
        or binding.public.publication_status != _PUBLICATION_NOT_APPROVED
        or not binding.public.config_version
        or len(binding.public.config_version) > 64
        or not binding.public.config_version.isascii()
        or binding.observed_source_verified is not True
        or type(corpus) is not ObservedResponseCorpus
        or corpus.profile_ref != profile.public.profile_ref
        or corpus.profile_sha256 != profile.repository.expected_profile_sha256
        or corpus.manifest_sha256 != profile.repository.expected_manifest_sha256
        or corpus.row_count != 800
        or type(binding.observed_corpus_sha256) is not str
        or _SHA256.fullmatch(binding.observed_corpus_sha256) is None
        or binding.observed_corpus_sha256 != corpus.response_csv_sha256
        or binding.observed_corpus_row_count != 800
    ):
        raise _conflict()


def _require_created_binding(
    persisted: Any,
    *,
    school_id: int,
    task_id: int,
    class_id: int,
    profile: ResearchProfileSelection,
    binding: ResearchBindingSelection,
    profile_version_id: int,
    profile_version_number: int,
) -> None:
    if (
        getattr(persisted, "school_id", None) != school_id
        or getattr(persisted, "task_id", None) != task_id
        or getattr(persisted, "class_id", None) != class_id
        or getattr(persisted, "profile_version_id", None) != profile_version_id
        or getattr(persisted, "profile_ref", None) != profile.public.profile_ref
        or getattr(persisted, "profile_version_number", None) != profile_version_number
        or getattr(persisted, "profile_sha256", None) != profile.repository.expected_profile_sha256
        or getattr(persisted, "response_origin", None) != _RESPONSE_ORIGIN
        or getattr(persisted, "status", None) != "ACTIVE"
        or getattr(persisted, "config_version", None) != binding.public.config_version
        or getattr(persisted, "config_sha256", None) != binding.config_sha256
        or getattr(persisted, "corpus_sha256", None) != binding.observed_corpus_sha256
        or getattr(persisted, "case_count", None) != binding.observed_corpus_row_count
        or getattr(persisted, "research_only", None) is not True
        or getattr(persisted, "revoked_at", None) is not None
    ):
        raise _conflict()


def _require_created_assignments(
    assignments: Any,
    *,
    expected_count: int,
    school_id: int,
    task_id: int,
    class_id: int,
    binding_id: int,
    profile_version_id: int,
    profile_version_number: int,
    profile: ResearchProfileSelection,
    binding: ResearchBindingSelection,
    case_index_plan: tuple[int, ...],
) -> None:
    if (
        type(assignments) is not tuple
        or len(assignments) != expected_count
        or type(case_index_plan) is not tuple
        or len(case_index_plan) != expected_count
    ):
        raise _conflict()
    enrollment_ids: set[int] = set()
    case_indexes: set[int] = set()
    for assignment in assignments:
        enrollment_id = getattr(assignment, "task_enrollment_id", None)
        subject_id = getattr(assignment, "subject_id", None)
        case_index = getattr(assignment, "case_index", None)
        if (
            type(enrollment_id) is not int
            or enrollment_id <= 0
            or enrollment_id in enrollment_ids
            or type(subject_id) is not int
            or subject_id <= 0
            or type(case_index) is not int
            or not 0 <= case_index < 800
            or case_index in case_indexes
            or getattr(assignment, "school_id", None) != school_id
            or getattr(assignment, "task_id", None) != task_id
            or getattr(assignment, "class_id", None) != class_id
            or getattr(assignment, "task_binding_id", None) != binding_id
            or getattr(assignment, "profile_ref", None) != profile.public.profile_ref
            or getattr(assignment, "profile_version_id", None) != profile_version_id
            or getattr(assignment, "profile_version_number", None) != profile_version_number
            or getattr(assignment, "profile_sha256", None)
            != profile.repository.expected_profile_sha256
            or getattr(assignment, "corpus_sha256", None) != binding.observed_corpus_sha256
            or getattr(assignment, "case_count", None) != 800
        ):
            raise _conflict()
        enrollment_ids.add(enrollment_id)
        case_indexes.add(case_index)
    if tuple(getattr(item, "case_index", None) for item in assignments) != case_index_plan:
        raise _conflict()
    if expected_count == 800 and case_indexes != set(range(800)):
        raise _conflict()


def _server_case_index_plan(
    *,
    school_id: int,
    task_id: int,
    profile_sha256: str,
    corpus_sha256: str,
    enrollment_count: int,
) -> tuple[int, ...]:
    """Build a stable without-replacement plan from server/task provenance only."""

    if (
        type(school_id) is not int
        or school_id <= 0
        or type(task_id) is not int
        or task_id <= 0
        or type(profile_sha256) is not str
        or _SHA256.fullmatch(profile_sha256) is None
        or type(corpus_sha256) is not str
        or _SHA256.fullmatch(corpus_sha256) is None
        or type(enrollment_count) is not int
        or not 1 <= enrollment_count <= 800
    ):
        raise _conflict()
    seed_material = b"psynova.public-observed-case-assignment.v1\0" + b"\0".join(
        (
            school_id.to_bytes(8, "big", signed=False),
            task_id.to_bytes(8, "big", signed=False),
            bytes.fromhex(profile_sha256),
            bytes.fromhex(corpus_sha256),
        )
    )
    seed = hashlib.sha256(seed_material).digest()
    permutation = list(range(800))
    counter = 0
    for last in range(799, 0, -1):
        draw = hashlib.sha256(seed + counter.to_bytes(8, "big")).digest()
        swap = int.from_bytes(draw[:8], "big") % (last + 1)
        permutation[last], permutation[swap] = permutation[swap], permutation[last]
        counter += 1
    return tuple(permutation[:enrollment_count])


def _require_task_identity(task: Any, profile, version_number: int, binding) -> None:
    if (
        task.instrument_id != profile.public.instrument_id
        or task.instrument_version != f"research-v{version_number}"
        or task.config_version != binding.public.config_version
    ):
        raise _conflict()


async def _published_enrollment_count(uow: Any, task: Any) -> int:
    counts = await uow.school_operations.task_progress_counts(
        task_id=task.id, school_id=task.school_id
    )
    value = getattr(counts, "published_enrollment_count", None)
    if type(value) is not int or value < 0:
        raise _conflict()
    return value


async def _audit(
    uow: Any,
    *,
    actor_account_id: int,
    task_ref: str,
    trace_id: str,
    action: str,
    success_result: Any,
    study_use_policy_sha256: str,
) -> None:
    await uow.audit.append(
        action=action,
        resource_type=_RESOURCE_TYPE,
        resource_public_id=task_ref,
        result=success_result,
        trace_id=trace_id,
        actor_account_id=actor_account_id,
        safe_metadata={
            "schema_version": "psynova.research-study-use.v1",
            "component_version": study_use_policy_sha256,
            "reason_code": "ISOLATED_HISTORICAL_REPLAY",
            "source": "school_research_tasks",
            "state": "PUBLISHED",
        },
    )


def _view(
    *,
    task: Any,
    class_ref: str,
    binding_ref: str,
    profile: ResearchProfileSelection,
    profile_version_number: int,
    enrollment_count: int,
    response_origin: str,
) -> ResearchTaskPublicationView:
    return ResearchTaskPublicationView(
        task_ref=task.task_ref,
        class_ref=class_ref,
        binding_ref=binding_ref,
        profile_ref=profile.public.profile_ref,
        profile_version_number=profile_version_number,
        source_population_scope=profile.repository.source_population_scope or "unknown",
        instrument_id=task.instrument_id,
        instrument_version=task.instrument_version,
        status=task.status,
        opens_at=_aware_utc(task.opens_at),
        due_at=_aware_utc(task.due_at),
        published_at=_aware_utc(task.published_at),
        published_enrollment_count=enrollment_count,
        response_origin=response_origin,
        research_only=True,
        publication_status=_PUBLICATION_NOT_APPROVED,
    )


def _require_admin_actor(actor: Actor) -> None:
    if (
        type(actor) is not Actor
        or actor.scope_profile != "school_tenant"
        or actor.role is not BackendRole.ADMIN
        or type(actor.school_id) is not int
        or actor.school_id <= 0
        or type(actor.school_ref) is not str
        or not actor.school_ref
    ):
        raise error(ErrorCode.FORBIDDEN, detail="access denied")


def _validate_refs(class_ref: str, task_ref: str, binding_ref: str) -> None:
    if type(class_ref) is not str or not _REF.fullmatch(class_ref):
        raise error(ErrorCode.VALIDATION_FAILED, detail="research task reference is invalid")
    if type(task_ref) is not str or not _TASK_REF.fullmatch(task_ref):
        raise error(ErrorCode.VALIDATION_FAILED, detail="research task reference is invalid")
    if type(binding_ref) is not str or not _REF.fullmatch(binding_ref):
        raise error(ErrorCode.VALIDATION_FAILED, detail="research task reference is invalid")


def _validate_version(value: object) -> None:
    if type(value) is not int or not 1 <= value <= 2_147_483_647:
        raise error(ErrorCode.VALIDATION_FAILED, detail="research profile version is invalid")


def _validate_time_window(opens_at: object, due_at: object) -> None:
    _validate_at(opens_at)
    _validate_at(due_at)
    if _database_utc(due_at) <= _database_utc(opens_at):
        raise error(ErrorCode.VALIDATION_FAILED, detail="research task window is invalid")


def _validate_at(value: object) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise error(ErrorCode.VALIDATION_FAILED, detail="timestamps must include a timezone")


def _database_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _validate_idempotency(value: object) -> None:
    if (
        type(value) is not tuple
        or len(value) != 3
        or any(type(part) is not str or not part for part in value)
        or len(value[0]) > 512
        or len(value[1]) != 64
        or any(char not in "0123456789abcdef" for char in value[1])
        or len(value[2]) != 64
        or any(char not in "0123456789abcdef" for char in value[2])
    ):
        raise error(ErrorCode.VALIDATION_FAILED, detail="research idempotency is invalid")


def _exception_code(exc: BaseException) -> str | None:
    code = getattr(exc, "code", None)
    value = getattr(code, "value", code)
    return value if type(value) is str else None


def _not_found() -> BackendError:
    return error(ErrorCode.RESOURCE_NOT_FOUND, detail="research task is unavailable")


def _conflict() -> BackendError:
    return error(ErrorCode.WORKFLOW_CONFLICT, detail="research task is no longer eligible")


def _policy_denied() -> BackendError:
    return error(ErrorCode.FORBIDDEN, detail="trusted study policy does not authorize this window")


def _policy_unavailable() -> BackendError:
    return error(
        ErrorCode.DEPENDENCY_UNAVAILABLE,
        detail="trusted study policy is unavailable",
        retryable=True,
    )


def _dependency_error() -> BackendError:
    return error(
        ErrorCode.DEPENDENCY_UNAVAILABLE,
        detail="research task persistence is unavailable",
        retryable=True,
    )
