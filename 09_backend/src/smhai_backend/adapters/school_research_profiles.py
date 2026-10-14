"""Actor-scoped import and candidate listing for school research profiles.

Only an immutable server-owned catalog can supply profile bytes and trust
hashes. This adapter persists candidate metadata transactionally; it never
grants rights, enables execution, or publishes a profile.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from smhai_backend.core.errors import BackendError, ErrorCode, error
from smhai_backend.core.request_context import get_request_context
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.domains.school_research.catalog import (
    ResearchProfileSelection,
    SchoolResearchCatalog,
    SchoolResearchCatalogError,
)

_RESOURCE_TYPE = "school_research_profile_version"
_PUBLICATION_NOT_APPROVED = "not_approved_for_publication_or_operational_use"
_PROMIS_V3_PROFILE_REF = "promis-pediatric-anxiety-8-item-subset-20261014-r1"
_PROMIS_V3_SCHEMA = "psynova.research-profile.v3"
_PROMIS_V3_STORAGE_DIMENSION = "PROMIS_PEDIATRIC_ANXIETY_RESEARCH"
_NOT_FOUND = "RESEARCH_PROFILE_NOT_FOUND"
_CONFLICTS = frozenset(
    {"RESEARCH_PERSISTENCE_CONFLICT", "RESEARCH_PROFILE_HASH_MISMATCH"}
)


@dataclass(frozen=True, slots=True)
class SchoolResearchProfileView:
    """Safe profile metadata; no IDs, source bytes, or cryptographic pins."""

    profile_ref: str
    version_number: int | None
    source_population_scope: str | None
    instrument_id: str
    research_only: bool
    publication_status: str
    rights_status: str
    execution_status: str
    created_at: datetime | None
    catalog_state: str


class SchoolResearchProfilesPersistenceAdapter:
    """School-local researcher profile catalog and candidate persistence."""

    def __init__(self, owner: Any, catalog: SchoolResearchCatalog) -> None:
        if not callable(getattr(owner, "_uow", None)):
            raise TypeError("owner must provide database units of work")
        if type(catalog) is not SchoolResearchCatalog:
            raise TypeError("catalog must be an immutable SchoolResearchCatalog")
        self._owner = owner
        self._catalog = catalog

    async def list_profiles(self, actor: Actor) -> tuple[SchoolResearchProfileView, ...]:
        _require_actor(actor)
        at = _database_utc(self._owner._utc_now())
        try:
            async with self._owner._uow() as uow:
                actor_account_id, _role_id = await self._authorize(uow, actor, at)
                if actor.school_id != self._catalog.school_id:
                    raise _not_found()
                views = tuple(
                    _catalog_view(self._catalog.select_profile(item.profile_ref))
                    for item in self._catalog.public_profiles
                )
                await _audit(
                    uow,
                    actor_account_id=actor_account_id,
                    action="school_research_profiles.list",
                    resource_ref=None,
                    trace_id=get_request_context().trace_id,
                    state="READ",
                    success_result=self._owner._db_enums.AuditResult.SUCCESS,
                )
                return views
        except BackendError:
            raise
        except SchoolResearchCatalogError:
            raise _not_found() from None
        except Exception:
            raise _dependency_error() from None

    async def import_profile(
        self,
        actor: Actor,
        profile_ref: str,
        version_number: int,
        *,
        at: datetime,
        idempotency: tuple[str, str, str],
    ) -> SchoolResearchProfileView:
        _require_actor(actor)
        _validate_at(at)
        database_at = _database_utc(at)
        _validate_version(version_number)
        if type(profile_ref) is not str or not profile_ref:
            raise error(ErrorCode.VALIDATION_FAILED, detail="research profile reference is invalid")
        _validate_idempotency(idempotency)
        try:
            async with self._owner._uow() as uow:
                actor_account_id, role_id = await self._authorize(uow, actor, database_at)
                if actor.school_id != self._catalog.school_id:
                    raise _not_found()

                # Authorization deliberately precedes catalog selection and
                # access to the profile's trusted source bytes.
                selection = self._catalog.select_profile(profile_ref, school_id=actor.school_id)
                if type(selection) is not ResearchProfileSelection:
                    raise _not_found()
                claim = await self._owner._school_idempotency_begin(uow, idempotency)
                if claim.replayed:
                    return await self._replay(uow, claim, selection, version_number)

                metadata = await _existing_metadata(
                    uow,
                    school_id=actor.school_id,
                    profile_ref=profile_ref,
                    version_number=version_number,
                )
                if metadata is None:
                    kwargs = selection.repository.create_profile_version_kwargs()
                    try:
                        metadata = await uow.research_cat.create_profile_version(
                            **kwargs,
                            version_number=version_number,
                            creator_membership_role_id=role_id,
                        )
                        catalog_state = "IMPORTED_CANDIDATE"
                    except Exception as exc:
                        if _exception_code(exc) != "RESEARCH_PERSISTENCE_CONFLICT":
                            raise
                        # A concurrent exact import may have won after the
                        # initial metadata read. The repository isolates its
                        # insert in a savepoint, so re-read and compare pins.
                        metadata = await _existing_metadata(
                            uow,
                            school_id=actor.school_id,
                            profile_ref=profile_ref,
                            version_number=version_number,
                        )
                        if metadata is None:
                            raise
                        _require_exact_pins(metadata, selection, version_number)
                        catalog_state = "EXISTING_CANDIDATE"
                else:
                    _require_exact_pins(metadata, selection, version_number)
                    # Existing rights/execution state is returned as stored;
                    # a revoked or disabled version is never reset here.
                    catalog_state = "EXISTING_CANDIDATE"

                _require_exact_pins(metadata, selection, version_number)
                await self._owner._school_idempotency_complete(
                    uow,
                    claim,
                    resource_type=_RESOURCE_TYPE,
                    result_ref=profile_ref,
                )
                await _audit(
                    uow,
                    actor_account_id=actor_account_id,
                    action="school_research_profiles.import",
                    resource_ref=profile_ref,
                    trace_id=get_request_context().trace_id,
                    state="CANDIDATE_IMPORTED",
                    success_result=self._owner._db_enums.AuditResult.SUCCESS,
                )
                return _persisted_view(metadata, catalog_state)
        except BackendError:
            raise
        except SchoolResearchCatalogError:
            raise _not_found() from None
        except Exception as exc:
            code = _exception_code(exc)
            if code == _NOT_FOUND:
                raise _not_found() from None
            if code in _CONFLICTS:
                raise _conflict() from None
            raise _dependency_error() from None

    async def _authorize(self, uow: Any, actor: Actor, at: datetime) -> tuple[int, int]:
        return await self._owner._school_actor_role(
            uow, actor, "psychological_specialist", at
        )

    async def _replay(
        self, uow: Any, claim: Any, selection: ResearchProfileSelection, version_number: int
    ) -> SchoolResearchProfileView:
        record = getattr(claim, "record", None)
        public = selection.public
        if (
            record is None
            or getattr(record, "result_resource_type", None) != _RESOURCE_TYPE
            or getattr(record, "result_public_id", None) != public.profile_ref
        ):
            raise _conflict()
        metadata = await uow.research_cat.get_profile_metadata(
            school_id=self._catalog.school_id,
            profile_ref=public.profile_ref,
            version_number=version_number,
        )
        _require_exact_pins(metadata, selection, version_number)
        return _persisted_view(metadata, "IDEMPOTENT_REPLAY")


async def _existing_metadata(
    uow: Any, *, school_id: int, profile_ref: str, version_number: int
) -> Any | None:
    try:
        return await uow.research_cat.get_profile_metadata(
            school_id=school_id,
            profile_ref=profile_ref,
            version_number=version_number,
        )
    except Exception as exc:
        if _exception_code(exc) == _NOT_FOUND:
            return None
        raise


def _require_exact_pins(
    metadata: Any, selection: ResearchProfileSelection, version_number: int
) -> None:
    public = selection.public
    repository = selection.repository
    profile = repository.profile
    expected_fit, expected_calibration, expected_crosswalk = _parameter_pins(selection)
    if (
        type(getattr(metadata, "school_id", None)) is not int
        or metadata.school_id != public.school_id
        or getattr(metadata, "profile_ref", None) != public.profile_ref
        or type(getattr(metadata, "version_number", None)) is not int
        or metadata.version_number != version_number
        or getattr(metadata, "instrument_id", None) != profile.instrument_id
        or getattr(metadata, "dimension", None) != _storage_dimension(selection)
        or getattr(metadata, "source_population_scope", None)
        != repository.source_population_scope
        or getattr(metadata, "profile_sha256", None) != repository.expected_profile_sha256
        or getattr(metadata, "manifest_sha256", None) != repository.expected_manifest_sha256
        or getattr(metadata, "parameter_origin", None) != public.parameter_origin
        or getattr(metadata, "fit_sha256", None) != expected_fit
        or getattr(metadata, "calibration_sha256", None) != expected_calibration
        or getattr(metadata, "published_parameter_crosswalk_sha256", None)
        != expected_crosswalk
        or getattr(metadata, "research_only", None) is not True
        or getattr(metadata, "human_curated", None) is not False
        or getattr(metadata, "psychological_interpretation_allowed", None) is not False
        or getattr(metadata, "publication_status", None) != _PUBLICATION_NOT_APPROVED
        or type(getattr(metadata, "rights_status", None)) is not str
        or type(getattr(metadata, "execution_status", None)) is not str
        or not isinstance(getattr(metadata, "created_at", None), datetime)
    ):
        raise _conflict()


def _parameter_pins(
    selection: ResearchProfileSelection,
) -> tuple[str | None, str | None, str | None]:
    try:
        document = json.loads(selection.trusted_profile.raw_profile_bytes)
        model = document.get("model")
        if not isinstance(model, dict):
            raise ValueError
        if selection.public.parameter_origin == "PUBLISHED_ROUNDED_REFERENCE":
            if "fit_sha256" in model or "calibration_sha256" in model:
                raise ValueError
            provenance = document.get("provenance")
            crosswalk = (
                provenance.get("parameter_crosswalk_sha256")
                if isinstance(provenance, dict)
                else None
            )
            if type(crosswalk) is not str or len(crosswalk) != 64 or any(
                char not in "0123456789abcdef" for char in crosswalk
            ):
                raise ValueError
            return None, None, crosswalk
        fit = model.get("fit_sha256")
        calibration = model.get("calibration_sha256")
        if (
            type(fit) is not str
            or type(calibration) is not str
            or len(fit) != 64
            or len(calibration) != 64
            or any(char not in "0123456789abcdef" for char in fit + calibration)
        ):
            raise ValueError
        return fit, calibration, None
    except Exception:
        raise _conflict() from None


def _storage_dimension(selection: ResearchProfileSelection) -> str:
    trusted = selection.trusted_profile
    if (
        getattr(trusted, "profile_schema", None) == _PROMIS_V3_SCHEMA
        and getattr(trusted, "profile_ref", None) == _PROMIS_V3_PROFILE_REF
    ):
        return _PROMIS_V3_STORAGE_DIMENSION
    return selection.repository.profile.dimension


def _catalog_view(selection: ResearchProfileSelection) -> SchoolResearchProfileView:
    public = selection.public
    repository = selection.repository
    return SchoolResearchProfileView(
        profile_ref=public.profile_ref,
        version_number=None,
        source_population_scope=repository.source_population_scope,
        instrument_id=public.instrument_id,
        research_only=True,
        publication_status=_PUBLICATION_NOT_APPROVED,
        rights_status=repository.rights_status,
        execution_status=repository.execution_status,
        created_at=None,
        catalog_state="REGISTRY_CANDIDATE",
    )


def _persisted_view(metadata: Any, catalog_state: str) -> SchoolResearchProfileView:
    return SchoolResearchProfileView(
        profile_ref=metadata.profile_ref,
        version_number=metadata.version_number,
        source_population_scope=metadata.source_population_scope,
        instrument_id=metadata.instrument_id,
        research_only=True,
        publication_status=_PUBLICATION_NOT_APPROVED,
        rights_status=metadata.rights_status,
        execution_status=metadata.execution_status,
        created_at=metadata.created_at,
        catalog_state=catalog_state,
    )


async def _audit(
    uow: Any,
    *,
    actor_account_id: int,
    action: str,
    resource_ref: str | None,
    trace_id: str,
    state: str,
    success_result: Any,
) -> None:
    await uow.audit.append(
        action=action,
        resource_type=_RESOURCE_TYPE,
        resource_public_id=resource_ref,
        result=success_result,
        trace_id=trace_id,
        actor_account_id=actor_account_id,
        safe_metadata={"source": "school_research_profiles", "state": state},
    )

def _require_actor(actor: Actor) -> None:
    if (
        type(actor) is not Actor
        or actor.scope_profile != "school_tenant"
        or actor.role is not BackendRole.PSYCHOLOGICAL_SPECIALIST
        or type(actor.school_id) is not int
        or actor.school_id <= 0
        or type(actor.school_ref) is not str
        or not actor.school_ref
    ):
        raise error(ErrorCode.FORBIDDEN, detail="access denied")


def _validate_at(value: object) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise error(ErrorCode.VALIDATION_FAILED, detail="request time is invalid")


def _database_utc(value: datetime) -> datetime:
    """Normalize the database layer's naive-UTC timestamp convention."""

    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=None)
    return value.astimezone(UTC).replace(tzinfo=None)


def _validate_version(value: object) -> None:
    if type(value) is not int or not 1 <= value <= 2_147_483_647:
        raise error(ErrorCode.VALIDATION_FAILED, detail="profile version is invalid")


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
    return error(ErrorCode.RESOURCE_NOT_FOUND, detail="research profile is unavailable")


def _conflict() -> BackendError:
    return error(ErrorCode.WORKFLOW_CONFLICT, detail="research profile changed or is unavailable")


def _dependency_error() -> BackendError:
    return error(
        ErrorCode.DEPENDENCY_UNAVAILABLE,
        detail="research profile persistence is unavailable",
        retryable=True,
    )
