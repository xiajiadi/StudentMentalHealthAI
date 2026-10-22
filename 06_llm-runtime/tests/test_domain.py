from __future__ import annotations

import pytest

from llm_runtime.domain.models import (
    Capabilities,
    GenerationConfig,
    ModelStatus,
)
from llm_runtime.domain.registry import ModelRegistry


def test_registry_loads_proposal_and_engineering_models(module_root):
    registry = ModelRegistry.from_file(module_root / "config" / "models.v1.json")

    cpu = registry.resolve("qwen2.5-0.5b-engineering")
    proposal = registry.resolve("MODEL_local_primary")

    assert cpu.provider_model_id == "qwen2.5:0.5b"
    assert cpu.status is ModelStatus.READY
    assert proposal.logical_model_id == "qwen2.5-7b-instruct"
    assert proposal.validation_status == "DEFERRED_GPU_VALIDATION"
    assert proposal.quantization == "Q4_K_M"
    assert registry.resolve("qwen2.5:0.5b") is cpu


def test_remote_registry_requires_explicit_opt_in_and_has_no_fallback(module_root):
    path = module_root / "config" / "models.deepseek.v1.json"
    with pytest.raises(ValueError, match="cloud model entries"):
        ModelRegistry.from_file(path)

    registry = ModelRegistry.from_file(path, allow_remote=True)

    assert registry.cloud_fallback is False
    assert len(registry.all()) == 1
    model = registry.resolve("deepseek-flash-education-support")
    assert model.local_only is False
    assert model.fallback_model_id is None
    assert model.fallback_eligible is False
    assert registry.fallback_chain(model.logical_model_id) == ()


def test_model_entry_round_trip_preserves_provenance(module_root):
    registry = ModelRegistry.from_file(module_root / "config" / "models.v1.json")
    value = registry.resolve("qwen2.5-0.5b-engineering").to_dict()
    restored = registry.resolve(value["logical_model_id"]).from_dict(value)

    assert restored.to_dict() == value


def test_capabilities_are_explicit():
    capabilities = Capabilities.from_dict({"stream": True, "json_schema": True})
    assert capabilities.stream is True
    assert capabilities.chat is False
    assert capabilities.to_dict()["structured_output"] is False


def test_generation_config_maps_provider_parameters():
    config = GenerationConfig(
        max_output_tokens=42,
        temperature=0.1,
        top_p=0.8,
        top_k=20,
        context_length=2048,
        seed=7,
        stop=("END",),
    )
    assert config.to_ollama_options() == {
        "num_predict": 42,
        "temperature": 0.1,
        "top_p": 0.8,
        "top_k": 20,
        "num_ctx": 2048,
        "seed": 7,
        "stop": ["END"],
    }
    assert config.max_tokens == 42
