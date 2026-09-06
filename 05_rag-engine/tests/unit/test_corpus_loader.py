from __future__ import annotations

from pathlib import Path

from rag_engine.indexing import KnowledgeCorpusLoader


def test_loads_only_knowledge_pipeline_embedding_ready_rows():
    root = Path(__file__).parents[3]
    result = KnowledgeCorpusLoader().load(
        root / "04_knowledge-pipeline/data/published/round1/embedding_ready.jsonl",
        documents_path=root / "04_knowledge-pipeline/data/published/round1/knowledge_documents.jsonl",
        review_queue_path=root / "04_knowledge-pipeline/data/published/round1/review_queue.jsonl",
    )
    assert len(result.records) == 14
    assert not any(record.rights_status != "verified" for record in result.records)
    assert {record.layer for record in result.records} == {"policy", "theory", "intervention"}
    assert all(record.metadata["review_status"] == "approved" for record in result.records)
