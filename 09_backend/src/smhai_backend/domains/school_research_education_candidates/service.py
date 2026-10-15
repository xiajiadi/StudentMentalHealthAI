"""Task-scoped specialist access to held research education candidates."""

from __future__ import annotations

import re
from collections.abc import Mapping

from pydantic import ValidationError

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.domains.research_general_education.schemas import (
    ResearchGeneralEducationCandidatePayload,
)

from .schemas import (
    ResearchEducationCandidateBatchDto,
    ResearchEducationCandidateBatchRequest,
    ResearchEducationCandidateDetailDto,
    ResearchEducationCandidateListDto,
    ResearchEducationCandidateResolutionRequest,
    ResearchEducationCandidateSummaryDto,
    ResearchEducationCandidateTaskListDto,
    ResearchEducationGenerationJobListDto,
    ResearchEducationInputReviewDetailDto,
    ResearchEducationInputReviewListDto,
    ResearchEducationInputReviewResolutionRequest,
    ResearchEducationInputReviewSummaryDto,
    ResearchEducationOutputReviewDetailDto,
    ResearchEducationOutputReviewListDto,
    ResearchEducationOutputReviewResolutionDto,
    ResearchEducationOutputReviewResolutionRequest,
)

_INPUT_REVIEW_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class SchoolResearchEducationCandidateService:
    """Expose no candidate operation without the configured persistence port."""

    def __init__(self, *, persistence=None) -> None:
        self.persistence = persistence

    def _port(self):
        if self.persistence is None:
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="research education candidates are unavailable",
                retryable=True,
            )
        return self.persistence

    @staticmethod
    def _require_specialist(actor: Actor) -> None:
        if (
            not isinstance(actor, Actor)
            or actor.scope_profile != "school_tenant"
            or actor.role is not BackendRole.PSYCHOLOGICAL_SPECIALIST
            or type(actor.school_id) is not int
            or actor.school_id <= 0
            or type(actor.school_ref) is not str
            or not actor.school_ref
        ):
            raise error(ErrorCode.FORBIDDEN, detail="access denied")

    @staticmethod
    def _validate(model, values):
        try:
            return model.model_validate(values, strict=True)
        except (ValidationError, ValueError) as exc:
            raise error(
                ErrorCode.VALIDATION_FAILED,
                detail="research education candidate request is invalid",
            ) from exc

    @staticmethod
    def _project(model, value):
        if not isinstance(value, Mapping):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research education candidate is unavailable",
            )
        try:
            values = dict(value)
            if model is ResearchEducationCandidateDetailDto:
                payload_value = values.get("candidate_payload")
                if type(payload_value) is ResearchGeneralEducationCandidatePayload:
                    payload = payload_value
                else:
                    payload = ResearchGeneralEducationCandidatePayload.from_closed_mapping(
                        payload_value
                    )
                values["candidate_payload"] = payload
            elif model is ResearchEducationOutputReviewDetailDto:
                from smhai_backend.domains.research_general_education.schemas import (
                    ResearchGeneralEducationSourceCard,
                )
                from smhai_backend.domains.support.schemas import GenerationContent, SupportCitation

                from .schemas import ResearchEducationOutputReviewPayloadDto

                payload_value = values.get("review_payload")
                if not isinstance(payload_value, Mapping):
                    raise ValueError("output review payload is unavailable")
                payload_values = dict(payload_value)
                payload_values["content"] = GenerationContent.model_validate(
                    payload_values.get("content"), strict=True
                )
                source_cards = payload_values.get("source_cards")
                if not isinstance(source_cards, list):
                    raise ValueError("output review sources are unavailable")
                payload_values["source_cards"] = [
                    ResearchGeneralEducationSourceCard.model_validate(card, strict=True)
                    for card in source_cards
                ]
                citations = payload_values.get("citations")
                citation_fields = set(SupportCitation.model_fields)
                if not isinstance(citations, list) or any(
                    not isinstance(citation, Mapping)
                    or set(citation) - citation_fields
                    for citation in citations
                ):
                    raise ValueError("output review citations are invalid")
                payload_values["citations"] = [
                    SupportCitation.model_validate(citation, strict=True)
                    for citation in citations
                ]
                from smhai_backend.domains.research_general_education.schemas import (
                    ResearchGeneralEducationOutputReviewProvenance,
                )

                payload_values["provenance"] = (
                    ResearchGeneralEducationOutputReviewProvenance.model_validate(
                        payload_values.get("provenance"), strict=True
                    )
                )
                payload_values["provenance"] = payload_values["provenance"].model_dump(
                    mode="python"
                )
                payload = ResearchEducationOutputReviewPayloadDto.model_validate(
                    payload_values, strict=True
                )
                values["review_payload"] = payload
            return model.model_validate(values, strict=True).model_dump(mode="python")
        except (ValidationError, ValueError) as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research education candidate is unavailable",
            ) from exc

    @staticmethod
    def _pagination(offset: int, limit: int) -> None:
        if (
            type(offset) is not int
            or not 0 <= offset <= 100_000
            or type(limit) is not int
            or not 1 <= limit <= 50
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="pagination is invalid")

    @staticmethod
    def _input_review_ref(value: str, name: str) -> str:
        if type(value) is not str or _INPUT_REVIEW_REF.fullmatch(value) is None:
            raise error(ErrorCode.VALIDATION_FAILED, detail=f"{name} is invalid")
        return value

    @staticmethod
    def _input_review_pagination(offset: int, limit: int) -> None:
        if (
            type(offset) is not int
            or not 0 <= offset <= 100_000
            or type(limit) is not int
            or not 1 <= limit <= 20
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="pagination is invalid")

    @staticmethod
    def _output_review_pagination(offset: int, limit: int) -> None:
        if (
            type(offset) is not int
            or not 0 <= offset <= 100_000
            or type(limit) is not int
            or not 1 <= limit <= 20
        ):
            raise error(ErrorCode.VALIDATION_FAILED, detail="pagination is invalid")

    async def list_tasks(self, actor: Actor):
        self._require_specialist(actor)
        result = await self._port().school_research_education_candidate_list_tasks(actor)
        return self._project(ResearchEducationCandidateTaskListDto, result)

    async def list_for_task(
        self, actor: Actor, task_ref: str, *, status="HELD", offset=0, limit=20
    ):
        self._require_specialist(actor)
        self._pagination(offset, limit)
        result = await self._port().school_research_education_candidate_list(
            actor, task_ref, status=status, offset=offset, limit=limit
        )
        return self._project(ResearchEducationCandidateListDto, result)

    async def list_jobs(self, actor: Actor, task_ref: str, *, offset=0, limit=20):
        self._require_specialist(actor)
        self._pagination(offset, limit)
        result = await self._port().school_research_education_candidate_generation_job_list(
            actor, task_ref, offset=offset, limit=limit
        )
        return self._project(ResearchEducationGenerationJobListDto, result)

    async def list_input_reviews(
        self, actor: Actor, task_ref: str, *, offset=0, limit=20
    ):
        self._require_specialist(actor)
        task_ref = self._input_review_ref(task_ref, "task_ref")
        self._input_review_pagination(offset, limit)
        result = await self._port().school_research_education_input_review_list(
            actor, task_ref, offset=offset, limit=limit
        )
        page = self._project(ResearchEducationInputReviewListDto, result)
        if (
            page["offset"] != offset
            or page["limit"] != limit
            or (page["has_more"] and len(page["items"]) != limit)
            or any(item["task_ref"] != task_ref for item in page["items"])
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research education input review is unavailable",
            )
        return page

    async def get_input_review(self, actor: Actor, task_ref: str, input_review_ref: str):
        self._require_specialist(actor)
        task_ref = self._input_review_ref(task_ref, "task_ref")
        input_review_ref = self._input_review_ref(input_review_ref, "input_review_ref")
        result = await self._port().school_research_education_input_review_get(
            actor, task_ref, input_review_ref
        )
        detail = self._project(ResearchEducationInputReviewDetailDto, result)
        if detail["task_ref"] != task_ref or detail["input_review_ref"] != input_review_ref:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research education input review is unavailable",
            )
        return detail

    async def list_output_reviews(self, actor: Actor, task_ref: str, *, offset=0, limit=20):
        self._require_specialist(actor)
        task_ref = self._input_review_ref(task_ref, "task_ref")
        self._output_review_pagination(offset, limit)
        result = await self._port().school_research_education_output_review_list(
            actor, task_ref, offset=offset, limit=limit
        )
        page = self._project(ResearchEducationOutputReviewListDto, result)
        if (
            page["offset"] != offset
            or page["limit"] != limit
            or (page["has_more"] and len(page["items"]) != limit)
            or any(item["task_ref"] != task_ref for item in page["items"])
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research education output review is unavailable",
            )
        return page

    async def get_output_review(self, actor: Actor, task_ref: str, output_review_ref: str):
        self._require_specialist(actor)
        task_ref = self._input_review_ref(task_ref, "task_ref")
        output_review_ref = self._input_review_ref(output_review_ref, "output_review_ref")
        result = await self._port().school_research_education_output_review_get(
            actor, task_ref, output_review_ref
        )
        detail = self._project(ResearchEducationOutputReviewDetailDto, result)
        if (
            detail["task_ref"] != task_ref
            or detail["output_review_ref"] != output_review_ref
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research education output review is unavailable",
            )
        return detail

    async def resolve_output_review(
        self,
        actor: Actor,
        task_ref: str,
        output_review_ref: str,
        *,
        expected_state_version: int,
        target: str,
        idempotency,
        trace_id: str,
    ):
        self._require_specialist(actor)
        task_ref = self._input_review_ref(task_ref, "task_ref")
        output_review_ref = self._input_review_ref(output_review_ref, "output_review_ref")
        request = self._validate(
            ResearchEducationOutputReviewResolutionRequest,
            {"expected_state_version": expected_state_version, "target": target},
        )
        result = await self._port().school_research_education_output_review_resolve(
            actor,
            task_ref,
            output_review_ref,
            expected_state_version=request.expected_state_version,
            target=request.target,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        projected = self._project(ResearchEducationOutputReviewResolutionDto, result)
        output_review = projected["output_review"]
        expected_status = {
            "REJECTED": "REJECTED",
            "REVOKED": "REVOKED",
            "CREATE_HELD_CANDIDATE": "CONSUMED",
        }[request.target]
        if (
            output_review["task_ref"] != task_ref
            or output_review["output_review_ref"] != output_review_ref
            or output_review["status"] != expected_status
            or output_review["state_version"] != 2
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research education output review is unavailable",
            )
        return projected

    async def resolve_input_review(
        self,
        actor: Actor,
        task_ref: str,
        input_review_ref: str,
        *,
        expected_state_version: int,
        target: str,
        idempotency,
        trace_id: str,
    ):
        self._require_specialist(actor)
        task_ref = self._input_review_ref(task_ref, "task_ref")
        input_review_ref = self._input_review_ref(input_review_ref, "input_review_ref")
        request = self._validate(
            ResearchEducationInputReviewResolutionRequest,
            {"expected_state_version": expected_state_version, "target": target},
        )
        result = await self._port().school_research_education_input_review_resolve(
            actor,
            task_ref,
            input_review_ref,
            expected_state_version=request.expected_state_version,
            target=request.target,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        summary = self._project(ResearchEducationInputReviewSummaryDto, result)
        expected_status_version = {
            "CONTINUATION_AUTHORIZED": ("CONTINUATION_AUTHORIZED", 2),
            "REJECTED": ("REJECTED", 2),
            "REVOKED": ("REVOKED", request.expected_state_version + 1),
        }[request.target]
        if (
            summary["task_ref"] != task_ref
            or summary["input_review_ref"] != input_review_ref
            or (summary["status"], summary["state_version"]) != expected_status_version
            or (
                request.target == "CONTINUATION_AUTHORIZED"
                and summary["continuation_enabled"] is not True
            )
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="research education input review is unavailable",
            )
        return summary

    async def get(self, actor: Actor, task_ref: str, candidate_ref: str):
        self._require_specialist(actor)
        result = await self._port().school_research_education_candidate_get(
            actor, task_ref, candidate_ref
        )
        return self._project(ResearchEducationCandidateDetailDto, result)

    async def queue_batch(
        self,
        actor: Actor,
        task_ref: str,
        *,
        limit: int = 25,
        offset: int = 0,
        idempotency,
        trace_id: str,
    ):
        self._require_specialist(actor)
        request = self._validate(
            ResearchEducationCandidateBatchRequest,
            {"limit": limit, "offset": offset},
        )
        result = await self._port().school_research_education_candidate_queue_batch(
            actor,
            task_ref,
            limit=request.limit,
            offset=request.offset,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        return self._project(ResearchEducationCandidateBatchDto, result)

    async def resolve(
        self,
        actor: Actor,
        task_ref: str,
        candidate_ref: str,
        *,
        expected_state_version: int,
        target: str,
        idempotency,
        trace_id: str,
    ):
        self._require_specialist(actor)
        request = self._validate(
            ResearchEducationCandidateResolutionRequest,
            {"expected_state_version": expected_state_version, "target": target},
        )
        result = await self._port().school_research_education_candidate_resolve(
            actor,
            task_ref,
            candidate_ref,
            expected_state_version=request.expected_state_version,
            target=request.target,
            idempotency=idempotency,
            trace_id=trace_id,
        )
        return self._project(ResearchEducationCandidateSummaryDto, result)
