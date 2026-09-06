"""Intervention chunking that groups scenario, strategy, steps and cautions."""

from __future__ import annotations

from ..domain.block import Block
from ..domain.document import CanonicalDocument
from .base import ChunkStrategy


_SCENARIO_WORDS = ("场景", "情境", "案例", "scenario", "situation", "case")
_CAUTION_WORDS = ("注意", "限制", "警示", "风险", "caution", "limitation", "warning")


class InterventionChunkStrategy(ChunkStrategy):
    name = "intervention"
    version = "1.0.0"

    def chunk(self, document: CanonicalDocument):  # type: ignore[no-untyped-def]
        manual = self._manual_units(document) if document.metadata.human_curated else []
        if manual:
            return self._make_chunks(document, [(unit, self._intervention_context(unit)) for unit in manual])
        units: list[tuple[list[Block], str]] = []
        current: list[Block] = []
        scenario = ""
        for block in document.blocks:
            if block.kind == "heading" and self._is_scenario(block.text) and current:
                units.append((current, f"Scenario: {scenario or 'document'}"))
                current = []
            if block.kind == "heading" and self._is_scenario(block.text):
                scenario = block.text
            current.append(block)
        if current:
            units.append((current, f"Scenario: {scenario or 'document'}"))
        return self._make_chunks(document, units)

    @staticmethod
    def _is_scenario(text: str) -> bool:
        lowered = text.lower()
        return any(word in lowered for word in _SCENARIO_WORDS)

    @staticmethod
    def _intervention_context(blocks: list[Block]) -> str:
        scenario = next((block.text for block in blocks if InterventionChunkStrategy._is_scenario(block.text)), "document")
        cautions = [block.text for block in blocks if any(word in block.text.lower() for word in _CAUTION_WORDS)]
        suffix = "; caution/limitation retained" if cautions else ""
        return f"Scenario: {scenario}{suffix}"

