"""Focused tests for the isolated, non-published research CAT adapter."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import pytest
from cat_engine.domain.config import CATConfig
from cat_engine.research import research_session
from cat_engine.research.research_session import (
    NHANES_DPQ_PROFILE_SCHEMA,
    PROFILE_SCHEMA,
    PROMIS_PEDIATRIC_PROFILE_SCHEMA,
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
REAL_NHANES_PROFILE_PATH = Path(
    r"D:\Dev\datasets\psynova-public-research\research-profiles\nhanes-p-dpq-adult-mirt-20261014-v2\profile.json"
)
REAL_NHANES_PROFILE_SHA256 = (
    "8fd1a76718447b5401da3a9c380f1b2fd64bb5a8b22b60e148986a7f74ca7401"
)
REAL_PROMIS_PROFILE_PATH = Path(
    r"D:\Dev\datasets\psynova-public-research\research-profiles\promis-pediatric-anxiety-8-item-subset-20261014-r1\profile.json"
)
REAL_PROMIS_PROFILE_SHA256 = (
    "a2720adf10496f495efe21262de0e1890650847a84aff770aa025e9da825acf3"
)
REAL_PROMIS_MANIFEST_SHA256 = (
    "984d395c29c26c1ce728d97790abf99d583ef47518ee6e058e067c8e8c15f524"
)
NHANES_DPQ_ITEMS = (
    "DPQ010",
    "DPQ020",
    "DPQ030",
    "DPQ040",
    "DPQ050",
    "DPQ060",
    "DPQ070",
    "DPQ080",
    "DPQ090",
)


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


def _load_nhanes_profile() -> ResearchCATProfile:
    if not REAL_NHANES_PROFILE_PATH.is_file():
        pytest.skip(
            "external NHANES_DPQ v2 research profile is not mounted in this environment"
        )
    return ResearchCATProfile.load(
        REAL_NHANES_PROFILE_PATH,
        expected_file_sha256=REAL_NHANES_PROFILE_SHA256,
    )


def _load_promis_profile() -> ResearchCATProfile:
    if not REAL_PROMIS_PROFILE_PATH.is_file():
        pytest.skip(
            "external PROMIS pediatric v3 profile is not mounted in this environment"
        )
    manifest_path = REAL_PROMIS_PROFILE_PATH.with_name("manifest.json")
    return ResearchCATProfile.load(
        REAL_PROMIS_PROFILE_PATH,
        expected_file_sha256=REAL_PROMIS_PROFILE_SHA256,
        manifest_path=manifest_path,
        expected_manifest_sha256=REAL_PROMIS_MANIFEST_SHA256,
    )


def test_profile_preserves_verified_original_bytes_for_encrypted_persistence() -> None:
    from dataclasses import FrozenInstanceError

    raw = json.dumps(_test_profile_document(), indent=2).encode("utf-8") + b"\n"
    profile = ResearchCATProfile.from_bytes(
        raw, expected_file_sha256=hashlib.sha256(raw).hexdigest()
    )
    assert profile.raw_profile_bytes == raw
    assert hashlib.sha256(profile.raw_profile_bytes).hexdigest() == profile.file_sha256
    assert profile.raw_metadata_json.encode("utf-8") != raw
    assert "raw_profile_bytes=" not in repr(profile)
    with pytest.raises(FrozenInstanceError):
        profile.raw_profile_bytes = b"changed"


def test_nhanes_preserves_verified_original_profile_bytes() -> None:
    profile = _load_nhanes_profile()
    assert profile.raw_profile_bytes == REAL_NHANES_PROFILE_PATH.read_bytes()
    assert (
        hashlib.sha256(profile.raw_profile_bytes).hexdigest()
        == REAL_NHANES_PROFILE_SHA256
    )


def _nhanes_profile_document() -> dict:
    if not REAL_NHANES_PROFILE_PATH.is_file():
        pytest.skip(
            "external NHANES_DPQ v2 research profile is not mounted in this environment"
        )
    return json.loads(REAL_NHANES_PROFILE_PATH.read_text(encoding="utf-8"))


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


def test_real_nhanes_v2_profile_runs_full_nine_step_authenticated_lifecycle() -> None:
    if not REAL_NHANES_PROFILE_PATH.is_file():
        pytest.skip(
            "external NHANES_DPQ v2 research profile is not mounted in this environment"
        )

    manifest = json.loads(
        REAL_NHANES_PROFILE_PATH.with_name("manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["profile_sha256"] == REAL_NHANES_PROFILE_SHA256
    profile = _load_nhanes_profile()
    assert profile.raw_metadata_json
    metadata = json.loads(profile.raw_metadata_json)
    assert metadata["schema"] == NHANES_DPQ_PROFILE_SCHEMA
    assert metadata["instrument_family"] == "NHANES_DPQ"
    assert [item.item_id for item in profile.items] == list(NHANES_DPQ_ITEMS)
    assert all(item.qid == item.item_code == item.item_id for item in profile.items)
    assert all(item.key_direction == "direct" for item in profile.items)
    assert profile.source_categories == (0, 1, 2, 3)
    assert profile.category_labels == (
        "Not at all",
        "Several days",
        "More than half the days",
        "Nearly every day",
    )
    assert profile.human_curated is False
    assert profile.research_only is True
    assert profile.psychological_interpretation_allowed is False
    assert metadata["candidate_cat_config"]["min_items"] == 9
    assert metadata["candidate_cat_config"]["max_items"] == 9
    assert (
        metadata["candidate_cat_config"]["status"] == "NOT_APPROVED_RESEARCH_CANDIDATE"
    )
    assert metadata["loader_compatibility"]["status"] == (
        "not_compatible_with_current_research_profile_v1_loader"
    )

    config = _config(min_items=9, max_items=9, version="nhanes-explicit-9-item-v1")
    original_config = config.to_dict()
    signer = _TestAuthenticator()
    session = ResearchCATSession.start(
        profile, config, session_id="real-nhanes-virtual-session-01"
    )
    answered = 0
    while True:
        question = session.next_item()
        if question is None:
            break
        assert question.item_id in NHANES_DPQ_ITEMS
        assert question.profile_id == profile.profile_id
        assert question.profile_sha256 == REAL_NHANES_PROFILE_SHA256
        assert question.dimension == profile.dimension
        assert question.step == answered
        assert tuple(option.raw_value for option in question.response_options) == (
            0,
            1,
            2,
            3,
        )

        pending_snapshot = session.save_state(signer)
        resumed_pending = ResearchCATSession.restore(
            profile, config, pending_snapshot, authenticator=signer
        )
        resumed_question = resumed_pending.next_item()
        assert resumed_question is not None
        assert resumed_question.item_id == question.item_id
        assert resumed_question.step == answered

        # Virtual ordinal responses exercise the interface; no source respondent rows are read.
        raw_category = answered % 4
        progress = session.answer(question.item_id, raw_category)
        assert progress.items_answered == answered + 1
        answered += 1

        answer_snapshot = session.save_state(signer)
        resumed = ResearchCATSession.restore(
            profile, config, answer_snapshot, authenticator=signer
        )
        assert resumed.status == session.status
        assert resumed.items_answered == session.items_answered == answered
        assert resumed.stop_reason == session.stop_reason
        next_original = session.next_item()
        next_resumed = resumed.next_item()
        assert (next_resumed.item_id if next_resumed else None) == (
            next_original.item_id if next_original else None
        )
        assert config.to_dict() == original_config

    assert answered == 9
    completion = asdict(session.completion())
    assert completion["status"] == "COMPLETED"
    assert completion["items_answered"] == 9
    assert completion["profile_sha256"] == REAL_NHANES_PROFILE_SHA256
    assert completion["research_only"] is True
    assert completion["psychological_interpretation_allowed"] is False
    assert not (
        {"theta", "se", "score", "ability", "response_pattern"} & set(completion)
    )


def test_nhanes_v2_candidate_bounds_do_not_override_explicit_caller_config() -> None:
    profile = _load_nhanes_profile()
    config = _config(min_items=1, max_items=1, version="caller-config-v1")
    before = config.to_dict()
    session = ResearchCATSession.start(
        profile, config, session_id="nhanes-config-passthrough-session-01"
    )
    question = session.next_item()
    assert question is not None
    session.answer(question.item_id, 0)
    assert session.status == "COMPLETED"
    assert session.items_answered == 1
    assert session.completion().config_sha256 == research_session._config_sha256(config)
    assert config.to_dict() == before
    assert (
        json.loads(profile.raw_metadata_json)["candidate_cat_config"]["min_items"] == 9
    )


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (lambda d: d.__setitem__("unrecognized", True), "profile_v2_schema_invalid"),
        (
            lambda d: d.__setitem__("instrument_family", "OTHER"),
            "profile_status_invalid",
        ),
        (
            lambda d: d.__setitem__("profile_id", "another-profile"),
            "profile_identity_invalid",
        ),
        (
            lambda d: d.__setitem__("psychological_interpretation_allowed", True),
            "profile_status_invalid",
        ),
        (
            lambda d: d["candidate_cat_config"].__setitem__("min_items", 2),
            "profile_candidate_config_invalid",
        ),
        (
            lambda d: d["response_scale"].__setitem__("values", [0, 1, 2, 4]),
            "profile_categories_invalid",
        ),
        (
            lambda d: d["scoring"].__setitem__("reverse_key_transform", "3 - response"),
            "profile_scoring_invalid",
        ),
        (
            lambda d: d["items"][0].__setitem__("key_direction", "reverse"),
            "profile_item_mapping_invalid",
        ),
        (
            lambda d: d["items"][0]["source_locator"].__setitem__(
                "url", "https://example.invalid/"
            ),
            "profile_item_locator_invalid",
        ),
        (
            lambda d: d["items"][0]["fit_locator"].__setitem__("parameter_key", "fake"),
            "profile_fit_locator_invalid",
        ),
        (
            lambda d: d["items"][0]["fit_locator"].__setitem__("sha256", "a" * 64),
            "profile_fit_locator_invalid",
        ),
        (
            lambda d: d["model"].__setitem__("fit_sha256", "a" * 64),
            "profile_model_provenance_invalid",
        ),
        (
            lambda d: d["model"].__setitem__("log_likelihood", 0.0),
            "profile_model_provenance_invalid",
        ),
        (
            lambda d: d["provenance"].__setitem__("importer_sha256", "a" * 64),
            "profile_provenance_invalid",
        ),
        (
            lambda d: d["rights"]["profile"].__setitem__("operational_release", True),
            "profile_rights_invalid",
        ),
        (
            lambda d: d["items"][0].__setitem__("ipip100_code", "FAKE"),
            "profile_v2_schema_invalid",
        ),
        (
            lambda d: d["not_approved_for"].remove(
                "crisis or suicide-risk determination"
            ),
            "profile_status_invalid",
        ),
    ],
)
def test_nhanes_v2_rejects_schema_mapping_rights_and_claim_promotions(
    mutation, expected_code: str
) -> None:
    document = deepcopy(_nhanes_profile_document())
    mutation(document)
    raw = json.dumps(document, ensure_ascii=False, sort_keys=True).encode("utf-8")
    with pytest.raises(ResearchSessionError) as raised:
        ResearchCATProfile.from_bytes(
            raw, expected_file_sha256=hashlib.sha256(raw).hexdigest()
        )
    assert raised.value.code == expected_code


def test_promis_pediatric_v3_loads_pinned_profile_and_manifest_without_claim_promotion() -> (
    None
):
    profile = _load_promis_profile()
    metadata = json.loads(profile.raw_metadata_json)

    assert metadata["schema"] == PROMIS_PEDIATRIC_PROFILE_SCHEMA
    assert metadata["instrument_family"] == "PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET"
    assert profile.profile_id == "promis-pediatric-anxiety-8-item-subset-20261014-r1"
    assert profile.dimension == (
        "Pediatric anxiety item-response research dimension; no psychological interpretation"
    )
    assert profile.source_categories == (1, 2, 3, 4, 5)
    assert profile.category_labels == (
        "Never",
        "Almost Never",
        "Sometimes",
        "Often",
        "Almost Always",
    )
    assert [item.item_id for item in profile.items] == [
        "Q227BR1",
        "Q2230R1",
        "Q3150BR2",
        "Q5044R1",
        "Q2220R2",
        "Q3459BR1",
        "Q713R1",
        "Q3462R1",
    ]
    assert all(item.key_direction == "positive" for item in profile.items)
    assert all(len(item.thresholds) == 4 for item in profile.items)
    assert profile.raw_profile_bytes == REAL_PROMIS_PROFILE_PATH.read_bytes()
    assert (
        hashlib.sha256(profile.raw_profile_bytes).hexdigest()
        == REAL_PROMIS_PROFILE_SHA256
    )
    assert profile.manifest_sha256 == REAL_PROMIS_MANIFEST_SHA256
    assert profile.human_curated is False
    assert profile.research_only is True
    assert profile.publication_status == "not_approved"
    assert profile.psychological_interpretation_allowed is False
    assert (
        metadata["model"]["parameter_origin"]
        == "published item bank parameters; no refit"
    )
    assert "1.7" not in metadata["model"]["parameter_metric"]
    assert metadata["scoring"]["theta_included"] is False


def _independent_promis_probabilities(
    theta: float, a: float, thresholds: tuple[float, ...]
) -> tuple[float, ...]:
    def logistic(value: float) -> float:
        if value >= 0:
            return 1.0 / (1.0 + math.exp(-value))
        exp_value = math.exp(value)
        return exp_value / (1.0 + exp_value)

    survival = [1.0]
    survival.extend(logistic(a * (theta - threshold)) for threshold in thresholds)
    survival.append(0.0)
    return tuple(survival[index] - survival[index + 1] for index in range(5))


def _independent_promis_eap(
    a: float, thresholds: tuple[float, ...], category: int
) -> tuple[float, float]:
    steps = 10_000
    mass = first = second = 0.0
    for index in range(steps + 1):
        theta = -4.0 + 8.0 * index / steps
        probability = _independent_promis_probabilities(theta, a, thresholds)[category]
        weight = math.exp(-0.5 * theta * theta) * probability
        if index == 0 or index == steps:
            weight *= 0.5
        mass += weight
        first += theta * weight
        second += theta * theta * weight
    mean = first / mass
    return mean, math.sqrt(max(0.0, second / mass - mean * mean))


def test_promis_five_category_probabilities_and_eap_match_independent_reference() -> (
    None
):
    profile = _load_promis_profile()
    for item in profile.items:
        for theta in (-3.0, -1.0, 0.0, 1.0, 3.0):
            expected = _independent_promis_probabilities(theta, item.a, item.thresholds)
            actual = research_session._category_probabilities(theta, item)
            assert len(actual) == 5
            assert sum(actual) == pytest.approx(1.0, abs=1e-12)
            assert actual == pytest.approx(expected, abs=1e-12)
            assert all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in actual)

        engine_item = research_session.adt.TestItem()
        engine_item.id = item.item_id
        engine_item.a = item.a
        engine_item.b = list(item.thresholds)
        for category in range(5):
            expected_mean, expected_se = _independent_promis_eap(
                item.a, item.thresholds, category
            )
            public_eap = research_session.adt.ExpectedAPosteriori(
                [category],
                [engine_item],
                prior=research_session.adt.NormalPrior(0.0, 1.0),
                optimization_interval=(-4.0, 4.0),
                model="GRM",
            )
            actual_mean = float(public_eap.get_estimation())
            actual_se = float(public_eap.get_standard_error(actual_mean))
            assert actual_mean == pytest.approx(expected_mean, abs=1e-3)
            assert actual_se == pytest.approx(expected_se, abs=1e-3)


def test_promis_v3_five_category_mid_session_snapshot_restores_and_returns_l1_only() -> (
    None
):
    profile = _load_promis_profile()
    config = _config(min_items=8, max_items=8, version="promis-v3-research-8-item")
    signer = _TestAuthenticator()
    session = ResearchCATSession.start(
        profile, config, session_id="promis-virtual-five-category-session-01"
    )
    answers = (1, 3, 5)
    for category in answers:
        question = session.next_item()
        assert question is not None
        assert tuple(option.raw_value for option in question.response_options) == (
            1,
            2,
            3,
            4,
            5,
        )
        assert (
            tuple(option.label for option in question.response_options)
            == profile.category_labels
        )
        assert question.stem == next(
            item.stem for item in profile.items if item.item_id == question.item_id
        )
        progress = session.answer(question.item_id, category)
        assert progress.items_answered <= 3
        assert not ({"theta", "se", "score", "ability"} & set(asdict(progress)))

    snapshot = session.save_state(signer)
    resumed = ResearchCATSession.restore(
        profile, config, snapshot, authenticator=signer
    )
    original_next = session.next_item()
    restored_next = resumed.next_item()
    assert original_next is not None and restored_next is not None
    assert restored_next.item_id == original_next.item_id
    assert restored_next.step == original_next.step == 3
    assert resumed.items_answered == session.items_answered == 3
    assert restored_next.profile_sha256 == REAL_PROMIS_PROFILE_SHA256

    while True:
        question = resumed.next_item()
        if question is None:
            break
        resumed.answer(question.item_id, 1 + (resumed.items_answered % 5))
    completion = asdict(resumed.completion())
    assert completion["status"] == "COMPLETED"
    assert completion["items_answered"] == 8
    assert completion["research_only"] is True
    assert completion["psychological_interpretation_allowed"] is False
    assert not (
        {"theta", "se", "score", "ability", "response_pattern"} & set(completion)
    )


def test_promis_v3_requires_independent_manifest_hash_and_rejects_manifest_drift() -> (
    None
):
    profile_bytes = REAL_PROMIS_PROFILE_PATH.read_bytes()
    manifest_bytes = REAL_PROMIS_PROFILE_PATH.with_name("manifest.json").read_bytes()
    with pytest.raises(ResearchSessionError) as missing_manifest:
        ResearchCATProfile.from_bytes(
            profile_bytes, expected_file_sha256=REAL_PROMIS_PROFILE_SHA256
        )
    assert missing_manifest.value.code == "profile_manifest_hash_invalid"

    for expected_hash, supplied in (
        ("0" * 64, manifest_bytes),
        (REAL_PROMIS_MANIFEST_SHA256, manifest_bytes + b" "),
    ):
        with pytest.raises(ResearchSessionError) as raised:
            ResearchCATProfile.from_bytes(
                profile_bytes,
                expected_file_sha256=REAL_PROMIS_PROFILE_SHA256,
                manifest_bytes=supplied,
                expected_manifest_sha256=expected_hash,
            )
        assert raised.value.code == "profile_manifest_hash_invalid"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (
            lambda d: d.__setitem__("publication_status", "approved"),
            "profile_identity_invalid",
        ),
        (lambda d: d.__setitem__("human_curated", True), "profile_identity_invalid"),
        (
            lambda d: d["response_scale"].__setitem__(
                "source_raw_codes", [0, 1, 2, 3, 4]
            ),
            "profile_identity_invalid",
        ),
        (
            lambda d: d["response_scale"].__setitem__(
                "engine_category_indices", [1, 2, 3, 4, 5]
            ),
            "profile_identity_invalid",
        ),
        (
            lambda d: d["items"][0]["parameters"].__setitem__("a", 0.0),
            "profile_identity_invalid",
        ),
        (
            lambda d: d["items"][0]["parameters"].__setitem__(
                "thresholds", [-0.2, 0.7, 0.6, 2.5]
            ),
            "profile_identity_invalid",
        ),
        (
            lambda d: d["items"][0].__setitem__("key_direction", "reverse"),
            "profile_identity_invalid",
        ),
    ],
)
def test_promis_v3_rejects_modified_approval_categories_and_parameters(
    mutation, expected_code: str
) -> None:
    document = json.loads(REAL_PROMIS_PROFILE_PATH.read_text(encoding="utf-8"))
    mutation(document)
    mutated = json.dumps(document, ensure_ascii=False, sort_keys=True).encode("utf-8")
    with pytest.raises(ResearchSessionError) as raised:
        ResearchCATProfile.from_bytes(
            mutated, expected_file_sha256=hashlib.sha256(mutated).hexdigest()
        )
    assert raised.value.code == expected_code


def test_v1_schema_does_not_expand_to_five_categories_for_v3() -> None:
    document = _test_profile_document(categories=(1, 2, 3, 4, 5))
    raw = json.dumps(document, sort_keys=True).encode("utf-8")
    with pytest.raises(ResearchSessionError) as raised:
        ResearchCATProfile.from_bytes(
            raw, expected_file_sha256=hashlib.sha256(raw).hexdigest()
        )
    assert raised.value.code == "profile_categories_invalid"


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
