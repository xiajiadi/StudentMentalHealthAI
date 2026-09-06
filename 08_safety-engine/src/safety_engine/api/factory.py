"""Default local dependency wiring for the independent safety service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from safety_engine.adapters.nemo import NemoIORailsAdapter
from safety_engine.adapters.presidio import PresidioPrivacyAdapter
from safety_engine.adapters.qwen_guard import Qwen3GuardProvider
from safety_engine.crisis import CrisisTemplateRepository
from safety_engine.policy import OPAProcessManager, PolicyClient
from safety_engine.review import (
    HumanReviewService,
    InMemoryReviewRepository,
    SQLiteReviewRepository,
)
from safety_engine.service import SafetyEngineConfig, SafetyService


@dataclass(slots=True)
class RuntimeBundle:
    service: SafetyService
    opa_manager: OPAProcessManager | None = None


def module_root() -> Path:
    return Path(__file__).resolve().parents[3]


def build_default_bundle(*, root: Path | None = None) -> RuntimeBundle:
    root = root or module_root()
    policies = root / "policies"
    runtime = root / "runtime"
    opa_url = os.environ.get("SMHAI_OPA_URL", "http://127.0.0.1:8181")
    policy = PolicyClient(base_url=opa_url, policy_dir=policies)
    opa_manager = None
    binary_value = os.environ.get("SMHAI_OPA_BINARY", r"D:\Dev\tools\opa\v1.20.2\opa.exe")
    if os.environ.get("SMHAI_MANAGE_OPA", "0") == "1":
        opa_manager = OPAProcessManager(
            binary=binary_value,
            policy_dir=policies,
            runtime_dir=runtime,
            port=_port_from_url(opa_url),
        )

    review_db = os.environ.get("SMHAI_REVIEW_DB")
    repository = SQLiteReviewRepository(review_db) if review_db else InMemoryReviewRepository()
    qwen_cache = os.environ.get("SMHAI_HF_HOME", os.environ.get("HF_HOME"))
    service = SafetyService(
        privacy=PresidioPrivacyAdapter(),
        nemo=NemoIORailsAdapter(root / "config" / "nemo"),
        qwen=Qwen3GuardProvider(cache_dir=qwen_cache),
        policy=policy,
        review=HumanReviewService(repository),
        crisis_templates=CrisisTemplateRepository(root / "templates" / "crisis"),
        config=SafetyEngineConfig(policy_revision=policy.policy_revision),
    )
    return RuntimeBundle(service=service, opa_manager=opa_manager)


def _port_from_url(url: str) -> int:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return parsed.port or 8181
