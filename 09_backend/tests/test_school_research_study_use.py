import hashlib
import json
import stat
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from smhai_backend.domains.school_research import study_use
from smhai_backend.domains.school_research.study_use import (
    ResearchStudyUseError,
    ResearchStudyUsePolicy,
    load_research_study_use_policy,
)

_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64
_HASH_D = "d" * 64
_LATEST_END = datetime(2027, 6, 30, 23, 59, 59, tzinfo=UTC)


def _policy_document() -> dict[str, object]:
    return {
        "schema": "psynova.research-study-use.v1",
        "study_ref": "study:replay-01",
        "school_id": 701,
        "institution": "Synthetic institution declaration",
        "use_scope": "ISOLATED_HISTORICAL_REPLAY",
        "noncommercial": True,
        "historical_replay_only": True,
        "english_unchanged": True,
        "starts_at": "2026-10-14T00:00:00Z",
        "ends_at": "2027-06-30T23:59:59Z",
        "profiles": [
            {
                "profile_ref": "profile:promis-research-v3",
                "profile_sha256": _HASH_A,
                "manifest_sha256": _HASH_B,
                "published_crosswalk_sha256": _HASH_C,
            }
        ],
        "rights_basis": "Recorded rights basis for a bounded, noncommercial historical replay.",
        "rights_source_urls": ["https://example.org/research-rights"],
        "recorded_by": "operator:synthetic-review",
        "recorded_at": "2026-10-14T00:00:00Z",
        "operator_declaration": "This is a server-configured declaration, not an external grant.",
        "clinical_approval": False,
        "ethics_approval": False,
        "psychometric_approval": False,
    }


def _write_policy(tmp_path: Path, raw: bytes | None = None) -> tuple[Path, str]:
    path = tmp_path / "study-use.json"
    content = json.dumps(_policy_document(), separators=(",", ":")).encode("utf-8")
    path.write_bytes(content if raw is None else raw)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path, digest: str, **overrides):
    values = {
        "expected_sha256": digest,
        "source_rights_verified": True,
        "latest_allowed_ends_at": _LATEST_END,
    }
    values.update(overrides)
    return load_research_study_use_policy(path, **values)


def test_loads_pinned_immutable_replay_scope_and_requires_exact_binding_pins(tmp_path):
    path, digest = _write_policy(tmp_path)
    policy = _load(path, digest)

    pin = policy.require_scope(
        school_id=701,
        profile_ref="profile:promis-research-v3",
        profile_sha256=_HASH_A,
        manifest_sha256=_HASH_B,
        at=datetime(2026, 10, 15, tzinfo=UTC),
        task_opens_at=datetime(2026, 11, 1, tzinfo=UTC),
        task_due_at=datetime(2026, 11, 30, tzinfo=UTC),
    )

    assert pin.published_crosswalk_sha256 == _HASH_C
    assert policy.use_scope == "ISOLATED_HISTORICAL_REPLAY"
    assert policy.source_rights_verified is True
    assert policy.clinical_approval is False
    assert policy.ethics_approval is False
    assert policy.psychometric_approval is False
    assert isinstance(policy.profiles, tuple)
    assert isinstance(policy.rights_source_urls, tuple)
    with pytest.raises(FrozenInstanceError):
        policy.school_id = 702
    with pytest.raises(FrozenInstanceError):
        policy.profiles[0].profile_ref = "profile:changed"


@pytest.mark.parametrize(
    "changes, at, profile_ref, profile_sha, manifest_sha, code",
    [
        (
            {},
            datetime(2026, 10, 13, tzinfo=UTC),
            "profile:promis-research-v3",
            _HASH_A,
            _HASH_B,
            "scope_denied",
        ),
        (
            {},
            datetime(2026, 10, 15, tzinfo=UTC),
            "profile:other",
            _HASH_A,
            _HASH_B,
            "profile_pin_mismatch",
        ),
        (
            {},
            datetime(2026, 10, 15, tzinfo=UTC),
            "profile:promis-research-v3",
            _HASH_D,
            _HASH_B,
            "profile_pin_mismatch",
        ),
        (
            {},
            datetime(2026, 10, 15, tzinfo=UTC),
            "profile:promis-research-v3",
            _HASH_A,
            _HASH_D,
            "profile_pin_mismatch",
        ),
        (
            {"school_id": 702},
            datetime(2026, 10, 15, tzinfo=UTC),
            "profile:promis-research-v3",
            _HASH_A,
            _HASH_B,
            "scope_denied",
        ),
    ],
)
def test_scope_rejects_out_of_period_cross_school_or_mismatched_profile_pins(
    tmp_path, changes, at, profile_ref, profile_sha, manifest_sha, code
):
    document = _policy_document()
    document.update(changes)
    content = json.dumps(document, separators=(",", ":")).encode("utf-8")
    path, digest = _write_policy(tmp_path, content)
    policy = _load(path, digest)

    with pytest.raises(ResearchStudyUseError) as exc:
        policy.require_scope(
            school_id=701,
            profile_ref=profile_ref,
            profile_sha256=profile_sha,
            manifest_sha256=manifest_sha,
            at=at,
        )
    assert exc.value.code == code


@pytest.mark.parametrize(
    "task_open, task_due, code",
    [
        (
            datetime(2026, 10, 1, tzinfo=UTC),
            datetime(2026, 11, 1, tzinfo=UTC),
            "task_window_outside_policy",
        ),
        (
            datetime(2027, 6, 1, tzinfo=UTC),
            datetime(2027, 7, 1, tzinfo=UTC),
            "task_window_outside_policy",
        ),
        (
            datetime(2026, 11, 2, tzinfo=UTC),
            datetime(2026, 11, 1, tzinfo=UTC),
            "task_window_outside_policy",
        ),
    ],
)
def test_scope_requires_task_window_inside_policy(tmp_path, task_open, task_due, code):
    path, digest = _write_policy(tmp_path)
    policy = _load(path, digest)

    with pytest.raises(ResearchStudyUseError) as exc:
        policy.require_scope(
            school_id=701,
            profile_ref="profile:promis-research-v3",
            profile_sha256=_HASH_A,
            manifest_sha256=_HASH_B,
            at=datetime(2026, 10, 15, tzinfo=UTC),
            task_opens_at=task_open,
            task_due_at=task_due,
        )
    assert exc.value.code == code


def test_scope_rejects_partial_or_naive_task_window(tmp_path):
    path, digest = _write_policy(tmp_path)
    policy = _load(path, digest)
    with pytest.raises(ResearchStudyUseError, match="task_window_invalid"):
        policy.require_scope(
            school_id=701,
            profile_ref="profile:promis-research-v3",
            profile_sha256=_HASH_A,
            manifest_sha256=_HASH_B,
            at=datetime(2026, 10, 15, tzinfo=UTC),
            task_opens_at=datetime(2026, 11, 1),
        )


def test_scope_rejects_action_after_task_due_date(tmp_path):
    path, digest = _write_policy(tmp_path)
    policy = _load(path, digest)
    with pytest.raises(ResearchStudyUseError, match="task_window_outside_policy"):
        policy.require_scope(
            school_id=701,
            profile_ref="profile:promis-research-v3",
            profile_sha256=_HASH_A,
            manifest_sha256=_HASH_B,
            at=datetime(2026, 12, 1, tzinfo=UTC),
            task_opens_at=datetime(2026, 11, 1, tzinfo=UTC),
            task_due_at=datetime(2026, 11, 30, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    "field, value, code",
    [
        ("clinical_approval", True, "approval_flags_invalid"),
        ("ethics_approval", True, "approval_flags_invalid"),
        ("psychometric_approval", True, "approval_flags_invalid"),
        ("noncommercial", False, "study_scope_invalid"),
        ("historical_replay_only", False, "study_scope_invalid"),
        ("english_unchanged", False, "study_scope_invalid"),
        ("use_scope", "OFFICIAL_CAT_LICENSE", "study_scope_invalid"),
        ("unexpected_approval", True, "policy_schema_invalid"),
        ("source_rights_verified", True, "policy_schema_invalid"),
    ],
)
def test_policy_rejects_approval_claims_unknown_fields_and_untrusted_rights_flag(
    tmp_path, field, value, code
):
    document = _policy_document()
    document[field] = value
    raw = json.dumps(document, separators=(",", ":")).encode("utf-8")
    path, digest = _write_policy(tmp_path, raw)
    with pytest.raises(ResearchStudyUseError) as exc:
        _load(path, digest)
    assert exc.value.code == code


def test_policy_requires_separate_truthy_but_strict_registry_rights_flag(tmp_path):
    path, digest = _write_policy(tmp_path)
    with pytest.raises(ResearchStudyUseError) as exc:
        _load(path, digest, source_rights_verified=1)
    assert exc.value.code == "rights_registry_unverified"


def test_expiry_is_bounded_by_external_utc_registry_configuration(tmp_path):
    document = _policy_document()
    document["ends_at"] = "2027-07-01T00:00:00Z"
    raw = json.dumps(document, separators=(",", ":")).encode("utf-8")
    path, digest = _write_policy(tmp_path, raw)

    with pytest.raises(ResearchStudyUseError) as exc:
        _load(path, digest)
    assert exc.value.code == "study_window_invalid"

    with pytest.raises(ResearchStudyUseError) as exc:
        _load(
            path,
            digest,
            latest_allowed_ends_at=datetime(2027, 6, 30, 23, 59, 59),
        )
    assert exc.value.code == "registry_pin_invalid"


@pytest.mark.parametrize(
    "value",
    ["2026-10-14 00:00:00Z", "2026-10-14T08:00:00+08:00", "2026-10-14T00:00:00"],
)
def test_policy_timestamps_must_be_strict_aware_utc(value, tmp_path):
    document = _policy_document()
    document["starts_at"] = value
    raw = json.dumps(document, separators=(",", ":")).encode("utf-8")
    path, digest = _write_policy(tmp_path, raw)
    with pytest.raises(ResearchStudyUseError) as exc:
        _load(path, digest)
    assert exc.value.code == "study_window_invalid"


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema":"x","schema":"y"}',
        b'{"not_json":NaN}',
        b'{"not_json":Infinity}',
        b"\xff",
    ],
)
def test_reader_rejects_duplicate_keys_nonfinite_and_non_utf8(tmp_path, raw):
    path, digest = _write_policy(tmp_path, raw)
    with pytest.raises(ResearchStudyUseError) as exc:
        _load(path, digest)
    assert exc.value.code == "policy_document_invalid"


def test_reader_enforces_exact_hash_and_64kib_bound_without_echoing_path(tmp_path):
    path, digest = _write_policy(tmp_path)
    with pytest.raises(ResearchStudyUseError) as exc:
        _load(path, "0" * 64)
    assert exc.value.code == "policy_pin_mismatch"
    assert str(path) not in str(exc.value)

    large = b" " * (64 * 1024 + 1)
    large_path, large_digest = _write_policy(tmp_path, large)
    with pytest.raises(ResearchStudyUseError) as exc:
        _load(large_path, large_digest)
    assert exc.value.code == "policy_size_invalid"


def test_reader_rejects_reparse_policy_path(tmp_path, monkeypatch):
    path, digest = _write_policy(tmp_path)
    original_lstat = Path.lstat

    def lstat_with_reparse(self):
        if self == path:
            return SimpleNamespace(
                st_mode=stat.S_IFREG,
                st_file_attributes=study_use._REPARSE_POINT,
            )
        return original_lstat(self)

    monkeypatch.setattr(Path, "lstat", lstat_with_reparse)

    with pytest.raises(ResearchStudyUseError) as exc:
        _load(path, digest)
    assert exc.value.code == "policy_path_invalid"


def test_public_record_constructor_cannot_claim_approval_or_mutable_profile_lists(
    tmp_path,
):
    path, digest = _write_policy(tmp_path)
    policy = _load(path, digest)
    fields = {name: getattr(policy, name) for name in ResearchStudyUsePolicy.__dataclass_fields__}
    fields["clinical_approval"] = True
    with pytest.raises(ResearchStudyUseError) as exc:
        ResearchStudyUsePolicy(**fields)
    assert exc.value.code == "policy_schema_invalid"

    fields["clinical_approval"] = False
    fields["profiles"] = list(policy.profiles)
    with pytest.raises(ResearchStudyUseError) as exc:
        ResearchStudyUsePolicy(**fields)
    assert exc.value.code == "policy_schema_invalid"
