"""D4 synthetic fixture-mode isolation and compatibility mapping."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .errors import FixtureModeError
from .hashing import sha256_hex
from .paths import normalise_artifact_path

FIXTURE_MODES = frozenset({"exact_d3_fixture", "legacy_compatibility_fixture"})
FIXTURE_MODE_TO_MAPPING = {
    "exact_d3_fixture": "none",
    "legacy_compatibility_fixture": "D3-4_BACKEND_SYNTHETIC_COMPATIBILITY_V1",
}


def assert_fixture_mode(mode: str) -> str:
    if mode not in FIXTURE_MODES:
        raise FixtureModeError(
            f"unsupported fixture_mode {mode!r}; expected one of {sorted(FIXTURE_MODES)}"
        )
    return mode


def fixture_mode_for(record: Mapping[str, Any]) -> str:
    """Read and validate a scenario or evidence fixture mode."""

    mode: Any = record.get("fixture_mode")
    if mode is None:
        binding = record.get("assessment_binding")
        if isinstance(binding, Mapping):
            mode = binding.get("fixture_mode")
    if mode is None:
        fixture_audit = record.get("fixture_audit")
        if isinstance(fixture_audit, Mapping):
            mode = fixture_audit.get("fixture_mode")
    if not isinstance(mode, str):
        raise FixtureModeError("record has no fixture_mode")
    return assert_fixture_mode(mode)


def compatibility_mapping_for(mode: str) -> str:
    return FIXTURE_MODE_TO_MAPPING[assert_fixture_mode(mode)]


def _fixture_refs(record: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    refs = record.get("fixture_refs")
    if refs is None:
        binding = record.get("assessment_binding")
        if isinstance(binding, Mapping):
            refs = (binding,)
    if not isinstance(refs, (list, tuple)) or not refs:
        raise FixtureModeError("record must contain at least one fixture reference")
    for ref in refs:
        if not isinstance(ref, Mapping):
            raise FixtureModeError("fixture_refs entries must be objects")
        yield ref


def _fixture_file_candidates(path_text: str) -> tuple[Path, ...]:
    eval_root = Path(__file__).resolve().parents[2]
    repo_root = Path(__file__).resolve().parents[4]
    return (eval_root / path_text, repo_root / path_text)


def _fixture_bytes(path: Path) -> bytes:
    """Read text fixtures using stable LF bytes across Windows checkouts.

    D4 fixture identity is a content identity, not a checkout line-ending
    identity.  The accepted JSON fixtures are therefore hashed after the
    single canonical transformation CRLF -> LF; no JSON values or ordering
    are changed.
    """

    data = path.read_bytes()
    if path.suffix.lower() == ".json":
        data = data.replace(b"\r\n", b"\n")
    return data


def validate_fixture_record(record: Mapping[str, Any]) -> str:
    """Validate mode/mapping agreement for one scenario or evidence record."""

    mode = fixture_mode_for(record)
    expected_mapping = compatibility_mapping_for(mode)
    for ref in _fixture_refs(record):
        mapping = ref.get("compatibility_mapping")
        if mapping != expected_mapping:
            raise FixtureModeError(
                f"fixture mapping {mapping!r} does not match {mode!r}"
            )
        if ref.get("purpose") not in (None, "synthetic_only"):
            raise FixtureModeError("D4 fixture references must be synthetic_only")
        if "path" in ref:
            try:
                normalized_path = normalise_artifact_path(ref["path"])
            except Exception as exc:
                raise FixtureModeError(f"fixture path is unsafe: {exc}") from exc
            candidates = _fixture_file_candidates(normalized_path)
            existing = next(
                (candidate for candidate in candidates if candidate.is_file()), None
            )
            if existing is None:
                raise FixtureModeError(f"fixture file does not exist: {normalized_path}")
            expected_hash = ref.get("sha256")
            actual_hash = sha256_hex(_fixture_bytes(existing))
            if expected_hash != actual_hash:
                raise FixtureModeError(
                    f"fixture sha256 mismatch for {normalized_path}: "
                    f"expected {expected_hash}, got {actual_hash}"
                )
    return mode


def enforce_fixture_mode_isolation(
    records: Iterable[Mapping[str, Any]],
    *,
    expected_mode: str | None = None,
) -> str | None:
    """Reject mixed exact/legacy fixture records in one evidence pool.

    A dataset catalog may contain different split names, but a formal run or
    normalized evidence set must call this function over the records it is
    pooling.  An empty collection returns ``None``.
    """

    modes: set[str] = set()
    for record in records:
        mode = validate_fixture_record(record)
        modes.add(mode)
    if expected_mode is not None:
        assert_fixture_mode(expected_mode)
        if modes and modes != {expected_mode}:
            raise FixtureModeError(
                f"fixture pool has {sorted(modes)}, expected {expected_mode}"
            )
    if len(modes) > 1:
        raise FixtureModeError(
            "fixture modes cannot be pooled in one run: " + ", ".join(sorted(modes))
        )
    return next(iter(modes), None)


def assert_fixture_mode_compatible(
    actual: str,
    expected: str,
) -> str:
    assert_fixture_mode(actual)
    assert_fixture_mode(expected)
    if actual != expected:
        raise FixtureModeError(f"fixture_mode changed from {expected} to {actual}")
    return actual


# Alias with a concise name for callers building a pool.
enforce_no_fixture_pooling = enforce_fixture_mode_isolation
