"""Scan a fresh evaluation artifact root for plaintext credential material."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


def scan_secret_artifacts(
    artifact_root: str | Path,
    secret_values: Iterable[str],
    *,
    chunk_size: int = 1024 * 1024,
) -> dict[str, int | str | bool]:
    root = Path(artifact_root).resolve()
    secrets = tuple(
        value.encode("utf-8", errors="surrogatepass")
        for value in secret_values
        if isinstance(value, str) and value
    )
    if not root.is_dir() or not secrets or chunk_size < 1024:
        return {
            "status": "FAIL",
            "plaintext_occurrences": 0,
            "scanned_file_count": 0,
            "unreadable_file_count": 0,
            "plaintext_recorded": False,
        }

    scanned = 0
    unreadable = 0
    occurrences = 0
    overlap_size = max(len(value) for value in secrets) - 1
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        scanned += 1
        overlap = b""
        try:
            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(chunk_size)
                    if not chunk:
                        break
                    window = overlap + chunk
                    occurrences += sum(window.count(value) for value in secrets)
                    overlap = window[-overlap_size:] if overlap_size else b""
        except OSError:
            unreadable += 1

    return {
        "status": "PASS" if occurrences == 0 and unreadable == 0 else "FAIL",
        "plaintext_occurrences": occurrences,
        "scanned_file_count": scanned,
        "unreadable_file_count": unreadable,
        "plaintext_recorded": False,
    }
