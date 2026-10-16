"""Consent-scoped workflow over the independent research education review port."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from types import SimpleNamespace

from pydantic import ValidationError

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.idempotency import fingerprint
from smhai_backend.core.request_context import RequestContext
from smhai_backend.domains.conversations.service import _contains_unsupported_bibliography
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.domains.support.schemas import GenerationContent
from smhai_backend.domains.support.service import _contains_forbidden_generated_claim
from smhai_backend.integrations.safety import SafetyCheckView, SafetyClient

from .schemas import (
    EducationReviewStateRequest,
    IndependentEducationPublishSafetyCheck,
    IndependentEducationReviewerListDto,
    IndependentEducationReviewPageDto,
    IndependentEducationReviewSummaryDto,
    IndependentEducationStaffDetailDto,
    IndependentEducationStaffPageDto,
    SaveEducationReviewDraftRequest,
    ShareEducationReviewRequest,
    publish_material_sha256,
)

_SAFE_REASON = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class IndependentEducationReviewService:
    """Expose held content only to the explicitly assigned active specialist."""

    def __init__(self, *, persistence=None, safety: SafetyClient | None = None) -> None:
        self.persistence = persistence
        self.safety = safety

    def _port(self):
        if self.persistence is None:
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="independent education reviews are unavailable",
                retryable=True,
            )
        return self.persistence

    @staticmethod
    def _student(actor: Actor) -> None:
        if (
            not isinstance(actor, Actor)
            or actor.scope_profile != "school_tenant"
            or actor.role is not BackendRole.STUDENT
            or type(actor.school_id) is not int
            or actor.school_id <= 0
            or not actor.school_ref
            or not actor.subject_id
        ):
            raise error(ErrorCode.FORBIDDEN, detail="access denied")

    @staticmethod
    def _specialist(actor: Actor) -> None:
        if (
            not isinstance(actor, Actor)
            or actor.scope_profile != "school_tenant"
            or actor.role is not BackendRole.PSYCHOLOGICAL_SPECIALIST
            or type(actor.school_id) is not int
            or actor.school_id <= 0
            or not actor.school_ref
        ):
            raise error(ErrorCode.FORBIDDEN, detail="access denied")

    @staticmethod
    def _model(model, value):
        try:
            # Persistence projections encode timestamps as ISO-8601 strings at the adapter edge.
            # Strict field types still protect scalar identifiers and counters.
            return model.model_validate(value, strict=False)
        except (ValidationError, TypeError, ValueError):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE, detail="review is unavailable"
            ) from None

    @staticmethod
    def _request(model, value):
        try:
            return model.model_validate(value, strict=True)
        except (ValidationError, TypeError, ValueError):
            raise error(ErrorCode.VALIDATION_FAILED, detail="review request is invalid") from None

    @staticmethod
    def _text_is_reviewable(*, title: str, body: str, candidate: Mapping[str, object]) -> None:
        try:
            content_value = candidate.get("content")
            candidate_content = GenerationContent.model_validate(content_value, strict=True)
            reviewed_content = GenerationContent(
                summary=f"{title}\n{body}",
                observations=[],
                suggestions=[],
                disclaimer=candidate_content.disclaimer,
            )
            cards = candidate.get("source_cards")
            if not isinstance(cards, list):
                raise ValueError("source cards are unavailable")
            evidence_view = SimpleNamespace(
                items=[
                    SimpleNamespace(citation={"organization": card.get("organization")})
                    for card in cards
                    if isinstance(card, Mapping)
                ]
            )
        except (TypeError, ValueError, ValidationError):
            raise error(
                ErrorCode.WORKFLOW_CONFLICT, detail="review source is unavailable"
            ) from None
        if _contains_forbidden_generated_claim(reviewed_content):
            raise error(
                ErrorCode.VALIDATION_FAILED,
                detail="review text exceeds the general education content boundary",
            )
        if _contains_unsupported_bibliography(
            reviewed_content,
            evidence_view,
            original_disclaimer=candidate_content.disclaimer,
        ):
            raise error(
                ErrorCode.VALIDATION_FAILED,
                detail="review text contains an unsupported citation detail",
            )

    @staticmethod
    def _validate_page(offset: int, limit: int) -> None:
        if (
            type(offset) is not int
            or not 0 <= offset <= 100_000
            or type(limit) is not int
            or not 1 <= limit <= 50
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="pagination is invalid")

    async def student_list(self, actor: Actor, conversation_id: str, *, offset=0, limit=20):
        self._student(actor)
        self._validate_page(offset, limit)
        value = await self._port().student_list(actor, conversation_id, offset=offset, limit=limit)
        return self._model(IndependentEducationReviewPageDto, value)

    async def student_reviewers(self, actor: Actor, conversation_id: str, *, offset=0, limit=20):
        self._student(actor)
        self._validate_page(offset, limit)
        value = await self._port().student_reviewers(
            actor, conversation_id, offset=offset, limit=limit
        )
        return self._model(IndependentEducationReviewerListDto, value)

    async def share(
        self,
        actor: Actor,
        conversation_id: str,
        review_ref: str,
        *,
        payload: ShareEducationReviewRequest,
        idempotency_key: str,
        context: RequestContext,
    ):
        self._student(actor)
        request = self._request(ShareEducationReviewRequest, payload)
        result = await self._port().share(
            actor,
            conversation_id,
            review_ref,
            expected_version=request.expected_version,
            reviewer_ref=request.reviewer_ref,
            consent=request.consent,
            idempotency=(idempotency_key, fingerprint(request.model_dump(mode="json"))),
            trace_id=context.trace_id,
        )
        return self._model(IndependentEducationReviewSummaryDto, result)

    async def withdraw(
        self,
        actor: Actor,
        conversation_id: str,
        review_ref: str,
        *,
        payload: EducationReviewStateRequest,
        idempotency_key: str,
        context: RequestContext,
    ):
        self._student(actor)
        request = self._request(EducationReviewStateRequest, payload)
        result = await self._port().withdraw(
            actor,
            conversation_id,
            review_ref,
            expected_version=request.expected_version,
            idempotency=(idempotency_key, fingerprint(request.model_dump(mode="json"))),
            trace_id=context.trace_id,
        )
        return self._model(IndependentEducationReviewSummaryDto, result)

    async def staff_list(self, actor: Actor, *, offset=0, limit=20):
        self._specialist(actor)
        self._validate_page(offset, limit)
        value = await self._port().staff_list(actor, offset=offset, limit=limit)
        return self._model(IndependentEducationStaffPageDto, value)

    async def staff_detail(self, actor: Actor, review_ref: str):
        self._specialist(actor)
        value = await self._port().staff_detail(actor, review_ref)
        return self._model(IndependentEducationStaffDetailDto, value)

    async def save_draft(
        self,
        actor: Actor,
        review_ref: str,
        *,
        payload: SaveEducationReviewDraftRequest,
        idempotency_key: str,
        context: RequestContext,
    ):
        self._specialist(actor)
        request = self._request(SaveEducationReviewDraftRequest, payload)
        detail = await self._port().staff_detail(actor, review_ref)
        self._text_is_reviewable(
            title=request.title,
            body=request.body,
            candidate=detail["candidate"],
        )
        result = await self._port().save_draft(
            actor,
            review_ref,
            expected_version=request.expected_version,
            title=request.title,
            body=request.body,
            idempotency=(idempotency_key, fingerprint(request.model_dump(mode="json"))),
            trace_id=context.trace_id,
        )
        return self._model(IndependentEducationReviewSummaryDto, result)

    async def publish(
        self,
        actor: Actor,
        review_ref: str,
        *,
        payload: EducationReviewStateRequest,
        idempotency_key: str,
        context: RequestContext,
    ):
        self._specialist(actor)
        request = self._request(EducationReviewStateRequest, payload)
        detail = await self._port().staff_detail(actor, review_ref)
        if detail.get("status") == "PUBLISHED":
            result = await self._port().publish(
                actor,
                review_ref,
                expected_version=request.expected_version,
                idempotency=(idempotency_key, fingerprint(request.model_dump(mode="json"))),
                trace_id=context.trace_id,
            )
            return self._model(IndependentEducationReviewSummaryDto, result)
        draft = detail.get("reviewed_draft")
        if not isinstance(draft, Mapping):
            raise error(ErrorCode.WORKFLOW_CONFLICT, detail="a reviewed draft is required")
        self._text_is_reviewable(
            title=str(draft.get("title", "")),
            body=str(draft.get("body", "")),
            candidate=detail["candidate"],
        )
        safety_check = await self._check_publish_safety(
            candidate=detail["candidate"],
            draft=draft,
            request_context=context,
        )
        safety_material_sha256 = publish_material_sha256(detail["candidate"], draft)
        receipt = IndependentEducationPublishSafetyCheck(
            operation="OUTPUT",
            action=safety_check.decision.action,
            reason_codes=list(dict.fromkeys(safety_check.decision.reason_codes)),
            requires_human=False,
            decision_id=safety_check.decision.decision_id,
            trace_id=context.trace_id,
            checked_material_sha256=safety_material_sha256,
        )
        result = await self._port().publish(
            actor,
            review_ref,
            expected_version=request.expected_version,
            safety_material_sha256=safety_material_sha256,
            publish_safety_check=receipt.model_dump(mode="json"),
            idempotency=(idempotency_key, fingerprint(request.model_dump(mode="json"))),
            trace_id=context.trace_id,
        )
        return self._model(IndependentEducationReviewSummaryDto, result)

    async def _check_publish_safety(
        self,
        *,
        candidate: Mapping[str, object],
        draft: Mapping[str, object],
        request_context: RequestContext,
    ) -> SafetyCheckView:
        if self.safety is None:
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="reviewed content Safety is unavailable",
                retryable=True,
            )
        try:
            provenance = candidate["provenance"]
            content = candidate["content"]
            if not isinstance(provenance, Mapping) or not isinstance(content, Mapping):
                raise ValueError("review source metadata is unavailable")
            citations = candidate.get("citations")
            if not isinstance(citations, list):
                raise ValueError("review source citations are unavailable")
            output_content = GenerationContent(
                summary=f"{draft['title']}\n{draft['body']}",
                observations=[],
                suggestions=[],
                disclaimer=content["disclaimer"],
            )
            candidate_text = json.dumps(
                output_content.model_dump(mode="json"),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
            source_chunk_ids = [
                citation["chunk_id"]
                for citation in citations
                if isinstance(citation, Mapping) and isinstance(citation.get("chunk_id"), str)
            ]
            if len(source_chunk_ids) != len(citations) or not source_chunk_ids:
                raise ValueError("review source citations are unavailable")
            output_context = {
                "trace_id": request_context.trace_id,
                "request_id": request_context.request_id,
                "actor_role": "STUDENT",
                "age_group": "UNKNOWN",
                "assessment_signals": [],
                "current_user_message": "",
                "conversation_metadata": {
                    "source": "independent_research_education_review",
                    "purpose": provenance["purpose"],
                    "research_only": provenance["research_only"],
                    "study_ref": provenance["source_study_ref"],
                    "source_package_ref": provenance["source_package_ref"],
                    "source_manifest_sha256": provenance["source_manifest_sha256"],
                    "professional_approval": False,
                    "clinical_approval": False,
                    "psychometric_approval": False,
                    "ethics_approval": False,
                    "school_production_approval": False,
                },
                "retrieval_metadata": {
                    "retrieval_id": provenance["retrieval_id"],
                    "retrieval_bundle_sha256": provenance["retrieval_bundle_sha256"],
                    "source_chunk_ids": source_chunk_ids,
                    "citation_binding_status": provenance["citation_binding_status"],
                },
                "generation_metadata": {
                    "source_model_id": provenance["model_id"],
                    "source_model_digest_sha256": provenance["model_digest_sha256"],
                    "source_prompt_id": provenance["prompt_id"],
                    "source_prompt_version": provenance["prompt_version"],
                    "reviewed_content_revision": draft["content_revision"],
                    "publication_eligible": False,
                    "production_use": False,
                },
                "component_health": {},
            }
        except (KeyError, TypeError, ValueError):
            raise error(
                ErrorCode.WORKFLOW_CONFLICT, detail="review source is unavailable"
            ) from None
        try:
            checked = await self.safety.check_output(
                output_context, candidate_text, request_context
            )
        except Exception:
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="reviewed content Safety is unavailable",
                retryable=True,
            ) from None
        if (
            not isinstance(checked, SafetyCheckView)
            or checked.operation != "OUTPUT"
            or checked.trace_id != request_context.trace_id
            or checked.decision.trace_id != request_context.trace_id
            or type(checked.decision.requires_human) is not bool
            or not checked.decision.reason_codes
            or any(
                type(code) is not str or _SAFE_REASON.fullmatch(code) is None
                for code in checked.decision.reason_codes
            )
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="reviewed content Safety returned an invalid decision",
            )
        if (
            checked.decision.action not in {"PROCEED", "PROCEED_WITH_BOUNDARY"}
            or checked.decision.requires_human is not False
        ):
            raise error(
                ErrorCode.WORKFLOW_CONFLICT,
                detail="reviewed content did not pass Output Safety",
            )
        return checked

    async def revoke(
        self,
        actor: Actor,
        review_ref: str,
        *,
        payload: EducationReviewStateRequest,
        idempotency_key: str,
        context: RequestContext,
    ):
        self._specialist(actor)
        request = self._request(EducationReviewStateRequest, payload)
        result = await self._port().revoke(
            actor,
            review_ref,
            expected_version=request.expected_version,
            idempotency=(idempotency_key, fingerprint(request.model_dump(mode="json"))),
            trace_id=context.trace_id,
        )
        return self._model(IndependentEducationReviewSummaryDto, result)
