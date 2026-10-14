from __future__ import annotations

from types import SimpleNamespace

import pytest

from smhai_backend.adapters.school_research_programme_candidates import (
    SchoolResearchProgrammeCandidatePersistenceAdapter,
)
from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.domains.research_programme_generation.schemas import STUDY_REF
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


def _candidate_content_payload(*, origin_fields=False):
    content = {
        "programme_ref": "staff-programme-r1",
        "title": "Source catalogue",
        "body": "Publisher: Source title [CHUNK_SOURCE]",
        "citations": [
            {
                "citation_id": "S1",
                "source_title": "Source title",
                "source_organization": "Publisher",
                "source_url": "https://example.org/source",
                "source_locator": "Section 1",
            }
        ],
    }
    if origin_fields:
        content.update(
            {
                "content_origin": "VERIFIED_SOURCE_METADATA",
                "generation_mode": "MODEL_SOURCE_SELECTION",
            }
        )
    return {
        "candidate_ref": "RPCAND_synthetic_1",
        "programme_ref": "staff-programme-r1",
        "content_revision": 1,
        "content": content,
    }


def _decrypt_row(*, prompt_version, payload_schema_version):
    return SimpleNamespace(
        candidate_ref="RPCAND_synthetic_1",
        programme_ref="staff-programme-r1",
        study_ref=STUDY_REF,
        prompt_version=prompt_version,
        payload_ciphertext=b"ciphertext",
        cipher_format_version="enc.v1",
        key_version="key-v1",
        payload_schema_version=payload_schema_version,
    )


def test_candidate_detail_labels_old_encrypted_passages_as_legacy_model_text():
    adapter = _adapter()
    adapter.protection = SimpleNamespace(
        decrypt_json=lambda _payload: _candidate_content_payload(origin_fields=False)
    )

    result = adapter._decrypt_content(
        _decrypt_row(
            prompt_version="1.1.1",
            payload_schema_version="school_research_programme_candidate.v1",
        )
    )

    assert result["content_origin"] == "LEGACY_MODEL_TEXT"
    assert result["generation_mode"] == "LEGACY_MODEL_AUTHORED_PASSAGES"


def test_candidate_detail_requires_explicit_origin_for_v120_ciphertext():
    adapter = _adapter()
    adapter.protection = SimpleNamespace(
        decrypt_json=lambda _payload: _candidate_content_payload(origin_fields=False)
    )

    with pytest.raises(BackendError) as raised:
        adapter._decrypt_content(
            _decrypt_row(
                prompt_version="1.2.0",
                payload_schema_version="school_research_programme_candidate.v2",
            )
        )

    assert raised.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE


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
