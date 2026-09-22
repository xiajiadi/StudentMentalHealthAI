"""Artifact path safety for D4 manifests and evidence."""

from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath
from typing import Iterable

from .errors import ArtifactPathError


# Result artifacts must stay inside the evaluation area and must never look
# like product writes or secret/configuration dumps.  Fixture references use
# ``normalise_artifact_path`` directly because they may intentionally point to
# a read-only accepted product fixture; this stricter policy is for outputs.
_FORBIDDEN_RESULT_ROOTS = frozenset(
    {
        "00_architecture",
        "01_cat-engine",
        "02_item-bank",
        "03_assessment-adapter",
        "04_knowledge-pipeline",
        "05_rag-engine",
        "06_llm-runtime",
        "07_prompt-engine",
        "08_safety-engine",
        "09_backend",
        "10_frontend",
        "11_database",
    }
)
_FORBIDDEN_RESULT_NAMES = frozenset(
    {".env", ".env.local", ".env.production", "id_rsa", "credentials.json"}
)


def _reject_sensitive_result_path(parts: list[str], original: str) -> None:
    lowered = [part.lower() for part in parts]
    if lowered and lowered[0] in _FORBIDDEN_RESULT_ROOTS:
        raise ArtifactPathError(
            f"result artifact cannot target a product directory: {original!r}"
        )
    basename = lowered[-1]
    if (
        basename in _FORBIDDEN_RESULT_NAMES
        or basename.startswith(".env.")
        or basename.endswith((".pem", ".key", ".p12", ".pfx"))
        or any(marker in basename for marker in ("secret", "credential", "token"))
    ):
        raise ArtifactPathError(
            f"result artifact looks like a secret or environment dump: {original!r}"
        )


def _path_text(relative: str | os.PathLike[str]) -> str:
    if isinstance(relative, os.PathLike):
        text = os.fspath(relative)
    else:
        text = relative
    if not isinstance(text, str) or not text:
        raise ArtifactPathError("artifact path must be a non-empty string")
    if "\x00" in text:
        raise ArtifactPathError("artifact path contains NUL")
    return text


def _validate_relative_syntax(text: str) -> list[str]:
    # Check both host-native and Windows syntax.  The latter matters when a
    # manifest created on Windows is inspected on another host.
    windows = PureWindowsPath(text)
    if windows.is_absolute() or windows.drive or text.startswith(("\\\\", "//")):
        raise ArtifactPathError(f"absolute artifact path is forbidden: {text!r}")
    if text.startswith(("/", "\\")):
        raise ArtifactPathError(f"absolute artifact path is forbidden: {text!r}")
    if "://" in text:
        raise ArtifactPathError(f"URI artifact path is forbidden: {text!r}")
    raw_parts = text.replace("\\", "/").split("/")
    if any(part == ".." for part in raw_parts):
        raise ArtifactPathError(f"parent traversal is forbidden: {text!r}")
    if any(part == "" for part in raw_parts):
        # Double separators create surprising spellings and are not needed in
        # machine result paths.  A single trailing slash is also rejected.
        raise ArtifactPathError(f"empty artifact path segment: {text!r}")
    parts = [part for part in raw_parts if part != "."]
    if not parts:
        raise ArtifactPathError("artifact path is empty")
    return parts


def safe_artifact_path(
    root: str | os.PathLike[str],
    relative: str | os.PathLike[str],
    *,
    allow_directory: bool = True,
) -> Path:
    """Resolve a relative artifact path and prove it remains under *root*.

    Existing symlinks are resolved before the containment check, so a path
    cannot escape through a link placed inside the artifact tree.  No file is
    created by this function.
    """

    root_path = Path(root)
    if not root_path:
        raise ArtifactPathError("artifact root is empty")
    text = _path_text(relative)
    parts = _validate_relative_syntax(text)
    if not parts:
        raise ArtifactPathError("artifact path is empty")
    root_resolved = root_path.resolve(strict=False)
    candidate = root_resolved.joinpath(*parts)
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ArtifactPathError(
            f"artifact path escapes root {root_resolved}: {relative!r}"
        ) from exc
    if not allow_directory and resolved.exists() and resolved.is_dir():
        raise ArtifactPathError(f"artifact path is a directory: {relative!r}")
    return resolved


def normalise_artifact_path(relative: str | os.PathLike[str]) -> str:
    """Return a portable slash-separated relative path after validation."""

    text = _path_text(relative)
    parts = _validate_relative_syntax(text)
    return "/".join(parts)


def validate_artifact_paths(
    paths: Iterable[str | os.PathLike[str]],
    *,
    root: str | os.PathLike[str],
) -> list[str]:
    """Validate result paths and return normalized manifest spellings."""

    normalized: list[str] = []
    for value in paths:
        path = normalise_artifact_path(value)
        _reject_sensitive_result_path(path.split("/"), path)
        safe_artifact_path(root, path)
        normalized.append(path)
    if len(set(normalized)) != len(normalized):
        raise ArtifactPathError("duplicate artifact paths are ambiguous")
    return normalized


def validate_result_path(value: str | os.PathLike[str]) -> str:
    """Validate one result spelling without resolving or creating a root."""

    normalized = normalise_artifact_path(value)
    _reject_sensitive_result_path(normalized.split("/"), normalized)
    return normalized


def assert_artifact_path(path: Path, *, root: Path) -> Path:
    """Check an already resolved path against a root."""

    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise ArtifactPathError(f"artifact path escapes root: {path}") from exc
    return path.resolve(strict=False)


normalize_artifact_path = normalise_artifact_path
