# RAG Backend Integration Request

Status: OPEN — no formal RAG HTTP service was found in Round 1.

## Evidence

The inspected 05_rag-engine module exposes internal retrieval, chunk, and
trace-oriented domain services, but no formal HTTP application contract. The
Backend therefore uses RagClient plus ContractFakeRagClient, labelled
CONTRACT_FAKE. The adapter validates returned chunks against knowledge.v1 and
preserves chunk order, identifiers, citations, and retrieval provenance.

## Requested future surface

The RAG owner should publish a versioned internal retrieval endpoint that
accepts an assessment context, target role, query, top_k, and trace
correlation, then returns retrieval.v1-compatible metadata plus ordered
knowledge.v1 chunks and citations. The endpoint should make reranker status
explicit and must not silently force the accepted default-off reranker policy.

The surface must define timeouts, bounded top_k, invalid-query behavior,
abstention behavior, provenance fields, and a safe error contract. Backend will
not implement vector search, BM25, embeddings, reranking, or abstention
logic. No RAG files were modified by Backend Round 1.
