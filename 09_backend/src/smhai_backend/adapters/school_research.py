"""Two-phase, actor-scoped persistence composition for private research CAT.

This adapter owns short database transactions only. A service may call the
client between ``prepare_*`` and ``commit_*``; no HTTP request runs while a
unit of work is open. Its plans and signed snapshot fields are Backend-private
and must never be projected directly to an API response. The service owns the
client lifetime and must close the captured client after its operation.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from smhai_backend.adapters.database import SchoolIdempotencyClaim
from smhai_backend.core.errors import BackendError, ErrorCode, error
from smhai_backend.domains.models import Actor
from smhai_backend.domains.school_research.authorization import (
    ResearchScopeResolutionError,
    ResearchStudentScope,
    resolve_research_student_scope,
)
from smhai_backend.domains.school_research.client import (
    ResearchCATClientError,
    ResearchCATSnapshotForPersistence,
)
from smhai_backend.domains.school_research.study_use import (
    ResearchStudyProfilePin,
    ResearchStudyUseError,
    ResearchStudyUsePolicy,
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_RESOURCE_TYPE = "research_session"
_NOT_FOUND_CODES = frozenset(
    {
        "RESEARCH_PROFILE_NOT_FOUND",
        "RESEARCH_TASK_NOT_FOUND",
        "RESEARCH_BINDING_NOT_FOUND",
        "RESEARCH_SESSION_NOT_FOUND",
    }
)
_CONFLICT_CODES = frozenset(
    {
        "RESEARCH_PROFILE_HASH_MISMATCH",
        "RESEARCH_PROFILE_NOT_ELIGIBLE",
        "RESEARCH_PROFILE_RIGHTS_REVOKED",
        "RESEARCH_TASK_MODE_MISMATCH",
        "RESEARCH_SCOPE_MISMATCH",
        "RESEARCH_BINDING_NOT_ACTIVE",
        "RESEARCH_CONFIG_HASH_MISMATCH",
        "RESEARCH_SESSION_DISABLED",
        "RESEARCH_SESSION_CONFLICT",
        "RESEARCH_CONCURRENCY_CONFLICT",
        "RESEARCH_PERSISTENCE_CONFLICT",
    }
)
_POLICY_DENIAL_CODES = frozenset(
    {"scope_denied", "task_window_invalid", "task_window_outside_policy"}
)


@dataclass(frozen=True, slots=True)
class ResearchSessionReceipt:
    """Lifecycle-only safe projection; no signed state or response content."""

    session_ref: str = field(repr=False)
    task_ref: str = field(repr=False)
    enrollment_ref: str = field(repr=False)
    subject_ref: str = field(repr=False)
    profile_ref: str = field(repr=False)
    profile_version_number: int
    profile_sha256: str = field(repr=False)
    config_version: str = field(repr=False)
    config_sha256: str = field(repr=False)
    status: str
    state_version: int
    items_answered: int
    stop_reason: str | None
    started_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class ResearchSessionPersistenceResult:
    """A stored receipt and explicit state-acceptance/replay disposition."""

    metadata: ResearchSessionReceipt
    persisted: bool
    replayed: bool
    state_accepted: bool


@dataclass(frozen=True, slots=True, repr=False)
class _ScopePin:
    account_id: int
    membership_role_id: int
    school_id: int
    school_ref: str = field(repr=False)
    task_id: int
    task_ref: str = field(repr=False)
    class_id: int
    class_ref: str = field(repr=False)
    task_enrollment_id: int
    enrollment_ref: str = field(repr=False)
    subject_id: int
    subject_ref: str = field(repr=False)


@dataclass(frozen=True, slots=True, repr=False)
class _ResolvedLockedScope:
    candidate: ResearchStudentScope = field(repr=False)
    locked: Any = field(repr=False)

    def __getattr__(self, name: str) -> Any:
        if name == "binding":
            return self.locked.binding
        if name == "enrollment_ref":
            return self.candidate.task_enrollment_ref
        if name == "principal_account_id":
            return self.candidate.account_id
        if name == "membership_role_id":
            return self.candidate.membership_role_id
        return getattr(self.candidate, name)


@dataclass(frozen=True, slots=True, repr=False)
class ResearchStartPlan:
    """Short-lived server plan/client returned after authorization and rollback."""

    scope: _ScopePin = field(repr=False)
    binding_metadata: Any = field(repr=False)
    client: Any | None = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True, repr=False)
class ResearchAnswerPlan:
    """Short-lived authorized resume input; snapshot text is never repr'd."""

    scope: _ScopePin = field(repr=False)
    binding_metadata: Any = field(repr=False)
    client: Any | None = field(repr=False, compare=False)
    session_ref: str = field(repr=False)
    profile_ref: str = field(repr=False)
    config_version: str = field(repr=False)
    profile_sha256: str = field(repr=False)
    config_sha256: str = field(repr=False)
    expected_state_version: int
    items_answered: int
    signed_snapshot_json: str = field(repr=False)
    observed_response: tuple[str, int] | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True, repr=False)
class ResearchResumePlan:
    """Authorized active-session restore input with a private HTTP client."""

    scope: _ScopePin = field(repr=False)
    binding_metadata: Any = field(repr=False)
    client: Any | None = field(repr=False, compare=False)
    session_ref: str = field(repr=False)
    profile_ref: str = field(repr=False)
    config_version: str = field(repr=False)
    profile_sha256: str = field(repr=False)
    config_sha256: str = field(repr=False)
    state_version: int
    items_answered: int
    signed_snapshot_json: str = field(repr=False)


class _RollbackPrepared(Exception):
    """Internal signal: roll back a tentative idempotency claim before HTTP."""

    def __init__(self, plan: ResearchStartPlan | ResearchAnswerPlan) -> None:
        self.plan = plan
        super().__init__("prepared")


class SchoolResearchPersistenceAdapter:
    """Compose current student authorization with immutable research storage.

    ``client_for_binding`` is injected by the server and receives only the
    repository's freshly locked binding metadata. It must return a client
    pinned to server-owned profile/config hashes and an injected snapshot
    verifier. No caller-supplied hash or client identity is accepted here.
    """

    def __init__(
        self,
        owner: Any,
        *,
        client_for_binding: Callable[[Any], Any],
        study_use_policy: ResearchStudyUsePolicy | None = None,
        observed_corpus_for_binding: Callable[[Any], Any] | None = None,
    ) -> None:
        if not callable(getattr(owner, "_uow", None)):
            raise TypeError("owner must provide short-lived database units of work")
        if not callable(client_for_binding):
            raise TypeError("client_for_binding must be injected")
        self._owner = owner
        self._client_for_binding = client_for_binding
        self._study_use_policy = study_use_policy
        self._observed_corpus_for_binding = observed_corpus_for_binding

    def client_for_binding(self, binding_metadata: Any) -> Any:
        """Create the injected, server-pinned client outside any UOW."""

        try:
            client = self._client_for_binding(binding_metadata)
        except Exception:
            raise _dependency_error() from None
        if not callable(getattr(client, "snapshot_for_persistence", None)):
            raise _dependency_error()
        return client

    async def prepare_start(
        self,
        actor: Actor,
        task_ref: str,
        *,
        at: datetime,
        idempotency: tuple[str, str, str],
    ) -> ResearchStartPlan | ResearchSessionPersistenceResult:
        """Authorize, detect replay, and return a plan before CAT HTTP work."""

        _validate_reference(task_ref)
        _validate_idempotency(idempotency)
        try:
            try:
                async with self._owner._uow() as uow:
                    scope = await self._resolve_and_lock(uow, actor, at=at, task_ref=task_ref)
                    claim = await self._owner._school_idempotency_begin(uow, idempotency)
                    if claim.replayed:
                        return await self._replay_result(
                            uow,
                            claim,
                            scope,
                            required_task_ref=task_ref,
                            requested_session_ref=None,
                        )
                    if await self._session_for_enrollment(uow, scope) is not None:
                        raise _conflict_error()
                    plan = ResearchStartPlan(
                        scope=_scope_pin(scope),
                        binding_metadata=scope.binding.metadata,
                        client=None,
                    )
                    # The helper's tentative IN_PROGRESS row is not durable.
                    # This exact sentinel forces rollback before the caller
                    # invokes the HTTP client.
                    raise _RollbackPrepared(plan)
            except _RollbackPrepared as prepared:
                if type(prepared.plan) is not ResearchStartPlan:
                    raise _dependency_error() from None
                client = self.client_for_binding(prepared.plan.binding_metadata)
                return ResearchStartPlan(
                    scope=prepared.plan.scope,
                    binding_metadata=prepared.plan.binding_metadata,
                    client=client,
                )
        except BackendError:
            raise
        except ResearchScopeResolutionError:
            raise _not_found_error() from None
        except Exception as exc:
            raise _translate_error(exc) from None

    async def commit_start(
        self,
        actor: Actor,
        plan: ResearchStartPlan,
        state: Any,
        *,
        at: datetime,
        trace_id: str,
        idempotency: tuple[str, str, str],
    ) -> ResearchSessionPersistenceResult:
        """Verify a CAT start state and commit it with the durable receipt."""

        if type(plan) is not ResearchStartPlan:
            raise error(ErrorCode.VALIDATION_FAILED, detail="research start plan is invalid")
        if not callable(getattr(plan.client, "snapshot_for_persistence", None)):
            raise error(ErrorCode.VALIDATION_FAILED, detail="research start plan is invalid")
        _validate_idempotency(idempotency)
        try:
            async with self._owner._uow() as uow:
                scope = await self._resolve_and_lock(
                    uow, actor, at=at, task_ref=plan.scope.task_ref
                )
                _require_same_scope(plan.scope, scope)
                if not _binding_matches_plan(scope.binding.metadata, plan.binding_metadata):
                    raise _conflict_error()
                claim = await self._owner._school_idempotency_begin(uow, idempotency)
                if claim.replayed:
                    return await self._replay_result(
                        uow,
                        claim,
                        scope,
                        required_task_ref=plan.scope.task_ref,
                        requested_session_ref=None,
                    )

                current = await self._session_for_enrollment(uow, scope)
                if current is not None:
                    metadata = await self._metadata_for_ref(
                        uow, school_id=scope.school_id, session_ref=current.session_ref
                    )
                    self._require_metadata_scope(metadata, scope)
                    await self._owner._school_idempotency_complete(
                        uow,
                        claim,
                        resource_type=_RESOURCE_TYPE,
                        result_ref=metadata.session_ref,
                    )
                    return _result(
                        metadata,
                        scope,
                        persisted=True,
                        replayed=False,
                        state_accepted=False,
                    )

                _validate_start_state(state, scope.binding.metadata)
                snapshot = _verified_repository_mapping(plan.client, state)
                repo_result = await uow.research_cat.create_or_load_session(
                    school_id=scope.school_id,
                    task_id=scope.task_id,
                    task_enrollment_id=scope.task_enrollment_id,
                    subject_id=scope.subject_id,
                    session_ref=state.session_ref,
                    expected_profile_sha256=scope.binding.metadata.profile_sha256,
                    expected_config_sha256=scope.binding.metadata.config_sha256,
                    signed_snapshot=snapshot,
                    trace_id=trace_id,
                )
                metadata = repo_result.metadata
                self._require_metadata_scope(metadata, scope)
                if (
                    metadata.session_ref != state.session_ref
                    or metadata.state_version != 1
                    or metadata.items_answered != 0
                    or metadata.status != "IN_PROGRESS"
                ):
                    raise _conflict_error()
                await self._owner._school_idempotency_complete(
                    uow,
                    claim,
                    resource_type=_RESOURCE_TYPE,
                    result_ref=metadata.session_ref,
                )
                return _result(
                    metadata,
                    scope,
                    persisted=True,
                    replayed=False,
                    state_accepted=True,
                )
        except BackendError:
            raise
        except ResearchScopeResolutionError:
            raise _not_found_error() from None
        except Exception as exc:
            raise _translate_error(exc) from None

    async def prepare_answer(
        self,
        actor: Actor,
        session_ref: str,
        *,
        expected_state_version: int,
        item_id: str,
        raw_value: int,
        at: datetime,
        idempotency: tuple[str, str, str],
    ) -> ResearchAnswerPlan | ResearchSessionPersistenceResult:
        """Reauthorize, verify expected CAS version, and load opaque state."""

        _validate_reference(session_ref)
        _validate_positive_int(expected_state_version, "state version")
        _validate_reference(item_id)
        if type(raw_value) is not int:
            raise _conflict_error()
        _validate_idempotency(idempotency)
        school_id = _actor_school_id(actor)
        try:
            try:
                async with self._owner._uow() as uow:
                    session_metadata = await self._metadata_for_ref(
                        uow, school_id=school_id, session_ref=session_ref
                    )
                    scope = await self._resolve_session_and_lock(
                        uow,
                        actor,
                        at=at,
                        metadata=session_metadata,
                        observed_response=(item_id, raw_value),
                    )
                    self._require_metadata_scope(session_metadata, scope)
                    claim = await self._owner._school_idempotency_begin(uow, idempotency)
                    if claim.replayed:
                        return await self._replay_result(
                            uow,
                            claim,
                            scope,
                            required_task_ref=scope.task_ref,
                            requested_session_ref=session_ref,
                            known_metadata=session_metadata,
                        )
                    if session_metadata.status != "IN_PROGRESS":
                        raise _conflict_error()
                    if session_metadata.state_version != expected_state_version:
                        raise _conflict_error()
                    repo_state = await uow.research_cat.load_session_for_resume(
                        school_id=scope.school_id,
                        session_ref=session_ref,
                        expected_profile_sha256=scope.binding.metadata.profile_sha256,
                        expected_config_sha256=scope.binding.metadata.config_sha256,
                    )
                    self._require_metadata_scope(repo_state.metadata, scope)
                    if (
                        repo_state.metadata.session_ref != session_ref
                        or repo_state.metadata.state_version != expected_state_version
                        or repo_state.metadata.status != "IN_PROGRESS"
                    ):
                        raise _conflict_error()
                    plan = ResearchAnswerPlan(
                        scope=_scope_pin(scope),
                        binding_metadata=scope.binding.metadata,
                        client=None,
                        session_ref=session_ref,
                        profile_ref=repo_state.metadata.profile_ref,
                        config_version=repo_state.metadata.config_version,
                        profile_sha256=repo_state.metadata.profile_sha256,
                        config_sha256=repo_state.metadata.config_sha256,
                        expected_state_version=expected_state_version,
                        items_answered=repo_state.metadata.items_answered,
                        signed_snapshot_json=repo_state.signed_snapshot_json,
                        observed_response=(item_id, raw_value),
                    )
                    raise _RollbackPrepared(plan)
            except _RollbackPrepared as prepared:
                if type(prepared.plan) is not ResearchAnswerPlan:
                    raise _dependency_error() from None
                client = self.client_for_binding(prepared.plan.binding_metadata)
                return ResearchAnswerPlan(
                    scope=prepared.plan.scope,
                    binding_metadata=prepared.plan.binding_metadata,
                    client=client,
                    session_ref=prepared.plan.session_ref,
                    profile_ref=prepared.plan.profile_ref,
                    config_version=prepared.plan.config_version,
                    profile_sha256=prepared.plan.profile_sha256,
                    config_sha256=prepared.plan.config_sha256,
                    expected_state_version=prepared.plan.expected_state_version,
                    items_answered=prepared.plan.items_answered,
                    signed_snapshot_json=prepared.plan.signed_snapshot_json,
                    observed_response=prepared.plan.observed_response,
                )
        except BackendError:
            raise
        except ResearchScopeResolutionError:
            raise _not_found_error() from None
        except Exception as exc:
            raise _translate_error(exc) from None

    async def commit_answer(
        self,
        actor: Actor,
        plan: ResearchAnswerPlan,
        state: Any,
        *,
        at: datetime,
        idempotency: tuple[str, str, str],
    ) -> ResearchSessionPersistenceResult:
        """Verify the signed state and save one answer under repository CAS."""

        if type(plan) is not ResearchAnswerPlan:
            raise error(ErrorCode.VALIDATION_FAILED, detail="research answer plan is invalid")
        if not callable(getattr(plan.client, "snapshot_for_persistence", None)):
            raise error(ErrorCode.VALIDATION_FAILED, detail="research answer plan is invalid")
        _validate_idempotency(idempotency)
        school_id = _actor_school_id(actor)
        try:
            async with self._owner._uow() as uow:
                # Metadata-only lookup allows a completed idempotency replay to
                # remain readable without attempting to decrypt/resume terminal
                # state. The task scope and current SELF grant are still fresh.
                current = await self._metadata_for_ref(
                    uow, school_id=school_id, session_ref=plan.session_ref
                )
                if plan.observed_response is None:
                    raise _conflict_error()
                scope = await self._resolve_session_and_lock(
                    uow,
                    actor,
                    at=at,
                    metadata=current,
                    observed_response=plan.observed_response,
                )
                self._require_metadata_scope(current, scope)
                _require_same_scope(plan.scope, scope)
                claim = await self._owner._school_idempotency_begin(uow, idempotency)
                if claim.replayed:
                    result = await self._replay_result(
                        uow,
                        claim,
                        scope,
                        required_task_ref=plan.scope.task_ref,
                        requested_session_ref=plan.session_ref,
                        known_metadata=current,
                    )
                    return result
                if (
                    current.status != "IN_PROGRESS"
                    or current.state_version != plan.expected_state_version
                    or current.items_answered != plan.items_answered
                    or not _binding_matches_plan(scope.binding.metadata, plan.binding_metadata)
                ):
                    raise _conflict_error()
                _validate_answer_state(state, plan, scope.binding.metadata)
                snapshot = _verified_repository_mapping(plan.client, state)
                metadata = await uow.research_cat.save_session_snapshot(
                    school_id=scope.school_id,
                    session_ref=plan.session_ref,
                    expected_state_version=plan.expected_state_version,
                    expected_profile_sha256=scope.binding.metadata.profile_sha256,
                    expected_config_sha256=scope.binding.metadata.config_sha256,
                    signed_snapshot=snapshot,
                )
                self._require_metadata_scope(metadata, scope)
                if (
                    metadata.session_ref != plan.session_ref
                    or metadata.state_version != plan.expected_state_version + 1
                    or metadata.items_answered != plan.items_answered + 1
                    or metadata.status
                    != ("COMPLETED" if state.status == "COMPLETED" else "IN_PROGRESS")
                ):
                    raise _conflict_error()
                await self._owner._school_idempotency_complete(
                    uow,
                    claim,
                    resource_type=_RESOURCE_TYPE,
                    result_ref=metadata.session_ref,
                )
                return _result(
                    metadata,
                    scope,
                    persisted=True,
                    replayed=False,
                    state_accepted=True,
                )
        except BackendError:
            raise
        except ResearchScopeResolutionError:
            raise _not_found_error() from None
        except Exception as exc:
            raise _translate_error(exc) from None

    async def prepare_resume(
        self,
        actor: Actor,
        session_ref: str,
        *,
        at: datetime,
    ) -> ResearchResumePlan:
        """Authorize and decrypt only an active session for stateless resume."""

        _validate_reference(session_ref)
        school_id = _actor_school_id(actor)
        try:
            async with self._owner._uow() as uow:
                session_metadata = await self._metadata_for_ref(
                    uow, school_id=school_id, session_ref=session_ref
                )
                scope = await self._resolve_session_and_lock(
                    uow, actor, at=at, metadata=session_metadata
                )
                self._require_metadata_scope(session_metadata, scope)
                if session_metadata.status != "IN_PROGRESS":
                    raise _conflict_error()
                repo_state = await uow.research_cat.load_session_for_resume(
                    school_id=scope.school_id,
                    session_ref=session_ref,
                    expected_profile_sha256=scope.binding.metadata.profile_sha256,
                    expected_config_sha256=scope.binding.metadata.config_sha256,
                )
                self._require_metadata_scope(repo_state.metadata, scope)
                if (
                    repo_state.metadata.session_ref != session_ref
                    or repo_state.metadata.state_version != session_metadata.state_version
                    or repo_state.metadata.items_answered != session_metadata.items_answered
                    or repo_state.metadata.status != "IN_PROGRESS"
                ):
                    raise _conflict_error()
                plan = ResearchResumePlan(
                    scope=_scope_pin(scope),
                    binding_metadata=scope.binding.metadata,
                    client=None,
                    session_ref=session_ref,
                    profile_ref=repo_state.metadata.profile_ref,
                    config_version=repo_state.metadata.config_version,
                    profile_sha256=repo_state.metadata.profile_sha256,
                    config_sha256=repo_state.metadata.config_sha256,
                    state_version=repo_state.metadata.state_version,
                    items_answered=repo_state.metadata.items_answered,
                    signed_snapshot_json=repo_state.signed_snapshot_json,
                )
            client = self.client_for_binding(plan.binding_metadata)
            return ResearchResumePlan(
                scope=plan.scope,
                binding_metadata=plan.binding_metadata,
                client=client,
                session_ref=plan.session_ref,
                profile_ref=plan.profile_ref,
                config_version=plan.config_version,
                profile_sha256=plan.profile_sha256,
                config_sha256=plan.config_sha256,
                state_version=plan.state_version,
                items_answered=plan.items_answered,
                signed_snapshot_json=plan.signed_snapshot_json,
            )
        except BackendError:
            raise
        except ResearchScopeResolutionError:
            raise _not_found_error() from None
        except Exception as exc:
            raise _translate_error(exc) from None

    async def _resolve_and_lock(
        self,
        uow: Any,
        actor: Actor,
        *,
        at: datetime,
        task_ref: str | None = None,
        session_ref: str | None = None,
        observed_response: tuple[str, int] | None = None,
    ) -> Any:
        owner = self._owner

        async def resolve_role(_actor: Actor, role_at: datetime) -> tuple[int, int]:
            return await owner._school_actor_role(uow, actor, "student", role_at, lock=True)

        candidate: ResearchStudentScope = await resolve_research_student_scope(
            session=uow.session,
            actor=actor,
            db_models=owner._db_models,
            db_enums=owner._db_enums,
            select=owner._select,
            resolve_student_role=resolve_role,
            at=at,
            task_ref=task_ref,
            session_ref=session_ref,
        )
        self._require_study_policy_configured()

        def require_study_scope(profile_metadata: Any, binding_metadata: Any) -> None:
            self._require_trusted_study_scope(candidate, profile_metadata, binding_metadata, at=at)

        async def require_observed_scope(profile_metadata: Any, binding_metadata: Any) -> None:
            factory = self._observed_corpus_for_binding
            if not callable(factory):
                raise _dependency_error()
            corpus = factory(binding_metadata)
            cohort_study = {}
            if getattr(binding_metadata, "cohort_id", None) is not None:
                # A new policy with the same profile pins must not silently
                # adopt a cohort sealed for a different research study.
                policy = self._require_study_policy_configured()
                study_ref = getattr(policy, "study_ref", None)
                if (
                    type(study_ref) is not str
                    or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", study_ref) is None
                ):
                    raise _study_policy_unavailable()
                cohort_study = {"expected_study_ref": study_ref}
            assignment = await uow.research_cat.require_public_observed_case_assignment(
                profile=profile_metadata,
                binding=binding_metadata,
                task_enrollment_id=candidate.task_enrollment_id,
                subject_id=candidate.subject_id,
                expected_profile_sha256=corpus.profile_sha256,
                expected_corpus_sha256=corpus.response_csv_sha256,
                **cohort_study,
            )
            if observed_response is not None and not corpus.matches(
                assignment.case_index, observed_response[0], observed_response[1]
            ):
                raise _conflict_error()

        locked = await uow.research_cat.lock_student_task_scope(
            school_id=candidate.school_id,
            task_id=candidate.task_id,
            task_enrollment_id=candidate.task_enrollment_id,
            subject_id=candidate.subject_id,
            principal_account_id=candidate.account_id,
            at=at,
            require_study_scope=require_study_scope,
            require_observed_scope=require_observed_scope,
        )
        if (
            locked.school_id != candidate.school_id
            or locked.task_id != candidate.task_id
            or locked.class_id != candidate.class_id
            or locked.task_enrollment_id != candidate.task_enrollment_id
            or locked.subject_id != candidate.subject_id
            or locked.principal_account_id != candidate.account_id
            or locked.task_ref != candidate.task_ref
            or locked.class_ref != candidate.class_ref
            or locked.enrollment_ref != candidate.task_enrollment_ref
            or locked.subject_ref != candidate.subject_ref
        ):
            raise _not_found_error()
        _validate_binding_metadata(locked.binding.metadata)
        scope = _ResolvedLockedScope(candidate=candidate, locked=locked)
        return scope

    def _require_study_policy_configured(self) -> ResearchStudyUsePolicy:
        policy = self._study_use_policy
        if (
            policy is None
            or getattr(policy, "source_rights_verified", None) is not True
            or not callable(getattr(policy, "require_scope", None))
        ):
            raise _study_policy_unavailable()
        return policy

    def _require_trusted_study_scope(
        self,
        candidate: ResearchStudentScope,
        profile_metadata: Any,
        binding: Any,
        *,
        at: datetime,
    ) -> None:
        policy = self._require_study_policy_configured()
        if (
            type(getattr(profile_metadata, "school_id", None)) is not int
            or getattr(profile_metadata, "school_id", None) != candidate.school_id
            or getattr(profile_metadata, "profile_ref", None) != binding.profile_ref
            or type(getattr(profile_metadata, "profile_version_id", None)) is not int
            or getattr(profile_metadata, "profile_version_id", None) != binding.profile_version_id
            or type(getattr(profile_metadata, "version_number", None)) is not int
            or getattr(profile_metadata, "version_number", None) != binding.profile_version_number
            or getattr(profile_metadata, "profile_sha256", None) != binding.profile_sha256
            or type(getattr(profile_metadata, "manifest_sha256", None)) is not str
            or _SHA256.fullmatch(profile_metadata.manifest_sha256) is None
        ):
            raise _conflict_error()

        try:
            policy_pin = policy.require_scope(
                school_id=candidate.school_id,
                profile_ref=binding.profile_ref,
                profile_sha256=binding.profile_sha256,
                manifest_sha256=profile_metadata.manifest_sha256,
                at=_aware_utc(at),
            )
        except BackendError:
            raise
        except ResearchStudyUseError as exc:
            if exc.code in _POLICY_DENIAL_CODES:
                raise _study_policy_denied() from None
            if exc.code == "profile_pin_mismatch":
                raise _conflict_error() from None
            raise _study_policy_unavailable() from None
        except Exception:
            raise _study_policy_unavailable() from None

        if (
            type(policy_pin) is not ResearchStudyProfilePin
            or policy_pin.profile_ref != binding.profile_ref
            or policy_pin.profile_sha256 != binding.profile_sha256
            or policy_pin.manifest_sha256 != getattr(profile_metadata, "manifest_sha256", None)
            or policy_pin.published_crosswalk_sha256
            != getattr(profile_metadata, "published_parameter_crosswalk_sha256", None)
            or getattr(profile_metadata, "parameter_origin", None) != "PUBLISHED_ROUNDED_REFERENCE"
            or getattr(profile_metadata, "fit_sha256", None) is not None
            or getattr(profile_metadata, "calibration_sha256", None) is not None
            or getattr(profile_metadata, "rights_status", None) != "VERIFIED"
            or getattr(profile_metadata, "execution_status", None) != "SIMULATION_ENABLED"
            or getattr(profile_metadata, "rights_revoked_at", None) is not None
            or getattr(profile_metadata, "disabled_at", None) is not None
            or getattr(profile_metadata, "simulation_enabled_at", None) is None
            or getattr(profile_metadata, "research_only", None) is not True
            or getattr(profile_metadata, "human_curated", None) is not False
            or getattr(profile_metadata, "psychological_interpretation_allowed", None) is not False
            or getattr(profile_metadata, "publication_status", None)
            != "not_approved_for_publication_or_operational_use"
            or getattr(binding, "response_origin", None) != "PUBLIC_OBSERVED"
            or getattr(binding, "research_only", None) is not True
            or getattr(binding, "status", None) != "ACTIVE"
            or getattr(binding, "revoked_at", None) is not None
        ):
            raise _conflict_error()

    async def _resolve_session_and_lock(
        self,
        uow: Any,
        actor: Actor,
        *,
        at: datetime,
        metadata: Any,
        observed_response: tuple[str, int] | None = None,
    ) -> Any:
        try:
            return await self._resolve_and_lock(
                uow,
                actor,
                at=at,
                session_ref=metadata.session_ref,
                observed_response=observed_response,
            )
        except ResearchScopeResolutionError:
            # Completed sessions are intentionally excluded from the active
            # session candidate join. Resolve their owning task under the
            # same school, then re-check the current actor/SELF scope there.
            if metadata.status not in {"COMPLETED", "FAILED", "ABANDONED"}:
                raise
            model = self._owner._db_models.MeasurementTask
            task_ref = await uow.session.scalar(
                self._owner._select(model.task_ref).where(
                    model.id == metadata.task_id,
                    model.school_id == actor.school_id,
                )
            )
            if type(task_ref) is not str or not task_ref:
                raise ResearchScopeResolutionError() from None
            return await self._resolve_and_lock(
                uow,
                actor,
                at=at,
                task_ref=task_ref,
                observed_response=observed_response,
            )

    async def _metadata_for_ref(self, uow: Any, *, school_id: int, session_ref: str) -> Any:
        return await uow.research_cat.get_session_l1_metadata(
            school_id=school_id, session_ref=session_ref
        )

    async def _session_for_enrollment(self, uow: Any, scope: Any) -> Any | None:
        model = self._owner._db_models.SchoolResearchSession
        return await uow.session.scalar(
            self._owner._select(model)
            .where(
                model.school_id == scope.school_id,
                model.task_id == scope.task_id,
                model.task_enrollment_id == scope.task_enrollment_id,
            )
            .limit(2)
        )

    async def _replay_result(
        self,
        uow: Any,
        claim: SchoolIdempotencyClaim,
        scope: Any,
        *,
        required_task_ref: str,
        requested_session_ref: str | None,
        known_metadata: Any | None = None,
    ) -> ResearchSessionPersistenceResult:
        receipt = claim.record
        if (
            receipt.result_resource_type != _RESOURCE_TYPE
            or type(receipt.result_public_id) is not str
            or not receipt.result_public_id
            or (
                requested_session_ref is not None
                and receipt.result_public_id != requested_session_ref
            )
            or scope.task_ref != required_task_ref
        ):
            raise _conflict_error()
        metadata = known_metadata
        if metadata is None or metadata.session_ref != receipt.result_public_id:
            metadata = await self._metadata_for_ref(
                uow,
                school_id=scope.school_id,
                session_ref=receipt.result_public_id,
            )
        self._require_metadata_scope(metadata, scope)
        return _result(
            metadata,
            scope,
            persisted=True,
            replayed=True,
            state_accepted=False,
        )

    @staticmethod
    def _require_metadata_scope(metadata: Any, scope: Any) -> None:
        if (
            metadata.school_id != scope.school_id
            or metadata.task_id != scope.task_id
            or metadata.class_id != scope.class_id
            or metadata.task_enrollment_id != scope.task_enrollment_id
            or metadata.subject_id != scope.subject_id
            or metadata.profile_version_id != scope.binding.metadata.profile_version_id
            or metadata.profile_ref != scope.binding.metadata.profile_ref
            or metadata.profile_sha256 != scope.binding.metadata.profile_sha256
            or metadata.config_version != scope.binding.metadata.config_version
            or metadata.config_sha256 != scope.binding.metadata.config_sha256
            or metadata.task_binding_id != scope.binding.metadata.binding_id
        ):
            raise _not_found_error()


def _scope_pin(scope: Any) -> _ScopePin:
    candidate = scope.candidate if isinstance(scope, _ResolvedLockedScope) else scope
    return _ScopePin(
        account_id=candidate.account_id,
        membership_role_id=candidate.membership_role_id,
        school_id=candidate.school_id,
        school_ref=candidate.school_ref,
        task_id=candidate.task_id,
        task_ref=candidate.task_ref,
        class_id=candidate.class_id,
        class_ref=candidate.class_ref,
        task_enrollment_id=candidate.task_enrollment_id,
        enrollment_ref=candidate.task_enrollment_ref,
        subject_id=candidate.subject_id,
        subject_ref=candidate.subject_ref,
    )


def _require_same_scope(expected: _ScopePin, actual: Any) -> None:
    if _scope_pin(actual) != expected:
        raise _not_found_error()


def _binding_matches_plan(actual: Any, expected: Any) -> bool:
    return _binding_fingerprint(actual) == _binding_fingerprint(expected)


def _binding_fingerprint(binding: Any) -> tuple[Any, ...]:
    return (
        binding.binding_id,
        binding.school_id,
        binding.task_id,
        binding.class_id,
        binding.profile_version_id,
        binding.profile_ref,
        binding.profile_version_number,
        binding.profile_sha256,
        binding.response_origin,
        binding.status,
        binding.config_version,
        binding.config_sha256,
        binding.research_only,
        binding.revoked_at,
    )


def _validate_binding_metadata(binding: Any) -> None:
    if (
        type(binding.binding_id) is not int
        or binding.binding_id <= 0
        or type(binding.school_id) is not int
        or binding.school_id <= 0
        or type(binding.task_id) is not int
        or binding.task_id <= 0
        or type(binding.class_id) is not int
        or binding.class_id <= 0
        or type(binding.profile_version_id) is not int
        or binding.profile_version_id <= 0
        or type(binding.profile_version_number) is not int
        or binding.profile_version_number <= 0
        or type(binding.profile_ref) is not str
        or not binding.profile_ref
        or type(binding.config_version) is not str
        or not binding.config_version
        or type(binding.profile_sha256) is not str
        or _SHA256.fullmatch(binding.profile_sha256) is None
        or type(binding.config_sha256) is not str
        or _SHA256.fullmatch(binding.config_sha256) is None
        or binding.status != "ACTIVE"
        or binding.research_only is not True
        or binding.revoked_at is not None
        or binding.response_origin not in {"PUBLIC_OBSERVED", "MODEL_GENERATED"}
    ):
        raise _conflict_error()


def _validate_start_state(state: Any, binding: Any) -> None:
    _validate_binding_metadata(binding)
    if (
        type(getattr(state, "session_ref", None)) is not str
        or not state.session_ref
        or type(getattr(state, "profile_id", None)) is not str
        or state.profile_id != binding.profile_ref
        or getattr(state, "profile_sha256", None) != binding.profile_sha256
        or getattr(state, "config_sha256", None) != binding.config_sha256
        or getattr(state, "config_version", None) != binding.config_version
        or getattr(state, "research_only", None) is not True
        or getattr(state, "human_curated", None) is not False
        or getattr(state, "psychological_interpretation_allowed", None) is not False
        or getattr(state, "publication_status", None)
        not in {"not_approved", "not_approved_for_publication_or_operational_use"}
        or getattr(state, "status", None) != "ACTIVE"
        or type(getattr(state, "items_answered", None)) is not int
        or state.items_answered != 0
        or getattr(state, "question", None) is None
        or getattr(state, "completion", None) is not None
    ):
        raise _conflict_error()


def _validate_answer_state(state: Any, plan: ResearchAnswerPlan, binding: Any) -> None:
    _validate_binding_metadata(binding)
    if (
        type(getattr(state, "session_ref", None)) is not str
        or state.session_ref != plan.session_ref
        or getattr(state, "profile_id", None) != plan.profile_ref
        or getattr(state, "profile_sha256", None) != plan.profile_sha256
        or getattr(state, "config_sha256", None) != plan.config_sha256
        or getattr(state, "config_version", None) != plan.config_version
        or getattr(state, "profile_sha256", None) != binding.profile_sha256
        or getattr(state, "config_sha256", None) != binding.config_sha256
        or getattr(state, "config_version", None) != binding.config_version
        or getattr(state, "research_only", None) is not True
        or getattr(state, "human_curated", None) is not False
        or getattr(state, "psychological_interpretation_allowed", None) is not False
        or getattr(state, "publication_status", None)
        not in {"not_approved", "not_approved_for_publication_or_operational_use"}
        or type(getattr(state, "items_answered", None)) is not int
        or state.items_answered != plan.items_answered + 1
        or getattr(state, "status", None) not in {"ACTIVE", "COMPLETED"}
    ):
        raise _conflict_error()


def _verified_repository_mapping(client: Any, state: Any) -> Mapping[str, object]:
    try:
        snapshot = client.snapshot_for_persistence(state)
        if type(snapshot) is not ResearchCATSnapshotForPersistence:
            raise ResearchCATClientError("snapshot_wrapper_invalid")
        mapping = snapshot.to_repository_mapping()
        if type(mapping) is not dict or not mapping:
            raise ResearchCATClientError("snapshot_wrapper_invalid")
        return mapping
    except ResearchCATClientError:
        raise error(
            ErrorCode.DEPENDENCY_INVALID_RESPONSE,
            detail="research CAT state could not be authenticated",
        ) from None
    except Exception:
        raise error(
            ErrorCode.DEPENDENCY_INVALID_RESPONSE,
            detail="research CAT state could not be authenticated",
        ) from None


def _result(
    metadata: Any,
    scope: Any,
    *,
    persisted: bool,
    replayed: bool,
    state_accepted: bool,
) -> ResearchSessionPersistenceResult:
    _validate_metadata(metadata)
    return ResearchSessionPersistenceResult(
        metadata=ResearchSessionReceipt(
            session_ref=metadata.session_ref,
            task_ref=scope.task_ref,
            enrollment_ref=scope.enrollment_ref,
            subject_ref=scope.subject_ref,
            profile_ref=metadata.profile_ref,
            profile_version_number=metadata.profile_version_number,
            profile_sha256=metadata.profile_sha256,
            config_version=metadata.config_version,
            config_sha256=metadata.config_sha256,
            status=metadata.status,
            state_version=metadata.state_version,
            items_answered=metadata.items_answered,
            stop_reason=metadata.stop_reason,
            started_at=metadata.started_at,
            completed_at=metadata.completed_at,
        ),
        persisted=persisted,
        replayed=replayed,
        state_accepted=state_accepted,
    )


def _validate_metadata(metadata: Any) -> None:
    if (
        type(getattr(metadata, "session_ref", None)) is not str
        or not metadata.session_ref
        or type(getattr(metadata, "status", None)) is not str
        or metadata.status not in {"IN_PROGRESS", "COMPLETED", "FAILED", "ABANDONED"}
        or type(getattr(metadata, "state_version", None)) is not int
        or metadata.state_version < 1
        or type(getattr(metadata, "items_answered", None)) is not int
        or metadata.items_answered < 0
        or type(getattr(metadata, "profile_sha256", None)) is not str
        or _SHA256.fullmatch(metadata.profile_sha256) is None
        or type(getattr(metadata, "config_sha256", None)) is not str
        or _SHA256.fullmatch(metadata.config_sha256) is None
        or not isinstance(getattr(metadata, "started_at", None), datetime)
    ):
        raise _dependency_error()


def _validate_reference(value: object) -> None:
    if (
        type(value) is not str
        or not value
        or len(value) > 128
        or not value[0].isalnum()
        or any(not (c.isascii() and (c.isalnum() or c in "_.:-")) for c in value)
    ):
        raise error(ErrorCode.VALIDATION_FAILED, detail="research reference is invalid")


def _actor_school_id(actor: Actor) -> int:
    school_id = getattr(actor, "school_id", None)
    if type(school_id) is not int or school_id <= 0:
        raise error(ErrorCode.FORBIDDEN, detail="access denied")
    return school_id


def _validate_positive_int(value: object, label: str) -> None:
    if type(value) is not int or value <= 0:
        raise error(ErrorCode.VALIDATION_FAILED, detail=f"{label} is invalid")


def _validate_idempotency(value: object) -> None:
    if (
        type(value) is not tuple
        or len(value) != 3
        or any(type(part) is not str or not part for part in value)
        or len(value[0]) > 512
        or _SHA256.fullmatch(value[1]) is None
        or _SHA256.fullmatch(value[2]) is None
    ):
        raise error(ErrorCode.VALIDATION_FAILED, detail="research idempotency is invalid")


def _not_found_error() -> BackendError:
    return error(ErrorCode.RESOURCE_NOT_FOUND, detail="research session is unavailable")


def _study_policy_denied() -> BackendError:
    return error(ErrorCode.FORBIDDEN, detail="trusted study policy does not authorize this use")


def _study_policy_unavailable() -> BackendError:
    return error(
        ErrorCode.DEPENDENCY_UNAVAILABLE,
        detail="trusted study policy is unavailable",
        retryable=True,
    )


def _conflict_error() -> BackendError:
    return error(ErrorCode.WORKFLOW_CONFLICT, detail="research session changed or is unavailable")


def _dependency_error() -> BackendError:
    return error(
        ErrorCode.DEPENDENCY_UNAVAILABLE,
        detail="research CAT persistence is unavailable",
        retryable=True,
    )


def _aware_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ResearchStudyUseError("task_window_invalid")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError):
        raise ResearchStudyUseError("task_window_invalid") from None


def _translate_error(exc: Exception) -> BackendError:
    if isinstance(exc, BackendError):
        return exc
    if isinstance(exc, ResearchCATClientError):
        if exc.code == "upstream_rejected" and exc.status_code in {502, 503, 504}:
            return error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="research CAT persistence is unavailable",
                retryable=True,
            )
        return error(
            ErrorCode.DEPENDENCY_INVALID_RESPONSE,
            detail="research CAT state could not be authenticated",
        )
    if isinstance(exc, ResearchScopeResolutionError):
        return _not_found_error()
    code = getattr(getattr(exc, "code", None), "value", getattr(exc, "code", None))
    if code in _NOT_FOUND_CODES:
        return _not_found_error()
    if code in _CONFLICT_CODES:
        return _conflict_error()
    return _dependency_error()
