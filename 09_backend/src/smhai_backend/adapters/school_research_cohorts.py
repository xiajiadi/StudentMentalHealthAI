"""Atomic, school-scoped cohort sealing from trusted public corpus selectors.

No research response payload or credentials are loaded by this adapter. The
existing task catalog's provenance and limited-study guard remain authoritative.
"""

from __future__ import annotations

import re
from random import SystemRandom
from typing import Any
from uuid import uuid4

from smhai_backend.adapters.school_research_tasks import (
    SchoolResearchTasksPersistenceAdapter,
    _database_utc,
    _dependency_error,
    _get_profile_metadata,
    _not_found,
    _require_admin_actor,
    _require_catalog_binding,
    _require_profile_eligible,
    _validate_at,
    _validate_idempotency,
    _validate_version,
)
from smhai_backend.core.errors import BackendError, ErrorCode, error
from smhai_backend.core.request_context import get_request_context
from smhai_backend.domains.models import Actor
from smhai_backend.domains.school_research.catalog import SchoolResearchCatalogError
from smhai_backend.domains.school_research.study_use import ResearchStudyUseError

_RESOURCE_TYPE = "school_research_cohort"
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_PUBLICATION = "not_approved_for_publication_or_operational_use"


class SchoolResearchCohortsPersistenceAdapter:
    def __init__(self, task_guard: SchoolResearchTasksPersistenceAdapter) -> None:
        if type(task_guard) is not SchoolResearchTasksPersistenceAdapter:
            raise TypeError("cohort sealing requires the configured research task guard")
        self._guard = task_guard
        self._owner = task_guard._owner
        self._catalog = task_guard._catalog

    async def seal_cohort(
        self,
        actor: Actor,
        *,
        binding_ref: str,
        profile_version_number: int,
        batch_refs: tuple[str, ...],
        at: Any,
        idempotency: tuple[str, str, str],
    ) -> dict[str, Any]:
        _require_admin_actor(actor)
        _validate_at(at)
        _validate_version(profile_version_number)
        _validate_idempotency(idempotency)
        if (
            type(binding_ref) is not str
            or _REF.fullmatch(binding_ref) is None
            or type(batch_refs) is not tuple
            or len(batch_refs) != 8
            or any(type(ref) is not str or _REF.fullmatch(ref) is None for ref in batch_refs)
            or len(set(batch_refs)) != 8
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="research cohort selectors are invalid")
        try:
            async with self._owner._uow() as uow:
                account_id, role_id = await self._owner._school_actor_role(
                    uow, actor, "admin", _database_utc(at)
                )
                if actor.school_id != self._catalog.school_id:
                    raise _not_found()
                binding = self._catalog.select_binding(binding_ref, school_id=actor.school_id)
                profile = self._catalog.select_profile(
                    binding.public.profile_ref, school_id=actor.school_id
                )
                _require_catalog_binding(profile, binding)
                policy = self._guard._require_catalog_policy(at=at)
                profile_metadata = await _get_profile_metadata(
                    uow, school_id=actor.school_id, profile=profile,
                    version_number=profile_version_number,
                )
                _require_profile_eligible(profile_metadata, profile, profile_version_number)
                self._guard._require_current_catalog_profile_policy(
                    policy, actor=actor, profile=profile, metadata=profile_metadata, at=at
                )
                claim = await self._owner._school_idempotency_begin(uow, idempotency)
                arguments = {
                    "school_id": actor.school_id,
                    "study_ref": policy.study_ref,
                    "profile_version_id": profile_metadata.profile_version_id,
                    "profile_ref": profile.public.profile_ref,
                    "profile_version_number": profile_version_number,
                    "expected_profile_sha256": profile.repository.expected_profile_sha256,
                    "expected_manifest_sha256": profile.repository.expected_manifest_sha256,
                    "expected_corpus_sha256": binding.observed_corpus_sha256,
                    "batch_refs": tuple(sorted(batch_refs)),
                }
                if claim.replayed:
                    record = getattr(claim, "record", None)
                    reference = getattr(record, "result_public_id", None)
                    if (
                        getattr(record, "result_resource_type", None) != _RESOURCE_TYPE
                        or type(reference) is not str
                        or _REF.fullmatch(reference) is None
                    ):
                        raise _conflict()
                    metadata = await uow.research_cohorts.require_existing_cohort_matches(
                        cohort_ref=reference, **arguments,
                    )
                else:
                    # This is a mapping permutation of all already-pinned cases,
                    # not a new calibration sample or a measurement parameter.
                    plan = list(range(800))
                    SystemRandom().shuffle(plan)
                    metadata = await uow.research_cohorts.seal_cohort(
                        cohort_ref=f"COHORT_R_{uuid4().hex}",
                        creator_membership_role_id=role_id,
                        case_index_plan=tuple(plan),
                        at=_database_utc(at),
                        **arguments,
                    )
                    await self._owner._school_idempotency_complete(
                        uow, claim, resource_type=_RESOURCE_TYPE, result_ref=metadata.cohort_ref,
                    )
                    await uow.audit.append(
                        action="school_research_cohorts.sealed",
                        resource_type=_RESOURCE_TYPE,
                        resource_public_id=metadata.cohort_ref,
                        result=self._owner._db_enums.AuditResult.SUCCESS,
                        trace_id=get_request_context().trace_id,
                        actor_account_id=account_id,
                        safe_metadata={"source": "school_research_cohorts", "state": "SEALED"},
                    )
                if (
                    metadata.subject_count != 800 or metadata.class_count != 8
                    or metadata.case_count != 800
                ):
                    raise _conflict()
                # Explicit projection: internal IDs, hashes and assignments must
                # not leak through dataclass serialization or generic envelopes.
                return {
                    "cohort_ref": metadata.cohort_ref,
                    "study_ref": metadata.study_ref,
                    "profile_ref": metadata.profile_ref,
                    "profile_version_number": metadata.profile_version_number,
                    "source_population_scope": profile_metadata.source_population_scope,
                    "instrument_id": profile_metadata.instrument_id,
                    "status": "SEALED",
                    "subject_count": metadata.subject_count,
                    "class_count": metadata.class_count,
                    "assigned_distinct_cases": metadata.case_count,
                    "sealed_at": metadata.sealed_at,
                    "response_origin": "PUBLIC_OBSERVED",
                    "research_only": True,
                    "publication_status": _PUBLICATION,
                }
        except BackendError:
            raise
        except SchoolResearchCatalogError:
            raise _not_found() from None
        except ResearchStudyUseError:
            raise error(ErrorCode.FORBIDDEN, detail="research study scope is unavailable") from None
        except Exception as exc:
            code = str(getattr(exc, "code", ""))
            if code in {"COHORT_NOT_FOUND", "CASE_ASSIGNMENT_NOT_FOUND"}:
                raise _not_found() from None
            if code in {
                "INVALID_INPUT", "PROFILE_NOT_ELIGIBLE", "COHORT_EXISTS",
                "COHORT_SCOPE_MISMATCH", "COHORT_MEMBERSHIP_INVALID", "PERSISTENCE_CONFLICT",
            }:
                raise _conflict() from None
            raise _dependency_error() from None


def _conflict():
    return error(ErrorCode.WORKFLOW_CONFLICT, detail="research cohort state has changed")
