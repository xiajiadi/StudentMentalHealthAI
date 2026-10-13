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
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Protocol

import adaptivetesting as adt

from cat_engine.domain.config import CATConfig

PROFILE_SCHEMA = "psynova.research-profile.v1"
SNAPSHOT_SCHEMA = "psynova.research-cat-snapshot.v1"
RESEARCH_PUBLICATION_STATUS = "not_approved_for_publication_or_operational_use"
PROFILE_STATUS = "CAT_RESEARCH_PROFILE_CANDIDATE"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SAFE_SIGNATURE = re.compile(r"^[!-~]{1,4096}$")
_ALLOWED_CATEGORY_SCALES = ((1, 2, 3, 4, 5, 6), (0, 1, 2, 3))
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
    source_metadata_json: str
    rights_metadata_json: str
    model_metadata_json: str
    scoring_metadata_json: str
    provenance_metadata_json: str
    raw_metadata_json: str

    @classmethod
    def load(cls, path: Path, *, expected_file_sha256: str) -> ResearchCATProfile:
        """Load a profile only when its exact file bytes match a trusted digest."""

        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ResearchSessionError(
                "profile_unreadable", "research profile file could not be read"
            ) from exc
        return cls.from_bytes(raw, expected_file_sha256=expected_file_sha256)

    @classmethod
    def from_bytes(cls, raw: bytes, *, expected_file_sha256: str) -> ResearchCATProfile:
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
        return cls._from_verified_document(document, actual_sha256)

    @classmethod
    def _from_verified_document(
        cls, document: Mapping[str, object], file_sha256: str
    ) -> ResearchCATProfile:
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
            if abs(sum(probabilities) - 1.0) > 1e-12:
                raise ResearchSessionError(
                    "profile_probability_normalization_failed",
                    "GRM probabilities do not sum to one",
                )
    item = profile.items[len(profile.items) // 2]
    engine_item = adt.TestItem()
    engine_item.id = 0
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
