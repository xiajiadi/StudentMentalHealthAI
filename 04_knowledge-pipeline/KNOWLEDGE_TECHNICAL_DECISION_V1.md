# Knowledge Technical Decision V1

Document Version: 1.0  
Status: PROVISIONALLY_FROZEN  
Date: 2026-09-04  
Depends on: Contract v0.1.0 FROZEN

This decision records the Round 1 implementation boundary. It does not change
the root contracts, make a clinical claim, or approve production knowledge
without a human reviewer.

## 1. Knowledge module role

04 owns controlled document intake, parser adaptation, normalization, domain
chunking, provenance, duplicate detection, quality reporting, review gating,
and export. It does not answer user questions or interpret an assessment.

## 2. Knowledge/RAG boundary

The module ends at contract-valid `knowledge.v1` projections and
`embedding_ready.jsonl`. 05 · RAG Engine owns embedding, indexing, retrieval,
hybrid search, reranking, and citations returned for a query. This module does
not contain BGE-M3, ChromaDB, BM25, top-k, reranking, query expansion, or LLM
answer generation.

## 3. Open-source-first principle

Document parsing is an adapter problem, not a reason to recreate PDF, DOCX,
OCR, layout, reading order, or table recognition. Maintained upstream
components are called directly where they solve the problem; project code
owns only contract mapping, policy, review, and orchestration.

## 4. Docling primary parser

`docling==2.125.0` is the primary parser. `DoclingParser` calls
`DocumentConverter`, consumes the v2 `DoclingDocument`, records parser status
and item provenance, and verifies Markdown and JSON export representations.
Round 1 also invokes the maintained `HierarchicalChunker` as a native baseline
and records its count. Final domain chunks still use canonical blocks so that
policy/theory/intervention rules do not depend on a Docling object.

Observed local evidence: PDF and DOCX fixtures both parsed successfully on
Python 3.14.6. The PDF produced page references and a table block; the DOCX
produced heading, paragraph, and table blocks. The first PDF run included model
initialization and is recorded in the acceptance report.

## 5. MinerU fallback

MinerU is an optional provider boundary, not a production dependency in V0.1.
`MinerUParser` fails explicitly when unavailable and never silently substitutes
unverified output. Its current package metadata requires Python `<3.14`; the
development environment is Python 3.14.6. The custom MinerU Open Source License
also has additional commercial-threshold and online-service attribution terms.
Status is therefore `PENDING`, not integrated or tested.

## 6. RAGFlow domain chunk reference

The current RAGFlow `main` sources were inspected at the recorded commit in
`THIRD_PARTY_NOTICES.md`. `rag/app/laws.py` uses hierarchy-aware tree merging
for law-like documents; `paper.py` keeps the abstract as an intact unit;
`manual.py` keeps ordered sections, derives section IDs, preserves table
context, and places page/layout context around chunks. These are design
references only. No RAGFlow source was copied into this module.

## 7. CanonicalDocument

All parser adapters return `CanonicalDocument`. It contains a stable document
ID, title, source record, language, structural blocks, explicit metadata,
parser/version information, and parser evidence. Downstream chunking, quality,
validation, review, and export consume only this abstraction.

## 8. Parser Adapter

`DocumentParser` is the adapter interface. The concrete adapters are:

- `DoclingParser` for PDF, DOCX, HTML, and HTM;
- `MarkdownCuratedParser` for UTF-8 Markdown with YAML front matter;
- `MinerUParser` as an explicit optional provider boundary.

The router is suffix-based and explicit. Unsupported formats create a
document-level `PARSE_FAILED` record instead of aborting a batch.

## 9. Parser Router

The router resolves one parser per source type. Optional providers are not
selected implicitly. A future fallback policy must be added as a reviewed
configuration and must retain both parser attempts and their versions.

## 10. Raw/Curated dual input

Every source records `input_mode` as `raw` or `curated`. Raw input is hashed
and read only; the pipeline refuses to place an output directory under the raw
root. Curated Markdown must declare `human_curated: true` when submitted as a
curated source.

## 11. Raw immutable

`data/raw` is an evidence boundary. The pipeline never edits, overwrites,
normalizes in place, or deletes source files. Normalized text and derived
objects are written only to output/canonical/published locations.

## 12. Policy/Theory/Intervention strategies

The category selects a real strategy:

- `PolicyChunkStrategy` preserves chapter, section, and article units. An
  overlong article is secondarily split while retaining article context.
- `TheoryChunkStrategy` starts a unit at each section/concept/research finding
  heading and does not merge unrelated concepts to fill a target.
- `InterventionChunkStrategy` groups scenario, strategy, steps, limitations,
  and warnings. Curated manual chunk markers take precedence.

These differences are covered by unit tests and are not aliases of one fixed
splitter.

## 13. Semantic-first chunking

The order is semantic boundary, structural boundary, then configured token
limit. Secondary splitting first tries paragraph/sentence boundaries and uses
a last-resort bounded split only for one still-overlong sentence. No fixed
character window is the primary algorithm. `min_tokens`, `target_tokens`, and
`max_tokens` are configuration, not claims of retrieval optimality.

## 14. text/context_text separation

`text` is the source excerpt after conservative line/whitespace cleanup.
`context_text` adds document, source, section, and strategy context for future
embedding. It never replaces or paraphrases the source excerpt. The strict
`knowledge.v1` projection contains `text`; the embedding-ready line carries
both fields.

## 15. Metadata

Internal metadata includes document/chunk IDs, layer, title, author,
organization, year, language, target population, topic, role scope, authority
level, source URL/filename/hash, page range, section, heading path, parser and
chunker versions, pipeline version, curation/review/rights status, content
hash, token estimate, and embedding status. Missing declared facts stay null
or empty internally and fail the strict projection when the frozen contract
requires a non-empty field; the pipeline does not guess them.

## 16. Stable ID

Source IDs are derived from source hash, filename, and input mode. Document IDs
are derived from source identity, pipeline version, configuration hash, and
title. Chunk IDs are derived from document identity, strategy/version,
position, location, and excerpt. Re-running the same source/config produces
the same document/chunk IDs; changing excerpt or location changes the digest.

## 17. SHA-256

Source files use `source_hash=sha256:<hex>`. Documents use a normalized content
hash. Chunks use normalized excerpt `content_hash=sha256:<hex>`. The displayed
excerpt preserves full-width punctuation; compatibility normalization is used
only for hashing and duplicate detection.

## 18. Dedup

File duplicates are detected by source hash. Chunk duplicates are detected by
normalized content hash, even when they originate from different files. The
pipeline flags duplicates and keeps every source/document/chunk provenance;
it never deletes a source automatically.

## 19. Quality Gate

Quality issues are structured records with code, severity, message, IDs, and
details. Current checks cover empty documents/chunks, missing source
provenance, missing layer or population, missing organization, very short or
long chunks, unverified rights, pending review, replacement characters,
suspicious OCR, malformed heading jumps, contract errors, and duplicates.
The aggregate is `PASS`, `WARN`, or `FAIL`.

## 20. Human Review Gate

Internal review states are `pending_review`, `approved`, and `rejected`.
Production publication requires `approved`, `rights_status=verified`, and no
quality failure. A pending, rejected, or rights-unknown item remains in the
audit/review output and cannot enter `embedding_ready.jsonl`.

## 21. No LLM rewrite

V0.1 has LLM enrichment off. There is no summarization, paraphrase, or model
replacement of official text. Future summaries, keywords, or questions must
be separate `derived_metadata` and never become canonical source text.

## 22. knowledge.v1

The root `00_architecture/schemas/knowledge.v1.schema.json` remains unchanged.
Documents and chunks are projected to the frozen schema and validated with
`jsonschema` before export. Extra embedding fields are intentionally kept in a
separate embedding-ready record rather than silently adding fields to the
frozen contract.

## 23. Embedding-ready boundary

Each line in `embedding_ready.jsonl` contains `chunk_id`, `document_id`,
`text`, `context_text`, and rich `metadata`. `embedding_status` remains
`not_indexed`; no vector or embedding model call is made here.

## 24. Manifest

Each run writes `manifest.json` with run ID, pipeline and contract versions,
timestamp, configuration/hash, source records, document statuses, chunk
counts, PASS/WARN/FAIL counts, duplicate groups, parser/chunker versions,
stage timings, and the no-embedding assertion. The manifest also preserves
document-level parse failures.

## 25. Reproducibility

IDs and content hashes are deterministic for the same source/config/version.
Tests compare repeated contract/embedding records with a fixed timestamp and
run ID. Wall-clock stage durations and a live run timestamp are intentionally
observational fields and are not used in IDs.

## 26. License governance

Direct dependencies and researched upstream projects are listed in
`THIRD_PARTY_NOTICES.md`. MinerU's custom license is recorded verbatim in
scope and treated as a deployment review item. No code from RAGFlow,
Unstructured, or IBM docling-pipelines is copied or adapted in V0.1.

## 27. V0.1/V0.2/V1.0

- V0.1: local Docling primary path, curated Markdown, three domain strategies,
  provenance, review/quality/dedup, contract validation, and export.
- V0.2: benchmark tokenizer/chunk parameters, complex-document corpus,
  reviewed optional fallback, and broader operator evidence.
- V1.0: only after retrieval evaluation, license/deployment approval, human
  curation operations, and cross-module integration acceptance.

## 28. Tests

The module tests cover domain strategies, manual curation, long-article
secondary splitting, contract mapping, invalid objects, duplicate detection,
review blocking, raw immutability, failure isolation, deterministic reruns,
and real Docling PDF/DOCX parsing. The acceptance report records the exact
commands and counts.

## 29. Acceptance

Round 1 is accepted only when all required local evidence is present: valid
contract projections, actual PDF/DOCX/Markdown runs, distinct strategy
behavior, stable IDs/hashes, non-destructive dedup, actionable quality issues,
review gating, export/manifest files, and passing tests. MinerU remains an
explicit optional `PENDING` item and is not represented as completed.

