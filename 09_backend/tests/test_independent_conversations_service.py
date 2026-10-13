from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from pydantic import ValidationError

from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.core.request_context import RequestContext
from smhai_backend.domains.conversations.schemas import (
    ConversationCreateRequest,
    ConversationMessageRequest,
)
from smhai_backend.domains.conversations.service import IndependentConversationService
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.integrations.evidence import EligibilityPolicy, build_retrieval_evidence_bundle
from smhai_backend.integrations.independent import GenerationResult
from smhai_backend.integrations.rag import KnowledgeChunk, RetrievalResult
from smhai_backend.integrations.safety import SafetyCheckView, SafetyDecisionView

CONTEXT = RequestContext(request_id="REQ_test", trace_id="TRACE_test")
ACTOR = Actor(
    user_id="ACCOUNT_test",
    username="synthetic_student",
    role=BackendRole.STUDENT,
    subject_id="SUBJ_test",
    school_id=1,
    school_ref="SCHOOL_test",
)


class FakePersistence:
    def __init__(
        self,
        *,
        replayed: bool = False,
        history: Mapping[str, Any] | None = None,
    ) -> None:
        self.replayed = replayed
        self.history = dict(history or {"turns": [], "messages": []})
        self.reserve_calls: list[dict[str, Any]] = []
        self.finish_calls: list[dict[str, Any]] = []
        self.detail_calls: list[tuple[int, int]] = []

    async def create(self, actor: Actor, *, idempotency_key: str, trace_id: str) -> dict[str, Any]:
        return {
            "conversation_id": "CONV_test",
            "status": "open",
            "created_at": "2026-10-12T00:00:00Z",
            "updated_at": "2026-10-12T00:00:00Z",
        }

    async def list(self, actor: Actor, *, offset: int, limit: int) -> dict[str, Any]:
        return {"items": [], "total": 0, "has_more": False}

    async def detail(
        self, actor: Actor, conversation_id: str, *, offset: int, limit: int
    ) -> dict[str, Any]:
        self.detail_calls.append((offset, limit))
        all_turns = self.history["turns"]
        page_turns = all_turns[offset : offset + limit]
        page_ids = {turn["turn_id"] for turn in page_turns}
        page_messages = [
            message
            for message in self.history["messages"]
            if message.get("payload", {}).get("turn_id") in page_ids
        ]
        return {
            "conversation": await self.create(actor, idempotency_key="", trace_id=""),
            "messages": page_messages,
            "turns": page_turns,
            "offset": offset,
            "limit": limit,
            "total_turns": len(all_turns),
            "has_more": offset + len(page_turns) < len(all_turns),
        }

    async def reserve_turn(
        self,
        actor: Actor,
        conversation_id: str,
        *,
        message: str,
        idempotency_key: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.reserve_calls.append({"message": message, "conversation_id": conversation_id})
        return {
            "turn_id": "TURN_test",
            "status": "completed" if self.replayed else "requested",
            "replayed": self.replayed,
            "user_message_sequence": 1,
            **({"action": "PROCEED", "assistant_message_sequence": 2} if self.replayed else {}),
        }

    async def finish_turn(
        self,
        actor: Actor,
        conversation_id: str,
        turn_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        record = {"conversation_id": conversation_id, "turn_id": turn_id, **kwargs}
        self.finish_calls.append(record)
        return {
            "turn_id": turn_id,
            "status": str(kwargs["status"]).lower(),
            "action": kwargs["action"],
            "completed_at": "2026-10-12T00:00:01Z",
            "user_message_sequence": 1,
            "assistant_message_sequence": 2 if kwargs.get("approved_content") is not None else None,
            "citations": [dict(item) for item in kwargs.get("citations", ())],
            "safe_metadata": dict(kwargs.get("safe_metadata", {})),
        }


class FakeSafety:
    label = "FAKE"

    def __init__(
        self,
        *,
        input_action: str = "PROCEED",
        retrieval_action: str = "PROCEED",
        output_action: str = "PROCEED",
        error_stage: str | None = None,
    ) -> None:
        self.input_action = input_action
        self.retrieval_action = retrieval_action
        self.output_action = output_action
        self.error_stage = error_stage
        self.calls: list[str] = []
        self.contexts: list[Mapping[str, Any]] = []
        self.retrieval_chunks: list[Sequence[Mapping[str, Any]]] = []

    def _view(
        self,
        action: str,
        context: RequestContext,
        *,
        crisis: bool = False,
    ) -> SafetyCheckView:
        return SafetyCheckView(
            operation="INPUT",
            decision=SafetyDecisionView(
                action=action,  # type: ignore[arg-type]
                reason_codes=["SYNTHETIC_TEST"],
                requires_human=action in {"BLOCK", "REVIEW_REQUIRED", "CRISIS_ROUTE"},
                trace_id=context.trace_id,
                crisis_template_id="CRISIS_APPROVED_TEST" if crisis else None,
            ),
            trace_id=context.trace_id,
            crisis_response="已审核的合成安全提示，请使用已确认的本地支持流程。"
            if crisis
            else None,
        )

    def _raise_if(self, stage: str) -> None:
        if self.error_stage == stage:
            raise TimeoutError("synthetic dependency timeout")

    async def check_input(self, context: Mapping[str, Any], request_context: RequestContext):
        self.calls.append("safety_input")
        self.contexts.append(context)
        self._raise_if("input")
        return self._view(
            self.input_action,
            request_context,
            crisis=self.input_action == "CRISIS_ROUTE",
        )

    async def check_retrieval(
        self,
        context: Mapping[str, Any],
        chunks: Sequence[Mapping[str, Any]],
        request_context: RequestContext,
    ):
        self.calls.append("safety_retrieval")
        self.contexts.append(context)
        self.retrieval_chunks.append(chunks)
        self._raise_if("retrieval")
        return self._view(self.retrieval_action, request_context)

    async def check_output(
        self, context: Mapping[str, Any], candidate_text: str, request_context: RequestContext
    ):
        self.calls.append("safety_output")
        self.contexts.append(context)
        self._raise_if("output")
        return self._view(self.output_action, request_context)


def _chunk(*, population: str = "university_student") -> KnowledgeChunk:
    return KnowledgeChunk(
        schema_version="knowledge.v1",
        chunk_id="CHUNK_edu_001",
        document_id="KB_edu_001",
        text="可以尝试固定一个容易坚持的学习开始时间，并每周回顾安排。",
        location={"page": 1},
        citation={"title": "学习安排", "organization": "合成资料", "locator": "第 1 页"},
        population_scope=[population],
        role_scope=["student"],
        risk_scope=["low"],
        review_status="approved",
        rights_status="verified",
        content_hash="a" * 64,
    )


class FakeRag:
    label = "FAKE_RAG"

    def __init__(
        self, *, chunks: Sequence[KnowledgeChunk] | None = None, fail: bool = False
    ) -> None:
        self.chunks = tuple(chunks if chunks is not None else [_chunk()])
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    async def retrieve(self, **kwargs: Any) -> RetrievalResult:
        self.calls.append(kwargs)
        if self.fail:
            raise TimeoutError("synthetic RAG timeout")
        return RetrievalResult(
            retrieval_id=kwargs["retrieval_id"],
            chunks=self.chunks,
            label=self.label,
            trace={
                "request_id": kwargs["context"].request_id,
                "trace_id": kwargs["context"].trace_id,
            },
        )


class FakeRuntime:
    label = "FAKE_RUNTIME"

    def __init__(self, *, candidate: str | None = None, fail: bool = False) -> None:
        self.candidate = candidate
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    async def generate(self, **kwargs: Any) -> GenerationResult:
        self.calls.append(kwargs)
        if self.fail:
            raise TimeoutError("synthetic runtime timeout")
        text = self.candidate or json.dumps(
            {
                "summary": "可以从一个固定的学习开始时间着手。",
                "observations": [],
                "suggestions": [
                    {
                        "text": "选一个容易坚持的开始时间，并每周回顾安排。",
                        "source_chunk_ids": ["CHUNK_edu_001"],
                    }
                ],
                "disclaimer": "这是一般教育支持信息，不构成测评解释、诊断或治疗建议。",
            },
            ensure_ascii=False,
        )
        return GenerationResult(
            request_id=kwargs["context"].request_id,
            trace_id=kwargs["context"].trace_id,
            generation_id=kwargs["generation_id"],
            conversation_id=kwargs["conversation_id"],
            turn_id=kwargs["turn_id"],
            text=text,
            model_id="MODEL_local_primary",
            logical_model_id="qwen2.5-7b-instruct-school-demo",
            model_version="synthetic-model-version",
            runtime_version="synthetic-runtime-version",
            synthetic_fixture_only=True,
            trace={"attempt_count": 1},
        )


def _service(
    *,
    persistence: FakePersistence | None = None,
    safety: FakeSafety | None = None,
    rag: FakeRag | None = None,
    runtime: FakeRuntime | None = None,
) -> tuple[IndependentConversationService, FakePersistence, FakeSafety, FakeRag, FakeRuntime]:
    store = persistence or FakePersistence()
    safety_client = safety or FakeSafety()
    rag_client = rag or FakeRag()
    runtime_client = runtime or FakeRuntime()
    service = IndependentConversationService(
        persistence=store,  # type: ignore[arg-type]
        safety=safety_client,  # type: ignore[arg-type]
        rag=rag_client,
        llm=runtime_client,
    )
    return service, store, safety_client, rag_client, runtime_client


def _prompt_for_source_metadata(*source_metadata: Mapping[str, Any]) -> str:
    chunks = []
    for index, metadata in enumerate(source_metadata, start=1):
        chunk = _chunk().model_dump(mode="json")
        chunk["chunk_id"] = f"CHUNK_prompt_{index}"
        chunk["document_id"] = f"KB_prompt_{index}"
        chunk.update(metadata)
        chunks.append(chunk)
    bundle = build_retrieval_evidence_bundle(
        RetrievalResult(
            retrieval_id="RETR_prompt_sources",
            chunks=tuple(chunks),  # type: ignore[arg-type]
            label="FAKE_RAG",
        ),
        policy=EligibilityPolicy(
            target_population="university_student",
            target_role="student",
            risk_level=None,
        ),
    )
    return IndependentConversationService._system_prompt(bundle)


async def _submit(service: IndependentConversationService, message: str = "如何安排学习？"):
    return await service.submit_message(
        ACTOR,
        "CONV_test",
        ConversationMessageRequest(text=message),
        idempotency_key="key-test",
        context=CONTEXT,
    )


def test_prompt_scopes_synthetic_demo_labels_by_source_not_curated_flag() -> None:
    prompt = _prompt_for_source_metadata(
        {
            "source_url": "synthetic://StudentMentalHealthAI/M0/demo",
            "human_curated": False,
            "review_semantics": "M0_DEMO_ELIGIBILITY_ONLY_NOT_HUMAN_OR_SPECIALIST_REVIEW",
        },
        {
            "source_url": "https://example.edu/learning-resource",
            "human_curated": False,
        },
    )

    assert "Synthetic Demo（合成演示材料）" in prompt
    assert "未经人工或专业审核" in prompt
    assert "不是真实教育证据" in prompt
    assert "CHUNK_prompt_1" in prompt
    assert "其余资料仍须各自满足现有审核、使用权和适用范围限制" in prompt
    synthetic_listing = (
        prompt.split("Synthetic Demo chunk_id：", maxsplit=1)[1].split(
            "。", maxsplit=1
        )[0]
    )
    assert json.loads(synthetic_listing) == ["CHUNK_prompt_1"]


def test_system_prompt_does_not_call_non_synthetic_human_curated_false_material_synthetic() -> None:
    prompt = _prompt_for_source_metadata(
        {
            "source_url": "https://example.edu/learning-resource",
            "human_curated": False,
        }
    )

    assert "已审核资料" in prompt
    assert "Synthetic Demo" not in prompt


@pytest.mark.asyncio
async def test_create_list_and_detail_use_typed_persistence_projections() -> None:
    service, _, _, _, _ = _service()

    created = await service.create(
        ACTOR,
        idempotency_key="key-create",
        context=CONTEXT,
        payload=ConversationCreateRequest(),
    )
    page = await service.list(ACTOR)
    detail = await service.detail(ACTOR, created.conversation_id, offset=0, limit=10)

    assert created.conversation_id == "CONV_test"
    assert page.items == [] and page.total == 0
    assert detail.conversation.conversation_id == created.conversation_id
    assert detail.messages == [] and detail.turns == []


@pytest.mark.asyncio
async def test_nonstudent_actor_is_rejected_before_persistence_or_dependencies() -> None:
    service, persistence, safety, rag, runtime = _service()
    teacher = Actor(
        user_id="ACCOUNT_teacher",
        username="synthetic_teacher",
        role=BackendRole.TEACHER,
        subject_id=None,
        school_id=1,
        school_ref="SCHOOL_test",
    )

    with pytest.raises(BackendError) as exc:
        await service.submit_message(
            teacher,
            "CONV_test",
            ConversationMessageRequest(text="help"),
            idempotency_key="key-test",
            context=CONTEXT,
        )

    assert exc.value.code == ErrorCode.FORBIDDEN
    assert persistence.reserve_calls == []
    assert safety.calls == [] and rag.calls == [] and runtime.calls == []


@pytest.mark.asyncio
async def test_normal_path_validates_and_persists_only_approved_content_and_citations() -> None:
    history = {
        "turns": [
            {"turn_id": "TURN_prior", "status": "completed", "action": "PROCEED"},
            {"turn_id": "TURN_blocked", "status": "blocked", "action": "BLOCK"},
            {"turn_id": "TURN_failed", "status": "failed", "action": "DEPENDENCY_FAILURE"},
            {"turn_id": "TURN_test", "status": "requested", "action": "REQUESTED"},
        ],
        "messages": [
            {
                "kind": "user_input",
                "payload": {"turn_id": "TURN_prior", "text": "我之前问过学习安排。"},
            },
            {
                "kind": "approved_output",
                "payload": {
                    "turn_id": "TURN_prior",
                    "content": {
                        "summary": "之前已批准的教育支持摘要。",
                        "observations": [],
                        "suggestions": [{"text": "可尝试每周回顾安排。"}],
                        "disclaimer": "这是一般教育支持信息。",
                    },
                },
            },
            {
                "kind": "user_input",
                "payload": {"turn_id": "TURN_blocked", "text": "BLOCKED_PRIVATE_TEXT"},
            },
            {
                "kind": "approved_output",
                "payload": {
                    "turn_id": "TURN_blocked",
                    "content": {"summary": "BLOCKED_PRIVATE_OUTPUT"},
                },
            },
            {
                "kind": "user_input",
                "payload": {"turn_id": "TURN_failed", "text": "FAILED_PRIVATE_TEXT"},
            },
            {
                "kind": "approved_output",
                "payload": {
                    "turn_id": "TURN_failed",
                    "content": {"summary": "FAILED_PRIVATE_OUTPUT"},
                },
            },
            {
                "kind": "user_input",
                "payload": {"turn_id": "TURN_test", "text": "如何安排学习？"},
            },
        ],
    }
    service, persistence, safety, rag, runtime = _service(
        persistence=FakePersistence(history=history)
    )

    result = await _submit(service)

    assert result.status == "completed"
    assert result.action == "PROCEED"
    assert result.content is not None
    assert len(result.citations) == 1
    assert safety.calls == ["safety_input", "safety_retrieval", "safety_output"]
    assert [call["target_population"] for call in rag.calls] == ["university_student"]
    assert runtime.calls[0]["conversation_id"] == "CONV_test"
    assert runtime.calls[0]["turn_id"] == "TURN_test"
    assert runtime.calls[0]["retrieval_id"] == rag.calls[0]["retrieval_id"]
    runtime_prompt = "\n".join(item["content"] for item in runtime.calls[0]["messages"])
    assert "我之前问过学习安排。" in runtime_prompt
    assert "之前已批准的教育支持摘要。" in runtime_prompt
    assert "BLOCKED_PRIVATE_TEXT" not in runtime_prompt
    assert "BLOCKED_PRIVATE_OUTPUT" not in runtime_prompt
    assert "FAILED_PRIVATE_TEXT" not in runtime_prompt
    assert "FAILED_PRIVATE_OUTPUT" not in runtime_prompt
    assert runtime_prompt.count("如何安排学习？") == 1
    assert "不可信历史文本" in runtime_prompt
    assert runtime.calls[0]["chunk_ids"] == ("CHUNK_edu_001",)
    assert "不得推断" in runtime.calls[0]["messages"][0]["content"]
    assert "assessment_signals" not in runtime.calls[0]["messages"][0]["content"]
    assert safety.contexts[0]["actor_role"] == "STUDENT"
    assert safety.contexts[0]["assessment_signals"] == []
    assert all(item["assessment_signals"] == [] for item in safety.contexts)
    assert all(
        item["conversation_metadata"]
        == {
            "source": "independent_education_support",
            "synthetic_fixture": True,
        }
        for item in safety.contexts
    )
    assert all(
        "explicit_crisis_signal" not in item["conversation_metadata"]
        for item in safety.contexts
    )
    assert safety.contexts[1]["retrieval_metadata"]["retrieval_id"] == rag.calls[0]["retrieval_id"]
    assert safety.contexts[2]["generation_metadata"]["retrieval_id"] == rag.calls[0]["retrieval_id"]
    assert persistence.finish_calls[0]["approved_content"].summary.startswith("可以从")
    assert persistence.finish_calls[0]["citations"][0].chunk_id == "CHUNK_edu_001"
    assert "trace" not in result.content


@pytest.mark.asyncio
async def test_replay_returns_reserved_turn_without_repeating_any_dependency() -> None:
    service, persistence, safety, rag, runtime = _service(
        persistence=FakePersistence(replayed=True)
    )

    result = await _submit(service)

    assert result.replayed is True
    assert result.turn_id == "TURN_test"
    assert safety.calls == []
    assert rag.calls == []
    assert runtime.calls == []
    assert persistence.detail_calls == []
    assert persistence.finish_calls == []


def test_history_block_is_bounded_to_twenty_messages_and_six_thousand_json_chars() -> None:
    pairs = [
        (f"prior student {index} " + "x" * 1_000, f"prior answer {index} " + "y" * 1_000)
        for index in range(14)
    ]

    history = IndependentConversationService._bound_history(pairs)

    assert len(history) <= 20
    assert len(json.dumps(history, ensure_ascii=False, separators=(",", ":"))) <= 6_000
    assert "prior student 13" in history[-2]["text"]
    assert "prior answer 13" in history[-1]["text"]


@pytest.mark.asyncio
async def test_no_eligible_evidence_abstains_without_retrieval_safety_or_runtime() -> None:
    service, persistence, safety, rag, runtime = _service(
        rag=FakeRag(chunks=[_chunk(population="k12_student")])
    )

    result = await _submit(service)

    assert result.status == "completed"
    assert result.action == "ABSTAIN"
    assert result.citations == []
    assert result.content is not None
    assert "没有找到适用" in result.content["summary"]
    assert safety.calls == ["safety_input"]
    assert len(rag.calls) == 1
    assert runtime.calls == []
    assert persistence.finish_calls[0].get("citations", ()) == ()


@pytest.mark.asyncio
async def test_duplicate_retrieval_chunk_ids_fail_closed_before_prompt_or_runtime() -> None:
    service, persistence, safety, rag, runtime = _service(rag=FakeRag(chunks=[_chunk(), _chunk()]))

    result = await _submit(service)

    assert result.status == "failed"
    assert result.action == "INVALID_OUTPUT"
    assert safety.calls == ["safety_input"]
    assert len(rag.calls) == 1
    assert runtime.calls == []
    assert persistence.finish_calls[0]["safe_metadata"]["failure_code"] == "DUPLICATE_CHUNK_ID"


@pytest.mark.parametrize("action", ["BLOCK", "REVIEW_REQUIRED", "CRISIS_ROUTE"])
@pytest.mark.asyncio
async def test_input_safety_stops_rag_and_runtime(action: str) -> None:
    service, persistence, safety, rag, runtime = _service(safety=FakeSafety(input_action=action))

    result = await _submit(service)

    assert result.status == "blocked"
    assert safety.calls == ["safety_input"]
    assert rag.calls == []
    assert runtime.calls == []
    finish = persistence.finish_calls[0]
    if action == "CRISIS_ROUTE":
        assert finish["action"] == "CRISIS_ROUTE"
        assert finish["approved_content"]["kind"] == "approved_safety_response"
    else:
        assert finish.get("approved_content") is None


@pytest.mark.asyncio
async def test_retrieval_safety_stops_runtime_and_never_persists_candidate() -> None:
    service, persistence, safety, rag, runtime = _service(
        safety=FakeSafety(retrieval_action="REVIEW_REQUIRED")
    )

    result = await _submit(service)

    assert result.status == "blocked"
    assert runtime.calls == []
    assert len(safety.retrieval_chunks) == 1
    assert safety.retrieval_chunks[0][0]["population_scope"] == ["university_student"]
    assert persistence.finish_calls[0]["approved_content"] is None


@pytest.mark.asyncio
async def test_runtime_timeout_marks_failed_dependency_and_does_not_store_candidate() -> None:
    service, persistence, safety, rag, runtime = _service(runtime=FakeRuntime(fail=True))

    with pytest.raises(BackendError) as exc:
        await _submit(service)

    assert exc.value.code == ErrorCode.DEPENDENCY_UNAVAILABLE
    finish = persistence.finish_calls[0]
    assert finish["status"] == "FAILED"
    assert finish["action"] == "DEPENDENCY_FAILURE"
    assert finish.get("approved_content") is None
    assert finish.get("citations", ()) == ()
    assert len(runtime.calls) == 1


@pytest.mark.parametrize(
    ("candidate", "expected_action"),
    [
        ("not-json", "INVALID_OUTPUT"),
        (
            json.dumps(
                {
                    "summary": "theta结果说明正常。",
                    "observations": [],
                    "suggestions": [
                        {"text": "建议安排学习。", "source_chunk_ids": ["CHUNK_edu_001"]}
                    ],
                    "disclaimer": "这是一般教育支持信息。",
                },
                ensure_ascii=False,
            ),
            "CLAIM_REJECTED",
        ),
    ],
)
@pytest.mark.asyncio
async def test_invalid_or_forbidden_candidate_is_failed_without_persisted_content(
    candidate: str, expected_action: str
) -> None:
    service, persistence, _, _, _ = _service(runtime=FakeRuntime(candidate=candidate))

    result = await _submit(service)

    assert result.status == "failed"
    assert result.action == expected_action
    finish = persistence.finish_calls[0]
    assert finish["status"] == "FAILED"
    assert finish.get("approved_content") is None
    assert finish.get("citations", ()) == ()


@pytest.mark.asyncio
async def test_output_safety_block_does_not_persist_candidate_or_citations() -> None:
    service, persistence, _, _, _ = _service(safety=FakeSafety(output_action="REVIEW_REQUIRED"))

    result = await _submit(service)

    assert result.status == "blocked"
    assert result.action == "REVIEW_REQUIRED"
    assert persistence.finish_calls[0].get("approved_content") is None
    assert persistence.finish_calls[0].get("citations", ()) == ()


@pytest.mark.asyncio
async def test_dependency_failure_at_input_safety_is_recorded_before_error_returns() -> None:
    service, persistence, _, rag, runtime = _service(safety=FakeSafety(error_stage="input"))

    with pytest.raises(BackendError) as exc:
        await _submit(service)

    assert exc.value.code == ErrorCode.DEPENDENCY_UNAVAILABLE
    assert persistence.finish_calls[0]["action"] == "DEPENDENCY_FAILURE"
    assert persistence.finish_calls[0]["safe_metadata"]["stage"] == "input_safety"
    assert rag.calls == []
    assert runtime.calls == []


@pytest.mark.parametrize(
    ("safety", "rag", "runtime", "failed_stage"),
    [
        (FakeSafety(), FakeRag(fail=True), FakeRuntime(), "retrieval"),
        (FakeSafety(error_stage="retrieval"), FakeRag(), FakeRuntime(), "retrieval_safety"),
        (FakeSafety(error_stage="output"), FakeRag(), FakeRuntime(), "output_safety"),
    ],
)
@pytest.mark.asyncio
async def test_external_stage_failures_are_terminal_and_never_store_candidates(
    safety: FakeSafety,
    rag: FakeRag,
    runtime: FakeRuntime,
    failed_stage: str,
) -> None:
    service, persistence, _, _, _ = _service(safety=safety, rag=rag, runtime=runtime)

    with pytest.raises(BackendError) as exc:
        await _submit(service)

    assert exc.value.code == ErrorCode.DEPENDENCY_UNAVAILABLE
    finish = persistence.finish_calls[0]
    assert finish["status"] == "FAILED"
    assert finish["action"] == "DEPENDENCY_FAILURE"
    assert finish["safe_metadata"]["stage"] == failed_stage
    assert finish.get("approved_content") is None
    assert finish.get("citations", ()) == ()


@pytest.mark.asyncio
async def test_valid_json_without_evidence_citation_is_rejected_without_candidate_storage() -> None:
    candidate = json.dumps(
        {
            "summary": "可以试着安排每周回顾。",
            "observations": [],
            "suggestions": [],
            "disclaimer": "这是一般教育支持信息。",
        },
        ensure_ascii=False,
    )
    service, persistence, _, _, _ = _service(runtime=FakeRuntime(candidate=candidate))

    result = await _submit(service)

    assert result.status == "failed"
    assert result.action == "INVALID_OUTPUT"
    assert persistence.finish_calls[0].get("approved_content") is None
    assert persistence.finish_calls[0].get("citations", ()) == ()


def test_request_dtos_reject_unknown_owner_ai_fields_and_coercion() -> None:
    with pytest.raises(ValidationError):
        ConversationMessageRequest.model_validate({"text": "help", "assessment_id": "ASSESS_fake"})
    with pytest.raises(ValidationError):
        ConversationMessageRequest.model_validate({
            "text": "help",
            "conversation_metadata": {"synthetic_fixture": True},
            "explicit_crisis_signal": True,
        })
    with pytest.raises(ValidationError):
        ConversationCreateRequest.model_validate({"owner_id": "SUBJ_other"})
