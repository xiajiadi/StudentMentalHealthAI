"""Run the reproducible Round 1 evidence batch from the module directory."""

from __future__ import annotations

import shutil
from pathlib import Path

from knowledge_pipeline import KnowledgePipeline, SourceRequest
from knowledge_pipeline.config import PipelineConfig


MODULE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = MODULE_ROOT.parent
FIXTURES = MODULE_ROOT / "fixtures"
OUTPUT = MODULE_ROOT / "data" / "published" / "round1"


DOCLING_METADATA = {
    "organization": "合成教育资料委员会",
    "author": None,
    "published_year": 2025,
    "source_type": "government",
    "source_url": "https://example.invalid/authorized/docling-fixture",
    "language": "zh-CN",
    "population_scope": ["K12学生"],
    "category": "policy",
    "rights_status": "verified",
    "review_status": "approved",
    "role_scope": ["student", "teacher", "parent"],
    "risk_scope": ["normal", "attention"],
}


def main() -> int:
    duplicate = FIXTURES / "invalid" / "policy_copy.md"
    shutil.copyfile(FIXTURES / "policy" / "policy.md", duplicate)
    config = PipelineConfig.from_file(MODULE_ROOT / "config" / "pipeline.v1.yaml")
    requests = [
        SourceRequest(FIXTURES / "policy" / "policy.md", input_mode="curated"),
        SourceRequest(FIXTURES / "theory" / "theory.md", input_mode="curated"),
        SourceRequest(FIXTURES / "intervention" / "intervention.md", input_mode="curated"),
        SourceRequest(FIXTURES / "policy" / "docling_sample.pdf", metadata=DOCLING_METADATA),
        SourceRequest(FIXTURES / "policy" / "docling_sample.docx", metadata=DOCLING_METADATA),
        SourceRequest(FIXTURES / "invalid" / "policy_copy.md", input_mode="curated"),
        SourceRequest(FIXTURES / "invalid" / "garbled.md", input_mode="curated"),
        SourceRequest(FIXTURES / "invalid" / "missing_source.md", input_mode="curated"),
        SourceRequest(FIXTURES / "invalid" / "unsupported.txt", input_mode="curated"),
    ]
    run = KnowledgePipeline(schema_root=PROJECT_ROOT, config=config).run(
        requests,
        output_dir=OUTPUT,
        timestamp="2026-09-04T00:00:00Z",
        run_id="RUN_knowledge_round1",
    )
    print(f"run_id={run.run_id}")
    print(f"processed_documents={len(run.documents)}")
    print(f"contract_documents={run.export.document_count if run.export else 0}")
    print(f"contract_chunks={run.export.chunk_count if run.export else 0}")
    print(f"embedding_ready={run.export.embedding_ready_count if run.export else 0}")
    print(f"source_duplicates={run.duplicates.source_duplicate_count}")
    print(f"chunk_duplicates={run.duplicates.chunk_duplicate_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

