"""Command line entry point for a small, reproducible batch."""

from __future__ import annotations

import argparse
from pathlib import Path

from .config import PipelineConfig
from .domain.source import SourceRequest
from .service.pipeline import KnowledgePipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the StudentMentalHealthAI knowledge pipeline")
    parser.add_argument("--input", action="append", required=True, help="input file; repeat for a batch")
    parser.add_argument("--output", required=True, help="output directory")
    parser.add_argument("--schema-root", default="..", help="StudentMentalHealthAI root containing 00_architecture")
    parser.add_argument("--input-mode", choices=("raw", "curated"), default="raw")
    parser.add_argument("--config", help="optional YAML pipeline configuration")
    args = parser.parse_args()
    config = PipelineConfig.from_file(Path(args.config)) if args.config else None
    pipeline = KnowledgePipeline(schema_root=Path(args.schema_root), config=config)
    run = pipeline.run(
        [SourceRequest(Path(value), input_mode=args.input_mode) for value in args.input],
        output_dir=Path(args.output),
    )
    print(f"run_id={run.run_id}")
    print(f"documents={len(run.documents)} chunks={len(run.chunks)} embedding_ready={run.export.embedding_ready_count if run.export else 0}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
