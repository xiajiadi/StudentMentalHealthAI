# M0 synthetic learning-planning fixtures

These project-authored Markdown fixtures exist only for isolated Synthetic Demo engineering. `review_status: approved` and `rights_status: verified` mean M0 demo eligibility for this locally authored fixture, as declared by `review_semantics`; they do not mean human or specialist review, external source approval, or suitability for real students. Keep `human_curated: false` and preserve the fixture's population scope exactly. Do not use these records in the production publication.

The current freshman fixture is scoped only to `university_freshman`. The student fixture is separately authored and scoped only to `university_student`; neither fixture broadens the other's population.

## Regenerate the isolated university-student demo corpus

Run from the repository root in PowerShell. This writes the Pipeline export to its own staging directory and does not build a RAG index or start services:

```powershell
$repo = (Resolve-Path '.').Path
$module = Join-Path $repo '04_knowledge-pipeline'
$fixture = Join-Path $module 'fixtures/m0_demo/university_study_task_planning.md'
$output = Join-Path $module 'data/demo_staging/m0-university-student'
& (Join-Path $module '.venv/Scripts/python.exe') -m knowledge_pipeline.cli `
  --input $fixture `
  --input-mode raw `
  --schema-root $repo `
  --output $output
```

The output includes `embedding_ready.jsonl`, `knowledge_chunks.jsonl`, `review_queue.jsonl`, and a manifest. `review_semantics` is retained in the embedding-ready metadata for demo consumers; it is intentionally absent from the frozen `knowledge.v1` chunk projection. The chunk text itself also states that it is Synthetic Demo material and not reviewed educational evidence.

For a later Backend end-to-end run, configure the isolated RAG process to read only this output's `embedding_ready.jsonl`, `knowledge_documents.jsonl`, and `review_queue.jsonl`, and give it a separate RAG config whose BM25 path points to a new demo-only directory. Do not reuse or overwrite `data/indexes/m0-demo`, the production corpus, or the root-owned services. The Backend's current population remains `university_student`; this fixture matches that exact filter. This command alone proves no retrieval, safety, citation-validation, generation, or 7B behavior.
