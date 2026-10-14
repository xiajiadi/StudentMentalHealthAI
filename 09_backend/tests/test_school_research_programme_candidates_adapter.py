from __future__ import annotations

from types import SimpleNamespace

import pytest

from smhai_backend.adapters.school_research_programme_candidates import (
    SchoolResearchProgrammeCandidatePersistenceAdapter,
)
from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.domains.school_research_programme_candidates.schemas import (
    GeneratedProgrammeCandidate,
)

from .test_school_research_feedback_adapter import _policy
from .test_school_research_programme_candidates_service import (
    _MODEL_DIGEST,
    _MODEL_REF,
    _PROMPT_REF,
    _PROMPT_VERSION,
    _generated_candidate_input,
)

_TRUSTED_SOURCE_MANIFEST_SHA256 = "f8af1a33487f175b02400fbfcf5f655cd93b40c7a5a35e0582dc363b11401a45"


def _adapter(*, expected_source_manifest_sha256=None):
    return SchoolResearchProgrammeCandidatePersistenceAdapter(
        None,
        study_use_policy=None,
        study_use_policy_sha256=None,
        enabled=True,
        expected_source_manifest_sha256=expected_source_manifest_sha256,
        expected_processor_policy_sha256="3" * 64,
        expected_model_ref=_MODEL_REF,
        expected_model_digest_sha256=_MODEL_DIGEST,
        expected_prompt_ref=_PROMPT_REF,
        expected_prompt_version=_PROMPT_VERSION,
    )


def test_candidate_detail_fails_closed_when_source_manifest_pin_is_missing():
    adapter = _adapter()

    with pytest.raises(BackendError) as raised:
        adapter._detail(
            SimpleNamespace(source_manifest_sha256=_TRUSTED_SOURCE_MANIFEST_SHA256)
        )

    assert raised.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE


def test_candidate_detail_rejects_source_manifest_mismatch_before_decrypting():
    adapter = _adapter(
        expected_source_manifest_sha256=_TRUSTED_SOURCE_MANIFEST_SHA256
    )

    with pytest.raises(BackendError) as raised:
        adapter._detail(SimpleNamespace(source_manifest_sha256="0" * 64))

    assert raised.value.code is ErrorCode.WORKFLOW_CONFLICT


async def test_candidate_store_requires_a_configured_source_manifest_pin():
    adapter = SchoolResearchProgrammeCandidatePersistenceAdapter(
        None,
        study_use_policy=_policy(),
        study_use_policy_sha256="a" * 64,
        enabled=True,
        expected_processor_policy_sha256="3" * 64,
        expected_model_ref=_MODEL_REF,
        expected_model_digest_sha256=_MODEL_DIGEST,
        expected_prompt_ref=_PROMPT_REF,
        expected_prompt_version=_PROMPT_VERSION,
    )
    generated = GeneratedProgrammeCandidate.model_validate(
        _generated_candidate_input(), strict=True
    )
    adapter.configure_generation(enabled=True, processor_policy_sha256="3" * 64)

    with pytest.raises(BackendError) as raised:
        await adapter.store_generated_candidate(generated)

    assert raised.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE


async def test_candidate_store_rejects_a_different_source_manifest_pin():
    adapter = SchoolResearchProgrammeCandidatePersistenceAdapter(
        None,
        study_use_policy=_policy(),
        study_use_policy_sha256="a" * 64,
        enabled=True,
        expected_source_manifest_sha256=_TRUSTED_SOURCE_MANIFEST_SHA256,
        expected_processor_policy_sha256="3" * 64,
        expected_model_ref=_MODEL_REF,
        expected_model_digest_sha256=_MODEL_DIGEST,
        expected_prompt_ref=_PROMPT_REF,
        expected_prompt_version=_PROMPT_VERSION,
    )
    generated = GeneratedProgrammeCandidate.model_validate(
        _generated_candidate_input(), strict=True
    )
    adapter.configure_generation(enabled=True, processor_policy_sha256="3" * 64)

    with pytest.raises(BackendError) as raised:
        await adapter.store_generated_candidate(generated)

    assert raised.value.code is ErrorCode.WORKFLOW_CONFLICT
