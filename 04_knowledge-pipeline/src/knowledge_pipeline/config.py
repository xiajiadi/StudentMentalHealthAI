"""Versioned configuration for the knowledge pipeline."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ChunkConfig:
    """Engineering baseline, not a retrieval benchmark optimum."""

    min_tokens: int = 16
    target_tokens: int = 96
    max_tokens: int = 160
    overlap_tokens: int = 0
    tokenizer: str = "approximate_unicode_v1"

    def __post_init__(self) -> None:
        if not (0 < self.min_tokens <= self.target_tokens <= self.max_tokens):
            raise ValueError("chunk token limits must satisfy 0 < min <= target <= max")
        if self.overlap_tokens < 0 or self.overlap_tokens >= self.max_tokens:
            raise ValueError("overlap_tokens must be non-negative and less than max_tokens")


@dataclass(frozen=True)
class PipelineConfig:
    """Configuration that participates in deterministic IDs and manifests."""

    pipeline_version: str = "0.1.0"
    contract_release: str = "v0.1.0"
    chunk: ChunkConfig = field(default_factory=ChunkConfig)
    default_language: str = "zh-CN"
    publish_only_approved: bool = True
    allow_test_auto_approve: bool = False

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        return value

    @classmethod
    def from_file(cls, path: Path) -> "PipelineConfig":
        with Path(path).open("r", encoding="utf-8") as handle:
            values = yaml.safe_load(handle) or {}
        if not isinstance(values, dict):
            raise ValueError("pipeline config must be a YAML object")
        chunk_values = values.get("chunk", {})
        if not isinstance(chunk_values, dict):
            raise ValueError("pipeline config chunk must be an object")
        known = {"pipeline_version", "contract_release", "chunk", "default_language", "publish_only_approved", "allow_test_auto_approve"}
        unknown = set(values) - known
        if unknown:
            raise ValueError(f"unknown pipeline config fields: {sorted(unknown)}")
        return cls(
            pipeline_version=str(values.get("pipeline_version", "0.1.0")),
            contract_release=str(values.get("contract_release", "v0.1.0")),
            chunk=ChunkConfig(**chunk_values),
            default_language=str(values.get("default_language", "zh-CN")),
            publish_only_approved=bool(values.get("publish_only_approved", True)),
            allow_test_auto_approve=bool(values.get("allow_test_auto_approve", False)),
        )

    @property
    def config_hash(self) -> str:
        return f"sha256:{_sha256_json(self.as_dict())}"
