from __future__ import annotations

from pathlib import Path

from knowledge_pipeline.chunking import PolicyChunkStrategy
from knowledge_pipeline.config import ChunkConfig, PipelineConfig
from knowledge_pipeline.dedup.detector import detect_duplicates
from knowledge_pipeline.domain.source import SourceRecord, SourceRequest
from knowledge_pipeline.parsers.markdown_parser import MarkdownCuratedParser
from knowledge_pipeline.quality.gate import QualityGate
from knowledge_pipeline.review.gate import ReviewGate


MODULE_ROOT = Path(__file__).resolve().parents[2]


def parse(name: str, config: PipelineConfig):
    source = SourceRecord.from_request(SourceRequest(MODULE_ROOT / "fixtures" / name, input_mode="curated"))
    return source, MarkdownCuratedParser().parse(source, config)


def test_quality_valid_fixture_passes() -> None:
    config = PipelineConfig(chunk=ChunkConfig(min_tokens=4, target_tokens=40, max_tokens=160))
    source, document = parse("policy/policy.md", config)
    chunks = PolicyChunkStrategy(config.chunk).chunk(document)
    report = QualityGate(config.chunk).evaluate(document, chunks)

    assert report.status == "PASS"
    assert report.fail_count == 0


def test_quality_missing_source_fails_and_garbled_content_warns() -> None:
    config = PipelineConfig(chunk=ChunkConfig(min_tokens=4, target_tokens=40, max_tokens=160))
    _, missing = parse("invalid/missing_source.md", config)
    missing_chunks = PolicyChunkStrategy(config.chunk).chunk(missing)
    missing_report = QualityGate(config.chunk).evaluate(missing, missing_chunks)
    assert missing_report.status == "FAIL"
    assert {issue.code for issue in missing_report.issues} >= {"MISSING_SOURCE_ORGANIZATION", "MISSING_POPULATION_SCOPE", "CONTRACT_INVALID"} or "MISSING_SOURCE_ORGANIZATION" in {issue.code for issue in missing_report.issues}

    _, garbled = parse("invalid/garbled.md", config)
    garbled_chunks = PolicyChunkStrategy(config.chunk).chunk(garbled)
    garbled_report = QualityGate(config.chunk).evaluate(garbled, garbled_chunks)
    assert garbled_report.status == "WARN"
    assert "REPLACEMENT_CHARACTER" in {issue.code for issue in garbled_report.issues}


def test_duplicate_detection_keeps_both_provenances(tmp_path: Path) -> None:
    original = MODULE_ROOT / "fixtures" / "policy" / "policy.md"
    copy = tmp_path / "same-content.md"
    copy.write_bytes(original.read_bytes())
    first = SourceRecord.from_request(SourceRequest(original, input_mode="curated"))
    second = SourceRecord.from_request(SourceRequest(copy, input_mode="curated"))
    config = PipelineConfig(chunk=ChunkConfig(min_tokens=4, target_tokens=40, max_tokens=160))
    first_document = MarkdownCuratedParser().parse(first, config)
    second_document = MarkdownCuratedParser().parse(second, config)
    strategy = PolicyChunkStrategy(config.chunk)
    chunks = strategy.chunk(first_document) + strategy.chunk(second_document)
    report = detect_duplicates([first, second], chunks)

    assert report.source_duplicate_count == 1
    assert report.chunk_duplicate_count == len(strategy.chunk(first_document))
    assert first.source_id != second.source_id
    assert first_document.document_id != second_document.document_id


def test_review_gate_blocks_pending_and_unknown_rights() -> None:
    config = PipelineConfig(chunk=ChunkConfig(min_tokens=4, target_tokens=40, max_tokens=160))
    _, document = parse("policy/policy.md", config)
    chunk = PolicyChunkStrategy(config.chunk).chunk(document)[0]
    gate = ReviewGate()
    assert gate.is_publishable(chunk, quality_status="PASS")
    chunk.metadata["review_status"] = "pending"
    assert gate.decision_for(chunk) == "pending_review"
    assert not gate.is_publishable(chunk, quality_status="PASS")
    chunk.metadata["review_status"] = "approved"
    chunk.metadata["rights_status"] = "unknown"
    assert not gate.is_publishable(chunk, quality_status="PASS")

