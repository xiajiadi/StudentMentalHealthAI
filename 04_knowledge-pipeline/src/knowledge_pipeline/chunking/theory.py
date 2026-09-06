"""Theory chunking by section/concept/research finding, without cross-concept merging."""

from __future__ import annotations

from ..domain.block import Block
from ..domain.document import CanonicalDocument
from .base import ChunkStrategy


class TheoryChunkStrategy(ChunkStrategy):
    name = "theory"
    version = "1.0.0"

    def chunk(self, document: CanonicalDocument):  # type: ignore[no-untyped-def]
        manual = self._manual_units(document) if document.metadata.human_curated else []
        if manual:
            return self._make_chunks(document, [(unit, self._theory_context(unit)) for unit in manual])
        units: list[tuple[list[Block], str]] = []
        current: list[Block] = []
        current_heading = ""
        has_body = False
        for block in document.blocks:
            if block.kind == "heading":
                if current and has_body:
                    units.append((current, f"Concept/section: {current_heading or 'document'}"))
                    current = []
                    has_body = False
                current.append(block)
                current_heading = block.text
            else:
                current.append(block)
                has_body = True
        if current:
            units.append((current, f"Concept/section: {current_heading or 'document'}"))
        return self._make_chunks(document, units)

    @staticmethod
    def _theory_context(blocks: list[Block]) -> str:
        heading = next((block.text for block in blocks if block.kind == "heading"), "document")
        return f"Concept/section: {heading}"
