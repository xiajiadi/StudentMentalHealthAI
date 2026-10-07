from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_pipeline import KnowledgePipeline, SourceRequest
from knowledge_pipeline.config import ChunkConfig, PipelineConfig
from knowledge_pipeline.utils import sha256_file


MODULE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = MODULE_ROOT.parent


def test_batch_exports_approved_chunks_and_isolates_invalid_document(tmp_path: Path) -> None:
    config = PipelineConfig(chunk=ChunkConfig(min_tokens=4, target_tokens=40, max_tokens=160))
    pipeline = KnowledgePipeline(schema_root=PROJECT_ROOT, config=config)
    output = tmp_path / "run"
    run = pipeline.run(
        [
            SourceRequest(MODULE_ROOT / "fixtures/policy/policy.md", input_mode="curated"),
            SourceRequest(MODULE_ROOT / "fixtures/theory/theory.md", input_mode="curated"),
            SourceRequest(MODULE_ROOT / "fixtures/intervention/intervention.md", input_mode="curated"),
            SourceRequest(MODULE_ROOT / "fixtures/invalid/missing_source.md", input_mode="curated"),
            SourceRequest(MODULE_ROOT / "fixtures/invalid/unsupported.txt", input_mode="curated"),
        ],
        output_dir=output,
        timestamp="2026-09-04T00:00:00Z",
        run_id="RUN_batch_fixture",
    )
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    ready = [json.loads(line) for line in (output / "embedding_ready.jsonl").read_text(encoding="utf-8").splitlines()]
    contract_chunks = [json.loads(line) for line in (output / "knowledge_chunks.jsonl").read_text(encoding="utf-8").splitlines()]

    assert len(run.documents) == 4
    assert len([json.loads(line) for line in (output / "knowledge_documents.jsonl").read_text(encoding="utf-8").splitlines()]) == 3
    assert any(item["status"] == "PARSE_FAILED" for item in run.document_runs)
    assert manifest["fail"] >= 1
    assert ready
    assert len(ready) == manifest["chunks"]["embedding_ready"]
    assert all(set(record) == {"chunk_id", "document_id", "text", "context_text", "metadata"} for record in ready)
    assert all(record["metadata"]["embedding_status"] == "not_indexed" for record in ready)
    assert all("context_text" not in record for record in contract_chunks)


def test_m0_demo_population_scope_survives_embedding_ready_export(tmp_path: Path) -> None:
    fixture = MODULE_ROOT / "fixtures/m0_demo/freshman_study_routine.md"
    output = tmp_path / "m0_demo"
    run = KnowledgePipeline(schema_root=PROJECT_ROOT).run(
        [SourceRequest(fixture, input_mode="raw")],
        output_dir=output,
        timestamp="2026-10-08T00:00:00Z",
        run_id="RUN_m0_population_scope",
    )

    rows = [
        json.loads(line)
        for line in (output / "embedding_ready.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert run.export is not None
    assert rows
    assert all(row["metadata"]["target_population"] == ["university_freshman"] for row in rows)


def test_repeat_run_has_stable_ids_and_hashes(tmp_path: Path) -> None:
    config = PipelineConfig(chunk=ChunkConfig(min_tokens=4, target_tokens=40, max_tokens=160))
    requests = [SourceRequest(MODULE_ROOT / "fixtures/policy/policy.md", input_mode="curated")]
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first = KnowledgePipeline(schema_root=PROJECT_ROOT, config=config).run(
        requests, output_dir=first_dir, timestamp="2026-09-04T00:00:00Z", run_id="RUN_repeat"
    )
    second = KnowledgePipeline(schema_root=PROJECT_ROOT, config=config).run(
        requests, output_dir=second_dir, timestamp="2026-09-04T00:00:00Z", run_id="RUN_repeat"
    )
    first_rows = [json.loads(line) for line in (first_dir / "embedding_ready.jsonl").read_text(encoding="utf-8").splitlines()]
    second_rows = [json.loads(line) for line in (second_dir / "embedding_ready.jsonl").read_text(encoding="utf-8").splitlines()]
    assert first.documents[0].document_id == second.documents[0].document_id
    assert [(row["chunk_id"], row["metadata"]["content_hash"]) for row in first_rows] == [
        (row["chunk_id"], row["metadata"]["content_hash"]) for row in second_rows
    ]


def test_real_docling_pdf_and_docx_are_parsed(tmp_path: Path) -> None:
    metadata = {
        "organization": "合成教育资料委员会",
        "published_year": 2025,
        "source_type": "government",
        "source_url": "https://example.invalid/docling",
        "language": "zh-CN",
        "population_scope": ["K12学生"],
        "category": "policy",
        "rights_status": "verified",
        "review_status": "approved",
        "role_scope": ["student", "teacher", "parent"],
        "risk_scope": ["normal", "attention"],
    }
    config = PipelineConfig(chunk=ChunkConfig(min_tokens=4, target_tokens=40, max_tokens=160))
    run = KnowledgePipeline(schema_root=PROJECT_ROOT, config=config).run(
        [
            SourceRequest(MODULE_ROOT / "fixtures/policy/docling_sample.pdf", metadata=metadata),
            SourceRequest(MODULE_ROOT / "fixtures/policy/docling_sample.docx", metadata=metadata),
        ],
        output_dir=tmp_path / "docling",
        timestamp="2026-09-04T00:00:00Z",
        run_id="RUN_docling_tests",
    )
    assert len(run.documents) == 2
    assert {document.parser for document in run.documents} == {"docling"}
    assert all(document.parser_version == "2.125.0" for document in run.documents)
    assert any(block.page_start == 1 for document in run.documents for block in document.blocks)
    assert any(block.kind == "table" for document in run.documents for block in document.blocks)
    assert all(document.parser_metadata["docling_hierarchical_chunk_count"] for document in run.documents)
    assert all(document.parser_metadata["docling_json_keys"] for document in run.documents)
    assert all(item["status"] == "PROCESSED" for item in run.document_runs)


def test_raw_source_remains_immutable_and_cannot_be_output_target(tmp_path: Path) -> None:
    raw_root = tmp_path / "data" / "raw"
    raw_root.mkdir(parents=True)
    source_path = raw_root / "source.md"
    source_path.write_text("# Raw source\n\nDeclared source text.", encoding="utf-8")
    before = sha256_file(source_path)
    config = PipelineConfig(chunk=ChunkConfig(min_tokens=1, target_tokens=10, max_tokens=20))
    pipeline = KnowledgePipeline(schema_root=PROJECT_ROOT, config=config, raw_root=raw_root)
    pipeline.run(
        [SourceRequest(source_path)],
        output_dir=tmp_path / "published",
        timestamp="2026-09-04T00:00:00Z",
        run_id="RUN_raw_guard",
    )
    assert sha256_file(source_path) == before
    with pytest.raises(ValueError, match="RAW_IMMUTABLE"):
        pipeline.run(
            [SourceRequest(source_path)],
            output_dir=raw_root / "published",
            timestamp="2026-09-04T00:00:00Z",
            run_id="RUN_raw_guard_blocked",
        )
