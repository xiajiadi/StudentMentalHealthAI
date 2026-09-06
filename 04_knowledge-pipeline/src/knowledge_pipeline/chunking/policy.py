"""Policy chunking that keeps chapter/section/article boundaries visible."""

from __future__ import annotations

import re

from ..domain.block import Block
from ..domain.document import CanonicalDocument
from .base import ChunkStrategy


_CHAPTER = re.compile(r"^第[一二三四五六七八九十百千万零〇0-9]+章")
_SECTION = re.compile(r"^第[一二三四五六七八九十百千万零〇0-9]+节")
_ARTICLE = re.compile(r"^第[一二三四五六七八九十百千万零〇0-9]+条")


class PolicyChunkStrategy(ChunkStrategy):
    name = "policy"
    version = "1.0.0"

    def chunk(self, document: CanonicalDocument):  # type: ignore[no-untyped-def]
        if document.metadata.human_curated:
            manual = self._manual_units(document)
            if manual:
                return self._make_chunks(document, [(unit, self._policy_context(unit)) for unit in manual])
        units: list[tuple[list[Block], str]] = []
        preamble: list[Block] = []
        current: list[Block] = []
        pending_headings: list[Block] = []
        chapter = ""
        section = ""
        current_article = ""
        for block in document.blocks:
            text = block.text.strip()
            if _CHAPTER.match(text):
                if current:
                    units.append((current, self._policy_context(current, chapter, section, current_article)))
                    current = []
                chapter = text
                section = ""
                current_article = ""
                pending_headings.append(block)
            elif _SECTION.match(text):
                if current:
                    units.append((current, self._policy_context(current, chapter, section, current_article)))
                    current = []
                section = text
                current_article = ""
                pending_headings.append(block)
            elif _ARTICLE.match(text):
                if current:
                    units.append((current, self._policy_context(current, chapter, section, current_article)))
                current = [*preamble, *pending_headings, block]
                preamble = []
                pending_headings = []
                current_article = _ARTICLE.match(text).group(0)  # type: ignore[union-attr]
            elif current:
                current.append(block)
            else:
                preamble.append(block)
        if current:
            units.append((current, self._policy_context(current, chapter, section, current_article)))
        elif preamble:
            units.append((preamble, self._policy_context(preamble, chapter, section, current_article)))
        if not units:
            return []
        return self._make_chunks(document, units)

    @staticmethod
    def _policy_context(blocks: list[Block], chapter: str = "", section: str = "", article: str = "") -> str:
        values = [f"Chapter: {chapter}" if chapter else "", f"Section: {section}" if section else "", f"Article: {article}" if article else ""]
        if not article:
            values.append("Policy hierarchy preserved; no article marker detected")
        return "\n".join(value for value in values if value)
