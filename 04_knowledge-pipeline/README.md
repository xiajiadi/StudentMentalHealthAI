# 04 · Knowledge Pipeline

This module turns public, authorised, or project-curated documents into
reviewable `knowledge.v1` documents and chunks. It stops at the
embedding-ready boundary: it does not create embeddings, run retrieval, or
generate answers.

## Local setup

The module is intentionally isolated from the system Python. From this
directory, create a project environment and install the pinned runtime plus
test extras:

```powershell
uv sync --locked --extra test
```

The Docling models/cache are external runtime data. Keep them on the D: drive
on this machine; do not add model files to the repository.

## Run a batch

```powershell
.venv\Scripts\python.exe -m knowledge_pipeline.cli `
  --input fixtures\policy\policy.md `
  --output data\published\round1 `
  --schema-root ..
```

The command writes contract projections, an audit/review queue,
`embedding_ready.jsonl`, and `manifest.json`. Only chunks with both
`review_status=approved` and `rights_status=verified` are eligible for the
embedding-ready file. No vector is produced.

## Design and evidence

- [KNOWLEDGE_TECHNICAL_DECISION_V1.md](KNOWLEDGE_TECHNICAL_DECISION_V1.md)
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- [reports/KNOWLEDGE_ROUND1_ACCEPTANCE.md](reports/KNOWLEDGE_ROUND1_ACCEPTANCE.md)
- [reports/MINERU_LICENSE_AND_COMPATIBILITY.md](reports/MINERU_LICENSE_AND_COMPATIBILITY.md)
