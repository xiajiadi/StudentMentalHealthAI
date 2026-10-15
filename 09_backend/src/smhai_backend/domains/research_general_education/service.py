"""Held-only processor for task-bound, non-personal education research drafts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.request_context import RequestContext, valid_correlation_id
from smhai_backend.domains.conversations.service import _contains_unsupported_bibliography
from smhai_backend.domains.support.schemas import GenerationContent
from smhai_backend.domains.support.service import (
    SupportOrchestrator,
    _contains_forbidden_generated_claim,
)
from smhai_backend.integrations.evidence import (
    CitationBindingError,
    EligibilityPolicy,
    EvidenceShapeError,
    RetrievalEvidenceBundle,
    build_retrieval_evidence_bundle,
)
from smhai_backend.integrations.rag import RetrievalResult
from smhai_backend.integrations.safety import SafetyAction, SafetyCheckView, SafetyClient

from .input_review_policy import (
    INPUT_REVIEW_CONTINUATION_POLICY_SHA256,
    INPUT_REVIEW_CONTINUATION_POLICY_VERSION,
)
from .prompt import (
    FIXED_GENERAL_EDUCATION_REQUEST,
    PROMPT_ID,
    PROMPT_SHA256,
    PROMPT_TEMPLATE,  # noqa: F401 - re-exported for Runtime integration clients.
    PROMPT_VERSION,
)
from .schemas import (
    ResearchGeneralEducationCandidatePayload,
    ResearchGeneralEducationInputReviewReceipt,
    ResearchGeneralEducationOutcome,
    ResearchGeneralEducationProvenance,
    ResearchGeneralEducationReviewedInputAuthorization,
    ResearchGeneralEducationSourceCard,
)

_FIXED_QUERY = (
    "general school wellbeing education, school environment, supportive relationships, "
    "student participation and evidence limitations"
)
_EXPECTED_LAYERS = ["policy", "theory", "intervention"]
EXPECTED_MODEL_ID = "qwen2.5-7b-instruct-school-demo"
EXPECTED_MODEL_VERSION = "qwen2.5:7b-instruct-q4_K_M"
EXPECTED_MODEL_DIGEST_SHA256 = "845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e"
SAFETY_POLICY_VERSION = "safety-port-unversioned.v1"
GENERAL_EDUCATION_POLICY_VERSION = "RESEARCH_GENERAL_EDUCATION_DRAFT_V1"
_MAX_RUNTIME_EVIDENCE_CHARS = 6_000
_MAX_GENERATED_CONTENT_CHARS = 12_000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ResearchGeneralEducationRuntimeSource:
    chunk_id: str
    text: str
    title: str
    organization: str
    locator: str


class ResearchGeneralEducationRuntimeResult(BaseModel):
    """Strict, one-attempt response from the separately pinned local adapter."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    request_id: StrictStr
    trace_id: StrictStr
    generation_id: StrictStr
    retrieval_id: StrictStr
    prompt_id: StrictStr
    prompt_version: StrictStr
    prompt_sha256: StrictStr
    content_json: StrictStr
    model_id: StrictStr
    model_version: StrictStr
    model_digest_sha256: StrictStr
    runtime_version: StrictStr = Field(min_length=1, max_length=64)
    attempt_count: StrictInt
    retry_count: StrictInt
    fallback_count: StrictInt
    fallback_attempted: StrictBool
    local_only: StrictBool
    synthetic_fixture_only: StrictBool


class ResearchGeneralEducationRuntimePort(Protocol):
    async def generate(
        self,
        *,
        context: RequestContext,
        generation_id: str,
        retrieval_id: str,
        source_manifest_sha256: str,
        prompt_id: str,
        prompt_version: str,
        prompt_sha256: str,
        sources: tuple[ResearchGeneralEducationRuntimeSource, ...],
    ) -> ResearchGeneralEducationRuntimeResult: ...


class SchoolResearchStudentRetrieverPort(Protocol):
    label: str

    async def retrieve(
        self,
        *,
        query: str,
        target_population: Literal["secondary_school_student"],
        top_k: int,
        required_layers: tuple[str, ...] | None = None,
        retrieval_id: str,
        context: RequestContext,
    ) -> RetrievalResult: ...


@dataclass(frozen=True, slots=True)
class ResearchGeneralEducationPolicyPins:
    policy_hash: str
    source_package_ref: str
    source_study_ref: str
    source_manifest_sha256: str


def source_cards_from_package(
    package: object,
    *,
    policy_pins: ResearchGeneralEducationPolicyPins,
    consumer_age_min: int = 14,
    consumer_age_max: int = 17,
) -> dict[str, ResearchGeneralEducationSourceCard]:
    """Build source cards from the pinned R3 package's actual records/sources."""
    if (consumer_age_min, consumer_age_max) != (14, 17):
        raise ValueError("research candidate audience must remain pinned to ages 14-17")
    if (
        getattr(package, "package_id", None) != policy_pins.source_package_ref
        or getattr(package, "study_ref", None) != policy_pins.source_study_ref
        or getattr(package, "manifest_sha256", None)
        != policy_pins.source_manifest_sha256
    ):
        raise ValueError("source cards do not come from the pinned R3 package")
    records = getattr(package, "records", None)
    sources = getattr(package, "sources", None)
    if type(records) is not tuple or type(sources) is not tuple:
        raise ValueError("pinned student research package shape is invalid")
    source_by_id = {
        source.source_id: source
        for source in sources
        if type(getattr(source, "source_id", None)) is str
    }
    result: dict[str, ResearchGeneralEducationSourceCard] = {}
    for record in records:
        if getattr(record, "student_retrieval_eligible", None) is not True:
            continue
        source = source_by_id.get(getattr(record, "source_id", None))
        if (
            source is None
            or getattr(source, "student_retrieval_eligible", None) is not True
            or getattr(source, "rights_status", None) != "VERIFIED_WITH_CONDITIONS"
        ):
            raise ValueError("eligible record does not resolve to an eligible source")
        chunk_id = f"CHUNK_SCHOOL_RESEARCH_{record.record_id}"
        card = ResearchGeneralEducationSourceCard(
            chunk_id=chunk_id,
            record_id=record.record_id,
            source_id=source.source_id,
            title=source.title,
            organization=source.publisher,
            canonical_url=source.canonical_url,
            record_locator=record.locator,
            source_population_scope=record.source_population_scope,
            source_language=source.source_language,
            license=source.license,
            license_url=source.license_url,
            attribution=source.attribution,
            excerpt_sha256=record.excerpt_sha256,
            excerpt_text=record.text,
            consumer_age_min=consumer_age_min,
            consumer_age_max=consumer_age_max,
        )
        if chunk_id in result:
            raise ValueError("pinned package contains a duplicate record id")
        result[chunk_id] = card
    if not result:
        raise ValueError("pinned package contains no eligible student records")
    return result


class ResearchGeneralEducationDraftService:
    """Run one fixed research request and return a candidate only in HELD."""

    def __init__(
        self,
        *,
        safety: SafetyClient,
        retriever: SchoolResearchStudentRetrieverPort,
        runtime: ResearchGeneralEducationRuntimePort,
        policy_pins: ResearchGeneralEducationPolicyPins,
        source_cards: Mapping[str, ResearchGeneralEducationSourceCard],
    ) -> None:
        if not callable(getattr(safety, "check_input", None)):
            raise TypeError("research Safety client is required")
        if not callable(getattr(retriever, "retrieve", None)):
            raise TypeError("pinned research retriever is required")
        if not callable(getattr(runtime, "generate", None)):
            raise TypeError("dedicated research Runtime port is required")
        if not isinstance(policy_pins, ResearchGeneralEducationPolicyPins):
            raise TypeError("server-owned research policy pins are required")
        for digest in (policy_pins.policy_hash, policy_pins.source_manifest_sha256):
            if type(digest) is not str or _SHA256.fullmatch(digest) is None:
                raise ValueError("research policy/source digest pin is invalid")
        if not policy_pins.source_package_ref or not policy_pins.source_study_ref:
            raise ValueError("pinned research source references are required")
        validated_cards: dict[str, ResearchGeneralEducationSourceCard] = {}
        for key, value in source_cards.items():
            card = (
                value
                if isinstance(value, ResearchGeneralEducationSourceCard)
                else ResearchGeneralEducationSourceCard.model_validate(value, strict=True)
            )
            if key != card.chunk_id or card.chunk_id in validated_cards:
                raise ValueError("server source-card index is invalid")
            if (card.consumer_age_min, card.consumer_age_max) != (14, 17):
                raise ValueError("source-card consumer age scope is not pinned")
            if hashlib.sha256(card.excerpt_text.encode("utf-8")).hexdigest() != card.excerpt_sha256:
                raise ValueError("source-card excerpt digest is invalid")
            validated_cards[key] = card
        self.safety = safety
        self.retriever = retriever
        self.runtime = runtime
        self.policy_pins = policy_pins
        self.source_cards = validated_cards

    async def generate(
        self,
        *,
        caller_role: Literal["SYSTEM", "PSYCHOLOGICAL_SPECIALIST"],
        request_context: RequestContext,
    ) -> ResearchGeneralEducationOutcome:
        return await self._generate(
            caller_role=caller_role,
            request_context=request_context,
            authorization=None,
        )

    async def generate_reviewed_input(
        self,
        *,
        caller_role: Literal["SYSTEM"],
        request_context: RequestContext,
        authorization: ResearchGeneralEducationReviewedInputAuthorization,
    ) -> ResearchGeneralEducationOutcome:
        """Continue only from a current worker-loaded, exact receipt capability."""
        if caller_role != "SYSTEM":
            raise error(ErrorCode.FORBIDDEN, detail="reviewed continuation is worker-only")
        return await self._generate(
            caller_role=caller_role,
            request_context=request_context,
            authorization=authorization,
        )

    async def _generate(
        self,
        *,
        caller_role: Literal["SYSTEM", "PSYCHOLOGICAL_SPECIALIST"],
        request_context: RequestContext,
        authorization: ResearchGeneralEducationReviewedInputAuthorization | None,
    ) -> ResearchGeneralEducationOutcome:
        if caller_role not in {"SYSTEM", "PSYCHOLOGICAL_SPECIALIST"}:
            raise error(ErrorCode.FORBIDDEN, detail="research draft access denied")
        if not isinstance(request_context, RequestContext):
            raise error(ErrorCode.VALIDATION_FAILED, detail="request context is invalid")

        safety_context = _safety_context(request_context, caller_role)
        if authorization is None:
            try:
                input_check = await self.safety.check_input(safety_context, request_context)
            except Exception:
                return _outcome("FAILED", "INPUT_SAFETY_UNAVAILABLE")
            input_codes = _safety_codes(input_check, "INPUT", request_context)
            if input_codes is None:
                return _outcome("FAILED", "INPUT_SAFETY_INVALID")
            input_action, input_reasons = input_codes
            stopped = _safety_stop(input_action, input_check.decision.requires_human)
            if stopped:
                input_review = (
                    _input_review_receipt(
                        input_check,
                        safety_context=safety_context,
                        request_context=request_context,
                        policy_pins=self.policy_pins,
                    )
                    if stopped == "REVIEW_REQUIRED"
                    else None
                )
                return ResearchGeneralEducationOutcome(
                    status=stopped,
                    reason_code="INPUT_SAFETY_STOP",
                    input_review=input_review,
                )
        else:
            if not _valid_reviewed_input_authorization(
                authorization,
                request_context=request_context,
                policy_pins=self.policy_pins,
            ):
                return _outcome("FAILED", "INPUT_REVIEW_AUTHORIZATION_INVALID")
            input_action = authorization.receipt.action
            input_reasons = list(authorization.receipt.reason_codes)

        retrieval_id = f"RETR_{uuid4().hex}"
        generation_id = f"GEN_{uuid4().hex}"
        try:
            retrieval = await self.retriever.retrieve(
                query=_FIXED_QUERY,
                target_population="secondary_school_student",
                top_k=3,
                required_layers=tuple(_EXPECTED_LAYERS),
                retrieval_id=retrieval_id,
                context=request_context,
            )
        except Exception:
            return _outcome("FAILED", "RESEARCH_RETRIEVAL_UNAVAILABLE")
        if not _valid_retrieval(retrieval, self.policy_pins, retrieval_id):
            return _outcome("ABSTAINED", "RESEARCH_EVIDENCE_INVALID")

        try:
            bundle = build_retrieval_evidence_bundle(
                retrieval,
                transaction_id=generation_id,
                request_id=request_context.request_id,
                trace_id=request_context.trace_id,
                policy=EligibilityPolicy(
                    target_population="secondary_school_student",
                    target_role="student",
                    risk_level=None,
                    required_review_status="pending",
                    required_rights_status="verified",
                ),
                strict_eligibility=True,
            )
            bundle.require_eligible()
        except (EvidenceShapeError, ValueError, TypeError):
            return _outcome("ABSTAINED", "RESEARCH_EVIDENCE_INELIGIBLE")
        if not bundle.items:
            return _outcome("ABSTAINED", "ZERO_EVIDENCE")
        if any(chunk_id not in self.source_cards for chunk_id in bundle.chunk_ids):
            return _outcome("ABSTAINED", "SOURCE_CARD_UNAVAILABLE")
        if not _source_cards_match_bundle(bundle, self.source_cards):
            return _outcome("ABSTAINED", "SOURCE_CARD_BINDING_INVALID")

        retrieval_context = {
            **safety_context,
            "retrieval_metadata": {
                "purpose": "RESEARCH_SIMULATION",
                "retrieval_id": retrieval_id,
                "retrieval_bundle_sha256": bundle.bundle_hash,
                "source_manifest_sha256": self.policy_pins.source_manifest_sha256,
                "matched_layers": _EXPECTED_LAYERS,
                "research_only": True,
                "professional_approval": False,
                "publication_eligible": False,
                "production_use": False,
            },
        }
        try:
            retrieval_check = await self.safety.check_retrieval(
                retrieval_context, bundle.trusted_chunks(), request_context
            )
        except Exception:
            return _outcome("FAILED", "RETRIEVAL_SAFETY_UNAVAILABLE")
        retrieval_codes = _safety_codes(retrieval_check, "RETRIEVAL", request_context)
        if retrieval_codes is None:
            return _outcome("FAILED", "RETRIEVAL_SAFETY_INVALID")
        retrieval_action, retrieval_reasons = retrieval_codes
        stopped = _safety_stop(retrieval_action, retrieval_check.decision.requires_human)
        if stopped:
            return _outcome(stopped, "RETRIEVAL_SAFETY_STOP")

        sources = tuple(
            ResearchGeneralEducationRuntimeSource(
                chunk_id=item.chunk_id,
                text=item.text or "",
                title=str(item.citation.get("title") or ""),
                organization=str(item.citation.get("organization") or ""),
                locator=item.locator or "",
            )
            for item in bundle.items
        )
        if not _within_runtime_evidence_budget(sources):
            return _outcome("REVIEW_REQUIRED", "RUNTIME_EVIDENCE_BUDGET_EXCEEDED")
        try:
            generated = await self.runtime.generate(
                context=request_context,
                generation_id=generation_id,
                retrieval_id=retrieval_id,
                source_manifest_sha256=self.policy_pins.source_manifest_sha256,
                prompt_id=PROMPT_ID,
                prompt_version=PROMPT_VERSION,
                prompt_sha256=PROMPT_SHA256,
                sources=sources,
            )
        except Exception:
            return _outcome("FAILED", "RESEARCH_RUNTIME_FAILED")
        if not _valid_runtime_result(generated, request_context, generation_id, retrieval_id):
            return _outcome("FAILED", "RESEARCH_RUNTIME_RESPONSE_INVALID")
        if len(generated.content_json) > _MAX_GENERATED_CONTENT_CHARS:
            return _outcome("FAILED", "RESEARCH_CONTENT_SIZE_EXCEEDED")
        try:
            content_data = _strict_json_object(generated.content_json)
            content = GenerationContent.model_validate(content_data, strict=True)
        except (ValueError, TypeError):
            return _outcome("FAILED", "RESEARCH_CONTENT_INVALID")
        output_context = {
            **safety_context,
            "generation_metadata": {
                "purpose": "RESEARCH_SIMULATION",
                "research_only": True,
                "generation_id": generation_id,
                "retrieval_id": retrieval_id,
                "source_chunk_ids": list(bundle.chunk_ids),
                "model_id": generated.model_id,
                "model_version": generated.model_version,
                "model_digest_sha256": generated.model_digest_sha256,
                "prompt_id": PROMPT_ID,
                "prompt_version": PROMPT_VERSION,
                "prompt_sha256": PROMPT_SHA256,
                "publication_eligible": False,
                "production_use": False,
            },
        }
        try:
            output_check = await self.safety.check_output(
                output_context, generated.content_json, request_context
            )
        except Exception:
            return _outcome("FAILED", "OUTPUT_SAFETY_UNAVAILABLE")
        output_codes = _safety_codes(output_check, "OUTPUT", request_context)
        if output_codes is None:
            return _outcome("FAILED", "OUTPUT_SAFETY_INVALID")
        output_action, output_reasons = output_codes
        stopped = _safety_stop(output_action, output_check.decision.requires_human)
        if stopped:
            return _outcome(stopped, "OUTPUT_SAFETY_STOP")

        if not _content_well_formed(content):
            return _outcome("ABSTAINED", "RESEARCH_CONTENT_EMPTY")
        if _contains_forbidden_generated_claim(content):
            return _outcome("ABSTAINED", "RESEARCH_CLAIM_BOUNDARY_REJECTED")
        if _contains_unsupported_bibliography(
            content,
            bundle,
            original_disclaimer="本草稿仅用于一般教育信息研究复核，不构成诊断或个体建议。",
        ):
            return _outcome("ABSTAINED", "RESEARCH_BIBLIOGRAPHY_REJECTED")
        try:
            citations = SupportOrchestrator._citations_from_bundle(bundle, content)
        except (CitationBindingError, EvidenceShapeError, ValueError, TypeError):
            return _outcome("ABSTAINED", "RESEARCH_CITATION_BINDING_REJECTED")
        if not citations:
            return _outcome("ABSTAINED", "RESEARCH_ZERO_BOUND_CITATIONS")
        cited_ids = [citation.chunk_id for citation in citations]
        if any(chunk_id is None for chunk_id in cited_ids):
            return _outcome("ABSTAINED", "RESEARCH_CITATION_BINDING_REJECTED")

        source_cards = [self.source_cards[chunk_id] for chunk_id in cited_ids]
        provenance = ResearchGeneralEducationProvenance(
            policy_version="RESEARCH_GENERAL_EDUCATION_DRAFT_V1",
            policy_hash=self.policy_pins.policy_hash,
            safety_policy_version=SAFETY_POLICY_VERSION,
            source_package_ref=self.policy_pins.source_package_ref,
            source_study_ref=self.policy_pins.source_study_ref,
            source_manifest_sha256=self.policy_pins.source_manifest_sha256,
            source_age_scope="14-17",
            retrieval_id=retrieval_id,
            retrieval_bundle_sha256=bundle.bundle_hash,
            cited_chunk_ids=cited_ids,
            generation_id=generation_id,
            prompt_id=PROMPT_ID,
            prompt_version=PROMPT_VERSION,
            prompt_sha256=PROMPT_SHA256,
            model_id=generated.model_id,
            model_version=generated.model_version,
            model_digest_sha256=generated.model_digest_sha256,
            runtime_version=generated.runtime_version,
            runtime_attempt_count=1,
            runtime_retry_count=0,
            runtime_fallback_count=0,
            runtime_fallback_attempted=False,
            runtime_local_only=True,
            input_safety_action=input_action,
            input_safety_reason_codes=input_reasons,
            retrieval_safety_action=retrieval_action,
            retrieval_safety_reason_codes=retrieval_reasons,
            output_safety_action=output_action,
            output_safety_reason_codes=output_reasons,
        )
        try:
            candidate = ResearchGeneralEducationCandidatePayload.from_closed_mapping(
                {
                    "schema_version": "school-research-general-education-candidate.v1",
                    "content": content.model_dump(mode="python"),
                    "citations": [citation.model_dump(mode="python") for citation in citations],
                    "source_cards": [card.model_dump(mode="python") for card in source_cards],
                    "provenance": provenance.model_dump(mode="python"),
                }
            )
        except (ValueError, TypeError):
            return _outcome("FAILED", "RESEARCH_CANDIDATE_BINDING_INVALID")
        return ResearchGeneralEducationOutcome(
            status="HELD",
            reason_code="AWAITING_SOURCE_LIMIT_AND_CONTENT_REVIEW",
            candidate=candidate,
        )


def canonical_candidate_payload_sha256(
    payload: ResearchGeneralEducationCandidatePayload,
) -> str:
    """Stable payload digest for immutable encrypted-candidate storage metadata."""
    canonical = json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def canonical_input_context_sha256(
    *, policy_pins: ResearchGeneralEducationPolicyPins
) -> str:
    """Hash the fixed SYSTEM input and trusted pins, without caller text or IDs."""
    if not isinstance(policy_pins, ResearchGeneralEducationPolicyPins):
        raise ValueError("trusted research policy pins are required")
    expected_input = _fixed_review_input_context()
    if (
        type(policy_pins.policy_hash) is not str
        or _SHA256.fullmatch(policy_pins.policy_hash) is None
        or type(policy_pins.source_manifest_sha256) is not str
        or _SHA256.fullmatch(policy_pins.source_manifest_sha256) is None
        or type(policy_pins.source_package_ref) is not str
        or not policy_pins.source_package_ref
        or len(policy_pins.source_package_ref) > 255
        or type(policy_pins.source_study_ref) is not str
        or not policy_pins.source_study_ref
        or len(policy_pins.source_study_ref) > 255
    ):
        raise ValueError("trusted research policy/source pins are invalid")
    binding = {
        "schema_version": "school-research-general-education-input-binding.v1",
        "input_context": expected_input,
        "policy": {
            "policy_version": GENERAL_EDUCATION_POLICY_VERSION,
            "policy_hash": policy_pins.policy_hash,
            "safety_policy_version": SAFETY_POLICY_VERSION,
        },
        "source": {
            "source_package_ref": policy_pins.source_package_ref,
            "source_study_ref": policy_pins.source_study_ref,
            "source_manifest_sha256": policy_pins.source_manifest_sha256,
            "source_age_scope": "14-17",
        },
        "prompt": {
            "prompt_id": PROMPT_ID,
            "prompt_version": PROMPT_VERSION,
            "prompt_sha256": PROMPT_SHA256,
        },
    }
    canonical = json.dumps(
        binding,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _valid_reviewed_input_authorization(
    authorization: ResearchGeneralEducationReviewedInputAuthorization,
    *,
    request_context: RequestContext,
    policy_pins: ResearchGeneralEducationPolicyPins,
) -> bool:
    if type(authorization) is not ResearchGeneralEducationReviewedInputAuthorization:
        return False
    receipt = authorization.receipt
    try:
        expected_input_hash = canonical_input_context_sha256(policy_pins=policy_pins)
    except (TypeError, ValueError):
        return False
    now = datetime.now(UTC)
    return (
        authorization.authorized_state_version == 2
        and receipt.review_ref == authorization.input_review_ref
        and authorization.continuation_job_ref.startswith("REJ_")
        and authorization.continuation_trace_id == request_context.trace_id
        and receipt.trace_id != authorization.continuation_trace_id
        and authorization.continuation_policy_version
        == INPUT_REVIEW_CONTINUATION_POLICY_VERSION
        and authorization.continuation_policy_hash
        == INPUT_REVIEW_CONTINUATION_POLICY_SHA256
        and receipt.operation == "INPUT"
        and receipt.action == "REVIEW_REQUIRED"
        and receipt.reason_codes == ("CONTENT_CONTROVERSIAL",)
        and receipt.requires_human is True
        and receipt.canonical_input_sha256 == expected_input_hash
        and receipt.policy_version == GENERAL_EDUCATION_POLICY_VERSION
        and receipt.policy_hash == policy_pins.policy_hash
        and receipt.safety_policy_version == SAFETY_POLICY_VERSION
        and receipt.source_package_ref == policy_pins.source_package_ref
        and receipt.source_study_ref == policy_pins.source_study_ref
        and receipt.source_manifest_sha256 == policy_pins.source_manifest_sha256
        and receipt.source_age_scope == "14-17"
        and receipt.prompt_id == PROMPT_ID
        and receipt.prompt_version == PROMPT_VERSION
        and receipt.prompt_sha256 == PROMPT_SHA256
        and authorization.expires_at.astimezone(UTC) > now
    )


def _matches_fixed_input_safety_context(context: Mapping[str, object]) -> bool:
    """Require the actual Safety call to use the exact fixed worker projection."""
    expected_input = _fixed_review_input_context()
    expected_keys = set(expected_input) | {"request_id", "trace_id"}
    if not isinstance(context, Mapping) or set(context) != expected_keys:
        return False
    request_id = context.get("request_id")
    trace_id = context.get("trace_id")
    if (
        type(request_id) is not str
        or valid_correlation_id(request_id, "REQ") != request_id
        or type(trace_id) is not str
        or valid_correlation_id(trace_id, "TRACE") != trace_id
    ):
        return False
    actual_input = {key: context[key] for key in expected_input}
    try:
        actual_input_json = json.dumps(
            actual_input,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        expected_input_json = json.dumps(
            expected_input,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return False
    return actual_input_json == expected_input_json


def _fixed_review_input_context() -> dict[str, object]:
    """Exact stable projection used by `_safety_context` for worker SYSTEM calls."""
    return {
        "actor_role": "SYSTEM",
        "age_group": "UNKNOWN",
        "assessment_signals": [],
        "current_user_message": FIXED_GENERAL_EDUCATION_REQUEST,
        "conversation_metadata": {
            "purpose": "RESEARCH_SIMULATION",
            "research_only": True,
            "student_data_supplied": False,
            "student_feedback_eligible": False,
            "publication_eligible": False,
            "production_use": False,
            "target_audience": "secondary_school_student_14_17",
        },
        "retrieval_metadata": {},
        "generation_metadata": {},
        "component_health": {},
    }


def _input_review_receipt(
    check: SafetyCheckView,
    *,
    safety_context: Mapping[str, object],
    request_context: RequestContext,
    policy_pins: ResearchGeneralEducationPolicyPins,
) -> ResearchGeneralEducationInputReviewReceipt | None:
    """Project only fully bound, real Safety INPUT review evidence."""
    if (
        not isinstance(check, SafetyCheckView)
        or check.operation != "INPUT"
        or check.trace_id != request_context.trace_id
        or check.decision.trace_id != request_context.trace_id
        or check.decision.action != "REVIEW_REQUIRED"
        or check.decision.requires_human is not True
        or check.decision.reason_codes != ["CONTENT_CONTROVERSIAL"]
        or not check.decision.decision_id
        or not check.review_reference
    ):
        return None
    if not _matches_fixed_input_safety_context(safety_context):
        return None
    if (
        safety_context.get("request_id") != request_context.request_id
        or safety_context.get("trace_id") != request_context.trace_id
    ):
        return None
    try:
        input_digest = canonical_input_context_sha256(
            policy_pins=policy_pins,
        )
        return ResearchGeneralEducationInputReviewReceipt(
            schema_version="school-research-general-education-input-review.v1",
            operation=check.operation,
            action=check.decision.action,
            reason_codes=tuple(check.decision.reason_codes),
            requires_human=check.decision.requires_human,
            decision_id=check.decision.decision_id,
            review_ref=check.review_reference,
            trace_id=check.trace_id,
            canonical_input_sha256=input_digest,
            policy_version=GENERAL_EDUCATION_POLICY_VERSION,
            policy_hash=policy_pins.policy_hash,
            safety_policy_version=SAFETY_POLICY_VERSION,
            source_package_ref=policy_pins.source_package_ref,
            source_study_ref=policy_pins.source_study_ref,
            source_manifest_sha256=policy_pins.source_manifest_sha256,
            source_age_scope="14-17",
            prompt_id=PROMPT_ID,
            prompt_version=PROMPT_VERSION,
            prompt_sha256=PROMPT_SHA256,
        )
    except (TypeError, ValueError):
        return None


def _safety_context(
    context: RequestContext,
    caller_role: Literal["SYSTEM", "PSYCHOLOGICAL_SPECIALIST"],
) -> dict[str, object]:
    return {
        "request_id": context.request_id,
        "trace_id": context.trace_id,
        "actor_role": caller_role,
        "age_group": "UNKNOWN",
        "assessment_signals": [],
        "current_user_message": FIXED_GENERAL_EDUCATION_REQUEST,
        "conversation_metadata": {
            "purpose": "RESEARCH_SIMULATION",
            "research_only": True,
            "student_data_supplied": False,
            "student_feedback_eligible": False,
            "publication_eligible": False,
            "production_use": False,
            "target_audience": "secondary_school_student_14_17",
        },
        "retrieval_metadata": {},
        "generation_metadata": {},
        "component_health": {},
    }


def _safety_codes(
    check: SafetyCheckView, stage: Literal["INPUT", "RETRIEVAL", "OUTPUT"], context: RequestContext
) -> tuple[SafetyAction, list[str]] | None:
    if (
        not isinstance(check, SafetyCheckView)
        or check.operation != stage
        or check.trace_id != context.trace_id
        or check.decision.trace_id != context.trace_id
        or type(check.decision.requires_human) is not bool
        or not check.decision.reason_codes
        or any(
            type(code) is not str or re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code) is None
            for code in check.decision.reason_codes
        )
    ):
        return None
    return check.decision.action, list(dict.fromkeys(check.decision.reason_codes))


def _safety_stop(action: SafetyAction, requires_human: bool) -> str | None:
    if action == "CRISIS_ROUTE":
        return "CRISIS_ROUTED"
    if action == "REVIEW_REQUIRED" or requires_human:
        return "REVIEW_REQUIRED"
    if action in {"BLOCK"}:
        return "ABSTAINED"
    return None if action in {"PROCEED", "PROCEED_WITH_BOUNDARY"} else "FAILED"


def _valid_retrieval(
    retrieval: RetrievalResult,
    pins: ResearchGeneralEducationPolicyPins,
    expected_retrieval_id: str,
) -> bool:
    if (
        not isinstance(retrieval, RetrievalResult)
        or retrieval.retrieval_id != expected_retrieval_id
        or retrieval.label != "SCHOOL_RESEARCH_STUDENT_SOURCE_PACKAGE"
        or not isinstance(retrieval.trace, Mapping)
    ):
        return False
    trace = retrieval.trace
    return (
        trace.get("package_id") == pins.source_package_ref
        and trace.get("study_ref") == pins.source_study_ref
        and trace.get("manifest_sha256") == pins.source_manifest_sha256
        and trace.get("purpose") == "RESEARCH_SIMULATION"
        and trace.get("target_population") == "secondary_school_student"
        and trace.get("target_role") == "student"
        and trace.get("review_status") == "pending"
        and trace.get("rights_status") == "verified"
        and trace.get("source_rights_status") == "VERIFIED_WITH_CONDITIONS"
        and trace.get("consumer_age_min") == 14
        and trace.get("consumer_age_max") == 17
        and trace.get("research_only") is True
        and trace.get("professional_approval") is False
        and trace.get("human_curated") is False
        and trace.get("ethics_approval") is False
        and trace.get("clinical_approval") is False
        and trace.get("psychometric_approval") is False
        and trace.get("publication_eligible") is False
        and trace.get("production_use") is False
        and trace.get("matched_layers") == _EXPECTED_LAYERS
        and trace.get("missing_layers") == []
        and 1 <= len(retrieval.chunks) <= 8
    )


def _source_cards_match_bundle(
    bundle: RetrievalEvidenceBundle,
    source_cards: Mapping[str, ResearchGeneralEducationSourceCard],
) -> bool:
    for item in bundle.items:
        card = source_cards.get(item.chunk_id)
        if card is None:
            return False
        section = item.location.get("section") if item.location else None
        source_hash = item.content_hash or ""
        if source_hash.startswith("sha256:"):
            source_hash = source_hash[7:]
        if (
            item.chunk_id != f"CHUNK_SCHOOL_RESEARCH_{card.record_id}"
            or card.excerpt_text != item.text
            or card.excerpt_sha256 != source_hash
            or card.record_locator != section
            or card.title != item.citation.get("title")
            or card.organization != item.citation.get("organization")
            or (card.consumer_age_min, card.consumer_age_max) != (14, 17)
        ):
            return False
    return True


def _within_runtime_evidence_budget(
    sources: Sequence[ResearchGeneralEducationRuntimeSource],
) -> bool:
    projection = [
        {
            "chunk_id": source.chunk_id,
            "text": source.text,
            "title": source.title,
            "organization": source.organization,
            "locator": source.locator,
        }
        for source in sources
    ]
    encoded = json.dumps(projection, ensure_ascii=False, separators=(",", ":"))
    return len(encoded) <= _MAX_RUNTIME_EVIDENCE_CHARS


def _valid_runtime_result(
    result: ResearchGeneralEducationRuntimeResult,
    context: RequestContext,
    generation_id: str,
    retrieval_id: str,
) -> bool:
    return (
        isinstance(result, ResearchGeneralEducationRuntimeResult)
        and result.request_id == context.request_id
        and result.trace_id == context.trace_id
        and result.generation_id == generation_id
        and result.retrieval_id == retrieval_id
        and result.prompt_id == PROMPT_ID
        and result.prompt_version == PROMPT_VERSION
        and result.prompt_sha256 == PROMPT_SHA256
        and result.model_id == EXPECTED_MODEL_ID
        and result.model_version == EXPECTED_MODEL_VERSION
        and result.model_digest_sha256 == EXPECTED_MODEL_DIGEST_SHA256
        and bool(result.runtime_version.strip())
        and result.attempt_count == 1
        and result.retry_count == 0
        and result.fallback_count == 0
        and result.fallback_attempted is False
        and result.local_only is True
        and result.synthetic_fixture_only is False
    )


def _strict_json_object(raw: str) -> dict[str, object]:
    def no_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    value = json.loads(
        raw,
        object_pairs_hook=no_duplicate_pairs,
        parse_constant=_reject_json_constant,
    )
    if type(value) is not dict:
        raise ValueError("generated JSON must be an object")
    return value


def _reject_json_constant(value: str) -> None:
    raise ValueError("non-standard JSON constant")


def _content_well_formed(content: GenerationContent) -> bool:
    return (
        bool(content.summary.strip())
        and bool(content.disclaimer.strip())
        and all(type(value) is str and value.strip() for value in content.observations)
        and all(
            bool(suggestion.text.strip())
            and bool(suggestion.source_chunk_ids)
            and len(set(suggestion.source_chunk_ids)) == len(suggestion.source_chunk_ids)
            for suggestion in content.suggestions
        )
    )


def _outcome(status: str, reason_code: str) -> ResearchGeneralEducationOutcome:
    return ResearchGeneralEducationOutcome(status=status, reason_code=reason_code)
