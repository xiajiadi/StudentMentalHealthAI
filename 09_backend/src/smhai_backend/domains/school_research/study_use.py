"""Server-configured, time-bounded scope for isolated historical research replay.

This record describes a trusted local study-use declaration. It is not an
external rights grant, ethics approval, psychometric approval, or official CAT
license, and it is never parsed from an HTTP request.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

_SCHEMA = "psynova.research-study-use.v1"
_MAX_POLICY_BYTES = 64 * 1024
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_UTC_TIMESTAMP_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|\+00:00)\Z"
)
_APPROVAL_FIELDS = frozenset({"clinical_approval", "ethics_approval", "psychometric_approval"})
_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema",
        "study_ref",
        "school_id",
        "institution",
        "use_scope",
        "noncommercial",
        "historical_replay_only",
        "english_unchanged",
        "starts_at",
        "ends_at",
        "profiles",
        "rights_basis",
        "rights_source_urls",
        "recorded_by",
        "recorded_at",
        "operator_declaration",
        *_APPROVAL_FIELDS,
    }
)
_PROFILE_FIELDS = frozenset(
    {
        "profile_ref",
        "profile_sha256",
        "manifest_sha256",
        "published_crosswalk_sha256",
    }
)
_REPARSE_POINT = 0x400
_UTC = UTC


class ResearchStudyUseError(ValueError):
    """Stable, non-content-bearing research-use validation error."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
            code = "study_use_invalid"
        self.code = code
        super().__init__(f"research study-use validation failed: {code}")


@dataclass(frozen=True, slots=True)
class ResearchStudyProfilePin:
    """A profile identity pinned by the trusted study-use record."""

    profile_ref: str
    profile_sha256: str
    manifest_sha256: str
    published_crosswalk_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.profile_ref) is not str
            or not _REF_RE.fullmatch(self.profile_ref)
            or any(
                type(digest) is not str or not _SHA256_RE.fullmatch(digest)
                for digest in (
                    self.profile_sha256,
                    self.manifest_sha256,
                    self.published_crosswalk_sha256,
                )
            )
        ):
            raise ResearchStudyUseError("profile_pins_invalid")


@dataclass(frozen=True, slots=True)
class ResearchStudyUsePolicy:
    """Immutable, server-validated scope for isolated historical replay only."""

    study_ref: str
    school_id: int
    institution: str
    use_scope: str
    noncommercial: bool
    historical_replay_only: bool
    english_unchanged: bool
    starts_at: datetime
    ends_at: datetime
    profiles: tuple[ResearchStudyProfilePin, ...]
    rights_basis: str
    rights_source_urls: tuple[str, ...]
    recorded_by: str
    recorded_at: datetime
    operator_declaration: str
    source_rights_verified: bool
    clinical_approval: bool = False
    ethics_approval: bool = False
    psychometric_approval: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.study_ref) is not str
            or not _REF_RE.fullmatch(self.study_ref)
            or type(self.school_id) is not int
            or self.school_id <= 0
            or type(self.institution) is not str
            or not 1 <= len(self.institution.strip()) <= 300
            or self.use_scope != "ISOLATED_HISTORICAL_REPLAY"
            or self.noncommercial is not True
            or self.historical_replay_only is not True
            or self.english_unchanged is not True
            or type(self.source_rights_verified) is not bool
            or self.source_rights_verified is not True
            or any(getattr(self, name) is not False for name in _APPROVAL_FIELDS)
            or not isinstance(self.profiles, tuple)
            or not 1 <= len(self.profiles) <= 32
            or not all(isinstance(pin, ResearchStudyProfilePin) for pin in self.profiles)
            or len({pin.profile_ref for pin in self.profiles}) != len(self.profiles)
            or not isinstance(self.rights_source_urls, tuple)
            or not 1 <= len(self.rights_source_urls) <= 32
            or not all(_valid_source_url(url) for url in self.rights_source_urls)
            or len(set(self.rights_source_urls)) != len(self.rights_source_urls)
            or type(self.rights_basis) is not str
            or not 1 <= len(self.rights_basis.strip()) <= 4000
            or type(self.recorded_by) is not str
            or not 1 <= len(self.recorded_by.strip()) <= 200
            or type(self.operator_declaration) is not str
            or not 1 <= len(self.operator_declaration.strip()) <= 4000
        ):
            raise ResearchStudyUseError("policy_schema_invalid")
        starts_at = _validated_utc_datetime(self.starts_at, code="study_window_invalid")
        ends_at = _validated_utc_datetime(self.ends_at, code="study_window_invalid")
        recorded_at = _validated_utc_datetime(self.recorded_at, code="study_record_invalid")
        if starts_at > ends_at or recorded_at > ends_at:
            raise ResearchStudyUseError("study_window_invalid")
        object.__setattr__(self, "starts_at", starts_at)
        object.__setattr__(self, "ends_at", ends_at)
        object.__setattr__(self, "recorded_at", recorded_at)

    def require_scope(
        self,
        *,
        school_id: int,
        profile_ref: str,
        profile_sha256: str,
        manifest_sha256: str,
        at: datetime,
        task_opens_at: datetime | None = None,
        task_due_at: datetime | None = None,
    ) -> ResearchStudyProfilePin:
        """Require exact study, profile pins, and a fully contained task window."""

        instant = _validated_utc_datetime(at, code="scope_denied")
        if (
            type(school_id) is not int
            or school_id != self.school_id
            or self.use_scope != "ISOLATED_HISTORICAL_REPLAY"
            or self.noncommercial is not True
            or self.historical_replay_only is not True
            or self.english_unchanged is not True
            or self.source_rights_verified is not True
            or any(getattr(self, name) is not False for name in _APPROVAL_FIELDS)
            or not self.starts_at <= instant <= self.ends_at
        ):
            raise ResearchStudyUseError("scope_denied")

        if type(profile_ref) is not str or not _REF_RE.fullmatch(profile_ref):
            raise ResearchStudyUseError("profile_pin_mismatch")
        if (
            type(profile_sha256) is not str
            or not _SHA256_RE.fullmatch(profile_sha256)
            or type(manifest_sha256) is not str
            or not _SHA256_RE.fullmatch(manifest_sha256)
        ):
            raise ResearchStudyUseError("profile_pin_mismatch")
        pin = next((item for item in self.profiles if item.profile_ref == profile_ref), None)
        if (
            pin is None
            or not hmac.compare_digest(pin.profile_sha256, profile_sha256)
            or not hmac.compare_digest(pin.manifest_sha256, manifest_sha256)
        ):
            raise ResearchStudyUseError("profile_pin_mismatch")

        if (task_opens_at is None) != (task_due_at is None):
            raise ResearchStudyUseError("task_window_invalid")
        if task_opens_at is not None and task_due_at is not None:
            opens = _validated_utc_datetime(task_opens_at, code="task_window_invalid")
            due = _validated_utc_datetime(task_due_at, code="task_window_invalid")
            if opens > due or opens < self.starts_at or due > self.ends_at or instant > due:
                raise ResearchStudyUseError("task_window_outside_policy")
        return pin


def load_research_study_use_policy(
    path: Path,
    *,
    expected_sha256: str,
    source_rights_verified: bool,
    latest_allowed_ends_at: datetime,
) -> ResearchStudyUsePolicy:
    """Read one explicitly configured policy with trusted external registry pins.

    ``source_rights_verified`` and ``latest_allowed_ends_at`` are supplied by
    server-controlled configuration, never by the policy file or HTTP input.
    The latest allowed expiry is passed in UTC by that configuration, which
    performs any institution-local timezone conversion outside this module.
    """

    if type(expected_sha256) is not str or not _SHA256_RE.fullmatch(expected_sha256):
        raise ResearchStudyUseError("registry_pin_invalid")
    if source_rights_verified is not True:
        raise ResearchStudyUseError("rights_registry_unverified")
    latest_end = _validated_utc_datetime(latest_allowed_ends_at, code="registry_pin_invalid")
    if not isinstance(path, Path) or not path.is_absolute():
        raise ResearchStudyUseError("policy_path_invalid")

    try:
        _assert_no_reparse_components(path)
        resolved = path.resolve(strict=True)
        if not stat.S_ISREG(resolved.stat().st_mode):
            raise ValueError
        with resolved.open("rb") as stream:
            raw = stream.read(_MAX_POLICY_BYTES + 1)
    except (OSError, RuntimeError, ValueError):
        raise ResearchStudyUseError("policy_path_invalid") from None
    if not raw or len(raw) > _MAX_POLICY_BYTES:
        raise ResearchStudyUseError("policy_size_invalid")
    if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected_sha256):
        raise ResearchStudyUseError("policy_pin_mismatch")

    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        raise ResearchStudyUseError("policy_document_invalid") from None
    return _policy_from_document(
        document,
        source_rights_verified=source_rights_verified,
        latest_allowed_ends_at=latest_end,
    )


def _policy_from_document(
    document: object,
    *,
    source_rights_verified: bool,
    latest_allowed_ends_at: datetime,
) -> ResearchStudyUsePolicy:
    if type(document) is not dict or set(document) != _TOP_LEVEL_FIELDS:
        raise ResearchStudyUseError("policy_schema_invalid")
    if document.get("schema") != _SCHEMA:
        raise ResearchStudyUseError("policy_schema_invalid")

    study_ref = _required_ref(document.get("study_ref"), "study_ref_invalid")
    school_id = document.get("school_id")
    if type(school_id) is not int or school_id <= 0:
        raise ResearchStudyUseError("study_scope_invalid")
    institution = _required_text(document.get("institution"), 1, 300, "study_scope_invalid")
    if (
        document.get("use_scope") != "ISOLATED_HISTORICAL_REPLAY"
        or document.get("noncommercial") is not True
        or document.get("historical_replay_only") is not True
        or document.get("english_unchanged") is not True
    ):
        raise ResearchStudyUseError("study_scope_invalid")
    if any(document.get(name) is not False for name in _APPROVAL_FIELDS):
        raise ResearchStudyUseError("approval_flags_invalid")

    starts_at = _parse_utc_timestamp(document.get("starts_at"), "study_window_invalid")
    ends_at = _parse_utc_timestamp(document.get("ends_at"), "study_window_invalid")
    recorded_at = _parse_utc_timestamp(document.get("recorded_at"), "study_record_invalid")
    if starts_at > ends_at or ends_at > latest_allowed_ends_at or recorded_at > ends_at:
        raise ResearchStudyUseError("study_window_invalid")

    raw_profiles = document.get("profiles")
    if type(raw_profiles) is not list or not 1 <= len(raw_profiles) <= 32:
        raise ResearchStudyUseError("profile_pins_invalid")
    profiles: list[ResearchStudyProfilePin] = []
    seen_refs: set[str] = set()
    for raw_pin in raw_profiles:
        if type(raw_pin) is not dict or set(raw_pin) != _PROFILE_FIELDS:
            raise ResearchStudyUseError("profile_pins_invalid")
        profile_ref = _required_ref(raw_pin.get("profile_ref"), "profile_pins_invalid")
        if profile_ref in seen_refs:
            raise ResearchStudyUseError("profile_pins_invalid")
        seen_refs.add(profile_ref)
        profiles.append(
            ResearchStudyProfilePin(
                profile_ref=profile_ref,
                profile_sha256=_required_sha256(
                    raw_pin.get("profile_sha256"), "profile_pins_invalid"
                ),
                manifest_sha256=_required_sha256(
                    raw_pin.get("manifest_sha256"), "profile_pins_invalid"
                ),
                published_crosswalk_sha256=_required_sha256(
                    raw_pin.get("published_crosswalk_sha256"), "profile_pins_invalid"
                ),
            )
        )

    rights_basis = _required_text(document.get("rights_basis"), 1, 4000, "rights_basis_invalid")
    raw_urls = document.get("rights_source_urls")
    if type(raw_urls) is not list or not 1 <= len(raw_urls) <= 32:
        raise ResearchStudyUseError("rights_source_urls_invalid")
    urls: list[str] = []
    for raw_url in raw_urls:
        url = _required_text(raw_url, 1, 2048, "rights_source_urls_invalid")
        if not _valid_source_url(url) or url in urls:
            raise ResearchStudyUseError("rights_source_urls_invalid")
        urls.append(url)

    recorded_by = _required_text(document.get("recorded_by"), 1, 200, "study_record_invalid")
    operator_declaration = _required_text(
        document.get("operator_declaration"), 1, 4000, "study_record_invalid"
    )
    return ResearchStudyUsePolicy(
        study_ref=study_ref,
        school_id=school_id,
        institution=institution,
        use_scope="ISOLATED_HISTORICAL_REPLAY",
        noncommercial=True,
        historical_replay_only=True,
        english_unchanged=True,
        starts_at=starts_at,
        ends_at=ends_at,
        profiles=tuple(profiles),
        rights_basis=rights_basis,
        rights_source_urls=tuple(urls),
        recorded_by=recorded_by,
        recorded_at=recorded_at,
        operator_declaration=operator_declaration,
        source_rights_verified=source_rights_verified,
        clinical_approval=False,
        ethics_approval=False,
        psychometric_approval=False,
    )


def _assert_no_reparse_components(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        info = current.lstat()
        attributes = getattr(info, "st_file_attributes", 0)
        if stat.S_ISLNK(info.st_mode) or attributes & _REPARSE_POINT:
            raise ValueError
        if hasattr(current, "is_junction") and current.is_junction():
            raise ValueError


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError


def _required_ref(value: object, code: str) -> str:
    if type(value) is not str or not _REF_RE.fullmatch(value):
        raise ResearchStudyUseError(code)
    return value


def _required_sha256(value: object, code: str) -> str:
    if type(value) is not str or not _SHA256_RE.fullmatch(value):
        raise ResearchStudyUseError(code)
    return value


def _required_text(value: object, minimum: int, maximum: int, code: str) -> str:
    if type(value) is not str or not minimum <= len(value.strip()) <= maximum:
        raise ResearchStudyUseError(code)
    if value != value.strip() or any(ord(char) < 0x20 and char not in "\t\n\r" for char in value):
        raise ResearchStudyUseError(code)
    return value


def _valid_source_url(value: object) -> bool:
    if type(value) is not str or not 1 <= len(value) <= 2048:
        return False
    if any(ord(char) < 0x20 for char in value):
        return False
    try:
        parsed = urlsplit(value)
        return bool(
            parsed.scheme in {"https", "http"}
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False


def _parse_utc_timestamp(value: object, code: str) -> datetime:
    if type(value) is not str or len(value) > 40 or not _UTC_TIMESTAMP_RE.fullmatch(value):
        raise ResearchStudyUseError(code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ResearchStudyUseError(code) from None
    return _validated_utc_datetime(parsed, code=code)


def _validated_utc_datetime(value: object, *, code: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ResearchStudyUseError(code)
    try:
        offset = value.utcoffset()
    except (OverflowError, ValueError):
        raise ResearchStudyUseError(code) from None
    if offset != timedelta(0):
        raise ResearchStudyUseError(code)
    return value.astimezone(_UTC)
