"""BM25S adapter with deterministic multilingual token preparation."""

from __future__ import annotations

import importlib.metadata
import json
import re
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping, Sequence

from ..domain import KnowledgeRecord, MetadataFilter, RetrievalHit
from ..exceptions import ProviderUnavailableError


_CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_ASCII_PATTERN = re.compile(r"[a-z0-9_]", re.IGNORECASE)


def tokenize_for_bm25(text: str) -> list[str]:
    """Tokenize CJK runs into bigrams and ASCII runs into words.

    The default BM25S splitter is tuned for two-or-more-character ``\\w``
    tokens and behaves inconsistently for Chinese on this Windows/Python
    combination.  CJK bigrams retain phrase signal without letting a single
    common character make an unrelated negative query look relevant.
    """

    value = str(text).lower()
    tokens: list[str] = []
    cjk_run: list[str] = []
    ascii_run: list[str] = []

    def flush_cjk() -> None:
        if not cjk_run:
            return
        if len(cjk_run) == 1:
            tokens.append(cjk_run[0])
        else:
            tokens.extend("".join(cjk_run[index : index + 2]) for index in range(len(cjk_run) - 1))
        cjk_run.clear()

    def flush_ascii() -> None:
        if ascii_run:
            tokens.append("".join(ascii_run))
            ascii_run.clear()

    for char in value:
        if _CJK_PATTERN.fullmatch(char):
            flush_ascii()
            cjk_run.append(char)
        elif _ASCII_PATTERN.fullmatch(char):
            flush_cjk()
            ascii_run.append(char)
        else:
            flush_cjk()
            flush_ascii()
    flush_cjk()
    flush_ascii()
    return tokens


class BM25SRetriever:
    """Thin adapter around the BM25S index and retrieval API."""

    def __init__(self, records: Sequence[KnowledgeRecord] | None = None) -> None:
        self.records: list[KnowledgeRecord] = list(records or [])
        self._bm25: Any | None = None
        self._tokenizer: Any | None = None
        self._built = False
        self.last_latency_ms = 0.0
        try:
            self.package_version = importlib.metadata.version("bm25s")
        except importlib.metadata.PackageNotFoundError:
            self.package_version = "not-installed"

    def build(self, records: Sequence[KnowledgeRecord] | None = None) -> None:
        if records is not None:
            self.records = list(records)
        if not self.records:
            raise ProviderUnavailableError("BM25S cannot index an empty corpus", code="BM25_EMPTY_CORPUS")
        try:
            import bm25s
            from bm25s.tokenization import Tokenizer

            # Python's default ``\\w`` splitter is not CJK-safe on the supported
            # Windows runtimes.  Pass the same deterministic tokenizer used for
            # both corpus and query text so one-character Chinese terms remain
            # searchable and the saved BM25 vocabulary is reproducible.
            self._tokenizer = Tokenizer(splitter=tokenize_for_bm25, stopwords=[])
            prepared = [" ".join(tokenize_for_bm25(record.context_text)) for record in self.records]
            corpus_tokens = self._tokenizer.tokenize(prepared, return_as="tuple", show_progress=False)
            self._bm25 = bm25s.BM25()
            self._bm25.index(corpus_tokens, show_progress=False)
            self._built = True
        except Exception as exc:
            raise ProviderUnavailableError(
                f"BM25S index build failed: {type(exc).__name__}: {exc}",
                code="BM25_BUILD_FAILED",
            ) from exc

    def search(self, query: str, *, limit: int, filters: MetadataFilter) -> list[RetrievalHit]:
        if not self._built or self._bm25 is None or self._tokenizer is None:
            raise ProviderUnavailableError("BM25S index has not been built", code="BM25_NOT_READY")
        if not query.strip() or not self.records:
            return []
        try:
            prepared_query = " ".join(tokenize_for_bm25(query))
            query_tokens = self._tokenizer.tokenize([prepared_query], update_vocab=False, show_progress=False)
            # Filtering after retrieval is safe here because the corpus is small
            # in Round 1 and we request every indexed position when a predicate
            # could exclude a high-scoring result.
            request_k = len(self.records) if filters != MetadataFilter() else min(limit, len(self.records))
            started = perf_counter()
            results, scores = self._bm25.retrieve(query_tokens, k=max(1, request_k), show_progress=False)
            elapsed_ms = (perf_counter() - started) * 1000
        except Exception as exc:
            raise ProviderUnavailableError(
                f"BM25S query failed: {type(exc).__name__}: {exc}",
                code="BM25_QUERY_FAILED",
            ) from exc
        hits: list[RetrievalHit] = []
        result_row = results[0] if getattr(results, "ndim", 1) > 1 else results
        score_row = scores[0] if getattr(scores, "ndim", 1) > 1 else scores
        for raw_index, raw_score in zip(result_row, score_row):
            index = _result_index(raw_index, self.records)
            if index is None or index >= len(self.records):
                continue
            if float(raw_score) <= 0.0:
                # BM25S returns a complete top-k array, including zero-score
                # documents.  They are not lexical matches and must not turn a
                # negative query into fabricated context.
                continue
            record = self.records[index]
            if not filters.matches(record):
                continue
            hits.append(
                RetrievalHit(
                    record=record,
                    retriever="bm25s",
                    rank=len(hits),
                    sparse_score=float(raw_score),
                )
            )
            if len(hits) >= limit:
                break
        # Keep the most recent timing observable without putting it in public
        # scores; the service owns the aggregate trace latency.
        self.last_latency_ms = elapsed_ms
        return hits

    def save(self, path: str | Path) -> None:
        if not self._built or self._bm25 is None or self._tokenizer is None:
            raise ProviderUnavailableError("BM25S index has not been built", code="BM25_NOT_READY")
        target = Path(path)
        target.mkdir(parents=True, exist_ok=True)
        try:
            self._bm25.save(str(target))
            self._tokenizer.save_vocab(save_dir=str(target))
            (target / "rag_records.jsonl").write_text(
                "".join(json.dumps(record.to_contract_projection(), ensure_ascii=False, sort_keys=True) + "\n" for record in self.records),
                encoding="utf-8",
            )
        except Exception as exc:
            raise ProviderUnavailableError(f"BM25S index save failed: {type(exc).__name__}: {exc}", code="BM25_SAVE_FAILED") from exc

    @classmethod
    def load(cls, path: str | Path, *, records: Sequence[KnowledgeRecord]) -> "BM25SRetriever":
        """Load a saved BM25S index with an explicit, caller-owned corpus.

        The corpus is deliberately required rather than silently reconstructed
        from provider files.  The Knowledge export remains the source of truth
        for metadata, eligibility, and citations.
        """

        target = Path(path)
        if not target.exists():
            raise ProviderUnavailableError(f"BM25S index path does not exist: {target}", code="BM25_INDEX_MISSING")
        try:
            import bm25s
            from bm25s.tokenization import Tokenizer

            result = cls(records)
            result._tokenizer = Tokenizer(splitter=tokenize_for_bm25, stopwords=[])
            result._tokenizer.load_vocab(save_dir=str(target))
            result._bm25 = bm25s.BM25.load(str(target), load_corpus=False)
            result._built = True
            return result
        except Exception as exc:
            raise ProviderUnavailableError(
                f"BM25S index load failed: {type(exc).__name__}: {exc}",
                code="BM25_LOAD_FAILED",
            ) from exc

    def health_check(self) -> dict[str, Any]:
        return {
            "status": "ok" if self._built else "not_ready",
            "provider": "bm25s",
            "version": self.package_version,
            "count": len(self.records),
            "built": self._built,
        }

    def index_info(self) -> dict[str, Any]:
        return {"provider": "bm25s", "version": self.package_version, "count": len(self.records), "built": self._built}


def _result_index(value: Any, records: Sequence[KnowledgeRecord]) -> int | None:
    try:
        if isinstance(value, (int, float)):
            return int(value)
        if hasattr(value, "item"):
            item = value.item()
            if isinstance(item, (int, float)):
                return int(item)
        if isinstance(value, Mapping):
            chunk_id = str(value.get("chunk_id") or value.get("id") or "")
            for index, record in enumerate(records):
                if record.chunk_id == chunk_id:
                    return index
    except (TypeError, ValueError):
        return None
    return None
