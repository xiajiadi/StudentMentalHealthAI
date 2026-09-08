from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from smhai_backend.core.config import ModuleClientSettings
from smhai_backend.core.request_context import RequestContext
from smhai_backend.domains.support.schemas import GenerationContent
from smhai_backend.integrations.llm import HttpLLMRuntimeClient

EXACT_CHUNK_IDS = [
    "CHUNK_67b56abe21fe9860a26d",
    "CHUNK_8f85f2c0472e21acd2fa",
    "CHUNK_c3718c65fcf4151af391",
    "CHUNK_3d2d02ba1c8fbc506665",
    "CHUNK_bcbe71382652340b2249",
]


class SyntheticBudgetProvider(HttpLLMRuntimeClient):
    """Synthetic provider that models the observed budget-boundary failure."""

    def __init__(self) -> None:
        super().__init__(ModuleClientSettings(mode="http", base_url="http://127.0.0.1:8160"))
        self.payload: dict[str, Any] | None = None

    @staticmethod
    def structured_text(max_output_tokens: int) -> str:
        full = {
            "summary": "Synthetic structured-output compatibility summary.",
            "observations": ["Synthetic evidence is used only for this regression."],
            "suggestions": [
                {
                    "text": "Break the next task into one small action.",
                    "source_chunk_ids": EXACT_CHUNK_IDS,
                }
            ],
            "disclaimer": "Synthetic engineering fixture; not diagnosis or treatment advice.",
        }
        text = json.dumps(full, ensure_ascii=False, separators=(",", ":"))
        return text if max_output_tokens >= 768 else text[:200]

    async def post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        context: RequestContext,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.payload = dict(payload)
        text = self.structured_text(int(payload["config"]["max_output_tokens"]))
        return {
            "data": {
                "text": text,
                "model_id": "MODEL_local_gpu_acceptance",
                "model_version": "synthetic",
                "runtime_version": "synthetic",
            }
        }


@pytest.mark.asyncio
async def test_truncated_structured_json_is_rejected() -> None:
    provider = SyntheticBudgetProvider()
    with pytest.raises(ValidationError):
        GenerationContent.model_validate_json(provider.structured_text(384))
    await provider.close()


@pytest.mark.asyncio
async def test_exact_provenance_budget_returns_valid_structured_object() -> None:
    provider = SyntheticBudgetProvider()
    try:
        candidate = await provider.generate(
            prompt=(
                "Return JSON only, matching the requested generation schema. "
                "Do not diagnose, assign clinical risk, or invent citations. "
                "education_support; target_role=student; message=请给出简短建议。; "
                f"source_chunk_ids={','.join(EXACT_CHUNK_IDS)}"
            ),
            model_id="MODEL_local_gpu_acceptance",
            provider_class="local",
            trace_id="TRACE_STRUCTURED_OUTPUT_COMPAT_TEST",
            request_id="REQ_STRUCTURED_OUTPUT_COMPAT_TEST",
            generation_id="GEN_STRUCTURED_OUTPUT_COMPAT_TEST",
            assessment_id="ASSESS_STRUCTURED_OUTPUT_COMPAT_TEST",
            subject_id="SUBJ_STRUCTURED_OUTPUT_COMPAT_TEST",
            target_role="student",
            retrieval_id="RETR_STRUCTURED_OUTPUT_COMPAT_TEST",
            chunk_ids=tuple(EXACT_CHUNK_IDS),
            metadata={"synthetic_fixture": True},
        )
        assert provider.payload is not None
        assert provider.payload["config"]["max_output_tokens"] == 768
        content = GenerationContent.model_validate_json(candidate.text)
        assert content.summary
        assert content.observations
        assert content.suggestions
        assert content.disclaimer
        assert content.suggestions[0].source_chunk_ids == EXACT_CHUNK_IDS
    finally:
        await provider.close()
