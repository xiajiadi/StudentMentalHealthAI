from __future__ import annotations

import json
from pathlib import Path

import pytest

from rag_engine.config import RAGConfig
from rag_engine.domain import KnowledgeRecord


@pytest.fixture()
def rag_config(tmp_path: Path) -> RAGConfig:
    value = json.loads((Path(__file__).parents[1] / "config" / "rag.v1.json").read_text(encoding="utf-8"))
    value["environment"] = "test"
    value["retrieval_mode"] = "dense"
    value["reranker"]["provider"] = "noop"
    value["stores"] = {
        "chroma_collection": "test_dense",
        "chroma_path": str(tmp_path / "chroma"),
        "qdrant_collection": "test_hybrid",
        "qdrant_path": str(tmp_path / "qdrant"),
        "bm25_path": str(tmp_path / "bm25"),
    }
    return RAGConfig.from_mapping(value, base_dir=tmp_path)


@pytest.fixture()
def sample_records() -> list[KnowledgeRecord]:
    rows = [
        {
            "chunk_id": "CHUNK_test_policy_001",
            "document_id": "KB_test_policy",
            "text": "第十三条 教师应当先进行支持性沟通，并按照审核流程寻求帮助。",
            "context_text": "政策文件\n第十三条 教师应当先进行支持性沟通，并按照审核流程寻求帮助。",
            "metadata": {
                "layer": "policy",
                "title": "合成政策",
                "organization": "合成组织",
                "source_filename": "policy.md",
                "source_url": "https://example.invalid/policy",
                "section": "第一章",
                "role_scope": ["teacher", "parent"],
                "target_population": ["K12学生"],
                "risk_scope": ["normal", "attention"],
                "review_status": "approved",
                "rights_status": "verified",
                "content_hash": "sha256:testpolicy",
            },
        },
        {
            "chunk_id": "CHUNK_test_theory_001",
            "document_id": "KB_test_theory",
            "text": "压力是个体对要求与资源之间关系的主观体验。",
            "context_text": "理论文件\n压力是个体对要求与资源之间关系的主观体验。",
            "metadata": {
                "layer": "theory",
                "title": "合成理论",
                "organization": "合成研究组",
                "source_filename": "theory.md",
                "source_url": "https://example.invalid/theory",
                "section": "压力",
                "role_scope": ["student", "teacher", "parent"],
                "target_population": ["K12学生"],
                "risk_scope": ["normal", "attention"],
                "review_status": "approved",
                "rights_status": "verified",
                "content_hash": "sha256:testtheory",
            },
        },
        {
            "chunk_id": "CHUNK_test_intervention_001",
            "document_id": "KB_test_intervention",
            "text": "建议把任务拆成可在短时间内完成的小步骤。",
            "context_text": "支持建议\n建议把任务拆成可在短时间内完成的小步骤。",
            "metadata": {
                "layer": "intervention",
                "title": "合成支持建议",
                "organization": "合成项目",
                "source_filename": "intervention.md",
                "source_url": "https://example.invalid/intervention",
                "section": "步骤",
                "role_scope": ["student", "teacher"],
                "target_population": ["K12学生"],
                "risk_scope": ["normal", "attention"],
                "review_status": "approved",
                "rights_status": "verified",
                "content_hash": "sha256:testintervention",
            },
        },
        {
            "chunk_id": "CHUNK_test_rejected_001",
            "document_id": "KB_test_rejected",
            "text": "压力和支持性沟通的拒绝夹具。",
            "context_text": "拒绝夹具\n压力和支持性沟通的拒绝夹具。",
            "metadata": {
                "layer": "policy",
                "title": "拒绝夹具",
                "organization": "测试组织",
                "source_filename": "rejected.md",
                "source_url": "https://example.invalid/rejected",
                "section": "测试",
                "role_scope": ["teacher"],
                "target_population": ["K12学生"],
                "risk_scope": ["normal"],
                "review_status": "rejected",
                "rights_status": "verified",
                "content_hash": "sha256:testrejected",
            },
        },
    ]
    return [KnowledgeRecord.from_embedding_record(row) for row in rows]
