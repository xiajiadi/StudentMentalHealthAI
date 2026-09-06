# Third-Party Notices

Evidence date: 2026-09-04. Versions below are the versions observed from the
current PyPI metadata or the current default branch commit at that date. The
repository has no Git metadata in the local workspace, so upstream commit
values are recorded explicitly where the branch has no release version.

| Project | Repository | Version / revision | License | Used as | Integration type | Files / APIs referenced | Source copied/adapted | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Docling | https://github.com/docling-project/docling | `2.125.0`; main `b2d333e12260fc9cb74d8e8748b0d45505afcabb` | MIT | Primary PDF/DOCX/HTML parser and native chunk baseline | Direct PyPI dependency plus adapter | `DocumentConverter`; `DoclingDocument`; `export_to_markdown`; `export_to_dict`; `docling.chunking.HierarchicalChunker` | No source copied | Actually installed and run in `.venv`; current local parser evidence is in the acceptance report. |
| Docling Core | https://github.com/docling-project/docling-core | `2.94.1` resolved with Docling | MIT | Transitive document model/chunking support | Transitive dependency | `DoclingDocument` and chunking types exposed by Docling | No source copied | Version was installed by the pinned Docling package. |
| MinerU | https://github.com/opendatalab/MinerU | `3.4.5`; master `4fe4bde114a23ee5dd637eae99b767f4669bf58c` | MinerU Open Source License, Apache 2.0 plus additional terms | Optional complex/scanned-document fallback | Adapter boundary only; not installed | Package metadata, `mineru` CLI/document-format claims, `LICENSE.md` | No source copied | Requires Python `<3.14`; custom license requires separate review. Status: `PENDING`. |
| RAGFlow | https://github.com/infiniflow/ragflow | main `f99b9cd44b00f99dc79537ecdad710c5d693c902` | Apache-2.0 | Domain chunking reference | Research/design reference only | `rag/app/laws.py`, `paper.py`, `book.py`, `manual.py`, `table.py`; hierarchy/token utilities | No source copied or adapted | Used to shape policy/theory/intervention boundaries; no framework dependency. |
| Unstructured | https://github.com/Unstructured-IO/unstructured | main `d68ab0fda9bcac317b7c033d42412d716ba1d790` | Apache-2.0 | ETL architecture reference | Research/design reference only | `partition` routing, elements, metadata, cleaning/chunking concepts | No source copied or adapted | Not a V0.1 production dependency. |
| IBM docling-pipelines | https://github.com/IBM/docling-pipelines | `1.0.0` metadata; main `bed85842ef00a1f90df11589d299cf00645ca262` | MIT | Curation/DAG/operator architecture reference | Research/design reference only | flow/operator, quality, dedup, PII, storage and embedding-boundary concepts | No source copied or adapted | Not installed; full framework is intentionally outside V0.1 scope. |
| jsonschema | https://github.com/python-jsonschema/jsonschema | `4.26.0` observed | MIT | Execute frozen `knowledge.v1` schema | Direct bounded dependency | `validator_for`, `iter_errors` | No source copied | Required for contract validation. |
| PyYAML | https://github.com/yaml/pyyaml | `6.0.3` observed | MIT | Curated Markdown front matter and pipeline config | Direct bounded dependency | `safe_load` | No source copied | Only safe YAML loading is used. |
| python-docx | https://github.com/python-openxml/python-docx | `1.2.0` observed | MIT | Synthetic DOCX fixture generation in tests | Test-only dependency | `Document`, headings, tables | No source copied | Not used as the production parser; Docling parses DOCX. |
| ReportLab | https://github.com/ReportLab/reportlab | `4.5.1` observed | BSD-style | Synthetic PDF fixture generation in tests | Test-only dependency | `Canvas`, `TTFont` | No source copied | Not used as a production PDF parser. |

## License decision

Docling is the only document parser dependency required for V0.1 and has a
clear MIT license. MinerU is not treated as Apache-2.0-only: its repository
declares a custom license with additional thresholds, online attribution, and
termination terms. No mandatory integration or distribution decision is made
for MinerU in this round.
