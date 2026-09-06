"""Format-neutral structural blocks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

BlockType = Literal["heading", "paragraph", "list", "table", "figure_caption", "other"]


@dataclass(frozen=True)
class Block:
    block_id: str
    kind: BlockType
    text: str
    heading_level: int | None = None
    heading_path: tuple[str, ...] = ()
    page_start: int | None = None
    page_end: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "kind": self.kind,
            "text": self.text,
            "heading_level": self.heading_level,
            "heading_path": list(self.heading_path),
            "page_start": self.page_start,
            "page_end": self.page_end,
            "metadata": self.metadata,
        }

