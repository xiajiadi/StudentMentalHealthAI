# Knowledge Round 1 Acceptance

Evidence date: 2026-09-04  
Module: `04_knowledge-pipeline`  
Contract: `knowledge.v1`, root release `v0.1.0 FROZEN`

## 1 Conclusion

**PASS** for the Round 1 module scope.

The required parser, canonical model, structural strategies, provenance,
quality/review gates, frozen-contract validation, deterministic IDs, duplicate
flagging, and no-vector export are implemented and locally verified. The
negative fixtures intentionally produce quality/parse failures and are not
published. MinerU remains explicitly `PENDING` and is not counted as an
integrated provider.

This is an engineering acceptance of synthetic/authorized fixtures. It is not
clinical validation, expert approval of real knowledge, or production release
acceptance.

## 2 Implemented

- `CanonicalDocument` and format-neutral structural blocks;
- `DocumentParser` abstraction and explicit `ParserRouter`;
- Docling adapter for PDF, DOCX, HTML/HTM routing;
- curated Markdown adapter with YAML front matter and
  `human_curated=true` enforcement;
- policy, theory, and intervention strategies with distinct boundaries;
- conservative text normalization, SHA-256 source/content hashes, and stable
  IDs;
- non-destructive file/content duplicate detection;
- structured PASS/WARN/FAIL quality issues;
- `pending_review`, `approved`, and `rejected` review gate;
- strict `knowledge.v1` document/chunk projection and JSON Schema execution;
- `knowledge_documents.jsonl`, `knowledge_chunks.jsonl`,
  `embedding_ready.jsonl`, review/quality/log files, and `manifest.json`;
- document-level error isolation and stage timing records;
- no LLM rewrite and no embedding vector generation.

## 3 Open-source Reuse

### Docling

`docling==2.125.0` was installed in the module `.venv` and actually used.
`DocumentConverter` produced a v2 `DoclingDocument` for the synthetic PDF and
DOCX fixtures. The adapter called/verified `export_to_markdown`,
`export_to_dict`, and `docling.chunking.HierarchicalChunker`; the native
chunker count is recorded in parser metadata while the final domain chunks are
created from canonical blocks.

### RAGFlow

The current `main` source was read at revision
`f99b9cd44b00f99dc79537ecdad710c5d693c902`:

- `rag/app/laws.py`: hierarchy-aware `tree_merge` for law-like chapter,
  section, and article structure;
- `rag/app/paper.py`: abstract kept as an intact semantic unit;
- `rag/app/manual.py`: ordered section IDs, structural grouping, page/layout
  context, and table handling;
- `rag/app/book.py` and `rag/app/table.py`: book/table-specific parsing
  boundaries and row-as-unit treatment.

No RAGFlow source was copied or adapted. Its structural ideas informed the
three small project-owned strategies and their tests.

### Other references

Unstructured's `partition`/element/metadata/clean/chunk model and IBM
docling-pipelines' operator, quality, dedup, redaction, and storage stages were
studied as architecture references. Neither is a V0.1 runtime dependency.

## 4 Third-party licenses

Full notices are in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

- Docling: MIT; active parser dependency.
- Docling Core: MIT; resolved transitive dependency.
- MinerU 3.4.5: custom MinerU Open Source License, Apache 2.0 plus additional
  terms; optional and `PENDING`.
- RAGFlow: Apache-2.0; research reference only.
- Unstructured: Apache-2.0; research reference only.
- IBM docling-pipelines: MIT; research reference only.
- jsonschema: MIT; direct contract-validation dependency.
- PyYAML: MIT; direct YAML dependency.
- python-docx and ReportLab: test-only fixture-generation dependencies.

## 5 Pipeline

```text
Input
  -> Source intake + SHA-256 + input_mode
  -> Parser Router
  -> Docling / Curated Markdown adapter
  -> CanonicalDocument + blocks
  -> Policy / Theory / Intervention chunk strategy
  -> Metadata + text/context_text
  -> File/content dedup flagging
  -> PASS/WARN/FAIL quality gate
  -> Human review gate
  -> knowledge.v1 validation
  -> contract JSONL + embedding_ready.jsonl + manifest
```

Raw files are read only. A run cannot place its output directory below the
configured raw root.

## 6 Parser Tests

The reproducible evidence command was:

```powershell
.venv\Scripts\python.exe -X utf8 scripts\run_round1.py
```

Result:

| Input | Parser | Result | Evidence |
| --- | --- | --- | --- |
| `fixtures/policy/docling_sample.pdf` | Docling 2.125.0 | PASS | title, heading/article text, page 1, table block |
| `fixtures/policy/docling_sample.docx` | Docling 2.125.0 | PASS | title, heading/article text, table block |
| `fixtures/policy/policy.md` | Curated Markdown 1.0.0 | PASS/WARN | YAML metadata, policy headings/articles |
| `fixtures/theory/theory.md` | Curated Markdown 1.0.0 | PASS | concept/research sections |
| `fixtures/intervention/intervention.md` | Curated Markdown 1.0.0 | PASS | manual chunk marker and caution retained |
| `fixtures/invalid/unsupported.txt` | Router | `PARSE_FAILED` | document-level failure record; batch continued |

Implemented routing includes PDF, DOCX, HTML/HTM, Markdown, and `.markdown`.
HTML was not included in the actual Round 1 input batch and is not claimed as
an executed format test.

## 7 Chunking Evidence

### Policy

`第十二条`, `第十三条`, and `第十四条` each remained in separate chunks in
the policy fixture. Each chunk carries chapter/section/article context; a long
single article test split only after the article exceeded the configured
limit, retaining `Article: 第十二条` in every resulting chunk.

### Theory

The concepts `概念：压力`, `概念：应对`, and `研究发现：支持网络` remained in
three separate semantic units. The strategy does not merge unrelated concepts
to fill the target token baseline.

### Intervention

The curated `exam-support` manual unit contains scenario, suggestion, steps,
and `注意事项` in one chunk. Its metadata records
`caution/limitation retained`.

## 8 Provenance

Every source record contains source ID, filename, file type, size, received
time, input mode, and `source_hash`. Every exported chunk contains
`document_id`, source filename/hash, section, page range when supplied,
heading path, citation locator, parser/chunker versions, and content hash.
The `embedding_ready.jsonl` rows retain the same document/chunk IDs and rich
metadata.

## 9 Dedup

The final evidence batch used `policy.md` and an identical `policy_copy.md`.
The manifest recorded:

- `source_duplicates`: 1 duplicate source;
- `chunk_duplicates`: 3 duplicate normalized chunk groups;
- both source identities remained present;
- no source or chunk was deleted automatically.

## 10 Quality Gate

The final manifest reported:

| Aggregate | Documents | Meaning in this batch |
| --- | ---:| --- |
| PASS | 4 | valid synthetic/authorized fixture runs |
| WARN | 3 | duplicate, pending/unknown rights, or replacement/OCR signals |
| FAIL | 2 | missing source metadata and unsupported-format parse failure |

There were 18 structured quality issue records. The failing inputs were
retained in the manifest/audit evidence but were excluded from the strict
contract export and embedding-ready corpus.

## 11 Contract

The frozen root schema was not modified. A post-run validation pass accepted:

- 7 `knowledge.v1` document records;
- 15 `knowledge.v1` chunk records;
- 25 `logging.v1` stage records.

An extra `context_text` field was deliberately rejected by the strict
`knowledge.v1` validator. It remains only in the separate embedding-ready
record, which preserves the frozen contract boundary.

## 12 Export

Output directory:

`data/published/round1/`

| File | Result |
| --- | --- |
| `knowledge_documents.jsonl` | 7 contract-valid documents |
| `knowledge_chunks.jsonl` | 15 contract-valid chunks |
| `embedding_ready.jsonl` | 14 rows; no vector field |
| `manifest.json` | present; run/config/parser/chunker/quality/dedup/timing evidence |
| `review_queue.jsonl` | 15 review decisions; one `pending_review` item |
| `quality_issues.jsonl` | 18 structured issues |
| `pipeline_logs.jsonl` | 25 logging.v1-valid records |

The one approved-looking text blocked from embedding-ready output had
`rights_status=unknown`; it remained in the review/audit material.

## 13 Reproducibility

`test_repeat_run_has_stable_ids_and_hashes` ran the same source, pipeline
version, configuration, fixed timestamp, and run ID twice. Document IDs, chunk
IDs, content hashes, and embedding-ready records matched. Wall-clock duration
and live timestamps remain observational manifest fields and do not participate
in IDs.

## 14 MinerU Status

**PENDING / OPTIONAL**

MinerU `3.4.5` was researched but not installed or executed. Its current
package metadata requires Python `<3.14`, while this environment is Python
`3.14.6`; its repository also uses a custom Apache-based license with extra
commercial-threshold, online-attribution, and termination terms. The adapter
boundary is present and fails explicitly when unavailable. See
[MINERU_LICENSE_AND_COMPATIBILITY.md](MINERU_LICENSE_AND_COMPATIBILITY.md).

## 15 Tests

Executed commands and results:

```text
.venv\Scripts\python.exe -m compileall -q src tests
.venv\Scripts\python.exe -m pytest -q
18 passed, 2 warnings

04_knowledge-pipeline\.venv\Scripts\python.exe -m pytest 00_architecture\tests\test_contracts.py -q
13 passed
```

The two warnings are upstream Docling deprecation warnings from PDF/table/OCR
internals; they did not fail the tests. The module tests include real Docling
PDF/DOCX conversion and do not use parser mocks for those cases.

## 16 Files Changed

### Module documentation/configuration

- `.gitignore`
- `README.md`
- `KNOWLEDGE_TECHNICAL_DECISION_V1.md`
- `THIRD_PARTY_NOTICES.md`
- `TASK.md`
- `pyproject.toml`
- `uv.lock`
- `config/pipeline.v1.yaml`
- `reports/MINERU_LICENSE_AND_COMPATIBILITY.md`
- `reports/KNOWLEDGE_ROUND1_ACCEPTANCE.md`

### Runtime implementation

- `src/knowledge_pipeline/__init__.py`
- `src/knowledge_pipeline/config.py`
- `src/knowledge_pipeline/utils.py`
- `src/knowledge_pipeline/cli.py`
- `src/knowledge_pipeline/logging_support.py`
- `src/knowledge_pipeline/domain/__init__.py`
- `src/knowledge_pipeline/domain/block.py`
- `src/knowledge_pipeline/domain/chunk.py`
- `src/knowledge_pipeline/domain/document.py`
- `src/knowledge_pipeline/domain/source.py`
- `src/knowledge_pipeline/parsers/__init__.py`
- `src/knowledge_pipeline/parsers/base.py`
- `src/knowledge_pipeline/parsers/docling_parser.py`
- `src/knowledge_pipeline/parsers/markdown_parser.py`
- `src/knowledge_pipeline/parsers/mineru_parser.py`
- `src/knowledge_pipeline/parsers/router.py`
- `src/knowledge_pipeline/chunking/__init__.py`
- `src/knowledge_pipeline/chunking/base.py`
- `src/knowledge_pipeline/chunking/policy.py`
- `src/knowledge_pipeline/chunking/theory.py`
- `src/knowledge_pipeline/chunking/intervention.py`
- `src/knowledge_pipeline/dedup/__init__.py`
- `src/knowledge_pipeline/dedup/detector.py`
- `src/knowledge_pipeline/quality/__init__.py`
- `src/knowledge_pipeline/quality/gate.py`
- `src/knowledge_pipeline/review/__init__.py`
- `src/knowledge_pipeline/review/gate.py`
- `src/knowledge_pipeline/validation/__init__.py`
- `src/knowledge_pipeline/validation/contracts.py`
- `src/knowledge_pipeline/validation/mapping.py`
- `src/knowledge_pipeline/export/__init__.py`
- `src/knowledge_pipeline/export/writer.py`
- `src/knowledge_pipeline/service/__init__.py`
- `src/knowledge_pipeline/service/pipeline.py`

### Fixtures/scripts/tests

- `04_knowledge_pipeline_fixture_generator.py`
- `scripts/run_round1.py`
- `fixtures/policy/policy.md`
- `fixtures/policy/docling_sample.pdf`
- `fixtures/policy/docling_sample.docx`
- `fixtures/theory/theory.md`
- `fixtures/intervention/intervention.md`
- `fixtures/invalid/garbled.md`
- `fixtures/invalid/missing_source.md`
- `fixtures/invalid/unsupported.txt`
- `fixtures/invalid/policy_copy.md`
- `tests/conftest.py`
- `tests/unit/test_chunk_strategies.py`
- `tests/unit/test_quality_dedup_review.py`
- `tests/unit/test_contract_and_exports.py`
- `tests/unit/test_logging_and_config.py`
- `tests/unit/test_router_and_mineru.py`
- `tests/integration/test_pipeline.py`
- `data/raw/.gitkeep`
- `data/curated/.gitkeep`
- `data/canonical/.gitkeep`
- `data/chunks/.gitkeep`
- `data/published/.gitkeep`

The local generated run directory `data/published/round1/` is ignored by the
module `.gitignore` as evidence output rather than source data. The `.venv`
and model/cache files are also local and are not repository deliverables.

## 17 Known Limitations

- MinerU has not been installed or compared against Docling.
- HTML routing is implemented but was not executed in the Round 1 evidence
  batch.
- The configured `approximate_unicode_v1` token counter is a deterministic
  engineering baseline, not the final embedding model tokenizer. Retrieval
  benchmarking must tune `min/target/max` in Round 2.
- Complex scanned PDFs, figures, OCR confidence review, and broad table
  regression coverage are not a complete corpus acceptance.
- Human approval in this run is represented by explicit synthetic fixture
  metadata; no real mental-health knowledge corpus was approved.
- The local workspace has no Git metadata, so there is no commit/diff or remote
  CI evidence in this report.

## 18 Blockers

No blocker prevents the Round 1 local module acceptance.

The following remain open before making a fallback provider or real corpus
production-ready: a Python 3.12 MinerU compatibility/license review, a reviewed
source registry with rights decisions, human expert approval, and Round 2
retrieval benchmark evidence.

## 19 Recommendation

Proceed to Knowledge Round 2 for tokenizer/chunk benchmark design and a
reviewed complex-document corpus. Keep Docling as the active V0.1 parser;
keep MinerU optional until its separate environment and license obligations
are resolved. Do not connect this output to a production RAG index until the
review and rights gates are backed by the project owner’s approved corpus.
