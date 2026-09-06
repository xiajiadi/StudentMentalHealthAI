from __future__ import annotations

from pathlib import Path

from knowledge_pipeline.chunking import InterventionChunkStrategy, PolicyChunkStrategy, TheoryChunkStrategy
from knowledge_pipeline.config import ChunkConfig, PipelineConfig
from knowledge_pipeline.domain.source import SourceRecord, SourceRequest
from knowledge_pipeline.parsers.markdown_parser import MarkdownCuratedParser

from conftest import declared_metadata


MODULE_ROOT = Path(__file__).resolve().parents[2]


def parse_fixture(name: str, category: str):
    config = PipelineConfig(chunk=ChunkConfig(min_tokens=4, target_tokens=40, max_tokens=80))
    request = SourceRequest(MODULE_ROOT / "fixtures" / name, input_mode="curated")
    source = SourceRecord.from_request(request)
    return MarkdownCuratedParser().parse(source, config)


def test_policy_keeps_articles_as_structural_units() -> None:
    document = parse_fixture("policy/policy.md", "policy")
    chunks = PolicyChunkStrategy(ChunkConfig(min_tokens=4, target_tokens=40, max_tokens=80)).chunk(document)

    assert len(chunks) == 3
    assert any("第十二条" in chunk.text for chunk in chunks)
    assert any("第十三条" in chunk.text for chunk in chunks)
    assert any("第十四条" in chunk.text for chunk in chunks)
    assert all(not ("第十二条" in chunk.text and "第十三条" in chunk.text) for chunk in chunks)
    assert all("Article:" in str(chunk.metadata["semantic_context"]) for chunk in chunks)


def test_theory_does_not_merge_different_concepts() -> None:
    document = parse_fixture("theory/theory.md", "theory")
    chunks = TheoryChunkStrategy(ChunkConfig(min_tokens=4, target_tokens=40, max_tokens=80)).chunk(document)

    assert len(chunks) == 3
    assert sum("概念：压力" in chunk.text for chunk in chunks) == 1
    assert sum("概念：应对" in chunk.text for chunk in chunks) == 1
    assert sum("研究发现：支持网络" in chunk.text for chunk in chunks) == 1
    assert all("Concept/section:" in str(chunk.metadata["semantic_context"]) for chunk in chunks)


def test_intervention_preserves_manual_chunk_with_caution() -> None:
    document = parse_fixture("intervention/intervention.md", "practice_guidance")
    chunks = InterventionChunkStrategy(ChunkConfig(min_tokens=4, target_tokens=80, max_tokens=160)).chunk(document)

    assert len(chunks) == 1
    assert "建议" in chunks[0].text
    assert "注意事项" in chunks[0].text
    assert chunks[0].metadata["manual_chunk_id"] == "exam-support"
    assert "caution/limitation retained" in str(chunks[0].metadata["semantic_context"])


def test_long_policy_article_uses_secondary_split_and_retains_article_context(tmp_path: Path) -> None:
    path = tmp_path / "long.md"
    path.write_text(
        "---\n"
        "title: Long policy\norganization: Synthetic\nsource_type: government\n"
        "language: zh-CN\npopulation_scope: [test]\ncategory: policy\n"
        "rights_status: verified\nreview_status: approved\nhuman_curated: false\n---\n\n"
        "# 第一章 总则\n\n第十二条 " + "学生支持安排应当保留来源和审核边界。" * 30,
        encoding="utf-8",
    )
    config = PipelineConfig(chunk=ChunkConfig(min_tokens=4, target_tokens=20, max_tokens=30))
    source = SourceRecord.from_request(SourceRequest(path))
    document = MarkdownCuratedParser().parse(source, config)
    chunks = PolicyChunkStrategy(config.chunk).chunk(document)

    assert len(chunks) > 1
    assert all("Article: 第十二条" in str(chunk.metadata["semantic_context"]) for chunk in chunks)
    assert all(chunk.token_count <= config.chunk.max_tokens for chunk in chunks)
