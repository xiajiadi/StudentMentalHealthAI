"""Structured context and source citation assembly."""

from __future__ import annotations

from ..domain import Citation, CitationBundle, ContextBundle, ContextItem, RetrievalHit


class ContextBuilder:
    def build(self, hits: list[RetrievalHit] | tuple[RetrievalHit, ...], *, max_chars: int) -> ContextBundle:
        if max_chars < 1:
            raise ValueError("max_chars must be positive")
        items: list[ContextItem] = []
        citations: list[Citation] = []
        blocks: list[str] = []
        seen: set[str] = set()
        truncated = False

        for hit in hits:
            if hit.chunk_id in seen:
                continue
            citation_id = f"S{len(citations) + 1}"
            citation = Citation.from_record(hit.record, citation_id)
            source_location = citation.source_locator
            if citation.section:
                source_location = f"{source_location}; section:{citation.section}"
            item = ContextItem(
                citation_id=citation_id,
                source_title=citation.source_title,
                source_location=source_location,
                chunk_text=hit.record.text,
            )
            block = (
                f"[{citation_id}]\n"
                f"来源：{citation.source_title} · {citation.source_organization}\n"
                f"位置：{source_location}\n"
                f"正文：{hit.record.text}"
            )
            separator = "\n\n" if blocks else ""
            remaining = max_chars - len("".join(blocks)) - len(separator)
            if remaining <= 0:
                truncated = True
                break
            if len(block) > remaining:
                block = block[:remaining].rstrip()
                truncated = True
            seen.add(hit.chunk_id)
            citations.append(citation)
            items.append(item)
            blocks.append(separator + block)
            if truncated:
                break
        bundle = CitationBundle(tuple(citations))
        return ContextBundle(items=tuple(items), text="".join(blocks), citation_bundle=bundle, truncated=truncated)
