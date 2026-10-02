"""Backend-owned bridge for the accepted D3-2, D3-3 and D3-1 seams.

The three deterministic D3 packages are deliberately kept outside the
Backend package.  This module only resolves their repository-local package
roots, builds their typed trusted contexts, and maps their typed results into
the one canonical Backend generation path.  It does not reimplement any D3
algorithm or accept caller supplied policy authority.
"""

from __future__ import annotations

import copy
import importlib
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from smhai_backend.core.trusted_context import TrustedRequestContext
from smhai_backend.domains.assessment.binding import (
    D3_RAG_POPULATION,
    LEGACY_BACKEND_COMPATIBILITY_FIXTURE,
    AssessmentBinding,
    AssessmentCompatibilityFixture,
)
from smhai_backend.integrations.evidence import RetrievalEvidenceBundle
from smhai_backend.integrations.population_mapping import resolve_population_mapping
from smhai_backend.integrations.rag import RetrievalResult
from smhai_backend.integrations.safety import SafetyAction


class D3CompositionError(RuntimeError):
    """A fail-closed error at an accepted D3 boundary."""

    def __init__(self, code: str, detail: str = "D3 composition refused") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True, slots=True)
class D3FixtureConfig:
    """Explicit Backend compatibility mappings for legacy synthetic fixtures.

    These mappings are opt-in configuration.  They never rewrite the stored
    assessment/retrieval object.  Retrieval eligibility uses the source scope
    actually observed from the RAG adapter; the target scope is reserved for
    the accepted D3-1 content mapping at that later seam.
    """

    assessment_fixtures: tuple[AssessmentCompatibilityFixture, ...]
    retrieval_fixture_id: str = "backend-legacy-rag-to-d3"
    retrieval_fixture_version: str = "1.0.0"
    retrieval_source_label: str = "CONTRACT_FAKE"
    retrieval_source_document: str = "KB_backend_synthetic"
    retrieval_source_population: str = "synthetic_demo"
    retrieval_target_population: str = D3_RAG_POPULATION
    retrieval_approved: bool = True


def default_fixture_config() -> D3FixtureConfig:
    """Return the explicit bounded synthetic Backend compatibility config."""

    assessment_fixture = AssessmentCompatibilityFixture(
        fixture_id=LEGACY_BACKEND_COMPATIBILITY_FIXTURE.fixture_id,
        fixture_version=LEGACY_BACKEND_COMPATIBILITY_FIXTURE.fixture_version,
        source=LEGACY_BACKEND_COMPATIBILITY_FIXTURE.source,
        target=LEGACY_BACKEND_COMPATIBILITY_FIXTURE.target,
        policy_id=LEGACY_BACKEND_COMPATIBILITY_FIXTURE.policy_id,
        approved=True,
        approval_reference="D3-4_BACKEND_SYNTHETIC_COMPATIBILITY_V1",
        dimension_map=(("wellbeing", "demo_trait"),),
    )
    return D3FixtureConfig(assessment_fixtures=(assessment_fixture,))


def _ensure_accepted_package_roots() -> None:
    """Make the two accepted sibling packages importable without installing them."""

    root = Path(__file__).resolve().parents[4]
    for relative in ("03_assessment-adapter/src", "07_prompt-engine/src"):
        package_root = str(root / relative)
        if package_root not in sys.path:
            # Keep the bridge deterministic when a globally installed package
            # happens to exist with the same import name.
            sys.path.insert(0, package_root)


def _accepted_modules() -> tuple[Any, Any, Any, Any, Any, Any]:
    _ensure_accepted_package_roots()
    try:
        assessment_models = importlib.import_module("assessment_adapter.models")
        assessment_adapter = importlib.import_module("assessment_adapter.adapter")
        role_models = importlib.import_module("prompt_engine.role_projection_models")
        role_projection = importlib.import_module("prompt_engine.role_projection")
        prompt_engine = importlib.import_module("prompt_engine.engine")
        prompt_registry = importlib.import_module("prompt_engine.registry")
    except (ImportError, ModuleNotFoundError) as exc:  # pragma: no cover - environment failure
        raise D3CompositionError("D3_PACKAGE_UNAVAILABLE") from exc
    return (
        assessment_models,
        assessment_adapter,
        role_models,
        role_projection,
        prompt_engine,
        prompt_registry,
    )


def server_prompt_reference(target_role: str) -> tuple[str, str]:
    """Return the exact server-owned D3-1 template identity for a role."""

    refs = {
        "student": ("PROMPT_student_synthetic_v1", "1.0.0"),
        "teacher": ("PROMPT_teacher_synthetic_v1", "1.0.0"),
        "parent": ("PROMPT_parent_synthetic_demo_v1", "1.0.0"),
    }
    try:
        return refs[target_role]
    except KeyError as exc:
        raise D3CompositionError("ROLE_NOT_ELIGIBLE", "admin has no psychology prompt") from exc


def server_model_reference(label: str) -> tuple[str, str]:
    """Return a server-owned model contract reference for the selected adapter."""

    if label == "REAL_HTTP":
        return "MODEL_local_primary", "local"
    if label == "CONTRACT_FAKE":
        return "MODEL_backend_fake", "mock"
    raise D3CompositionError("MODEL_POLICY_UNAVAILABLE")


def assessment_policy_reference() -> dict[str, str]:
    """Read the exact D3-2 policy identity from its shipped registry."""

    _models, adapter, _role_models, _role_projection, _engine, _registry = _accepted_modules()
    try:
        registry = adapter.load_shipped_registry()
        policies = getattr(registry, "policies", ())
        if len(policies) != 1:
            raise D3CompositionError("D3_POLICY_AMBIGUOUS")
        policy = policies[0]
        return {
            "policy_id": str(policy.policy_id),
            "policy_version": str(policy.policy_version),
            "policy_hash": str(policy.policy_hash),
        }
    except D3CompositionError:
        raise
    except Exception as exc:  # pragma: no cover - shipped asset failure
        raise D3CompositionError("D3_POLICY_UNAVAILABLE") from exc


def adapt_legacy_retrieval(
    retrieval: RetrievalResult,
    *,
    config: D3FixtureConfig,
) -> RetrievalResult:
    """Retain the observed retrieval without rewriting its facts.

    This name remains as a compatibility shim for older Backend callers.  The
    former implementation appended a D3 content population to each
    ``KnowledgeChunk`` and added fixture metadata to the RAG trace.  Neither is
    provenance observed from RAG, so the mapping is now applied only by the
    typed D3-1 seam after the evidence bundle has been frozen.
    """

    del config
    return retrieval


def retrieval_eligibility_population(
    retrieval: RetrievalResult,
    *,
    config: D3FixtureConfig,
) -> str:
    """Return the server-selected scope used for evidence eligibility.

    Contract fake retrieval exposes ``synthetic_demo``.  It is the only value
    eligible for that adapter; the D3 content population mapping is a separate
    server policy and must not be inferred as RAG provenance.  Other adapters
    are checked against the configured target population and fail closed when
    their observed chunks do not contain it.
    """

    if retrieval.label == config.retrieval_source_label:
        return config.retrieval_source_population
    if retrieval.label == "REAL_HTTP":
        return resolve_population_mapping(D3_RAG_POPULATION).evidence_eligibility_population
    raise D3CompositionError("RAG_POPULATION_MAPPING_REQUIRED")


def bind_assessment_for_d3(
    context: TrustedRequestContext,
    binding: AssessmentBinding,
) -> dict[str, Any]:
    """Return the explicit D3 assessment projection after integrity checks."""

    binding.assert_intact()
    if binding.context_id != context.context_id or binding.transaction_id != context.transaction_id:
        raise D3CompositionError("ASSESSMENT_BINDING_MISMATCH")
    if binding.principal_id != context.principal_id or binding.subject_id != context.subject_id:
        raise D3CompositionError("ASSESSMENT_BINDING_MISMATCH")
    projected = binding.assessment_for_d3()
    if projected.get("assessment_id") != context_to_id(context, "assessment_id", projected):
        raise D3CompositionError("ASSESSMENT_BINDING_MISMATCH")
    return projected


def context_to_id(
    _context: TrustedRequestContext, _name: str, assessment: Mapping[str, Any]
) -> str:
    value = assessment.get("assessment_id")
    if not isinstance(value, str) or not value.startswith("ASSESS_"):
        raise D3CompositionError("ASSESSMENT_BINDING_INVALID")
    return value


def interpret_assessment(
    *,
    context: TrustedRequestContext,
    assessment: Mapping[str, Any],
    safety_action: SafetyAction | str,
) -> Any:
    """Call the accepted D3-2 adapter through its typed trusted seam."""

    if context.execution_mode.value != "SYNTHETIC_DEMO":
        raise D3CompositionError("EXECUTION_MODE_NOT_ALLOWED")
    if not isinstance(assessment, Mapping):
        raise D3CompositionError("ASSESSMENT_BINDING_INVALID")
    assessment_id = assessment.get("assessment_id")
    if not isinstance(assessment_id, str) or not assessment_id.startswith("ASSESS_"):
        raise D3CompositionError("ASSESSMENT_BINDING_MISMATCH")
    if assessment.get("subject_id") != context.subject_id:
        raise D3CompositionError("ASSESSMENT_BINDING_MISMATCH")
    models, adapter, _role_models, _role_projection, _engine, _registry = _accepted_modules()
    policy = assessment_policy_reference()
    try:
        request = models.InterpretationRequest(
            assessment=copy.deepcopy(dict(assessment)),
            policy_ref=models.PolicyReference(**policy),
            request_id=context.request_id,
            trace_id=context.trace_id,
        )
        d3_context = adapter._build_trusted_interpretation_context(
            {
                "execution_mode": context.execution_mode.value,
                "assessment_population": str(assessment.get("population_scope", "")),
                "context_id": context.context_id,
                "context_version": context.context_version,
                "safety_action": str(getattr(safety_action, "value", safety_action)),
                "request_id": context.request_id,
                "trace_id": context.trace_id,
            }
        )
        result = adapter.InterpretationAdapter(adapter.load_shipped_registry()).interpret(
            request, d3_context
        )
    except D3CompositionError:
        raise
    except Exception as exc:
        raise D3CompositionError("D3_2_COMPOSITION_FAILED") from exc
    status = getattr(result, "status", None)
    if status is None or str(getattr(status, "value", status)) not in {
        "MEASUREMENT_ONLY",
        "READY_FOR_RENDERING",
    }:
        raise D3CompositionError(
            "D3_2_ABSTAINED",
            f"D3-2 returned {getattr(status, 'value', status)}",
        )
    return result


def project_role(
    *,
    context: TrustedRequestContext,
    interpretation: Any,
    bundle: RetrievalEvidenceBundle,
    safety_action: SafetyAction | str,
) -> tuple[Any, dict[str, Any]]:
    """Call D3-3 with server-built context and opaque bundle citations."""

    _models, _adapter, role_models, role_projection, _engine, _registry = _accepted_modules()
    try:
        role = role_models.AudienceRole(context.audience_role.value)
        purpose = role_models.PurposeOfUse(context.purpose.value)
        relation = role_models.TrustedRelation(context.relationship.value)
        mode = role_models.ProjectionMode(context.execution_mode.value)
        disclosure = role_models.DisclosureAuthorization(context.disclosure_state.value)
        source_status = role_models.SourceStatus(
            str(getattr(interpretation.status, "value", interpretation.status))
        )
        source_codes_list: list[str] = []
        for claim in getattr(interpretation, "claims", ()):
            if isinstance(claim, Mapping):
                value = claim.get("claim_code")
            else:
                value = getattr(claim, "claim_code", None)
            if not isinstance(value, str):
                raise D3CompositionError("D3_2_RESULT_INVALID")
            source_codes_list.append(value)
        source_codes = tuple(source_codes_list)
        trusted = role_models._build_trusted_audience_context(
            {
                "audience_role": role.value,
                "purpose_of_use": purpose.value,
                "subject_relation": relation.value,
                "execution_mode": mode.value,
                "disclosure_authorization": disclosure.value,
                "source_status": source_status.value,
                "source_claim_codes": source_codes,
                "safety_action": str(getattr(safety_action, "value", safety_action)),
                "request_id": context.request_id,
                "trace_id": context.trace_id,
                "context_id": context.context_id,
                "context_version": context.context_version,
            }
        )
        refs = [
            role_models.PolicyReference(
                policy_id=str(policy.policy_id),
                policy_version=str(policy.policy_version),
                policy_hash=str(policy.policy_hash),
            )
            for policy in role_projection.load_role_projection_policy_registry().policies
            if policy.audience_role is role
        ]
        if len(refs) != 1:
            raise D3CompositionError("D3_3_POLICY_AMBIGUOUS")
        result = role_projection.project(
            interpretation,
            refs[0],
            trusted,
            bundle.prompt_citations(),
        )
        prompt_payload = role_projection.prompt_input(result.prompt)
    except D3CompositionError:
        raise
    except Exception as exc:
        raise D3CompositionError("D3_3_COMPOSITION_FAILED") from exc
    return result, cast(dict[str, Any], prompt_payload)


def render_prompt(
    *,
    context: TrustedRequestContext,
    assessment: Mapping[str, Any],
    bundle: RetrievalEvidenceBundle,
    target_role: str,
    generation_id: str,
    language: str,
    input_safety_action: SafetyAction | str,
    retrieval_safety_action: SafetyAction | str,
) -> Any:
    """Call D3-1 with trusted chunks from the already bound bundle."""

    _models, _adapter, _role_models, _role_projection, engine, registry = _accepted_modules()
    try:
        prompt_id, prompt_version = server_prompt_reference(target_role)
        policy = registry.resolve_policy(
            "POLICY_synthetic_engineering_university_freshmen", "1.0.0"
        )
        policy_ref = {
            "policy_id": policy.policy_id,
            "policy_version": policy.policy_version,
            "mapping_id": policy["mapping"]["mapping_id"],
            "mapping_version": policy["mapping"]["mapping_version"],
        }
        generation_request = {
            "schema_version": "generation.v1",
            "generation_id": generation_id,
            "assessment_id": assessment["assessment_id"],
            "subject_id": assessment["subject_id"],
            "target_role": target_role,
            "purpose": "education_support",
            "language": language,
            "safety_mode": "standard",
            "retrieval": {
                "retrieval_id": bundle.retrieval_id,
                "chunk_ids": list(bundle.chunk_ids),
            },
            "prompt_ref": {"prompt_id": prompt_id, "prompt_version": prompt_version},
            "model_policy": {"model_id": "MODEL_backend_fake", "provider_class": "mock"},
        }
        trusted = engine._build_trusted_prompt_context(
            {
                "request_id": context.request_id,
                "trace_id": context.trace_id,
                "execution_mode": context.execution_mode.value.lower(),
                "content_population": D3_RAG_POPULATION,
                "input_safety_action": str(
                    getattr(input_safety_action, "value", input_safety_action)
                ),
                "retrieval_safety_action": str(
                    getattr(retrieval_safety_action, "value", retrieval_safety_action)
                ),
            },
            assessment,
            list(bundle.trusted_chunks()),
        )
        return engine.render(
            assessment,
            generation_request,
            list(bundle.trusted_chunks()),
            policy_ref,
            trusted,
        )
    except D3CompositionError:
        raise
    except Exception as exc:
        raise D3CompositionError("D3_1_COMPOSITION_FAILED") from exc


__all__ = [
    "D3CompositionError",
    "D3FixtureConfig",
    "adapt_legacy_retrieval",
    "assessment_policy_reference",
    "bind_assessment_for_d3",
    "default_fixture_config",
    "interpret_assessment",
    "project_role",
    "render_prompt",
    "server_model_reference",
    "server_prompt_reference",
]
