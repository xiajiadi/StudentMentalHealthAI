"""Pure, fail-closed Prompt assembly for D3-1."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from string import Template
from typing import Any, NoReturn, cast

from .contracts import validate_assessment, validate_generation_request, validate_knowledge_chunk
from .errors import PromptRefusal, refusal, safe_identifier
from .registry import PolicyRecord, TemplateRecord, resolve_policy_ref, resolve_template

_ALLOWED_SAFETY_ACTIONS = {"PROCEED", "PROCEED_WITH_BOUNDARY"}
_REQUIRED_CONTEXT_KEYS = {
    "request_id",
    "trace_id",
    "execution_mode",
    "content_population",
    "input_safety_action",
    "retrieval_safety_action",
}
_FORBIDDEN_MEASUREMENT_TERMS = ("theta", "se", "score", "band")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_TRUSTED_CONTEXT_CAPABILITY = object()
_TRUSTED_ACTIONS = {
    "PROCEED",
    "PROCEED_WITH_BOUNDARY",
    "BLOCK",
    "CRISIS_ROUTE",
    "REVIEW_REQUIRED",
}


@dataclass(frozen=True, slots=True)
class TrustedChunkContext:
    """Internal eligibility snapshot supplied by a controlled upstream port."""

    chunk_id: str
    document_id: str
    content_hash: str
    citation_locator: str
    review_status: str
    rights_status: str
    population_scope: tuple[str, ...]
    role_scope: tuple[str, ...]
    risk_scope: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TrustedPromptContext:
    """Opaque internal gate state; raw request mappings cannot construct it."""

    request_id: str
    trace_id: str
    execution_mode: str
    content_population: str
    input_safety_action: str
    retrieval_safety_action: str
    assessment_population: str
    assessment_risk_level: str
    assessment_need_human_review: bool
    chunk_states: tuple[TrustedChunkContext, ...]
    _capability: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._capability is not _TRUSTED_CONTEXT_CAPABILITY:
            raise TypeError("TrustedPromptContext is internal-only")


def _build_trusted_prompt_context(
    context: Mapping[str, Any],
    assessment: Mapping[str, Any],
    chunks: Sequence[Mapping[str, Any]],
) -> TrustedPromptContext:
    """Build synthetic/internal trusted state for controlled ports and tests.

    This private helper is intentionally not part of the package's public API.
    It is a process-local construction seam, not a hostile same-process
    security boundary or a human approval mechanism.
    """

    required_context = {
        "request_id",
        "trace_id",
        "execution_mode",
        "content_population",
        "input_safety_action",
        "retrieval_safety_action",
    }
    if set(context) != required_context:
        raise ValueError("trusted context shape is invalid")
    if not all(isinstance(context.get(key), str) for key in required_context):
        raise ValueError("trusted context values are invalid")
    if not isinstance(context["request_id"], str) or not _IDENTIFIER.fullmatch(
        context["request_id"]
    ):
        raise ValueError("trusted request_id is invalid")
    if not isinstance(context["trace_id"], str) or not _IDENTIFIER.fullmatch(
        context["trace_id"]
    ):
        raise ValueError("trusted trace_id is invalid")
    if not isinstance(context["content_population"], str) or not _IDENTIFIER.fullmatch(
        context["content_population"]
    ):
        raise ValueError("trusted content population is invalid")
    if not isinstance(context["input_safety_action"], str):
        raise ValueError("trusted input Safety action is invalid")
    if not isinstance(context["retrieval_safety_action"], str):
        raise ValueError("trusted retrieval Safety action is invalid")

    risk = assessment.get("risk")
    if not isinstance(risk, Mapping):
        raise ValueError("trusted assessment risk is invalid")
    assessment_population = assessment.get("population_scope")
    risk_level = risk.get("level")
    needs_review = risk.get("need_human_review")
    if not isinstance(assessment_population, str):
        raise ValueError("trusted assessment population is invalid")
    if not isinstance(risk_level, str) or not isinstance(needs_review, bool):
        raise ValueError("trusted assessment risk is invalid")

    states: list[TrustedChunkContext] = []
    for chunk in chunks:
        citation = chunk.get("citation")
        population_scope = chunk.get("population_scope")
        role_scope = chunk.get("role_scope")
        risk_scope = chunk.get("risk_scope")
        fields = (
            chunk.get("chunk_id"),
            chunk.get("document_id"),
            chunk.get("content_hash"),
            chunk.get("review_status"),
            chunk.get("rights_status"),
        )
        if not all(isinstance(value, str) for value in fields):
            raise ValueError("trusted chunk identity is invalid")
        if not isinstance(citation, Mapping) or not isinstance(citation.get("locator"), str):
            raise ValueError("trusted citation locator is invalid")
        if not all(
            isinstance(value, list) and all(isinstance(item, str) for item in value)
            for value in (population_scope, role_scope, risk_scope)
        ):
            raise ValueError("trusted chunk scope is invalid")
        states.append(
            TrustedChunkContext(
                chunk_id=cast(str, chunk.get("chunk_id")),
                document_id=cast(str, chunk.get("document_id")),
                content_hash=cast(str, chunk.get("content_hash")),
                citation_locator=citation["locator"],
                review_status=cast(str, chunk.get("review_status")),
                rights_status=cast(str, chunk.get("rights_status")),
                population_scope=tuple(cast(list[str], population_scope)),
                role_scope=tuple(cast(list[str], role_scope)),
                risk_scope=tuple(cast(list[str], risk_scope)),
            )
        )
    return TrustedPromptContext(
        request_id=cast(str, context["request_id"]),
        trace_id=cast(str, context["trace_id"]),
        execution_mode=cast(str, context["execution_mode"]),
        content_population=cast(str, context["content_population"]),
        input_safety_action=cast(str, context["input_safety_action"]),
        retrieval_safety_action=cast(str, context["retrieval_safety_action"]),
        assessment_population=assessment_population,
        assessment_risk_level=risk_level,
        assessment_need_human_review=needs_review,
        chunk_states=tuple(states),
        _capability=_TRUSTED_CONTEXT_CAPABILITY,
    )


@dataclass(frozen=True)
class RenderedPrompt:
    """Rendered text plus independent request and internal audit projections."""

    generation_request: dict[str, Any]
    rendered_text: str
    prompt_hash: str
    audit: dict[str, Any]

    @property
    def request(self) -> dict[str, Any]:
        return self.generation_request

    @property
    def text(self) -> str:
        return self.rendered_text

    @property
    def sha256(self) -> str:
        return self.prompt_hash

    @property
    def hash(self) -> str:
        return self.prompt_hash


def _copy(value: object, reason_code: str) -> Any:
    try:
        return copy.deepcopy(value)
    except Exception as exc:  # pragma: no cover - hostile objects are defensive coverage
        raise PromptRefusal(reason_code) from exc


def _safe_context_ids(context: object) -> dict[str, object]:
    if isinstance(context, TrustedPromptContext):
        return {"request_id": context.request_id, "trace_id": context.trace_id}
    if not isinstance(context, Mapping):
        return {}
    return {
        key: context[key]
        for key in ("request_id", "trace_id")
        if safe_identifier(context.get(key)) is not None
    }


def _reject(reason_code: str, context: object = None) -> NoReturn:
    raise refusal(reason_code, _safe_context_ids(context))


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _validate_trusted_context(context: object) -> TrustedPromptContext:
    if not isinstance(context, TrustedPromptContext):
        _reject("TRUSTED_CONTEXT_REQUIRED")
    if context.execution_mode != "synthetic_demo":
        _reject("EXECUTION_MODE_NOT_ALLOWED", context)
    if context.input_safety_action not in _ALLOWED_SAFETY_ACTIONS:
        _reject("INPUT_SAFETY_ACTION_REJECTED", context)
    if context.retrieval_safety_action not in _ALLOWED_SAFETY_ACTIONS:
        _reject("RETRIEVAL_SAFETY_ACTION_REJECTED", context)
    return context


def _context_values(context: TrustedPromptContext) -> dict[str, Any]:
    return {
        "request_id": context.request_id,
        "trace_id": context.trace_id,
        "execution_mode": context.execution_mode,
        "content_population": context.content_population,
        "input_safety_action": context.input_safety_action,
        "retrieval_safety_action": context.retrieval_safety_action,
    }


def _validate_policy(
    policy: PolicyRecord,
    assessment: Mapping[str, Any],
    request: Mapping[str, Any],
    context: Mapping[str, Any],
) -> None:
    required = {
        "policy_id",
        "policy_version",
        "status",
        "engineering_activation_scope",
        "intended_use",
        "psychology_review_status",
        "score_meaning_status",
        "threshold_status",
        "score_interpretation_allowed",
        "real_population_allowed",
        "instrument_allowlist",
        "assessment_population_allowlist",
        "content_population_allowlist",
        "roles",
        "template_ids",
        "evidence_refs",
        "evidence_citation_required",
        "mapping",
    }
    if not required.issubset(policy):
        _reject("POLICY_ASSET_INVALID", context)
    if (
        policy["status"] != "active"
        or policy["engineering_activation_scope"] != "synthetic_demo"
        or policy["intended_use"] != "synthetic_engineering_only"
        or policy["psychology_review_status"] != "HUMAN_PSYCHOLOGY_REVIEW_PENDING"
        or policy["score_meaning_status"] != "UNVERIFIED"
        or policy["threshold_status"] != "NO_CUTOFFS"
        or policy["score_interpretation_allowed"] is not False
        or policy["real_population_allowed"] is not False
        or policy["evidence_citation_required"] is not True
    ):
        _reject("POLICY_NOT_ELIGIBLE", context)
    if policy["policy_version"] != policy.get("mapping", {}).get(
        "policy_version", policy["policy_version"]
    ):
        _reject("POLICY_MAPPING_INVALID", context)
    if context["execution_mode"] != policy["engineering_activation_scope"]:
        _reject("POLICY_SCOPE_MISMATCH", context)
    if assessment.get("population_scope") not in policy["assessment_population_allowlist"]:
        _reject("POLICY_ASSESSMENT_POPULATION_MISMATCH", context)
    if context["content_population"] not in policy["content_population_allowlist"]:
        _reject("POLICY_CONTENT_POPULATION_MISMATCH", context)
    instrument = assessment.get("instrument")
    if not isinstance(instrument, Mapping):
        _reject("POLICY_INSTRUMENT_MISMATCH", context)
    instrument_matches = [
        entry
        for entry in policy["instrument_allowlist"]
        if isinstance(entry, Mapping)
        and entry.get("instrument_id") == instrument.get("instrument_id")
        and instrument.get("version") in entry.get("versions", [])
    ]
    if len(instrument_matches) != 1:
        _reject("POLICY_INSTRUMENT_MISMATCH", context)
    mapping = policy["mapping"]
    if not isinstance(mapping, Mapping):
        _reject("POLICY_MAPPING_INVALID", context)
    if (
        mapping.get("assessment_population") != assessment.get("population_scope")
        or mapping.get("content_population") != context["content_population"]
        or mapping.get("execution_mode") != context["execution_mode"]
        or request.get("target_role") not in mapping.get("roles", [])
    ):
        _reject("POLICY_MAPPING_MISMATCH", context)
    if request.get("target_role") not in policy["roles"]:
        _reject("POLICY_ROLE_NOT_ALLOWED", context)


def _validate_template(
    template: TemplateRecord,
    request: Mapping[str, Any],
    context: Mapping[str, Any],
    policy: PolicyRecord,
) -> None:
    if template.prompt_id not in policy["template_ids"]:
        _reject("TEMPLATE_NOT_ALLOWED_BY_POLICY", context)
    if template.purpose != request.get("purpose") or template.language != request.get("language"):
        _reject("TEMPLATE_REQUEST_SCOPE_MISMATCH", context)
    if template.engineering_activation_scope != policy["engineering_activation_scope"]:
        _reject("TEMPLATE_SCOPE_MISMATCH", context)
    try:
        pattern_matches = list(Template.pattern.finditer(template.template_text))
    except (AttributeError, TypeError, ValueError) as exc:
        raise PromptRefusal("TEMPLATE_INVALID") from exc
    names: set[str] = set()
    for match in pattern_matches:
        if match.group("invalid") is not None:
            _reject("TEMPLATE_INVALID", context)
        name = match.group("named") or match.group("braced")
        if name is not None:
            names.add(name)
    allowed = set(template.allowed_placeholders)
    if not names.issubset(allowed) or names != allowed:
        _reject("TEMPLATE_PLACEHOLDER_INVALID", context)


def _validate_assessment(assessment: Mapping[str, Any], context: Mapping[str, Any]) -> None:
    if assessment.get("status") != "completed":
        _reject("ASSESSMENT_NOT_COMPLETED", context)
    risk = assessment.get("risk")
    if not isinstance(risk, Mapping):
        _reject("ASSESSMENT_RISK_INVALID", context)
    if risk.get("level") in {"high", "crisis"} or risk.get("need_human_review") is True:
        _reject("ASSESSMENT_REVIEW_REQUIRED", context)


def _validate_cross_ids(
    assessment: Mapping[str, Any], request: Mapping[str, Any], context: Mapping[str, Any]
) -> None:
    if assessment.get("assessment_id") != request.get("assessment_id"):
        _reject("ASSESSMENT_ID_MISMATCH", context)
    if assessment.get("subject_id") != request.get("subject_id"):
        _reject("SUBJECT_ID_MISMATCH", context)
    prompt_ref = request.get("prompt_ref")
    if (
        not isinstance(prompt_ref, Mapping)
        or not prompt_ref.get("prompt_id")
        or not prompt_ref.get("prompt_version")
    ):
        _reject("PROMPT_REF_INVALID", context)


def _validate_chunks(
    chunks: Sequence[Mapping[str, Any]],
    request: Mapping[str, Any],
    assessment: Mapping[str, Any],
    context: Mapping[str, Any],
    trusted_context: TrustedPromptContext,
) -> list[Mapping[str, Any]]:
    retrieval = request.get("retrieval")
    if not isinstance(retrieval, Mapping):
        _reject("RETRIEVAL_REF_INVALID", context)
    requested_ids = retrieval.get("chunk_ids")
    if (
        not isinstance(requested_ids, list)
        or not requested_ids
        or not all(isinstance(chunk_id, str) for chunk_id in requested_ids)
        or len(set(requested_ids)) != len(requested_ids)
    ):
        _reject("RETRIEVAL_REFERENCES_INVALID", context)
    requested_chunk_ids = cast(list[str], requested_ids)
    if (
        not isinstance(chunks, Sequence)
        or isinstance(chunks, (str, bytes))
        or len(chunks) != len(requested_chunk_ids)
    ):
        _reject("RETRIEVAL_REFERENCES_MISMATCH", context)
    by_id: dict[str, Mapping[str, Any]] = {}
    trusted_by_id = {state.chunk_id: state for state in trusted_context.chunk_states}
    for chunk in chunks:
        if not isinstance(chunk, Mapping):
            _reject("KNOWLEDGE_CHUNK_SCHEMA_INVALID", context)
        chunk_id = chunk.get("chunk_id")
        if not isinstance(chunk_id, str) or chunk_id in by_id:
            _reject("RETRIEVAL_REFERENCES_INVALID", context)
        trusted_state = trusted_by_id.get(chunk_id)
        if trusted_state is None:
            _reject("TRUSTED_CONTEXT_CHUNK_MISSING", context)
        citation = chunk.get("citation")
        if (
            chunk.get("document_id") != trusted_state.document_id
            or chunk.get("content_hash") != trusted_state.content_hash
            or chunk.get("review_status") != trusted_state.review_status
            or chunk.get("rights_status") != trusted_state.rights_status
            or chunk.get("population_scope") != list(trusted_state.population_scope)
            or chunk.get("role_scope") != list(trusted_state.role_scope)
            or chunk.get("risk_scope") != list(trusted_state.risk_scope)
            or not isinstance(citation, Mapping)
            or citation.get("locator") != trusted_state.citation_locator
        ):
            _reject("TRUSTED_CONTEXT_MISMATCH", context)
        by_id[chunk_id] = chunk
        try:
            validate_knowledge_chunk(chunk)
        except PromptRefusal as exc:
            raise PromptRefusal(exc.reason_code, **_safe_context_ids(context)) from exc
        if (
            trusted_state.review_status != "approved"
            or trusted_state.rights_status != "verified"
            or not isinstance(citation, Mapping)
            or not isinstance(citation.get("locator"), str)
            or not citation["locator"].strip()
        ):
            _reject("RETRIEVAL_CHUNK_NOT_ELIGIBLE", context)
        if trusted_context.content_population not in trusted_state.population_scope:
            _reject("RETRIEVAL_POPULATION_MISMATCH", context)
        if request.get("target_role") not in trusted_state.role_scope:
            _reject("RETRIEVAL_ROLE_MISMATCH", context)
        if trusted_context.assessment_risk_level not in trusted_state.risk_scope:
            _reject("RETRIEVAL_RISK_MISMATCH", context)
    if set(by_id) != set(requested_chunk_ids):
        _reject("RETRIEVAL_REFERENCES_MISMATCH", context)
    return [by_id[chunk_id] for chunk_id in requested_chunk_ids]


def _assessment_projection(assessment: Mapping[str, Any]) -> dict[str, Any]:
    instrument = assessment["instrument"]
    return {
        "assessment_id": assessment["assessment_id"],
        "subject_id": assessment["subject_id"],
        "instrument_id": instrument["instrument_id"],
        "instrument_version": instrument["version"],
        "assessment_population": assessment["population_scope"],
        "data_nature": "synthetic_engineering_only",
        "interpretation": "not_provided",
    }


def _retrieval_projection(chunks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "chunk_id": chunk["chunk_id"],
            "document_id": chunk["document_id"],
            "text": chunk["text"],
            "content_type": chunk["content_type"],
            "location": chunk["location"],
            "citation": chunk["citation"],
            "content_hash": chunk["content_hash"],
        }
        for chunk in chunks
    ]


def _render_text(
    template: TemplateRecord, values: Mapping[str, str], context: Mapping[str, Any]
) -> str:
    try:
        text = Template(template.template_text).substitute(values)
    except (KeyError, ValueError) as exc:
        raise PromptRefusal("TEMPLATE_SUBSTITUTION_FAILED", **_safe_context_ids(context)) from exc
    return text.replace("\r\n", "\n").replace("\r", "\n")


def render(
    assessment: Mapping[str, Any],
    generation_request: Mapping[str, Any],
    chunks: Sequence[Mapping[str, Any]],
    policy_ref: Mapping[str, Any],
    trusted_context: TrustedPromptContext,
) -> RenderedPrompt:
    """Validate and render one request using controlled internal gate state."""

    ctx = _validate_trusted_context(trusted_context)
    context_values = _context_values(ctx)
    assessment_copy = _copy(assessment, "ASSESSMENT_SCHEMA_INVALID")
    request_copy = _copy(generation_request, "GENERATION_REQUEST_SCHEMA_INVALID")
    chunks_copy = _copy(chunks, "RETRIEVAL_REFERENCES_INVALID")
    policy_ref_copy = _copy(policy_ref, "POLICY_REF_INVALID")
    if not isinstance(assessment_copy, Mapping):
        _reject("ASSESSMENT_SCHEMA_INVALID", ctx)
    if not isinstance(request_copy, Mapping):
        _reject("GENERATION_REQUEST_SCHEMA_INVALID", ctx)
    if not isinstance(chunks_copy, Sequence) or isinstance(chunks_copy, (str, bytes)):
        _reject("RETRIEVAL_REFERENCES_INVALID", ctx)
    if not isinstance(policy_ref_copy, Mapping):
        _reject("POLICY_REF_INVALID", ctx)
    try:
        validate_assessment(assessment_copy)
        validate_generation_request(request_copy)
        policy = resolve_policy_ref(policy_ref_copy)
    except PromptRefusal as exc:
        raise PromptRefusal(exc.reason_code, **_safe_context_ids(context_values)) from exc
    if assessment_copy.get("population_scope") != ctx.assessment_population:
        _reject("TRUSTED_CONTEXT_MISMATCH", ctx)
    risk = assessment_copy.get("risk")
    if not isinstance(risk, Mapping):
        _reject("ASSESSMENT_RISK_INVALID", ctx)
    if (
        risk.get("level") != ctx.assessment_risk_level
        or risk.get("need_human_review") != ctx.assessment_need_human_review
    ):
        _reject("TRUSTED_CONTEXT_MISMATCH", ctx)
    _validate_assessment(assessment_copy, context_values)
    _validate_cross_ids(assessment_copy, request_copy, context_values)
    _validate_policy(policy, assessment_copy, request_copy, context_values)
    prompt_ref = request_copy["prompt_ref"]
    try:
        template = resolve_template(
            prompt_ref["prompt_id"], prompt_ref["prompt_version"], request_copy["target_role"]
        )
    except PromptRefusal as exc:
        raise PromptRefusal(exc.reason_code, **_safe_context_ids(context_values)) from exc
    _validate_template(template, request_copy, context_values, policy)
    ordered_chunks = _validate_chunks(
        cast(Sequence[Mapping[str, Any]], chunks_copy),
        request_copy,
        assessment_copy,
        context_values,
        ctx,
    )
    values = {
        "target_role": str(request_copy["target_role"]),
        "language": str(request_copy["language"]),
        "execution_mode": ctx.execution_mode,
        "input_safety_action": ctx.input_safety_action,
        "retrieval_safety_action": ctx.retrieval_safety_action,
        "assessment_context_json": _stable_json(_assessment_projection(assessment_copy)),
        "retrieval_context_json": _stable_json(_retrieval_projection(ordered_chunks)),
        "allowed_source_chunk_ids_json": _stable_json(
            [chunk["chunk_id"] for chunk in ordered_chunks]
        ),
    }
    rendered_text = _render_text(template, values, context_values)
    prompt_hash = "sha256:" + hashlib.sha256(rendered_text.encode("utf-8")).hexdigest()
    risk_level = ctx.assessment_risk_level
    audit = {
        "audit_version": "1.0.0",
        "workflow_outcome": "PROMPT_RENDERED",
        "request_id": ctx.request_id,
        "trace_id": ctx.trace_id,
        "generation_id": request_copy["generation_id"],
        "assessment_id": assessment_copy["assessment_id"],
        "subject_id": assessment_copy["subject_id"],
        "target_role": request_copy["target_role"],
        "instrument_id": assessment_copy["instrument"]["instrument_id"],
        "instrument_version": assessment_copy["instrument"]["version"],
        "assessment_population": assessment_copy["population_scope"],
        "content_population": ctx.content_population,
        "execution_mode": ctx.execution_mode,
        "policy_id": policy["policy_id"],
        "policy_version": policy["policy_version"],
        "mapping_id": policy["mapping"]["mapping_id"],
        "mapping_version": policy["mapping"]["mapping_version"],
        "prompt_id": template.prompt_id,
        "prompt_version": template.prompt_version,
        "prompt_hash": prompt_hash,
        "hash_algorithm": "SHA-256",
        "hash_encoding": "UTF-8",
        "newline": "LF",
        "retrieval_id": request_copy["retrieval"]["retrieval_id"],
        "chunk_ids": [chunk["chunk_id"] for chunk in ordered_chunks],
        "source_hashes": [chunk["content_hash"] for chunk in ordered_chunks],
        "input_safety_action": ctx.input_safety_action,
        "retrieval_safety_action": ctx.retrieval_safety_action,
        "risk_level": risk_level,
        "evidence_refs": list(policy["evidence_refs"]),
    }
    return RenderedPrompt(
        generation_request=dict(request_copy),
        rendered_text=rendered_text,
        prompt_hash=prompt_hash,
        audit=audit,
    )


render_prompt = render
