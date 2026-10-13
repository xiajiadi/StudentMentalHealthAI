"""Focused tests for the isolated, non-published research CAT adapter."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import asdict
from pathlib import Path

import pytest
from cat_engine.domain.config import CATConfig
from cat_engine.research import research_session
from cat_engine.research.research_session import (
    PROFILE_SCHEMA,
    RESEARCH_PUBLICATION_STATUS,
    ResearchCATProfile,
    ResearchCATSession,
    ResearchSessionError,
    _keyed_score,
)

REAL_PROFILE_PATH = Path(
    r"D:\Dev\datasets\psynova-public-research\research-profiles\ipip100-extraversion-sapa-mirt-20261014-r1\profile.json"
)
REAL_PROFILE_SHA256 = "cf49329d2848f5fc4ba38f29e39144b79e7363e0725a3381d0b0273bab235f10"


class _TestAuthenticator:
    """Test-only signer; production key management belongs to the caller."""

    def __init__(self) -> None:
        self._key = b"test-only-research-snapshot-key"

    def sign(self, payload: bytes) -> str:
        return hmac.new(self._key, payload, hashlib.sha256).hexdigest()

    def verify(self, payload: bytes, signature: str) -> bool:
        return hmac.compare_digest(self.sign(payload), signature)


class _FailingSigner:
    def sign(self, payload: bytes) -> str:
        raise RuntimeError("private signer detail")

    def verify(self, payload: bytes, signature: str) -> bool:
        return False


class _InvalidSignatureSigner:
    def sign(self, payload: bytes) -> str:
        return " "

    def verify(self, payload: bytes, signature: str) -> bool:
        return False


def _test_profile_document(*, categories: tuple[int, ...] = (1, 2, 3, 4, 5, 6)) -> dict:
    """Explicit test-only GRM parameters; never represented as empirical data."""

    item_count = 4
    thresholds = (
        [-1.2, -0.3, 0.4, 1.0, 1.8] if len(categories) == 6 else [-0.8, 0.2, 0.9]
    )
    reverse_transform = "7 - response" if len(categories) == 6 else "3 - response"
    items = []
    for index in range(item_count):
        direction = "reverse" if index % 2 else "positive"
        items.append(
            {
                "item_id": f"TEST_ONLY_ITEM_{index + 1}",
                "qid": f"test_q_{index + 1}",
                "ipip100_code": "TEST_ONLY",
                "item_info_id": f"test_q_{index + 1}",
                "response_column": f"test_q_{index + 1}",
                "stem": f"Test-only statement {index + 1}.",
                "key_direction": direction,
                "response_transform": "identity"
                if direction == "positive"
                else reverse_transform,
                "a": 0.9 + index * 0.1,
                "thresholds": [value + index * 0.03 for value in thresholds],
                "observed_n": 0,
                "source_locator": {
                    "url": "https://example.invalid/test-only",
                    "section": "synthetic unit-test fixture",
                    "key_block": f"{direction}_keyed",
                    "position_in_block": index + 1,
                    "crosswalk_file": "test-only-crosswalk.tsv",
                    "crosswalk_row": index + 1,
                    "item_info_file": "test-only-iteminfo.tab",
                },
                "fit_locator": {
                    "file": "test-only-fit.json",
                    "sha256": "a" * 64,
                    "parameter_key": f"test_q_{index + 1}",
                    "parameter_metric": "TEST ONLY; not an empirical calibration",
                },
            }
        )
    reverse_key = reverse_transform if len(categories) == 6 else "3 - response"
    scoring = {
        "parameter_orientation": "TEST ONLY keyed ordinal categories",
        "positive_key_transform": "identity",
        "reverse_key_transform": reverse_key,
        "transform_before_category_index_conversion": True,
        "no_person_scores_or_norms_included": True,
    }
    return {
        "schema": PROFILE_SCHEMA,
        "profile_id": "test-only-research-candidate",
        "profile_type": "CAT_RESEARCH_PROFILE_CANDIDATE",
        "instrument_id": "TEST_ONLY_RESEARCH_INSTRUMENT",
        "dimension": "TEST ONLY",
        "research_only": True,
        "publication_status": RESEARCH_PUBLICATION_STATUS,
        "psychological_interpretation_allowed": False,
        "response_scale": {
            "values": list(categories),
            "category_labels": None,
            "category_labels_status": "test_only_labels_absent",
        },
        "scoring": scoring,
        "model": {
            "package": "mirt",
            "version": "test-only",
            "itemtype": "graded",
            "factors": 1,
            "method": "TEST ONLY",
            "latent_distribution": "Gaussian N(0,1)",
            "converged": True,
            "fit_sha256": "a" * 64,
            "calibration_sha256": "b" * 64,
        },
        "source": {"population": "Synthetic test fixture only; no observations."},
        "rights": {
            "items": {
                "status": "test_only",
                "source_url": "https://example.invalid/test-only",
            },
            "dataset": {"license": "test-only; no data"},
            "profile": {
                "status": "research_only_candidate",
                "operational_release": False,
            },
        },
        "provenance": {"created_at_utc": "test-only", "source_files": {}},
        "items": items,
        "not_approved_for": ["all operational or interpretive uses"],
    }


def _load_test_profile(
    *, categories: tuple[int, ...] = (1, 2, 3, 4, 5, 6)
) -> ResearchCATProfile:
    raw = json.dumps(
        _test_profile_document(categories=categories), sort_keys=True
    ).encode("utf-8")
    return ResearchCATProfile.from_bytes(
        raw, expected_file_sha256=hashlib.sha256(raw).hexdigest()
    )


def _config(
    *, min_items: int = 1, max_items: int = 2, version: str = "test-v1"
) -> CATConfig:
    return CATConfig.from_dict(
        {
            "config_version": version,
            "model": "GRM",
            "estimator": "EAP",
            "selection_method": "MFI",
            "min_items": min_items,
            "max_items": max_items,
            "se_threshold": None,
            "initial_theta": 0.0,
            "prior_mean": 0.0,
            "prior_sd": 1.0,
            "optimization_interval": [-4.0, 4.0],
            "seed": 17,
            "exposure_control": "none",
            "content_balancing": "none",
        }
    )


def test_public_profile_hash_and_source_fields_are_bound() -> None:
    if not REAL_PROFILE_PATH.is_file():
        pytest.skip(
            "external SAPA/IPIP candidate profile is not mounted in this environment"
        )

    manifest_path = REAL_PROFILE_PATH.with_name("manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["profile_sha256"] == REAL_PROFILE_SHA256
    profile = ResearchCATProfile.load(
        REAL_PROFILE_PATH, expected_file_sha256=REAL_PROFILE_SHA256
    )

    assert profile.profile_id == "ipip100-extraversion-sapa-mirt1.47-20261014-r1"
    assert profile.dimension == "Extraversion"
    assert len(profile.items) == 20
    assert sum(item.key_direction == "positive" for item in profile.items) == 10
    assert sum(item.key_direction == "reverse" for item in profile.items) == 10
    assert all(item.stem for item in profile.items)
    assert profile.category_labels is None
    assert profile.human_curated is False
    assert profile.publication_status == RESEARCH_PUBLICATION_STATUS

    config = _config(min_items=1, max_items=2)
    signer = _TestAuthenticator()
    session = ResearchCATSession.start(
        profile, config, session_id="real-profile-virtual-session-01"
    )
    first = session.next_item()
    assert first is not None
    # These are explicitly virtual test answers, not observed SAPA responses.
    session.answer(first.item_id, 4)
    pending = session.next_item()
    assert pending is not None
    snapshot = session.save_state(signer)

    for field, value in (("payload_sha256", "é" * 64), ("signature", "é")):
        malformed = dict(snapshot)
        malformed[field] = value
        with pytest.raises(ResearchSessionError) as raised:
            ResearchCATSession.restore(profile, config, malformed, authenticator=signer)
        assert raised.value.code == "snapshot_schema_invalid"
    restored = ResearchCATSession.restore(
        profile, config, snapshot, authenticator=signer
    )
    resumed = restored.next_item()
    assert resumed is not None
    assert resumed.item_id == pending.item_id
    restored.answer(resumed.item_id, 2)
    completion = asdict(restored.completion())
    assert completion["profile_sha256"] == REAL_PROFILE_SHA256
    assert completion["research_only"] is True
    assert completion["psychological_interpretation_allowed"] is False
    assert not ({"theta", "se", "score", "ability"} & set(completion))


def test_profile_hash_mismatch_and_publication_promotion_fail_closed() -> None:
    document = _test_profile_document()
    raw = json.dumps(document, sort_keys=True).encode("utf-8")
    with pytest.raises(ResearchSessionError, match="expected SHA-256"):
        ResearchCATProfile.from_bytes(raw, expected_file_sha256="0" * 64)

    document["publication_status"] = "published"
    raw = json.dumps(document, sort_keys=True).encode("utf-8")
    with pytest.raises(ResearchSessionError) as raised:
        ResearchCATProfile.from_bytes(
            raw, expected_file_sha256=hashlib.sha256(raw).hexdigest()
        )
    assert raised.value.code == "profile_status_invalid"

    with pytest.raises(ResearchSessionError) as raised:
        ResearchCATProfile.from_bytes(raw, expected_file_sha256=123)  # type: ignore[arg-type]
    assert raised.value.code == "profile_hash_required"


def test_profile_json_rejects_duplicate_keys_nonfinite_values_and_boolean_factor() -> (
    None
):
    duplicate = b'{"schema":"psynova.research-profile.v1","schema":"other"}'
    with pytest.raises(ResearchSessionError) as raised:
        ResearchCATProfile.from_bytes(
            duplicate, expected_file_sha256=hashlib.sha256(duplicate).hexdigest()
        )
    assert raised.value.code == "profile_json_duplicate_key"

    document = _test_profile_document()
    document["model"]["factors"] = float("nan")
    raw = json.dumps(document, sort_keys=True).encode("utf-8")
    with pytest.raises(ResearchSessionError) as raised:
        ResearchCATProfile.from_bytes(
            raw, expected_file_sha256=hashlib.sha256(raw).hexdigest()
        )
    assert raised.value.code == "profile_json_nonfinite_number"

    document = _test_profile_document()
    document["model"]["factors"] = True
    raw = json.dumps(document, sort_keys=True).encode("utf-8")
    with pytest.raises(ResearchSessionError) as raised:
        ResearchCATProfile.from_bytes(
            raw, expected_file_sha256=hashlib.sha256(raw).hexdigest()
        )
    assert raised.value.code == "profile_model_unsupported"


def test_profile_item_key_and_category_contract_fail_closed() -> None:
    document = _test_profile_document()
    document["items"][0]["response_transform"] = "7 - response"
    raw = json.dumps(document, sort_keys=True).encode("utf-8")
    with pytest.raises(ResearchSessionError) as raised:
        ResearchCATProfile.from_bytes(
            raw, expected_file_sha256=hashlib.sha256(raw).hexdigest()
        )
    assert raised.value.code == "profile_key_transform_invalid"

    document = _test_profile_document()
    document["response_scale"]["values"] = [1, 2, 3, 4, 5]
    raw = json.dumps(document, sort_keys=True).encode("utf-8")
    with pytest.raises(ResearchSessionError) as raised:
        ResearchCATProfile.from_bytes(
            raw, expected_file_sha256=hashlib.sha256(raw).hexdigest()
        )
    assert raised.value.code == "profile_categories_invalid"


def test_raw_category_key_mapping_preserves_source_scale_and_reverse_direction() -> (
    None
):
    assert [
        _keyed_score(raw, "positive", (1, 2, 3, 4, 5, 6)) for raw in range(1, 7)
    ] == list(range(6))
    assert [
        _keyed_score(raw, "reverse", (1, 2, 3, 4, 5, 6)) for raw in range(1, 7)
    ] == list(reversed(range(6)))
    assert [_keyed_score(raw, "positive", (0, 1, 2, 3)) for raw in range(4)] == list(
        range(4)
    )
    assert [_keyed_score(raw, "reverse", (0, 1, 2, 3)) for raw in range(4)] == list(
        reversed(range(4))
    )
    with pytest.raises(ResearchSessionError):
        _keyed_score(True, "positive", (1, 2, 3, 4, 5, 6))


def test_session_rejects_wrong_item_duplicate_and_non_ordinal_answer() -> None:
    profile = _load_test_profile()
    session = ResearchCATSession.start(profile, _config(), session_id="unit-session-01")

    with pytest.raises(ResearchSessionError) as raised:
        session.answer("TEST_ONLY_ITEM_1", 3)
    assert raised.value.code == "no_pending_item"

    question = session.next_item()
    assert question is not None
    assert all(option.label is None for option in question.response_options)
    with pytest.raises(ResearchSessionError) as raised:
        session.answer("wrong-item", 3)
    assert raised.value.code == "wrong_pending_item"
    with pytest.raises(ResearchSessionError) as raised:
        session.answer(question.item_id, True)
    assert raised.value.code == "response_category_invalid"

    session.answer(question.item_id, 3)
    with pytest.raises(ResearchSessionError) as raised:
        session.answer(question.item_id, 3)
    assert raised.value.code in {"session_not_active", "duplicate_response"}


def test_session_rejects_unsupported_config_and_item_count_cap() -> None:
    profile = _load_test_profile()
    with pytest.raises(ResearchSessionError) as raised:
        ResearchCATSession.start(
            profile, _config(max_items=5), session_id="too-many-items-01"
        )
    assert raised.value.code == "config_unsupported"

    unsupported = _config().to_dict()
    unsupported["estimator"] = "BM"
    with pytest.raises(ResearchSessionError) as raised:
        ResearchCATSession.start(
            profile,
            CATConfig.from_dict(unsupported),
            session_id="unsupported-config-01",
        )
    assert raised.value.code == "config_unsupported"


def test_snapshot_restore_is_authenticated_bound_and_resumes_same_selection() -> None:
    profile = _load_test_profile()
    config = _config(min_items=1, max_items=3)
    signer = _TestAuthenticator()
    session = ResearchCATSession.start(
        profile, config, session_id="snapshot-session-01"
    )
    first = session.next_item()
    assert first is not None
    session.answer(first.item_id, 4)
    pending = session.next_item()
    assert pending is not None
    snapshot = session.save_state(signer)

    restored = ResearchCATSession.restore(
        profile, config, snapshot, authenticator=signer
    )
    resumed = restored.next_item()
    assert resumed is not None
    assert resumed.item_id == pending.item_id
    assert restored.items_answered == 1

    with pytest.raises(ResearchSessionError) as raised:
        ResearchCATSession.restore(
            profile,
            _config(min_items=1, max_items=3, version="changed"),
            snapshot,
            authenticator=signer,
        )
    assert raised.value.code == "snapshot_config_mismatch"

    altered = dict(snapshot)
    altered_payload = dict(snapshot["payload"])
    altered_payload["step"] = 0
    altered["payload"] = altered_payload
    with pytest.raises(ResearchSessionError) as raised:
        ResearchCATSession.restore(profile, config, altered, authenticator=signer)
    assert raised.value.code == "snapshot_digest_mismatch"

    altered["payload_sha256"] = hashlib.sha256(
        json.dumps(
            altered_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(ResearchSessionError) as raised:
        ResearchCATSession.restore(profile, config, altered, authenticator=signer)
    assert raised.value.code == "snapshot_authentication_failed"


def test_save_state_wraps_signer_errors_and_rejects_invalid_signature_text() -> None:
    session = ResearchCATSession.start(
        _load_test_profile(), _config(), session_id="signer-session-01"
    )
    for signer in (_FailingSigner(), _InvalidSignatureSigner()):
        with pytest.raises(ResearchSessionError) as raised:
            session.save_state(signer)
        assert raised.value.code == "snapshot_signing_failed"
        assert "private signer detail" not in str(raised.value)
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None


def test_answer_item_pool_delete_failure_rolls_back_without_losing_pending_item(
    monkeypatch,
) -> None:
    session = ResearchCATSession.start(
        _load_test_profile(), _config(), session_id="delete-fault-session-01"
    )
    question = session.next_item()
    assert question is not None
    original_delete = session._engine.item_pool.delete_item
    should_fail = True

    def fail_once(item):
        nonlocal should_fail
        if should_fail:
            should_fail = False
            raise RuntimeError("injected delete failure")
        return original_delete(item)

    monkeypatch.setattr(session._engine.item_pool, "delete_item", fail_once)
    with pytest.raises(ResearchSessionError) as raised:
        session.answer(question.item_id, 3)
    assert raised.value.code == "response_update_failed"
    assert session.status == "ACTIVE"
    assert session.items_answered == 0
    assert session.pending_item_id == question.item_id

    session.answer(question.item_id, 3)
    assert session.items_answered == 1


def test_rollback_failure_marks_session_failed_and_preserves_both_causes(
    monkeypatch,
) -> None:
    session = ResearchCATSession.start(
        _load_test_profile(), _config(), session_id="rollback-fault-session-01"
    )
    question = session.next_item()
    assert question is not None

    def fail_delete(item):
        raise RuntimeError("injected original update failure")

    def fail_rebuild(*args, **kwargs):
        raise OSError("injected recovery failure")

    monkeypatch.setattr(session._engine.item_pool, "delete_item", fail_delete)
    monkeypatch.setattr(research_session, "_make_engine", fail_rebuild)
    with pytest.raises(ResearchSessionError) as raised:
        session.answer(question.item_id, 3)

    assert raised.value.code == "session_recovery_failed"
    cause = raised.value.__cause__
    assert isinstance(cause, research_session._CATRecoveryFailure)
    assert str(cause.update_error) == "injected original update failure"
    assert str(cause.recovery_error) == "injected recovery failure"
    assert session.status == "FAILED"
    assert session.stop_reason == "state_recovery_failed"
    assert session.items_answered == 0
    assert session.next_item() is None
    with pytest.raises(ResearchSessionError) as raised:
        session.save_state(_TestAuthenticator())
    assert raised.value.code == "snapshot_unavailable"


def test_completion_returns_metadata_without_theta_or_score() -> None:
    profile = _load_test_profile()
    session = ResearchCATSession.start(
        profile, _config(min_items=1, max_items=1), session_id="completion-session-01"
    )
    question = session.next_item()
    assert question is not None
    session.answer(question.item_id, 4)
    completion = asdict(session.completion())

    assert completion["status"] == "COMPLETED"
    assert completion["items_answered"] == 1
    assert completion["research_only"] is True
    assert completion["psychological_interpretation_allowed"] is False
    assert not (
        {"theta", "se", "score", "ability", "response_pattern"} & set(completion)
    )


def test_four_category_test_fixture_uses_direct_codes_without_clinical_claim() -> None:
    profile = _load_test_profile(categories=(0, 1, 2, 3))
    session = ResearchCATSession.start(
        profile, _config(max_items=1), session_id="four-category-test-01"
    )
    question = session.next_item()
    assert question is not None
    assert tuple(option.raw_value for option in question.response_options) == (
        0,
        1,
        2,
        3,
    )
    assert question.dimension == "TEST ONLY"
