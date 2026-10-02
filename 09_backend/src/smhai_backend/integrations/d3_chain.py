"""Typed Backend adapter for one accepted D3-2 -> D3-3 -> D3-1 chain.

The accepted D3 packages live in their own sibling module roots.  This adapter
only resolves those roots, constructs their internal trusted contexts from
Backend-owned typed state, verifies exact shipped identities, and records the
bounded stages around the calls.  It does not copy any D3 algorithm and it
never accepts a caller mapping as authority.
"""

from __future__ import annotations

import importlib
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from smhai_backend.core.orchestration import OrchestrationStage, StageLedger
from smhai_backend.core.trusted_context import (
    AudienceRole,
    TrustedRequestContext,
    is_trusted_request_context,
)
from smhai_backend.domains.assessment.binding import (
    D3_IDENTITY,
    D3_POLICY_HASH,
    D3_POLICY_ID,
    D3_POLICY_VERSION,
    AssessmentBinding,
)
from smhai_backend.integrations.evidence import RetrievalEvidenceBundle
from smhai_backend.integrations.population_mapping import resolve_population_mapping

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_GENERATION_ID = re.compile(r"^GEN_[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_SAFETY_ACTIONS = frozenset(
    {"PROCEED", "PROCEED_WITH_BOUNDARY", "CRISIS_ROUTE", "REVIEW_REQUIRED", "BLOCK"}
)
_STOP_ACTIONS = frozenset({"CRISIS_ROUTE", "REVIEW_REQUIRED", "BLOCK"})

_D3_1_POLICY_ID = "POLICY_synthetic_engineering_university_freshmen"
_D3_1_POLICY_VERSION = "1.0.0"
_D3_1_MAPPING_ID = "MAP_SYNTHETIC_DEMO_TO_UNIVERSITY_FRESHMEN_CONTENT_V1"
_D3_1_MAPPING_VERSION = "1.0.0"
_D3_1_SOURCE_LABEL = "CONTRACT_FAKE"
_D3_1_SOURCE_DOCUMENT = "KB_backend_synthetic"
_D3_1_SOURCE_POPULATION = "synthetic_demo"
_D3_1_TARGET_POPULATION = "UNIVERSITY_FRESHMEN_SYNTHETIC_DEMO"

_ROLE_POLICY_REFS: dict[str, tuple[str, str, str]] = {
    "student": (
        "ROLE_PROJECTION_STUDENT_SELF_V09",
        "1.0.0",
        "sha256:7396fa34f2e08d24cf415bd526d3647b254492f8ec715150e76e7c22515e40d4",
    ),
    "teacher": (
        "ROLE_PROJECTION_TEACHER_SUPPORT_V09",
        "1.0.0",
        "sha256:378adb0b7a701e1c27bd65c89939d081d9abcf325db622595591f33c81817d7b",
    ),
    "parent": (
        "ROLE_PROJECTION_PARENT_DEMO_V09",
        "1.0.0",
        "sha256:d562fd172a496674b77d5943502f9413345166c8c3e582a771735e7a5c9be912",
    ),
}
_TEMPLATE_REFS: dict[str, tuple[str, str, str]] = {
    "student": (
        "PROMPT_student_synthetic_v1",
        "1.0.0",
        "sha256:8f821afbcbe53b4741982ac9cac02961151ab1b2f15b2fdb2786e5707baa237e",
    ),
    "teacher": (
        "PROMPT_teacher_synthetic_v1",
        "1.0.0",
        "sha256:51eedb7fb436474eb5ee6b141df66db12cd3230254948b637ffff6639e0dacb0",
    ),
    "parent": (
        "PROMPT_parent_synthetic_demo_v1",
        "1.0.0",
        "sha256:6297d629b7e2f1a124dd5950e111177d2515999a15d755830aae4f20b5d0f528",
    ),
}


class D3ChainError(RuntimeError):
    """Fail-closed error raised by the Backend D3 chain seam."""

    def __init__(self, code: str, detail: str = "D3 chain composition refused") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True, slots=True)
class D3PolicyReference:
    """An exact policy identity observed in an accepted shipped registry."""

    policy_id: str
    policy_version: str
    policy_hash: str


@dataclass(frozen=True, slots=True)
class D3TemplateReference:
    """An exact template identity observed in an accepted shipped registry."""

    prompt_id: str
    prompt_version: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class D3ContentPopulationMapping:
    """Server policy used to project observed evidence into D3-1 scope.

    The mapping is a detached D3-1 input projection.  It never rewrites the
    ``KnowledgeChunk`` or the immutable evidence bundle, and its source fields
    are checked against the observed bundle before use.
    """

    mapping_id: str
    mapping_version: str
    source_label: str | None
    source_document: str | None
    source_population: str | None
    target_population: str
    approved: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "mapping_id": self.mapping_id,
            "mapping_version": self.mapping_version,
            "source_label": self.source_label,
            "source_document": self.source_document,
            "source_population": self.source_population,
            "target_population": self.target_population,
            "approved": self.approved,
        }


@dataclass(frozen=True, slots=True)
class D3ChainResult:
    """Typed result retaining both public prompt input and internal audit result."""

    interpretation: Any
    role_projection: Any
    prompt_input: Mapping[str, Any]
    rendered_prompt: Any
    assessment_policy: D3PolicyReference
    role_policy: D3PolicyReference
    template: D3TemplateReference
    content_population_mapping: D3ContentPopulationMapping


@dataclass(frozen=True, slots=True)
class D3InterpretationResult:
    """Typed, request-bound result of the one D3-2 interpretation phase.

    The Backend keeps the interpretation separate from the later RAG-backed
    D3-3/D3-1 composition so a normal request cannot retrieve evidence before
    D3-2 has run.  The identity fields prevent a result from one request or
    assessment being reused with another trusted context.
    """

    interpretation: Any
    assessment_policy: D3PolicyReference
    assessment_id: str
    subject_id: str
    assessment_hash: str
    context_id: str
    transaction_id: str
    request_id: str
    trace_id: str
    input_safety_action: str


def _accepted_roots() -> tuple[Path, Path]:
    root = Path(__file__).resolve().parents[4]
    return (
        root / "03_assessment-adapter" / "src",
        root / "07_prompt-engine" / "src",
    )


def _ensure_accepted_roots() -> None:
    """Resolve only the repository-local accepted package roots."""

    for package_root in _accepted_roots():
        if not package_root.is_dir():
            raise D3ChainError("D3_PACKAGE_UNAVAILABLE", str(package_root))
        text = str(package_root)
        if text not in sys.path:
            sys.path.insert(0, text)


def _import_accepted(name: str, root: Path) -> Any:
    try:
        module = importlib.import_module(name)
    except (ImportError, ModuleNotFoundError) as exc:
        raise D3ChainError("D3_PACKAGE_UNAVAILABLE", name) from exc
    location = getattr(module, "__file__", None)
    if not isinstance(location, str):
        raise D3ChainError("D3_PACKAGE_UNAVAILABLE", f"{name} has no source location")
    try:
        Path(location).resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise D3ChainError("D3_PACKAGE_UNAVAILABLE", f"{name} is not repository-local") from exc
    return module


def _accepted_modules() -> tuple[Any, Any, Any, Any, Any, Any]:
    _ensure_accepted_roots()
    assessment_root, prompt_root = _accepted_roots()
    return (
        _import_accepted("assessment_adapter.models", assessment_root),
        _import_accepted("assessment_adapter.adapter", assessment_root),
        _import_accepted("prompt_engine.role_projection_models", prompt_root),
        _import_accepted("prompt_engine.role_projection", prompt_root),
        _import_accepted("prompt_engine.engine", prompt_root),
        _import_accepted("prompt_engine.registry", prompt_root),
    )


def _role_for_context(context: TrustedRequestContext) -> str:
    roles = {
        AudienceRole.STUDENT_SELF: "student",
        AudienceRole.TEACHER_SUPPORT: "teacher",
        AudienceRole.PARENT_DEMO: "parent",
    }
    try:
        return roles[context.audience_role]
    except KeyError as exc:
        raise D3ChainError("ROLE_NOT_ELIGIBLE", "admin has no psychology generation path") from exc


def _check_identifier(value: object, *, code: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise D3ChainError(code)
    return value


def _context_and_ledger(
    context: TrustedRequestContext,
    binding: AssessmentBinding,
    ledger: StageLedger,
    *,
    expected_stage: OrchestrationStage = OrchestrationStage.ASSESSMENT_BOUND,
) -> None:
    if not is_trusted_request_context(context):
        raise D3ChainError("TRUSTED_CONTEXT_REQUIRED")
    if context.execution_mode.value != "SYNTHETIC_DEMO":
        raise D3ChainError("EXECUTION_MODE_NOT_ALLOWED")
    if not isinstance(binding, AssessmentBinding):
        raise D3ChainError("ASSESSMENT_BINDING_REQUIRED")
    if not isinstance(ledger, StageLedger):
        raise D3ChainError("STAGE_LEDGER_REQUIRED")
    if ledger.context is not context:
        raise D3ChainError("TRUSTED_CONTEXT_MISMATCH")
    if (
        binding.principal_id != context.principal_id
        or binding.subject_id != context.subject_id
        or binding.context_id != context.context_id
        or binding.transaction_id != context.transaction_id
        or binding.policy_id != D3_POLICY_ID
    ):
        raise D3ChainError("ASSESSMENT_BINDING_MISMATCH")
    if ledger.current is not expected_stage:
        raise D3ChainError(
            "STAGE_PRECONDITION",
            f"D3 chain requires the exact {expected_stage.value} predecessor",
        )
    try:
        binding.assert_intact()
    except Exception as exc:
        raise D3ChainError("ASSESSMENT_BINDING_TAMPERED") from exc


def _assessment_projection(binding: AssessmentBinding) -> dict[str, Any]:
    try:
        assessment = binding.assessment_for_d3()
    except Exception as exc:
        raise D3ChainError("ASSESSMENT_BINDING_INVALID") from exc
    instrument = assessment.get("instrument")
    if (
        assessment.get("assessment_id") != binding.assessment_id
        or assessment.get("subject_id") != binding.subject_id
        or assessment.get("status") != "completed"
        or not isinstance(instrument, Mapping)
        or instrument.get("instrument_id") != D3_IDENTITY.instrument_id
        or instrument.get("version") != D3_IDENTITY.instrument_version
        or assessment.get("population_scope") != D3_IDENTITY.population_scope
    ):
        raise D3ChainError("D3_ASSESSMENT_IDENTITY_MISMATCH")
    return assessment


def _assessment_policy(
    models: Any,
    adapter: Any,
) -> tuple[Any, D3PolicyReference]:
    try:
        registry = adapter.load_shipped_registry()
        policies = tuple(registry.policies)
    except Exception as exc:
        raise D3ChainError("D3_2_POLICY_UNAVAILABLE") from exc
    if len(policies) != 1:
        raise D3ChainError("D3_2_POLICY_AMBIGUOUS")
    policy = policies[0]
    observed = D3PolicyReference(
        policy_id=str(policy.policy_id),
        policy_version=str(policy.policy_version),
        policy_hash=str(policy.policy_hash),
    )
    expected = D3PolicyReference(D3_POLICY_ID, D3_POLICY_VERSION, D3_POLICY_HASH)
    if observed != expected:
        raise D3ChainError("D3_2_POLICY_IDENTITY_MISMATCH")
    try:
        models.PolicyReference(
            policy_id=observed.policy_id,
            policy_version=observed.policy_version,
            policy_hash=observed.policy_hash,
        )
    except Exception as exc:
        raise D3ChainError("D3_2_POLICY_REFERENCE_INVALID") from exc
    return registry, observed


def _input_safety_action(ledger: StageLedger) -> str:
    try:
        record = ledger.require(OrchestrationStage.INPUT_SAFETY_EVALUATED)
    except Exception as exc:
        raise D3ChainError("STAGE_PRECONDITION") from exc
    action = record.safety_action or "PROCEED"
    if action not in _SAFETY_ACTIONS:
        raise D3ChainError("SAFETY_ACTION_INVALID")
    if action in _STOP_ACTIONS:
        raise D3ChainError("D3_SAFETY_STOP", action)
    return action


def _require_evidence(context: TrustedRequestContext, bundle: RetrievalEvidenceBundle) -> None:
    if not isinstance(bundle, RetrievalEvidenceBundle):
        raise D3ChainError("EVIDENCE_BUNDLE_REQUIRED")
    try:
        bundle.verify()
        bundle.require_eligible()
    except Exception as exc:
        raise D3ChainError("D3_EVIDENCE_NOT_ELIGIBLE") from exc
    expected_linkage = {
        "transaction_id": context.transaction_id,
        "request_id": context.request_id,
        "trace_id": context.trace_id,
    }
    if any(bundle.linkage.get(key) != value for key, value in expected_linkage.items()):
        raise D3ChainError("D3_EVIDENCE_CONTEXT_MISMATCH")
    if not bundle.items:
        raise D3ChainError("D3_EVIDENCE_NOT_ELIGIBLE")


_KNOWLEDGE_CHUNK_FIELDS = (
    "schema_version",
    "chunk_id",
    "document_id",
    "text",
    "content_type",
    "location",
    "citation",
    "population_scope",
    "role_scope",
    "risk_scope",
    "review_status",
    "rights_status",
    "content_hash",
    "embedding",
)


def _content_population_mapping(
    bundle: RetrievalEvidenceBundle,
) -> D3ContentPopulationMapping:
    """Resolve the only approved detached scope projection for D3-1.

    A contract fake exposes ``synthetic_demo`` while the accepted D3-1 policy
    names its content population more narrowly.  That compatibility mapping
    is server-owned policy context.  It is accepted only for the exact fake
    label/document/scope observed in the bundle; a different RAG source must
    provide the D3-1 population itself or fail closed.
    """

    target_population = _D3_1_TARGET_POPULATION
    if all(target_population in (item.population_scope or ()) for item in bundle.items):
        return D3ContentPopulationMapping(
            mapping_id=_D3_1_MAPPING_ID,
            mapping_version=_D3_1_MAPPING_VERSION,
            source_label=cast(str | None, bundle.provenance.get("label")),
            source_document=None,
            source_population=target_population,
            target_population=target_population,
        )

    if bundle.provenance.get("label") == "REAL_HTTP":
        population_mapping = resolve_population_mapping(target_population)
        for item in bundle.items:
            if population_mapping.rag_query_taxonomy not in (item.population_scope or ()):
                raise D3ChainError("D3_CONTENT_POPULATION_MAPPING_INVALID")
        return D3ContentPopulationMapping(
            mapping_id=population_mapping.mapping_id,
            mapping_version=population_mapping.mapping_version,
            source_label="REAL_HTTP",
            source_document=None,
            source_population=population_mapping.rag_query_taxonomy,
            target_population=population_mapping.d3_content_population,
        )

    if bundle.provenance.get("label") != _D3_1_SOURCE_LABEL:
        raise D3ChainError("D3_CONTENT_POPULATION_MAPPING_REQUIRED")
    for item in bundle.items:
        if item.document_id != _D3_1_SOURCE_DOCUMENT or _D3_1_SOURCE_POPULATION not in (
            item.population_scope or ()
        ):
            raise D3ChainError("D3_CONTENT_POPULATION_MAPPING_INVALID")
    return D3ContentPopulationMapping(
        mapping_id=_D3_1_MAPPING_ID,
        mapping_version=_D3_1_MAPPING_VERSION,
        source_label=_D3_1_SOURCE_LABEL,
        source_document=_D3_1_SOURCE_DOCUMENT,
        source_population=_D3_1_SOURCE_POPULATION,
        target_population=target_population,
    )


def _d3_1_chunks(
    bundle: RetrievalEvidenceBundle,
    mapping: D3ContentPopulationMapping,
) -> tuple[dict[str, Any], ...]:
    """Project bound evidence back to the exact accepted ``knowledge.v1`` shape.

    ``RetrievalEvidenceBundle`` carries Backend-only evidence IDs, eligibility,
    and observed provenance alongside the original chunk.  Those fields remain
    in the bundle/audit surface and must not cross the D3-1 schema boundary.
    """

    chunks: list[dict[str, Any]] = []
    for item in bundle.items:
        payload = item.payload.to_dict()
        if any(field not in payload for field in _KNOWLEDGE_CHUNK_FIELDS):
            raise D3ChainError("D3_EVIDENCE_SHAPE_INVALID")
        chunk: dict[str, Any] = {field: payload[field] for field in _KNOWLEDGE_CHUNK_FIELDS}
        for field in ("population_scope", "role_scope", "risk_scope"):
            value = chunk[field]
            if not isinstance(value, (list, tuple)) or not all(
                isinstance(entry, str) for entry in value
            ):
                raise D3ChainError("D3_EVIDENCE_SHAPE_INVALID")
            chunk[field] = list(value)
        population_scope = cast(list[str], chunk["population_scope"])
        if mapping.target_population not in population_scope:
            if (
                not mapping.approved
                or mapping.source_population is None
                or mapping.source_population not in population_scope
            ):
                raise D3ChainError("D3_CONTENT_POPULATION_MAPPING_INVALID")
            population_scope.append(mapping.target_population)
        chunk["population_scope"] = population_scope
        chunks.append(chunk)
    return tuple(chunks)


def _interpret(
    *,
    context: TrustedRequestContext,
    assessment: Mapping[str, Any],
    safety_action: str,
    models: Any,
    adapter: Any,
) -> tuple[Any, D3PolicyReference]:
    registry, policy_ref = _assessment_policy(models, adapter)
    try:
        request = models.InterpretationRequest(
            assessment=assessment,
            policy_ref=models.PolicyReference(
                policy_id=policy_ref.policy_id,
                policy_version=policy_ref.policy_version,
                policy_hash=policy_ref.policy_hash,
            ),
            request_id=context.request_id,
            trace_id=context.trace_id,
        )
        trusted_context = adapter._build_trusted_interpretation_context(
            {
                "execution_mode": context.execution_mode.value,
                "assessment_population": str(assessment["population_scope"]),
                "context_id": context.context_id,
                "context_version": context.context_version,
                "safety_action": safety_action,
                "request_id": context.request_id,
                "trace_id": context.trace_id,
            }
        )
        result = adapter.InterpretationAdapter(registry).interpret(request, trusted_context)
    except D3ChainError:
        raise
    except Exception as exc:
        raise D3ChainError("D3_2_COMPOSITION_FAILED") from exc
    status = str(getattr(getattr(result, "status", None), "value", ""))
    if status not in {"MEASUREMENT_ONLY", "READY_FOR_RENDERING"}:
        raise D3ChainError("D3_2_ABSTAINED", status)
    return result, policy_ref


def interpret_d3_chain(
    context: TrustedRequestContext,
    binding: AssessmentBinding,
    ledger: StageLedger,
) -> D3InterpretationResult:
    """Run D3-2 once and record ``INTERPRETATION_READY``.

    This is the first half of the normal Backend D3 seam.  It deliberately
    has no RAG or evidence input so the caller must complete this phase before
    retrieving knowledge.  A second call fails through the stage precondition
    rather than recalculating the interpretation.
    """

    _context_and_ledger(context, binding, ledger)
    _role_for_context(context)
    input_safety_action = _input_safety_action(ledger)
    assessment = _assessment_projection(binding)
    models, adapter, _role_models, _role_projection, _engine, _registry = _accepted_modules()
    interpretation, assessment_policy = _interpret(
        context=context,
        assessment=assessment,
        safety_action=input_safety_action,
        models=models,
        adapter=adapter,
    )
    ledger.advance(
        OrchestrationStage.INTERPRETATION_READY,
        metadata={
            "d3_2_policy_id": assessment_policy.policy_id,
            "d3_2_policy_version": assessment_policy.policy_version,
            "d3_2_policy_hash": assessment_policy.policy_hash,
        },
    )
    return D3InterpretationResult(
        interpretation=interpretation,
        assessment_policy=assessment_policy,
        assessment_id=binding.assessment_id,
        subject_id=binding.subject_id,
        assessment_hash=binding.assessment_hash,
        context_id=context.context_id,
        transaction_id=context.transaction_id,
        request_id=context.request_id,
        trace_id=context.trace_id,
        input_safety_action=input_safety_action,
    )


def _validate_interpretation_result(
    context: TrustedRequestContext,
    binding: AssessmentBinding,
    ledger: StageLedger,
    prepared: D3InterpretationResult,
) -> None:
    """Ensure the second phase consumes the exact first-phase result."""

    if not isinstance(prepared, D3InterpretationResult):
        raise D3ChainError("D3_INTERPRETATION_REQUIRED")
    if ledger.current is not OrchestrationStage.INTERPRETATION_READY:
        raise D3ChainError(
            "STAGE_PRECONDITION",
            "D3 composition requires the exact INTERPRETATION_READY predecessor",
        )
    if (
        prepared.assessment_id != binding.assessment_id
        or prepared.subject_id != binding.subject_id
        or prepared.assessment_hash != binding.assessment_hash
        or prepared.context_id != context.context_id
        or prepared.transaction_id != context.transaction_id
        or prepared.request_id != context.request_id
        or prepared.trace_id != context.trace_id
    ):
        raise D3ChainError("D3_INTERPRETATION_CONTEXT_MISMATCH")
    try:
        record = ledger.require(OrchestrationStage.INTERPRETATION_READY)
        if (
            record.metadata.get("d3_2_policy_id") != prepared.assessment_policy.policy_id
            or record.metadata.get("d3_2_policy_version")
            != prepared.assessment_policy.policy_version
            or record.metadata.get("d3_2_policy_hash") != prepared.assessment_policy.policy_hash
        ):
            raise D3ChainError("D3_INTERPRETATION_POLICY_MISMATCH")
        if _input_safety_action(ledger) != prepared.input_safety_action:
            raise D3ChainError("D3_INTERPRETATION_SAFETY_MISMATCH")
    except D3ChainError:
        raise
    except Exception as exc:
        raise D3ChainError("D3_INTERPRETATION_INVALID") from exc


def _role_policy(
    *, role: str, role_models: Any, role_projection: Any
) -> tuple[Any, D3PolicyReference, Any]:
    expected = _ROLE_POLICY_REFS[role]
    try:
        audience = role_models.AudienceRole(
            {
                "student": "STUDENT_SELF",
                "teacher": "TEACHER_SUPPORT",
                "parent": "PARENT_DEMO",
            }[role]
        )
        policies = tuple(role_projection.load_role_projection_policy_registry().policies)
        selected = tuple(policy for policy in policies if policy.audience_role is audience)
    except Exception as exc:
        raise D3ChainError("D3_3_POLICY_UNAVAILABLE") from exc
    if len(selected) != 1:
        raise D3ChainError("D3_3_POLICY_AMBIGUOUS")
    policy = selected[0]
    observed = D3PolicyReference(
        policy_id=str(policy.policy_id),
        policy_version=str(policy.policy_version),
        policy_hash=str(policy.policy_hash),
    )
    if observed != D3PolicyReference(*expected):
        raise D3ChainError("D3_3_POLICY_IDENTITY_MISMATCH")
    try:
        reference = role_models.PolicyReference(*expected)
    except Exception as exc:
        raise D3ChainError("D3_3_POLICY_REFERENCE_INVALID") from exc
    return reference, observed, policy


def _validate_prompt_projection(
    *,
    result: Any,
    prompt_value: Mapping[str, Any],
    source_claim_codes: tuple[str, ...],
    policy: Any,
    role_models: Any,
    bundle: RetrievalEvidenceBundle,
) -> None:
    """Check the D3-3 public projection before it reaches the D3-1 seam."""

    try:
        prompt = result.prompt
        audit = result.audit
        prompt_codes = tuple(prompt.content_claim_codes)
        emitted_codes = tuple(audit.emitted_claim_codes)
        approved_codes = tuple(audit.source_approved_claim_codes)
        if approved_codes != source_claim_codes or emitted_codes != prompt_codes:
            raise D3ChainError("D3_3_CLAIM_SURFACES_MISMATCH")
        validate = role_models.validate_claim_monotonicity
        validated = tuple(validate(emitted_codes, approved_codes, policy))
        if validated != emitted_codes:
            raise D3ChainError("D3_3_CLAIM_MONOTONICITY_FAILED")
        prompt_chunk_ids = tuple(citation.source_chunk_id for citation in prompt.citations)
        audit_chunk_ids = tuple(audit.source_chunk_ids)
        if prompt_chunk_ids != bundle.chunk_ids or audit_chunk_ids != bundle.chunk_ids:
            raise D3ChainError("D3_3_CITATION_SURFACES_MISMATCH")
        public_value = prompt.to_public_dict()
    except D3ChainError:
        raise
    except Exception as exc:
        raise D3ChainError("D3_3_PROMPT_PROJECTION_INVALID") from exc
    if set(prompt_value) != {"status", "claims", "limitations", "citations"}:
        raise D3ChainError("D3_3_PROMPT_PROJECTION_INVALID")
    if dict(prompt_value) != public_value:
        raise D3ChainError("D3_3_PROMPT_PROJECTION_MISMATCH")


def _project(
    *,
    context: TrustedRequestContext,
    role: str,
    interpretation: Any,
    bundle: RetrievalEvidenceBundle,
    safety_action: str,
    role_models: Any,
    role_projection: Any,
) -> tuple[Any, Mapping[str, Any], D3PolicyReference]:
    role_ref, observed_policy, role_policy = _role_policy(
        role=role, role_models=role_models, role_projection=role_projection
    )
    try:
        source_status = role_models.SourceStatus(
            str(getattr(interpretation.status, "value", interpretation.status))
        )
        source_claim_codes = tuple(
            _claim_code(claim) for claim in getattr(interpretation, "claims", ())
        )
        trusted = role_models._build_trusted_audience_context(
            {
                "audience_role": {
                    "student": "STUDENT_SELF",
                    "teacher": "TEACHER_SUPPORT",
                    "parent": "PARENT_DEMO",
                }[role],
                "purpose_of_use": context.purpose.value,
                "subject_relation": context.relationship.value,
                "execution_mode": context.execution_mode.value,
                "disclosure_authorization": context.disclosure_state.value,
                "source_status": source_status.value,
                "source_claim_codes": source_claim_codes,
                "safety_action": safety_action,
                "request_id": context.request_id,
                "trace_id": context.trace_id,
                "context_id": context.context_id,
                "context_version": context.context_version,
            }
        )
        citations = tuple(
            role_models.PromptCitation(
                source_chunk_id=str(citation["source_chunk_id"]),
                locator=cast(str | None, citation.get("locator")),
            )
            for citation in bundle.prompt_citations()
        )
        result = role_projection.project(interpretation, role_ref, trusted, citations)
        if str(getattr(result.status, "value", result.status)) != "READY_FOR_PROMPT":
            raise D3ChainError(
                "D3_3_NOT_READY", str(getattr(result.status, "value", result.status))
            )
        prompt_value = role_projection.prompt_input(result.prompt)
    except D3ChainError:
        raise
    except Exception as exc:
        raise D3ChainError("D3_3_COMPOSITION_FAILED") from exc
    if not isinstance(prompt_value, Mapping):
        raise D3ChainError("D3_3_PROMPT_PROJECTION_INVALID")
    _validate_prompt_projection(
        result=result,
        prompt_value=prompt_value,
        source_claim_codes=source_claim_codes,
        policy=role_policy,
        role_models=role_models,
        bundle=bundle,
    )
    return result, cast(Mapping[str, Any], prompt_value), observed_policy


def _claim_code(claim: object) -> str:
    value = getattr(claim, "claim_code", None)
    if not isinstance(value, str) or not value:
        raise D3ChainError("D3_2_RESULT_INVALID")
    return value


def _render(
    *,
    context: TrustedRequestContext,
    role: str,
    assessment: Mapping[str, Any],
    bundle: RetrievalEvidenceBundle,
    prompt_projection: Any,
    generation_id: str,
    input_safety_action: str,
    retrieval_safety_action: str,
    engine: Any,
    registry: Any,
) -> tuple[Any, D3TemplateReference, D3ContentPopulationMapping]:
    expected_template = _TEMPLATE_REFS[role]
    try:
        policy = registry.resolve_policy(_D3_1_POLICY_ID, _D3_1_POLICY_VERSION)
        mapping = policy.get("mapping")
        if (
            policy.policy_id != _D3_1_POLICY_ID
            or policy.policy_version != _D3_1_POLICY_VERSION
            or not isinstance(mapping, Mapping)
            or mapping.get("mapping_id") != _D3_1_MAPPING_ID
            or mapping.get("mapping_version") != _D3_1_MAPPING_VERSION
        ):
            raise D3ChainError("D3_1_POLICY_IDENTITY_MISMATCH")
        template = registry.resolve_template(expected_template[0], expected_template[1], role)
        observed_template = D3TemplateReference(
            prompt_id=str(template.prompt_id),
            prompt_version=str(template.prompt_version),
            content_hash=str(template.content_hash),
        )
        if observed_template != D3TemplateReference(*expected_template):
            raise D3ChainError("D3_1_TEMPLATE_IDENTITY_MISMATCH")
        content_population_mapping = _content_population_mapping(bundle)
        trusted_chunks = _d3_1_chunks(bundle, content_population_mapping)
        trusted_context = engine._build_trusted_prompt_context(
            {
                "request_id": context.request_id,
                "trace_id": context.trace_id,
                "execution_mode": context.execution_mode.value.lower(),
                "content_population": content_population_mapping.target_population,
                "input_safety_action": input_safety_action,
                "retrieval_safety_action": retrieval_safety_action,
            },
            assessment,
            trusted_chunks,
        )
        request = {
            "schema_version": "generation.v1",
            "generation_id": generation_id,
            "assessment_id": str(assessment["assessment_id"]),
            "subject_id": str(assessment["subject_id"]),
            "target_role": role,
            "purpose": "education_support",
            "language": "zh-CN",
            "safety_mode": "standard",
            "retrieval": {
                "retrieval_id": bundle.retrieval_id,
                "chunk_ids": list(bundle.chunk_ids),
            },
            "prompt_ref": {
                "prompt_id": template.prompt_id,
                "prompt_version": template.prompt_version,
            },
            "model_policy": {"model_id": "MODEL_backend_fake", "provider_class": "mock"},
        }
        policy_ref = {
            "policy_id": policy.policy_id,
            "policy_version": policy.policy_version,
            "mapping_id": mapping["mapping_id"],
            "mapping_version": mapping["mapping_version"],
        }
        rendered = engine.render_projected(
            assessment,
            request,
            trusted_chunks,
            policy_ref,
            trusted_context,
            prompt_projection,
        )
    except D3ChainError:
        raise
    except Exception as exc:
        raise D3ChainError("D3_1_COMPOSITION_FAILED") from exc
    text = getattr(rendered, "rendered_text", None)
    if not isinstance(text, str):
        raise D3ChainError("D3_1_RESULT_INVALID")
    # Match measurement names as standalone words.  A plain substring search
    # would incorrectly reject normal identifiers such as ``ASSESS_*``.
    if re.search(r"(?i)\b(?:theta|se)\b", text) is not None:
        raise D3ChainError("D3_1_PROMPT_LEAK")
    return rendered, observed_template, content_population_mapping


def compose_d3_chain(
    context: TrustedRequestContext,
    binding: AssessmentBinding,
    ledger: StageLedger,
    bundle: RetrievalEvidenceBundle,
    *,
    generation_id: str,
    retrieval_safety_action: str = "PROCEED",
    interpretation: D3InterpretationResult | None = None,
) -> D3ChainResult:
    """Compose the real accepted D3-2, D3-3 and D3-1 typed seams.

    The normal service path calls :func:`interpret_d3_chain` immediately after
    assessment binding, retrieves and binds evidence, then passes the returned
    typed result here.  The optional compatibility path keeps existing direct
    callers working by running that first phase when the ledger is still at
    ``ASSESSMENT_BOUND``.  Role, purpose, relation, disclosure, assessment
    identity, and Safety come from typed server state in either path.
    """

    _check_identifier(generation_id, code="GENERATION_ID_INVALID", pattern=_GENERATION_ID)
    if retrieval_safety_action not in _SAFETY_ACTIONS:
        raise D3ChainError("SAFETY_ACTION_INVALID")

    expected_stage = (
        OrchestrationStage.INTERPRETATION_READY
        if interpretation is not None
        else OrchestrationStage.ASSESSMENT_BOUND
    )
    _context_and_ledger(context, binding, ledger, expected_stage=expected_stage)
    role = _role_for_context(context)
    # Retrieval Safety is an additional authoritative gate.  A stop decision
    # must prevent every normal D3 call, including D3-2; the caller records the
    # retrieval result and the bounded review path separately.
    if retrieval_safety_action in _STOP_ACTIONS:
        raise D3ChainError("D3_SAFETY_STOP", retrieval_safety_action)

    if interpretation is None:
        interpretation = interpret_d3_chain(context, binding, ledger)
    else:
        _validate_interpretation_result(context, binding, ledger, interpretation)
    input_safety_action = interpretation.input_safety_action

    _require_evidence(context, bundle)
    ledger.advance(
        OrchestrationStage.RETRIEVAL_BOUND,
        metadata={"retrieval_id": bundle.retrieval_id, "bundle_hash": bundle.bundle_hash},
        safety_action=retrieval_safety_action,
    )
    assessment = _assessment_projection(binding)
    _models, _adapter, role_models, role_projection, engine, registry = _accepted_modules()

    role_result, prompt_value, role_policy = _project(
        context=context,
        role=role,
        interpretation=interpretation.interpretation,
        bundle=bundle,
        safety_action=retrieval_safety_action,
        role_models=role_models,
        role_projection=role_projection,
    )
    ledger.advance(
        OrchestrationStage.ROLE_PROJECTED,
        metadata={
            "d3_3_policy_id": role_policy.policy_id,
            "d3_3_policy_version": role_policy.policy_version,
            "d3_3_policy_hash": role_policy.policy_hash,
        },
    )
    rendered, template, content_population_mapping = _render(
        context=context,
        role=role,
        assessment=assessment,
        bundle=bundle,
        prompt_projection=role_result.prompt,
        generation_id=generation_id,
        input_safety_action=input_safety_action,
        retrieval_safety_action=retrieval_safety_action,
        engine=engine,
        registry=registry,
    )
    ledger.advance(
        OrchestrationStage.PROMPT_ASSEMBLED,
        metadata={
            "prompt_id": template.prompt_id,
            "prompt_version": template.prompt_version,
            "prompt_content_hash": template.content_hash,
            "content_population_mapping_id": content_population_mapping.mapping_id,
            "content_population_mapping_version": content_population_mapping.mapping_version,
            "content_population": content_population_mapping.target_population,
        },
    )
    return D3ChainResult(
        interpretation=interpretation.interpretation,
        role_projection=role_result,
        prompt_input=prompt_value,
        rendered_prompt=rendered,
        assessment_policy=interpretation.assessment_policy,
        role_policy=role_policy,
        template=template,
        content_population_mapping=content_population_mapping,
    )


# Keep the public entrypoint discoverable under the names used by the bounded
# integration request without adding additional orchestration implementations.
interpret = interpret_d3_chain
compose = compose_d3_chain
compose_d3 = compose_d3_chain


__all__ = [
    "D3ChainError",
    "D3ChainResult",
    "D3InterpretationResult",
    "D3PolicyReference",
    "D3TemplateReference",
    "D3ContentPopulationMapping",
    "interpret",
    "interpret_d3_chain",
    "compose",
    "compose_d3",
    "compose_d3_chain",
]
