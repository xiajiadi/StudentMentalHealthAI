"""Acceptance-only query probe that prints RAG chunk identities, not content."""

from __future__ import annotations

import json

from rag_engine.api.app import RagRuntime, RetrieveRequest
from rag_engine.cli import _synthetic_assessment


def main() -> int:
    runtime = RagRuntime()
    runtime.load()
    print(json.dumps({"ready": runtime.ready, "health": runtime.health()}, ensure_ascii=False))
    queries = [
        "请给出简短建议。",
        "我最近学习压力很大。",
        "如何安排睡眠和学习？",
        "我感到焦虑，想找人聊聊。",
        "怎样缓解考试前的紧张？",
        "请给我一个学习计划。",
    ]
    assessment = _synthetic_assessment()
    for query in queries:
        response = runtime.retrieve(
            RetrieveRequest(
                assessment=assessment,
                target_role="student",
                query=query,
                top_k=5,
            ),
            request_id="REQ_diag",
            trace_id="TRACE_diag",
        )
        chunks = response["data"]["chunks"]
        print(
            json.dumps(
                {"query": query, "chunks": [chunk["chunk_id"] for chunk in chunks]},
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
