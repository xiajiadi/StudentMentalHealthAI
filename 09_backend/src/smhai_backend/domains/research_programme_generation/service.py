"""Safety-first, hold-only orchestration for internal school-programme references."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.request_context import RequestContext
from smhai_backend.domains.models import BackendRole
from smhai_backend.integrations.research_programme import (
    EXPECTED_MODEL_DIGEST,
    PROMPT_ID,
    PROMPT_VERSION,
    RuntimeGeneration,
    RuntimeSource,
)
from smhai_backend.integrations.safety import SafetyCheckView, SafetyClient

from .schemas import (
    RESEARCH_SCOPE,
    ResearchProgrammeCandidate,
    ResearchProgrammeCitation,
    ResearchProgrammeOutcome,
    ResearchProgrammeSafetyEvidence,
    canonical_sha256,
    validate_retrieval_evidence,
)

_EXPECTED_ROLE = "psychological_specialist"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CLAIM_BOUNDARY = re.compile(
    r"(?i)(\bdiagnos(?:e|is|tic)\b|\bclinical\b|\btreatment\b|\btherapy\b|"
    r"\bcure\b|\bscore(?:s|d|ing)?\b|\btest result\b|\bassess(?:ment|ed|ing) result\b|"
    r"\bguarantee(?:d|s)?\b|\bproven effective\b|\beffect(?:ive|iveness)\b|"
    r"\bimprov(?:e|es|ed|ing)\b|\beffects?\b|\bcausal(?:ity)?\b|"
    r"\b(results?|outcomes?|impact|benefits?|success(?:ful)?)\b|"
    r"\bachiev(?:e|es|ed|ing)\b|\byour (?:score|result|symptom|assessment)\b|"
    r"\byou should\b|\breport(?:s|ed|ing)?\b|\bindividual(?:ized|ised)? feedback\b|"
    r"\bindividual student\b|\bfor each student\b|"
    r"诊断|治疗|疗效|治愈|测评分数|测评结果|风险等级|个体反馈|保证有效|显著改善|"
    r"报告|个人建议|你应该|针对每位学生)"
)
_FIXED_RETRIEVAL_QUERY = (
    "WHO HAT strategy policy healthy school environment school climate "
    "supportive school programme implementation theory"
)
_INPUT_MESSAGE = (
    "Prepare an internal staff-only general school-programme reference from "
    "pinned public research excerpts. No student, assessment, score, or personal data is supplied."
)


class ResearchRetrieverPort(Protocol):
    def retrieve(self, query: str, *, caller_role: str, limit: int = 3) -> Any: ...


class ResearchRuntimePort(Protocol):
    async def generate_programme(
        self,
        *,
        context: RequestContext,
        retrieval_id: str,
        programme_ref: str,
        source_manifest_sha256: str,
        sources: tuple[RuntimeSource, ...],
    ) -> RuntimeGeneration: ...


class ResearchProgrammeGenerationService:
    """Generate only a staff research reference and leave it in HELD state."""

    def __init__(
        self,
        *,
        safety: SafetyClient,
        retriever: ResearchRetrieverPort,
        runtime: ResearchRuntimePort,
        expected_manifest_sha256: str,
        clock=None,
    ) -> None:
        if not callable(getattr(safety, "check_input", None)):
            raise TypeError("research Safety client must be configured")
        if not callable(getattr(retriever, "retrieve", None)):
            raise TypeError("research retriever must be configured")
        if not callable(getattr(runtime, "generate_programme", None)):
            raise TypeError("research Runtime client must be configured")
        if (
            type(expected_manifest_sha256) is not str
            or _SHA256.fullmatch(expected_manifest_sha256) is None
        ):
            raise ValueError("trusted research manifest pin is invalid")
        self.safety = safety
        self.retriever = retriever
        self.runtime = runtime
        self.expected_manifest_sha256 = expected_manifest_sha256
        self._clock = clock or (lambda: datetime.now(UTC))

    async def generate(
        self,
        *,
        actor_role: BackendRole,
        request_context: RequestContext,
    ) -> ResearchProgrammeOutcome:
        if actor_role is not BackendRole.PSYCHOLOGICAL_SPECIALIST:
            raise error(ErrorCode.FORBIDDEN, detail="research programme access denied")
        if not isinstance(request_context, RequestContext):
            raise error(ErrorCode.VALIDATION_FAILED, detail="request context is invalid")

        safety_context = _safety_context(request_context)
        input_check = await self.safety.check_input(safety_context, request_context)
        input_evidence = _validated_safety_evidence("INPUT", input_check, request_context)
        if not _safety_allows_generation(input_evidence):
            return _halt("INPUT_SAFETY_STOP", input_check)

        try:
            retrieval = self.retriever.retrieve(
                _FIXED_RETRIEVAL_QUERY,
                caller_role=_EXPECTED_ROLE,
                limit=4,
            )
        except (PermissionError, RuntimeError, ValueError):
            # Retrieval errors contain package paths/implementation details in
            # some environments; this lane exposes one stable abstention only.
            return _abstain("RESEARCH_RETRIEVAL_UNAVAILABLE")
        if not validate_retrieval_evidence(
            retrieval,
            self.expected_manifest_sha256,
            self._clock(),
        ):
            return _abstain("RESEARCH_EVIDENCE_INCOMPLETE_OR_UNTRUSTED")
        retrieval_id = f"RETR_{uuid4().hex}"
        retrieval_bundle_sha256 = _retrieval_bundle_sha256(retrieval, retrieval_id)
        chunk_ids = tuple(_chunk_id(hit.record_id) for hit in retrieval.hits)
        chunk_set_sha256 = canonical_sha256(sorted(chunk_ids))
        source_ids = tuple(sorted({hit.citation.source_id for hit in retrieval.hits}))
        source_set_sha256 = canonical_sha256(source_ids)

        safety_retrieval_context = {
            **safety_context,
            "retrieval_metadata": {
                "retrieval_status": "MATCHES",
                "retriever": "BM25S",
                "retrieval_id": retrieval_id,
                "retrieval_bundle_sha256": retrieval_bundle_sha256,
                "chunk_count": len(retrieval.hits),
                "research_only": True,
                "research_scope": RESEARCH_SCOPE,
                "reviewer_kind": "AI_ENGINEERING",
                "human_curated": False,
                "professional_approval": False,
                "ethics_approval": False,
                "clinical_approval": False,
                "psychometric_approval": False,
                "publication_eligible": False,
                "production_use": False,
            },
        }
        safety_chunks = [_safety_projection(hit) for hit in retrieval.hits]
        retrieval_check = await self.safety.check_retrieval(
            safety_retrieval_context,
            safety_chunks,
            request_context,
        )
        retrieval_evidence = _validated_safety_evidence(
            "RETRIEVAL", retrieval_check, request_context
        )
        if not _safety_allows_generation(retrieval_evidence):
            return _halt("RETRIEVAL_SAFETY_STOP", retrieval_check)

        programme_ref = "PROGRAMME_SCHOOL_CONNECTEDNESS_REFERENCE_V1"
        runtime_sources = tuple(
            RuntimeSource(
                chunk_id=_chunk_id(hit.record_id),
                text=hit.text,
                citation_label=f"{hit.citation.publisher}: {hit.citation.title}",
                locator=hit.citation.locator,
            )
            for hit in retrieval.hits
        )
        generated = await self.runtime.generate_programme(
            context=request_context,
            retrieval_id=retrieval_id,
            programme_ref=programme_ref,
            source_manifest_sha256=retrieval.manifest_sha256,
            sources=runtime_sources,
        )
        if not _valid_runtime_generation(
            generated,
            retrieval,
            retrieval_id,
            programme_ref,
            request_context,
        ):
            return _abstain("RESEARCH_RUNTIME_RESPONSE_INVALID")
        if _CLAIM_BOUNDARY.search(f"{generated.title}\n{generated.body}"):
            return _abstain("RESEARCH_OUTPUT_OUT_OF_SCOPE")

        output_check = await self.safety.check_output(
            {
                **safety_context,
                "generation_metadata": {
                    "purpose": "staff_research_reference",
                    "research_only": True,
                    "research_scope": RESEARCH_SCOPE,
                    "evidence_limit": (
                        "POTENTIAL_SCHOOL_PROGRAMME_FRAMEWORKS_ONLY_OUTCOMES_NOT_ESTABLISHED"
                    ),
                    "source_chunk_ids": list(generated.citation_chunk_ids),
                    "model_id": generated.model_id,
                    "model_version": generated.model_version,
                    "model_digest": generated.model_digest,
                    "prompt_id": generated.prompt_id,
                    "prompt_version": generated.prompt_version,
                    "prompt_sha256": generated.prompt_sha256,
                    "retrieval_id": generated.retrieval_id,
                    "generation_id": generated.generation_id,
                    "publication_eligible": False,
                    "production_use": False,
                },
            },
            f"{generated.title}\n\n{generated.body}",
            request_context,
        )
        output_evidence = _validated_safety_evidence("OUTPUT", output_check, request_context)
        if not _safety_allows_generation(output_evidence):
            return _halt("OUTPUT_SAFETY_STOP", output_check)

        citations = tuple(
            _citation_for_hit(hit)
            for hit in retrieval.hits
            if _chunk_id(hit.record_id) in set(generated.citation_chunk_ids)
        )
        if not citations or {citation.chunk_id for citation in citations} != set(
            generated.citation_chunk_ids
        ):
            return _abstain("RESEARCH_CITATION_BINDING_INVALID")
        candidate = ResearchProgrammeCandidate(
            programme_ref=programme_ref,
            title=generated.title,
            body=generated.body,
            citations=citations,
            request_id=generated.request_id,
            trace_id=generated.trace_id,
            generation_id=generated.generation_id,
            retrieval_id=generated.retrieval_id,
            prompt_id=generated.prompt_id,
            prompt_version=generated.prompt_version,
            prompt_sha256=generated.prompt_sha256,
            retrieval_bundle_sha256=retrieval_bundle_sha256,
            chunk_set_sha256=chunk_set_sha256,
            source_set_sha256=source_set_sha256,
            safety_evidence=(
                input_evidence,
                retrieval_evidence,
                output_evidence,
            ),
            source_manifest_sha256=retrieval.manifest_sha256,
            study_ref=retrieval.study_ref,
            valid_through_month=retrieval.valid_through_month,
            model_version=generated.model_version,
            runtime_version=generated.runtime_version,
            model_digest=generated.model_digest,
        )
        return ResearchProgrammeOutcome(
            status="HELD",
            reason_code="AWAITING_INTERNAL_RESEARCH_REVIEW",
            candidate=candidate,
        )


def _safety_context(context: RequestContext) -> dict[str, Any]:
    return {
        "request_id": context.request_id,
        "trace_id": context.trace_id,
        "actor_role": "SYSTEM",
        "age_group": "UNKNOWN",
        "assessment_signals": [],
        "current_user_message": _INPUT_MESSAGE,
        "conversation_metadata": {
            "purpose": "staff_school_programme_research",
            "research_only": True,
            "research_scope": RESEARCH_SCOPE,
            "student_data_supplied": False,
            "student_feedback_eligible": False,
            "publication_eligible": False,
            "production_use": False,
        },
        "retrieval_metadata": {},
        "generation_metadata": {},
        "component_health": {},
    }


def _validated_safety_evidence(
    stage: str,
    check: SafetyCheckView,
    context: RequestContext,
) -> ResearchProgrammeSafetyEvidence:
    expected_operation = stage
    if (
        check.operation != expected_operation
        or check.trace_id != context.trace_id
        or check.decision.trace_id != context.trace_id
        or type(check.decision.requires_human) is not bool
        or not check.decision.reason_codes
        or any(type(code) is not str or not code for code in check.decision.reason_codes)
    ):
        raise error(
            ErrorCode.DEPENDENCY_INVALID_RESPONSE,
            status_code=502,
            detail="Safety returned an invalid research decision projection",
        )
    return ResearchProgrammeSafetyEvidence(
        stage=stage,
        action=check.decision.action,
        reason_codes=tuple(check.decision.reason_codes),
        trace_id=check.trace_id,
        requires_human=check.decision.requires_human,
    )


def _safety_allows_generation(evidence: ResearchProgrammeSafetyEvidence) -> bool:
    return evidence.action in {"PROCEED", "PROCEED_WITH_BOUNDARY"} and not evidence.requires_human


def _retrieval_bundle_sha256(retrieval: Any, retrieval_id: str) -> str:
    citations = []
    for hit in retrieval.hits:
        citation = hit.citation
        citations.append(
            {
                "record_id": hit.record_id,
                "chunk_id": _chunk_id(hit.record_id),
                "layer": hit.layer,
                "text": hit.text,
                "rank": hit.rank,
                "lexical_score": hit.lexical_score,
                "source_population": hit.source_population,
                "certainty": hit.certainty,
                "citation": {
                    "source_id": citation.source_id,
                    "title": citation.title,
                    "publisher": citation.publisher,
                    "year": citation.year,
                    "locator": citation.locator,
                    "source_url": citation.source_url,
                    "official_pdf_url": citation.official_pdf_url,
                    "rights_listing_url": citation.rights_listing_url,
                    "license": citation.license,
                    "license_url": citation.license_url,
                    "attribution": citation.attribution,
                    "source_extraction_sha256": citation.source_extraction_sha256,
                    "excerpt_sha256": citation.excerpt_sha256,
                },
            }
        )
    bundle = {
        "schema": "psynova.research-retrieval-bundle.v1",
        "retrieval_id": retrieval_id,
        "package_id": retrieval.package_id,
        "manifest_sha256": retrieval.manifest_sha256,
        "study_ref": retrieval.study_ref,
        "research_scope": retrieval.scope,
        "use_mode": retrieval.use_mode,
        "role_scope": list(retrieval.role_scope),
        "population_scope": list(retrieval.population_scope),
        "risk_scope": list(retrieval.risk_scope),
        "valid_through_month": retrieval.valid_through_month,
        "reviewer_kind": retrieval.reviewer_kind,
        "human_curated": retrieval.human_curated,
        "professional_approval": retrieval.professional_approval,
        "ethics_approval": retrieval.ethics_approval,
        "clinical_approval": retrieval.clinical_approval,
        "psychometric_approval": retrieval.psychometric_approval,
        "publication_eligible": retrieval.publication_eligible,
        "production_use": retrieval.production_use,
        "hits": citations,
    }
    return canonical_sha256(bundle)


def _chunk_id(record_id: str) -> str:
    return f"CHUNK_RESEARCH_{record_id}"


def _safety_projection(hit: Any) -> dict[str, Any]:
    return {
        "text": hit.text,
        "chunk_id": _chunk_id(hit.record_id),
        # This is a narrow projection of AI_ENGINEERING review and rights
        # verification for Safety's existing retrieval interface. Research
        # limitations remain separately explicit in the Safety context.
        "review_status": "approved",
        "rights_status": "verified",
        "research_only": True,
        "reviewer_kind": "AI_ENGINEERING",
        "professional_approval": False,
        "publication_eligible": False,
        "production_use": False,
    }


def _valid_runtime_generation(
    generated: Any,
    retrieval: Any,
    retrieval_id: str,
    programme_ref: str,
    context: RequestContext,
) -> bool:
    try:
        from smhai_backend.domains.research_programme_generation.schemas import (
            validate_source_bound_body,
        )

        if (
            not isinstance(generated, RuntimeGeneration)
            or generated.request_id != context.request_id
            or generated.trace_id != context.trace_id
            or generated.retrieval_id != retrieval_id
            or generated.programme_ref != programme_ref
            or generated.source_manifest_sha256 != retrieval.manifest_sha256
            or type(generated.title) is not str
            or not generated.title.strip()
            or len(generated.title) > 120
            or type(generated.body) is not str
            or not generated.body.strip()
            or len(generated.body) > 3_000
            or generated.model_id != "qwen2.5-7b-instruct-school-demo"
            or generated.model_version != "qwen2.5:7b-instruct-q4_K_M"
            or generated.model_digest != EXPECTED_MODEL_DIGEST
            or generated.prompt_id != PROMPT_ID
            or generated.prompt_version != PROMPT_VERSION
            or _SHA256.fullmatch(generated.prompt_sha256) is None
            or generated.target_role != "psychological_specialist"
            or generated.purpose != "staff_school_programme_research"
            or generated.status != "HOLD_FOR_REVIEW"
            or generated.publication_eligible is not False
            or generated.production_use is not False
            or not generated.runtime_version
            or len(generated.runtime_version) > 64
            or type(generated.citation_chunk_ids) is not tuple
            or not set(generated.citation_chunk_ids).issubset(
                {_chunk_id(hit.record_id) for hit in retrieval.hits}
            )
        ):
            return False
        validate_source_bound_body(generated.body, list(generated.citation_chunk_ids))
        return True
    except (AttributeError, TypeError, ValueError):
        return False


def _citation_for_hit(hit: Any) -> ResearchProgrammeCitation:
    citation = hit.citation
    return ResearchProgrammeCitation(
        chunk_id=_chunk_id(hit.record_id),
        layer=hit.layer,
        source_id=citation.source_id,
        title=citation.title,
        publisher=citation.publisher,
        year=citation.year,
        locator=citation.locator,
        source_url=citation.source_url,
        license=citation.license,
        license_url=citation.license_url,
        attribution=citation.attribution,
        source_extraction_sha256=citation.source_extraction_sha256,
        excerpt_sha256=citation.excerpt_sha256,
        source_population=hit.source_population,
        certainty=hit.certainty,
    )


def _abstain(reason_code: str) -> ResearchProgrammeOutcome:
    return ResearchProgrammeOutcome(status="ABSTAINED", reason_code=reason_code)


def _halt(reason_code: str, check: SafetyCheckView) -> ResearchProgrammeOutcome:
    return ResearchProgrammeOutcome(
        status="HALTED",
        reason_code=reason_code,
        safety_action=check.decision.action,
    )
