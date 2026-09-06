from __future__ import annotations

from pathlib import Path

import pytest

from llm_runtime.domain.models import GenerationConfig, GenerationRequest, HardwareInfo


@pytest.fixture
def hardware() -> HardwareInfo:
    return HardwareInfo(
        os="test",
        cpu="synthetic CPU",
        threads=4,
        ram_bytes=8 * 1024**3,
        gpu_present=False,
    )


@pytest.fixture
def request_factory():
    def factory(**overrides):
        values = {
            "request_id": "REQ_test_001",
            "trace_id": "TRACE_test_001",
            "generation_id": "GEN_test_001",
            "assessment_id": "ASSESS_test_001",
            "subject_id": "SUBJ_test_001",
            "target_role": "teacher",
            "purpose": "education_support",
            "language": "zh-CN",
            "safety_mode": "standard",
            "retrieval_id": "RETR_test_001",
            "chunk_ids": ("CHUNK_test_001",),
            "prompt_id": "PROMPT_test_v1",
            "prompt_version": "0.1.0",
            "contract_model_id": "MODEL_local_primary",
            "logical_model_id": "primary",
            "prompt": "synthetic engineering prompt",
            "config": GenerationConfig(max_output_tokens=32, timeout_seconds=5),
        }
        values.update(overrides)
        return GenerationRequest(**values)

    return factory


@pytest.fixture
def module_root() -> Path:
    return Path(__file__).resolve().parents[1]

