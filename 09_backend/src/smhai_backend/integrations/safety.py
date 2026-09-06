"""Backend Safety port and the real loopback HTTP adapter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.request_context import RequestContext

from .common_http import LongLivedHttpClient, UpstreamError, translate_upstream_error

SafetyAction = Literal[
    "PROCEED", "PROCEED_WITH_BOUNDARY", "BLOCK", "REVIEW_REQUIRED", "CRISIS_ROUTE"
]


class SafetyDecisionView(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action: SafetyAction
    reason_codes: list[str] = Field(min_length=1)
    requires_human: bool
    trace_id: str = Field(min_length=1)
    review_case_id: str | None = None
    crisis_template_id: str | None = None
    disclosure_policy: str = "FULL"


class SafetyCheckView(BaseModel):
    model_config = ConfigDict(extra="ignore")

    operation: str
    decision: SafetyDecisionView
    trace_id: str = Field(min_length=1)
    crisis_response: str | None = None
    review_case: dict[str, Any] | None = None
    sanitized_text: str | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> SafetyCheckView:
        decision_value = payload.get("decision")
        if not isinstance(decision_value, Mapping):
            raise ValueError("Safety response has no decision object")
        decision = SafetyDecisionView.model_validate(decision_value)
        review_case = payload.get("review_case")
        if review_case is not None and not isinstance(review_case, Mapping):
            raise ValueError("Safety response review_case is not an object")
        return cls(
            operation=str(payload.get("operation", "INPUT")),
            decision=decision,
            trace_id=str(payload.get("trace_id") or decision.trace_id),
            crisis_response=(
                str(payload["crisis_response"])
                if payload.get("crisis_response") is not None
                else None
            ),
            review_case=dict(review_case) if isinstance(review_case, Mapping) else None,
            sanitized_text=(
                str(payload["sanitized_text"])
                if payload.get("sanitized_text") is not None
                else None
            ),
        )

    @property
    def review_reference(self) -> str | None:
        if self.decision.review_case_id:
            return self.decision.review_case_id
        if self.review_case:
            value = self.review_case.get("review_case_id") or self.review_case.get("review_id")
            return str(value) if value else None
        return None


class SafetyClient(Protocol):
    label: str

    async def start(self) -> None: ...
    async def close(self) -> None: ...
    async def check_input(
        self, context: Mapping[str, Any], request_context: RequestContext
    ) -> SafetyCheckView: ...
    async def check_output(
        self, context: Mapping[str, Any], candidate_text: str, request_context: RequestContext
    ) -> SafetyCheckView: ...
    async def check_retrieval(
        self,
        context: Mapping[str, Any],
        chunks: Sequence[Mapping[str, Any]],
        request_context: RequestContext,
    ) -> SafetyCheckView: ...
    async def health(self, request_context: RequestContext) -> dict[str, Any]: ...
    async def finalize_review(
        self, review_case_id: str, *, request_context: RequestContext
    ) -> None: ...


class HttpSafetyClient(LongLivedHttpClient):
    label = "REAL_HTTP"

    async def check_input(
        self, context: Mapping[str, Any], request_context: RequestContext
    ) -> SafetyCheckView:
        return await self._check(
            "/internal/safety/check-input",
            {"context": dict(context)},
            request_context,
        )

    async def check_output(
        self, context: Mapping[str, Any], candidate_text: str, request_context: RequestContext
    ) -> SafetyCheckView:
        return await self._check(
            "/internal/safety/check-output",
            {"context": dict(context), "candidate_text": candidate_text},
            request_context,
        )

    async def check_retrieval(
        self,
        context: Mapping[str, Any],
        chunks: Sequence[Mapping[str, Any]],
        request_context: RequestContext,
    ) -> SafetyCheckView:
        safety_chunks = [self._retrieval_chunk_for_safety(chunk) for chunk in chunks]
        return await self._check(
            "/internal/safety/check-retrieval",
            {"context": dict(context), "chunks": safety_chunks},
            request_context,
        )

    async def health(self, request_context: RequestContext) -> dict[str, Any]:
        try:
            return await self.get_json("/health", context=request_context)
        except UpstreamError as exc:
            raise translate_upstream_error(exc) from exc

    async def finalize_review(
        self, review_case_id: str, *, request_context: RequestContext
    ) -> None:
        for status in ("ASSIGNED", "IN_REVIEW", "APPROVED"):
            try:
                await self.post_json(
                    f"/internal/safety/reviews/{review_case_id}/transition",
                    {"to_status": status, "actor_id": "synthetic-reviewer-001"},
                    context=request_context,
                )
            except UpstreamError as exc:
                raise translate_upstream_error(exc) from exc

    async def _check(
        self, path: str, payload: Mapping[str, Any], request_context: RequestContext
    ) -> SafetyCheckView:
        try:
            response = await self.post_json(path, payload, context=request_context)
            return SafetyCheckView.from_payload(response)
        except UpstreamError as exc:
            raise translate_upstream_error(exc) from exc
        except ValueError as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                status_code=502,
                detail="Safety returned an invalid decision",
            ) from exc

    @staticmethod
    def _retrieval_chunk_for_safety(chunk: Mapping[str, Any]) -> dict[str, Any]:
        """Translate the frozen knowledge projection to Safety's chunk port.

        Backend and Safety intentionally own different representations: the
        Backend keeps ``text`` and eligibility fields in ``knowledge.v1``,
        while Safety's retrieval adapter consumes ``content`` plus a compact
        ``metadata`` object.  Sending only the required projection avoids
        coupling the two contracts or forwarding unrelated source fields.
        """

        content = chunk.get("text")
        if not isinstance(content, str):
            content = chunk.get("content")
        metadata = {
            "chunk_id": str(chunk.get("chunk_id", "")),
            "review_status": str(chunk.get("review_status", "")),
            "rights_status": str(chunk.get("rights_status", "")),
        }
        return {"content": content if isinstance(content, str) else "", "metadata": metadata}


@dataclass(slots=True)
class ContractFakeSafetyClient:
    """Synthetic adapter used when a real Safety process is not requested."""

    label: str = "CONTRACT_FAKE"
    input_calls: int = 0
    output_calls: int = 0
    retrieval_calls: int = 0
    call_order: list[str] = field(default_factory=list)
    available: bool = True

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def health(self, request_context: RequestContext) -> dict[str, Any]:
        if not self.available:
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="required dependency could not complete the request",
                retryable=True,
            )
        return {"status": "READY", "mode": self.label}

    async def check_input(
        self, context: Mapping[str, Any], request_context: RequestContext
    ) -> SafetyCheckView:
        self.input_calls += 1
        self.call_order.append("safety_input")
        if not self.available:
            raise error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="required dependency could not complete the request",
                retryable=True,
            )
        message = str(context.get("current_user_message", ""))
        if "SYNTHETIC_CRISIS_SIGNAL" in message:
            return self._decision(
                "CRISIS_ROUTE",
                ["CRISIS_SIGNAL"],
                request_context,
                crisis_response=(
                    "这是合成演示中的安全提示，当前内容需要人工复核。请使用已确认的本地支持流程。"
                ),
            )
        if "SYNTHETIC_BLOCK" in message:
            return self._decision("BLOCK", ["CONTENT_UNSAFE"], request_context)
        if "SYNTHETIC_REVIEW" in message:
            return self._decision("REVIEW_REQUIRED", ["INPUT_REVIEW_REQUIRED"], request_context)
        return self._decision("PROCEED", ["NO_BLOCKING_SIGNAL"], request_context)

    async def check_output(
        self, context: Mapping[str, Any], candidate_text: str, request_context: RequestContext
    ) -> SafetyCheckView:
        self.output_calls += 1
        self.call_order.append("safety_output")
        if "SYNTHETIC_UNSAFE_OUTPUT" in candidate_text:
            return self._decision("REVIEW_REQUIRED", ["OUTPUT_REVIEW_REQUIRED"], request_context)
        return self._decision("PROCEED", ["CONTENT_SAFE"], request_context)

    async def check_retrieval(
        self,
        context: Mapping[str, Any],
        chunks: Sequence[Mapping[str, Any]],
        request_context: RequestContext,
    ) -> SafetyCheckView:
        self.retrieval_calls += 1
        self.call_order.append("safety_retrieval")
        return self._decision("PROCEED", ["RETRIEVAL_SAFE"], request_context)

    async def finalize_review(
        self, review_case_id: str, *, request_context: RequestContext
    ) -> None:
        self.call_order.append("safety_review")

    @staticmethod
    def _decision(
        action: SafetyAction,
        reason_codes: list[str],
        request_context: RequestContext,
        *,
        crisis_response: str | None = None,
    ) -> SafetyCheckView:
        requires_human = action in {"BLOCK", "REVIEW_REQUIRED", "CRISIS_ROUTE"}
        review_id = f"REVIEW_fake_{uuid4().hex}" if requires_human else None
        decision = SafetyDecisionView(
            action=action,
            reason_codes=reason_codes,
            requires_human=requires_human,
            trace_id=request_context.trace_id,
            review_case_id=review_id,
            crisis_template_id="CRISIS_SYNTHETIC_001" if action == "CRISIS_ROUTE" else None,
        )
        return SafetyCheckView(
            operation="INPUT",
            decision=decision,
            trace_id=request_context.trace_id,
            crisis_response=crisis_response,
        )
