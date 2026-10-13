"""Isolated, hash-bound CAT sessions for explicitly supplied research profiles.

This adapter never constructs the online ItemBank or Session and never returns
an ability estimate. A caller owns persistence, encryption, and snapshot
authentication; snapshots are restored only with a trusted authenticator.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.metadata
import inspect
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Protocol

import adaptivetesting as adt

from cat_engine.domain.config import CATConfig

PROFILE_SCHEMA = "psynova.research-profile.v1"
SNAPSHOT_SCHEMA = "psynova.research-cat-snapshot.v1"
NHANES_DPQ_PROFILE_SCHEMA = "psynova.research-profile.v2"
PROMIS_PEDIATRIC_PROFILE_SCHEMA = "psynova.research-profile.v3"
RESEARCH_PUBLICATION_STATUS = "not_approved_for_publication_or_operational_use"
PROFILE_STATUS = "CAT_RESEARCH_PROFILE_CANDIDATE"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SAFE_SIGNATURE = re.compile(r"^[!-~]{1,4096}$")
_ALLOWED_CATEGORY_SCALES = ((1, 2, 3, 4, 5, 6), (0, 1, 2, 3))
_NHANES_DPQ_ITEMS = (
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
_NHANES_DPQ_PROFILE_ID = "nhanes-p-dpq-adult-mirt1.47-20261014-v2"
_NHANES_DPQ_SOURCE_POPULATION = (
    "NHANES 2017-March 2020 pre-pandemic public-use adults; codebook target "
    "18-150, but ages are absent from this response-only fit; not an adolescent, "
    "high-school, or school cohort"
)
_NHANES_DPQ_SOURCE_URL = (
    "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/P_DPQ.htm"
)
_NHANES_DPQ_DATA_URL = (
    "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/P_DPQ.xpt"
)
_NHANES_DPQ_SOURCE_SHA256 = (
    "1a050397dc420e8eb685a43a5a7b481bb3ff61c38e3b5f4d6fb00988a15a2091"
)
_NHANES_DPQ_CODEBOOK_SHA256 = (
    "579e0bcef4f8c2efc815f538b590cdbbf86f3d201309d8d8347d7b3dd299684d"
)
_NHANES_DPQ_FIT_SHA256 = (
    "becedd3437d18a1bdfbb2cf7e4af6f8fef84fd37ca740c68c0bd04b4eb1ae9f6"
)
_NHANES_DPQ_FIT_SCRIPT_SHA256 = (
    "2145704a0ea0c4ab80840122936488913e79555f346b4f9836c2c1e241834a96"
)
_NHANES_DPQ_IMPORTER_SHA256 = (
    "901d09e23f95c58ebd5f3d5cb2676822df25f1a2c6b89fe4634c592fa4ea99e2"
)
_NHANES_DPQ_SPLIT_MANIFEST_SHA256 = (
    "17f73b25173206e28e7342448eb9a106a539d3d65886e513483bc8b94b8e361f"
)
_NHANES_DPQ_CALIBRATION_SHA256 = (
    "4d7536cc669084b7ff815e47e5da556d3dc69e58254630e3c20b3d4874396c95"
)
_NHANES_DPQ_EVALUATION_SHA256 = (
    "0a2e2f825cc450f9f53ce403e30c5979fb57f2e4e239b6dedbb2afaa79ba9669"
)
_NHANES_DPQ_FIT_FILE = (
    "derived/nhanes-dpq-20261014-v1/mirt-nhanes-dpq-20261014-r1/fit-summary.json"
)
_NHANES_DPQ_RIGHTS_STATUS = (
    "research_only_candidate_rights_and_specialist_review_pending"
)
_PROMIS_PEDIATRIC_PROFILE_ID = "promis-pediatric-anxiety-8-item-subset-20261014-r1"
_PROMIS_PEDIATRIC_PROFILE_SHA256 = (
    "a2720adf10496f495efe21262de0e1890650847a84aff770aa025e9da825acf3"
)
_PROMIS_PEDIATRIC_MANIFEST_SHA256 = (
    "984d395c29c26c1ce728d97790abf99d583ef47518ee6e058e067c8e8c15f524"
)
_PROMIS_PEDIATRIC_ITEMS = (
    (
        "Q227BR1",
        "In the past 7 days...I felt scared.",
        1.89,
        (-0.25, 0.59, 1.72, 2.52),
        "I felt scared.",
    ),
    (
        "Q2230R1",
        "In the past 7 days...I worried about what could happen to me.",
        1.84,
        (-0.24, 0.48, 1.54, 2.21),
        "I worried about what could happen to me.",
    ),
    (
        "Q3150BR2",
        "In the past 7 days...I worried when I went to bed at night.",
        1.83,
        (0.25, 0.91, 1.83, 2.57),
        "I worried when I went to bed at night.",
    ),
    (
        "Q5044R1",
        "In the past 7 days...I felt worried.",
        1.81,
        (-0.78, 0.25, 1.59, 2.65),
        "I felt worried.",
    ),
    (
        "Q2220R2",
        "In the past 7 days...I felt like something awful might happen.",
        1.71,
        (-0.43, 0.51, 1.75, 2.65),
        "I felt like something awful might happen.",
    ),
    (
        "Q3459BR1",
        "In the past 7 days...I worried when I was at home",
        1.64,
        (0.40, 1.22, 2.61, 3.30),
        "I worried when I was at home.",
    ),
    (
        "Q713R1",
        "In the past 7 days...I felt nervous.",
        1.51,
        (-0.85, 0.18, 1.86, 2.85),
        "I felt nervous.",
    ),
    (
        "Q3462R1",
        "In the past 7 days...I got scared really easy.",
        1.49,
        (0.29, 1.16, 2.07, 2.74),
        "I got scared really easy.",
    ),
)
_PROMIS_PEDIATRIC_LABELS = (
    "Never",
    "Almost Never",
    "Sometimes",
    "Often",
    "Almost Always",
)
_PROMIS_PEDIATRIC_CODEBOOK_SHA256 = (
    "00344836cabd71ca2ab247dedd04b5a2b759b574874dd3296db06699d132f786"
)
_PROMIS_PEDIATRIC_CROSSWALK_SHA256 = (
    "2176b6cbf7498d8ef912f2902a22c31cb7b229ac82d988d54567cfe615c9066c"
)
_PROMIS_PEDIATRIC_RESPONSE_SHA256 = (
    "c833b0614e74d40aca54b64fcbb5d8983a83638d66d9e7da642147fe9603834a"
)
_PROMIS_PEDIATRIC_NUMERIC_SHA256 = (
    "b00e87fc4e0335a941d92b09195943deec92e21a53f3101576941e2dab54f6fc"
)
_PROMIS_PEDIATRIC_COMPLETE800_SHA256 = (
    "7c723fbdb2590a24cc3fa33adb70c8affb323e3688ce3f0477620bd6507d7f32"
)
_PROMIS_PEDIATRIC_ITEM_MAP_SHA256 = (
    "e395bcd95374dcfba2271491cd1f16215c25179e59a9ef1b26f91225a54c59e9"
)
_PROMIS_PEDIATRIC_BUILD_SHA256 = (
    "b6f35c59dcecb11181dfd6ec510cdabfecdb282da9ee5fde5c4abb9dbac26b7b"
)
_RECOVERABLE_ENGINE_ERRORS = (
    ArithmeticError,
    AttributeError,
    ImportError,
    LookupError,
    MemoryError,
    OSError,
    RuntimeError,
    StopIteration,
    TypeError,
    ValueError,
)


class ResearchSessionError(ValueError):
    """Fail-closed profile, configuration, answer, or snapshot error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _CATRecoveryFailure(RuntimeError):
    """Keep the original update and rollback exceptions inspectable together."""

    def __init__(self, update_error: Exception, recovery_error: Exception) -> None:
        super().__init__("CAT update and state recovery both failed")
        self.update_error = update_error
        self.recovery_error = recovery_error


class SnapshotAuthenticator(Protocol):
    """Application-owned authenticator; keys never belong in a profile/snapshot."""

    def sign(self, payload: bytes) -> str: ...

    def verify(self, payload: bytes, signature: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class ResearchCATItem:
    item_id: str
    qid: str
    item_code: str
    stem: str
    source_locator: str
    fit_locator: str
    key_direction: str
    a: float
    thresholds: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class ResearchResponseOption:
    raw_value: int
    label: str | None


@dataclass(frozen=True, slots=True)
class ResearchCATQuestion:
    session_id: str
    profile_id: str
    profile_sha256: str
    dimension: str
    item_id: str
    qid: str
    stem: str
    response_options: tuple[ResearchResponseOption, ...]
    step: int


@dataclass(frozen=True, slots=True)
class ResearchCATProgress:
    session_id: str
    profile_id: str
    profile_sha256: str
    config_sha256: str
    status: str
    items_answered: int
    stop_reason: str | None


@dataclass(frozen=True, slots=True)
class ResearchCATCompletion:
    """Completion metadata only; no theta, SE, score, or interpretation."""

    session_id: str
    profile_id: str
    profile_sha256: str
    config_sha256: str
    dimension: str
    status: str
    items_administered: int
    items_answered: int
    stop_reason: str
    research_only: bool
    publication_status: str
    psychological_interpretation_allowed: bool


@dataclass(frozen=True, slots=True, init=False)
class ResearchCATProfile:
    """Validated profile loaded from exact bytes supplied by the caller."""

    profile_id: str
    profile_type: str
    instrument_id: str
    dimension: str
    source_population: str
    source_categories: tuple[int, ...]
    category_labels: tuple[str, ...] | None
    category_labels_status: str
    items: tuple[ResearchCATItem, ...]
    file_sha256: str
    research_only: bool
    publication_status: str
    psychological_interpretation_allowed: bool
    human_curated: bool
    raw_profile_bytes: bytes = field(repr=False)
    manifest_sha256: str | None
    source_metadata_json: str
    rights_metadata_json: str
    model_metadata_json: str
    scoring_metadata_json: str
    provenance_metadata_json: str
    raw_metadata_json: str

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        expected_file_sha256: str,
        manifest_path: Path | None = None,
        expected_manifest_sha256: str | None = None,
    ) -> ResearchCATProfile:
        """Load exact bytes against an independently registered trusted digest.

        The digest must come from the server's reviewed registry, never from an
        uploaded profile or a client-computed digest. Structural validation does
        not independently prove that parameters were exported from a fit.
        """

        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ResearchSessionError(
                "profile_unreadable", "research profile file could not be read"
            ) from exc
        manifest_bytes = None
        if manifest_path is not None:
            try:
                manifest_bytes = manifest_path.read_bytes()
            except OSError as exc:
                raise ResearchSessionError(
                    "profile_manifest_unreadable",
                    "research profile manifest could not be read",
                ) from exc
        return cls.from_bytes(
            raw,
            expected_file_sha256=expected_file_sha256,
            manifest_bytes=manifest_bytes,
            expected_manifest_sha256=expected_manifest_sha256,
        )

    @classmethod
    def from_bytes(
        cls,
        raw: bytes,
        *,
        expected_file_sha256: str,
        manifest_bytes: bytes | None = None,
        expected_manifest_sha256: str | None = None,
    ) -> ResearchCATProfile:
        if (
            not isinstance(raw, bytes)
            or type(expected_file_sha256) is not str
            or not _SHA256.fullmatch(expected_file_sha256)
        ):
            raise ResearchSessionError(
                "profile_hash_required",
                "a lowercase expected profile SHA-256 is required",
            )
        actual_sha256 = hashlib.sha256(raw).hexdigest()
        if not hmac.compare_digest(actual_sha256, expected_file_sha256):
            raise ResearchSessionError(
                "profile_hash_mismatch",
                "research profile bytes differ from the expected SHA-256",
            )
        try:
            document = json.loads(
                raw.decode("utf-8-sig"),
                object_pairs_hook=_reject_duplicate_json_keys,
                parse_constant=_reject_nonfinite_json_constant,
            )
        except ResearchSessionError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ResearchSessionError(
                "profile_json_invalid", "research profile is not valid UTF-8 JSON"
            ) from exc
        if not isinstance(document, dict):
            raise ResearchSessionError(
                "profile_schema_invalid", "research profile root must be an object"
            )
        return cls._from_verified_document(
            document,
            actual_sha256,
            raw,
            manifest_bytes=manifest_bytes,
            expected_manifest_sha256=expected_manifest_sha256,
        )

    @classmethod
    def _from_verified_document(
        cls,
        document: Mapping[str, object],
        file_sha256: str,
        raw: bytes,
        *,
        manifest_bytes: bytes | None = None,
        expected_manifest_sha256: str | None = None,
    ) -> ResearchCATProfile:
        if document.get("schema") != PROMIS_PEDIATRIC_PROFILE_SCHEMA and (
            manifest_bytes is not None or expected_manifest_sha256 is not None
        ):
            raise ResearchSessionError(
                "profile_manifest_unexpected",
                "manifest inputs are supported only by the pinned PROMIS pediatric v3 schema",
            )
        if document.get("schema") == NHANES_DPQ_PROFILE_SCHEMA:
            return _from_verified_nhanes_dpq_document(cls, document, file_sha256, raw)
        if document.get("schema") == PROMIS_PEDIATRIC_PROFILE_SCHEMA:
            return _from_verified_promis_pediatric_document(
                cls,
                document,
                file_sha256,
                raw,
                manifest_bytes=manifest_bytes,
                expected_manifest_sha256=expected_manifest_sha256,
            )
        required = {
            "schema",
            "profile_id",
            "profile_type",
            "research_only",
            "publication_status",
            "psychological_interpretation_allowed",
            "dimension",
            "instrument_id",
            "response_scale",
            "scoring",
            "model",
            "source",
            "rights",
            "provenance",
            "items",
            "not_approved_for",
        }
        if set(document) != required:
            raise ResearchSessionError(
                "profile_schema_invalid",
                "research profile fields differ from the v1 schema",
            )
        if (
            document.get("schema") != PROFILE_SCHEMA
            or type(document.get("research_only")) is not bool
            or document.get("research_only") is not True
            or document.get("publication_status") != RESEARCH_PUBLICATION_STATUS
            or type(document.get("psychological_interpretation_allowed")) is not bool
            or document.get("psychological_interpretation_allowed") is not False
            or document.get("profile_type") != PROFILE_STATUS
        ):
            raise ResearchSessionError(
                "profile_status_invalid",
                "profile must remain a candidate research-only profile",
            )
        if "human_curated" in document and document["human_curated"] is not False:
            raise ResearchSessionError(
                "profile_status_invalid", "research profile cannot claim human curation"
            )
        profile_id = _require_ref(document.get("profile_id"), "profile_id")
        instrument_id = _require_ref(document.get("instrument_id"), "instrument_id")
        dimension = _require_text(
            document.get("dimension"), "dimension", max_length=128
        )
        response_scale = document.get("response_scale")
        if not isinstance(response_scale, Mapping):
            raise ResearchSessionError(
                "profile_response_scale_invalid", "response_scale must be an object"
            )
        values = response_scale.get("values")
        if (
            not isinstance(values, list)
            or any(type(value) is not int for value in values)
            or tuple(values) not in _ALLOWED_CATEGORY_SCALES
        ):
            raise ResearchSessionError(
                "profile_categories_invalid",
                "only ordinal source codes 1..6 or 0..3 are supported",
            )
        labels_value = response_scale.get("category_labels")
        labels: tuple[str, ...] | None
        if labels_value is None:
            labels = None
        elif (
            isinstance(labels_value, list)
            and len(labels_value) == len(values)
            and all(isinstance(label, str) and label.strip() for label in labels_value)
        ):
            labels = tuple(labels_value)
        else:
            raise ResearchSessionError(
                "profile_labels_invalid",
                "category_labels must be null or match source categories",
            )
        label_status = _require_text(
            response_scale.get("category_labels_status"),
            "response_scale.category_labels_status",
            max_length=128,
        )
        scoring = document.get("scoring")
        model = document.get("model")
        source = document.get("source")
        rights = document.get("rights")
        provenance = document.get("provenance")
        if not all(
            isinstance(value, Mapping) and value
            for value in (scoring, model, source, rights, provenance)
        ):
            raise ResearchSessionError(
                "profile_metadata_invalid",
                "scoring, model, source, rights and provenance must be non-empty objects",
            )
        _validate_model_metadata(model)
        _validate_rights_metadata(rights)
        source_population = _require_text(
            source.get("population"), "source.population", max_length=512
        )
        _validate_scoring_metadata(scoring, tuple(values))
        if not isinstance(document.get("items"), list) or not document["items"]:
            raise ResearchSessionError(
                "profile_items_invalid", "research profile must include items"
            )
        items = tuple(
            _parse_item(
                item,
                source_categories=tuple(values),
                expected_fit_sha256=str(model.get("fit_sha256")),
            )
            for item in document["items"]
        )
        item_ids = [item.item_id for item in items]
        qids = [item.qid for item in items]
        if len(set(item_ids)) != len(item_ids) or len(set(qids)) != len(qids):
            raise ResearchSessionError(
                "profile_item_ids_duplicate",
                "research profile item identifiers must be unique",
            )
        if (
            not isinstance(document.get("not_approved_for"), list)
            or not document["not_approved_for"]
        ):
            raise ResearchSessionError(
                "profile_status_invalid",
                "not_approved_for must list the profile's prohibited uses",
            )
        instance = object.__new__(cls)
        fields = {
            "profile_id": profile_id,
            "profile_type": PROFILE_STATUS,
            "instrument_id": instrument_id,
            "dimension": dimension,
            "source_population": source_population,
            "source_categories": tuple(values),
            "category_labels": labels,
            "category_labels_status": label_status,
            "items": items,
            "file_sha256": file_sha256,
            "research_only": True,
            "publication_status": RESEARCH_PUBLICATION_STATUS,
            "psychological_interpretation_allowed": False,
            "human_curated": False,
            "source_metadata_json": _canonical_json(source),
            "rights_metadata_json": _canonical_json(rights),
            "model_metadata_json": _canonical_json(model),
            "scoring_metadata_json": _canonical_json(scoring),
            "provenance_metadata_json": _canonical_json(provenance),
            "raw_metadata_json": _canonical_json(document),
            "raw_profile_bytes": raw,
            "manifest_sha256": None,
        }
        for key, value in fields.items():
            object.__setattr__(instance, key, value)
        _verify_profile_probability_parity(instance, model)
        return instance


@dataclass(frozen=True, slots=True)
class _RecordedAnswer:
    item_id: str
    raw_value: int


class ResearchCATSession:
    """In-memory one-domain GRM CAT state using explicit research profile data.

    The accepted seed remains in the configuration hash for provenance; MFI/EAP
    are deterministic here and this adapter does not consume random numbers.
    """

    def __init__(self) -> None:
        raise TypeError("use ResearchCATSession.start() or restore()")

    @classmethod
    def start(
        cls,
        profile: ResearchCATProfile,
        config: CATConfig,
        *,
        session_id: str,
    ) -> ResearchCATSession:
        if not isinstance(profile, ResearchCATProfile):
            raise ResearchSessionError(
                "profile_not_verified",
                "session requires a hash-verified ResearchCATProfile",
            )
        _validate_config(config, len(profile.items))
        session_id = _require_ref(session_id, "session_id")
        return cls._new(profile, config, session_id)

    @classmethod
    def restore(
        cls,
        profile: ResearchCATProfile,
        config: CATConfig,
        snapshot: Mapping[str, object],
        *,
        authenticator: SnapshotAuthenticator,
    ) -> ResearchCATSession:
        if not isinstance(profile, ResearchCATProfile):
            raise ResearchSessionError(
                "profile_not_verified",
                "restore requires a hash-verified ResearchCATProfile",
            )
        _validate_config(config, len(profile.items))
        payload = _verify_snapshot(snapshot, authenticator)
        if (
            payload.get("profile_id") != profile.profile_id
            or payload.get("profile_sha256") != profile.file_sha256
        ):
            raise ResearchSessionError(
                "snapshot_profile_mismatch",
                "snapshot is bound to a different research profile",
            )
        config_sha256 = _config_sha256(config)
        if (
            payload.get("config_version") != config.config_version
            or payload.get("config_sha256") != config_sha256
        ):
            raise ResearchSessionError(
                "snapshot_config_mismatch",
                "snapshot is bound to a different CAT configuration",
            )
        session_id = _require_ref(payload.get("session_id"), "snapshot.session_id")
        session = cls._new(profile, config, session_id)
        raw_answers = payload.get("answers")
        if not isinstance(raw_answers, list):
            raise ResearchSessionError(
                "snapshot_answers_invalid", "snapshot answers must be an ordered list"
            )
        if type(payload.get("step")) is not int or payload["step"] != len(raw_answers):
            raise ResearchSessionError(
                "snapshot_step_invalid",
                "snapshot step must equal the number of recorded answers",
            )
        for event in raw_answers:
            if not isinstance(event, Mapping) or set(event) != {"item_id", "raw_value"}:
                raise ResearchSessionError(
                    "snapshot_answer_invalid",
                    "snapshot answer event has an invalid schema",
                )
            item_id = _require_ref(event.get("item_id"), "snapshot.answer.item_id")
            raw_value = event.get("raw_value")
            if type(raw_value) is not int:
                raise ResearchSessionError(
                    "snapshot_answer_invalid",
                    "snapshot answer must preserve a source ordinal integer",
                )
            question = session.next_item()
            if question is None or question.item_id != item_id:
                raise ResearchSessionError(
                    "snapshot_answer_order_invalid",
                    "snapshot answer item does not match deterministic MFI order",
                )
            session.answer(item_id, raw_value)

        expected_status = payload.get("status")
        if expected_status != session.status:
            raise ResearchSessionError(
                "snapshot_status_invalid",
                "snapshot status differs from replayed CAT state",
            )
        expected_stop_reason = payload.get("stop_reason")
        if expected_stop_reason != session.stop_reason:
            raise ResearchSessionError(
                "snapshot_stop_reason_invalid",
                "snapshot stopping state differs from replayed CAT state",
            )
        pending_id = payload.get("pending_item_id")
        if pending_id is None:
            if session._pending_item_id is not None:
                raise ResearchSessionError(
                    "snapshot_pending_item_invalid",
                    "snapshot omits the pending selected item",
                )
        else:
            pending_id = _require_ref(pending_id, "snapshot.pending_item_id")
            question = session.next_item()
            if question is None or question.item_id != pending_id:
                raise ResearchSessionError(
                    "snapshot_pending_item_invalid",
                    "snapshot pending item is not the next deterministic MFI item",
                )
        return session

    @classmethod
    def _new(
        cls, profile: ResearchCATProfile, config: CATConfig, session_id: str
    ) -> ResearchCATSession:
        instance = object.__new__(cls)
        instance._profile = profile
        instance._config = config
        instance._config_sha256 = _config_sha256(config)
        instance._session_id = session_id
        instance._engine_items, instance._engine, instance._item_lookup = _make_engine(
            profile, config, session_id
        )
        instance._theta = float(config.initial_theta)
        instance._se = float(config.prior_sd)
        instance._answers = []
        instance._pending_item_id = None
        instance._status = "ACTIVE"
        instance._stop_reason = None
        instance._completion = None
        return instance

    @property
    def status(self) -> str:
        return self._status

    @property
    def items_answered(self) -> int:
        return len(self._answers)

    @property
    def pending_item_id(self) -> str | None:
        return self._pending_item_id

    @property
    def stop_reason(self) -> str | None:
        return self._stop_reason

    def next_item(self) -> ResearchCATQuestion | None:
        """Select deterministically with MFI; repeated reads return the same item."""

        if self._status != "ACTIVE":
            return None
        if self._pending_item_id is None:
            self._refresh_stopping_state()
        if self._status != "ACTIVE":
            return None
        if self._pending_item_id is None:
            try:
                engine_item = self._engine.get_next_item()
                item_id = str(engine_item.additional_properties["research_item_id"])
            except Exception as exc:
                raise ResearchSessionError(
                    "mfi_selection_failed", "research CAT MFI selection failed"
                ) from exc
            if item_id not in self._item_lookup:
                raise ResearchSessionError(
                    "mfi_item_mapping_invalid",
                    "MFI selected an item outside the verified profile",
                )
            self._pending_item_id = item_id
        item = self._item_lookup[self._pending_item_id]
        options = tuple(
            ResearchResponseOption(
                raw_value=value,
                label=(
                    self._profile.category_labels[index]
                    if self._profile.category_labels
                    else None
                ),
            )
            for index, value in enumerate(self._profile.source_categories)
        )
        return ResearchCATQuestion(
            session_id=self._session_id,
            profile_id=self._profile.profile_id,
            profile_sha256=self._profile.file_sha256,
            dimension=self._profile.dimension,
            item_id=item.item_id,
            qid=item.qid,
            stem=item.stem,
            response_options=options,
            step=len(self._answers),
        )

    def answer(self, item_id: str, raw_value: int) -> ResearchCATProgress:
        """Accept one actual source category for the currently pending item."""

        if self._status != "ACTIVE":
            raise ResearchSessionError(
                "session_not_active", "research CAT session no longer accepts responses"
            )
        if not isinstance(item_id, str) or not item_id:
            raise ResearchSessionError("item_id_invalid", "item_id is required")
        answered_ids = {answer.item_id for answer in self._answers}
        if item_id in answered_ids:
            raise ResearchSessionError(
                "duplicate_response",
                "research CAT item already has an accepted response",
            )
        if self._pending_item_id is None:
            raise ResearchSessionError(
                "no_pending_item", "select the next research CAT item before answering"
            )
        if item_id != self._pending_item_id:
            raise ResearchSessionError(
                "wrong_pending_item",
                "response item does not match the currently selected item",
            )
        if (
            type(raw_value) is not int
            or raw_value not in self._profile.source_categories
        ):
            raise ResearchSessionError(
                "response_category_invalid",
                "response is outside the profile's source category codes",
            )
        item = self._item_lookup[item_id]
        score = _keyed_score(
            raw_value, item.key_direction, self._profile.source_categories
        )
        engine_item = self._engine_items[item_id]
        committed_answers = list(self._answers)
        committed_theta = self._theta
        committed_se = self._se
        try:
            self._apply_answer(item, engine_item, score, raw_value)
            if len(self._answers) != len(committed_answers) + 1:
                raise RuntimeError("response accounting did not advance")
        except _RECOVERABLE_ENGINE_ERRORS as update_error:
            try:
                self._restore_committed_state(
                    committed_answers, pending_item_id=item_id
                )
            except _RECOVERABLE_ENGINE_ERRORS as recovery_error:
                self._answers = committed_answers
                self._theta = committed_theta
                self._se = committed_se
                self._status = "FAILED"
                self._stop_reason = "state_recovery_failed"
                self._pending_item_id = None
                self._completion = None
                raise ResearchSessionError(
                    "session_recovery_failed",
                    "research CAT update failed and prior state could not be recovered",
                ) from _CATRecoveryFailure(update_error, recovery_error)
            raise ResearchSessionError(
                "response_update_failed", "research CAT response could not be committed"
            ) from update_error
        return self._progress()

    def _apply_answer(
        self,
        item: ResearchCATItem,
        engine_item: object,
        score: int,
        raw_value: int,
    ) -> None:
        self._engine.response_pattern.append(score)
        self._engine.answered_items.append(engine_item)
        estimate, standard_error = self._engine.estimate_ability_level()
        theta = float(estimate)
        se = float(standard_error)
        if not math.isfinite(theta) or not math.isfinite(se) or se <= 0:
            raise ValueError("non-finite EAP estimate")
        self._engine.ability_level = theta
        self._engine.standard_error = se
        self._theta = theta
        self._se = se
        self._engine.item_pool.delete_item(engine_item)
        self._answers.append(_RecordedAnswer(item_id=item.item_id, raw_value=raw_value))
        self._pending_item_id = None
        self._refresh_stopping_state()

    def completion(self) -> ResearchCATCompletion:
        """Return only completion/provenance metadata, never the EAP estimate."""

        if self._status != "COMPLETED" or not self._stop_reason:
            raise ResearchSessionError(
                "completion_not_reached",
                "research CAT stopping criteria have not been met",
            )
        if self._completion is None:
            self._completion = ResearchCATCompletion(
                session_id=self._session_id,
                profile_id=self._profile.profile_id,
                profile_sha256=self._profile.file_sha256,
                config_sha256=self._config_sha256,
                dimension=self._profile.dimension,
                status="COMPLETED",
                items_administered=len(self._answers),
                items_answered=len(self._answers),
                stop_reason=self._stop_reason,
                research_only=True,
                publication_status=RESEARCH_PUBLICATION_STATUS,
                psychological_interpretation_allowed=False,
            )
        return self._completion

    def save_state(self, authenticator: SnapshotAuthenticator) -> dict[str, object]:
        """Create an authenticated snapshot; the caller must store it encrypted."""

        if self._status == "FAILED":
            raise ResearchSessionError(
                "snapshot_unavailable", "a failed CAT session cannot be checkpointed"
            )
        if not _is_authenticator(authenticator):
            raise ResearchSessionError(
                "snapshot_authenticator_required",
                "a trusted snapshot authenticator is required",
            )
        payload: dict[str, object] = {
            "schema": SNAPSHOT_SCHEMA,
            "session_id": self._session_id,
            "profile_id": self._profile.profile_id,
            "profile_sha256": self._profile.file_sha256,
            "config_version": self._config.config_version,
            "config_sha256": self._config_sha256,
            "step": len(self._answers),
            "status": self._status,
            "stop_reason": self._stop_reason,
            "pending_item_id": self._pending_item_id,
            "answers": [
                {"item_id": answer.item_id, "raw_value": answer.raw_value}
                for answer in self._answers
            ],
        }
        encoded = _canonical_json(payload).encode("utf-8")
        signing_failed = False
        signature: object = None
        try:
            signature = authenticator.sign(encoded)
        except _RECOVERABLE_ENGINE_ERRORS:
            signing_failed = True
        if (
            signing_failed
            or type(signature) is not str
            or not _SAFE_SIGNATURE.fullmatch(signature)
        ):
            raise ResearchSessionError(
                "snapshot_signing_failed",
                "snapshot authentication could not be created",
            )
        return {
            "payload": payload,
            "payload_sha256": hashlib.sha256(encoded).hexdigest(),
            "signature": signature,
        }

    def _progress(self) -> ResearchCATProgress:
        return ResearchCATProgress(
            session_id=self._session_id,
            profile_id=self._profile.profile_id,
            profile_sha256=self._profile.file_sha256,
            config_sha256=self._config_sha256,
            status=self._status,
            items_answered=len(self._answers),
            stop_reason=self._stop_reason,
        )

    def _refresh_stopping_state(self) -> None:
        if self._status != "ACTIVE" or self._pending_item_id is not None:
            return
        answered = len(self._answers)
        remaining = bool(self._engine.item_pool.test_items)
        if answered >= self._config.min_items:
            if (
                self._config.se_threshold is not None
                and self._se <= self._config.se_threshold
            ):
                self._status = "COMPLETED"
                self._stop_reason = "se_threshold_reached"
            elif answered >= self._config.max_items:
                self._status = "COMPLETED"
                self._stop_reason = "max_items_reached"
            elif not remaining:
                self._status = "COMPLETED"
                self._stop_reason = "item_bank_exhausted"
        elif not remaining:
            self._status = "INCOMPLETE"
            self._stop_reason = "item_bank_exhausted_before_minimum"

    def _restore_committed_state(
        self,
        committed_answers: Sequence[_RecordedAnswer],
        *,
        pending_item_id: str,
    ) -> None:
        self._engine_items, self._engine, self._item_lookup = _make_engine(
            self._profile, self._config, self._session_id
        )
        self._theta = float(self._config.initial_theta)
        self._se = float(self._config.prior_sd)
        self._pending_item_id = None
        self._status = "ACTIVE"
        self._stop_reason = None
        self._answers = []
        for answer in committed_answers:
            try:
                engine_item = self._engine.get_next_item()
                selected_id = str(engine_item.additional_properties["research_item_id"])
            except _RECOVERABLE_ENGINE_ERRORS as exc:
                raise ResearchSessionError(
                    "session_rollback_failed",
                    "could not select an item while recovering CAT state",
                ) from exc
            if selected_id != answer.item_id:
                raise ResearchSessionError(
                    "session_rollback_failed",
                    "could not rebuild the accepted research response state",
                )
            self._pending_item_id = selected_id
            item = self._item_lookup[selected_id]
            score = _keyed_score(
                answer.raw_value, item.key_direction, self._profile.source_categories
            )
            self._apply_answer(item, engine_item, score, answer.raw_value)
        if self._status != "ACTIVE":
            raise ResearchSessionError(
                "session_rollback_failed",
                "replayed CAT state stopped before its pending item",
            )
        try:
            engine_item = self._engine.get_next_item()
            selected_id = str(engine_item.additional_properties["research_item_id"])
        except _RECOVERABLE_ENGINE_ERRORS as exc:
            raise ResearchSessionError(
                "session_rollback_failed", "could not restore the pending CAT item"
            ) from exc
        if selected_id != pending_item_id:
            raise ResearchSessionError(
                "session_rollback_failed", "could not restore the pending research item"
            )
        self._pending_item_id = selected_id
        if len(self._answers) != len(committed_answers):
            raise ResearchSessionError(
                "session_rollback_failed",
                "recovered CAT response count does not match checkpoint",
            )


def _parse_item(
    value: object,
    *,
    source_categories: tuple[int, ...],
    expected_fit_sha256: str,
) -> ResearchCATItem:
    required = {
        "item_id",
        "qid",
        "ipip100_code",
        "item_info_id",
        "response_column",
        "stem",
        "key_direction",
        "response_transform",
        "a",
        "thresholds",
        "observed_n",
        "source_locator",
        "fit_locator",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise ResearchSessionError(
            "profile_item_schema_invalid",
            "profile item fields differ from the research schema",
        )
    item_id = _require_ref(value.get("item_id"), "item.item_id")
    qid = _require_ref(value.get("qid"), "item.qid")
    item_code = _require_text(
        value.get("ipip100_code"), "item.ipip100_code", max_length=64
    )
    stem = _require_text(value.get("stem"), "item.stem", max_length=2000)
    if value.get("item_info_id") != qid or value.get("response_column") != qid:
        raise ResearchSessionError(
            "profile_item_crosswalk_invalid", "item crosswalk IDs must agree with qid"
        )
    direction = value.get("key_direction")
    if direction not in {"positive", "reverse"}:
        raise ResearchSessionError(
            "profile_key_direction_invalid", "key_direction must be positive or reverse"
        )
    expected_transform = (
        "identity"
        if direction == "positive"
        else f"{source_categories[0] + source_categories[-1]} - response"
    )
    if value.get("response_transform") != expected_transform:
        raise ResearchSessionError(
            "profile_key_transform_invalid",
            "raw response transform must match key direction",
        )
    observed_n = value.get("observed_n")
    if type(observed_n) is not int or observed_n < 0:
        raise ResearchSessionError(
            "profile_item_observed_n_invalid",
            "observed_n must be a non-negative integer",
        )
    source_locator = value.get("source_locator")
    fit_locator = value.get("fit_locator")
    if not isinstance(source_locator, Mapping) or set(source_locator) != {
        "url",
        "section",
        "key_block",
        "position_in_block",
        "crosswalk_file",
        "crosswalk_row",
        "item_info_file",
    }:
        raise ResearchSessionError(
            "profile_item_locator_invalid",
            "source_locator does not match the profile schema",
        )
    if not isinstance(fit_locator, Mapping) or set(fit_locator) != {
        "file",
        "sha256",
        "parameter_key",
        "parameter_metric",
    }:
        raise ResearchSessionError(
            "profile_item_locator_invalid",
            "fit_locator does not match the profile schema",
        )
    for key in ("url", "section", "key_block", "crosswalk_file", "item_info_file"):
        _require_text(
            source_locator.get(key), f"item.source_locator.{key}", max_length=1000
        )
    if source_locator.get("key_block") != f"{direction}_keyed":
        raise ResearchSessionError(
            "profile_item_locator_invalid",
            "source key block must agree with item key direction",
        )
    for key in ("file", "parameter_key", "parameter_metric"):
        _require_text(fit_locator.get(key), f"item.fit_locator.{key}", max_length=1000)
    if (
        type(source_locator.get("position_in_block")) is not int
        or source_locator["position_in_block"] < 1
        or type(source_locator.get("crosswalk_row")) is not int
        or source_locator["crosswalk_row"] < 1
        or not _SHA256.fullmatch(str(fit_locator.get("sha256") or ""))
        or fit_locator.get("sha256") != expected_fit_sha256
        or fit_locator.get("parameter_key") != qid
    ):
        raise ResearchSessionError(
            "profile_item_locator_invalid",
            "source/fit locator indexes and hashes must be valid",
        )
    a = value.get("a")
    thresholds = value.get("thresholds")
    if (
        isinstance(a, bool)
        or not isinstance(a, (int, float))
        or not math.isfinite(float(a))
        or float(a) <= 0
        or not isinstance(thresholds, list)
        or len(thresholds) != len(source_categories) - 1
        or any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in thresholds
        )
    ):
        raise ResearchSessionError(
            "profile_item_parameters_invalid",
            "GRM requires finite a>0 and one threshold per category boundary",
        )
    try:
        threshold_values = tuple(float(value) for value in thresholds)
    except (TypeError, ValueError) as exc:
        raise ResearchSessionError(
            "profile_item_parameters_invalid", "GRM thresholds must be numeric"
        ) from exc
    if any(not math.isfinite(value) for value in threshold_values) or any(
        left >= right for left, right in pairwise(threshold_values)
    ):
        raise ResearchSessionError(
            "profile_item_parameters_invalid",
            "GRM thresholds must be finite and strictly increasing",
        )
    return ResearchCATItem(
        item_id=item_id,
        qid=qid,
        item_code=item_code,
        stem=stem,
        source_locator=_canonical_json(source_locator),
        fit_locator=_canonical_json(fit_locator),
        key_direction=direction,
        a=float(a),
        thresholds=threshold_values,
    )


def _from_verified_nhanes_dpq_document(
    cls: type[ResearchCATProfile],
    document: Mapping[str, object],
    file_sha256: str,
    raw: bytes,
) -> ResearchCATProfile:
    root_fields = {
        "schema",
        "profile_id",
        "profile_type",
        "instrument_id",
        "instrument_family",
        "dimension",
        "research_only",
        "publication_status",
        "psychological_interpretation_allowed",
        "response_scale",
        "scoring",
        "candidate_cat_config",
        "model",
        "source",
        "rights",
        "provenance",
        "loader_compatibility",
        "items",
        "not_approved_for",
    }
    if set(document) != root_fields:
        raise ResearchSessionError(
            "profile_v2_schema_invalid",
            "NHANES_DPQ v2 profile fields differ from its closed schema",
        )
    if (
        document.get("schema") != NHANES_DPQ_PROFILE_SCHEMA
        or document.get("profile_type") != PROFILE_STATUS
        or document.get("instrument_id") != "NHANES_P_DPQ_9ITEM_RESEARCH_CANDIDATE"
        or document.get("instrument_family") != "NHANES_DPQ"
        or type(document.get("research_only")) is not bool
        or document.get("research_only") is not True
        or document.get("publication_status") != RESEARCH_PUBLICATION_STATUS
        or type(document.get("psychological_interpretation_allowed")) is not bool
        or document.get("psychological_interpretation_allowed") is not False
    ):
        raise ResearchSessionError(
            "profile_status_invalid",
            "NHANES_DPQ v2 must remain a non-published research candidate",
        )

    profile_id = _require_ref(document.get("profile_id"), "profile_id")
    if profile_id != _NHANES_DPQ_PROFILE_ID:
        raise ResearchSessionError(
            "profile_identity_invalid",
            "NHANES_DPQ v2 profile ID must match the fixed adult research candidate",
        )
    dimension = _require_text(document.get("dimension"), "dimension", max_length=128)
    if dimension != "DPQ item-response research dimension; no clinical interpretation":
        raise ResearchSessionError(
            "profile_dimension_invalid",
            "NHANES_DPQ v2 dimension label must preserve its nonclinical scope",
        )

    response_scale = _require_v2_mapping(
        document.get("response_scale"),
        {
            "values",
            "category_labels",
            "category_labels_status",
            "missing_codes",
            "missing_policy",
        },
        "response_scale",
    )
    values = response_scale.get("values")
    labels_value = response_scale.get("category_labels")
    if (
        type(values) is not list
        or values != [0, 1, 2, 3]
        or any(type(value) is not int for value in values)
        or type(labels_value) is not list
        or labels_value
        != [
            "Not at all",
            "Several days",
            "More than half the days",
            "Nearly every day",
        ]
        or response_scale.get("category_labels_status")
        != "verified_verbatim_against_official_NCHS_P_DPQ_codebook"
        or response_scale.get("missing_codes") != ["7", "9", "."]
        or not isinstance(response_scale.get("missing_policy"), str)
        or not response_scale["missing_policy"].strip()
    ):
        raise ResearchSessionError(
            "profile_categories_invalid",
            "NHANES_DPQ v2 must retain its official direct 0..3 categories and missing codes",
        )

    scoring = _require_v2_mapping(
        document.get("scoring"),
        {
            "positive_key_transform",
            "reverse_key_transform",
            "key_direction",
            "item_parameters",
            "no_person_scores_or_norms_included",
            "clinical_cutpoints",
            "crisis_thresholds",
        },
        "scoring",
    )
    if (
        scoring.get("positive_key_transform") != "identity"
        or scoring.get("reverse_key_transform") is not None
        or scoring.get("key_direction") != "direct for all nine source variables"
        or scoring.get("item_parameters")
        != "mirt 1.47 graded model; source categories 0..3 retained directly"
        or scoring.get("no_person_scores_or_norms_included") is not True
        or scoring.get("clinical_cutpoints") is not None
        or scoring.get("crisis_thresholds") is not None
    ):
        raise ResearchSessionError(
            "profile_scoring_invalid",
            "NHANES_DPQ v2 cannot introduce reverse keys, scores, or clinical thresholds",
        )

    candidate = _require_v2_mapping(
        document.get("candidate_cat_config"),
        {"min_items", "max_items", "se_threshold", "status", "rationale"},
        "candidate_cat_config",
    )
    if (
        type(candidate.get("min_items")) is not int
        or candidate.get("min_items") != 9
        or type(candidate.get("max_items")) is not int
        or candidate.get("max_items") != 9
        or candidate.get("se_threshold") is not None
        or candidate.get("status") != "NOT_APPROVED_RESEARCH_CANDIDATE"
        or not isinstance(candidate.get("rationale"), str)
        or not candidate["rationale"].strip()
    ):
        raise ResearchSessionError(
            "profile_candidate_config_invalid",
            "NHANES_DPQ v2 candidate bounds must remain explicit and unapproved",
        )

    model = _require_v2_mapping(
        document.get("model"),
        {
            "package",
            "version",
            "itemtype",
            "factors",
            "method",
            "latent_distribution",
            "converged",
            "iterations",
            "quadrature_points",
            "maximum_cycles",
            "standard_errors",
            "freely_estimated_parameters",
            "calibration_records",
            "estimation_rows_used",
            "all_missing_rows_retained_in_input",
            "all_missing_rows_omitted_as_informationless",
            "partial_missing_rows_used",
            "complete_case_filter",
            "imputation",
            "fit_sha256",
            "calibration_sha256",
            "evaluation_sha256",
            "evaluation_fit_performed",
            "log_likelihood",
            "aic",
            "bic",
            "warnings",
        },
        "model",
    )
    _validate_model_metadata(model)
    if (
        model.get("version") != "1.47"
        or model.get("method") != "EM"
        or model.get("iterations") != 76
        or type(model.get("iterations")) is not int
        or model.get("quadrature_points") != 41
        or type(model.get("quadrature_points")) is not int
        or model.get("maximum_cycles") != 1000
        or type(model.get("maximum_cycles")) is not int
        or model.get("standard_errors") is not False
        or model.get("freely_estimated_parameters") != 36
        or model.get("calibration_records") != 6000
        or model.get("estimation_rows_used") != 5551
        or model.get("all_missing_rows_retained_in_input") != 449
        or model.get("all_missing_rows_omitted_as_informationless") != 449
        or model.get("partial_missing_rows_used") is not True
        or model.get("complete_case_filter") is not False
        or model.get("imputation") is not False
        or model.get("fit_sha256") != _NHANES_DPQ_FIT_SHA256
        or model.get("calibration_sha256") != _NHANES_DPQ_CALIBRATION_SHA256
        or model.get("evaluation_sha256") != _NHANES_DPQ_EVALUATION_SHA256
        or model.get("evaluation_fit_performed") is not False
        or model.get("log_likelihood") != -30361.64541003759
        or model.get("aic") != 60795.29082007518
        or model.get("bic") != 61033.673221420024
        or model.get("warnings") != "data contains response patterns with only NAs"
    ):
        raise ResearchSessionError(
            "profile_model_provenance_invalid",
            "NHANES_DPQ v2 fit metadata differs from the fixed calibration-only research fit",
        )
    for name in ("log_likelihood", "aic", "bic"):
        value = model.get(name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise ResearchSessionError(
                "profile_model_provenance_invalid",
                "NHANES_DPQ v2 aggregate fit diagnostics must be finite numbers",
            )

    source = _require_v2_mapping(
        document.get("source"),
        {
            "population",
            "language",
            "version",
            "data_reference",
            "response_only_sha256",
            "codebook_url",
            "codebook_content_sha256",
            "codebook_bytes",
            "codebook_first_published",
            "codebook_last_revised",
            "target_age",
            "adolescent_access",
        },
        "source",
    )
    source_population = _require_text(
        source.get("population"), "source.population", max_length=512
    )
    if (
        source.get("language") != "English"
        or source.get("version")
        != "NHANES 2017-March 2020 pre-pandemic public-use P_DPQ"
        or source.get("data_reference") != _NHANES_DPQ_DATA_URL
        or source.get("response_only_sha256") != _NHANES_DPQ_SOURCE_SHA256
        or source.get("codebook_url") != _NHANES_DPQ_SOURCE_URL
        or source.get("codebook_content_sha256") != _NHANES_DPQ_CODEBOOK_SHA256
        or type(source.get("codebook_bytes")) is not int
        or source.get("codebook_bytes") != 44395
        or source.get("codebook_first_published") != "June 2021"
        or source.get("codebook_last_revised") != "NA"
        or source.get("target_age") != "18-150 in codebook; ages absent from fit input"
        or source.get("adolescent_access")
        != "P_DPQ public file has ages 18+ only; youth 12-17 is available through the NCHS Research Data Center and was not accessed"
        or source_population != _NHANES_DPQ_SOURCE_POPULATION
    ):
        raise ResearchSessionError(
            "profile_source_invalid",
            "NHANES_DPQ v2 source provenance or adult-only scope is invalid",
        )

    rights = _require_v2_mapping(
        document.get("rights"),
        {"items", "dataset", "cdc_content_guidance", "profile"},
        "rights",
    )
    item_rights = _require_v2_mapping(
        rights.get("items"),
        {
            "status",
            "basis",
            "source_url",
            "source_content_sha256",
            "source_bytes",
            "attribution",
        },
        "rights.items",
    )
    dataset_rights = _require_v2_mapping(
        rights.get("dataset"),
        {"status", "terms_url", "scope", "official_page_checked_via_web"},
        "rights.dataset",
    )
    cdc_guidance = _require_v2_mapping(
        rights.get("cdc_content_guidance"),
        {"source_url", "scope", "direct_http_status"},
        "rights.cdc_content_guidance",
    )
    profile_rights = _require_v2_mapping(
        rights.get("profile"), {"status", "operational_release"}, "rights.profile"
    )
    if (
        item_rights.get("status")
        != "official_reproduction_basis_found_for_PHQ_screener_content"
        or item_rights.get("source_url")
        != "https://www.phqscreeners.com/select-screener"
        or not _SHA256.fullmatch(str(item_rights.get("source_content_sha256") or ""))
        or type(item_rights.get("source_bytes")) is not int
        or item_rights.get("source_bytes") < 1
        or not _require_text(
            item_rights.get("basis"), "rights.items.basis", max_length=1000
        )
        or not _require_text(
            item_rights.get("attribution"), "rights.items.attribution", max_length=500
        )
        or dataset_rights.get("status") != "public_use_under_NCHS_data_user_agreement"
        or dataset_rights.get("terms_url")
        != "https://www.cdc.gov/nchs/policy/data-user-agreement.html"
        or not _require_text(
            dataset_rights.get("scope"), "rights.dataset.scope", max_length=1000
        )
        or dataset_rights.get("official_page_checked_via_web") != "2026-10-14"
        or cdc_guidance.get("source_url") != "https://www.cdc.gov/Other/imagereuse.html"
        or cdc_guidance.get("direct_http_status")
        != "403; page reviewed through official CDC search result only."
        or not _require_text(
            cdc_guidance.get("scope"),
            "rights.cdc_content_guidance.scope",
            max_length=1000,
        )
        or profile_rights.get("status") != _NHANES_DPQ_RIGHTS_STATUS
        or type(profile_rights.get("operational_release")) is not bool
        or profile_rights.get("operational_release") is not False
    ):
        raise ResearchSessionError(
            "profile_rights_invalid",
            "NHANES_DPQ v2 rights must remain source-attributed and pending operational review",
        )

    provenance = _require_v2_mapping(
        document.get("provenance"),
        {
            "created_at_utc",
            "fit_summary_sha256",
            "fit_script_sha256",
            "importer_sha256",
            "source_response_only_sha256",
            "split_manifest_sha256",
            "mirt_version",
            "r_version",
            "source_row_ids_included",
            "individual_theta_or_responses_included",
        },
        "provenance",
    )
    for name in ("fit_script_sha256", "importer_sha256", "split_manifest_sha256"):
        if not _SHA256.fullmatch(str(provenance.get(name) or "")):
            raise ResearchSessionError(
                "profile_provenance_invalid",
                f"provenance.{name} must be a lowercase SHA-256",
            )
    if (
        provenance.get("fit_summary_sha256") != model.get("fit_sha256")
        or provenance.get("source_response_only_sha256") != _NHANES_DPQ_SOURCE_SHA256
        or provenance.get("fit_script_sha256") != _NHANES_DPQ_FIT_SCRIPT_SHA256
        or provenance.get("importer_sha256") != _NHANES_DPQ_IMPORTER_SHA256
        or provenance.get("split_manifest_sha256") != _NHANES_DPQ_SPLIT_MANIFEST_SHA256
        or provenance.get("mirt_version") != "1.47"
        or not isinstance(provenance.get("r_version"), str)
        or not provenance.get("r_version", "").startswith("R version 4.6.1")
        or type(provenance.get("source_row_ids_included")) is not bool
        or provenance.get("source_row_ids_included") is not False
        or type(provenance.get("individual_theta_or_responses_included")) is not bool
        or provenance.get("individual_theta_or_responses_included") is not False
        or not _require_text(
            provenance.get("created_at_utc"), "provenance.created_at_utc", max_length=64
        )
    ):
        raise ResearchSessionError(
            "profile_provenance_invalid",
            "NHANES_DPQ v2 provenance cannot claim row IDs or person-level outputs",
        )

    loader = _require_v2_mapping(
        document.get("loader_compatibility"),
        {"status", "required_followup"},
        "loader_compatibility",
    )
    if loader.get(
        "status"
    ) != "not_compatible_with_current_research_profile_v1_loader" or not _require_text(
        loader.get("required_followup"),
        "loader_compatibility.required_followup",
        max_length=500,
    ):
        raise ResearchSessionError(
            "profile_v2_loader_metadata_invalid",
            "NHANES_DPQ v2 must declare that its source schema differs from v1",
        )

    not_approved = document.get("not_approved_for")
    required_prohibited_uses = {
        "adolescent or high-school use",
        "diagnosis or clinical severity classification",
        "crisis or suicide-risk determination",
        "psychological interpretation or individual reports",
        "approved/adaptive school CAT use",
        "population norms or cut-points",
        "operational or publication release",
    }
    if (
        type(not_approved) is not list
        or any(not isinstance(value, str) for value in not_approved)
        or not required_prohibited_uses.issubset(set(not_approved))
    ):
        raise ResearchSessionError(
            "profile_status_invalid",
            "NHANES_DPQ v2 must retain its explicit nonclinical and nonoperational exclusions",
        )

    raw_items = document.get("items")
    if type(raw_items) is not list or len(raw_items) != len(_NHANES_DPQ_ITEMS):
        raise ResearchSessionError(
            "profile_items_invalid",
            "NHANES_DPQ v2 must include exactly nine source variables",
        )
    parsed_items: list[ResearchCATItem] = []
    item_fields = {
        "item_id",
        "qid",
        "instrument_item_code",
        "stem",
        "key_direction",
        "response_transform",
        "a",
        "thresholds",
        "observed_n",
        "missing_n",
        "category_counts",
        "source_locator",
        "fit_locator",
    }
    locator_section = (
        "Codebook and Frequencies; English Text and Code or Value / Value Description"
    )
    for expected_item, value in zip(_NHANES_DPQ_ITEMS, raw_items, strict=True):
        value = _require_v2_mapping(value, item_fields, f"item[{expected_item}]")
        item_id = value.get("item_id")
        qid = value.get("qid")
        item_code = value.get("instrument_item_code")
        if (
            item_id != expected_item
            or qid != expected_item
            or item_code != expected_item
            or value.get("key_direction") != "direct"
            or value.get("response_transform") != "identity"
        ):
            raise ResearchSessionError(
                "profile_item_mapping_invalid",
                "NHANES_DPQ v2 item identifiers and direct source coding must match the nine DPQ variables",
            )
        item_id = _require_ref(item_id, "item.item_id")
        _require_text(value.get("stem"), f"item.{item_id}.stem", max_length=2000)
        source_locator = _require_v2_mapping(
            value.get("source_locator"),
            {"url", "variable", "section"},
            "item.source_locator",
        )
        if (
            source_locator.get("url") != _NHANES_DPQ_SOURCE_URL
            or source_locator.get("variable") != expected_item
            or source_locator.get("section") != locator_section
        ):
            raise ResearchSessionError(
                "profile_item_locator_invalid",
                "NHANES_DPQ v2 source locator must point to its exact official codebook variable",
            )
        fit_locator = _require_v2_mapping(
            value.get("fit_locator"),
            {"file", "sha256", "parameter_key", "parameter_metric"},
            "item.fit_locator",
        )
        if (
            fit_locator.get("file") != _NHANES_DPQ_FIT_FILE
            or fit_locator.get("sha256") != _NHANES_DPQ_FIT_SHA256
            or fit_locator.get("sha256") != model.get("fit_sha256")
            or fit_locator.get("parameter_key") != expected_item
            or fit_locator.get("parameter_metric")
            != "direct mirt 1.47 graded a and ordered thresholds for source codes 0..3; no reverse transform"
        ):
            raise ResearchSessionError(
                "profile_fit_locator_invalid",
                "NHANES_DPQ v2 parameters must bind to the exact variable and current fit hash",
            )
        observed_n = value.get("observed_n")
        missing_n = value.get("missing_n")
        category_counts = _require_v2_mapping(
            value.get("category_counts"), {"0", "1", "2", "3"}, "item.category_counts"
        )
        counts = [category_counts[str(category)] for category in range(4)]
        if (
            type(observed_n) is not int
            or type(missing_n) is not int
            or observed_n < 1
            or missing_n < 0
            or observed_n + missing_n != 6000
            or any(type(count) is not int or count < 1 for count in counts)
            or sum(counts) != observed_n
        ):
            raise ResearchSessionError(
                "profile_item_counts_invalid",
                "NHANES_DPQ v2 item support must match the calibration-only aggregate counts",
            )
        parsed_items.append(
            _parse_nhanes_dpq_item(
                value,
                expected_item=expected_item,
                source_categories=(0, 1, 2, 3),
                expected_fit_sha256=_NHANES_DPQ_FIT_SHA256,
            )
        )

    instance = object.__new__(cls)
    fields = {
        "profile_id": profile_id,
        "profile_type": PROFILE_STATUS,
        "instrument_id": "NHANES_P_DPQ_9ITEM_RESEARCH_CANDIDATE",
        "dimension": dimension,
        "source_population": source_population,
        "source_categories": (0, 1, 2, 3),
        "category_labels": tuple(labels_value),
        "category_labels_status": "verified_verbatim_against_official_NCHS_P_DPQ_codebook",
        "items": tuple(parsed_items),
        "file_sha256": file_sha256,
        "research_only": True,
        "publication_status": RESEARCH_PUBLICATION_STATUS,
        "psychological_interpretation_allowed": False,
        "human_curated": False,
        "source_metadata_json": _canonical_json(source),
        "rights_metadata_json": _canonical_json(rights),
        "model_metadata_json": _canonical_json(model),
        "scoring_metadata_json": _canonical_json(scoring),
        "provenance_metadata_json": _canonical_json(provenance),
        "raw_metadata_json": _canonical_json(document),
        "raw_profile_bytes": raw,
        "manifest_sha256": None,
    }
    for name, value in fields.items():
        object.__setattr__(instance, name, value)
    _verify_profile_probability_parity(instance, model)
    return instance


def _from_verified_promis_pediatric_document(
    cls: type[ResearchCATProfile],
    document: Mapping[str, object],
    file_sha256: str,
    raw: bytes,
    *,
    manifest_bytes: bytes | None,
    expected_manifest_sha256: str | None,
) -> ResearchCATProfile:
    # The profile and manifest hashes are pinned independently of their contents.
    # This adapter accepts this one reviewed research artifact, never arbitrary v3.
    if file_sha256 != _PROMIS_PEDIATRIC_PROFILE_SHA256:
        raise ResearchSessionError(
            "profile_identity_invalid",
            "PROMIS pediatric v3 bytes are not the independently pinned candidate",
        )
    manifest_sha256 = _validate_promis_manifest(
        manifest_bytes, expected_manifest_sha256
    )
    root_fields = {
        "schema",
        "profile_id",
        "profile_type",
        "instrument_id",
        "instrument_family",
        "dimension",
        "research_only",
        "publication_status",
        "human_curated",
        "psychological_interpretation_allowed",
        "loader_compatibility",
        "response_scale",
        "model",
        "scoring",
        "candidate_cat_config",
        "items",
        "source_data",
        "rights",
        "provenance",
        "not_approved_for",
    }
    if set(document) != root_fields:
        raise ResearchSessionError(
            "profile_v3_schema_invalid",
            "PROMIS pediatric v3 profile fields differ from its closed schema",
        )
    if (
        document.get("schema") != PROMIS_PEDIATRIC_PROFILE_SCHEMA
        or document.get("profile_id") != _PROMIS_PEDIATRIC_PROFILE_ID
        or document.get("profile_type") != "research_only_candidate"
        or document.get("instrument_id") != "PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET"
        or document.get("instrument_family") != "PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET"
        or document.get("dimension")
        != "Pediatric anxiety item-response research dimension; no psychological interpretation"
        or type(document.get("research_only")) is not bool
        or document.get("research_only") is not True
        or document.get("publication_status") != "not_approved"
        or type(document.get("human_curated")) is not bool
        or document.get("human_curated") is not False
        or type(document.get("psychological_interpretation_allowed")) is not bool
        or document.get("psychological_interpretation_allowed") is not False
    ):
        raise ResearchSessionError(
            "profile_status_invalid",
            "PROMIS pediatric candidate must remain unpublished, uncurated and noninterpretive",
        )

    scale = _require_v3_mapping(
        document.get("response_scale"),
        {
            "source_labels",
            "source_raw_codes",
            "published_v1_raw_codes",
            "engine_category_indices",
            "category_mapping",
            "missing_policy",
            "label_source",
        },
        "response_scale",
    )
    expected_mapping = [
        {
            "label": label,
            "source_raw_code": code,
            "published_v1_raw_code": code - 1,
            "engine_category_index": code - 1,
        }
        for code, label in enumerate(_PROMIS_PEDIATRIC_LABELS, start=1)
    ]
    if (
        scale.get("source_labels") != list(_PROMIS_PEDIATRIC_LABELS)
        or scale.get("source_raw_codes") != [1, 2, 3, 4, 5]
        or scale.get("published_v1_raw_codes") != [0, 1, 2, 3, 4]
        or scale.get("engine_category_indices") != [0, 1, 2, 3, 4]
        or scale.get("category_mapping") != expected_mapping
        or scale.get("missing_policy")
        != {
            "source_blank": "NA",
            "source_codebook_refused_minus1": "not distinguishable from system missing in source CSV; do not infer subtype",
        }
        or scale.get("label_source")
        != f"PROMIS GenPop Dataverse V2 codebook, SHA-256 {_PROMIS_PEDIATRIC_CODEBOOK_SHA256}"
    ):
        raise ResearchSessionError(
            "profile_categories_invalid",
            "PROMIS v3 categories must map source codes 1..5 to engine indices 0..4 exactly",
        )

    scoring = _require_v3_mapping(
        document.get("scoring"),
        {
            "response_label_to_engine_category_index",
            "reverse_key_transform",
            "person_scores_included",
            "theta_included",
            "clinical_cutoffs",
            "crisis_thresholds",
            "interpretation_allowed",
        },
        "scoring",
    )
    if (
        scoring.get("response_label_to_engine_category_index")
        != dict(zip(_PROMIS_PEDIATRIC_LABELS, range(5), strict=True))
        or scoring.get("reverse_key_transform") is not None
        or scoring.get("person_scores_included") is not False
        or type(scoring.get("person_scores_included")) is not bool
        or scoring.get("theta_included") is not False
        or type(scoring.get("theta_included")) is not bool
        or scoring.get("clinical_cutoffs") is not None
        or scoring.get("crisis_thresholds") is not None
        or scoring.get("interpretation_allowed") is not False
        or type(scoring.get("interpretation_allowed")) is not bool
    ):
        raise ResearchSessionError(
            "profile_scoring_invalid",
            "PROMIS v3 scoring must retain identity keying and prohibit person scores",
        )

    candidate = _require_v3_mapping(
        document.get("candidate_cat_config"),
        {"min_items", "max_items", "se_threshold", "status", "rationale"},
        "candidate_cat_config",
    )
    if (
        type(candidate.get("min_items")) is not int
        or candidate.get("min_items") != 8
        or type(candidate.get("max_items")) is not int
        or candidate.get("max_items") != 8
        or candidate.get("se_threshold") is not None
        or candidate.get("status")
        != "reference_full_subset_only_not_approved_research_configuration"
        or not _require_text(
            candidate.get("rationale"),
            "candidate_cat_config.rationale",
            max_length=1000,
        )
    ):
        raise ResearchSessionError(
            "profile_candidate_config_invalid",
            "PROMIS v3 candidate bounds must remain a fixed, unapproved eight-item reference",
        )

    model = _require_v3_mapping(
        document.get("model"),
        {
            "family",
            "parameter_origin",
            "parameter_version",
            "parameter_metric",
            "precision",
            "version_compatibility",
        },
        "model",
    )
    if (
        model.get("family") != "Samejima graded response model"
        or model.get("parameter_origin") != "published item bank parameters; no refit"
        or model.get("parameter_version") != "PROMIS Pediatric Anxiety v1.0"
        or model.get("parameter_metric")
        != "theta anchored to the North Carolina reference group with mean 0 and variance 1"
        or model.get("precision")
        != "a and b1..b4 retained at two decimal places as published; no precision inferred"
        or model.get("version_compatibility")
        != "HealthMeasures reports Pediatric Anxiety v1.0/v1.1/v2.0 calibrations identical; v1.1 8b and v2.0 8a item sets match, with different raw category scores. GenPop v3.0 is a different metric."
    ):
        raise ResearchSessionError(
            "profile_model_unsupported",
            "PROMIS v3 requires its published v1.0 GRM parameters and stated metric",
        )

    source_data = _require_v3_mapping(
        document.get("source_data"),
        {"observed_response_source", "published_parameters"},
        "source_data",
    )
    source = _require_v3_mapping(
        source_data.get("observed_response_source"),
        {
            "doi",
            "version",
            "license",
            "population",
            "response_only_csv_sha256",
            "rows_with_any_selected_response",
            "complete_on_8_selected_items",
            "partial_rows_retained",
        },
        "source_data.observed_response_source",
    )
    population = _require_text(
        source.get("population"), "source.population", max_length=512
    )
    if (
        source.get("doi") != "10.7910/DVN/UXH6DH"
        or source.get("version") != "2"
        or source.get("license") != "CC0-1.0 per official Dataverse record"
        or "child self-report age 8" not in population
        or "not school-based" not in population
        or source.get("response_only_csv_sha256") != _PROMIS_PEDIATRIC_RESPONSE_SHA256
        or type(source.get("rows_with_any_selected_response")) is not int
        or source.get("rows_with_any_selected_response") != 1005
        or type(source.get("complete_on_8_selected_items")) is not int
        or source.get("complete_on_8_selected_items") != 958
        or type(source.get("partial_rows_retained")) is not int
        or source.get("partial_rows_retained") != 47
    ):
        raise ResearchSessionError(
            "profile_source_invalid",
            "PROMIS v3 must preserve its public child self-report research population and counts",
        )
    published = _require_v3_mapping(
        source_data.get("published_parameters"),
        {"citation", "calibration_sample", "table"},
        "source_data.published_parameters",
    )
    if (
        "10.1007/s11136-010-9619-3" not in str(published.get("citation"))
        or "1,529 children ages 8" not in str(published.get("calibration_sample"))
        or published.get("table")
        != "Table 5; item-level a and four category thresholds."
    ):
        raise ResearchSessionError(
            "profile_source_invalid",
            "PROMIS v3 published parameter source must be the cited Table 5 pediatric calibration",
        )

    rights = _require_v3_mapping(
        document.get("rights"), {"dataset", "measure_text", "distribution"}, "rights"
    )
    if (
        not _require_text(rights.get("dataset"), "rights.dataset", max_length=500)
        or "CC0-1.0" not in rights["dataset"]
        or not _require_text(
            rights.get("measure_text"), "rights.measure_text", max_length=1000
        )
        or not _require_text(
            rights.get("distribution"), "rights.distribution", max_length=500
        )
        or "no product-bank import" not in rights["distribution"]
        or "school deployment" not in rights["distribution"]
    ):
        raise ResearchSessionError(
            "profile_rights_invalid",
            "PROMIS v3 must retain the research-only rights and distribution boundary",
        )

    provenance = _require_v3_mapping(
        document.get("provenance"),
        {
            "response_label_csv_sha256",
            "numeric_1_5_csv_sha256",
            "complete_observed_800_csv_sha256",
            "item_map_sha256",
            "parameter_crosswalk_sha256",
            "transform_script_sha256",
            "source_sha256_scope",
            "numeric_transform",
            "coverage_sample",
        },
        "provenance",
    )
    for key, digest in (
        ("response_label_csv_sha256", _PROMIS_PEDIATRIC_RESPONSE_SHA256),
        ("numeric_1_5_csv_sha256", _PROMIS_PEDIATRIC_NUMERIC_SHA256),
        ("complete_observed_800_csv_sha256", _PROMIS_PEDIATRIC_COMPLETE800_SHA256),
        ("item_map_sha256", _PROMIS_PEDIATRIC_ITEM_MAP_SHA256),
        ("parameter_crosswalk_sha256", _PROMIS_PEDIATRIC_CROSSWALK_SHA256),
        ("transform_script_sha256", _PROMIS_PEDIATRIC_BUILD_SHA256),
    ):
        if provenance.get(key) != digest:
            raise ResearchSessionError(
                "profile_provenance_invalid",
                "PROMIS v3 provenance hashes differ from the pinned research artifacts",
            )
    coverage = _require_v3_mapping(
        provenance.get("coverage_sample"),
        {
            "name",
            "seed",
            "algorithm",
            "python_implementation",
            "python_version",
            "complete_source_rows",
            "selected_rows",
            "complete_rows_not_selected",
            "partial_rows_retained_in_full_numeric_matrix",
            "calibration_or_evaluation_split",
        },
        "provenance.coverage_sample",
    )
    if (
        provenance.get("source_sha256_scope")
        != "file-level hashes only; no per-person hashes or row identifiers stored"
        or provenance.get("numeric_transform")
        != "exact English label to codebook raw values 1..5; blank to literal NA; no reverse coding or imputation"
        or coverage.get("name") != "COMPLETE_OBSERVED800"
        or type(coverage.get("seed")) is not int
        or coverage.get("seed") != 2026101403
        or "without replacement" not in str(coverage.get("algorithm"))
        or coverage.get("python_implementation") != "CPython"
        or coverage.get("python_version") != "3.14.6"
        or type(coverage.get("complete_source_rows")) is not int
        or coverage.get("complete_source_rows") != 958
        or type(coverage.get("selected_rows")) is not int
        or coverage.get("selected_rows") != 800
        or type(coverage.get("complete_rows_not_selected")) is not int
        or coverage.get("complete_rows_not_selected") != 158
        or type(coverage.get("partial_rows_retained_in_full_numeric_matrix")) is not int
        or coverage.get("partial_rows_retained_in_full_numeric_matrix") != 47
        or coverage.get("calibration_or_evaluation_split")
        != "none; published item parameters are used as references and no local model is fit"
    ):
        raise ResearchSessionError(
            "profile_provenance_invalid",
            "PROMIS v3 coverage provenance is not the declared response-only subset",
        )

    raw_items = document.get("items")
    if type(raw_items) is not list or len(raw_items) != len(_PROMIS_PEDIATRIC_ITEMS):
        raise ResearchSessionError(
            "profile_items_invalid", "PROMIS v3 must contain exactly eight mapped items"
        )
    parsed: list[ResearchCATItem] = []
    item_fields = {
        "item_id",
        "source_column",
        "stem",
        "key_direction",
        "parameters",
        "source_locator",
        "parameter_locator",
    }
    for index, (expected, value) in enumerate(
        zip(_PROMIS_PEDIATRIC_ITEMS, raw_items, strict=True)
    ):
        item_id, stem, expected_a, expected_thresholds, table_stem = expected
        value = _require_v3_mapping(value, item_fields, f"items[{index}]")
        parameters = _require_v3_mapping(
            value.get("parameters"),
            {
                "model",
                "a",
                "thresholds",
                "parameter_precision_decimal_places",
                "precision_note",
            },
            f"items[{index}].parameters",
        )
        source_locator = _require_v3_mapping(
            value.get("source_locator"),
            {"dataset_doi", "dataset_version", "codebook_variable", "codebook_sha256"},
            f"items[{index}].source_locator",
        )
        parameter_locator = _require_v3_mapping(
            value.get("parameter_locator"),
            {
                "citation_doi",
                "paper_version",
                "table",
                "row_stem",
                "metric",
                "crosswalk_sha256",
            },
            f"items[{index}].parameter_locator",
        )
        a = parameters.get("a")
        thresholds = parameters.get("thresholds")
        if (
            value.get("item_id") != item_id
            or value.get("source_column") != item_id
            or value.get("stem") != stem
            or value.get("key_direction")
            != "direct_positive_symptom_no_reverse_transform"
            or parameters.get("model") != "Samejima graded response model"
            or isinstance(a, bool)
            or not isinstance(a, (int, float))
            or not math.isfinite(float(a))
            or float(a) <= 0
            or type(thresholds) is not list
            or len(thresholds) != 4
            or any(
                type(v) not in (int, float) or not math.isfinite(float(v))
                for v in thresholds
            )
            or type(parameters.get("parameter_precision_decimal_places")) is not int
            or parameters.get("parameter_precision_decimal_places") != 2
            or parameters.get("precision_note")
            != "transcribed at the two-decimal precision published in Irwin et al. Table 5; no additional precision inferred"
            or float(a) != expected_a
            or tuple(float(v) for v in thresholds) != expected_thresholds
            or any(left >= right for left, right in pairwise(thresholds))
            or source_locator.get("dataset_doi") != "10.7910/DVN/UXH6DH"
            or source_locator.get("dataset_version") != "2"
            or source_locator.get("codebook_variable") != item_id
            or source_locator.get("codebook_sha256")
            != _PROMIS_PEDIATRIC_CODEBOOK_SHA256
            or parameter_locator.get("citation_doi") != "10.1007/s11136-010-9619-3"
            or parameter_locator.get("paper_version")
            != "PROMIS Pediatric Anxiety v1.0 item bank calibration"
            or parameter_locator.get("table") != "Table 5, Anxiety item parameters"
            or parameter_locator.get("row_stem") != table_stem
            or parameter_locator.get("metric")
            != "theta metric anchored to NC reference group N(0,1)"
            or parameter_locator.get("crosswalk_sha256")
            != _PROMIS_PEDIATRIC_CROSSWALK_SHA256
        ):
            raise ResearchSessionError(
                "profile_item_mapping_invalid",
                "PROMIS v3 item text, source mapping or published parameter differs from its pinned crosswalk",
            )
        parsed.append(
            ResearchCATItem(
                item_id=item_id,
                qid=item_id,
                item_code=item_id,
                stem=stem,
                source_locator=_canonical_json(source_locator),
                fit_locator=_canonical_json(parameter_locator),
                key_direction="positive",
                a=float(a),
                thresholds=tuple(float(v) for v in thresholds),
            )
        )

    exclusions = document.get("not_approved_for")
    required_exclusions = {
        "psychological interpretation or clinical decisions",
        "school administration or pilot use",
        "production CAT item bank or published measure",
        "Chinese translation or cross-cultural validity claim",
        "diagnosis, risk thresholds, crisis classification, or cutoffs",
    }
    if (
        type(exclusions) is not list
        or any(type(value) is not str for value in exclusions)
        or not required_exclusions.issubset(set(exclusions))
    ):
        raise ResearchSessionError(
            "profile_status_invalid",
            "PROMIS v3 must retain all nonclinical, non-school and non-publication exclusions",
        )

    fields = {
        "profile_id": _PROMIS_PEDIATRIC_PROFILE_ID,
        "profile_type": PROFILE_STATUS,
        "instrument_id": "PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET",
        "dimension": "Pediatric anxiety item-response research dimension; no psychological interpretation",
        "source_population": population,
        "source_categories": (1, 2, 3, 4, 5),
        "category_labels": _PROMIS_PEDIATRIC_LABELS,
        "category_labels_status": "verified_verbatim_against_PROMIS_GenPop_Dataverse_V2_codebook",
        "items": tuple(parsed),
        "file_sha256": file_sha256,
        "research_only": True,
        "publication_status": "not_approved",
        "psychological_interpretation_allowed": False,
        "human_curated": False,
        "source_metadata_json": _canonical_json(source_data),
        "rights_metadata_json": _canonical_json(rights),
        "model_metadata_json": _canonical_json(model),
        "scoring_metadata_json": _canonical_json(scoring),
        "provenance_metadata_json": _canonical_json(provenance),
        "raw_metadata_json": _canonical_json(document),
        "raw_profile_bytes": raw,
        "manifest_sha256": manifest_sha256,
    }
    instance = object.__new__(cls)
    for name, value in fields.items():
        object.__setattr__(instance, name, value)
    _verify_profile_probability_parity(instance, model)
    return instance


def _validate_promis_manifest(
    manifest_bytes: bytes | None, expected_manifest_sha256: str | None
) -> str:
    if (
        not isinstance(manifest_bytes, bytes)
        or type(expected_manifest_sha256) is not str
        or expected_manifest_sha256 != _PROMIS_PEDIATRIC_MANIFEST_SHA256
        or not _SHA256.fullmatch(expected_manifest_sha256)
        or hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest_sha256
    ):
        raise ResearchSessionError(
            "profile_manifest_hash_invalid",
            "PROMIS v3 requires independently pinned, hash-matched manifest bytes",
        )
    try:
        manifest = json.loads(
            manifest_bytes.decode("utf-8-sig"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_nonfinite_json_constant,
        )
    except ResearchSessionError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResearchSessionError(
            "profile_manifest_invalid", "PROMIS manifest is not valid UTF-8 JSON"
        ) from exc
    if not isinstance(manifest, Mapping) or set(manifest) != {
        "artifact_status",
        "profile_sha256",
        "numeric_response_csv",
        "complete_observed_800",
        "profile_json_sha256",
        "build_script_sha256",
        "source_response_only_sha256",
        "parameter_crosswalk_sha256",
        "item_map_sha256",
        "no_person_response_hashes_or_identifiers",
        "no_scores_or_person_parameters",
    }:
        raise ResearchSessionError(
            "profile_manifest_invalid",
            "PROMIS manifest fields differ from the closed schema",
        )
    numeric = _require_v3_mapping(
        manifest.get("numeric_response_csv"),
        {
            "path",
            "sha256",
            "rows",
            "columns",
            "partial_rows_NA_retained",
            "category_counts",
        },
        "manifest.numeric_response_csv",
    )
    complete = _require_v3_mapping(
        manifest.get("complete_observed_800"),
        {
            "path",
            "sha256",
            "rows",
            "complete_source_rows",
            "not_selected_complete_rows",
            "seed",
            "sampling",
            "python_implementation",
            "python_version",
        },
        "manifest.complete_observed_800",
    )
    _require_v3_mapping(
        numeric.get("category_counts"),
        {item[0] for item in _PROMIS_PEDIATRIC_ITEMS},
        "manifest.numeric_response_csv.category_counts",
    )
    if (
        manifest.get("artifact_status") != "research_staging_only"
        or manifest.get("profile_sha256") != _PROMIS_PEDIATRIC_PROFILE_SHA256
        or manifest.get("profile_json_sha256") != _PROMIS_PEDIATRIC_PROFILE_SHA256
        or manifest.get("build_script_sha256") != _PROMIS_PEDIATRIC_BUILD_SHA256
        or manifest.get("source_response_only_sha256")
        != _PROMIS_PEDIATRIC_RESPONSE_SHA256
        or manifest.get("parameter_crosswalk_sha256")
        != _PROMIS_PEDIATRIC_CROSSWALK_SHA256
        or manifest.get("item_map_sha256") != _PROMIS_PEDIATRIC_ITEM_MAP_SHA256
        or manifest.get("no_person_response_hashes_or_identifiers") is not True
        or type(manifest.get("no_person_response_hashes_or_identifiers")) is not bool
        or manifest.get("no_scores_or_person_parameters") is not True
        or type(manifest.get("no_scores_or_person_parameters")) is not bool
        or numeric.get("path") != "responses_numeric_1_5.csv"
        or numeric.get("sha256") != _PROMIS_PEDIATRIC_NUMERIC_SHA256
        or type(numeric.get("rows")) is not int
        or numeric.get("rows") != 1005
        or numeric.get("columns") != [item[0] for item in _PROMIS_PEDIATRIC_ITEMS]
        or type(numeric.get("partial_rows_NA_retained")) is not int
        or numeric.get("partial_rows_NA_retained") != 47
        or complete.get("path") != "complete_observed_800.csv"
        or complete.get("sha256") != _PROMIS_PEDIATRIC_COMPLETE800_SHA256
        or type(complete.get("rows")) is not int
        or complete.get("rows") != 800
        or type(complete.get("complete_source_rows")) is not int
        or complete.get("complete_source_rows") != 958
        or type(complete.get("not_selected_complete_rows")) is not int
        or complete.get("not_selected_complete_rows") != 158
        or type(complete.get("seed")) is not int
        or complete.get("seed") != 2026101403
        or complete.get("python_implementation") != "CPython"
        or complete.get("python_version") != "3.14.6"
        or not _require_text(
            complete.get("sampling"),
            "manifest.complete_observed_800.sampling",
            max_length=500,
        )
    ):
        raise ResearchSessionError(
            "profile_manifest_invalid",
            "PROMIS manifest does not match its source, transform, and coverage artifacts",
        )
    return expected_manifest_sha256


def _require_v3_mapping(
    value: object, fields: set[str], name: str
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ResearchSessionError(
            "profile_v3_schema_invalid",
            f"PROMIS pediatric v3 {name} fields differ from the closed schema",
        )
    return value


def _require_v2_mapping(
    value: object, fields: set[str], name: str
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ResearchSessionError(
            "profile_v2_schema_invalid",
            f"NHANES_DPQ v2 {name} fields differ from its closed schema",
        )
    return value


def _parse_nhanes_dpq_item(
    value: Mapping[str, object],
    *,
    expected_item: str,
    source_categories: tuple[int, ...],
    expected_fit_sha256: str,
) -> ResearchCATItem:
    a = value.get("a")
    raw_thresholds = value.get("thresholds")
    if (
        isinstance(a, bool)
        or not isinstance(a, (int, float))
        or not math.isfinite(float(a))
        or float(a) <= 0
        or type(raw_thresholds) is not list
        or len(raw_thresholds) != len(source_categories) - 1
        or any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in raw_thresholds
        )
    ):
        raise ResearchSessionError(
            "profile_item_parameters_invalid",
            "NHANES_DPQ v2 GRM parameters require finite a>0 and three thresholds",
        )
    thresholds = tuple(float(value) for value in raw_thresholds)
    if any(not math.isfinite(value) for value in thresholds) or any(
        left >= right for left, right in pairwise(thresholds)
    ):
        raise ResearchSessionError(
            "profile_item_parameters_invalid",
            "NHANES_DPQ v2 thresholds must be finite and strictly increasing",
        )
    locator = value["fit_locator"]
    if (
        not isinstance(locator, Mapping)
        or locator.get("sha256") != expected_fit_sha256
        or locator.get("parameter_key") != expected_item
    ):
        raise ResearchSessionError(
            "profile_fit_locator_invalid",
            "NHANES_DPQ v2 fit parameters are not hash-bound to their variable",
        )
    return ResearchCATItem(
        item_id=expected_item,
        qid=expected_item,
        item_code=expected_item,
        stem=_require_text(
            value.get("stem"), f"item.{expected_item}.stem", max_length=2000
        ),
        source_locator=_canonical_json(value["source_locator"]),
        fit_locator=_canonical_json(locator),
        key_direction="direct",
        a=float(a),
        thresholds=thresholds,
    )


def _validate_model_metadata(model: Mapping[str, object]) -> None:
    if (
        model.get("package") != "mirt"
        or model.get("itemtype") != "graded"
        or type(model.get("factors")) is not int
        or model.get("factors") != 1
        or type(model.get("converged")) is not bool
        or model.get("converged") is not True
        or model.get("latent_distribution") != "Gaussian N(0,1)"
    ):
        raise ResearchSessionError(
            "profile_model_unsupported",
            "profile must contain a converged one-factor graded mirt fit",
        )
    _require_ref(model.get("version"), "model.version")
    for key in ("fit_sha256", "calibration_sha256"):
        if not _SHA256.fullmatch(str(model.get(key) or "")):
            raise ResearchSessionError(
                "profile_model_provenance_invalid",
                f"model.{key} must be a lowercase SHA-256",
            )


def _validate_scoring_metadata(
    scoring: Mapping[str, object], categories: tuple[int, ...]
) -> None:
    if categories == (1, 2, 3, 4, 5, 6):
        if (
            scoring.get("positive_key_transform") != "identity"
            or scoring.get("reverse_key_transform") != "7 - response"
            or scoring.get("transform_before_category_index_conversion") is not True
            or scoring.get("no_person_scores_or_norms_included") is not True
            or not isinstance(scoring.get("parameter_orientation"), str)
            or not scoring["parameter_orientation"].strip()
        ):
            raise ResearchSessionError(
                "profile_scoring_invalid",
                "six-category profile scoring does not match the keyed mirt metric",
            )
    elif categories == (0, 1, 2, 3) and (
        scoring.get("positive_key_transform") != "identity"
        or scoring.get("reverse_key_transform") != "3 - response"
    ):
        raise ResearchSessionError(
            "profile_scoring_invalid",
            "four-category profile scoring must preserve its explicit ordinal key",
        )


def _validate_rights_metadata(rights: Mapping[str, object]) -> None:
    items = rights.get("items")
    dataset = rights.get("dataset")
    profile = rights.get("profile")
    if not all(isinstance(value, Mapping) for value in (items, dataset, profile)):
        raise ResearchSessionError(
            "profile_rights_invalid",
            "rights must declare item, dataset, and profile provenance",
        )
    if (
        not _require_text(items.get("status"), "rights.items.status", max_length=64)
        or not _require_text(
            dataset.get("license"), "rights.dataset.license", max_length=128
        )
        or profile.get("status") != "research_only_candidate"
        or type(profile.get("operational_release")) is not bool
        or profile.get("operational_release") is not False
    ):
        raise ResearchSessionError(
            "profile_rights_invalid",
            "profile must remain non-operational and carry explicit rights metadata",
        )


def _validate_config(config: CATConfig, item_count: int) -> None:
    if not isinstance(config, CATConfig):
        raise ResearchSessionError(
            "config_invalid", "an explicit CATConfig is required"
        )
    try:
        config.validate()
    except Exception as exc:
        raise ResearchSessionError(
            "config_invalid", "CATConfig validation failed"
        ) from exc
    if (
        config.model != "GRM"
        or config.estimator != "EAP"
        or config.selection_method != "MFI"
        or config.initial_theta != 0.0
        or config.prior_mean != 0.0
        or config.prior_sd != 1.0
        or config.optimization_interval != (-4.0, 4.0)
        or config.exposure_control != "none"
        or config.content_balancing != "none"
        or type(config.seed) is not int
        or config.seed < 0
        or config.max_items > item_count
        or config.min_items > item_count
    ):
        raise ResearchSessionError(
            "config_unsupported",
            "research session requires GRM/EAP/MFI, N(0,1), interval [-4,4], no balancing, and a bounded item count",
        )


def _make_engine(
    profile: ResearchCATProfile, config: CATConfig, session_id: str
) -> tuple[dict[str, object], object, dict[str, ResearchCATItem]]:
    engine_items: list[object] = []
    item_lookup = {item.item_id: item for item in profile.items}
    engine_by_id: dict[str, object] = {}
    for index, item in enumerate(profile.items):
        engine_item = adt.TestItem()
        engine_item.id = index
        engine_item.a = item.a
        engine_item.b = list(item.thresholds)
        engine_item.additional_properties = {"research_item_id": item.item_id}
        engine_items.append(engine_item)
        engine_by_id[item.item_id] = engine_item
    engine = adt.TestAssembler(
        item_pool=adt.ItemPool(engine_items),
        simulation_id=session_id,
        participant_id=session_id,
        ability_estimator=adt.ExpectedAPosteriori,
        estimator_args={
            "prior": adt.NormalPrior(config.prior_mean, config.prior_sd),
            "optimization_interval": config.optimization_interval,
            "model": "GRM",
        },
        item_selector=adt.maximum_information_criterion,
        item_selector_args={"model": "GRM"},
        model_type="GRM",
        initial_ability_level=config.initial_theta,
        simulation=False,
        debug=False,
    )
    owned_items = {
        str(item.additional_properties["research_item_id"]): item
        for item in engine.item_pool.test_items
    }
    return owned_items, engine, item_lookup


def _keyed_score(
    raw_value: int, direction: str, source_categories: tuple[int, ...]
) -> int:
    if type(raw_value) is not int or raw_value not in source_categories:
        raise ResearchSessionError(
            "response_category_invalid",
            "response is outside the profile source categories",
        )
    source_index = source_categories.index(raw_value)
    if direction == "reverse":
        source_index = len(source_categories) - 1 - source_index
    return source_index


def _verify_profile_probability_parity(
    profile: ResearchCATProfile, model: Mapping[str, object]
) -> None:
    if importlib.metadata.version("adaptivetesting") != "1.2.1":
        raise ResearchSessionError(
            "adaptivetesting_version_mismatch",
            "research parity is verified only for adaptivetesting 1.2.1",
        )
    if len(profile.source_categories) == 6:
        from .empirical_cat_replay import (
            ResearchDomain,
            ResearchItem,
            _verify_probability_parity,
        )

        domain = ResearchDomain(
            name=profile.dimension,
            items=tuple(
                ResearchItem(
                    qid=item.qid,
                    key_direction=item.key_direction,
                    a=item.a,
                    thresholds=item.thresholds,
                )
                for item in profile.items
            ),
            fit_sha256=str(model["fit_sha256"]),
            fit_model=dict(model),
            fit_iterations=int(model.get("iterations", 0)),
            fit_warnings=tuple(str(value) for value in model.get("warnings", [])),
        )
        evidence = _verify_probability_parity((domain,))
        if (
            evidence.get("status") != "source_and_public_eap_likelihood_parity_passed"
            or evidence.get("source_category_count") != 6
            or evidence.get("slope_scale") != 1.0
        ):
            raise ResearchSessionError(
                "profile_parity_failed",
                "six-category profile did not pass the existing GRM/EAP parity gate",
            )
        return
    _verify_generic_probability_parity(profile)


def _verify_generic_probability_parity(profile: ResearchCATProfile) -> None:
    """Same mirt logistic link/public EAP comparison for four-category profiles."""

    package_root = Path(adt.__file__).resolve().parent
    grm_path = (
        package_root / "math" / "estimators" / "__functions" / "__poly" / "__grm.py"
    )
    eap_path = Path(inspect.getsourcefile(adt.ExpectedAPosteriori) or "")
    if not grm_path.is_file() or not eap_path.is_file():
        raise ResearchSessionError(
            "adaptivetesting_source_missing",
            "pinned GRM/EAP source is unavailable for parity verification",
        )
    grm_source = re_sub_whitespace(grm_path.read_text(encoding="utf-8"))
    if (
        "prob_k = p_ge_k - p_ge_k_plus_1" not in grm_source
        or "GRM" not in eap_path.read_text(encoding="utf-8")
    ):
        raise ResearchSessionError(
            "profile_parity_source_mismatch",
            "installed GRM/EAP source differs from the verified ordinal logistic link",
        )
    theta_grid = tuple(-4.0 + index * 0.5 for index in range(17))
    for item in profile.items:
        for theta in theta_grid:
            probabilities = _category_probabilities(theta, item)
            if (
                len(probabilities) != len(profile.source_categories)
                or any(
                    not math.isfinite(value) or value < -1e-12 or value > 1.0 + 1e-12
                    for value in probabilities
                )
                or abs(sum(probabilities) - 1.0) > 1e-12
            ):
                raise ResearchSessionError(
                    "profile_probability_normalization_failed",
                    "GRM probabilities do not sum to one",
                )
    for item_index, item in enumerate(profile.items):
        engine_item = adt.TestItem()
        engine_item.id = item_index
        engine_item.a = item.a
        engine_item.b = list(item.thresholds)
        for score in range(len(profile.source_categories)):
            try:
                estimator = adt.ExpectedAPosteriori(
                    [score],
                    [engine_item],
                    prior=adt.NormalPrior(0.0, 1.0),
                    optimization_interval=(-4.0, 4.0),
                    model="GRM",
                )
                public_mean = float(estimator.get_estimation())
                public_se = float(estimator.get_standard_error(public_mean))
            except Exception as exc:
                raise ResearchSessionError(
                    "profile_public_eap_failed", "public EAP parity check failed"
                ) from exc
            local_mean, local_se = _manual_eap_moments(
                item, score, len(profile.source_categories)
            )
            if abs(public_mean - local_mean) > 1e-3 or abs(public_se - local_se) > 1e-3:
                raise ResearchSessionError(
                    "profile_public_eap_mismatch",
                    "public EAP differs from the declared GRM likelihood",
                )


def _category_probabilities(theta: float, item: ResearchCATItem) -> tuple[float, ...]:
    cumulative = (
        (1.0,)
        + tuple(_logistic(item.a * (theta - value)) for value in item.thresholds)
        + (0.0,)
    )
    return tuple(
        cumulative[index] - cumulative[index + 1]
        for index in range(len(cumulative) - 1)
    )


def _manual_eap_moments(
    item: ResearchCATItem, response_score: int, category_count: int
) -> tuple[float, float]:
    numerator = denominator = second_moment = 0.0
    steps = 4000
    for index in range(steps + 1):
        theta = -4.0 + 8.0 * index / steps
        probability = _category_probabilities(theta, item)[response_score]
        weight = math.exp(-0.5 * theta * theta) * probability
        if index in {0, steps}:
            weight *= 0.5
        denominator += weight
        numerator += theta * weight
        second_moment += theta * theta * weight
    if not math.isfinite(denominator) or denominator <= 0:
        raise ResearchSessionError(
            "profile_manual_eap_failed", "manual GRM likelihood has zero posterior mass"
        )
    mean = numerator / denominator
    variance = max(0.0, second_moment / denominator - mean * mean)
    return mean, math.sqrt(variance)


def _logistic(value: float) -> float:
    if value >= 0.0:
        inverse = math.exp(-value)
        return 1.0 / (1.0 + inverse)
    exponential = math.exp(value)
    return exponential / (1.0 + exponential)


def re_sub_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value)


def _config_sha256(config: CATConfig) -> str:
    return hashlib.sha256(_canonical_json(config.to_dict()).encode("utf-8")).hexdigest()


def _verify_snapshot(
    snapshot: Mapping[str, object], authenticator: SnapshotAuthenticator
) -> Mapping[str, object]:
    if not _is_authenticator(authenticator):
        raise ResearchSessionError(
            "snapshot_authenticator_required",
            "a trusted snapshot authenticator is required",
        )
    if not isinstance(snapshot, Mapping) or set(snapshot) != {
        "payload",
        "payload_sha256",
        "signature",
    }:
        raise ResearchSessionError(
            "snapshot_schema_invalid", "snapshot envelope fields are invalid"
        )
    payload = snapshot.get("payload")
    signature = snapshot.get("signature")
    payload_sha256 = snapshot.get("payload_sha256")
    if (
        not isinstance(payload, Mapping)
        or type(signature) is not str
        or not _SAFE_SIGNATURE.fullmatch(signature)
        or type(payload_sha256) is not str
        or not _SHA256.fullmatch(payload_sha256)
    ):
        raise ResearchSessionError(
            "snapshot_schema_invalid",
            "snapshot payload, digest and signature are required",
        )
    encoded = _canonical_json(payload).encode("utf-8")
    actual_sha256 = hashlib.sha256(encoded).hexdigest()
    if not hmac.compare_digest(actual_sha256, payload_sha256):
        raise ResearchSessionError(
            "snapshot_digest_mismatch", "snapshot payload does not match its digest"
        )
    try:
        verified = authenticator.verify(encoded, signature)
    except Exception as exc:
        raise ResearchSessionError(
            "snapshot_authentication_failed", "snapshot authentication failed"
        ) from exc
    if verified is not True:
        raise ResearchSessionError(
            "snapshot_authentication_failed", "snapshot authentication failed"
        )
    expected_fields = {
        "schema",
        "session_id",
        "profile_id",
        "profile_sha256",
        "config_version",
        "config_sha256",
        "step",
        "status",
        "stop_reason",
        "pending_item_id",
        "answers",
    }
    if set(payload) != expected_fields or payload.get("schema") != SNAPSHOT_SCHEMA:
        raise ResearchSessionError(
            "snapshot_payload_invalid",
            "snapshot payload does not match the research state schema",
        )
    return payload


def _is_authenticator(value: object) -> bool:
    return callable(getattr(value, "sign", None)) and callable(
        getattr(value, "verify", None)
    )


def _require_ref(value: object, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF.fullmatch(value):
        raise ResearchSessionError(
            "reference_invalid", f"{name} must be a bounded ASCII reference"
        )
    return value


def _require_text(value: object, name: str, *, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise ResearchSessionError(
            "text_invalid", f"{name} must be non-empty bounded text"
        )
    return value.strip()


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ResearchSessionError(
            "json_canonicalization_failed", "profile or state is not canonical JSON"
        ) from exc


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ResearchSessionError(
                "profile_json_duplicate_key",
                "research profile JSON contains a duplicate object key",
            )
        result[key] = value
    return result


def _reject_nonfinite_json_constant(value: str) -> object:
    raise ResearchSessionError(
        "profile_json_nonfinite_number",
        "research profile JSON contains a non-finite number",
    )
