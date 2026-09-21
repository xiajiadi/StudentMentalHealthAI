"""Fail-closed assessment binding for D3-4.

The binding is the Backend's object-scope proof between an authenticated
request and a completed assessment.  It also makes the current mismatch
between the legacy Backend synthetic CAT fixture and the accepted D3-2 policy
visible.  No assessment identity is silently rewritten.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, cast

from smhai_backend.core.async_utils import maybe_await
from smhai_backend.core.trusted_context import (
    TrustedContextError,
    TrustedRequestContext,
    derive_trusted_request_context,
)
from smhai_backend.domains.models import Actor, AssessmentRecord, BackendRole
from smhai_backend.domains.ports import AssessmentRepository


class AssessmentBindingError(TrustedContextError):
    """An assessment cannot be bound to the trusted request origin."""


@dataclass(frozen=True, slots=True)
class AssessmentIdentity:
    instrument_id: str
    instrument_version: str
    population_scope: str

    def to_dict(self) -> dict[str, str]:
        return {
            "instrument_id": self.instrument_id,
            "instrument_version": self.instrument_version,
            "population_scope": self.population_scope,
        }


@dataclass(frozen=True, slots=True)
class AssessmentCompatibilityFixture:
    """Explicit, versioned source-to-D3 identity mapping.

    ``approved`` is intentionally required to opt into a compatibility path.
    A fixture with ``approved=False`` documents a known source mismatch but
    cannot make the source eligible for D3-2.
    """

    fixture_id: str
    fixture_version: str
    source: AssessmentIdentity
    target: AssessmentIdentity
    policy_id: str
    approved: bool = False
    approval_reference: str | None = None
    # Legacy Backend's synthetic CAT fixture uses ``wellbeing`` while the
    # accepted D3 fixture uses ``demo_trait``.  A construct mapping is an
    # explicit compatibility decision; it is never inferred from a caller or
    # silently applied to an assessment with a different identity.
    dimension_map: tuple[tuple[str, str], ...] = ()

    def matches(self, identity: AssessmentIdentity) -> bool:
        return identity == self.source

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "fixture_version": self.fixture_version,
            "source": self.source.to_dict(),
            "target": self.target.to_dict(),
            "policy_id": self.policy_id,
            "approved": self.approved,
            "approval_reference": self.approval_reference,
            "dimension_map": [list(item) for item in self.dimension_map],
        }


# These values mirror the exact accepted D3-2 shipped fixture.  The instrument
# identity is deliberately kept as the module-owned pair used by the accepted
# assessment fixture; it must not be inferred from the legacy Backend fixture.
D3_POLICY_ID = "POLICY_assessment_synthetic_measurement_only"
D3_POLICY_VERSION = "1.0.0"
D3_POLICY_HASH = "sha256:7c61cf80dc68561c78618c2d6e3859295b0dc53a291a1805c9bb623c5b7714a4"
D3_IDENTITY = AssessmentIdentity(
    instrument_id="CURRENT_SYNTHETIC_GRM",
    instrument_version="synthetic_item_bank.v1 / demo.v1",
    population_scope="SYNTHETIC_STUDENT_DEMO",
)
D3_RAG_POPULATION = "UNIVERSITY_FRESHMEN_SYNTHETIC_DEMO"
LEGACY_BACKEND_IDENTITY = AssessmentIdentity(
    instrument_id="instrument.synthetic",
    instrument_version="1.0",
    population_scope="synthetic_demo",
)

# This fixture is a refusal/documentation path by default.  A later worker may
# provide an explicitly approved instance in configuration after the required
# controller decision; the binder never enables it implicitly.
LEGACY_BACKEND_COMPATIBILITY_FIXTURE = AssessmentCompatibilityFixture(
    fixture_id="backend-legacy-synthetic-to-d3",
    fixture_version="1.0.0",
    source=LEGACY_BACKEND_IDENTITY,
    target=D3_IDENTITY,
    policy_id=D3_POLICY_ID,
    approved=False,
    approval_reference=None,
)


def _canonical_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _snapshot(value: Mapping[str, Any]) -> Mapping[str, Any]:
    copied = copy.deepcopy(dict(value))
    return MappingProxyType(copied)


def _assessment_mapping(
    record_or_assessment: AssessmentRecord | Mapping[str, Any],
) -> Mapping[str, Any]:
    if isinstance(record_or_assessment, AssessmentRecord):
        return record_or_assessment.assessment
    if isinstance(record_or_assessment, Mapping):
        return record_or_assessment
    raise AssessmentBindingError("ASSESSMENT_BINDING_INVALID", "assessment is not a mapping")


def _identity(assessment: Mapping[str, Any]) -> AssessmentIdentity:
    instrument = assessment.get("instrument")
    if not isinstance(instrument, Mapping):
        raise AssessmentBindingError("ASSESSMENT_BINDING_INVALID", "instrument identity is missing")
    values = (
        instrument.get("instrument_id"),
        instrument.get("version"),
        assessment.get("population_scope"),
    )
    if not all(isinstance(value, str) and value for value in values):
        raise AssessmentBindingError("ASSESSMENT_BINDING_INVALID", "instrument identity is invalid")
    return AssessmentIdentity(
        cast(str, values[0]),
        cast(str, values[1]),
        cast(str, values[2]),
    )


def _scope_allows(actor: Actor, subject_id: str) -> bool:
    if actor.role is BackendRole.STUDENT:
        return actor.subject_id == subject_id
    if actor.role in {BackendRole.TEACHER, BackendRole.REVIEWER, BackendRole.ADMIN}:
        return subject_id in actor.accessible_subject_ids
    if actor.role is BackendRole.PARENT:
        return actor.subject_id == subject_id or subject_id in actor.accessible_subject_ids
    return False


@dataclass(frozen=True, slots=True)
class AssessmentBinding:
    """Immutable binding and source identity evidence for one request."""

    assessment_id: str
    subject_id: str
    assessment: Mapping[str, Any]
    source_identity: AssessmentIdentity
    d3_identity: AssessmentIdentity
    policy_id: str
    principal_id: str
    context_id: str
    transaction_id: str
    assessment_hash: str
    compatibility_fixture_id: str | None = None
    compatibility_fixture_version: str | None = None
    compatibility_approval_reference: str | None = None
    compatibility_dimension_map: tuple[tuple[str, str], ...] = ()
    _source_snapshot: Mapping[str, Any] = field(repr=False, compare=False, default_factory=dict)

    def __post_init__(self) -> None:
        if not self.assessment_id.startswith("ASSESS_"):
            raise AssessmentBindingError("ASSESSMENT_BINDING_INVALID", "assessment_id is invalid")
        if not self.subject_id.startswith("SUBJ_"):
            raise AssessmentBindingError("ASSESSMENT_BINDING_INVALID", "subject_id is invalid")
        if self.assessment.get("assessment_id") != self.assessment_id:
            raise AssessmentBindingError("ASSESSMENT_ID_MISMATCH", "assessment identity changed")
        if self.assessment.get("subject_id") != self.subject_id:
            raise AssessmentBindingError("SUBJECT_SCOPE_DENIED", "assessment subject changed")

    @property
    def is_compatibility_mapped(self) -> bool:
        return self.compatibility_fixture_id is not None

    @property
    def instrument_id(self) -> str:
        return self.source_identity.instrument_id

    @property
    def instrument_version(self) -> str:
        return self.source_identity.instrument_version

    @property
    def population_scope(self) -> str:
        return self.source_identity.population_scope

    def assert_intact(self) -> None:
        """Detect assessment mutation after binding (TOCTOU protection)."""

        if _canonical_hash(self.assessment) != self.assessment_hash:
            raise AssessmentBindingError(
                "ASSESSMENT_BINDING_TAMPERED", "bound assessment content changed"
            )

    def audit_projection(self) -> dict[str, Any]:
        return {
            "assessment_id": self.assessment_id,
            "subject_id": self.subject_id,
            "source_identity": self.source_identity.to_dict(),
            "d3_identity": self.d3_identity.to_dict(),
            "policy_id": self.policy_id,
            "principal_id": self.principal_id,
            "context_id": self.context_id,
            "transaction_id": self.transaction_id,
            "assessment_hash": self.assessment_hash,
            "compatibility_fixture_id": self.compatibility_fixture_id,
            "compatibility_fixture_version": self.compatibility_fixture_version,
            "compatibility_approval_reference": self.compatibility_approval_reference,
            "compatibility_dimension_map": {
                source: target for source, target in self.compatibility_dimension_map
            },
        }

    def assessment_for_d3(self) -> dict[str, Any]:
        """Return an explicitly named D3 projection when a fixture is approved.

        The projection carries a compatibility marker and never mutates the
        original binding.  Callers should prefer the original exact fixture;
        this method exists only for a separately approved integration path.
        """

        self.assert_intact()
        if self.is_compatibility_mapped:
            instrument = self.assessment.get("instrument")
            if not isinstance(instrument, Mapping):
                raise AssessmentBindingError(
                    "ASSESSMENT_BINDING_INVALID", "instrument identity missing"
                )
            projected = copy.deepcopy(dict(self.assessment))
            projected["instrument"] = {
                "instrument_id": self.d3_identity.instrument_id,
                "version": self.d3_identity.instrument_version,
            }
            projected["population_scope"] = self.d3_identity.population_scope
            dimensions = projected.get("dimensions")
            if not isinstance(dimensions, Mapping):
                raise AssessmentBindingError(
                    "ASSESSMENT_BINDING_INVALID", "assessment dimensions are missing"
                )
            if self.compatibility_fixture_id is not None:
                fixture_map = self._compatibility_dimension_map()
                if fixture_map:
                    mapped_dimensions: dict[str, Any] = {}
                    for construct_id, value in dimensions.items():
                        mapped_id = fixture_map.get(str(construct_id), str(construct_id))
                        if mapped_id in mapped_dimensions:
                            raise AssessmentBindingError(
                                "ASSESSMENT_COMPATIBILITY_INVALID",
                                "compatibility construct mapping is ambiguous",
                            )
                        mapped_dimensions[mapped_id] = copy.deepcopy(value)
                    projected["dimensions"] = mapped_dimensions
            # Compatibility identity and the dimension alias are Backend
            # audit evidence only.  ``assessment.v1`` has
            # ``provenance.additionalProperties=false``; putting fixture
            # metadata into that object would make the accepted D3-2 adapter
            # abstain with ASSESSMENT_SCHEMA_INVALID.
            return projected
        return copy.deepcopy(dict(self.assessment))

    def _compatibility_dimension_map(self) -> dict[str, str]:
        """Return the mapping from the bound, approved fixture only."""

        # The binding currently stores the fixture identity rather than the
        # fixture object.  Keep the explicit map in the projection through the
        # source assessment provenance when an approved caller supplied it;
        # the Backend default fixture registers the same map below.  A missing
        # map means the original construct names are preserved and D3-2 will
        # fail closed if they are not accepted by its policy.
        return dict(self.compatibility_dimension_map)


def bind_assessment(
    actor: Actor,
    record_or_assessment: AssessmentRecord | Mapping[str, Any],
    *,
    assessment_id: str,
    requested_assessment_id: str | None = None,
    subject_id_assertion: str | None = None,
    trusted_context: TrustedRequestContext | None = None,
    request: object | None = None,
    transaction_id: str | None = None,
    request_id: str = "REQ_d3_binding",
    trace_id: str = "TRACE_d3_binding",
    compatibility_fixtures: tuple[AssessmentCompatibilityFixture, ...] = (),
) -> AssessmentBinding:
    """Bind a completed record to the authenticated actor and trusted origin."""

    if not isinstance(actor, Actor):
        raise AssessmentBindingError("TRUSTED_CONTEXT_REQUIRED", "verified Actor is required")
    if requested_assessment_id is not None and requested_assessment_id != assessment_id:
        raise AssessmentBindingError(
            "ASSESSMENT_ID_MISMATCH", "path and body assessment IDs differ"
        )
    assessment = _assessment_mapping(record_or_assessment)
    if (
        isinstance(record_or_assessment, AssessmentRecord)
        and record_or_assessment.assessment_id != assessment_id
    ):
        raise AssessmentBindingError(
            "ASSESSMENT_ID_MISMATCH", "repository record ID does not match requested assessment"
        )
    if assessment.get("assessment_id") != assessment_id:
        raise AssessmentBindingError(
            "ASSESSMENT_ID_MISMATCH", "assessment ID does not match bound record"
        )
    if assessment.get("status") != "completed":
        raise AssessmentBindingError("ASSESSMENT_NOT_COMPLETED", "assessment must be completed")
    subject_id = assessment.get("subject_id")
    if not isinstance(subject_id, str) or not subject_id.startswith("SUBJ_"):
        raise AssessmentBindingError("ASSESSMENT_BINDING_INVALID", "assessment subject is invalid")
    if (
        isinstance(record_or_assessment, AssessmentRecord)
        and record_or_assessment.subject_id != subject_id
    ):
        raise AssessmentBindingError(
            "SUBJECT_SCOPE_DENIED", "record and assessment subjects differ"
        )
    if subject_id_assertion is not None and subject_id_assertion != subject_id:
        raise AssessmentBindingError(
            "SUBJECT_SCOPE_DENIED", "subject assertion does not match record"
        )
    if not _scope_allows(actor, subject_id):
        raise AssessmentBindingError("SUBJECT_SCOPE_DENIED", "actor is outside assessment scope")

    source_identity = _identity(assessment)
    fixture: AssessmentCompatibilityFixture | None = None
    if source_identity != D3_IDENTITY:
        fixture = next(
            (
                candidate
                for candidate in compatibility_fixtures
                if candidate.matches(source_identity)
            ),
            None,
        )
        if fixture is None or not fixture.approved:
            raise AssessmentBindingError(
                "ASSESSMENT_COMPATIBILITY_REQUIRED",
                "assessment identity is not the accepted D3-2 fixture; "
                "explicit approved compatibility is required",
            )
        if fixture.target != D3_IDENTITY or fixture.policy_id != D3_POLICY_ID:
            raise AssessmentBindingError(
                "ASSESSMENT_COMPATIBILITY_INVALID",
                "compatibility fixture target does not match the accepted D3-2 policy",
            )

    expected_d3_identity = fixture.target if fixture is not None else D3_IDENTITY
    if trusted_context is None:
        trusted_context = derive_trusted_request_context(
            actor,
            assessment,
            request=request,
            target_role=getattr(request, "target_role", None)
            if request is not None and not isinstance(request, Mapping)
            else (request.get("target_role") if isinstance(request, Mapping) else None),
            transaction_id=transaction_id,
            request_id=request_id,
            trace_id=trace_id,
        )
    else:
        if not isinstance(trusted_context, TrustedRequestContext):
            raise AssessmentBindingError(
                "TRUSTED_CONTEXT_REQUIRED", "typed trusted context is required"
            )
        if (
            trusted_context.subject_id != subject_id
            or trusted_context.principal_id != actor.user_id
        ):
            raise AssessmentBindingError(
                "TRUSTED_CONTEXT_MISMATCH", "trusted context does not bind assessment"
            )
        if transaction_id is not None and trusted_context.transaction_id != transaction_id:
            raise AssessmentBindingError(
                "TRUSTED_CONTEXT_MISMATCH", "transaction identity does not match context"
            )

    snapshot = _snapshot(assessment)
    return AssessmentBinding(
        assessment_id=assessment_id,
        subject_id=subject_id,
        assessment=snapshot,
        source_identity=source_identity,
        d3_identity=expected_d3_identity,
        policy_id=D3_POLICY_ID,
        principal_id=trusted_context.principal_id,
        context_id=trusted_context.context_id,
        transaction_id=trusted_context.transaction_id,
        assessment_hash=_canonical_hash(snapshot),
        compatibility_fixture_id=fixture.fixture_id if fixture else None,
        compatibility_fixture_version=fixture.fixture_version if fixture else None,
        compatibility_approval_reference=fixture.approval_reference if fixture else None,
        compatibility_dimension_map=fixture.dimension_map if fixture else (),
        _source_snapshot=snapshot,
    )


class AssessmentBinder:
    """Repository-aware async facade for the pure binding function."""

    def __init__(
        self,
        repository: AssessmentRepository,
        *,
        compatibility_fixtures: tuple[AssessmentCompatibilityFixture, ...] = (),
    ) -> None:
        self.repository = repository
        self.compatibility_fixtures = tuple(compatibility_fixtures)

    async def bind(
        self,
        actor: Actor,
        assessment_id: str,
        *,
        requested_assessment_id: str | None = None,
        subject_id_assertion: str | None = None,
        trusted_context: TrustedRequestContext | None = None,
        request: object | None = None,
        transaction_id: str | None = None,
        request_id: str = "REQ_d3_binding",
        trace_id: str = "TRACE_d3_binding",
    ) -> AssessmentBinding:
        record = await maybe_await(self.repository.get(assessment_id))
        if record is None:
            raise AssessmentBindingError("ASSESSMENT_NOT_FOUND", "assessment not found")
        return bind_assessment(
            actor,
            record,
            assessment_id=assessment_id,
            requested_assessment_id=requested_assessment_id,
            subject_id_assertion=subject_id_assertion,
            trusted_context=trusted_context,
            request=request,
            transaction_id=transaction_id,
            request_id=request_id,
            trace_id=trace_id,
            compatibility_fixtures=self.compatibility_fixtures,
        )


__all__ = [
    "AssessmentBinder",
    "AssessmentBinding",
    "AssessmentBindingError",
    "AssessmentCompatibilityFixture",
    "AssessmentIdentity",
    "D3_IDENTITY",
    "D3_POLICY_ID",
    "D3_POLICY_VERSION",
    "D3_POLICY_HASH",
    "D3_RAG_POPULATION",
    "LEGACY_BACKEND_COMPATIBILITY_FIXTURE",
    "LEGACY_BACKEND_IDENTITY",
    "bind_assessment",
]
