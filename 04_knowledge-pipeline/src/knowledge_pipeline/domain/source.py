"""Source intake and immutable provenance records."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from ..utils import sha256_file, stable_id

InputMode = Literal["raw", "curated"]


@dataclass(frozen=True)
class SourceRequest:
    """A user-supplied input declaration; metadata is never inferred from text."""

    path: Path
    input_mode: InputMode = "raw"
    metadata: dict[str, Any] = field(default_factory=dict)
    received_at: str | None = None


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    path: Path
    filename: str
    file_type: str
    mime_type: str | None
    size: int
    source_hash: str
    received_at: str
    input_mode: InputMode
    metadata: dict[str, Any]

    @classmethod
    def from_request(cls, request: SourceRequest) -> "SourceRecord":
        path = Path(request.path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"source file does not exist: {path}")
        if request.input_mode not in {"raw", "curated"}:
            raise ValueError(f"unsupported input_mode: {request.input_mode}")
        source_hash = sha256_file(path)
        received_at = request.received_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
        filename = path.name
        source_id = stable_id("SRC", source_hash, filename, request.input_mode)
        suffix = path.suffix.lower().lstrip(".") or "unknown"
        return cls(
            source_id=source_id,
            path=path,
            filename=filename,
            file_type=suffix,
            mime_type=mimetypes.guess_type(filename)[0],
            size=path.stat().st_size,
            source_hash=f"sha256:{source_hash}",
            received_at=received_at,
            input_mode=request.input_mode,
            metadata=dict(request.metadata),
        )

    def to_manifest_dict(self, duplicate_of: str | None = None) -> dict[str, Any]:
        value: dict[str, Any] = {
            "source_id": self.source_id,
            "filename": self.filename,
            "file_type": self.file_type,
            "mime_type": self.mime_type,
            "size": self.size,
            "source_hash": self.source_hash,
            "received_at": self.received_at,
            "input_mode": self.input_mode,
            "metadata": self.metadata,
        }
        if duplicate_of:
            value["duplicate_of"] = duplicate_of
        return value


def assert_raw_is_read_only(path: Path, raw_root: Path | None = None) -> None:
    """Fail closed if a caller tries to treat a raw source as a writable target."""

    if raw_root is None:
        return
    resolved = Path(path).resolve()
    root = Path(raw_root).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return
    if not resolved.is_file():
        raise FileNotFoundError(f"raw source is not a file: {resolved}")

